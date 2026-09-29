import json
from uuid import UUID

import pytest

from agent.services import flow_browser_state as state_module
from agent.services.flow_browser_state import BrowserStateError, BrowserStateStore

PROJECT = "11111111-2222-3333-4444-555555555555"
MEDIA = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OPERATION = "01234567-89ab-cdef-0123-456789abcdef"


@pytest.fixture
def store(tmp_path):
    return BrowserStateStore(tmp_path / "state.json", "profile-owner")


def test_absent_state_is_fresh_without_constructor_or_read_writes(tmp_path):
    path = tmp_path / "missing" / "state.json"
    state = BrowserStateStore(path, "profile-owner").load()
    assert state == {
        "schema_version": 1, "owner_key": "profile-owner", "project_id": None,
        "intents": {}, "operation_projects": {},
    }
    assert not path.parent.exists()


def test_begin_is_durable_and_completed_receipt_reused_after_restart(store, tmp_path):
    attributes = {"title": "Dự án"}
    entry = store.begin("create:1", "create", attributes)
    assert entry["state"] == "SUBMITTING"
    assert entry["receipt"] is None
    assert entry["created_at"] > 0
    assert json.loads((tmp_path / "state.json").read_text("utf-8"))["intents"]["create:1"] == entry
    attributes["title"] = "Changed"
    entry["attributes"]["title"] = "Also changed"
    assert store.lookup("create:1")["attributes"] == {"title": "Dự án"}
    store.complete("create:1", {"project_id": PROJECT, "title": "Dự án"})
    reopened = BrowserStateStore(tmp_path / "state.json", "profile-owner")
    reused = reopened.begin("create:1", "create", {"title": "New"})
    assert reused["state"] == "COMPLETED"
    assert reused["receipt"] == {"project_id": PROJECT, "title": "Dự án"}
    assert reopened.lookup("missing") is None


@pytest.mark.parametrize("unknown", [False, True])
def test_pending_or_unknown_cannot_begin_again(store, unknown):
    store.begin("upload:1", "upload", {"project_id": PROJECT, "image_sha256": "a" * 64})
    if unknown:
        store.mark_unknown("upload:1")
    before = store.load()
    with pytest.raises(BrowserStateError, match="^RECONCILIATION_REQUIRED$"):
        store.begin("upload:1", "upload", {})
    assert store.load() == before


@pytest.mark.parametrize("method", ["complete", "mark_unknown"])
@pytest.mark.parametrize("existing", ["missing", "UNKNOWN", "COMPLETED"])
def test_transitions_only_accept_submitting(store, method, existing):
    if existing != "missing":
        store.begin("key", "create", {})
        if existing == "UNKNOWN":
            store.mark_unknown("key")
        else:
            store.complete("key", {"project_id": PROJECT})
    before = store.load()
    with pytest.raises(BrowserStateError, match="^INVALID_TRANSITION$"):
        getattr(store, method)("key", *([{ "project_id": PROJECT}] if method == "complete" else []))
    assert store.load() == before


def test_projects_operations_and_completed_upload_survive_restart(store, tmp_path):
    store.set_project(PROJECT)
    store.remember_operation(OPERATION, PROJECT)
    store.begin("upload:1", "upload", {
        "project_id": PROJECT, "image_sha256": "a" * 64,
        "file_name": "image.png", "mime_type": "image/png",
    })
    store.complete("upload:1", {"media_id": MEDIA, "operation_id": OPERATION})
    loaded = BrowserStateStore(tmp_path / "state.json", "profile-owner").load()
    assert loaded["project_id"] == PROJECT
    assert loaded["operation_projects"] == {OPERATION: PROJECT}
    assert loaded["intents"]["upload:1"]["receipt"]["media_id"] == MEDIA


@pytest.mark.parametrize("attributes", [
    {"token": "SECRET"}, {"cookies": []}, {"url": "https://example.com"},
    {"title": {}}, {"title": "a" * 161}, {"file_name": "a" * 161},
    {"project_id": "CAMSSECRET"}, {"project_id": PROJECT.replace("-", "")},
    {"image_sha256": "A" * 64}, {"image_sha256": "a" * 63},
    {"mime_type": "text/plain"}, [],
])
def test_unsafe_attributes_are_rejected_before_persistence(store, tmp_path, attributes):
    with pytest.raises(BrowserStateError, match="^INVALID_INPUT$"):
        store.begin("key", "upload", attributes)
    assert not (tmp_path / "state.json").exists()


@pytest.mark.parametrize("receipt", [
    {"raw": {"token": "SECRET"}}, {"url": "https://example.com"},
    {"media_id": "CAMSSECRET"}, {"operation_id": True}, {"title": "x" * 161},
    {"project_id": [PROJECT]}, {"cookies": "SECRET"}, [],
])
def test_unsafe_receipts_leave_submitting_durable(store, receipt):
    store.begin("key", "upload", {})
    with pytest.raises(BrowserStateError, match="^INVALID_INPUT$"):
        store.complete("key", receipt)
    assert store.lookup("key")["state"] == "SUBMITTING"


@pytest.mark.parametrize("method,args", [
    ("set_project", ["bad"]), ("remember_operation", ["bad", PROJECT]),
    ("remember_operation", [OPERATION, "bad"]), ("begin", ["key", "paid", {}]),
    ("begin", ["", "create", {}]),
])
def test_invalid_arguments_fail_closed(store, method, args):
    with pytest.raises(BrowserStateError, match="^INVALID_INPUT$"):
        getattr(store, method)(*args)


@pytest.mark.parametrize("payload", [b"broken SECRET", b"\xff", b"[]", b"{}"])
def test_corrupt_state_is_not_treated_as_fresh(store, tmp_path, payload):
    (tmp_path / "state.json").write_bytes(payload)
    with pytest.raises(BrowserStateError, match="^INVALID_STATE$"):
        store.load()
    assert (tmp_path / "state.json").read_bytes() == payload


def test_wrong_owner_is_refused(store, tmp_path):
    store.set_project(PROJECT)
    with pytest.raises(BrowserStateError, match="^OWNER_MISMATCH$"):
        BrowserStateStore(tmp_path / "state.json", "other").load()


@pytest.mark.parametrize("corruption", ["extra", "receipt", "timestamp", "state", "schema", "mapping"])
def test_entire_schema_is_validated_on_load(store, tmp_path, corruption):
    store.begin("key", "create", {})
    state = store.load()
    if corruption == "extra":
        state["token"] = "SECRET"
    elif corruption == "receipt":
        state["intents"]["key"]["receipt"] = {"token": "SECRET"}
    elif corruption == "timestamp":
        state["intents"]["key"]["created_at"] = float("nan")
    elif corruption == "state":
        state["intents"]["key"]["state"] = "RETRY"
    elif corruption == "schema":
        state["schema_version"] = True
    else:
        state["operation_projects"] = {"bad": PROJECT}
    (tmp_path / "state.json").write_text(json.dumps(state), "utf-8")
    with pytest.raises(BrowserStateError, match="^INVALID_STATE$"):
        store.load()


def test_unreadable_state_has_fixed_error(store, tmp_path):
    (tmp_path / "state.json").mkdir()
    with pytest.raises(BrowserStateError, match="^STATE_READ_FAILED$"):
        store.load()


def test_failed_begin_prevents_caller_source_effect_and_cleans_only_own_temp(store, tmp_path, monkeypatch):
    foreign_temp = tmp_path / ".state.json.other.tmp"
    foreign_temp.write_text("other writer")
    effects = []

    def fail_replace(*args):
        raise OSError("SECRET path")

    monkeypatch.setattr(state_module.os, "replace", fail_replace)
    with pytest.raises(BrowserStateError, match="^STATE_WRITE_FAILED$") as caught:
        store.begin("key", "create", {})
        effects.append("source submission")
    assert caught.value.code == "STATE_WRITE_FAILED"
    assert effects == []
    assert list(tmp_path.iterdir()) == [foreign_temp]


@pytest.mark.parametrize("failing_stage", ["fsync", "replace"])
def test_failed_complete_preserves_previous_submitting_state(store, tmp_path, monkeypatch, failing_stage):
    store.begin("key", "create", {})
    before = (tmp_path / "state.json").read_bytes()

    def fail(*args):
        raise OSError("SECRET path")

    monkeypatch.setattr(state_module.os, failing_stage, fail)
    with pytest.raises(BrowserStateError, match="^STATE_WRITE_FAILED$"):
        store.complete("key", {"project_id": PROJECT})
    assert (tmp_path / "state.json").read_bytes() == before
    assert store.lookup("key")["state"] == "SUBMITTING"
    assert list(tmp_path.iterdir()) == [tmp_path / "state.json"]


@pytest.mark.parametrize("field", ["intents", "operation_projects"])
def test_record_budget_rejects_growth_without_pruning(store, tmp_path, field):
    state = store.load()
    if field == "intents":
        entry = {"state": "UNKNOWN", "kind": "create", "attributes": {}, "receipt": None, "created_at": 1}
        state[field] = {f"key:{i}": entry for i in range(4096)}
    else:
        state[field] = {str(UUID(int=i)): PROJECT for i in range(4096)}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state), "utf-8")
    before = path.read_bytes()
    with pytest.raises(BrowserStateError, match="^STATE_LIMIT_EXCEEDED$"):
        if field == "intents":
            store.begin("new", "create", {})
        else:
            store.remember_operation(OPERATION, PROJECT)
    assert path.read_bytes() == before
    state[field]["overflow"] = next(iter(state[field].values()))
    path.write_text(json.dumps(state), "utf-8")
    with pytest.raises(BrowserStateError, match="^STATE_LIMIT_EXCEEDED$"):
        store.load()


def test_oversize_state_fails_closed(store, tmp_path):
    (tmp_path / "state.json").write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(BrowserStateError, match="^STATE_LIMIT_EXCEEDED$"):
        store.load()


def test_duplicate_json_fields_are_refused_as_ambiguous(store, tmp_path):
    state = json.dumps(store.load())
    state = state.replace('"project_id": null', f'"project_id": null, "project_id": "{PROJECT}"')
    (tmp_path / "state.json").write_text(state, "utf-8")
    with pytest.raises(BrowserStateError, match="^INVALID_STATE$"):
        store.load()


def test_mark_unknown_preserves_existing_validated_receipt(store, tmp_path):
    store.begin("key", "upload", {})
    state = store.load()
    state["intents"]["key"]["receipt"] = {"media_id": MEDIA}
    (tmp_path / "state.json").write_text(json.dumps(state), "utf-8")
    store.mark_unknown("key")
    assert store.lookup("key")["receipt"] == {"media_id": MEDIA}


def test_write_byte_budget_preserves_previous_file(store, tmp_path):
    state = store.load()
    entry = {
        "state": "UNKNOWN", "kind": "upload", "created_at": 1, "receipt": None,
        "attributes": {"title": "😀" * 160, "file_name": "😀" * 160},
    }
    state["intents"] = {f"key:{i}": entry for i in range(2980)}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), "utf-8")
    # The compact state fits on disk, but adding ordinary JSON spacing exceeds 4 MiB.
    assert path.stat().st_size < 4 * 1024 * 1024
    before = path.read_bytes()
    with pytest.raises(BrowserStateError, match="^STATE_LIMIT_EXCEEDED$"):
        store.set_project(PROJECT)
    assert path.read_bytes() == before
