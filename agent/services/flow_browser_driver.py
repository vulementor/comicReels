"""Concrete synchronous owner for the non-paid Flow browser backend.

FBR-2-code-1 established lifecycle/state ownership. FBR-2-code-2 adds the
bounded project open/resume/create-session path plus project/media reads.
FBR-2-code-3a connects durable uploads through the existing shared uploader.
Operation reconciliation and every paid capability remain fail-closed.
No browser is constructed at import time or in the driver constructor.
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from agent.services import flow_batch as fb
from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_contract import (
    BrowserCommandError,
    uuid_value,
    validate_command,
)
from agent.services.flow_browser_session import FlowBrowserSessionProvider, FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore
from agent.services.flow_browser_upload import execute_upload

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
    'RECONCILIATION_REQUIRED', 'BROWSER_NOT_READY', 'PROJECT_REQUIRED',
    'PROJECT_OPEN_FAILED', 'PROJECT_RECEIPT_UNVERIFIED',
    'RPC_READ_FAILED', 'RPC_NOT_ALLOWED', 'RECIPE_UNVERIFIED',
    'SESSION_UNVERIFIED', 'HTTP_REJECTED', 'BODY_INCOMPLETE', 'BODY_BUDGET',
    'IMAGE_CONTENT_INVALID', 'IMAGE_MIME_MISMATCH', 'UPLOAD_FAILED',
    'UPLOAD_RECEIPT_UNVERIFIED', 'UPLOAD_RECONCILIATION_REQUIRED',
    'OPERATION_BINDING_REQUIRED', 'OPERATION_BINDING_CONFLICT',
    'OPERATION_RECEIPT_UNVERIFIED', 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
})


def _public_error(error: BaseException, fallback: str) -> str:
    code = getattr(error, 'code', None)
    if isinstance(error, BrowserCommandError):
        code = str(error)
    return code if isinstance(code, str) and code in _PUBLIC_CODES else fallback


def _fixed_response_error(value, fallback='RPC_READ_FAILED') -> str:
    return value if isinstance(value, str) and value in _PUBLIC_CODES else fallback


class FlowBrowserDriver:
    """Own one provider on the backend's existing single executor thread.

    The provider alone owns the browser context and physical profile lease.
    State is read/written only while that provider reports its lease held.
    Existing SUBMITTING/UNKNOWN records are never replayed automatically.

    Project creation here is the durable *session-project* path. Generic raw
    create RPC execution stays unavailable until a caller-facing idempotency
    contract exists; repeated identical raw create envelopes are not silently
    treated as permission to create duplicate remote projects.
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

    def _require_session(self):
        self._check_thread()
        if self._phase != 'open' or self._provider is None:
            raise BrowserCommandError('BROWSER_NOT_READY')
        self.config.verify_directory()
        self._require_lease()
        observed = self._provider.capture_health()
        if not isinstance(observed, dict):
            raise BrowserCommandError('BROWSER_NOT_READY')
        code = observed.get('error')
        if code is not None:
            raise BrowserCommandError(_fixed_response_error(
                code, 'BROWSER_NOT_READY'))
        if (observed.get('state') != 'open' or observed.get('lease_held') is not True
                or observed.get('authentication') != 'authenticated'
                or observed.get('ready') is not True
                or type(observed.get('semantic_node_count')) is not int
                or observed.get('semantic_node_count') <= 0):
            raise BrowserCommandError('BROWSER_NOT_READY')
        session = getattr(self._provider, 'session', None)
        page = getattr(session, 'page', None)
        if page is None:
            raise BrowserCommandError('BROWSER_NOT_READY')
        return page

    def _state(self) -> dict:
        self._require_lease()
        return self._store.load()

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
        """Fresh session evidence plus bounded capability/state projection."""
        self._check_thread()
        capabilities = {
            'project_open_resume': True,
            'project_create_session': True,
            'project_media_read': True,
            'media_read': True,
            'operation_reconcile': True,
            'upload': True,
            'paid_dispatch': False,
        }
        report = {
            'backend_kind': 'browser', 'profile': self.config.profile_logical_name,
            'state': self._phase,
            # In particular, CLOSE_UNCERTAIN is not evidence of a released lease.
            'lease_held': False if self._phase in {'new', 'closed', 'failed'} else None,
            'authentication': 'unknown', 'semantic_node_count': 0,
            'observed_at': None, 'session_ready': False,
            'ready': False, 'readiness_scope': 'non_paid_parity',
            'operations_implemented': True, 'capabilities': capabilities,
            'paid_dispatch_enabled': False,
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
            report['ready'] = report['session_ready']
            code = observed.get('error')
            if code is not None:
                report['error'] = (code if isinstance(code, str) and code in _PUBLIC_CODES
                                   else 'DRIVER_OBSERVATION_FAILED')
            elif not report['session_ready']:
                report['error'] = 'BROWSER_NOT_READY'
            elif report['reconciliation_required']:
                # The backend remains usable for safe non-paid reads/reconciliation,
                # while health still surfaces that a mutation outcome needs review.
                report['error'] = 'RECONCILIATION_REQUIRED'
            else:
                report['error'] = None
        except Exception as error:  # Never leak state bytes, profile paths or account text.
            report['session_ready'] = False
            report['ready'] = False
            report['error'] = _public_error(error, 'DRIVER_OBSERVATION_FAILED')
        return report

    def _open_project_page(self, project_id: str):
        project_id = uuid_value(project_id)
        page = self._require_session()
        try:
            page.goto(f'https://flow.google.com/project/{project_id}',
                      wait_until='domcontentloaded', timeout=60_000)
            location = urlsplit(page.url)
            if (location.scheme != 'https' or location.hostname != 'flow.google.com'
                    or location.port not in {None, 443}
                    or location.username or location.password
                    or location.path != f'/project/{project_id}'):
                raise ValueError
            # Navigation can change identity/session state. Require fresh evidence.
            self._require_session()
        except BrowserCommandError:
            raise
        except Exception:
            raise BrowserCommandError('PROJECT_OPEN_FAILED') from None
        return page

    def open_project(self, project_id: str) -> dict:
        self._check_thread()
        try:
            project_id = uuid_value(project_id)
            self._open_project_page(project_id)
            self._store.set_project(project_id)
            return {'status': 200, 'data': {'projectId': project_id},
                    'effect': 'completed'}
        except Exception as error:
            return {'status': 409,
                    'error': _public_error(error, 'PROJECT_OPEN_FAILED'),
                    'effect': 'not_submitted'}

    def _create_intents(self, saved: dict):
        return [(key, entry) for key, entry in saved['intents'].items()
                if entry.get('kind') == 'create']

    def _matching_completed_create(self, saved: dict, title: str):
        matches = []
        for key, entry in self._create_intents(saved):
            receipt = entry.get('receipt')
            if (entry.get('state') == 'COMPLETED'
                    and entry.get('attributes', {}).get('title') == title
                    and isinstance(receipt, dict)
                    and receipt.get('title') == title):
                try:
                    project_id = uuid_value(receipt.get('project_id'))
                except Exception:
                    continue
                matches.append((entry.get('created_at', 0), key, project_id))
        return max(matches, default=None)

    def _create_key(self, saved: dict, title: str) -> str:
        digest = hashlib.sha256(title.encode('utf-8')).hexdigest()[:24]
        ordinal = sum(entry.get('attributes', {}).get('title') == title
                      for _, entry in self._create_intents(saved))
        return f'create:{digest}:{ordinal}'

    def _evaluate_rpc(self, page, command, timeout: float) -> dict:
        script = Path(__file__).with_name('flow_browser_rpc.js').read_text(encoding='utf-8')
        try:
            result = page.evaluate('mw:' + script, {
                'rpcid': command.rpcid,
                'freq': command.freq,
                'projectId': command.project_id,
                'match': command.match,
                'timeoutMs': max(1000, min(int(float(timeout) * 1000), 120000)),
            })
        except Exception:
            raise BrowserCommandError('RPC_READ_FAILED') from None
        if not isinstance(result, dict):
            raise BrowserCommandError('RPC_READ_FAILED')
        return result

    def _submit_session_project(self, command, key: str) -> tuple[str, str]:
        page = self._require_session()
        entry = self._store.begin(key, 'create', {'title': command.title})
        if entry['state'] == 'COMPLETED':
            receipt = entry.get('receipt') or {}
            return uuid_value(receipt.get('project_id')), receipt.get('title') or command.title
        try:
            response = self._evaluate_rpc(page, command, 60)
            if (response.get('status') != 200 or response.get('body_complete') is not True
                    or response.get('effect') != 'completed'
                    or not isinstance(response.get('data'), str)):
                raise BrowserCommandError('RECONCILIATION_REQUIRED')
            payload = fb.first_payload(response['data'], fb.RPC_CREATE_PROJECT)
            project_id, observed_title = fb.read_created_project(payload)
            project_id = uuid_value(project_id)
            title = observed_title or command.title
            if title != command.title:
                raise BrowserCommandError('PROJECT_RECEIPT_UNVERIFIED')
            # Receipt first, active-project pointer second. If pointer persistence
            # is interrupted, the completed receipt is enough to recover safely.
            self._store.complete(key, {'project_id': project_id, 'title': title})
            self._store.set_project(project_id)
            return project_id, title
        except Exception as error:
            try:
                current = self._store.lookup(key)
                if current and current.get('state') == 'SUBMITTING':
                    self._store.mark_unknown(key)
            except Exception:
                pass
            code = _public_error(error, 'RECONCILIATION_REQUIRED')
            if code == 'PROJECT_RECEIPT_UNVERIFIED':
                # The remote effect may have completed under a different receipt.
                code = 'RECONCILIATION_REQUIRED'
            raise BrowserCommandError(code) from None

    def ensure_session_project(self, title=None, force_new=False) -> dict:
        self._check_thread()
        self._require_session()
        saved = self._state()
        pending_create = [entry for _, entry in self._create_intents(saved)
                          if entry.get('state') in {'SUBMITTING', 'UNKNOWN'}]
        if pending_create:
            raise BrowserCommandError('RECONCILIATION_REQUIRED')

        if not force_new and saved.get('project_id'):
            project_id = uuid_value(saved['project_id'])
            opened = self.open_project(project_id)
            if opened.get('status') != 200:
                raise BrowserCommandError(opened.get('error') or 'PROJECT_OPEN_FAILED')
            return {'status': 200, 'data': {'projectId': project_id, 'reused': True},
                    'effect': 'completed'}

        command = validate_command('batch_rpc', {
            'rpcid': fb.RPC_CREATE_PROJECT,
            'freq': fb.create_project_request(title),
        })
        if not force_new:
            completed = self._matching_completed_create(saved, command.title)
            if completed is not None:
                _, _, project_id = completed
                # Recover the narrow crash window between receipt and pointer.
                self._store.set_project(project_id)
                opened = self.open_project(project_id)
                if opened.get('status') != 200:
                    raise BrowserCommandError(opened.get('error') or 'PROJECT_OPEN_FAILED')
                return {'status': 200, 'data': {'projectId': project_id, 'reused': True},
                        'effect': 'completed'}

        key = self._create_key(saved, command.title)
        project_id, resolved_title = self._submit_session_project(command, key)
        opened = self.open_project(project_id)
        if opened.get('status') != 200:
            raise BrowserCommandError(opened.get('error') or 'PROJECT_OPEN_FAILED')
        return {
            'status': 200,
            'data': {'projectId': project_id, 'title': resolved_title, 'reused': False},
            'effect': 'completed',
        }

    def _operation_project(self, operation_id: str) -> str:
        self._require_lease()
        status, project_id = self._store.operation_binding(uuid_value(operation_id))
        if status == 'conflict':
            raise BrowserCommandError('OPERATION_BINDING_CONFLICT')
        if project_id is None:
            raise BrowserCommandError('OPERATION_BINDING_REQUIRED')
        project_id = uuid_value(project_id)
        if status == 'receipt':
            # Local-only promotion after a unique COMPLETED receipt proves the
            # binding. Re-check the lease before mutating the durable journal.
            self._require_lease()
            self._store.remember_operation(operation_id, project_id)
        return project_id

    def _read_project_for(self, command) -> str:
        if command.rpcid == fb.RPC_PROJECT_MEDIA:
            return uuid_value(command.project_id)
        if command.rpcid == fb.RPC_OPERATION:
            return self._operation_project(command.operation_id)
        saved = self._state()
        project_id = saved.get('project_id')
        if not project_id:
            raise BrowserCommandError('PROJECT_REQUIRED')
        return uuid_value(project_id)

    def _execute_read(self, command, timeout=300) -> dict:
        if command.rpcid not in {fb.RPC_PROJECT_MEDIA, fb.RPC_MEDIA, fb.RPC_OPERATION}:
            return {'status': 501, 'error': 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
                    'effect': 'not_submitted'}
        project_id = self._read_project_for(command)
        opened = self.open_project(project_id)
        if opened.get('status') != 200:
            return opened
        page = self._require_session()
        bound_command = (replace(command, project_id=project_id)
                         if command.rpcid == fb.RPC_OPERATION else command)
        response = self._evaluate_rpc(page, bound_command, timeout)
        if response.get('status') != 200 or response.get('body_complete') is not True:
            return {
                'status': int(response.get('status') or 502),
                'error': _fixed_response_error(response.get('error')),
                'effect': response.get('effect') if response.get('effect') in {
                    'completed', 'unknown', 'not_submitted'} else 'unknown',
            }
        data = response.get('data')
        if not isinstance(data, str):
            return {'status': 502, 'error': 'RPC_READ_FAILED', 'effect': 'unknown'}
        if command.match is None:
            try:
                payload = fb.first_payload(data, command.rpcid)
                if command.rpcid == fb.RPC_OPERATION:
                    operation = fb.read_operation(payload)
                    if (operation.operation_id != command.operation_id
                            or operation.project_id != project_id):
                        raise BrowserCommandError('OPERATION_RECEIPT_UNVERIFIED')
            except BrowserCommandError as error:
                return {'status': 502, 'error': _public_error(
                    error, 'OPERATION_RECEIPT_UNVERIFIED'), 'effect': 'unknown'}
            except Exception:
                return {'status': 502, 'error': 'RPC_READ_FAILED', 'effect': 'unknown'}
        return {**response, 'effect': 'completed'}

    def _execute_upload(self, command) -> dict:
        self._require_session()
        return execute_upload(
            self._provider.session, command, self._store,
            require_lease=self._require_lease, prepare=self._open_project_page,
        )

    def execute(self, command, timeout=300) -> dict:
        self._check_thread()
        capability = getattr(command, 'capability', None)
        try:
            if capability == 'read':
                return self._execute_read(command, timeout)
            if capability == 'upload':
                return self._execute_upload(command)
            # Session-project creation uses ensure_session_project so a durable
            # intent key exists before the effect. Raw create and paid RPCs stay off.
            return {'status': 501, 'error': 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
                    'effect': 'not_submitted'}
        except Exception as error:
            return {
                'status': 409,
                'error': _public_error(error, 'UPLOAD_FAILED' if capability == 'upload'
                                       else 'RPC_READ_FAILED'),
                'effect': 'not_submitted',
            }

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
