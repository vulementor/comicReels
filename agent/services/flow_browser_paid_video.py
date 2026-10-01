"""Durable/idempotent one-shot paid video safety boundary."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import BrowserCommandError, uuid_value


@dataclass(frozen=True)
class PaidVideoCommand:
    rpcid: str
    freq: str
    project_id: str
    request_sha256: str


class FlowPaidVideoGate:
    """Exactly one existing video RPC effect with durable reconciliation."""

    ALLOWED_RPCIDS = frozenset({
        fb.RPC_GEN_VIDEO,
        fb.RPC_GEN_VIDEO_TEXT,
        fb.RPC_GEN_VIDEO_FIRST_LAST,
        fb.RPC_GEN_VIDEO_REFERENCES,
    })
    _OPERATION_RPCIDS = frozenset({
        fb.RPC_GEN_VIDEO,
        fb.RPC_GEN_VIDEO_FIRST_LAST,
    })

    def __init__(self, state, dispatch, *, dispatch_enabled=False, authorization=None):
        self._state = state
        self._dispatch = dispatch
        self.dispatch_enabled = dispatch_enabled is True
        self._authorization = authorization

    @staticmethod
    def _error(code: str, effect: str = "not_submitted", status: int = 409) -> dict:
        return {"status": status, "error": code, "effect": effect}

    @staticmethod
    def _walk(node):
        yield node
        if isinstance(node, list):
            for item in node:
                yield from FlowPaidVideoGate._walk(item)

    def validate(self, params: dict) -> PaidVideoCommand:
        try:
            if not isinstance(params, dict) or set(params) != {
                "rpcid", "freq", "projectId", "captchaAction",
            }:
                raise ValueError
            rpcid = params["rpcid"]
            if rpcid not in self.ALLOWED_RPCIDS:
                raise ValueError
            if params["captchaAction"] != fb.CAPTCHA_VIDEO:
                raise ValueError
            project_id = uuid_value(params["projectId"])
            freq = params["freq"]
            if not isinstance(freq, str) or not 1 <= len(freq.encode()) <= 64 * 1024:
                raise ValueError
            outer = json.loads(freq)
            if (not isinstance(outer, list) or len(outer) != 1
                    or not isinstance(outer[0], list) or len(outer[0]) != 1):
                raise ValueError
            envelope = outer[0][0]
            if (not isinstance(envelope, list) or len(envelope) != 4
                    or envelope[0] != rpcid or envelope[2:] != [None, "generic"]):
                raise ValueError
            body = json.loads(envelope[1])
            if not isinstance(body, list):
                raise ValueError

            seen_project = False
            captcha_slots = 0
            for node in self._walk(body):
                if node == project_id:
                    seen_project = True
                if (isinstance(node, list) and len(node) == 2
                        and node[0] == fb.CAPTCHA_SLOT and node[1] == 1):
                    captcha_slots += 1
            if not seen_project or captcha_slots < 1:
                raise ValueError

            return PaidVideoCommand(
                rpcid=rpcid,
                freq=freq,
                project_id=project_id,
                request_sha256=hashlib.sha256(freq.encode()).hexdigest(),
            )
        except Exception:
            raise BrowserCommandError("PAID_RECIPE_UNVERIFIED") from None

    def intent(self, command: PaidVideoCommand, idempotency_key: str) -> tuple[str, dict]:
        if (not isinstance(idempotency_key, str)
                or not 1 <= len(idempotency_key) <= 160
                or not re.fullmatch(r"[A-Za-z0-9._:-]+", idempotency_key)):
            raise BrowserCommandError("PAID_IDEMPOTENCY_INVALID")
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        return f"paid-video:{digest}", {
            "project_id": command.project_id,
            "request_sha256": command.request_sha256,
            "idempotency_sha256": digest,
            "rpcid": command.rpcid,
        }

    def _operation_receipt(self, payload, command: PaidVideoCommand) -> dict:
        operation = fb.read_operation(payload)
        operation_id = uuid_value(operation.operation_id)
        project_id = uuid_value(operation.project_id)
        if project_id != command.project_id:
            raise BrowserCommandError("PAID_RECEIPT_UNVERIFIED")
        return {"project_id": project_id, "operation_id": operation_id}

    def _media_receipt(self, payload, command: PaidVideoCommand) -> dict:
        submitted = fb.read_video_submit(payload, require_workflow=True)
        project_id = uuid_value(submitted.get("project_id"))
        media_id = uuid_value(submitted.get("media_id"))
        workflow_id = uuid_value(submitted.get("workflow_id"))
        if project_id != command.project_id:
            raise BrowserCommandError("PAID_RECEIPT_UNVERIFIED")
        return {
            "project_id": project_id,
            "media_id": media_id,
            "workflow_id": workflow_id,
        }

    def _parse_receipt(self, body: str, command: PaidVideoCommand) -> dict:
        payload = fb.first_payload(body, command.rpcid)
        if command.rpcid in self._OPERATION_RPCIDS:
            return self._operation_receipt(payload, command)
        if command.rpcid == fb.RPC_GEN_VIDEO_TEXT:
            return self._media_receipt(payload, command)
        if command.rpcid == fb.RPC_GEN_VIDEO_REFERENCES:
            if isinstance(payload, list) and len(payload) > 3 and payload[3] is not None:
                return self._media_receipt(payload, command)
            return self._operation_receipt(payload, command)
        raise BrowserCommandError("PAID_RECIPE_UNVERIFIED")

    def _completed(self, entry: dict, attributes: dict, *, reused: bool) -> dict:
        try:
            if (entry.get("kind") != "paid_video"
                    or entry.get("state") != "COMPLETED"
                    or entry.get("attributes") != attributes):
                return self._error("PAID_IDEMPOTENCY_CONFLICT")
            receipt = entry.get("receipt")
            if not isinstance(receipt, dict):
                raise ValueError
            project_id = uuid_value(receipt.get("project_id"))
            if project_id != attributes["project_id"]:
                return self._error("PAID_IDEMPOTENCY_CONFLICT")

            data = {"projectId": project_id}
            if "operation_id" in receipt:
                data.update(
                    receiptKind="operation",
                    operationId=uuid_value(receipt.get("operation_id")),
                )
            else:
                data.update(
                    receiptKind="media",
                    mediaId=uuid_value(receipt.get("media_id")),
                    workflowId=uuid_value(receipt.get("workflow_id")),
                )
            return {
                "status": 200,
                "data": data,
                "effect": "completed",
                "reused": reused,
            }
        except Exception:
            return self._error("PAID_RECONCILIATION_REQUIRED", "unknown")

    def submit(self, params: dict, *, idempotency_key: str, authorization=None,
               timeout: float = 300) -> dict:
        if not self.dispatch_enabled:
            return self._error("PAID_DISPATCH_DISABLED", status=403)
        if self._authorization is None or authorization is not self._authorization:
            return self._error("PAID_AUTHORIZATION_REQUIRED", status=403)

        try:
            command = self.validate(params)
            key, attributes = self.intent(command, idempotency_key)
        except BrowserCommandError as error:
            return self._error(str(error))

        existing = self._state.lookup(key)
        if existing is not None:
            if existing.get("attributes") != attributes:
                return self._error("PAID_IDEMPOTENCY_CONFLICT")
            if existing.get("state") == "COMPLETED":
                return self._completed(existing, attributes, reused=True)
            return self._error("PAID_RECONCILIATION_REQUIRED", "unknown")

        try:
            entry = self._state.begin(key, "paid_video", attributes)
        except Exception:
            return self._error("PAID_STATE_FAILED")
        if entry.get("state") == "COMPLETED":
            return self._completed(entry, attributes, reused=True)

        try:
            result = self._dispatch(command, timeout)
            if (not isinstance(result, dict) or result.get("status") != 200
                    or result.get("body_complete") is not True
                    or result.get("effect") != "completed"
                    or not isinstance(result.get("data"), str)):
                raise BrowserCommandError("PAID_RECONCILIATION_REQUIRED")
            receipt = self._parse_receipt(result["data"], command)
            self._state.complete(key, receipt)
            entry = self._state.lookup(key)
            if not isinstance(entry, dict):
                raise BrowserCommandError("PAID_RECONCILIATION_REQUIRED")
            return self._completed(entry, attributes, reused=False)
        except BaseException:
            try:
                current = self._state.lookup(key)
                if current is not None and current.get("state") == "SUBMITTING":
                    self._state.mark_unknown(key)
            except Exception:
                pass
            return self._error("PAID_RECONCILIATION_REQUIRED", "unknown")
