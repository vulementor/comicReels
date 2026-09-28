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


@pytest.mark.parametrize('highest,expected',[(False,'360p Original'),(True,'720p Upscaled')])
def test_reopened_download_uses_exact_workflow_and_observed_multiline_menu(tmp_path,highest,expected,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services.flow_story_browser import FlowStoryBrowser
    page=MagicMock()
    record={'project_id':PROJECT,'workflow_id':REFS[0],'media_id':REFS[1]}
    url='https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    page.url=url
    page.get_by_role.return_value.all_inner_texts.return_value=['270p\nGIF','360p\nOriginal','720p\nUpscaled']
    download=page.expect_download.return_value.__enter__.return_value.value
    download.failure.return_value=None
    operation=FlowStoryBrowser(SimpleNamespace(),None)
    monkeypatch.setattr(operation,'_promote_download',lambda *args:{'selected':args[4]})
    assert operation._download(page,record,tmp_path,highest=highest)['selected'].replace('\n',' ')==expected
    page.goto.assert_called_once_with(url,wait_until='domcontentloaded',timeout=60000)
    page.get_by_role.assert_any_call('menuitem',name=expected,exact=True)
    download.save_as.assert_called_once()


def test_pause_at_upscale_boundary_has_no_download_intent_or_click(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from agent.services.flow_story_browser import FlowStoryBrowser,ProductionPaused
    page=MagicMock()
    record={'project_id':PROJECT,'workflow_id':REFS[0],'media_id':REFS[1]}
    page.url='https://flow.google.com/project/'+PROJECT+'/edit/'+REFS[0]
    page.get_by_role.return_value.all_inner_texts.return_value=['360p Original','720p Upscaled']
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
        with pytest.raises(TimeoutError):operation.run('video',{},tmp_path,lambda _:None)
        assert not (folder/'preparation-error.json').exists()
    else:
        result=operation.run('video',{},tmp_path,lambda _:None)
        assert result['state']=='blocked' and result['not_submitted'] is True
        assert 'private' not in (folder/'preparation-error.json').read_text()
    provider.close.assert_called_once()
