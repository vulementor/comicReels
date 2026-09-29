import pytest
from agent.thoremix.story_audio import duplicate_intervals


def words(text):
    return [dict(word=w,start=i*.3,end=(i+1)*.3,probability=.98) for i,w in enumerate(text.split())]


def source(*lines):
    return [dict(text=line,panel_index=i,display_order=i) for i,line in enumerate(lines)]


def test_keep_first_utterance_and_mute_only_exact_duplicate():
    assert duplicate_intervals(source('Xin chào!','Đi thôi.'),words('Xin chào Xin chào Đi thôi'),10)==[[.6,1.2]]


@pytest.mark.parametrize('heard',['Xin chào','Xin chào Đi ngay','Đi thôi Xin chào','Xin chào Đi thôi người lạ'])
def test_missing_rewritten_reordered_extra_dialogue_is_rejected(heard):
    with pytest.raises(ValueError):
        duplicate_intervals(source('Xin chào','Đi thôi'),words(heard),10)


def test_legitimate_repeated_source_line_is_not_muted():
    assert duplicate_intervals(source('Xin chào','Xin chào'),words('Xin chào Xin chào'),10)==[]


def test_uncertain_words_or_overlapping_duplicate_fail_closed():
    rows=words('Xin chào Xin chào')
    rows[2]['start']=.4
    with pytest.raises(ValueError,match='OVERLAP'):
        duplicate_intervals(source('Xin chào'),rows,10)
    rows=words('Xin chào');rows[0]['probability']=.1
    with pytest.raises(ValueError,match='UNCERTAIN'):
        duplicate_intervals(source('Xin chào'),rows,10)


def test_empty_source_words_cannot_loop():
    with pytest.raises(ValueError): duplicate_intervals(source('...'),words('Xin'),10)


def test_analysis_line_break_notation_does_not_invent_spoken_letter_n():
    assert duplicate_intervals(source(r'ĐỐI VỚI ANH EM\nLUÔN LÀ THỨ NHẤT'),
                               words('Đối với anh em luôn là thứ nhất'),10)==[]


@pytest.fixture
def native_audio(tmp_path):
    import subprocess
    from types import SimpleNamespace
    from agent.thoremix.config import Settings
    from agent.thoremix.core import media_tool
    from agent.thoremix.story_operations import StoryOperations

    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'))
    ffmpeg=media_tool('ffmpeg',settings.directory)
    def create(*,silent=False):
        path=tmp_path/('silent.mp4' if silent else 'native.mp4')
        subprocess.run([ffmpeg,'-nostdin','-y','-v','error','-f','lavfi','-i',
            'color=c=blue:s=120x240:r=24:d=2','-f','lavfi','-i',
            'anullsrc=r=48000:cl=stereo' if silent else 'sine=frequency=440:duration=2',
            '-t','2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],
            check=True,capture_output=True)
        return StoryOperations(settings,SimpleNamespace()),path
    return create


def test_source_without_dialogue_keeps_native_sound_and_requires_review(native_audio,tmp_path):
    from pathlib import Path
    ops,video=native_audio()
    result=ops._audio({'video':{'files':[{'path':str(video)}]},'analysis':{'dialogues':[]}},
        tmp_path,lambda _:None,None)
    # No dialogue in the comic is not evidence that generated ambience should be erased.
    assert Path(result['files'][0]['path']).read_bytes()==video.read_bytes()
    assert result['data']['decoded_audio_all_zero'] is False
    assert result['data']['accepted'] is False
    assert 'AUDIO_NO_DIALOGUE_REVIEW_REQUIRED' in result['data']['issues']
    assert result['data']['muted_duplicate_intervals']==[]


def test_source_without_dialogue_keeps_already_silent_native_audio(native_audio,tmp_path):
    from pathlib import Path
    ops,video=native_audio(silent=True)
    result=ops._audio({'video':{'files':[{'path':str(video)}]},'analysis':{'dialogues':[]}},
        tmp_path,lambda _:None,None)
    assert Path(result['files'][0]['path']).read_bytes()==video.read_bytes()
    assert result['data']['decoded_audio_all_zero'] is True
    assert result['data']['accepted'] is True


def test_verified_duplicate_muting_preserves_first_and_following_sound(native_audio,tmp_path,monkeypatch):
    import numpy as np
    ops,video=native_audio()
    monkeypatch.setattr(ops,'_audio_assessment',lambda *a:([[.6,1.2]],{'accepted':True,'issues':[]}))
    result=ops._audio({'video':{'files':[{'path':str(video)}]},'analysis':{'dialogues':source('Xin chào')}},
        tmp_path,lambda _:None,None)
    def pcm(path):
        return np.frombuffer(ops._ffmpeg(['-i',str(path),'-map','0:a:0','-ac','1',
            '-ar','8000','-f','f32le','-']).stdout,np.float32)
    original,final=pcm(video),pcm(result['files'][0]['path'])
    assert np.max(np.abs(final[int(.7*8000):int(1.1*8000)]))<.0001
    for start,end in [(.1,.5),(1.4,1.8)]:
        a,b=original[int(start*8000):int(end*8000)],final[int(start*8000):int(end*8000)]
        assert np.corrcoef(a,b)[0,1]>.99
        assert .95<float(a@b/(a@a))<1.05
