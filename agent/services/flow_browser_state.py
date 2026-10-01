"""Durable browser intent receipts, serialized by the caller's profile lease."""

import copy
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

_MAX_BYTES = 4 * 1024 * 1024
_MAX_RECORDS = 4096
_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ATTRIBUTES = {"project_id", "image_sha256", "request_sha256", "idempotency_sha256", "title", "file_name", "mime_type", "rpcid"}
_RECEIPT = {"project_id", "media_id", "title", "operation_id", "workflow_id"}
_ERROR_CODES = {
    "INVALID_INPUT", "INVALID_STATE", "OWNER_MISMATCH", "STATE_READ_FAILED",
    "STATE_WRITE_FAILED", "STATE_LIMIT_EXCEEDED", "INVALID_TRANSITION",
    "RECONCILIATION_REQUIRED",
}


class BrowserStateError(RuntimeError):
    """A fixed, non-sensitive state store error."""

    def __init__(self, code: str):
        self.code = code if code in _ERROR_CODES else "INVALID_STATE"
        super().__init__(self.code)


def _identifier(value) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _key(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 512


def _fields(value, allowed: set[str]) -> bool:
    if not isinstance(value, dict) or not value.keys() <= allowed:
        return False
    for key, item in value.items():
        if key.endswith("_id"):
            valid = _identifier(item)
        elif key in {"title", "file_name"}:
            valid = isinstance(item, str) and len(item) <= 160
        elif key in {"image_sha256", "request_sha256", "idempotency_sha256"}:
            valid = isinstance(item, str) and _SHA256.fullmatch(item) is not None
        elif key == "rpcid":
            valid = isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", item) is not None
        else:
            valid = isinstance(item, str) and item in {"image/png", "image/jpeg", "image/webp"}
        if not valid:
            return False
    return True


def _require(condition: bool, code: str = "INVALID_INPUT") -> None:
    if not condition:
        raise BrowserStateError(code)


def _unique_fields(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


class BrowserStateStore:
    """Single-owner store; callers must hold their profile lease across operations.

    SUBMITTING and UNKNOWN entries never become retryable automatically. Callers
    may reuse COMPLETED receipts but must reconcile ambiguous source effects.
    """

    def __init__(self, path: Path, owner_key: str):
        _require(_key(owner_key))
        self.path = Path(path)
        self.owner_key = owner_key

    def load(self) -> dict:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(_MAX_BYTES + 1)
        except FileNotFoundError:
            return {
                "schema_version": 1, "owner_key": self.owner_key,
                "project_id": None, "intents": {}, "operation_projects": {},
            }
        except OSError:
            raise BrowserStateError("STATE_READ_FAILED") from None
        _require(len(raw) <= _MAX_BYTES, "STATE_LIMIT_EXCEEDED")
        try:
            state = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
        except (ValueError, UnicodeError, RecursionError):
            raise BrowserStateError("INVALID_STATE") from None
        self._validate(state)
        return state

    def begin(self, key: str, kind: str, attributes: dict) -> dict:
        _require(_key(key) and isinstance(kind, str) and kind in {"create", "upload", "paid_image", "paid_video"})
        _require(_fields(attributes, _ATTRIBUTES))
        state = self.load()
        existing = state["intents"].get(key)
        if existing is not None:
            _require(existing["state"] == "COMPLETED", "RECONCILIATION_REQUIRED")
            return copy.deepcopy(existing)
        entry = {
            "state": "SUBMITTING", "kind": kind, "attributes": copy.deepcopy(attributes),
            "receipt": None, "created_at": time.time(),
        }
        state["intents"][key] = entry
        self._write(state)
        return copy.deepcopy(entry)

    def complete(self, key: str, receipt: dict) -> None:
        _require(_fields(receipt, _RECEIPT))
        state, entry = self._submitting(key)
        entry["state"] = "COMPLETED"
        entry["receipt"] = copy.deepcopy(receipt)
        self._write(state)

    def mark_unknown(self, key: str) -> None:
        state, entry = self._submitting(key)
        entry["state"] = "UNKNOWN"
        self._write(state)

    def set_project(self, project_id: str) -> None:
        _require(_identifier(project_id))
        state = self.load()
        state["project_id"] = project_id
        self._write(state)

    def remember_operation(self, operation_id: str, project_id: str) -> None:
        _require(_identifier(operation_id) and _identifier(project_id))
        state = self.load()
        state["operation_projects"][operation_id] = project_id
        self._write(state)

    def operation_binding(self, operation_id: str) -> tuple[str, str | None]:
        """Resolve a durable operation/project binding without remote effects.

        Returns ("bound", project_id), ("receipt", project_id), ("missing", None)
        or ("conflict", None). COMPLETED upload and paid-video operation receipts
        can recover the binding after a narrow post-receipt crash.
        """
        _require(_identifier(operation_id))
        state = self.load()
        direct = state["operation_projects"].get(operation_id)
        receipt_projects = set()
        for entry in state["intents"].values():
            if (entry["kind"] not in {"upload", "paid_video"}
                    or entry["state"] != "COMPLETED"):
                continue
            receipt = entry.get("receipt")
            if (isinstance(receipt, dict)
                    and receipt.get("operation_id") == operation_id
                    and _identifier(receipt.get("project_id"))):
                receipt_projects.add(receipt["project_id"])
        if direct is not None:
            if receipt_projects and receipt_projects != {direct}:
                return "conflict", None
            return "bound", direct
        if len(receipt_projects) > 1:
            return "conflict", None
        if len(receipt_projects) == 1:
            return "receipt", next(iter(receipt_projects))
        return "missing", None

    def lookup(self, key: str) -> dict | None:
        _require(_key(key))
        return copy.deepcopy(self.load()["intents"].get(key))

    def _submitting(self, key: str) -> tuple[dict, dict]:
        _require(_key(key))
        state = self.load()
        entry = state["intents"].get(key)
        _require(entry is not None and entry["state"] == "SUBMITTING", "INVALID_TRANSITION")
        return state, entry

    def _validate(self, state: dict) -> None:
        code = "INVALID_STATE"
        _require(isinstance(state, dict) and set(state) == {
            "schema_version", "owner_key", "project_id", "intents", "operation_projects",
        }, code)
        _require(type(state["schema_version"]) is int and state["schema_version"] == 1, code)
        _require(_key(state["owner_key"]), code)
        _require(state["owner_key"] == self.owner_key, "OWNER_MISMATCH")
        _require(state["project_id"] is None or _identifier(state["project_id"]), code)
        for field in ("intents", "operation_projects"):
            _require(isinstance(state[field], dict), code)
            _require(len(state[field]) <= _MAX_RECORDS, "STATE_LIMIT_EXCEEDED")
        for operation, project in state["operation_projects"].items():
            _require(_identifier(operation) and _identifier(project), code)
        for key, entry in state["intents"].items():
            _require(_key(key) and isinstance(entry, dict), code)
            _require(set(entry) == {"state", "kind", "attributes", "receipt", "created_at"}, code)
            _require(isinstance(entry["state"], str)
                     and entry["state"] in {"SUBMITTING", "UNKNOWN", "COMPLETED"}, code)
            _require(isinstance(entry["kind"], str) and entry["kind"] in {"create", "upload", "paid_image", "paid_video"}, code)
            _require(_fields(entry["attributes"], _ATTRIBUTES), code)
            receipt = entry["receipt"]
            _require(receipt is None or _fields(receipt, _RECEIPT), code)
            _require(entry["state"] != "COMPLETED" or receipt is not None, code)
            created = entry["created_at"]
            _require(type(created) in (int, float), code)
            try:
                valid_time = math.isfinite(created) and created >= 0
            except OverflowError:
                valid_time = False
            _require(valid_time, code)

    def _write(self, state: dict) -> None:
        self._validate(state)
        try:
            raw = json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, UnicodeError, TypeError):
            raise BrowserStateError("INVALID_INPUT") from None
        _require(len(raw) <= _MAX_BYTES, "STATE_LIMIT_EXCEEDED")
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{self.path.name}.", suffix=".tmp",
                dir=self.path.parent, delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise BrowserStateError("STATE_WRITE_FAILED") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
