"""Task 8a authored runtime/package removal requirements.

Development-first policy: source coverage only; execution is deferred until the
full browser-only source plan is complete.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_flow_extension_package_is_retired_from_source_tree():
    assert not (ROOT / 'extension').exists()


def test_extension_ws_runtime_config_is_removed():
    config = text('agent/config.py')
    assert 'WS_HOST' not in config
    assert 'WS_PORT' not in config
    assert 'extension connects here' not in config
    assert 'the extension runs it' not in config


def test_flowclient_has_no_extension_status_compatibility_shims():
    client = text('agent/services/flow_client.py')
    assert 'extension_connected' not in client
    assert 'ws_stats' not in client
    assert '_flow_key' not in client


def test_browser_session_module_describes_browser_as_active_transport():
    session = text('agent/services/flow_browser_session.py')
    assert 'Extension remains the active transport' not in session
    assert 'browser-only' in session.lower()


def test_setup_no_longer_instructs_loading_unpackaged_flow_extension():
    setup = text('setup.sh')
    assert 'Load Chrome extension' not in setup
    assert 'Load unpacked' not in setup
    assert 'needed for extension' not in setup
    assert 'COMICREELS_FLOW_PROFILE_CONFIG' in setup
    assert 'flow-browser.local.json' in setup


def test_extension_metadata_ignore_is_removed():
    gitignore = text('.gitignore')
    assert 'extension/_metadata/' not in gitignore


def test_dashboard_websocket_dependency_and_route_are_preserved():
    requirements = text('requirements.txt')
    main = text('agent/main.py')
    assert 'websockets>=12.0' in requirements
    assert '@app.websocket("/ws/dashboard")' in main
    assert 'event_bus.subscribe()' in main


def test_no_profile_or_browser_data_cleanup_is_added():
    setup = text('setup.sh')
    session = text('agent/services/flow_browser_session.py')
    combined = setup + session
    assert 'rm -rf' not in setup
    assert 'clear cookies' not in combined.lower()
    assert 'sign out' not in combined.lower()


def test_worker_docstring_does_not_describe_retired_extension_transport():
    worker = text('agent/worker/processor.py')
    assert 'via Chrome extension' not in worker
    assert 'browser' in worker.splitlines()[0].lower()
