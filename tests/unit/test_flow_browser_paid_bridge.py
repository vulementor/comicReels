"""Task 4a authored requirements for the paid gate -> leased browser bridge.

Development-first policy: these tests are authored now but are NOT executed until
all browser-only source tasks are complete.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_browser_backend import BrowserFlowBackend
from agent.services.flow_browser_driver import FlowBrowserDriver
from agent.services.flow_browser_session import FlowProfileConfig

PROJECT = '11111111-2222-3333-4444-555555555555'
MEDIA = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
AUTH = object()


def paid_params(prompt='one paid validation image'):
    return {
        'rpcid': fb.RPC_GEN_IMAGE,
        'freq': fb.image_request(prompt, PROJECT, count=1, aspect='1:1', seed=7),
        'projectId': PROJECT,
        'captchaAction': fb.CAPTCHA_IMAGE,
    }


def paid_response():
    url = f'https://flow-content.google/image/{MEDIA}?signed=private'
    payload = [PROJECT, [url]]
    return {
        'status': 200,
        'body_complete': True,
        'effect': 'completed',
        'data': json.dumps([['wrb.fr', fb.RPC_GEN_IMAGE, json.dumps(payload)]]),
    }


class Page:
    def __init__(self):
        self.url = 'https://flow.google.com/'
        self.gotos = []
        self.evaluations = []

    def goto(self, url, *, wait_until, timeout):
        self.url = url
        self.gotos.append((url, wait_until, timeout))

    def evaluate(self, script, args):
        self.evaluations.append((script, args))
        return paid_response()


class Provider:
    def __init__(self):
        self.lease = False
        self.page = Page()
        self.session = SimpleNamespace(page=self.page)

    def open(self):
        self.lease = True
        return self

    def health(self):
        return {'state': 'open' if self.lease else 'closed',
                'lease_held': self.lease, 'ready': self.lease}

    def capture_health(self):
        return {
            'state': 'open' if self.lease else 'closed',
            'lease_held': self.lease,
            'authentication': 'authenticated',
            'ready': self.lease,
            'semantic_node_count': 3,
            'observed_at': '2026-10-01T12:00:00+00:00',
            'error': None,
        }

    def close(self):
        self.lease = False


@pytest.fixture
def driver_rig(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    provider = Provider()
    state = tmp_path / 'state.json'
    driver = FlowBrowserDriver(
        config, state, 'owner',
        session_factory=lambda _config, **_kwargs: provider,
    )
    driver.start()
    yield driver, provider, state
    driver.close()


def test_driver_paid_dispatch_is_locked_by_default_before_navigation_or_journal(driver_rig):
    driver, provider, state = driver_rig
    result = driver.submit_paid_image(
        paid_params(), idempotency_key='shot-1', authorization=AUTH,
    )
    assert result == {
        'status': 403, 'error': 'PAID_DISPATCH_DISABLED',
        'effect': 'not_submitted',
    }
    assert provider.page.gotos == []
    assert provider.page.evaluations == []
    assert not state.exists()


def test_authorized_driver_uses_same_leased_project_page_and_persists_before_evaluate(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    provider = Provider()
    state_path = tmp_path / 'paid.json'
    driver = FlowBrowserDriver(
        config, state_path, 'owner',
        session_factory=lambda _config, **_kwargs: provider,
        paid_dispatch_enabled=True,
        paid_authorization=AUTH,
    )
    driver.start()
    try:
        original = provider.page.evaluate

        def evaluate(script, args):
            saved = driver._store.load()
            paid = [e for e in saved['intents'].values() if e['kind'] == 'paid_image']
            assert len(paid) == 1 and paid[0]['state'] == 'SUBMITTING'
            assert provider.lease is True
            assert provider.page.url == f'https://flow.google.com/project/{PROJECT}'
            assert args == {
                'projectId': PROJECT,
                'freq': paid_params()['freq'],
                'timeoutMs': 45000,
            }
            return original(script, args)

        provider.page.evaluate = evaluate
        result = driver.submit_paid_image(
            paid_params(), idempotency_key='shot-1',
            authorization=AUTH, timeout=45,
        )
        assert result == {
            'status': 200,
            'data': {'projectId': PROJECT, 'mediaId': MEDIA},
            'effect': 'completed',
            'reused': False,
        }
        assert len(provider.page.gotos) == 1
        assert len(provider.page.evaluations) == 1
        assert provider.page.evaluations[0][0].startswith('mw:')
        assert 'grecaptcha' in provider.page.evaluations[0][0]
    finally:
        driver.close()


def test_unknown_paid_intent_is_never_evaluated_again(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    stat = profile.stat()
    config = FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                               (stat.st_dev, stat.st_ino))
    provider = Provider()
    state_path = tmp_path / 'paid.json'
    driver = FlowBrowserDriver(
        config, state_path, 'owner',
        session_factory=lambda _config, **_kwargs: provider,
        paid_dispatch_enabled=True,
        paid_authorization=AUTH,
    )
    driver.start()
    try:
        params = paid_params()
        digest = hashlib.sha256('shot-unknown'.encode()).hexdigest()
        request_digest = hashlib.sha256(params['freq'].encode()).hexdigest()
        key = f'paid-image:{digest}'
        driver._store.begin(key, 'paid_image', {
            'project_id': PROJECT,
            'request_sha256': request_digest,
            'idempotency_sha256': digest,
            'rpcid': fb.RPC_GEN_IMAGE,
        })
        driver._store.mark_unknown(key)

        result = driver.submit_paid_image(
            params, idempotency_key='shot-unknown',
            authorization=AUTH,
        )
        assert result == {
            'status': 409, 'error': 'PAID_RECONCILIATION_REQUIRED',
            'effect': 'unknown',
        }
        assert provider.page.evaluations == []
    finally:
        driver.close()


def test_paid_browser_script_has_bounded_single_shot_contract():
    source = Path('agent/services/flow_browser_paid_image.js').read_text(encoding='utf-8')
    assert "ogiZ0b" in source
    assert "IMAGE_GENERATION" in source
    assert "__CAPTCHA__" in source
    assert "window.grecaptcha.enterprise.execute" in source
    assert "location.pathname !== `/project/${projectId}`" in source
    assert "effect: 'completed'" in source
    assert "effect: 'unknown'" in source
    assert "effect: 'not_submitted'" in source
    assert "for (" not in source or "for (;;)" in source  # body-read loop only; no submit retry loop


@pytest.mark.asyncio
async def test_backend_paid_dispatch_is_locked_by_default_without_driver_submission():
    class Driver:
        def health(self):
            return {'ready': True}

        def submit_paid_image(self, *_args, **_kwargs):
            raise AssertionError('disabled backend must not reach driver')

    backend = BrowserFlowBackend.__new__(BrowserFlowBackend)
    backend._ready = True
    backend._closing = False
    backend._closed = False
    backend._driver = Driver()
    backend._paid_dispatch_enabled = False
    backend._paid_authorization = None

    assert backend.paid_dispatch_enabled is False
    result = await backend.submit_paid_image(
        paid_params(), idempotency_key='shot-1', authorization=AUTH,
    )
    assert result == {
        'status': 403, 'error': 'PAID_DISPATCH_DISABLED',
        'effect': 'not_submitted',
    }
