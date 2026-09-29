"""FBR-1 bounded observation and one-use replay of the observed project-media read.

KBS owns live request handles. This Flow adapter classifies exact RPC/body shapes and exports
only structural evidence. No request body, token, account value, media URL or response text is
persisted. Mutation RPCs are deliberately absent from the executable allowlist.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote_plus, urlsplit

from agent.services import flow_batch as fb

MAX_BODY = 512 * 1024
MAX_FORM = 16 * 1024
_PROJECT = re.compile(r'^projects/([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$')


class DiscoveryError(RuntimeError):
    """Fixed public code only; browser exceptions can contain credentials."""


def classify_read_request(request) -> dict:
    try:
        url = urlsplit(request.url)
        if (url.scheme != 'https' or url.hostname != 'flow.google.com'
                or url.port not in {None, 443} or url.username or url.password
                or url.path != fb.BATCH_PATH or request.method != 'POST'
                or parse_qs(url.query).get('rpcids') != ['Zzl0ze']):
            raise ValueError
        # Inspect only f.req. Never decode or return the form's authentication field.
        form = request.post_data
        if not isinstance(form, str) or len(form.encode('utf-8')) > MAX_FORM:
            raise ValueError
        # Native Flow adds a trailing '&'; empty separators carry no form field.
        parts = [part for part in form.split('&') if part]
        names = [unquote_plus(part.partition('=')[0]) for part in parts]
        if len(set(names)) != len(names) or set(names) != {'f.req', 'at'}:
            raise ValueError
        encoded = next(part.partition('=')[2] for part in parts
            if unquote_plus(part.partition('=')[0]) == 'f.req')
        envelope = json.loads(unquote_plus(encoded))
        if not isinstance(envelope, list) or len(envelope) != 1 or len(envelope[0]) != 1:
            raise ValueError
        item = envelope[0][0]
        if len(item) != 4 or item[0] != 'Zzl0ze' or item[2:] != [None, 'generic']:
            raise ValueError
        payload = json.loads(item[1])
        if (not isinstance(payload, list) or len(payload) != 5
                or payload[1:] != [None, None, None, [1]] or type(payload[4][0]) is not int
                or not isinstance(payload[0], str)):
            raise ValueError
        match = _PROJECT.fullmatch(payload[0])
        if not match:
            raise ValueError
        return {'rpc_id': 'Zzl0ze', 'project_id': match.group(1),
                'shape_version': 1, 'request_digest': hashlib.sha256(item[1].encode()).hexdigest()}
    except Exception:  # noqa: BLE001 - sanitize all malformed/browser state.
        raise DiscoveryError('READ_RECIPE_UNVERIFIED') from None


def body_shape(value) -> dict:
    """Values AND object keys are private. Emit bounded type/length structure only."""
    remaining = [96]

    def walk(item, depth):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 6:
            return {'type': 'bounded'}
        if isinstance(item, (list, dict)):
            values = item if isinstance(item, list) else list(item.values())
            return {'type': 'array' if isinstance(item, list) else 'object',
                    'length': len(item), 'items': [walk(v, depth + 1) for v in values[:8]]}
        return {'type': 'null' if item is None else 'boolean' if isinstance(item, bool)
                else 'number' if isinstance(item, (int, float)) else 'string'}
    return walk(value, 0)


def _body_policy():
    from kabin_browser_semantic import BodyCapturePolicy
    return BodyCapturePolicy(max_response_capture_bytes=MAX_BODY, max_inline_bytes=MAX_BODY,
        max_request_capture_bytes=MAX_BODY, max_preview_chars=1,
        allow_unknown_size=False, allow_request_body=False)


def _project_body(body) -> dict:
    if body is None or str(body.summary.status) != 'captured_inline':
        return {'capture': 'unavailable'}
    return _project_raw(body.raw_bytes)


def _project_raw(raw) -> dict:
    if not isinstance(raw, bytes) or len(raw) > MAX_BODY:
        raise DiscoveryError('BODY_BUDGET')
    try:
        payload = fb.first_payload(raw.decode('utf-8'), 'Zzl0ze')
        return {'capture': 'captured', 'bytes': len(raw), 'shape': body_shape(payload),
                'image_count': len(fb.read_images(payload))}
    except Exception:  # noqa: BLE001 - raw Flow errors can include user data.
        raise DiscoveryError('RESPONSE_SHAPE_UNVERIFIED') from None


class FlowReadDiscovery:
    """Synchronous, finite discovery window bound to one provider/session/navigation epoch."""

    def __init__(self, provider, *, observer=None, clock=time.monotonic):
        from kabin_browser_semantic import NetworkObserver, NetworkPolicy
        self._provider = provider
        self._session = provider.session
        self._observer = observer or NetworkObserver(self._session, policy=NetworkPolicy(
            completed_exchange_limit=64, event_limit=256, active_exchange_limit=64,
            safe_value_headers=(), retain_static_assets=False))
        self._clock = clock
        self._recipes = {}
        self._bound = set()
        self._shapes = {}
        self._request_times = {}
        self._captures = 0
        self._replay_inflight = False
        self._started = False
        self._closed = False
        self._listeners = []
        self._navigation = lambda frame: self.invalidate() if frame is self._session.page.main_frame else None
        self._request_seen = lambda request: self._observe_request(request)

    @property
    def observer(self):
        return self._observer

    def _healthy(self):
        if (self._closed or self._provider.session is not self._session
                or not self._provider.capture_health()['ready']):
            self.invalidate()
            raise DiscoveryError('SESSION_UNVERIFIED')

    def start(self):
        self._healthy()
        if self._started:
            return self
        try:
            self._observer.attach()
            for event, handler in [('framenavigated', self._navigation), ('request', self._request_seen)]:
                self._session.page.on(event, handler)
                self._listeners.append((event, handler))
        except Exception:  # noqa: BLE001 - rollback partial listener registration.
            self.close()
            raise DiscoveryError('OBSERVER_START_FAILED') from None
        self._started = True
        return self

    def invalidate(self):
        self._recipes.clear()
        self._shapes.clear()
        self._request_times.clear()

    def _observe_request(self, request):
        if self._replay_inflight:
            return  # a replay is never independent native evidence for another ticket
        url = urlsplit(request.url)
        if (request.method != 'POST' or url.scheme != 'https' or url.hostname != 'flow.google.com'
                or url.path != fb.BATCH_PATH or parse_qs(url.query).get('rpcids') != ['Zzl0ze']):
            return
        if len(self._request_times) >= 64:
            self._request_times.pop(next(iter(self._request_times)))
        self._request_times[id(request)] = self._clock()

    def _read(self, exchange_id):
        self._healthy()
        if not self._started:
            raise DiscoveryError('OBSERVER_NOT_STARTED')
        exchange = self._observer.exchange(exchange_id)
        ref = self._observer.runtime_ref(exchange_id)
        if (not exchange or not ref or not ref.request or str(exchange.outcome) != 'completed'
                or not exchange.response or exchange.response.status != 200):
            raise DiscoveryError('EXCHANGE_UNVERIFIED')
        observed = self._request_times.get(id(ref.request))
        if observed is None or not 0 <= self._clock() - observed <= 60:
            raise DiscoveryError('RECIPE_EXPIRED')
        return classify_read_request(ref.request)

    def bind(self, exchange_id):
        classification = self._read(exchange_id)
        if exchange_id in self._bound or len(self._bound) >= 3:
            raise DiscoveryError('RECIPE_ALREADY_BOUND')
        self._bound.add(exchange_id)
        ticket = secrets.token_hex(12)
        self._recipes[ticket] = (exchange_id, self._clock(), classification)
        return ticket

    def capture(self, exchange_id, *, service=None):
        from kabin_browser_semantic import BodyCaptureService
        classification = self._read(exchange_id)
        if self._captures >= 3:
            raise DiscoveryError('CAPTURE_BUDGET')
        self._captures += 1
        service = service or BodyCaptureService(self._observer, policy=_body_policy())
        try:
            result = _project_body(service.capture_response(exchange_id, mode='inline', sensitive=True))
        except DiscoveryError:
            raise
        except Exception:  # noqa: BLE001 - no browser error text in public evidence.
            raise DiscoveryError('CAPTURE_FAILED') from None
        if result.get('shape'):
            self._shapes[exchange_id] = result['shape']
        return {'rpc_id': classification['rpc_id'], **result}

    def _consume_binding(self, ticket):
        binding = self._recipes.pop(ticket, None)  # consume before any attempted network effect
        if not binding:
            raise DiscoveryError('RECIPE_EXPIRED')
        exchange_id, created, classification = binding
        if self._clock() - created > 60 or self._read(exchange_id) != classification:
            raise DiscoveryError('RECIPE_EXPIRED')
        expected = self._shapes.get(exchange_id)
        if expected is None:
            raise DiscoveryError('RESPONSE_BASELINE_REQUIRED')
        return exchange_id, classification, expected

    def replay(self, ticket, *, service=None):
        from kabin_browser_semantic import ApiReplayPolicy, ApiReplayService
        exchange_id, _, expected = self._consume_binding(ticket)
        # Opt-ins apply ONLY after exact single-RPC/form validation above, never arbitrary POSTs.
        service = service or ApiReplayService(self._session, policy=ApiReplayPolicy(
            timeout_ms=15000, max_redirects=0, max_request_body_bytes=MAX_FORM,
            allow_side_effect_methods=True, allow_sensitive_body=True,
            allow_unknown_request_body_size=True), body_policy=_body_policy())
        try:
            result = service.replay_exchange(self._observer, exchange_id,
                body_mode='inline', sensitive_response=True)
            if str(result.summary.status) != 'completed' or result.summary.http_status != 200:
                return {'replay': 'not_validated', 'http_status': result.summary.http_status,
                        'reason': str(result.summary.status)}
            projection = _project_body(result.body)
            if projection.get('capture') != 'captured':
                return {'replay': 'not_validated', **projection}
            if projection.get('shape') != expected:
                self.invalidate()
                raise DiscoveryError('RESPONSE_SHAPE_CHANGED')
            return {'replay': 'validated', **projection}
        except DiscoveryError:
            raise
        except Exception:  # noqa: BLE001 - ambiguous results are consumed, never retried.
            raise DiscoveryError('REPLAY_FAILED') from None

    def replay_in_page(self, ticket):
        """Explicit alternate read channel; credentials and bounded stream stay in the page.

        Not an automatic retry of request-context replay: both channels consume the same ticket.
        The caller needs a separately observed, fresh native read to select another channel.
        """
        exchange_id, classification, expected = self._consume_binding(ticket)
        script = Path(__file__).with_name('flow_read_replay.js').read_text(encoding='utf-8')
        self._replay_inflight = True
        try:
            result = self._session.page.evaluate('mw:' + script,
                {'projectId': classification['project_id']})
            # Navigation/auth/session changes during asynchronous fetch invalidate its evidence.
            if self._read(exchange_id) != classification or self._shapes.get(exchange_id) != expected:
                raise DiscoveryError('RECIPE_EXPIRED')
            status = result.get('status') if isinstance(result, dict) else None
            reasons = {'BODY_BUDGET', 'BODY_INCOMPLETE', 'SESSION_UNVERIFIED', 'HTTP_REJECTED'}
            reason = result.get('error') if isinstance(result, dict) else None
            if status != 200 or reason:
                return {'replay': 'not_validated', 'http_status': status,
                        'reason': reason if reason in reasons else 'BODY_INCOMPLETE'}
            raw = result.get('text')
            raw = raw.encode('utf-8') if isinstance(raw, str) else None
            if raw is None or len(raw) != result.get('bytes') or len(raw) > MAX_BODY:
                return {'replay': 'not_validated', 'http_status': status, 'reason': 'BODY_INCOMPLETE'}
            projection = _project_raw(raw)
            if projection['shape'] != expected:
                self.invalidate()
                raise DiscoveryError('RESPONSE_SHAPE_CHANGED')
            return {'replay': 'validated', 'channel': 'browser_page', **projection}
        except DiscoveryError:
            raise
        except Exception:  # noqa: BLE001 - never return page/token/response exception details.
            raise DiscoveryError('REPLAY_FAILED') from None
        finally:
            self._replay_inflight = False

    def close(self):
        self.invalidate()
        failed = False
        for event, handler in reversed(self._listeners):
            try:
                self._session.page.remove_listener(event, handler)
            except Exception:  # noqa: BLE001 - attempt all detachments even after one failure.
                failed = True
        self._listeners.clear()
        try:
            self._observer.close()
        except Exception:  # noqa: BLE001 - sanitized close diagnostic only.
            failed = True
        finally:
            self._closed = True
        if failed:
            raise DiscoveryError('OBSERVER_CLOSE_FAILED')
