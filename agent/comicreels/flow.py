"""Google Flow generation queue for ComicReels.

Jobs are never created unless the caller explicitly confirms cost. The worker
processes one job at a time and never performs blind automatic retries.
"""
from __future__ import annotations
import asyncio
import json
import logging
import shutil
from pathlib import Path
import aiohttp

from agent.config import FLOW_PROJECT_ID, OUTPUT_DIR, VIDEO_POLL_TIMEOUT
from agent.comicreels import repository as repo
from agent.services.flow_client import get_flow_client
from agent.services.flow_project_session import ensure_session_project
from agent.services.omni_flash import (
    OMNI_FLASH_CREDIT_COST,
    generate_omni_flash_first_frame_video,
)
from agent.sdk.services.operations import _extract_operations, _poll_operations
from agent.worker._parsing import _extract_media_id, _extract_output_url

logger = logging.getLogger(__name__)
COMIC_VIDEO_DIR = OUTPUT_DIR / "comicreels" / "videos"

def estimate_cost(model_family: str, duration_s: int) -> int | None:
    if model_family == "omni_flash":
        return OMNI_FLASH_CREDIT_COST.get(int(duration_s))
    return None

async def resolve_flow_project_id(explicit: str | None, comic_project: dict) -> str:
    pid = (explicit or comic_project.get("flow_project_id") or FLOW_PROJECT_ID or "").strip()
    if pid:
        return pid
    client = get_flow_client()
    if not client.connected:
        raise RuntimeError("Chrome Extension chưa kết nối Google Flow")
    session = await ensure_session_project(client, title=f"ComicReels · {comic_project['name']}")
    pid = str(session.get("project_id") or "")
    if not pid:
        raise RuntimeError("Không lấy được Flow project id")
    await repo.update_project(comic_project["id"], flow_project_id=pid)
    return pid

async def _save_video_from_result(result: dict, generation_id: str) -> tuple[str | None, str | None]:
    media_id = _extract_media_id(result)
    url = _extract_output_url(result)
    COMIC_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    out = COMIC_VIDEO_DIR / f"{generation_id}.mp4"
    if isinstance(url, str) and url.startswith("file://"):
        source = Path(url[7:])
        if source.exists():
            shutil.copyfile(source, out)
            return media_id, str(out)
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Không tải được video Flow: HTTP {resp.status}")
                data = await resp.read()
                if len(data) < 12 or data[4:8] != b"ftyp":
                    raise RuntimeError("Flow trả nội dung không phải MP4")
                out.write_bytes(data)
                return media_id, str(out)
    return media_id, None

async def run_generation(generation: dict) -> None:
    gid = generation["id"]
    shot = await repo.get_shot(generation["shot_id"])
    if not shot:
        raise RuntimeError("Shot không tồn tại")
    panel = await repo.get_panel(shot["panel_id"])
    if not panel or not panel.get("vertical_path"):
        raise RuntimeError("Shot chưa có ảnh 9:16")
    if panel.get("approved_sha256") != panel.get("vertical_sha256"):
        raise RuntimeError("Ảnh panel đã thay đổi sau khi duyệt; cần OK lại trước khi tạo video")
    if shot.get("image_sha256") != panel.get("approved_sha256"):
        raise RuntimeError("Shot không còn khớp hash ảnh đã duyệt")
    project = await repo.get_project(generation["project_id"])
    if not project:
        raise RuntimeError("Dự án không tồn tại")
    client = get_flow_client()
    if not client.connected:
        raise RuntimeError("Chrome Extension chưa kết nối Google Flow")
    flow_pid = await resolve_flow_project_id(generation.get("flow_project_id"), project)

    raw = Path(panel["vertical_path"]).read_bytes()
    import base64, mimetypes
    upload = await client.upload_image(
        base64.b64encode(raw).decode(),
        mime_type=mimetypes.guess_type(panel["vertical_path"])[0] or "image/png",
        project_id=flow_pid,
        file_name=Path(panel["vertical_path"]).name,
    )
    if upload.get("error"):
        raise RuntimeError(f"Upload Flow thất bại: {upload['error']}")
    image_media_id = upload.get("_mediaId")
    if not image_media_id:
        raise RuntimeError("Flow không trả media id cho ảnh")
    await repo.update_generation(gid, image_media_id=image_media_id, flow_project_id=flow_pid)

    family = generation["model_family"]
    duration = int(generation["duration_s"])
    if family == "omni_flash":
        submit = await generate_omni_flash_first_frame_video(
            start_image_media_id=image_media_id,
            prompt=shot["prompt"],
            project_id=flow_pid,
            scene_id=shot["id"],
            duration_s=duration,
            resolution=generation["resolution"],
            aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        )
    else:
        submit = await client.generate_video(
            start_image_media_id=image_media_id,
            prompt=shot["prompt"],
            project_id=flow_pid,
            scene_id=shot["id"],
            aspect_ratio="VIDEO_ASPECT_RATIO_PORTRAIT",
        )
    if submit.get("error") or (isinstance(submit.get("status"), int) and submit["status"] >= 400):
        raise RuntimeError(str(submit.get("error") or submit.get("data") or "Flow submit thất bại"))
    await repo.update_generation(gid, submit_json=json.dumps(submit, ensure_ascii=False))
    operations = _extract_operations(submit)
    if not operations:
        raise RuntimeError("Flow submit không trả operation để theo dõi")
    result = await _poll_operations(client, operations, timeout=VIDEO_POLL_TIMEOUT)
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    media_id, path = await _save_video_from_result(result, gid)
    if not path:
        raise RuntimeError("Video hoàn tất nhưng chưa lấy được file MP4 bền vững")
    await repo.update_generation(gid, status="COMPLETED", video_media_id=media_id, video_path=path)
    await repo.update_shot(shot["id"], status="GENERATED")

class ComicGenerationWorker:
    def __init__(self) -> None:
        self._shutdown = asyncio.Event()
        self.active_generation_id: str | None = None
        self.paused = False

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    async def start(self) -> None:
        while not self._shutdown.is_set():
            if self.paused:
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
                continue
            job = await repo.next_queued_generation()
            if not job:
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
                continue
            self.active_generation_id = job["id"]
            await repo.update_generation(job["id"], status="PROCESSING", error_message=None)
            try:
                await run_generation(job)
            except asyncio.CancelledError:
                await repo.update_generation(job["id"], status="QUEUED", error_message="worker cancelled")
                raise
            except Exception as exc:
                logger.exception("ComicReels generation %s failed: %s", job["id"][:8], exc)
                await repo.update_generation(job["id"], status="FAILED", error_message=str(exc)[:1000])
            finally:
                self.active_generation_id = None

_worker: ComicGenerationWorker | None = None

def get_comic_generation_worker() -> ComicGenerationWorker:
    global _worker
    if _worker is None:
        _worker = ComicGenerationWorker()
    return _worker
