"""Read-only selected-backend status; configuration is never a health verdict.

This adapter reads the existing singleton snapshot. GET/status must not construct
clients, re-resolve environment settings, reopen profiles, or authorize effects.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from agent.services.flow_backend_selection import BackendSelection
from agent.services.flow_browser_contract import BrowserCommandError

READINESS_TIMEOUT_S = 2.0
_SOURCES = {'explicit', 'extension_default', 'accepted_browser_default'}
_STATES = {'new', 'starting', 'open', 'failed', 'closing', 'closed', 'close_uncertain'}
_SCOPES = {'project_read', 'project_read_upload', 'non_paid_parity', 'extension'}
_ERRORS = {
    'BACKEND_NOT_INITIALIZED', 'BACKEND_SELECTION_MISMATCH', 'BACKEND_CLOSED',
    'FLOW_BACKEND_INITIALIZATION_FAILED', 'BROWSER_NOT_READY', 'BROWSER_QUEUE_FULL',
    'EXTENSION_NOT_CONNECTED', 'READINESS_TIMEOUT', 'READINESS_UNAVAILABLE',
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


def project_status(selection, observation, *, actual_kind=None,
                   extension_connected=None, paid_dispatch_enabled=None,
                   read_error=None) -> dict:
    """Allowlisted projection, with independent selection/readiness/paid fields."""
    actual_kind = _choice(actual_kind, {'extension', 'browser'})
    selected = selection if isinstance(selection, BackendSelection) else None
    kind = _choice(selected.kind, {'extension', 'browser'}) if selected else actual_kind
    source = _choice(selected.source, _SOURCES) if selected else None
    observed = observation if isinstance(observation, dict) else {}
    error = _error(read_error) or _error(observed.get('error'))
    if not isinstance(observation, dict) and error is None:
        error = 'READINESS_UNAVAILABLE'
    if selected is not None and actual_kind != kind and read_error is None:
        error = 'BACKEND_SELECTION_MISMATCH'

    extension = _boolean(extension_connected)
    ready = kind is not None and observed.get('ready') is True
    if kind == 'browser':
        ready = bool(ready and observed.get('session_ready') is True
                     and observed.get('authentication') == 'authenticated'
                     and observed.get('lease_held') is True)
    elif kind == 'extension':
        ready = ready and extension is True
    if error not in {None, 'RECONCILIATION_REQUIRED'}:
        ready = False
    if not ready and error is None:
        error = 'EXTENSION_NOT_CONNECTED' if kind == 'extension' else 'BROWSER_NOT_READY'

    pending = observed.get('pending_intents')
    pending = pending if type(pending) is int and 0 <= pending <= 4096 else None
    return {
        'schema_version': 1,
        'backend_kind': kind or 'unknown',
        'backend_selection_source': source or 'unrecorded',
        'browser_default_candidate': 'browser',
        'backend_switch_requires_restart': True,
        'automatic_backend_failover': False,
        'backend_ready': ready,
        'backend_state': _choice(observed.get('state'), _STATES),
        'session_ready': _boolean(observed.get('session_ready')),
        'authentication': _choice(observed.get('authentication'),
                                  {'authenticated', 'signed_out', 'unknown'}),
        'lease_held': _boolean(observed.get('lease_held')),
        'observed_at': _timestamp(observed.get('observed_at')),
        'readiness_scope': _choice(observed.get('readiness_scope'), _SCOPES),
        'operations_implemented': _boolean(observed.get('operations_implemented')),
        'pending_intents': pending,
        'reconciliation_required': _boolean(observed.get('reconciliation_required')),
        # Report the backend's explicit dispatch switch, not an inference from
        # readiness, selection, an acceptance marker or a returned capability map.
        'paid_dispatch_enabled': _boolean(paid_dispatch_enabled),
        'extension_connected': extension,
        'production_acceptance': 'not_verified',
        'error': error,
        'preflight': {
            'ready': ready,
            'extension_required': kind == 'extension' if kind is not None else None,
        },
    }


async def read_backend_status() -> dict:
    """Observe the chosen client only; no creation, reselection or auto-failover.

    Snapshot the internal singleton fields together under its construction lock.
    Keep that compatibility seam here rather than letting API/UI code inspect it.
    Never hold the lock across asynchronous observation.
    """
    from agent.services import flow_client as clients

    with clients._client_lock:
        client = clients._client
        selection = clients._client_selection
        initialization_error = clients._client_initialization_error
    if client is None:
        return project_status(selection, None,
                              read_error=initialization_error or 'BACKEND_NOT_INITIALIZED')

    kind = extension = paid = None
    try:
        kind = client.backend_kind
        extension = client.extension_connected
        paid = client.paid_dispatch_enabled
        observed = await asyncio.wait_for(client.backend_readiness(), READINESS_TIMEOUT_S)
        return project_status(selection, observed, actual_kind=kind,
                              extension_connected=extension, paid_dispatch_enabled=paid)
    except asyncio.TimeoutError:
        error = 'READINESS_TIMEOUT'
    except BrowserCommandError as failure:
        error = _error(str(failure))
    except Exception:
        error = 'READINESS_UNAVAILABLE'
    # Timeout/error is not a fresh positive observation. Known disabled paid
    # dispatch may stay false; never advertise an enabled switch from a failed read.
    return project_status(selection, None, actual_kind=kind,
                          extension_connected=extension,
                          paid_dispatch_enabled=False if paid is False else None,
                          read_error=error)
