"""Browser-only lifecycle regression requirements.

Authored during the development-first phase; execution is deferred until the
full browser-only source pass reaches validation.
"""
import ast
from pathlib import Path


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
