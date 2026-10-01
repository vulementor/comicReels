"""Task 5c authored restart/resume and public response-shape requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
import re
from types import SimpleNamespace

import pytest

from agent.sdk.services import operations as ops_module
from agent.sdk.services.operations import OperationService
from agent.services.flow_client import (
    FlowClient,
    _as_pending_operation,
)

OPERATION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
MEDIA = '99999999-8888-7777-6666-555555555555'
VIDEO = f'https://flow-content.google/video/{MEDIA}?signed=ephemeral'


class PollOnlyClient:
    async def generate_video(self, **_kwargs):
        raise AssertionError('restart resume must not submit a new video effect')

    async def check_video_status(self, operations):
        return {
            'status': 200,
            'data': {
                'operations': [{
                    'operation': {
                        'name': OPERATION,
                        'metadata': {'video': {'mediaId': MEDIA, 'fifeUrl': VIDEO}},
                    },
                    'status': 'MEDIA_GENERATION_STATUS_SUCCESSFUL',
                }],
            },
        }


@pytest.mark.asyncio
async def test_restart_resume_with_saved_request_id_repolls_without_resubmit(monkeypatch):
    client = PollOnlyClient()
    service = OperationService(client, repo=None)

    async def get_project(_pid):
        return {'user_paygate_tier': 'PAYGATE_TIER_TWO'}

    async def get_request(_rid):
        return {'request_id': OPERATION}

    monkeypatch.setattr(ops_module.crud, 'get_project', get_project)
    monkeypatch.setattr(ops_module.crud, 'get_request', get_request)
    monkeypatch.setattr(ops_module, '_build_video_prompt',
                        lambda *args, **kwargs: _async_value('prompt'))

    scene = {
        'id': 'scene-1',
        '_project_id': '11111111-2222-3333-4444-555555555555',
        'vertical_image_media_id': MEDIA,
        'video_prompt': 'move',
    }
    result = await service.generate_scene_video(
        scene, 'VERTICAL',
        request_id='22222222-3333-4444-5555-666666666666',
    )

    assert result['data']['operations'][0]['operation']['name'] == OPERATION
    assert result['data']['operations'][0]['status'] == 'MEDIA_GENERATION_STATUS_SUCCESSFUL'


async def _async_value(value):
    return value


def test_pending_operation_business_shape_is_stable():
    result = _as_pending_operation(
        OPERATION,
        error='POLL_READ_UNAVAILABLE',
        media_id=MEDIA,
    )
    assert result == {
        'operation': {
            'name': OPERATION,
            'metadata': {'video': {'mediaId': MEDIA}},
        },
        'status': 'MEDIA_GENERATION_STATUS_PENDING',
        'complaint': 'POLL_READ_UNAVAILABLE',
    }


def test_success_response_shape_remains_operation_metadata_video():
    source = __import__('inspect').getsource(FlowClient._poll_batch_operation)
    assert '"operation"' in source
    assert '"name": operation_id' in source
    assert '"metadata": {"video": {"mediaId": media_id, "fifeUrl": urls.video}}' in source
    assert '"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL"' in source


@pytest.mark.asyncio
async def test_check_video_status_sanitizes_poll_exception_to_fixed_complaint(monkeypatch):
    class Backend:
        kind = 'browser'
        ready = True
        paid_dispatch_enabled = False
        session_owner_key = 'owner'

    client = FlowClient(backend=Backend())

    async def explode(_operation_id):
        raise RuntimeError('private profile/path/token detail')

    monkeypatch.setattr(client, '_poll_batch_operation', explode)
    result = await client.check_video_status([
        {'operation': {'name': OPERATION}},
    ])

    entry = result['data']['operations'][0]
    assert entry['status'] == 'MEDIA_GENERATION_STATUS_PENDING'
    assert entry['operation']['name'] == OPERATION
    assert entry['complaint'] == 'POLL_READ_UNAVAILABLE'
    assert 'private' not in str(result)


def test_restart_resume_source_does_not_use_extension_or_ram_operation_state():
    import inspect
    source = inspect.getsource(FlowClient.check_video_status)
    assert 'extension' not in source.lower()
    entire = inspect.getsource(FlowClient)
    assert 'self._operation_projects' not in entire
    assert 'self._operation_media' not in entire
    assert 'self._operation_polls' not in entire


def test_all_operation_services_use_one_restart_resume_helper():
    import inspect
    source = inspect.getsource(OperationService)
    assert 'async def _resume_saved_operation' in source

    scene_video = source[source.index('async def generate_scene_video'):
                         source.index('async def generate_scene_video_refs')]
    refs_video = source[source.index('async def generate_scene_video_refs'):
                        source.index('async def upscale_scene_video')]
    upscale = source[source.index('async def upscale_scene_video'):
                     source.index('# ------------------------------------------------------------------\n    # Reference image operations')]

    resume_call = re.compile(r'_resume_saved_operation\(\s*request_id\s*,')
    assert resume_call.search(scene_video)
    assert resume_call.search(refs_video)
    assert resume_call.search(upscale)

    # Resume checks happen before each submit call, so a saved operation can
    # only be re-polled and cannot fall through to a second paid submit.
    assert resume_call.search(scene_video).start() < scene_video.index('self._client.generate_video(')
    assert resume_call.search(refs_video).start() < refs_video.index('self._client.generate_video_from_references(')
    assert resume_call.search(upscale).start() < upscale.index('self._client.upscale_video(')
