"""Browser-only lifecycle regression requirements.

Authored during the development-first phase; execution is deferred until the
full browser-only source pass reaches validation.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.worker import processor
from agent.worker.processor import WorkerController


def _source():
    return Path("agent/main.py").read_text(encoding="utf-8")


def _async_function_source(name: str) -> str:
    source = _source()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found")


def test_worker_always_starts_after_browser_backend():
    source = _async_function_source("lifespan")
    assert "await client.start_backend()" in source
    assert "controller = get_worker_controller()" in source
    assert "asyncio.create_task(controller.start())" in source
    assert "client.backend_kind" not in source
    assert "run_ws_server" not in source


def test_worker_shutdown_remains_graceful():
    source = _async_function_source("lifespan")
    assert "controller.request_shutdown()" in source
    assert "await controller.drain()" in source
    assert "await client.close_backend()" in source
    assert "await close_db()" in source


def test_flow_extension_websocket_lifecycle_is_absent():
    source = _source()
    assert "import websockets" not in source
    assert "async def ws_handler" not in source
    assert "async def run_ws_server" not in source
    assert "WS_HOST" not in source
    assert "WS_PORT" not in source


def test_flow_extension_callback_endpoint_is_absent():
    source = _source()
    assert '"/api/ext/callback"' not in source
    assert "_CALLBACK_SECRET" not in source
    assert "async def ext_callback" not in source


def test_dashboard_websocket_remains_independent():
    source = _source()
    assert '@app.websocket("/ws/dashboard")' in source
    assert "async def dashboard_ws" in source


@pytest.mark.asyncio
async def test_worker_runs_cleanup_and_loop_when_paid_dispatch_is_locked(monkeypatch):
    controller = WorkerController()
    calls = []

    async def cleanup():
        calls.append("cleanup")

    async def run_loop():
        calls.append("loop")

    monkeypatch.setattr(
        processor,
        "get_flow_client",
        lambda: SimpleNamespace(paid_dispatch_enabled=False),
    )
    monkeypatch.setattr(controller, "_cleanup_stale_processing", cleanup)
    monkeypatch.setattr(controller, "_run_loop", run_loop)

    await controller.start()

    assert calls == ["cleanup", "loop"]


def test_worker_start_does_not_return_when_paid_dispatch_is_locked():
    source = ast.get_source_segment(
        Path("agent/worker/processor.py").read_text(encoding="utf-8"),
        next(
            node for node in ast.walk(
                ast.parse(Path("agent/worker/processor.py").read_text(encoding="utf-8"))
            )
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "start"
        ),
    )
    assert "Worker disabled" not in source
    assert "paid_dispatch_enabled" in source
    assert "await self._cleanup_stale_processing()" in source
    assert "await self._run_loop()" in source
    assert source.index("await self._cleanup_stale_processing()") < source.index("await self._run_loop()")


def test_worker_lifecycle_cannot_manufacture_paid_authorization():
    source = Path("agent/worker/processor.py").read_text(encoding="utf-8")
    assert "build_paid_validation_session" not in source
    assert "paid_dispatch_enabled=True" not in source
    assert "paid_authorization=" not in source


def test_worker_has_no_retired_extension_transient_retry_branch():
    source = Path("agent/worker/processor.py").read_text(encoding="utf-8")
    assert "extension reconnected" not in source.lower()
    assert "extension disconnected" not in source.lower()
    assert "extension not connected" not in source.lower()
