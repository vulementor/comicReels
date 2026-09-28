"""Wrong-media revisions preserve the old package and consume no new source."""
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

from agent.thoremix import core
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import Campaign, sha256

REAL_VALIDATE_MEDIA = core.validate_media


def module():
    assert importlib.util.find_spec('agent.thoremix.revisions') is not None, 'revision capability missing'
    return importlib.import_module('agent.thoremix.revisions')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source_dir = tmp_path / 'input'
    source_dir.mkdir()
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(source_dir))
    settings.save()
    source = source_dir / 'comic.png'
    Image.new('RGB', (32, 64), 'blue').save(source)
    frames = []
    for index, color in enumerate(('red', 'green', 'blue')):
        frame = tmp_path / f'frame-{index}.png'
        Image.new('RGB', (32, 64), color).save(frame)
        frames.append(frame)
    old_video = tmp_path / 'old.mp4'
    old_video.write_bytes(b'old reviewed static media' * 100)
    monkeypatch.setattr(core, 'validate_media', lambda *a, **k: {'full_decode': True})
    campaign = Campaign(settings)
    job = campaign.reserve('original-slot', source=source)
    old = campaign.finalize(job['id'], old_video, children=frames,
                            metadata={'qa': {'release_ready': True}, 'title': 'Original',
                                      'caption': 'Original caption', 'affiliate': {'state': 'verified'}})
    campaign.update(job['id'], 'wrong_media_blocked', why='Owner requested native animation')
    old_dir = Path(campaign.get(job['id'])['package_dir'])
    old_bytes = {str(p.relative_to(old_dir)): p.read_bytes() for p in old_dir.rglob('*') if p.is_file()}
    cleanup = {'source_sha256': old['source_sha256'], 'video_sha256': old['video_sha256'],
               'facebook': {'state': 'deleted'}, 'youtube': {'state': 'retained'},
               'tiktok': {'state': 'not_submitted'}}
    cleanup_path = settings.data / 'review/wrong-media-cleanup/complete.json'
    atomic_json(cleanup_path, cleanup)
    new_video = tmp_path / 'animation.mp4'
    new_video.write_bytes(b'new native animated media' * 100)
    metadata = {'qa': {'release_ready': True, 'visual_mode': 'native_ai_animation'},
                'owner_correction': 'Owner requests native AI animation for Facebook and TikTok; retain YouTube.',
                'publication_targets': ['facebook', 'tiktok']}
    return settings, campaign, job, old, old_dir, old_bytes, cleanup_path, new_video, metadata


def invoke(setup, monkeypatch, *, decoder=None):
    mod = module()
    monkeypatch.setattr(mod, 'validate_media', decoder or (lambda *a, **k: {'full_decode': True}))
    settings, _, job, _, _, _, _, video, metadata = setup
    return mod.revise_package(settings, job['id'], video, metadata)


def assert_old_unchanged(setup):
    _, campaign, _, old, old_dir, old_bytes, *_ = setup
    assert {str(p.relative_to(old_dir)): p.read_bytes() for p in old_dir.rglob('*') if p.is_file()} == old_bytes
    assert len(campaign.jobs()) == 1
    assert campaign.jobs()[0]['source_sha256'] == old['source_sha256']


def test_revision_preserves_old_package_job_and_ordered_frames(setup, monkeypatch):
    settings, campaign, job, old, old_dir, old_bytes, _, video, _ = setup
    seen = []
    def decode(staged, **kwargs):
        assert staged != video and staged.read_bytes() == video.read_bytes()
        seen.append(staged)
        return {'full_decode': True, 'width': 32, 'height': 64}
    revised = invoke(setup, monkeypatch, decoder=decode)
    target = old_dir.with_name(old_dir.name + '-ai-' + sha256(video)[:12])
    assert seen and Path(revised['video_path']) == target / Path(old['video_path']).name
    assert revised['publication_revision'] == sha256(video)
    import hashlib
    assert revised['supersedes_package_sha256'] == hashlib.sha256(old_bytes['package.json']).hexdigest()
    assert revised['source_sha256'] == old['source_sha256'] and revised['job_id'] == job['id']
    assert [f['sha256'] for f in revised['frames']] == [f['sha256'] for f in old['frames']]
    assert [Path(f['path']).name for f in revised['frames']] == ['01.png', '02.png', '03.png']
    assert all(Path(f['path']).is_file() for f in revised['frames'])
    current = campaign.get(job['id'])
    assert current['package_dir'] == str(target) and current['state'] == 'video_ready'
    detail = json.loads(current['detail'])
    assert detail['prior_package'] == str(old_dir) and detail['revision'] == sha256(video)
    assert revised['caption'] == old['caption']
    assert_old_unchanged(setup)


@pytest.mark.parametrize('bad', ['missing_cleanup', 'source_hash', 'video_hash', 'facebook', 'youtube', 'tiktok',
                               'unapproved', 'static', 'no_correction', 'wrong_state', 'same_video', 'fanout',
                               'facebook_retained'])
def test_ineligible_revision_does_not_change_job_or_create_target(setup, monkeypatch, bad):
    settings, campaign, job, old, old_dir, _, receipt, video, metadata = setup
    if bad == 'missing_cleanup':
        receipt.unlink()
    elif bad in {'source_hash', 'video_hash', 'facebook', 'youtube', 'tiktok'}:
        value = json.loads(receipt.read_text())
        if bad.endswith('_hash'):
            value['source_sha256' if bad == 'source_hash' else 'video_sha256'] = '0' * 64
        else:
            value[bad]['state'] = 'unknown'
        atomic_json(receipt, value)
    elif bad == 'unapproved':
        metadata['qa']['release_ready'] = False
    elif bad == 'static':
        metadata['qa']['visual_mode'] = 'static_frames'
    elif bad == 'no_correction':
        metadata['owner_correction'] = ' '
    elif bad == 'wrong_state':
        campaign.update(job['id'], 'published')
    elif bad == 'fanout':
        metadata['publication_targets'] = ['facebook', 'tiktok', 'youtube']
    elif bad == 'facebook_retained':
        value = json.loads(receipt.read_text())
        value['facebook']['state'] = 'retained'
        atomic_json(receipt, value)
    else:
        video.write_bytes(Path(old['video_path']).read_bytes())
    before = campaign.get(job['id'])
    with pytest.raises((ValueError, FileNotFoundError)):
        invoke(setup, monkeypatch)
    assert campaign.get(job['id']) == before
    assert list(settings.output.glob('*-ai-*')) == []
    assert_old_unchanged(setup)


@pytest.mark.parametrize('which', ['video_path', 'source_path', 'frame'])
def test_tampered_old_bytes_block_revision(setup, monkeypatch, which):
    settings, campaign, job, old, *_ = setup
    path = Path(old['frames'][0]['path'] if which == 'frame' else old[which])
    path.write_bytes(b'tampered')
    before = campaign.get(job['id'])
    with pytest.raises(ValueError):
        invoke(setup, monkeypatch)
    assert campaign.get(job['id']) == before and not list(settings.output.glob('*-ai-*'))


def test_copy_failure_and_decode_failure_leave_old_and_allow_retry(setup, monkeypatch):
    mod = module()
    settings, campaign, job, old, *_ = setup
    def failed_decode(*a, **k):
        raise ValueError('decode failed')
    with pytest.raises(ValueError, match='decode'):
        invoke(setup, monkeypatch, decoder=failed_decode)
    original_copy = mod.shutil.copy2
    def fail_frame(source, destination):
        if Path(source) == Path(old['frames'][1]['path']):
            raise OSError('frame failed')
        return original_copy(source, destination)
    monkeypatch.setattr(mod.shutil, 'copy2', fail_frame)
    with pytest.raises(OSError, match='frame'):
        invoke(setup, monkeypatch)
    assert campaign.get(job['id'])['state'] == 'wrong_media_blocked'
    assert not list(settings.output.glob('*-ai-*'))
    assert_old_unchanged(setup)
    monkeypatch.setattr(mod.shutil, 'copy2', original_copy)
    assert invoke(setup, monkeypatch)['job_id'] == job['id']


def test_existing_unrelated_target_is_never_overwritten(setup, monkeypatch):
    _, campaign, job, _, old_dir, _, _, video, _ = setup
    target = old_dir.with_name(old_dir.name + '-ai-' + sha256(video)[:12])
    target.mkdir()
    (target / 'keep').write_bytes(b'private collision')
    with pytest.raises((ValueError, FileExistsError)):
        invoke(setup, monkeypatch)
    assert (target / 'keep').read_bytes() == b'private collision'
    assert campaign.get(job['id'])['package_dir'] == str(old_dir)
    assert_old_unchanged(setup)


def test_crash_after_complete_promotion_resumes_same_target(setup, monkeypatch):
    mod = module()
    settings, campaign, job, _, old_dir, _, _, video, _ = setup
    real_rename = mod.os.rename
    def crash_after_rename(source, destination):
        real_rename(source, destination)
        raise OSError('interrupted after promotion')
    monkeypatch.setattr(mod.os, 'rename', crash_after_rename)
    with pytest.raises(OSError, match='interrupted'):
        invoke(setup, monkeypatch)
    target = old_dir.with_name(old_dir.name + '-ai-' + sha256(video)[:12])
    frozen = (target / 'package.json').read_bytes()
    assert campaign.get(job['id'])['state'] == 'wrong_media_blocked'
    monkeypatch.setattr(mod.os, 'rename', real_rename)
    result = invoke(setup, monkeypatch)
    assert result['job_id'] == job['id'] and (target / 'package.json').read_bytes() == frozen
    assert len(list(settings.output.glob('*-ai-*'))) == 1
    assert_old_unchanged(setup)


def test_revision_validates_real_portrait_audio_video(setup, monkeypatch):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        pytest.skip('ffmpeg required for real-media validation')
    settings, campaign, job, _, _, _, _, video, metadata = setup
    subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=32x64:rate=12:duration=0.5', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(video)], check=True, capture_output=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    mod = module()
    monkeypatch.setattr(mod, 'validate_media', REAL_VALIDATE_MEDIA)
    result = mod.revise_package(settings, job['id'], video, metadata)
    assert result['media']['full_decode'] is True
    assert result['media']['height'] == 64 and result['media']['width'] == 32
    assert sha256(Path(result['video_path'])) == sha256(video)
    assert campaign.get(job['id'])['state'] == 'video_ready'
    assert_old_unchanged(setup)
