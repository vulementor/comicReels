import base64
import json

import pytest

from agent.services import flow_batch as fb

PID = '11111111-2222-3333-4444-555555555555'
MID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'


def validate(rpc, freq, **kwargs):
    from agent.services.flow_browser_contract import validate_command
    return validate_command('batch_rpc', {'rpcid': rpc, 'freq': freq, **kwargs})


@pytest.mark.parametrize('rpc,freq,capability', [
    (fb.RPC_CREATE_PROJECT, fb.create_project_request('FBR2 test'), 'create'),
    (fb.RPC_PROJECT_MEDIA, fb.project_media_request(PID), 'read'),
    (fb.RPC_MEDIA, fb.media_request(MID), 'read'),
    (fb.RPC_OPERATION, fb.operation_request(MID), 'read'),
])
def test_only_exact_nonpaid_rpc_recipes_are_admitted(rpc, freq, capability):
    command = validate(rpc, freq)
    assert command.capability == capability and command.rpcid == rpc


def test_upload_is_nonpaid_despite_captcha_action_and_keeps_original_bytes():
    raw = b'non-sensitive-test-bytes'
    command = validate(fb.RPC_UPLOAD_IMAGE,
        fb.upload_request(base64.b64encode(raw).decode(), PID, 'image/png', 'test.png'),
        projectId=PID, captchaAction=fb.CAPTCHA_IMAGE)
    assert command.capability == 'upload' and command.project_id == PID
    assert command.image_bytes == raw


@pytest.mark.parametrize('rpc', [fb.RPC_GEN_IMAGE, fb.RPC_GEN_VIDEO, fb.RPC_GEN_VIDEO_REFERENCES,
                                fb.RPC_UPSCALE_IMAGE, 'unknown'])
def test_paid_or_unknown_rpc_never_reaches_browser(rpc):
    from agent.services.flow_browser_contract import BrowserCommandError
    with pytest.raises(BrowserCommandError, match='RPC_NOT_ALLOWED'):
        validate(rpc, fb.build_envelope(rpc, []))


def test_hidden_paid_envelope_mixed_batch_and_wrong_project_are_rejected():
    from agent.services.flow_browser_contract import BrowserCommandError
    mixed = json.loads(fb.project_media_request(PID))
    mixed[0].append([fb.RPC_GEN_IMAGE, '[]', None, 'generic'])
    for freq in [fb.build_envelope(fb.RPC_GEN_IMAGE, []), json.dumps(mixed)]:
        with pytest.raises(BrowserCommandError):
            validate(fb.RPC_PROJECT_MEDIA, freq)
    with pytest.raises(BrowserCommandError):
        validate(fb.RPC_PROJECT_MEDIA, fb.project_media_request(PID), projectId=MID)


@pytest.mark.parametrize('changes', [
    {'image_b64': 'invalid%%'}, {'mime_type': 'text/html'}, {'file_name': '../test.png'},
    {'file_name': 'CON'}, {'project_id': 'not-a-uuid'},
])
def test_upload_rejects_bad_bytes_type_path_or_identity(changes):
    from agent.services.flow_browser_contract import BrowserCommandError
    kwargs = {'image_b64': 'aGVsbG8=', 'project_id': PID,
              'mime_type': 'image/png', 'file_name': 'test.png', **changes}
    with pytest.raises(BrowserCommandError):
        validate(fb.RPC_UPLOAD_IMAGE, fb.upload_request(**kwargs), captchaAction=fb.CAPTCHA_IMAGE)


def test_upload_receipt_must_bind_valid_media_and_project_uuids():
    from agent.services.flow_browser_contract import (
        BrowserCommandError,
        verified_upload_receipt,
    )
    assert verified_upload_receipt([[MID, PID, 'operation']], PID) == MID
    for payload in [[['CAMSbad', PID]], [[MID, MID]], [[]], []]:
        with pytest.raises(BrowserCommandError):
            verified_upload_receipt(payload, PID)
