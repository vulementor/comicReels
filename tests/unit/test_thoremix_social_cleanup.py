import json
from pathlib import Path

import pytest

from agent.thoremix.config import Settings, atomic_json
from kabin_reel_poster.core.models import OperationResult


class FakeCampaign:
    def __init__(self, settings, jobs):
        self.settings = settings
        self._jobs = jobs

    def get(self, job_id):
        return dict(self._jobs[job_id])


def test_video_ready_approved_correction_can_enter_proof_bound_cleanup(tmp_path, monkeypatch):
    from agent.thoremix import social_cleanup as mod
    from agent.thoremix import media_correction

    settings = Settings(root=str(tmp_path/'app'), input_dir=str(tmp_path/'input'))
    settings.save()
    current_id='a'*32
    stale_id='b'*32
    current_dir=tmp_path/'current'; current_dir.mkdir()
    stale_dir=tmp_path/'stale'; stale_dir.mkdir()
    stale_video=stale_dir/'stale.mp4'; stale_video.write_bytes(b'x'*4096)
    current_video=current_dir/'current.mp4'; current_video.write_bytes(b'y'*4096)
    current_digest='1'*64
    stale_digest='2'*64

    current_pkg={
        'job_id':current_id,'source_sha256':'3'*64,'video_sha256':'4'*64,
        'publication_targets':['facebook','tiktok'],'correction':{'kind':'clean_native_audio'}}
    current_pub={'package_sha256':current_digest,'platforms':{'tiktok':{
        'publication':{'operation_id':'current-op','idempotency_key':'current-key','state':'needs_input'}}}}
    stale_pkg={'job_id':stale_id,'source_sha256':'5'*64,'video_sha256':'6'*64}
    stale_pub={'complete':True,'package_sha256':stale_digest,'platforms':{'tiktok':{
        'publication':{'operation_id':'stale-op','idempotency_key':'stale-key',
                       'state':'confirmed','permalink':'https://www.tiktok.com/@thoremixofficial/video/1'}}}}
    jobs={
        current_id:{'id':current_id,'state':'video_ready','package_dir':str(current_dir)},
        stale_id:{'id':stale_id,'state':'published','package_dir':str(stale_dir)},
    }
    campaign=FakeCampaign(settings,jobs)
    monkeypatch.setattr(mod,'Campaign',lambda _s:campaign)
    monkeypatch.setattr(mod,'_package',lambda _c,jid:
        (jobs[jid], current_dir,current_pkg,current_pub,current_digest)
        if jid==current_id else
        (jobs[jid], stale_dir,stale_pkg,stale_pub,stale_digest))
    monkeypatch.setattr(media_correction,'correction_approval_valid',lambda *a,**k:True)

    current_record={
        'operation_id':'current-op','idempotency_key':'current-key','platform':'tiktok',
        'action':'publish_reel','actor':'thoremix','profile':settings.social_profile,
        'asset_sha256':'4'*64,'payload_json':json.dumps({'extra':{'package_sha256':current_digest}}),
        'payload_sha256':'7'*64,'evidence_json':'{}','state':'needs_input',
        'permalink':None,'external_id':None}
    stale_payload={
        'platform':'tiktok','video':str(stale_video),'caption':'old caption',
        'title':'old title','description':'old description','visibility':'public',
        'profile':settings.social_profile,'actor':'thoremix',
        'idempotency_key':'stale-key','extra':{'package_sha256':stale_digest}}
    stale_record={
        'operation_id':'stale-op','idempotency_key':'stale-key','platform':'tiktok',
        'action':'publish_reel','actor':'thoremix','profile':settings.social_profile,
        'asset_sha256':mod.sha256(stale_video),'payload_json':json.dumps(stale_payload),
        'payload_sha256':'8'*64,'evidence_json':'{}','state':'confirmed',
        'permalink':'https://www.tiktok.com/@thoremixofficial/video/1','external_id':'1'}
    monkeypatch.setattr(mod,'_effect',lambda _s,op: current_record if op=='current-op' else stale_record)
    monkeypatch.setattr(mod,'_bound_record',lambda *a,**k:None)
    proof=settings.data/'proof.json'; atomic_json(proof,{'ok':True})
    monkeypatch.setattr(mod,'_pre_submit_receipt',lambda *a,**k:proof)

    called=[]
    result=mod.cleanup_tiktok_stale_editor(
        settings,current_id,stale_id,
        runner=lambda _s,request,cleanup_id:
            called.append((request.video,cleanup_id)) or
            OperationResult(state='confirmed',operation_id=cleanup_id,evidence={'verified':True}))

    assert result['state']=='confirmed'
    assert len(called)==1
    assert result['current_job_id']==current_id
    assert result['stale_job_id']==stale_id
    assert result['stale_operation_id']=='stale-op'


def test_unapproved_correction_is_blocked_before_cleanup_runner(tmp_path, monkeypatch):
    from agent.thoremix import social_cleanup as mod
    from agent.thoremix import media_correction

    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'))
    settings.save()
    current_id='c'*32; stale_id='d'*32
    current={'id':current_id,'state':'video_ready','package_dir':str(tmp_path/'current')}
    stale={'id':stale_id,'state':'published','package_dir':str(tmp_path/'stale')}
    campaign=FakeCampaign(settings,{current_id:current,stale_id:stale})
    monkeypatch.setattr(mod,'Campaign',lambda _s:campaign)
    monkeypatch.setattr(mod,'_package',lambda _c,jid:
        (current,tmp_path/'current',{'correction':{'kind':'clean_native_audio'}},{},'1'*64)
        if jid==current_id else
        (stale,tmp_path/'stale',{}, {'complete':True}, '2'*64))
    monkeypatch.setattr(media_correction,'correction_approval_valid',lambda *a,**k:False)
    called=[]

    with pytest.raises(ValueError,match='CURRENT_CORRECTION_NOT_APPROVED'):
        mod.cleanup_tiktok_stale_editor(
            settings,current_id,stale_id,
            runner=lambda *a,**k: called.append(True))

    assert called==[]
