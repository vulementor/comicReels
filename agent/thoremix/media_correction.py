"""Prepare a clean-media correction for Facebook/TikTok without touching retained YouTube.

This is intentionally separate from wrong-media cleanup revisions.  The prior
Facebook/TikTok effects must be durably proven pre-submit, while the prior
YouTube publication must be journal-confirmed.  Preparation is local only: no
social SDK/browser action occurs here.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from .config import Settings, atomic_json
from .core import Campaign, campaign_operation, now_iso, sha256, validate_media

ACTOR = 'thoremix'
TARGETS = ('facebook', 'tiktok')


def _json(path: Path) -> dict:
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('CORRECTION_JSON_OBJECT_REQUIRED')
    return value


def _contained_file(path, parent: Path, digest: str | None = None) -> Path:
    value = Path(path).resolve(strict=True)
    if not value.is_file() or not value.is_relative_to(parent.resolve()):
        raise ValueError('CORRECTION_FILE_OUTSIDE_BOUND_ROOT')
    if digest is not None and sha256(value) != digest:
        raise ValueError('CORRECTION_FILE_HASH_MISMATCH')
    return value


def _journal(settings: Settings):
    path = settings.data / 'krp' / 'state.sqlite3'
    if not path.is_file():
        raise ValueError('CORRECTION_KRP_JOURNAL_MISSING')
    return path


def _effect(settings: Settings, operation_id: str) -> dict:
    path = _journal(settings)
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.5) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT * FROM effects WHERE operation_id=?', (operation_id,)).fetchone()
    except sqlite3.Error as error:
        raise ValueError('CORRECTION_KRP_JOURNAL_UNREADABLE') from error
    if row is None:
        raise ValueError('CORRECTION_KRP_EFFECT_MISSING')
    return dict(row)


def _payload(record: dict) -> dict:
    try:
        value = json.loads(record.get('payload_json') or '{}')
    except (ValueError, TypeError):
        raise ValueError('CORRECTION_KRP_PAYLOAD_INVALID') from None
    if not isinstance(value, dict):
        raise ValueError('CORRECTION_KRP_PAYLOAD_INVALID')
    return value


def _evidence(record: dict) -> dict:
    try:
        value = json.loads(record.get('evidence_json') or '{}')
    except (ValueError, TypeError):
        raise ValueError('CORRECTION_KRP_EVIDENCE_INVALID') from None
    return value if isinstance(value, dict) else {}


def _bound_effect(record: dict, effect: dict, *, platform: str, action: str,
                  profile: str, old_video_sha: str, publication_sha: str) -> None:
    if (record.get('operation_id') != effect.get('operation_id')
            or record.get('idempotency_key') != effect.get('idempotency_key')
            or record.get('platform') != platform or record.get('action') != action
            or record.get('actor') != ACTOR or record.get('profile') != profile):
        raise ValueError('CORRECTION_KRP_EFFECT_IDENTITY_MISMATCH')
    if action == 'publish_reel' and record.get('asset_sha256') != old_video_sha:
        raise ValueError('CORRECTION_KRP_MEDIA_MISMATCH')
    payload = _payload(record)
    if (payload.get('extra') or {}).get('package_sha256') != publication_sha:
        raise ValueError('CORRECTION_KRP_PACKAGE_MISMATCH')


def _pre_submit_proof(settings: Settings, effect: dict, platform: str,
                      old_video_sha: str, publication_sha: str) -> dict:
    record = _effect(settings, str(effect.get('operation_id') or ''))
    _bound_effect(record, effect, platform=platform, action='publish_reel',
                  profile=settings.social_profile, old_video_sha=old_video_sha,
                  publication_sha=publication_sha)
    if (record.get('state') != 'needs_input' or record.get('permalink')
            or record.get('external_id') or int(record.get('attempts') or 0) < 1):
        raise ValueError('CORRECTION_OLD_EFFECT_NOT_PROVEN_PRE_SUBMIT')
    receipts = (_evidence(record).get('receipts') or {})
    raw = receipts.get('needs_input') if isinstance(receipts, dict) else None
    if not isinstance(raw, str):
        raise ValueError('CORRECTION_PRE_SUBMIT_RECEIPT_MISSING')
    expected_dir = settings.data/'krp'/'artifacts'/record['operation_id']
    receipt_path = _contained_file(raw, expected_dir)
    receipt = _json(receipt_path)
    if (receipt.get('operation_id') != record['operation_id']
            or receipt.get('platform') != platform
            or receipt.get('action') != 'publish_reel'
            or receipt.get('actor') != ACTOR
            or receipt.get('profile') != settings.social_profile
            or receipt.get('payload_sha256') != record.get('payload_sha256')
            or receipt.get('asset_sha256') != old_video_sha
            or receipt.get('stage') != 'needs_input'
            or receipt.get('state') != 'needs_input'
            or receipt.get('submit_may_have_happened') is not False
            or receipt.get('permalink') or receipt.get('external_id')):
        raise ValueError('CORRECTION_PRE_SUBMIT_RECEIPT_INVALID')
    return {'operation_id': record['operation_id'], 'state': 'not_submitted',
            'attempts': int(record.get('attempts') or 0),
            'proof_sha256': sha256(receipt_path)}


def _youtube_retained(settings: Settings, publication: dict, old_video_sha: str,
                      publication_sha: str) -> dict:
    item = (publication.get('platforms') or {}).get('youtube')
    item = item if isinstance(item, dict) else {}
    effect = item.get('publication')
    if not isinstance(effect, dict):
        raise ValueError('CORRECTION_YOUTUBE_PUBLICATION_MISSING')
    record = _effect(settings, str(effect.get('operation_id') or ''))
    _bound_effect(record, effect, platform='youtube', action='publish_reel',
                  profile=settings.social_profile, old_video_sha=old_video_sha,
                  publication_sha=publication_sha)
    if record.get('state') != 'confirmed' or not record.get('permalink'):
        raise ValueError('CORRECTION_YOUTUBE_NOT_CONFIRMED')
    if effect.get('permalink') != record.get('permalink'):
        raise ValueError('CORRECTION_YOUTUBE_PERMALINK_MISMATCH')
    retained = {'state': 'retained', 'operation_id': record['operation_id'],
                'permalink': record['permalink']}
    comment = item.get('comment')
    if isinstance(comment, dict) and comment.get('operation_id'):
        comment_record = _effect(settings, str(comment['operation_id']))
        _bound_effect(comment_record, comment, platform='youtube', action='create_comment',
                      profile=settings.social_profile, old_video_sha=old_video_sha,
                      publication_sha=publication_sha)
        retained['comment'] = {'operation_id': comment_record['operation_id'],
                               'state': comment_record.get('state')}
    return retained


def _current_package(settings: Settings, campaign: Campaign, job_id: str):
    job = campaign.get(job_id)
    if job['state'] != 'publishing':
        raise ValueError('CORRECTION_REQUIRES_PUBLISHING_JOB')
    folder = Path(job['package_dir']).resolve(strict=True)
    if folder.parent != settings.output.resolve():
        raise ValueError('CORRECTION_PACKAGE_OUTSIDE_OUTPUT')
    package_path = folder/'package.json'
    publication_path = folder/'publication.json'
    if not package_path.is_file() or not publication_path.is_file():
        raise ValueError('CORRECTION_PUBLICATION_EVIDENCE_MISSING')
    package = _json(package_path)
    publication = _json(publication_path)
    current_sha = sha256(package_path)
    if (package.get('job_id') != job_id or package.get('source_sha256') != job['source_sha256']
            or publication.get('source_sha256') != job['source_sha256']):
        raise ValueError('CORRECTION_PACKAGE_IDENTITY_MISMATCH')
    return job, folder, package_path, current_sha, package, publication_path, publication


def _repair(settings: Settings, job_id: str, package: dict, package_sha: str):
    path = settings.data/'audio-repairs'/job_id/'repair.json'
    if not path.is_file():
        raise ValueError('CORRECTION_AUDIO_REPAIR_MISSING')
    receipt = _json(path)
    if (receipt.get('state') != 'candidate_ready_revision_required'
            or receipt.get('job_id') != job_id
            or receipt.get('package_sha256_before') != package_sha
            or receipt.get('video_sha256_before') != package.get('video_sha256')):
        raise ValueError('CORRECTION_AUDIO_REPAIR_NOT_BOUND')
    candidate_root = settings.data/'audio-repairs'/job_id
    candidate = _contained_file(receipt.get('candidate_path'), candidate_root,
                                str(receipt.get('candidate_sha256') or ''))
    if receipt.get('audio_guard', {}).get('preserved') is not True:
        raise ValueError('CORRECTION_AUDIO_GUARD_NOT_PRESERVED')
    finishing = receipt.get('finishing')
    if (not isinstance(finishing, dict)
            or finishing.get('video_sha256') != receipt.get('candidate_sha256')
            or finishing.get('audio_guard', {}).get('preserved') is not True
            or finishing.get('base_sha256') != receipt.get('native_sha256')):
        raise ValueError('CORRECTION_FINISHING_RECEIPT_INVALID')
    generated = (package.get('generation') or {}).get('download_sha256')
    if isinstance(generated, str) and generated and generated != receipt.get('native_sha256'):
        raise ValueError('CORRECTION_NATIVE_FLOW_HASH_MISMATCH')
    return path, receipt, candidate


def _copy(source: Path, destination: Path, expected: str) -> None:
    if sha256(source) != expected:
        raise ValueError('CORRECTION_SOURCE_CHANGED')
    shutil.copy2(source, destination)
    if sha256(source) != expected or sha256(destination) != expected:
        raise ValueError('CORRECTION_COPY_CHANGED')


def prepare_media_correction(settings: Settings, job_id: str) -> dict:
    """Prepare the clean candidate as a new Facebook/TikTok publication revision."""
    settings = Settings.load(settings.directory) if settings.path.exists() else settings
    with campaign_operation(settings):
        campaign = Campaign(settings)
        (job, old_dir, package_path, old_package_sha, old, publication_path,
         publication) = _current_package(settings, campaign, job_id)
        repair_path, repair, candidate = _repair(settings, job_id, old, old_package_sha)
        publication_sha = publication.get('package_sha256')
        if not re.fullmatch(r'[0-9a-f]{64}', str(publication_sha or '')):
            raise ValueError('CORRECTION_PRIOR_PUBLICATION_HASH_INVALID')

        pre_submit = {}
        for platform in TARGETS:
            item = (publication.get('platforms') or {}).get(platform)
            effect = item.get('publication') if isinstance(item, dict) else None
            if not isinstance(effect, dict):
                raise ValueError('CORRECTION_OLD_EFFECT_MISSING')
            pre_submit[platform] = _pre_submit_proof(
                settings, effect, platform, old['video_sha256'], publication_sha)
        youtube = _youtube_retained(settings, publication, old['video_sha256'], publication_sha)

        source = _contained_file(old['source_path'], old_dir, old['source_sha256'])
        frames = old.get('frames')
        if not isinstance(frames, list) or not 1 <= len(frames) <= 4:
            raise ValueError('CORRECTION_FRAME_SET_INVALID')
        frame_dir = old_dir/'frames'
        children = [_contained_file(row.get('path'), frame_dir, str(row.get('sha256') or ''))
                    for row in frames if isinstance(row, dict)]
        if len(children) != len(frames) or len({os.path.normcase(str(p)) for p in children}) != len(children):
            raise ValueError('CORRECTION_FRAME_SET_INVALID')

        candidate_sha = repair['candidate_sha256']
        target = old_dir.with_name(old_dir.name + '-correction-' + candidate_sha[:12])
        if target.resolve().parent != settings.output.resolve() or target.is_symlink():
            raise ValueError('CORRECTION_TARGET_OUTSIDE_OUTPUT')

        qa = json.loads(json.dumps(old.get('qa') or {}, ensure_ascii=False))
        qa.update(release_ready=True, decoded_audio_all_zero=False,
                  audio_treatment='preserve_native_audio_plus_laugh_overlay',
                  native_audio_preserved=True,
                  correction_kind='restore_native_audio_before_first_facebook_tiktok_submit')
        retained = {'youtube': youtube}
        correction = {
            'kind': 'clean_native_audio',
            'audio_repair_receipt_sha256': sha256(repair_path),
            'prior_package_sha256': old_package_sha,
            'prior_publication_package_sha256': publication_sha,
            'pre_submit': pre_submit,
            'retained_publications': retained,
        }

        owned = {'schema_version','job_id','source_sha256','source_path','video_path','video_sha256',
                 'frames','media','created_at','publication_targets','publication_revision',
                 'supersedes_package_sha256','finishing','qa','review','correction',
                 'prior_publication_package_sha256','audio_repair_receipt_sha256',
                 'retained_publications'}
        metadata = {k:v for k,v in old.items() if k not in owned}
        metadata.update(
            qa=qa,
            owner_correction='Owner authorized clean-native audio correction for Facebook and TikTok; retain existing YouTube publication.',
            publication_targets=['facebook','tiktok'],
            publication_revision=candidate_sha,
            supersedes_package_sha256=old_package_sha,
            prior_publication_package_sha256=publication_sha,
            audio_repair_receipt_sha256=sha256(repair_path),
            retained_publications=retained,
            correction=correction,
            finishing=repair['finishing'],
        )

        expected = metadata | {
            'schema_version':1,'job_id':job_id,'source_sha256':old['source_sha256'],
            'source_path':str(target/source.name),
            'video_path':str(target/Path(old['video_path']).name),
            'video_sha256':candidate_sha,
            'frames':[{'path':str(target/'frames'/f'{index:02d}{child.suffix.lower()}'),
                       'sha256':old['frames'][index-1]['sha256']}
                      for index,child in enumerate(children,1)],
            'story_contract': old.get('story_contract') or {
                'source_count':1,'output_clips':1,'source_sha256':old['source_sha256'],
                'join_other_stories':False},
        }

        if target.exists():
            manifest_path = target/'package.json'
            actual = _json(manifest_path)
            if (actual.get('video_sha256') != candidate_sha
                    or actual.get('publication_revision') != candidate_sha
                    or actual.get('supersedes_package_sha256') != old_package_sha
                    or actual.get('prior_publication_package_sha256') != publication_sha):
                raise ValueError('CORRECTION_EXISTING_TARGET_MISMATCH')
            package = actual
        else:
            with tempfile.TemporaryDirectory(prefix='.thoremix-correction-', dir=settings.output) as temporary:
                stage = Path(temporary)/'package'
                stage.mkdir()
                staged_video = stage/Path(old['video_path']).name
                _copy(candidate, staged_video, candidate_sha)
                media = validate_media(staged_video, tool_root=settings.directory)
                if sha256(staged_video) != candidate_sha:
                    raise ValueError('CORRECTION_VIDEO_CHANGED_DURING_DECODE')
                _copy(source, stage/source.name, old['source_sha256'])
                (stage/'frames').mkdir()
                for child,row in zip(children,expected['frames']):
                    _copy(child,stage/'frames'/Path(row['path']).name,row['sha256'])
                package = expected | {'media':media,'created_at':now_iso()}
                atomic_json(stage/'package.json',package)
                atomic_json(stage/'source.json',{'job_id':job_id,'source_sha256':old['source_sha256'],
                                                 'original_name':source.name,'slot':job['slot']})
                atomic_json(stage/'correction.json',correction)
                if (sha256(package_path) != old_package_sha
                        or sha256(publication_path) != sha256(old_dir/'publication.json')
                        or sha256(repair_path) != correction['audio_repair_receipt_sha256']):
                    raise ValueError('CORRECTION_EVIDENCE_CHANGED')
                os.rename(stage,target)

        # Re-validate all decisive evidence immediately before moving the job pointer.
        current = campaign.get(job_id)
        if (current['state'] != 'publishing'
                or Path(current['package_dir']).resolve() != old_dir
                or sha256(package_path) != old_package_sha
                or sha256(repair_path) != correction['audio_repair_receipt_sha256']):
            raise ValueError('CORRECTION_JOB_OR_EVIDENCE_CHANGED')
        for platform in TARGETS:
            item = (publication.get('platforms') or {}).get(platform) or {}
            _pre_submit_proof(settings,item.get('publication') or {},platform,
                              old['video_sha256'],publication_sha)
        _youtube_retained(settings,publication,old['video_sha256'],publication_sha)

        detail = json.loads(current.get('detail') or '{}')
        detail.update(prior_package=str(old_dir),correction_revision=candidate_sha,
                      package=str(target/'package.json'),
                      retained_youtube_operation=youtube['operation_id'])
        with campaign.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute(
                'UPDATE jobs SET package_dir=?,state=?,detail=?,updated_at=? '
                'WHERE id=? AND state=? AND package_dir=? AND source_sha256=?',
                (str(target),'video_ready',json.dumps(detail,ensure_ascii=False),now_iso(),
                 job_id,'publishing',str(old_dir),old['source_sha256']))
            if changed.rowcount != 1:
                raise ValueError('CORRECTION_JOB_CHANGED_BEFORE_PROMOTION')

        receipt_dir = settings.data/'media-corrections'/job_id
        receipt_dir.mkdir(parents=True,exist_ok=True)
        result = {
            'state':'correction_ready','job_id':job_id,'package':str(target/'package.json'),
            'package_sha256':sha256(target/'package.json'),'video_sha256':candidate_sha,
            'publication_targets':['facebook','tiktok'],
            'idempotency_namespace':f"thoremix:{old['source_sha256']}:revision:{candidate_sha}",
            'retained_publications':retained,'prior_package':str(old_dir),
            'prior_package_sha256':old_package_sha,
            'prior_publication_package_sha256':publication_sha,
            'audio_repair_receipt_sha256':correction['audio_repair_receipt_sha256'],
        }
        atomic_json(receipt_dir/'revision.json',result)
        return result
