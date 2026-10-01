"""Regression requirement: worker runs for both selected Flow backends.

Authored during development-first phase; execution is deferred until validation.
"""
import ast
from pathlib import Path


def _lifespan_source():
    source = Path("agent/main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan":
            return ast.get_source_segment(source, node)
    raise AssertionError("lifespan not found")


def test_worker_start_is_not_conditioned_on_extension_backend():
    source = _lifespan_source()

    # Extension-only infrastructure may remain conditional, but the queue worker
    # must be started for browser and extension backends alike.
    assert "controller = get_worker_controller()" in source
    assert "asyncio.create_task(controller.start())" in source

    extension_block = source.split('if client.backend_kind == "extension":', 1)[1]
    extension_suite = extension_block.split("\n\n        yield", 1)[0]
    assert "run_ws_server()" in extension_suite
    assert "controller.start()" not in extension_suite


def test_extension_websocket_server_remains_extension_only():
    source = _lifespan_source()
    before_condition, extension_block = source.split(
        'if client.backend_kind == "extension":', 1
    )
    assert "run_ws_server()" not in before_condition
    extension_suite = extension_block.split("\n\n        yield", 1)[0]
    assert "run_ws_server()" in extension_suite
