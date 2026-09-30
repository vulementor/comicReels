from contextlib import nullcontext
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'kabin_affiliate_toolkit/src'))
from kabin_affiliate_toolkit.models import ProductRecommendRequest
from kabin_affiliate_toolkit.providers.shopee import ShopeeProviderConfig
from agent.thoremix import affiliate
from agent.thoremix.catalog import (CATALOG_URL, ShopeeCatalogProvider, channel_rates,
                                   parse_card, parse_observed_commission, parse_observed_sold,
                                   parse_price, product_identity)
from agent.thoremix.config import Settings


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CARDS = json.loads((FIXTURES / 'thoremix_shopee_cards.json').read_text(encoding='utf-8'))['cards']
DETAIL = json.loads((FIXTURES / 'thoremix_shopee_detail.json').read_text(encoding='utf-8'))
NOW = datetime.now(timezone.utc)


@pytest.mark.parametrize('raw, expected', [('₫120.000', 120000), ('225.000', 225000), ('4.398.999', 4398999),
                                          ('12,5', None), ('--', None), ('0', 0)])
def test_observed_price_forms(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize('raw, amount, lower', [
    ('10k+ lượt bán', 10000, True),
    ('600k+ lượt bán', 600000, True),
    ('155 lượt bán', 155, False),
    ('1,5k+ lượt bán', 1500, True),
    ('600k+ sold', 600000, True),
    ('155 sold', 155, False),
])
def test_observed_sold_is_explicit_lower_bound(raw, amount, lower):
    parsed = parse_observed_sold(raw)
    assert parsed['sold'] == amount and parsed['is_lower_bound'] is lower
    assert parsed['display_text'] == raw


def test_unknown_and_ambiguous_sold_are_not_zero():
    assert parse_observed_sold('Sản phẩm mới') is None
    assert parse_observed_sold('10 lượt bán 100 lượt bán') is None


@pytest.mark.parametrize('raw, expected', [
    ('Tỉ lệ hoa hồng 12,5%', .125),
    ('Tỷ lệ hoa hồng 17.5%', .175),
    ('TỈ LỆ HOA HỒNG 17.5%', .175),
    ('Comm Rate 12,5%', .125),
    ('Commission Rate 17.5%', .175),
    ('Tỉ lệ hoa hồng 0%', 0.0),
])
def test_product_offer_card_commission_is_parsed_as_listing_evidence(raw, expected):
    parsed = parse_observed_commission(raw)
    assert parsed['effective_rate'] == expected
    assert parsed['display_text'] == raw


def test_missing_or_ambiguous_card_commission_stays_unknown():
    assert parse_observed_commission('Không hiển thị hoa hồng') is None
    assert parse_observed_commission('Tỉ lệ hoa hồng 12,5% / Tỉ lệ hoa hồng 5%') is None


def test_live_card_fixture_projects_source_and_lower_bound():
    p = parse_card(DETAIL['selected_card'], observed_at=NOW)
    assert p.product_id == '2931643720' and p.price.current == 120000
    assert p.sold == 10000 and p.metadata['sold_evidence']['is_lower_bound']
    assert p.metadata['sold_evidence']['source'] == CATALOG_URL
    assert p.metadata['catalog_commission']['effective_rate'] == .125
    assert p.metadata['catalog_commission']['source'] == CATALOG_URL
    assert not p.commission.verified  # listing rate remains separate from per-placement proof


def test_observed_internal_offer_trace_is_validated_then_removed():
    from urllib.parse import urlencode
    # Keys/types observed during the bounded live diagnostic; values are fixtures.
    trace = {'trace_id': '0.catalog.100', 'list_type': 100, 'exp_group_ids': [738367],
             'root_trace_id': '0.catalog.100', 'root_list_type': 100}
    card = DETAIL['selected_card'].copy()
    card['href'] += '?' + urlencode({'trace': json.dumps(trace)})
    p = parse_card(card, observed_at=NOW)
    assert p is not None
    assert p.metadata['offer_url'] == DETAIL['selected_card']['href']
    assert '?' not in p.product_url and 'trace_id' not in p.model_dump_json()
    for query in ('sid=private', 'session=private', 'trace=invalid', 'unknown=value'):
        card['href'] = DETAIL['selected_card']['href'] + '?' + query
        assert parse_card(card, observed_at=NOW) is None
    trace['session'] = 'private'
    card['href'] = DETAIL['selected_card']['href'] + '?' + urlencode({'trace': json.dumps(trace)})
    assert parse_card(card, observed_at=NOW) is None


def test_channel_totals_are_percentages_and_do_not_sum_money_column():
    rates = channel_rates(DETAIL['rows'])
    assert rates['other_social']['effective_rate'] == .125
    assert rates['facebook_reels']['effective_rate'] == .15
    assert min(r['effective_rate'] for r in rates.values()) == .125


def test_english_detail_labels_use_the_same_cross_channel_contract():
    rows = [
        ['Channel Type', 'Content Type', '', 'Commission from Shopee', 'Estimated Commission'],
        ['Social Media\nMost Used Channel', 'Other Content', '10% (₫12.000)', '2,5% (₫3.000)', '₫15.000'],
        ['Reels on Facebook/Instagram', '10% (₫12.000)', '5% (₫6.000)', '₫18.000'],
    ]
    rates = channel_rates(rows)
    assert rates['other_social']['effective_rate'] == .125
    assert rates['facebook_reels']['effective_rate'] == .15


@pytest.mark.parametrize('row, column, replacement', [(1, 2, '--'), (1, 3, ''), (2, 1, '10% total 15%'),
                                                     (2, 2, 'unknown'), (2, 3, '15%')])
def test_unknown_components_or_total_column_reject(row, column, replacement):
    rows = json.loads(json.dumps(DETAIL['rows']))
    rows[row][column] = replacement
    with pytest.raises(ValueError):
        channel_rates(rows)


def test_other_social_and_reels_must_both_be_unique():
    with pytest.raises(ValueError):
        channel_rates(DETAIL['rows'] + [DETAIL['rows'][2]])
    with pytest.raises(ValueError):
        channel_rates([DETAIL['rows'][0], DETAIL['rows'][2]])


def test_identity_requires_one_exact_shop_item():
    assert product_identity(DETAIL['product_links'], '2931643720') == ('252432728', '2931643720')
    with pytest.raises(ValueError):
        product_identity(DETAIL['product_links'], '999')
    with pytest.raises(ValueError):
        product_identity(DETAIL['product_links'] + ['https://shopee.vn/product/999/2931643720'], '2931643720')


class Locator:
    def __init__(self, page, selector, index=None):
        self.page, self.selector, self.index = page, selector, index
        self.first = self

    def nth(self, index):
        return Locator(self.page, self.selector, index=index)

    def wait_for(self, **kwargs):
        if self.selector == '.AffiliateItemCard':
            self.page.waited_cards = True

    def inner_text(self, **kwargs):
        return self.page.guard_text

    def count(self):
        if self.selector == '.AffiliateItemCard':
            return 1 if self.index is not None else len(self.page.cards)
        return self.page.dialog_count if 'dialog' in self.selector else 1

    def evaluate(self, script):
        if self.selector == '.AffiliateItemCard' and self.index is not None:
            return self.page.cards[self.index]
        raise AssertionError(self.selector)

    def get_by_role(self, role, **kwargs):
        assert role == 'button' and kwargs == {'name': 'Lấy link', 'exact': True}
        return Button(self.page)

    def evaluate_all(self, script):
        if self.selector == '.AffiliateItemCard':
            assert self.page.waited_cards
            return self.page.cards
        if self.selector == 'a[href]':
            return self.page.product_links
        if self.selector == 'tr':
            return self.page.rows
        raise AssertionError(self.selector)


class Button:
    def __init__(self, page):
        self.page = page

    def count(self):
        return self.page.button_count

    def focus(self, **kwargs):
        self.page.focused = True

    def evaluate(self, script):
        return self.page.focused

    def press(self, key, **kwargs):
        assert key == 'Enter' and self.page.focused
        self.page.presses += 1
        if self.page.press_error:
            raise TimeoutError('dispatch timeout')


class CatalogPage:
    def __init__(self, cards=None):
        self.cards = cards if cards is not None else [DETAIL['selected_card']]
        self.product_links = DETAIL['product_links']
        self.rows = DETAIL['rows']
        self.url = CATALOG_URL
        self.visited = []
        self.waited_cards = False
        self.dialog_count = 0
        self.button_count = 1
        self.presses = 0
        self.focused = False
        self.press_error = False
        self.short_links = ['https://s.shopee.vn/newexample']
        self.guard_text = 'Catalog authenticated'

    def goto(self, url, **kwargs):
        self.url = url
        self.visited.append(url)

    def locator(self, selector):
        return Locator(self, selector)

    def get_by_text(self, text, **kwargs):
        return Locator(self, text)

    def get_by_role(self, role, **kwargs):
        assert role == 'button' and kwargs == {'name': 'Lấy link', 'exact': True}
        return Button(self)

    def evaluate(self, script):
        return self.short_links

    def wait_for_timeout(self, ms):
        pass

    def wait_for_function(self, script, **kwargs):
        self.waited_detail = True


class Browser:
    def __init__(self, page):
        self.pages = [page]
        self.destinations = ['https://shopee.vn/product/252432728/2931643720']
        self.link_visits = []

    def session(self, **kwargs):
        return nullcontext(self)

    def new_page(self):
        browser = self
        class Redirect:
            index = 0

            @property
            def url(self):
                return browser.destinations[min(self.index, len(browser.destinations) - 1)]

            def goto(self, url, **kwargs):
                browser.link_visits.append(url)

            def wait_for_timeout(self, ms):
                self.index += 1

            def close(self):
                pass
        return Redirect()


@pytest.fixture
def settings(tmp_path):
    profile = tmp_path / 'commerce-profile'
    profile.mkdir()
    return Settings(root=str(tmp_path / 'app'), affiliate_profile_dir=str(profile))


def request():
    return ProductRecommendRequest(
        query='gia dụng',
        selection={'price_max': 200000, 'sold_min': 1000},
        context={},
    )


def test_catalog_card_rates_avoid_detail_reads_and_cache_across_queries():
    page = CatalogPage(CARDS)
    provider = ShopeeCatalogProvider(Browser(page), config=ShopeeProviderConfig(enrich_limit=2))
    detailed = []
    def detail(page, product):
        detailed.append(product.product_id)
        return ('123', product.product_id), channel_rates(DETAIL['rows'])
    provider._detail = detail
    found = provider.search(request())
    enriched = provider.enrich(found, request())
    provider.enrich(provider.search(request()), request())
    assert len(found) == 20 and provider.observed_count == 20
    assert detailed == []
    assert len(page.visited) == 1 and provider.detail_count == 0
    verified = [p for p in enriched if p.commission.verified]
    assert verified
    assert all(p.metadata['commission_basis'] == 'product_offer_card_display' for p in verified)


def test_default_is_catalog_first_with_one_activation_and_lower_bound_comment(settings):
    page = CatalogPage()
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified'
    assert result['product']['commission']['effective_rate'] == .125
    assert result['product']['commission']['basis'] == 'product_offer_card_display'
    assert 'placement_rates' not in result['product']['commission']
    assert 'ít nhất 10000' in result['comment']
    assert result['selection_evidence']['detail_count'] == 0
    assert result['selection_evidence']['rate_basis'] == 'product_offer_card_display'
    assert result['candidate_count'] == 1 and page.presses == 1
    assert page.visited == [CATALOG_URL, CATALOG_URL]
    receipt = json.loads(next((settings.data / 'affiliate').glob('*.json')).read_text(encoding='utf-8'))
    assert receipt['resolved_url'] == result['url']
    assert receipt['resolved_product_id'] == '2931643720'
    assert receipt['resolved_identity'] == ['252432728', '2931643720']
    assert receipt['intent']['catalog_offer'] == DETAIL['selected_card']['href']
    assert receipt['intent']['sold_is_lower_bound'] is True


@pytest.mark.parametrize('button_count, dialog_count', [(0, 0), (2, 0), (1, 1)])
def test_link_button_or_existing_dialog_ambiguity_never_activates(settings, button_count, dialog_count):
    page = CatalogPage()
    page.button_count, page.dialog_count = button_count, dialog_count
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'blocked' and page.presses == 0


def test_dispatch_timeout_only_reads_dialog_and_never_represses(settings):
    page = CatalogPage()
    page.press_error = True
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and page.presses == 1


def test_unknown_submit_without_link_remains_blocked_on_new_call(settings):
    page = CatalogPage()
    page.short_links = []
    browser = Browser(page)
    result = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert result['state'] == 'blocked' and page.presses == 1
    second = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert second['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert page.presses == 1


def test_delayed_redirect_keeps_resolved_url_and_retries_only_reads(settings):
    page = CatalogPage()
    browser = Browser(page)
    browser.destinations = ['https://shopee.vn/opaanlp/252432728/2931643720?session=private']
    first = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert first['state'] == 'blocked' and page.presses == 1
    path = next((settings.data / 'affiliate').glob('*.json'))
    before = json.loads(path.read_text(encoding='utf-8'))
    assert before['resolved_url'] == 'https://s.shopee.vn/newexample'
    assert 'private' not in path.read_text(encoding='utf-8')
    browser.destinations = ['https://shopee.vn/opaanlp/252432728/2931643720?sid=private',
                            'https://shopee.vn/product/252432728/2931643720?session=private']
    second = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert second['state'] == 'verified' and page.presses == 1
    assert browser.link_visits == [before['resolved_url'], before['resolved_url']]
    after = json.loads(path.read_text(encoding='utf-8'))
    assert after['intent'] == before['intent'] and after['intent_sha256'] == before['intent_sha256']
    assert 'private' not in json.dumps(second) + path.read_text(encoding='utf-8')


def test_known_qualified_product_reuses_receipt_url_without_new_activation(settings):
    settings.data.mkdir(parents=True)
    url = 'https://s.shopee.vn/AKauRjeEWR'
    receipt = {'state': 'verified', 'shop_id': '252432728', 'product_id': '2931643720', 'url': url,
               'destination_review': {'url': DETAIL['product_links'][0]},
               'responses': [{'path': '/api/v3/gql', 'status': 200,
                              'fields': {'itemId': '2931643720', 'shopId': '252432728'}}]}
    (settings.data / 'affiliate-live-link-2931643720.json').write_text(json.dumps(receipt), encoding='utf-8')
    page = CatalogPage()
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and result['url'] == url and page.presses == 0


def test_provider_cannot_activate_without_durable_intent():
    page = CatalogPage()
    provider = ShopeeCatalogProvider(Browser(page), config=ShopeeProviderConfig())
    products = provider.enrich(provider.search(request()), request())
    with pytest.raises(ValueError, match='intent_required'):
        provider.resolve_links(products, 1)
    assert page.presses == 0


def test_card_commission_selection_does_not_depend_on_detail_reels_table(settings):
    lower = DETAIL['selected_card'].copy()
    lower['href'] = f"{CATALOG_URL}/2338530731"
    lower['text'] = lower['text'].replace('Tỉ lệ hoa hồng 12,5%', 'Tỉ lệ hoa hồng 5%')
    page = CatalogPage([lower, DETAIL['selected_card']])
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and result['candidate_count'] == 2
    assert result['product']['product_id'] == '2931643720' and page.presses == 1
    assert result['selection_evidence']['detail_count'] == 0
    assert result['selection_evidence']['excluded_details'] == []
    assert result['selection_evidence']['rate_basis'] == 'product_offer_card_display'


@pytest.mark.parametrize('guard, reason', [('Đăng nhập', 'shopee_affiliate_auth_required'),
                                         ('Security check CAPTCHA', 'shopee_security_challenge')])
def test_auth_or_captcha_blocks_discovery_without_activation(settings, guard, reason):
    page = CatalogPage()
    page.guard_text = guard
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'needs_input' and result['reason'] == reason
    assert page.presses == 0


def test_header_only_table_is_not_enough_wait_for_product_and_populated_rows(settings):
    class HydratingPage(CatalogPage):
        def goto(self, url, **kwargs):
            super().goto(url, **kwargs)
            self.product_links = []
            self.rows = [DETAIL['rows'][0]]

        def wait_for_function(self, script, **kwargs):
            assert kwargs['arg'] == '2931643720'
            self.product_links = DETAIL['product_links']
            self.rows = DETAIL['rows']
            super().wait_for_function(script, **kwargs)
    card = DETAIL['selected_card'].copy()
    card['text'] = card['text'].replace('Tỉ lệ hoa hồng 12,5%\n', '')
    page = HydratingPage([card])
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and page.waited_detail and page.presses == 1
    assert result['selection_evidence']['detail_count'] == 1
    assert result['selection_evidence']['rate_basis'] == 'minimum_other_social_and_facebook_reels_fallback'


@pytest.mark.parametrize('press_timeout', [False, True])
def test_link_checkpoint_is_durable_before_activation_and_keeps_public_url(settings, monkeypatch, press_timeout):
    page = CatalogPage()
    page.press_error = press_timeout
    original = Button.press
    def press(button, *args, **kwargs):
        receipt = json.loads(next((settings.data/'affiliate').glob('*.json')).read_text())
        assert receipt['link_stage'] == 'activation_intent'
        assert receipt['activation_state'] == 'intent'
        assert receipt['link_steps'] == ['link_navigation', 'link_readiness', 'link_card_match',
                                        'link_focus', 'activation_intent']
        return original(button, *args, **kwargs)
    monkeypatch.setattr(Button, 'press', press)
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and page.presses == 1
    receipt = json.loads(next((settings.data/'affiliate').glob('*.json')).read_text())
    assert receipt['activation_state'] == ('unknown_after_dispatch' if press_timeout else 'returned')
    assert receipt['link_steps'][-3:] == [
        'activation_uncertain' if press_timeout else 'activation_returned', 'link_observation', 'link_observed']
    assert receipt['resolved_url'] == 'https://s.shopee.vn/newexample'


def test_pre_activation_failure_records_phase_and_blocks_new_product_fallback(settings):
    class FailingPage(CatalogPage):
        def goto(self, *args, **kwargs):
            if self.visited:
                raise RuntimeError('Cookie: private-do-not-store')
            return super().goto(*args, **kwargs)
    page = FailingPage()
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['reason'] == 'affiliate_link_resolution_failed'
    assert result['phase'] == 'link_resolution' and result['link_stage'] == 'link_navigation'
    assert result['activation_state'] == 'not_started'
    receipt_path = next((settings.data/'affiliate').glob('*.json'))
    assert json.loads(receipt_path.read_text())['error_code'] == result['reason']
    changed = CatalogPage()
    changed.cards = [dict(DETAIL['selected_card'], href=CATALOG_URL+'/999')]
    again = affiliate.acquire_affiliate(settings, session_provider=Browser(changed))
    assert again['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert again['phase'] == 'intent_reconciliation'
    assert not changed.visited and page.presses == changed.presses == 0
    assert 'private-do-not-store' not in receipt_path.read_text() + json.dumps(result)


def test_observed_url_survives_failure_before_provider_returns_and_retry_only_reads(settings, monkeypatch):
    import agent.thoremix.catalog as catalog
    original = catalog.AffiliateLink
    def fail(**kwargs):
        receipt = json.loads(next((settings.data/'affiliate').glob('*.json')).read_text())
        assert receipt['resolved_url'] == kwargs['url']
        assert receipt['link_stage'] == 'link_observed'
        raise RuntimeError('private-model-failure')
    monkeypatch.setattr(catalog, 'AffiliateLink', fail)
    page = CatalogPage()
    browser = Browser(page)
    result = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert result['state'] == 'blocked' and page.presses == 1
    path = next((settings.data/'affiliate').glob('*.json'))
    before = json.loads(path.read_text())
    assert before['state'] == 'incomplete' and before['resolved_product_id'] == '2931643720'
    monkeypatch.setattr(catalog, 'AffiliateLink', original)
    retry = affiliate.acquire_affiliate(settings, session_provider=browser)
    assert retry['state'] == 'verified' and page.presses == 1
    after = json.loads(path.read_text())
    assert before['intent'] == after['intent'] and before['link_steps'] == after['link_steps']
    assert 'private-model-failure' not in path.read_text()


def test_uncertain_activation_history_is_retained_and_cannot_replay(settings):
    page = CatalogPage()
    page.short_links = []
    page.press_error = True
    first = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert first['reason'] == 'shopee_affiliate_link_unconfirmed'
    assert first['activation_state'] == 'unknown_after_dispatch'
    assert first['link_stage'] == 'link_observation'
    path = next((settings.data/'affiliate').glob('*.json'))
    before = path.read_bytes()
    second = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert second['reason'] == 'affiliate_link_incomplete_requires_reconciliation'
    assert path.read_bytes() == before and page.presses == 1
