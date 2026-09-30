"""Bounded, offline failed-analysis snapshot tests; no provider or browser calls."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.thoremix.migration import MigrationRejected, snapshot_failed_analysis_resume

JOB = "a" * 32
OTHER = "b" * 32


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def rows(path, table):
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        return [dict(r) for r in db.execute("SELECT * FROM " + table + " ORDER BY 1")]


class FailedAnalysisMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "legacy"
        self.inputs = self.base / "old-input"
        self.inputs.mkdir()
        self.source = self.inputs / "nguon.jfif"
        self.source.write_bytes(b"original image bytes")
        self.sha = digest(self.source.read_bytes())
        self.destination = self.base / "owned"
        self.archive = self.base / "archive"
        write_json(self.root / "config/settings.json",
                   {"root": str(self.root), "input_dir": str(self.inputs), "enabled": False})
        self.receipts = self.root / "data/production" / JOB
        self.receipts.mkdir(parents=True)
        self.old_request = {"source": str(self.source), "source_sha256": self.sha}
        write_json(self.receipts / "analysis.json", {
            "schema_version": 1, "stage": "analysis", "source_sha256": self.sha,
            "request_sha256": digest(canonical(self.old_request)), "state": "FAILED",
            "progress": {"conversation_url": "https://chatgpt.com/c/bound"},
            "result": {"state": "qa_failed", "reason": "STORY_DIALOGUE_TOO_LONG"}})
        self.upload = [{"name": self.source.name, "path": str(self.source),
                        "size_bytes": self.source.stat().st_size, "sha256": self.sha}]
        write_json(self.receipts / "analysis-prompt.json",
                   {"text": "frozen prompt", "attachments": [{"path": str(self.source), "sha256": self.sha}]})
        write_json(self.receipts / "analysis-upload.json", self.upload)
        write_json(self.receipts / "analysis-provider.json", {
            "state": "verified", "conversation_url": "https://chatgpt.com/c/bound",
            "conversation_id": "bound", "assistant_message_id": "exact-message",
            "text": "unchanged reply", "attachments": [self.source.name],
            "attachment_receipts": self.upload,
            "submitted_prompt_sha256": None, "submit_boundary_crossed": None})
        self.campaign = self.root / "data/campaign.sqlite3"
        db = sqlite3.connect(self.campaign)
        self.addCleanup(db.close)
        db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA wal_autocheckpoint=0;
            CREATE TABLE jobs(id TEXT PRIMARY KEY, slot TEXT UNIQUE NOT NULL,
              source TEXT NOT NULL, source_sha256 TEXT UNIQUE NOT NULL,
              package_dir TEXT UNIQUE NOT NULL, state TEXT NOT NULL,
              detail TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE source_errors(path TEXT PRIMARY KEY, reason TEXT NOT NULL, observed_at TEXT NOT NULL);
            CREATE TABLE production_attempts(job_id TEXT PRIMARY KEY REFERENCES jobs(id),
              started_day TEXT NOT NULL, started_at TEXT NOT NULL, status TEXT NOT NULL,
              completed_day TEXT, completed_at TEXT, reason TEXT NOT NULL DEFAULT '');
            CREATE TABLE publication_slots(slot TEXT PRIMARY KEY, job_id TEXT,
              state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}');
        """)
        detail = json.dumps({"production_stage": "analysis", "production_receipts": str(self.receipts),
                             "production_error": "qa_failed"})
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", (
            JOB, "slot-1", str(self.source), self.sha, str(self.inputs / "video/package-one"),
            "production_failed", detail, "created", "updated"))
        db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)", (
            OTHER, "slot-2", str(self.inputs / "other.jpg"), "f" * 64,
            str(self.inputs / "video/package-two"), "published", "{}", "earlier", "later"))
        db.execute("INSERT INTO production_attempts VALUES(?,?,?,?,?,?,?)",
                   (JOB, "day", "start", "failed", "day", "end", "qa_failed:analysis"))
        db.execute("INSERT INTO publication_slots VALUES(?,?,?,?)", ("slot-2", OTHER, "confirmed", "{}"))
        db.commit()
        self.writer = db  # Keep WAL open: raw main-file copying loses these rows.
        self.krp = self.root / "data/krp/state.sqlite3"
        self.krp.parent.mkdir()
        with sqlite3.connect(self.krp) as journal:
            journal.executescript("""
                CREATE TABLE effects(operation_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
                  platform TEXT NOT NULL, actor TEXT NOT NULL, profile TEXT NOT NULL,
                  asset_sha256 TEXT, payload_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                  state TEXT NOT NULL, permalink TEXT, external_id TEXT, reason TEXT,
                  evidence_json TEXT NOT NULL DEFAULT '{}', attempts INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            """)
            for i, state in enumerate(["confirmed", "unknown"]):
                journal.execute("INSERT INTO effects VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    str(i), f"thoremix:{'f' * 64}:publish:{i}", "publish", "facebook", "actor",
                    "thoremix-social", "e" * 64, digest(b'{"path":"historical"}'),
                    '{"path":"historical"}', state, None, None, None, "{}", 1, "old", "old"))

    def run_snapshot(self):
        return snapshot_failed_analysis_resume(
            self.root, self.destination, JOB, source_input_root=self.inputs,
            expected_source_sha256=self.sha, archive_dir=self.archive)

    def test_wal_snapshot_keeps_exact_identity_and_full_ledger_without_replay(self):
        provider = (self.receipts / "analysis-provider.json").read_bytes()
        before = {p.name: p.read_bytes() for p in self.receipts.iterdir()}
        original_job = rows(self.campaign, "jobs")[0]
        original_ledger = rows(self.krp, "effects")
        receipt = self.run_snapshot()
        target = self.destination / "data/production" / JOB
        new_source = self.destination / "input" / self.source.name
        job = rows(self.destination / "data/campaign.sqlite3", "jobs")
        self.assertEqual(len(job), 1)
        self.assertEqual(job[0]["id"], JOB)
        self.assertEqual(job[0]["slot"], "slot-1")
        self.assertEqual(job[0]["state"], "production_failed")
        self.assertEqual(job[0]["source_sha256"], self.sha)
        self.assertEqual(job[0]["source"], str(new_source))
        self.assertEqual(job[0]["package_dir"], str(self.destination / "output/package-one"))
        self.assertEqual(rows(self.destination / "data/campaign.sqlite3", "production_attempts"),
                         rows(self.campaign, "production_attempts"))
        self.assertEqual(rows(self.destination / "data/campaign.sqlite3", "publication_slots"), [])
        self.assertEqual(rows(self.destination / "data/krp/state.sqlite3", "effects"), original_ledger)
        self.assertEqual((target / "analysis-provider.json").read_bytes(), provider)
        self.assertEqual(new_source.read_bytes(), self.source.read_bytes())
        stage = json.loads((target / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(stage["state"], "FAILED")
        self.assertEqual(stage["request_sha256"],
                         digest(canonical({"source": str(new_source), "source_sha256": self.sha})))
        self.assertEqual(json.loads((target / "analysis-prompt.json").read_text())["text"], "frozen prompt")
        self.assertEqual(json.loads((target / "analysis-upload.json").read_text())[0]["path"], str(new_source))
        self.assertEqual(rows(self.campaign, "jobs")[0], original_job)
        self.assertEqual({p.name: p.read_bytes() for p in self.receipts.iterdir()}, before)
        for name, content in before.items():
            self.assertEqual((self.archive / "original/receipts" / name).read_bytes(), content)
        self.assertEqual(len(rows(self.archive / "original/campaign.sqlite3", "jobs")), 2)
        self.assertEqual(receipt["state"], "SNAPSHOT_READY_NOT_RESUMED")
        self.assertEqual(receipt["krp"]["rows"], 2)
        self.assertNotIn("payload_json", json.dumps(receipt))
        self.assertFalse((self.inputs / ".thoremix").exists())
        self.assertFalse((self.destination / "config").exists())
        self.assertFalse((self.destination / "data/krp/profiles").exists())

        from agent.thoremix.story_stages import StageJournal, StageRejected
        journal = StageJournal(target, source_sha256=self.sha)
        request = {"source": str(new_source), "source_sha256": self.sha}
        def forbid(_):
            self.fail("migration/reconciliation must not make a new provider attempt")
        with self.assertRaises(StageRejected):
            journal.run("analysis", request, forbid, reconcile=lambda *_: {"state": "verified"})
        # Canonical retry_story performs this explicit transition only after authorization.
        stage["state"] = "UNKNOWN"
        write_json(target / "analysis.json", stage)
        calls = []
        def reconcile(record, progress):
            calls.append(record["progress"]["conversation_url"])
            return {"state": "verified", "files": []}
        self.assertEqual(journal.run("analysis", request, forbid, reconcile=reconcile)["state"], "verified")
        self.assertEqual(calls, ["https://chatgpt.com/c/bound"])

    def test_refuses_changed_source_or_failed_stage_intent(self):
        self.source.write_bytes(b"changed image")
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.destination.exists())
        self.source.write_bytes(b"original image bytes")
        stage = json.loads((self.receipts / "analysis.json").read_text())
        stage["request_sha256"] = "0" * 64
        write_json(self.receipts / "analysis.json", stage)
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.archive.exists())

    def test_refuses_attachment_drift_before_creating_snapshot(self):
        upload = list(self.upload)
        upload[0] = dict(upload[0], path=str(self.inputs / "wrong.jpg"))
        write_json(self.receipts / "analysis-upload.json", upload)
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.destination.exists())

    def test_refuses_later_stage_package_or_selected_publication(self):
        extra = self.receipts / "images.json"
        write_json(extra, {"state": "UNKNOWN"})
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        extra.unlink()
        package = self.inputs / "video/package-one"
        package.mkdir(parents=True)
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        package.rmdir()
        self.writer.execute("INSERT INTO publication_slots VALUES(?,?,?,?)", ("slot-1", JOB, "unknown", "{}"))
        self.writer.commit()
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.destination.exists())

    def test_refuses_existing_selected_effect_without_touching_ledger(self):
        with sqlite3.connect(self.krp) as db:
            db.execute("UPDATE effects SET idempotency_key=? WHERE operation_id='1'",
                       (f"thoremix:{self.sha}:publish:facebook",))
        before = self.krp.read_bytes()
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertEqual(self.krp.read_bytes(), before)

    def test_refuses_reuse_overlap_and_enabled_source(self):
        self.destination = self.inputs / "owned"
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.destination = self.base / "owned"
        self.destination.mkdir()
        (self.destination / "sentinel").write_bytes(b"must remain")
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertEqual((self.destination / "sentinel").read_bytes(), b"must remain")
        self.destination = self.base / "other-owned"
        write_json(self.root / "config/settings.json",
                   {"root": str(self.root), "input_dir": str(self.inputs), "enabled": True})
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.destination.exists())

    def test_refuses_hardlinked_receipt_and_leaves_source_unchanged(self):
        original = self.receipts / "analysis-provider.json"
        (self.base / "provider-link").hardlink_to(original)
        with self.assertRaises(MigrationRejected):
            self.run_snapshot()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
