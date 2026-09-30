"""FBR-2-code-2 authored coverage for project/session reuse and non-paid reads.

Development policy intentionally defers execution. These tests are source coverage
only until the separate validation pass runs them against the completed coding plan.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import BrowserCommandError, validate_command
from agent.services.flow_browser_session import FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = "11111111-2222-3333-4444-555555555555"
MEDIA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Page:
    def __init__(self):
        self.url = "https://flow.google.com/"
        self.gotos = []
        self.evaluations = []
        self.evaluate_result = {
            "status": 200, "data": "READ_BODY", "body_complete": True,
            "effect": "completed",
        }
        self.before_evaluate = None

    def goto(self, url, *, wait_until, timeout):
        self.gotos.append((url, wait_until, timeout))
        self.url = url
        return None

    def evaluate(self, script, args):
        self.evaluations.append((script, args))
        if self.before_evaluate:
            self.before_evaluate(args)
        return dict(self.evaluate_result)


class Provider:
    def __init__(self, page):
        self.page = page
        self.session = SimpleNamespace(page=page)
        self.lease = False

    def open(self):
        self.lease = True
        return self

    def health(self):
        return {"state": "open" if self.lease else "closed",
                "lease_held": self.lease, "ready": False}

    def capture_health(self):
        return {
            "state": "open" if self.lease else "closed",
            "lease_held": self.lease,
            "authentication": "authenticated" if self.lease else "unknown",
            "ready": self.lease,
            "semantic_node_count": 5 if self.lease else 0,
            "observed_at": "2026-09-30T07:00:00+00:00",
            "error": None,
        }

    def close(self):
        self.lease = False


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from agent.services import flow_browser_driver as implementation
    profile = tmp_path / "profile"
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig(
        "unit-flow", profile, tmp_path / "binding.json", (stat.st_dev, stat.st_ino)
    )
    digest = hashlib.sha256(str(profile.resolve()).casefold().encode()).hexdigest()
    owner = f"browser:{config.profile_logical_name}:{digest}"
    state_path = tmp_path / "state" / "flow.json"
    page = Page()
    provider = Provider(page)

    def factory(bound_config, **kwargs):
        assert bound_config is config
        return provider

    monkeypatch.setattr(implementation, "FlowBrowserSessionProvider", factory)
    driver = implementation.FlowBrowserDriver(config, state_path, owner)
    driver.start()
    return driver, provider, page, state_path, owner, implementation


def test_saved_session_project_is_reopened_without_create_effect(rig):
    driver, _, page, state_path, owner, _ = rig
    BrowserStateStore(state_path, owner).set_project(PROJECT)

    result = driver.ensure_session_project(title="ignored", force_new=False)

    assert result == {
        "status": 200, "data": {"projectId": PROJECT, "reused": True},
        "effect": "completed",
    }
    assert page.gotos == [(f"https://flow.google.com/project/{PROJECT}",
                           "domcontentloaded", 60000)]
    assert page.evaluations == []
    assert BrowserStateStore(state_path, owner).load()["project_id"] == PROJECT


def test_project_create_persists_submitting_before_browser_effect_then_binds_receipt(
        rig, monkeypatch):
    driver, _, page, state_path, owner, implementation = rig
    state = BrowserStateStore(state_path, owner)

    def before(args):
        snapshot = state.load()
        create = [entry for entry in snapshot["intents"].values()
                  if entry["kind"] == "create"]
        assert len(create) == 1 and create[0]["state"] == "SUBMITTING"
        assert snapshot["project_id"] is None
        assert args["rpcid"] == fb.RPC_CREATE_PROJECT
        assert args["projectId"] is None

    page.before_evaluate = before
    page.evaluate_result["data"] = "CREATED_BODY"
    monkeypatch.setattr(implementation.fb, "first_payload",
                        lambda body, rpcid: [PROJECT, ["Story A"]])
    monkeypatch.setattr(implementation.fb, "read_created_project",
                        lambda payload: (PROJECT, "Story A"))

    result = driver.ensure_session_project(title="Story A", force_new=False)

    assert result == {
        "status": 200,
        "data": {"projectId": PROJECT, "title": "Story A", "reused": False},
        "effect": "completed",
    }
    saved = state.load()
    assert saved["project_id"] == PROJECT
    create = [entry for entry in saved["intents"].values() if entry["kind"] == "create"]
    assert len(create) == 1 and create[0]["state"] == "COMPLETED"
    assert create[0]["receipt"] == {"project_id": PROJECT, "title": "Story A"}
    assert page.url == f"https://flow.google.com/project/{PROJECT}"


def test_completed_create_receipt_recovers_project_binding_without_resubmit(rig):
    driver, _, page, state_path, owner, _ = rig
    state = BrowserStateStore(state_path, owner)
    key = "create:story-a:0"
    state.begin(key, "create", {"title": "Story A"})
    state.complete(key, {"project_id": PROJECT, "title": "Story A"})
    assert state.load()["project_id"] is None

    result = driver.ensure_session_project(title="Story A", force_new=False)

    assert result["data"] == {"projectId": PROJECT, "reused": True}
    assert state.load()["project_id"] == PROJECT
    assert page.evaluations == []


def test_unknown_create_outcome_is_never_replayed(rig, monkeypatch):
    driver, _, page, state_path, owner, implementation = rig
    state = BrowserStateStore(state_path, owner)
    page.evaluate_result = {
        "status": 502, "error": "BODY_INCOMPLETE", "effect": "unknown"
    }

    with pytest.raises(BrowserCommandError, match="^RECONCILIATION_REQUIRED$"):
        driver.ensure_session_project(title="Story A", force_new=False)

    snapshot = state.load()
    create = [entry for entry in snapshot["intents"].values()
              if entry["kind"] == "create"]
    assert len(create) == 1 and create[0]["state"] == "UNKNOWN"
    calls = len(page.evaluations)
    with pytest.raises(BrowserCommandError, match="^RECONCILIATION_REQUIRED$"):
        driver.ensure_session_project(title="Story A", force_new=False)
    assert len(page.evaluations) == calls


def test_project_media_read_opens_exact_project_and_returns_raw_transport_body(rig):
    driver, _, page, _, _, _ = rig
    command = validate_command("batch_rpc", {
        "rpcid": fb.RPC_PROJECT_MEDIA,
        "freq": fb.project_media_request(PROJECT),
        "projectId": PROJECT,
    })

    result = driver.execute(command, timeout=25)

    assert result == {
        "status": 200, "data": "READ_BODY", "body_complete": True,
        "effect": "completed",
    }
    assert page.gotos[-1][0] == f"https://flow.google.com/project/{PROJECT}"
    script, args = page.evaluations[-1]
    assert "flow_browser_rpc.js" not in script
    assert args == {
        "rpcid": fb.RPC_PROJECT_MEDIA, "freq": command.freq,
        "projectId": PROJECT, "match": None, "timeoutMs": 25000,
    }


def test_media_read_uses_saved_project_and_unbound_operation_raw_create_fail_closed(rig):
    driver, _, page, state_path, owner, _ = rig
    BrowserStateStore(state_path, owner).set_project(PROJECT)
    media = validate_command("batch_rpc", {
        "rpcid": fb.RPC_MEDIA, "freq": fb.media_request(MEDIA),
    })
    assert driver.execute(media, 10)["effect"] == "completed"
    assert page.gotos[-1][0] == f"https://flow.google.com/project/{PROJECT}"

    operation = validate_command("batch_rpc", {
        "rpcid": fb.RPC_OPERATION, "freq": fb.operation_request(MEDIA),
    })
    assert driver.execute(operation, 10) == {
        "status": 409, "error": "OPERATION_BINDING_REQUIRED",
        "effect": "not_submitted",
    }

    create = validate_command("batch_rpc", {
        "rpcid": fb.RPC_CREATE_PROJECT, "freq": fb.create_project_request("Other"),
    })
    assert driver.execute(create, 10) == {
        "status": 501, "error": "BROWSER_CAPABILITY_NOT_IMPLEMENTED",
        "effect": "not_submitted",
    }


def test_final_non_paid_slice_advertises_complete_non_paid_capabilities(rig):
    driver, _, _, _, _, _ = rig
    report = driver.health()
    assert report["ready"] is True and report["session_ready"] is True
    assert report["readiness_scope"] == "non_paid_parity"
    assert report["operations_implemented"] is True
    assert report["capabilities"] == {
        "project_open_resume": True,
        "project_create_session": True,
        "project_media_read": True,
        "media_read": True,
        "operation_reconcile": True,
        "upload": True,
        "paid_dispatch": False,
    }
    assert report["paid_dispatch_enabled"] is False
