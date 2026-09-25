"""ComicReels-specific SQLite schema kept separate from FlowKit core tables."""
from __future__ import annotations
from agent.db.schema import get_db, _db_lock

COMIC_SCHEMA = r"""
CREATE TABLE IF NOT EXISTS comic_project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_mime TEXT NOT NULL,
    source_width INTEGER NOT NULL,
    source_height INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'IMPORTED',
    analysis_provider TEXT,
    analysis_json TEXT,
    flow_project_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_comic_project_source_sha ON comic_project(source_sha256);

CREATE TABLE IF NOT EXISTS comic_character (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES comic_project(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    reference_path TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, stable_key)
);

CREATE TABLE IF NOT EXISTS comic_panel (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES comic_project(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    confidence REAL,
    crop_path TEXT,
    mask_path TEXT,
    clean_path TEXT,
    vertical_path TEXT,
    vertical_sha256 TEXT,
    protected_box_json TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    approved_sha256 TEXT,
    approved_at TEXT,
    status TEXT NOT NULL DEFAULT 'DETECTED',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(project_id, display_order)
);
CREATE INDEX IF NOT EXISTS idx_comic_panel_project ON comic_panel(project_id, display_order);

CREATE TABLE IF NOT EXISTS comic_dialogue (
    id TEXT PRIMARY KEY,
    panel_id TEXT NOT NULL REFERENCES comic_panel(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    speaker_id TEXT REFERENCES comic_character(id) ON DELETE SET NULL,
    verbatim_text TEXT NOT NULL,
    confidence REAL,
    bbox_json TEXT,
    user_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(panel_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_comic_dialogue_panel ON comic_dialogue(panel_id, sequence);

CREATE TABLE IF NOT EXISTS comic_shot (
    id TEXT PRIMARY KEY,
    panel_id TEXT NOT NULL REFERENCES comic_panel(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL,
    speaker_id TEXT REFERENCES comic_character(id) ON DELETE SET NULL,
    dialogue_ids_json TEXT NOT NULL DEFAULT '[]',
    verbatim_text TEXT NOT NULL DEFAULT '',
    duration_s INTEGER NOT NULL,
    model_family TEXT NOT NULL DEFAULT 'omni_flash',
    prompt TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'READY',
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(panel_id, display_order)
);
CREATE INDEX IF NOT EXISTS idx_comic_shot_panel ON comic_shot(panel_id, display_order);

CREATE TABLE IF NOT EXISTS comic_generation (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES comic_project(id) ON DELETE CASCADE,
    shot_id TEXT NOT NULL REFERENCES comic_shot(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL UNIQUE,
    model_family TEXT NOT NULL,
    duration_s INTEGER NOT NULL,
    resolution TEXT NOT NULL DEFAULT '720p',
    flow_project_id TEXT,
    cost_estimate INTEGER,
    cost_approved INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    image_media_id TEXT,
    video_media_id TEXT,
    video_path TEXT,
    submit_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_comic_generation_status ON comic_generation(status, created_at);
CREATE INDEX IF NOT EXISTS idx_comic_generation_shot ON comic_generation(shot_id, created_at);
"""

async def init_comicreels_db() -> None:
    db = await get_db()
    async with _db_lock:
        await db.executescript(COMIC_SCHEMA)
        await db.commit()
