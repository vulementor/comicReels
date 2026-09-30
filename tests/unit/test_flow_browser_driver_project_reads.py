"""FBR-2-code-2 authored coverage for project lifecycle and read transport.

Development-only coverage: these tests are intentionally authored but not executed
until the approved coding pass is complete.
"""
import hashlib
import json
from types import SimpleNamespace

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import BrowserCommandError, validate_command
from agent.services.flow_browser_driver import FlowBrowserDriver
from agent.services.flow_browser_session import FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = "11111111-2222-3333-4444-555555555555"
MEDIA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class Page:
    def __init__(self):
        self.url = "https://flow.google.com/"
        self.goto_calls = []

    def goto(self, url, *, wait_until, timeout):
        self.goto_calls.append((url, wait_until, timeout))
        self.url = url


class Provider:
    def __init__(self):
        self.lease = False
        self.page = Page()
        self.session = SimpleNamespace(page=self.page)

    def open(self):
        self.lease = True
        return self

    def health(self):
        return {
            "state": "open" if self.lease else "closed",
            "lease_held": self.lease,
        }

    def capture_health(self):
        return {
            "state": "open" if self.lease else "closed",
            "lease_held": self.lease,
            "authentication": "authenticated",
            "ready": self.lease,
            "semantic_node_count": 3,
            "observed_at": "2026-09-30T09:00:00+00:00",
            "error": None,
        }

    def close(self):
        self.lease = False


@pytest.fixture
def rig(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig(
        "unit-flow",
        profile,
        tmp_path / "binding.json",
        (stat.st_dev, stat.st_ino),
    )
    digest = hashlib.sha256(str(profile.resolve()).casefold().encode()).hexdigest()
    owner_key = f"browser:{config.profile_logical_name}:{digest}"
    state_path = tmp_path / "state" / "flow.json"
    provider = Provider()
    driver = FlowBrowserDriver(
        config,
        state_path,
        owner_key,
        session_factory=lambda _config, **_kwargs: provider,
    )
    driver.start()
    return driver, provider, state_path, owner_key


def _rpc_body(rpcid, payload):
    return json.dumps([["wrb.fr", rpcid, json.dumps(payload)]])


def test_open_project_navigates_exact_flow_project_and_persists_identity(rig):
    driver, provider, state_path, owner_key = rig
    result = driver.open_project(PROJECT)

    assert result == {
        "status": 200,
        "data": {"projectId": PROJECT},
        "effect": "completed",
    }
    assert provider.page.goto_calls == [
        (
            f"https://flow.google.com/project/{PROJECT}",
            "domcontentloaded",
            60_000,
        )
    ]
    assert BrowserStateStore(state_path, owner_key).load()["project_id"] == PROJECT
    driver.close()


def test_ensure_session_project_reuses_saved_project_without_create_rpc(rig, monkeypatch):
    driver, provider, _, _ = rig
    driver._store.set_project(PROJECT)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("saved project resume must not submit create RPC")

    monkeypatch.setattr(driver, "_evaluate_rpc", forbidden)
    result = driver.ensure_session_project("story", False)

    assert result == {
        "status": 200,
        "data": {"projectId": PROJECT, "reused": True},
        "effect": "completed",
    }
    assert provider.page.url == f"https://flow.google.com/project/{PROJECT}"
    driver.close()


def test_ensure_session_project_records_completed_create_receipt_before_pointer(rig, monkeypatch):
    driver, provider, state_path, owner_key = rig

    def create_rpc(_page, command, _timeout):
        assert command.rpcid == fb.RPC_CREATE_PROJECT
        return {
            "status": 200,
            "body_complete": True,
            "effect": "completed",
            "data": _rpc_body(
                fb.RPC_CREATE_PROJECT,
                [PROJECT, [command.title]],
            ),
        }

    monkeypatch.setattr(driver, "_evaluate_rpc", create_rpc)
    result = driver.ensure_session_project("Episode board", False)

    assert result == {
        "status": 200,
        "data": {
            "projectId": PROJECT,
            "title": "Episode board",
            "reused": False,
        },
        "effect": "completed",
    }
    saved = BrowserStateStore(state_path, owner_key).load()
    assert saved["project_id"] == PROJECT
    create_entries = [
        entry for entry in saved["intents"].values() if entry["kind"] == "create"
    ]
    assert len(create_entries) == 1
    assert create_entries[0]["state"] == "COMPLETED"
    assert create_entries[0]["receipt"] == {
        "project_id": PROJECT,
        "title": "Episode board",
    }
    assert provider.page.url == f"https://flow.google.com/project/{PROJECT}"
    driver.close()


def test_unknown_create_blocks_replay_before_any_browser_rpc(rig, monkeypatch):
    driver, _, _, _ = rig
    driver._store.begin("create:existing", "create", {"title": "Episode board"})
    driver._store.mark_unknown("create:existing")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unknown create must not be replayed")

    monkeypatch.setattr(driver, "_evaluate_rpc", forbidden)
    with pytest.raises(BrowserCommandError, match="^RECONCILIATION_REQUIRED$"):
        driver.ensure_session_project("Episode board", False)
    driver.close()


def test_project_media_read_uses_bound_project_and_read_only_rpc(rig, monkeypatch):
    driver, provider, _, _ = rig
    command = validate_command(
        "batch_rpc",
        {
            "rpcid": fb.RPC_PROJECT_MEDIA,
            "freq": fb.project_media_request(PROJECT),
            "projectId": PROJECT,
        },
    )

    def read_rpc(_page, seen, _timeout):
        assert seen is command
        return {
            "status": 200,
            "body_complete": True,
            "effect": "completed",
            "data": _rpc_body(fb.RPC_PROJECT_MEDIA, [["listing"]]),
        }

    monkeypatch.setattr(driver, "_evaluate_rpc", read_rpc)
    result = driver.execute(command, 30)

    assert result["status"] == 200
    assert result["effect"] == "completed"
    assert provider.page.url == f"https://flow.google.com/project/{PROJECT}"
    driver.close()


def test_media_read_requires_saved_project_context_and_never_creates_one(rig, monkeypatch):
    driver, provider, state_path, _ = rig
    command = validate_command(
        "batch_rpc",
        {
            "rpcid": fb.RPC_MEDIA,
            "freq": fb.media_request(MEDIA),
        },
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("media read without a saved project must not submit RPC")

    monkeypatch.setattr(driver, "_evaluate_rpc", forbidden)
    result = driver.execute(command, 30)

    assert result == {
        "status": 409,
        "error": "PROJECT_REQUIRED",
        "effect": "not_submitted",
    }
    assert provider.page.goto_calls == []
    assert not state_path.exists()
    driver.close()
