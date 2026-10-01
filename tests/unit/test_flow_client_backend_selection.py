"""Browser-only singleton selection requirements.

Authored during the development-first coding phase; execution is deferred until
the dedicated validation phase. No browser/profile/network/paid call is made here.
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from types import ModuleType

import pytest

from agent.services import flow_client as implementation
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


@pytest.mark.parametrize('explicit,legacy_marker', [
    (None, None),
    (None, '0'),
    (None, '1'),
    (None, 'legacy-obsolete'),
    ('browser', None),
    ('browser', '0'),
])
def test_get_flow_client_always_constructs_one_browser_without_launch(
        monkeypatch, browser_factory, explicit, legacy_marker):
    if explicit is not None:
        monkeypatch.setenv(BACKEND_ENV, explicit)
    if legacy_marker is not None:
        monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, legacy_marker)

    instances, _ = browser_factory
    client = implementation.get_flow_client()

    assert implementation.get_flow_client() is client
    assert len(instances) == 1 and client.backend is instances[0]
    assert instances[0].starts == 0 and client.connected is False
    assert client.backend_kind == 'browser'
    assert client.paid_dispatch_enabled is False
    assert implementation._client_selection.kind == 'browser'
    assert implementation._client_selection.source == 'browser_only'


def test_extension_configuration_is_rejected_before_browser_construction(
        monkeypatch, browser_factory):
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    instances, _ = browser_factory

    with pytest.raises(ValueError, match='^FLOW_EXTENSION_BACKEND_REMOVED$'):
        implementation.get_flow_client()

    assert instances == []
    assert implementation._client is None
    assert implementation._client_selection is None


def test_invalid_configuration_is_rejected_before_browser_construction(
        monkeypatch, browser_factory):
    monkeypatch.setenv(BACKEND_ENV, PRIVATE)
    instances, _ = browser_factory

    with pytest.raises(ValueError, match='^FLOW_BACKEND_SELECTION_INVALID$') as error:
        implementation.get_flow_client()

    assert PRIVATE not in str(error.value)
    assert instances == []
    assert implementation._client is None
    assert implementation._client_selection is None


def test_successful_browser_selection_is_not_recomputed_from_environment(
        monkeypatch, browser_factory):
    instances, _ = browser_factory
    client = implementation.get_flow_client()
    selection = implementation._client_selection

    monkeypatch.setenv(BACKEND_ENV, 'extension')
    monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, PRIVATE)

    assert implementation.get_flow_client() is client
    assert implementation._client_selection is selection
    assert client.backend_kind == 'browser'
    assert len(instances) == 1


def test_browser_constructor_failure_is_sticky_without_retry_or_extension_fallback(
        monkeypatch, browser_factory):
    instances, module = browser_factory
    attempted = []

    def fail():
        attempted.append('browser')
        raise RuntimeError(PRIVATE)

    module.BrowserFlowBackend = fail
    with pytest.raises(RuntimeError, match='^FLOW_BACKEND_INITIALIZATION_FAILED$') as first:
        implementation.get_flow_client()

    assert PRIVATE not in str(first.value)
    assert implementation._client is None
    assert implementation._client_selection.kind == 'browser'

    monkeypatch.setenv(BACKEND_ENV, 'extension')
    with pytest.raises(RuntimeError, match='^FLOW_BACKEND_INITIALIZATION_FAILED$'):
        implementation.get_flow_client()

    assert attempted == ['browser']
    assert instances == []
    assert implementation._client is None


@pytest.mark.asyncio
async def test_async_browser_start_failure_never_replaces_selected_client(
        monkeypatch, browser_factory):
    instances, _ = browser_factory
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
async def test_close_does_not_create_an_extension_rollback_path(
        monkeypatch, browser_factory):
    instances, _ = browser_factory
    client = implementation.get_flow_client()
    await client.close_backend()

    monkeypatch.setenv(BACKEND_ENV, 'extension')
    assert implementation.get_flow_client() is client
    assert len(instances) == 1 and instances[0].closes == 1


def test_concurrent_getters_construct_only_one_browser(monkeypatch, browser_factory):
    instances, _ = browser_factory
    with ThreadPoolExecutor(max_workers=4) as pool:
        clients = list(pool.map(lambda _: implementation.get_flow_client(), range(12)))

    assert all(client is clients[0] for client in clients)
    assert len(instances) == 1 and instances[0].starts == 0


def test_direct_injected_browser_client_does_not_consult_environment(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    backend = BrowserStub()
    client = implementation.FlowClient(backend=backend)
    assert client.backend is backend
    assert client.backend_kind == 'browser'
    assert client.paid_dispatch_enabled is False
    assert implementation._client is None
    assert implementation._client_selection is None
