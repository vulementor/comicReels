"""Selected backend boundaries and non-paid application lifecycle."""
import asyncio
import sys
from types import SimpleNamespace

import pytest

from agent.services.flow_client import FlowClient


class FakeBackend:
    def __init__(self, kind="browser", ready=False, events=None):
        self.kind = kind
        self.ready = ready
        self.paid_dispatch_enabled = kind == "extension"
        self.session_owner_key = f"{kind}:test-owner"
        self.events = events if events is not None else []

    async def start(self):
        self.events.append("backend-start")
        self.ready = True

    async def close(self):
        self.events.append("backend-close")
        self.ready = False

    async def check_readiness(self):
        return {"ready": self.ready, "backend_kind": self.kind}

    async def execute(self, method, params, timeout=300):
        self.events.append((method, params, timeout))
        return {"status": 200, "data": "selected-backend"}

    async def open_project(self, project_id):
        return {"status": 200, "data": {"projectId": project_id}}


@pytest.mark.parametrize("kind", ["browser", "extension"])
async def test_injected_backend_owns_dispatch_and_lifecycle(kind):
    backend = FakeBackend(kind)
    client = FlowClient(backend=backend)
    assert client.backend is backend
    assert not client.connected
    await client.start_backend()
    assert client.connected
    assert client.backend_kind == kind
    assert client.session_owner_key == f"{kind}:test-owner"
    assert client.paid_dispatch_enabled is (kind == "extension")
    assert await client._send("batchExecute", {"rpcid": "read"}, 7) == {
        "status": 200, "data": "selected-backend",
    }
    assert backend.events[-1] == ("batchExecute", {"rpcid": "read"}, 7)
    assert (await client.open_project("project"))["data"]["projectId"] == "project"
    assert (await client.backend_readiness())["ready"] is True
    await client.close_backend()
    assert not client.connected


async def test_extension_events_cannot_promote_browser_readiness():
    client = FlowClient(backend=FakeBackend())
    socket = object()
    client.set_extension(socket)
    await client.handle_message({"type": "extension_ready"}, socket)
    assert client.extension_connected
    assert client.ws_stats["connected"]
    assert not client.connected
    client.clear_extension(socket)
    client.backend.ready = True
    assert client.connected
    assert not client.extension_connected
    assert not client.ws_stats["connected"]


async def test_default_extension_keeps_error_and_ws_response_shapes():
    client = FlowClient()
    assert client.backend_kind == "extension"
    assert client.paid_dispatch_enabled
    assert await client._send("read", {}) == {"error": "Extension not connected"}
    assert (await client.backend_readiness())["ready"] is False
    assert (await client.open_project("project"))["status"] == 501

    class Socket:
        async def send(self, raw):
            import json
            request = json.loads(raw)
            await client.handle_message({"id": request["id"], "status": 200, "data": "ok"}, self)

    client.set_extension(Socket())
    assert client.connected
    assert (await client._send("read", {}))["data"] == "ok"


def test_environment_selector_defaults_and_rejects_invalid(monkeypatch):
    from agent.services import flow_client
    monkeypatch.setattr(flow_client, "_client", None)
    monkeypatch.delenv("COMICREELS_FLOW_BACKEND", raising=False)
    assert flow_client.get_flow_client().backend_kind == "extension"
    monkeypatch.setattr(flow_client, "_client", None)
    monkeypatch.setenv("COMICREELS_FLOW_BACKEND", "typo")
    with pytest.raises(ValueError, match="COMICREELS_FLOW_BACKEND"):
        flow_client.get_flow_client()


def test_browser_selector_constructs_explicit_backend(monkeypatch):
    from agent.services import flow_client
    monkeypatch.setattr(flow_client, "_client", None)
    monkeypatch.setenv("COMICREELS_FLOW_BACKEND", "browser")
    monkeypatch.setitem(sys.modules, "agent.services.flow_browser_backend", SimpleNamespace(
        BrowserFlowBackend=FakeBackend,
    ))
    assert flow_client.get_flow_client().backend_kind == "browser"


@pytest.fixture
def lifecycle(monkeypatch):
    from agent import main
    from agent.db import crud
    events = []

    async def init_db():
        events.append("db-start")

    async def close_db():
        events.append("db-close")

    async def materials():
        return []

    async def ws_server():
        events.append("ws-start")
        try:
            await asyncio.Future()
        finally:
            events.append("ws-stop")

    class Controller:
        async def start(self):
            events.append("worker-start")
            try:
                await asyncio.Future()
            finally:
                events.append("worker-stop")

        def request_shutdown(self):
            events.append("worker-shutdown")

        async def drain(self):
            events.append("worker-drain")

    monkeypatch.setattr(main, "init_db", init_db)
    monkeypatch.setattr(main, "close_db", close_db)
    monkeypatch.setattr(crud, "list_materials", materials)
    monkeypatch.setattr(main, "init_sdk", lambda client: None)
    monkeypatch.setattr(main, "get_worker_controller", Controller)
    monkeypatch.setattr(main, "run_ws_server", ws_server)
    return main, events


@pytest.mark.parametrize("fail_body", [False, True])
async def test_browser_lifespan_never_starts_ws_or_worker_and_closes(lifecycle, monkeypatch, fail_body):
    main, events = lifecycle
    client = FlowClient(backend=FakeBackend(events=events))
    monkeypatch.setattr(main, "get_flow_client", lambda: client)
    try:
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
            assert client.connected
            assert "ws-start" not in events
            assert "worker-start" not in events
            if fail_body:
                raise RuntimeError("body-error")
    except RuntimeError as exc:
        assert str(exc) == "body-error"
    assert events == ["db-start", "backend-start", "backend-close", "db-close"]


async def test_extension_lifespan_drains_tasks_before_backend_close(lifecycle, monkeypatch):
    main, events = lifecycle
    client = FlowClient(backend=FakeBackend("extension", events=events))
    monkeypatch.setattr(main, "get_flow_client", lambda: client)
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert "ws-start" in events and "worker-start" in events
    assert events.index("worker-drain") < events.index("backend-close")
    assert events.index("ws-stop") < events.index("backend-close")
    assert events.index("worker-stop") < events.index("backend-close")
    assert events[-1] == "db-close"


async def test_failed_backend_start_still_closes_resources(lifecycle, monkeypatch):
    main, events = lifecycle
    backend = FakeBackend(events=events)

    async def fail_start():
        raise RuntimeError("start-failed")

    backend.start = fail_start
    monkeypatch.setattr(main, "get_flow_client", lambda: FlowClient(backend=backend))
    with pytest.raises(RuntimeError, match="start-failed"):
        async with main.lifespan(main.app):
            pytest.fail("failed startup must not yield")
    assert events == ["db-start", "backend-close", "db-close"]


async def test_worker_direct_start_cannot_reset_processing_without_paid_capability(monkeypatch):
    from agent.worker import processor
    client = FlowClient(backend=FakeBackend())
    monkeypatch.setattr(processor, "get_flow_client", lambda: client)

    async def forbidden():
        pytest.fail("non-paid worker must not reset PROCESSING or enter its loop")

    controller = processor.WorkerController()
    monkeypatch.setattr(controller, "_cleanup_stale_processing", forbidden)
    monkeypatch.setattr(controller, "_run_loop", forbidden)
    await controller.start()


async def test_health_and_status_report_selected_backend_separately(monkeypatch):
    from agent import main
    from agent.api import flow
    client = FlowClient(backend=FakeBackend(ready=True))
    monkeypatch.setattr(main, "get_flow_client", lambda: client)
    monkeypatch.setattr(flow, "get_flow_client", lambda: client)
    for result in (await main.health(), await flow.extension_status()):
        assert result["backend_kind"] == "browser"
        assert result["backend_ready"] is True
        assert result["extension_connected"] is False
        assert result["paid_dispatch_enabled"] is False
    assert (await flow.extension_status())["transport"] == "batch"
