"""Task 5b authored restart-safe media discovery requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import inspect

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_client import FlowClient
from agent.services.flow_browser_driver import FlowBrowserDriver

OPERATION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
PROJECT = '11111111-2222-3333-4444-555555555555'
MEDIA = '99999999-8888-7777-6666-555555555555'
VIDEO = f'https://flow-content.google/video/{MEDIA}?signed=ephemeral'


class Backend:
    kind = 'browser'
    ready = True
    paid_dispatch_enabled = False
    session_owner_key = 'owner'

    async def bind_operation(self, operation_id, project_id):
        return {'status': 200, 'data': {'operationId': operation_id, 'projectId': project_id}}

    async def operation_project(self, operation_id):
        return {
            'status': 200,
            'data': {'operationId': operation_id, 'projectId': PROJECT},
            'effect': 'completed',
        }

    async def execute(self, method, params, timeout=300):
        raise AssertionError('test overrides FlowClient read helpers')

    async def submit_paid_image(self, *args, **kwargs):
        raise AssertionError('paid path is unrelated to Task 5b')

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
async def test_restart_without_ram_media_cache_discovers_listing_on_first_poll(monkeypatch):
    client = FlowClient(backend=Backend())
    calls = []

    async def operation_project(operation_id):
        calls.append(('binding', operation_id))
        return PROJECT

    async def listing(operation_id, project_id):
        calls.append(('listing', operation_id, project_id))
        return MEDIA

    async def media_urls(media_id, project_id=None):
        calls.append(('media', media_id, project_id))
        return fb.MediaUrls(media_id=media_id, video=VIDEO)

    async def operation_payload(*args, **kwargs):
        calls.append(('operation_poll',))
        raise fb.FlowBatchError('poll unavailable')

    monkeypatch.setattr(client, '_operation_project_id', operation_project)
    monkeypatch.setattr(client, '_media_id_for', listing)
    monkeypatch.setattr(client, '_batch_media_urls', media_urls)
    monkeypatch.setattr(client, '_batch_payload', operation_payload)

    result = await client._poll_batch_operation(OPERATION)

    assert result['status'] == 'MEDIA_GENERATION_STATUS_SUCCESSFUL'
    assert ('listing', OPERATION, PROJECT) in calls
    assert ('media', MEDIA, PROJECT) in calls
    assert not hasattr(client, '_operation_polls')
    assert not hasattr(client, '_operation_media')


@pytest.mark.asyncio
async def test_listing_miss_stays_pending_without_any_submit(monkeypatch):
    client = FlowClient(backend=Backend())

    async def operation_project(operation_id):
        return PROJECT

    async def listing(operation_id, project_id):
        return None

    async def operation_payload(*args, **kwargs):
        raise fb.FlowBatchError('poll unavailable')

    monkeypatch.setattr(client, '_operation_project_id', operation_project)
    monkeypatch.setattr(client, '_media_id_for', listing)
    monkeypatch.setattr(client, '_batch_payload', operation_payload)

    result = await client._poll_batch_operation(OPERATION)

    assert result['status'] == 'MEDIA_GENERATION_STATUS_PENDING'
    assert result['operation']['name'] == OPERATION


def test_poll_correctness_has_no_process_local_operation_caches():
    source = inspect.getsource(FlowClient)
    assert '_operation_polls' not in source
    assert '_operation_media' not in source
    find = source[source.index('async def _find_operation_media'):
                  source.index('async def _media_id_for')]
    assert 'rounds % 3' not in find
    assert '_media_id_for(operation_id, project_id)' in find


def test_media_read_can_be_scoped_to_durable_operation_project():
    source = inspect.getsource(FlowClient._batch_media_urls)
    assert 'project_id' in source
    assert 'project_id=project_id' in source


def test_browser_media_read_prefers_explicit_durable_project_scope():
    source = inspect.getsource(FlowBrowserDriver._read_project_for)
    assert "command.rpcid == fb.RPC_MEDIA" in source
    assert "command.project_id" in source
