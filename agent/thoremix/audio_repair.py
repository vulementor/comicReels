"""Rebuild old finishing outputs from a clean, Flow-bound native download.

The current package video and any historical finishing base are audit evidence only:
they are never accepted as repair input.  Unpublished packages may be promoted after
hash checks; any package with publication intent receives a separate repair candidate
without mutating the frozen publication payload.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from .audio_guard import signal_stats, decode_pcm, verify_native_audio
from .config import Settings, atomic_json
from .core import Campaign, campaign_operation, root_operation, sha256
from .quality import POLICY


def _flow_identity(package: dict) -> dict:
    flow=package.get('flow')
    if not isinstance(flow,dict):
        raise ValueError('AUDIO_REPAIR_FLOW_IDENTITY_MISSING')
    keys=('media_id','project_id','workflow_id')
    if any(not isinstance(flow.get(k),str) or not flow[k] for k in keys):
        raise ValueError('AUDIO_REPAIR_FLOW_IDENTITY_INVALID')
    return {k:flow[k] for k in keys}


def _flow_story_receipt(settings: Settings, package: dict) -> dict:
    identity=_flow_identity(package)
    job_id=package.get('job_id')
    source_sha256=package.get('source_sha256')
    if (not isinstance(job_id,str) or not job_id
            or not isinstance(source_sha256,str)):
        raise ValueError('AUDIO_REPAIR_PACKAGE_IDENTITY_MISMATCH')
    path=settings.data/'production'/job_id/'flow'/'story-receipt.json'
    if not path.is_file() or path.is_symlink():
        raise ValueError('AUDIO_REPAIR_STORY_RECEIPT_MISSING')
    try:
        record=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,UnicodeError,ValueError,TypeError,json.JSONDecodeError):
        raise ValueError('AUDIO_REPAIR_STORY_RECEIPT_INVALID') from None
    from agent.services.flow_story_browser import _validate_recovery_record
    try:
        _validate_recovery_record(
            record,expected_project_id=identity['project_id'],
            expected_source_sha256=source_sha256)
    except (TypeError,ValueError) as error:
        raise ValueError('AUDIO_REPAIR_STORY_RECEIPT_INVALID') from error
    if any(record.get(key)!=identity[key] for key in identity):
        raise ValueError('AUDIO_REPAIR_STORY_RECEIPT_MISMATCH')
    return record


def _bound_local_native(
        settings: Settings, package: dict, record: dict) -> Path | None:
    """Use only immutable Flow downloads with their matching download receipt."""
    identity=_flow_identity(package)
    folder=settings.data/'production'/package['job_id']/'flow'
    for stem in ('highest','original'):
        video=folder/(stem+'.mp4')
        receipt_path=folder/(stem+'-download.json')
        if not video.is_file() or not receipt_path.is_file():
            continue
        try:
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        except (OSError,UnicodeError,ValueError,TypeError,json.JSONDecodeError):
            raise ValueError('AUDIO_REPAIR_NATIVE_RECEIPT_INVALID') from None
        if (receipt.get('state')!='COMPLETED'
                or any(receipt.get(k)!=identity[k] for k in identity)
                or receipt.get('artifact',{}).get('sha256')!=sha256(video)):
            raise ValueError('AUDIO_REPAIR_NATIVE_RECEIPT_INVALID')
        from .core import validate_media
        media=validate_media(video,tool_root=settings.directory)
        if sha256(video)!=receipt['artifact']['sha256']:
            raise ValueError('AUDIO_REPAIR_NATIVE_CHANGED')
        duration=record['intent']['duration_s']
        if abs(float(media.get('duration_s',-1))-duration)>.1:
            raise ValueError('AUDIO_REPAIR_NATIVE_DURATION_MISMATCH')
        return video
    return None


def _redownload_native(
        settings: Settings, package: dict, record: dict, target: Path) -> Path:
    """Read the already-created 720p derivative; no generation/upscale effect."""
    from .story_runtime import StoryRuntime
    from agent.services.flow_story_browser import FlowStoryBrowser
    runtime=StoryRuntime.load(settings)
    result=FlowStoryBrowser(settings,runtime).download_existing(
        record,target,highest=True)
    path=Path(result['path']).resolve(strict=True)
    if path.parent!=target.resolve():
        raise ValueError('AUDIO_REPAIR_DOWNLOAD_OUTSIDE_RECOVERY')
    return path


def _snapshot(settings: Settings, job_id: str):
    campaign=Campaign(settings)
    package=campaign.reconcile_package(job_id)
    job=campaign.get(job_id)
    folder=Path(job['package_dir']).resolve(strict=True)
    if folder.parent!=settings.output.resolve():
        raise ValueError('AUDIO_REPAIR_PACKAGE_OUTSIDE_OUTPUT')
    path=folder/'package.json'
    if package.get('job_id')!=job_id or package.get('source_sha256')!=job['source_sha256']:
        raise ValueError('AUDIO_REPAIR_PACKAGE_IDENTITY_MISMATCH')
    return campaign,job,folder,path,package,sha256(path)


def repair_audio(settings: Settings, job_id: str, *, downloader=None, force=False) -> dict:
    """Rebuild finishing from Flow native bytes and promote only if never published."""
    settings=Settings.load(settings.directory) if settings.path.exists() else settings
    campaign,job,folder,package_path,package,package_hash=_snapshot(settings,job_id)
    current_video=Path(package['video_path']).resolve(strict=True)
    if current_video.parent!=folder or sha256(current_video)!=package['video_sha256']:
        raise ValueError('AUDIO_REPAIR_CURRENT_VIDEO_CHANGED')
    record=_flow_story_receipt(settings,package)

    with root_operation(settings.data/'audio-repairs'/job_id):
        native=_bound_local_native(settings,package,record)
        source='local_bound_flow_download'
        if native is None:
            recovery=settings.data/'production'/job_id/'flow-recovery'
            native=(downloader(settings,package,record,recovery) if downloader
                    else _redownload_native(settings,package,record,recovery))
            native=Path(native).resolve(strict=True)
            source='redownloaded_bound_flow_derivative'
        if native in {current_video,Path(package.get('finishing',{}).get('base_path','')).resolve()}:
            raise ValueError('AUDIO_REPAIR_REFUSES_PROCESSED_SOURCE')

        native_stats=signal_stats(decode_pcm(settings,native))
        finishing=package.get('finishing') if isinstance(package.get('finishing'),dict) else {}
        laugh=finishing.get('laugh') if isinstance(finishing.get('laugh'),dict) else {}
        preserved=None
        try:
            preserved=verify_native_audio(settings,native,current_video,
                laugh_start_s=laugh.get('start_s'))
        except ValueError as error:
            if str(error) not in {'NATIVE_AUDIO_DROPPED','NATIVE_AUDIO_NOT_PRESERVED'}:
                raise
        if preserved is not None and not force:
            return {'state':'native_audio_already_preserved','job_id':job_id,
                    'native_path':str(native),'native_sha256':sha256(native),
                    'native_audio':native_stats,'proof':preserved}

        from .finishing import render,options
        render_dir=settings.data/'audio-repairs'/job_id/'render'
        rendered,finish_data=render(settings,native,render_dir,options(settings))
        repair_receipt={
            'state':'candidate_ready','job_id':job_id,'package_sha256_before':package_hash,
            'video_sha256_before':package['video_sha256'],'native_path':str(native),
            'native_sha256':sha256(native),'native_source':source,'native_audio':native_stats,
            'candidate_path':str(rendered),'candidate_sha256':sha256(rendered),
            'audio_guard':finish_data.get('audio_guard'),'finishing':finish_data,
        }
        receipt_path=settings.data/'audio-repairs'/job_id/'repair.json'
        atomic_json(receipt_path,repair_receipt)

        # Publication payloads are immutable.  A corrected candidate may be used
        # by a separately authorized revision, but this repair never overwrites it.
        publication=folder/'publication.json'
        current_job=campaign.get(job_id)
        if publication.exists() or current_job['state'] in {'publishing','published','wrong_media_blocked'}:
            repair_receipt['state']='candidate_ready_revision_required'
            atomic_json(receipt_path,repair_receipt)
            return repair_receipt

        with campaign_operation(settings):
            current_job=campaign.get(job_id)
            if (Path(current_job['package_dir']).resolve()!=folder
                    or sha256(package_path)!=package_hash
                    or (folder/'publication.json').exists()
                    or current_job['state'] in {'publishing','published','wrong_media_blocked'}):
                repair_receipt['state']='candidate_ready_revision_required'
                atomic_json(receipt_path,repair_receipt)
                return repair_receipt
            edits=folder/'edits'
            history=edits/'history'
            history.mkdir(parents=True,exist_ok=True)
            from .finishing import _archive,_promote
            _archive(package_path,history/(package_hash+'.json'),package_hash)
            promoted_render=edits/('audio-repair-'+sha256(rendered)+'.mp4')
            if not promoted_render.exists():
                shutil.copy2(rendered,promoted_render)
            if sha256(promoted_render)!=sha256(rendered):
                raise ValueError('AUDIO_REPAIR_CANDIDATE_CHANGED')

            updated=json.loads(json.dumps(package))
            updated.update(video_sha256=finish_data['video_sha256'],
                           media=finish_data['media'],finishing=finish_data)
            qa=dict(updated.get('qa') or {})
            qa.update(policy=POLICY,production_complete=True,release_ready=False)
            updated['qa']=qa
            review=dict(updated.get('review') or {})
            updated['review']={'status':'pending','warnings':list(review.get('warnings') or []),
                'reason':'Âm thanh đã được dựng lại từ bản Flow native sạch; cần xem/nghe bản mới trước khi đăng.'}
            transaction={'key':'audio-repair-'+finish_data['render_key'],'before':package,
                         'after':updated,'rendered':str(promoted_render)}
            atomic_json(edits/'pending.json',transaction)
            final=_promote(campaign,current_job,folder,transaction)
            repair_receipt.update(state='promoted_awaiting_approval',
                                  package_sha256_after=sha256(package_path),
                                  video_sha256_after=final['video_sha256'])
            atomic_json(receipt_path,repair_receipt)
            return repair_receipt


def repair_all_finished(settings: Settings, *, force=False) -> dict:
    """Audit/rebuild every package that has historical finishing metadata."""
    campaign=Campaign(settings)
    results=[]
    for job in campaign.jobs():
        folder=Path(job['package_dir'])
        path=folder/'package.json'
        if not path.is_file():
            continue
        try:
            package=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            continue
        if not isinstance(package.get('finishing'),dict):
            continue
        results.append(repair_audio(settings,job['id'],force=force))
    return {'state':'audio_repair_batch_finished','processed':len(results),'results':results}
