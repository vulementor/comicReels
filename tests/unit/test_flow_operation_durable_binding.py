"""Task 5a authored durable operation/project binding requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import inspect

import pytest

from agent.services.flow_client import FlowClient

OPERATION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
PROJECT = '11111111-2222-3333-4444-555555555555'


class DurableBackend:
    kind = 'browser'
    ready = True
    paid_dispatch_enabled = False
    session_owner_key = 'owner'

    def __init__(self, bindings=None):
        self.bindings = bindings if bindings is not None else {}
        self.bind_calls = []
        self.lookup_calls = []

    async def bind_operation(self, operation_id, project_id):
        self.bind_calls.append((operation_id, project_id))
        existing = self.bindings.get(operation_id)
        if existing and existing != project_id:
            return {
                'status': 409,
                'error': 'OPERATION_BINDING_CONFLICT',
                'effect': 'not_submitted',
            }
        self.bindings[operation_id] = project_id
        return {
            'status': 200,
            'data': {'operationId': operation_id, 'projectId': project_id},
            'effect': 'completed',
        }

    async def operation_project(self, operation_id):
        self.lookup_calls.append(operation_id)
        project_id = self.bindings.get(operation_id)
        if not project_id:
            return {
                'status': 409,
                'error': 'OPERATION_BINDING_REQUIRED',
                'effect': 'not_submitted',
            }
        return {
            'status': 200,
            'data': {'operationId': operation_id, 'projectId': project_id},
            'effect': 'completed',
        }

    async def execute(self, method, params, timeout=300):
        raise AssertionError('not used by this source-contract test')

    async def submit_paid_image(self, *args, **kwargs):
        raise AssertionError('paid path is unrelated to Task 5a')

    async def start(self):
        pass

    async def close(self):
        pass

    async def check_readiness(self):
        return {'ready': True}

    async def open_project(self, project_id):
        return {'status': 200}

    async def ensure_session_project(self, *, title=None, force_new=False):
        return {'status': 200}


@pytest.mark.asyncio
async def test_flowclient_persists_operation_binding_through_backend():
    backend = DurableBackend()
    client = FlowClient(backend=backend)

    await client._remember_operation(OPERATION, PROJECT)

    assert backend.bind_calls == [(OPERATION, PROJECT)]
    assert backend.bindings == {OPERATION: PROJECT}


@pytest.mark.asyncio
async def test_new_flowclient_instance_resolves_binding_from_shared_durable_backend():
    durable = {OPERATION: PROJECT}
    first = FlowClient(backend=DurableBackend(durable))
    second_backend = DurableBackend(durable)
    second = FlowClient(backend=second_backend)

    assert not hasattr(first, '_operation_projects')
    assert not hasattr(second, '_operation_projects')
    assert await second._operation_project_id(OPERATION) == PROJECT
    assert second_backend.lookup_calls == [OPERATION]


@pytest.mark.asyncio
async def test_missing_durable_binding_has_no_config_project_fallback():
    backend = DurableBackend()
    client = FlowClient(backend=backend)

    with pytest.raises(Exception, match='OPERATION_BINDING_REQUIRED'):
        await client._operation_project_id(OPERATION)

    assert backend.lookup_calls == [OPERATION]


def test_flowclient_source_has_no_ephemeral_operation_project_map():
    source = inspect.getsource(FlowClient)
    assert '_operation_projects' not in source
    assert 'or FLOW_PROJECT_ID' not in source


def test_paid_guards_remain_unrelated_to_operation_binding():
    source = inspect.getsource(FlowClient)
    remember = source[source.index('async def _remember_operation'):
                      source.index('# ─── High-level API Methods')]
    assert 'paid' not in remember.lower()
    assert 'generate_images' not in remember
