"""Task 4c authored durable idempotency + UNKNOWN no-retry requirements.

Development-first policy: source coverage only; execution is deferred until the
browser-only source pass is complete.
"""
from pathlib import Path
import re

import pytest

from agent.worker import processor
from agent.worker._parsing import _is_error


def test_worker_routes_durable_request_id_into_all_paid_image_paths():
    source = Path("agent/worker/processor.py").read_text(encoding="utf-8")

    assert re.search(
        r"ops\.generate_scene_image\(\s*scene,\s*orientation,\s*request_id=rid,?\s*\)",
        source,
    )
    assert re.search(
        r"ops\.edit_scene_image\(.*?request_id=rid,?\s*\)",
        source,
        re.S,
    )
    # Both character-generation branches must preserve the same durable rid.
    assert len(re.findall(
        r"ops\.generate_reference_image\(\s*char,\s*pid,\s*request_id=rid,?\s*\)",
        source,
    )) == 2
    # Direct character edit bypasses OperationService but must use that rid as
    # the Flow idempotency key rather than minting a retry-specific key.
    assert "idempotency_key=rid" in source


def test_sdk_image_methods_forward_request_id_as_flow_idempotency_key():
    source = Path("agent/sdk/services/operations.py").read_text(encoding="utf-8")

    assert "async def generate_scene_image(self, scene: dict, orientation: str," in source
    assert "request_id: str = \"\") -> dict:" in source
    assert "idempotency_key=request_id" in source

    assert "async def edit_scene_image(self, scene: dict, orientation: str," in source
    assert "request_id: str = \"\") -> dict:" in source

    assert "async def generate_reference_image(self, char: dict, project_id: str," in source
    assert "request_id: str = \"\") -> dict:" in source


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    {
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "unknown",
    },
    {
        "status": 502,
        "error": "PAID_OUTCOME_UNKNOWN",
        "effect": "unknown",
    },
    {
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "not_submitted",
    },
])
async def test_unknown_or_reconciliation_required_is_terminal_for_auto_retry(
        monkeypatch, result):
    updates = []
    failed = []

    async def update_request(rid, **kwargs):
        updates.append((rid, kwargs))

    async def mark_failed(req):
        failed.append(req["id"])

    monkeypatch.setattr(processor.crud, "update_request", update_request)
    monkeypatch.setattr(processor, "_mark_scene_failed", mark_failed)

    req = {
        "id": "11111111-2222-3333-4444-555555555555",
        "type": "GENERATE_IMAGE",
        "retry_count": 0,
    }
    retry_after = {}

    await processor._handle_failure(req["id"], req, result, retry_after)

    assert updates == [(
        req["id"],
        {
            "status": "FAILED",
            "error_message": "PAID_RECONCILIATION_REQUIRED",
        },
    )]
    assert failed == [req["id"]]
    assert retry_after == {}


@pytest.mark.asyncio
async def test_not_submitted_non_unknown_error_can_still_use_existing_retry_policy(monkeypatch):
    updates = []

    async def update_request(rid, **kwargs):
        updates.append((rid, kwargs))

    async def mark_failed(req):
        raise AssertionError("ordinary retryable error should not fail terminally yet")

    monkeypatch.setattr(processor.crud, "update_request", update_request)
    monkeypatch.setattr(processor, "_mark_scene_failed", mark_failed)

    req = {
        "id": "11111111-2222-3333-4444-555555555555",
        "type": "GENERATE_IMAGE",
        "retry_count": 0,
    }
    await processor._handle_failure(
        req["id"],
        req,
        {
            "status": 409,
            "error": "PAID_AUTHORIZATION_REQUIRED",
            "effect": "not_submitted",
        },
        {},
    )

    assert updates
    assert updates[-1][1]["status"] == "PENDING"
    assert updates[-1][1]["retry_count"] == 1


def test_worker_never_derives_a_new_paid_key_from_retry_count_or_time():
    source = Path("agent/worker/processor.py").read_text(encoding="utf-8")
    assert "idempotency_key=rid" in source
    assert "idempotency_key=f" not in source
    assert "idempotency_key=str(time" not in source


def test_effect_unknown_is_always_an_error_even_with_http_200():
    assert _is_error({
        "status": 200,
        "effect": "unknown",
        "data": {"media": []},
    }) is True


def test_worker_routes_durable_request_id_into_video_submit_paths():
    source = Path("agent/worker/processor.py").read_text(encoding="utf-8")
    sdk = Path("agent/sdk/services/operations.py").read_text(encoding="utf-8")

    assert "ops.generate_scene_video(scene, orientation, request_id=rid)" in source
    assert "ops.generate_scene_video_refs(scene, orientation, request_id=rid)" in source

    video = sdk[sdk.index("async def generate_scene_video"):
                sdk.index("async def generate_scene_video_refs")]
    refs = sdk[sdk.index("async def generate_scene_video_refs"):
               sdk.index("async def upscale_scene_video")]

    assert "idempotency_key=request_id" in video
    assert "idempotency_key=request_id" in refs
    assert "paid_authorization=" not in video
    assert "paid_authorization=" not in refs
