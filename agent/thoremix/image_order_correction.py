"""Audited permutation of existing story images before any paid Flow intent."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .analysis_correction import canonical, digest
from .config import Settings, atomic_json
from .core import Campaign, campaign_operation, now_iso, sha256
from .story_assets import validate_draft
from .story_stages import StageJournal, StageUncertain

SCHEMA = "thoremix.image-order-review.v1"
AUDIT = "image-order-review"


def _read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 4 * 1024**2:
        raise ValueError("IMAGE_ORDER_RECORD_TOO_LARGE")
    return json.loads(raw)


def _put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _shape(spec):
    import re
    if (type(spec) is not dict or set(spec) != {"schema", "job_id", "source_sha256",
            "images_sha256", "provider_sha256", "order", "reviewed_by", "evidence"}
            or spec["schema"] != SCHEMA
            or not re.fullmatch("[0-9a-f]{32}", str(spec["job_id"]))):
        raise ValueError("IMAGE_ORDER_SPEC_INVALID")
    for key in ("source_sha256", "images_sha256", "provider_sha256"):
        if not re.fullmatch("[0-9a-f]{64}", str(spec[key])):
            raise ValueError("IMAGE_ORDER_SPEC_INVALID")
    if any(type(spec[k]) is not str or not 1 <= len(spec[k].strip()) <= 2000
           for k in ("reviewed_by", "evidence")):
        raise ValueError("IMAGE_ORDER_EVIDENCE_REQUIRED")
    order = spec["order"]
    if (type(order) is not list or not 1 <= len(order) <= 4
            or any(type(i) is not int for i in order) or sorted(order) != list(range(len(order)))):
        raise ValueError("IMAGE_ORDER_PERMUTATION_INVALID")


def _bound(settings, job, spec):
    _shape(spec)
    directory = settings.data / "production" / job["id"]
    if (spec["job_id"] != job["id"] or spec["source_sha256"] != job["source_sha256"]
            or sha256(Path(job["source"])) != spec["source_sha256"]
            or sha256(directory / "images.json") != spec["images_sha256"]
            or sha256(directory / "images/provider.json") != spec["provider_sha256"]):
        raise ValueError("IMAGE_ORDER_BINDING_CHANGED")
    stage = _read(directory / "images.json")
    if (stage.get("state") != "COMPLETED" or stage.get("source_sha256") != spec["source_sha256"]
            or stage.get("result", {}).get("state") != "verified"):
        raise ValueError("IMAGE_ORDER_IMAGES_NOT_COMPLETE")
    files = stage["result"]["files"]
    if len(files) != len(spec["order"]):
        raise ValueError("IMAGE_ORDER_PERMUTATION_INVALID")
    StageJournal._validate_files(stage["result"])
    if (any(not Path(item["path"]).resolve().is_relative_to((directory / "images").resolve()) for item in files)
            or len({item["sha256"] for item in files}) != len(files)):
        raise ValueError("IMAGE_ORDER_ASSET_INVALID")
    return directory, stage["result"]


def _flow_clear(directory, files, source_hash):
    flow = directory / "flow"
    allowed = {"uploads.json", "readiness.json", "preparation-error.json"}
    if flow.exists() and any(p.name not in allowed or not p.is_file() for p in flow.iterdir()):
        raise ValueError("IMAGE_ORDER_FLOW_EFFECT_EXISTS")
    path = flow / "uploads.json"
    if not path.exists():
        return None
    from agent.services.flow_browser_state import BrowserStateStore
    value = BrowserStateStore(path, "thoremix-" + source_hash[:20]).load()
    expected = {(item["sha256"], Path(item["path"]).name) for item in files}
    if value["operation_projects"]:
        raise ValueError("IMAGE_ORDER_FLOW_EFFECT_EXISTS")
    for key, item in value["intents"].items():
        attrs, receipt = item["attributes"], item["receipt"]
        if (item["kind"] != "upload" or item["state"] != "COMPLETED"
                or (attrs.get("image_sha256"), attrs.get("file_name")) not in expected
                or not receipt or receipt.get("project_id") != attrs.get("project_id")
                or not receipt.get("media_id")
                or key != f"upload:{attrs['project_id']}:{attrs['image_sha256']}:{attrs['file_name']}"):
            raise ValueError("IMAGE_ORDER_UPLOAD_UNCERTAIN")
    return sha256(path)


def _preflight(directory, files, source_hash):
    uploads_hash = _flow_clear(directory, files, source_hash)
    # These stages could consume or publish a generated video, so none may exist.
    for name in ("video_review", "highest", "audio", "copy", "affiliate", "finishing"):
        if any(directory.glob(name + "*")):
            raise ValueError("IMAGE_ORDER_DOWNSTREAM_EXISTS")
    review = directory / "image_review.json"
    if review.exists() and (_read(review).get("state") != "COMPLETED"
                            or _read(review).get("source_sha256") != source_hash):
        raise ValueError("IMAGE_ORDER_REVIEW_UNCERTAIN")
    video = directory / "video.json"
    if video.exists():
        value = _read(video)
        if (value.get("state") != "BLOCKED" or value.get("source_sha256") != source_hash
                or value.get("result", {}).get("state") != "blocked"
                or value.get("result", {}).get("not_submitted") is not True):
            raise ValueError("IMAGE_ORDER_VIDEO_UNCERTAIN")
    return uploads_hash


def _plan(path):
    value = _read(path)
    if (value.get("schema") != "thoremix.image-order-plan.v1"
            or digest(canonical(value["spec"])) != value.get("spec_sha256")):
        raise ValueError("IMAGE_ORDER_AUDIT_CHANGED")
    _shape(value["spec"])
    return value


def _apply(settings, job, plan):
    spec = plan["spec"]
    directory, images = _bound(settings, job, spec)
    audit = directory / AUDIT
    if _preflight(directory, images["files"], spec["source_sha256"]) != plan["uploads_sha256"]:
        raise ValueError("IMAGE_ORDER_UPLOADS_CHANGED")
    # Retire exact old QA/input fingerprints, preserving every byte for audit.
    for name, expected in plan["retired"].items():
        active, retained = directory / name, audit / "retired" / name
        if retained.exists() and sha256(retained) != expected:
            raise ValueError("IMAGE_ORDER_AUDIT_CHANGED")
        if active.exists():
            if sha256(active) != expected or retained.exists():
                raise ValueError("IMAGE_ORDER_STAGE_CHANGED")
            retained.parent.mkdir(parents=True, exist_ok=True)
            active.rename(retained)
        elif not retained.exists():
            raise ValueError("IMAGE_ORDER_STAGE_MISSING")
    folder = Path(job["package_dir"])
    current = _read(folder / "draft.json")
    if current not in (plan["draft_before"], plan["draft_after"]):
        raise ValueError("IMAGE_ORDER_DRAFT_CHANGED")
    before, after = plan["draft_before"]["frames"], plan["draft_after"]["frames"]
    ordered = [images["files"][i] for i in spec["order"]]
    for old, new, source in zip(before, after, ordered):
        target = folder / new["path"]
        if sha256(target) not in {old["sha256"], new["sha256"]}:
            raise ValueError("IMAGE_ORDER_DRAFT_CHANGED")
        raw = Path(source["path"]).read_bytes()
        if digest(raw) != new["sha256"]:
            raise ValueError("IMAGE_ORDER_ASSET_CHANGED")
        # Atomic replacement makes an interrupted apply resumable from either hash.
        temporary = audit / ("frame-" + target.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, target)
    atomic_json(folder / "draft.json", plan["draft_after"])
    validate_draft(folder, job)
    _put(audit / "applied.json", canonical({"schema":"thoremix.image-order-applied.v1",
         "plan_sha256":sha256(audit / "plan.json"), "recorded_at":now_iso()}))


def review_image_order(settings, job_id, spec_path):
    from agent.private_runtime import current_runtime
    path = Path(spec_path).resolve(strict=True)
    if current_runtime() is not None:
        current_runtime().data_path(path)
    spec = _read(path); _shape(spec)
    if job_id != spec["job_id"]:
        raise ValueError("IMAGE_ORDER_JOB_MISMATCH")
    with campaign_operation(settings):
        if Settings.load(settings.directory).enabled:
            raise ValueError("IMAGE_ORDER_REQUIRES_PAUSE")
        job = Campaign(settings).get(job_id)
        directory, images = _bound(settings, job, spec)
        audit = directory / AUDIT
        plan_path = audit / "plan.json"
        if plan_path.exists():
            plan = _plan(plan_path)
            if canonical(spec) != canonical(plan["spec"]):
                raise ValueError("IMAGE_ORDER_ALREADY_REVIEWED")
            if (audit / "applied.json").exists():
                ensure_image_order_ready(settings, job)
                return {"state":"image_order_already_applied","job_id":job_id}
        else:
            uploads_hash = _preflight(directory, images["files"], spec["source_sha256"])
            folder = Path(job["package_dir"])
            if folder.resolve().parent != settings.output.resolve() or (folder / "package.json").exists():
                raise ValueError("IMAGE_ORDER_PACKAGE_EXISTS")
            draft = validate_draft(folder, job)
            expected = [item["sha256"] for item in images["files"]]
            if [item["sha256"] for item in draft["frames"]] != expected:
                raise ValueError("IMAGE_ORDER_DRAFT_CHANGED")
            # Stable suffixes avoid altering file identity or existing upload keys.
            if len({Path(item["path"]).suffix.lower() for item in images["files"]}) != 1:
                raise ValueError("IMAGE_ORDER_MIXED_FORMATS")
            after = json.loads(json.dumps(draft))
            for target, index in zip(after["frames"], spec["order"]):
                target["sha256"] = images["files"][index]["sha256"]
            retired = [p for p in directory.glob("image_review*.json")]
            if (directory / "video.json").exists():
                retired.append(directory / "video.json")
            plan = {"schema":"thoremix.image-order-plan.v1","spec":spec,
                    "spec_sha256":digest(canonical(spec)),"recorded_at":now_iso(),
                    "uploads_sha256":uploads_hash,"draft_before":draft,"draft_after":after,
                    "retired":{p.name:sha256(p) for p in retired}}
            _put(plan_path, canonical(plan))
        _apply(settings, job, plan)
        return {"state":"image_order_applied","job_id":job_id,"order":spec["order"],
                "plan_sha256":sha256(plan_path),"media_qa":"NOT_CHECKED"}


def ensure_image_order_ready(settings, job):
    directory = settings.data / "production" / job["id"]
    audit = directory / AUDIT
    if not audit.exists():
        return None
    if not (audit / "plan.json").exists() or not (audit / "applied.json").exists():
        raise StageUncertain("IMAGE_ORDER_APPLY_INCOMPLETE")
    plan = _plan(audit / "plan.json")
    applied = _read(audit / "applied.json")
    if applied.get("plan_sha256") != sha256(audit / "plan.json"):
        raise StageUncertain("IMAGE_ORDER_AUDIT_CHANGED")
    _bound(settings, job, plan["spec"])
    return plan


def reviewed_image_order(settings, job, images):
    plan = ensure_image_order_ready(settings, job)
    if plan is None:
        return images
    if images != _read(settings.data / "production" / job["id"] / "images.json")["result"]:
        raise ValueError("IMAGE_ORDER_BINDING_CHANGED")
    return dict(images, files=[images["files"][i] for i in plan["spec"]["order"]],
                order_review={"plan_sha256":sha256(settings.data / "production" / job["id"] / AUDIT / "plan.json"),
                              "order":plan["spec"]["order"]})
