"""FBR-1 must never turn arbitrary observed POSTs into executable recipes."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlencode

import pytest

from agent.services import flow_batch as fb

PROJECT = '487247a1-00f4-4de3-83c1-4c16ce834b93'


def impl():
    from agent.services import flow_browser_discovery
    return flow_browser_discovery


def request(*, rpc='Zzl0ze', freq=None, url=None, method='POST'):
    return SimpleNamespace(method=method,
        url=url or f'https://flow.google.com{fb.BATCH_PATH}?rpcids={rpc}&bl=build',
        post_data=urlencode({'f.req': freq or fb.project_media_request(PROJECT), 'at': 'PRIVATE_TOKEN'}))


def test_observed_read_envelope_is_validated_without_returning_credentials():
    recipe = impl().classify_read_request(request())
    assert recipe['rpc_id'] == 'Zzl0ze'
    assert recipe['project_id'] == PROJECT
    assert 'PRIVATE_TOKEN' not in json.dumps(recipe)


def test_live_form_trailing_separator_is_accepted_without_loosening_key_guard():
    value = request()
    value.post_data += '&'
    assert impl().classify_read_request(value)['rpc_id'] == 'Zzl0ze'


@pytest.mark.parametrize('changes', [
    {'rpc': fb.RPC_GEN_VIDEO}, {'method': 'GET'},
    {'url': f'https://evil.invalid{fb.BATCH_PATH}?rpcids=Zzl0ze'},
    {'url': f'https://user@flow.google.com{fb.BATCH_PATH}?rpcids=Zzl0ze'},
    {'url': f'https://flow.google.com:444{fb.BATCH_PATH}?rpcids=Zzl0ze'},
    {'url': f'https://flow.google.com{fb.BATCH_PATH}?rpcids=Zzl0ze&rpcids=ogiZ0b'},
    {'freq': fb.build_envelope('ogiZ0b', ['mutating'])},
    {'freq': fb.build_envelope('Zzl0ze', ['projects/not-uuid', None, None, None, [1]])},
    {'freq': fb.build_envelope('Zzl0ze', [f'projects/{PROJECT}', None, None, None, [2]])},
    {'freq': 'not-json'},
])
def test_unverified_request_is_blocked(changes):
    with pytest.raises(impl().DiscoveryError):
        impl().classify_read_request(request(**changes))


def test_mixed_batch_and_oversized_form_are_blocked():
    envelope = json.loads(fb.project_media_request(PROJECT))
    envelope[0].append([fb.RPC_GEN_VIDEO, '[]', None, 'generic'])
    with pytest.raises(impl().DiscoveryError):
        impl().classify_read_request(request(freq=json.dumps(envelope)))
    value = request()
    value.post_data += '&extra=' + 'x' * 20000
    with pytest.raises(impl().DiscoveryError):
        impl().classify_read_request(value)


def test_encoded_duplicate_form_key_and_boolean_enum_cannot_bypass_guard():
    value = request()
    value.post_data += '&%66.req=' + urlencode({'x': fb.build_envelope('ogiZ0b', [])})[2:]
    with pytest.raises(impl().DiscoveryError):
        impl().classify_read_request(value)


def test_boolean_enum_cannot_bypass_guard():
    with pytest.raises(impl().DiscoveryError):
        impl().classify_read_request(request(freq=fb.build_envelope('Zzl0ze',
            [f'projects/{PROJECT}', None, None, None, [True]])))


def test_structure_projection_contains_no_scalar_values_or_object_keys():
    secret = {'secret-key@example.invalid': ['private-token', 'https://host/?token=SECRET', 123456]}
    serialized = json.dumps(impl().body_shape(secret))
    for forbidden in ('secret-key', 'private-token', 'https://', 'SECRET', '123456'):
        assert forbidden not in serialized
    assert len(json.dumps(impl().body_shape([[['x']] * 100] * 100))) < 6000


def harness():
    provider = Mock()
    provider.capture_health.return_value = {'ready': True}
    provider.session.page.url = 'https://flow.google.com/'
    observer = Mock()
    observer.session = provider.session
    observer.runtime_ref.return_value = SimpleNamespace(request=request())
    observer.exchange.return_value = SimpleNamespace(response=SimpleNamespace(status=200), outcome='completed')
    clock = [100.0]
    handlers = {}
    provider.session.page.on.side_effect = lambda event, handler: handlers.update({event: handler})
    discovery = impl().FlowReadDiscovery(provider, observer=observer, clock=lambda: clock[0])
    discovery.start()
    if 'request' in handlers:
        handlers['request'](observer.runtime_ref.return_value.request)
    return discovery, provider, observer, clock


@pytest.mark.parametrize('stale', ['navigation', 'expired'])
def test_old_exchange_cannot_be_rebound_after_navigation_or_expiry(stale):
    discovery, _, _, clock = harness()
    if stale == 'navigation': discovery.invalidate()
    else: clock[0] += 61
    with pytest.raises(impl().DiscoveryError):
        discovery.bind('exchange-1')


def test_unrelated_static_requests_do_not_evict_read_freshness():
    discovery, _, _, _ = harness()
    requests = [SimpleNamespace(url=f'https://flow.google.com/static/{index}.js', method='GET')
                for index in range(70)]
    for request_value in requests:
        discovery._observe_request(request_value)
    assert discovery.bind('exchange-1')


def test_child_frame_navigation_does_not_invalidate_main_page_read():
    discovery, provider, _, _ = harness()
    handlers = dict(call.args for call in provider.session.page.on.call_args_list)
    handlers['framenavigated'](object())
    assert discovery.bind('exchange-1')


@pytest.mark.parametrize('stale', ['expired', 'navigation', 'session', 'auth', 'request_changed'])
def test_stale_recipe_never_reaches_replay(stale):
    discovery, provider, observer, clock = harness()
    recipe = discovery.bind('exchange-1')
    replay = Mock()
    if stale == 'expired': clock[0] += 61
    if stale == 'navigation': discovery.invalidate()
    if stale == 'session': provider.session = Mock()
    if stale == 'auth': provider.capture_health.return_value = {'ready': False}
    if stale == 'request_changed': observer.runtime_ref.return_value.request = request(rpc='ogiZ0b')
    with pytest.raises(impl().DiscoveryError):
        discovery.replay(recipe, service=replay)
    replay.replay_exchange.assert_not_called()


def test_validated_recipe_is_single_use_even_after_ambiguous_replay_failure():
    discovery, _, _, _ = harness()
    recipe = discovery.bind('exchange-1')
    discovery.capture('exchange-1', service=body_service())
    replay = Mock()
    replay.replay_exchange.side_effect = RuntimeError('PRIVATE_TOKEN')
    with pytest.raises(impl().DiscoveryError, match='REPLAY_FAILED'):
        discovery.replay(recipe, service=replay)
    with pytest.raises(impl().DiscoveryError):
        discovery.replay(recipe, service=replay)
    assert replay.replay_exchange.call_count == 1


def body_service():
    service = Mock()
    payload = json.dumps([['wrb.fr','Zzl0ze',json.dumps(['PRIVATE_CONTENT']),None]])
    service.capture_response.return_value = SimpleNamespace(
        raw_bytes=payload.encode(), summary=SimpleNamespace(status='captured_inline',captured_bytes=len(payload)))
    return service


def test_missing_captured_baseline_blocks_before_network_effect():
    discovery, _, _, _ = harness()
    replay = Mock()
    with pytest.raises(impl().DiscoveryError):
        discovery.replay(discovery.bind('exchange-1'), service=replay)
    replay.replay_exchange.assert_not_called()


def test_failed_replay_cannot_be_rebound_to_bypass_single_use_guard():
    discovery, _, _, _ = harness()
    discovery.capture('exchange-1', service=body_service())
    replay = Mock()
    replay.replay_exchange.side_effect = RuntimeError('private failure')
    with pytest.raises(impl().DiscoveryError):
        discovery.replay(discovery.bind('exchange-1'), service=replay)
    with pytest.raises(impl().DiscoveryError):
        discovery.bind('exchange-1')


def test_second_ticket_for_same_exchange_cannot_send_again():
    discovery, _, _, _ = harness()
    discovery.bind('exchange-1')
    with pytest.raises(impl().DiscoveryError):
        discovery.bind('exchange-1')


def test_registration_failure_rolls_back_every_attached_listener():
    discovery, provider, observer, _ = harness()
    discovery.close()
    provider.session.page.reset_mock()
    provider.session.page.on.side_effect = [None, RuntimeError('private')]
    new = impl().FlowReadDiscovery(provider, observer=observer)
    with pytest.raises(impl().DiscoveryError):
        new.start()
    provider.session.page.remove_listener.assert_called_once()


def test_cleanup_attempts_all_listeners_when_one_removal_fails():
    discovery, provider, observer, _ = harness()
    provider.session.page.remove_listener.side_effect = RuntimeError('private')
    with pytest.raises(impl().DiscoveryError):
        discovery.close()
    assert provider.session.page.remove_listener.call_count == 2
    observer.close.assert_called_once()


def test_replay_response_shape_drift_invalidates_recipe():
    discovery, _, _, _ = harness()
    discovery.capture('exchange-1', service=body_service())
    service = body_service()
    service.capture_response.return_value.raw_bytes = json.dumps(
        [['wrb.fr','Zzl0ze',json.dumps([[['different shape']]]),None]]).encode()
    replay = Mock()
    replay.replay_exchange.return_value = SimpleNamespace(
        summary=SimpleNamespace(status='completed', http_status=200),
        body=service.capture_response.return_value)
    with pytest.raises(impl().DiscoveryError, match='RESPONSE_SHAPE_CHANGED'):
        discovery.replay(discovery.bind('exchange-1'), service=replay)


def test_matching_response_shape_validates_single_read_and_hides_content():
    discovery, _, observer, _ = harness()
    service = body_service()
    discovery.capture('exchange-1', service=service)
    replay = Mock()
    replay.replay_exchange.return_value = SimpleNamespace(
        summary=SimpleNamespace(status='completed', http_status=200),
        body=service.capture_response.return_value)
    receipt = discovery.replay(discovery.bind('exchange-1'), service=replay)
    assert receipt['replay'] == 'validated'
    assert 'PRIVATE_CONTENT' not in json.dumps(receipt)
    replay.replay_exchange.assert_called_once_with(observer, 'exchange-1',
        body_mode='inline', sensitive_response=True)


def test_bounded_replay_failure_reports_structured_reason_without_raw_diagnostic():
    discovery, _, _, _ = harness()
    discovery.capture('exchange-1', service=body_service())
    replay = Mock()
    replay.replay_exchange.return_value = SimpleNamespace(
        summary=SimpleNamespace(status='body_size_unknown', http_status=200, diagnostic='PRIVATE'), body=None)
    receipt = discovery.replay(discovery.bind('exchange-1'), service=replay)
    assert receipt['reason'] == 'body_size_unknown'
    assert 'PRIVATE' not in json.dumps(receipt)


def test_capture_budget_refuses_extra_body_reads_and_returns_shape_only():
    discovery, _, _, _ = harness()
    service = Mock()
    payload = json.dumps([['wrb.fr','Zzl0ze',json.dumps(['PRIVATE_CONTENT']),None]])
    service.capture_response.return_value = SimpleNamespace(
        raw_bytes=payload.encode(), summary=SimpleNamespace(status='captured_inline',captured_bytes=len(payload)))
    for index in range(3):
        receipt = discovery.capture(f'exchange-{index}', service=service)
        assert 'PRIVATE_CONTENT' not in json.dumps(receipt)
    with pytest.raises(impl().DiscoveryError, match='CAPTURE_BUDGET'):
        discovery.capture('exchange-4', service=service)
    assert service.capture_response.call_count == 3


def test_real_kbs_policy_replays_only_the_live_validated_read_handle():
    from kabin_browser_semantic import BrowserSession

    req = request()
    raw = json.dumps([['wrb.fr', 'Zzl0ze', json.dumps(['PRIVATE_CONTENT']), None]]).encode()
    req.headers = {'content-type': 'application/x-www-form-urlencoded',
                   'content-length': str(len(req.post_data))}
    req.resource_type = 'xhr'
    req.is_navigation_request = lambda: False
    req.redirected_from = None
    req.sizes = lambda: {'requestBodySize': len(req.post_data), 'responseBodySize': len(raw)}
    response = SimpleNamespace(request=req, status=200, status_text='OK', url=req.url,
        headers={'content-type': 'application/json', 'content-length': str(len(raw))},
        body=lambda: raw, dispose=Mock())
    fetch = Mock(return_value=response)

    class Page:
        url = 'https://flow.google.com/'
        context = SimpleNamespace(request=SimpleNamespace(fetch=fetch))

        def __init__(self):
            self.listeners = {}

        def on(self, event, handler):
            self.listeners.setdefault(event, []).append(handler)

        def remove_listener(self, event, handler):
            self.listeners[event].remove(handler)

        def emit(self, event, value):
            for handler in self.listeners.get(event, []):
                handler(value)

    page = Page()
    provider = SimpleNamespace(session=BrowserSession.from_page(page), capture_health=lambda: {'ready': True})
    discovery = impl().FlowReadDiscovery(provider).start()
    try:
        page.emit('request', req)
        page.emit('response', response)
        page.emit('requestfinished', req)
        exchange = discovery.observer.exchanges()[0]
        assert discovery.capture(exchange.exchange_id)['capture'] == 'captured'
        receipt = discovery.replay(discovery.bind(exchange.exchange_id))
        assert receipt['replay'] == 'validated'
        assert fetch.call_args.args == (req,)
        assert fetch.call_args.kwargs['max_retries'] == 0
        assert fetch.call_args.kwargs['max_redirects'] == 0
        assert fetch.call_count == 1
        assert response.dispose.call_count == 1
        assert 'PRIVATE' not in json.dumps(receipt)
    finally:
        discovery.close()
    assert all(not values for values in page.listeners.values())


def test_page_replay_consumes_ticket_and_returns_only_verified_projection():
    discovery, provider, _, _ = harness()
    baseline = body_service()
    discovery.capture('exchange-1', service=baseline)
    raw = baseline.capture_response.return_value.raw_bytes
    provider.session.page.evaluate.return_value = {'status': 200, 'text': raw.decode(), 'bytes': len(raw)}
    ticket = discovery.bind('exchange-1')
    receipt = discovery.replay_in_page(ticket)
    assert receipt['replay'] == 'validated'
    assert 'PRIVATE_CONTENT' not in json.dumps(receipt)
    args = provider.session.page.evaluate.call_args.args[1]
    assert args == {'projectId': PROJECT}
    with pytest.raises(impl().DiscoveryError):
        discovery.replay_in_page(ticket)
    assert provider.session.page.evaluate.call_count == 1


@pytest.mark.parametrize('result', [
    {'status': 200, 'error': 'BODY_BUDGET'},
    {'status': 200, 'error': 'BODY_INCOMPLETE'},
    {'status': 200, 'bytes': 10, 'text': 'partial'},
    {'status': 403, 'text': 'PRIVATE_TOKEN'},
])
def test_page_replay_never_validates_incomplete_or_rejected_body(result):
    discovery, provider, _, _ = harness()
    discovery.capture('exchange-1', service=body_service())
    provider.session.page.evaluate.return_value = result
    receipt = discovery.replay_in_page(discovery.bind('exchange-1'))
    assert receipt['replay'] == 'not_validated'
    assert 'PRIVATE_TOKEN' not in json.dumps(receipt)


@pytest.mark.parametrize('stale', ['navigation', 'expired', 'auth', 'missing_baseline'])
def test_page_replay_checks_guard_before_browser_effect(stale):
    discovery, provider, _, clock = harness()
    ticket = discovery.bind('exchange-1')
    if stale != 'missing_baseline':
        discovery.capture('exchange-1', service=body_service())
    if stale == 'navigation': discovery.invalidate()
    if stale == 'expired': clock[0] += 61
    if stale == 'auth': provider.capture_health.return_value = {'ready': False}
    with pytest.raises(impl().DiscoveryError):
        discovery.replay_in_page(ticket)
    provider.session.page.evaluate.assert_not_called()


@pytest.mark.parametrize('change', ['navigation', 'auth', 'own_request'])
def test_page_replay_does_not_validate_stale_flight_or_authorize_its_own_fetch(change):
    discovery, provider, observer, _ = harness()
    baseline = body_service()
    discovery.capture('exchange-1', service=baseline)
    raw = baseline.capture_response.return_value.raw_bytes
    own_request = request()

    def in_flight(*_):
        if change == 'navigation': discovery.invalidate()
        if change == 'auth': provider.capture_health.return_value = {'ready': False}
        if change == 'own_request': discovery._observe_request(own_request)
        return {'status': 200, 'text': raw.decode(), 'bytes': len(raw)}

    provider.session.page.evaluate.side_effect = in_flight
    ticket = discovery.bind('exchange-1')
    if change == 'own_request':
        assert discovery.replay_in_page(ticket)['replay'] == 'validated'
        observer.runtime_ref.return_value = SimpleNamespace(request=own_request)
        with pytest.raises(impl().DiscoveryError, match='RECIPE_EXPIRED'):
            discovery.bind('replayed-exchange')
    else:
        with pytest.raises(impl().DiscoveryError):
            discovery.replay_in_page(ticket)
