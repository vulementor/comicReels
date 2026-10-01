"""Async application boundary with one synchronous browser owner and finite admission."""
from __future__ import annotations

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent.services.flow_browser_contract import (
    BrowserCommandError,
    uuid_value,
    validate_command,
)
from agent.services.flow_browser_session import FlowProfileConfig


class BrowserFlowBackend:
    kind = 'browser'
    paid_dispatch_enabled = False

    def __init__(self, *, config=None, state_path=None, driver_factory=None):
        self.config = config or FlowProfileConfig.load()
        identity = str(self.config.user_data_dir.resolve()).casefold()
        digest = hashlib.sha256(identity.encode()).hexdigest()
        self.session_owner_key = f'browser:{self.config.profile_logical_name}:{digest}'
        self._state_path = Path(state_path) if state_path else self.config.source_path.parent / 'flow-browser-state' / f'{digest}.json'
        self._factory = driver_factory
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='flow-browser-owner')
        self._pending = set()
        self._pending_lock = threading.Lock()
        self._driver = None
        self._start_future = None
        self._close_future = None
        self._ready = self._closing = self._closed = False

    @property
    def ready(self):
        return self._ready and not self._closing and not self._closed

    def _submit(self, function, *args, closing=False):
        if self._closed or (self._closing and not closing):
            raise BrowserCommandError('BACKEND_CLOSED')
        with self._pending_lock:
            if not closing and len(self._pending) >= 8:
                raise BrowserCommandError('BROWSER_QUEUE_FULL')
            future = self._pool.submit(function, *args)
            self._pending.add(future)
        def completed(value):
            with self._pending_lock:
                self._pending.discard(value)
        future.add_done_callback(completed)
        return asyncio.wrap_future(future)

    async def start(self):
        if self._start_future is None:
            self._start_future = self._submit(self._start)
        await asyncio.shield(self._start_future)

    def _start(self):
        if self._factory is None:
            from agent.services.flow_browser_driver import FlowBrowserDriver
            self._factory = FlowBrowserDriver
        self._driver = self._factory(self.config, self._state_path, self.session_owner_key)
        self._driver.start()
        self._ready = bool(self._driver.health()['ready'])

    def _run(self, method, *args):
        if not self._driver or not self._driver.health()['ready']:
            self._ready = False
            return {'status': 503, 'error': 'BROWSER_NOT_READY', 'effect': 'not_submitted'}
        self._ready = True
        return getattr(self._driver, method)(*args)

    async def check_readiness(self):
        # A cached False is not a terminal lifecycle state. Observe the SAME
        # driver on its owner thread; never restart, navigate or switch backend.
        if self._closing or self._closed:
            return {'backend_kind': self.kind, 'ready': False, 'session_ready': False,
                    'state': 'closed' if self._closed else 'closing',
                    'error': 'BACKEND_CLOSED', 'paid_dispatch_enabled': False}
        if (self._driver is None or self._start_future is None
                or not self._start_future.done()):
            return {'backend_kind': self.kind, 'ready': False, 'session_ready': False,
                    'state': 'new' if self._start_future is None else 'starting',
                    'error': 'BROWSER_NOT_READY', 'paid_dispatch_enabled': False}
        try:
            result = await asyncio.shield(self._submit(self._driver.health))
            if not isinstance(result, dict):
                raise BrowserCommandError('BROWSER_NOT_READY')
        except Exception:
            self._ready = False
            raise
        self._ready = result.get('ready') is True and not self._closing and not self._closed
        return {**result, 'backend_kind': self.kind, 'ready': self.ready,
                'paid_dispatch_enabled': False}

    async def execute(self, method, params, timeout=300):
        try:
            command = validate_command(method, params)
            if not self.ready:
                raise BrowserCommandError('BROWSER_NOT_READY')
            future = self._submit(self._run, 'execute', command, timeout)
        except BrowserCommandError as exc:
            return {'status': 409, 'error': str(exc), 'effect': 'not_submitted'}
        # Canceling the HTTP await must not cancel a queued/running browser effect.
        return await asyncio.shield(future)

    async def open_project(self, project_id):
        try:
            uuid_value(project_id)
            if not self.ready:
                raise BrowserCommandError('BROWSER_NOT_READY')
            return await asyncio.shield(self._submit(self._run, 'open_project', project_id))
        except BrowserCommandError as exc:
            return {'status': 409, 'error': str(exc), 'effect': 'not_submitted'}

    async def ensure_session_project(self, *, title=None, force_new=False):
        if not self.ready:
            raise BrowserCommandError('BROWSER_NOT_READY')
        return await asyncio.shield(self._submit(self._run, 'ensure_session_project', title, force_new))

    def _close(self):
        try:
            if self._driver:
                self._driver.close()
        except Exception:  # noqa: BLE001 - preserve owner thread and lease for a close retry.
            raise BrowserCommandError('CLOSE_UNCERTAIN') from None
        self._ready = False
        self._closed = True
        self._pool.shutdown(wait=False)

    async def close(self):
        self._closing = True  # stop admission before queuing close behind all actual operations
        self._ready = False
        if self._closed:
            return
        if self._close_future is None:
            self._close_future = self._submit(self._close, closing=True)
        try:
            await asyncio.shield(self._close_future)
        except asyncio.CancelledError:
            raise  # close continues on the owner; later callers await the same result
        except Exception:
            self._close_future = None
            raise
