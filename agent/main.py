"""Flow Kit — FastAPI + dashboard WebSocket entry point."""
import asyncio
import json
import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.config import API_HOST, API_PORT
from agent.db.schema import init_db, close_db
from agent.api.characters import router as characters_router
from agent.api.projects import router as projects_router
from agent.api.videos import router as videos_router
from agent.api.scenes import router as scenes_router
from agent.api.requests import router as requests_router
from agent.api.flow import router as flow_router
from agent.api.flow_backend_status import router as flow_backend_status_router
from agent.api.reviews import router as reviews_router
from agent.api.tts import router as tts_router
from agent.api.materials import router as materials_router
from agent.api.music import router as music_router
from agent.api.models import router as models_router
from agent.api.providers import router as providers_router
from agent.api.active_project import router as active_project_router
from agent.api.comicreels import router as comicreels_router
from agent.worker.processor import get_worker_controller
from agent.services.flow_client import get_flow_client
from agent.services.flow_backend_status import read_backend_status
from agent.services.event_bus import event_bus
from agent.sdk import init_sdk

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# ─── FastAPI App ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = get_flow_client()
    await init_db()
    tasks = []
    controller = None
    try:
        # Load custom materials from DB into in-memory registry.
        from agent.db.crud import list_materials as db_list_materials
        from agent.materials import register_material, _BUILTIN_IDS
        try:
            custom_materials = await db_list_materials()
            for m in custom_materials:
                if m["id"] not in _BUILTIN_IDS:
                    register_material(m)
                    logger.info("Loaded custom material from DB: %s", m["id"])
        except Exception as e:
            logger.warning("Failed to load custom materials: %s", e)

        await client.start_backend()
        init_sdk(client)
        logger.info("Flow Kit starting on %s:%d (backend=%s)", API_HOST, API_PORT, client.backend_kind)

        controller = get_worker_controller()
        # Browser-only Flow transport does not own the business queue: the worker
        # remains an application service and must consume pending production and
        # publishing work whenever the app is running.
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, controller.request_shutdown)
        except (NotImplementedError, AttributeError):
            pass
        tasks.append(asyncio.create_task(controller.start()))
        logger.info("Worker started (backend=browser)")

        yield
    finally:
        try:
            if controller is not None:
                controller.request_shutdown()
                await controller.drain()
        finally:
            try:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                try:
                    await client.close_backend()
                finally:
                    await close_db()
                    logger.info("Flow Kit stopped")


app = FastAPI(title="Flow Kit", version="1.3.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_GENERATION_PATHS = {
    "/api/flow/generate-image",
    "/api/flow/generate-video",
    "/api/flow/generate-video-refs",
    "/api/flow/generate-video-omni",
    "/api/flow/generate-video-omni-text",
    "/api/flow/edit-image",
}


@app.middleware("http")
async def flow_caller_observability(request: Request, call_next):
    """Attribute generation submits without logging prompts, media or secrets."""
    response = await call_next(request)
    if request.method == "POST" and request.url.path in _GENERATION_PATHS:
        caller = (request.headers.get("x-flowkit-caller") or "unknown")[:80]
        logger.info(
            "Flow generation request caller=%s path=%s status=%s",
            caller,
            request.url.path,
            response.status_code,
        )
    return response


app.include_router(characters_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(videos_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(requests_router, prefix="/api")
app.include_router(flow_router, prefix="/api")
app.include_router(flow_backend_status_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(tts_router, prefix="/api")
app.include_router(materials_router, prefix="/api")
app.include_router(music_router, prefix="/api")
app.include_router(models_router)
app.include_router(providers_router)
app.include_router(active_project_router)
app.include_router(comicreels_router, prefix="/api")


@app.get("/health")
async def health():
    backend_status = await read_backend_status()
    return {
        "status": "ok",
        "version": app.version,
        "transport": "browser",
        "backend_kind": "browser",
        "backend_ready": backend_status.get("backend_ready"),
        "browser_session_ready": backend_status.get("session_ready"),
        "authentication": backend_status.get("authentication"),
        "lease_held": backend_status.get("lease_held"),
        "reconciliation_required": backend_status.get("reconciliation_required"),
        "pending_intents": backend_status.get("pending_intents"),
        "paid_dispatch_enabled": backend_status.get("paid_dispatch_enabled"),
        "backend_status": backend_status,
    }


# ─── Dashboard WebSocket ──────────────────────────────────────

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    """Dashboard event WebSocket; independent from Flow browser transport."""
    # Reject cross-origin connections (only allow localhost)
    origin = (websocket.headers.get("origin") or "").lower()
    if origin and not any(origin.startswith(p) for p in (
        "http://127.0.0.1", "http://localhost", "chrome-extension://",
    )):
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    await websocket.accept()

    q = event_bus.subscribe()
    try:
        # Send initial snapshot
        backend_status = await read_backend_status()
        controller = get_worker_controller()
        from agent.db import crud
        pending_requests = await crud.list_requests(status="PENDING")
        processing_requests = await crud.list_requests(status="PROCESSING")
        snapshot = {
            "type": "snapshot",
            "health": {
                "status": "ok",
                "transport": "browser",
                "backend_kind": "browser",
                "backend_ready": backend_status.get("backend_ready"),
                "browser_session_ready": backend_status.get("session_ready"),
                "authentication": backend_status.get("authentication"),
                "lease_held": backend_status.get("lease_held"),
                "reconciliation_required": backend_status.get("reconciliation_required"),
                "pending_intents": backend_status.get("pending_intents"),
                "paid_dispatch_enabled": backend_status.get("paid_dispatch_enabled"),
            },
            "requests": pending_requests + processing_requests,
            "worker": {
                "active": controller.active_count,
                "slots": max(0, 5 - controller.active_count),
            },
        }
        await websocket.send_text(json.dumps(snapshot))

        # Forward events from event_bus to this client
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Dashboard WS client disconnected: %s", e)
    finally:
        event_bus.unsubscribe(q)


if __name__ == "__main__":
    import os
    import uvicorn
    reload_enabled = os.environ.get("GLA_RELOAD", "0") == "1"
    uvicorn.run(
        "agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=reload_enabled,
        reload_excludes=["*.db", "*.db-wal", "*.db-shm", "output/*"],
    )
