"""Observed vi-VN native Flow story workflow under one Camoufox/KBS owner.

The native UI owns paid requests. Read RPCs only poll exact recorded media IDs.
No automatic repeat of a paid submit or an uncertain upscale.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent.comicreels.prompts import story_video_prompt
from agent.comicreels.story import StoryReceipt
from agent.services import flow_batch as fb
from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_semantics import (
    ExistingReference,
    attach_existing_references,
    highest_video_download,
    normalized_prompt,
    verify_reference_composer,
)
from agent.services.flow_browser_session import (
    FlowBrowserSessionProvider,
    FlowProfileConfig,
)
from agent.services.flow_browser_state import BrowserStateStore
from agent.services.flow_browser_upload import upload_reference
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import runner_lock, validate_media
from agent.thoremix.story_operations import artifact


def model_label(text):
    """Native Material dropdown icons can appear in rendered inner_text."""
    return re.sub(r'\s+arrow_drop_down$', '', text.strip())


class ProductionPaused(RuntimeError):
    pass


_VIDEO_CREDITS={4:4,6:5,8:6,10:7}
_VIDEO_MODEL='Omni 1.1 Flash'
_VIDEO_RESOLUTION='360p'
_VIDEO_OUTPUTS=1
_VIDEO_VARIANT_LABEL='x1'


def _generation_contract(generation,budget_contract=None):
    if generation is None:
        generation={
            'duration_s':10,'model':_VIDEO_MODEL,'resolution':_VIDEO_RESOLUTION,
            'outputs_per_request':_VIDEO_OUTPUTS,'variants':1,
            'variant_label':_VIDEO_VARIANT_LABEL,
            'quoted_cost_credits':(
                budget_contract.get('quoted_cost_credits')
                if isinstance(budget_contract,dict) else None),
            'currency':'flow_credits',
            'quote_id':(
                budget_contract.get('quote_id')
                if isinstance(budget_contract,dict) else None),
        }
    if not isinstance(generation,dict):
        raise TypeError('FLOW_GENERATION_CONTRACT_INVALID')
    duration=generation.get('duration_s')
    cost=generation.get('quoted_cost_credits')
    if (type(duration) is not int or duration not in _VIDEO_CREDITS
            or generation.get('model')!=_VIDEO_MODEL
            or generation.get('resolution')!=_VIDEO_RESOLUTION
            or generation.get('outputs_per_request')!=_VIDEO_OUTPUTS
            or generation.get('variants')!=1
            or generation.get('variant_label')!=_VIDEO_VARIANT_LABEL
            or generation.get('currency')!='flow_credits'):
        raise ValueError('FLOW_GENERATION_CONTRACT_INVALID')
    if (cost is not None
            and (isinstance(cost,bool) or not isinstance(cost,(int,float))
                 or not math.isfinite(float(cost))
                 or float(cost)!=float(_VIDEO_CREDITS[duration]))):
        raise ValueError('FLOW_GENERATION_QUOTE_INVALID')
    quote_id=generation.get('quote_id')
    if quote_id is not None and (
            not isinstance(quote_id,str) or not quote_id.strip() or len(quote_id)>200):
        raise ValueError('FLOW_GENERATION_QUOTE_INVALID')
    if (budget_contract is not None
            and (float(_VIDEO_CREDITS[duration])!=budget_contract['quoted_cost_credits']
                 or quote_id!=budget_contract['quote_id'])):
        raise ValueError('FLOW_GENERATION_BUDGET_MISMATCH')
    return {
        'duration_s':duration,'model':_VIDEO_MODEL,'resolution':_VIDEO_RESOLUTION,
        'outputs_per_request':_VIDEO_OUTPUTS,'variants':1,
        'variant_label':_VIDEO_VARIANT_LABEL,
        'quoted_cost_credits':(
            float(_VIDEO_CREDITS[duration]) if cost is not None else None),
        'currency':'flow_credits','quote_id':quote_id,
    }


def verified_native_submit(body, post_data, intent):
    duration=intent.get('duration_s')
    if (type(duration) is not int or duration not in _VIDEO_CREDITS
            or intent.get('model')!=_VIDEO_MODEL
            or intent.get('resolution')!=_VIDEO_RESOLUTION
            or intent.get('variants')!=1
            or intent.get('outputs_per_request',1)!=_VIDEO_OUTPUTS
            or intent.get('variant_label',_VIDEO_VARIANT_LABEL)!=_VIDEO_VARIANT_LABEL):
        raise ValueError('NATIVE_INTENT_INVALID')
    expected_model=f'abra_r2v_{duration}s_360p'
    request = json.loads(json.loads(parse_qs(post_data)['f.req'][0])[0][0][1])
    if (len(request[0]) != 1 or request[0][0][2] != expected_model
            or request[0][0][3] != fb.VIDEO_ASPECT_PORTRAIT
            or request[1][5] != intent['project_id']
            or normalized_prompt(request[0][0][0][2][0][0][0]) != normalized_prompt(intent['prompt'])
            or [r[1] for r in request[0][0][1]] != intent['ordered_reference_ids']):
        raise ValueError('NATIVE_SUBMIT_MISMATCH')
    matched = [r for r in fb.parse_envelope(body) if r.rpcid == 'MZZa6b' and not r.error]
    if len(matched) != 1:
        raise ValueError('NATIVE_RECEIPT_MISSING')
    if len(matched[0].data[3]) != 1:
        raise ValueError('NATIVE_VARIANTS_MISMATCH')
    result = fb.read_video_submit(matched[0].data, require_workflow=True)
    if result['project_id'] != intent['project_id']:
        raise ValueError('NATIVE_PROJECT_MISMATCH')
    return {k:result[k] for k in ('media_id','workflow_id','project_id')}


def _json_sha256(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,ensure_ascii=False,separators=(',',':')
    ).encode()).hexdigest()


def _valid_uuid(value):
    return (isinstance(value,str)
            and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                             value) is not None)


_RECOVERY_INTENT_FIELDS={
    'source_sha256','project_id','ordered_reference_ids','prompt',
    'duration_s','model','resolution','aspect','variants',
}


def _validate_recovery_record(
        record,*,expected_project_id=None,expected_source_sha256=None):
    if (not isinstance(record,dict) or record.get('schema_version')!=1
            or record.get('state') not in {'PROCESSING','COMPLETED'}
            or any(not _valid_uuid(record.get(key))
                   for key in ('media_id','workflow_id','project_id'))):
        raise ValueError('RECOVERY_STORY_RECEIPT_INVALID')
    intent=record.get('intent')
    if (not isinstance(intent,dict) or set(intent)!=_RECOVERY_INTENT_FIELDS
            or not isinstance(intent.get('source_sha256'),str)
            or re.fullmatch(r'[0-9a-f]{64}',intent['source_sha256']) is None
            or not isinstance(intent.get('prompt'),str) or not intent['prompt'].strip()
            or len(intent['prompt'])>30000
            or type(intent.get('duration_s')) is not int
            or intent['duration_s'] not in _VIDEO_CREDITS
            or intent.get('model')!=_VIDEO_MODEL
            or intent.get('resolution')!=_VIDEO_RESOLUTION
            or intent.get('aspect')!='9:16'
            or type(intent.get('variants')) is not int or intent['variants']!=1
            or intent.get('project_id')!=record['project_id']):
        raise ValueError('RECOVERY_STORY_RECEIPT_INVALID')
    refs=intent.get('ordered_reference_ids')
    if (not isinstance(refs,list) or not 1<=len(refs)<=32
            or len(set(refs))!=len(refs) or any(not _valid_uuid(value) for value in refs)):
        raise ValueError('RECOVERY_STORY_RECEIPT_INVALID')
    if (expected_project_id is not None
            and record['project_id']!=expected_project_id):
        raise ValueError('RECOVERY_FLOW_PROJECT_MISMATCH')
    if (expected_source_sha256 is not None
            and intent['source_sha256']!=expected_source_sha256):
        raise ValueError('RECOVERY_FLOW_SOURCE_MISMATCH')
    return record


def _recovery_candidate_identity(path,expected_path):
    path=Path(path)
    expected_path=Path(expected_path)
    if path!=expected_path or path.is_symlink() or not path.is_file():
        raise ValueError('RECOVERY_DOWNLOAD_PATH_INVALID')
    try:
        resolved=path.resolve(strict=True)
        stat=os.stat(path,follow_symlinks=False)
    except OSError:
        raise ValueError('RECOVERY_DOWNLOAD_PATH_INVALID') from None
    if resolved!=expected_path:
        raise ValueError('RECOVERY_DOWNLOAD_PATH_INVALID')
    return (stat.st_dev,stat.st_ino)


def _budget_contract(authorization,req):
    if not isinstance(authorization,dict):
        raise TypeError('FLOW_BUDGET_AUTHORIZATION_REQUIRED')
    budget=authorization.get('budget')
    if not isinstance(budget,dict):
        raise TypeError('FLOW_BUDGET_INVALID')
    expected={
        'provider':'google_flow',
        'action':'native_video_generate',
        'currency':'flow_credits',
        'operation':authorization.get('action'),
        'stage':'video',
        'job_id':authorization.get('job_id'),
        'source_sha256':req.get('source_sha256'),
        'evidence_sha256':authorization.get('evidence_sha256'),
    }
    if any(budget.get(key)!=value for key,value in expected.items()):
        raise ValueError('FLOW_BUDGET_BINDING_MISMATCH')
    if authorization.get('job_id')!=req.get('resume_job_id'):
        raise ValueError('FLOW_BUDGET_JOB_MISMATCH')
    if authorization.get('source_sha256')!=req.get('source_sha256'):
        raise ValueError('FLOW_BUDGET_SOURCE_MISMATCH')
    if authorization.get('evidence_sha256')!=req.get('resume_evidence_sha256'):
        raise ValueError('FLOW_BUDGET_EVIDENCE_MISMATCH')

    for key in ('operation_id','quote_id','aggregate_id','profile_logical_name'):
        value=budget.get(key)
        if (not isinstance(value,str) or not value.strip() or len(value)>200
                or (key in {'aggregate_id','profile_logical_name'}
                    and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value) is None)):
            raise ValueError('FLOW_BUDGET_INVALID')
    for key in ('aggregate_authorization_sha256','account_identity_sha256'):
        value=budget.get(key)
        if not isinstance(value,str) or re.fullmatch(r'[0-9a-f]{64}',value) is None:
            raise ValueError('FLOW_BUDGET_INVALID')
    project_id=budget.get('project_id')
    if (not isinstance(project_id,str)
            or re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                            project_id) is None):
        raise ValueError('FLOW_BUDGET_INVALID')

    quoted=budget.get('quoted_cost_credits')
    maximum=budget.get('max_cost_credits')
    if (isinstance(quoted,bool) or isinstance(maximum,bool)
            or not isinstance(quoted,(int,float)) or not isinstance(maximum,(int,float))
            or not math.isfinite(quoted) or not math.isfinite(maximum)
            or quoted<=0 or maximum<=0 or quoted>maximum):
        raise ValueError('FLOW_BUDGET_INVALID')
    return {
        **expected,
        'authorization_sha256':_json_sha256(authorization),
        'operation_id':budget['operation_id'],
        'quote_id':budget['quote_id'],
        'aggregate_id':budget['aggregate_id'],
        'aggregate_authorization_sha256':budget['aggregate_authorization_sha256'],
        'profile_logical_name':budget['profile_logical_name'],
        'account_identity_sha256':budget['account_identity_sha256'],
        'project_id':project_id,
        'quoted_cost_credits':float(quoted),
        'max_cost_credits':float(maximum),
    }


def _budget_ledger_folder(settings,contract):
    base=getattr(settings,'data',None)
    if base is None:
        base=Path(settings.directory)/'data'
    return Path(base)/'flow-budget-ledgers'/contract['job_id']/contract['aggregate_id']


def _validate_observed_owner(contract,profile_config,auth,project_id):
    if (auth.state!='authenticated' or not isinstance(auth.identity,str)
            or not auth.identity.strip()):
        raise ValueError('FLOW_ACCOUNT_IDENTITY_UNVERIFIED')
    identity_sha=hashlib.sha256(auth.identity.casefold().encode()).hexdigest()
    if contract['account_identity_sha256']!=identity_sha:
        raise ValueError('FLOW_ACCOUNT_IDENTITY_MISMATCH')
    if contract['profile_logical_name']!=profile_config.profile_logical_name:
        raise ValueError('FLOW_PROFILE_IDENTITY_MISMATCH')
    if contract['project_id']!=project_id:
        raise ValueError('FLOW_PROJECT_IDENTITY_MISMATCH')
    return identity_sha


def _observed_submit_binding(contract,profile_config,auth,project_id,native_intent):
    identity_sha=_validate_observed_owner(contract,profile_config,auth,project_id)
    if native_intent.get('project_id')!=project_id:
        raise ValueError('FLOW_PROJECT_IDENTITY_MISMATCH')
    if native_intent.get('source_sha256')!=contract['source_sha256']:
        raise ValueError('FLOW_SUBMIT_INTENT_SOURCE_MISMATCH')
    return {
        'schema_version':1,
        'provider':contract['provider'],
        'action':contract['action'],
        'currency':contract['currency'],
        'operation':contract['operation'],
        'stage':contract['stage'],
        'operation_id':contract['operation_id'],
        'aggregate_id':contract['aggregate_id'],
        'aggregate_authorization_sha256':contract['aggregate_authorization_sha256'],
        'authorization_sha256':contract['authorization_sha256'],
        'job_id':contract['job_id'],
        'source_sha256':contract['source_sha256'],
        'evidence_sha256':contract['evidence_sha256'],
        'quote_id':contract['quote_id'],
        'quoted_cost_credits':contract['quoted_cost_credits'],
        'max_cost_credits':contract['max_cost_credits'],
        'profile_logical_name':contract['profile_logical_name'],
        'account_identity_sha256':identity_sha,
        'project_id':project_id,
        'native_intent_sha256':_json_sha256(native_intent),
    }


def _bind_submit_intent(path,binding):
    path=Path(path)
    if path.exists():
        try:
            current=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,ValueError,TypeError,json.JSONDecodeError):
            raise ValueError('FLOW_SUBMIT_INTENT_INVALID') from None
        if current!=binding:
            raise ValueError('FLOW_SUBMIT_INTENT_MISMATCH')
        return current
    atomic_json(path,binding)
    return binding


class _BudgetLedger:
    _STATES=frozenset(('RESERVED','UNKNOWN','COMMITTED'))
    _SCOPE_KEYS=(
        'provider','action','currency','job_id','source_sha256',
        'aggregate_id','aggregate_authorization_sha256','profile_logical_name',
        'account_identity_sha256','project_id','max_cost_credits')
    _EXACT_KEYS=(
        'authorization_sha256','operation','stage','operation_id','evidence_sha256',
        'quote_id','quoted_cost_credits')

    def __init__(self,folder,contract):
        self.folder=Path(folder)
        self.path=self.folder/'budget-ledger.json'
        self.contract=contract

    @staticmethod
    def _positive_cost(value):
        return (not isinstance(value,bool) and isinstance(value,(int,float))
                and math.isfinite(value) and value>0)

    def _validate_scope(self,row,operation_id):
        if (not isinstance(row,dict) or not isinstance(operation_id,str)
                or row.get('operation_id')!=operation_id
                or row.get('state') not in self._STATES):
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID')
        if any(row.get(key)!=self.contract.get(key) for key in self._SCOPE_KEYS):
            raise ValueError('FLOW_BUDGET_RESERVATION_MISMATCH')
        if (not isinstance(row.get('operation'),str) or not row['operation']
                or not isinstance(row.get('stage'),str) or not row['stage']
                or not isinstance(row.get('operation_id'),str) or not row['operation_id']
                or not isinstance(row.get('evidence_sha256'),str)
                or re.fullmatch(r'[0-9a-f]{64}',row['evidence_sha256']) is None
                or not self._positive_cost(row.get('quoted_cost_credits'))
                or not self._positive_cost(row.get('reserved_cost_credits'))
                or float(row['quoted_cost_credits'])!=float(row['reserved_cost_credits'])
                or not isinstance(row.get('quote_id'),str) or not row['quote_id']
                or not isinstance(row.get('authorization_sha256'),str)
                or re.fullmatch(r'[0-9a-f]{64}',row['authorization_sha256']) is None
                or not isinstance(row.get('submit_intent_sha256'),str)
                or re.fullmatch(r'[0-9a-f]{64}',row['submit_intent_sha256']) is None):
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID')
        balance=row.get('balance_before')
        if isinstance(balance,bool) or not isinstance(balance,int) or balance<0:
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID')
        if row['state']=='COMMITTED':
            spent=row.get('spent_cost_credits')
            receipt=row.get('receipt')
            if (not self._positive_cost(spent)
                    or float(spent)!=float(row['reserved_cost_credits'])
                    or not isinstance(receipt,dict)
                    or receipt.get('project_id')!=self.contract['project_id']
                    or any(not _valid_uuid(receipt.get(key))
                           for key in ('media_id','workflow_id','project_id'))):
                raise ValueError('FLOW_BUDGET_LEDGER_INVALID')
        elif 'spent_cost_credits' in row or 'receipt' in row:
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID')

    def _load(self):
        if not self.path.exists():
            return {'schema_version':1,'currency':'flow_credits','reservations':{}}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,ValueError,TypeError,json.JSONDecodeError):
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID') from None
        if (not isinstance(value,dict) or value.get('schema_version')!=1
                or value.get('currency')!='flow_credits'
                or not isinstance(value.get('reservations'),dict)):
            raise ValueError('FLOW_BUDGET_LEDGER_INVALID')
        for operation_id,row in value['reservations'].items():
            self._validate_scope(row,operation_id)
        return value

    def _validate_existing(self,row):
        self._validate_scope(row,self.contract['operation_id'])
        if any(row.get(key)!=self.contract.get(key) for key in self._EXACT_KEYS):
            raise ValueError('FLOW_BUDGET_RESERVATION_MISMATCH')

    def reserve(self,current_ui_cost,balance,submit_binding):
        if (not self._positive_cost(current_ui_cost)
                or float(current_ui_cost)!=self.contract['quoted_cost_credits']):
            raise ValueError('FLOW_CURRENT_QUOTE_CHANGED')
        if isinstance(balance,bool) or not isinstance(balance,int) or balance<current_ui_cost:
            raise ValueError('NO_FLOW_CREDIT')
        submit_sha=_json_sha256(submit_binding)
        with runner_lock(self.folder):
            ledger=self._load()
            reservations=ledger['reservations']
            operation_id=self.contract['operation_id']
            existing=reservations.get(operation_id)
            if existing is not None:
                self._validate_existing(existing)
                if existing.get('submit_intent_sha256')!=submit_sha:
                    raise ValueError('FLOW_SUBMIT_INTENT_MISMATCH')
                if existing.get('state')=='COMMITTED':
                    return dict(existing,already_committed=True)
                raise ValueError('FLOW_BUDGET_OUTCOME_UNKNOWN')
            counted=sum(float(row['reserved_cost_credits']) for row in reservations.values())
            if counted+float(current_ui_cost)>self.contract['max_cost_credits']:
                raise ValueError('FLOW_BUDGET_CAP_EXCEEDED')
            row={**self.contract,'state':'RESERVED',
                 'reserved_cost_credits':float(current_ui_cost),
                 'balance_before':balance,'submit_intent_sha256':submit_sha}
            reservations[operation_id]=row
            atomic_json(self.path,ledger)
            return row

    def mark_unknown(self):
        with runner_lock(self.folder):
            ledger=self._load()
            row=ledger['reservations'].get(self.contract['operation_id'])
            if row is None:
                raise ValueError('FLOW_BUDGET_RESERVATION_MISSING')
            self._validate_existing(row)
            if row.get('state')!='COMMITTED':
                row['state']='UNKNOWN'
                atomic_json(self.path,ledger)

    @staticmethod
    def _validate_story_record(record,submit_binding):
        if (not isinstance(record,dict)
                or record.get('state') not in {'PROCESSING','COMPLETED'}
                or not isinstance(record.get('intent'),dict)
                or _json_sha256(record['intent'])!=submit_binding['native_intent_sha256']
                or record['intent'].get('project_id')!=submit_binding['project_id']
                or record['intent'].get('source_sha256')!=submit_binding['source_sha256']
                or any(not _valid_uuid(record.get(key))
                       for key in ('media_id','workflow_id','project_id'))
                or record.get('project_id')!=submit_binding['project_id']):
            raise ValueError('FLOW_BUDGET_SUBMIT_RECEIPT_INVALID')

    def commit(self,record,submit_binding):
        self._validate_story_record(record,submit_binding)
        submit_sha=_json_sha256(submit_binding)
        with runner_lock(self.folder):
            ledger=self._load()
            row=ledger['reservations'].get(self.contract['operation_id'])
            if row is None:
                raise ValueError('FLOW_BUDGET_RESERVATION_MISSING')
            self._validate_existing(row)
            if row.get('submit_intent_sha256')!=submit_sha:
                raise ValueError('FLOW_SUBMIT_INTENT_MISMATCH')
            if row.get('state')=='COMMITTED':
                incoming={k:record[k] for k in ('media_id','workflow_id','project_id')}
                if row.get('receipt')!=incoming:
                    raise ValueError('FLOW_BUDGET_COMMITTED_RECEIPT_MISMATCH')
                return row
            if row.get('state') not in {'RESERVED','UNKNOWN'}:
                raise ValueError('FLOW_BUDGET_RESERVATION_INVALID')
            row['state']='COMMITTED'
            row['spent_cost_credits']=row['reserved_cost_credits']
            row['receipt']={k:record[k] for k in ('media_id','workflow_id','project_id')}
            atomic_json(self.path,ledger)
            return row

    def reconcile_known_submit(self,record,submit_binding):
        if not self.path.exists():
            raise ValueError('FLOW_BUDGET_LEDGER_MISSING')
        return self.commit(record,submit_binding)


class FlowStoryBrowser:
    def __init__(self, settings, runtime):
        self.settings, self.runtime = settings, runtime

    def _check_enabled(self):
        path=getattr(self.settings,'path',None)
        current=Settings.load(self.settings.directory) if path and path.exists() else self.settings
        if getattr(current,'enabled',True) is not True:
            raise ProductionPaused('PRODUCTION_PAUSED')

    def _rpc(self, page, rpcid, freq):
        script = Path(__file__).with_name('flow_browser_rpc.js').read_text(encoding='utf-8')
        response = page.evaluate('mw:'+script, {'rpcid':rpcid,'freq':freq,
                        'projectId':self.runtime.flow_project_id,'timeoutMs':30000})
        if response.get('status')!=200 or response.get('body_complete') is not True:
            raise RuntimeError('POLL_BODY_INCOMPLETE')
        values=[v for v in fb.parse_envelope(response['data']) if v.rpcid==rpcid and not v.error]
        if len(values)!=1:
            raise RuntimeError('POLL_RECEIPT_INVALID')
        return values[0].data

    def _wait(self,page,record):
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            result=fb.read_operation(self._rpc(page,'jwpduf',fb.operation_request(record['media_id'])))
            if result.operation_id!=record['media_id'] or result.project_id!=record['project_id']:
                raise RuntimeError('POLL_ID_MISMATCH')
            if result.outcome==3:
                return
            if result.error:
                raise ValueError('NATIVE_GENERATION_FAILED')
            page.wait_for_timeout(5000)
        raise TimeoutError('NATIVE_GENERATION_PENDING')

    def _prepare(self,page,generation=None):
        generation=_generation_contract(generation)
        page.get_by_role('button',name='Thông tin về tài khoản',exact=True).press('Enter')
        credit=page.get_by_role('dialog',name='Cài đặt tài khoản',exact=True).get_by_role(
            'link',name=re.compile(r'^\d+ tín dụng Google Flow$'))
        credit.wait_for(state='visible',timeout=10000)
        balance=int(credit.inner_text().split()[0])
        page.get_by_role('button',name='Đóng bảng điều khiển tài khoản',exact=True).press('Enter')
        trigger=page.get_by_role('button',name='Điều kiện kích hoạt cài đặt',exact=True)
        trigger.press('Enter')
        labels=(
            'Video','Thành phần','9:16',
            '360p 360p tạo nhanh hơn ở độ phân giải thấp hơn',
            f"{generation['duration_s']} giây",_VIDEO_VARIANT_LABEL)
        for label in labels:
            radio=page.get_by_role('radio',name=label,exact=True)
            if not radio.is_checked():
                radio.press('Space')
            if not radio.is_checked():
                raise ValueError('FLOW_PRESET_UNVERIFIED')
        if model_label(page.get_by_role(
                'button',name='Chọn nhóm mô hình',exact=True).inner_text())!=_VIDEO_MODEL:
            raise ValueError('FLOW_MODEL_CHANGED')
        quote=page.get_by_role('link',name=re.compile(r'^\d+ tín dụng$'))
        cost=int(quote.inner_text().split()[0])
        if generation['quoted_cost_credits'] is not None and (
                float(cost)!=generation['quoted_cost_credits']):
            raise ValueError('FLOW_CURRENT_QUOTE_CHANGED')
        if balance<cost:
            raise ValueError('NO_FLOW_CREDIT')
        page.keyboard.press('Escape')
        return {
            'credits':balance,'quoted_cost':cost,
            'duration_s':generation['duration_s'],
            'model':generation['model'],'resolution':generation['resolution'],
            'variants':generation['variants'],
        }

    def _current_quote(self,page,generation=None):
        generation=_generation_contract(generation)
        page.get_by_role('button',name='Thông tin về tài khoản',exact=True).press('Enter')
        credit=page.get_by_role('dialog',name='Cài đặt tài khoản',exact=True).get_by_role(
            'link',name=re.compile(r'^\d+ tín dụng Google Flow$'))
        credit.wait_for(state='visible',timeout=10000)
        balance=int(credit.inner_text().split()[0])
        page.get_by_role('button',name='Đóng bảng điều khiển tài khoản',exact=True).press('Enter')
        trigger=page.get_by_role('button',name='Điều kiện kích hoạt cài đặt',exact=True)
        trigger.press('Enter')
        labels=(
            'Video','Thành phần','9:16',
            '360p 360p tạo nhanh hơn ở độ phân giải thấp hơn',
            f"{generation['duration_s']} giây",_VIDEO_VARIANT_LABEL)
        for label in labels:
            if not page.get_by_role('radio',name=label,exact=True).is_checked():
                raise ValueError('FLOW_PRESET_CHANGED')
        if model_label(page.get_by_role(
                'button',name='Chọn nhóm mô hình',exact=True).inner_text())!=_VIDEO_MODEL:
            raise ValueError('FLOW_MODEL_CHANGED')
        quote=page.get_by_role('link',name=re.compile(r'^\d+ tín dụng$'))
        cost=int(quote.inner_text().split()[0])
        page.keyboard.press('Escape')
        if cost<=0:
            raise ValueError('FLOW_CURRENT_QUOTE_INVALID')
        if generation['quoted_cost_credits'] is not None and (
                float(cost)!=generation['quoted_cost_credits']):
            raise ValueError('FLOW_CURRENT_QUOTE_CHANGED')
        if balance<cost:
            raise ValueError('NO_FLOW_CREDIT')
        return {
            'credits':balance,'quoted_cost':cost,
            'duration_s':generation['duration_s'],
            'model':generation['model'],'resolution':generation['resolution'],
            'variants':generation['variants'],
        }

    def run(
            self,name,req,directory,progress,*,reconcile=False,
            authorization=None,generation=None):
        folder=directory/'flow'
        folder.mkdir(exist_ok=True)
        story=StoryReceipt(folder/'story-receipt.json')
        budget_contract=_budget_contract(authorization,req) if authorization is not None else None
        try:
            generation_contract=_generation_contract(generation,budget_contract)
        except (TypeError,ValueError) as exc:
            return {
                'state':'blocked','not_submitted':True,
                'reason':str(exc) or 'FLOW_GENERATION_CONTRACT_INVALID',
            }
        budget_ledger=(_BudgetLedger(_budget_ledger_folder(self.settings,budget_contract),
                                    budget_contract)
                       if budget_contract is not None else None)
        budget_reserved=False
        budget_committed=False
        submit_binding=None
        step='open'
        profile_config=FlowProfileConfig.load(Path(self.runtime.flow_profile_config))
        provider=FlowBrowserSessionProvider(
            profile_config,auth_probe=observe_flow_account,visible=False).open()
        try:
            page=provider.session.page
            project=self.runtime.flow_project_id
            page.goto('https://flow.google.com/project/'+project,wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Thông tin về tài khoản',exact=True).wait_for(state='visible',timeout=30000)
            auth=observe_flow_account(page)
            if auth.state!='authenticated':
                return {'state':'blocked','not_submitted':True,'reason':'FLOW_AUTH_REQUIRED'}
            if budget_contract is not None:
                try:
                    _validate_observed_owner(budget_contract,profile_config,auth,project)
                except ValueError as exc:
                    return {'state':'blocked','not_submitted':True,'reason':str(exc)}
            if name=='video':
                if story.path.exists():
                    record=story.load()
                    if record['state'] not in {'PROCESSING','COMPLETED'}:
                        return {'state':'uncertain','reason':'PAID_SUBMIT_NOT_BOUND'}
                    if budget_ledger is not None:
                        try:
                            submit_binding=_observed_submit_binding(
                                budget_contract,profile_config,auth,project,record['intent'])
                            _bind_submit_intent(
                                folder/'paid-submit-intent.json',submit_binding)
                            budget_ledger.reconcile_known_submit(record,submit_binding)
                            budget_committed=True
                        except (KeyError,TypeError,ValueError) as exc:
                            return {'state':'uncertain','reason':str(exc)}
                elif reconcile:
                    return {'state':'uncertain','reason':'FLOW_PREPARATION_INCOMPLETE'}
                else:
                    step='settings'
                    try:
                        readiness=self._prepare(page,generation_contract)
                    except ValueError as exc:
                        if str(exc) in {
                                'NO_FLOW_CREDIT','FLOW_MODEL_CHANGED',
                                'FLOW_PRESET_UNVERIFIED','FLOW_CURRENT_QUOTE_CHANGED'}:
                            return {'state':'blocked','not_submitted':True,'reason':str(exc)}
                        raise
                    atomic_json(folder/'readiness.json',readiness)
                    state=BrowserStateStore(folder/'uploads.json',owner_key='thoremix-'+req['source_sha256'][:20])
                    refs=[]
                    step='upload_references'
                    progress({'preparation_step':step})
                    for item in req['images']['files']:
                        path=Path(item['path'])
                        media_id=upload_reference(provider.session,path,project,state)
                        refs.append(ExistingReference(media_id,path.name))
                    # Refresh makes freshly uploaded native assets visible in the picker.
                    page.reload(wait_until='domcontentloaded')
                    step='attach_references'
                    progress({'preparation_step':step})
                    attach_existing_references(page,refs)
                    panels=json.loads(json.dumps(req['analysis']['panels']))
                    approved_words=req['image_review']['data'].get('dialogues_verified') is True
                    for panel in panels:
                        for dialogue in panel.get('dialogues',[]):
                            dialogue['verified']=approved_words
                    prompt=story_video_prompt(panels,allow_unverified=True)
                    step='fill_prompt'
                    progress({'preparation_step':step})
                    page.locator('div.ProseMirror').fill(prompt)
                    step='verify_composer'
                    progress({'preparation_step':step})
                    verified=verify_reference_composer(page,project,refs,prompt)
                    intent={
                        'source_sha256':req['source_sha256'],'project_id':project,
                        'ordered_reference_ids':verified['ordered_reference_ids'],
                        'prompt':prompt,
                        'duration_s':generation_contract['duration_s'],
                        'aspect':'9:16',
                        'resolution':generation_contract['resolution'],
                        'model':generation_contract['model'],
                        'variants':generation_contract['variants'],
                    }
                    self._check_enabled()
                    if budget_ledger is not None:
                        step='budget_quote'
                        try:
                            final_auth=observe_flow_account(page)
                            submit_binding=_observed_submit_binding(
                                budget_contract,profile_config,final_auth,project,intent)
                            current_quote=self._current_quote(
                                page,generation_contract)
                            current_auth=observe_flow_account(page)
                            current_binding=_observed_submit_binding(
                                budget_contract,profile_config,current_auth,project,intent)
                            if current_binding!=submit_binding:
                                raise ValueError('FLOW_CURRENT_ACTOR_CHANGED')
                            reservation=budget_ledger.reserve(
                                current_quote['quoted_cost'],current_quote['credits'],
                                submit_binding)
                            _bind_submit_intent(
                                folder/'paid-submit-intent.json',submit_binding)
                        except ValueError as exc:
                            if str(exc)=='FLOW_BUDGET_OUTCOME_UNKNOWN':
                                return {'state':'uncertain','reason':str(exc)}
                            return {'state':'blocked','not_submitted':True,'reason':str(exc)}
                        if reservation.get('already_committed') is True:
                            return {'state':'uncertain',
                                    'reason':'FLOW_BUDGET_COMMITTED_WITHOUT_STORY_RECEIPT'}
                        budget_reserved=True
                    story.begin(intent)
                    with page.expect_response(lambda r:'rpcids=MZZa6b' in r.url,timeout=120000) as pending:
                        page.get_by_role('button',name='Bắt đầu tạo',exact=True).press('Enter')
                    response=pending.value
                    if response.status!=200:
                        if budget_ledger is not None and budget_reserved:
                            budget_ledger.mark_unknown()
                        raise RuntimeError('NATIVE_SUBMIT_UNCONFIRMED')
                    receipt=verified_native_submit(
                        response.body().decode('utf-8'),response.request.post_data,intent)
                    record=story.submitted(receipt)
                    if budget_ledger is not None:
                        budget_ledger.commit(record,submit_binding)
                        budget_committed=True
                    progress(receipt)
                self._wait(page,record)
                downloaded=self._download(page,record,folder,highest=False)
            else:
                record=story.load()
                expected=req['video']['data']
                if any(record[k]!=expected[k] for k in ('project_id','media_id','workflow_id')):
                    raise ValueError('HIGHEST_MEDIA_MISMATCH')
                downloaded=self._download(page,record,folder,highest=True)
            return {'state':'verified','files':[artifact(downloaded['path'])],
                'data':{k:record[k] for k in ('project_id','media_id','workflow_id')}|downloaded['data']}
        except ProductionPaused:
            return {'state':'blocked','not_submitted':True,'reason':'PRODUCTION_PAUSED'}
        except Exception as error:
            if budget_ledger is not None and budget_reserved and not budget_committed:
                budget_ledger.mark_unknown()
            # The paid intent is durable BEFORE the only generate click. Missing
            # intent proves preparation stopped before that boundary; upload
            # receipts still reconcile independently and are never replayed.
            if name=='video' and not story.path.exists():
                atomic_json(folder/'preparation-error.json',
                    {'step':step,'error_type':type(error).__name__,'not_submitted':True})
                return {'state':'blocked','not_submitted':True,'reason':'FLOW_PREPARATION_'+step.upper()}
            raise
        finally:
            provider.close()

    def download_existing(self, record, folder, *, highest=True):
        """Download an already-created Flow derivative without generation/upscale clicks.

        Recovery accepts only a complete durable StoryReceipt.  Record and cached
        metadata are validated before any browser owner is opened.
        """
        record=_validate_recovery_record(
            record,expected_project_id=self.runtime.flow_project_id)
        required=('media_id','project_id','workflow_id')
        duration=record['intent']['duration_s']
        folder=Path(folder)
        folder.mkdir(parents=True,exist_ok=True)
        folder=folder.resolve(strict=True)
        stem='highest' if highest else 'original'
        receipt_path=folder/(stem+'-download.json')
        final=folder/(stem+'.mp4')
        part=folder/(stem+'.part.mp4')
        resolution=720 if highest else 360
        if receipt_path.exists():
            try:
                receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            except (OSError,UnicodeError,ValueError,TypeError,json.JSONDecodeError):
                raise ValueError('RECOVERY_DOWNLOAD_RECEIPT_INVALID') from None
            data=receipt.get('data')
            selected=data.get('selected_resolution') if isinstance(data,dict) else None
            match=re.match(r'^(\d+)p(?:\s|$)',selected or '')
            state=receipt.get('state')
            receipt_artifact=receipt.get('artifact')
            if (state not in {'BYTES_VALIDATED','COMPLETED'}
                    or any(receipt.get(k)!=record[k] for k in required)
                    or not isinstance(receipt_artifact,dict)
                    or not isinstance(receipt_artifact.get('path'),str)
                    or not isinstance(receipt_artifact.get('sha256'),str)
                    or not isinstance(data,dict)
                    or data.get('highest') is not highest
                    or match is None or int(match.group(1))!=resolution):
                raise ValueError('RECOVERY_DOWNLOAD_RECEIPT_INVALID')
            expected_artifact_path=part if state=='BYTES_VALIDATED' else final
            if Path(receipt_artifact['path']).resolve(strict=False)!=expected_artifact_path:
                raise ValueError('RECOVERY_DOWNLOAD_RECEIPT_INVALID')
            trusted_sha=receipt_artifact['sha256']
            if state=='COMPLETED':
                candidate=final
                candidate_identity=_recovery_candidate_identity(candidate,final)
                if artifact(candidate)!=receipt_artifact:
                    raise ValueError('RECOVERY_DOWNLOAD_RECEIPT_INVALID')
            else:
                if final.exists() and part.exists():
                    raise ValueError('RECOVERY_DOWNLOAD_FINAL_CONFLICT')
                candidate=final if final.exists() else part
                candidate_identity=_recovery_candidate_identity(candidate,candidate)
                if artifact(candidate)['sha256']!=trusted_sha:
                    raise ValueError('RECOVERY_DOWNLOAD_BYTES_CHANGED')
            media=validate_media(candidate,tool_root=self.settings.directory)
            post_probe_identity=_recovery_candidate_identity(candidate,candidate)
            if (post_probe_identity!=candidate_identity
                    or artifact(candidate)['sha256']!=trusted_sha):
                raise ValueError('RECOVERY_DOWNLOAD_BYTES_CHANGED')
            if (media.get('width')!=resolution
                    or abs(float(media.get('duration_s',-1))-duration)>.1
                    or data.get('width')!=media.get('width')
                    or data.get('duration_s')!=media.get('duration_s')):
                raise ValueError('RECOVERY_DOWNLOAD_MEDIA_MISMATCH')
            if state=='BYTES_VALIDATED':
                if candidate==part:
                    if final.exists():
                        raise ValueError('RECOVERY_DOWNLOAD_FINAL_CONFLICT')
                    try:
                        part.rename(final)
                    except FileExistsError:
                        raise ValueError('RECOVERY_DOWNLOAD_FINAL_CONFLICT') from None
                    final_identity=_recovery_candidate_identity(final,final)
                    if (final_identity!=candidate_identity
                            or artifact(final)['sha256']!=trusted_sha):
                        raise ValueError('RECOVERY_DOWNLOAD_BYTES_CHANGED')
                receipt.update(state='COMPLETED',artifact={
                    'path':str(final.resolve(strict=True)),
                    'sha256':trusted_sha,
                })
                atomic_json(receipt_path,receipt)
            return {'path':str(final),'data':data}
        provider=FlowBrowserSessionProvider(
            FlowProfileConfig.load(Path(self.runtime.flow_profile_config)),
            auth_probe=observe_flow_account,visible=False).open()
        try:
            page=provider.session.page
            page.goto('https://flow.google.com/project/'+record['project_id'],
                      wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Thông tin về tài khoản',exact=True).wait_for(
                state='visible',timeout=30000)
            if observe_flow_account(page).state!='authenticated':
                raise ValueError('FLOW_AUTH_REQUIRED')
            derivative=record['media_id']+('_720p_upsampled' if highest else '')
            data=self._rpc(page,'as29s',fb.media_request(derivative))
            url=fb.read_media_urls(data,derivative).video
            parsed=urlsplit(url or '')
            if (parsed.scheme!='https' or parsed.hostname!='flow-content.google'
                    or parsed.path!='/video/'+derivative):
                raise RuntimeError('RECOVERY_DOWNLOAD_NOT_BOUND')
            response=page.request.get(url,timeout=120000)
            if response.status!=200:
                raise RuntimeError('RECOVERY_DOWNLOAD_FAILED')
            raw=response.body()
            if not 1024<len(raw)<128*1024*1024:
                raise RuntimeError('RECOVERY_DOWNLOAD_BYTES_INVALID')
            part=folder/(stem+'.part.mp4')
            with part.open('wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            selected=f'{resolution}p existing Flow derivative'
            return self._promote_download(part,final,receipt_path,record,selected,
                                          [selected],highest)
        finally:
            provider.close()

    def _download(self,page,record,folder,*,highest):
        stem='highest' if highest else 'original'
        receipt_path=folder/(stem+'-download.json')
        final=folder/(stem+'.mp4')
        if receipt_path.exists():
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            if any(receipt.get(k)!=record[k] for k in ('media_id','project_id','workflow_id')):
                raise ValueError('DOWNLOAD_RECEIPT_MEDIA_MISMATCH')
            if receipt.get('state')=='COMPLETED' and artifact(final)==receipt['artifact']:
                return {'path':str(final),'data':receipt['data']}
            part=folder/(stem+'.part.mp4')
            if receipt.get('state')=='BYTES_VALIDATED':
                candidate=final if final.exists() else part
                if artifact(candidate)['sha256']!=receipt['artifact']['sha256']:
                    raise RuntimeError('DOWNLOAD_BYTES_CHANGED')
                validate_media(candidate,tool_root=self.settings.directory)
                if candidate!=final:
                    os.replace(part,final)
                receipt.update(state='COMPLETED',artifact=artifact(final))
                atomic_json(receipt_path,receipt)
                return {'path':str(final),'data':receipt['data']}
            # Read the exact already-created remote derivative; never re-click upscale.
            selected=receipt['selected']
            resolution=int(re.match(r'\d+',selected)[0])
            if resolution not in {360,720}:
                raise RuntimeError('DOWNLOAD_RECONCILIATION_REQUIRED')
            derivative=record['media_id']+('_720p_upsampled' if resolution==720 else '')
            data=self._rpc(page,'as29s',fb.media_request(derivative))
            url=fb.read_media_urls(data,derivative).video
            parsed=urlsplit(url or '')
            if parsed.scheme!='https' or parsed.hostname!='flow-content.google' or parsed.path!='/video/'+derivative:
                raise RuntimeError('DOWNLOAD_RECONCILIATION_REQUIRED')
            response=page.request.get(url,timeout=120000)
            if response.status!=200:
                raise RuntimeError('DOWNLOAD_RECONCILIATION_REQUIRED')
            raw=response.body()
            if not 1024<len(raw)<128*1024*1024:
                raise RuntimeError('DOWNLOAD_BYTES_INVALID')
            with part.open('wb') as stream:
                stream.write(raw);stream.flush();os.fsync(stream.fileno())
            return self._promote_download(part,final,receipt_path,record,selected,receipt['options'],highest)
        # Reopened gallery thumbnails use opaque CDN paths. The native editor
        # route is bound to the workflow ID from the validated submit receipt.
        editor_path=f"/project/{record['project_id']}/edit/{record['workflow_id']}"
        page.goto('https://flow.google.com'+editor_path,wait_until='domcontentloaded',timeout=60000)
        if urlsplit(page.url).path!=editor_path:
            raise ValueError('DOWNLOAD_EDITOR_MISMATCH')
        button=page.get_by_role('button',name='Tải nội dung nghe nhìn xuống',exact=True)
        button.wait_for(state='visible',timeout=15000)
        button.press('Enter')
        menu=page.get_by_role('menuitem')
        menu.first.wait_for(state='visible',timeout=10000)
        labels=menu.all_inner_texts()
        selected=highest_video_download(labels) if highest else next(
            label for label in labels if re.match(r'^360p(?:\s|$)',label) and 'gif' not in label.casefold())
        # Observe and save intent before native click. Browser owner stays alive through save_as.
        self._check_enabled()
        atomic_json(receipt_path,{'state':'SUBMITTING',
            **{k:record[k] for k in ('media_id','project_id','workflow_id')},'selected':selected,'options':labels})
        with page.expect_download(timeout=900000) as pending:
            page.get_by_role('menuitem',name=normalized_prompt(selected),exact=True).press('Enter')
        download=pending.value
        part=folder/(stem+'.part.mp4')
        download.save_as(str(part))
        if download.failure() is not None:
            raise RuntimeError('DOWNLOAD_INCOMPLETE')
        return self._promote_download(part,final,receipt_path,record,selected,labels,highest)

    def _promote_download(self,part,final,receipt_path,record,selected,labels,highest):
        intent=record.get('intent')
        duration=intent.get('duration_s') if isinstance(intent,dict) else None
        if type(duration) is not int or duration not in _VIDEO_CREDITS:
            raise ValueError('DOWNLOAD_INTENT_DURATION_INVALID')
        media=validate_media(part,tool_root=self.settings.directory)
        wanted=int(re.match(r'\d+',selected)[0])
        if media['width']!=wanted or abs(media['duration_s']-duration)>.1:
            raise ValueError('DOWNLOAD_MEDIA_MISMATCH')
        data={'selected_resolution':selected,'observed_options':labels,'highest':highest,**media}
        receipt={'state':'BYTES_VALIDATED',**{k:record[k] for k in ('media_id','project_id','workflow_id')},
                 'artifact':artifact(part),'data':data}
        atomic_json(receipt_path,receipt)
        os.replace(part,final)
        receipt.update(state='COMPLETED',artifact=artifact(final))
        atomic_json(receipt_path,receipt)
        return {'path':str(final),'data':data}
