"""Task 8b authored browser-only operator/docs/Guide requirements.

Development-first policy: source checks only; not executed until Phase 3.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def assert_browser_preflight(source: str) -> None:
    assert 'browser_session_ready' in source
    assert 'backend_ready' in source
    assert 'authentication' in source
    assert 'lease_held' in source
    assert 'extension_connected' not in source
    assert 'flow_key_present' not in source
    assert 'NO_FLOW_KEY' not in source
    assert 'localhost:9222' not in source
    assert '127.0.0.1:9222' not in source


def test_generated_agents_source_is_browser_only():
    source = text('setup.py')
    assert_browser_preflight(source)
    assert 'Chrome-extension/WebSocket Flow transport' not in source
    assert 'Do not delete the extension early' not in source
    assert 'extension backend' not in source
    assert 'persistent signed-in Flow browser profile' in source


def test_checked_in_agents_and_claude_preflight_are_browser_only():
    assert_browser_preflight(text('AGENTS.md'))
    assert_browser_preflight(text('CLAUDE.md'))


def test_readme_current_operator_sections_are_browser_only():
    source = text('README.md')
    current = source.split('## Historical migration notes', 1)[0]
    assert_browser_preflight(current)
    assert 'Load Chrome extension' not in current
    assert 'Chrome Extension — Live Dashboard' not in current
    assert 'extension/' not in current
    assert 'WebSocket bridge to the extension' not in current
    assert 'persistent browser profile' in current.lower()


def test_dashboard_guide_uses_browser_health_and_keeps_dashboard_ws_separate():
    guide = text('dashboard/src/pages/GuidePage.tsx')
    assert 'browser_session_ready' in guide
    assert 'reconciliation_required' in guide
    assert 'paid_dispatch_enabled' in guide
    assert 'extension_connected' not in guide
    assert '.ws.' not in guide


def test_i18n_operator_copy_has_no_flow_extension_setup_instructions():
    source = text('dashboard/src/i18n/translations.ts')
    forbidden = (
        'Chrome Extension Setup Guide',
        'chrome://extensions',
        'Load unpacked',
        'extension_connected',
        'NO_FLOW_KEY',
        'port 9222',
        'cổng 9222',
        'extension/ folder',
        'extension/ फ़ोल्डर',
    )
    for marker in forbidden:
        assert marker not in source
    assert "'guide.status.browserReady'" in source
    assert "'guide.status.paidLocked'" in source
    assert "'guide.status.dashboardChannel'" in source


def test_core_operator_skills_use_browser_session_diagnostics():
    for path in (
        'skills/fk-doctor.md',
        'skills/fk-dashboard.md',
        'skills/fk-status.md',
        'skills/fk-pipeline.md',
    ):
        source = text(path)
        assert 'extension_connected' not in source
        assert 'reload extension' not in source.lower()
    doctor = text('skills/fk-doctor.md')
    assert 'RECONCILIATION_REQUIRED' in doctor
    assert 'BROWSER_NOT_READY' in doctor
    assert 'PROFILE_' in doctor


def test_docs_never_instruct_profile_cookie_or_storage_reset():
    paths = (
        'setup.py', 'AGENTS.md', 'CLAUDE.md', 'README.md',
        'dashboard/src/i18n/translations.ts', 'skills/fk-doctor.md',
    )
    combined = '\n'.join(text(path) for path in paths).lower()
    for marker in (
        'remove all cookies',
        'delete cookies',
        'clear cookies',
        'clear storage',
        'sign out and',
        'create a new profile',
        'replace the profile',
    ):
        assert marker not in combined
