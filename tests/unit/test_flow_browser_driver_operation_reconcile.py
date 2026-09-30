"""FBR-2-code-3b authored requirements; deliberately NOT executed during coding."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import BrowserCommandError, validate_command
from agent.services.flow_browser_driver import FlowBrowserDriver
from agent.services.flow_browser_session import FlowProfileConfig

PROJECT = '11111111-2222-3333-4444-555555555555'
OTHER = '99999999-2222-3333-4444-555555555555'
MEDIA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
OPERATION = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'


class Page:
    def __init__(self):
        self.url = 'https://flow.google.com/'
        self.visits = []
        self.calls = []

    def goto(self, url, **_kwargs):
        self.visits.append(url)
        self.url = url

    def evaluate(self, _script, args):
        self.calls.append(args)
        payload = [None, 50, [[OPERATION, PROJECT, None, 'DONE']]]
        return {'status': 200, 'body_complete': True, 'effect': 'completed',
                'data': json.dumps([['wrb.fr', fb.RPC_OPERATION, json.dumps(payload)]])}


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
                'observed_at': '2026-09-30T14:00:00+00:00', 'error': None}

    def close(self):
        self.lease = False


@pytest.fixture
def rig(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    provider = Provider()
    state_path = tmp_path / 'journal' / 'state.json'
    driver = FlowBrowserDriver(config, state_path, 'unit-owner',
                               session_factory=lambda *a, **k: provider)
    driver.start()
    yield driver, provider, state_path
    driver.close()


def operation_command(operation=OPERATION):
    return validate_command('batch_rpc', {
        'rpcid': fb.RPC_OPERATION,
        'freq': fb.operation_request(operation),
    })


def add_completed_upload(driver, project=PROJECT, operation=OPERATION, suffix='a'):
    digest = hashlib.sha256(suffix.encode()).hexdigest()
    key = f'upload:{project}:{digest}:reference-{suffix}.png'
    driver._store.begin(key, 'upload', {
        'project_id': project, 'image_sha256': digest,
        'file_name': f'reference-{suffix}.png', 'mime_type': 'image/png',
    })
    driver._store.complete(key, {
        'project_id': project, 'media_id': MEDIA, 'operation_id': operation,
    })


def test_contract_exposes_operation_uuid_for_reconciliation():
    command = operation_command()
    assert command.capability == 'read'
    assert command.operation_id == OPERATION
    assert command.project_id is None


def test_operation_read_uses_existing_journal_binding_not_current_tab(rig):
    driver, provider, _ = rig
    driver._store.remember_operation(OPERATION, PROJECT)
    provider.session.page.url = f'https://flow.google.com/project/{OTHER}'

    result = driver.execute(operation_command(), 30)

    assert result['status'] == 200 and result['effect'] == 'completed'
    assert provider.session.page.visits == [f'https://flow.google.com/project/{PROJECT}']
    assert provider.session.page.calls[0]['projectId'] == PROJECT


def test_completed_upload_receipt_can_promote_verified_operation_binding(rig):
    driver, provider, _ = rig
    add_completed_upload(driver)

    result = driver.execute(operation_command(), 30)

    assert result['status'] == 200
    saved = driver._store.load()
    assert saved['operation_projects'][OPERATION] == PROJECT
    assert provider.session.page.visits == [f'https://flow.google.com/project/{PROJECT}']


def test_restart_uses_promoted_operation_binding_without_requiring_upload_receipt_scan(rig):
    driver, provider, state_path = rig
    add_completed_upload(driver)
    assert driver.execute(operation_command(), 30)['status'] == 200
    driver.close()

    reopened_provider = Provider()
    reopened = FlowBrowserDriver(driver.config, state_path, 'unit-owner',
                                  session_factory=lambda *a, **k: reopened_provider)
    try:
        reopened.start()
        result = reopened.execute(operation_command(), 30)
        assert result['status'] == 200
        assert reopened_provider.session.page.visits == [
            f'https://flow.google.com/project/{PROJECT}'
        ]
    finally:
        reopened.close()


def test_unbound_operation_fails_without_navigation_or_rpc(rig):
    driver, provider, state_path = rig

    result = driver.execute(operation_command(), 30)

    assert result == {'status': 409, 'error': 'OPERATION_BINDING_REQUIRED',
                      'effect': 'not_submitted'}
    assert provider.session.page.visits == [] and provider.session.page.calls == []
    assert not state_path.exists()


def test_conflicting_completed_receipts_fail_closed_without_mutating_state(rig):
    driver, provider, state_path = rig
    add_completed_upload(driver, PROJECT, OPERATION, 'a')
    add_completed_upload(driver, OTHER, OPERATION, 'b')
    before = state_path.read_bytes()

    result = driver.execute(operation_command(), 30)

    assert result == {'status': 409, 'error': 'OPERATION_BINDING_CONFLICT',
                      'effect': 'not_submitted'}
    assert provider.session.page.visits == [] and provider.session.page.calls == []
    assert state_path.read_bytes() == before


def test_explicit_binding_conflicting_with_receipt_fails_closed(rig):
    driver, provider, state_path = rig
    add_completed_upload(driver, OTHER, OPERATION, 'b')
    driver._store.remember_operation(OPERATION, PROJECT)
    before = state_path.read_bytes()

    result = driver.execute(operation_command(), 30)

    assert result == {'status': 409, 'error': 'OPERATION_BINDING_CONFLICT',
                      'effect': 'not_submitted'}
    assert provider.session.page.visits == [] and provider.session.page.calls == []
    assert state_path.read_bytes() == before


@pytest.mark.parametrize('state', ['SUBMITTING', 'UNKNOWN'])
def test_uncertain_upload_receipt_never_authorizes_operation_binding(rig, state):
    driver, provider, _ = rig
    digest = hashlib.sha256(b'pending').hexdigest()
    key = f'upload:{PROJECT}:{digest}:reference.png'
    driver._store.begin(key, 'upload', {
        'project_id': PROJECT, 'image_sha256': digest,
        'file_name': 'reference.png', 'mime_type': 'image/png',
    })
    if state == 'UNKNOWN':
        driver._store.mark_unknown(key)

    result = driver.execute(operation_command(), 30)

    assert result['error'] == 'OPERATION_BINDING_REQUIRED'
    assert provider.session.page.visits == [] and provider.session.page.calls == []


def test_operation_response_project_must_match_bound_project(rig):
    driver, provider, _ = rig
    driver._store.remember_operation(OPERATION, PROJECT)

    def conflicting(_script, args):
        provider.session.page.calls.append(args)
        payload = [None, 50, [[OPERATION, OTHER, None, 'DONE']]]
        return {'status': 200, 'body_complete': True, 'effect': 'completed',
                'data': json.dumps([['wrb.fr', fb.RPC_OPERATION, json.dumps(payload)]])}

    provider.session.page.evaluate = conflicting
    result = driver.execute(operation_command(), 30)

    assert result == {'status': 502, 'error': 'OPERATION_RECEIPT_UNVERIFIED',
                      'effect': 'unknown'}


def test_health_reports_operation_reconciliation_after_wiring(rig):
    driver, _, _ = rig
    report = driver.health()
    assert report['capabilities']['operation_reconcile'] is True
    assert report['capabilities']['upload'] is True
    assert report['readiness_scope'] == 'non_paid_parity'
    assert report['operations_implemented'] is True
    assert report['paid_dispatch_enabled'] is False
