"""
Flow Client — business API over the browser-only Flow backend.

FlowKit now has one Flow transport: BrowserFlowBackend owns the persistent
signed-in browser session and executes validated batchexecute requests in that
leased session. Business callers keep using FlowClient response shapes and do
not depend on browser internals.
"""
import asyncio
import json
import logging
import threading
import time
from typing import Optional

from agent.config import (
    VIDEO_MODELS,
    FLOW_PROJECT_ID, FLOW_ALLOW_DEGRADED,
    DEFAULT_PAYGATE_TIER,
    FLOW_GENERATION_MIN_INTERVAL_S, FLOW_GENERATION_MAX_CONCURRENT,
    FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S,
)
from agent import config as _config
from agent.services import flow_batch as fb
from agent.services.flow_backend import FlowBackend
from agent.services.flow_backend_selection import BackendSelection, resolve_backend_selection

logger = logging.getLogger(__name__)

class FlowClient:
    """Flow business API over one browser backend."""

    def __init__(self, backend: FlowBackend | None = None):
        if backend is None:
            # Preserve direct FlowClient() construction as a browser-only API.
            # get_flow_client() still owns production singleton/error caching.
            from agent.services.flow_browser_backend import BrowserFlowBackend
            backend = BrowserFlowBackend()
        self._backend = backend

        # Compatibility sentinel only until Task 6 removes legacy status fields.
        # It is never populated and cannot route transport.
        self._flow_key = None

        # Existing business-level generation guards remain intact. They do not
        # authorize a paid browser effect; the paid gate remains separate.
        self._generation_slots = asyncio.Semaphore(FLOW_GENERATION_MAX_CONCURRENT)
        self._generation_rate_gate = asyncio.Lock()
        self._generation_last_submit_at = 0.0
        self._generation_unusual_until = 0.0
        self._generation_last_unusual_at: Optional[float] = None
        self._generation_last_unusual_rpc: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._backend.ready

    @property
    def extension_connected(self) -> bool:
        """Temporary read-only compatibility field; Flow extension is removed."""
        return False

    @property
    def backend(self) -> FlowBackend:
        return self._backend

    @property
    def backend_kind(self) -> str:
        return self._backend.kind

    @property
    def paid_dispatch_enabled(self) -> bool:
        return self._backend.paid_dispatch_enabled

    @property
    def session_owner_key(self) -> str:
        return self._backend.session_owner_key

    async def start_backend(self) -> None:
        await self._backend.start()

    async def close_backend(self) -> None:
        await self._backend.close()

    async def backend_readiness(self) -> dict:
        return await self._backend.check_readiness()

    async def open_project(self, project_id: str) -> dict:
        return await self._backend.open_project(project_id)

    @property
    def generation_guard_status(self) -> dict:
        remaining = max(0.0, self._generation_unusual_until - time.monotonic())
        return {
            "cooldown_active": remaining > 0,
            "cooldown_remaining_s": round(remaining, 3),
            "last_unusual_activity_at": self._generation_last_unusual_at,
            "last_unusual_activity_rpc": self._generation_last_unusual_rpc,
        }

    @property
    def ws_stats(self) -> dict:
        """Temporary legacy status shape with no extension transport behind it."""
        return {
            "connected": False,
            "active_connections": 0,
            "authenticated_connections": 0,
            "extension_versions": [],
            "flow_url_supported": None,
            "connects": 0,
            "disconnects": 0,
            "uptime_s": None,
            "transport_removed": True,
        }

    async def refresh_project_urls(self, project_id: str) -> dict:
        """Re-sign every stored media url for a project.

        The batch path can do this properly: the media rpc answers a media id
        with a freshly signed url, so we walk the project's scenes and entities
        and refresh each id we hold.
        """
        from agent.db import crud

        # (media_id, kind) -> the scene/character fields it should land in
        targets: dict[tuple[str, str], list[tuple[str, str, str]]] = {}

        def want(media_id, kind, table, row_id, field):
            if media_id and self._UUID_RE.match(media_id):
                targets.setdefault((media_id, kind), []).append((table, row_id, field))

        scenes = []
        for video in await crud.list_videos(project_id):
            scenes.extend(await crud.list_scenes(video["id"]))

        for scene in scenes:
            for prefix in ("vertical", "horizontal"):
                want(scene.get(f"{prefix}_image_media_id"), "image",
                     "scene", scene["id"], f"{prefix}_image_url")
                want(scene.get(f"{prefix}_video_media_id"), "video",
                     "scene", scene["id"], f"{prefix}_video_url")
                want(scene.get(f"{prefix}_upscale_media_id"), "video",
                     "scene", scene["id"], f"{prefix}_upscale_url")
        for char in await crud.get_project_characters(project_id):
            want(char.get("media_id"), "image", "character", char["id"], "reference_image_url")

        refreshed = 0
        for (media_id, kind), fields in targets.items():
            try:
                urls = await self._batch_media_urls(media_id)
            except Exception as e:
                logger.warning("Refresh failed for media %s: %s", media_id[:12], e)
                continue
            url = urls.video if kind == "video" else urls.image
            if not url:
                continue
            for table, row_id, field in fields:
                if table == "scene":
                    await crud.update_scene(row_id, **{field: url})
                else:
                    await crud.update_character(row_id, **{field: url})
                refreshed += 1

        logger.info("Refreshed %d/%d media urls for project %s",
                    refreshed, len(targets), project_id[:12])
        return {"refreshed": refreshed, "found": len(targets)}

    async def _send(self, method: str, params: dict, timeout: float = 300) -> dict:
        """Dispatch through the selected backend; retain the business API seam."""
        return await self._backend.execute(method, params, timeout)

    # ─── batchexecute transport ──────────────────────────────
    #
    # Flow's rewritten frontend signs every call with the session cookie plus a
    # per-page `at` token, and generation also carries single-use browser proof.
    # FlowClient builds the business envelope; BrowserFlowBackend executes it in
    # the leased signed-in flow.google.com session.

    async def batch_rpc(self, rpcid: str, freq: str,
                        captcha_action: str | None = None,
                        match: str | None = None,
                        timeout: float = 300,
                        project_id: str | None = None) -> dict:
        """Run one batchexecute RPC in the Flow page. Returns the raw body.

        CAPTCHA-bearing image/video submits pass through one process-wide guard
        so direct API callers cannot accidentally bypass the worker limiter.
        Non-generation RPCs (polling/media/project metadata) remain unthrottled.
        """
        params: dict = {"rpcid": rpcid, "freq": freq}
        if project_id:
            params["projectId"] = project_id
        if captcha_action:
            params["captchaAction"] = captcha_action
        if match:
            params["match"] = match

        is_generation = captcha_action in {fb.CAPTCHA_IMAGE, fb.CAPTCHA_VIDEO}
        if not is_generation:
            return await self._send("batch_rpc", params, timeout=timeout)

        now = time.monotonic()
        if now < self._generation_unusual_until:
            remaining = max(1, int(self._generation_unusual_until - now + 0.999))
            return {
                "status": 429,
                "error": (
                    "PUBLIC_ERROR_UNUSUAL_ACTIVITY local cooldown active; "
                    f"retry in about {remaining}s"
                ),
            }

        await self._generation_slots.acquire()
        try:
            async with self._generation_rate_gate:
                now = time.monotonic()
                if now < self._generation_unusual_until:
                    remaining = max(1, int(self._generation_unusual_until - now + 0.999))
                    return {
                        "status": 429,
                        "error": (
                            "PUBLIC_ERROR_UNUSUAL_ACTIVITY local cooldown active; "
                            f"retry in about {remaining}s"
                        ),
                    }
                delay = FLOW_GENERATION_MIN_INTERVAL_S - (
                    now - self._generation_last_submit_at
                )
                if delay > 0:
                    await asyncio.sleep(delay)
                self._generation_last_submit_at = time.monotonic()

            result = await self._send("batch_rpc", params, timeout=timeout)
            blob = f"{result.get('error', '')} {result.get('data', '')}"
            if (
                "PUBLIC_ERROR_UNUSUAL_ACTIVITY" in blob
                or "unusual activity" in blob.lower()
            ):
                self._generation_unusual_until = max(
                    self._generation_unusual_until,
                    time.monotonic() + FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S,
                )
                self._generation_last_unusual_at = time.time()
                self._generation_last_unusual_rpc = rpcid
                logger.warning(
                    "Google unusual-activity block detected; pausing generation submits for %.0fs",
                    FLOW_UNUSUAL_ACTIVITY_COOLDOWN_S,
                )
            return result
        finally:
            self._generation_slots.release()

    async def _batch_payload(self, rpcid: str, freq: str,
                             captcha_action: str | None = None,
                             timeout: float = 300,
                             project_id: str | None = None):
        """One RPC, unwrapped to its inner payload. Raises on anything else."""
        result = await self.batch_rpc(
            rpcid, freq, captcha_action, timeout=timeout, project_id=project_id
        )
        if result.get("error"):
            raise fb.FlowBatchError(f"{rpcid}: {result['error']}")
        return fb.first_payload(result.get("data") or "", rpcid)

    def _batch_project_id(self, project_id: str) -> str:
        """The Flow project an RPC is scoped to.

        Flow Kit stores the Flow project uuid as the local project id. Public
        direct endpoints resolve project-less work through the persistent
        session-project lease before reaching this lower-level helper. The
        legacy FLOW_PROJECT_ID fallback remains for older internal callers.
        """
        if project_id and self._UUID_RE.match(str(project_id)):
            return str(project_id)
        if FLOW_PROJECT_ID:
            return FLOW_PROJECT_ID
        raise fb.FlowBatchError(
            "NO_FLOW_PROJECT: every batchexecute call is scoped to a Flow project. "
            "Create one in the Flow UI and pin its uuid as FLOW_PROJECT_ID."
        )

    def _batch_image_model(self, override: str | None = None) -> str:
        # Read through the module: PATCH /api/models hot-reloads both of these.
        nickname = _config.DEFAULT_IMAGE_MODEL
        return fb.resolve_image_model(
            override or _config.IMAGE_MODELS.get(nickname) or nickname
        )

    def _batch_video_model(self, tier: str, gen_type: str, aspect_ratio: str) -> str:
        legacy = VIDEO_MODELS.get(tier, {}).get(gen_type, {}).get(aspect_ratio)
        return fb.resolve_video_model(legacy)

    async def _remember_operation(self, operation_id: str, project_id: str):
        """Persist operation ownership through the browser backend journal."""
        result = await self._backend.bind_operation(operation_id, project_id)
        if not isinstance(result, dict) or result.get("status") != 200:
            code = result.get("error") if isinstance(result, dict) else None
            raise fb.FlowBatchError(code or "OPERATION_BINDING_REQUIRED")
        return result

    async def _operation_project_id(self, operation_id: str) -> str:
        """Resolve operation ownership from durable browser state only."""
        result = await self._backend.operation_project(operation_id)
        if not isinstance(result, dict) or result.get("status") != 200:
            code = result.get("error") if isinstance(result, dict) else None
            raise fb.FlowBatchError(code or "OPERATION_BINDING_REQUIRED")
        data = result.get("data")
        project_id = data.get("projectId") if isinstance(data, dict) else None
        if not isinstance(project_id, str) or not self._UUID_RE.match(project_id):
            raise fb.FlowBatchError("OPERATION_BINDING_REQUIRED")
        return project_id

    # ─── High-level API Methods ──────────────────────────────

    def flow_project_id(self, requested: str | None = None) -> str | None:
        """Validate an explicitly requested Flow project id."""
        if requested and self._UUID_RE.match(requested):
            return requested
        return None

    async def create_project(self, project_title: str, tool_name: str = "PINHOLE") -> dict:
        try:
            result = await self.batch_rpc(
                fb.RPC_CREATE_PROJECT,
                fb.create_project_request(project_title),
                timeout=60,
            )
            if result.get("error"):
                return {"status": result.get("status", 502), "error": result["error"]}
            payload = fb.first_payload(result.get("data") or "", fb.RPC_CREATE_PROJECT)
            pid, title = fb.read_created_project(payload)
            if not self._UUID_RE.match(pid):
                raise fb.FlowBatchError(f"invalid project id returned by Flow: {pid!r}")
            logger.info("Flow project created: %s title=%r", pid, title or project_title)
            return {"status": 200, "data": {"projectId": pid, "title": title or project_title}}
        except Exception as exc:
            return _batch_error(exc)

    async def generate_images(self, prompt: str, project_id: str,
                               aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT",
                               user_paygate_tier: str = "PAYGATE_TIER_TWO",
                               character_media_ids: list[str] = None,
                               image_model: str = None,
                               count: int = 1,
                               seed: int | None = None,
                               base_media_id: str | None = None,
                               idempotency_key: str | None = None,
                               paid_authorization=None) -> dict:
        """Submit exactly one paid image through the durable browser gate.

        The business response keeps the historical media[] shape. Durable state
        stores only project/media UUIDs; signed URLs are refreshed afterwards by
        a separate read-only media RPC. Missing URL data never turns a completed
        paid receipt back into a generation failure.
        """
        if count != 1:
            return {
                "status": 409,
                "error": "PAID_SINGLE_SHOT_REQUIRED",
                "effect": "not_submitted",
            }
        if not isinstance(idempotency_key, str) or not idempotency_key:
            return {
                "status": 409,
                "error": "PAID_IDEMPOTENCY_REQUIRED",
                "effect": "not_submitted",
            }

        try:
            pid = self._batch_project_id(project_id)
            model = self._batch_image_model(image_model)
            refs = list(character_media_ids or []) or None
            freq = fb.image_request(
                prompt, pid, count=1, aspect=aspect_ratio, seed=seed,
                model=model, ref_media_ids=refs, base_media_id=base_media_id,
            )
        except Exception as exc:
            return _batch_error(exc)

        try:
            result = await self._backend.submit_paid_image(
                {
                    "rpcid": fb.RPC_GEN_IMAGE,
                    "freq": freq,
                    "projectId": pid,
                    "captchaAction": fb.CAPTCHA_IMAGE,
                },
                idempotency_key=idempotency_key,
                authorization=paid_authorization,
                timeout=300,
            )
        except Exception:
            # The bridge may fail after the browser accepted the effect. Never
            # infer non-submission, leak browser details or attempt another paid call.
            return {
                "status": 409,
                "error": "PAID_RECONCILIATION_REQUIRED",
                "effect": "unknown",
            }
        if (not isinstance(result, dict) or result.get("status") != 200
                or result.get("effect") != "completed"):
            return result if isinstance(result, dict) else {
                "status": 502,
                "error": "PAID_RECONCILIATION_REQUIRED",
                "effect": "unknown",
            }

        data = result.get("data")
        if not isinstance(data, dict):
            return {
                "status": 409,
                "error": "PAID_RECONCILIATION_REQUIRED",
                "effect": "unknown",
            }
        media_id = data.get("mediaId")
        if not isinstance(media_id, str) or not self._UUID_RE.match(media_id):
            return {
                "status": 409,
                "error": "PAID_RECONCILIATION_REQUIRED",
                "effect": "unknown",
            }

        # Receipt is already durable at this point. URL lookup is read-only and
        # must never cause a paid resend or downgrade a completed effect.
        image_url = ""
        try:
            media = await self.get_media(media_id)
            if isinstance(media, dict) and media.get("status") == 200:
                record = media.get("data")
                if isinstance(record, dict):
                    image = record.get("image")
                    if isinstance(image, dict):
                        value = image.get("fifeUrl")
                        if isinstance(value, str):
                            image_url = value
        except Exception:
            image_url = ""

        generated = fb.GeneratedImage(media_id=media_id, url=image_url)
        return {
            "status": 200,
            "data": {
                "media": [_as_media_record(generated)],
                "requested_count": 1,
                "generated_count": 1,
                "complete": True,
            },
            "effect": "completed",
            "reused": result.get("reused") is True,
        }

    async def edit_image(self, prompt: str, source_media_id: str,
                          project_id: str,
                          aspect_ratio: str = "IMAGE_ASPECT_RATIO_PORTRAIT",
                          user_paygate_tier: str = "PAYGATE_TIER_ONE",
                          character_media_ids: list[str] = None,
                          image_model: str = None,
                          count: int = 1,
                          seed: int | None = None,
                          idempotency_key: str | None = None,
                          paid_authorization=None) -> dict:
        """Edit an image with the source encoded as Flow's BASE_IMAGE input.

        Additional references remain REFERENCE inputs. Sending the source as a
        generic reference conditions a fresh generation; BASE_IMAGE is the wire
        shape the current Flow editor uses for an actual image edit/refine.
        """

        refs = [mid for mid in (character_media_ids or []) if mid != source_media_id]
        return await self.generate_images(
            prompt=prompt,
            project_id=project_id,
            aspect_ratio=aspect_ratio,
            user_paygate_tier=user_paygate_tier,
            character_media_ids=refs,
            image_model=image_model,
            count=count,
            seed=seed,
            base_media_id=source_media_id,
            idempotency_key=idempotency_key,
            paid_authorization=paid_authorization,
        )

    async def upscale_image(self, media_id: str, project_id: str,
                            resolution: str = "2K") -> dict:
        """Return Flow's synchronous 2K/4K image upscale as base64 JPEG data."""
        try:
            pid = self._batch_project_id(project_id)
            freq = fb.image_upscale_request(media_id, resolution)
            payload = await self._batch_payload(
                fb.RPC_UPSCALE_IMAGE,
                freq,
                fb.CAPTCHA_IMAGE,
                timeout=150,
                project_id=pid,
            )
            encoded = fb.read_upscaled_image(payload)
        except Exception as e:
            return _batch_error(e)
        return {
            "status": 200,
            "data": {
                "media_id": media_id,
                "project_id": pid,
                "resolution": str(resolution).upper(),
                "encodedImage": encoded,
                "contentType": "image/jpeg",
            },
        }

    async def generate_video(self, start_image_media_id: str, prompt: str,
                              project_id: str, scene_id: str,
                              aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                              end_image_media_id: str = None,
                              user_paygate_tier: str = "PAYGATE_TIER_TWO") -> dict:
        """Submit an i2v generation. Returns operations for the poller."""

        if end_image_media_id:
            if not FLOW_ALLOW_DEGRADED:
                return {"error": _unsupported(
                    "start+end frame chaining",
                    "the new payload's end-image slot was never captured",
                )}
            logger.warning(
                "Scene %s: dropping end frame %s — chaining is not on the batch path, "
                "running plain i2v because FLOW_ALLOW_DEGRADED=1",
                str(scene_id)[:12], end_image_media_id[:12])

        gen_type = "start_end_frame_2_video" if end_image_media_id else "frame_2_video"
        try:
            pid = self._batch_project_id(project_id)
            freq = fb.video_request(
                prompt, pid, start_image_media_id, aspect=aspect_ratio,
                model=self._batch_video_model(user_paygate_tier, gen_type, aspect_ratio),
            )
            payload = await self._batch_payload(
                fb.RPC_GEN_VIDEO, freq, fb.CAPTCHA_VIDEO, timeout=120,
                project_id=pid)
            operation = fb.read_operation(payload)
        except Exception as e:
            return _batch_error(e)

        try:
            await self._remember_operation(operation.operation_id, pid)
        except Exception as exc:
            # The remote submit may already have happened. Never suggest that a
            # missing local binding makes the paid/remote effect safe to resend.
            return {
                "status": 409,
                "error": "OPERATION_BINDING_REQUIRED",
                "effect": "unknown",
            }
        return {"status": 200, "data": {"operations": [_as_pending_operation(operation.operation_id)]}}

    async def generate_video_from_references(self, reference_media_ids: list[str],
                                              prompt: str, project_id: str, scene_id: str,
                                              aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                                              user_paygate_tier: str = "PAYGATE_TIER_TWO") -> dict:
        """Generate video from multiple reference images (r2v)."""

        if not FLOW_ALLOW_DEGRADED:
            return {"error": _unsupported(
                "reference-to-video (r2v)",
                "its payload was never captured off the new UI",
            )}
        if not reference_media_ids:
            return {"error": "No reference media_ids for r2v"}
        logger.warning(
            "Scene %s: r2v is not on the batch path — running i2v off the first "
            "reference %s because FLOW_ALLOW_DEGRADED=1",
            str(scene_id)[:12], reference_media_ids[0][:12])
        return await self.generate_video(
            start_image_media_id=reference_media_ids[0], prompt=prompt,
            project_id=project_id, scene_id=scene_id, aspect_ratio=aspect_ratio,
            user_paygate_tier=user_paygate_tier,
        )

    async def upscale_video(self, media_id: str, scene_id: str,
                             aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT",
                             resolution: str = "VIDEO_RESOLUTION_4K") -> dict:
        """Upscale a video."""
        return {"error": _unsupported(
            "video upscale",
            "no upsampler rpc appears in the new frontend's captures",
        )}

    async def check_video_status(self, operations: list[dict]) -> dict:
        """One poll round for each submitted operation.

        Three signals have to agree before a clip can be downloaded, and they
        arrive out of order:

        * the operation poll says how the job is going — but it can sit at no
          status at all on a job that finished, and a "Media not found."
          complaint on it is survivable rather than fatal;
        * the project listing is what actually gains a media id;
        * the media record serves the poster image first and grows the
          ``/video/`` url in later.

        So an operation only reports SUCCESSFUL once there is a video url.
        Everything short of that is PENDING, and the caller's own poll loop
        owns the timeout.
        """

        out = []
        for entry in operations or []:
            op_id = (entry.get("operation") or {}).get("name") or entry.get("name") or ""
            if not op_id:
                out.append({"operation": {}, "status": "MEDIA_GENERATION_STATUS_FAILED",
                            "error": "operation carried no name"})
                continue
            try:
                out.append(await self._poll_batch_operation(op_id))
            except Exception as e:
                # A hiccup on one poll round costs a round, not the job.
                logger.warning("Operation %s poll failed: %s", op_id[:20], e)
                out.append(_as_pending_operation(op_id, error=str(e)))
        return {"status": 200, "data": {"operations": out}}

    async def _poll_batch_operation(self, operation_id: str) -> dict:
        """Poll from durable binding + current listing; no RAM cache is authoritative."""
        try:
            project_id = await self._operation_project_id(operation_id)
        except Exception as error:
            return _as_pending_operation(operation_id, error=str(error))

        media_id, complaint = await self._find_operation_media(
            operation_id, project_id=project_id,
        )
        if not media_id:
            return _as_pending_operation(operation_id, error=complaint)

        try:
            urls = await self._batch_media_urls(media_id, project_id=project_id)
        except Exception as error:
            return _as_pending_operation(operation_id, error=str(error), media_id=media_id)

        if not urls.video:
            # The listing has the id but the clip is still being written.
            return _as_pending_operation(operation_id, error=complaint, media_id=media_id)

        return {
            "operation": {
                "name": operation_id,
                "metadata": {"video": {"mediaId": media_id, "fifeUrl": urls.video}},
            },
            "status": "MEDIA_GENERATION_STATUS_SUCCESSFUL",
        }

    async def _find_operation_media(
        self, operation_id: str, *, project_id: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Read current operation diagnostics and always consult its project listing.

        Durable operation/project binding is the authority. The operation poll is
        diagnostic only; every round may discover media from the current listing,
        so restart with empty RAM caches cannot delay correctness.
        """
        if project_id is None:
            try:
                project_id = await self._operation_project_id(operation_id)
            except Exception as error:
                return None, str(error)

        complaint = None
        try:
            operation = fb.read_operation(
                await self._batch_payload(
                    fb.RPC_OPERATION, fb.operation_request(operation_id), timeout=60)
            )
            complaint = operation.error
            if operation.project_id and operation.project_id != project_id:
                return None, "OPERATION_BINDING_CONFLICT"
        except Exception as error:
            # A decayed/unreadable operation still remains discoverable in the
            # durable project's listing, so read failure never blocks discovery.
            logger.debug(
                "Operation %s poll unreadable (%s); consulting durable project listing",
                operation_id[:20], error,
            )

        return await self._media_id_for(operation_id, project_id), complaint

    async def _media_id_for(self, operation_id: str, project_id: str) -> str | None:
        """Find an operation's media id in the project listing.

        Requests an 800-byte browser-side window around the operation id
        rather than the whole listing — that payload is past 17 MB and grows
        with every generation, so anything that ships it whole gets truncated
        and loses roughly half of all lookups.
        """
        result = await self.batch_rpc(
            fb.RPC_PROJECT_MEDIA, fb.project_media_request(project_id),
            match=operation_id, timeout=120,
        )
        if result.get("error"):
            raise fb.FlowBatchError(f"{fb.RPC_PROJECT_MEDIA}: {result['error']}")
        raw = result.get("data") or ""
        media_id = fb.find_media_id_in_text(raw, operation_id)
        if not media_id and raw.lstrip().startswith(")]}"):
            # A backend that cannot filter may hand back the whole envelope.
            try:
                media_id = fb.find_media_id(
                    fb.first_payload(raw, fb.RPC_PROJECT_MEDIA), operation_id)
            except (fb.FlowBatchError, fb.RpcError, json.JSONDecodeError):
                media_id = None
        return media_id

    async def _batch_media_urls(
        self, media_id: str, project_id: str | None = None,
    ) -> "fb.MediaUrls":
        payload = await self._batch_payload(
            fb.RPC_MEDIA, fb.media_request(media_id), timeout=60,
            project_id=project_id,
        )
        return fb.read_media_urls(payload, media_id)

    async def get_credits(self) -> dict:
        """Get user credits and tier.

        The new frontend has no captured credits rpc, and the tier no longer
        selects a model — aspect is its own slot and the model names are
        fixed — so on the batch path this answers with the configured default
        rather than pretending to know.
        """
        return {"status": 200, "data": {
            "userPaygateTier": DEFAULT_PAYGATE_TIER,
            "note": "batchexecute path: tier is configured (DEFAULT_PAYGATE_TIER), not fetched",
        }}

    async def validate_media_id(self, media_id: str) -> bool:
        """Check if a mediaId is still valid."""
        result = await self.get_media(media_id)
        status = result.get("status", 500)
        return isinstance(status, int) and status == 200

    async def get_media(self, media_id: str) -> dict:
        """Fetch a media record, which is where a fresh signed url lives."""
        try:
            urls = await self._batch_media_urls(media_id)
        except Exception as e:
            return _batch_error(e)
        if not urls.video and not urls.image:
            return {"status": 404, "error": f"No urls for media {media_id}"}
        data: dict = {}
        if urls.video:
            data["video"] = {"fifeUrl": urls.video}
        if urls.image:
            data["image"] = {"fifeUrl": urls.image}
        return {"status": 200, "data": data}

    async def upload_image(self, image_base64: str, mime_type: str = "image/jpeg",
                            project_id: str = "", file_name: str = "image.jpg") -> dict:
        """Upload an image into the project so it can be used as a reference."""
        try:
            pid = self._batch_project_id(project_id)
            payload = await self._batch_payload(
                fb.RPC_UPLOAD_IMAGE,
                fb.upload_request(image_base64, pid, mime_type, file_name),
                fb.CAPTCHA_IMAGE, timeout=120, project_id=pid,
            )
            media_id = fb.read_uploaded_media_id(payload)
        except Exception as e:
            return _batch_error(e)
        return {"status": 200, "data": {"media": {"name": media_id}}, "_mediaId": media_id}

# ─── Response shaping ────────────────────────────────────────
#
# The batch path answers in Flow's positional arrays; everything downstream
# reads the old REST shapes. These put one back on the other so the parsers,
# the poller and the DB writers never learn which transport ran.

_CAPTURE_HINT = "see docs/CAPTURE.md to record its payload off the new UI"

def _unsupported(feature: str, why: str) -> str:
    return f"UNSUPPORTED_ON_BATCH_API: {feature} — {why}; {_CAPTURE_HINT}."


def _batch_error(exc: Exception) -> dict:
    """An exception from the batch path, in the error shape callers expect."""
    return {"status": 502, "error": f"{type(exc).__name__}: {exc}"}


def _as_media_record(image: "fb.GeneratedImage") -> dict:
    """One generated image, in the REST response's `media[]` shape."""
    return {
        "name": image.media_id,
        "image": {"generatedImage": {"mediaId": image.media_id, "fifeUrl": image.url}},
    }


def _as_pending_operation(operation_id: str, error: str | None = None,
                          media_id: str | None = None) -> dict:
    """An operation that has not produced a fetchable clip yet.

    ``error`` is carried, not acted on: a poll complaint is a diagnostic that
    finished jobs also report, so it exists to make a timeout message useful.
    """
    entry: dict = {
        "operation": {"name": operation_id},
        "status": "MEDIA_GENERATION_STATUS_PENDING",
    }
    if media_id:
        entry["operation"]["metadata"] = {"video": {"mediaId": media_id}}
    if error:
        entry["complaint"] = error
    return entry




# Browser-only singleton. The first valid selection is immutable for the process.
# There is no extension fallback/rollback transport. A construction failure is
# sticky until process restart so repeated getters cannot create multiple profiles
# or silently revive a removed backend.
_client: Optional[FlowClient] = None
_client_selection: Optional[BackendSelection] = None
_client_initialization_error: Optional[str] = None
_client_lock = threading.Lock()


def get_flow_client() -> FlowClient:
    """Construct the sole browser-backed Flow client without launching it."""
    global _client, _client_selection, _client_initialization_error
    with _client_lock:
        if _client is not None:
            return _client
        if _client_initialization_error is not None:
            raise RuntimeError(_client_initialization_error) from None
        if _client_selection is None:
            # Reject obsolete/invalid backend configuration before importing
            # browser dependencies or touching the persistent profile.
            _client_selection = resolve_backend_selection()
        try:
            from agent.services.flow_browser_backend import BrowserFlowBackend
            candidate = FlowClient(backend=BrowserFlowBackend())
        except Exception:
            # Retain only a fixed public code; never store profile paths, auth
            # details or native exceptions. Do not retry or fall back.
            _client_initialization_error = "FLOW_BACKEND_INITIALIZATION_FAILED"
            raise RuntimeError(_client_initialization_error) from None
        _client = candidate
        return _client
