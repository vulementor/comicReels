"""One non-paid, browser-authenticated reference upload; no automatic retry.

Path-based story callers and the concrete browser driver share the same intent
identity and receipt handling. Callers own the session/profile lease; the driver
also supplies a fresh lease guard for every journal read/write and dispatch.
"""
from __future__ import annotations

import base64
import hashlib
import json
import warnings
from io import BytesIO
from pathlib import Path

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import (
    BrowserCommandError, MAX_IMAGE_BYTES, uuid_value, validate_command,
    verified_upload_receipt,
)


def _image_mime(raw: bytes) -> str:
    try:
        from PIL import Image
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                mime = Image.MIME.get(image.format)
                image.verify()
        if mime not in {'image/png', 'image/jpeg', 'image/webp'}:
            raise ValueError
        return mime
    except Exception:
        raise BrowserCommandError('IMAGE_CONTENT_INVALID') from None


def _unknown() -> dict:
    return {'status': 409, 'error': 'UPLOAD_RECONCILIATION_REQUIRED',
            'effect': 'unknown'}


def _receipt_response(receipt: dict, *, reused: bool) -> dict:
    """Reconstruct only the verified upload record, not a raw private response."""
    record = [uuid_value(receipt['media_id']), uuid_value(receipt['project_id'])]
    if 'operation_id' in receipt:
        record.append(uuid_value(receipt['operation_id']))
    return {
        'status': 200, 'body_complete': True, 'effect': 'completed',
        'reused': reused,
        'data': json.dumps([['wrb.fr', fb.RPC_UPLOAD_IMAGE, json.dumps([record])]]),
    }


def _reuse(entry: dict, attributes: dict) -> dict:
    # Store-level validation covers schema, not the semantic binding of a key.
    # A colliding, incomplete or foreign receipt must never authorize an upload.
    try:
        if (entry['kind'] != 'upload' or entry['attributes'] != attributes
                or entry['state'] != 'COMPLETED'):
            return _unknown()
        receipt = entry['receipt']
        if receipt['project_id'] != attributes['project_id']:
            return _unknown()
        return _receipt_response(receipt, reused=True)
    except (KeyError, TypeError, BrowserCommandError):
        return _unknown()


def execute_upload(session, command, state, *, require_lease=None, prepare=None) -> dict:
    """Submit one validated upload or reuse its durable completed receipt.

    ``prepare(project_id)`` may navigate the same leased session before a NEW
    intent. Existing uncertain/completed intents never cause navigation/replay.
    No source image bytes, auth data, signed URLs or raw errors enter the journal.
    """
    if (getattr(command, 'capability', None) != 'upload'
            or getattr(command, 'rpcid', None) != fb.RPC_UPLOAD_IMAGE):
        raise BrowserCommandError('RPC_NOT_ALLOWED')
    # Re-derive all fields from the envelope rather than trusting a constructed
    # BrowserCommand whose image bytes or project fields might disagree.
    command = validate_command('batch_rpc', {
        'rpcid': fb.RPC_UPLOAD_IMAGE, 'freq': command.freq,
        'projectId': command.project_id, 'captchaAction': fb.CAPTCHA_IMAGE,
    })
    raw = command.image_bytes
    if _image_mime(raw) != command.mime_type:
        raise BrowserCommandError('IMAGE_MIME_MISMATCH')
    project_id = command.project_id
    digest = hashlib.sha256(raw).hexdigest()
    attributes = dict(project_id=project_id, image_sha256=digest,
                      file_name=command.file_name, mime_type=command.mime_type)
    # Keep the established upload_reference key: random client request UUIDs
    # change between calls, but do not create new permission to upload again.
    key = f'upload:{project_id}:{digest}:{command.file_name}'

    def guarded(function, *args):
        if require_lease is not None:
            require_lease()
        return function(*args)

    existing = guarded(state.lookup, key)
    if existing is not None:
        return _reuse(existing, attributes)
    # Missing packaged JS is a pre-dispatch failure, not an ambiguous upload.
    script = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    if prepare is not None:
        prepare(project_id)
    entry = guarded(state.begin, key, 'upload', attributes)
    if entry['state'] == 'COMPLETED':
        return _reuse(entry, attributes)
    try:
        if require_lease is not None:
            require_lease()
        response = session.page.evaluate('mw:' + script,
                                         dict(projectId=project_id, freq=command.freq))
        if (not isinstance(response, dict) or response.get('status') != 200
                or response.get('body_complete') is not True
                or response.get('effect') in {'unknown', 'not_submitted'}
                or not isinstance(response.get('data'), str)):
            raise BrowserCommandError('UPLOAD_RECONCILIATION_REQUIRED')
        results = fb.parse_envelope(response['data'])
        matched = [result for result in results if result.rpcid == fb.RPC_UPLOAD_IMAGE]
        if len(matched) != 1 or not matched[0].ok:
            raise BrowserCommandError('UPLOAD_RECONCILIATION_REQUIRED')
        payload = matched[0].data
        media_id = verified_upload_receipt(payload, project_id)
        receipt = dict(project_id=project_id, media_id=media_id)
        record = payload[0]
        if len(record) > 2 and record[2] is not None:
            receipt['operation_id'] = uuid_value(record[2])
        # Persist before acknowledging. Keep an observed operation UUID in the
        # receipt for the separately scoped read-only reconciliation wiring.
        guarded(state.complete, key, receipt)
        return _receipt_response(receipt, reused=False)
    except BaseException as error:
        try:
            current = guarded(state.lookup, key)
            if current is not None and current['state'] == 'SUBMITTING':
                guarded(state.mark_unknown, key)
        except Exception:
            # Lease loss or disk failure leaves SUBMITTING intact. It is still
            # non-retryable; never overwrite a completed receipt or hide it.
            pass
        if not isinstance(error, Exception):
            raise
        return _unknown()


def upload_reference(session, path: Path, project_id: str, state) -> str:
    """Compatibility path API; the caller must hold its existing profile lease."""
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError('IMAGE_SIZE_INVALID')
    mime = _image_mime(raw)
    freq = fb.upload_request(base64.b64encode(raw).decode(), project_id,
                             mime_type=mime, file_name=Path(path).name)
    command = validate_command('batch_rpc', dict(
        rpcid=fb.RPC_UPLOAD_IMAGE, freq=freq, projectId=project_id,
        captchaAction=fb.CAPTCHA_IMAGE,
    ))
    result = execute_upload(session, command, state)
    if result['status'] != 200:
        raise RuntimeError('UPLOAD_RECONCILIATION_REQUIRED')
    return verified_upload_receipt(fb.first_payload(result['data'], fb.RPC_UPLOAD_IMAGE),
                                    project_id)
