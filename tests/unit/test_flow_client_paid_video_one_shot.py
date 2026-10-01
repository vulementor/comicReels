"""Task 9d repair-3 authored FlowClient paid-video one-shot requirements."""
import inspect

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_client import FlowClient

PROJECT = "11111111-2222-3333-4444-555555555555"
OPERATION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MEDIA = "99999999-8888-7777-6666-555555555555"
AUTH = object()


class VideoBackend:
    kind = "browser"
    ready = True
    paid_dispatch_enabled = True
    session_owner_key = "owner"

    def __init__(self, paid_result=None, bind_result=None):
        self.paid_calls = []
        self.execute_calls = []
        self.bind_calls = []
        self.paid_result = paid_result or {
            "status": 200,
            "data": {
                "projectId": PROJECT,
                "receiptKind": "operation",
                "operationId": OPERATION,
            },
            "effect": "completed",
            "reused": False,
        }
        self.bind_result = bind_result or {
            "status": 200,
            "data": {"operationId": OPERATION, "projectId": PROJECT},
            "effect": "completed",
        }

    async def submit_paid_video(self, params, *, idempotency_key,
                                authorization=None, timeout=300):
        self.paid_calls.append({
            "params": params,
            "idempotency_key": idempotency_key,
            "authorization": authorization,
            "timeout": timeout,
        })
        return dict(self.paid_result)

    async def bind_operation(self, operation_id, project_id):
        self.bind_calls.append((operation_id, project_id))
        return dict(self.bind_result)

    async def operation_project(self, operation_id):
        return {
            "status": 200,
            "data": {"operationId": operation_id, "projectId": PROJECT},
            "effect": "completed",
        }

    async def execute(self, method, params, timeout=300):
        self.execute_calls.append((method, params, timeout))
        raise AssertionError("paid video must not use generic execute")

    async def submit_paid_image(self, *args, **kwargs):
        raise AssertionError("image path unrelated")

    async def start(self): pass
    async def close(self): pass
    async def check_readiness(self): return {"ready": True}
    async def open_project(self, project_id): return {"status": 200}
    async def ensure_session_project(self, *, title=None, force_new=False):
        return {"status": 200, "data": {"projectId": PROJECT}}


@pytest.mark.asyncio
async def test_generate_video_uses_one_paid_submit_then_awaited_durable_binding(monkeypatch):
    import agent.services.flow_client as module
    monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", False)
    backend = VideoBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_video(
        start_image_media_id=MEDIA,
        prompt="move",
        project_id=PROJECT,
        scene_id="scene-1",
        idempotency_key="request-video-1",
        paid_authorization=AUTH,
    )

    assert len(backend.paid_calls) == 1
    call = backend.paid_calls[0]
    assert call["idempotency_key"] == "request-video-1"
    assert call["authorization"] is AUTH
    assert call["params"]["rpcid"] == fb.RPC_GEN_VIDEO
    assert call["params"]["projectId"] == PROJECT
    assert call["params"]["captchaAction"] == fb.CAPTCHA_VIDEO
    payload = __import__("json").loads(
        __import__("json").loads(call["params"]["freq"])[0][0][1]
    )
    assert payload[0][0][4][1] == MEDIA
    assert backend.bind_calls == [(OPERATION, PROJECT)]
    assert backend.execute_calls == []
    assert result == {
        "status": 200,
        "data": {"operations": [{
            "operation": {"name": OPERATION},
            "status": "MEDIA_GENERATION_STATUS_PENDING",
        }]},
        "effect": "completed",
        "reused": False,
    }


@pytest.mark.asyncio
async def test_missing_video_idempotency_key_fails_before_paid_submit():
    backend = VideoBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_video(
        start_image_media_id=MEDIA,
        prompt="move",
        project_id=PROJECT,
        scene_id="scene-1",
    )

    assert result == {
        "status": 409,
        "error": "PAID_IDEMPOTENCY_REQUIRED",
        "effect": "not_submitted",
    }
    assert backend.paid_calls == []
    assert backend.bind_calls == []


@pytest.mark.asyncio
async def test_unknown_video_result_is_returned_without_binding_or_retry():
    unknown = {
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "unknown",
    }
    backend = VideoBackend(paid_result=unknown)
    client = FlowClient(backend=backend)

    result = await client.generate_video(
        start_image_media_id=MEDIA,
        prompt="move",
        project_id=PROJECT,
        scene_id="scene-1",
        idempotency_key="request-video-unknown",
        paid_authorization=AUTH,
    )

    assert result == unknown
    assert len(backend.paid_calls) == 1
    assert backend.bind_calls == []
    assert backend.execute_calls == []


@pytest.mark.asyncio
async def test_post_submit_binding_failure_fails_closed_unknown():
    backend = VideoBackend(bind_result={
        "status": 409,
        "error": "OPERATION_BINDING_CONFLICT",
        "effect": "not_submitted",
    })
    client = FlowClient(backend=backend)

    result = await client.generate_video(
        start_image_media_id=MEDIA,
        prompt="move",
        project_id=PROJECT,
        scene_id="scene-1",
        idempotency_key="request-video-bind-fail",
        paid_authorization=AUTH,
    )

    assert result == {
        "status": 409,
        "error": "OPERATION_BINDING_REQUIRED",
        "effect": "unknown",
    }
    assert len(backend.paid_calls) == 1
    assert backend.bind_calls == [(OPERATION, PROJECT)]


def test_generate_video_source_has_no_generic_paid_batch_submit():
    source = inspect.getsource(FlowClient.generate_video)
    assert "submit_paid_video" in source
    assert "_batch_payload(" not in source
    assert "await self._remember_operation" in source


@pytest.mark.asyncio
async def test_degraded_end_frame_fallback_still_uses_start_frame_through_paid_gate(monkeypatch):
    import agent.services.flow_client as module

    monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", True)
    backend = VideoBackend()
    client = FlowClient(backend=backend)

    result = await client.generate_video(
        start_image_media_id=MEDIA,
        prompt="move",
        project_id=PROJECT,
        scene_id="scene-1",
        end_image_media_id="22222222-3333-4444-5555-666666666666",
        idempotency_key="request-video-degraded",
        paid_authorization=AUTH,
    )

    assert result["status"] == 200
    payload = __import__("json").loads(
        __import__("json").loads(backend.paid_calls[0]["params"]["freq"])[0][0][1]
    )
    assert payload[0][0][4][1] == MEDIA
    assert len(backend.paid_calls) == 1


@pytest.mark.asyncio
async def test_degraded_reference_video_uses_first_reference_through_same_one_shot_key(monkeypatch):
    import agent.services.flow_client as module

    monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", True)
    backend = VideoBackend()
    client = FlowClient(backend=backend)
    first = MEDIA

    result = await client.generate_video_from_references(
        [first, "22222222-3333-4444-5555-666666666666"],
        "move",
        PROJECT,
        "scene-1",
        idempotency_key="request-r2v-degraded",
        paid_authorization=AUTH,
    )

    assert result["status"] == 200
    assert backend.paid_calls[0]["idempotency_key"] == "request-r2v-degraded"
    payload = __import__("json").loads(
        __import__("json").loads(backend.paid_calls[0]["params"]["freq"])[0][0][1]
    )
    assert payload[0][0][4][1] == first
    assert len(backend.paid_calls) == 1
