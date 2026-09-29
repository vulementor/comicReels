"""Proof-bound cleanup of a stale TikTok Studio local editor.

The cleanup is a separate external action from publication.  It is allowed only
when the blocking editor can be tied to a fully published ThoRemix job and the
current correction's TikTok effect is durably proven pre-submit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from kabin_reel_poster.core.models import PublishRequest

from .config import Settings, atomic_json
from .core import Campaign, root_operation, sha256
from .publishing import ACTOR, _config, _home, _manifest


def _json(path: Path) -> dict:
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict):
        raise ValueError('SOCIAL_CLEANUP_JSON_INVALID')
    return value


def _effect(settings: Settings, operation_id: str) -> dict:
    path=settings.data/'krp'/'state.sqlite3'
    if not path.is_file():
        raise ValueError('SOCIAL_CLEANUP_KRP_JOURNAL_MISSING')
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.5) as db:
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT * FROM effects WHERE operation_id=?',(operation_id,)).fetchone()
    except sqlite3.Error as error:
        raise ValueError('SOCIAL_CLEANUP_KRP_JOURNAL_UNREADABLE') from error
    if row is None:
        raise ValueError('SOCIAL_CLEANUP_KRP_EFFECT_MISSING')
    return dict(row)


def _payload(record: dict) -> dict:
    try:
        value=json.loads(record.get('payload_json') or '{}')
    except (TypeError,ValueError):
        raise ValueError('SOCIAL_CLEANUP_KRP_PAYLOAD_INVALID') from None
    if not isinstance(value,dict):
        raise ValueError('SOCIAL_CLEANUP_KRP_PAYLOAD_INVALID')
    return value


def _evidence(record: dict) -> dict:
    try:
        value=json.loads(record.get('evidence_json') or '{}')
    except (TypeError,ValueError):
        raise ValueError('SOCIAL_CLEANUP_KRP_EVIDENCE_INVALID') from None
    return value if isinstance(value,dict) else {}


def _package(campaign: Campaign, job_id: str):
    job=campaign.get(job_id)
    folder=Path(job['package_dir']).resolve(strict=True)
    package_path=folder/'package.json'
    publication_path=folder/'publication.json'
    if not package_path.is_file() or not publication_path.is_file():
        raise ValueError('SOCIAL_CLEANUP_PACKAGE_OR_PUBLICATION_MISSING')
    package=_json(package_path)
    publication=_json(publication_path)
    _,digest=_manifest(folder)
    if publication.get('package_sha256')!=digest:
        raise ValueError('SOCIAL_CLEANUP_PUBLICATION_PACKAGE_MISMATCH')
    return job,folder,package,publication,digest


def _bound_record(record: dict, effect: dict, *, platform: str, action: str,
                  profile: str, video_sha: str | None, package_digest: str) -> None:
    if (record.get('operation_id')!=effect.get('operation_id')
            or record.get('idempotency_key')!=effect.get('idempotency_key')
            or record.get('platform')!=platform or record.get('action')!=action
            or record.get('actor')!=ACTOR or record.get('profile')!=profile):
        raise ValueError('SOCIAL_CLEANUP_EFFECT_IDENTITY_MISMATCH')
    if video_sha is not None and record.get('asset_sha256')!=video_sha:
        raise ValueError('SOCIAL_CLEANUP_EFFECT_MEDIA_MISMATCH')
    if (_payload(record).get('extra') or {}).get('package_sha256')!=package_digest:
        raise ValueError('SOCIAL_CLEANUP_EFFECT_PACKAGE_MISMATCH')


def _pre_submit_receipt(settings: Settings, record: dict) -> Path:
    receipts=_evidence(record).get('receipts') or {}
    raw=receipts.get('needs_input') if isinstance(receipts,dict) else None
    if not isinstance(raw,str):
        raise ValueError('SOCIAL_CLEANUP_PRE_SUBMIT_RECEIPT_MISSING')
    path=Path(raw).resolve(strict=True)
    root=(settings.data/'krp'/'artifacts'/record['operation_id']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('SOCIAL_CLEANUP_PRE_SUBMIT_RECEIPT_OUTSIDE_ARTIFACT')
    receipt=_json(path)
    if (receipt.get('operation_id')!=record['operation_id']
            or receipt.get('stage')!='needs_input'
            or receipt.get('state')!='needs_input'
            or receipt.get('submit_may_have_happened') is not False
            or receipt.get('permalink') or receipt.get('external_id')
            or receipt.get('asset_sha256')!=record.get('asset_sha256')
            or receipt.get('payload_sha256')!=record.get('payload_sha256')):
        raise ValueError('SOCIAL_CLEANUP_PRE_SUBMIT_RECEIPT_INVALID')
    return path


def _browser_cleanup(settings: Settings, stale_request: PublishRequest,
                     cleanup_id: str):
    from kabin_reel_poster.platforms.tiktok import TikTokAdapter
    with _home(settings.data/'krp',settings.social_profile) as home:
        adapter=TikTokAdapter(_config(home,settings.social_profile,False))
        with adapter.context(settings.social_profile) as context:
            page=context.new_page()
            page.goto('https://www.tiktok.com/tiktokstudio/upload?from=webapp',
                      wait_until='domcontentloaded',timeout=60000)
            gate=adapter.final_actor_gate(
                page,actor=ACTOR,operation_id=cleanup_id,stage='TikTok Studio')
            if gate is not None:
                return gate
            return adapter.discard_verified_unsaved_editor(
                page,stale_request,cleanup_id)


def cleanup_tiktok_stale_editor(settings: Settings, current_job_id: str,
                                stale_job_id: str, *, runner=None) -> dict:
    settings=Settings.load(settings.directory) if settings.path.exists() else settings
    with root_operation(settings.data):
        campaign=Campaign(settings)
        current_job,current_dir,current_pkg,current_pub,current_digest=_package(
            campaign,current_job_id)
        stale_job,stale_dir,stale_pkg,stale_pub,stale_digest=_package(
            campaign,stale_job_id)

        if current_job['state'] not in {'video_ready','publishing'}:
            raise ValueError('SOCIAL_CLEANUP_CURRENT_JOB_NOT_READY')
        from .media_correction import correction_approval_valid
        if (not isinstance(current_pkg.get('correction'),dict)
                or not correction_approval_valid(settings,current_job_id,current_pkg)):
            raise ValueError('SOCIAL_CLEANUP_CURRENT_CORRECTION_NOT_APPROVED')
        if stale_job['state']!='published' or stale_pub.get('complete') is not True:
            raise ValueError('SOCIAL_CLEANUP_STALE_JOB_NOT_FULLY_PUBLISHED')
        if 'tiktok' not in (current_pkg.get('publication_targets') or []):
            raise ValueError('SOCIAL_CLEANUP_CURRENT_TIKTOK_NOT_REQUESTED')

        current_item=(current_pub.get('platforms') or {}).get('tiktok') or {}
        current_effect=current_item.get('publication') or {}
        current_record=_effect(settings,str(current_effect.get('operation_id') or ''))
        _bound_record(current_record,current_effect,platform='tiktok',
                      action='publish_reel',profile=settings.social_profile,
                      video_sha=current_pkg.get('video_sha256'),
                      package_digest=current_digest)
        if (current_record.get('state')!='needs_input'
                or current_record.get('permalink') or current_record.get('external_id')):
            raise ValueError('SOCIAL_CLEANUP_CURRENT_EFFECT_NOT_PROVEN_PRE_SUBMIT')
        current_proof=_pre_submit_receipt(settings,current_record)

        stale_item=(stale_pub.get('platforms') or {}).get('tiktok') or {}
        stale_effect=stale_item.get('publication') or {}
        stale_record=_effect(settings,str(stale_effect.get('operation_id') or ''))
        _bound_record(stale_record,stale_effect,platform='tiktok',
                      action='publish_reel',profile=settings.social_profile,
                      video_sha=stale_pkg.get('video_sha256'),
                      package_digest=stale_digest)
        if (stale_record.get('state')!='confirmed'
                or not stale_record.get('permalink')
                or stale_effect.get('permalink')!=stale_record.get('permalink')):
            raise ValueError('SOCIAL_CLEANUP_STALE_TIKTOK_NOT_CONFIRMED')

        stale_request=PublishRequest.model_validate(_payload(stale_record))
        stale_video=Path(stale_request.video).resolve(strict=True)
        if sha256(stale_video)!=stale_record.get('asset_sha256'):
            raise ValueError('SOCIAL_CLEANUP_STALE_VIDEO_CHANGED')

        cleanup_id=hashlib.sha256(
            (current_record['operation_id']+':'+stale_record['operation_id']).encode()
        ).hexdigest()[:32]
        directory=settings.data/'social-cleanups'/current_job_id
        directory.mkdir(parents=True,exist_ok=True)
        receipt_path=directory/'tiktok-stale-editor.json'
        intent={
            'state':'prepared','cleanup_id':cleanup_id,
            'current_job_id':current_job_id,'stale_job_id':stale_job_id,
            'current_operation_id':current_record['operation_id'],
            'current_video_sha256':current_pkg['video_sha256'],
            'current_pre_submit_receipt_sha256':sha256(current_proof),
            'stale_operation_id':stale_record['operation_id'],
            'stale_video_sha256':stale_record['asset_sha256'],
            'stale_publication_permalink':stale_record['permalink'],
            'stale_package_sha256':stale_digest,
        }
        if receipt_path.exists():
            previous=_json(receipt_path)
            if previous.get('state')=='confirmed' and all(
                    previous.get(k)==v for k,v in intent.items() if k!='state'):
                return previous
            if any(previous.get(k)!=v for k,v in intent.items() if k!='state'):
                raise ValueError('SOCIAL_CLEANUP_EXISTING_RECEIPT_MISMATCH')
        atomic_json(receipt_path,intent)

        result=(runner or _browser_cleanup)(settings,stale_request,cleanup_id)
        if getattr(result,'state',None)!='confirmed':
            failed=intent|{
                'state':'needs_input',
                'reason':str(getattr(result,'reason',None) or 'TikTok stale editor cleanup needs input'),
                'evidence':getattr(result,'evidence',{}) or {},
                'observed_at':datetime.now(timezone.utc).isoformat(),
            }
            atomic_json(receipt_path,failed)
            return failed

        complete=intent|{
            'state':'confirmed',
            'evidence':getattr(result,'evidence',{}) or {},
            'observed_at':datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(receipt_path,complete)
        return complete
