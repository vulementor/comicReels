"""Owner-directed Facebook/TikTok correction preserving the prior media package.

The cleanup receipt records actual operator outcomes; this module never creates
that receipt or performs social effects. Only a blocked job may start/resume a
revision. Promotion is complete before the original job's package pointer moves.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .config import atomic_json
from .core import Campaign, campaign_operation, now_iso, sha256, validate_media


_OWNED_FIELDS = {'schema_version', 'job_id', 'source_sha256', 'source_path', 'video_path',
                 'video_sha256', 'frames', 'media', 'created_at', 'publication_revision',
                 'supersedes_package_sha256', 'cleanup_receipt_sha256'}


def _file(path, parent: Path, digest: str | None = None) -> Path:
    value = Path(path)
    if (not value.is_absolute() or value.is_symlink() or not value.is_file()
            or value.resolve().parent != parent.resolve()):
        raise ValueError('Revision file is outside its verified package.')
    if digest is not None and (not isinstance(digest, str)
            or not re.fullmatch('[0-9a-f]{64}', digest) or sha256(value) != digest):
        raise ValueError('Revision package file hash does not match.')
    return value


def _old_package(folder: Path, job: dict, output: Path):
    if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != output:
        raise ValueError('Prior package is outside campaign output.')
    manifest_path = _file(folder / 'package.json', folder)
    manifest_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != 1 or manifest.get('job_id') != job['id']
            or manifest.get('source_sha256') != job['source_sha256']):
        raise ValueError('Prior package does not belong to the blocked job.')
    source = _file(manifest['source_path'], folder, job['source_sha256'])
    video = _file(manifest['video_path'], folder, manifest['video_sha256'])
    frames = manifest.get('frames')
    frame_dir = folder / 'frames'
    if (not isinstance(frames, list) or len(frames) != 3 or frame_dir.is_symlink()
            or not frame_dir.is_dir()):
        raise ValueError('Revision requires three verified ordered frames.')
    children = [_file(row['path'], frame_dir, row['sha256']) for row in frames]
    if len({os.path.normcase(str(p.resolve())) for p in children}) != 3:
        raise ValueError('Revision frame identities must be distinct.')
    if sha256(manifest_path) != manifest_hash:
        raise ValueError('Prior manifest changed while being verified.')
    return manifest, manifest_hash, source, video, children


def _cleanup(settings, old: dict) -> tuple[Path, str]:
    path = settings.data / 'review/wrong-media-cleanup/complete.json'
    if path.is_symlink() or not path.is_file():
        raise ValueError('Actual wrong-media cleanup receipt is required.')
    receipt = json.loads(path.read_text(encoding='utf-8'))
    if (receipt.get('source_sha256') != old['source_sha256']
            or receipt.get('video_sha256') != old['video_sha256']):
        raise ValueError('Cleanup receipt does not match the prior media.')
    permitted = {'facebook': {'withdrawn', 'deleted'},
                 'youtube': {'retained', 'private', 'deleted'}, 'tiktok': {'not_submitted'}}
    for platform, states in permitted.items():
        evidence = receipt.get(platform)
        if not isinstance(evidence, dict) or evidence.get('state') not in states:
            raise ValueError('Cleanup outcome is not verified for ' + platform + '.')
    return path, sha256(path)


def _copy(source: Path, destination: Path, expected: str) -> None:
    if sha256(source) != expected:
        raise ValueError('Revision input changed before copy.')
    shutil.copy2(source, destination)
    if sha256(source) != expected or sha256(destination) != expected:
        raise ValueError('Revision input changed during copy.')


def _check_target(folder: Path, expected: dict, settings) -> dict:
    """Reconcile a fully promoted directory only; never repair/overwrite collision."""
    if folder.is_symlink() or not folder.is_dir():
        raise FileExistsError('Revision destination is not a complete owned package.')
    path = folder / 'package.json'
    if not path.is_file() or path.is_symlink():
        raise FileExistsError('Revision destination already exists without a frozen manifest.')
    actual = json.loads(path.read_text(encoding='utf-8'))
    comparable = {k: v for k, v in actual.items() if k not in {'created_at', 'media'}}
    if comparable != expected or not isinstance(actual.get('created_at'), str):
        raise ValueError('Existing revision destination differs from the frozen request.')
    _file(actual['source_path'], folder, actual['source_sha256'])
    video = _file(actual['video_path'], folder, actual['video_sha256'])
    if (folder / 'frames').is_symlink():
        raise ValueError('Revision frames cannot use a linked directory.')
    for row in actual['frames']:
        _file(row['path'], folder / 'frames', row['sha256'])
    probe = validate_media(video, tool_root=settings.directory)
    if actual.get('media') != probe or sha256(video) != actual['video_sha256']:
        raise ValueError('Existing revision media validation does not match.')
    return actual


def revise_package(settings, job_id, video: Path, metadata: dict) -> dict:
    """Create a Facebook/TikTok native-animation revision under the same source/job.

    Metadata requires explicit release approval, native_ai_animation visual mode,
    owner_correction mentioning both destinations and publication_targets containing
    exactly ['facebook', 'tiktok']. Existing YouTube publication is retained. Caller
    may override editorial fields but cannot supply generated identity/path fields.
    """
    if not isinstance(metadata, dict) or not isinstance(metadata.get('qa'), dict):
        raise ValueError('Explicit reviewed animation metadata is required.')
    if (metadata['qa'].get('release_ready') is not True
            or metadata['qa'].get('visual_mode') != 'native_ai_animation'
            or metadata.get('publication_targets') != ['facebook', 'tiktok']
            or not isinstance(metadata.get('owner_correction'), str)
            or 'tiktok' not in metadata['owner_correction'].casefold()
            or 'facebook' not in metadata['owner_correction'].casefold()
            or _OWNED_FIELDS.intersection(metadata)):
        raise ValueError('Revision requires owner-reviewed native animation for Facebook and TikTok only.')
    # Freeze nested caller metadata and reject non-JSON values before filesystem work.
    metadata = json.loads(json.dumps(metadata, ensure_ascii=False, allow_nan=False))
    with campaign_operation(settings):
        campaign = Campaign(settings)
        job = campaign.get(job_id)
        if job['state'] != 'wrong_media_blocked':
            raise ValueError('Only a wrong_media_blocked job may be revised.')
        output = settings.output.resolve()
        old_dir = Path(job['package_dir'])
        old, old_hash, source, old_video, children = _old_package(old_dir, job, output)
        cleanup_path, cleanup_hash = _cleanup(settings, old)
        video = Path(video).resolve(strict=True)
        if not video.is_file():
            raise ValueError('Revision video does not exist.')
        video_hash = sha256(video)
        if video_hash == old['video_sha256']:
            raise ValueError('Revision must contain different animated media.')
        target = old_dir.with_name(old_dir.name + '-ai-' + video_hash[:12])
        if target.resolve().parent != output or target.is_symlink():
            raise ValueError('Revision destination is outside campaign output.')
        expected = {k: v for k, v in old.items() if k not in _OWNED_FIELDS} | metadata | {
            'schema_version': 1, 'job_id': job_id, 'source_sha256': job['source_sha256'],
            'source_path': str(target / source.name), 'video_path': str(target / old_video.name),
            'video_sha256': video_hash, 'publication_revision': video_hash,
            'supersedes_package_sha256': old_hash, 'cleanup_receipt_sha256': cleanup_hash,
            'frames': [{'path': str(target / 'frames' / f'{index:02d}{child.suffix.lower()}'),
                        'sha256': old['frames'][index - 1]['sha256']}
                       for index, child in enumerate(children, 1)],
        }
        if target.exists():
            package = _check_target(target, expected, settings)
        else:
            with tempfile.TemporaryDirectory(prefix='.thoremix-revision-', dir=output) as temporary:
                staging = Path(temporary)
                staged = staging / 'package'
                staged.mkdir()
                staged_video = staged / old_video.name
                _copy(video, staged_video, video_hash)
                probe = validate_media(staged_video, tool_root=settings.directory)
                if sha256(staged_video) != video_hash:
                    raise ValueError('Revision video changed during decode.')
                _copy(source, staged / source.name, job['source_sha256'])
                (staged / 'frames').mkdir()
                for child, row in zip(children, expected['frames']):
                    _copy(child, staged / 'frames' / Path(row['path']).name, row['sha256'])
                package = expected | {'media': probe, 'created_at': now_iso()}
                atomic_json(staged / 'package.json', package)
                atomic_json(staged / 'source.json', {'job_id': job_id, 'source_sha256': job['source_sha256'],
                                                    'original_name': source.name, 'slot': job['slot']})
                # Validate absolute containment before the one directory promotion.
                if (staged.resolve().parent != staging.resolve() or staging.resolve().parent != output
                        or target.resolve().parent != output or target.exists() or target.is_symlink()):
                    raise FileExistsError('Revision destination collision or invalid staging path.')
                if _old_package(old_dir, job, output)[1] != old_hash or sha256(cleanup_path) != cleanup_hash:
                    raise ValueError('Prior package or cleanup evidence changed.')
                os.rename(staged, target)
        if _old_package(old_dir, job, output)[1] != old_hash or sha256(cleanup_path) != cleanup_hash:
            raise ValueError('Prior package or cleanup evidence changed before job update.')
        detail = json.loads(job['detail']) | {'prior_package': str(old_dir), 'revision': video_hash,
                                            'package': str(target / 'package.json')}
        with campaign.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE jobs SET package_dir=?,state=?,detail=?,updated_at=? '
                'WHERE id=? AND state=? AND package_dir=? AND source_sha256=?',
                (str(target), 'video_ready', json.dumps(detail, ensure_ascii=False), now_iso(),
                 job_id, 'wrong_media_blocked', str(old_dir), job['source_sha256']))
            if changed.rowcount != 1:
                raise ValueError('Blocked revision job changed before transactional update.')
        return package
