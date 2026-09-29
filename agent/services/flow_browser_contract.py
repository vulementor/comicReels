"""Fail-closed, non-paid browser RPC boundary. Flow semantics stay outside KBS."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field

from agent.services import flow_batch as fb

UUID = re.compile(r'^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ALLOWED = {fb.RPC_CREATE_PROJECT, fb.RPC_PROJECT_MEDIA, fb.RPC_MEDIA,
           fb.RPC_OPERATION, fb.RPC_UPLOAD_IMAGE}


class BrowserCommandError(RuntimeError):
    """Public fixed codes; never include native request/auth/response text."""


def uuid_value(value):
    if not isinstance(value, str) or not UUID.fullmatch(value):
        raise BrowserCommandError('INVALID_UUID')
    return value


@dataclass(frozen=True)
class BrowserCommand:
    rpcid: str
    capability: str
    freq: str = field(repr=False)
    project_id: str | None = None
    match: str | None = None
    image_bytes: bytes | None = field(default=None, repr=False)
    file_name: str | None = None
    mime_type: str | None = None
    title: str | None = None


def validate_command(method, params) -> BrowserCommand:
    if method != 'batch_rpc' or not isinstance(params, dict) or params.get('rpcid') not in ALLOWED:
        raise BrowserCommandError('RPC_NOT_ALLOWED')
    try:
        if set(params) - {'rpcid', 'freq', 'projectId', 'captchaAction', 'match'}:
            raise ValueError
        rpc, freq = params['rpcid'], params['freq']
        limit = 12 * 1024 * 1024 if rpc == fb.RPC_UPLOAD_IMAGE else 16 * 1024
        if not isinstance(freq, str) or len(freq.encode()) > limit:
            raise ValueError
        outer = json.loads(freq)
        if not isinstance(outer, list) or len(outer) != 1 or len(outer[0]) != 1:
            raise ValueError
        item = outer[0][0]
        if not isinstance(item, list) or len(item) != 4 or item[0] != rpc or item[2:] != [None, 'generic']:
            raise ValueError
        data = json.loads(item[1])
        if not isinstance(data, list):
            raise TypeError
        pid = params.get('projectId')
        if pid is not None:
            uuid_value(pid)
        match = params.get('match')
        if match is not None and (rpc != fb.RPC_PROJECT_MEDIA or not UUID.fullmatch(match)):
            raise ValueError
        if rpc != fb.RPC_UPLOAD_IMAGE and params.get('captchaAction'):
            raise ValueError
        kwargs = {'rpcid': rpc, 'freq': freq, 'project_id': pid, 'match': match}
        if rpc == fb.RPC_CREATE_PROJECT:
            title = data[1][1][0]
            if (not isinstance(title, str) or not 1 <= len(title) <= 160
                    or data != ['projects/*', [None, [title]], [None, fb.SURFACE_ID]] or pid or match):
                raise ValueError
            return BrowserCommand(capability='create', title=title, **kwargs)
        if rpc == fb.RPC_PROJECT_MEDIA:
            bound = uuid_value(data[0].removeprefix('projects/'))
            if (data != [f'projects/{bound}', None, None, None, [1]]
                    or type(data[4][0]) is not int or pid not in {None, bound}):
                raise ValueError
            return BrowserCommand(capability='read', **{**kwargs, 'project_id': bound})
        if rpc == fb.RPC_MEDIA:
            if len(data) != 1:
                raise ValueError
            uuid_value(data[0])
        elif rpc == fb.RPC_OPERATION:
            operation = uuid_value(data[2][0][0])
            if data != [None, None, [[operation]]]:
                raise ValueError
        elif rpc == fb.RPC_UPLOAD_IMAGE:
            bound = uuid_value(data[0][5])
            if (len(data) != 12 or data[0] != fb._context(bound)
                    or type(data[0][10][1]) is not int or type(data[3]) is not int
                    or data[3:8] != [1, None, None, None, None] or data[9] is not None
                    or pid not in {None, bound} or params.get('captchaAction') != fb.CAPTCHA_IMAGE
                    or data[2] not in {'image/png', 'image/jpeg', 'image/webp'}):
                raise ValueError
            uuid_value(data[10])
            uuid_value(data[11])
            name = data[8]
            reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
            if (not isinstance(name, str) or not 1 <= len(name) <= 160
                    or re.search(r'[\\/<>:"|?*\x00-\x1f]', name) or name.endswith((' ', '.'))
                    or name.split('.')[0].upper() in reserved):
                raise ValueError
            raw = base64.b64decode(data[1], validate=True)
            if not 0 < len(raw) <= MAX_IMAGE_BYTES:
                raise ValueError
            return BrowserCommand(capability='upload', image_bytes=raw, file_name=name,
                mime_type=data[2], **{**kwargs, 'project_id': bound})
        return BrowserCommand(capability='read', **kwargs)
    except Exception:  # noqa: BLE001 - malformed request details must not leak.
        raise BrowserCommandError('RECIPE_UNVERIFIED') from None


def verified_upload_receipt(payload, project_id):
    try:
        record = payload[0]
        media_id = uuid_value(record[0])
        if record[1] != uuid_value(project_id):
            raise ValueError
        return media_id
    except Exception:  # noqa: BLE001 - response contents are private.
        raise BrowserCommandError('UPLOAD_RECEIPT_UNVERIFIED') from None
