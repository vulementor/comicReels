# Flow Kit — Architecture

## Overview

Flow Kit is a standalone AI-video production system with a Python/FastAPI/SQLite
business layer and one Flow transport: `BrowserFlowBackend`. The backend owns a
leased persistent signed-in `flow.google.com` browser profile and executes
validated Flow browser recipes through the pinned `kabin_browser_semantic`
integration.

The independent `/ws/dashboard` endpoint carries dashboard events only. It is
not Flow transport and does not establish Flow readiness.

## Runtime components

### 1. Browser Flow transport

- `FlowClient` remains the business API.
- `BrowserFlowBackend` is the sole Flow backend.
- `FlowBrowserDriver` owns Flow-specific browser recipes.
- `FlowBrowserSessionProvider` owns one existing persistent profile under an
  explicit lease.
- `BrowserStateStore` persists project/operation bindings and effect
  intent/receipt state.
- KBS provides generic browser semantics; Flow selectors/RPC meaning remain in
  Flow Kit.
- Browser readiness requires current session/authentication/lease evidence.
- Paid dispatch is a separate explicit gate. A ready browser never grants paid
  authorization.
- Unknown paid outcomes are not automatically resent.

### 2. Local agent

- CRUD for projects, videos, scenes and entities.
- Durable request/job tracking in SQLite.
- Queue worker and restart/resume behavior.
- Review/regeneration, post-processing, TTS, concat, branding and YouTube tools.
- REST API on port 8100.
- Independent dashboard event WebSocket at `/ws/dashboard`.

## Stack

- Agent: Python 3.10+, FastAPI, SQLite/aiosqlite.
- Browser transport: persistent Camoufox/Firefox-compatible profile + KBS.
- Dashboard: React/Vite.
- Post-processing: ffmpeg/ffprobe.

---
## Database Schema

### character (STANDALONE — not owned by project)
```sql
CREATE TABLE character (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    entity_type         TEXT NOT NULL DEFAULT 'character'
                        CHECK(entity_type IN ('character','location','creature','visual_asset','generic_troop','faction')),
    description         TEXT,
    image_prompt        TEXT,
    voice_description   TEXT,       -- max ~30 words, for video prompt voice consistency
    reference_image_url TEXT,
    media_id            TEXT,       -- UUID format from uploadImage
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now'))
);
```

### project
```sql
CREATE TABLE project (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    description         TEXT,
    thumbnail_url       TEXT,
    language            TEXT DEFAULT 'en',
    status              TEXT DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','ARCHIVED')),
    created_at          DATETIME DEFAULT (datetime('now')),
    updated_at          DATETIME DEFAULT (datetime('now'))
);
```

### project_character (link table, M:N)
```sql
CREATE TABLE project_character (
    project_id   TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    character_id TEXT NOT NULL REFERENCES character(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, character_id)
);
```

### video (belongs to project)
```sql
CREATE TABLE video (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description     TEXT,
    display_order   INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','PROCESSING','COMPLETED','FAILED')),
    vertical_url    TEXT,
    horizontal_url  TEXT,
    thumbnail_url   TEXT,
    duration        REAL,
    resolution      TEXT,
    youtube_id      TEXT,
    privacy         TEXT DEFAULT 'unlisted',
    tags            TEXT,
    created_at      DATETIME DEFAULT (datetime('now')),
    updated_at      DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_video_project ON video(project_id);
```

### scene (belongs to video, chainable, dual orientation)
```sql
CREATE TABLE scene (
    id                  TEXT PRIMARY KEY,
    video_id            TEXT NOT NULL REFERENCES video(id) ON DELETE CASCADE,
    display_order       INTEGER DEFAULT 0,
    prompt              TEXT,           -- image generation prompt (frame 0)
    image_prompt        TEXT,           -- override for image gen (optional)
    video_prompt        TEXT,           -- sub-clip timing: "0-3s: ... 3-5s: ... 5-8s: ..."
    character_names     TEXT,           -- JSON array of reference entity names

    -- Chain
    parent_scene_id     TEXT REFERENCES scene(id),
    chain_type          TEXT DEFAULT 'ROOT' CHECK(chain_type IN ('ROOT','CONTINUATION','INSERT')),

    -- Vertical
    vertical_image_url              TEXT,
    vertical_video_url              TEXT,
    vertical_upscale_url            TEXT,
    vertical_image_media_id     TEXT,
    vertical_video_media_id     TEXT,
    vertical_upscale_media_id   TEXT,
    vertical_image_status           TEXT DEFAULT 'PENDING',
    vertical_video_status           TEXT DEFAULT 'PENDING',

    -- Horizontal
    horizontal_image_url            TEXT,
    horizontal_video_url            TEXT,
    horizontal_upscale_url          TEXT,
    horizontal_image_media_id   TEXT,
    horizontal_video_media_id   TEXT,
    horizontal_upscale_media_id TEXT,
    horizontal_image_status         TEXT DEFAULT 'PENDING',
    horizontal_video_status         TEXT DEFAULT 'PENDING',

    -- Chain source
    vertical_end_scene_media_id   TEXT,
    horizontal_end_scene_media_id TEXT,

    -- Trim
    trim_start  REAL,
    trim_end    REAL,
    duration    REAL,

    created_at  DATETIME DEFAULT (datetime('now')),
    updated_at  DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_scene_video ON scene(video_id);
CREATE INDEX idx_scene_parent ON scene(parent_scene_id);
```

### request (job tracking)
```sql
CREATE TABLE request (
    id              TEXT PRIMARY KEY,
    project_id      TEXT REFERENCES project(id),
    video_id        TEXT REFERENCES video(id),
    scene_id        TEXT REFERENCES scene(id),
    character_id    TEXT REFERENCES character(id),
    type            TEXT NOT NULL CHECK(type IN ('GENERATE_IMAGE','REGENERATE_IMAGE','EDIT_IMAGE','GENERATE_VIDEO','GENERATE_VIDEO_REFS','UPSCALE_VIDEO','GENERATE_CHARACTER_IMAGE','REGENERATE_CHARACTER_IMAGE','EDIT_CHARACTER_IMAGE')),
    orientation     TEXT CHECK(orientation IN ('VERTICAL','HORIZONTAL')),
    status          TEXT DEFAULT 'PENDING' CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED')),
    request_id      TEXT,
    media_id    TEXT,
    output_url      TEXT,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT (datetime('now')),
    updated_at      DATETIME DEFAULT (datetime('now'))
);
CREATE INDEX idx_request_scene ON request(scene_id);
CREATE INDEX idx_request_status ON request(status);
```

---

## Video AI SDK

Domain-model layer that wraps FlowClient operations with type-safe classes.

### Two Execution Modes

```python
# 1. Queue-based (async — background processor picks up)
request_id = await scene.generate_image(project_id="...")
# Returns immediately. Poll request status to know when done.

# 2. Direct execution (blocking — calls FlowClient immediately)
result = await scene.execute_generate_image(project_id="...")
if result.success:
    print(result.media_id, result.url)
else:
    print(result.error)
```

### Domain Models (`agent/sdk/models/`)

| Model | Key Methods |
|-------|------------|
| `Project` | `get()`, `create()`, `add_character()`, `get_characters()`, `add_video()`, `get_videos()` |
| `Video` | `add_scene()`, `get_scenes()`, `remove_scene()`, `move_scene()` |
| `Scene` | `generate_image()`, `edit_image()`, `generate_video()`, `upscale_video()` (queue) |
| | `execute_generate_image()`, `execute_edit_image()`, `execute_generate_video()`, `execute_generate_video_refs()`, `execute_upscale_video()` (direct) |
| `Character` | `generate_image()`, `edit_image()` (queue), `execute_generate_image()`, `execute_edit_image()` (direct) |

### Value Objects (`agent/sdk/models/media.py`)

- `MediaAsset` — status + media_id + url for one asset
- `OrientationSlot` — image/video/upscale MediaAssets for one orientation
- `GenerationResult` — success/error + media_id + url from direct execution

### Services (`agent/sdk/services/`)

- `OperationService` — direct FlowClient execution (generate, edit, video, upscale, reference images) + queue wrappers
- `result_handler` — shared result parsing + DB update logic (used by both direct SDK path and background processor)

### Architecture

```
Scene.execute_generate_image()
  → OperationService.generate_scene_image()  (calls FlowClient)
  → result_handler.parse_result()            (extract media_id, url)
  → result_handler.apply_scene_result()      (update DB + cascade)
  → update local OrientationSlot             (in-memory sync)

Scene.generate_image()
  → OperationService.queue_scene_image()     (create DB request)
  → processor picks up PENDING               (background)
  → OperationService.generate_scene_image()  (same direct method)
  → result_handler.apply_scene_result()      (same DB update)
```

### Cascade Rules

- Regenerate image → clears video + upscale (downstream)
- Regenerate video → clears upscale
- Upscale → no cascade

---

## File Structure

```
comicReels/
├── agent/
│   ├── main.py                         # FastAPI + independent dashboard event WS
│   ├── config.py
│   ├── services/
│   │   ├── flow_client.py              # business API
│   │   ├── flow_browser_backend.py     # sole Flow backend
│   │   ├── flow_browser_driver.py      # Flow browser recipes
│   │   ├── flow_browser_session.py     # persistent profile + lease
│   │   ├── flow_browser_state.py       # durable intent/receipt/bindings
│   │   └── flow_browser_paid.py        # paid one-shot gate
│   ├── sdk/
│   ├── db/
│   ├── api/
│   └── worker/
├── dashboard/                          # React ops console
├── skills/                             # operator/agent workflows
├── docs/
└── requirements-flow-browser.txt       # pinned KBS dependency
```

## Reference and transport authority

- Browser-only cutover plan:
  `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`
- Browser architecture:
  `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`
- Pinned KBS revision:
  `requirements-flow-browser.txt`
- Payload-capture guidance:
  `docs/CAPTURE.md`

## Current Flow transport details

- Origin: `https://flow.google.com`.
- Flow calls execute inside the leased signed-in browser session.
- Authentication/session state remains in the browser profile; credentials,
  cookies and profile databases are never copied into repository state.
- Read/poll RPCs may be replayed only through validated browser recipes.
- Paid image generation uses durable intent/idempotency/receipt gates.
- `effect=unknown` / reconciliation-required outcomes are non-retryable until
  explicitly reconciled.
- The removed Chrome Flow extension is not a fallback or rollback transport.
