"""Visible, hash-bound working assets in the eventual story folder."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from .config import atomic_json
from .core import sha256


def validate_draft(folder, job, *, video=None):
    folder = Path(folder).resolve()
    draft = json.loads((folder/'draft.json').read_text(encoding='utf-8'))
    if draft.get('job_id') != job['id'] or draft.get('source_sha256') != job['source_sha256']:
        raise ValueError('WORKING_STORY_IDENTITY_MISMATCH')
    allowed = {'draft.json'}
    for item in [draft['source'], *draft['frames']]:
        relative = Path(item['path'])
        path = (folder/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(folder) or sha256(path) != item['sha256']:
            raise ValueError('WORKING_STORY_ASSET_CHANGED')
        allowed.add(relative.as_posix())
    if draft['source']['sha256'] != job['source_sha256']:
        raise ValueError('WORKING_STORY_SOURCE_CHANGED')
    # source.json may be the first file promoted before an interrupted MP4 move.
    allowed.add('source.json')
    receipt = folder/'source.json'
    if receipt.exists():
        value = json.loads(receipt.read_text(encoding='utf-8'))
        if value.get('job_id') != job['id'] or value.get('source_sha256') != job['source_sha256']:
            raise ValueError('WORKING_STORY_IDENTITY_MISMATCH')
    if video is not None:
        allowed.add(Path(job['source']).stem+'.mp4')
        target = folder/(Path(job['source']).stem+'.mp4')
        if target.exists() and sha256(target) != sha256(Path(video)):
            raise ValueError('WORKING_STORY_VIDEO_CHANGED')
    if any(p.is_symlink() or p.relative_to(folder).as_posix() not in allowed
           for p in folder.rglob('*') if p.is_file() or p.is_symlink()):
        raise ValueError('WORKING_STORY_UNEXPECTED_FILE')
    return draft


def save_working_assets(settings, job, files):
    """Caller holds the campaign lease. Keep originals until successful finalization."""
    folder = Path(job['package_dir'])
    if folder.resolve().parent != settings.output.resolve():
        raise ValueError('WORKING_STORY_PATH_INVALID')
    if (folder/'package.json').exists():
        return
    source = Path(job['source'])
    if source.resolve().parent != Path(settings.input_dir).resolve() or sha256(source) != job['source_sha256']:
        raise ValueError('WORKING_STORY_SOURCE_CHANGED')
    frames = []
    for i, item in enumerate(files, 1):
        child = Path(item['path'])
        if sha256(child) != item['sha256']:
            raise ValueError('WORKING_STORY_ASSET_CHANGED')
        frames.append({'path': f'frames/{i:02d}{child.suffix.lower()}', 'sha256': item['sha256']})
    draft = {'schema_version': 1, 'job_id': job['id'], 'source_sha256': job['source_sha256'],
             'source': {'path': source.name, 'sha256': job['source_sha256']}, 'frames': frames,
             'state': 'working_assets_only', 'release_ready': False}
    if folder.exists():
        partial_video = folder/(source.stem+'.mp4')
        existing = validate_draft(folder, job, video=partial_video if partial_video.is_file() else None)
        if existing != draft:
            raise ValueError('WORKING_STORY_ASSET_SET_CHANGED')
        return
    settings.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.story-assets-', dir=settings.output) as temporary:
        staged = Path(temporary)/'story'
        (staged/'frames').mkdir(parents=True)
        shutil.copy2(source, staged/source.name)
        for item, target in zip(files, frames):
            shutil.copy2(item['path'], staged/target['path'])
        atomic_json(staged/'draft.json', draft)
        validate_draft(staged, job)
        if folder.exists():
            raise FileExistsError('WORKING_STORY_FOLDER_COLLISION')
        os.rename(staged, folder)
