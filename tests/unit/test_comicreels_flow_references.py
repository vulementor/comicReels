from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

import agent.api.comicreels as comic_api
from agent.comicreels.images import sha256_file


@pytest.mark.asyncio
async def test_generate_shot_from_three_references_uploads_all_images_and_embeds_script(
    tmp_path, monkeypatch
):
    portraits = []
    panels = []
    for index in range(3):
        path = tmp_path / f"p{index}.png"
        Image.new("RGB", (576, 1024), (20 + index, 30 + index, 40 + index)).save(path)
        digest = sha256_file(path)
        portraits.append(path)
        panels.append({
            "id": f"panel-{index}",
            "display_order": index,
            "status": "AI_IMAGE_APPROVED",
            "portrait_path": str(path),
            "portrait_sha256": digest,
            "approved_sha256": digest,
        })

    shot = {
        "id": "shot-1",
        "project_id": "project-1",
        "panel_id": "panel-1",
        "status": "PENDING",
        "idempotency_key": None,
        "flow_payload": None,
        "model_family": "omni_flash",
        "duration_s": 8,
        "prompt": (
            'COMICREELS SHOT\n'
            'DIALOGUE LOCK: CHỈ CHAR_A nói đúng nguyên văn: "Xin chào."\n'
            'LIP SYNC: chỉ CHAR_A cử động miệng.'
        ),
    }

    uploads = []
    submitted = {}
    updates = []

    async def fake_shot(_shot_id):
        return dict(shot)

    async def fake_details(_project_id):
        return {"project": {"id": "project-1"}, "panels": panels, "shots": [shot]}

    async def fake_flowkit_upload(body):
        uploads.append({
            "file_path": body.file_path,
            "project_id": body.project_id,
            "file_name": body.file_name,
        })
        return {"media_id": f"media-{len(uploads)}"}

    async def fake_flowkit_status():
        return {
            "connected": True,
            "flow_project_id": None,
            "session_project": {"project_id": "flow-project"},
        }

    async def fake_flowkit_generate(body):
        submitted.update(body.model_dump())
        return {"operations": [{"operation": {"name": "op-1"}}]}

    async def fake_update_shot(_shot_id, **changes):
        updates.append(changes)

    monkeypatch.setattr(comic_api.store, "shot", fake_shot)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "_safe_file", lambda value: __import__("pathlib").Path(value))
    monkeypatch.setattr(comic_api, "flowkit_upload_image", fake_flowkit_upload)
    monkeypatch.setattr(comic_api, "flowkit_extension_status", fake_flowkit_status)
    monkeypatch.setattr(comic_api, "flowkit_generate_video_refs", fake_flowkit_generate)
    monkeypatch.setattr(comic_api.store, "update_shot", fake_update_shot)

    body = comic_api.ReferenceFlowGenerateBody(
        confirm_paid=True,
        idempotency_key="refs-test-123",
        panel_ids=["panel-0", "panel-1", "panel-2"],
        project_id="flow-project",
        resolution="360p",
        duration_s=10,
        variant_count=1,
    )
    result = await comic_api._generate_shot_from_references("shot-1", body)

    assert result["deduplicated"] is False
    assert result["reference_panel_ids"] == ["panel-0", "panel-1", "panel-2"]
    assert [u["file_name"] for u in uploads] == [
        "shot-1-ref-1.png",
        "shot-1-ref-2.png",
        "shot-1-ref-3.png",
    ]
    assert all(u["project_id"] == "flow-project" for u in uploads)
    assert submitted["reference_media_ids"] == ["media-1", "media-2", "media-3"]
    assert submitted["duration_s"] == 10
    assert submitted["resolution"] == "360p"
    assert "REFERENCE IMAGES: 3 ảnh" in submitted["prompt"]
    assert 'Xin chào.' in submitted["prompt"]
    assert "không dùng bước TTS/lồng tiếng riêng" in submitted["prompt"]
    assert updates[-1]["status"] == "PROCESSING"
    stored = __import__("json").loads(updates[-1]["flow_payload_json"])
    assert stored["flowkit_delegated"] is True
    assert stored["project_id"] == "flow-project"
    assert stored["generation_preset"] == {
        "model_family": "omni_flash",
        "duration_s": 10,
        "resolution": "360p",
        "variant_count": 1,
        "credit_cost": None,
        "credit_note": "Flow quyết định credit thực tế tại thời điểm gửi.",
    }


@pytest.mark.asyncio
async def test_generate_shot_from_references_rejects_unapproved_panel(tmp_path, monkeypatch):
    path = tmp_path / "p.png"
    Image.new("RGB", (576, 1024), (1, 2, 3)).save(path)
    digest = sha256_file(path)

    async def fake_shot(_shot_id):
        return {
            "id": "shot-1",
            "project_id": "project-1",
            "status": "PENDING",
            "idempotency_key": None,
            "flow_payload": None,
            "model_family": "omni_flash",
            "duration_s": 8,
            "prompt": "script",
        }

    async def fake_details(_project_id):
        return {
            "project": {"id": "project-1"},
            "panels": [{
                "id": "panel-0",
                "display_order": 0,
                "status": "AI_IMAGE_READY",
                "portrait_path": str(path),
                "portrait_sha256": digest,
                "approved_sha256": None,
            }],
            "shots": [],
        }

    monkeypatch.setattr(comic_api.store, "shot", fake_shot)
    monkeypatch.setattr(comic_api, "_details", fake_details)

    body = comic_api.ReferenceFlowGenerateBody(
        confirm_paid=True,
        idempotency_key="refs-test-456",
        panel_ids=["panel-0"],
    )

    with pytest.raises(comic_api.HTTPException) as exc:
        await comic_api._generate_shot_from_references("shot-1", body)

    assert exc.value.status_code == 409
    assert "chưa được duyệt đúng phiên bản" in str(exc.value.detail)



def test_reference_flow_contract_is_fixed_to_omni_10s_360p_single_variant():
    body = comic_api.ReferenceFlowGenerateBody(
        idempotency_key="preset-123",
        panel_ids=["panel-0"],
    )
    assert body.resolution == "360p"
    assert body.duration_s == 10
    assert body.variant_count == 1

    with pytest.raises(Exception):
        comic_api.ReferenceFlowGenerateBody(
            idempotency_key="preset-720p",
            panel_ids=["panel-0"],
            resolution="720p",
        )

    with pytest.raises(Exception):
        comic_api.ReferenceFlowGenerateBody(
            idempotency_key="preset-multi",
            panel_ids=["panel-0"],
            variant_count=2,
        )



@pytest.mark.asyncio
async def test_comicreels_preflight_delegates_to_flowkit(monkeypatch):
    async def fake_status():
        return {
            "connected": True,
            "flow_project_id": "flow-project",
            "session_project": {"project_id": "session-project"},
            "transport": "batch",
        }

    monkeypatch.setattr(comic_api, "flowkit_extension_status", fake_status)

    result = await comic_api.flow_preflight()

    assert result["ready"] is True
    assert result["project_id"] == "flow-project"
    assert result["flowkit"]["transport"] == "batch"
