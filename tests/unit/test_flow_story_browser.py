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
    monkeypatch.setattr(operation,'_prepare',lambda _page:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_current_quote',lambda _page:{'credits':100,'quoted_cost':7})
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
    monkeypatch.setattr(operation,'_prepare',lambda _page:{'credits':100,'quoted_cost':7})
    monkeypatch.setattr(operation,'_current_quote',
                        lambda _page:pytest.fail('quote must not be read after account mismatch'))
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
    monkeypatch.setattr(operation,'_prepare',lambda _page:{'credits':100,'quoted_cost':8})
    monkeypatch.setattr(operation,'_current_quote',lambda _page:{'credits':100,'quoted_cost':8})
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
        authorization=resume_authorization(quoted=8,maximum=14))
    assert second['state']=='verified'
    assert events==['click']
    assert (tmp_path/'flow'/'paid-submit-intent.json').is_file()
