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


def test_flow_batch_transport_description_is_browser_only():
    source = text('agent/services/flow_batch.py')
    # flow_batch is an envelope/codec layer. Historical prose may describe how
    # captures were once issued, but active extension runtime protocol must not
    # reappear here.
    assert 'browser' in source.lower()
    assert 'ExtensionFlowBackend' not in source
    assert 'extension_connected' not in source
    assert 'ws_stats' not in source
    assert '_send_extension' not in source
    assert 'run_ws_server' not in source


def test_live_flow_surfaces_have_no_retired_extension_protocol_markers():
    live_paths = (
        'agent/main.py',
        'agent/config.py',
        'agent/api/flow.py',
        'agent/api/flow_backend_status.py',
        'agent/services/flow_backend.py',
        'agent/services/flow_backend_status.py',
        'agent/services/flow_client.py',
        'agent/services/flow_batch.py',
        'agent/services/flow_browser_backend.py',
        'agent/services/flow_browser_driver.py',
        'agent/services/flow_browser_session.py',
        'agent/worker/processor.py',
        'agent/sdk/services/operations.py',
        'dashboard/src/App.tsx',
        'dashboard/src/components/FlowBackendStatus.tsx',
        'dashboard/src/pages/GuidePage.tsx',
        'scripts/statusline.sh',
    )
    forbidden = (
        'extension_connected',
        'flow_key_present',
        'NO_FLOW_KEY',
        'NO_FLOW_TAB',
        'extension_switched',
        '127.0.0.1:9222',
        'localhost:9222',
        'run_ws_server',
        'set_extension(',
        'clear_extension(',
        '_send_extension',
        '/api/ext/callback',
        'WS_PORT',
        'WS_HOST',
    )
    for path in live_paths:
        source = text(path)
        for marker in forbidden:
            assert marker not in source, f'{path}: {marker}'


def test_obsolete_extension_config_is_rejected_not_supported():
    source = text('agent/services/flow_backend_selection.py')
    assert "explicit == 'extension'" in source
    assert 'FLOW_EXTENSION_BACKEND_REMOVED' in source
    assert 'ExtensionFlowBackend' not in source


def test_dashboard_event_channel_survives_flow_extension_retirement():
    main = text('agent/main.py')
    websocket_context = text('dashboard/src/api/WebSocketContext.tsx')
    assert '@app.websocket("/ws/dashboard")' in main
    assert 'event_bus.subscribe()' in main
    assert 'not the Flow transport' in websocket_context
