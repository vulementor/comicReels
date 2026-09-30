"""FBR-2-code-1 authored coverage; no live browser or production profile.

The development pass does not execute these tests. The later validation pass
must exercise them and the complete required regression suite independently.
"""
import asyncio
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.services.flow_browser_contract import BrowserCommandError
from agent.services.flow_browser_session import FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = '11111111-2222-3333-4444-555555555555'
PRIVATE = 'private-account@example.test private browser detail'


class Provider:
    def __init__(self):
        self.calls = []
        self.lease = False
        self.authentication = 'authenticated'
        self.error = None
        self.open_error = None
        self.close_failures = 0

    def record(self, name):
        self.calls.append((name, threading.get_ident()))

    def open(self):
        self.record('open')
        self.lease = True
        if self.open_error:
            raise self.open_error
        return self

    def health(self):
        self.record('passive')
        return {'state': 'open' if self.lease else 'closed',
                'lease_held': self.lease, 'ready': False}

    def capture_health(self):
        self.record('capture')
        return {
            'state': 'open' if self.lease else 'closed',
            'lease_held': self.lease,
            'authentication': self.authentication,
            'ready': self.lease and self.authentication == 'authenticated' and not self.error,
            'semantic_node_count': 4,
            'observed_at': '2026-09-30T06:30:00+00:00',
            'error': self.error,
            'identity': PRIVATE, 'untrusted_detail': PRIVATE,
        }

    def close(self):
        self.record('close')
        if self.close_failures:
            self.close_failures -= 1
            raise RuntimeError(PRIVATE)
        self.lease = False


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from agent.services import flow_browser_driver as implementation
    profile = tmp_path / 'existing-profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    digest = hashlib.sha256(str(profile.resolve()).casefold().encode()).hexdigest()
    key = f'browser:{config.profile_logical_name}:{digest}'
    path = tmp_path / 'state' / 'flow.json'
    provider = Provider()
    constructed = []

    def factory(bound_config, **kwargs):
        constructed.append((bound_config, kwargs, threading.get_ident()))
        return provider

    # Replace only the browser/session seam, NOT FlowBrowserDriver itself.
    monkeypatch.setattr(implementation, 'FlowBrowserSessionProvider', factory)
    driver = implementation.FlowBrowserDriver(config, path, key)
    return driver, provider, config, path, key, constructed


def test_constructor_and_unstarted_health_have_no_session_or_state_effect(rig):
    driver, provider, _, path, _, constructed = rig
    assert not constructed and not provider.calls and not path.exists()
    report = driver.health()
    assert report['state'] == 'new'
    assert report['ready'] is False and report['session_ready'] is False
    assert not constructed and not provider.calls and not path.exists()


def test_default_provider_uses_existing_profile_and_canonical_readonly_auth_probe(rig, monkeypatch):
    from agent.services.flow_browser_auth import observe_flow_account
    driver, provider, config, path, _, constructed = rig
    load = driver._store.load

    def guarded_load():
        assert provider.lease, 'state must be read under the owned profile lease'
        return load()

    monkeypatch.setattr(driver._store, 'load', guarded_load)
    driver.start()
    driver.start()  # Idempotent; no second context/lease acquisition.
    assert len(constructed) == 1
    assert constructed[0][0] is config
    assert constructed[0][1]['auth_probe'] is observe_flow_account
    report = driver.health()
    assert report['session_ready'] is True
    assert report['ready'] is True  # Code-2 exposes only the bounded project/read transport.
    assert report['operations_implemented'] is False
    assert report['paid_dispatch_enabled'] is False
    assert report['error'] is None
    assert not path.exists(), 'an empty read must not manufacture a journal'
    driver.close()
    driver.close()
    assert [name for name, _ in provider.calls].count('close') == 1
    assert driver.health()['state'] == 'closed'
    with pytest.raises(BrowserCommandError, match='^DRIVER_CLOSED$'):
        driver.start()


def test_start_retains_submitting_and_unknown_receipts_without_replay(rig):
    driver, provider, _, path, key, _ = rig
    store = BrowserStateStore(path, key)
    store.set_project(PROJECT)
    store.begin('create:pending', 'create', {'title': 'saved story'})
    store.begin('upload:unknown', 'upload', {'project_id': PROJECT, 'image_sha256': 'a' * 64})
    store.mark_unknown('upload:unknown')
    before = path.read_bytes()
    driver.start()
    report = driver.health()
    assert report['has_saved_project'] is True
    assert report['pending_intents'] == 2
    assert report['reconciliation_required'] is True
    assert report['error'] == 'RECONCILIATION_REQUIRED'
    assert report['ready'] is False
    driver.close()
    assert path.read_bytes() == before
    assert all(name in {'open', 'passive', 'capture', 'close'} for name, _ in provider.calls)


@pytest.mark.parametrize('state_case,expected', [
    ('corrupt', 'INVALID_STATE'), ('wrong-owner', 'OWNER_MISMATCH'),
])
def test_bad_state_closes_only_owned_provider_and_keeps_original_bytes(rig, state_case, expected):
    driver, provider, _, path, _, _ = rig
    path.parent.mkdir()
    if state_case == 'corrupt':
        path.write_text('not json: ' + PRIVATE, encoding='utf-8')
    else:
        BrowserStateStore(path, 'another-owner').set_project(PROJECT)
    before = path.read_bytes()
    with pytest.raises(BrowserCommandError, match='^' + expected + '$'):
        driver.start()
    assert provider.lease is False
    assert path.read_bytes() == before
    assert driver.health()['ready'] is False
    driver.close()


def test_missing_profile_fails_before_constructing_replacement_context(rig):
    driver, provider, config, path, _, constructed = rig
    config.user_data_dir.rmdir()
    with pytest.raises(BrowserCommandError, match='^PROFILE_CHANGED$'):
        driver.start()
    assert not constructed and not provider.calls
    assert not config.user_data_dir.exists() and not path.exists()


def test_health_uses_fresh_auth_and_projects_no_identity_or_physical_paths(rig):
    driver, provider, config, path, _, _ = rig
    driver.start()
    assert driver.health()['session_ready'] is True
    for state in ('unknown', 'signed_out'):
        provider.authentication = state
        report = driver.health()
        assert report['authentication'] == state
        assert report['session_ready'] is False and report['ready'] is False
    provider.authentication = 'authenticated'
    provider.error = 'IDENTITY_CHANGED'
    report = driver.health()
    assert report['error'] == 'IDENTITY_CHANGED' and not report['session_ready']
    encoded = json.dumps(report)
    assert PRIVATE not in encoded
    assert str(config.user_data_dir) not in encoded and str(path) not in encoded
    assert [name for name, _ in provider.calls].count('capture') == 4
    driver.close()


def test_lost_lease_blocks_observation_and_state_access(rig, monkeypatch):
    driver, provider, _, _, _, _ = rig
    driver.start()
    provider.lease = False

    def forbidden():
        raise AssertionError('must not read state without the lease')

    monkeypatch.setattr(driver._store, 'load', forbidden)
    before = len([name for name, _ in provider.calls if name == 'capture'])
    report = driver.health()
    assert report['error'] == 'PROFILE_LEASE_REQUIRED'
    assert report['ready'] is False and report['session_ready'] is False
    assert len([name for name, _ in provider.calls if name == 'capture']) == before
    driver.close()


def test_state_corruption_after_start_is_not_repaired_or_hidden(rig):
    driver, provider, _, path, _, _ = rig
    driver.start()
    path.parent.mkdir()
    path.write_text(PRIVATE, encoding='utf-8')
    before = path.read_bytes()
    report = driver.health()
    assert report['error'] == 'INVALID_STATE' and not report['ready']
    assert path.read_bytes() == before and provider.lease
    driver.close()


def test_start_failure_is_sanitized_and_releases_owned_session(rig):
    driver, provider, _, path, _, _ = rig
    provider.open_error = RuntimeError(PRIVATE)
    with pytest.raises(BrowserCommandError, match='^DRIVER_START_FAILED$'):
        driver.start()
    assert not provider.lease and not path.exists()
    assert PRIVATE not in json.dumps(driver.health())
    driver.close()


@pytest.mark.parametrize('during_start', [False, True])
def test_uncertain_close_retains_provider_until_explicit_close_retry(rig, during_start):
    driver, provider, _, _, _, constructed = rig
    provider.close_failures = 1
    if during_start:
        provider.open_error = RuntimeError(PRIVATE)
        with pytest.raises(BrowserCommandError, match='^CLOSE_UNCERTAIN$'):
            driver.start()
    else:
        driver.start()
        with pytest.raises(BrowserCommandError, match='^CLOSE_UNCERTAIN$'):
            driver.close()
    assert provider.lease
    assert driver.health()['state'] == 'close_uncertain'
    with pytest.raises(BrowserCommandError, match='^CLOSE_UNCERTAIN$'):
        driver.start()
    driver.close()
    assert not provider.lease and driver.health()['state'] == 'closed'
    assert len(constructed) == 1
    assert [name for name, _ in provider.calls].count('close') == 2


def test_unsupported_execute_stays_fail_closed_without_receipts_or_effects(rig):
    driver, provider, _, path, _, _ = rig
    driver.start()
    assert driver.execute(object(), 30) == {
        'status': 501, 'error': 'BROWSER_CAPABILITY_NOT_IMPLEMENTED',
        'effect': 'not_submitted',
    }
    assert not path.exists()
    driver.close()
    assert all(name in {'open', 'passive', 'capture', 'close'} for name, _ in provider.calls)


def test_other_thread_cannot_capture_close_or_mutate_owned_driver(rig):
    driver, provider, _, _, _, _ = rig
    driver.start()
    before = list(provider.calls)
    operations = (driver.start, driver.health, driver.close,
                  lambda: driver.execute(object(), 30),
                  lambda: driver.open_project(PROJECT),
                  lambda: driver.ensure_session_project('story', False))
    with ThreadPoolExecutor(max_workers=1) as pool:
        for operation in operations:
            with pytest.raises(BrowserCommandError, match='^WRONG_OWNER_THREAD$'):
                pool.submit(operation).result()
    assert provider.calls == before and provider.lease
    driver.close()


@pytest.mark.asyncio
async def test_backend_default_import_instantiates_real_driver_on_one_owner_thread(rig):
    from agent.services.flow_browser_backend import BrowserFlowBackend
    from agent.services.flow_browser_driver import FlowBrowserDriver
    _, provider, config, path, _, constructed = rig
    backend = BrowserFlowBackend(config=config, state_path=path)
    try:
        await backend.start()  # Deliberately no driver_factory injection.
        assert isinstance(backend._driver, FlowBrowserDriver)
        assert backend.ready is True and backend.paid_dispatch_enabled is False
        report = await backend.check_readiness()
        assert report['ready'] is True
        assert report['operations_implemented'] is False
    finally:
        await backend.close()
    threads = {owner for _, owner in provider.calls}
    assert len(threads) == 1 and threading.get_ident() not in threads
    assert constructed[0][2] in threads and not provider.lease
    assert not path.exists()
