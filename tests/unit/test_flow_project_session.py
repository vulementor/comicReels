import time

import pytest

from agent.services import flow_project_session as fps
from agent.api import flow as flow_api

PROJECT_A = "11111111-2222-3333-4444-555555555555"
PROJECT_B = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class FakeClient:
    def __init__(self):
        self.created = []

    async def create_project(self, title):
        self.created.append(title)
        pid = PROJECT_A if len(self.created) == 1 else PROJECT_B
        return {"status": 200, "data": {"projectId": pid, "title": title}}


@pytest.mark.asyncio
async def test_session_project_reuses_inside_idle_window(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 7200.0)
    client = FakeClient()

    first = await fps.ensure_session_project(client, title="Session A")
    second = await fps.ensure_session_project(client, title="Ignored")

    assert first["project_id"] == PROJECT_A
    assert second["project_id"] == PROJECT_A
    assert len(client.created) == 1


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
    assert len(client.created) == 2


@pytest.mark.asyncio
async def test_session_project_force_new_rotates_even_when_active(tmp_path, monkeypatch):
    monkeypatch.setattr(fps, "_STATE_PATH", tmp_path / "lease.json")
    monkeypatch.setattr(fps, "FLOW_SESSION_PROJECT_IDLE_S", 7200.0)
    client = FakeClient()

    first = await fps.ensure_session_project(client, title="Session A")
    rotated = await fps.ensure_session_project(client, title="Session B", force_new=True)

    assert first["project_id"] == PROJECT_A
    assert rotated["project_id"] == PROJECT_B
    assert len(client.created) == 2


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

    result = await flow_api.rotate_session_project()
    assert result["project_id"] == PROJECT_B
    assert calls == [{"client": client, "title": None, "force_new": True}]
