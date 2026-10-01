"""FBR-5-code-2a requirements; execution deferred until the full coding pass.

Exercise the real FlowClient/get_flow_client wiring and selection resolver.
Only browser construction is replaced; no profile, browser, network or paid call.
"""
import builtins
import sys
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

import pytest

from agent.services import flow_client as implementation
from agent.services.flow_backend import ExtensionFlowBackend
from agent.services.flow_backend_selection import (
    BACKEND_ENV, BROWSER_DEFAULT_ACCEPTANCE_ENV,
)

PRIVATE = 'private profile path / token=do-not-expose'


class BrowserStub:
    kind = 'browser'
    paid_dispatch_enabled = False
    session_owner_key = 'test-browser'

    def __init__(self):
        self.ready = False
        self.starts = 0
        self.closes = 0

    async def start(self):
        self.starts += 1
        self.ready = True

    async def close(self):
        self.closes += 1
        self.ready = False


@pytest.fixture(autouse=True)
def isolated_singleton(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    monkeypatch.delenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, raising=False)
    monkeypatch.setattr(implementation, '_client', None)
    monkeypatch.setattr(implementation, '_client_selection', None, raising=False)
    monkeypatch.setattr(implementation, '_client_initialization_error', None, raising=False)


@pytest.fixture
def browser_factory(monkeypatch):
    instances = []
    module = ModuleType('agent.services.flow_browser_backend')

    def construct():
        instance = BrowserStub()
        instances.append(instance)
        return instance

    module.BrowserFlowBackend = construct
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return instances, module


@pytest.mark.parametrize('explicit,marker,source', [
    (None, None, 'extension_default'),
    (None, '0', 'extension_default'),
    ('extension', '1', 'explicit'),
    ('extension', 'broken-private-marker', 'explicit'),
])
def test_extension_selection_never_imports_browser(monkeypatch, explicit, marker, source):
    if explicit is not None:
        monkeypatch.setenv(BACKEND_ENV, explicit)
    if marker is not None:
        monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, marker)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == 'agent.services.flow_browser_backend':
            raise AssertionError('extension selection must not import browser dependencies')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    client = implementation.get_flow_client()
    assert isinstance(client.backend, ExtensionFlowBackend)
    assert implementation._client_selection.kind == 'extension'
    assert implementation._client_selection.source == source
    assert implementation.get_flow_client() is client


@pytest.mark.parametrize('explicit,marker,source', [
    ('browser', None, 'explicit'),
    ('browser', 'bad-marker-ignored', 'explicit'),
    (None, '1', 'accepted_browser_default'),
])
def test_browser_is_constructed_once_without_launch(monkeypatch, browser_factory,
                                                     explicit, marker, source):
    if explicit is not None:
        monkeypatch.setenv(BACKEND_ENV, explicit)
    if marker is not None:
        monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, marker)
    instances, _ = browser_factory
    client = implementation.get_flow_client()
    assert implementation.get_flow_client() is client
    assert len(instances) == 1 and client.backend is instances[0]
    assert instances[0].starts == 0 and client.connected is False
    assert client.paid_dispatch_enabled is False
    assert implementation._client_selection.source == source


def test_successful_selection_is_not_recomputed_from_changed_environment(monkeypatch,
                                                                         browser_factory):
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    instances, _ = browser_factory
    client = implementation.get_flow_client()
    selection = implementation._client_selection
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, PRIVATE)
    assert implementation.get_flow_client() is client
    assert implementation._client_selection is selection
    assert client.backend_kind == 'browser' and len(instances) == 1


@pytest.mark.parametrize('explicit,marker,code', [
    ('invalid-private-backend', None, 'FLOW_BACKEND_SELECTION_INVALID'),
    (None, 'invalid-private-marker', 'FLOW_BROWSER_DEFAULT_ACCEPTANCE_INVALID'),
])
def test_bad_configuration_fails_before_constructing_either_backend(monkeypatch,
                                                                    explicit, marker, code):
    if explicit is not None:
        monkeypatch.setenv(BACKEND_ENV, explicit)
    if marker is not None:
        monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, marker)

    def forbidden(*args, **kwargs):
        raise AssertionError('invalid selection must not construct a client')

    monkeypatch.setattr(implementation, 'FlowClient', forbidden)
    with pytest.raises(ValueError, match='^' + code + '$'):
        implementation.get_flow_client()
    assert implementation._client is None
    assert implementation._client_selection is None


def test_browser_constructor_failure_is_sticky_without_retry_or_fallback(monkeypatch,
                                                                          browser_factory):
    instances, module = browser_factory
    attempted = []

    def fail():
        attempted.append('browser')
        raise RuntimeError(PRIVATE)

    module.BrowserFlowBackend = fail
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    with pytest.raises(RuntimeError, match='^FLOW_BACKEND_INITIALIZATION_FAILED$') as first:
        implementation.get_flow_client()
    assert PRIVATE not in str(first.value)
    assert implementation._client is None
    assert implementation._client_selection.kind == 'browser'
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    with pytest.raises(RuntimeError, match='^FLOW_BACKEND_INITIALIZATION_FAILED$'):
        implementation.get_flow_client()
    assert attempted == ['browser'] and instances == []
    assert implementation._client is None


@pytest.mark.asyncio
async def test_async_browser_start_failure_does_not_replace_selected_client(monkeypatch,
                                                                           browser_factory):
    instances, _ = browser_factory
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    client = implementation.get_flow_client()

    async def fail_start():
        raise RuntimeError('TEST_BROWSER_START_FAILED')

    instances[0].start = fail_start
    with pytest.raises(RuntimeError, match='^TEST_BROWSER_START_FAILED$'):
        await client.start_backend()
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    assert implementation.get_flow_client() is client
    assert client.backend is instances[0] and len(instances) == 1
    assert client.paid_dispatch_enabled is False


@pytest.mark.asyncio
async def test_close_does_not_implicitly_reselect_but_fresh_process_can_rollback(monkeypatch,
                                                                               browser_factory):
    instances, _ = browser_factory
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    client = implementation.get_flow_client()
    await client.close_backend()
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    assert implementation.get_flow_client() is client
    assert len(instances) == 1 and instances[0].closes == 1
    # Simulate fresh process-only singleton state, not a production reset API.
    monkeypatch.setattr(implementation, '_client', None)
    monkeypatch.setattr(implementation, '_client_selection', None)
    monkeypatch.setattr(implementation, '_client_initialization_error', None)
    replacement = implementation.get_flow_client()
    assert replacement is not client
    assert isinstance(replacement.backend, ExtensionFlowBackend)
    assert len(instances) == 1


def test_concurrent_getters_construct_only_one_browser(monkeypatch, browser_factory):
    instances, _ = browser_factory
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    with ThreadPoolExecutor(max_workers=4) as pool:
        clients = list(pool.map(lambda _: implementation.get_flow_client(), range(12)))
    assert all(client is clients[0] for client in clients)
    assert len(instances) == 1 and instances[0].starts == 0


def test_direct_injected_client_does_not_consult_environment(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, PRIVATE)
    backend = BrowserStub()
    client = implementation.FlowClient(backend=backend)
    assert client.backend is backend and client.paid_dispatch_enabled is False
    assert implementation._client is None and implementation._client_selection is None
