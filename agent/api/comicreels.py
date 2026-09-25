"""ComicReels API.

All expensive Flow calls require confirm_paid=true and an idempotency key.
Image import/analysis/editing remains local unless mode=vision is explicitly
selected, in which case the source is sent to the configured vision provider.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.comicreels.images import (
    ImageValidationError,
    MAX_SOURCE_BYTES,
    build_backup,
    clamp_box,
    clean_with_rect_masks,
    crop_panel,
    detect_panels,
    portrait_9_16,
    save_source,
    sha256_file,
)
from agent.comicreels.prompts import SUPPORTED_DURATIONS, build_shots
from agent.comicreels.store import ROOT, store
from agent.comicreels.ai_provider import (
    analyze_comic,
    backfill_visual_anchors_in_conversation,
    generate_clean_portrait,
    provider_status,
    verify_dialogues_in_conversation,
)
from agent.comicreels.vision import analyze as vision_analyze
from agent.config import FLOW_PROJECT_ID
from agent.services.flow_client import get_flow_client
from agent.services.flow_project_session import current_session_project
from agent.services.omni_flash import (
    check_omni_flash_status,
    generate_omni_flash_first_frame_video,
)


router = APIRouter(prefix="/comicreels", tags=["comicreels"])


def project_dir(project_id: str) -> Path:
    return ROOT / "projects" / project_id


def _safe_file(path: str | None) -> Path:
    if not path:
        raise HTTPException(404, "Chưa có file cho bước này.")
    p = Path(path).resolve()
    root = ROOT.resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "Đường dẫn asset nằm ngoài ComicReels storage.") from exc
    if not p.is_file():
        raise HTTPException(404, "Asset không tồn tại trên máy.")
    return p


def _first(obj: Any, keys: set[str]) -> Any | None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and value not in (None, "", [], {}):
                return value
        for value in obj.values():
            found = _first(value, keys)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _first(value, keys)
            if found is not None:
                return found
    return None


def _flow_project_id(explicit: str = "") -> str:
    session = current_session_project() or {}
    return str(explicit or FLOW_PROJECT_ID or session.get("project_id") or "").strip()


async def _details(project_id: str) -> dict[str, Any]:
    try:
        return await store.get_project(project_id)
    except KeyError as exc:
        raise HTTPException(404, "Không tìm thấy dự án ComicReels.") from exc


class AnalyzeBody(BaseModel):
    mode: Literal["ai", "heuristic", "vision"] = "ai"
    confirm_paid: bool = False


class AIImageBody(BaseModel):
    confirm_paid: bool = False
    force: bool = False


class Box(BaseModel):
    x: int
    y: int
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class ManualPanel(BaseModel):
    box: Box
    order: int


class ManualDialogue(BaseModel):
    panel_index: int
    display_order: int
    speaker_id: str
    text: str
    confidence: float | None = None
    verified: bool = True


class ManualAnalysis(BaseModel):
    panels: list[ManualPanel]
    dialogues: list[ManualDialogue] = []


class PanelUpdate(BaseModel):
    box: Box
    display_order: int | None = None


class DialogueUpdate(BaseModel):
    id: str | None = None
    display_order: int = 0
    speaker_id: str
    text: str
    confidence: float | None = None
    verified: bool = True


class MaskBody(BaseModel):
    rects: list[Box] = []


class StoryboardBody(BaseModel):
    model_family: Literal["omni_flash", "veo"] = "omni_flash"


class FlowGenerateBody(BaseModel):
    confirm_paid: bool = False
    idempotency_key: str = Field(min_length=8, max_length=200)
    project_id: str = ""
    resolution: Literal["360p", "720p"] = "720p"
    force: bool = False


class BatchGenerateBody(BaseModel):
    shot_ids: list[str]
    confirm_paid: bool = False
    batch_key: str = Field(min_length=8, max_length=160)
    project_id: str = ""
    resolution: Literal["360p", "720p"] = "720p"


class ReviewBody(BaseModel):
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    notes: str = ""


class RegisterVideoBody(BaseModel):
    video_path: str


@router.get("/status")
async def comicreels_status():
    client = get_flow_client()
    session = current_session_project() or {}
    pid = _flow_project_id()
    return {
        "status": "ok",
        "storage_root": str(ROOT),
        "flow": {
            "extension_connected": client.connected,
            "project_id": pid or None,
            "session_project": session or None,
            "ready": bool(client.connected and pid),
        },
        "ai": provider_status(),
        "supported_video_durations": SUPPORTED_DURATIONS,
        "local_test_state": "OFFLINE_PASS_EXTERNAL_GATES_PENDING",
    }


@router.post("/projects/import")
async def import_project(file: UploadFile = File(...), name: str = Form("")):
    data = await file.read(MAX_SOURCE_BYTES + 1)
    mime = (file.content_type or "").lower()
    pid = uuid.uuid4().hex
    directory = project_dir(pid)
    try:
        source, width, height, digest = save_source(data, mime, directory)
    except ImageValidationError as exc:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    project = await store.create_project(
        project_id=pid,
        name=(name.strip() or Path(file.filename or "comic").stem or "ComicReels"),
        source_path=str(source),
        sha256=digest,
        mime=mime,
        width=width,
        height=height,
    )
    return {"project": project, "duplicate_hash": digest}


@router.get("/projects")
async def list_projects():
    return await store.list_projects()


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    return await _details(project_id)


@router.get("/projects/{project_id}/source")
async def get_source(project_id: str):
    details = await _details(project_id)
    return FileResponse(_safe_file(details["project"]["source_path"]))


@router.get("/panels/{panel_id}/asset/{kind}")
async def get_panel_asset(panel_id: str, kind: Literal["crop", "clean", "portrait"]):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    key = {"crop": "crop_path", "clean": "clean_path", "portrait": "portrait_path"}[kind]
    return FileResponse(_safe_file(panel.get(key)), media_type="image/png")


async def _apply_analysis(project_id: str, panels: list[dict[str, Any]],
                          dialogues: list[dict[str, Any]]) -> dict[str, Any]:
    details = await _details(project_id)
    project = details["project"]
    width, height = project["source_width"], project["source_height"]
    safe: list[dict[str, Any]] = []
    for panel in panels:
        box = clamp_box(panel, width, height)
        box["mask"] = [
            clamp_box(region, box["w"], box["h"])
            for region in (panel.get("mask") or [])
        ]
        box["visual_anchor"] = str(panel.get("visual_anchor") or "").strip()
        safe.append(box)
    if not safe or len(safe) > 32:
        raise HTTPException(400, "Số panel phải từ 1 đến 32.")
    await store.replace_analysis(project_id, safe, dialogues)
    details = await _details(project_id)
    src = Path(project["source_path"])
    for panel in details["panels"]:
        out = project_dir(project_id) / "panels" / panel["id"] / "crop.png"
        crop_panel(src, panel, out)
        await store.update_panel(panel["id"], crop_path=str(out), status="EXTRACTED")
    return await _details(project_id)


@router.post("/projects/{project_id}/analyze")
async def analyze_project(project_id: str, body: AnalyzeBody):
    details = await _details(project_id)
    project = details["project"]
    source = Path(project["source_path"])
    if body.mode == "ai":
        if not body.confirm_paid:
            raise HTTPException(409, "AI phân tích có thể phát sinh chi phí. Cần xác nhận thao tác AI.")
        if not provider_status()["configured"]:
            raise HTTPException(503, "ChatGPT Web chưa kết nối qua GPT FullProxy. Cần SDK + profile ZaloConnect đã đăng nhập.")
        try:
            result = await analyze_comic(
                source, project["source_mime"], project["source_width"], project["source_height"]
            )
        except Exception as exc:
            raise HTTPException(502, f"AI phân tích thất bại: {exc}") from exc
        panels = sorted(result.get("panels", []), key=lambda x: x.get("order", 0))
        dialogues = []
        for item in result.get("dialogues", []):
            row = dict(item)
            row["verified"] = bool(item.get("verified", False))
            dialogues.append(row)
        receipt = result.get("provider_receipt") or {}
        conversation_url = str(receipt.get("conversation_url") or "").strip()
        if not conversation_url:
            raise HTTPException(502, "AI phân tích không trả ChatGPT conversation URL; không thể tái sử dụng cùng chat.")
        await store.set_project_ai_session(
            project_id,
            conversation_url=conversation_url,
            assistant_message_id=(
                str(receipt.get("assistant_message_id"))
                if receipt.get("assistant_message_id")
                else None
            ),
        )
        response = await _apply_analysis(project_id, panels, dialogues)
        response["analysis_warnings"] = result.get("warnings", [])
        response["characters"] = result.get("characters", [])
        response["analysis_mode"] = "ai"
        return response
    if body.mode == "vision":
        try:
            result = await vision_analyze(
                source, project["source_mime"], project["source_width"], project["source_height"]
            )
        except Exception as exc:
            raise HTTPException(502, f"Vision analysis thất bại: {exc}") from exc
        panels = sorted(result.get("panels", []), key=lambda x: x.get("order", 0))
        dialogues = result.get("dialogues", [])
        response = await _apply_analysis(project_id, panels, dialogues)
        response["analysis_warnings"] = result.get("warnings", [])
        response["characters"] = result.get("characters", [])
        response["analysis_mode"] = "vision"
        return response
    panels = detect_panels(source)
    response = await _apply_analysis(project_id, panels, [])
    response["analysis_warnings"] = [
        "Heuristic chỉ dựa trên gutter. Hãy sửa bbox/thứ tự và nhập thoại thủ công nếu trang không đều."
    ]
    response["analysis_mode"] = "heuristic"
    return response


@router.post("/projects/{project_id}/verify-dialogues")
async def verify_project_dialogues(project_id: str):
    details = await _details(project_id)
    project = details["project"]
    conversation_url = str(project.get("ai_conversation_url") or "").strip()
    if not conversation_url:
        raise HTTPException(409, "Project chưa có ChatGPT conversation nguồn.")

    candidates: list[dict[str, Any]] = []
    dialogue_index: dict[tuple[int, int], dict[str, Any]] = {}
    for panel in details["panels"]:
        panel_index = int(panel["display_order"])
        for dialogue in panel.get("dialogues", []):
            order = int(dialogue.get("display_order", 0))
            candidates.append({
                "panel_index": panel_index,
                "display_order": order,
                "speaker_id": str(dialogue.get("speaker_id") or "UNKNOWN"),
                "text": str(dialogue.get("text") or ""),
            })
            dialogue_index[(panel_index, order)] = dialogue

    if not candidates:
        raise HTTPException(409, "Project chưa có lời thoại để kiểm tra.")

    try:
        verified = await verify_dialogues_in_conversation(conversation_url, candidates)
    except Exception as exc:
        raise HTTPException(502, f"AI kiểm tra thoại thất bại: {exc}") from exc

    if len(verified) != len(candidates) or any(
        not bool(row.get("verified")) for row in verified
    ):
        raise HTTPException(
            422,
            "AI chưa xác minh chắc chắn toàn bộ lời thoại; không cập nhật transcript hoặc trạng thái verified.",
        )

    for row in verified:
        key = (int(row["panel_index"]), int(row["display_order"]))
        current = dialogue_index.get(key)
        if current is None:
            raise HTTPException(502, "AI trả dialogue ngoài mapping hiện tại.")
        await store.upsert_dialogue(
            current["panel_id"],
            dialogue_id=current["id"],
            order=int(row["display_order"]),
            speaker_id=str(row["speaker_id"]),
            text=str(row["text"]),
            verified=bool(row.get("verified")),
            confidence=current.get("confidence"),
        )
    await store.clear_shots(project_id)
    return await _details(project_id)


@router.post("/projects/{project_id}/backfill-visual-anchors")
async def backfill_project_visual_anchors(project_id: str):
    details = await _details(project_id)
    project = details["project"]
    conversation_url = str(project.get("ai_conversation_url") or "").strip()
    if not conversation_url:
        raise HTTPException(409, "Project chưa có ChatGPT conversation nguồn.")

    panels = [
        {
            "panel_index": int(panel["display_order"]),
            "display_order": int(panel["display_order"]),
            "x": int(panel["x"]),
            "y": int(panel["y"]),
            "w": int(panel["w"]),
            "h": int(panel["h"]),
            "dialogues": [
                {
                    "speaker_id": str(dialogue.get("speaker_id") or "UNKNOWN"),
                    "text": str(dialogue.get("text") or ""),
                }
                for dialogue in panel.get("dialogues", [])
            ],
        }
        for panel in details["panels"]
    ]
    if not panels:
        raise HTTPException(409, "Project chưa có panel để backfill visual anchor.")

    try:
        anchors = await backfill_visual_anchors_in_conversation(
            conversation_url,
            panels,
            source_width=int(project["source_width"]),
            source_height=int(project["source_height"]),
        )
    except Exception as exc:
        raise HTTPException(502, f"AI backfill visual anchor thất bại: {exc}") from exc

    if len(anchors) != len(panels):
        raise HTTPException(
            422,
            "AI chưa trả đủ visual anchor cho toàn bộ panel; không cập nhật một phần.",
        )

    try:
        await store.apply_visual_anchors_and_invalidate_portraits(project_id, anchors)
    except Exception as exc:
        raise HTTPException(500, f"Không thể lưu visual anchor atomic: {type(exc).__name__}") from exc
    return await _details(project_id)


@router.put("/projects/{project_id}/analysis")
async def manual_analysis(project_id: str, body: ManualAnalysis):
    panels = [
        {"x": p.box.x, "y": p.box.y, "w": p.box.w, "h": p.box.h, "order": p.order}
        for p in sorted(body.panels, key=lambda p: p.order)
    ]
    dialogues = [d.model_dump() for d in body.dialogues]
    return await _apply_analysis(project_id, panels, dialogues)


@router.patch("/panels/{panel_id}")
async def update_panel_box(panel_id: str, body: PanelUpdate):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    details = await _details(panel["project_id"])
    project = details["project"]
    safe = clamp_box(body.box.model_dump(), project["source_width"], project["source_height"])
    out = project_dir(panel["project_id"]) / "panels" / panel_id / "crop.png"
    crop_panel(Path(project["source_path"]), safe, out)
    await store.update_panel(
        panel_id, **safe, display_order=body.display_order if body.display_order is not None else panel["display_order"],
        crop_path=str(out), clean_path=None, portrait_path=None, portrait_sha256=None,
        approved_sha256=None, mask_json="[]", visual_anchor=None, protected_json=None, status="EXTRACTED",
    )
    await store.clear_shots(panel["project_id"])
    await store.set_project_status(panel["project_id"], "EXTRACTED")
    return await _details(panel["project_id"])


@router.put("/panels/{panel_id}/dialogue")
async def update_dialogue(panel_id: str, body: DialogueUpdate):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    row = await store.upsert_dialogue(
        panel_id, dialogue_id=body.id, order=body.display_order,
        speaker_id=body.speaker_id.strip() or "UNKNOWN", text=body.text,
        verified=body.verified, confidence=body.confidence,
    )
    await store.clear_shots(panel["project_id"])
    return row


@router.delete("/dialogues/{dialogue_id}")
async def delete_dialogue(dialogue_id: str):
    row = await store.fetch_one("SELECT panel_id FROM comic_dialogue WHERE id=?", (dialogue_id,))
    if not row:
        raise HTTPException(404, "Không tìm thấy lời thoại.")
    panel = await store.panel(row["panel_id"])
    await store.execute("DELETE FROM comic_dialogue WHERE id=?", (dialogue_id,))
    if panel:
        await store.clear_shots(panel["project_id"])
    return {"deleted": dialogue_id}


@router.put("/panels/{panel_id}/mask")
async def update_panel_mask(panel_id: str, body: MaskBody):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    rects = [r.model_dump() for r in body.rects]
    await store.update_panel(
        panel_id,
        mask_json=json.dumps(rects),
        portrait_path=None,
        portrait_sha256=None,
        approved_sha256=None,
        protected_json=None,
        status="ANALYZED",
    )
    await store.clear_shots(panel["project_id"])
    return {"panel_id": panel_id, "mask": rects}


@router.post("/panels/{panel_id}/ai-generate")
async def ai_generate_panel(panel_id: str, body: AIImageBody):
    if not body.confirm_paid:
        raise HTTPException(409, "AI Generate có thể phát sinh chi phí. Cần xác nhận thao tác AI.")
    if not provider_status()["configured"]:
        raise HTTPException(503, "AI hình ảnh chưa kết nối qua GPT FullProxy. Cần SDK + profile ZaloConnect đã đăng nhập.")
    raw_panel = await store.panel(panel_id)
    if not raw_panel:
        raise HTTPException(404, "Không tìm thấy panel.")

    visual_anchor = str(raw_panel.get("visual_anchor") or "").strip()
    if not visual_anchor:
        raise HTTPException(
            409,
            "Panel chưa có visual anchor từ ảnh nguồn. Cần AI phân tích/backfill anchor trước khi Generate.",
        )

    if (
        not body.force
        and raw_panel.get("status") in {"AI_IMAGE_READY", "AI_IMAGE_APPROVED"}
        and raw_panel.get("portrait_path")
        and raw_panel.get("portrait_sha256")
    ):
        try:
            existing = _safe_file(raw_panel.get("portrait_path"))
        except HTTPException:
            existing = None
        if existing is not None and sha256_file(existing) == raw_panel.get("portrait_sha256"):
            return {
                "panel_id": panel_id,
                "portrait_sha256": raw_panel["portrait_sha256"],
                "status": raw_panel["status"],
                "deduplicated": True,
            }

    crop = _safe_file(raw_panel.get("crop_path"))
    try:
        regions = json.loads(raw_panel.get("mask_json") or "[]")
    except json.JSONDecodeError:
        regions = []
    details = await _details(raw_panel["project_id"])
    parsed = next((p for p in details["panels"] if p["id"] == panel_id), None)
    dialogue_context = ""
    if parsed:
        lines = [
            f'{d.get("speaker_id")}: {d.get("text")}'
            for d in parsed.get("dialogues", [])
            if d.get("text")
        ]
        if lines:
            dialogue_context = "Detected dialogue context only; do NOT render it as text: " + " | ".join(lines)
    out = project_dir(raw_panel["project_id"]) / "panels" / panel_id / "portrait.png"
    project = details["project"]
    conversation_url = str(project.get("ai_conversation_url") or "").strip()
    if not conversation_url:
        raise HTTPException(
            409,
            "Project chưa có ChatGPT conversation nguồn. Hãy chạy AI phân tích ảnh nguồn trước.",
        )
    try:
        _, protected, digest = await generate_clean_portrait(
            crop,
            regions,
            out,
            conversation_url=conversation_url,
            panel_index=int(raw_panel["display_order"]),
            panel_context=dialogue_context,
            panel_box={
                "x": int(raw_panel["x"]),
                "y": int(raw_panel["y"]),
                "w": int(raw_panel["w"]),
                "h": int(raw_panel["h"]),
            },
            source_width=int(project["source_width"]),
            source_height=int(project["source_height"]),
            visual_anchor=visual_anchor,
        )
    except Exception as exc:
        raise HTTPException(502, f"AI Generate ảnh thất bại: {exc}") from exc
    await store.update_panel(
        panel_id,
        portrait_path=str(out),
        portrait_sha256=digest,
        approved_sha256=None,
        protected_json=json.dumps(protected),
        status="AI_IMAGE_READY",
    )
    await store.clear_shots(raw_panel["project_id"])
    return {
        "panel_id": panel_id,
        "portrait_sha256": digest,
        "protected_region": protected,
        "status": "AI_IMAGE_READY",
    }


@router.post("/panels/{panel_id}/clean")
async def clean_panel(panel_id: str, body: MaskBody):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    crop = _safe_file(panel["crop_path"])
    rects = [r.model_dump() for r in body.rects]
    if not rects:
        raise HTTPException(400, "Cần ít nhất một vùng mask trước khi xóa chữ / bong bóng.")
    out = project_dir(panel["project_id"]) / "panels" / panel_id / "clean.png"
    _, applied = clean_with_rect_masks(crop, rects, out)
    await store.update_panel(
        panel_id, clean_path=str(out), mask_json=json.dumps(applied),
        portrait_path=None, portrait_sha256=None, approved_sha256=None, protected_json=None,
        status="CLEANED",
    )
    await store.clear_shots(panel["project_id"])
    return {"panel_id": panel_id, "clean_path": str(out), "mask": applied}


@router.post("/panels/{panel_id}/portrait")
async def make_portrait(panel_id: str):
    panel = await store.panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel.")
    source = _safe_file(panel.get("clean_path") or panel.get("crop_path"))
    out = project_dir(panel["project_id"]) / "panels" / panel_id / "portrait.png"
    _, protected, digest = portrait_9_16(source, out)
    await store.update_panel(
        panel_id, portrait_path=str(out), portrait_sha256=digest,
        approved_sha256=None, protected_json=json.dumps(protected), status="IMAGES_READY",
    )
    await store.clear_shots(panel["project_id"])
    return {"panel_id": panel_id, "portrait_sha256": digest, "protected_region": protected}


@router.post("/panels/{panel_id}/approve")
async def approve_panel(panel_id: str):
    panel = await store.panel(panel_id)
    if not panel or not panel.get("portrait_path"):
        raise HTTPException(409, "Cần tạo ảnh 9:16 trước khi duyệt.")
    if not str(panel.get("visual_anchor") or "").strip():
        raise HTTPException(
            409,
            "Ảnh này chưa khóa visual anchor của panel nguồn; không cho duyệt để tránh cross-panel contamination.",
        )
    digest = sha256_file(_safe_file(panel["portrait_path"]))
    if digest != panel.get("portrait_sha256"):
        raise HTTPException(409, "Ảnh 9:16 đã thay đổi ngoài state; hãy tạo lại trước khi OK.")
    next_status = "AI_IMAGE_APPROVED" if panel.get("status") == "AI_IMAGE_READY" else "IMAGE_APPROVED"
    await store.update_panel(panel_id, approved_sha256=digest, status=next_status)
    return {"panel_id": panel_id, "approved_sha256": digest, "status": next_status}


@router.post("/projects/{project_id}/storyboard")
async def storyboard(project_id: str, body: StoryboardBody):
    details = await _details(project_id)
    panels = details["panels"]
    if not panels:
        raise HTTPException(409, "Dự án chưa có panel.")
    for panel in panels:
        if not str(panel.get("visual_anchor") or "").strip():
            raise HTTPException(
                409,
                f"Panel {panel['display_order'] + 1} chưa khóa visual anchor từ ảnh nguồn.",
            )
        if panel.get("status") != "AI_IMAGE_APPROVED":
            raise HTTPException(409, f"Panel {panel['display_order'] + 1} chưa được duyệt từ ảnh AI Generate.")
        if not panel.get("portrait_sha256") or panel.get("approved_sha256") != panel.get("portrait_sha256"):
            raise HTTPException(409, f"Panel {panel['display_order'] + 1} chưa OK đúng phiên bản ảnh hiện tại.")
        for dialogue in panel["dialogues"]:
            if not dialogue.get("verified"):
                raise HTTPException(409, f"Panel {panel['display_order'] + 1} còn thoại chưa xác minh.")
    await store.clear_shots(project_id)
    shots = build_shots(project_id, panels, body.model_family)
    for shot in shots:
        await store.insert_shot(shot)
    await store.set_project_status(project_id, "PROMPTS_READY")
    return await _details(project_id)


@router.get("/projects/{project_id}/backup")
async def backup_project(project_id: str):
    details = await _details(project_id)
    target = project_dir(project_id) / "exports" / f"comicreels-{project_id}.zip"
    build_backup(project_dir(project_id), details, target)
    return FileResponse(target, media_type="application/zip", filename=target.name)


@router.post("/restore")
async def restore_project(file: UploadFile = File(...)):
    data = await file.read(100 * 1024 * 1024)
    temp = ROOT / "restore" / uuid.uuid4().hex
    temp.mkdir(parents=True, exist_ok=True)
    archive = temp / "restore.zip"
    archive.write_bytes(data)
    try:
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                resolved = (temp / member.filename).resolve()
                try:
                    resolved.relative_to(temp.resolve())
                except ValueError as exc:
                    raise HTTPException(400, "Backup chứa đường dẫn không an toàn.") from exc
            zf.extractall(temp)
        manifest_path = temp / "manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(400, "Backup thiếu manifest.json.")
        manifest = json.loads(manifest_path.read_text("utf-8"))
        old_project = manifest.get("project") or {}
        source_candidates = [p for p in temp.rglob("source.*") if p.is_file()]
        if not source_candidates:
            raise HTTPException(400, "Backup thiếu ảnh nguồn.")
        source = source_candidates[0]
        mime_by_suffix = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime = mime_by_suffix.get(source.suffix.lower())
        if not mime:
            raise HTTPException(400, "Ảnh nguồn trong backup không được hỗ trợ.")
        raw = source.read_bytes()
        pid = uuid.uuid4().hex
        out, width, height, digest = save_source(raw, mime, project_dir(pid))
        await store.create_project(
            project_id=pid, name=f"{old_project.get('name','ComicReels')} (restored)",
            source_path=str(out), sha256=digest, mime=mime, width=width, height=height,
        )
        old_panels = manifest.get("panels") or []
        boxes = [{"x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"]} for p in old_panels]
        dialogues: list[dict[str, Any]] = []
        for p_index, p in enumerate(old_panels):
            for d in p.get("dialogues", []):
                dialogues.append({
                    "panel_index": p_index, "display_order": d.get("display_order", 0),
                    "speaker_id": d.get("speaker_id", "UNKNOWN"), "text": d.get("text", ""),
                    "confidence": d.get("confidence"), "verified": bool(d.get("verified")),
                })
        return await _apply_analysis(pid, boxes or [{"x": 0, "y": 0, "w": width, "h": height}], dialogues)
    finally:
        shutil.rmtree(temp, ignore_errors=True)


@router.get("/flow/preflight")
async def flow_preflight(project_id: str = ""):
    client = get_flow_client()
    pid = _flow_project_id(project_id)
    return {
        "extension_connected": client.connected,
        "project_id": pid or None,
        "ready": bool(client.connected and pid),
        "message": "Sẵn sàng gửi job có phí." if client.connected and pid
                   else "Cần Extension kết nối và FLOW_PROJECT_ID/session project.",
    }


async def _generate_shot(shot_id: str, body: FlowGenerateBody) -> dict[str, Any]:
    if not body.confirm_paid:
        raise HTTPException(409, "Cần confirm_paid=true sau khi anh duyệt tác vụ có phí.")
    shot = await store.shot(shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot.")
    if shot.get("idempotency_key") == body.idempotency_key and shot.get("flow_payload"):
        return {"deduplicated": True, "shot": shot}
    if shot.get("status") in {"PROCESSING", "COMPLETED"} and not body.force:
        raise HTTPException(409, "Shot đã được gửi. Dùng cùng idempotency_key hoặc force sau khi kiểm tra.")
    panel = await store.panel(shot["panel_id"])
    if not panel or panel.get("approved_sha256") != shot.get("image_sha256"):
        raise HTTPException(409, "Ảnh của shot không còn trùng phiên bản đã OK.")
    portrait = _safe_file(panel["portrait_path"])
    if sha256_file(portrait) != shot["image_sha256"]:
        raise HTTPException(409, "File ảnh đã thay đổi sau khi lập storyboard.")
    client = get_flow_client()
    pid = _flow_project_id(body.project_id)
    if not client.connected or not pid:
        raise HTTPException(503, "Google Flow chưa sẵn sàng (Extension/project).")
    upload = await client.upload_image(
        base64.b64encode(portrait.read_bytes()).decode("ascii"),
        mime_type="image/png", project_id=pid, file_name=f"{shot_id}.png",
    )
    media_id = _first(upload, {"media_id", "mediaId", "id"})
    if not isinstance(media_id, str) or not media_id:
        raise HTTPException(502, f"Upload Flow không trả media ID: {upload}")
    if shot["model_family"] == "omni_flash":
        result = await generate_omni_flash_first_frame_video(
            start_image_media_id=media_id, prompt=shot["prompt"], project_id=pid,
            scene_id=shot_id, duration_s=int(shot["duration_s"]), resolution=body.resolution,
            aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        )
    else:
        result = await client.generate_video(
            start_image_media_id=media_id, prompt=shot["prompt"], project_id=pid,
            scene_id=shot_id, aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        )
    payload = {"project_id": pid, "start_image_media_id": media_id, "result": result}
    await store.update_shot(
        shot_id, status="PROCESSING", idempotency_key=body.idempotency_key,
        flow_payload_json=json.dumps(payload, ensure_ascii=False),
    )
    return {"deduplicated": False, "shot_id": shot_id, "payload": payload}


@router.post("/shots/{shot_id}/generate")
async def generate_shot(shot_id: str, body: FlowGenerateBody):
    return await _generate_shot(shot_id, body)


@router.post("/projects/{project_id}/generate-batch")
async def generate_batch(project_id: str, body: BatchGenerateBody):
    if not body.confirm_paid:
        raise HTTPException(409, "Batch có thể tốn tín dụng. Cần confirm_paid=true.")
    details = await _details(project_id)
    allowed = {s["id"] for s in details["shots"]}
    requested = body.shot_ids or [s["id"] for s in details["shots"]]
    if any(sid not in allowed for sid in requested):
        raise HTTPException(400, "Danh sách chứa shot không thuộc dự án.")
    results = []
    for index, shot_id in enumerate(requested):
        item = FlowGenerateBody(
            confirm_paid=True, idempotency_key=f"{body.batch_key}:{index}:{shot_id}",
            project_id=body.project_id, resolution=body.resolution,
        )
        try:
            results.append(await _generate_shot(shot_id, item))
        except HTTPException as exc:
            results.append({"shot_id": shot_id, "error": exc.detail, "status": exc.status_code})
    return {"project_id": project_id, "results": results}


@router.post("/shots/{shot_id}/poll")
async def poll_shot(shot_id: str):
    shot = await store.shot(shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot.")
    payload = shot.get("flow_payload") or {}
    result = payload.get("result") or {}
    pid = payload.get("project_id") or _flow_project_id()
    workflows = _first(result, {"workflows"})
    operations = _first(result, {"operations"})
    if isinstance(workflows, list) and workflows:
        status = await check_omni_flash_status(workflows, include_encoded_video=False, project_id=pid)
    elif isinstance(operations, list) and operations:
        status = await get_flow_client().check_video_status(operations)
    else:
        status = result
    url = _first(status, {"video_url", "videoUrl", "download_url", "downloadUrl", "signed_url"})
    saved = None
    if isinstance(url, str) and url.startswith(("https://", "http://")):
        target = project_dir(shot["project_id"]) / "videos" / f"{shot_id}.mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
        saved = str(target)
        await store.update_shot(shot_id, status="COMPLETED", video_path=saved)
    else:
        await store.update_shot(
            shot_id, flow_payload_json=json.dumps({**payload, "last_status": status}, ensure_ascii=False)
        )
    return {"shot_id": shot_id, "status": status, "saved_video": saved}


@router.put("/shots/{shot_id}/video")
async def register_video(shot_id: str, body: RegisterVideoBody):
    shot = await store.shot(shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot.")
    path = Path(body.video_path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(400, "File video không tồn tại trên máy backend.")
    await store.update_shot(shot_id, status="COMPLETED", video_path=str(path))
    return await store.shot(shot_id)


@router.put("/shots/{shot_id}/review")
async def review_shot(shot_id: str, body: ReviewBody):
    shot = await store.shot(shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot.")
    if body.status == "APPROVED" and not shot.get("video_path"):
        raise HTTPException(409, "Cần file video trước khi duyệt shot.")
    await store.update_shot(shot_id, review_status=body.status, review_notes=body.notes)
    return await store.shot(shot_id)


@router.get("/projects/{project_id}/assemble")
@router.post("/projects/{project_id}/assemble")
async def assemble(project_id: str):
    details = await _details(project_id)
    shots = details["shots"]
    if not shots or any(s.get("review_status") != "APPROVED" or not s.get("video_path") for s in shots):
        raise HTTPException(409, "Chỉ ghép khi mọi shot có file và đã được anh APPROVED.")
    out_dir = project_dir(project_id) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    concat_file = out_dir / "concat.txt"
    lines = []
    for shot in shots:
        path = Path(shot["video_path"]).resolve()
        if not path.is_file():
            raise HTTPException(409, f"Thiếu video của shot {shot['id']}.")
        escaped = str(path).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    concat_file.write_text("\n".join(lines) + "\n", "utf-8")
    output = out_dir / "comicreels-final.mp4"
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-c:a", "aac", "-movflags", "+faststart", str(output),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(500, "ffmpeg ghép video thất bại: " + stderr.decode("utf-8", "replace")[-1200:])
    await store.set_project_status(project_id, "EXPORTED")
    return FileResponse(output, media_type="video/mp4", filename=output.name)
