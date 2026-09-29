import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.thoremix.config import atomic_json
from agent.thoremix.story_stages import StageJournal,StageBlocked,StageUncertain
from agent.thoremix.story_operations import StoryOperations


@pytest.mark.parametrize('bad_data',[None,[],{'accepted':False}])
def test_unavailable_image_qa_is_advisory_and_needs_owner_review(tmp_path,bad_data,monkeypatch):
    ops=StoryOperations(SimpleNamespace(),SimpleNamespace())
    monkeypatch.setattr(ops,'_review_chat',lambda *a,**k:{'state':'verified','data':bad_data})
    result=ops.execute('image_review',{'source':str(tmp_path/'source.png'),
        'analysis':{},'images':{'files':[]}},tmp_path,lambda _:None)
    assert result['state']=='verified' and result['data']['accepted'] is False
    assert result['data']['issues']


def test_audio_quality_warning_preserves_native_video_and_audio(tmp_path,monkeypatch):
    import agent.thoremix.story_operations as module
    video=tmp_path/'highest.mp4';video.write_bytes(b'native-media-bytes')
    ops=StoryOperations(SimpleNamespace(directory=tmp_path),SimpleNamespace())
    monkeypatch.setattr(ops,'_audio_assessment',lambda *a:([],{'accepted':False,'issues':['uncertain ASR']}))
    monkeypatch.setattr(module,'validate_media',lambda *a,**k:{'full_decode':True})
    monkeypatch.setattr(ops,'_ffmpeg',lambda args:SimpleNamespace(stdout=b'video hash' if 'hash' in args else b'pcm'*1000))
    result=ops._audio({'video':{'files':[{'path':str(video)}]},'analysis':{'dialogues':[{'text':'Xin chào'}]}},
        tmp_path,lambda _:None,None)
    assert result['state']=='verified' and result['data']['accepted'] is False
    assert Path(result['files'][0]['path']).read_bytes()==video.read_bytes()
    assert result['data']['muted_duplicate_intervals']==[]


def test_video_sampling_failure_is_an_advisory_warning(tmp_path,monkeypatch):
    ops=StoryOperations(SimpleNamespace(),SimpleNamespace())
    def fail(*args):raise RuntimeError('sample decode failed')
    monkeypatch.setattr(ops,'_contact',fail)
    result=ops.execute('video_review',{'source':str(tmp_path/'source.png'),
        'analysis':{'panels':[{}]},'video':{'files':[{'path':str(tmp_path/'native.mp4')}]}}
        ,tmp_path,lambda _:None)
    assert result['state']=='verified' and result['data']['accepted'] is False
    assert result['data']['issues']==['QA_SAMPLE_UNAVAILABLE_RuntimeError']


def test_failed_qa_attachment_is_warning_but_explicit_pause_still_blocks():
    from agent.thoremix.quality import advisory
    failure={'state':'blocked','not_submitted':True,'reason':'GPT_BEFORE_SUBMIT'}
    result=advisory(failure)
    assert result['state']=='verified' and result['data']['accepted'] is False
    pause=dict(failure,reason='CHATGPT_WAIT_PAUSED')
    assert advisory(pause)==pause


def test_pre_submit_block_may_retry_but_retry_checkpoint_cannot_replay(tmp_path):
    journal=StageJournal(tmp_path,source_sha256='a'*64)
    with pytest.raises(StageBlocked):
        journal.run('video',{},lambda p:{'state':'blocked','not_submitted':True})
    def crash(progress):
        assert json.loads((tmp_path/'video.json').read_text())['state']=='SUBMITTING'
        raise TimeoutError()
    with pytest.raises(StageUncertain): journal.run('video',{},crash)
    with pytest.raises(StageUncertain):
        journal.run('video',{},lambda p:pytest.fail('must not repeat possible paid submit'))


def test_attachment_reply_recovery_requires_exact_verified_upload(tmp_path):
    settings=SimpleNamespace()
    runtime=SimpleNamespace(client=lambda:pytest.fail('no browser without upload evidence'))
    ops=StoryOperations(settings,runtime)
    source=tmp_path/'source.png';source.write_bytes(b'original')
    atomic_json(tmp_path/'analysis-provider.json',{'state':'uncertain','conversation_url':'https://chatgpt.com/c/bound'})
    result=ops._chat('analysis','prompt',[source],tmp_path,lambda _:None,{'progress':{}})
    assert result['reason']=='UPLOAD_NOT_VERIFIED'
    atomic_json(tmp_path/'analysis-upload.json',[{'path':str(source),'sha256':'b'*64}])
    result=ops._chat('analysis','prompt',[source],tmp_path,lambda _:None,{'progress':{}})
    assert result['reason']=='UPLOAD_SOURCE_MISMATCH'


def test_cached_nonterminal_text_reply_is_reconciled_with_settled_sdk_read(tmp_path):
    calls=[]
    user=SimpleNamespace(role='user',text='prompt',provider_message_id='user-id')
    reply=SimpleNamespace(text='{"accepted":true}',stable=True,provider_message_id='assistant-id')
    class Handle:
        def tail(self,**kw): calls.append('tail');return [user]
        def wait_for_new_message(self,**kw):
            assert kw['after_message_id']=='user-id'
            calls.append('settle');return reply
    runtime=SimpleNamespace(client=lambda:SimpleNamespace(chat=SimpleNamespace(open=lambda _:Handle())))
    atomic_json(tmp_path/'copy-provider.json',{'state':'uncertain','conversation_url':'https://chatgpt.com/c/bound'})
    result=StoryOperations(SimpleNamespace(),runtime)._chat('copy','prompt',[],tmp_path,lambda _:None,{'progress':{}})
    assert result['state']=='verified' and calls==['tail','settle']


def test_cached_download_is_bound_to_exact_native_identity(tmp_path):
    from agent.services.flow_story_browser import FlowStoryBrowser
    final=tmp_path/'highest.mp4';final.write_bytes(b'video')
    from agent.thoremix.story_operations import artifact
    atomic_json(tmp_path/'highest-download.json',{'state':'COMPLETED','media_id':'other','project_id':'project',
                 'workflow_id':'workflow','artifact':artifact(final),'data':{}})
    browser=FlowStoryBrowser(SimpleNamespace(),None)
    with pytest.raises(ValueError,match='MEDIA_MISMATCH'):
        browser._download(None,{'media_id':'correct','project_id':'project','workflow_id':'workflow'},tmp_path,highest=True)


@pytest.mark.parametrize('initial_uncertain', [False, True])
def test_rendered_json_escape_loss_recovers_exact_raw_message_without_resending(tmp_path, initial_uncertain):
    calls=[]
    class Chat:
        def send(self,*a,**k):pytest.fail('must not resend')
        def read_message_text(self,url,*,assistant_message_id):
            calls.append(assistant_message_id)
            if initial_uncertain and len(calls) == 1:
                return {'state':'uncertain','reason':'READ_TIMEOUT'}
            return {'state':'verified','conversation_url':url,'assistant_message_id':assistant_message_id,
                    'text':json.dumps({'accepted':True,'reason':'Nguồn nói "đi thôi".'})}
    runtime=SimpleNamespace(client=lambda:SimpleNamespace(chat=Chat()))
    atomic_json(tmp_path/'copy-provider.json',{'state':'verified','conversation_url':'https://chatgpt.com/c/bound',
        'assistant_message_id':'exact','text':'{"accepted":true,"reason":"Nguồn nói "đi thôi"."}'})
    ops=StoryOperations(SimpleNamespace(),runtime)
    if initial_uncertain:
        assert ops._chat('copy','frozen prompt',[],tmp_path,lambda _:None)['state']=='uncertain'
    result=ops._chat('copy','frozen prompt',[],tmp_path,lambda _:None)
    expected=['exact']*(2 if initial_uncertain else 1)
    assert result['data']['accepted'] is True and calls==expected
    assert ops._chat('copy','frozen prompt',[],tmp_path,lambda _:None)['data']==result['data']
    assert calls==expected
