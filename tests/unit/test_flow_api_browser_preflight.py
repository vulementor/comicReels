"""Task 6b authored direct Flow API browser-preflight requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from agent.api import flow as api


def ready_status(**overrides):
    return {
        'backend_kind': 'browser',
        'backend_ready': True,
        'session_ready': True,
        'authentication': 'authenticated',
        'lease_held': True,
        'reconciliation_required': False,
        'pending_intents': 0,
        'paid_dispatch_enabled': False,
        'error': None,
        'preflight': {
            'ready': True,
            'transport': 'browser',
            'session_required': True,
        },
        **overrides,
    }


@pytest.mark.asyncio
async def test_browser_preflight_uses_fresh_status_not_client_connected(monkeypatch):
    client = SimpleNamespace(connected=False)
    reader = AsyncMock(return_value=ready_status())
    monkeypatch.setattr(api, 'read_backend_status', reader)

    result = await api._require_browser_session(client)

    assert result['backend_ready'] is True
    reader.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('overrides', [
    {'backend_ready': False, 'error': 'BROWSER_NOT_READY'},
    {'session_ready': False, 'backend_ready': False},
    {'authentication': 'signed_out', 'backend_ready': False},
    {'lease_held': False, 'backend_ready': False},
])
async def test_browser_preflight_fails_closed_with_fixed_503(monkeypatch, overrides):
    monkeypatch.setattr(
        api,
        'read_backend_status',
        AsyncMock(return_value=ready_status(**overrides)),
    )

    with pytest.raises(HTTPException) as caught:
        await api._require_browser_session(SimpleNamespace())

    assert caught.value.status_code == 503
    assert caught.value.detail == 'Browser session not ready'


@pytest.mark.asyncio
async def test_reconciliation_warning_does_not_block_safe_transport_preflight(monkeypatch):
    status = ready_status(
        reconciliation_required=True,
        pending_intents=2,
        error='RECONCILIATION_REQUIRED',
    )
    monkeypatch.setattr(api, 'read_backend_status', AsyncMock(return_value=status))

    result = await api._require_browser_session(SimpleNamespace())

    assert result['backend_ready'] is True
    assert result['reconciliation_required'] is True


@pytest.mark.asyncio
async def test_flow_status_exposes_browser_session_reconciliation_and_paid_lock(monkeypatch):
    client = SimpleNamespace(
        generation_guard_status={
            'cooldown_active': False,
            'cooldown_remaining_s': 0.0,
            'last_unusual_activity_at': None,
            'last_unusual_activity_rpc': None,
        },
    )
    monkeypatch.setattr(api, 'get_flow_client', lambda: client)
    monkeypatch.setattr(api, 'read_backend_status', AsyncMock(return_value=ready_status()))
    monkeypatch.setattr(api, 'current_session_project', lambda: {'project_id': None})

    result = await api.flow_status()

    assert result['transport'] == 'browser'
    assert result['browser_session_ready'] is True
    assert result['authentication'] == 'authenticated'
    assert result['lease_held'] is True
    assert result['reconciliation_required'] is False
    assert result['pending_intents'] == 0
    assert result['paid_dispatch_enabled'] is False

    serialized = json.dumps(result)
    for removed in (
        'extension_connected',
        'extension_session',
        'flow_key_present',
    ):
        assert removed not in serialized


def test_flow_api_source_has_no_extension_preflight_or_auto_paid_authorization():
    source = inspect.getsource(api)

    assert 'Extension not connected' not in source
    assert 'extension_connected' not in source
    assert 'extension_session' not in source
    assert 'flow_key_present' not in source
    assert 'client.ws_stats' not in source
    assert 'client._flow_key' not in source

    # Normal HTTP API must not manufacture/import the explicit validation grant.
    assert 'flow_paid_validation' not in source
    assert 'paid_authorization=' not in source
    assert 'build_paid_validation_session' not in source


def test_direct_endpoints_use_browser_session_preflight_helper():
    source = inspect.getsource(api)
    assert source.count('await _require_browser_session(client)') >= 10
    assert 'if not client.connected' not in source


def test_direct_video_request_schemas_can_carry_idempotency_without_paid_authorization():
    for model in (
        api.GenerateVideoRequest,
        api.GenerateVideoRefsRequest,
        api.GenerateOmniFlashVideoRequest,
        api.GenerateOmniFlashTextVideoRequest,
    ):
        assert "idempotency_key" in model.model_fields
        assert "paid_authorization" not in model.model_fields


def test_direct_video_endpoints_forward_idempotency_but_never_authorization():
    source = inspect.getsource(api)
    assert "idempotency_key" in source
    assert "paid_authorization=" not in source
    assert "build_paid_video_validation_session" not in source
    assert "flow_paid_video_validation" not in source
