"""Deterministic KAT boundary; provider evidence is data, never public diagnostics.

Injected providers use KAT's search/enrich/resolve_links interface and must supply
metadata.sold_evidence = {source, observed_at, sold}. Rates are fractions (0.1 is
10%), as in KAT. A missing effective rate can use a verified base only when xtra
is explicitly zero. Injected session owners must hold their exclusive lease for
the entire session; the production default uses KAT's profile lease.
Native KAT synthetic totals require both components. Custom providers may expose
an independently observed effective total without inventing its components.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

from .config import atomic_json


DISCLOSURE = 'Đây là liên kết tiếp thị liên kết; mình có thể nhận hoa hồng khi bạn mua qua link.'
_HOSTS = {'shopee.vn', 'www.shopee.vn', 'affiliate.shopee.vn', 's.shopee.vn', 'shope.ee'}
_SECRET = re.compile(r'password|passwd|cookie|authorization|bearer|secret|access.?token|refresh.?token|session.?id', re.I)


def _stop(reason, *, state='needs_input', candidate_count=0):
    return {'state': state, 'reason': reason, 'candidate_count': candidate_count}


def _safe_url(value, *, affiliate=False):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname not in _HOSTS
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or '\\' in value or parsed.fragment):
            return False
        decoded = unquote(value)
        if _SECRET.search(decoded):
            return False
        if parsed.query:
            # KAT shopee.py constructs /search?keyword=... for source evidence.
            # Its README/test_commenting.py only demonstrate query-free short
            # affiliate URLs. No public affiliate query key is yet supported.
            fields = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            return (not affiliate and parsed.hostname in {'shopee.vn', 'www.shopee.vn'}
                    and parsed.path == '/search' and len(fields) == 1
                    and fields[0][0] == 'keyword' and bool(fields[0][1]))
        return True
    except ValueError:
        return False


def _identity(url):
    from kabin_affiliate_toolkit.providers.shopee_parsing import parse_identity
    if not _safe_url(url) or urlsplit(url).hostname not in {'shopee.vn', 'www.shopee.vn'}:
        return None
    parsed = parse_identity(url)
    return (parsed.shop_id, parsed.product_id) if parsed else None


def _fresh(value, now):
    try:
        observed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        return observed.tzinfo is not None and 0 <= (now - observed).total_seconds() <= 21600
    except (TypeError, ValueError, AttributeError):
        return False


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _eligibility(product, settings, now, *, native=False):
    """Return a rate and a stable safe reason; never turn unknown into zero."""
    if product.provider != 'shopee_vn':
        return None, 'product_identity_unverified'
    catalog_basis = product.metadata.get('commission_basis') == 'product_offer_card_display'
    if catalog_basis:
        from .catalog import offer_identity
        offer = product.metadata.get('offer_url')
        if offer_identity(offer) != product.product_id:
            return None, 'product_identity_unverified'
        if product.shop_id:
            if _identity(product.product_url) != (product.shop_id, product.product_id):
                return None, 'product_identity_unverified'
        elif product.product_url != offer:
            return None, 'product_identity_unverified'
    elif (not product.shop_id
          or _identity(product.product_url) != (product.shop_id, product.product_id)):
        return None, 'product_identity_unverified'
    price = product.price
    if (price.currency != 'VND' or not _number(price.current) or price.current <= 0
            or not _safe_url(price.source)):
        return None, 'price_evidence_missing'
    if not _fresh(price.observed_at, now):
        return None, 'price_evidence_stale'
    if price.current > settings.affiliate_max_price:
        return None, 'price_above_limit'
    commission = product.commission
    if not commission.verified or not _safe_url(commission.source):
        return None, 'commission_unverified'
    if not _fresh(commission.observed_at, now):
        return None, 'commission_evidence_stale'
    rate = commission.effective_rate
    if native:
        # KAT currently calculates (base or 0) + (xtra or 0). Its non-None
        # effective_rate is therefore not proof both components were observed.
        if not all(_number(v) and v >= 0 for v in (commission.base_rate, commission.xtra_rate)):
            return None, 'native_commission_components_unknown'
        if rate is not None and not math.isclose(rate, commission.base_rate + commission.xtra_rate):
            return None, 'native_commission_total_inconsistent'
    if rate is None and commission.xtra_rate == 0:
        rate = commission.base_rate
    if not _number(rate) or not 0 < rate <= 1:
        return None, 'commission_percentage_unknown_or_zero'
    sold = product.sold
    evidence = product.metadata.get('sold_evidence')
    if (type(sold) is not int or not isinstance(evidence, dict)
            or type(evidence.get('sold')) is not int or evidence['sold'] != sold
            or not _safe_url(evidence.get('source'))):
        return None, 'observed_sold_evidence_missing'
    if not _fresh(evidence.get('observed_at'), now):
        return None, 'observed_sold_evidence_stale'
    if sold < settings.affiliate_min_sold:
        return None, 'observed_sold_below_limit'
    title = product.title
    if (not title.strip() or len(title) > 500 or _SECRET.search(title)
            or '://' in title or any(ord(c) < 32 for c in title)):
        return None, 'product_title_invalid'
    return rate, None


class _SharedSession:
    def __init__(self, context):
        self.context = context

    def session(self, **kwargs):
        return nullcontext(self.context)


def _native_sold_evidence(products, now):
    # The native search parser derives sold from this exact anchor. Stamp only
    # search results; a later detail enrichment cannot refresh old sold evidence.
    for product in products:
        evidence = product.metadata.get('evidence', {})
        if (product.sold is not None and evidence.get('surface') == 'shopee_search'
                and type(evidence.get('anchor_index')) is int and _safe_url(evidence.get('url'))):
            product.metadata['sold_evidence'] = {
                'source': evidence['url'], 'observed_at': now.isoformat(),
                'sold': product.sold, 'anchor_index': evidence['anchor_index'],
            }


def _destination_identity(context, url, expected):
    """Return the browser-observed Shopee identity, allowing unknown shop pre-link."""
    if not _safe_url(url, affiliate=True) or urlsplit(url).hostname == 'affiliate.shopee.vn':
        return None
    expected_shop, expected_product = expected
    page = context.new_page()
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        for attempt in range(13):
            parsed = urlsplit(page.url)
            if (parsed.scheme != 'https' or parsed.hostname not in {'shopee.vn', 'www.shopee.vn'}
                    or parsed.username is not None or parsed.password is not None
                    or parsed.port not in (None, 443) or '\\' in page.url):
                return None
            canonical = urlunsplit(('https', parsed.hostname, parsed.path, '', ''))
            identity = _identity(canonical)
            if identity is not None:
                if identity[1] != expected_product:
                    return None
                if expected_shop is not None and identity[0] != expected_shop:
                    return None
                return identity
            intermediate = re.fullmatch(r'/opaanlp/(\d+)/(\d+)/?', parsed.path)
            if (not intermediate or intermediate[2] != expected_product
                    or (expected_shop is not None and intermediate[1] != expected_shop)
                    or attempt == 12):
                return None
            page.wait_for_timeout(500)
        return None
    finally:
        page.close()


def _verified_destination(context, url, expected):
    return _destination_identity(context, url, expected) is not None


def _receipt_path(settings, profile, identity):
    key = hashlib.sha256(json.dumps([str(profile), *identity], separators=(',', ':')).encode()).hexdigest()
    return settings.data / 'affiliate' / (key + '.json')


def _intent_hash(intent):
    return hashlib.sha256(json.dumps(intent, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _canonical_source(url):
    identity = _identity(url)
    if identity:
        return f'https://shopee.vn/product/{identity[0]}/{identity[1]}'
    parsed = urlsplit(url)
    return urlunsplit(('https', parsed.hostname, parsed.path or '/', '', ''))


def _new_receipt(product, rate, now, *, effect, existing_url=None):
    intent = {'shop_id': product.shop_id, 'product_id': product.product_id,
              'commission_rate': rate, 'price': product.price.current, 'sold': product.sold,
              'sold_is_lower_bound': product.metadata['sold_evidence'].get('is_lower_bound') is True,
              'price_observed_at': product.price.observed_at.isoformat(),
              'commission_observed_at': product.commission.observed_at.isoformat(),
              'sold_observed_at': str(product.metadata['sold_evidence']['observed_at']),
              'price_source': _canonical_source(product.price.source),
              'commission_source': _canonical_source(product.commission.source),
              'sold_source': _canonical_source(product.metadata['sold_evidence']['source']),
              'effect': effect, 'created_at': now.isoformat()}
    selection = _catalog_selection_evidence(product)
    if selection is not None:
        intent['catalog_selection'] = selection
        if product.metadata.get('commission_basis') == 'product_offer_card_display':
            offer = product.metadata.get('offer_url')
            from .catalog import offer_identity
            if offer_identity(offer) != product.product_id:
                raise ValueError('invalid catalog offer')
            intent['catalog_offer'] = _canonical_source(offer)
    if effect == 'verify_existing_link':
        if not _safe_url(existing_url, affiliate=True):
            raise ValueError('invalid existing link')
        intent['existing_url'] = existing_url
    return {'schema_version': 2, 'state': 'intent', 'intent': intent,
            'intent_sha256': _intent_hash(intent)}


def _catalog_selection_evidence(product):
    selection = product.metadata.get('selection_evidence', {})
    if selection.get('scope') != 'authenticated_catalog_first_20_visible_cards':
        return None
    if any(type(selection.get(key)) is not int or not 0 <= selection[key] <= 20
           for key in ('observed_card_count', 'detail_count')):
        raise ValueError('invalid catalog selection evidence')
    exclusions = selection.get('excluded_details', [])
    allowed = {'catalog_cross_channel_commission_unavailable', 'catalog_detail_unavailable',
               'catalog_identity_or_commission_unverified'}
    if not isinstance(exclusions, list) or len(exclusions) > 12:
        raise ValueError('invalid catalog exclusions')
    safe = []
    for entry in exclusions:
        if (not isinstance(entry, dict) or not isinstance(entry.get('product_id'), str)
                or not entry['product_id'].isdigit() or entry.get('reason') not in allowed):
            raise ValueError('invalid catalog exclusion')
        item = {'product_id': entry['product_id'], 'reason': entry['reason']}
        if 'stage' in entry:
            if entry['stage'] not in {'detail_navigation', 'detail_readiness', 'product_identity', 'commission_table'}:
                raise ValueError('invalid catalog exclusion stage')
            item['stage'] = entry['stage']
        safe.append(item)
    basis = selection.get('rate_basis')
    if basis not in {'product_offer_card_display', 'minimum_other_social_and_facebook_reels_fallback'}:
        raise ValueError('invalid catalog rate basis')
    return {key: selection[key] for key in ('scope', 'observed_card_count', 'detail_count')} | {
        'rate_basis': basis, 'excluded_details': safe}


def _pack(product, rate, url, count):
    price = product.price.current
    # Explicit projection: metadata, provider warnings, cookies, and diagnostics
    # must never escape the browser/provider boundary.
    safe_product = {
        'provider': 'shopee_vn', 'shop_id': product.shop_id, 'product_id': product.product_id,
        'title': product.title, 'product_url': _canonical_source(product.product_url), 'sold': product.sold,
        'price': {'current': price, 'currency': 'VND', 'source': _canonical_source(product.price.source),
                  'observed_at': product.price.observed_at.isoformat()},
        'commission': {'effective_rate': rate, 'verified': True, 'source': _canonical_source(product.commission.source),
                       'observed_at': product.commission.observed_at.isoformat()},
        'sold_evidence': {key: product.metadata['sold_evidence'][key]
                          for key in ('source', 'sold', 'observed_at')},
    }
    safe_product['sold_evidence']['source'] = _canonical_source(safe_product['sold_evidence']['source'])
    observed = safe_product['sold_evidence']['observed_at']
    if isinstance(observed, datetime):
        safe_product['sold_evidence']['observed_at'] = observed.isoformat()
    price_text = f'{price:,.0f}'.replace(',', '.')
    lower_bound = product.metadata['sold_evidence'].get('is_lower_bound') is True
    safe_product['sold_evidence']['is_lower_bound'] = lower_bound
    basis = product.metadata.get('commission_basis')
    if basis in {'product_offer_card_display', 'minimum_other_social_and_facebook_reels_fallback'}:
        safe_product['commission']['basis'] = basis
    placements = product.metadata.get('placement_rates')
    if isinstance(placements, dict) and set(placements) == {'other_social', 'facebook_reels'}:
        safe_rates = {}
        for name, value in placements.items():
            components = value.get('component_rates')
            effective = value.get('effective_rate')
            if (not isinstance(components, list) or len(components) != 2
                    or any(not _number(v) or not 0 <= v <= 1 for v in components)
                    or not _number(effective) or not math.isclose(effective, sum(components))):
                raise ValueError('invalid placement projection')
            safe_rates[name] = {'component_rates': components, 'effective_rate': effective}
        safe_product['commission']['placement_rates'] = safe_rates
    sold_text = ('ít nhất ' if lower_bound else '') + str(product.sold)
    comment = (f'Bạn có thể tham khảo {product.title}. Giá ghi nhận: {price_text} đ; '
               f'lượt bán ghi nhận: {sold_text}. Giá có thể thay đổi.\n{url}')
    result = {'state': 'verified', 'url': url, 'disclosure': DISCLOSURE, 'comment': comment,
            'product': safe_product, 'candidate_count': count,
            'selection': 'highest_verified_commission_percentage_then_low_price_then_observed_sold'}
    selection = _catalog_selection_evidence(product)
    if selection is not None:
        result['selection_evidence'] = selection
    return result


def acquire_affiliate(settings, *, session_provider=None, provider_factory=None) -> dict:
    """Acquire once; an incomplete link intent requires reconciliation, not retry.

    No network, browser, or third-party SDK is imported at module import time.
    The default catalog's link flow has live qualification. Stock KAT buyer-search
    remains gated. Local intent is always durable before a mutation, and a received
    safe URL is saved before destination checks so recovery can remain read-only.
    """
    count = 0
    receipt_path = None
    receipt = None
    phase = 'configuration'
    try:
        raw_profile = settings.affiliate_profile_dir
        if not raw_profile or not Path(raw_profile).is_absolute() or not Path(raw_profile).is_dir():
            return _stop('configured_existing_affiliate_profile_required')
        profile = Path(raw_profile).resolve()
        queries = settings.affiliate_queries
        if (not isinstance(queries, (tuple, list)) or not queries
                or any(not isinstance(q, str) or not q.strip() for q in queries)
                or not _number(settings.affiliate_max_price) or settings.affiliate_max_price <= 0
                or type(settings.affiliate_min_sold) is not int or settings.affiliate_min_sold < 1):
            return _stop('affiliate_selection_settings_invalid')
        from kabin_affiliate_toolkit.browser import BrowserRuntimeConfig, OwnedCamoufoxSessionProvider
        from kabin_affiliate_toolkit.models import ProductRecommendRequest
        from kabin_affiliate_toolkit.providers.shopee import ShopeeProviderConfig, ShopeeVNProvider
        from .catalog import ShopeeCatalogProvider

        owner = session_provider if session_provider is not None else OwnedCamoufoxSessionProvider(
            BrowserRuntimeConfig(profile_dir=profile, visible=False, lock_profile=True))
        phase = 'session'
        with owner.session() as context:
            phase = 'discovery'
            if provider_factory is None:
                provider = ShopeeCatalogProvider(_SharedSession(context), config=ShopeeProviderConfig(),
                                                 receipt_directory=settings.data)
            else:
                provider = provider_factory(_SharedSession(context), config=ShopeeProviderConfig())
            native = isinstance(ShopeeVNProvider, type) and isinstance(provider, ShopeeVNProvider)
            candidates = {}
            for query in queries:
                request = ProductRecommendRequest(query=query, selection={'top_k': 100, 'resolve_links': 0,
                                                                          'price_max': settings.affiliate_max_price},
                                                  context={'affiliate_min_sold': settings.affiliate_min_sold},
                                                  caller={'harness': 'thoremix'})
                products = provider.search(request)
                if native:
                    _native_sold_evidence(products, datetime.now(timezone.utc))
                products = provider.enrich(products, request)
                for product in products:
                    candidates[(product.shop_id, product.product_id)] = product
            count = len(candidates)
            eligible, reasons = [], set()
            now = datetime.now(timezone.utc)
            for product in candidates.values():
                rate, reason = _eligibility(product, settings, now, native=native)
                if reason:
                    reasons.add(reason)
                else:
                    eligible.append((product, rate))
            if not eligible:
                result = _stop('no_eligible_observed_product', candidate_count=count)
                result['missing_evidence'] = sorted(reasons) or ['no_candidates']
                if candidates:
                    selection = _catalog_selection_evidence(next(iter(candidates.values())))
                    if selection is not None:
                        result['selection_evidence'] = selection
                return result
            selected, rate = min(eligible, key=lambda row: (
                -row[1], row[0].price.current, -row[0].sold, row[0].shop_id or '', row[0].product_id))
            expected = (selected.shop_id, selected.product_id)
            receipt_path = _receipt_path(settings, profile, expected)
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                intent = receipt.get('intent')
                if (receipt.get('schema_version') != 2 or not isinstance(intent, dict)
                        or receipt.get('intent_sha256') != _intent_hash(intent)
                        or (intent.get('shop_id'), intent.get('product_id')) != expected):
                    return _stop('affiliate_link_intent_requires_reconciliation', state='blocked', candidate_count=count)
                if receipt.get('state') == 'verified':
                    # Reuse a confirmed URL with current eligibility/destination.
                    url = receipt.get('url')
                elif (receipt.get('state') in {'intent', 'incomplete'}
                      and intent.get('effect') == 'verify_existing_link'
                      and _safe_url(intent.get('existing_url'), affiliate=True)):
                    # Only retry a read of the same immutable existing URL. The
                    # provider's current link cannot replace the frozen intent.
                    url = intent['existing_url']
                    receipt.update(state='intent', last_stage='existing_link_reverification')
                    atomic_json(receipt_path, receipt)
                elif (receipt.get('state') in {'intent', 'incomplete'}
                      and intent.get('effect') == 'resolve_link'
                      and (receipt.get('resolved_product_id') == selected.product_id
                           or receipt.get('resolved_identity') == list(expected))
                      and _safe_url(receipt.get('resolved_url'), affiliate=True)):
                    url = receipt['resolved_url']
                    receipt.update(state='intent', last_stage='resolved_link_reverification')
                    atomic_json(receipt_path, receipt)
                else:
                    return _stop('affiliate_link_incomplete_requires_reconciliation', state='blocked', candidate_count=count)
            elif selected.affiliate.status in {'verified', 'resolved'} and selected.affiliate.url:
                url = selected.affiliate.url
                if _safe_url(url, affiliate=True):
                    receipt = _new_receipt(selected, rate, now, effect='verify_existing_link', existing_url=url)
                    atomic_json(receipt_path, receipt)
            else:
                if native:
                    return _stop('shopee_link_resolution_not_live_verified', state='blocked', candidate_count=count)
                receipt = _new_receipt(selected, rate, now, effect='resolve_link')
                atomic_json(receipt_path, receipt)
                binder = getattr(provider, 'bind_link_intent', None)
                if binder is not None:
                    binder(receipt_path, receipt['intent_sha256'])
                phase = 'link_resolution'
                # Snapshot identity before calling a provider that may mutate the
                # same Pydantic model in place. One call only, even after timeout.
                resolved = provider.resolve_links([selected.model_copy(deep=True)], 1)
                if len(resolved) != 1 or resolved[0].product_id != selected.product_id:
                    raise ValueError('identity')
                linked = resolved[0]
                if expected[0] is not None:
                    if ((linked.shop_id, linked.product_id) != expected
                            or _identity(linked.product_url) != expected):
                        raise ValueError('identity')
                elif linked.shop_id is not None:
                    # A catalog resolver must not invent shop identity before redirect verification.
                    raise ValueError('identity')
                if linked.affiliate.status not in {'verified', 'resolved'}:
                    raise ValueError('status')
                url = linked.affiliate.url
                linked_rate, linked_reason = _eligibility(linked, settings, datetime.now(timezone.utc), native=native)
                if (linked_reason or linked_rate != rate or linked.price.current != selected.price.current
                        or linked.sold != selected.sold or linked.title != selected.title):
                    receipt.update(state='incomplete', last_stage='evidence_changed_during_link_resolution')
                    atomic_json(receipt_path, receipt)
                    return _stop('affiliate_evidence_changed_during_link_resolution',
                                 state='blocked', candidate_count=count)
                if _safe_url(url, affiliate=True):
                    update = {'resolved_url': url, 'resolved_product_id': selected.product_id,
                              'resolved_at': datetime.now(timezone.utc).isoformat()}
                    if expected[0] is not None:
                        update['resolved_identity'] = list(expected)
                    receipt.update(**update)
                    atomic_json(receipt_path, receipt)
            phase = 'destination_verification'
            destination_identity = _destination_identity(context, url, expected)
            if destination_identity is None:
                if receipt is not None and receipt.get('state') == 'intent':
                    receipt.update(state='incomplete', last_stage=phase)
                    atomic_json(receipt_path, receipt)
                return _stop('affiliate_link_destination_unverified', state='blocked', candidate_count=count)
            if selected.shop_id is None:
                selected.shop_id = destination_identity[0]
                selected.product_url = f'https://shopee.vn/product/{destination_identity[0]}/{destination_identity[1]}'
            if receipt is not None and receipt.get('state') == 'intent':
                receipt.update(resolved_identity=list(destination_identity),
                               resolved_product_id=selected.product_id)
                atomic_json(receipt_path, receipt)
            # Browser work may take long enough to expire eligibility.
            rate, reason = _eligibility(selected, settings, datetime.now(timezone.utc), native=native)
            if reason:
                return _stop(reason, candidate_count=count)
            pack = _pack(selected, rate, url, count)
            # Reuse does not rewrite the original intent or the confirmed result.
            if receipt['state'] != 'verified':
                receipt.update(state='verified', url=url, verified_at=datetime.now(timezone.utc).isoformat())
                atomic_json(receipt_path, receipt)
            return pack
    except Exception as exc:
        # Exception messages and provider details can contain session credentials.
        # Emit only controlled stage names. An existing intent survives a crash.
        if receipt_path is not None and receipt is not None and receipt.get('state') == 'intent':
            try:
                receipt.update(state='incomplete', last_stage=phase)
                atomic_json(receipt_path, receipt)
            except OSError:
                pass
        code = getattr(exc, 'code', None)
        if code in {'shopee_security_challenge', 'shopee_affiliate_auth_required', 'shopee_affiliate_link_unconfirmed',
                    'catalog_detail_unavailable', 'catalog_cross_channel_commission_unavailable'}:
            return _stop(code, state='needs_input' if code in {'shopee_security_challenge', 'shopee_affiliate_auth_required'} else 'blocked',
                         candidate_count=count)
        return _stop('affiliate_' + phase + '_failed', state='blocked', candidate_count=count)
