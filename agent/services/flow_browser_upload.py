"""One non-paid, browser-authenticated reference upload; no automatic retry."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from agent.services import flow_batch as fb
from agent.services.flow_browser_contract import MAX_IMAGE_BYTES, validate_command, verified_upload_receipt


def upload_reference(session, path: Path, project_id: str, state) -> str:
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_IMAGE_BYTES + 1)
    if not 0 < len(raw) <= MAX_IMAGE_BYTES:
        raise ValueError('IMAGE_SIZE_INVALID')
    from PIL import Image
    with Image.open(BytesIO(raw)) as image:
        mime = Image.MIME.get(image.format)
        image.verify()
    digest = hashlib.sha256(raw).hexdigest()
    freq = fb.upload_request(base64.b64encode(raw).decode(), project_id, mime_type=mime,
                             file_name=Path(path).name)
    command = validate_command('batch_rpc', dict(rpcid=fb.RPC_UPLOAD_IMAGE, freq=freq,
                                projectId=project_id, captchaAction=fb.CAPTCHA_IMAGE))
    key = f'upload:{project_id}:{digest}:{Path(path).name}'
    entry = state.begin(key, 'upload', dict(project_id=project_id, image_sha256=digest,
                                          file_name=Path(path).name, mime_type=mime))
    if entry['state'] == 'COMPLETED':
        return entry['receipt']['media_id']
    script = Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    try:
        response = session.page.evaluate('mw:' + script,
                                         dict(projectId=project_id, freq=command.freq))
        if response.get('status') != 200 or response.get('body_complete') is not True:
            raise RuntimeError('UPLOAD_UNCONFIRMED')
        results = fb.parse_envelope(response['data'])
        matched = [r for r in results if r.rpcid == fb.RPC_UPLOAD_IMAGE and not r.error]
        if len(matched) != 1:
            raise RuntimeError('UPLOAD_UNCONFIRMED')
        media_id = verified_upload_receipt(matched[0].data, project_id)
        state.complete(key, dict(project_id=project_id, media_id=media_id))
        return media_id
    except Exception:
        state.mark_unknown(key)
        raise RuntimeError('UPLOAD_RECONCILIATION_REQUIRED') from None
