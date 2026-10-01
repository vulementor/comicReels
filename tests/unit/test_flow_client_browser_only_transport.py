"""Browser-only transport-layer requirements for Task 3.

Authored during development-first phase; execution is deferred until final
validation. These tests protect the FlowClient business API while proving the
extension transport implementation is absent.
"""
import inspect
import pytest

from agent.services import flow_backend
from agent.services.flow_client import FlowClient


class BrowserStub:
    kind = 'browser'
    ready = True
    paid_dispatch_enabled = False
    session_owner_key = 'test-browser'

    def __init__(self):
        self.calls = []

    async def start(self):
        self.calls.append(('start',))

    async def close(self):
        self.calls.append(('close',))

    async def check_readiness(self):
        return {'backend_kind': 'browser', 'ready': True,
                'paid_dispatch_enabled': False}

    async def execute(self, method, params, timeout=300):
        self.calls.append(('execute', method, params, timeout))
        return {'status': 200, 'data': 'ok', 'effect': 'completed'}

    async def open_project(self, project_id):
        self.calls.append(('open_project', project_id))
        return {'status': 200, 'data': {'projectId': project_id},
                'effect': 'completed'}

    async def ensure_session_project(self, *, title=None, force_new=False):
        self.calls.append(('ensure_session_project', title, force_new))
        return {'status': 200, 'data': {'projectId': '11111111-2222-3333-4444-555555555555'}}


def test_flow_backend_module_has_no_extension_implementation():
    assert not hasattr(flow_backend, 'ExtensionFlowBackend')
    source = inspect.getsource(flow_backend)
    assert 'class ExtensionFlowBackend' not in source
    assert 'Callable' not in source
    assert 'Awaitable' not in source


def test_flow_client_has_no_extension_transport_methods_or_mutable_socket_state():
    source = inspect.getsource(FlowClient)
    forbidden = (
        'def set_extension',
        'def clear_extension',
        'def _extension_candidates',
        'def _select_extension',
        'def _should_failover',
        'def set_flow_key',
        'def handle_message',
        'def _send_extension',
        '_extension_ws',
        '_extensions',
        '_pending_ws',
        'websocket',
    )
    for marker in forbidden:
        assert marker not in source


def test_extension_status_compatibility_shims_are_retired():
    client = FlowClient(backend=BrowserStub())
    assert not hasattr(client, 'extension_connected')
    assert not hasattr(client, '_flow_key')
    assert not hasattr(client, 'ws_stats')


@pytest.mark.asyncio
async def test_business_send_dispatches_only_through_browser_backend():
    backend = BrowserStub()
    client = FlowClient(backend=backend)
    result = await client._send('batch_rpc', {'rpcid': 'read-only'}, timeout=27)
    assert result['status'] == 200
    assert backend.calls == [
        ('execute', 'batch_rpc', {'rpcid': 'read-only'}, 27),
    ]


@pytest.mark.asyncio
async def test_business_backend_lifecycle_api_is_preserved():
    backend = BrowserStub()
    client = FlowClient(backend=backend)

    await client.start_backend()
    assert client.connected is True
    assert client.backend_kind == 'browser'
    assert client.paid_dispatch_enabled is False
    assert client.session_owner_key == 'test-browser'
    assert (await client.backend_readiness())['ready'] is True
    await client.open_project('11111111-2222-3333-4444-555555555555')
    await client.close_backend()

    assert backend.calls[0] == ('start',)
    assert ('open_project', '11111111-2222-3333-4444-555555555555') in backend.calls
    assert backend.calls[-1] == ('close',)


def test_direct_client_without_injected_backend_defaults_to_browser(monkeypatch):
    import sys
    from types import ModuleType

    made = []
    module = ModuleType('agent.services.flow_browser_backend')

    def construct():
        backend = BrowserStub()
        made.append(backend)
        return backend

    module.BrowserFlowBackend = construct
    monkeypatch.setitem(sys.modules, module.__name__, module)

    client = FlowClient()
    assert client.backend is made[0]
    assert client.backend_kind == 'browser'
    assert len(made) == 1
