import json
from types import SimpleNamespace

import pytest

from agent.services.flow_browser_upload import upload_reference
from agent.services.flow_browser_state import BrowserStateStore

PID = '10000000-0000-4000-8000-000000000001'
MID = '20000000-0000-4000-8000-000000000001'


def session(result):
    calls = []
    def evaluate(script, args):
        calls.append(args)
        return result
    return SimpleNamespace(page=SimpleNamespace(evaluate=evaluate)), calls


def test_upload_is_idempotent_and_only_persists_validated_receipt(tmp_path):
    path = tmp_path / 'ref.png'
    from PIL import Image
    Image.new('RGB', (8, 8)).save(path)
    body = json.dumps([['wrb.fr', 'maseQ', json.dumps([[MID, PID]]), None, None, None, 'generic']])
    browser, calls = session(dict(status=200, data=body, body_complete=True))
    state = BrowserStateStore(tmp_path/'state.json', 'test-profile')
    assert upload_reference(browser, path, PID, state) == MID
    assert upload_reference(browser, path, PID, state) == MID
    assert len(calls) == 1
    assert 'maseQ' in calls[0]['freq']
    assert 'data' not in repr(state.load()['intents'])


def test_ambiguous_upload_cannot_be_sent_again(tmp_path):
    path = tmp_path/'ref.png'
    from PIL import Image
    Image.new('RGB', (8, 8)).save(path)
    browser, calls = session(dict(status=502, error='BODY_INCOMPLETE'))
    state = BrowserStateStore(tmp_path/'state.json', 'test-profile')
    with pytest.raises(RuntimeError):
        upload_reference(browser, path, PID, state)
    with pytest.raises(RuntimeError):
        upload_reference(browser, path, PID, state)
    assert len(calls) == 1
    assert next(iter(state.load()['intents'].values()))['state'] == 'UNKNOWN'


def test_oversized_input_is_bounded_before_decode_or_browser_call(tmp_path, monkeypatch):
    from agent.services import flow_browser_upload as upload
    monkeypatch.setattr(upload, 'MAX_IMAGE_BYTES', 16)
    path = tmp_path/'ref.png'
    path.write_bytes(b'x' * 17)
    browser, calls = session({})
    state = BrowserStateStore(tmp_path/'state.json', 'test-profile')
    with pytest.raises(ValueError, match='IMAGE_SIZE_INVALID'):
        upload_reference(browser, path, PID, state)
    assert calls == []
    assert not state.path.exists()
