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
                                   parse_card, parse_observed_sold, parse_price, product_identity)
from agent.thoremix.config import Settings


FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures'
CARDS = json.loads((FIXTURES / 'thoremix_shopee_cards.json').read_text(encoding='utf-8'))['cards']
DETAIL = json.loads((FIXTURES / 'thoremix_shopee_detail.json').read_text(encoding='utf-8'))
NOW = datetime.now(timezone.utc)


@pytest.mark.parametrize('raw, expected', [('₫120.000', 120000), ('225.000', 225000), ('4.398.999', 4398999),
                                          ('12,5', None), ('--', None), ('0', 0)])
def test_observed_price_forms(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize('raw, amount, lower', [('10k+ lượt bán', 10000, True), ('600k+ lượt bán', 600000, True),
                                              ('155 lượt bán', 155, False), ('1,5k+ lượt bán', 1500, True)])
def test_observed_sold_is_explicit_lower_bound(raw, amount, lower):
    parsed = parse_observed_sold(raw)
    assert parsed['sold'] == amount and parsed['is_lower_bound'] is lower
    assert parsed['display_text'] == raw


def test_unknown_and_ambiguous_sold_are_not_zero():
    assert parse_observed_sold('Sản phẩm mới') is None
    assert parse_observed_sold('10 lượt bán 100 lượt bán') is None


def test_live_card_fixture_projects_source_and_lower_bound():
    p = parse_card(DETAIL['selected_card'], observed_at=NOW)
    assert p.product_id == '2931643720' and p.price.current == 120000
    assert p.sold == 10000 and p.metadata['sold_evidence']['is_lower_bound']
    assert p.metadata['sold_evidence']['source'] == CATALOG_URL
    assert not p.commission.verified  # headline percentage is not channel proof


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
    def __init__(self, page, selector):
        self.page, self.selector = page, selector
        self.first = self

    def wait_for(self, **kwargs):
        if self.selector == '.AffiliateItemCard':
            self.page.waited_cards = True

    def inner_text(self, **kwargs):
        return self.page.guard_text

    def count(self):
        return self.page.dialog_count if 'dialog' in self.selector else 1

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
    return ProductRecommendRequest(query='gia dụng', selection={'price_max': 200000},
                                    context={'affiliate_min_sold': 1000})


def test_prefilter_before_bounded_detail_reads_and_cache_across_queries():
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
    assert detailed == ['7988383802', '2931643720']
    assert len(page.visited) == 1 and provider.detail_count == 2
    assert sum(p.commission.verified for p in enriched) == 2


def test_default_is_qualified_catalog_with_one_activation_and_lower_bound_comment(settings):
    page = CatalogPage()
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified'
    assert result['product']['commission']['effective_rate'] == .125
    assert result['product']['commission']['placement_rates']['facebook_reels']['effective_rate'] == .15
    assert 'ít nhất 10000' in result['comment']
    assert result['selection_evidence']['detail_count'] == 1
    assert result['candidate_count'] == 1 and page.presses == 1
    receipt = json.loads(next((settings.data / 'affiliate').glob('*.json')).read_text(encoding='utf-8'))
    assert receipt['resolved_url'] == result['url']
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


def test_missing_reels_row_excludes_only_that_product_and_freezes_safe_reason(settings):
    missing = json.loads((FIXTURES / 'thoremix_shopee_missing_reels.json').read_text(encoding='utf-8'))
    bad = DETAIL['selected_card'] | {'href': f"{CATALOG_URL}/{missing['product_id']}"}
    class MixedPage(CatalogPage):
        def goto(self, url, **kwargs):
            super().goto(url, **kwargs)
            unsupported = url.endswith('/' + missing['product_id'])
            self.rows = missing['rows'] if unsupported else DETAIL['rows']
            self.product_links = [f"https://shopee.vn/product/252432728/{missing['product_id']}"] if unsupported else DETAIL['product_links']
    page = MixedPage([bad, DETAIL['selected_card']])
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and result['candidate_count'] == 2
    assert result['product']['product_id'] == '2931643720' and page.presses == 1
    expected = [{'product_id': '2338530731', 'reason': 'catalog_cross_channel_commission_unavailable',
                 'stage': 'commission_table'}]
    assert result['selection_evidence']['excluded_details'] == expected
    receipt = json.loads(next((settings.data / 'affiliate').glob('*.json')).read_text(encoding='utf-8'))
    assert receipt['intent']['catalog_selection']['excluded_details'] == expected


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
    page = HydratingPage()
    result = affiliate.acquire_affiliate(settings, session_provider=Browser(page))
    assert result['state'] == 'verified' and page.waited_detail and page.presses == 1
