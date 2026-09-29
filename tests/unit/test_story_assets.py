import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from agent.thoremix.config import Settings
from agent.thoremix.core import Campaign, sha256
from agent.thoremix.story_assets import save_working_assets
from agent.thoremix.dashboard import build_snapshot


def setup(tmp_path):
    source = tmp_path/'input'
    source.mkdir()
    original = source/'story.png'
    Image.new('RGB', (80, 200), 'blue').save(original)
    child = tmp_path/'child.png'
    Image.new('RGB', (90, 160), 'red').save(child)
    settings = Settings(root=str(tmp_path/'app'), input_dir=str(source))
    settings.save()
    campaign = Campaign(settings)
    job = campaign.reserve('test', source=original)
    files = [{'path':str(child), 'sha256':sha256(child)}]
    return settings,campaign,job,original,child,files


def test_working_frames_are_visible_in_final_folder_without_publishing_or_moving_source(tmp_path):
    settings,campaign,job,source,child,files=setup(tmp_path)
    save_working_assets(settings,job,files)
    save_working_assets(settings,job,files)
    folder=Path(job['package_dir'])
    assert source.exists() and not (folder/'package.json').exists()
    row=build_snapshot(settings)['rows'][0]
    assert row['preview']==folder/'frames/01.png'
    assert row['frames']==[folder/'frames/01.png']
    assert row['original']==folder/source.name
    assert row['video'] is None and not row['complete']


def test_partial_draft_promotion_resumes_identical_bytes_only(tmp_path,monkeypatch):
    from agent.thoremix import core
    settings,campaign,job,source,child,files=setup(tmp_path)
    save_working_assets(settings,job,files)
    video=tmp_path/'output.mp4'
    video.write_bytes(b'reviewed native video')
    monkeypatch.setattr(core,'validate_media',lambda *a,**k: {'full_decode':True})
    replace=core.os.replace
    def interrupted(source_path,path):
        path=Path(path)
        if path.name=='package.json' and path.parent==Path(job['package_dir']):
            raise OSError('interrupted at final manifest')
        return replace(source_path,path)
    monkeypatch.setattr(core.os,'replace',interrupted)
    with pytest.raises(OSError):
        campaign.finalize(job['id'],video,children=[child],metadata={'qa':{'release_ready':True}})
    assert source.exists()
    save_working_assets(settings,job,files)
    assert not list(Path(job['package_dir']).glob('*.tmp'))
    monkeypatch.setattr(core.os,'replace',replace)
    result=campaign.finalize(job['id'],video,children=[child],metadata={'qa':{'release_ready':True}})
    assert not source.exists()
    assert sha256(Path(result['video_path']))==sha256(video)
    assert campaign.get(job['id'])['state']=='video_ready'


def test_changed_draft_is_never_overwritten(tmp_path):
    settings,campaign,job,source,child,files=setup(tmp_path)
    save_working_assets(settings,job,files)
    frame=Path(job['package_dir'])/'frames/01.png'
    frame.write_bytes(b'user change')
    with pytest.raises(ValueError):
        save_working_assets(settings,job,files)
    assert frame.read_bytes()==b'user change' and source.exists()


def test_source_receipt_promoted_before_video_can_resume(tmp_path,monkeypatch):
    from agent.thoremix import core
    settings,campaign,job,source,child,files=setup(tmp_path)
    save_working_assets(settings,job,files)
    folder=Path(job['package_dir'])
    core.atomic_json(folder/'source.json',{'job_id':job['id'],'source_sha256':job['source_sha256'],
                                         'original_name':source.name,'slot':job['slot']})
    save_working_assets(settings,job,files)
    video=tmp_path/'output.mp4'
    video.write_bytes(b'reviewed video')
    monkeypatch.setattr(core,'validate_media',lambda *a,**k:{'full_decode':True})
    campaign.finalize(job['id'],video,children=[child],metadata={'qa':{'release_ready':True}})
    assert (folder/'package.json').is_file() and not source.exists()


def test_desktop_can_open_as_passive_viewer_while_producer_holds_lock(tmp_path,monkeypatch):
    from agent.thoremix import cli,desktop
    settings,*_=setup(tmp_path)
    monkeypatch.setattr(cli,'root_operation',Mock(side_effect=AssertionError('producer owns lock')))
    opened=Mock()
    monkeypatch.setattr(desktop,'run_desktop',opened)
    assert cli.main(['--root',settings.root,'desktop'])==0
    opened.assert_called_once()
