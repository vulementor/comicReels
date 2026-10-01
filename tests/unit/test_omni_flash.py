"""Unit tests for Gemini Omni Flash Flow submissions and workflow polling.

Every mode here runs on the flow.google.com batch path; the REST implementations
they used to shadow went with the transport. The wire-contract tests lock the
captured envelopes — rpc id, model key and slot order — because a payload that
submits but is shaped wrong buys a render and returns the wrong clip.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agent.services.omni_flash as omni_flash
AUTH = object()
OPERATION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

from agent.services.omni_flash import (
    OMNI_FLASH_MAX_REFERENCE_IMAGES,
    _load_model_key,
    check_omni_flash_status,
    extract_omni_workflows,
    generate_omni_flash_first_frame_video,
    generate_omni_flash_first_last_video,
    generate_omni_flash_text_video,
    generate_omni_flash_video,
)


@pytest.fixture
def native_reference_submit():
    # MZZa6b observed 2026-09-27: workflow metadata in slot 2, media in slot 3.
    # Credentials, balance, prompt and account identifiers are excluded.
    path = Path(__file__).parents[1] / "fixtures" / "flow_native_reference_submit.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_native_reference_receipt_survives_restart_and_polls_media(native_reference_submit):
    pid = native_reference_submit[3][0][1]
    media_id = native_reference_submit[3][0][0]
    workflow_id = native_reference_submit[3][0][2]
    submitter = MagicMock()
    submitter._batch_project_id.return_value = pid
    submitter.submit_paid_video = AsyncMock(return_value={
        "status": 200,
        "data": {
            "projectId": pid,
            "receiptKind": "media",
            "mediaId": media_id,
            "workflowId": workflow_id,
        },
        "effect": "completed",
        "reused": False,
    })
    with patch("agent.services.omni_flash.get_flow_client", return_value=submitter):
        result = await generate_omni_flash_video(
            reference_media_ids=["ref-1", "ref-2", "ref-3"],
            prompt="One clip containing three scenes", project_id=pid,
            duration_s=10, resolution="360p",
            idempotency_key="omni-native-1",
            paid_authorization=AUTH,
        )
    assert result["status"] == 200
    descriptor = json.loads(json.dumps(result["data"]["flowkitPolling"]))
    assert descriptor == {
        "mode": "batch_media", "project_id": pid,
        "workflows": [{"name": workflow_id, "primary_media_id": media_id, "project_id": pid}],
    }
    assert result["data"]["media"] == [{"name": media_id}]
    assert extract_omni_workflows(result) == descriptor["workflows"]
    submitter.submit_paid_video.assert_awaited_once()
    assert submitter.submit_paid_video.await_args.kwargs["idempotency_key"] == "omni-native-1"
    submitter._remember_operation.assert_not_called()

    poller = MagicMock()
    poller.get_media = AsyncMock(side_effect=[
        {"status": 200, "data": {"image": {"fifeUrl": f"https://flow-content.google/image/{media_id}"}}},
        {"status": 200, "data": {"video": {"fifeUrl": f"https://flow-content.google/video/{media_id}"}}},
    ])
    with patch("agent.services.omni_flash.get_flow_client", return_value=poller):
        pending = await check_omni_flash_status(descriptor["workflows"], project_id=pid)
        complete = await check_omni_flash_status(descriptor["workflows"], project_id=pid)
    assert pending["done"] is False
    assert complete["done"] is True
    assert complete["workflows"][0]["primary_media_id"] == media_id
    assert [
        (call.args, call.kwargs) for call in poller.get_media.await_args_list
    ] == [
        ((media_id,), {"project_id": pid}),
        ((media_id,), {"project_id": pid}),
    ]


@pytest.mark.asyncio
async def test_unknown_paid_reference_result_is_returned_without_binding_or_retry():
    client = MagicMock()
    client._batch_project_id.return_value = "11111111-2222-3333-4444-555555555555"
    client.submit_paid_video = AsyncMock(return_value={
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "unknown",
    })
    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await generate_omni_flash_video(
            ["ref-1"], "clip", "11111111-2222-3333-4444-555555555555",
            duration_s=10,
            idempotency_key="omni-unknown-1",
            paid_authorization=AUTH,
        )
    assert result["effect"] == "unknown"
    assert result["error"] == "PAID_RECONCILIATION_REQUIRED"
    client.submit_paid_video.assert_awaited_once()
    client._remember_operation.assert_not_called()


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (4, "abra_r2v_4s"),
        (6, "abra_r2v_6s"),
        (8, "abra_r2v_8s"),
        (10, "abra_r2v_10s"),
    ],
)
def test_omni_reference_duration_model_keys(duration, expected):
    assert _load_model_key(duration) == expected


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (4, "abra_i2v_4s"),
        (6, "abra_i2v_6s"),
        (8, "abra_i2v_8s"),
        (10, "abra_i2v_10s"),
    ],
)
def test_omni_first_frame_model_keys(duration, expected):
    assert _load_model_key(duration, mode="frame_to_video") == expected


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (4, "abra_i2v_4s"),
        (6, "abra_i2v_6s"),
        (8, "abra_i2v_8s"),
        (10, "abra_i2v_10s"),
    ],
)
def test_omni_first_last_model_keys_are_independently_configured(duration, expected):
    assert _load_model_key(duration, mode="start_end_frame_to_video") == expected


def test_invalid_duration_fails_before_submit():
    with pytest.raises(ValueError, match="duration 5s is unsupported"):
        _load_model_key(5)


def test_extract_omni_workflows_uses_primary_media_id():
    result = {
        "status": 200,
        "data": {
            "operations": [
                {
                    "operation": {"name": "operation-looking-handle"},
                    "status": "MEDIA_GENERATION_STATUS_PENDING",
                }
            ],
            "workflows": [
                {
                    "name": "workflow-1",
                    "metadata": {"primaryMediaId": "media-1"},
                }
            ],
        },
    }
    assert extract_omni_workflows(result) == [
        {"name": "workflow-1", "primary_media_id": "media-1"}
    ]


@pytest.mark.asyncio
async def test_batch_text_video_builds_4s_yhhmef_submit(monkeypatch):
    client = MagicMock()
    pid = "11111111-2222-3333-4444-555555555555"
    media_id = "22222222-3333-4444-5555-666666666666"
    workflow_id = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
    client._batch_project_id.return_value = pid
    client.submit_paid_video = AsyncMock(return_value={
        "status": 200,
        "data": {
            "projectId": pid,
            "receiptKind": "media",
            "mediaId": media_id,
            "workflowId": workflow_id,
        },
        "effect": "completed",
        "reused": False,
    })

    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await generate_omni_flash_text_video(
            prompt="A red paper boat drifts across a pond",
            project_id=pid,
            duration_s=4,
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            idempotency_key="omni-text-1",
            paid_authorization=AUTH,
        )

    assert result["status"] == 200
    assert result["data"]["model"] == "abra_t2v_4s"
    assert result["data"]["duration_s"] == 4
    assert result["data"]["flowkitPolling"]["mode"] == "batch_media"
    assert result["data"]["flowkitPolling"]["workflows"][0]["primary_media_id"] == media_id
    call = client.submit_paid_video.await_args.kwargs
    assert call["rpcid"] == omni_flash.fb.RPC_GEN_VIDEO_TEXT
    assert call["project_id"] == pid
    assert call["idempotency_key"] == "omni-text-1"
    payload = json.loads(json.loads(call["freq"])[0][0][1])
    assert payload[0][0][1] == "abra_t2v_4s"
    assert payload[0][0][2] == omni_flash.fb.VIDEO_ASPECT_LANDSCAPE


@pytest.mark.asyncio
async def test_batch_first_frame_video_uses_eb1hjf_abra_i2v(monkeypatch):
    client = MagicMock()
    pid = "11111111-2222-3333-4444-555555555555"
    client._batch_project_id.return_value = pid
    client.submit_paid_video = AsyncMock(return_value={
        "status": 200,
        "data": {
            "projectId": pid,
            "receiptKind": "operation",
            "operationId": OPERATION,
        },
        "effect": "completed",
        "reused": False,
    })
    client._remember_operation = AsyncMock(return_value={"status": 200})

    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await generate_omni_flash_first_frame_video(
            start_image_media_id="media-start",
            prompt="Three children clap gently",
            project_id=pid,
            duration_s=6,
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            idempotency_key="omni-frame-1",
            paid_authorization=AUTH,
        )

    assert result["status"] == 200
    assert result["data"]["model"] == "abra_i2v_6s"
    assert result["data"]["duration_s"] == 6
    assert result["data"]["flowkitPolling"]["mode"] == "batch_operation"
    assert result["data"]["flowkitPolling"]["project_id"] == pid
    assert result["data"]["operations"][0]["operation"]["name"] == OPERATION
    client._remember_operation.assert_awaited_once_with(OPERATION, pid)

    call = client.submit_paid_video.await_args.kwargs
    assert call["rpcid"] == omni_flash.fb.RPC_GEN_VIDEO
    assert call["idempotency_key"] == "omni-frame-1"
    payload = json.loads(json.loads(call["freq"])[0][0][1])
    request = payload[0][0]
    assert request[0][2][0][0][0] == "Three children clap gently"
    assert request[1] == "abra_i2v_6s"
    assert request[2] == omni_flash.fb.VIDEO_ASPECT_LANDSCAPE
    assert request[4][1] == "media-start"


@pytest.mark.asyncio
async def test_first_frame_rejects_missing_start_before_submit():
    with pytest.raises(ValueError, match="requires start_image_media_id"):
        await generate_omni_flash_first_frame_video(
            start_image_media_id="",
            prompt="test",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_first_last_rejects_missing_end_before_submit():
    with pytest.raises(ValueError, match="non-empty end_image_media_id"):
        await generate_omni_flash_first_last_video(
            start_image_media_id="start",
            end_image_media_id="",
            prompt="test",
            project_id="p",
        )


@pytest.mark.asyncio
async def test_batch_omni_poll_uses_as29s_media(monkeypatch):
    client = MagicMock()
    client.get_media = AsyncMock(return_value={
        "status": 200,
        "data": {
            "video": {
                "fifeUrl": "https://flow-content.google/video/media-1?Signature=test"
            }
        },
    })

    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await check_omni_flash_status([
            {
                "name": "workflow-1",
                "primary_media_id": "media-1",
                "project_id": "project-1",
            }
        ])

    assert result["done"] is True
    assert result["status"] == "COMPLETED"
    assert result["workflows"][0]["media"]["resolved_via"] == "as29s"
    client.get_media.assert_awaited_once_with("media-1", project_id="project-1")


@pytest.mark.asyncio
async def test_batch_poll_hands_back_the_signed_url_and_buffers_nothing():
    """The poller must return Flow's signed url, never the bytes: buffering a
    finished clip through the agent is what the as29s lookup exists to avoid."""
    client = MagicMock()
    client.get_media = AsyncMock(return_value={"status": 200, "data": {"video": {
        "fifeUrl": "https://flow-content.google/video/media-1?Signature=test"}}})

    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await check_omni_flash_status(
            [{"name": "workflow-1", "primary_media_id": "media-1"}],
            include_encoded_video=True, project_id="project-1")

    media = result["workflows"][0]["media"]
    assert result["done"] is True
    assert media["url"].startswith("https://flow-content.google/video/")
    assert media["encoded_video_available"] is False
    assert media["encoded_video"] is None
    client.get_media.assert_awaited_once_with("media-1", project_id="project-1")


@pytest.mark.asyncio
async def test_batch_poll_treats_a_media_record_without_video_as_pending():
    """A media id exists before its clip does — the record serves the poster
    image first. Reading that as done is what saves a still instead of a video."""
    client = MagicMock()
    client.get_media = AsyncMock(return_value={"status": 200, "data": {"image": {
        "fifeUrl": "https://flow-content.google/image/media-1?Signature=test"}}})

    with patch("agent.services.omni_flash.get_flow_client", return_value=client):
        result = await check_omni_flash_status(
            [{"name": "workflow-1", "primary_media_id": "media-1"}],
            project_id="project-1")

    assert result["done"] is False
    assert result["workflows"][0]["status"] == "PENDING"
    client.get_media.assert_awaited_once_with("media-1", project_id="project-1")


@pytest.mark.asyncio
async def test_submit_rejects_more_than_seven_references():
    refs = [f"ref-{i}" for i in range(OMNI_FLASH_MAX_REFERENCE_IMAGES + 1)]

    with pytest.raises(ValueError, match="at most 7 reference images"):
        await generate_omni_flash_video(
            reference_media_ids=refs,
            prompt="test",
            project_id="p",
            duration_s=8,
        )


@pytest.mark.asyncio
async def test_submit_rejects_empty_reference_set():
    with pytest.raises(ValueError, match="requires at least one reference image"):
        await generate_omni_flash_video(
            reference_media_ids=[],
            prompt="test",
            project_id="p",
            duration_s=8,
        )


class TestMigratedOmniReferenceBatchModes:

    @pytest.fixture
    def client(self):
        with patch("agent.services.omni_flash.get_flow_client") as factory:
            stub = MagicMock()
            pid = "11111111-2222-3333-4444-555555555555"
            stub._batch_project_id.return_value = pid
            stub.submit_paid_video = AsyncMock(return_value={
                "status": 200,
                "data": {
                    "projectId": pid,
                    "receiptKind": "operation",
                    "operationId": OPERATION,
                },
                "effect": "completed",
                "reused": False,
            })
            stub._remember_operation = AsyncMock(return_value={"status": 200})
            factory.return_value = stub
            yield stub

    async def test_first_last_uses_nprqif_and_batch_operation_polling(self, client):
        result = await generate_omni_flash_first_last_video(
            start_image_media_id="start", end_image_media_id="end",
            prompt="morph", project_id="pid", duration_s=4,
            resolution="360p", aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            idempotency_key="omni-first-last-1", paid_authorization=AUTH)
        assert result["status"] == 200
        assert result["data"]["model"] == "omni_flash_i2v_4s_first_last_360p"
        assert result["data"]["resolution"] == "360p"
        assert result["data"]["flowkitPolling"]["mode"] == "batch_operation"
        call = client.submit_paid_video.await_args.kwargs
        assert call["rpcid"] == omni_flash.fb.RPC_GEN_VIDEO_FIRST_LAST
        payload = json.loads(json.loads(call["freq"])[0][0][1])
        req = payload[0][0]
        assert req[1] == "omni_flash_i2v_4s_first_last_360p"
        assert req[4][1] == "start"
        assert req[5][1] == "end"
        client._remember_operation.assert_awaited_once_with(
            OPERATION, "11111111-2222-3333-4444-555555555555")

    async def test_seven_references_submit_rather_than_trip_the_validator(self, client):
        refs = [f"ref-{i}" for i in range(OMNI_FLASH_MAX_REFERENCE_IMAGES)]
        result = await generate_omni_flash_video(
            reference_media_ids=refs, prompt="seven", project_id="pid",
            duration_s=4, resolution="720p",
            idempotency_key="omni-seven-1", paid_authorization=AUTH)
        assert result["status"] == 200
        freq = client.submit_paid_video.await_args.kwargs["freq"]
        payload = json.loads(json.loads(freq)[0][0][1])
        assert payload[0][0][1] == [[None, r] for r in refs]

    async def test_reference_to_video_uses_mzza6b_and_all_references(self, client):
        result = await generate_omni_flash_video(
            reference_media_ids=["a", "b", "c"], prompt="keep all refs",
            project_id="pid", duration_s=6, resolution="720p",
            aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
            idempotency_key="omni-r2v-1", paid_authorization=AUTH)
        assert result["status"] == 200
        assert result["data"]["model"] == "abra_r2v_6s"
        assert result["data"]["flowkitPolling"]["mode"] == "batch_operation"
        call = client.submit_paid_video.await_args.kwargs
        assert call["rpcid"] == omni_flash.fb.RPC_GEN_VIDEO_REFERENCES
        payload = json.loads(json.loads(call["freq"])[0][0][1])
        req = payload[0][0]
        assert req[1] == [[None, "a"], [None, "b"], [None, "c"]]
        assert req[2] == "abra_r2v_6s"
        assert req[3] == omni_flash.fb.VIDEO_ASPECT_PORTRAIT

    async def test_reference_360p_uses_live_wire_model_and_quality_slot(self, client):
        await generate_omni_flash_video(
            reference_media_ids=["a", "b"], prompt="refs", project_id="pid",
            duration_s=4, resolution="360p",
            aspect_ratio="VIDEO_ASPECT_RATIO_LANDSCAPE",
            idempotency_key="omni-r2v-360-1", paid_authorization=AUTH)
        freq = client.submit_paid_video.await_args.kwargs["freq"]
        payload = json.loads(json.loads(freq)[0][0][1])
        req = payload[0][0]
        assert req[2] == "abra_r2v_4s_360p"
        assert req[-1] == [4]

    async def test_invalid_resolution_is_rejected_before_submit(self, client):
        with pytest.raises(ValueError, match="resolution must be 360p or 720p"):
            await generate_omni_flash_first_frame_video(
                start_image_media_id="a", prompt="go", project_id="pid",
                resolution="1080p", idempotency_key="omni-invalid-1")
        client.submit_paid_video.assert_not_called()
