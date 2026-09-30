"""Hash-bound local source review; never rewrite or resubmit a provider response."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from .core import Campaign, campaign_operation, now_iso, sha256

SCHEMA = "thoremix.analysis-review.v1"
RECEIPT = "analysis-correction.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _spec(value):
    fields = {"schema", "job_id", "source_sha256", "analysis_sha256", "provider_sha256",
              "reviewed_by", "evidence", "analysis", "timing_policy"}
    if type(value) is not dict or set(value) != fields or value["schema"] != SCHEMA:
        raise ValueError("ANALYSIS_REVIEW_INVALID")
    if not re.fullmatch(r"[0-9a-f]{32}", str(value["job_id"])):
        raise ValueError("ANALYSIS_REVIEW_INVALID")
    for name in ("source_sha256", "analysis_sha256", "provider_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value[name])):
            raise ValueError("ANALYSIS_REVIEW_INVALID")
    for name in ("reviewed_by", "evidence"):
        if type(value[name]) is not str or not 1 <= len(value[name].strip()) <= 2000:
            raise ValueError("ANALYSIS_REVIEW_EVIDENCE_REQUIRED")
    from agent.comicreels.prompts import reviewed_speech_rate
    reviewed_speech_rate(value["timing_policy"])
    if value["timing_policy"] is None or type(value["analysis"]) is not dict:
        raise ValueError("ANALYSIS_REVIEW_INVALID")
    from .story_operations import normalize_analysis
    return normalize_analysis(value["analysis"], timing_policy=value["timing_policy"])


def _no_downstream(directory, package):
    allowed = {"analysis.json", "analysis-provider.json", "analysis-prompt.json",
               "analysis-upload.json", "analysis-raw-message.json", RECEIPT, "manual-retries"}
    if any(p.name not in allowed for p in directory.iterdir()):
        raise ValueError("ANALYSIS_REVIEW_DOWNSTREAM_EXISTS")
    if Path(package).exists():
        raise ValueError("ANALYSIS_REVIEW_DOWNSTREAM_EXISTS")


def _read_receipt(path):
    raw = path.read_bytes()
    if len(raw) > 2 * 1024**2:
        raise ValueError("ANALYSIS_REVIEW_INVALID")
    value = json.loads(raw)
    if (set(value) != {"schema", "spec", "spec_sha256", "analysis_before", "recorded_at"}
            or value["schema"] != "thoremix.analysis-review-receipt.v1"
            or digest(canonical(value["spec"])) != value["spec_sha256"]
            or digest(value["analysis_before"].encode("utf-8")) != value["spec"]["analysis_sha256"]):
        raise ValueError("ANALYSIS_REVIEW_CHANGED")
    return value


def _bound_files(spec, source, directory, original):
    if (sha256(Path(source)) != spec["source_sha256"]
            or sha256(directory / "analysis-provider.json") != spec["provider_sha256"]
            or digest(original) != spec["analysis_sha256"]):
        raise ValueError("ANALYSIS_REVIEW_BINDING_CHANGED")
    before = json.loads(original)
    provider = json.loads((directory / "analysis-provider.json").read_bytes())
    if (before.get("stage") != "analysis" or before.get("state") != "FAILED"
            or before.get("source_sha256") != spec["source_sha256"]
            or provider.get("state") not in {"verified", "completed"}
            or not provider.get("assistant_message_id")):
        raise ValueError("ANALYSIS_REVIEW_NOT_FAILED_ANALYSIS")
    return before, provider


def review_analysis(settings, job_id, spec_path):
    """Install a reviewed correction only before any downstream work starts."""
    from agent.private_runtime import current_runtime
    path = Path(spec_path).resolve(strict=True)
    if current_runtime() is not None:
        current_runtime().data_path(path)
    raw = path.read_bytes()
    if len(raw) > 1024**2:
        raise ValueError("ANALYSIS_REVIEW_INVALID")
    spec = json.loads(raw)
    normalized = _spec(spec)
    if job_id != spec["job_id"]:
        raise ValueError("ANALYSIS_REVIEW_JOB_MISMATCH")
    with campaign_operation(settings):
        job = Campaign(settings).get(job_id)
        directory = settings.data / "production" / job_id
        receipt = directory / RECEIPT
        if receipt.exists():
            existing = _read_receipt(receipt)
            if canonical(existing["spec"]) != canonical(spec):
                raise ValueError("ANALYSIS_REVIEW_ALREADY_EXISTS")
            return {"state": "analysis_review_exists", "job_id": job_id,
                    "receipt_sha256": sha256(receipt)}
        if job["state"] != "production_failed" or job["source_sha256"] != spec["source_sha256"]:
            raise ValueError("ANALYSIS_REVIEW_NOT_FAILED_ANALYSIS")
        _no_downstream(directory, job["package_dir"])
        original = (directory / "analysis.json").read_bytes()
        _bound_files(spec, job["source"], directory, original)
        from PIL import Image
        with Image.open(job["source"]) as image:
            width, height = image.size
        for panel in normalized["panels"]:
            if (any(type(panel.get(k)) is not int for k in ("x", "y", "w", "h"))
                    or min(panel["x"], panel["y"]) < 0 or min(panel["w"], panel["h"]) <= 0
                    or panel["x"] + panel["w"] > width or panel["y"] + panel["h"] > height):
                raise ValueError("ANALYSIS_REVIEW_GEOMETRY_INVALID")
        journal = settings.data / "krp" / "state.sqlite3"
        if journal.exists():
            with sqlite3.connect(journal.as_uri() + "?mode=ro", uri=True) as db:
                if db.execute("SELECT 1 FROM effects WHERE idempotency_key LIKE ? LIMIT 1",
                              ("%" + spec["source_sha256"] + "%",)).fetchone():
                    raise ValueError("ANALYSIS_REVIEW_SOCIAL_EFFECT_EXISTS")
        value = {"schema": "thoremix.analysis-review-receipt.v1", "spec": spec,
                 "spec_sha256": digest(canonical(spec)),
                 "analysis_before": original.decode("utf-8"), "recorded_at": now_iso()}
        # Create once. An interrupted partial write fails closed; never replace history.
        with receipt.open("xb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        return {"state": "analysis_review_recorded", "job_id": job_id,
                "receipt_sha256": sha256(receipt), "media_qa": "NOT_CHECKED"}


def reviewed_analysis(settings, request, directory):
    """Consume a correction during the existing failed stage's reconciliation."""
    directory = Path(directory)
    receipt = directory / RECEIPT
    if not receipt.exists():
        return None
    value = _read_receipt(receipt)
    spec = value["spec"]
    normalized = _spec(spec)
    if (directory != settings.data / "production" / spec["job_id"]
            or request["source_sha256"] != spec["source_sha256"]):
        raise ValueError("ANALYSIS_REVIEW_JOB_MISMATCH")
    job = Campaign(settings).get(spec["job_id"])
    if job["source"] != request["source"] or job["source_sha256"] != spec["source_sha256"]:
        raise ValueError("ANALYSIS_REVIEW_JOB_MISMATCH")
    _no_downstream(directory, job["package_dir"])
    before, provider = _bound_files(spec, request["source"], directory,
                                     value["analysis_before"].encode("utf-8"))
    active = json.loads((directory / "analysis.json").read_bytes())
    if active != dict(before, state="UNKNOWN"):
        raise ValueError("ANALYSIS_REVIEW_STAGE_CHANGED")
    proof = {"path": str(receipt), "sha256": sha256(receipt)}
    normalized["analysis_correction"] = {"job_id": spec["job_id"],
        "receipt_sha256": proof["sha256"], "source_sha256": spec["source_sha256"],
        "provider_sha256": spec["provider_sha256"], "media_review_required": True}
    return {"state": "verified", "data": normalized, "files": [proof],
            "provider_receipt": {k: provider[k] for k in ("conversation_url", "assistant_message_id")}}
