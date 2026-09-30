"""Concrete synchronous owner for the non-paid Flow browser backend.

FBR-2-code-1 implements lifecycle and read-only journal loading only. Session
readiness is NOT operation readiness: project/read/upload/reconciliation wiring
is still pending, so the backend stays unready and all operations fail closed.
No browser is constructed at import time or in the driver constructor.
"""
from __future__ import annotations

import threading
from pathlib import Path

from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_contract import BrowserCommandError, uuid_value
from agent.services.flow_browser_session import FlowBrowserSessionProvider, FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore

# Only fixed, non-sensitive codes may cross the driver boundary. Do not forward
# arbitrary browser exceptions, account observations, paths or raw state data.
_PUBLIC_CODES = frozenset({
    'PROFILE_CONFIG_REQUIRED', 'PROFILE_CONFIG_INVALID', 'PROFILE_NOT_FOUND',
    'PROFILE_CHANGED', 'PROFILE_BUSY', 'PROFILE_RECONCILE_REQUIRED',
    'PROFILE_NATIVE_BUSY', 'PROFILE_LEASE_REQUIRED', 'ALREADY_OPEN',
    'OPEN_FAILED', 'CLOSE_UNCERTAIN', 'WRONG_OWNER_THREAD',
    'SYNC_BROWSER_REQUIRED', 'SYNC_AUTH_PROBE_REQUIRED',
    'FLOW_PAGE_UNAVAILABLE', 'SEMANTIC_CAPTURE_UNAVAILABLE',
    'IDENTITY_UNVERIFIED', 'IDENTITY_CHANGED', 'OBSERVATION_FAILED',
    'INVALID_INPUT', 'INVALID_STATE', 'OWNER_MISMATCH', 'STATE_READ_FAILED',
    'STATE_WRITE_FAILED', 'STATE_LIMIT_EXCEEDED', 'INVALID_TRANSITION',
    'RECONCILIATION_REQUIRED',
})


def _public_error(error: BaseException, fallback: str) -> str:
    code = getattr(error, 'code', None)
    if isinstance(error, BrowserCommandError):
        code = str(error)
    return code if isinstance(code, str) and code in _PUBLIC_CODES else fallback


class FlowBrowserDriver:
    """Own one provider on the backend's existing single executor thread.

    The provider alone owns the browser context and physical profile lease.
    The driver reads BrowserStateStore only while that provider reports its
    lease held. Existing SUBMITTING/UNKNOWN records are never replayed, marked
    complete, or replaced during start/health/close.

    session_factory is the offline session seam; production supplies neither
    a fake driver nor a replacement profile. A failed close retains the same
    provider for an explicit close retry. A closed driver cannot be restarted.
    """

    paid_dispatch_enabled = False

    def __init__(self, config: FlowProfileConfig, state_path: Path,
                 owner_key: str, *, session_factory=None):
        self.config = config
        self._store = BrowserStateStore(Path(state_path), owner_key)
        self._factory = session_factory or FlowBrowserSessionProvider
        self._provider = None
        self._thread = None
        self._phase = 'new'
        self._error = None

    def _check_thread(self) -> None:
        if self._thread is not None and self._thread != threading.get_ident():
            raise BrowserCommandError('WRONG_OWNER_THREAD')

    def _require_lease(self) -> None:
        if self._provider is None:
            raise BrowserCommandError('PROFILE_LEASE_REQUIRED')
        observed = self._provider.health()
        if (not isinstance(observed, dict) or observed.get('state') != 'open'
                or observed.get('lease_held') is not True):
            raise BrowserCommandError('PROFILE_LEASE_REQUIRED')

    def start(self) -> None:
        self._check_thread()
        if self._phase == 'open':
            return
        if self._phase == 'close_uncertain':
            raise BrowserCommandError('CLOSE_UNCERTAIN')
        if self._phase != 'new':
            raise BrowserCommandError('DRIVER_CLOSED')
        self._thread = threading.get_ident()
        self._phase = 'starting'
        try:
            # Verify the original physical directory; never create a fallback.
            self.config.verify_directory()
            self._provider = self._factory(self.config, auth_probe=observe_flow_account)
            self._provider.open()
            self._require_lease()
            self._store.load()  # Validate owner/schema without writing or resetting state.
            self._phase = 'open'
        except BaseException as error:  # Also clean up an interrupted partial open.
            self._phase = 'failed'
            self._error = _public_error(error, 'DRIVER_START_FAILED')
            try:
                if self._provider is not None:
                    self._provider.close()
            except BaseException:
                # Do not release a lock independently of its still-uncertain owner.
                self._phase, self._error = 'close_uncertain', 'CLOSE_UNCERTAIN'
                raise BrowserCommandError('CLOSE_UNCERTAIN') from None
            self._provider = None
            if not isinstance(error, Exception):
                raise
            raise BrowserCommandError(self._error) from None

    def health(self) -> dict:
        """Fresh session evidence and journal summary, never a parity/PASS claim."""
        self._check_thread()
        report = {
            'backend_kind': 'browser', 'profile': self.config.profile_logical_name,
            'state': self._phase,
            # In particular, CLOSE_UNCERTAIN is not evidence of a released lease.
            'lease_held': False if self._phase in {'new', 'closed', 'failed'} else None,
            'authentication': 'unknown', 'semantic_node_count': 0,
            'observed_at': None, 'session_ready': False,
            'ready': False, 'readiness_scope': 'session_only',
            'operations_implemented': False, 'paid_dispatch_enabled': False,
            'has_saved_project': None, 'pending_intents': None,
            'reconciliation_required': None, 'error': self._error,
        }
        if self._phase != 'open':
            return report
        try:
            self.config.verify_directory()
            self._require_lease()
            report['lease_held'] = True
            saved = self._store.load()
            pending = sum(entry['state'] in {'SUBMITTING', 'UNKNOWN'}
                          for entry in saved['intents'].values())
            report.update(has_saved_project=saved['project_id'] is not None,
                          pending_intents=pending, reconciliation_required=bool(pending))
            observed = self._provider.capture_health()
            if not isinstance(observed, dict):
                raise ValueError
            authentication = observed.get('authentication')
            if authentication in ('authenticated', 'signed_out', 'unknown'):
                report['authentication'] = authentication
            count = observed.get('semantic_node_count')
            if type(count) is int and count >= 0:
                report['semantic_node_count'] = count
            timestamp = observed.get('observed_at')
            if isinstance(timestamp, str) and len(timestamp) <= 64:
                report['observed_at'] = timestamp
            report['lease_held'] = (observed.get('lease_held') is True
                                    and observed.get('state') == 'open')
            report['session_ready'] = bool(
                report['lease_held'] and observed.get('ready') is True
                and report['authentication'] == 'authenticated'
                and report['semantic_node_count'] > 0 and report['observed_at']
                and observed.get('error') is None)
            code = observed.get('error')
            if code is not None:
                report['error'] = (code if isinstance(code, str) and code in _PUBLIC_CODES
                                   else 'DRIVER_OBSERVATION_FAILED')
            elif not report['session_ready']:
                report['error'] = 'BROWSER_NOT_READY'
            elif pending:
                report['error'] = 'RECONCILIATION_REQUIRED'
            else:
                report['error'] = 'BROWSER_CAPABILITIES_PENDING'
        except Exception as error:  # Never leak state bytes, profile paths or account text.
            report['session_ready'] = False
            report['error'] = _public_error(error, 'DRIVER_OBSERVATION_FAILED')
        return report

    def execute(self, command, timeout=300) -> dict:
        self._check_thread()
        return {'status': 501, 'error': 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
                'effect': 'not_submitted'}

    def open_project(self, project_id: str) -> dict:
        self._check_thread()
        uuid_value(project_id)
        return {'status': 501, 'error': 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
                'effect': 'not_submitted'}

    def ensure_session_project(self, title=None, force_new=False) -> dict:
        self._check_thread()
        raise BrowserCommandError('BROWSER_CAPABILITY_NOT_IMPLEMENTED')

    def close(self) -> None:
        self._check_thread()
        if self._phase == 'closed':
            return
        self._phase = 'closing'
        try:
            if self._provider is not None:
                self._provider.close()
        except BaseException:
            self._phase, self._error = 'close_uncertain', 'CLOSE_UNCERTAIN'
            raise BrowserCommandError('CLOSE_UNCERTAIN') from None
        self._provider = None
        self._phase, self._error = 'closed', None
