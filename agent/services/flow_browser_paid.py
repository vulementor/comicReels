"""FBR-3 one-shot paid image safety boundary.

This module prepares the durable/idempotent control plane only. It has no browser
recipe and is not wired into FlowBrowserDriver.execute(). Dispatch is disabled by
default and requires an exact in-memory authorization object when explicitly
enabled by the later paid validation checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import BrowserCommandError, uuid_value


@dataclass(frozen=True)
class PaidImageCommand:
    rpcid: str
    freq: str
    project_id: str
    request_sha256: str


class FlowPaidImageGate:
    """Exactly-one-variant paid image intent with no automatic resend."""

    def __init__(self, state, dispatch, *, dispatch_enabled=False, authorization=None):
        self._state = state
        self._dispatch = dispatch
        self.dispatch_enabled = dispatch_enabled is True
        self._authorization = authorization

    @staticmethod
    def _error(code: str, effect: str = 'not_submitted', status: int = 409) -> dict:
        return {'status': status, 'error': code, 'effect': effect}

    def validate(self, params: dict) -> PaidImageCommand:
        try:
            if not isinstance(params, dict) or set(params) != {
                    'rpcid', 'freq', 'projectId', 'captchaAction'}:
                raise ValueError
            if params['rpcid'] != fb.RPC_GEN_IMAGE or params['captchaAction'] != fb.CAPTCHA_IMAGE:
                raise ValueError
            project_id = uuid_value(params['projectId'])
            freq = params['freq']
            if not isinstance(freq, str) or not 1 <= len(freq.encode()) <= 16 * 1024:
                raise ValueError
            outer = json.loads(freq)
            if (not isinstance(outer, list) or len(outer) != 1
                    or not isinstance(outer[0], list) or len(outer[0]) != 1):
                raise ValueError
            envelope = outer[0][0]
            if (not isinstance(envelope, list) or len(envelope) != 4
                    or envelope[0] != fb.RPC_GEN_IMAGE
                    or envelope[2:] != [None, 'generic']):
                raise ValueError
            body = json.loads(envelope[1])
            if not isinstance(body, list) or len(body) != 5:
                raise ValueError
            variants = body[1]
            if not isinstance(variants, list) or len(variants) != 1:
                raise ValueError
            variant = variants[0]
            if not isinstance(variant, list) or len(variant) != 14:
                raise ValueError
            expected_context = fb._context(project_id)
            if variant[7] != expected_context or body[3] != expected_context:
                raise ValueError
            if body[2] != 1:
                raise ValueError
            # The exact single-use captcha marker must still be present here.
            # Minting/replacing it belongs to the later browser dispatch recipe.
            if (variant[7][10] != [fb.CAPTCHA_SLOT, 1]
                    or body[3][10] != [fb.CAPTCHA_SLOT, 1]):
                raise ValueError
            request_sha256 = hashlib.sha256(freq.encode()).hexdigest()
            return PaidImageCommand(
                rpcid=fb.RPC_GEN_IMAGE, freq=freq, project_id=project_id,
                request_sha256=request_sha256,
            )
        except Exception:
            raise BrowserCommandError('PAID_RECIPE_UNVERIFIED') from None

    def intent(self, command: PaidImageCommand, idempotency_key: str) -> tuple[str, dict]:
        if (not isinstance(idempotency_key, str)
                or not 1 <= len(idempotency_key) <= 160
                or not re.fullmatch(r'[A-Za-z0-9._:-]+', idempotency_key)):
            raise BrowserCommandError('PAID_IDEMPOTENCY_INVALID')
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        return f'paid-image:{digest}', {
            'project_id': command.project_id,
            'request_sha256': command.request_sha256,
            'idempotency_sha256': digest,
            'rpcid': command.rpcid,
        }

    def _completed(self, entry: dict, attributes: dict, *, reused: bool) -> dict:
        try:
            if (entry.get('kind') != 'paid_image'
                    or entry.get('state') != 'COMPLETED'
                    or entry.get('attributes') != attributes):
                return self._error('PAID_IDEMPOTENCY_CONFLICT')
            receipt = entry.get('receipt')
            if not isinstance(receipt, dict):
                raise ValueError
            project_id = uuid_value(receipt.get('project_id'))
            media_id = uuid_value(receipt.get('media_id'))
            if project_id != attributes['project_id']:
                return self._error('PAID_IDEMPOTENCY_CONFLICT')
            return {
                'status': 200,
                'data': {'projectId': project_id, 'mediaId': media_id},
                'effect': 'completed',
                'reused': reused,
            }
        except Exception:
            return self._error('PAID_RECONCILIATION_REQUIRED', 'unknown')

    def submit(self, params: dict, *, idempotency_key: str, authorization=None,
               timeout: float = 300) -> dict:
        # These gates are intentionally before validation/journal access: an
        # unapproved call cannot even manufacture a paid intent.
        if not self.dispatch_enabled:
            return self._error('PAID_DISPATCH_DISABLED', status=403)
        if self._authorization is None or authorization is not self._authorization:
            return self._error('PAID_AUTHORIZATION_REQUIRED', status=403)

        try:
            command = self.validate(params)
            key, attributes = self.intent(command, idempotency_key)
        except BrowserCommandError as error:
            return self._error(str(error))

        existing = self._state.lookup(key)
        if existing is not None:
            if existing.get('attributes') != attributes:
                return self._error('PAID_IDEMPOTENCY_CONFLICT')
            if existing.get('state') == 'COMPLETED':
                return self._completed(existing, attributes, reused=True)
            return self._error('PAID_RECONCILIATION_REQUIRED', 'unknown')

        try:
            entry = self._state.begin(key, 'paid_image', attributes)
        except Exception:
            return self._error('PAID_STATE_FAILED')
        if entry.get('state') == 'COMPLETED':
            return self._completed(entry, attributes, reused=True)

        try:
            result = self._dispatch(command, timeout)
            if (not isinstance(result, dict) or result.get('status') != 200
                    or result.get('body_complete') is not True
                    or result.get('effect') != 'completed'
                    or not isinstance(result.get('data'), str)):
                raise BrowserCommandError('PAID_RECONCILIATION_REQUIRED')
            payload = fb.first_payload(result['data'], fb.RPC_GEN_IMAGE)
            generated = fb.read_images(payload)
            if len(generated) != 1:
                raise BrowserCommandError('PAID_RECEIPT_UNVERIFIED')
            media_id = uuid_value(generated[0].media_id)
            receipt = {'project_id': command.project_id, 'media_id': media_id}
            self._state.complete(key, receipt)
            return {
                'status': 200,
                'data': {'projectId': command.project_id, 'mediaId': media_id},
                'effect': 'completed',
                'reused': False,
            }
        except BaseException as error:
            try:
                current = self._state.lookup(key)
                if current is not None and current.get('state') == 'SUBMITTING':
                    self._state.mark_unknown(key)
            except Exception:
                pass
            if not isinstance(error, Exception):
                raise
            return self._error('PAID_RECONCILIATION_REQUIRED', 'unknown')
