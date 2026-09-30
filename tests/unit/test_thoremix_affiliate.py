from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'kabin_affiliate_toolkit' / 'src'))

from kabin_affiliate_toolkit.models import AffiliateLink, CommissionSnapshot, PriceSnapshot, ProductCandidate
from agent.thoremix.affiliate import acquire_affiliate
from agent.thoremix.config import Settings


NOW = datetime.now(timezone.utc)


def product(item='1', *, rate=.10, price=100000, sold=2000):
    url = f'https://shopee.vn/product/12/{item}'
    return ProductCandidate(
        shop_id='12', product_id=item, title='Đèn bàn', product_url=url, sold=sold,
        price=PriceSnapshot(current=price, source=url, observed_at=NOW),
        commission=CommissionSnapshot(effective_rate=rate, estimated_value=price * (rate or 0),
                                      verified=True, source='https://affiliate.shopee.vn/offer/shopee_offer',
                                      observed_at=NOW),
        metadata={'sold_evidence': {'source': url, 'sold': sold, 'observed_at': NOW.isoformat()}},
    )


class Context:
    def __init__(self):
        self.destination = None
        self.visited = []
        self.closed_pages = 0
        self.alive = False
        self.navigation_error = None

    def new_page(self):
        context = self

        class Page:
            def goto(self, url, **kwargs):
                assert context.alive
                context.visited.append(url)
                if context.navigation_error:
                    raise context.navigation_error
                self.url = context.destination or url

            def close(self):
                context.closed_pages += 1

        return Page()


class Session:
    def __init__(self):
        self.context = Context()
        self.opened = 0

    @contextmanager
    def session(self):
        self.opened += 1
        self.context.alive = True
        try:
            yield self.context
        finally:
            self.context.alive = False


class Provider:
    def __init__(self, products):
        self.products = products
        self.requests = []
        self.resolves = 0
        self.failure = None
        self.rewrite = None
        self.settings = None
        self.frozen_intent_bytes = None
        self.frozen_intent_hash = None

    def factory(self, browser, *, config):
        self.browser = browser
        self.config = config
        return self

    def search(self, request):
        self.requests.append(request)
        with self.browser.session() as context:
            assert context.alive
        return self.products

    def enrich(self, products, request):
        return products

    def resolve_links(self, products, limit):
        self.resolves += 1
        assert limit == 1
        receipts = list((self.settings.data / 'affiliate').glob('*.json'))
        assert len(receipts) == 1
        receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
        assert receipt['state'] == 'intent'
        self.frozen_intent_bytes = json.dumps(receipt['intent'], ensure_ascii=False, sort_keys=True,
                                             separators=(',', ':')).encode('utf-8')
        self.frozen_intent_hash = receipt['intent_sha256']
        if self.failure:
            raise self.failure
        p = products[0]
        p.affiliate = AffiliateLink(url=p.product_url, status='verified')
        if self.rewrite:
            self.rewrite(p)
        return [p]


@pytest.fixture
def settings(tmp_path):
    profile = tmp_path / 'kdvt-commerce'
    profile.mkdir()
    return Settings(root=str(tmp_path / 'app'), affiliate_profile_dir=str(profile),
                    affiliate_queries=('đèn bàn', 'gia dụng'))


def run(settings, candidates, *, provider=None, session=None):
    provider = provider or Provider(candidates)
    provider.settings = settings
    session = session or Session()
    return acquire_affiliate(settings, session_provider=session, provider_factory=provider.factory), provider, session


def test_percentage_beats_money_and_deduplicates_queries(settings):
    # 20% of 30k < 10% of 190k, but the user asked for percentage.
    a, b = product('1', rate=.2, price=30000), product('2', rate=.1, price=190000)
    result, provider, session = run(settings, [b, a])
    assert result['state'] == 'verified'
    assert result['product']['product_id'] == '1'
    assert result['candidate_count'] == 2
    assert 'tiếp thị liên kết' not in result['comment']
    assert result['url'] in result['comment']
    assert 'lượt bán ghi nhận: 2000' in result['comment']
    assert 'trending' not in result['comment']
    assert provider.resolves == 1 and session.opened == 1
    assert not session.context.alive and session.context.closed_pages == 1
    assert [r.query for r in provider.requests] == list(settings.affiliate_queries)
    assert all(r.selection.resolve_links == 0 for r in provider.requests)


def test_ties_rank_price_then_observed_sold(settings):
    result, _, _ = run(settings, [product('1', price=150000, sold=20000),
                                  product('2', price=50000, sold=1000),
                                  product('3', price=50000, sold=3000)])
    assert result['product']['product_id'] == '3'


@pytest.mark.parametrize('field, value, reason', [
    ('commission.effective_rate', None, 'commission_percentage_unknown_or_zero'),
    ('commission.effective_rate', 0, 'commission_percentage_unknown_or_zero'),
    ('commission.verified', False, 'commission_unverified'),
    ('commission.source', None, 'commission_unverified'),
    ('sold', None, 'observed_sold_evidence_missing'),
    ('price.current', 200001, 'price_above_limit'),
    ('price.current', None, 'price_evidence_missing'),
    ('price.currency', 'USD', 'price_evidence_missing'),
    ('price.source', None, 'price_evidence_missing'),
    ('price.observed_at', NOW - timedelta(hours=7), 'price_evidence_stale'),
    ('commission.observed_at', NOW - timedelta(hours=7), 'commission_evidence_stale'),
    ('commission.observed_at', NOW + timedelta(hours=1), 'commission_evidence_stale'),
])
def test_insufficient_evidence_never_resolves(settings, field, value, reason):
    p = product()
    parts = field.split('.')
    setattr(getattr(p, parts[0]) if len(parts) == 2 else p, parts[-1], value)
    result, provider, _ = run(settings, [p])
    assert result['state'] == 'needs_input'
    assert reason in result['missing_evidence']
    assert provider.resolves == 0


@pytest.mark.parametrize('evidence, reason', [
    ({}, 'observed_sold_evidence_missing'),
    ({'source': 'https://shopee.vn/product/12/1', 'sold': 2000,
      'observed_at': (NOW - timedelta(hours=7)).isoformat()}, 'observed_sold_evidence_stale'),
    ({'source': 'https://shopee.vn/product/12/1', 'sold': 1999,
      'observed_at': NOW.isoformat()}, 'observed_sold_evidence_missing'),
])
def test_sold_needs_actual_fresh_evidence(settings, evidence, reason):
    p = product()
    p.metadata['sold_evidence'] = evidence
    result, provider, _ = run(settings, [p])
    assert reason in result['missing_evidence'] and provider.resolves == 0


def test_price_boundary_and_sales_threshold(settings):
    result, _, _ = run(settings, [product(price=200000, sold=1000)])
    assert result['state'] == 'verified'


def test_low_sales_rejected(settings):
    result, provider, _ = run(settings, [product(sold=999)])
    assert 'observed_sold_below_limit' in result['missing_evidence']
    assert provider.resolves == 0


def test_unknown_xtra_cannot_make_base_effective(settings):
    p = product(rate=None)
    p.commission.base_rate = .2
    result, provider, _ = run(settings, [p])
    assert result['state'] == 'needs_input' and provider.resolves == 0
    p.commission.xtra_rate = 0
    result, _, _ = run(settings, [p])
    assert result['state'] == 'verified'
    assert result['product']['commission']['effective_rate'] == .2


@pytest.mark.parametrize('destination', [
    'https://shopee.vn/product/12/999', 'https://shopee.vn/product/99/1',
    'https://evil.example/product/12/1', 'http://shopee.vn/product/12/1',
])
def test_resolved_destination_identity_required(settings, destination):
    session = Session()
    session.context.destination = destination
    result, provider, _ = run(settings, [product()], session=session)
    assert result['state'] == 'blocked'
    assert result['reason'] == 'affiliate_link_destination_unverified'
    retry, _, _ = run(settings, [product()], provider=provider, session=session)
    assert retry['reason'] == 'affiliate_link_destination_unverified'
    assert provider.resolves == 1


def test_provider_inplace_identity_rewrite_rejected(settings):
    provider = Provider([product()])
    provider.rewrite = lambda p: setattr(p, 'shop_id', '99')
    result, _, _ = run(settings, [], provider=provider)
    assert result['reason'] == 'affiliate_link_resolution_failed'
    assert provider.products[0].shop_id == '12'


def test_provider_changed_commission_during_link_creation_requires_reconciliation(settings):
    provider = Provider([product()])
    provider.rewrite = lambda p: setattr(p.commission, 'effective_rate', .01)
    result, _, _ = run(settings, [], provider=provider)
    assert result['reason'] == 'affiliate_evidence_changed_during_link_resolution'
    again, _, _ = run(settings, [], provider=provider)
    assert again['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert provider.resolves == 1


def test_ambiguous_mutation_never_retried_and_no_credentials_returned(settings):
    provider = Provider([product()])
    provider.failure = RuntimeError('Cookie: sid=secret-value; Authorization: Bearer abc')
    first, _, _ = run(settings, [], provider=provider)
    second, _, _ = run(settings, [], provider=provider)
    assert first['reason'] == 'affiliate_link_resolution_failed'
    assert second['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert provider.resolves == 1
    persisted = next((settings.data / 'affiliate').glob('*.json')).read_text()
    assert 'incomplete' in persisted
    assert 'secret-value' not in json.dumps([first, second]) + persisted
    assert 'Bearer' not in persisted


def test_confirmed_link_reused_with_fresh_evidence_and_destination(settings):
    provider = Provider([product()])
    first, _, _ = run(settings, [], provider=provider)
    second, _, session = run(settings, [], provider=provider)
    assert first['state'] == second['state'] == 'verified'
    assert provider.resolves == 1 and len(session.context.visited) == 1


def test_frozen_intent_and_hash_unchanged_after_success_and_reuse(settings):
    import hashlib
    provider = Provider([product()])
    first, _, _ = run(settings, [], provider=provider)
    assert first['state'] == 'verified'
    path = next((settings.data / 'affiliate').glob('*.json'))
    confirmed_bytes = path.read_bytes()
    receipt = json.loads(confirmed_bytes)
    assert json.dumps(receipt['intent'], ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8') == provider.frozen_intent_bytes
    assert receipt['intent_sha256'] == provider.frozen_intent_hash
    assert hashlib.sha256(provider.frozen_intent_bytes).hexdigest() == provider.frozen_intent_hash
    assert receipt['intent']['commission_rate'] == .1
    assert receipt['intent']['price'] == 100000
    assert receipt['intent']['sold'] == 2000
    assert receipt['intent']['created_at']
    # New discovery data may authorize current reuse; it must not rewrite the
    # evidence that originally authorized the link mutation.
    provider.products[0].price.current = 90000
    second, _, _ = run(settings, [], provider=provider)
    assert second['state'] == 'verified'
    assert path.read_bytes() == confirmed_bytes
    assert provider.resolves == 1


def test_altered_intent_cannot_be_silently_reused(settings):
    provider = Provider([product()])
    run(settings, [], provider=provider)
    path = next((settings.data / 'affiliate').glob('*.json'))
    receipt = json.loads(path.read_text(encoding='utf-8'))
    receipt['intent']['price'] = 1
    path.write_text(json.dumps(receipt), encoding='utf-8')
    result, _, session = run(settings, [], provider=provider)
    assert result['reason'] == 'affiliate_link_intent_requires_reconciliation'
    assert not session.context.visited and provider.resolves == 1


@pytest.mark.parametrize('url', [
    'https://user:password@shopee.vn/product/12/1',
    'https://shopee.vn/product/12/1?access_token=private-token',
    'https://shopee.vn/product/12/1?token=private-token',
    'https://shopee.vn/product/12/1?sid=abc123',
    'https://shopee.vn/product/12/1?session=abc123',
    'https://shopee.vn/product/12/1?utm_source=affiliate',
    'https://s.shopee.vn/example?sid=abc123',
    'https://shopee.vn/product/12/1#private-token',
    'https://shopee.vn.evil.example/product/12/1',
])
def test_credential_or_unsafe_url_not_visited_or_returned(settings, url):
    p = product()
    p.affiliate = AffiliateLink(url=url, status='verified')
    result, provider, session = run(settings, [p])
    assert result['state'] == 'blocked'
    assert not session.context.visited and provider.resolves == 0
    assert url not in json.dumps(result)
    assert not list((settings.data / 'affiliate').glob('*.json'))


@pytest.mark.parametrize('field', ['product', 'price', 'commission', 'sold'])
def test_unknown_source_query_never_reaches_public_pack_or_receipt(settings, field):
    p = product()
    unsafe = 'https://shopee.vn/product/12/1?session=private-session-value'
    if field == 'product':
        p.product_url = unsafe
    elif field == 'sold':
        p.metadata['sold_evidence']['source'] = unsafe
    else:
        getattr(p, field).source = unsafe
    result, provider, _ = run(settings, [p])
    assert result['state'] == 'needs_input' and provider.resolves == 0
    assert 'private-session-value' not in json.dumps(result)
    assert not list((settings.data / 'affiliate').glob('*.json'))


def test_resolver_session_query_cannot_leak_to_incomplete_receipt(settings):
    provider = Provider([product()])
    unsafe = 'https://shopee.vn/product/12/1?sid=private-session-value'
    provider.rewrite = lambda p: setattr(p.affiliate, 'url', unsafe)
    result, _, session = run(settings, [], provider=provider)
    assert result['reason'] == 'affiliate_link_destination_unverified'
    assert not session.context.visited
    receipt = next((settings.data / 'affiliate').glob('*.json')).read_text(encoding='utf-8')
    assert 'incomplete' in receipt
    assert 'private-session-value' not in receipt + json.dumps(result)
    retry, _, _ = run(settings, [], provider=provider)
    assert retry['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert provider.resolves == 1


def test_public_sources_and_product_urls_are_canonicalized(settings):
    p = product()
    p.product_url = 'https://www.shopee.vn/Den-ban-i.12.1'
    p.price.source = 'https://shopee.vn/search?keyword=den+ban'
    p.metadata['sold_evidence']['source'] = p.price.source
    result, _, _ = run(settings, [p])
    assert result['state'] == 'verified'
    assert result['product']['product_url'] == 'https://shopee.vn/product/12/1'
    assert result['product']['price']['source'] == 'https://shopee.vn/search'
    assert result['product']['sold_evidence']['source'] == 'https://shopee.vn/search'


def test_short_link_requires_observed_redirect_and_metadata_is_not_output(settings):
    p = product()
    p.metadata['cookies'] = 'private-cookie'
    p.metadata['warnings'] = ['Authorization: private-token']
    # Exact query-free form demonstrated in KAT tests/test_commenting.py.
    p.affiliate = AffiliateLink(url='https://s.shopee.vn/example', status='resolved')
    session = Session()
    session.context.destination = p.product_url
    result, provider, _ = run(settings, [p], session=session)
    assert result['state'] == 'verified' and provider.resolves == 0
    assert 'private-' not in json.dumps(result)


@pytest.mark.parametrize('failure', ['login_redirect', 'timeout'])
def test_existing_link_read_only_retry_preserves_frozen_intent(settings, failure):
    p = product()
    frozen_url = 'https://s.shopee.vn/example'
    p.affiliate = AffiliateLink(url=frozen_url, status='resolved')
    provider = Provider([p])
    session = Session()
    if failure == 'timeout':
        session.context.navigation_error = TimeoutError('network temporarily unavailable')
    else:
        session.context.destination = 'https://shopee.vn/buyer/login'
    first, _, _ = run(settings, [], provider=provider, session=session)
    assert first['state'] == 'blocked' and provider.resolves == 0
    path = next((settings.data / 'affiliate').glob('*.json'))
    before = json.loads(path.read_text(encoding='utf-8'))
    assert before['state'] == 'incomplete'
    assert before['intent']['effect'] == 'verify_existing_link'
    assert before['intent']['existing_url'] == frozen_url
    intent_bytes = json.dumps(before['intent'], sort_keys=True).encode()
    # Repair the read surface. A changed provider URL must not change the intent.
    session.context.navigation_error = None
    session.context.destination = p.product_url
    p.affiliate.url = 'https://s.shopee.vn/different'
    second, _, _ = run(settings, [], provider=provider, session=session)
    assert second['state'] == 'verified' and second['url'] == frozen_url
    assert session.context.visited == [frozen_url, frozen_url]
    assert provider.resolves == 0
    after = json.loads(path.read_text(encoding='utf-8'))
    assert after['state'] == 'verified'
    assert json.dumps(after['intent'], sort_keys=True).encode() == intent_bytes
    assert before['intent_sha256'] == after['intent_sha256']


def test_configured_profile_passed_to_owned_kat_with_exclusive_lease(settings, monkeypatch):
    import kabin_affiliate_toolkit.browser as browser
    session = Session()
    configs = []

    def owner(config):
        configs.append(config)
        return session

    monkeypatch.setattr(browser, 'OwnedCamoufoxSessionProvider', owner)
    provider = Provider([product()])
    provider.settings = settings
    result = acquire_affiliate(settings, provider_factory=provider.factory)
    assert result['state'] == 'verified'
    assert configs[0].profile_dir == Path(settings.affiliate_profile_dir).resolve()
    assert configs[0].lock_profile is True and session.opened == 1


def test_missing_profile_never_created(settings, tmp_path):
    from dataclasses import replace
    absent = tmp_path / 'absent-profile'
    session = Session()
    result = acquire_affiliate(replace(settings, affiliate_profile_dir=str(absent)), session_provider=session)
    assert result['reason'] == 'configured_existing_affiliate_profile_required'
    assert not absent.exists() and session.opened == 0


def test_native_provider_keeps_live_gate_and_records_search_evidence(settings, monkeypatch):
    import kabin_affiliate_toolkit.providers.shopee as shopee
    p = product()
    p.commission.base_rate = .1
    p.commission.xtra_rate = 0
    p.metadata = {'evidence': {'surface': 'shopee_search', 'url': 'https://shopee.vn/search?keyword=den',
                               'anchor_index': 0}}
    class StockProvider(Provider, shopee.ShopeeVNProvider):
        pass
    provider = StockProvider([p])
    result = acquire_affiliate(settings, session_provider=Session(), provider_factory=provider.factory)
    assert result['reason'] == 'shopee_link_resolution_not_live_verified'
    assert provider.resolves == 0 and provider.config.allow_unverified_link_resolution is False
    assert p.metadata['sold_evidence']['sold'] == 2000


@pytest.mark.parametrize('base, xtra, total', [(None, .2, .2), (.2, None, .2), (None, None, .2)])
def test_native_synthetic_non_none_total_rejects_unknown_components(settings, monkeypatch, base, xtra, total):
    import kabin_affiliate_toolkit.providers.shopee as shopee
    p = product(rate=total)
    p.commission.base_rate = base
    p.commission.xtra_rate = xtra
    class StockProvider(Provider, shopee.ShopeeVNProvider):
        pass
    provider = StockProvider([p])
    result = acquire_affiliate(settings, session_provider=Session(), provider_factory=provider.factory)
    assert result['state'] == 'needs_input'
    assert 'native_commission_components_unknown' in result['missing_evidence']
    assert provider.resolves == 0


def test_trusted_provider_observed_total_does_not_require_components(settings):
    p = product(rate=.2)
    assert p.commission.base_rate is None and p.commission.xtra_rate is None
    result, _, _ = run(settings, [p])
    assert result['state'] == 'verified'
    assert result['product']['commission']['effective_rate'] == .2


@pytest.mark.parametrize('unsafe', [False, True])
def test_story_stage_preserves_only_fixed_affiliate_failure_diagnostics(settings, monkeypatch, unsafe):
    from agent.thoremix import affiliate
    from agent.thoremix.story_operations import StoryOperations
    value = {'state':'blocked', 'reason':'shopee_affiliate_link_unconfirmed', 'phase':'link_resolution',
             'candidate_count':20, 'link_stage':'link_observation', 'activation_state':'unknown_after_dispatch',
             'provider_text':'Cookie: private', 'url':'https://example.invalid/?token=private'}
    if unsafe:
        value.update(reason='Cookie: private', phase='https://private.invalid', candidate_count='private',
                     link_stage='private', activation_state='private')
    monkeypatch.setattr(affiliate, 'acquire_affiliate', lambda _:value)
    result = StoryOperations(settings, object())._run('affiliate', {'source':str(settings.directory/'fixture.png')},
                                                  settings.data, lambda _:None)
    assert result['state'] == 'uncertain'
    if unsafe:
        assert result == {'state':'uncertain', 'reason':'AFFILIATE_UNVERIFIED'}
    else:
        assert result == {'state':'uncertain', 'reason':'shopee_affiliate_link_unconfirmed',
            'phase':'link_resolution', 'candidate_count':20, 'link_stage':'link_observation',
            'activation_state':'unknown_after_dispatch'}
    assert 'private' not in json.dumps(result)
