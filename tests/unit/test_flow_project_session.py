import time

import pytest

from agent.services import flow_project_session as fps
from agent.services.flow_client import FlowClient
from agent.api import flow as flow_api

PROJECT_A = "11111111-2222-3333-4444-555555555555"
PROJECT_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class FakeClient:
    def __init__(self):
        self.calls = []
        self.project_id = None

    async def ensure_session_project(self, *, title=None, force_new=False):
        self.calls.append({"title": title, "force_new": force_new})
        created = self.project_id is None or force_new
        if created:
            self.project_id = PROJECT_A if self.project_id is None else PROJECT_B
        return {
            "status": 200,
            "data": {
                "projectId": self.project_id,
                "title": title,
                "reused": not created,
            },
            "effect": "completed",
        }


@pytest.mark.asyncio
async def test_session_project_reuses_inside_idle_window(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 7200.0)
    client = FakeClient()

    first = await fps.ensure_session_project(client, title="Session A")
    second = await fps.ensure_session_project(client, title="Ignored")

    assert first["project_id"] == PROJECT_A
    assert second["project_id"] == PROJECT_A
    assert client.calls == [
        {"title": "Session A", "force_new": False},
        {"title": "Ignored", "force_new": False},
    ]


@pytest.mark.asyncio
async def test_session_project_rotates_after_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 10.0)
    client = FakeClient()

    await fps.ensure_session_project(client, title="Session A")
    state = fps._read_state()
    state["last_activity_at"] = time.time() - 11
    fps._write_state(state)

    rotated = await fps.ensure_session_project(client, title="Session B")
    assert rotated["project_id"] == PROJECT_B
    assert client.calls[-1] == {"title": "Session B", "force_new": True}


@pytest.mark.asyncio
async def test_session_project_force_new_rotates_even_when_active(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 7200.0)
    client = FakeClient()

    first = await fps.ensure_session_project(client, title="Session A")
    rotated = await fps.ensure_session_project(client, title="Session B", force_new=True)

    assert first["project_id"] == PROJECT_A
    assert rotated["project_id"] == PROJECT_B
    assert client.calls[-1] == {"title": "Session B", "force_new": True}


@pytest.mark.asyncio
async def test_rotate_session_project_endpoint_uses_force_new(monkeypatch):
    calls = []

    class ConnectedClient:
        connected = True

    async def fake_ensure(client, *, title=None, force_new=False):
        calls.append({"client": client, "title": title, "force_new": force_new})
        return {"project_id": PROJECT_B, "active": True}

    client = ConnectedClient()
    monkeypatch.setattr(flow_api, "get_flow_client", lambda: client)
    monkeypatch.setattr(flow_api, "ensure_session_project", fake_ensure)

    async def ready(_client):
        return {"backend_ready": True}

    monkeypatch.setattr(flow_api, "_require_browser_session", ready)

    result = await flow_api.rotate_session_project()
    assert result["project_id"] == PROJECT_B
    assert calls == [{"client": client, "title": None, "force_new": True}]


@pytest.mark.asyncio
async def test_flow_client_session_project_delegates_to_browser_backend():
    calls = []

    class Backend:
        async def ensure_session_project(self, *, title=None, force_new=False):
            calls.append({"title": title, "force_new": force_new})
            return {
                "status": 200,
                "data": {"projectId": PROJECT_A, "title": title, "reused": False},
                "effect": "completed",
            }

    client = FlowClient(backend=Backend())
    result = await client.ensure_session_project(title="Session A", force_new=True)

    assert result["data"]["projectId"] == PROJECT_A
    assert calls == [{"title": "Session A", "force_new": True}]


@pytest.mark.asyncio
async def test_local_session_state_is_projection_not_remote_create_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 7200.0)
    client = FakeClient()

    fps._write_state({
        "project_id": PROJECT_B,
        "title": "stale local projection",
        "created_at": time.time(),
        "last_activity_at": time.time(),
    })

    resolved = await fps.ensure_session_project(client, title="Current")

    # Browser backend/journal decides the actual project; local projection follows it.
    assert resolved["project_id"] == PROJECT_A
    assert fps.current_session_project()["project_id"] == PROJECT_A
    assert client.calls == [{"title": "Current", "force_new": False}]
