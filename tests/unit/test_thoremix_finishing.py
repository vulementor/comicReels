import json
import subprocess
import os
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from agent.thoremix.config import Settings,atomic_json
from agent.thoremix.core import Campaign,media_tool,sha256,validate_media
from agent.thoremix.finishing import render,apply_package,recover_pending
from agent.thoremix.quality import POLICY,manifest_digest,request_approval


@pytest.fixture
def media(tmp_path):
    source=tmp_path/'input';source.mkdir()
    s=Settings(root=str(tmp_path/'app'),input_dir=str(source))
    s.save();ffmpeg=media_tool('ffmpeg',s.directory)
    video=tmp_path/'native.mp4';laugh=tmp_path/'laugh.mp3'
    for args in [
        ['-f','lavfi','-i','color=c=blue:s=120x240:r=24:d=2','-f','lavfi','-i','sine=frequency=220:duration=2',
         '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],
        ['-f','lavfi','-i','sine=frequency=1000:duration=0.3',str(laugh)]]:
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',*args],check=True,capture_output=True)
    s=replace(s,laugh_enabled=True,laugh_path=str(laugh));s.save()
    return s,video,laugh


def rgb(settings,path):
    raw=subprocess.run([media_tool('ffmpeg',settings.directory),'-v','error','-i',str(path),
        '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],check=True,capture_output=True).stdout
    return np.frombuffer(raw,np.uint8).reshape(240,120,3)


def test_media_validation_handles_vietnamese_path_with_windows_legacy_encoding(media,tmp_path):
    import shutil
    s,video,_=media
    translated=tmp_path/'Thỏ Remix';translated.mkdir()
    target=translated/'tiếng cười.mp4';shutil.copy2(video,target)
    code='from pathlib import Path;from agent.thoremix.core import validate_media;import sys,json;print(json.dumps(validate_media(Path(sys.argv[1]),tool_root=Path(sys.argv[2]))))'
    result=subprocess.run([sys.executable,'-X','utf8=0','-c',code,str(target),str(s.directory)],
        capture_output=True,env=dict(os.environ,PYTHONUTF8='0'),check=True)
    assert json.loads(result.stdout)['full_decode'] is True


def test_render_masks_preserve_dimensions_duration_and_add_laugh_only_at_end(media,tmp_path):
    s,video,laugh=media
    original=sha256(video)
    final,receipt=render(s,video,tmp_path/'renders')
    assert sha256(video)==original
    assert receipt['media']['width']==120 and receipt['media']['height']==240
    assert abs(receipt['media']['duration_s']-2)<.05
    pixels=rgb(s,final)
    assert pixels[:23].max()<8 and pixels[-26:].max()<8
    assert np.abs(pixels[40:200].astype(int)-rgb(s,video)[40:200].astype(int)).max()<8
    audio=subprocess.run([media_tool('ffmpeg',s.directory),'-v','error','-i',str(final),'-vn','-ac','1',
        '-ar','8000','-f','f32le','-'],check=True,capture_output=True).stdout
    pcm=np.frombuffer(audio,np.float32)
    def band(start,end):
        a=pcm[int(start*8000):int(end*8000)];spectrum=np.abs(np.fft.rfft(a));freq=np.fft.rfftfreq(len(a),1/8000)
        return spectrum[(freq>950)&(freq<1050)].max()
    assert band(1.8,1.95)>10*band(.2,.35)
    # Catch replacement or attenuation of the original track, including the overlap.
    original_pcm=np.frombuffer(subprocess.run([media_tool('ffmpeg',s.directory),'-v','error','-i',str(video),
        '-vn','-ac','1','-ar','8000','-f','f32le','-'],check=True,capture_output=True).stdout,np.float32)
    for start,end in [(.2,.35),(1.8,1.95)]:
        source=original_pcm[int(start*8000):int(end*8000)]
        mixed=pcm[int(start*8000):int(end*8000)]
        frequency=np.fft.rfftfreq(len(source),1/8000)
        native_band=(frequency>200)&(frequency<240)
        ratio=np.linalg.norm(np.fft.rfft(mixed)[native_band])/np.linalg.norm(np.fft.rfft(source)[native_band])
        assert .95<ratio<1.05
    assert receipt['laugh']['end_s']==receipt['media']['duration_s']
    stamp=final.stat().st_mtime_ns
    assert render(s,video,tmp_path/'renders')[0]==final and final.stat().st_mtime_ns==stamp


def package(media,*,approved=False):
    s,video,_=media;Image.new('RGB',(40,80),'yellow').save(Path(s.input_dir)/'story.png')
    c=Campaign(s);job=c.reserve('production/test')
    manifest=c.finalize(job['id'],video,children=[],metadata={
        'qa':{'policy':POLICY,'production_complete':True,'release_ready':not approved},
        'review':{'status':'pending' if approved else 'not_required',
                  'warnings':[{'stage':'video'}] if approved else []}})
    if approved:manifest=c.approve(job['id'],manifest_digest(manifest))
    return c,job,manifest


def test_existing_approved_unposted_clip_is_reversible_and_needs_new_approval(media):
    c,job,old=package(media,approved=True)
    first=apply_package(c,job['id']);m=first['package'];folder=Path(job['package_dir'])
    assert first['state']=='processed' and c.get(job['id'])['state']=='awaiting_approval'
    assert m['video_path']==old['video_path'] and sha256(folder/'edits/original.mp4')==old['video_sha256']
    assert m['created_at']==old['created_at']
    assert apply_package(c,job['id'])['state']=='unchanged'
    s=replace(c.settings,mask_enabled=False,laugh_enabled=False);s.save()
    restored=apply_package(Campaign(s),job['id'])['package']
    assert restored['finishing']['base_sha256']==old['video_sha256']
    assert rgb(s,Path(restored['video_path']))[0,0,2]>240


@pytest.mark.parametrize('state,receipt',[('published',False),('publishing',False),('video_ready',True)])
def test_any_publication_intent_excludes_media_edits(media,state,receipt):
    c,job,old=package(media)
    c.update(job['id'],state)
    if receipt:atomic_json(Path(job['package_dir'])/'publication.json',{'complete':False})
    assert apply_package(c,job['id'])['state']=='skipped_publication'
    assert sha256(Path(old['video_path']))==old['video_sha256']
    assert not (Path(job['package_dir'])/'edits').exists()


@pytest.mark.parametrize('after_video',[False,True])
def test_interrupted_local_swap_recovers_before_direct_owner_approval(media,monkeypatch,after_video):
    import agent.thoremix.finishing as module
    c,job,old=package(media,approved=True)
    if after_video:
        original=module.atomic_json
        def crash(path,data):
            if path==Path(job['package_dir'])/'package.json':raise OSError('crash after video replacement')
            original(path,data)
        monkeypatch.setattr(module,'atomic_json',crash)
    else:
        original=module._promote
        monkeypatch.setattr(module,'_promote',lambda *a:(_ for _ in ()).throw(OSError('before video swap')))
    with pytest.raises(OSError):apply_package(c,job['id'])
    monkeypatch.undo()
    # Old click cannot approve the transformed file; direct approve first recovers the swap.
    with pytest.raises(ValueError):c.approve(job['id'],manifest_digest(old))
    current=c.reconcile_package(job['id'])
    assert not (Path(job['package_dir'])/'edits/pending.json').exists()
    assert sha256(Path(current['video_path']))==current['video_sha256']
    assert c.get(job['id'])['state']=='awaiting_approval'
    assert c.approve(job['id'],manifest_digest(current))['review']['status']=='approved'


def test_settings_copy_temporary_laugh_into_stable_assets(media):
    from agent.thoremix.sdk import ThoRemixClient
    s,_,laugh=media
    updated=ThoRemixClient(s.directory).configure_finishing(laugh_enabled=True,laugh_path=str(laugh),mask_enabled=True)
    copied=Path(updated.laugh_path)
    assert copied.is_relative_to(s.directory/'assets/laugh') and sha256(copied)==sha256(laugh)
    laugh.unlink();assert copied.is_file()


def test_auto_ready_revision_keeps_paid_receipt_immutable_and_binds_archived_manifest(media):
    from agent.comicreels.story import StoryReceipt
    c,job,old=package(media)
    path=Path(job['package_dir'])/'package.json'
    identity={'project_id':'11111111-2222-3333-4444-555555555555',
              'media_id':'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
              'workflow_id':'11111111-aaaa-bbbb-cccc-dddddddddddd'}
    old['flow']=identity;atomic_json(path,old)
    prior_hash=sha256(path)
    receipt=c.settings.data/'production'/job['id']/'flow/story-receipt.json'
    native=StoryReceipt(receipt)
    native.begin({'source_sha256':old['source_sha256'],'project_id':identity['project_id'],
        'ordered_reference_ids':['aaaaaaaa-1111-2222-3333-444444444444'],'prompt':'Một câu chuyện.',
        'duration_s':10,'aspect':'9:16','resolution':'360p','model':'Omni 1.1 Flash','variants':1})
    native.submitted(identity);native.complete(path)
    receipt_before=receipt.read_bytes()
    result=apply_package(c,job['id'])
    binding=json.loads((path.parent/'edits/flow-binding.json').read_text())
    assert binding['package_sha256']==sha256(path) and binding['video_sha256']==result['package']['video_sha256']
    assert receipt.read_bytes()==receipt_before
    assert sha256(path.parent/'edits/history'/(prior_hash+'.json'))==prior_hash
    assert apply_package(c,job['id'])['state']=='unchanged'
    recover_pending(c,job['id']);assert receipt.read_bytes()==receipt_before


def test_finish_intent_survives_partial_package_promotion_and_settings_change(media,monkeypatch):
    import agent.thoremix.core as core
    from agent.thoremix.story_assets import save_working_assets
    from agent.thoremix.story_operations import StoryOperations,artifact
    from agent.thoremix.story_stages import StageJournal
    from types import SimpleNamespace
    s,video,_=media
    source=Path(s.input_dir)/'story.png';Image.new('RGB',(40,80),'yellow').save(source)
    c=Campaign(s);job=c.reserve('production/interrupted')
    save_working_assets(s,job,[artifact(source)])
    directory=s.data/'production'/job['id'];journal=StageJournal(directory,source_sha256=job['source_sha256'])
    operations=StoryOperations(s,SimpleNamespace())
    req={'source':str(source),'video':{'files':[artifact(video)]}}
    result=journal.run('finishing',req,lambda progress:operations.execute('finishing',req,directory,progress))
    final=Path(result['files'][0]['path']);metadata={'qa':{'release_ready':True},'finishing':result['data']}
    original=core.os.replace
    def crash(incoming,destination):
        if Path(destination)==Path(job['package_dir'])/'package.json':raise OSError('after MP4 promotion')
        return original(incoming,destination)
    monkeypatch.setattr(core.os,'replace',crash)
    with pytest.raises(OSError):c.finalize(job['id'],final,children=[source],metadata=metadata)
    monkeypatch.undo()
    replace(s,mask_enabled=False,laugh_enabled=False).save()
    restored=journal.run('finishing',req,lambda _:pytest.fail('must reuse frozen completed render'))
    assert restored==result
    package=c.finalize(job['id'],Path(restored['files'][0]['path']),children=[source],metadata=metadata)
    assert package['video_sha256']==sha256(final) and package['finishing']['options']['mask_enabled'] is True
