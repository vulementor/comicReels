"""Task 6c authored root health/dashboard snapshot requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import inspect
import json

from agent import main


def test_root_health_source_is_browser_only_and_uses_fresh_backend_status():
    source = inspect.getsource(main.health)

    assert 'read_backend_status()' in source
    assert '"transport": "browser"' in source
    assert '"browser_session_ready"' in source
    assert '"reconciliation_required"' in source
    assert '"paid_dispatch_enabled"' in source

    assert 'extension_connected' not in source
    assert 'ws_stats' not in source
    assert 'client.connected' not in source


def test_dashboard_snapshot_source_uses_fresh_browser_status():
    source = inspect.getsource(main.dashboard_ws)

    assert 'read_backend_status()' in source
    assert '"transport": "browser"' in source
    assert '"browser_session_ready"' in source
    assert '"reconciliation_required"' in source
    assert '"paid_dispatch_enabled"' in source

    assert 'extension_connected' not in source
    assert 'client.connected' not in source
    assert 'ws_stats' not in source


def test_dashboard_websocket_remains_an_independent_event_channel():
    source = inspect.getsource(main.dashboard_ws)
    module = inspect.getsource(main)

    assert '@app.websocket("/ws/dashboard")' in module
    assert 'event_bus.subscribe()' in source
    assert 'event_bus.unsubscribe(q)' in source
    assert 'Dashboard event WebSocket' in source
    assert 'Flow extension' not in source


def test_main_health_and_snapshot_do_not_manufacture_paid_authorization():
    source = inspect.getsource(main)

    assert 'flow_paid_validation' not in source
    assert 'paid_authorization=' not in source
    assert 'build_paid_validation_session' not in source


def test_backend_status_route_description_is_browser_only():
    from agent.api import flow_backend_status

    source = inspect.getsource(flow_backend_status)
    assert 'Browser transport status' in source
    assert 'extension' not in source.lower()
    assert "Cache-Control" in source
