"""Authored browser-only FastAPI lifespan contract; not executed during coding."""
from pathlib import Path


def test_main_has_no_flow_extension_transport_surface():
    source = Path("agent/main.py").read_text(encoding="utf-8")
    forbidden = (
        "set_extension(",
        "clear_extension(",
        "handle_message(data, websocket)",
        "websockets.serve(",
        "/api/ext/callback",
        "callback_secret",
        "Extension WS server",
    )
    for marker in forbidden:
        assert marker not in source


def test_browser_backend_then_worker_then_yield_order_is_explicit():
    source = Path("agent/main.py").read_text(encoding="utf-8")
    start = source.index("await client.start_backend()")
    worker = source.index("asyncio.create_task(controller.start())")
    yielded = source.index("        yield", worker)
    assert start < worker < yielded


def test_shutdown_drains_worker_before_closing_browser_backend():
    source = Path("agent/main.py").read_text(encoding="utf-8")
    request_shutdown = source.index("controller.request_shutdown()")
    drain = source.index("await controller.drain()", request_shutdown)
    close_backend = source.index("await client.close_backend()", drain)
    close_db = source.index("await close_db()", close_backend)
    assert request_shutdown < drain < close_backend < close_db
