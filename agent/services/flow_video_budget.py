"""Exact native single-job Flow credit grant validator, with zero paid effects.

This validates the owner-issued authorization envelope and its aggregate
single-job allocation. It is NOT an authorization issuer or credit spender.
The actual paid provider must separately enforce this contract at submission.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-zA-Z0-9_-]{16,128}$")
_PROJECT = re.compile(r"^[a-zA-Z0-9_-]{5,150}$")


def _digest(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _budget_contract(authorization: dict, request: dict) -> dict:
    """Reject an unbound, changed, stale, over-cap or duplicated credit grant.

    Native ThoRemix owns the approval/actor/SQLite effect journal. This
    method checks the provider-facing boundary contract and does NOT execute
    or promise a successful paid generation.
    """
    if type(authorization) is not dict or type(request) is not dict:
        raise ValueError("NATIVE_VIDEO_BUDGET_INVALID")
    if (authorization.get("schema_version") != 1
            or authorization.get("action") != "resume_blocked_story"
            or type(authorization.get("authorization_id")) is not str
            or _ID.fullmatch(authorization["authorization_id"]) is None
            or not isinstance(authorization.get("authorized_by"), str)
            or not authorization["authorized_by"].strip()):
        raise ValueError("NATIVE_VIDEO_BUDGET_AUTHORIZATION_INVALID")

    jid=request.get("resume_job_id")
    source=request.get("source_sha256")
    evidence=request.get("resume_evidence_sha256")
    if (type(jid) is not str or not re.fullmatch(r"[0-9a-f]{32}",jid)
            or type(source) is not str or _SHA.fullmatch(source) is None
            or type(evidence) is not str or _SHA.fullmatch(evidence) is None
            or authorization.get("job_id") != jid
            or authorization.get("source_sha256") != source
            or authorization.get("evidence_sha256") != evidence):
        raise ValueError("NATIVE_VIDEO_BUDGET_JOB_BINDING_INVALID")

    try:
        timestamp=datetime.fromisoformat(authorization["authorized_at"])
        now=datetime.now(timezone.utc)
        if (timestamp.tzinfo is None or timestamp > now+timedelta(seconds=5)
                or now-timestamp > timedelta(minutes=3)):
            raise ValueError
    except (KeyError,TypeError,ValueError,OverflowError):
        raise ValueError("NATIVE_VIDEO_BUDGET_EXPIRED") from None

    b=authorization.get("budget")
    g=authorization.get("seven_job_budget")
    if type(b) is not dict or type(g) is not dict:
        raise ValueError("NATIVE_VIDEO_BUDGET_INVALID")
    expected={"provider":"google_flow","action":"native_video_generate",
        "currency":"flow_credits","operation":"resume_blocked_story",
        "stage":"video","job_id":jid,"source_sha256":source,
        "evidence_sha256":evidence}
    if any(b.get(k)!=v for k,v in expected.items()):
        raise ValueError("NATIVE_VIDEO_BUDGET_PROVIDER_MISMATCH")
    cost=b.get("quoted_cost_credits")
    cap=b.get("max_cost_credits")
    if (type(cost) not in (int,float) or type(cap) not in (int,float)
            or not math.isfinite(cost) or not math.isfinite(cap)
            or cost != 7 or cap != 7):
        raise ValueError("NATIVE_VIDEO_BUDGET_CAP_EXCEEDED")
    if (type(b.get("project_id")) is not str
            or _PROJECT.fullmatch(b["project_id"]) is None
            or type(b.get("profile_logical_name")) is not str
            or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}",
                                b["profile_logical_name"])
            or type(b.get("account_identity_sha256")) is not str
            or _SHA.fullmatch(b["account_identity_sha256"]) is None
            or not isinstance(b.get("quote_id"),str) or
            not b["quote_id"].startswith("verified-readiness-")):
        raise ValueError("NATIVE_VIDEO_BUDGET_ACCOUNT_INVALID")
    if (b.get("operation_id") != authorization["authorization_id"]
            or g.get("schema_version") != 3
            or g.get("currency") != "flow_credits"
            or g.get("scope") != "single_reviewed_job"
            or g.get("job_ids") != [jid]
            or g.get("reviewed_job_ids") != [jid]
            or g.get("allocations") != {jid: 7}
            or g.get("cap_credits") != 7
            or b.get("aggregate_id") != g.get("batch_id")
            or b.get("aggregate_authorization_sha256") != _digest(g)):
        raise ValueError("NATIVE_VIDEO_BUDGET_AGGREGATE_INVALID")
    return {
        "authorization_sha256":_digest(authorization),
        "provider":"google_flow","action":"native_video_generate",
        "currency":"flow_credits","operation":"resume_blocked_story",
        "stage":"video","job_id":jid,"source_sha256":source,
        "evidence_sha256":evidence,
        "quoted_cost_credits":7.0,"max_cost_credits":7.0,
        "quote_id":b["quote_id"],"operation_id":b["operation_id"],
        "profile_logical_name":b["profile_logical_name"],
        "account_identity_sha256":b["account_identity_sha256"],
        "project_id":b["project_id"],"aggregate_id":g["batch_id"],
        "aggregate_authorization_sha256":_digest(g),
        "enforcement_scope":"requires_provider_paid_submit_boundary",
        "paid_generate_called":False,
    }
