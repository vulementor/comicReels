"""FBR-3 authored paid one-shot boundary requirements; not executed during coding."""
import hashlib
import json

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_paid import FlowPaidImageGate
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = '11111111-2222-3333-4444-555555555555'
MEDIA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
PRIVATE = 'secret prompt / browser token'
AUTH = object()


def one_shot(prompt='one safe test image'):
    return {
        'rpcid': fb.RPC_GEN_IMAGE,
        'freq': fb.image_request(prompt, PROJECT, count=1, aspect='1:1', seed=7),
        'projectId': PROJECT,
        'captchaAction': fb.CAPTCHA_IMAGE,
    }


def response(media=MEDIA, project=PROJECT):
    url = f'https://flow-content.google/image/{media}?signed=private'
    payload = [project, [url]]
    return {
        'status': 200, 'body_complete': True, 'effect': 'completed',
        'data': json.dumps([['wrb.fr', fb.RPC_GEN_IMAGE, json.dumps(payload)]]),
    }


@pytest.fixture
def rig(tmp_path):
    store = BrowserStateStore(tmp_path / 'paid.json', 'unit-owner')
    calls = []

    def dispatch(command, timeout):
        calls.append((command, timeout))
        return response()

    return store, calls, dispatch


def test_default_gate_blocks_before_journal_or_dispatch(rig):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch)
    result = gate.submit(one_shot(), idempotency_key='shot-1', authorization=AUTH)

    assert result == {
        'status': 403, 'error': 'PAID_DISPATCH_DISABLED',
        'effect': 'not_submitted',
    }
    assert calls == [] and not store.path.exists()


def test_enabled_gate_still_requires_exact_authorization_object(rig):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)
    for supplied in (None, object(), True, 'yes'):
        assert gate.submit(one_shot(), idempotency_key='shot-1',
                           authorization=supplied) == {
            'status': 403, 'error': 'PAID_AUTHORIZATION_REQUIRED',
            'effect': 'not_submitted',
        }
    assert calls == [] and not store.path.exists()


def test_one_shot_intent_is_durable_before_exactly_one_dispatch(rig):
    store, calls, dispatch = rig
    expected_digest = gate_digest = None

    def guarded(command, timeout):
        saved = store.load()
        entries = list(saved['intents'].values())
        assert len(entries) == 1
        entry = entries[0]
        assert entry['kind'] == 'paid_image'
        assert entry['state'] == 'SUBMITTING'
        assert entry['attributes']['project_id'] == PROJECT
        assert entry['attributes']['request_sha256'] == command.request_sha256
        assert PRIVATE not in json.dumps(saved)
        return dispatch(command, timeout)

    gate = FlowPaidImageGate(store, guarded, dispatch_enabled=True,
                             authorization=AUTH)
    result = gate.submit(one_shot(), idempotency_key='shot-1',
                         authorization=AUTH, timeout=45)

    assert result == {
        'status': 200,
        'data': {'projectId': PROJECT, 'mediaId': MEDIA},
        'effect': 'completed',
        'reused': False,
    }
    assert len(calls) == 1 and calls[0][1] == 45
    entry = next(iter(store.load()['intents'].values()))
    assert entry['state'] == 'COMPLETED'
    assert entry['receipt'] == {'project_id': PROJECT, 'media_id': MEDIA}


def test_same_idempotency_key_reuses_receipt_without_resend(rig):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)
    first = gate.submit(one_shot(), idempotency_key='shot-1', authorization=AUTH)
    second = gate.submit(one_shot(), idempotency_key='shot-1', authorization=AUTH)

    assert first['reused'] is False
    assert second == {**first, 'reused': True}
    assert len(calls) == 1


def test_same_idempotency_key_with_different_request_is_rejected(rig):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)
    assert gate.submit(one_shot('first'), idempotency_key='shot-1',
                       authorization=AUTH)['status'] == 200

    result = gate.submit(one_shot('changed'), idempotency_key='shot-1',
                         authorization=AUTH)
    assert result == {
        'status': 409, 'error': 'PAID_IDEMPOTENCY_CONFLICT',
        'effect': 'not_submitted',
    }
    assert len(calls) == 1


@pytest.mark.parametrize('pending', ['SUBMITTING', 'UNKNOWN'])
def test_pending_or_unknown_paid_intent_never_resends(rig, pending):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)
    command = gate.validate(one_shot())
    key, attributes = gate.intent(command, 'shot-1')
    store.begin(key, 'paid_image', attributes)
    if pending == 'UNKNOWN':
        store.mark_unknown(key)

    before = store.path.read_bytes()
    result = gate.submit(one_shot(), idempotency_key='shot-1',
                         authorization=AUTH)

    assert result == {
        'status': 409, 'error': 'PAID_RECONCILIATION_REQUIRED',
        'effect': 'unknown',
    }
    assert calls == [] and store.path.read_bytes() == before


@pytest.mark.parametrize('bad', [
    {'status': 502, 'error': 'BODY_INCOMPLETE', 'effect': 'unknown'},
    {'status': 200, 'body_complete': False, 'data': ''},
    {'status': 200, 'body_complete': True, 'effect': 'completed', 'data': 'bad'},
    RuntimeError(PRIVATE),
])
def test_ambiguous_outcome_becomes_unknown_and_never_auto_retries(rig, bad):
    store, calls, _ = rig

    def dispatch(command, timeout):
        calls.append((command, timeout))
        if isinstance(bad, Exception):
            raise bad
        return bad

    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)
    result = gate.submit(one_shot(), idempotency_key='shot-1',
                         authorization=AUTH)

    assert result == {
        'status': 409, 'error': 'PAID_RECONCILIATION_REQUIRED',
        'effect': 'unknown',
    }
    entry = next(iter(store.load()['intents'].values()))
    assert entry['state'] == 'UNKNOWN'
    before = store.path.read_bytes()
    assert gate.submit(one_shot(), idempotency_key='shot-1',
                       authorization=AUTH) == result
    assert len(calls) == 1 and store.path.read_bytes() == before
    assert PRIVATE not in store.path.read_text()


def test_multi_variant_or_non_image_generation_is_rejected_before_state(rig):
    store, calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True,
                             authorization=AUTH)

    multi = one_shot()
    multi['freq'] = fb.image_request('x', PROJECT, count=2, aspect='1:1', seed=7)
    assert gate.submit(multi, idempotency_key='shot-1', authorization=AUTH) == {
        'status': 409, 'error': 'PAID_RECIPE_UNVERIFIED',
        'effect': 'not_submitted',
    }

    other = dict(one_shot(), rpcid=fb.RPC_GEN_VIDEO,
                 freq=fb.video_request('x', PROJECT, MEDIA))
    assert gate.submit(other, idempotency_key='shot-2', authorization=AUTH) == {
        'status': 409, 'error': 'PAID_RECIPE_UNVERIFIED',
        'effect': 'not_submitted',
    }
    assert calls == [] and not store.path.exists()


def test_image_request_digest_ignores_only_ephemeral_client_uuids(rig):
    store, _calls, dispatch = rig
    gate = FlowPaidImageGate(store, dispatch, dispatch_enabled=True, authorization=AUTH)

    first_params = one_shot("same semantic request")
    second_params = one_shot("same semantic request")
    assert first_params["freq"] != second_params["freq"]

    first = gate.validate(first_params)
    second = gate.validate(second_params)
    changed = gate.validate(one_shot("different prompt"))

    assert first.request_sha256 == second.request_sha256
    assert first.request_sha256 != changed.request_sha256
