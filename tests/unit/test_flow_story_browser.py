import json
from pathlib import Path
from urllib.parse import urlencode
import pytest
from agent.services import flow_batch as fb
from agent.services.flow_story_browser import verified_native_submit, model_label

PROJECT='11111111-2222-3333-4444-555555555555'
REFS=['aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee','11111111-aaaa-bbbb-cccc-dddddddddddd']


def test_observed_model_dropdown_icon_is_not_a_model_change():
    assert model_label('Omni 1.1 Flash\narrow_drop_down')=='Omni 1.1 Flash'
    assert model_label('Omni 1.1 Flash')=='Omni 1.1 Flash'
    assert model_label('Veo 3.1\narrow_drop_down')!='Omni 1.1 Flash'
    assert model_label('Omni 1.1 Flash 2\narrow_drop_down')!='Omni 1.1 Flash'


def native(*,mutate=None,records=1):
    intent={'project_id':PROJECT,'prompt':'MỘT câu chuyện.','ordered_reference_ids':REFS}
    envelope=json.loads(fb.omni_reference_video_request(intent['prompt'],PROJECT,REFS,
                duration_s=10,resolution='360p',aspect=fb.VIDEO_ASPECT_PORTRAIT))
    inner=json.loads(envelope[0][0][1])
    if mutate: mutate(inner)
    envelope[0][0][1]=json.dumps(inner)
    payload=json.loads((Path(__file__).parents[1]/'fixtures/flow_native_reference_submit.json').read_text())
    payload[3]=payload[3]*records
    body=json.dumps([['wrb.fr','MZZa6b',json.dumps(payload)]])
    return body,urlencode({'f.req':json.dumps(envelope)}),intent


def test_exact_native_one_story_receipt():
    assert verified_native_submit(*native())['project_id']==PROJECT


@pytest.mark.parametrize('mutate',[
    lambda r:r[0].append(r[0][0]),
    lambda r:r[0][0].__setitem__(2,'abra_r2v_8s_360p'),
    lambda r:r[0][0].__setitem__(3,2),
    lambda r:r[0][0][1].reverse(),
    lambda r:r[1].__setitem__(5,REFS[0]),
])
def test_mismatched_native_effect_is_not_adopted(mutate):
    with pytest.raises(ValueError): verified_native_submit(*native(mutate=mutate))


def test_multiple_native_variants_are_rejected():
    with pytest.raises(ValueError,match='VARIANTS'): verified_native_submit(*native(records=2))


def observed_menu(page, upscale_enabled=True):
    from unittest.mock import MagicMock
    options = [{'label': '270p\nGIF', 'enabled': True},
               {'label': '360p\nOriginal', 'enabled': True},
               {'label': '720p\nUpscaled', 'enabled': upscale_enabled}]
    items = []
    for option in options:
        item = MagicMock()
        item.inner_text.return_value = option['label']
        item.is_enabled.return_value = option['enabled']
        items.append(item)
    menu = page.get_by_role.return_value
    menu.count.return_value = len(items)
    menu.nth.side_effect = lambda i: items[i]
    menu.is_enabled.return_value = True
    return options


@pytest.mark.parametrize('highest,upscale_enabled,expected',[
    (False,True,'360p Original'),(True,True,'720p Upscaled'),(True,False,'360p Original')])
def test_reopened_download_uses_exact_workflow_and_observed_multiline_menu(
        tmp_path,highest,upscale_enabled,expected,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services.flow_story_browser import FlowStoryBrowser
    page=MagicMock()
    record={'project_id':PROJECT,'workflow_id':REFS[0],'media_id':REFS[1]}
    url='https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    page.url=url
    options = observed_menu(page, upscale_enabled)
    download=page.expect_download.return_value.__enter__.return_value.value
    download.failure.return_value=None
    operation=FlowStoryBrowser(SimpleNamespace(),None)
    monkeypatch.setattr(operation,'_promote_download',lambda *args:{'selected':args[4]})
    assert operation._download(page,record,tmp_path,highest=highest)['selected'].replace('\n',' ')==expected
    page.goto.assert_called_once_with(url,wait_until='domcontentloaded',timeout=60000)
    page.get_by_role.assert_any_call('menuitem',name=expected,exact=True)
    download.save_as.assert_called_once()
    assert json.loads((tmp_path/(('highest' if highest else 'original')+'-menu.json')).read_text())['options'] == options


def test_pause_at_upscale_boundary_has_no_download_intent_or_click(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services.flow_story_browser import FlowStoryBrowser,ProductionPaused
    page=MagicMock()
    record={'project_id':PROJECT,'workflow_id':REFS[0],'media_id':REFS[1]}
    page.url='https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    observed_menu(page)
    operation=FlowStoryBrowser(SimpleNamespace(enabled=False),None)
    with pytest.raises(ProductionPaused):operation._download(page,record,tmp_path,highest=True)
    page.expect_download.assert_not_called()
    assert not (tmp_path/'highest-download.json').exists()


@pytest.mark.parametrize('paid_intent_exists',[False,True])
def test_only_preparation_before_paid_intent_is_retryable(tmp_path,monkeypatch,paid_intent_exists):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services import flow_story_browser as flow
    folder=tmp_path/'flow';folder.mkdir()
    receipt=folder/'story-receipt.json'
    if paid_intent_exists:receipt.write_text('{}')
    monkeypatch.setattr(flow,'StoryReceipt',lambda path:SimpleNamespace(path=path,load=lambda:{'state':'PROCESSING'}))
    provider=MagicMock();provider.open.return_value=provider
    monkeypatch.setattr(flow,'FlowBrowserSessionProvider',lambda *a,**k:provider)
    monkeypatch.setattr(flow.FlowProfileConfig,'load',lambda _:None)
    monkeypatch.setattr(flow,'observe_flow_account',lambda _:SimpleNamespace(state='authenticated'))
    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    operation=flow.FlowStoryBrowser(SimpleNamespace(),runtime)
    def fail(*a):raise TimeoutError('private provider diagnostic')
    monkeypatch.setattr(operation,'_prepare',fail)
    monkeypatch.setattr(operation,'_wait',fail)
    if paid_intent_exists:
        result = operation.run('video',{},tmp_path,lambda _:None)
        assert result['state'] == 'uncertain' and result['reason'] == 'FLOW_POLL_FAILED'
        assert result['step'] == 'poll' and 'private' not in json.dumps(result)
        assert json.loads((folder/'video-error.json').read_text())['reason'] == 'FLOW_POLL_FAILED'
        assert not (folder/'preparation-error.json').exists()
    else:
        result=operation.run('video',{},tmp_path,lambda _:None)
        assert result['state']=='blocked' and result['not_submitted'] is True
        assert 'private' not in (folder/'preparation-error.json').read_text()
    provider.close.assert_called_once()

def test_rpc_failure_keeps_safe_diagnostic_in_unknown_stage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services import flow_story_browser as flow
    from agent.thoremix.story_stages import StageJournal, StageUncertain
    folder = tmp_path/'flow'; folder.mkdir()
    (folder/'story-receipt.json').write_text('{}')
    record = {'state': 'PROCESSING', 'project_id': PROJECT, 'workflow_id': REFS[0], 'media_id': REFS[1]}
    monkeypatch.setattr(flow, 'StoryReceipt', lambda path: SimpleNamespace(path=path, load=lambda:record))
    provider = MagicMock(); provider.open.return_value = provider
    page = provider.session.page
    page.url = 'https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    page.evaluate.return_value = {'status':409, 'error':'SESSION_UNVERIFIED',
                                 'private':'must-not-leak', 'data':'signed-url'}
    monkeypatch.setattr(flow, 'FlowBrowserSessionProvider', lambda *a,**k:provider)
    monkeypatch.setattr(flow.FlowProfileConfig, 'load', lambda _:None)
    monkeypatch.setattr(flow, 'observe_flow_account', lambda _:SimpleNamespace(state='authenticated'))
    operation = flow.FlowStoryBrowser(SimpleNamespace(),
        SimpleNamespace(flow_profile_config='config', flow_project_id=PROJECT))
    journal = StageJournal(tmp_path, source_sha256='a'*64)
    with pytest.raises(StageUncertain):
        journal.run('video', {}, lambda progress:operation.run('video', {}, tmp_path, progress))
    stage = json.loads((tmp_path/'video.json').read_text())
    assert stage['state'] == 'UNKNOWN'
    assert stage['progress']['preparation_step'] == 'poll'
    diagnostic = json.loads((folder/'video-error.json').read_text())
    assert stage['result']['reason'] == diagnostic['reason'] == 'POLL_BODY_INCOMPLETE'
    assert diagnostic['rpc'] == {'phase':'poll', 'rpcid':'jwpduf', 'route_match':False,
                                 'status':409, 'error':'SESSION_UNVERIFIED', 'body_complete':False}
    assert 'signed-url' not in json.dumps(stage) and 'must-not-leak' not in json.dumps(diagnostic)
    provider.close.assert_called_once()


def test_selection_disabled_after_observation_has_no_intent(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services.flow_story_browser import FlowStoryBrowser
    page = MagicMock()
    observed_menu(page)
    page.get_by_role.return_value.is_enabled.return_value = False
    record = {'project_id':PROJECT, 'workflow_id':REFS[0], 'media_id':REFS[1]}
    page.url = 'https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    with pytest.raises(ValueError, match='DOWNLOAD_OPTION_CHANGED'):
        FlowStoryBrowser(SimpleNamespace(), None)._download(page, record, tmp_path, highest=True)
    page.expect_download.assert_not_called()
    assert not (tmp_path/'highest-download.json').exists()
