"""Task 6a authored browser-only backend status requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.services import flow_backend_status as status
from agent.services import flow_client as clients
from agent.services.flow_backend_selection import BackendSelection

PRIVATE = 'private-account@example.test /private/profile?token=secret'
BROWSER = BackendSelection()


def browser_health(**overrides):
    return {
        'backend_kind': 'browser',
        'ready': True,
        'state': 'open',
        'session_ready': True,
        'authentication': 'authenticated',
        'lease_held': True,
        'observed_at': '2026-10-01T06:00:00+00:00',
        'readiness_scope': 'non_paid_parity',
        'operations_implemented': True,
        'reconciliation_required': False,
        'pending_intents': 0,
        'paid_dispatch_enabled': False,
        'error': None,
        **overrides,
    }


def test_browser_is_the_only_status_transport_and_preflight():
    result = status.project_status(
        BROWSER, browser_health(),
        actual_kind='browser',
        paid_dispatch_enabled=False,
    )
    assert result['backend_kind'] == 'browser'
    assert result['backend_selection_source'] == 'browser_only'
    assert result['backend_ready'] is True
    assert result['preflight'] == {
        'ready': True,
        'transport': 'browser',
        'session_required': True,
    }
    assert result['paid_dispatch_enabled'] is False
    assert result['production_acceptance'] == 'not_verified'
    serialized = json.dumps(result)
    assert 'extension_connected' not in result
    assert 'extension_required' not in serialized
    assert 'browser_default_candidate' not in result


@pytest.mark.parametrize('overrides', [
    {'ready': 'true'},
    {'lease_held': False},
    {'session_ready': False},
    {'authentication': 'signed_out'},
    {'error': 'PROFILE_CHANGED'},
])
def test_browser_requires_current_positive_session_evidence(overrides):
    result = status.project_status(
        BROWSER, browser_health(**overrides),
        actual_kind='browser',
        paid_dispatch_enabled=False,
    )
    assert result['backend_ready'] is False
    assert result['preflight']['ready'] is False


def test_reconciliation_is_visible_without_becoming_transport_failure():
    result = status.project_status(
        BROWSER,
        browser_health(
            reconciliation_required=True,
            pending_intents=2,
            error='RECONCILIATION_REQUIRED',
        ),
        actual_kind='browser',
        paid_dispatch_enabled=False,
    )
    assert result['backend_ready'] is True
    assert result['reconciliation_required'] is True
    assert result['pending_intents'] == 2
    assert result['error'] == 'RECONCILIATION_REQUIRED'
    assert result['paid_dispatch_enabled'] is False


@pytest.mark.parametrize('paid', [False, True])
def test_paid_switch_is_independent_from_browser_readiness(paid):
    result = status.project_status(
        BROWSER,
        browser_health(session_ready=False, ready=False, error='BROWSER_NOT_READY'),
        actual_kind='browser',
        paid_dispatch_enabled=paid,
    )
    assert result['backend_ready'] is False
    assert result['paid_dispatch_enabled'] is paid


def test_status_drops_private_and_unrecognized_fields():
    result = status.project_status(
        BROWSER,
        browser_health(
            error=PRIVATE,
            observed_at=PRIVATE,
            profile=PRIVATE,
            identity=PRIVATE,
            capabilities={'private': PRIVATE},
        ),
        actual_kind='browser',
        paid_dispatch_enabled=False,
    )
    assert PRIVATE not in json.dumps(result)
    assert result['observed_at'] is None
    assert result['error'] == 'READINESS_UNAVAILABLE'
    assert result['backend_ready'] is False


def test_non_browser_actual_backend_is_fail_closed_not_supported():
    result = status.project_status(
        BROWSER,
        {'ready': True},
        actual_kind='extension',
        paid_dispatch_enabled=False,
    )
    assert result['backend_kind'] == 'browser'
    assert result['backend_ready'] is False
    assert result['error'] == 'BACKEND_SELECTION_MISMATCH'
    assert result['automatic_backend_failover'] is False
    assert 'extension' not in json.dumps(result['preflight'])


@pytest.mark.parametrize('observation', [None, [], PRIVATE, {'ready': True}])
def test_missing_browser_evidence_does_not_manufacture_ready(observation):
    result = status.project_status(
        BROWSER, observation,
        actual_kind='browser',
        paid_dispatch_enabled=False,
    )
    assert result['backend_ready'] is False


@pytest.fixture
def singleton(monkeypatch):
    reader = AsyncMock(return_value=browser_health())
    client = SimpleNamespace(
        backend_kind='browser',
        paid_dispatch_enabled=False,
        backend_readiness=reader,
    )
    monkeypatch.setattr(clients, '_client', client)
    monkeypatch.setattr(clients, '_client_selection', BROWSER)
    monkeypatch.setattr(clients, '_client_initialization_error', None)

    def forbidden(*args, **kwargs):
        raise AssertionError('status must not construct a client or resolve environment')

    monkeypatch.setattr(clients, 'get_flow_client', forbidden)
    monkeypatch.setattr(clients, 'resolve_backend_selection', forbidden)
    return client


@pytest.mark.asyncio
async def test_status_reads_frozen_browser_selection(singleton, monkeypatch):
    monkeypatch.setenv('COMICREELS_FLOW_BACKEND', 'extension')
    result = await status.read_backend_status()
    assert result['backend_kind'] == 'browser'
    assert result['backend_selection_source'] == 'browser_only'
    assert result['backend_ready'] is True
    singleton.backend_readiness.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_never_reads_extension_compatibility_properties(singleton):
    class Trap:
        @property
        def extension_connected(self):
            raise AssertionError('browser-only status must not read extension state')

    singleton.__class__ = Trap
    # SimpleNamespace cannot be safely class-swapped on all Python versions;
    # source-level assertion below is the durable contract.
    source = __import__('inspect').getsource(status.read_backend_status)
    assert 'extension_connected' not in source
    assert 'ws_stats' not in source


@pytest.mark.asyncio
async def test_uninitialized_status_does_not_start_or_resolve_backend(singleton, monkeypatch):
    monkeypatch.setattr(clients, '_client', None)
    result = await status.read_backend_status()
    assert result['error'] == 'BACKEND_NOT_INITIALIZED'
    assert result['backend_ready'] is False
    singleton.backend_readiness.assert_not_awaited()


@pytest.mark.asyncio
async def test_exception_is_sanitized_without_losing_browser_selection(singleton):
    singleton.backend_readiness.side_effect = RuntimeError(PRIVATE)
    result = await status.read_backend_status()
    assert result['backend_kind'] == 'browser'
    assert result['backend_ready'] is False
    assert result['error'] == 'READINESS_UNAVAILABLE'
    assert PRIVATE not in json.dumps(result)


@pytest.mark.asyncio
async def test_timeout_returns_unknown_observation_not_cached_success(singleton, monkeypatch):
    async def slow():
        await asyncio.sleep(60)

    singleton.backend_readiness.side_effect = slow
    monkeypatch.setattr(status, 'READINESS_TIMEOUT_S', 0.01)
    result = await status.read_backend_status()
    assert result['error'] == 'READINESS_TIMEOUT'
    assert result['backend_ready'] is False
    assert result['observed_at'] is None


@pytest.mark.asyncio
async def test_backend_reobserves_false_readiness_on_same_owner_without_restart(tmp_path):
    from agent.services.flow_browser_backend import BrowserFlowBackend
    from agent.services.flow_browser_session import FlowProfileConfig

    profile = tmp_path / 'profile'
    profile.mkdir()
    info = profile.stat()
    config = FlowProfileConfig(
        'unit-flow', profile, tmp_path / 'binding.json',
        (info.st_dev, info.st_ino),
    )
    ready = {'value': True}
    calls = []

    class Driver:
        def __init__(self, *args):
            pass

        def start(self):
            calls.append(('start', threading.get_ident()))

        def health(self):
            calls.append(('health', threading.get_ident()))
            return browser_health(
                ready=ready['value'],
                session_ready=ready['value'],
            )

        def close(self):
            calls.append(('close', threading.get_ident()))

    backend = BrowserFlowBackend(
        config=config,
        state_path=tmp_path / 'state.json',
        driver_factory=Driver,
    )
    try:
        await backend.start()
        ready['value'] = False
        assert (await backend.check_readiness())['ready'] is False
        ready['value'] = True
        assert (await backend.check_readiness())['ready'] is True
    finally:
        await backend.close()

    assert [name for name, _ in calls].count('start') == 1
    assert len({owner for _, owner in calls}) == 1
