import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from agent.comicreels.story import StoryReceipt
from agent.thoremix.audio_guard import decode_pcm, signal_stats
from agent.thoremix.audio_repair import repair_audio
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import Campaign, media_tool, sha256


@pytest.fixture
def repair_rig(tmp_path):
    source=tmp_path/'input';source.mkdir()
    root=tmp_path/'app'
    s=Settings(root=str(root),input_dir=str(source),enabled=False)
    s.save()
    ffmpeg=media_tool('ffmpeg',s.directory)
    clean=tmp_path/'clean.mp4'
    faulty=tmp_path/'faulty.mp4'
    laugh=tmp_path/'laugh.mp3'
    try:
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',
            '-f','lavfi','-i','color=c=blue:s=120x240:r=24:d=4',
            '-f','lavfi','-i','sine=frequency=220:duration=4',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(clean)],
            check=True,capture_output=True)
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',
            '-f','lavfi','-i','color=c=blue:s=120x240:r=24:d=4',
            '-f','lavfi','-i','anullsrc=r=44100:cl=mono',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-t','4',str(faulty)],
            check=True,capture_output=True)
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',
            '-f','lavfi','-i','sine=frequency=1000:duration=0.3',str(laugh)],
            check=True,capture_output=True)
    except (FileNotFoundError,subprocess.CalledProcessError):
        pytest.skip('ffmpeg required')
    s=replace(s,laugh_enabled=True,laugh_path=str(laugh),mask_enabled=False)
    s.save()
    image=source/'story.png';Image.new('RGB',(40,80),'white').save(image)
    campaign=Campaign(s);job=campaign.reserve('repair/test')
    identity={'project_id':'11111111-2222-3333-4444-555555555555',
              'media_id':'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
              'workflow_id':'99999999-aaaa-bbbb-cccc-dddddddddddd'}
    package=campaign.finalize(job['id'],faulty,children=[],metadata={
        'title':'Repair','caption':'Repair','description':'Repair',
        'qa':{'release_ready':True},'flow':identity,
        'publication_targets':['facebook','tiktok','youtube'],
        'finishing':{'base_path':str(faulty),'base_sha256':sha256(faulty),
                     'laugh':{'start_s':1.7,'duration_s':0.3,'end_s':2.0}},
    })
    flow=s.data/'production'/job['id']/'flow';flow.mkdir(parents=True)
    story=StoryReceipt(flow/'story-receipt.json')
    story.begin({
        'source_sha256':job['source_sha256'],'project_id':identity['project_id'],
        'ordered_reference_ids':[identity['media_id']],'prompt':'audio-repair-fixture',
        'duration_s':4,'model':'Omni 1.1 Flash','resolution':'360p',
        'aspect':'9:16','variants':1,
    })
    story.submitted(identity)
    highest=flow/'highest.mp4';shutil.copy2(clean,highest)
    atomic_json(flow/'highest-download.json',{'state':'COMPLETED',**identity,
        'artifact':{'path':str(highest),'sha256':sha256(highest)},
        'data':{'selected_resolution':'120p test','highest':True,
                'duration_s':4.0,'width':120,'height':240,'full_decode':True}})
    return s,campaign,job,package,clean,faulty


def test_repair_promotes_only_from_bound_clean_native_and_requires_new_approval(repair_rig):
    s,campaign,job,old,clean,faulty=repair_rig
    old_hash=old['video_sha256']
    result=repair_audio(s,job['id'])
    assert result['state']=='promoted_awaiting_approval'
    package=campaign.reconcile_package(job['id'])
    assert package['video_sha256']!=old_hash
    assert package['finishing']['base_sha256']==sha256(
        s.data/'production'/job['id']/'flow/highest.mp4')
    assert package['finishing']['base_sha256']!=sha256(faulty)
    assert package['review']['status']=='pending'
    assert package['qa']['release_ready'] is False
    assert campaign.get(job['id'])['state']=='awaiting_approval'
    assert package['finishing']['audio_guard']['preserved'] is True
    final_stats=signal_stats(decode_pcm(s,Path(package['video_path'])))
    assert not final_stats['all_zero']


def test_publication_intent_keeps_frozen_package_and_only_builds_candidate(repair_rig):
    s,campaign,job,old,clean,faulty=repair_rig
    folder=Path(job['package_dir'])
    before_manifest=(folder/'package.json').read_bytes()
    before_video=Path(old['video_path']).read_bytes()
    atomic_json(folder/'publication.json',{'complete':False})
    campaign.update(job['id'],'publishing')
    result=repair_audio(s,job['id'])
    assert result['state']=='candidate_ready_revision_required'
    assert Path(result['candidate_path']).is_file()
    assert (folder/'package.json').read_bytes()==before_manifest
    assert Path(old['video_path']).read_bytes()==before_video
    assert campaign.get(job['id'])['state']=='publishing'


def test_missing_local_native_uses_injected_bound_redownload_not_processed_video(repair_rig):
    s,campaign,job,old,clean,faulty=repair_rig
    flow=s.data/'production'/job['id']/'flow'
    (flow/'highest.mp4').unlink()
    (flow/'highest-download.json').unlink()
    calls=[]
    def downloader(settings,package,record,target):
        calls.append((package['flow'],record,target))
        target.mkdir(parents=True,exist_ok=True)
        recovered=target/'highest.mp4'
        shutil.copy2(clean,recovered)
        return recovered
    result=repair_audio(s,job['id'],downloader=downloader)
    assert result['state']=='promoted_awaiting_approval'
    assert len(calls)==1
    assert calls[0][1]['intent']['duration_s']==4
    package=campaign.reconcile_package(job['id'])
    assert package['finishing']['base_path'].endswith('flow-recovery\\highest.mp4') or package['finishing']['base_path'].endswith('flow-recovery/highest.mp4')
    assert package['finishing']['base_sha256']==sha256(clean)


@pytest.mark.parametrize(('kind','reason'),[
    ('missing','AUDIO_REPAIR_STORY_RECEIPT_MISSING'),
    ('corrupt','AUDIO_REPAIR_STORY_RECEIPT_INVALID'),
    ('unknown','AUDIO_REPAIR_STORY_RECEIPT_INVALID'),
    ('wrong_source','AUDIO_REPAIR_STORY_RECEIPT_INVALID'),
    ('wrong_media','AUDIO_REPAIR_STORY_RECEIPT_MISMATCH'),
])
def test_repair_requires_exact_durable_story_receipt_before_native_or_provider(
        repair_rig,monkeypatch,kind,reason):
    from agent.thoremix import audio_repair

    s,_campaign,job,_old,_clean,_faulty=repair_rig
    path=s.data/'production'/job['id']/'flow'/'story-receipt.json'
    if kind=='missing':
        path.unlink()
    elif kind=='corrupt':
        path.write_text('{',encoding='utf-8')
    else:
        record=json.loads(path.read_text(encoding='utf-8'))
        if kind=='unknown':
            record['state']='UNKNOWN'
        elif kind=='wrong_source':
            record['intent']['source_sha256']='f'*64
        elif kind=='wrong_media':
            record['media_id']='bbbbbbbb-cccc-dddd-eeee-ffffffffffff'
        path.write_text(json.dumps(record),encoding='utf-8')
    monkeypatch.setattr(
        audio_repair,'_bound_local_native',
        lambda *_args,**_kwargs:pytest.fail('local native must not be adopted'))
    monkeypatch.setattr(
        audio_repair,'_redownload_native',
        lambda *_args,**_kwargs:pytest.fail('provider recovery must not open'))
    with pytest.raises(ValueError,match=reason):
        audio_repair.repair_audio(s,job['id'])


def test_local_native_duration_mismatch_fails_before_redownload(
        repair_rig,monkeypatch):
    from agent.thoremix import audio_repair

    s,_campaign,job,_old,_clean,_faulty=repair_rig
    path=s.data/'production'/job['id']/'flow'/'story-receipt.json'
    record=json.loads(path.read_text(encoding='utf-8'))
    record['intent']['duration_s']=6
    path.write_text(json.dumps(record),encoding='utf-8')
    monkeypatch.setattr(
        audio_repair,'_redownload_native',
        lambda *_args,**_kwargs:pytest.fail('provider recovery must not open'))
    with pytest.raises(ValueError,match='AUDIO_REPAIR_NATIVE_DURATION_MISMATCH'):
        audio_repair.repair_audio(s,job['id'])


@pytest.mark.parametrize('duration',[4,6,8,10])
def test_audio_recovery_redownload_existing_promotes_exact_duration(
        tmp_path,monkeypatch,duration):
    from types import SimpleNamespace

    from agent.services import flow_story_browser as flow
    from agent.thoremix import audio_repair, story_runtime

    source=tmp_path/'input';source.mkdir()
    s=Settings(root=str(tmp_path/'app'),input_dir=str(source),enabled=False)
    s.save()
    job_id='b'*32
    identity={
        'project_id':'11111111-2222-3333-4444-555555555555',
        'media_id':'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'workflow_id':'99999999-aaaa-bbbb-cccc-dddddddddddd',
    }
    package={'job_id':job_id,'source_sha256':'a'*64,'flow':identity}
    flow_dir=s.data/'production'/job_id/'flow'
    flow_dir.mkdir(parents=True)
    story=StoryReceipt(flow_dir/'story-receipt.json')
    story.begin({
        'source_sha256':package['source_sha256'],
        'project_id':identity['project_id'],
        'ordered_reference_ids':[identity['media_id']],
        'prompt':'synthetic-audio-recovery',
        'duration_s':duration,'model':'Omni 1.1 Flash',
        'resolution':'360p','aspect':'9:16','variants':1,
    })
    story.submitted(identity)
    record=audio_repair._flow_story_receipt(s,package)
    runtime=SimpleNamespace(
        flow_profile_config='config',flow_project_id=identity['project_id'])
    monkeypatch.setattr(
        story_runtime.StoryRuntime,'load',staticmethod(lambda _settings:runtime))
    monkeypatch.setattr(
        flow.FlowProfileConfig,'load',lambda _path:SimpleNamespace())

    class Node:
        def wait_for(self,**_kwargs):
            return None
    class Response:
        status=200
        def body(self):
            return b'x'*2048
    class Requests:
        def get(self,*_args,**_kwargs):
            return Response()
    class Page:
        request=Requests()
        def goto(self,*_args,**_kwargs):
            return None
        def get_by_role(self,*_args,**_kwargs):
            return Node()

    provider=SimpleNamespace(
        session=SimpleNamespace(page=Page()),close=lambda:None)
    monkeypatch.setattr(
        flow,'FlowBrowserSessionProvider',
        lambda *args,**kwargs:SimpleNamespace(open=lambda:provider))
    monkeypatch.setattr(
        flow,'observe_flow_account',
        lambda _page:SimpleNamespace(state='authenticated',identity='owner@example.com'))
    monkeypatch.setattr(
        flow.FlowStoryBrowser,'_rpc',lambda *_args,**_kwargs:{})
    monkeypatch.setattr(
        flow.fb,'read_media_urls',
        lambda _data,derivative:SimpleNamespace(
            video='https://flow-content.google/video/'+derivative))
    monkeypatch.setattr(
        flow,'validate_media',
        lambda *_args,**_kwargs:{'width':720,'duration_s':float(duration)})

    target=s.data/'production'/job_id/'flow-recovery'
    recovered=audio_repair._redownload_native(s,package,record,target)
    assert recovered==target/'highest.mp4'
    receipt=json.loads((target/'highest-download.json').read_text(encoding='utf-8'))
    assert receipt['state']=='COMPLETED'
    assert receipt['data']['duration_s']==float(duration)
    assert receipt['data']['width']==720
    assert receipt['data']['highest'] is True
