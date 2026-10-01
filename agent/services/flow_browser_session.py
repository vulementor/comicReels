"""Browser-only persistent Flow session foundation.

Run on one owning thread: both Camoufox and the pinned KBS semantic API are synchronous.
Authentication requires an explicit, live-evidence-backed probe; absent evidence is UNKNOWN.
This module never submits generation, creates projects, or exports authentication state.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import secrets
import socket
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class FlowBrowserError(RuntimeError):
    """Public errors contain a fixed code only, never browser exception strings."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FlowProfileConfig:
    profile_logical_name: str
    user_data_dir: Path = field(repr=False)
    source_path: Path = field(repr=False)
    directory_identity: tuple[int, int] = field(repr=False)

    @classmethod
    def load(cls, source: Path | None = None) -> FlowProfileConfig:
        if source is None:
            configured = os.environ.get('COMICREELS_FLOW_PROFILE_CONFIG')
            if configured:
                source = Path(configured)
            elif os.environ.get('LOCALAPPDATA'):
                source = Path(os.environ['LOCALAPPDATA']) / 'ComicReels' / 'flow-browser.local.json'
            else:
                raise FlowBrowserError('PROFILE_CONFIG_REQUIRED')
        try:
            source = Path(source).resolve(strict=True)
            data = json.loads(source.read_text(encoding='utf-8'))
            name = data['profile_logical_name']
            if (data['schema_version'] != 1 or data['browser_kind'] != 'camoufox'
                    or not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', name)):
                raise ValueError
            path_value = data['user_data_dir']
            if not isinstance(path_value, str) or not path_value.strip():
                raise ValueError
            profile = Path(path_value)
            if not profile.is_absolute():
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise FlowBrowserError('PROFILE_CONFIG_INVALID') from None
        try:
            profile = profile.resolve(strict=True)
            stat = profile.stat()
            if not profile.is_dir():
                raise OSError
        except OSError:
            raise FlowBrowserError('PROFILE_NOT_FOUND') from None
        return cls(name, profile, source, (stat.st_dev, stat.st_ino))

    def verify_directory(self):
        try:
            stat = self.user_data_dir.stat()
            if not self.user_data_dir.is_dir() or (stat.st_dev, stat.st_ino) != self.directory_identity:
                raise OSError
        except OSError:
            raise FlowBrowserError('PROFILE_CHANGED') from None


@dataclass(frozen=True)
class _ProcessObservation:
    state: str
    started_at: str | None = None


@dataclass(frozen=True)
class _LeaseMarkerSnapshot:
    raw: bytes
    file_identity: tuple[int, int, int, int]
    schema_version: int
    host: str
    pid: int
    owner_token: str
    pid_started_at: str | None


_OWNER_TOKEN = re.compile(r'^[0-9a-f]{48}$')
_PROCESS_STARTED_AT = re.compile(r'^(?:windows-filetime|linux-proc-start):[0-9]+$')
_MAX_LEASE_MARKER_BYTES = 4096


def _observe_windows_process(pid: int) -> _ProcessObservation:
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [('low', wintypes.DWORD), ('high', wintypes.DWORD)]

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_exit_code.restype = wintypes.BOOL
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                          ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    get_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(0x1000, False, pid)
    if not handle:
        return _ProcessObservation('dead' if ctypes.get_last_error() == 87 else 'unknown')
    try:
        exit_code = wintypes.DWORD()
        created = FILETIME()
        exited = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return _ProcessObservation('unknown')
        if not get_times(handle, ctypes.byref(created), ctypes.byref(exited),
                         ctypes.byref(kernel), ctypes.byref(user)):
            return _ProcessObservation('unknown')
        started = (int(created.high) << 32) | int(created.low)
        state = 'alive' if exit_code.value == 259 else 'dead'
        return _ProcessObservation(state, f'windows-filetime:{started}')
    finally:
        close_handle(handle)


def _observe_process(pid: int) -> _ProcessObservation:
    if type(pid) is not int or pid <= 0:
        return _ProcessObservation('unknown')
    if os.name == 'nt':
        return _observe_windows_process(pid)
    proc_stat = Path('/proc') / str(pid) / 'stat'
    try:
        raw = proc_stat.read_text(encoding='utf-8')
    except FileNotFoundError:
        return _ProcessObservation('dead')
    except OSError:
        return _ProcessObservation('unknown')
    try:
        tail = raw[raw.rfind(')') + 2:].split()
        started = int(tail[19])
        if started < 0:
            raise ValueError
    except (ValueError, IndexError):
        return _ProcessObservation('unknown')
    return _ProcessObservation('alive', f'linux-proc-start:{started}')


def _native_profile_available(config: FlowProfileConfig) -> bool:
    """Read-only proof that Firefox/Camoufox is not holding its native profile lock."""
    lock = config.user_data_dir / 'parent.lock'
    if not lock.exists():
        return True
    if os.name != 'nt':
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                            wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(str(lock), 0x00010000, 0x00000001 | 0x00000002 | 0x00000004,
                         None, 3, 0x00000080, None)
    invalid = ctypes.c_void_p(-1).value
    if handle == invalid:
        return ctypes.get_last_error() == 2
    close_handle(handle)
    return True


def _marker_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_lease_marker(path: Path) -> _LeaseMarkerSnapshot:
    try:
        identity = _marker_identity(path)
        raw = path.read_bytes()
        if not raw or len(raw) > _MAX_LEASE_MARKER_BYTES:
            raise ValueError
        data = json.loads(raw.decode('utf-8'))
        if type(data) is not dict:
            raise ValueError
        schema = data.get('schema_version', 1)
        legacy = {'host', 'pid', 'owner_token'}
        current = legacy | {'schema_version', 'pid_started_at'}
        if schema == 1:
            if set(data) != legacy:
                raise ValueError
            started_at = None
        elif schema == 2:
            if set(data) != current:
                raise ValueError
            started_at = data.get('pid_started_at')
            if not isinstance(started_at, str) or not _PROCESS_STARTED_AT.fullmatch(started_at):
                raise ValueError
        else:
            raise ValueError
        host = data.get('host')
        pid = data.get('pid')
        token = data.get('owner_token')
        if (not isinstance(host, str) or not host or len(host) > 255
                or type(pid) is not int or not 0 < pid <= 0xFFFFFFFF
                or not isinstance(token, str) or not _OWNER_TOKEN.fullmatch(token)):
            raise ValueError
        return _LeaseMarkerSnapshot(
            raw=raw, file_identity=identity, schema_version=schema,
            host=host, pid=pid, owner_token=token, pid_started_at=started_at,
        )
    except FlowBrowserError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED') from None


class FlowProfileLease:
    """Exclusive OS lock plus explicit, auditable stale-provider reconciliation.

    Normal acquire remains fail-closed whenever a provider marker already
    exists. reconcile_stale_and_acquire is the only recovery path and may
    archive a marker only while this process owns the OS guard, the exact bound
    profile identity is unchanged, the recorded owner is confirmed dead, and
    the native browser profile is not busy.
    """

    def __init__(self, config: FlowProfileConfig):
        self.config = config
        self._guard = None
        self._token = None
        self._marker = config.user_data_dir / '.flow-browser-lease.json'
        self._last_reconciliation_receipt = None

    @property
    def held(self) -> bool:
        return self._guard is not None

    @property
    def last_reconciliation_receipt(self) -> Path | None:
        return self._last_reconciliation_receipt

    def _acquire_guard(self) -> None:
        guard = None
        try:
            guard = (self.config.user_data_dir / '.gptfp-runtime.guard').open('a+b')
            if guard.seek(0, 2) == 0:
                guard.write(b'0')
                guard.flush()
            guard.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if guard is not None:
                guard.close()
            raise FlowBrowserError('PROFILE_BUSY') from None
        self._guard = guard

    def _write_current_marker(self) -> None:
        observed = _observe_process(os.getpid())
        if observed.state != 'alive' or not observed.started_at:
            raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
        token = secrets.token_hex(24)
        payload = {
            'schema_version': 2,
            'host': socket.gethostname(),
            'pid': os.getpid(),
            'pid_started_at': observed.started_at,
            'owner_token': token,
        }
        try:
            with self._marker.open('x', encoding='utf-8') as marker:
                json.dump(payload, marker, separators=(',', ':'))
                marker.flush()
                os.fsync(marker.fileno())
        except FileExistsError:
            raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED') from None
        self._token = token

    def _archive_stale_marker(self, snapshot: _LeaseMarkerSnapshot) -> Path:
        try:
            if _marker_identity(self._marker) != snapshot.file_identity:
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            if self._marker.read_bytes() != snapshot.raw:
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            digest = hashlib.sha256(snapshot.raw).hexdigest()[:16]
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            receipt = self.config.user_data_dir / (
                f'.flow-browser-lease.reconciled-{snapshot.pid}-{stamp}-{digest}.json')
            if receipt.exists():
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            os.rename(self._marker, receipt)
            receipt_identity = _marker_identity(receipt)
            same_file = receipt_identity[:2] == snapshot.file_identity[:2]
            same_bytes = receipt.read_bytes() == snapshot.raw
            if not same_file or not same_bytes:
                if not self._marker.exists():
                    try:
                        os.rename(receipt, self._marker)
                    except OSError:
                        pass
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            return receipt
        except FlowBrowserError:
            raise
        except OSError:
            raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED') from None

    def acquire(self):
        if self.held:
            raise FlowBrowserError('PROFILE_BUSY')
        self.config.verify_directory()
        self._acquire_guard()
        try:
            self.config.verify_directory()
            if (self.config.user_data_dir / '.gptfp-runtime.lock').exists() or self._marker.exists():
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            self._write_current_marker()
        except BaseException:
            self.release()
            raise
        return self

    def reconcile_stale_and_acquire(self):
        """Recover one confirmed-dead provider marker without force takeover."""
        if self.held:
            raise FlowBrowserError('PROFILE_BUSY')
        self.config.verify_directory()
        self._acquire_guard()
        try:
            self.config.verify_directory()
            if (self.config.user_data_dir / '.gptfp-runtime.lock').exists():
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            if not self._marker.exists():
                self._write_current_marker()
                return self

            snapshot = _read_lease_marker(self._marker)
            if snapshot.host.casefold() != socket.gethostname().casefold():
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')

            owner = _observe_process(snapshot.pid)
            if owner.state == 'unknown':
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            if snapshot.schema_version == 1:
                if owner.state != 'dead':
                    raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            else:
                if owner.state == 'alive':
                    raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
                if owner.state != 'dead':
                    raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')

            if not _native_profile_available(self.config):
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            self.config.verify_directory()

            receipt = self._archive_stale_marker(snapshot)
            self._last_reconciliation_receipt = receipt

            if not _native_profile_available(self.config):
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            self.config.verify_directory()
            self._write_current_marker()
        except BaseException:
            self.release()
            raise
        return self

    def release(self):
        if self._guard is not None:
            if self._token is not None:
                try:
                    data = json.loads(self._marker.read_text(encoding='utf-8'))
                    if (data.get('owner_token') != self._token
                            or data.get('pid') != os.getpid()
                            or data.get('schema_version') != 2):
                        raise ValueError
                    self._marker.unlink()
                except (OSError, ValueError, TypeError):
                    raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED') from None
                self._token = None
            self._guard.close()
            self._guard = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_):
        self.release()


@dataclass(frozen=True)
class AuthObservation:
    state: str = 'unknown'
    # Account identity evidence remains in memory and is omitted from public health.
    identity: str | None = field(default=None, repr=False)


def _camoufox_context(**kwargs):
    from camoufox.sync_api import Camoufox
    return Camoufox(**kwargs)


class FlowBrowserSessionProvider:
    """Own exactly one explicitly bound persistent context under an exclusive lease.

    auth_probe is a Flow adapter seam, not a model callback. Its implementation must use
    observed read-only account UI evidence. No probe is installed by default until that live
    surface has been verified. Browser-open, hostname and nonempty snapshots are not auth.
    """

    def __init__(self, config: FlowProfileConfig, *, context_factory: Callable | None = None,
                 auth_probe: Callable | None = None, visible: bool = True):
        self.config = config
        self._visible = visible
        self._factory = context_factory or _camoufox_context
        self._auth_probe = auth_probe or (lambda _: AuthObservation())
        self._lease = FlowProfileLease(config)
        self._manager = None
        self._context = None
        self.session = None
        self._thread = None
        self._identity = None
        self._identity_changed = False
        self._state = 'closed'
        self._auth = 'unknown'
        self._count = 0
        self._error = None
        self._observed_at = None

    def _check_thread(self):
        if self._thread is not None and self._thread != threading.get_ident():
            raise FlowBrowserError('WRONG_OWNER_THREAD')

    def _reconcile_windows_parent_lock(self):
        """Quarantine a stale Firefox parent.lock only while our OS lease is held.

        A live Windows Firefox/Camoufox process normally keeps this file open
        without delete sharing, so rename fails closed.  The canonical profile
        is never edited beyond moving the zero-byte stale lock to an auditable
        reconciled name.
        """
        if os.name!='nt':
            return
        lock=self.config.user_data_dir/'parent.lock'
        if not lock.exists():
            return
        target=self.config.user_data_dir/(
            f'.parent.lock.reconciled-{os.getpid()}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}')
        try:
            lock.rename(target)
        except OSError:
            raise FlowBrowserError('PROFILE_NATIVE_BUSY') from None

    def open(self):
        self._check_thread()
        if self._state == 'close_uncertain':
            raise FlowBrowserError('CLOSE_UNCERTAIN')
        if self._lease.held:
            raise FlowBrowserError('ALREADY_OPEN')
        self._lease.acquire()
        self._thread = threading.get_ident()
        self._auth, self._count, self._error, self._observed_at = 'unknown', 0, None, None
        try:
            self._reconcile_windows_parent_lock()
            from kabin_browser_semantic import BrowserSession
            self._manager = self._factory(persistent_context=True,
                user_data_dir=str(self.config.user_data_dir), headless=not self._visible, locale='vi-VN',
                main_world_eval=True)
            self._context = self._manager.__enter__()
            page = self._context.pages[0] if self._context.pages else self._context.new_page()
            if inspect.iscoroutinefunction(page.goto):
                raise FlowBrowserError('SYNC_BROWSER_REQUIRED')
            page.goto('https://flow.google.com/', wait_until='domcontentloaded', timeout=60_000)
            self.session = BrowserSession.from_page(page)
            self._state = 'open'
            return self
        except BaseException:  # noqa: BLE001 - cleanup must also run on interruption.
            self.close()  # If cleanup fails, retain the lease and report CLOSE_UNCERTAIN.
            raise FlowBrowserError('OPEN_FAILED') from None

    def capture_health(self) -> dict:
        self._check_thread()
        self._auth, self._count, self._error = 'unknown', 0, None
        self._observed_at = datetime.now(timezone.utc).isoformat()
        if self._identity_changed:
            self._error = 'IDENTITY_CHANGED'
            return self._report(fresh=True)
        if not self._usable_page():
            self._error = 'FLOW_PAGE_UNAVAILABLE'
            return self._report(fresh=True)
        try:
            from kabin_browser_semantic import capture_semantic_snapshot
            page = self.session.page
            target = page if callable(getattr(page, 'aria_snapshot', None)) else page.locator('body')
            if inspect.iscoroutinefunction(getattr(target, 'aria_snapshot', None)):
                raise FlowBrowserError('SYNC_BROWSER_REQUIRED')
            surface = capture_semantic_snapshot(target, depth=4, boxes=False, include_raw=False)
            if not surface['supported'] or surface['capture_error'] or not surface['node_count']:
                self._error = 'SEMANTIC_CAPTURE_UNAVAILABLE'
                return self._report(fresh=True)
            self._count = surface['node_count']
            auth = self._auth_probe(page)
            if inspect.isawaitable(auth):
                if inspect.iscoroutine(auth):
                    auth.close()
                raise FlowBrowserError('SYNC_AUTH_PROBE_REQUIRED')
            if not isinstance(auth, AuthObservation) or auth.state not in {'unknown', 'signed_out', 'authenticated'}:
                raise ValueError
            if auth.state == 'authenticated':
                if not isinstance(auth.identity, str) or not auth.identity.strip():
                    self._error = 'IDENTITY_UNVERIFIED'
                elif self._identity is not None and self._identity != auth.identity:
                    self._error = 'IDENTITY_CHANGED'
                    self._identity_changed = True
                else:
                    self._identity = auth.identity
                    self._auth = 'authenticated'
            else:
                self._auth = auth.state
        except Exception:  # noqa: BLE001 - browser errors must not leak page/auth details.
            self._auth, self._count, self._error = 'unknown', 0, 'OBSERVATION_FAILED'
        return self._report(fresh=True)

    def _usable_page(self) -> bool:
        try:
            return bool(self._state == 'open' and self._lease.held and self.session
                        and not self.session.page.is_closed()
                        and urlsplit(self.session.page.url).scheme == 'https'
                        and urlsplit(self.session.page.url).hostname == 'flow.google.com')
        except Exception:  # noqa: BLE001 - disconnected browser handles fail closed.
            return False

    def health(self) -> dict:
        """Passive diagnostics never promote cached evidence into current readiness."""
        return self._report(fresh=False)

    def _report(self, *, fresh: bool) -> dict:
        self._check_thread()
        usable = self._usable_page()
        return {'backend': 'browser_shadow', 'profile': self.config.profile_logical_name,
                    'state': self._state, 'lease_held': self._lease.held,
                    'authentication': self._auth if usable and fresh else 'unknown',
                    'last_observation_authentication': self._auth,
                    'semantic_node_count': self._count if usable else 0,
                    'observed_at': self._observed_at, 'error': self._error,
                    'ready': bool(fresh and usable and self._auth == 'authenticated' and self._count and not self._error)}

    def close(self):
        self._check_thread()
        if self._manager is not None:
            try:
                self._manager.__exit__(None, None, None)
            except BaseException:  # noqa: BLE001 - an interrupted close is also uncertain.
                self._state, self._error, self._auth = 'close_uncertain', 'CLOSE_UNCERTAIN', 'unknown'
                raise FlowBrowserError('CLOSE_UNCERTAIN') from None
        self._manager = self._context = self.session = None
        try:
            self._lease.release()
        except FlowBrowserError:
            self._state, self._error, self._auth = 'close_uncertain', 'CLOSE_UNCERTAIN', 'unknown'
            raise FlowBrowserError('CLOSE_UNCERTAIN') from None
        self._state, self._auth, self._count = 'closed', 'unknown', 0
        self._thread = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.close()
