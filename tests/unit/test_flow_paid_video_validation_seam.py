"""Task 9d repair-3 authored isolated paid-video validation capability."""
from pathlib import Path

import pytest

from agent.services.flow_paid_video_validation import PaidVideoValidationSession

AUTH = object()
PROJECT = "11111111-2222-3333-4444-555555555555"


class Backend:
    paid_video_dispatch_enabled = True

    async def start(self): pass
    async def close(self): pass
    async def check_readiness(self):
        return {"ready": True, "paid_dispatch_enabled": True}


class Client:
    def __init__(self):
        self.calls = []

    async def submit_paid_video(self, *, rpcid, freq, project_id,
                                idempotency_key, paid_authorization=None,
                                timeout=300):
        self.calls.append({
            "rpcid": rpcid,
            "freq": freq,
            "project_id": project_id,
            "idempotency_key": idempotency_key,
            "paid_authorization": paid_authorization,
            "timeout": timeout,
        })
        return {"status": 200, "effect": "completed", "data": {"projectId": PROJECT}}


@pytest.mark.asyncio
async def test_video_validation_capability_is_consumed_before_await():
    backend = Backend()
    session = PaidVideoValidationSession._for_test(AUTH, backend)
    fake = Client()
    session._client = fake

    first = await session.submit_one_video(
        rpcid="eb1hJf",
        freq="freq",
        project_id=PROJECT,
        idempotency_key="video-validation-1",
    )
    second = await session.submit_one_video(
        rpcid="eb1hJf",
        freq="freq",
        project_id=PROJECT,
        idempotency_key="video-validation-1",
    )

    assert first["status"] == 200
    assert second == {
        "status": 409,
        "error": "PAID_VALIDATION_SHOT_ALREADY_USED",
        "effect": "not_submitted",
    }
    assert len(fake.calls) == 1
    assert fake.calls[0]["paid_authorization"] is AUTH


def test_normal_application_does_not_import_video_validation_capability():
    for path in (
        "agent/main.py",
        "agent/api/flow.py",
        "agent/worker/processor.py",
        "agent/sdk/services/operations.py",
    ):
        source = Path(path).read_text(encoding="utf-8")
        assert "flow_paid_video_validation" not in source
        assert "build_paid_video_validation_session" not in source


def test_image_and_video_validation_capabilities_remain_separate_modules():
    video_source = Path(
        "agent/services/flow_paid_video_validation.py"
    ).read_text(encoding="utf-8")
    image_source = Path(
        "agent/services/flow_paid_validation.py"
    ).read_text(encoding="utf-8")

    assert "class PaidVideoValidationSession" in video_source
    assert "class PaidValidationSession" in image_source
    assert "generate_one_image" not in video_source


def test_video_validation_builder_enables_only_video_paid_capability():
    source = Path(
        "agent/services/flow_paid_video_validation.py"
    ).read_text(encoding="utf-8")
    assert "paid_video_dispatch_enabled=True" in source
    assert "paid_video_authorization=authorization" in source
    assert "paid_dispatch_enabled=True" not in source


def test_image_validation_builder_does_not_enable_video_paid_capability():
    source = Path(
        "agent/services/flow_paid_validation.py"
    ).read_text(encoding="utf-8")
    assert "paid_dispatch_enabled=True" in source
    assert "paid_video_dispatch_enabled=True" not in source
    assert "paid_video_authorization=" not in source
