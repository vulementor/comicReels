import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_story_browser import model_label, verified_native_submit

PROJECT='11111111-2222-3333-4444-555555555555'
REFS=['aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee','11111111-aaaa-bbbb-cccc-dddddddddddd']
ACCOUNT='owner@example.com'
ACCOUNT_SHA=hashlib.sha256(ACCOUNT.casefold().encode()).hexdigest()
PROFILE='flow-browser'
AGGREGATE='story-aggregate-1'
AGGREGATE_AUTH='9'*64


def test_observed_model_dropdown_icon_is_not_a_model_change():
    assert model_label('Omni 1.1 Flash\narrow_drop_down')=='Omni 1.1 Flash'
    assert model_label('Omni 1.1 Flash')=='Omni 1.1 Flash'
    assert model_label('Veo 3.1\narrow_drop_down')!='Omni 1.1 Flash'
    assert model_label('Omni 1.1 Flash 2\narrow_drop_down')!='Omni 1.1 Flash'


def native(*,duration=10,mutate=None,records=1):
    intent={
        'project_id':PROJECT,'prompt':'synthetic-story-prompt',
        'ordered_reference_ids':REFS,'duration_s':duration,
        'model':'Omni 1.1 Flash','resolution':'360p',
        'outputs_per_request':1,'variants':1,'variant_label':'x1',
    }
    envelope=json.loads(fb.omni_reference_video_request(
        intent['prompt'],PROJECT,REFS,duration_s=duration,
        resolution='360p',aspect=fb.VIDEO_ASPECT_PORTRAIT))
    inner=json.loads(envelope[0][0][1])
    if mutate: mutate(inner)
    envelope[0][0][1]=json.dumps(inner)
    payload=json.loads((Path(__file__).parents[1]/'fixtures/flow_native_reference_submit.json').read_text())
    payload[3]=payload[3]*records
    body=json.dumps([['wrb.fr','MZZa6b',json.dumps(payload)]])
    return body,urlencode({'f.req':json.dumps(envelope)}),intent


@pytest.mark.parametrize('duration',[4,6,8,10])
def test_exact_native_one_story_receipt(duration):
    assert verified_native_submit(*native(duration=duration))['project_id']==PROJECT


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


def resume_authorization(
        *,operation_id='flow-op-1',quoted=7,maximum=14,
        evidence_sha='c'*64,authorization_id='auth_1234567890123456',
        aggregate_id=AGGREGATE,account_sha=ACCOUNT_SHA,
        profile=PROFILE,project=PROJECT):
    req=resume_req()|{'resume_evidence_sha256':evidence_sha}
    return {
        'schema_version':1,
        'action':'resume_failed_analysis',
        'authorization_id':authorization_id,
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
            'quote_id':'flow-quote-current-'+operation_id,
            'aggregate_id':aggregate_id,
            'aggregate_authorization_sha256':AGGREGATE_AUTH,
            'profile_logical_name':profile,
            'account_identity_sha256':account_sha,
            'project_id':project,
            'quoted_cost_credits':quoted,
            'max_cost_credits':maximum,
        },
    }


def generation(duration,*,operation_id='flow-op-1'):
    costs={4:4,6:5,8:6,10:7}
    return {
        'duration_s':duration,'model':'Omni 1.1 Flash','resolution':'360p',
        'outputs_per_request':1,'variants':1,'variant_label':'x1',
        'quoted_cost_credits':costs[duration],'currency':'flow_credits',
        'quote_id':'flow-quote-current-'+operation_id,
    }


def story_intent(req=None):
    req=req or resume_req()
    return {
        'source_sha256':req['source_sha256'],
        'project_id':PROJECT,
        'ordered_reference_ids':[REFS[0]],
        'prompt':'prompt',
        'duration_s':10,
        'aspect':'9:16',
        'resolution':'360p',
        'model':'Omni 1.1 Flash',
        'variants':1,
    }


def observed_submit_binding(contract,*,identity=ACCOUNT,profile=PROFILE,project=PROJECT,intent=None):
    from types import SimpleNamespace

    from agent.services.flow_story_browser import _observed_submit_binding

    return _observed_submit_binding(
        contract,SimpleNamespace(profile_logical_name=profile),
        SimpleNamespace(state='authenticated',identity=identity),
        project,intent or story_intent())


def story_record(*,intent=None,state='PROCESSING',media_id=REFS[1],workflow_id=REFS[0],project=PROJECT):
    return {
        'schema_version':1,
        'state':state,
        'intent':intent or story_intent(),
        'media_id':media_id,
        'workflow_id':workflow_id,
        'project_id':project,
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
    assert contract['aggregate_id']==AGGREGATE
    assert contract['aggregate_authorization_sha256']==AGGREGATE_AUTH
    assert contract['profile_logical_name']==PROFILE
    assert contract['account_identity_sha256']==ACCOUNT_SHA
    assert contract['project_id']==PROJECT
    assert contract['quoted_cost_credits']==7
    assert contract['max_cost_credits']==14


@pytest.mark.parametrize('mutate',[
    lambda a:a['budget'].__setitem__('provider','other'),
    lambda a:a['budget'].__setitem__('currency','usd'),
    lambda a:a['budget'].__setitem__('stage','images'),
    lambda a:a['budget'].__setitem__('job_id','d'*32),
    lambda a:a['budget'].__setitem__('source_sha256','e'*64),
    lambda a:a['budget'].__setitem__('evidence_sha256','f'*64),
    lambda a:a['budget'].__setitem__('aggregate_id','bad aggregate'),
    lambda a:a['budget'].__setitem__('aggregate_authorization_sha256','0'*63),
    lambda a:a['budget'].__setitem__('account_identity_sha256','1'*63),
    lambda a:a['budget'].__setitem__('profile_logical_name','bad profile'),
    lambda a:a['budget'].__setitem__('project_id','not-a-project'),
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

    first=_budget_contract(
        resume_authorization(operation_id='one',quoted=7,maximum=10),resume_req())
    first_binding=observed_submit_binding(first)
    ledger=_BudgetLedger(tmp_path,first)
    row=ledger.reserve(7,100,first_binding)
    assert row['state']=='RESERVED'
    persisted=json.loads((tmp_path/'budget-ledger.json').read_text())
    assert persisted['reservations']['one']['state']=='RESERVED'
    ledger.mark_unknown()
    persisted=json.loads((tmp_path/'budget-ledger.json').read_text())
    assert persisted['reservations']['one']['state']=='UNKNOWN'
    with pytest.raises(ValueError,match='OUTCOME_UNKNOWN'):
        ledger.reserve(7,100,first_binding)

    second_req=resume_req()|{'resume_evidence_sha256':'d'*64}
    second=_budget_contract(
        resume_authorization(
            operation_id='two',quoted=4,maximum=10,evidence_sha='d'*64,
            authorization_id='auth_abcdefghijklmnop'),
        second_req)
    second_binding=observed_submit_binding(second)
    with pytest.raises(ValueError,match='CAP_EXCEEDED'):
        _BudgetLedger(tmp_path,second).reserve(4,100,second_binding)


def test_budget_ledger_requires_exact_current_ui_quote_and_commits_known_submit(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    with pytest.raises(ValueError,match='CURRENT_QUOTE_CHANGED'):
        ledger.reserve(8,100,binding)
    ledger.reserve(7,100,binding)
    record=story_record()
    committed=ledger.commit(record,binding)
    assert committed['state']=='COMMITTED'
    assert committed['spent_cost_credits']==7
    again=ledger.reconcile_known_submit(record,binding)
    assert again['state']=='COMMITTED'


def test_budget_ledger_missing_submit_receipt_never_reopens_committed_effect(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100,binding)
    ledger.commit(story_record(),binding)
    replay=ledger.reserve(7,100,binding)
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
    ledger_path=(
        tmp_path/'data'/'flow-budget-ledgers'/req['resume_job_id']/AGGREGATE/
        'budget-ledger.json')
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
                ledger=json.loads(ledger_path.read_text())
                assert ledger['reservations']['flow-op-1']['state']=='RESERVED'
                assert (tmp_path/'flow'/'paid-submit-intent.json').is_file()
                assert (tmp_path/'flow'/'story-receipt.json').is_file()
                events.append('click')
            button.press.side_effect=press
        return button
    page.get_by_role.side_effect=role
    provider=SimpleNamespace(session=SimpleNamespace(page=page),close=lambda:events.append('close'))
    monkeypatch.setattr(flow,'FlowBrowserSessionProvider',
                        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(
        flow.FlowProfileConfig,'load',
        lambda _:SimpleNamespace(profile_logical_name=PROFILE))
    monkeypatch.setattr(
        flow,'observe_flow_account',
        lambda _:SimpleNamespace(state='authenticated',identity=ACCOUNT))
    monkeypatch.setattr(flow,'BrowserStateStore',lambda *args,**kwargs:SimpleNamespace())
    monkeypatch.setattr(flow,'upload_reference',lambda *args:REFS[0])
    monkeypatch.setattr(flow,'attach_existing_references',lambda *args:None)
    monkeypatch.setattr(flow,'verify_reference_composer',
                        lambda *args:{'ordered_reference_ids':[REFS[0]]})
    monkeypatch.setattr(flow,'story_video_prompt',lambda *args,**kwargs:'prompt')
    monkeypatch.setattr(flow,'verified_native_submit',
                        lambda *args:{'media_id':REFS[1],'workflow_id':REFS[0],'project_id':PROJECT})

    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    settings=SimpleNamespace(enabled=True,directory=tmp_path,data=tmp_path/'data')
    operation=flow.FlowStoryBrowser(settings,runtime)
    monkeypatch.setattr(operation,'_prepare',lambda _page,_generation:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_current_quote',lambda _page,_generation:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_check_enabled',lambda:None)
    monkeypatch.setattr(operation,'_wait',lambda *args:None)
    monkeypatch.setattr(operation,'_download',
                        lambda *args,**kwargs:{'path':str(video),'data':{'highest':False}})

    result=operation.run('video',req,tmp_path,lambda _:None,authorization=auth)
    assert result['state']=='verified'
    assert events==['click','close']
    ledger=json.loads(ledger_path.read_text())
    row=ledger['reservations']['flow-op-1']
    assert row['state']=='COMMITTED'
    assert row['spent_cost_credits']==7


def test_budget_ledger_folder_is_aggregate_scoped_not_segment_scoped(tmp_path):
    from types import SimpleNamespace

    from agent.services.flow_story_browser import (
        _budget_contract,
        _budget_ledger_folder,
    )

    settings=SimpleNamespace(data=tmp_path/'data',directory=tmp_path)
    first=_budget_contract(
        resume_authorization(operation_id='segment-a',maximum=20),resume_req())
    second_req=resume_req()|{'resume_evidence_sha256':'d'*64}
    second=_budget_contract(
        resume_authorization(
            operation_id='segment-b',maximum=20,evidence_sha='d'*64,
            authorization_id='auth_abcdefghijklmnop'),
        second_req)
    first_path=_budget_ledger_folder(settings,first)
    second_path=_budget_ledger_folder(settings,second)
    assert first_path==second_path
    assert first_path==(
        tmp_path/'data'/'flow-budget-ledgers'/resume_req()['resume_job_id']/AGGREGATE)


@pytest.mark.parametrize(('field','value'),[
    ('state','BROKEN'),
    ('reserved_cost_credits',0),
    ('reserved_cost_credits',-1),
    ('reserved_cost_credits',float('nan')),
    ('reserved_cost_credits',float('inf')),
])
def test_budget_ledger_rejects_malformed_persisted_entry(tmp_path,field,value):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100,binding)
    persisted=json.loads(ledger.path.read_text())
    persisted['reservations']['flow-op-1'][field]=value
    ledger.path.write_text(json.dumps(persisted),encoding='utf-8')
    with pytest.raises(ValueError,match='FLOW_BUDGET_LEDGER_INVALID'):
        ledger.reserve(7,100,binding)


def test_budget_ledger_rejects_non_object_persisted_entry(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100,binding)
    persisted=json.loads(ledger.path.read_text())
    persisted['reservations']['flow-op-1']=[]
    ledger.path.write_text(json.dumps(persisted),encoding='utf-8')
    with pytest.raises(ValueError,match='FLOW_BUDGET_LEDGER_INVALID'):
        ledger.reserve(7,100,binding)


@pytest.mark.parametrize(('identity','profile','project','reason'),[
    ('other@example.com',PROFILE,PROJECT,'FLOW_ACCOUNT_IDENTITY_MISMATCH'),
    (ACCOUNT,'other-profile',PROJECT,'FLOW_PROFILE_IDENTITY_MISMATCH'),
    (ACCOUNT,PROFILE,'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee','FLOW_PROJECT_IDENTITY_MISMATCH'),
])
def test_submit_binding_rejects_cross_account_profile_or_project(
        identity,profile,project,reason):
    from agent.services.flow_story_browser import _budget_contract

    contract=_budget_contract(resume_authorization(),resume_req())
    with pytest.raises(ValueError,match=reason):
        observed_submit_binding(
            contract,identity=identity,profile=profile,project=project)


def test_durable_submit_intent_is_exact_and_idempotent(tmp_path):
    from agent.services.flow_story_browser import (
        _bind_submit_intent,
        _budget_contract,
    )

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    path=tmp_path/'paid-submit-intent.json'
    assert _bind_submit_intent(path,binding)==binding
    original=path.read_bytes()
    assert _bind_submit_intent(path,binding)==binding
    assert path.read_bytes()==original

    changed=dict(binding,quote_id='other-quote')
    with pytest.raises(ValueError,match='FLOW_SUBMIT_INTENT_MISMATCH'):
        _bind_submit_intent(path,changed)
    assert path.read_bytes()==original


@pytest.mark.parametrize(('record','reason'),[
    (story_record(media_id='not-a-uuid'),'FLOW_BUDGET_SUBMIT_RECEIPT_INVALID'),
    (story_record(project='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
     'FLOW_BUDGET_SUBMIT_RECEIPT_INVALID'),
    (story_record(intent={**story_intent(),'prompt':'changed'}),
     'FLOW_BUDGET_SUBMIT_RECEIPT_INVALID'),
])
def test_budget_reconciliation_requires_exact_story_receipt(record,reason,tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100,binding)
    with pytest.raises(ValueError,match=reason):
        ledger.reconcile_known_submit(record,binding)


def test_cross_account_or_project_cannot_reuse_aggregate_ledger(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    first=_budget_contract(resume_authorization(operation_id='one'),resume_req())
    binding=observed_submit_binding(first)
    ledger=_BudgetLedger(tmp_path,first)
    ledger.reserve(7,100,binding)

    wrong_account=_budget_contract(
        resume_authorization(
            operation_id='two',account_sha='0'*64,
            authorization_id='auth_abcdefghijklmnop'),
        resume_req())
    with pytest.raises(ValueError,match='FLOW_BUDGET_RESERVATION_MISMATCH'):
        _BudgetLedger(tmp_path,wrong_account)._load()

    wrong_project=_budget_contract(
        resume_authorization(
            operation_id='two',project='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            authorization_id='auth_abcdefghijklmnop'),
        resume_req())
    with pytest.raises(ValueError,match='FLOW_BUDGET_RESERVATION_MISMATCH'):
        _BudgetLedger(tmp_path,wrong_project)._load()


def test_committed_replay_requires_exact_receipt_ids(tmp_path):
    from agent.services.flow_story_browser import _budget_contract, _BudgetLedger

    contract=_budget_contract(resume_authorization(),resume_req())
    binding=observed_submit_binding(contract)
    ledger=_BudgetLedger(tmp_path,contract)
    ledger.reserve(7,100,binding)
    original=story_record()
    ledger.commit(original,binding)

    assert ledger.reconcile_known_submit(original,binding)['state']=='COMMITTED'
    different=story_record(media_id='22222222-aaaa-bbbb-cccc-dddddddddddd')
    with pytest.raises(ValueError,match='FLOW_BUDGET_COMMITTED_RECEIPT_MISMATCH'):
        ledger.reconcile_known_submit(different,binding)


def test_account_change_before_submit_blocks_without_reservation_or_click(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from agent.services import flow_story_browser as flow

    source=tmp_path/'source.png';source.write_bytes(b'source')
    child=tmp_path/'child.png';child.write_bytes(b'child')
    req=resume_req()|{
        'source':str(source),
        'images':{'files':[{'path':str(child),'sha256':'d'*64}]},
        'analysis':{'panels':[{'display_order':0,'dialogues':[]}]},
        'image_review':{'data':{'dialogues_verified':True}},
    }
    auth=resume_authorization()
    page=MagicMock()
    page.get_by_role.return_value.wait_for.return_value=None
    page.locator.return_value.fill.return_value=None
    generate=MagicMock()
    def role(kind,**kwargs):
        if kind=='button' and kwargs.get('name')=='Bắt đầu tạo':
            return generate
        return MagicMock()
    page.get_by_role.side_effect=role
    provider=SimpleNamespace(session=SimpleNamespace(page=page),close=lambda:None)
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(
        flow.FlowProfileConfig,'load',
        lambda _:SimpleNamespace(profile_logical_name=PROFILE))
    observed=iter((
        SimpleNamespace(state='authenticated',identity=ACCOUNT),
        SimpleNamespace(state='authenticated',identity='other@example.com'),
    ))
    monkeypatch.setattr(flow,'observe_flow_account',lambda _page:next(observed))
    monkeypatch.setattr(flow,'BrowserStateStore',lambda *args,**kwargs:SimpleNamespace())
    monkeypatch.setattr(flow,'upload_reference',lambda *args:REFS[0])
    monkeypatch.setattr(flow,'attach_existing_references',lambda *args:None)
    monkeypatch.setattr(
        flow,'verify_reference_composer',
        lambda *args:{'ordered_reference_ids':[REFS[0]]})
    monkeypatch.setattr(flow,'story_video_prompt',lambda *args,**kwargs:'prompt')

    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    settings=SimpleNamespace(enabled=True,directory=tmp_path,data=tmp_path/'data')
    operation=flow.FlowStoryBrowser(settings,runtime)
    monkeypatch.setattr(operation,'_prepare',lambda _page,_generation:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_current_quote',
                        lambda _page,_generation:pytest.fail('quote must not be read after account mismatch'))
    monkeypatch.setattr(operation,'_check_enabled',lambda:None)

    result=operation.run('video',req,tmp_path,lambda _:None,authorization=auth)
    assert result['state']=='blocked'
    assert result['reason']=='FLOW_ACCOUNT_IDENTITY_MISMATCH'
    assert not (tmp_path/'flow'/'paid-submit-intent.json').exists()
    assert not (tmp_path/'data'/'flow-budget-ledgers').exists()
    generate.press.assert_not_called()


def test_rejected_quote_does_not_leave_stale_submit_intent(tmp_path,monkeypatch):
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
    events=[]
    page=MagicMock()
    page.get_by_role.return_value.wait_for.return_value=None
    page.locator.return_value.fill.return_value=None
    response=SimpleNamespace(
        status=200,body=lambda:b'body',
        request=SimpleNamespace(post_data='post'))
    pending=MagicMock()
    pending.__enter__.return_value=SimpleNamespace(value=response)
    pending.__exit__.return_value=False
    page.expect_response.return_value=pending
    def role(kind,**kwargs):
        button=MagicMock()
        if kind=='button' and kwargs.get('name')=='Bắt đầu tạo':
            button.press.side_effect=lambda _key:events.append('click')
        return button
    page.get_by_role.side_effect=role
    provider=SimpleNamespace(session=SimpleNamespace(page=page),close=lambda:None)
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(
        flow.FlowProfileConfig,'load',
        lambda _:SimpleNamespace(profile_logical_name=PROFILE))
    monkeypatch.setattr(
        flow,'observe_flow_account',
        lambda _page:SimpleNamespace(state='authenticated',identity=ACCOUNT))
    monkeypatch.setattr(flow,'BrowserStateStore',lambda *args,**kwargs:SimpleNamespace())
    monkeypatch.setattr(flow,'upload_reference',lambda *args:REFS[0])
    monkeypatch.setattr(flow,'attach_existing_references',lambda *args:None)
    monkeypatch.setattr(
        flow,'verify_reference_composer',
        lambda *args:{'ordered_reference_ids':[REFS[0]]})
    monkeypatch.setattr(flow,'story_video_prompt',lambda *args,**kwargs:'prompt')
    monkeypatch.setattr(
        flow,'verified_native_submit',
        lambda *args:{'media_id':REFS[1],'workflow_id':REFS[0],'project_id':PROJECT})

    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    settings=SimpleNamespace(enabled=True,directory=tmp_path,data=tmp_path/'data')
    operation=flow.FlowStoryBrowser(settings,runtime)
    monkeypatch.setattr(
        operation,'_prepare',
        lambda _page,_generation:{'credits':100,'quoted_cost':7})
    quotes=iter((8,7))
    monkeypatch.setattr(
        operation,'_current_quote',
        lambda _page,_generation:{
            'credits':100,'quoted_cost':next(quotes)})
    monkeypatch.setattr(operation,'_check_enabled',lambda:None)
    monkeypatch.setattr(operation,'_wait',lambda *args:None)
    monkeypatch.setattr(
        operation,'_download',
        lambda *args,**kwargs:{'path':str(video),'data':{'highest':False}})

    first=operation.run(
        'video',req,tmp_path,lambda _:None,
        authorization=resume_authorization(quoted=7,maximum=14))
    assert first['state']=='blocked'
    assert first['reason']=='FLOW_CURRENT_QUOTE_CHANGED'
    assert not (tmp_path/'flow'/'paid-submit-intent.json').exists()
    assert events==[]

    second=operation.run(
        'video',req,tmp_path,lambda _:None,
        authorization=resume_authorization(quoted=7,maximum=14))
    assert second['state']=='verified'
    assert events==['click']
    assert (tmp_path/'flow'/'paid-submit-intent.json').is_file()


def test_generation_contract_binds_observed_mixed_duration_prices():
    from agent.services.flow_story_browser import _generation_contract

    for duration,cost in ((4,4),(6,5),(8,6),(10,7)):
        value=_generation_contract(generation(duration))
        assert value['duration_s']==duration
        assert value['quoted_cost_credits']==float(cost)
        assert value['model']=='Omni 1.1 Flash'
        assert value['resolution']=='360p'
        assert value['outputs_per_request']==1
        assert value['variants']==1
        assert value['variant_label']=='x1'


@pytest.mark.parametrize(('field','value','reason'),[
    ('duration_s',5,'FLOW_GENERATION_CONTRACT_INVALID'),
    ('model','other','FLOW_GENERATION_CONTRACT_INVALID'),
    ('resolution','720p','FLOW_GENERATION_CONTRACT_INVALID'),
    ('outputs_per_request',2,'FLOW_GENERATION_CONTRACT_INVALID'),
    ('variants',2,'FLOW_GENERATION_CONTRACT_INVALID'),
    ('quoted_cost_credits',99,'FLOW_GENERATION_QUOTE_INVALID'),
])
def test_generation_contract_rejects_unsupported_or_mismatched_values(
        field,value,reason):
    from agent.services.flow_story_browser import _generation_contract

    spec=generation(6)
    spec[field]=value
    with pytest.raises(ValueError,match=reason):
        _generation_contract(spec)


class _UiNode:
    def __init__(self,text='',checked=None,on_press=None):
        self._text=text
        self._checked=checked
        self._on_press=on_press
    def press(self,_key):
        if self._checked is not None:
            self._checked=True
        if self._on_press is not None:
            self._on_press()
    def is_checked(self):
        return self._checked
    def inner_text(self):
        return self._text
    def wait_for(self,**_kwargs):
        return None
    def fill(self,_text):
        return None


class _UiDialog:
    def __init__(self,balance):
        self.balance=balance
    def get_by_role(self,kind,**_kwargs):
        assert kind=='link'
        return _UiNode(f'{self.balance} tín dụng Google Flow')


class _UiPage:
    def __init__(self,cost,balance=100):
        from types import SimpleNamespace

        self.cost=cost
        self.balance=balance
        self.radios={}
        self.keyboard=SimpleNamespace(press=lambda _key:None)
    def get_by_role(self,kind,**kwargs):
        name=kwargs.get('name')
        if kind=='dialog':
            return _UiDialog(self.balance)
        if kind=='radio':
            return self.radios.setdefault(name,_UiNode(checked=False))
        if kind=='link':
            return _UiNode(f'{self.cost} tín dụng')
        if kind=='button' and name=='Chọn nhóm mô hình':
            return _UiNode('Omni 1.1 Flash\narrow_drop_down')
        return _UiNode()


@pytest.mark.parametrize(('duration','cost'),[(4,4),(6,5),(8,6),(10,7)])
def test_prepare_and_current_quote_use_exact_duration_ui_and_price(
        duration,cost):
    from types import SimpleNamespace

    from agent.services.flow_story_browser import FlowStoryBrowser

    page=_UiPage(cost)
    operation=FlowStoryBrowser(SimpleNamespace(),None)
    spec=generation(duration)
    ready=operation._prepare(page,spec)
    assert ready['quoted_cost']==cost
    assert ready['duration_s']==duration
    checked_duration_labels=[
        label for label,node in page.radios.items()
        if node.is_checked() is True and label.startswith(f'{duration} ')
    ]
    assert len(checked_duration_labels)==1
    assert page.radios['360p 360p tạo nhanh hơn ở độ phân giải thấp hơn'].is_checked() is True
    assert page.radios['x1'].is_checked() is True
    current=operation._current_quote(page,spec)
    assert current['quoted_cost']==cost
    assert current['duration_s']==duration
    assert current['model']=='Omni 1.1 Flash'
    assert current['resolution']=='360p'
    assert current['variants']==1


def test_current_quote_change_is_rejected_before_reservation():
    from types import SimpleNamespace

    from agent.services.flow_story_browser import FlowStoryBrowser

    page=_UiPage(6)
    operation=FlowStoryBrowser(SimpleNamespace(),None)
    spec=generation(8)
    operation._prepare(page,spec)
    page.cost=7
    with pytest.raises(ValueError,match='FLOW_CURRENT_QUOTE_CHANGED'):
        operation._current_quote(page,spec)


def test_invalid_generation_blocks_before_provider_or_budget_reservation(
        tmp_path,monkeypatch):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path,data=tmp_path/'data'),
        SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT))
    bad=generation(6)
    bad['quoted_cost_credits']=99
    result=operation.run(
        'video',resume_req(),tmp_path,lambda _:None,
        authorization=resume_authorization(quoted=5,maximum=14),
        generation=bad)
    assert result=={
        'state':'blocked','not_submitted':True,
        'reason':'FLOW_GENERATION_QUOTE_INVALID',
    }
    assert not (tmp_path/'data'/'flow-budget-ledgers').exists()


class _PendingResponse:
    def __init__(self,response):
        self.value=response
    def __enter__(self):
        return self
    def __exit__(self,*_args):
        return False


class _RunUiPage(_UiPage):
    def __init__(self,cost,response,on_generate):
        super().__init__(cost)
        self.response=response
        self.on_generate=on_generate
        self.quote_reads=0
        self.expecting_submit=False
    def goto(self,*_args,**_kwargs):
        return None
    def reload(self,*_args,**_kwargs):
        return None
    def locator(self,_selector):
        return _UiNode()
    def expect_response(self,*_args,**_kwargs):
        self.expecting_submit=True
        return _PendingResponse(self.response)
    def get_by_role(self,kind,**kwargs):
        if kind=='button' and self.expecting_submit:
            self.expecting_submit=False
            return _UiNode(on_press=self.on_generate)
        if kind=='link':
            self.quote_reads+=1
        return super().get_by_role(kind,**kwargs)


@pytest.mark.parametrize(('duration','cost'),[(4,4),(6,5),(8,6),(10,7)])
def test_mixed_duration_request_to_receipt_budget_native_and_download_is_exact(
        tmp_path,monkeypatch,duration,cost):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    source=tmp_path/'source.png';source.write_bytes(b'source')
    children=[]
    for index in range(2):
        child=tmp_path/f'child-{index}.png'
        child.write_bytes(f'child-{index}'.encode())
        children.append(child)
    req=resume_req()|{
        'source':str(source),
        'images':{'files':[
            {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in children]},
        'analysis':{'panels':[{'display_order':0,'dialogues':[]}]},
        'image_review':{'data':{'dialogues_verified':True}},
    }
    authorization=resume_authorization(quoted=cost,maximum=14)
    spec=generation(duration)
    body,post_data,_native_intent=native(duration=duration)
    response=SimpleNamespace(
        status=200,body=lambda:body.encode(),
        request=SimpleNamespace(post_data=post_data))
    events=[]
    ledger_path=(
        tmp_path/'data'/'flow-budget-ledgers'/req['resume_job_id']/AGGREGATE/
        'budget-ledger.json')
    def on_generate():
        ledger=json.loads(ledger_path.read_text())
        assert ledger['reservations']['flow-op-1']['state']=='RESERVED'
        assert (tmp_path/'flow'/'paid-submit-intent.json').is_file()
        receipt=json.loads((tmp_path/'flow'/'story-receipt.json').read_text())
        assert receipt['state']=='SUBMITTING'
        assert receipt['intent']['duration_s']==duration
        events.append('click')
    page=_RunUiPage(cost,response,on_generate)
    provider=SimpleNamespace(
        session=SimpleNamespace(page=page),
        close=lambda:events.append('close'))
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(
        flow.FlowProfileConfig,'load',
        lambda _:SimpleNamespace(profile_logical_name=PROFILE))
    auth_reads=[]
    def observe(_page):
        auth_reads.append('read')
        return SimpleNamespace(state='authenticated',identity=ACCOUNT)
    monkeypatch.setattr(flow,'observe_flow_account',observe)
    monkeypatch.setattr(flow,'BrowserStateStore',lambda *args,**kwargs:SimpleNamespace())
    ref_ids=iter(REFS)
    monkeypatch.setattr(flow,'upload_reference',lambda *args:next(ref_ids))
    monkeypatch.setattr(flow,'attach_existing_references',lambda *args:None)
    monkeypatch.setattr(
        flow,'verify_reference_composer',
        lambda *args:{'ordered_reference_ids':REFS})
    monkeypatch.setattr(flow,'story_video_prompt',lambda *args,**kwargs:'synthetic-story-prompt')
    runtime=SimpleNamespace(flow_profile_config='config',flow_project_id=PROJECT)
    settings=SimpleNamespace(enabled=True,directory=tmp_path,data=tmp_path/'data')
    operation=flow.FlowStoryBrowser(settings,runtime)
    monkeypatch.setattr(operation,'_check_enabled',lambda:None)
    monkeypatch.setattr(operation,'_wait',lambda *args:None)
    monkeypatch.setattr(
        flow,'validate_media',
        lambda *_args,**_kwargs:{'width':360,'duration_s':float(duration)})
    def fake_download(_page,record,folder,*,highest):
        assert highest is False
        part=folder/'synthetic.part.mp4';part.write_bytes(b'video-bytes')
        final=folder/'synthetic.mp4'
        receipt_path=folder/'synthetic-download.json'
        return operation._promote_download(
            part,final,receipt_path,record,'360p Original',
            ['360p Original'],False)
    monkeypatch.setattr(operation,'_download',fake_download)

    result=operation.run(
        'video',req,tmp_path,lambda _value:None,
        authorization=authorization,generation=spec)
    assert result['state']=='verified'
    assert result['data']['duration_s']==float(duration)
    assert result['data']['width']==360
    assert events==['click','close']
    assert len(auth_reads)==3
    assert page.quote_reads==2
    checked_duration_labels=[
        label for label,node in page.radios.items()
        if node.is_checked() is True and label.startswith(f'{duration} ')
    ]
    assert len(checked_duration_labels)==1
    story=json.loads((tmp_path/'flow'/'story-receipt.json').read_text())
    assert story['state']=='PROCESSING'
    assert story['intent']['duration_s']==duration
    assert story['intent']['model']=='Omni 1.1 Flash'
    assert story['intent']['resolution']=='360p'
    assert story['intent']['variants']==1
    ledger=json.loads(ledger_path.read_text())
    row=ledger['reservations']['flow-op-1']
    assert row['state']=='COMMITTED'
    assert row['reserved_cost_credits']==float(cost)
    assert row['spent_cost_credits']==float(cost)
    assert row['aggregate_id']==AGGREGATE
    assert row['receipt']=={
        key:story[key] for key in ('media_id','workflow_id','project_id')}


@pytest.mark.parametrize('duration',[True,4.0,'4',None,5])
def test_generation_native_and_promotion_reject_non_integer_or_unsupported_duration(
        tmp_path,monkeypatch,duration):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    spec=generation(4)
    spec['duration_s']=duration
    with pytest.raises(ValueError,match='FLOW_GENERATION_CONTRACT_INVALID'):
        flow._generation_contract(spec)

    body,post_data,intent=native(duration=4)
    intent['duration_s']=duration
    with pytest.raises(ValueError,match='NATIVE_INTENT_INVALID'):
        verified_native_submit(body,post_data,intent)

    operation=flow.FlowStoryBrowser(SimpleNamespace(directory=tmp_path),None)
    part=tmp_path/'part.mp4';part.write_bytes(b'bytes')
    record=story_record(intent=story_intent()|{'duration_s':duration})
    monkeypatch.setattr(
        flow,'validate_media',
        lambda *_args,**_kwargs:pytest.fail('media probe must not run'))
    with pytest.raises(ValueError,match='DOWNLOAD_INTENT_DURATION_INVALID'):
        operation._promote_download(
            part,tmp_path/'final.mp4',tmp_path/'receipt.json',record,
            '360p Original',['360p Original'],False)


@pytest.mark.parametrize('change',[
    lambda record:record.update(state='UNKNOWN'),
    lambda record:record['intent'].__setitem__('duration_s',True),
    lambda record:record['intent'].__setitem__('duration_s',4.0),
    lambda record:record['intent'].__setitem__('duration_s','4'),
    lambda record:record['intent'].__setitem__('duration_s',5),
])
def test_download_existing_rejects_invalid_story_record_before_provider(
        tmp_path,monkeypatch,change):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    record=story_record()
    change(record)
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(flow_project_id=PROJECT,flow_profile_config='config'))
    with pytest.raises(ValueError,match='RECOVERY_STORY_RECEIPT_INVALID'):
        operation.download_existing(record,tmp_path/'recovery',highest=True)


def test_cached_recovery_duration_mismatch_blocks_before_provider(
        tmp_path,monkeypatch):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    record=story_record()
    folder=tmp_path/'recovery';folder.mkdir()
    final=folder/'highest.mp4';final.write_bytes(b'cached-video')
    receipt={
        'state':'COMPLETED',
        **{key:record[key] for key in ('media_id','project_id','workflow_id')},
        'artifact':flow.artifact(final),
        'data':{
            'selected_resolution':'720p existing Flow derivative',
            'highest':True,'width':720,'duration_s':10.0,
        },
    }
    (folder/'highest-download.json').write_text(json.dumps(receipt),encoding='utf-8')
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    monkeypatch.setattr(
        flow,'validate_media',
        lambda *_args,**_kwargs:{'width':720,'duration_s':8.0})
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(flow_project_id=PROJECT,flow_profile_config='config'))
    with pytest.raises(ValueError,match='RECOVERY_DOWNLOAD_MEDIA_MISMATCH'):
        operation.download_existing(record,folder,highest=True)


def test_corrupt_cached_recovery_receipt_blocks_before_provider(
        tmp_path,monkeypatch):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    folder=tmp_path/'recovery';folder.mkdir()
    (folder/'highest-download.json').write_text('{',encoding='utf-8')
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(flow_project_id=PROJECT,flow_profile_config='config'))
    with pytest.raises(ValueError,match='RECOVERY_DOWNLOAD_RECEIPT_INVALID'):
        operation.download_existing(story_record(),folder,highest=True)


def _bytes_validated_recovery_fixture(flow,folder,record,*,duration=10):
    part=folder/'highest.part.mp4'
    part.write_bytes(b'validated-recovery-bytes')
    receipt={
        'state':'BYTES_VALIDATED',
        **{key:record[key] for key in ('media_id','project_id','workflow_id')},
        'artifact':flow.artifact(part),
        'data':{
            'selected_resolution':'720p existing Flow derivative',
            'observed_options':['720p existing Flow derivative'],
            'highest':True,'width':720,'duration_s':float(duration),
        },
    }
    receipt_path=folder/'highest-download.json'
    receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
    return part,receipt_path,receipt


@pytest.mark.parametrize('after_rename',[False,True])
def test_download_existing_recovers_bytes_validated_crash_without_provider(
        tmp_path,monkeypatch,after_rename):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    record=story_record(intent=story_intent()|{'duration_s':6})
    folder=tmp_path/'recovery';folder.mkdir()
    part,receipt_path,original=_bytes_validated_recovery_fixture(
        flow,folder,record,duration=6)
    final=folder/'highest.mp4'
    if after_rename:
        part.replace(final)
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    monkeypatch.setattr(
        flow,'validate_media',
        lambda path,**_kwargs:{
            'width':720,'duration_s':6.0,
            'observed_path':str(path)})
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(flow_project_id=PROJECT,flow_profile_config='config'))

    result=operation.download_existing(record,folder,highest=True)
    assert Path(result['path'])==final
    assert final.read_bytes()==b'validated-recovery-bytes'
    assert not part.exists()
    completed=json.loads(receipt_path.read_text(encoding='utf-8'))
    assert completed['state']=='COMPLETED'
    assert completed['artifact']==flow.artifact(final)
    assert completed['data']==original['data']

    before_bytes=final.read_bytes()
    before_receipt=receipt_path.read_bytes()
    replay=operation.download_existing(record,folder,highest=True)
    assert Path(replay['path'])==final
    assert final.read_bytes()==before_bytes
    assert receipt_path.read_bytes()==before_receipt


@pytest.mark.parametrize('kind',[
    'wrong_id','wrong_hash','wrong_path','wrong_duration','final_conflict',
])
def test_bytes_validated_recovery_mismatch_blocks_without_provider_or_overwrite(
        tmp_path,monkeypatch,kind):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow

    record=story_record(intent=story_intent()|{'duration_s':8})
    folder=tmp_path/'recovery';folder.mkdir()
    part,receipt_path,receipt=_bytes_validated_recovery_fixture(
        flow,folder,record,duration=8)
    final=folder/'highest.mp4'
    if kind=='wrong_id':
        receipt['media_id']='22222222-aaaa-bbbb-cccc-dddddddddddd'
    elif kind=='wrong_hash':
        receipt['artifact']['sha256']='0'*64
    elif kind=='wrong_path':
        receipt['artifact']['path']=str(tmp_path/'outside.mp4')
    elif kind=='wrong_duration':
        receipt['data']['duration_s']=6.0
    elif kind=='final_conflict':
        final.write_bytes(b'conflicting-final')
    receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
    part_before=part.read_bytes()
    final_before=final.read_bytes() if final.exists() else None
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:pytest.fail('provider must not open'))
    monkeypatch.setattr(
        flow,'validate_media',
        lambda *_args,**_kwargs:{'width':720,'duration_s':8.0})
    operation=flow.FlowStoryBrowser(
        SimpleNamespace(directory=tmp_path),
        SimpleNamespace(flow_project_id=PROJECT,flow_profile_config='config'))

    expected=(
        'RECOVERY_DOWNLOAD_FINAL_CONFLICT' if kind=='final_conflict'
        else 'RECOVERY_DOWNLOAD_MEDIA_MISMATCH' if kind=='wrong_duration'
        else 'RECOVERY_DOWNLOAD_RECEIPT_INVALID' if kind in {'wrong_id','wrong_path'}
        else 'RECOVERY_DOWNLOAD_BYTES_CHANGED')
    with pytest.raises(ValueError,match=expected):
        operation.download_existing(record,folder,highest=True)
    assert part.read_bytes()==part_before
    if final_before is None:
        assert not final.exists()
    else:
        assert final.read_bytes()==final_before
