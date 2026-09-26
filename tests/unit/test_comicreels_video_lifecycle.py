"""Regression coverage at the FlowKit boundary; no live services."""
import asyncio
import importlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

import agent.api.comicreels as api
from agent.comicreels.images import sha256_file
from agent.comicreels.prompts import build_shots
from agent.comicreels.store import ComicStore

store_module = importlib.import_module("agent.comicreels.store")
FLOW_PROJECT = "10000000-0000-0000-0000-000000000001"


@pytest.fixture
async def comic(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "ROOT", tmp_path)
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comic.db")
    monkeypatch.setattr(api, "ROOT", tmp_path)
    store = ComicStore()
    monkeypatch.setattr(api, "store", store)
    await store.create_project(project_id="comic", name="Comic", source_path="source.png",
                               sha256="source", mime="image/png", width=900, height=900)
    await store.replace_analysis("comic", [
        {"x": 0, "y": i * 300, "w": 900, "h": 300, "visual_anchor": f"Khung {i + 1}"}
        for i in range(3)
    ], [{"panel_index": i, "display_order": 0, "speaker_id": f"CHAR_{i}",
         "text": f"Câu nói {i}.", "verified": True} for i in range(3)])
    panels = (await store.get_project("comic"))["panels"]
    for i, panel in enumerate(panels):
        path = tmp_path / f"p{i}.png"
        Image.new("RGB", (9, 16), (i * 10, 20, 30)).save(path)
        digest = sha256_file(path)
        await store.update_panel(panel["id"], portrait_path=str(path), portrait_sha256=digest,
                                 approved_sha256=digest, status="AI_IMAGE_APPROVED")
    panels = (await store.get_project("comic"))["panels"]
    shots = build_shots("comic", panels, fixed_duration_s=10)
    for shot in shots:
        await store.insert_shot(shot)
    calls = {"uploads": [], "submits": []}

    async def status():
        return {"connected": True, "flow_project_id": FLOW_PROJECT, "transport": "batch",
                "session_project": {"project_id": "other-session", "active": True}}

    async def upload(body):
        calls["uploads"].append(body.model_dump())
        return {"media_id": f"20000000-0000-0000-0000-{len(calls['uploads']):012d}",
                "project_id": body.project_id or FLOW_PROJECT}

    async def generate(body):
        calls["submits"].append(body.model_dump())
        await asyncio.sleep(0)
        return {"operations": [{"operation": {"name": "op-1"}}],
                "flowkitPolling": {"mode": "batch_operation", "project_id": body.project_id}}

    monkeypatch.setattr(api, "flowkit_extension_status", status)
    monkeypatch.setattr(api, "flowkit_upload_image", upload)
    monkeypatch.setattr(api, "flowkit_generate_video_refs", generate)
    return SimpleNamespace(store=store, panels=panels, shot=shots[0], calls=calls, root=tmp_path)


def request(comic, **extra):
    return api.ReferenceFlowGenerateBody(**{
        "confirm_paid": True, "idempotency_key": "reference-attempt-1",
        "panel_ids": [p["id"] for p in comic.panels], **extra,
    })


async def test_status_uses_flowkit_and_retains_ai_availability(comic, monkeypatch):
    monkeypatch.setattr(api, "provider_status", lambda: {"configured": True})
    result = await api.comicreels_status()
    assert result["flow"]["ready"] is True
    assert result["flow"]["project_id"] == FLOW_PROJECT
    assert result["ai"]["configured"] is True
    assert (await api.flow_preflight())["flowkit"]["transport"] == "batch"


async def test_three_references_use_one_flowkit_project_and_exact_script(comic):
    result = await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert result["deduplicated"] is False
    assert len(comic.calls["uploads"]) == 3
    assert {u["project_id"] for u in comic.calls["uploads"]} == {FLOW_PROJECT}
    submitted, = comic.calls["submits"]
    assert submitted["project_id"] == FLOW_PROJECT
    assert len(submitted["reference_media_ids"]) == 3
    assert (submitted["model_family"], submitted["duration_s"], submitted["resolution"]) == ("omni_flash", 10, "360p")
    assert comic.shot["dialogue_text"] in submitted["prompt"]
    assert "SCENE REFERENCE: 1" in submitted["prompt"]
    assert "không dùng bước TTS/lồng tiếng riêng" in submitted["prompt"]
    saved = await comic.store.shot(comic.shot["id"])
    assert saved["status"] == "PROCESSING"
    assert saved["flow_payload"]["generation_preset"]["variant_count"] == 1


@pytest.mark.parametrize("ids", [["p1"], ["p1", "p2"], ["p1", "p1", "p2"]])
def test_reference_contract_requires_three_distinct_panels(ids):
    with pytest.raises(ValidationError):
        api.ReferenceFlowGenerateBody(idempotency_key="attempt-1", panel_ids=ids)


def test_all_comic_video_routes_default_to_360p():
    assert api.FlowGenerateBody(idempotency_key="attempt-1").resolution == "360p"
    assert api.BatchGenerateBody(shot_ids=[], batch_key="batch-123").resolution == "360p"
    with pytest.raises(ValidationError):
        api.FlowGenerateBody(idempotency_key="attempt-1", resolution="720p")


@pytest.mark.parametrize("field,value", [("resolution", "720p"), ("duration_s", 8), ("variant_count", 2)])
def test_reference_preset_is_fixed(field, value):
    with pytest.raises(ValidationError):
        api.ReferenceFlowGenerateBody(idempotency_key="attempt-1", panel_ids=["p1", "p2", "p3"], **{field: value})


async def test_changed_reference_is_blocked_before_any_upload(comic):
    Path(comic.panels[1]["portrait_path"]).write_bytes(b"changed")
    with pytest.raises(api.HTTPException) as error:
        await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert error.value.status_code == 409
    assert not comic.calls["uploads"]


async def test_concurrent_submission_has_only_one_paid_call(comic):
    results = await asyncio.gather(*[
        api._generate_shot_from_references(comic.shot["id"], request(comic)) for _ in range(2)
    ], return_exceptions=True)
    assert len(comic.calls["submits"]) == 1
    assert any(isinstance(r, dict) and not r["deduplicated"] for r in results)
    repeated = await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert repeated["deduplicated"] is True


async def test_submit_timeout_is_not_automatically_retried(comic, monkeypatch):
    async def timeout(body):
        comic.calls["submits"].append(body.model_dump())
        raise TimeoutError("lost receipt")
    monkeypatch.setattr(api, "flowkit_generate_video_refs", timeout)
    with pytest.raises(api.HTTPException):
        await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert (await comic.store.shot(comic.shot["id"]))["status"] == "SUBMISSION_UNKNOWN"
    with pytest.raises(api.HTTPException):
        await api._generate_shot_from_references(comic.shot["id"], request(comic, force=True, idempotency_key="attempt-two"))
    assert len(comic.calls["submits"]) == 1


async def test_unexpected_receipt_is_persisted_before_reporting_error(comic, monkeypatch):
    async def multiple(body):
        return {"operations": [{"operation": {"name": "op-1"}}, {"operation": {"name": "op-2"}}]}
    monkeypatch.setattr(api, "flowkit_generate_video_refs", multiple)
    with pytest.raises(api.HTTPException):
        await api._generate_shot_from_references(comic.shot["id"], request(comic))
    shot = await comic.store.shot(comic.shot["id"])
    assert shot["status"] == "SUBMISSION_UNKNOWN"
    assert len(shot["flow_payload"]["result"]["operations"]) == 2


async def test_retry_rejected_video_resets_old_review_and_file(comic):
    await comic.store.update_shot(comic.shot["id"], status="COMPLETED", video_path="old.mp4",
                                 review_status="REJECTED", idempotency_key="old-attempt")
    await api._generate_shot_from_references(comic.shot["id"], request(comic, force=True))
    shot = await comic.store.shot(comic.shot["id"])
    assert shot["video_path"] is None
    assert shot["review_status"] == "PENDING"
    assert shot["status"] == "PROCESSING"


@pytest.mark.parametrize("workflow", [False, True])
async def test_poll_downloads_flowkit_video_shapes(comic, monkeypatch, workflow):
    await api._generate_shot_from_references(comic.shot["id"], request(comic))
    url = "https://flow-content.google/video/example"
    async def poll(body):
        if workflow:
            return {"done": True, "workflows": [{"done": True, "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "media": {"url": url}}]}
        return {"operations": [{"status": "MEDIA_GENERATION_STATUS_SUCCESSFUL", "operation": {
            "metadata": {"video": {"fifeUrl": url}}
        }}]}
    monkeypatch.setattr(api, "flowkit_check_status", poll)
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=b"test-video", headers={"content-type": "video/mp4"}))
    monkeypatch.setattr(api.httpx, "AsyncClient", lambda **kw: real_client(transport=transport, **kw))
    result = await api.poll_shot(comic.shot["id"])
    assert Path(result["saved_video"]).read_bytes() == b"test-video"
    shot = await comic.store.shot(comic.shot["id"])
    assert shot["status"] == "COMPLETED"
    assert shot["flow_payload"]["last_status"]
    preview = await api.get_shot_video(comic.shot["id"])
    assert Path(preview.path) == Path(shot["video_path"])
    assert preview.media_type == "video/mp4"


async def test_poll_terminal_failure_is_retryable(comic, monkeypatch):
    await api._generate_shot_from_references(comic.shot["id"], request(comic))
    async def poll(body):
        return {"operations": [{"status": "MEDIA_GENERATION_STATUS_FAILED", "error": "failed"}]}
    monkeypatch.setattr(api, "flowkit_check_status", poll)
    await api.poll_shot(comic.shot["id"])
    assert (await comic.store.shot(comic.shot["id"]))["status"] == "FAILED"
    await api._generate_shot_from_references(comic.shot["id"], request(comic, force=True, idempotency_key="retry-two"))
    assert len(comic.calls["submits"]) == 2


@pytest.mark.parametrize("mutation", ["clear", "analysis", "panel", "dialogue", "insert_dialogue"])
async def test_active_paid_jobs_block_destructive_project_mutations(comic, mutation):
    await api._generate_shot_from_references(comic.shot["id"], request(comic))
    with pytest.raises(sqlite3.IntegrityError, match="chưa kết thúc"):
        if mutation == "clear":
            await comic.store.clear_shots("comic")
        elif mutation == "analysis":
            await comic.store.replace_analysis("comic", [], [])
        elif mutation == "panel":
            await comic.store.update_panel(comic.panels[0]["id"], approved_sha256=None)
        else:
            dialogue = comic.panels[0]["dialogues"][0]
            await comic.store.upsert_dialogue(
                comic.panels[0]["id"], dialogue_id=dialogue["id"] if mutation == "dialogue" else None,
                order=0, speaker_id="CHAR_0", text="changed", verified=True,
            )
    assert (await comic.store.shot(comic.shot["id"]))["status"] == "PROCESSING"
    assert (await comic.store.panel(comic.panels[0]["id"]))["approved_sha256"]


async def test_late_poll_cannot_replace_newer_attempt_or_reset_review(comic):
    await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert await comic.store.update_attempt(comic.shot["id"], "reference-attempt-1",
                                            status="COMPLETED", video_path="first.mp4")
    await comic.store.review_video(comic.shot["id"], video_path="first.mp4", status="REJECTED", notes="old")
    assert not await comic.store.update_attempt(comic.shot["id"], "reference-attempt-1",
                                                status="COMPLETED", review_status="PENDING")
    await api._generate_shot_from_references(comic.shot["id"], request(comic, force=True, idempotency_key="second-attempt"))
    assert not await comic.store.update_attempt(comic.shot["id"], "reference-attempt-1",
                                                status="COMPLETED", video_path="first.mp4")
    saved = await comic.store.shot(comic.shot["id"])
    assert saved["status"] == "PROCESSING"
    assert saved["idempotency_key"] == "second-attempt"
    assert saved["video_path"] is None


async def test_review_must_match_the_video_that_was_viewed(comic):
    await comic.store.update_shot(comic.shot["id"], status="COMPLETED", video_path="current.mp4")
    with pytest.raises(store_module.ComicConflictError):
        await comic.store.review_video(comic.shot["id"], video_path="old.mp4", status="APPROVED", notes="")
    assert (await comic.store.shot(comic.shot["id"]))["review_status"] == "PENDING"


@pytest.mark.parametrize("state", ["SUBMITTING", "PROCESSING", "SUBMISSION_UNKNOWN"])
async def test_manual_video_cannot_override_an_unfinished_paid_job(comic, state):
    await comic.store.update_shot(comic.shot["id"], status=state)
    with pytest.raises(store_module.ComicConflictError):
        await comic.store.register_video_file(comic.shot["id"], "manual.mp4")
    assert (await comic.store.shot(comic.shot["id"]))["status"] == state


async def test_workflow_receipt_uses_flowkit_workflow_polling(comic, monkeypatch):
    workflow = {"name": "workflow-1", "primary_media_id": "media-1", "project_id": FLOW_PROJECT}
    async def generate(body):
        return {"flowkitPolling": {"workflows": [workflow]}}
    async def poll(body):
        assert body.workflows == [workflow]
        assert body.operations == []
        return {"workflows": [{**workflow, "done": False, "status": "PENDING"}]}
    monkeypatch.setattr(api, "flowkit_generate_video_refs", generate)
    monkeypatch.setattr(api, "flowkit_check_status", poll)
    await api._generate_shot_from_references(comic.shot["id"], request(comic))
    assert (await comic.store.shot(comic.shot["id"]))["status"] == "PROCESSING"
    result = await api.poll_shot(comic.shot["id"])
    assert result["saved_video"] is None
