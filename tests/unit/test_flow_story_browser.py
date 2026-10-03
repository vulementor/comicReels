import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_story_browser import model_label, verified_native_submit

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

    from agent.services.flow_story_browser import FlowStoryBrowser, ProductionPaused
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


def resume_req():
    return {
        'source_sha256':'a'*64,
        'resume_job_id':'b'*32,
        'resume_evidence_sha256':'c'*64,
    }


def resume_authorization(*,operation_id='flow-op-1',quoted=7,maximum=14):
    req=resume_req()
    return {
        'schema_version':1,
        'action':'resume_failed_analysis',
        'authorization_id':'auth_1234567890123456',
        'job_id':req['resume_job_id'],
        'authorized_by':'owner-test',
        'authorized_at':'2026-10-03T00:00:00+00:00',
        'source_sha256':req['source_sha256'],
        'evidence_sha256':req['resume_evidence_sha256'],
        'budget':{
            'provider':'google_flow',
            'action':'native_video_generate',
            'currency':'flow_credits',
            'operation':'resume_failed_analysis',
            'stage':'video',
            'operation_id':operation_id,
            'job_id':req['resume_job_id'],
            'source_sha256':req['source_sha256'],
            'evidence_sha256':req['resume_evidence_sha256'],
            'quote_id':'flow-quote-current',
            'quoted_cost_credits':quoted,
            'max_cost_credits':maximum,
        },
    }


def test_resume_budget_contract_binds_provider_action_currency_job_source_and_evidence():
    from agent.services.flow_story_browser import _budget_contract
    req=resume_req()
    auth=resume_authorization()
    contract=_budget_contract(auth,req)
    assert contract['provider']=='google_flow'
    assert contract['action']=='native_video_generate'
    assert contract['currency']=='flow_credits'
    assert contract['operation']=='resume_failed_analysis'
    assert contract['stage']=='video'
    assert contract['job_id']==req['resume_job_id']
    assert contract['source_sha256']==req['source_sha256']
    assert contract['evidence_sha256']==req['resume_evidence_sha256']
    assert contract['quoted_cost_credits']==7
    assert contract['max_cost_credits']==14


@pytest.mark.parametrize('mutate',[
    lambda a:a['budget'].__setitem__('provider','other'),
    lambda a:a['budget'].__setitem__('currency','usd'),
    lambda a:a['budget'].__setitem__('stage','images'),
    lambda a:a['budget'].__setitem__('job_id','d'*32),
    lambda a:a['budget'].__setitem__('source_sha256','e'*64),
    lambda a:a['budget'].__setitem__('evidence_sha256','f'*64),
    lambda a:a['budget'].__setitem__('quoted_cost_credits',0),
])
def test_resume_budget_contract_rejects_unbound_or_zero_budget(mutate):
    from agent.services.flow_story_browser import _budget_contract
    auth=resume_authorization()
    mutate(auth)
    with pytest.raises(ValueError):
        _budget_contract(auth,resume_req())


def test_budget_ledger_reserves_before_effect_and_counts_unknown_against_cap(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger
    contract=_budget_contract(resume_authorization(operation_id='one',quoted=7,maximum=10),resume_req())
    ledger=_BudgetLedger(tmp_path,contract)
    row=ledger.reserve(7,100)
    assert row['state']=='RESERVED'
    persisted=json.loads((tmp_path/'budget-ledger.json').read_text())
    assert persisted['reservations']['one']['state']=='RESERVED'
    ledger.mark_unknown()
    persisted=json.loads((tmp_path/'budget-ledger.json').read_text())
    assert persisted['reservations']['one']['state']=='UNKNOWN'
    with pytest.raises(ValueError,match='OUTCOME_UNKNOWN'):
        ledger.reserve(7,100)

    second=_budget_contract(
        resume_authorization(operation_id='two',quoted=4,maximum=10),resume_req())
    with pytest.raises(ValueError,match='CAP_EXCEEDED'):
        _BudgetLedger(tmp_path,second).reserve(4,100)


def test_budget_ledger_requires_exact_current_ui_quote_and_commits_known_submit(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger
    contract=_budget_contract(resume_authorization(),resume_req())
    ledger=_BudgetLedger(tmp_path,contract)
    with pytest.raises(ValueError,match='CURRENT_QUOTE_CHANGED'):
        ledger.reserve(8,100)
    ledger.reserve(7,100)
    receipt={'media_id':'1'*36,'workflow_id':'2'*36,'project_id':'3'*36}
    committed=ledger.commit(receipt)
    assert committed['state']=='COMMITTED'
    assert committed['spent_cost_credits']==7
    again=ledger.reconcile_known_submit(receipt)
    assert again['state']=='COMMITTED'


def test_budget_ledger_missing_submit_receipt_never_reopens_committed_effect(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger
    contract=_budget_contract(resume_authorization(),resume_req())
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100)
    receipt={'media_id':'1'*36,'workflow_id':'2'*36,'project_id':'3'*36}
    ledger.commit(receipt)
    replay=ledger.reserve(7,100)
    assert replay['already_committed'] is True


def test_authorized_run_reserves_budget_before_native_submit_click(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from agent.services import flow_story_browser as flow

    source=tmp_path/'source.png';source.write_bytes(b'source')
    child=tmp_path/'child.png';child.write_bytes(b'child')
    video=tmp_path/'video.mp4';video.write_bytes(b'video')
    req=resume_req()|{
        'source':str(source),
        'images':{'files':[{'path':str(child),'sha256':'d'*64}]},
        'analysis':{'panels':[{'display_order':0,'dialogues':[]}]},
        'image_review':{'data':{'dialogues_verified':True}},
    }
    auth=resume_authorization()
    events=[]
    page=MagicMock()
    page.get_by_role.return_value.wait_for.return_value=None
    page.locator.return_value.fill.return_value=None
    response=SimpleNamespace(
        status=200,
        body=lambda:b'body',
        request=SimpleNamespace(post_data='post'))
    pending=MagicMock()
    pending.__enter__.return_value=SimpleNamespace(value=response)
    pending.__exit__.return_value=False
    page.expect_response.return_value=pending

    def role(kind,**kwargs):
        button=MagicMock()
        if kind=='button' and kwargs.get('name')=='Bắt đầu tạo':
            def press(_key):
                ledger=json.loads((tmp_path/'flow'/'budget-ledger.json').read_text())
                assert ledger['reservations']['flow-op-1']['state']=='RESERVED'
                assert (tmp_path/'flow'/'story-receipt.json').is_file()
                events.append('click')
            button.press.side_effect=press
        return button
    page.get_by_role.side_effect=role
    provider=SimpleNamespace(session=SimpleNamespace(page=page),close=lambda:events.append('close'))
    monkeypatch.setattr(flow,'FlowBrowserSessionProvider',
                        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(flow.FlowProfileConfig,'load',lambda _:None)
    monkeypatch.setattr(flow,'observe_flow_account',lambda _:SimpleNamespace(state='authenticated'))
    monkeypatch.setattr(flow,'BrowserStateStore',lambda *args,**kwargs:SimpleNamespace())
    monkeypatch.setattr(flow,'upload_reference',lambda *args:REFS[0])
    monkeypatch.setattr(flow,'attach_existing_references',lambda *args:None)
    monkeypatch.setattr(flow,'verify_reference_composer',
                        lambda *args:{'ordered_reference_ids':[REFS[0]]})
    monkeypatch.setattr(flow,'story_video_prompt',lambda *args,**kwargs:'prompt')
    monkeypatch.setattr(flow,'verified_native_submit',
                        lambda *args:{'media_id':REFS[1],'workflow_id':REFS[0],'project_id':PROJECT})

    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    settings=SimpleNamespace(enabled=True,directory=tmp_path)
    operation=flow.FlowStoryBrowser(settings,runtime)
    monkeypatch.setattr(operation,'_prepare',lambda _page:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_current_quote',lambda _page:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_check_enabled',lambda:None)
    monkeypatch.setattr(operation,'_wait',lambda *args:None)
    monkeypatch.setattr(operation,'_download',
                        lambda *args,**kwargs:{'path':str(video),'data':{'highest':False}})

    result=operation.run('video',req,tmp_path,lambda _:None,authorization=auth)
    assert result['state']=='verified'
    assert events==['click','close']
    ledger=json.loads((tmp_path/'flow'/'budget-ledger.json').read_text())
    row=ledger['reservations']['flow-op-1']
    assert row['state']=='COMMITTED'
    assert row['spent_cost_credits']==7
