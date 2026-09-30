"""Offline snapshot of one failed analysis, never a retry or a profile migration.

The owner must stop all source runners and schedules first; SQLite backup is
consistent per database, not a cross-database transaction. The source settings
must be paused. This helper does not create config, enable a deployment, claim
the old input folder, copy profiles, or invoke providers. A completed snapshot
still needs owned runtime config and an explicit canonical retry_story call.

Only the four-receipt, no-package, no-publication failed-analysis shape is
supported. Archives are exclusive, hash-sealed evidence, not OS-enforced WORM.
Keep the archive private: the original ledger/provider files can contain private
data. The returned receipt contains paths/hashes, never those payloads.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import ExitStack, closing
from datetime import datetime, timezone
from pathlib import Path

_RECEIPTS = ("analysis.json", "analysis-prompt.json", "analysis-upload.json", "analysis-provider.json")
_CAMPAIGN = {
    "jobs": ("id", "slot", "source", "source_sha256", "package_dir", "state", "detail", "created_at", "updated_at"),
    "source_errors": ("path", "reason", "observed_at"),
    "production_attempts": ("job_id", "started_day", "started_at", "status", "completed_day", "completed_at", "reason"),
    "publication_slots": ("slot", "job_id", "state", "result"),
}
_KRP = {"effects": (
    "operation_id", "idempotency_key", "action", "platform", "actor", "profile", "asset_sha256",
    "payload_sha256", "payload_json", "state", "permalink", "external_id", "reason", "evidence_json",
    "attempts", "created_at", "updated_at",
)}


class MigrationRejected(ValueError):
    """A fixed, payload-free diagnostic for an unsupported or changed snapshot."""


def _require(condition, code):
    if not condition:
        raise MigrationRejected(code)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json(data):
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeError):
        raise MigrationRejected("INVALID_JSON") from None


def _path(value):
    path = Path(value)
    _require(path.is_absolute() and ".." not in path.parts, "ABSOLUTE_CANONICAL_PATH_REQUIRED")
    # Check lexical ancestors before resolve() can hide junctions or symlinks.
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        _require(not stat.S_ISLNK(info.st_mode)
                 and not (getattr(info, "st_file_attributes", 0) & 0x400), "LINK_OR_REPARSE_POINT")
        _require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1, "HARDLINK_NOT_ALLOWED")
    return path.resolve()


def _file(path):
    path = _path(path)
    _require(path.is_file(), "REQUIRED_FILE_MISSING")
    return path.read_bytes()


def _within(path, root):
    return path == root or root in path.parents


def _rows(db, table):
    return [dict(row) for row in db.execute('SELECT * FROM "' + table + '" ORDER BY 1')]


def _snapshot(path, tables):
    _file_path = _path(path)
    _require(_file_path.is_file(), "REQUIRED_DATABASE_MISSING")
    for suffix in ("-wal", "-shm"):
        _path(str(_file_path) + suffix)
    memory = sqlite3.connect(":memory:")
    memory.row_factory = sqlite3.Row
    try:
        deadline = time.monotonic() + 10
        def progress(*_):
            _require(time.monotonic() < deadline, "DATABASE_BACKUP_TIMEOUT")
        with closing(sqlite3.connect(_file_path.as_uri() + "?mode=ro", uri=True, timeout=2)) as source:
            source.execute("PRAGMA query_only=ON")
            source.backup(memory, pages=128, progress=progress, sleep=0.01)
        schema = memory.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        _require({r["name"] for r in schema if r["type"] == "table"} == set(tables)
                 and all(r["type"] in {"table", "index"} for r in schema), "UNSUPPORTED_DATABASE_SCHEMA")
        for table, columns in tables.items():
            actual = tuple(r["name"] for r in memory.execute('PRAGMA table_info("' + table + '")'))
            _require(actual == columns, "UNSUPPORTED_DATABASE_COLUMNS")
        _require(memory.execute("PRAGMA quick_check").fetchone()[0] == "ok", "DATABASE_INTEGRITY")
        return memory
    except BaseException:
        memory.close()
        raise


def _put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _save_database(db, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb"):
        pass
    with closing(sqlite3.connect(path)) as target:
        db.backup(target)
        target.execute("PRAGMA journal_mode=DELETE")


def snapshot_failed_analysis_resume(source_root, destination_home, job_id, *,
                                    source_input_root, expected_source_sha256, archive_dir):
    """Copy one verified failed analysis into a fresh owned home, without execution.

    All roots must be absolute, non-overlapping, and free of links/reparse points.
    Destination may be absent or empty; archive must be absent. Their parents
    must already exist. expected_source_sha256 binds the owner's chosen job.
    No arbitrary path rewrite or generic job/package migration is performed.
    Failure after archival leaves evidence and a partial destination for review;
    calling again never overwrites either. No payload is included in errors.
    """
    _require(isinstance(job_id, str) and re.fullmatch("[0-9a-f]{32}", job_id), "INVALID_JOB_ID")
    _require(isinstance(expected_source_sha256, str)
             and re.fullmatch("[0-9a-f]{64}", expected_source_sha256), "INVALID_SOURCE_HASH")
    root, inputs, home, archive = map(_path, (source_root, source_input_root, destination_home, archive_dir))
    _require(root.is_dir() and inputs.is_dir(), "SOURCE_ROOT_MISSING")
    _require(home.parent.is_dir() and archive.parent.is_dir(), "DESTINATION_PARENT_MISSING")
    for owned in (home, archive):
        for original in (root, inputs):
            _require(not _within(owned, original) and not _within(original, owned), "ROOT_OVERLAP")
    _require(not _within(home, archive) and not _within(archive, home), "ROOT_OVERLAP")
    _require(not archive.exists(), "ARCHIVE_ALREADY_EXISTS")
    _require(not home.exists() or (home.is_dir() and not any(home.iterdir())), "DESTINATION_NOT_EMPTY")
    settings_bytes = _file(root / "config/settings.json")
    settings = _json(settings_bytes)
    _require(isinstance(settings, dict) and settings.get("enabled") is False, "SOURCE_MUST_BE_PAUSED")
    _require(_path(settings.get("root", "")) == root
             and _path(settings.get("input_dir", "")) == inputs, "SOURCE_SETTINGS_MISMATCH")

    with ExitStack() as stack:
        campaign = stack.enter_context(closing(_snapshot(root / "data/campaign.sqlite3", _CAMPAIGN)))
        krp = stack.enter_context(closing(_snapshot(root / "data/krp/state.sqlite3", _KRP)))
        jobs = [r for r in _rows(campaign, "jobs") if r["id"] == job_id]
        attempts = [r for r in _rows(campaign, "production_attempts") if r["job_id"] == job_id]
        _require(len(jobs) == len(attempts) == 1, "SELECTED_IDENTITY_MISSING")
        job, attempt = jobs[0], attempts[0]
        _require(job["source_sha256"] == expected_source_sha256
                 and job["state"] == "production_failed"
                 and attempt["status"] == "failed" and attempt["reason"] == "qa_failed:analysis",
                 "NOT_FAILED_ANALYSIS")
        old_source, old_package = _path(job["source"]), _path(job["package_dir"])
        _require(old_source.parent == inputs and old_source.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".jfif"},
                 "SOURCE_OUTSIDE_INPUT")
        _require(old_package.parent == inputs / "video" and not old_package.exists(), "PACKAGE_ALREADY_EXISTS_OR_OUTSIDE_OUTPUT")
        source_bytes = _file(old_source)
        _require(_hash(source_bytes) == expected_source_sha256, "SOURCE_HASH_CHANGED")
        receipt_dir = _path(root / "data/production" / job_id)
        _require(receipt_dir.is_dir() and {p.name for p in receipt_dir.iterdir()} == set(_RECEIPTS),
                 "UNSUPPORTED_RECEIPT_SET")
        originals = {name: _file(receipt_dir / name) for name in _RECEIPTS}
        stage, prompt, upload, provider = (_json(originals[name]) for name in _RECEIPTS)
        detail = _json(job["detail"].encode("utf-8"))
        _require(isinstance(detail, dict) and set(detail) == {
            "production_stage", "production_receipts", "production_error"}
            and detail["production_stage"] == "analysis" and detail["production_error"] == "qa_failed"
            and _path(detail["production_receipts"]) == receipt_dir, "JOB_DETAIL_UNSUPPORTED")
        old_request = {"source": job["source"], "source_sha256": expected_source_sha256}
        _require(isinstance(stage, dict) and stage.get("schema_version") == 1
                 and stage.get("stage") == "analysis" and stage.get("state") == "FAILED"
                 and stage.get("source_sha256") == expected_source_sha256
                 and stage.get("request_sha256") == _hash(_json_bytes(old_request))
                 and isinstance(stage.get("result"), dict) and stage["result"].get("state") == "qa_failed",
                 "STAGE_INTENT_CHANGED")
        attachment = {"path": str(old_source), "sha256": expected_source_sha256}
        expected_upload = [dict(attachment, name=old_source.name, size_bytes=len(source_bytes))]
        _require(isinstance(prompt, dict) and set(prompt) == {"text", "attachments"}
                 and isinstance(prompt["text"], str) and prompt["attachments"] == [attachment]
                 and upload == expected_upload, "ATTACHMENT_CHANGED")
        _require(isinstance(provider, dict) and provider.get("state") == "verified"
                 and isinstance(provider.get("text"), str)
                 and isinstance(provider.get("assistant_message_id"), str) and provider["assistant_message_id"]
                 and isinstance(provider.get("conversation_url"), str)
                 and re.fullmatch(r"https://chatgpt\.com/c/[A-Za-z0-9_-]{1,200}", provider["conversation_url"])
                 and provider.get("attachment_receipts") == upload
                 and provider.get("attachments") == [old_source.name]
                 and stage.get("progress", {}).get("conversation_url") == provider["conversation_url"],
                 "PROVIDER_IDENTITY_UNVERIFIED")
        _require(not any(r["job_id"] == job_id or r["slot"] == job["slot"]
                         for r in _rows(campaign, "publication_slots")), "SELECTED_PUBLICATION_EXISTS")
        ledger = _rows(krp, "effects")
        _require(not any(expected_source_sha256 in r["idempotency_key"] for r in ledger),
                 "SELECTED_EFFECT_EXISTS")
        ledger_hash = _hash(_json_bytes(ledger))
        new_source = home / "input" / old_source.name
        new_package = home / "output" / old_package.name
        new_receipts = home / "data/production" / job_id
        new_request = dict(old_request, source=str(new_source))
        translated_stage = dict(stage, request_sha256=_hash(_json_bytes(new_request)))
        translated_prompt = dict(prompt, attachments=[dict(attachment, path=str(new_source))])
        translated_upload = [dict(upload[0], path=str(new_source))]
        transformed = dict(originals)
        transformed.update({
            "analysis.json": _json_bytes(translated_stage),
            "analysis-prompt.json": _json_bytes(translated_prompt),
            "analysis-upload.json": _json_bytes(translated_upload),
        })
        archive.mkdir()  # Exclusive owner claim; never reuse or erase prior evidence.
        try:
            _save_database(campaign, archive / "original/campaign.sqlite3")
            _save_database(krp, archive / "original/krp.sqlite3")
            _put(archive / "original/settings.json", settings_bytes)
            _put(archive / "original/source" / old_source.name, source_bytes)
            for name, data in originals.items():
                _put(archive / "original/receipts" / name, data)
            archive_hashes = {
                p.relative_to(archive).as_posix(): _hash(_file(p))
                for p in (archive / "original").rglob("*") if p.is_file()
            }
            _put(archive / "before.json", _json_bytes({
                "schema": "thoremix.failed-analysis-archive.v1", "job_id": job_id,
                "source_sha256": expected_source_sha256, "files": archive_hashes,
                "krp_rows": len(ledger), "krp_rows_sha256": ledger_hash,
            }))
            # Sources must still match the validated snapshot before any target work.
            _require(_file(root / "config/settings.json") == settings_bytes
                     and _file(old_source) == source_bytes
                     and all(_file(receipt_dir / n) == b for n, b in originals.items()),
                     "SOURCE_CHANGED_DURING_SNAPSHOT")
            for path, tables, before in (
                (root / "data/campaign.sqlite3", _CAMPAIGN, campaign),
                (root / "data/krp/state.sqlite3", _KRP, krp),
            ):
                with closing(_snapshot(path, tables)) as current:
                    _require(all(_rows(current, t) == _rows(before, t) for t in tables),
                             "DATABASE_CHANGED_DURING_SNAPSHOT")
            _require(not home.exists() or (home.is_dir() and not any(home.iterdir())), "DESTINATION_NOT_EMPTY")
            home.mkdir(exist_ok=True)
            _put(new_source, source_bytes)
            (home / "output").mkdir()
            for name, data in transformed.items():
                _put(new_receipts / name, data)
            _save_database(campaign, home / "data/campaign.sqlite3")
            new_detail = dict(detail, production_receipts=str(new_receipts))
            with closing(sqlite3.connect(home / "data/campaign.sqlite3")) as target:
                with target:
                    target.execute("DELETE FROM publication_slots")
                    target.execute("DELETE FROM source_errors")
                    target.execute("DELETE FROM production_attempts WHERE job_id<>?", (job_id,))
                    target.execute("DELETE FROM jobs WHERE id<>?", (job_id,))
                    target.execute("UPDATE jobs SET source=?,package_dir=?,detail=? WHERE id=?",
                                   (str(new_source), str(new_package), _json_bytes(new_detail).decode("utf-8"), job_id))
                target.execute("VACUUM")
            _put(home / "data/krp/state.sqlite3", _file(archive / "original/krp.sqlite3"))
            with closing(_snapshot(home / "data/krp/state.sqlite3", _KRP)) as copied_krp:
                _require(_rows(copied_krp, "effects") == ledger, "LEDGER_COPY_CHANGED")
            _require(all(_hash(_file(archive / p)) == h for p, h in archive_hashes.items()), "ARCHIVE_CHANGED")
            receipt = {
                "schema": "thoremix.failed-analysis-snapshot.v1",
                "state": "SNAPSHOT_READY_NOT_RESUMED", "created_at": datetime.now(timezone.utc).isoformat(),
                "job_id": job_id, "source_sha256": expected_source_sha256,
                "source_root": str(root), "source_input_root": str(inputs),
                "destination_home": str(home), "archive_dir": str(archive),
                "paths": {
                    "source": {"before": job["source"], "after": str(new_source)},
                    "package_dir": {"before": job["package_dir"], "after": str(new_package)},
                    "production_receipts": {"before": str(receipt_dir), "after": str(new_receipts)},
                },
                "request_sha256": {"before": stage["request_sha256"], "after": translated_stage["request_sha256"]},
                "receipts": {name: {"before": _hash(originals[name]), "after": _hash(_file(new_receipts / name))}
                             for name in _RECEIPTS},
                "databases": {
                    "campaign_before": archive_hashes["original/campaign.sqlite3"],
                    "campaign_after": _hash(_file(home / "data/campaign.sqlite3")),
                    "krp_before": archive_hashes["original/krp.sqlite3"],
                    "krp_after": _hash(_file(home / "data/krp/state.sqlite3")),
                },
                "krp": {"rows": len(ledger), "rows_sha256": ledger_hash},
                "invariants": {
                    "provider_bytes_preserved": True, "source_bytes_preserved": True,
                    "selected_job_and_attempt_only": True, "selected_publication_absent": True,
                    "full_krp_ledger_preserved": True, "stage_state": "FAILED",
                    "profiles_copied": False, "settings_created": False, "execution_started": False,
                },
            }
            _put(archive / "receipt.json", _json_bytes(receipt))
            _put(home / "migration-receipt.json", _json_bytes(receipt))
            return receipt
        except Exception as exc:
            _put(archive / "failure.json", _json_bytes({
                "state": "INCOMPLETE_DO_NOT_RESUME", "job_id": job_id, "error_type": type(exc).__name__,
            }))
            raise
