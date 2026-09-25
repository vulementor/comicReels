"""HTTP API for the ComicReels workflow."""
from __future__ import annotations
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from agent.comicreels import repository as repo
from agent.comicreels import service
from agent.comicreels.flow import estimate_cost, get_comic_generation_worker
from agent.comicreels.models import (
    AnalyzeRequest, ApprovalRequest, BatchGenerationRequest, BBox, DialogueBatch,
    GenerationRequest, MaskRequest, PanelPatch, ReviewRequest, ShotPlanRequest,
)

router = APIRouter(prefix="/comicreels", tags=["comicreels"])

def _bad(exc: Exception, status: int = 400):
    raise HTTPException(status, str(exc)) from exc

@router.get("/status")
async def status():
    worker = get_comic_generation_worker()
    return {
        "ok": True,
        "worker_active_generation_id": worker.active_generation_id,
        "worker_paused": worker.paused,
        "pipeline": {
            "import": True, "panel_detection": True, "dialogue_edit": True,
            "local_inpaint": True, "vertical_9_16": True, "approval_gate": True,
            "prompt_export": True, "flow_queue": True, "review_concat": True, "backup_restore": True,
        },
    }

@router.post("/projects/import")
async def import_project(file: UploadFile = File(...), name: str = Form("ComicReels")):
    data = await file.read(service.MAX_SOURCE_BYTES + 1)
    try:
        return await service.import_source(name, data, (file.content_type or "").lower())
    except Exception as exc:
        _bad(exc)

@router.post("/projects/restore")
async def restore_project(file: UploadFile = File(...), name_override: str | None = Form(default=None)):
    data = await file.read(500 * 1024 * 1024 + 1)
    if len(data) > 500 * 1024 * 1024:
        raise HTTPException(413, "Backup vượt giới hạn 500 MB")
    try:
        return await service.restore_project_backup(data, name_override=name_override)
    except Exception as exc:
        _bad(exc)

@router.get("/projects")
async def list_projects():
    return await repo.list_projects()

@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    value = await repo.project_bundle(project_id)
    if not value:
        raise HTTPException(404, "Không tìm thấy dự án")
    return value

@router.get("/projects/{project_id}/source")
async def project_source(project_id: str):
    value = await repo.get_project(project_id)
    if not value:
        raise HTTPException(404, "Không tìm thấy dự án")
    path = Path(value["source_path"])
    if not path.exists():
        raise HTTPException(404, "Ảnh nguồn không còn trên đĩa")
    return FileResponse(path, media_type=value.get("source_mime") or "application/octet-stream", filename=path.name)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    if not await repo.get_project(project_id):
        raise HTTPException(404, "Không tìm thấy dự án")
    await repo.delete_project(project_id)
    return {"ok": True}

@router.post("/projects/{project_id}/analyze")
async def analyze(project_id: str, body: AnalyzeRequest):
    try:
        return await service.analyze_project(project_id, use_vision=body.use_vision, replace_existing=body.replace_existing)
    except Exception as exc:
        _bad(exc)

@router.post("/projects/{project_id}/panels")
async def create_panel(project_id: str, bbox: BBox, display_order: int | None = Query(default=None, ge=0)):
    project = await repo.get_project(project_id)
    if not project:
        raise HTTPException(404, "Không tìm thấy dự án")
    b = bbox.model_dump()
    if b["x"] + b["width"] > project["source_width"] or b["y"] + b["height"] > project["source_height"]:
        raise HTTPException(400, "BBox nằm ngoài ảnh nguồn")
    return await repo.create_panel(project_id, b, display_order)

@router.patch("/panels/{panel_id}")
async def patch_panel(panel_id: str, body: PanelPatch):
    try:
        return await service.patch_panel(panel_id, display_order=body.display_order,
                                         bbox=body.bbox.model_dump() if body.bbox else None)
    except Exception as exc:
        _bad(exc)

@router.put("/panels/{panel_id}/dialogues")
async def set_dialogues(panel_id: str, body: DialogueBatch):
    try:
        return await service.set_dialogues(panel_id, [d.model_dump(exclude_none=True) for d in body.dialogues])
    except Exception as exc:
        _bad(exc)

@router.post("/panels/{panel_id}/process")
async def process_panel(panel_id: str, body: MaskRequest):
    try:
        return await service.process_panel(
            panel_id, boxes=[b.model_dump() for b in body.boxes] if body.boxes is not None else None,
            padding=body.padding, inpaint_radius=body.inpaint_radius,
        )
    except Exception as exc:
        _bad(exc)

@router.post("/projects/{project_id}/process-all")
async def process_all(project_id: str):
    try:
        return await service.process_all_panels(project_id)
    except Exception as exc:
        _bad(exc)

@router.get("/panels/{panel_id}/asset/{kind}")
async def panel_asset(panel_id: str, kind: str):
    panel = await repo.get_panel(panel_id)
    if not panel:
        raise HTTPException(404, "Không tìm thấy panel")
    field = {"crop":"crop_path","mask":"mask_path","clean":"clean_path","vertical":"vertical_path"}.get(kind)
    if not field or not panel.get(field):
        raise HTTPException(404, "Asset chưa tồn tại")
    path = Path(panel[field])
    if not path.exists():
        raise HTTPException(404, "File asset không còn trên đĩa")
    return FileResponse(path)

@router.post("/panels/{panel_id}/approve")
async def approve(panel_id: str, body: ApprovalRequest):
    try:
        return await service.approve_panel(panel_id, body.expected_sha256)
    except Exception as exc:
        _bad(exc)

@router.post("/projects/{project_id}/plan-shots")
async def plan(project_id: str, body: ShotPlanRequest):
    try:
        return await service.plan_shots(
            project_id, model_family=body.model_family,
            allowed_durations=body.allowed_durations, words_per_second=body.words_per_second,
        )
    except Exception as exc:
        _bad(exc)

@router.get("/projects/{project_id}/export/manual")
async def export_manual(project_id: str):
    try:
        path = await service.export_prompt_zip(project_id)
        return FileResponse(path, media_type="application/zip", filename=path.name)
    except Exception as exc:
        _bad(exc)

@router.get("/projects/{project_id}/backup")
async def backup(project_id: str):
    try:
        path = await service.backup_project(project_id)
        return FileResponse(path, media_type="application/zip", filename=path.name)
    except Exception as exc:
        _bad(exc)

@router.get("/shots/{shot_id}/cost")
async def cost_estimate(shot_id: str, model_family: str | None = Query(default=None)):
    shot = await repo.get_shot(shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot")
    family = model_family or shot["model_family"]
    if family not in {"omni_flash", "veo"}:
        raise HTTPException(400, "Model family không hỗ trợ")
    estimate = estimate_cost(family, int(shot["duration_s"]))
    return {
        "shot_id":shot_id, "model_family":family, "duration_s":shot["duration_s"],
        "estimated_credits":estimate,
        "note":("Giá là ước tính từ cấu hình FlowKit và có thể thay đổi theo Google/tài khoản."
                if estimate is not None else
                "Không có ước tính đáng tin cho model này; kiểm tra Flow trước khi xác nhận."),
    }

async def _enqueue(project_id: str, body: GenerationRequest):
    if not body.confirm_cost:
        raise HTTPException(409, "Phải xác nhận chi phí trước khi xếp job Google Flow")
    shot = await repo.get_shot(body.shot_id)
    if not shot:
        raise HTTPException(404, "Không tìm thấy shot")
    panel = await repo.get_panel(shot["panel_id"])
    if not panel or panel["project_id"] != project_id:
        raise HTTPException(400, "Shot không thuộc dự án")
    if body.model_family != shot["model_family"]:
        raise HTTPException(409, "Model family khác shot plan; hãy plan lại prompt trước")
    duration = int(body.duration_s or shot["duration_s"])
    if duration != int(shot["duration_s"]):
        raise HTTPException(409, "Duration khác shot plan; hãy plan lại prompt trước")
    if body.model_family == "omni_flash" and duration not in {4,6,8,10}:
        raise HTTPException(400, "Omni Flash chỉ hỗ trợ 4/6/8/10 giây")
    return await repo.create_generation(
        project_id=project_id, shot_id=shot["id"], idempotency_key=body.idempotency_key,
        model_family=body.model_family, duration_s=duration, resolution=body.resolution,
        flow_project_id=body.flow_project_id, cost_estimate=estimate_cost(body.model_family,duration),
        cost_approved=True,
    )

@router.post("/projects/{project_id}/generations")
async def enqueue_generation(project_id: str, body: GenerationRequest):
    return await _enqueue(project_id, body)

@router.post("/projects/{project_id}/generations/batch")
async def enqueue_batch(project_id: str, body: BatchGenerationRequest):
    if not body.confirm_cost:
        raise HTTPException(409, "Phải xác nhận chi phí trước khi xếp batch Google Flow")
    out=[]; seen=set()
    for shot_id in body.shot_ids:
        if shot_id in seen:
            continue
        seen.add(shot_id)
        shot=await repo.get_shot(shot_id)
        if not shot:
            raise HTTPException(404, f"Không tìm thấy shot {shot_id}")
        out.append(await _enqueue(project_id, GenerationRequest(
            shot_id=shot_id, idempotency_key=f"{body.batch_key}:{shot_id}", confirm_cost=True,
            model_family=body.model_family, duration_s=int(shot["duration_s"]),
            resolution=body.resolution, flow_project_id=body.flow_project_id,
        )))
    return out

@router.get("/projects/{project_id}/generations")
async def generations(project_id: str):
    return await repo.list_generations(project_id)

@router.post("/queue/pause")
async def pause_queue():
    worker = get_comic_generation_worker()
    worker.pause()
    return {"ok": True, "paused": True, "active_generation_id": worker.active_generation_id}

@router.post("/queue/resume")
async def resume_queue():
    worker = get_comic_generation_worker()
    worker.resume()
    return {"ok": True, "paused": False, "active_generation_id": worker.active_generation_id}

@router.post("/generations/{generation_id}/cancel")
async def cancel_generation(generation_id: str):
    value = await repo.get_generation(generation_id)
    if not value:
        raise HTTPException(404, "Không tìm thấy generation")
    if value["status"] != "QUEUED":
        raise HTTPException(409, "Chỉ hủy job đang QUEUED; job đã gửi Flow không bị hủy ngầm")
    return await repo.update_generation(generation_id, status="CANCELLED", error_message="cancelled by user")

@router.get("/generations/{generation_id}/video")
async def generated_video(generation_id: str):
    value=await repo.get_generation(generation_id)
    if not value or not value.get("video_path"):
        raise HTTPException(404,"Video chưa tồn tại")
    path=Path(value["video_path"])
    if not path.exists():
        raise HTTPException(404,"File video không còn trên đĩa")
    return FileResponse(path,media_type="video/mp4",filename=path.name)

@router.patch("/shots/{shot_id}/review")
async def review_shot(shot_id: str, body: ReviewRequest):
    shot=await repo.update_shot(shot_id,review_status=body.review_status)
    if not shot:
        raise HTTPException(404,"Không tìm thấy shot")
    return shot

@router.post("/projects/{project_id}/concat")
async def concat(project_id: str):
    try:
        path=await service.concat_approved_videos(project_id)
        return FileResponse(path,media_type="video/mp4",filename=path.name)
    except Exception as exc:
        _bad(exc)
