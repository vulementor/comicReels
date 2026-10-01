"""Task 4b authored FlowClient paid one-shot requirements.

Development-first policy: authored only, not executed until source completion.
"""
import json

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_client import FlowClient

PROJECT = '11111111-2222-3333-4444-555555555555'
MEDIA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
URL = f'https://flow-content.google/image/{MEDIA}?signed=ephemeral'
AUTH = object()


class PaidBackend:
    kind = 'browser'
    ready = True
    paid_dispatch_enabled = True
    session_owner_key = 'owner'

    def __init__(self, paid_result=None, media_url=URL):
        self.paid_calls = []
        self.read_calls = []
        self.paid_result = paid_result or {
            'status': 200,
            'data': {'projectId': PROJECT, 'mediaId': MEDIA},
            'effect': 'completed',
            'reused': False,
        }
        self.media_url = media_url

    async def submit_paid_image(self, params, *, idempotency_key,
                                authorization=None, timeout=300):
        self.paid_calls.append({
            'params': params,
            'idempotency_key': idempotency_key,
            'authorization': authorization,
            'timeout': timeout,
        })
        return dict(self.paid_result)

    async def execute(self, method, params, timeout=300):
        self.read_calls.append((method, params, timeout))
        if params.get('rpcid') != fb.RPC_MEDIA:
            raise AssertionError('4b only permits read-only media refresh after paid receipt')
        payload = [self.media_url] if self.media_url else []
        return {
            'status': 200,
            'data': json.dumps([['wrb.fr', fb.RPC_MEDIA, json.dumps(payload)]]),
            'body_complete': True,
            'effect': 'completed',
        }

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
async def test_generate_images_routes_one_shot_to_paid_backend_once_and_keeps_shape():
    backend = PaidBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_images(
        prompt='single paid image',
        project_id=PROJECT,
        aspect_ratio='1:1',
        image_model='GEM_PIX_2',
        count=1,
        seed=7,
        idempotency_key='request-123',
        paid_authorization=AUTH,
    )

    assert len(backend.paid_calls) == 1
    call = backend.paid_calls[0]
    assert call['idempotency_key'] == 'request-123'
    assert call['authorization'] is AUTH
    assert call['params']['rpcid'] == fb.RPC_GEN_IMAGE
    assert call['params']['projectId'] == PROJECT
    assert call['params']['captchaAction'] == fb.CAPTCHA_IMAGE

    assert result == {
        'status': 200,
        'data': {
            'media': [{
                'name': MEDIA,
                'image': {'generatedImage': {'mediaId': MEDIA, 'fifeUrl': URL}},
            }],
            'requested_count': 1,
            'generated_count': 1,
            'complete': True,
        },
        'effect': 'completed',
        'reused': False,
    }
    assert len(backend.read_calls) == 1


@pytest.mark.asyncio
async def test_completed_receipt_without_ready_url_stays_completed_and_never_resubmits():
    backend = PaidBackend(media_url='')
    client = FlowClient(backend=backend)

    result = await client.generate_images(
        prompt='single paid image',
        project_id=PROJECT,
        count=1,
        idempotency_key='request-124',
        paid_authorization=AUTH,
    )

    assert len(backend.paid_calls) == 1
    assert result['status'] == 200
    assert result['effect'] == 'completed'
    assert result['data']['media'][0]['name'] == MEDIA
    assert result['data']['media'][0]['image']['generatedImage']['mediaId'] == MEDIA
    assert result['data']['media'][0]['image']['generatedImage']['fifeUrl'] == ''


@pytest.mark.asyncio
async def test_unknown_paid_result_is_returned_unchanged_without_media_read_or_retry():
    unknown = {
        'status': 409,
        'error': 'PAID_RECONCILIATION_REQUIRED',
        'effect': 'unknown',
    }
    backend = PaidBackend(paid_result=unknown)
    client = FlowClient(backend=backend)

    result = await client.generate_images(
        prompt='single paid image',
        project_id=PROJECT,
        count=1,
        idempotency_key='request-unknown',
        paid_authorization=AUTH,
    )

    assert result == unknown
    assert len(backend.paid_calls) == 1
    assert backend.read_calls == []


@pytest.mark.asyncio
async def test_missing_idempotency_key_fails_before_backend_submission():
    backend = PaidBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_images(
        prompt='single paid image', project_id=PROJECT, count=1,
        paid_authorization=AUTH,
    )

    assert result == {
        'status': 409,
        'error': 'PAID_IDEMPOTENCY_REQUIRED',
        'effect': 'not_submitted',
    }
    assert backend.paid_calls == []
    assert backend.read_calls == []


@pytest.mark.asyncio
async def test_multi_variant_paid_request_fails_before_backend_submission():
    backend = PaidBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_images(
        prompt='two images', project_id=PROJECT, count=2,
        idempotency_key='request-multi', paid_authorization=AUTH,
    )

    assert result == {
        'status': 409,
        'error': 'PAID_SINGLE_SHOT_REQUIRED',
        'effect': 'not_submitted',
    }
    assert backend.paid_calls == []
    assert backend.read_calls == []


def test_flowclient_paid_path_has_no_wave_or_transient_resubmit_policy():
    import inspect
    source = inspect.getsource(FlowClient.generate_images)
    assert 'run_wave' not in source
    assert 'retry_indices' not in source
    assert 'IMAGE_UI_SUBMIT_OFFSETS_S' not in source
    assert 'IMAGE_TRANSIENT_RETRY_DELAY_S' not in source
