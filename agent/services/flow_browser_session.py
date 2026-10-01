"""Browser-only persistent Flow session foundation.

Run on one owning thread: both Camoufox and the pinned KBS semantic API are synchronous.
Authentication requires an explicit, live-evidence-backed probe; absent evidence is UNKNOWN.
This module never submits generation, creates projects, or exports authentication state.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import secrets
import socket
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


class FlowProfileLease:
    """Exclusive OS lock compatible with the workspace's one-time login helper.

    The guard is permanent; never unlink it. A legacy helper marker requires explicit
    reconciliation, even when it appears stale. Only this lease object's handle is released.
    """

    def __init__(self, config: FlowProfileConfig):
        self.config = config
        self._guard = None
        self._token = None
        self._marker = config.user_data_dir / '.flow-browser-lease.json'

    @property
    def held(self) -> bool:
        return self._guard is not None

    def acquire(self):
        if self.held:
            raise FlowBrowserError('PROFILE_BUSY')
        self.config.verify_directory()
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
        try:
            self.config.verify_directory()
            if (self.config.user_data_dir / '.gptfp-runtime.lock').exists() or self._marker.exists():
                raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED')
            token = secrets.token_hex(24)
            with self._marker.open('x', encoding='utf-8') as marker:
                json.dump({'host': socket.gethostname(), 'pid': os.getpid(), 'owner_token': token}, marker)
                marker.flush()
                os.fsync(marker.fileno())
            self._token = token
        except BaseException:
            self.release()
            raise
        return self

    def release(self):
        if self._guard is not None:
            if self._token is not None:
                try:
                    data = json.loads(self._marker.read_text(encoding='utf-8'))
                    if data.get('owner_token') != self._token or data.get('pid') != os.getpid():
                        raise ValueError
                    self._marker.unlink()
                except (OSError, ValueError, TypeError):
                    raise FlowBrowserError('PROFILE_RECONCILE_REQUIRED') from None
                self._token = None
            # Closing this handle releases the kernel lock, including on process exit.
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
