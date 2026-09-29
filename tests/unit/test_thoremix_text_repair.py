import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from agent.comicreels.sign_text import select_overlay_font
from agent.thoremix.config import Settings
from agent.thoremix.core import Campaign, media_tool, sha256
from agent.thoremix.text_repair import repair_source_text


@pytest.fixture
def repair_case(tmp_path):
    source_dir=tmp_path/'input'
    source_dir.mkdir()
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(source_dir))
    settings.save()
    ffmpeg=media_tool('ffmpeg',settings.directory)
    video=tmp_path/'native.mp4'
    try:
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error',
            '-f','lavfi','-i','color=c=white:s=120x240:r=24:d=2',
            '-f','lavfi','-i','sine=frequency=220:duration=2',
            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],
            check=True,capture_output=True)
    except (FileNotFoundError,subprocess.CalledProcessError):
        pytest.skip('ffmpeg required')
    source=source_dir/'story.png'
    Image.new('RGB',(400,600),'white').save(source)
    campaign=Campaign(settings)
    job=campaign.reserve('text-repair/test')
    package=campaign.finalize(job['id'],video,children=[],metadata={
        'title':'Source text repair','caption':'Source text repair',
        'description':'Source text repair','qa':{'release_ready':True},
    })
    spec={
        'kind':'signage','text':'CẤM VÀO',
        'source_sha256':package['source_sha256'],
        'video_sha256':package['video_sha256'],
        'source_verified':True,'geometry_verified':True,
        'evidence':'test source and stationary sign geometry',
        'width':120,'height':240,'fps':24.0,'start_frame':12,'end_frame':24,
        'box':{'x':10,'y':80,'w':100,'h':60},
    }
    try:
        font=select_overlay_font(spec['text'])
    except ValueError:
        pytest.skip('Vietnamese overlay font required')
    return settings,campaign,job,spec,font


def test_repeating_same_source_text_repair_is_idempotent(repair_case):
    settings,campaign,job,spec,font=repair_case
    first=repair_source_text(settings,job['id'],spec,font=font)
    assert first['state']=='promoted_awaiting_approval'
    folder=Path(campaign.get(job['id'])['package_dir'])
    package=json.loads((folder/'package.json').read_text(encoding='utf-8'))
    before=(folder/'package.json').read_bytes()
    first_warning_count=sum(
        row.get('stage')=='source_text_repair'
        for row in package['review']['warnings']
        if isinstance(row,dict)
    )
    assert first_warning_count==1
    assert package['source_text_overlay']['base_video_sha256']==spec['video_sha256']
    assert package['source_text_overlay']['output_sha256']==package['video_sha256']
    assert package['source_text_overlay']['output_sha256']!=spec['video_sha256']

    second=repair_source_text(settings,job['id'],spec,font=font)
    assert second['state']=='source_text_already_repaired'
    assert second['video_sha256']==package['video_sha256']
    assert (folder/'package.json').read_bytes()==before
    after=json.loads((folder/'package.json').read_text(encoding='utf-8'))
    assert sum(
        row.get('stage')=='source_text_repair'
        for row in after['review']['warnings']
        if isinstance(row,dict)
    )==1
