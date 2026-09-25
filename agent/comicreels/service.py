"""High-level ComicReels workflow services."""
from __future__ import annotations
import hashlib
import io
import json
import mimetypes
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from agent.config import OUTPUT_DIR
from agent.comicreels import image_ops
from agent.comicreels import planner
from agent.comicreels import repository as repo
from agent.comicreels import vision

COMIC_ROOT = OUTPUT_DIR / "comicreels"
SOURCE_DIR = COMIC_ROOT / "sources"
PROJECT_DIR = COMIC_ROOT / "projects"
EXPORT_DIR = COMIC_ROOT / "exports"
ALLOWED_MIME = {"image/png":".png","image/jpeg":".jpg","image/webp":".webp"}
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 80_000_000

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _safe_name(name: str) -> str:
    value = "".join(c for c in name if c.isalnum() or c in " ._-").strip()
    return value[:80] or "ComicReels"

def _panel_dir(project_id: str, panel_id: str) -> Path:
    p = PROJECT_DIR / project_id / "panels" / panel_id
    p.mkdir(parents=True, exist_ok=True)
    return p

async def import_source(name: str, data: bytes, mime: str) -> dict:
    if mime not in ALLOWED_MIME:
        raise ValueError("Chỉ hỗ trợ PNG, JPG/JPEG hoặc WebP")
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Ảnh phải có dung lượng từ 1 byte đến 30 MB")
    digest = _sha(data)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    path = SOURCE_DIR / f"{digest}{ALLOWED_MIME[mime]}"
    if not path.exists():
        path.write_bytes(data)
    try:
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            width, height = im.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise ValueError("Kích thước ảnh không hợp lệ hoặc vượt giới hạn an toàn")
    except Exception:
        if path.exists() and path.stat().st_size == len(data):
            try:
                with Image.open(path) as im:
                    im.verify()
            except Exception:
                path.unlink(missing_ok=True)
        raise ValueError("Nội dung tệp không phải ảnh hợp lệ")
    return await repo.create_project(
        name=_safe_name(name), source_path=str(path), source_sha256=digest,
        source_mime=mime, source_width=width, source_height=height,
    )

def _bbox_inside(b: dict, width: int, height: int) -> bool:
    return (
        int(b.get("x", -1)) >= 0 and int(b.get("y", -1)) >= 0 and
        int(b.get("width", 0)) > 0 and int(b.get("height", 0)) > 0 and
        int(b["x"]) + int(b["width"]) <= width and
        int(b["y"]) + int(b["height"]) <= height
    )

async def analyze_project(project_id: str, *, use_vision: bool = True,
                          replace_existing: bool = False) -> dict:
    project = await repo.get_project(project_id)
    if not project:
        raise ValueError("Không tìm thấy dự án")
    existing = await repo.list_panels(project_id)
    if existing and not replace_existing:
        return await repo.project_bundle(project_id)

    provider = "local_layout"
    raw: dict = {}
    panels = image_ops.detect_panels(project["source_path"])
    if use_vision:
        try:
            raw = await vision.analyze_comic(
                project["source_path"], project["source_width"], project["source_height"]
            )
            candidate = []
            for i, p in enumerate(raw.get("panels", [])):
                b = p.get("bbox") if isinstance(p, dict) else None
                if isinstance(b, dict) and _bbox_inside(b, project["source_width"], project["source_height"]):
                    candidate.append({
                        **b,
                        "display_order": int(p.get("display_order", i)),
                        "confidence": p.get("confidence"),
                    })
            if candidate:
                panels = candidate
                provider = "anthropic_vision"
        except Exception as exc:
            raw = {"vision_warning": str(exc), "panels": []}

    stored_panels = await repo.replace_panels(project_id, panels)
    characters = []
    if isinstance(raw.get("characters"), list):
        characters = [
            {
                "stable_key": c.get("stable_key") or f"character-{i+1}",
                "name": c.get("name") or f"Nhân vật {i+1}",
                "description": c.get("description"),
            }
            for i,c in enumerate(raw["characters"]) if isinstance(c, dict)
        ]
    stored_chars = await repo.replace_characters(project_id, characters) if characters else []
    char_by_key = {c["stable_key"]:c for c in stored_chars}

    raw_panels = sorted(
        [p for p in raw.get("panels", []) if isinstance(p, dict)],
        key=lambda p: int(p.get("display_order", 0)),
    )
    panel_by_order = {p["display_order"]:p for p in stored_panels}
    for rp in raw_panels:
        order = int(rp.get("display_order", 0))
        panel = panel_by_order.get(order)
        if not panel:
            continue
        dialogues = []
        for seq, d in enumerate(rp.get("dialogues", []) or []):
            if not isinstance(d, dict) or not str(d.get("verbatim_text") or ""):
                continue
            global_box = d.get("bbox")
            local_box = None
            if isinstance(global_box, dict):
                local_box = {
                    "x": max(0, int(global_box.get("x",0)) - panel["x"]),
                    "y": max(0, int(global_box.get("y",0)) - panel["y"]),
                    "width": int(global_box.get("width",0)),
                    "height": int(global_box.get("height",0)),
                }
                if not _bbox_inside(local_box, panel["width"], panel["height"]):
                    local_box = None
            speaker = char_by_key.get(d.get("speaker_key"))
            dialogues.append({
                "sequence": int(d.get("sequence", seq)),
                "speaker_id": speaker["id"] if speaker else None,
                "verbatim_text": str(d["verbatim_text"]),
                "confidence": d.get("confidence"),
                "bbox": local_box,
                "user_verified": False,
            })
        if dialogues:
            await repo.replace_dialogues(panel["id"], dialogues)
    await repo.update_project(
        project_id, status="ANALYZED", analysis_provider=provider,
        analysis_json=json.dumps(raw, ensure_ascii=False) if raw else None,
    )
    return await repo.project_bundle(project_id)

async def patch_panel(panel_id: str, *, display_order: int | None = None,
                      bbox: dict | None = None) -> dict:
    panel = await repo.get_panel(panel_id)
    if not panel:
        raise ValueError("Không tìm thấy panel")
    project = await repo.get_project(panel["project_id"])
    if bbox:
        if not _bbox_inside(bbox, project["source_width"], project["source_height"]):
            raise ValueError("BBox panel nằm ngoài ảnh nguồn")
        await repo.invalidate_panel(panel_id, clear_images=True)
        panel = await repo.update_panel(panel_id, **bbox)
    if display_order is not None:
        panel = await repo.update_panel(panel_id, display_order=display_order)
    return panel

async def set_dialogues(panel_id: str, dialogues: list[dict]) -> list[dict]:
    panel = await repo.get_panel(panel_id)
    if not panel:
        raise ValueError("Không tìm thấy panel")
    project_id = panel["project_id"]
    normalized = []
    for d in dialogues:
        speaker_id = d.get("speaker_id")
        if not speaker_id and d.get("speaker_name"):
            c = await repo.upsert_character(project_id, d["speaker_name"])
            speaker_id = c["id"]
        normalized.append({**d, "speaker_id":speaker_id})
    return await repo.replace_dialogues(panel_id, normalized)

async def process_panel(panel_id: str, *, boxes: list[dict] | None = None,
                        padding: int = 8, inpaint_radius: int = 5) -> dict:
    panel = await repo.get_panel(panel_id)
    if not panel:
        raise ValueError("Không tìm thấy panel")
    project = await repo.get_project(panel["project_id"])
    pdir = _panel_dir(project["id"], panel_id)
    crop = pdir / "crop.png"
    mask = pdir / "mask.png"
    clean = pdir / "clean.png"
    vertical = pdir / "vertical.png"
    image_ops.crop_panel(project["source_path"], panel, crop)
    if boxes is None:
        boxes = [d["bbox"] for d in await repo.list_dialogues(panel_id) if d.get("bbox")]
    with Image.open(crop) as im:
        size = im.size
    image_ops.make_mask(size, boxes or [], mask, padding=padding)
    image_ops.clean_with_mask(crop, mask, clean, radius=inpaint_radius)
    _, protected = image_ops.verticalize(clean, vertical)
    if not image_ops.verify_protected_region(clean, vertical, protected):
        raise RuntimeError("Kiểm tra bảo toàn pixel thất bại")
    digest = image_ops.sha256_file(vertical)
    updated = await repo.update_panel(
        panel_id, crop_path=str(crop), mask_path=str(mask), clean_path=str(clean),
        vertical_path=str(vertical), vertical_sha256=digest,
        protected_box_json=json.dumps(protected), approved_sha256=None, approved_at=None,
        status="IMAGES_READY",
    )
    await repo.update_project(project["id"], status="IMAGES_READY")
    return updated

async def process_all_panels(project_id: str) -> dict:
    panels = await repo.list_panels(project_id)
    if not panels:
        raise ValueError("Dự án chưa có panel")
    for p in panels:
        await process_panel(p["id"])
    return await repo.project_bundle(project_id)

async def approve_panel(panel_id: str, expected_sha256: str) -> dict:
    panel = await repo.get_panel(panel_id)
    if not panel or not panel.get("vertical_sha256"):
        raise ValueError("Panel chưa có ảnh 9:16 để duyệt")
    if panel["vertical_sha256"] != expected_sha256:
        raise ValueError("Ảnh đã thay đổi; tải lại phiên bản hiện tại trước khi OK")
    result = await repo.approve_panel(panel_id, expected_sha256)
    panels = await repo.list_panels(result["project_id"])
    if panels and all(p.get("approved_sha256") == p.get("vertical_sha256") and p.get("vertical_sha256") for p in panels):
        await repo.update_project(result["project_id"], status="IMAGE_APPROVED")
    return result

async def plan_shots(project_id: str, **kwargs) -> list[dict]:
    return await planner.plan_project(project_id, **kwargs)

def _asset_lookup(bundle: dict) -> list[Path]:
    paths = [Path(bundle["source_path"])]
    for p in bundle.get("panels", []):
        for key in ("crop_path","mask_path","clean_path","vertical_path"):
            if p.get(key):
                paths.append(Path(p[key]))
    for g in bundle.get("generations", []):
        if g.get("video_path"):
            paths.append(Path(g["video_path"]))
    return [p for p in paths if p.exists()]

async def export_prompt_zip(project_id: str) -> Path:
    bundle = await repo.project_bundle(project_id)
    if not bundle:
        raise ValueError("Không tìm thấy dự án")
    panels = bundle["panels"]
    if not panels or any(p.get("approved_sha256") != p.get("vertical_sha256") for p in panels):
        raise ValueError("Tất cả ảnh phải được duyệt trước khi export")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORT_DIR / f"{project_id}-manual-flow.zip"
    manifest = {
        "project_id":project_id,
        "name":bundle["name"],
        "source_sha256":bundle["source_sha256"],
        "panels":[],
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in panels:
            image_name=f"panel-{p['display_order']+1:02d}.png"
            z.write(p["vertical_path"], f"images/{image_name}")
            shot_items=[]
            for s in p.get("shots", []):
                shot_items.append({
                    "shot_id":s["id"],"duration_s":s["duration_s"],"model_family":s["model_family"],
                    "speaker_id":s.get("speaker_id"),"verbatim_text":s["verbatim_text"],"prompt":s["prompt"],
                })
            manifest["panels"].append({
                "panel_id":p["id"],"order":p["display_order"],"image":f"images/{image_name}",
                "image_sha256":p["vertical_sha256"],"shots":shot_items,
            })
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        lines=[]
        for panel in manifest["panels"]:
            for i,s in enumerate(panel["shots"],1):
                lines += [f"## Panel {panel['order']+1} · Shot {i} · {s['duration_s']}s", s["prompt"], ""]
        z.writestr("prompts.md", "\n".join(lines))
    return out

async def backup_project(project_id: str) -> Path:
    bundle = await repo.project_bundle(project_id)
    if not bundle:
        raise ValueError("Không tìm thấy dự án")
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = EXPORT_DIR / f"{project_id}-backup.zip"
    root = Path(COMIC_ROOT).resolve()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("comicreels-backup.json", json.dumps(bundle, ensure_ascii=False, indent=2))
        for path in _asset_lookup(bundle):
            try:
                rel = path.resolve().relative_to(root)
            except ValueError:
                continue
            z.write(path, f"assets/{rel.as_posix()}")
    return out

async def concat_approved_videos(project_id: str) -> Path:
    shots = await repo.list_shots(project_id)
    if not shots:
        raise ValueError("Dự án chưa có shot")
    videos=[]
    for shot in shots:
        if shot.get("review_status") != "APPROVED":
            raise ValueError("Tất cả shot phải được anh duyệt trước khi ghép")
        gen=await repo.latest_completed_generation_for_shot(shot["id"])
        if not gen or not gen.get("video_path") or not Path(gen["video_path"]).exists():
            raise ValueError("Thiếu file video đã hoàn tất cho một shot")
        videos.append(Path(gen["video_path"]).resolve())
    EXPORT_DIR.mkdir(parents=True,exist_ok=True)
    list_path=EXPORT_DIR/f"{project_id}-concat.txt"
    def ffquote(p: Path) -> str:
        return str(p).replace("'", "'\\''")
    list_path.write_text("".join(f"file '{ffquote(v)}'\n" for v in videos), encoding="utf-8")
    out=EXPORT_DIR/f"{project_id}-final.mp4"
    cmd=["ffmpeg","-y","-f","concat","-safe","0","-i",str(list_path),
         "-c:v","libx264","-c:a","aac","-pix_fmt","yuv420p","-movflags","+faststart",str(out)]
    try:
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=900)
    except FileNotFoundError as exc:
        raise RuntimeError("Không tìm thấy ffmpeg trên máy") from exc
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError("Ghép video thất bại: "+proc.stderr[-1200:])
    return out

async def restore_project_backup(data: bytes, *, name_override: str | None = None) -> dict:
    """Restore a ComicReels backup without trusting paths stored in its JSON manifest."""
    with tempfile.TemporaryDirectory(prefix="comicreels-restore-") as td:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names=z.namelist()
                if "comicreels-backup.json" not in names:
                    raise ValueError("ZIP không phải backup ComicReels")
                for name in names:
                    normalized=Path(name)
                    if normalized.is_absolute() or ".." in normalized.parts:
                        raise ValueError("Backup chứa đường dẫn không an toàn")
                bundle=json.loads(z.read("comicreels-backup.json").decode("utf-8"))
                assets=[n for n in names if n.startswith("assets/")]
                source_name=next((n for n in assets if "/sources/" in "/"+n), None)
                if not source_name:
                    raise ValueError("Backup thiếu ảnh nguồn")
                source_data=z.read(source_name)
                mime=bundle.get("source_mime") or mimetypes.guess_type(source_name)[0] or "image/png"
                project=await import_source(name_override or bundle.get("name") or "ComicReels restore", source_data, mime)
                pid=project["id"]
                old_chars=bundle.get("characters") or []
                new_chars=await repo.replace_characters(pid,[{
                    "stable_key":c.get("stable_key"),
                    "name":c.get("name"),
                    "description":c.get("description"),
                } for c in old_chars])
                key_to_new={c["stable_key"]:c for c in new_chars}
                oldid_to_newchar={
                    c.get("id"):key_to_new.get(c.get("stable_key"),{}).get("id") for c in old_chars
                }
                old_panels=bundle.get("panels") or []
                new_panels=await repo.replace_panels(pid,[{
                    "display_order":p.get("display_order",i),
                    "x":p["x"],"y":p["y"],"width":p["width"],"height":p["height"],
                    "confidence":p.get("confidence"),
                } for i,p in enumerate(old_panels)])
                by_order={p["display_order"]:p for p in new_panels}
                oldshot_to_new={}
                for oldp in old_panels:
                    newp=by_order.get(oldp.get("display_order"))
                    if not newp:
                        continue
                    old_panel_id=oldp.get("id")
                    pdir=_panel_dir(pid,newp["id"])
                    updates={}
                    for key,filename in (("crop_path","crop.png"),("mask_path","mask.png"),
                                         ("clean_path","clean.png"),("vertical_path","vertical.png")):
                        arc=next((n for n in assets if f"/panels/{old_panel_id}/{filename}" in "/"+n),None)
                        if arc:
                            out=pdir/filename
                            out.write_bytes(z.read(arc))
                            updates[key]=str(out)
                    if updates.get("vertical_path"):
                        digest=image_ops.sha256_file(updates["vertical_path"])
                        updates["vertical_sha256"]=digest
                        updates["protected_box_json"]=oldp.get("protected_box_json")
                        if oldp.get("approved_sha256")==digest:
                            updates["approved_sha256"]=digest
                            updates["approved_at"]=oldp.get("approved_at")
                            updates["status"]="APPROVED"
                        else:
                            updates["status"]="IMAGES_READY"
                    await repo.update_panel(newp["id"],**updates)
                    restored_dialogues=[]
                    for d in oldp.get("dialogues") or []:
                        restored_dialogues.append({
                            "id":d.get("id"),
                            "sequence":d.get("sequence",0),
                            "speaker_id":oldid_to_newchar.get(d.get("speaker_id")),
                            "verbatim_text":d.get("verbatim_text",""),
                            "confidence":d.get("confidence"),
                            "bbox":d.get("bbox"),
                            "user_verified":bool(d.get("user_verified")),
                        })
                    if restored_dialogues:
                        await repo.replace_dialogues(newp["id"],restored_dialogues)
                        current=await repo.get_panel(newp["id"])
                        if updates.get("approved_sha256") and current.get("vertical_sha256")==updates["approved_sha256"]:
                            await repo.approve_panel(newp["id"],updates["approved_sha256"])
                    old_shots=oldp.get("shots") or []
                    if old_shots and updates.get("vertical_sha256"):
                        new_shots=await repo.replace_shots(newp["id"],[{
                            "display_order":s.get("display_order",i),
                            "speaker_id":oldid_to_newchar.get(s.get("speaker_id")),
                            "dialogue_ids":s.get("dialogue_ids") or [],
                            "verbatim_text":s.get("verbatim_text",""),
                            "duration_s":s.get("duration_s",8),
                            "model_family":s.get("model_family","omni_flash"),
                            "prompt":s.get("prompt",""),
                            "image_sha256":updates["vertical_sha256"],
                        } for i,s in enumerate(old_shots)])
                        for old_s,new_s in zip(old_shots,new_shots):
                            oldshot_to_new[old_s.get("id")]=new_s["id"]
                            if old_s.get("review_status"):
                                await repo.update_shot(new_s["id"],review_status=old_s["review_status"])
                for g in bundle.get("generations") or []:
                    shot_id=oldshot_to_new.get(g.get("shot_id"))
                    if not shot_id:
                        continue
                    gen=await repo.create_generation(
                        project_id=pid,shot_id=shot_id,
                        idempotency_key=f"restore-{pid}-{g.get('idempotency_key') or g.get('id')}",
                        model_family=g.get("model_family","omni_flash"),
                        duration_s=int(g.get("duration_s",8)),
                        resolution=g.get("resolution","720p"),
                        flow_project_id=g.get("flow_project_id"),
                        cost_estimate=g.get("cost_estimate"),cost_approved=False,
                    )
                    video_arc=next((n for n in assets if g.get("video_path") and n.endswith(Path(g["video_path"]).name)),None)
                    video_path=None
                    if video_arc:
                        vdir=COMIC_ROOT/"videos"
                        vdir.mkdir(parents=True,exist_ok=True)
                        vp=vdir/f"{gen['id']}.mp4"
                        vp.write_bytes(z.read(video_arc))
                        video_path=str(vp)
                    await repo.update_generation(
                        gen["id"],status="COMPLETED" if video_path else "RESTORED",
                        video_media_id=g.get("video_media_id"),video_path=video_path,
                        error_message=None,
                    )
                await repo.update_project(pid,status=bundle.get("status") or "IMPORTED")
                return await repo.project_bundle(pid)
        except zipfile.BadZipFile as exc:
            raise ValueError("Backup ZIP bị hỏng") from exc
