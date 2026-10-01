"""FBR-2-code-3a authored requirements; deliberately NOT executed during coding."""
import base64
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import validate_command
from agent.services.flow_browser_driver import FlowBrowserDriver
from agent.services.flow_browser_session import FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateError
from agent.services.flow_browser_upload import upload_reference

PROJECT = '11111111-2222-3333-4444-555555555555'
OTHER = '99999999-2222-3333-4444-555555555555'
MEDIA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
OPERATION = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'
PRIVATE = 'private-account@example.test token=do-not-persist'


def body(payload, rpcid=fb.RPC_UPLOAD_IMAGE):
    return json.dumps([['wrb.fr', rpcid, json.dumps(payload)]])


def response(project=PROJECT):
    return {'status': 200, 'body_complete': True,
            'data': body([[MEDIA, project, OPERATION]])}


class Page:
    def __init__(self):
        self.url = 'https://flow.google.com/'
        self.visits = []
        self.calls = []
        self.reply = response()

    def goto(self, url, **kwargs):
        self.visits.append(url)
        self.url = url

    def evaluate(self, script, args):
        assert script.startswith('mw:')
        envelope = json.loads(args['freq'])
        assert envelope[0][0][0] == fb.RPC_UPLOAD_IMAGE
        self.calls.append(args)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply(args) if callable(self.reply) else self.reply


class Provider:
    def __init__(self):
        self.lease = False
        self.session = SimpleNamespace(page=Page())

    def open(self):
        self.lease = True

    def health(self):
        return {'state': 'open' if self.lease else 'closed', 'lease_held': self.lease}

    def capture_health(self):
        return {**self.health(), 'authentication': 'authenticated',
                'ready': self.lease, 'semantic_node_count': 3,
                'observed_at': '2026-09-30T10:00:00+00:00', 'error': None}

    def close(self):
        self.lease = False


@pytest.fixture
def rig(tmp_path):
    profile = tmp_path / 'existing-profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    provider = Provider()
    state_path = tmp_path / 'journal' / 'state.json'
    driver = FlowBrowserDriver(config, state_path, 'unit-owner',
                               session_factory=lambda *a, **k: provider)
    driver.start()
    buffer = BytesIO()
    Image.new('RGB', (2, 2)).save(buffer, format='PNG')
    raw = buffer.getvalue()
    yield driver, provider, state_path, raw
    driver.close()


def command(raw, project=PROJECT, mime='image/png', name='reference.png'):
    return validate_command('batch_rpc', {
        'rpcid': fb.RPC_UPLOAD_IMAGE, 'projectId': project,
        'captchaAction': fb.CAPTCHA_IMAGE,
        'freq': fb.upload_request(base64.b64encode(raw).decode(), project,
                                  mime_type=mime, file_name=name),
    })


def key(raw, project=PROJECT):
    return f'upload:{project}:{hashlib.sha256(raw).hexdigest()}:reference.png'


def attributes(raw, project=PROJECT):
    return {'project_id': project, 'image_sha256': hashlib.sha256(raw).hexdigest(),
            'file_name': 'reference.png', 'mime_type': 'image/png'}


def test_upload_records_intent_before_effect_and_only_persists_verified_receipt(rig):
    driver, provider, path, raw = rig
    page = provider.session.page

    def reply(args):
        assert provider.lease
        entry = driver._store.lookup(key(raw))
        assert entry['state'] == 'SUBMITTING'
        assert entry['attributes'] == attributes(raw)
        assert args['projectId'] == PROJECT
        assert page.url == f'https://flow.google.com/project/{PROJECT}'
        return {**response(), 'private_extra': PRIVATE}

    page.reply = reply
    result = driver.execute(command(raw), 30)
    assert result['status'] == 200 and result['effect'] == 'completed'
    assert result['reused'] is False
    assert fb.read_uploaded_media_id(fb.first_payload(result['data'], fb.RPC_UPLOAD_IMAGE)) == MEDIA
    entry = driver._store.lookup(key(raw))
    assert entry['state'] == 'COMPLETED'
    assert entry['receipt'] == {'project_id': PROJECT, 'media_id': MEDIA,
                                'operation_id': OPERATION}
    assert PRIVATE not in json.dumps(result) and PRIVATE not in path.read_text()
    assert base64.b64encode(raw).decode() not in path.read_text()
    report = driver.health()
    assert report['capabilities']['upload'] is True
    assert report['capabilities']['operation_reconcile'] is True
    assert report['operations_implemented'] is True
    assert report['paid_dispatch_enabled'] is False


def test_restart_reuses_same_receipt_despite_fresh_request_uuids(rig):
    driver, provider, path, raw = rig
    first = driver.execute(command(raw), 30)
    assert first['status'] == 200
    before = path.read_bytes()
    driver.close()
    reopened_provider = Provider()
    reopened = FlowBrowserDriver(driver.config, path, 'unit-owner',
                                  session_factory=lambda *a, **k: reopened_provider)
    try:
        reopened.start()
        result = reopened.execute(command(raw), 30)
        assert result['status'] == 200 and result['reused'] is True
        assert result['data'] == first['data']
        assert reopened_provider.session.page.calls == []
        assert reopened_provider.session.page.visits == []
        assert path.read_bytes() == before
    finally:
        reopened.close()


@pytest.mark.parametrize('pending', ['SUBMITTING', 'UNKNOWN'])
def test_existing_uncertain_upload_is_not_replayed_or_rewritten(rig, pending):
    driver, provider, path, raw = rig
    driver._store.begin(key(raw), 'upload', attributes(raw))
    if pending == 'UNKNOWN':
        driver._store.mark_unknown(key(raw))
    before = path.read_bytes()
    result = driver.execute(command(raw), 30)
    assert result == {'status': 409, 'error': 'UPLOAD_RECONCILIATION_REQUIRED',
                      'effect': 'unknown'}
    assert provider.session.page.calls == [] and provider.session.page.visits == []
    assert path.read_bytes() == before


@pytest.mark.parametrize('bad', [
    {'status': 200, 'body_complete': False, 'data': body([[MEDIA, PROJECT]])},
    {'status': 200, 'body_complete': True, 'data': body([[MEDIA, OTHER]])},
    {'status': 200, 'body_complete': True, 'data': body([['not-a-uuid', PROJECT]])},
    {'status': 200, 'body_complete': True, 'data': body([[MEDIA, PROJECT]], fb.RPC_MEDIA)},
    {'status': 200, 'body_complete': True, 'data': 'not-json ' + PRIVATE},
    {'status': 503, 'body_complete': True, 'data': PRIVATE},
    RuntimeError(PRIVATE),
    None,
])
def test_unverified_outcome_stays_unknown_and_cannot_trigger_second_upload(rig, bad):
    driver, provider, path, raw = rig
    provider.session.page.reply = bad
    result = driver.execute(command(raw), 30)
    assert result == {'status': 409, 'error': 'UPLOAD_RECONCILIATION_REQUIRED',
                      'effect': 'unknown'}
    assert driver._store.lookup(key(raw))['state'] == 'UNKNOWN'
    before = path.read_bytes()
    assert driver.execute(command(raw), 30) == result
    assert len(provider.session.page.calls) == 1 and path.read_bytes() == before
    assert PRIVATE not in json.dumps(result) and PRIVATE not in path.read_text()


def test_complete_write_failure_never_reports_upload_success(rig, monkeypatch):
    driver, provider, _, raw = rig

    def fail(*args):
        raise BrowserStateError('STATE_WRITE_FAILED')

    monkeypatch.setattr(driver._store, 'complete', fail)
    result = driver.execute(command(raw), 30)
    assert result['effect'] == 'unknown'
    assert driver._store.lookup(key(raw))['state'] == 'UNKNOWN'
    assert len(provider.session.page.calls) == 1


def test_lost_lease_after_dispatch_preserves_submitting_journal(rig):
    driver, provider, path, raw = rig
    snapshot = []

    def reply(args):
        snapshot.append(path.read_bytes())
        provider.lease = False
        return response()

    provider.session.page.reply = reply
    result = driver.execute(command(raw), 30)
    assert result['effect'] == 'unknown'
    assert path.read_bytes() == snapshot[0]
    provider.lease = True  # Restore only the fake lease for fixture cleanup.
    assert driver._store.lookup(key(raw))['state'] == 'SUBMITTING'


@pytest.mark.parametrize('invalid_raw,mime,expected', [
    (None, 'image/jpeg', 'IMAGE_MIME_MISMATCH'),
    (b'not an image', 'image/png', 'IMAGE_CONTENT_INVALID'),
])
def test_invalid_image_fails_before_navigation_journal_or_upload(rig, invalid_raw, mime, expected):
    driver, provider, path, raw = rig
    result = driver.execute(command(raw if invalid_raw is None else invalid_raw, mime=mime), 30)
    assert result == {'status': 409, 'error': expected, 'effect': 'not_submitted'}
    assert not path.exists()
    assert provider.session.page.calls == [] and provider.session.page.visits == []


def test_cached_receipt_with_wrong_binding_is_not_trusted_or_overwritten(rig):
    driver, provider, path, raw = rig
    driver._store.begin(key(raw), 'upload', attributes(raw))
    driver._store.complete(key(raw), {'project_id': OTHER, 'media_id': MEDIA})
    before = path.read_bytes()
    result = driver.execute(command(raw), 30)
    assert result['status'] == 409
    assert result['error'] == 'UPLOAD_RECONCILIATION_REQUIRED'
    assert provider.session.page.calls == [] and path.read_bytes() == before


def test_same_bytes_in_different_project_have_distinct_intents(rig):
    driver, provider, _, raw = rig
    assert driver.execute(command(raw), 30)['status'] == 200
    provider.session.page.reply = response(OTHER)
    assert driver.execute(command(raw, OTHER), 30)['status'] == 200
    assert len(provider.session.page.calls) == 2
    assert driver._store.lookup(key(raw, OTHER))['receipt']['project_id'] == OTHER


def test_path_based_reference_helper_and_driver_share_existing_receipt(rig, tmp_path):
    driver, provider, _, raw = rig
    assert driver.execute(command(raw), 30)['status'] == 200
    source = tmp_path / 'reference.png'
    source.write_bytes(raw)
    assert upload_reference(provider.session, source, PROJECT, driver._store) == MEDIA
    assert len(provider.session.page.calls) == 1
