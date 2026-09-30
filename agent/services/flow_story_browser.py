"""Observed vi-VN native Flow story workflow under one Camoufox/KBS owner.

The native UI owns paid requests. Read RPCs only poll exact recorded media IDs.
No automatic repeat of a paid submit or an uncertain upscale.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from agent.comicreels.prompts import story_video_prompt
from agent.comicreels.story import StoryReceipt
from agent.services import flow_batch as fb
from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_session import FlowBrowserSessionProvider, FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore
from agent.services.flow_browser_upload import upload_reference
from agent.services.flow_browser_semantics import (
    ExistingReference, attach_existing_references, verify_reference_composer,
    highest_video_download, normalized_prompt,
)
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import validate_media
from agent.thoremix.story_operations import artifact


def model_label(text):
    """Native Material dropdown icons can appear in rendered inner_text."""
    return re.sub(r'\s+arrow_drop_down$', '', text.strip())


class ProductionPaused(RuntimeError):
    pass


def verified_native_submit(body, post_data, intent):
    request = json.loads(json.loads(parse_qs(post_data)['f.req'][0])[0][0][1])
    if (len(request[0]) != 1 or request[0][0][2] != 'abra_r2v_10s_360p'
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

    def _prepare(self,page):
        page.get_by_role('button',name='Thông tin về tài khoản',exact=True).press('Enter')
        credit=page.get_by_role('dialog',name='Cài đặt tài khoản',exact=True).get_by_role(
            'link',name=re.compile(r'^\d+ tín dụng Google Flow$'))
        credit.wait_for(state='visible',timeout=10000)
        balance=int(credit.inner_text().split()[0])
        page.get_by_role('button',name='Đóng bảng điều khiển tài khoản',exact=True).press('Enter')
        trigger=page.get_by_role('button',name='Điều kiện kích hoạt cài đặt',exact=True)
        trigger.press('Enter')
        for label in ('Video','Thành phần','9:16','360p 360p tạo nhanh hơn ở độ phân giải thấp hơn','10 giây','x1'):
            radio=page.get_by_role('radio',name=label,exact=True)
            if not radio.is_checked():
                radio.press('Space')
            if not radio.is_checked():
                raise ValueError('FLOW_PRESET_UNVERIFIED')
        if model_label(page.get_by_role('button',name='Chọn nhóm mô hình',exact=True).inner_text())!='Omni 1.1 Flash':
            raise ValueError('FLOW_MODEL_CHANGED')
        quote=page.get_by_role('link',name=re.compile(r'^\d+ tín dụng$'))
        cost=int(quote.inner_text().split()[0])
        if balance<cost:
            raise ValueError('NO_FLOW_CREDIT')
        page.keyboard.press('Escape')
        return {'credits':balance,'quoted_cost':cost}

    def run(self,name,req,directory,progress,*,reconcile=False):
        folder=directory/'flow'
        folder.mkdir(exist_ok=True)
        story=StoryReceipt(folder/'story-receipt.json')
        step='open'
        provider=FlowBrowserSessionProvider(FlowProfileConfig.load(Path(self.runtime.flow_profile_config)),
                                            auth_probe=observe_flow_account, visible=False).open()
        try:
            page=provider.session.page
            project=self.runtime.flow_project_id
            page.goto('https://flow.google.com/project/'+project,wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Thông tin về tài khoản',exact=True).wait_for(state='visible',timeout=30000)
            if observe_flow_account(page).state!='authenticated':
                return {'state':'blocked','not_submitted':True,'reason':'FLOW_AUTH_REQUIRED'}
            if name=='video':
                if story.path.exists():
                    record=story.load()
                    if record['state'] not in {'PROCESSING','COMPLETED'}:
                        return {'state':'uncertain','reason':'PAID_SUBMIT_NOT_BOUND'}
                elif reconcile:
                    return {'state':'uncertain','reason':'FLOW_PREPARATION_INCOMPLETE'}
                else:
                    step='settings'
                    try:
                        readiness=self._prepare(page)
                    except ValueError as exc:
                        if str(exc) in {'NO_FLOW_CREDIT','FLOW_MODEL_CHANGED','FLOW_PRESET_UNVERIFIED'}:
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
                    prompt=story_video_prompt(panels,allow_unverified=True,
                        timing_policy=req["analysis"].get("timing_policy"))
                    step='fill_prompt'
                    progress({'preparation_step':step})
                    page.locator('div.ProseMirror').fill(prompt)
                    step='verify_composer'
                    progress({'preparation_step':step})
                    verified=verify_reference_composer(page,project,refs,prompt)
                    intent={'source_sha256':req['source_sha256'],'project_id':project,
                        'ordered_reference_ids':verified['ordered_reference_ids'],'prompt':prompt,
                        'duration_s':10,'aspect':'9:16','resolution':'360p','model':'Omni 1.1 Flash','variants':1}
                    self._check_enabled()
                    story.begin(intent)
                    with page.expect_response(lambda r:'rpcids=MZZa6b' in r.url,timeout=120000) as pending:
                        page.get_by_role('button',name='Bắt đầu tạo',exact=True).press('Enter')
                    response=pending.value
                    if response.status!=200:
                        raise RuntimeError('NATIVE_SUBMIT_UNCONFIRMED')
                    receipt=verified_native_submit(response.body().decode('utf-8'),response.request.post_data,intent)
                    record=story.submitted(receipt)
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

        This path is used for repair/recovery.  It performs only the read RPC that
        resolves the immutable media URL plus an authenticated GET of those bytes;
        it never presses the generate or upscale controls and works while production
        automation is paused.
        """
        required=('media_id','project_id','workflow_id')
        if (not isinstance(record,dict) or any(not isinstance(record.get(k),str)
                or not record[k] for k in required)):
            raise ValueError('RECOVERY_FLOW_IDENTITY_INVALID')
        if record['project_id']!=self.runtime.flow_project_id:
            raise ValueError('RECOVERY_FLOW_PROJECT_MISMATCH')
        folder=Path(folder)
        folder.mkdir(parents=True,exist_ok=True)
        provider=FlowBrowserSessionProvider(FlowProfileConfig.load(Path(self.runtime.flow_profile_config)),
                                            auth_probe=observe_flow_account,visible=False).open()
        try:
            page=provider.session.page
            page.goto('https://flow.google.com/project/'+record['project_id'],
                      wait_until='domcontentloaded',timeout=60000)
            page.get_by_role('button',name='Thông tin về tài khoản',exact=True).wait_for(
                state='visible',timeout=30000)
            if observe_flow_account(page).state!='authenticated':
                raise ValueError('FLOW_AUTH_REQUIRED')
            stem='highest' if highest else 'original'
            receipt_path=folder/(stem+'-download.json')
            final=folder/(stem+'.mp4')
            if receipt_path.exists():
                receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
                if (receipt.get('state')=='COMPLETED'
                        and all(receipt.get(k)==record[k] for k in required)
                        and final.is_file() and artifact(final)==receipt.get('artifact')):
                    validate_media(final,tool_root=self.settings.directory)
                    return {'path':str(final),'data':receipt['data']}
            resolution=720 if highest else 360
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
        media=validate_media(part,tool_root=self.settings.directory)
        wanted=int(re.match(r'\d+',selected)[0])
        if media['width']!=wanted or abs(media['duration_s']-10)>.1:
            raise ValueError('DOWNLOAD_MEDIA_MISMATCH')
        data={'selected_resolution':selected,'observed_options':labels,'highest':highest,**media}
        receipt={'state':'BYTES_VALIDATED',**{k:record[k] for k in ('media_id','project_id','workflow_id')},
                 'artifact':artifact(part),'data':data}
        atomic_json(receipt_path,receipt)
        os.replace(part,final)
        receipt.update(state='COMPLETED',artifact=artifact(final))
        atomic_json(receipt_path,receipt)
        return {'path':str(final),'data':data}

