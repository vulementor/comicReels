"""Read-only browser backend status projection.

Status observes the already-selected browser singleton only. It never constructs
clients, resolves environment settings, reopens profiles or authorizes effects.
Browser session evidence is the sole transport preflight. Reconciliation and paid
dispatch are reported independently from transport readiness.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from agent.services.flow_backend_selection import BackendSelection
from agent.services.flow_browser_contract import BrowserCommandError

READINESS_TIMEOUT_S = 2.0
_STATES = {'new', 'starting', 'open', 'failed', 'closing', 'closed', 'close_uncertain'}
_SCOPES = {'project_read', 'project_read_upload', 'non_paid_parity'}
_ERRORS = {
    'BACKEND_NOT_INITIALIZED', 'BACKEND_SELECTION_MISMATCH', 'BACKEND_CLOSED',
    'FLOW_BACKEND_INITIALIZATION_FAILED', 'BROWSER_NOT_READY', 'BROWSER_QUEUE_FULL',
    'READINESS_TIMEOUT', 'READINESS_UNAVAILABLE',
    'RECONCILIATION_REQUIRED', 'CLOSE_UNCERTAIN', 'PROFILE_CONFIG_REQUIRED',
    'PROFILE_CONFIG_INVALID', 'PROFILE_NOT_FOUND', 'PROFILE_CHANGED', 'PROFILE_BUSY',
    'PROFILE_RECONCILE_REQUIRED', 'PROFILE_NATIVE_BUSY', 'PROFILE_LEASE_REQUIRED',
    'IDENTITY_UNVERIFIED', 'IDENTITY_CHANGED', 'INVALID_STATE', 'OWNER_MISMATCH',
    'STATE_READ_FAILED', 'STATE_WRITE_FAILED', 'STATE_LIMIT_EXCEEDED',
    'DRIVER_START_FAILED', 'DRIVER_OBSERVATION_FAILED', 'OBSERVATION_FAILED',
    'FLOW_PAGE_UNAVAILABLE', 'SEMANTIC_CAPTURE_UNAVAILABLE',
}


def _boolean(value):
    return value if type(value) is bool else None


def _choice(value, choices):
    return value if isinstance(value, str) and value in choices else None


def _error(value):
    if value is None:
        return None
    return _choice(value, _ERRORS) or 'READINESS_UNAVAILABLE'


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError:
        return None


def project_status(
    selection,
    observation,
    *,
    actual_kind=None,
    paid_dispatch_enabled=None,
    read_error=None,
) -> dict:
    """Project browser readiness plus independent reconciliation/paid state."""
    selected = selection if isinstance(selection, BackendSelection) else None
    selected_kind = selected.kind if selected is not None else 'browser'
    selected_source = selected.source if selected is not None else 'unrecorded'
    actual_kind = actual_kind if isinstance(actual_kind, str) else None

    observed = observation if isinstance(observation, dict) else {}
    error = _error(read_error) or _error(observed.get('error'))
    if not isinstance(observation, dict) and error is None:
        error = 'READINESS_UNAVAILABLE'
    if actual_kind not in {None, 'browser'} or selected_kind != 'browser':
        error = 'BACKEND_SELECTION_MISMATCH'

    ready = bool(
        observed.get('ready') is True
        and observed.get('session_ready') is True
        and observed.get('authentication') == 'authenticated'
        and observed.get('lease_held') is True
    )
    # Reconciliation can coexist with a healthy read/session transport. Every
    # other status error invalidates transport readiness.
    if error not in {None, 'RECONCILIATION_REQUIRED'}:
        ready = False
    if not ready and error is None:
        error = 'BROWSER_NOT_READY'

    pending = observed.get('pending_intents')
    pending = pending if type(pending) is int and 0 <= pending <= 4096 else None
    reconciliation = _boolean(observed.get('reconciliation_required'))

    return {
        'schema_version': 2,
        'backend_kind': 'browser',
        'backend_selection_source': (
            selected_source if selected_source == 'browser_only' else 'unrecorded'
        ),
        'backend_switch_requires_restart': True,
        'automatic_backend_failover': False,
        'backend_ready': ready,
        'backend_state': _choice(observed.get('state'), _STATES),
        'session_ready': _boolean(observed.get('session_ready')),
        'authentication': _choice(
            observed.get('authentication'),
            {'authenticated', 'signed_out', 'unknown'},
        ),
        'lease_held': _boolean(observed.get('lease_held')),
        'observed_at': _timestamp(observed.get('observed_at')),
        'readiness_scope': _choice(observed.get('readiness_scope'), _SCOPES),
        'operations_implemented': _boolean(observed.get('operations_implemented')),
        'pending_intents': pending,
        'reconciliation_required': reconciliation,
        # Explicit backend switch only. Never infer paid authorization from
        # browser readiness, reconciliation state or capability maps.
        'paid_dispatch_enabled': _boolean(paid_dispatch_enabled),
        'production_acceptance': 'not_verified',
        'error': error,
        'preflight': {
            'ready': ready,
            'transport': 'browser',
            'session_required': True,
        },
    }


async def read_backend_status() -> dict:
    """Observe the frozen browser singleton only, without construction or effects."""
    from agent.services import flow_client as clients

    with clients._client_lock:
        client = clients._client
        selection = clients._client_selection
        initialization_error = clients._client_initialization_error

    if client is None:
        return project_status(
            selection,
            None,
            read_error=initialization_error or 'BACKEND_NOT_INITIALIZED',
        )

    kind = paid = None
    try:
        kind = client.backend_kind
        paid = client.paid_dispatch_enabled
        observed = await asyncio.wait_for(
            client.backend_readiness(),
            READINESS_TIMEOUT_S,
        )
        return project_status(
            selection,
            observed,
            actual_kind=kind,
            paid_dispatch_enabled=paid,
        )
    except asyncio.TimeoutError:
        error = 'READINESS_TIMEOUT'
    except BrowserCommandError as failure:
        error = _error(str(failure))
    except Exception:
        error = 'READINESS_UNAVAILABLE'

    # Failed readiness is not evidence that an enabled paid switch is currently
    # usable. Known disabled state may remain false; otherwise report unknown.
    return project_status(
        selection,
        None,
        actual_kind=kind,
        paid_dispatch_enabled=False if paid is False else None,
        read_error=error,
    )
