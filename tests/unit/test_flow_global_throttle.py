import asyncio

import pytest

from agent.services import flow_batch as fb
from agent.services import flow_client as fc
from agent.api import flow as flow_api


class ThrottleBackend:
    """Pure unit-test backend; never opens a real browser/profile."""

    kind = "browser"
    ready = True
    paid_dispatch_enabled = False
    session_owner_key = "unit-throttle"

    async def execute(self, method, params, timeout=300):
        raise AssertionError("throttle tests replace FlowClient._send")

    async def start(self):
        pass

    async def close(self):
        pass

    async def check_readiness(self):
        return {"ready": True}

    async def open_project(self, project_id):
        return {"status": 200, "data": {"projectId": project_id}}

    async def ensure_session_project(self, *, title=None, force_new=False):
        return {"status": 200}

    async def submit_paid_image(self, *args, **kwargs):
        raise AssertionError("paid image path is outside throttle unit scope")

    async def submit_paid_video(self, *args, **kwargs):
        raise AssertionError("paid video path is outside throttle unit scope")

    async def bind_operation(self, operation_id, project_id):
        return {"status": 200, "data": {"operationId": operation_id, "projectId": project_id}}

    async def operation_project(self, operation_id):
        return {"status": 409, "error": "OPERATION_BINDING_REQUIRED"}


@pytest.fixture
def throttle_client():
    return fc.FlowClient(backend=ThrottleBackend())


@pytest.mark.asyncio
async def test_generation_rpc_is_globally_serialized(monkeypatch, throttle_client):
    monkeypatch.setattr(fc, "FLOW_GENERATION_MAX_CONCURRENT", 1)
    monkeypatch.setattr(fc, "FLOW_GENERATION_MIN_INTERVAL_S", 0.0)
    client = throttle_client
    active = 0
    max_active = 0

    async def fake_send(method, params, timeout=300):
        nonlocal active, max_active
        assert method == "batch_rpc"
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"status": 200, "data": "ok"}

    monkeypatch.setattr(client, "_send", fake_send)
    await asyncio.gather(
        client.batch_rpc("a", "x", captcha_action=fb.CAPTCHA_VIDEO),
        client.batch_rpc("b", "y", captcha_action=fb.CAPTCHA_IMAGE),
    )
    assert max_active == 1


@pytest.mark.asyncio
async def test_unusual_activity_opens_local_circuit_breaker(monkeypatch, throttle_client):
    monkeypatch.setattr(fc, "FLOW_GENERATION_MAX_CONCURRENT", 1)
    monkeypatch.setattr(fc, "FLOW_GENERATION_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(fc, "FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S", 120.0)
    client = throttle_client
    calls = 0

    async def fake_send(method, params, timeout=300):
        nonlocal calls
        calls += 1
        return {
            "status": 200,
            "data": "PUBLIC_ERROR_UNUSUAL_ACTIVITY reCAPTCHA evaluation failed",
        }

    monkeypatch.setattr(client, "_send", fake_send)
    first = await client.batch_rpc("a", "x", captcha_action=fb.CAPTCHA_VIDEO)
    second = await client.batch_rpc("b", "y", captcha_action=fb.CAPTCHA_VIDEO)

    assert first["status"] == 200
    assert second["status"] == 429
    assert "local cooldown active" in second["error"]
    assert calls == 1
    assert client.generation_guard_status["cooldown_active"] is True
    assert client.generation_guard_status["last_unusual_activity_rpc"] == "a"


@pytest.mark.asyncio
async def test_non_generation_rpc_bypasses_generation_guard(monkeypatch, throttle_client):
    client = throttle_client
    client._generation_unusual_until = asyncio.get_running_loop().time() + 60
    calls = 0

    async def fake_send(method, params, timeout=300):
        nonlocal calls
        calls += 1
        return {"status": 200, "data": "metadata"}

    monkeypatch.setattr(client, "_send", fake_send)
    result = await client.batch_rpc("meta", "x")
    assert result["status"] == 200
    assert calls == 1


@pytest.mark.asyncio
async def test_flow_status_exposes_browser_readiness_reconciliation_and_paid_lock(monkeypatch):
    class FakeClient:
        generation_guard_status = {
            "cooldown_active": False,
            "cooldown_remaining_s": 0.0,
            "last_unusual_activity_at": None,
            "last_unusual_activity_rpc": None,
        }

    async def browser_status():
        return {
            "backend_kind": "browser",
            "backend_ready": True,
            "session_ready": True,
            "authentication": "authenticated",
            "lease_held": True,
            "reconciliation_required": False,
            "pending_intents": 0,
            "paid_dispatch_enabled": False,
            "error": None,
            "preflight": {
                "ready": True,
                "transport": "browser",
                "session_required": True,
            },
        }

    monkeypatch.setattr(flow_api, "get_flow_client", lambda: FakeClient())
    monkeypatch.setattr(flow_api, "read_backend_status", browser_status)
    monkeypatch.setattr(flow_api, "current_session_project", lambda: {"project_id": None})

    status = await flow_api.flow_status()
    assert status["transport"] == "browser"
    assert status["browser_session_ready"] is True
    assert status["authentication"] == "authenticated"
    assert status["lease_held"] is True
    assert status["reconciliation_required"] is False
    assert status["paid_dispatch_enabled"] is False
    assert "extension_session" not in status


def test_throttle_fixture_never_constructs_default_browser_backend(monkeypatch, throttle_client):
    def fail():
        raise AssertionError("real browser backend constructor must not run in throttle unit tests")

    monkeypatch.setattr(fc, "FlowClient", fail)
    assert throttle_client.backend.kind == "browser"
    assert throttle_client.backend.session_owner_key == "unit-throttle"
