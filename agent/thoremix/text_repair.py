"""Repair verified source signage on an already-produced clip.

This is a recovery path for legacy output only.  Geometry and exact text must be
supplied by a hash-bound verified spec; the code never OCR-guesses, never edits a
published payload in place, and always returns an unpublished repair to review.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from agent.comicreels.sign_text import render_sign_text, select_overlay_font, validate_overlay

from .audio_guard import verify_native_audio
from .config import Settings, atomic_json
from .core import Campaign, campaign_operation, media_tool, root_operation, sha256, validate_media
from .quality import POLICY


def _bound_repair_input(settings: Settings, job_id: str, folder: Path, package: dict, expected_sha: str) -> Path:
    current=Path(package['video_path']).resolve(strict=True)
    if sha256(current)==expected_sha:
        return current
    overlay=package.get('source_text_overlay') if isinstance(package.get('source_text_overlay'),dict) else {}
    if overlay.get('base_video_sha256')!=expected_sha:
        raise ValueError('SOURCE_TEXT_REPAIR_SPEC_NOT_BOUND')
    roots=[
        folder/'edits',
        settings.data/'audio-repairs'/job_id,
        settings.data/'production'/job_id/'finishing',
    ]
    matches=[]
    for root in roots:
        if not root.exists():
            continue
        for candidate in root.rglob('*.mp4'):
            try:
                resolved=candidate.resolve(strict=True)
                if sha256(resolved)==expected_sha:
                    validate_media(resolved,tool_root=settings.directory)
                    matches.append(resolved)
            except (OSError,ValueError):
                continue
    unique=list(dict.fromkeys(matches))
    if not unique:
        raise ValueError('SOURCE_TEXT_REPAIR_BASE_NOT_FOUND')
    return unique[0]


def repair_source_text(settings: Settings, job_id: str, spec: dict, *, font: Path | None = None) -> dict:
    settings=Settings.load(settings.directory) if settings.path.exists() else settings
    spec=validate_overlay(spec)
    campaign=Campaign(settings)
    job=campaign.get(job_id)
    folder=Path(job['package_dir']).resolve(strict=True)
    if folder.parent!=settings.output.resolve():
        raise ValueError('SOURCE_TEXT_REPAIR_PACKAGE_OUTSIDE_OUTPUT')
    package_path=folder/'package.json'
    package=campaign.reconcile_package(job_id)
    before_hash=sha256(package_path)
    source=Path(package['source_path']).resolve(strict=True)
    current_video=Path(package['video_path']).resolve(strict=True)
    if (source.parent!=folder or current_video.parent!=folder
            or sha256(source)!=package['source_sha256']
            or sha256(current_video)!=package['video_sha256']):
        raise ValueError('SOURCE_TEXT_REPAIR_PACKAGE_CHANGED')
    if spec['source_sha256']!=package['source_sha256']:
        raise ValueError('SOURCE_TEXT_REPAIR_SPEC_NOT_BOUND')
    existing=package.get('source_text_overlay') if isinstance(package.get('source_text_overlay'),dict) else {}
    if (existing.get('spec')==spec
            and existing.get('output_sha256')==package['video_sha256']):
        if sha256(current_video)!=existing['output_sha256']:
            raise ValueError('SOURCE_TEXT_REPAIR_OUTPUT_CHANGED')
        return {'state':'source_text_already_repaired','job_id':job_id,
                'video_sha256':package['video_sha256'],
                'base_video_sha256':existing.get('base_video_sha256'),
                'source_text_overlay':existing}
    video=_bound_repair_input(settings,job_id,folder,package,spec['video_sha256'])

    font=Path(font).resolve(strict=True) if font else select_overlay_font(spec['text'])
    work=settings.data/'source-text-repairs'/job_id
    work.mkdir(parents=True,exist_ok=True)
    output=work/(package['video_sha256'][:16]+'-source-text.mp4')
    receipt_path=work/'repair.json'
    if output.exists():
        output.unlink()
    receipt=render_sign_text(video,source,output,work,spec,
        ffmpeg=Path(media_tool('ffmpeg',settings.directory)),
        ffprobe=Path(media_tool('ffprobe',settings.directory)),font=font)
    media=validate_media(output,tool_root=settings.directory)
    audio_guard=verify_native_audio(settings,video,output)
    repair={'state':'candidate_ready','job_id':job_id,'package_sha256_before':before_hash,
        'video_sha256_before':package['video_sha256'],'candidate_path':str(output),
        'candidate_sha256':sha256(output),'overlay':receipt,'audio_guard':audio_guard}
    atomic_json(receipt_path,repair)

    # Existing publication evidence remains immutable.  The candidate can later
    # become a separately authorized correction revision.
    current=campaign.get(job_id)
    if (folder/'publication.json').exists() or current['state'] in {'publishing','published','wrong_media_blocked'}:
        repair['state']='candidate_ready_revision_required'
        atomic_json(receipt_path,repair)
        return repair

    with campaign_operation(settings):
        current=campaign.get(job_id)
        if (sha256(package_path)!=before_hash or (folder/'publication.json').exists()
                or current['state'] in {'publishing','published','wrong_media_blocked'}):
            repair['state']='candidate_ready_revision_required'
            atomic_json(receipt_path,repair)
            return repair
        edits=folder/'edits';history=edits/'history';history.mkdir(parents=True,exist_ok=True)
        from .finishing import _archive,_promote
        _archive(package_path,history/(before_hash+'.json'),before_hash)
        promoted=edits/('source-text-'+sha256(output)+'.mp4')
        if not promoted.exists():
            shutil.copy2(output,promoted)
        if sha256(promoted)!=sha256(output):
            raise ValueError('SOURCE_TEXT_REPAIR_CANDIDATE_CHANGED')
        updated=json.loads(json.dumps(package))
        updated['video_sha256']=sha256(output)
        updated['media']=media
        updated['source_text_overlay']={
            'base_video_sha256':sha256(video),
            'output_sha256':sha256(output),
            'spec':spec,
            'receipt_sha256':sha256(work/'sign-overlay-receipt.json'),
            'audio_stream_preserved':audio_guard,
        }
        qa=dict(updated.get('qa') or {})
        qa.update(policy=POLICY,production_complete=True,release_ready=False)
        updated['qa']=qa
        old_review=updated.get('review') if isinstance(updated.get('review'),dict) else {}
        warnings=list(old_review.get('warnings') or [])
        warnings.append({'stage':'source_text_repair','result':{
            'accepted':False,'issues':['SOURCE_TEXT_OVERLAY_REQUIRES_OWNER_REVIEW'],
            'reason':'Đã phục hồi chữ nguồn bằng geometry đã xác minh; cần xem bản mới trước khi đăng.'}})
        updated['review']={'status':'pending','warnings':warnings,
            'reason':'Đã phục hồi chữ nguồn trên bảng; cần xem bản mới trước khi đăng.'}
        transaction={'key':'source-text-'+receipt['output_sha256'],'before':package,
                     'after':updated,'rendered':str(promoted)}
        atomic_json(edits/'pending.json',transaction)
        final=_promote(campaign,current,folder,transaction)
        repair.update(state='promoted_awaiting_approval',
                      package_sha256_after=sha256(package_path),
                      video_sha256_after=final['video_sha256'])
        atomic_json(receipt_path,repair)
        return repair


def repair_source_text_from_file(settings: Settings, job_id: str, spec_path: Path) -> dict:
    spec_path=Path(spec_path).resolve(strict=True)
    spec=json.loads(spec_path.read_text(encoding='utf-8'))
    return repair_source_text(settings,job_id,spec)
