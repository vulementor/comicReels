"""Async persistence helpers for ComicReels."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from agent.db.schema import get_db, _db_lock

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _id() -> str:
    return str(uuid.uuid4())

async def _one(sql: str, params: tuple = ()) -> dict | None:
    db = await get_db()
    cur = await db.execute(sql, params)
    row = await cur.fetchone()
    return dict(row) if row else None

async def _all(sql: str, params: tuple = ()) -> list[dict]:
    db = await get_db()
    cur = await db.execute(sql, params)
    return [dict(x) for x in await cur.fetchall()]

async def create_project(*, name: str, source_path: str, source_sha256: str, source_mime: str,
                         source_width: int, source_height: int) -> dict:
    existing = await _one("SELECT * FROM comic_project WHERE source_sha256=?", (source_sha256,))
    if existing:
        return existing
    pid, now = _id(), _now()
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """INSERT INTO comic_project
               (id,name,source_path,source_sha256,source_mime,source_width,source_height,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (pid, name, source_path, source_sha256, source_mime, source_width, source_height, now, now),
        )
        await db.commit()
    return await get_project(pid)

async def get_project(pid: str) -> dict | None:
    return await _one("SELECT * FROM comic_project WHERE id=?", (pid,))

async def list_projects() -> list[dict]:
    return await _all("SELECT * FROM comic_project ORDER BY created_at DESC")

async def update_project(pid: str, **fields: Any) -> dict | None:
    allowed = {"name", "status", "analysis_provider", "analysis_json", "flow_project_id"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        fields["updated_at"] = _now()
        db = await get_db()
        async with _db_lock:
            await db.execute(
                f"UPDATE comic_project SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), pid),
            )
            await db.commit()
    return await get_project(pid)

async def delete_project(pid: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM comic_project WHERE id=?", (pid,))
        await db.commit()

async def replace_characters(pid: str, characters: list[dict]) -> list[dict]:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute("DELETE FROM comic_character WHERE project_id=?", (pid,))
        for i, c in enumerate(characters):
            stable = c.get("stable_key") or f"character-{i+1}"
            await db.execute(
                """INSERT INTO comic_character
                   (id,project_id,stable_key,name,description,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (_id(), pid, stable, c.get("name") or stable, c.get("description"), now, now),
            )
        await db.commit()
    return await list_characters(pid)

async def upsert_character(pid: str, name: str, stable_key: str | None = None,
                           description: str | None = None) -> dict:
    stable = stable_key or name.strip().lower().replace(" ", "-")
    row = await _one("SELECT * FROM comic_character WHERE project_id=? AND stable_key=?", (pid, stable))
    db = await get_db()
    now = _now()
    async with _db_lock:
        if row:
            await db.execute(
                "UPDATE comic_character SET name=?,description=?,updated_at=? WHERE id=?",
                (name, description, now, row["id"]),
            )
            cid = row["id"]
        else:
            cid = _id()
            await db.execute(
                """INSERT INTO comic_character
                   (id,project_id,stable_key,name,description,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (cid, pid, stable, name, description, now, now),
            )
        await db.commit()
    return await get_character(cid)

async def get_character(cid: str) -> dict | None:
    return await _one("SELECT * FROM comic_character WHERE id=?", (cid,))

async def list_characters(pid: str) -> list[dict]:
    return await _all("SELECT * FROM comic_character WHERE project_id=? ORDER BY created_at", (pid,))

async def replace_panels(pid: str, panels: list[dict]) -> list[dict]:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute("DELETE FROM comic_panel WHERE project_id=?", (pid,))
        for order, p in enumerate(panels):
            await db.execute(
                """INSERT INTO comic_panel
                   (id,project_id,display_order,x,y,width,height,confidence,status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (_id(), pid, int(p.get("display_order", order)), int(p["x"]), int(p["y"]),
                 int(p["width"]), int(p["height"]), p.get("confidence"), "DETECTED", now, now),
            )
        await db.commit()
    return await list_panels(pid)

async def create_panel(pid: str, bbox: dict, display_order: int | None = None,
                       confidence: float | None = None) -> dict:
    if display_order is None:
        display_order = len(await list_panels(pid))
    db = await get_db()
    now, panel_id = _now(), _id()
    async with _db_lock:
        await db.execute(
            """INSERT INTO comic_panel
               (id,project_id,display_order,x,y,width,height,confidence,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (panel_id, pid, display_order, bbox["x"], bbox["y"], bbox["width"], bbox["height"],
             confidence, "DETECTED", now, now),
        )
        await db.commit()
    return await get_panel(panel_id)

async def get_panel(panel_id: str) -> dict | None:
    return await _one("SELECT * FROM comic_panel WHERE id=?", (panel_id,))

async def list_panels(pid: str) -> list[dict]:
    return await _all("SELECT * FROM comic_panel WHERE project_id=? ORDER BY display_order", (pid,))

async def invalidate_panel(panel_id: str, *, clear_images: bool = False) -> None:
    db = await get_db()
    async with _db_lock:
        fields = ["approved_sha256=NULL", "approved_at=NULL", "status='DIRTY'",
                  "version=version+1", "updated_at=?"]
        if clear_images:
            fields += ["crop_path=NULL", "mask_path=NULL", "clean_path=NULL", "vertical_path=NULL",
                       "vertical_sha256=NULL", "protected_box_json=NULL"]
        await db.execute(f"UPDATE comic_panel SET {', '.join(fields)} WHERE id=?", (_now(), panel_id))
        await db.execute("DELETE FROM comic_shot WHERE panel_id=?", (panel_id,))
        await db.commit()

async def update_panel(panel_id: str, **fields: Any) -> dict | None:
    allowed = {"display_order","x","y","width","height","confidence","crop_path","mask_path","clean_path",
               "vertical_path","vertical_sha256","protected_box_json","approved_sha256","approved_at","status","version"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        fields["updated_at"] = _now()
        db = await get_db()
        async with _db_lock:
            await db.execute(
                f"UPDATE comic_panel SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), panel_id),
            )
            await db.commit()
    return await get_panel(panel_id)

async def delete_panel(panel_id: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute("DELETE FROM comic_panel WHERE id=?", (panel_id,))
        await db.commit()

async def reorder_panels(project_id: str, panel_ids: list[str]) -> list[dict]:
    current = await list_panels(project_id)
    current_ids = [p["id"] for p in current]
    if len(panel_ids) != len(current_ids) or set(panel_ids) != set(current_ids):
        raise ValueError("Danh sách thứ tự phải chứa đúng toàn bộ panel của dự án")
    db = await get_db()
    now = _now()
    async with _db_lock:
        for i, panel_id in enumerate(panel_ids):
            await db.execute(
                "UPDATE comic_panel SET display_order=?,updated_at=? WHERE id=? AND project_id=?",
                (100000 + i, now, panel_id, project_id),
            )
        for i, panel_id in enumerate(panel_ids):
            await db.execute(
                "UPDATE comic_panel SET display_order=?,updated_at=? WHERE id=? AND project_id=?",
                (i, now, panel_id, project_id),
            )
        await db.commit()
    return await list_panels(project_id)

async def replace_dialogues(panel_id: str, dialogues: list[dict]) -> list[dict]:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute("DELETE FROM comic_dialogue WHERE panel_id=?", (panel_id,))
        for d in sorted(dialogues, key=lambda x: int(x.get("sequence", 0))):
            await db.execute(
                """INSERT INTO comic_dialogue
                   (id,panel_id,sequence,speaker_id,verbatim_text,confidence,bbox_json,user_verified,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (d.get("id") or _id(), panel_id, int(d.get("sequence", 0)), d.get("speaker_id"),
                 d.get("verbatim_text",""), d.get("confidence"),
                 json.dumps(d.get("bbox")) if d.get("bbox") else None,
                 int(bool(d.get("user_verified"))), now, now),
            )
        await db.commit()
    await invalidate_panel(panel_id, clear_images=False)
    return await list_dialogues(panel_id)

async def list_dialogues(panel_id: str) -> list[dict]:
    rows = await _all("SELECT * FROM comic_dialogue WHERE panel_id=? ORDER BY sequence", (panel_id,))
    for r in rows:
        r["bbox"] = json.loads(r["bbox_json"]) if r.get("bbox_json") else None
        r["user_verified"] = bool(r.get("user_verified"))
    return rows

async def all_dialogues_for_project(pid: str) -> list[dict]:
    rows = await _all(
        """SELECT d.*, p.display_order panel_order FROM comic_dialogue d
           JOIN comic_panel p ON p.id=d.panel_id WHERE p.project_id=?
           ORDER BY p.display_order,d.sequence""", (pid,),
    )
    for r in rows:
        r["bbox"] = json.loads(r["bbox_json"]) if r.get("bbox_json") else None
    return rows

async def approve_panel(panel_id: str, sha256: str) -> dict:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute(
            "UPDATE comic_panel SET approved_sha256=?,approved_at=?,status='APPROVED',updated_at=? WHERE id=?",
            (sha256, now, now, panel_id),
        )
        await db.commit()
    return await get_panel(panel_id)

async def replace_shots(panel_id: str, shots: list[dict]) -> list[dict]:
    db = await get_db()
    now = _now()
    async with _db_lock:
        await db.execute("DELETE FROM comic_shot WHERE panel_id=?", (panel_id,))
        for s in shots:
            await db.execute(
                """INSERT INTO comic_shot
                   (id,panel_id,display_order,speaker_id,dialogue_ids_json,verbatim_text,duration_s,
                    model_family,prompt,image_sha256,status,review_status,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (s.get("id") or _id(), panel_id, int(s["display_order"]), s.get("speaker_id"),
                 json.dumps(s.get("dialogue_ids",[]), ensure_ascii=False), s.get("verbatim_text",""),
                 int(s["duration_s"]), s.get("model_family","omni_flash"), s["prompt"], s["image_sha256"],
                 "READY", "PENDING", now, now),
            )
        await db.commit()
    return await list_shots_for_panel(panel_id)

async def get_shot(shot_id: str) -> dict | None:
    row = await _one("SELECT * FROM comic_shot WHERE id=?", (shot_id,))
    if row:
        row["dialogue_ids"] = json.loads(row.get("dialogue_ids_json") or "[]")
    return row

async def list_shots_for_panel(panel_id: str) -> list[dict]:
    rows = await _all("SELECT * FROM comic_shot WHERE panel_id=? ORDER BY display_order", (panel_id,))
    for r in rows:
        r["dialogue_ids"] = json.loads(r.get("dialogue_ids_json") or "[]")
    return rows

async def list_shots(pid: str) -> list[dict]:
    rows = await _all(
        """SELECT s.*,p.display_order panel_order FROM comic_shot s
           JOIN comic_panel p ON p.id=s.panel_id WHERE p.project_id=?
           ORDER BY p.display_order,s.display_order""", (pid,),
    )
    for r in rows:
        r["dialogue_ids"] = json.loads(r.get("dialogue_ids_json") or "[]")
    return rows

async def update_shot(shot_id: str, **fields: Any) -> dict | None:
    allowed = {"status", "review_status", "prompt", "duration_s", "model_family"}
    fields = {k:v for k,v in fields.items() if k in allowed}
    if fields:
        fields["updated_at"] = _now()
        db = await get_db()
        async with _db_lock:
            await db.execute(
                f"UPDATE comic_shot SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), shot_id),
            )
            await db.commit()
    return await get_shot(shot_id)

async def create_generation(*, project_id: str, shot_id: str, idempotency_key: str, model_family: str,
                            duration_s: int, resolution: str, flow_project_id: str | None,
                            cost_estimate: int | None, cost_approved: bool) -> dict:
    existing = await _one("SELECT * FROM comic_generation WHERE idempotency_key=?", (idempotency_key,))
    if existing:
        return existing
    gid, now = _id(), _now()
    db = await get_db()
    async with _db_lock:
        await db.execute(
            """INSERT INTO comic_generation
               (id,project_id,shot_id,idempotency_key,model_family,duration_s,resolution,flow_project_id,
                cost_estimate,cost_approved,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (gid, project_id, shot_id, idempotency_key, model_family, duration_s, resolution,
             flow_project_id, cost_estimate, int(cost_approved), "QUEUED", now, now),
        )
        await db.commit()
    return await get_generation(gid)

async def get_generation(gid: str) -> dict | None:
    row = await _one("SELECT * FROM comic_generation WHERE id=?", (gid,))
    if row:
        row["cost_approved"] = bool(row.get("cost_approved"))
    return row

async def list_generations(pid: str) -> list[dict]:
    rows = await _all("SELECT * FROM comic_generation WHERE project_id=? ORDER BY created_at", (pid,))
    for r in rows:
        r["cost_approved"] = bool(r.get("cost_approved"))
    return rows

async def next_queued_generation() -> dict | None:
    return await _one(
        "SELECT * FROM comic_generation WHERE status='QUEUED' AND cost_approved=1 ORDER BY created_at LIMIT 1"
    )

async def update_generation(gid: str, **fields: Any) -> dict | None:
    allowed = {"status","image_media_id","video_media_id","video_path","submit_json","error_message",
               "flow_project_id","cost_estimate","cost_approved"}
    fields = {k:v for k,v in fields.items() if k in allowed}
    if fields:
        fields["updated_at"] = _now()
        db = await get_db()
        async with _db_lock:
            await db.execute(
                f"UPDATE comic_generation SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                (*fields.values(), gid),
            )
            await db.commit()
    return await get_generation(gid)

async def project_bundle(pid: str) -> dict | None:
    p = await get_project(pid)
    if not p:
        return None
    panels = await list_panels(pid)
    for panel in panels:
        panel["dialogues"] = await list_dialogues(panel["id"])
        panel["shots"] = await list_shots_for_panel(panel["id"])
    p["panels"] = panels
    p["characters"] = await list_characters(pid)
    p["generations"] = await list_generations(pid)
    return p

async def list_generations_for_shot(shot_id: str) -> list[dict]:
    rows = await _all("SELECT * FROM comic_generation WHERE shot_id=? ORDER BY created_at DESC", (shot_id,))
    for r in rows:
        r["cost_approved"] = bool(r.get("cost_approved"))
    return rows

async def latest_completed_generation_for_shot(shot_id: str) -> dict | None:
    row = await _one(
        "SELECT * FROM comic_generation WHERE shot_id=? AND status='COMPLETED' ORDER BY created_at DESC LIMIT 1",
        (shot_id,),
    )
    if row:
        row["cost_approved"] = bool(row.get("cost_approved"))
    return row

async def clear_project_shots(pid: str) -> None:
    db = await get_db()
    async with _db_lock:
        await db.execute(
            "DELETE FROM comic_shot WHERE panel_id IN (SELECT id FROM comic_panel WHERE project_id=?)",
            (pid,),
        )
        await db.commit()
