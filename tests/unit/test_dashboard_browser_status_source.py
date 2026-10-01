"""Task 7 authored dashboard browser-only status UI requirements.

Development-first policy: source coverage only; dashboard build/test is deferred
until the full browser-only source plan is complete.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def test_flow_backend_panel_decodes_browser_only_status_v2():
    panel = source('dashboard/src/components/FlowBackendStatus.tsx')

    assert 'schema_version: 2' in panel
    assert "backend_kind: 'browser'" in panel
    assert "transport: 'browser'" in panel
    assert 'session_ready: boolean | null' in panel
    assert 'authentication:' in panel
    assert 'lease_held: boolean | null' in panel
    assert 'pending_intents: number | null' in panel
    assert 'reconciliation_required: boolean | null' in panel
    assert 'paid_dispatch_enabled: boolean | null' in panel

    lowered = panel.lower()
    assert 'extension_required' not in lowered
    assert "backend_kind === 'extension'" not in panel
    assert 'extension default' not in lowered
    assert 'extension connection' not in lowered


def test_flow_backend_panel_keeps_readiness_reconciliation_and_paid_separate():
    panel = source('dashboard/src/components/FlowBackendStatus.tsx')

    assert 'status?.session_ready' in panel
    assert 'status?.reconciliation_required' in panel
    assert 'status?.paid_dispatch_enabled' in panel
    assert 'status?.pending_intents' in panel
    assert 'paidLocked' in panel
    assert 'reconciliationLabel' in panel
    assert 'sessionLabel' in panel


def test_dashboard_websocket_indicator_is_named_as_dashboard_channel():
    app = source('dashboard/src/App.tsx')
    translations = source('dashboard/src/i18n/translations.ts')

    assert "t('app.dashboardLive')" in app
    assert "t('app.dashboardDisconnected')" in app
    assert "t('app.wsLive')" not in app
    assert "t('app.wsDisconnected')" not in app
    assert "'app.dashboardLive': 'DASHBOARD LIVE'" in translations
    assert "'app.dashboardDisconnected': 'DASHBOARD OFFLINE'" in translations


def test_task7_surfaces_do_not_call_dashboard_ws_flow_transport():
    panel = source('dashboard/src/components/FlowBackendStatus.tsx')
    app = source('dashboard/src/App.tsx')

    assert 'extension' not in panel.lower()
    assert 'Flow extension' not in app
    assert '<FlowBackendStatus />' in app
    assert 'useWebSocketContext()' in app
