"""Small isolated SQLite store for ComicReels.

Keeping this schema separate from FlowKit's production tables makes upstream
syncs less fragile and lets ComicReels evolve its state machine independently.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from agent.config import OUTPUT_DIR


ROOT = OUTPUT_DIR / "comicreels"
DB_PATH = ROOT / "comicreels.db"

ACTIVE_SHOT_STATES = ("SUBMITTING", "PROCESSING", "SUBMISSION_UNKNOWN")
BUSY_MESSAGE = "ComicReels đang có video chưa kết thúc; không thể sửa hoặc xóa kịch bản/ảnh."


class ComicConflictError(ValueError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS comic_project (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    source_mime TEXT NOT NULL,
    source_width INTEGER NOT NULL,
    source_height INTEGER NOT NULL,
    ai_conversation_url TEXT,
    ai_analysis_message_id TEXT,
    status TEXT NOT NULL DEFAULT 'IMPORTED',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comic_panel (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    x INTEGER NOT NULL, y INTEGER NOT NULL, w INTEGER NOT NULL, h INTEGER NOT NULL,
    crop_path TEXT,
    clean_path TEXT,
    portrait_path TEXT,
    portrait_sha256 TEXT,
    approved_sha256 TEXT,
    mask_json TEXT NOT NULL DEFAULT '[]',
    visual_anchor TEXT,
    protected_json TEXT,
    status TEXT NOT NULL DEFAULT 'ANALYZED',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES comic_project(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_comic_panel_project ON comic_panel(project_id, display_order);
CREATE TABLE IF NOT EXISTS comic_dialogue (
    id TEXT PRIMARY KEY,
    panel_id TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    speaker_id TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(panel_id) REFERENCES comic_panel(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_comic_dialogue_panel ON comic_dialogue(panel_id, display_order);
CREATE TABLE IF NOT EXISTS comic_shot (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    panel_id TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    speaker_id TEXT,
    dialogue_text TEXT NOT NULL DEFAULT '',
    duration_s INTEGER NOT NULL,
    model_family TEXT NOT NULL DEFAULT 'omni_flash',
    prompt TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'READY',
    flow_payload_json TEXT,
    idempotency_key TEXT,
    video_path TEXT,
    review_status TEXT NOT NULL DEFAULT 'PENDING',
    review_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES comic_project(id) ON DELETE CASCADE,
    FOREIGN KEY(panel_id) REFERENCES comic_panel(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_comic_shot_project ON comic_shot(project_id, display_order);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ComicStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._ready = False

    async def init(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            ROOT.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("PRAGMA foreign_keys=ON")
                await db.executescript(SCHEMA)
                columns = {
                    str(row[1])
                    for row in await (await db.execute("PRAGMA table_info(comic_project)")).fetchall()
                }
                if "ai_conversation_url" not in columns:
                    await db.execute("ALTER TABLE comic_project ADD COLUMN ai_conversation_url TEXT")
                if "ai_analysis_message_id" not in columns:
                    await db.execute("ALTER TABLE comic_project ADD COLUMN ai_analysis_message_id TEXT")
                panel_columns = {
                    str(row[1])
                    for row in await (await db.execute("PRAGMA table_info(comic_panel)")).fetchall()
                }
                if "visual_anchor" not in panel_columns:
                    await db.execute("ALTER TABLE comic_panel ADD COLUMN visual_anchor TEXT")
                # Enforce the paid-job boundary for every writer, including
                # bulk analysis, legacy endpoints and concurrent processes.
                for table, project_expr in (
                    ("comic_shot", "OLD.project_id"),
                    ("comic_panel", "OLD.project_id"),
                    ("comic_dialogue", "(SELECT project_id FROM comic_panel WHERE id=OLD.panel_id)"),
                ):
                    events = ["DELETE"]
                    if table == "comic_panel":
                        events += ["UPDATE"]
                    elif table == "comic_dialogue":
                        events += ["UPDATE"]
                    for event in events:
                        await db.execute(f"""CREATE TRIGGER IF NOT EXISTS guard_{table}_{event.lower()}
                            BEFORE {event} ON {table}
                            WHEN EXISTS(SELECT 1 FROM comic_shot WHERE project_id={project_expr}
                              AND status IN ('SUBMITTING','PROCESSING','SUBMISSION_UNKNOWN'))
                            BEGIN SELECT RAISE(ABORT, '{BUSY_MESSAGE}'); END""")
                await db.execute(f"""CREATE TRIGGER IF NOT EXISTS guard_dialogue_insert
                    BEFORE INSERT ON comic_dialogue
                    WHEN EXISTS(SELECT 1 FROM comic_shot
                      WHERE project_id=(SELECT project_id FROM comic_panel WHERE id=NEW.panel_id)
                      AND status IN ('SUBMITTING','PROCESSING','SUBMISSION_UNKNOWN'))
                    BEGIN SELECT RAISE(ABORT, '{BUSY_MESSAGE}'); END""")
                for event, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
                    await db.execute(f"""CREATE TRIGGER IF NOT EXISTS invalidate_dialogue_{event.lower()}
                        AFTER {event} ON comic_dialogue BEGIN
                        DELETE FROM comic_shot WHERE project_id=(
                          SELECT project_id FROM comic_panel WHERE id={row}.panel_id);
                        END""")
                await db.commit()
            self._ready = True

    async def _connect(self) -> aiosqlite.Connection:
        await self.init()
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        return db

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        db = await self._connect()
        try:
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        db = await self._connect()
        try:
            cur = await db.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        db = await self._connect()
        try:
            await db.execute(sql, params)
            await db.commit()
        finally:
            await db.close()

    async def create_project(self, *, name: str, source_path: str, sha256: str, mime: str,
                             width: int, height: int, project_id: str | None = None) -> dict[str, Any]:
        project_id = project_id or uuid.uuid4().hex
        ts = now()
        await self.execute(
            """INSERT INTO comic_project
            (id,name,source_path,source_sha256,source_mime,source_width,source_height,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,'IMPORTED',?,?)""",
            (project_id, name, source_path, sha256, mime, width, height, ts, ts),
        )
        return (await self.get_project(project_id))["project"]

    async def list_projects(self) -> list[dict[str, Any]]:
        return await self.fetch_all("SELECT * FROM comic_project ORDER BY created_at DESC")

    async def set_project_ai_session(
        self,
        project_id: str,
        *,
        conversation_url: str,
        assistant_message_id: str | None = None,
    ) -> None:
        await self.execute(
            """UPDATE comic_project
            SET ai_conversation_url=?, ai_analysis_message_id=?, updated_at=?
            WHERE id=?""",
            (conversation_url, assistant_message_id, now(), project_id),
        )


    async def get_project(self, project_id: str) -> dict[str, Any]:
        project = await self.fetch_one("SELECT * FROM comic_project WHERE id=?", (project_id,))
        if not project:
            raise KeyError(project_id)
        panels = await self.fetch_all(
            "SELECT * FROM comic_panel WHERE project_id=? ORDER BY display_order", (project_id,)
        )
        for panel in panels:
            panel["mask"] = json.loads(panel.pop("mask_json") or "[]")
            panel["protected"] = json.loads(panel.pop("protected_json") or "null")
            panel["dialogues"] = await self.fetch_all(
                "SELECT * FROM comic_dialogue WHERE panel_id=? ORDER BY display_order", (panel["id"],)
            )
        shots = await self.fetch_all(
            "SELECT * FROM comic_shot WHERE project_id=? ORDER BY display_order", (project_id,)
        )
        for shot in shots:
            shot["flow_payload"] = json.loads(shot.pop("flow_payload_json") or "null")
        return {"project": project, "panels": panels, "shots": shots}

    async def replace_analysis(self, project_id: str, panels: list[dict[str, Any]],
                               dialogues: list[dict[str, Any]]) -> None:
        ts = now()
        db = await self._connect()
        try:
            await db.execute("DELETE FROM comic_shot WHERE project_id=?", (project_id,))
            old = await (await db.execute("SELECT id FROM comic_panel WHERE project_id=?", (project_id,))).fetchall()
            for row in old:
                await db.execute("DELETE FROM comic_dialogue WHERE panel_id=?", (row[0],))
            await db.execute("DELETE FROM comic_panel WHERE project_id=?", (project_id,))
            panel_ids: list[str] = []
            for idx, panel in enumerate(panels):
                pid = uuid.uuid4().hex
                panel_ids.append(pid)
                await db.execute(
                    """INSERT INTO comic_panel
                    (id,project_id,display_order,x,y,w,h,mask_json,visual_anchor,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,'ANALYZED',?,?)""",
                    (
                        pid, project_id, idx,
                        int(panel["x"]), int(panel["y"]), int(panel["w"]), int(panel["h"]),
                        json.dumps(panel.get("mask") or []),
                        str(panel.get("visual_anchor") or "").strip() or None,
                        ts, ts,
                    ),
                )
            for idx, dialogue in enumerate(dialogues):
                panel_index = int(dialogue.get("panel_index", 0))
                if panel_index < 0 or panel_index >= len(panel_ids):
                    continue
                await db.execute(
                    """INSERT INTO comic_dialogue
                    (id,panel_id,display_order,speaker_id,text,confidence,verified,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        uuid.uuid4().hex, panel_ids[panel_index], int(dialogue.get("display_order", idx)),
                        str(dialogue.get("speaker_id") or "UNKNOWN"), str(dialogue.get("text") or ""),
                        dialogue.get("confidence"), 1 if dialogue.get("verified") else 0, ts, ts,
                    ),
                )
            await db.execute(
                "UPDATE comic_project SET status='ANALYZED',updated_at=? WHERE id=?", (ts, project_id)
            )
            await db.commit()
        finally:
            await db.close()

    async def update_panel(self, panel_id: str, **fields: Any) -> None:
        allowed = {
            "display_order", "x", "y", "w", "h", "crop_path", "clean_path", "portrait_path",
            "portrait_sha256", "approved_sha256", "mask_json", "visual_anchor", "protected_json", "status",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return
        values["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in values)
        await self.execute(f"UPDATE comic_panel SET {sets} WHERE id=?", tuple(values.values()) + (panel_id,))

    async def panel(self, panel_id: str) -> dict[str, Any] | None:
        return await self.fetch_one("SELECT * FROM comic_panel WHERE id=?", (panel_id,))

    async def upsert_dialogue(self, panel_id: str, *, dialogue_id: str | None, order: int,
                              speaker_id: str, text: str, verified: bool,
                              confidence: float | None = None) -> dict[str, Any]:
        ts = now()
        if dialogue_id and await self.fetch_one("SELECT id FROM comic_dialogue WHERE id=?", (dialogue_id,)):
            await self.execute(
                """UPDATE comic_dialogue SET display_order=?,speaker_id=?,text=?,verified=?,confidence=?,updated_at=?
                WHERE id=?""",
                (order, speaker_id, text, int(verified), confidence, ts, dialogue_id),
            )
            did = dialogue_id
        else:
            did = uuid.uuid4().hex
            await self.execute(
                """INSERT INTO comic_dialogue
                (id,panel_id,display_order,speaker_id,text,verified,confidence,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (did, panel_id, order, speaker_id, text, int(verified), confidence, ts, ts),
            )
        return await self.fetch_one("SELECT * FROM comic_dialogue WHERE id=?", (did,)) or {}

    async def clear_shots(self, project_id: str) -> None:
        await self.execute("DELETE FROM comic_shot WHERE project_id=?", (project_id,))

    async def apply_visual_anchors_and_invalidate_portraits(
        self,
        project_id: str,
        anchors: dict[int, str],
    ) -> None:
        ts = now()
        db = await self._connect()
        try:
            rows = await (
                await db.execute(
                    "SELECT id,display_order FROM comic_panel WHERE project_id=? ORDER BY display_order",
                    (project_id,),
                )
            ).fetchall()
            expected = {int(row[1]) for row in rows}
            if set(anchors) != expected:
                raise ValueError("visual-anchor set does not match project panels")
            for row in rows:
                panel_id = str(row[0])
                display_order = int(row[1])
                visual_anchor = str(anchors[display_order]).strip()
                if not visual_anchor:
                    raise ValueError("visual anchor must not be empty")
                await db.execute(
                    """UPDATE comic_panel
                    SET visual_anchor=?,portrait_path=NULL,portrait_sha256=NULL,approved_sha256=NULL,
                        protected_json=NULL,status='EXTRACTED',updated_at=?
                    WHERE id=?""",
                    (visual_anchor, ts, panel_id),
                )
            await db.execute("DELETE FROM comic_shot WHERE project_id=?", (project_id,))
            await db.execute(
                "UPDATE comic_project SET status='EXTRACTED',updated_at=? WHERE id=?",
                (ts, project_id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def apply_visual_anchor_validation(
        self,
        project_id: str,
        validations: dict[int, dict[str, Any]],
    ) -> list[int]:
        ts = now()
        db = await self._connect()
        changed: list[int] = []
        try:
            rows = await (
                await db.execute(
                    """SELECT id,display_order,visual_anchor FROM comic_panel
                    WHERE project_id=? ORDER BY display_order""",
                    (project_id,),
                )
            ).fetchall()
            expected = {int(row[1]) for row in rows}
            if set(validations) != expected:
                raise ValueError("visual-anchor validation set does not match project panels")
            for row in rows:
                panel_id = str(row[0])
                display_order = int(row[1])
                current_anchor = str(row[2] or "").strip()
                result = validations[display_order]
                matches_source = bool(result.get("matches_source"))
                if matches_source:
                    continue
                corrected_anchor = str(result.get("corrected_anchor") or "").strip()
                if not corrected_anchor:
                    raise ValueError("corrected visual anchor must not be empty")
                if corrected_anchor == current_anchor:
                    raise ValueError("corrected visual anchor must differ from current anchor")
                await db.execute(
                    """UPDATE comic_panel
                    SET visual_anchor=?,portrait_path=NULL,portrait_sha256=NULL,approved_sha256=NULL,
                        protected_json=NULL,status='EXTRACTED',updated_at=?
                    WHERE id=?""",
                    (corrected_anchor, ts, panel_id),
                )
                changed.append(display_order)

            if changed:
                await db.execute("DELETE FROM comic_shot WHERE project_id=?", (project_id,))
                await db.execute(
                    "UPDATE comic_project SET status='EXTRACTED',updated_at=? WHERE id=?",
                    (ts, project_id),
                )
            await db.commit()
            return changed
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def insert_shot(self, data: dict[str, Any]) -> None:
        ts = now()
        await self.execute(
            """INSERT INTO comic_shot
            (id,project_id,panel_id,display_order,speaker_id,dialogue_text,duration_s,model_family,prompt,
             image_sha256,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,'READY',?,?)""",
            (
                data["id"], data["project_id"], data["panel_id"], data["display_order"],
                data.get("speaker_id"), data.get("dialogue_text", ""), data["duration_s"],
                data.get("model_family", "omni_flash"), data["prompt"], data["image_sha256"], ts, ts,
            ),
        )

    async def shot(self, shot_id: str) -> dict[str, Any] | None:
        row = await self.fetch_one("SELECT * FROM comic_shot WHERE id=?", (shot_id,))
        if row:
            row["flow_payload"] = json.loads(row.pop("flow_payload_json") or "null")
        return row

    async def update_shot(self, shot_id: str, **fields: Any) -> None:
        allowed = {
            "status", "flow_payload_json", "idempotency_key", "video_path", "review_status",
            "review_notes", "duration_s", "model_family",
        }
        values = {k: v for k, v in fields.items() if k in allowed}
        if not values:
            return
        values["updated_at"] = now()
        sets = ",".join(f"{k}=?" for k in values)
        await self.execute(f"UPDATE comic_shot SET {sets} WHERE id=?", tuple(values.values()) + (shot_id,))

    async def claim_shot(self, shot: dict[str, Any], idempotency_key: str,
                         *, force: bool, payload: dict[str, Any]) -> bool:
        """Reserve a paid attempt atomically across concurrent requests/processes.

        Return False for a replay of a known attempt. Never resubmit an uncertain
        attempt, even with force: the provider may already have charged for it.
        """
        db = await self._connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute("SELECT * FROM comic_shot WHERE id=?", (shot["id"],))).fetchone()
            if not row:
                raise ValueError("Kịch bản đã thay đổi; hãy mở lại dự án.")
            current = dict(row)
            if current["status"] == "SUBMISSION_UNKNOWN":
                raise ValueError("Chưa rõ Flow đã nhận job hay chưa. Kiểm tra job trên Flow trước khi gửi lại.")
            if current.get("idempotency_key") == idempotency_key:
                if current["status"] in {"SUBMITTING", "PROCESSING", "COMPLETED"}:
                    await db.rollback()
                    return False
                raise ValueError("Lượt gửi này đã kết thúc. Dùng Tạo lại với mã lượt mới.")
            if current["status"] in {"SUBMITTING", "PROCESSING"}:
                raise ValueError("Shot đang được gửi hoặc đang xử lý; không thể gửi trùng.")
            if current["status"] == "COMPLETED" and not (force and current["review_status"] == "REJECTED"):
                raise ValueError("Hãy đánh dấu video lỗi trước khi tạo lại shot này.")
            if current["status"] == "FAILED" and not force:
                raise ValueError("Shot đã thất bại. Bấm Tạo lại để xác nhận một lượt mới.")
            if current["image_sha256"] != shot["image_sha256"] or current["prompt"] != shot["prompt"]:
                raise ValueError("Ảnh hoặc kịch bản đã thay đổi; hãy mở lại dự án.")
            for panel_id, digest in zip(payload["reference_panel_ids"], payload["reference_image_sha256"]):
                panel = await (await db.execute(
                    "SELECT approved_sha256,portrait_sha256,status FROM comic_panel WHERE id=? AND project_id=?",
                    (panel_id, shot["project_id"]),
                )).fetchone()
                if not panel or panel[0] != digest or panel[1] != digest or panel[2] != "AI_IMAGE_APPROVED":
                    raise ValueError("Ảnh reference đã thay đổi; hãy mở lại dự án.")
            await db.execute(
                """UPDATE comic_shot SET status='SUBMITTING', idempotency_key=?,
                   flow_payload_json=?,video_path=NULL,review_status='PENDING',review_notes=NULL,
                   updated_at=? WHERE id=?""",
                (idempotency_key, json.dumps(payload, ensure_ascii=False), now(), shot["id"]),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.close()

    async def update_attempt(self, shot_id: str, attempt_key: str | None, **fields: Any) -> bool:
        """Late polls may update only the unfinished attempt they observed."""
        allowed = {"status", "flow_payload_json", "video_path", "review_status", "review_notes"}
        values = {key: value for key, value in fields.items() if key in allowed}
        values["updated_at"] = now()
        db = await self._connect()
        try:
            sets = ",".join(f"{key}=?" for key in values)
            cursor = await db.execute(
                f"UPDATE comic_shot SET {sets} WHERE id=? AND idempotency_key IS ? "
                "AND status IN ('PROCESSING','SUBMISSION_UNKNOWN')",
                tuple(values.values()) + (shot_id, attempt_key),
            )
            await db.commit()
            return cursor.rowcount == 1
        finally:
            await db.close()

    async def review_video(self, shot_id: str, *, video_path: str, status: str, notes: str) -> None:
        db = await self._connect()
        try:
            cursor = await db.execute(
                """UPDATE comic_shot SET review_status=?,review_notes=?,updated_at=?
                WHERE id=? AND status='COMPLETED' AND video_path=?""",
                (status, notes, now(), shot_id, video_path),
            )
            if cursor.rowcount != 1:
                raise ComicConflictError("Video đã đổi hoặc chưa hoàn thành. Hãy mở lại và xem video hiện tại.")
            await db.commit()
        finally:
            await db.close()

    async def register_video_file(self, shot_id: str, path: str) -> None:
        db = await self._connect()
        try:
            cursor = await db.execute(
                """UPDATE comic_shot SET status='COMPLETED',video_path=?,review_status='PENDING',
                review_notes=NULL,updated_at=? WHERE id=?
                AND status NOT IN ('SUBMITTING','PROCESSING','SUBMISSION_UNKNOWN')""",
                (path, now(), shot_id),
            )
            if cursor.rowcount != 1:
                raise ComicConflictError("Không thể thay file khi job Flow chưa kết thúc.")
            await db.commit()
        finally:
            await db.close()

    async def set_project_status(self, project_id: str, status: str) -> None:
        await self.execute(
            "UPDATE comic_project SET status=?,updated_at=? WHERE id=?", (status, now(), project_id)
        )


store = ComicStore()
