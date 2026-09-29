import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

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
            '-f','lavfi','-i','color=c=blue:s=120x240:r=24:d=2',
            '-f','lavfi','-i','sine=frequency=220:duration=2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(clean)],
            check=True,capture_output=True)
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',
            '-f','lavfi','-i','color=c=blue:s=120x240:r=24:d=2',
            '-f','lavfi','-i','anullsrc=r=44100:cl=mono',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-t','2',str(faulty)],
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
    highest=flow/'highest.mp4';shutil.copy2(clean,highest)
    atomic_json(flow/'highest-download.json',{'state':'COMPLETED',**identity,
        'artifact':{'path':str(highest),'sha256':sha256(highest)},
        'data':{'selected_resolution':'120p test','highest':True,
                'duration_s':2.0,'width':120,'height':240,'full_decode':True}})
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
    shutil.rmtree(flow)
    calls=[]
    def downloader(settings,package,target):
        calls.append((package['flow'],target))
        target.mkdir(parents=True,exist_ok=True)
        recovered=target/'highest.mp4'
        shutil.copy2(clean,recovered)
        return recovered
    result=repair_audio(s,job['id'],downloader=downloader)
    assert result['state']=='promoted_awaiting_approval'
    assert len(calls)==1
    package=campaign.reconcile_package(job['id'])
    assert package['finishing']['base_path'].endswith('flow-recovery\\highest.mp4') or package['finishing']['base_path'].endswith('flow-recovery/highest.mp4')
    assert package['finishing']['base_sha256']==sha256(clean)
