"""Bounded native Shopee catalog, qualified against the 2026-09-27 live flow.

Uses the first visible catalog page, not an unobserved search/category selector.
Price, sold count, and the displayed Product Offer commission are read from cards.
Detail commission tables are a bounded fallback only when no eligible card exposes a rate.
The already-qualified URL is loaded from a local evidence receipt when present;
it never influences selection. No account body text or response headers escape.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from kabin_affiliate_toolkit.models import AffiliateLink, CommissionSnapshot, PriceSnapshot, ProductCandidate
from kabin_affiliate_toolkit.providers.errors import ProviderBlocked, ProviderNeedsInput

CATALOG_URL = 'https://affiliate.shopee.vn/offer/product_offer'
REELS = 'Reels trên Facebook/Instagram'
MAX_CARDS = 20
MAX_DETAILS = 12


def offer_identity(url):
    from .affiliate import _safe_url
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
        if (not _safe_url(canonical) or parsed.hostname != 'affiliate.shopee.vn' or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in url)):
            return None
        if parsed.query:
            # Observed live catalog offer links contain this analytics-only trace
            # object. It is neither a public affiliate URL nor needed to navigate
            # the canonical offer. No unknown source/affiliate fields are allowed.
            fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            if len(fields) != 1 or fields[0][0] != 'trace':
                return None
            trace = json.loads(fields[0][1])
            if (not isinstance(trace, dict) or set(trace) != {'trace_id', 'list_type', 'exp_group_ids',
                                                            'root_trace_id', 'root_list_type'}
                    or any(not isinstance(trace[k], str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,100}', trace[k])
                           for k in ('trace_id', 'root_trace_id'))
                    or any(type(trace[k]) is not int or trace[k] < 0 for k in ('list_type', 'root_list_type'))
                    or not isinstance(trace['exp_group_ids'], list) or len(trace['exp_group_ids']) > 100
                    or any(type(v) is not int or v < 0 for v in trace['exp_group_ids'])):
                return None
        match = re.fullmatch(r'/offer/product_offer/(\d+)/?', parsed.path)
        return match[1] if match else None
    except (ValueError, TypeError):
        return None


def parse_price(value):
    value = str(value).strip().removeprefix('₫').strip()
    if not re.fullmatch(r'(?:\d{1,3}(?:\.\d{3})+|\d+)', value):
        return None
    return int(value.replace('.', ''))


def parse_observed_sold(text):
    matches = list(re.finditer(r'(?<![\w.,])([\d]+(?:[.,]\d+)?)\s*([kKmM]?)\s*(\+?)\s+lượt bán', text))
    if len(matches) != 1:
        return None
    match = matches[0]
    number, suffix, plus = match[1], match[2].lower(), match[3]
    if not suffix and ('.' in number or ',' in number):
        return None  # unobserved grouping/decimal semantics, not an invented count
    multiplier = {'': 1, 'k': 1000, 'm': 1000000}[suffix]
    amount = Decimal(number.replace(',', '.')) * multiplier
    if amount != amount.to_integral_value():
        return None
    return {'sold': int(amount), 'is_lower_bound': bool(suffix or plus), 'display_text': match[0].strip()}


def parse_observed_commission(text):
    """Parse the single commission percentage printed on a Product Offer card.

    This is listing evidence only. It stays separate from the per-placement
    detail table so catalog-first selection can use what Shopee already exposes
    without upgrading the claim to cross-channel proof.
    """
    matches = list(re.finditer(
        r'(?<!\w)tỉ\s*lệ\s*hoa\s*hồng\s*(\d+(?:[.,]\d+)?)\s*%',
        str(text),
        re.IGNORECASE,
    ))
    if len(matches) != 1:
        return None
    rate = Decimal(matches[0][1].replace(',', '.')) / 100
    if not 0 <= rate <= 1:
        return None
    return {
        'effective_rate': float(rate),
        'display_text': matches[0][0].strip(),
    }


def parse_card(card, *, observed_at):
    item = offer_identity(card.get('href'))
    price = parse_price(card.get('price'))
    text = card.get('text', '')
    sold = parse_observed_sold(text)
    commission = parse_observed_commission(text)
    title = card.get('title')
    if not item or price is None or price <= 0 or sold is None or not isinstance(title, str) or not title.strip():
        return None
    canonical_offer = f'{CATALOG_URL}/{item}'
    metadata = {
        'offer_url': canonical_offer,
        'sold_evidence': sold | {'source': CATALOG_URL, 'observed_at': observed_at.isoformat()},
    }
    if commission is not None:
        metadata['catalog_commission'] = commission | {
            'source': CATALOG_URL,
            'observed_at': observed_at.isoformat(),
        }
    return ProductCandidate(product_id=item, title=title.strip(), product_url=canonical_offer,
                            price=PriceSnapshot(current=price, source=CATALOG_URL, observed_at=observed_at),
                            sold=sold['sold'], metadata=metadata)


def _component(cell):
    match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)%\s*\(₫[\d.]+\)\s*', cell)
    if not match:
        raise ValueError('commission_component_unknown')
    rate = Decimal(match[1].replace(',', '.')) / 100
    if not 0 <= rate <= 1:
        raise ValueError('commission_component_invalid')
    return rate


def channel_rates(rows):
    """Parse exactly two component cells; the final money column is not a rate."""
    if not rows or rows[0] != ['Loại kênh', 'Loại nội dung', '', 'Hoa hồng từ Shopee', 'Hoa hồng ước tính']:
        raise ValueError('commission_header_changed')
    other = [row for row in rows[1:] if len(row) == 5
             and row[0].splitlines()[0].strip() == 'Mạng xã hội' and row[1].strip() == 'Nội dung khác']
    reels = [row for row in rows[1:] if len(row) == 4 and row[0].strip() == REELS]
    if len(other) != 1 or len(reels) != 1:
        raise ValueError('commission_placement_ambiguous')
    result = {}
    for placement, cells in (('other_social', other[0][2:]), ('facebook_reels', reels[0][1:])):
        if parse_price(cells[-1]) is None:
            raise ValueError('commission_total_column_unknown')
        first, second = _component(cells[0]), _component(cells[1])
        total = first + second
        if total > 1:
            raise ValueError('commission_total_invalid')
        result[placement] = {'component_rates': [float(first), float(second)], 'effective_rate': float(total)}
    return result


def product_identity(links, item):
    from .affiliate import _identity
    identities = {_identity(url) for url in links if isinstance(url, str)} - {None}
    if len(identities) != 1 or next(iter(identities))[1] != item:
        raise ValueError('catalog_product_identity_ambiguous')
    return next(iter(identities))


def qualified_existing_links(directory):
    """Project only previously verified identity/link evidence; never portal text."""
    from .affiliate import _identity, _safe_url
    result = {}
    if directory is None:
        return result
    for path in sorted(Path(directory).glob('affiliate-live-link-*.json')):
        try:
            receipt = json.loads(path.read_text(encoding='utf-8-sig'))
            identity = (receipt['shop_id'], receipt['product_id'])
            url = receipt['url']
            final = receipt.get('destination_review', {}).get('url')
            responses = receipt.get('responses', [])
            response_match = any(row.get('path') == '/api/v3/gql' and row.get('status') == 200
                                 and row.get('fields') == {'itemId': identity[1], 'shopId': identity[0]}
                                 for row in responses)
            if (receipt.get('state') == 'verified' and _identity(final) == identity
                    and _safe_url(url, affiliate=True) and response_match):
                if identity in result and result[identity] != url:
                    raise ValueError('conflicting_qualified_links')
                result[identity] = url
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
    return result


class ShopeeCatalogProvider:
    name = 'shopee_vn'
    discovery_scope = 'authenticated_catalog_first_20_visible_cards'

    def __init__(self, browser, *, config, receipt_directory=None):
        self.browser, self.config = browser, config
        self.known_links = qualified_existing_links(receipt_directory)
        self._products = None
        self._enriched = False
        self._intent = None
        self._activation_attempted = False
        self.observed_count = 0
        self.detail_count = 0
        self.detail_failures = []
        self.detail_stage = 'detail_navigation'

    @staticmethod
    def _page(context):
        return context.pages[0] if context.pages else context.new_page()

    @staticmethod
    def _guard(page):
        url = str(page.url).casefold()
        text = page.locator('body').inner_text(timeout=5000).casefold()
        if any(marker in text for marker in ('captcha', 'xác minh', 'security check', 'verify you are human')):
            raise ProviderNeedsInput('shopee_security_challenge', 'Shopee yêu cầu xác minh trong phiên Affiliate.')
        if 'login' in url or 'signin' in url or 'đăng nhập' in text[:1500]:
            raise ProviderNeedsInput('shopee_affiliate_auth_required', 'Cần đăng nhập phiên Shopee Affiliate đã chọn.')

    def search(self, request):
        if self._products is not None:
            return self._products
        with self.browser.session() as context:
            page = self._page(context)
            page.goto(CATALOG_URL, wait_until='domcontentloaded', timeout=60000)
            try:
                page.locator('.AffiliateItemCard').first.wait_for(state='visible', timeout=25000)
            finally:
                self._guard(page)
            limit = min(MAX_CARDS, self.config.search_candidate_limit)
            cards = page.locator('.AffiliateItemCard').evaluate_all('''nodes => nodes.slice(0, 20).map(n => ({
                text: n.innerText, title: n.querySelector('.ItemCard__name')?.innerText,
                price: n.querySelector('.price')?.innerText, href: n.querySelector('a')?.href
            }))''')[:limit]
            self.observed_count = len(cards)
            now = datetime.now(timezone.utc)
            products = {}
            for card in cards:
                product = parse_card(card, observed_at=now)
                if product is not None:
                    products[product.product_id] = product
            self._products = list(products.values())
            return self._products

    def _detail(self, page, product):
        offer = product.metadata['offer_url']
        if offer_identity(offer) != product.product_id:
            raise ValueError('catalog_offer_identity_mismatch')
        self.detail_stage = 'detail_navigation'
        try:
            page.goto(offer, wait_until='domcontentloaded', timeout=60000)
            self.detail_stage = 'detail_readiness'
            # Header-only tables appear before the product fetch completes.
            # Require the exact item's canonical anchor AND all observed baseline
            # channel rows populated. Only then can absent Reels be classified.
            page.wait_for_function(r'''item => {
                const product = [...document.querySelectorAll('a[href]')].some(a => {
                    try {const u=new URL(a.href), m=u.pathname.match(/^\/product\/(\d+)\/(\d+)\/?$/);
                        return u.protocol==='https:' && ['shopee.vn','www.shopee.vn'].includes(u.hostname)
                            && !u.username && !u.password && m && m[2]===item;
                    } catch (_) {return false;}
                });
                const rows=[...document.querySelectorAll('tr')].map(n=>[...n.querySelectorAll('td,th')].map(c=>c.innerText.trim()));
                const loaded=label=>rows.some(r=>r.length>=4 && r[0].split('\n')[0]===label
                    && r.slice(1,-1).some(c=>c.includes('%')) && /^₫[\d.,]+$/.test(r[r.length-1]));
                return product && loaded('Mạng xã hội') && loaded('Shopee Live') && loaded('Shopee Video');
            }''', arg=product.product_id, timeout=20000)
        except Exception:
            self._guard(page)
            raise ProviderBlocked('catalog_detail_unavailable', 'Trang chi tiết chưa có bảng hoa hồng đọc được.') from None
        self._guard(page)
        self.detail_stage = 'product_identity'
        links = page.locator('a[href]').evaluate_all('nodes => nodes.map(n => n.href)')
        identity = product_identity(links, product.product_id)
        self.detail_stage = 'commission_table'
        rows = page.locator('tr').evaluate_all("nodes => nodes.map(n => [...n.querySelectorAll('td,th')].map(c => c.innerText))")
        try:
            rates = channel_rates(rows)
        except ValueError:
            raise ProviderBlocked('catalog_cross_channel_commission_unavailable',
                                  'Thiếu hoa hồng xác minh cho cả Mạng xã hội và Reels Facebook/Instagram.') from None
        return identity, rates

    def enrich(self, products, request):
        if self._enriched:
            return products
        cap = request.selection.price_max
        minimum = request.context.get('affiliate_min_sold')
        if cap is None or type(minimum) is not int:
            raise ValueError('catalog_selection_bounds_required')
        eligible = [p for p in products if p.price.current is not None and 0 < p.price.current <= cap
                    and p.sold is not None and p.sold >= minimum]

        catalog_rate_count = 0
        for product in eligible:
            evidence = product.metadata.get('catalog_commission')
            if not isinstance(evidence, dict):
                continue
            rate = evidence.get('effective_rate')
            observed_at = evidence.get('observed_at')
            source = evidence.get('source')
            try:
                observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
            except (AttributeError, TypeError, ValueError):
                continue
            if (type(rate) not in (int, float) or not 0 < rate <= 1
                    or source != CATALOG_URL or observed.tzinfo is None):
                continue
            product.commission = CommissionSnapshot(
                effective_rate=rate,
                verified=True,
                source=CATALOG_URL,
                observed_at=observed,
            )
            product.metadata['commission_basis'] = 'product_offer_card_display'
            catalog_rate_count += 1
            matches = [(identity, url) for identity, url in self.known_links.items()
                       if identity[1] == product.product_id]
            if len(matches) == 1:
                identity, url = matches[0]
                product.shop_id = identity[0]
                product.product_url = f'https://shopee.vn/product/{identity[0]}/{identity[1]}'
                product.affiliate = AffiliateLink(url=url, status='verified')

        # Normal runtime is detail-zero. The old table path remains only as a
        # bounded fallback if the Product Offer listing yields no usable rate at all.
        if eligible and catalog_rate_count == 0:
            with self.browser.session() as context:
                page = self._page(context)
                for product in eligible[:min(MAX_DETAILS, self.config.enrich_limit)]:
                    self.detail_count += 1
                    try:
                        identity, rates = self._detail(page, product)
                    except ProviderBlocked as exc:
                        if exc.code not in {'catalog_cross_channel_commission_unavailable', 'catalog_detail_unavailable'}:
                            raise
                        product.metadata['detail_state'] = 'unverified'
                        self.detail_failures.append({'product_id': product.product_id, 'reason': exc.code,
                                                     'stage': self.detail_stage})
                        continue
                    except ValueError:
                        product.metadata['detail_state'] = 'unverified'
                        self.detail_failures.append({'product_id': product.product_id,
                                                    'reason': 'catalog_identity_or_commission_unverified',
                                                    'stage': self.detail_stage})
                        continue
                    product.shop_id = identity[0]
                    product.product_url = f'https://shopee.vn/product/{identity[0]}/{identity[1]}'
                    rate = min(value['effective_rate'] for value in rates.values())
                    product.commission = CommissionSnapshot(effective_rate=rate, verified=True,
                        source=product.metadata['offer_url'], observed_at=datetime.now(timezone.utc))
                    product.metadata['placement_rates'] = rates
                    product.metadata['commission_basis'] = 'minimum_other_social_and_facebook_reels_fallback'
                    if identity in self.known_links:
                        product.affiliate = AffiliateLink(url=self.known_links[identity], status='verified')

        basis = ('product_offer_card_display' if catalog_rate_count
                 else 'minimum_other_social_and_facebook_reels_fallback')
        for product in products:
            product.metadata['selection_evidence'] = {'scope': self.discovery_scope,
                'observed_card_count': self.observed_count, 'detail_count': self.detail_count,
                'excluded_details': self.detail_failures.copy(), 'rate_basis': basis}
        self._enriched = True
        return products

    def bind_link_intent(self, path, expected_hash):
        self._intent = (Path(path), expected_hash)

    def _require_intent(self, product):
        from .affiliate import _intent_hash
        if self._intent is None:
            raise ValueError('catalog_link_intent_required')
        path, expected_hash = self._intent
        receipt = json.loads(path.read_text(encoding='utf-8'))
        intent = receipt.get('intent', {})
        catalog_offer = product.metadata.get('offer_url')
        if (receipt.get('state') != 'intent' or receipt.get('intent_sha256') != expected_hash
                or _intent_hash(intent) != expected_hash or intent.get('effect') != 'resolve_link'
                or (intent.get('shop_id'), intent.get('product_id')) != (product.shop_id, product.product_id)
                or intent.get('catalog_offer') != catalog_offer
                or offer_identity(catalog_offer) != product.product_id):
            raise ValueError('catalog_link_intent_invalid')

    @staticmethod
    def _visible_short_links(page):
        return page.evaluate(r'''() => {
            const visible = n => {const r=n.getBoundingClientRect(), s=getComputedStyle(n);
                return r.width>0 && r.height>0 && s.visibility!=='hidden' && s.display!=='none'};
            return [...new Set([...document.querySelectorAll('[role="dialog"],.ant-modal')]
                .filter(visible).flatMap(n=>[...n.querySelectorAll('input,textarea')])
                .filter(visible).map(n=>(n.value||'').trim())
                .filter(v=>/^https:\/\/s\.shopee\.vn\/[A-Za-z0-9._~-]+$/.test(v)))];
        }''')


    def _matching_catalog_card(self, page, product):
        cards = page.locator('.AffiliateItemCard')
        snapshots = cards.evaluate_all("""nodes => nodes.map(n => ({
            text: n.innerText,
            title: n.querySelector('.ItemCard__name')?.innerText,
            price: n.querySelector('.price')?.innerText,
            href: n.querySelector('a')?.href
        }))""")
        matches = [(index, raw) for index, raw in enumerate(snapshots)
                   if offer_identity(raw.get('href')) == product.product_id]
        if len(matches) != 1:
            raise ValueError('catalog_product_card_ambiguous')
        index, raw = matches[0]
        observed = parse_card(raw, observed_at=datetime.now(timezone.utc))
        if observed is None or observed.product_id != product.product_id:
            raise ValueError('catalog_product_card_unreadable')
        expected = product.metadata.get('catalog_commission', {}).get('effective_rate')
        actual = observed.metadata.get('catalog_commission', {}).get('effective_rate')
        if (observed.title != product.title or observed.price.current != product.price.current
                or observed.sold != product.sold or expected != actual):
            raise ValueError('catalog_link_evidence_changed')
        return cards.nth(index)

    def resolve_links(self, products, limit):
        if self._activation_attempted:
            raise ValueError('catalog_link_activation_already_attempted')
        if limit != 1 or len(products) != 1:
            raise ValueError('catalog_one_link_only')
        product = products[0]
        self._require_intent(product)
        with self.browser.session() as context:
            page = self._page(context)
            page.goto(CATALOG_URL, wait_until='domcontentloaded', timeout=60000)
            try:
                page.locator('.AffiliateItemCard').first.wait_for(state='visible', timeout=25000)
            finally:
                self._guard(page)
            card = self._matching_catalog_card(page, product)
            if page.locator('[role="dialog"]:visible,.ant-modal:visible').count():
                raise ValueError('catalog_existing_dialog_requires_reconciliation')
            button = card.get_by_role('button', name='Lấy link', exact=True)
            if button.count() != 1:
                raise ValueError('catalog_link_button_ambiguous')
            button.focus(timeout=5000)
            if not button.evaluate('n => document.activeElement === n'):
                raise ValueError('catalog_link_button_focus_unverified')
            # One activation only; after dispatch, read/reconcile but never press again.
            self._activation_attempted = True
            try:
                button.press('Enter', timeout=5000)
            except Exception:
                pass
            for _ in range(12):
                self._guard(page)
                urls = self._visible_short_links(page)
                if len(urls) == 1:
                    product.affiliate = AffiliateLink(url=urls[0], status='resolved',
                                                     observed_at=datetime.now(timezone.utc))
                    return products
                if len(urls) > 1:
                    break
                page.wait_for_timeout(500)
        raise ProviderBlocked('shopee_affiliate_link_unconfirmed', 'Chưa đọc được một link; cần đối soát, không tạo lại.')

