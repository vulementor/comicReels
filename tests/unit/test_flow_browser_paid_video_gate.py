"""Task 9d repair-3 authored paid-video browser gate requirements.

Development-first policy: source coverage only. No test execution or live paid
request is permitted before source closure.
"""
import hashlib
import json

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_paid_video import FlowPaidVideoGate
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = "11111111-2222-3333-4444-555555555555"
OPERATION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
MEDIA = "99999999-8888-7777-6666-555555555555"
WORKFLOW = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
AUTH = object()


def operation_params():
    return {
        "rpcid": fb.RPC_GEN_VIDEO,
        "freq": fb.video_request("move", PROJECT, MEDIA),
        "projectId": PROJECT,
        "captchaAction": fb.CAPTCHA_VIDEO,
    }


def operation_body():
    payload = [None, 50, [[OPERATION, PROJECT, WORKFLOW, None]]]
    return json.dumps([["wrb.fr", fb.RPC_GEN_VIDEO, json.dumps(payload)]])


def media_params():
    return {
        "rpcid": fb.RPC_GEN_VIDEO_TEXT,
        "freq": fb.text_video_request("move", PROJECT, model="abra_t2v_4s"),
        "projectId": PROJECT,
        "captchaAction": fb.CAPTCHA_VIDEO,
    }


def media_body():
    payload = [None, 10, [], [[MEDIA, PROJECT, WORKFLOW, "CAE"]]]
    return json.dumps([["wrb.fr", fb.RPC_GEN_VIDEO_TEXT, json.dumps(payload)]])


def completed(body):
    return {
        "status": 200,
        "data": body,
        "body_complete": True,
        "effect": "completed",
    }


def test_paid_video_is_locked_before_state_or_dispatch(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    calls = []
    gate = FlowPaidVideoGate(
        state,
        lambda *_args: calls.append("dispatch"),
        dispatch_enabled=False,
        authorization=AUTH,
    )

    result = gate.submit(
        operation_params(),
        idempotency_key="video-1",
        authorization=AUTH,
    )

    assert result == {
        "status": 403,
        "error": "PAID_DISPATCH_DISABLED",
        "effect": "not_submitted",
    }
    assert calls == []
    assert not state.path.exists()


def test_operation_receipt_is_journaled_before_success_and_recoverable_as_binding(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    observed = []

    def dispatch(command, _timeout):
        snapshot = state.load()
        entry = next(v for v in snapshot["intents"].values() if v["kind"] == "paid_video")
        observed.append(entry["state"])
        return completed(operation_body())

    gate = FlowPaidVideoGate(
        state, dispatch, dispatch_enabled=True, authorization=AUTH,
    )
    result = gate.submit(
        operation_params(),
        idempotency_key="video-2",
        authorization=AUTH,
    )

    assert observed == ["SUBMITTING"]
    assert result == {
        "status": 200,
        "data": {
            "projectId": PROJECT,
            "receiptKind": "operation",
            "operationId": OPERATION,
        },
        "effect": "completed",
        "reused": False,
    }
    status, bound = state.operation_binding(OPERATION)
    assert (status, bound) == ("receipt", PROJECT)


def test_native_media_receipt_is_durable_and_reused_without_second_dispatch(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    calls = []

    def dispatch(_command, _timeout):
        calls.append(1)
        return completed(media_body())

    gate = FlowPaidVideoGate(
        state, dispatch, dispatch_enabled=True, authorization=AUTH,
    )
    first = gate.submit(media_params(), idempotency_key="video-3", authorization=AUTH)
    second = gate.submit(media_params(), idempotency_key="video-3", authorization=AUTH)

    assert first["data"] == {
        "projectId": PROJECT,
        "receiptKind": "media",
        "mediaId": MEDIA,
        "workflowId": WORKFLOW,
    }
    assert first["reused"] is False
    assert second["data"] == first["data"]
    assert second["reused"] is True
    assert calls == [1]


def test_unknown_paid_video_intent_is_never_dispatched_again(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    calls = []
    params = operation_params()
    digest = hashlib.sha256("video-unknown".encode()).hexdigest()
    gate = FlowPaidVideoGate(
        state,
        lambda *_args: calls.append(1),
        dispatch_enabled=True,
        authorization=AUTH,
    )
    request_digest = gate.validate(params).request_sha256
    key = f"paid-video:{digest}"
    state.begin(key, "paid_video", {
        "project_id": PROJECT,
        "request_sha256": request_digest,
        "idempotency_sha256": digest,
        "rpcid": fb.RPC_GEN_VIDEO,
    })
    state.mark_unknown(key)

    result = gate.submit(
        params,
        idempotency_key="video-unknown",
        authorization=AUTH,
    )

    assert result == {
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "unknown",
    }
    assert calls == []


@pytest.mark.parametrize("rpcid", [
    fb.RPC_GEN_VIDEO,
    fb.RPC_GEN_VIDEO_TEXT,
    fb.RPC_GEN_VIDEO_FIRST_LAST,
    fb.RPC_GEN_VIDEO_REFERENCES,
])
def test_only_existing_video_rpc_ids_are_in_paid_video_allowlist(rpcid):
    assert rpcid in FlowPaidVideoGate.ALLOWED_RPCIDS
    assert fb.RPC_GEN_IMAGE not in FlowPaidVideoGate.ALLOWED_RPCIDS


def test_paid_video_script_is_single_fetch_video_captcha_recipe():
    source = __import__("pathlib").Path(
        "agent/services/flow_browser_paid_video.js"
    ).read_text(encoding="utf-8")

    assert "VIDEO_GENERATION" in source
    assert "__CAPTCHA__" in source
    assert "fetch(" in source
    assert source.count("fetch(") == 1
    assert "for (;;)" in source  # response-body reader only
    assert "effect: 'unknown'" in source
    assert "effect: 'not_submitted'" in source
    assert "inner[1][5] !== projectId" in source
    assert "inner[2][1] !== 2" in source


@pytest.mark.parametrize("record", [
    [MEDIA, None, WORKFLOW, "CAE"],
    ["CAMS-not-a-uuid", PROJECT, WORKFLOW, "CAE"],
    [MEDIA, PROJECT, "not-a-workflow-uuid", "CAE"],
])
def test_malformed_native_video_receipt_becomes_unknown_and_is_never_replayed(
        tmp_path, record):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    calls = []

    def dispatch(_command, _timeout):
        calls.append(1)
        payload = [None, 10, [], [record]]
        body = json.dumps([["wrb.fr", fb.RPC_GEN_VIDEO_TEXT, json.dumps(payload)]])
        return completed(body)

    gate = FlowPaidVideoGate(
        state, dispatch, dispatch_enabled=True, authorization=AUTH,
    )
    first = gate.submit(
        media_params(), idempotency_key="video-malformed", authorization=AUTH,
    )
    second = gate.submit(
        media_params(), idempotency_key="video-malformed", authorization=AUTH,
    )

    assert first == {
        "status": 409,
        "error": "PAID_RECONCILIATION_REQUIRED",
        "effect": "unknown",
    }
    assert second == first
    assert calls == [1]


@pytest.mark.asyncio
async def test_browser_backend_paid_video_is_locked_by_default_without_driver_submission():
    from agent.services.flow_browser_backend import BrowserFlowBackend

    class Driver:
        def health(self):
            return {"ready": True}

        def submit_paid_video(self, *_args, **_kwargs):
            raise AssertionError("disabled backend must not reach video driver")

    backend = BrowserFlowBackend.__new__(BrowserFlowBackend)
    backend._ready = True
    backend._closing = False
    backend._closed = False
    backend._driver = Driver()
    backend._paid_dispatch_enabled = False
    backend._paid_authorization = None
    backend._paid_video_dispatch_enabled = False
    backend._paid_video_authorization = None

    result = await backend.submit_paid_video(
        operation_params(),
        idempotency_key="video-locked-1",
        authorization=AUTH,
    )

    assert result == {
        "status": 403,
        "error": "PAID_DISPATCH_DISABLED",
        "effect": "not_submitted",
    }


def test_paid_video_gate_rejects_project_only_present_outside_context(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    params = operation_params()
    outer = json.loads(params["freq"])
    body = json.loads(outer[0][0][1])
    body[1][5] = "22222222-3333-4444-5555-666666666666"
    body[0][0][0][2][0][0].append(PROJECT)  # project string elsewhere must not count
    outer[0][0][1] = json.dumps(body)
    params["freq"] = json.dumps(outer)

    gate = FlowPaidVideoGate(
        state, lambda *_args: completed(operation_body()),
        dispatch_enabled=True, authorization=AUTH,
    )
    result = gate.submit(
        params, idempotency_key="video-bad-context", authorization=AUTH,
    )

    assert result == {
        "status": 409,
        "error": "PAID_RECIPE_UNVERIFIED",
        "effect": "not_submitted",
    }


def test_paid_video_gate_reraises_non_exception_interrupt_after_marking_unknown(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")

    class Stop(BaseException):
        pass

    def interrupt(_command, _timeout):
        raise Stop()

    gate = FlowPaidVideoGate(
        state, interrupt, dispatch_enabled=True, authorization=AUTH,
    )

    with pytest.raises(Stop):
        gate.submit(
            operation_params(),
            idempotency_key="video-interrupt",
            authorization=AUTH,
        )

    entry = next(v for v in state.load()["intents"].values() if v["kind"] == "paid_video")
    assert entry["state"] == "UNKNOWN"


def test_video_request_digest_ignores_only_ephemeral_client_uuids(tmp_path):
    state = BrowserStateStore(tmp_path / "state.json", "owner")
    gate = FlowPaidVideoGate(
        state, lambda *_args: None, dispatch_enabled=True, authorization=AUTH,
    )

    first_params = operation_params()
    second_params = operation_params()
    assert first_params["freq"] != second_params["freq"]

    first = gate.validate(first_params)
    second = gate.validate(second_params)

    changed_params = dict(operation_params())
    changed_params["freq"] = fb.video_request("different prompt", PROJECT, MEDIA)
    changed = gate.validate(changed_params)

    assert first.request_sha256 == second.request_sha256
    assert first.request_sha256 != changed.request_sha256
