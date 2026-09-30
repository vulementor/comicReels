import json
from datetime import datetime,timedelta
from pathlib import Path

import pytest
from PIL import Image

from agent.thoremix.config import Settings,atomic_json
from agent.thoremix.core import Campaign,campaign_operation,sha256
from agent.thoremix.production_queue import ProductionQueue
from agent.thoremix.story_stages import StageJournal,StageRejected

NOW=datetime.fromisoformat('2026-09-28T10:00:00+07:00')


def failed_story(tmp_path):
    source=tmp_path/'input';source.mkdir()
    Image.new('RGB',(30,60),'white').save(source/'story.png')
    s=Settings(root=str(tmp_path/'app'),input_dir=str(source),enabled=True);s.save()
    q=ProductionQueue(s);j=q.campaign.reserve('production/2026-09-28/test')
    with q.campaign.connect() as db:
        db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status,completed_at) VALUES(?,?,?,?,?)',
            (j['id'],'2026-09-28',NOW.isoformat(),'failed',(NOW-timedelta(seconds=61)).isoformat()))
    q.campaign.update(j['id'],'production_failed',production_stage='analysis')
    directory=s.data/'production'/j['id'];journal=StageJournal(directory,source_sha256=j['source_sha256'])
    request={'source':j['source']}
    with pytest.raises(StageRejected):
        journal.run('analysis',request,lambda progress:{'state':'invalid_source','reason':'STORY_DIALOGUE_TOO_LONG'})
    return s,q,j,directory,request


def test_retry_reconciles_failed_stage_without_resending_and_keeps_original_audit(tmp_path):
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    original=(directory/'analysis.json').read_bytes();calls=[]
    class Producer:
        def __init__(self,campaign):pass
        def close(self):calls.append('closed')
        def run(self,job_id):
            assert job_id==j['id']
            journal=StageJournal(directory,source_sha256=j['source_sha256'])
            try:
                journal.run('analysis',request,lambda p:pytest.fail('must not send a fresh prompt'),
                    reconcile=lambda prior,p:{'state':'invalid_source','reason':'STORY_DIALOGUE_TOO_LONG'})
            except StageRejected:return {'state':'qa_failed','reason':'analysis'}
    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_failed' and result['reason']=='STORY_DIALOGUE_TOO_LONG'
    assert calls==['closed'] and Path(j['source']).is_file()
    audits=list((directory/'manual-retries').glob('*/analysis.json'))
    assert len(audits)==1 and audits[0].read_bytes()==original
    assert retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)['state']=='retry_failed'
    assert calls==['closed','closed']


def test_retry_unknown_preserves_effect_and_only_reconciles(tmp_path):
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    r=json.loads((directory/'analysis.json').read_text());r['state']='UNKNOWN';r['progress']={'conversation_url':'https://chatgpt.com/c/bound'}
    atomic_json(directory/'analysis.json',r)
    with q.campaign.connect() as db:db.execute("UPDATE production_attempts SET status='quarantined' WHERE job_id=?",(j['id'],))
    q.campaign.update(j['id'],'production_quarantined')
    class Producer:
        def __init__(self,campaign):pass
        def close(self):pass
        def run(self,job_id):
            assert json.loads((directory/'analysis.json').read_text())==r
            return {'state':'reconciliation_required'}
    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_uncertain'
    assert q.attempts()[0]['status']=='quarantined'
    assert json.loads((directory/'analysis.json').read_text())==r


def test_retry_does_not_mutate_changed_source_or_completed_artifact(tmp_path):
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    old=(directory/'analysis.json').read_bytes()
    Path(j['source']).write_bytes(b'changed')
    result=retry_story(s,j['id'],producer_factory=lambda c:pytest.fail('changed source'),now=lambda:NOW)
    assert result['state']=='retry_rejected' and (directory/'analysis.json').read_bytes()==old
    q.campaign.update(j['id'],'published')
    assert retry_story(s,j['id'],producer_factory=lambda c:pytest.fail('published'),now=lambda:NOW)['state']=='retry_not_needed'


def test_failed_row_exposes_reason_and_retry_button(tmp_path):
    from agent.thoremix.dashboard import build_snapshot
    from agent.thoremix.desktop import DesktopWindow
    import tkinter as tk
    s,q,j,directory,request=failed_story(tmp_path)
    snapshot=build_snapshot(s);row=snapshot['rows'][0]
    assert row['retry_label']=='Thử lại sản xuất' and '10 giây' in row['failure_message']
    root=tk.Tk();app=DesktopWindow(s,window=root,poll=False)
    calls=[];app.launch=lambda *args:calls.append(args) or True
    try:
        root.update();app.retry_button.invoke()
        assert calls==[('retry-production',j['id'])]
        assert str(app.retry_button.cget('state'))=='disabled'
        app.retry_button.invoke();assert len(calls)==1
        app.active='retry-production';app.retry_production(dict(row,job_id='c'*32))
        assert app.retry_job_id==j['id'] and len(calls)==1
    finally:app.quit()


def test_successful_retry_keeps_completed_images_and_is_idempotent(tmp_path,monkeypatch):
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    journal=StageJournal(directory,source_sha256=j['source_sha256'])
    child=directory/'child.png';Image.new('RGB',(30,60),'blue').save(child)
    journal.run('images',{},lambda p:{'state':'verified','files':[{'path':str(child),'sha256':sha256(child)}]})
    saved_images=(directory/'images.json').read_bytes();video=directory/'video.mp4';video.write_bytes(b'x'*4096)
    monkeypatch.setattr('agent.thoremix.core.validate_media',lambda *a,**k:{'full_decode':True})
    monkeypatch.setattr('agent.thoremix.core.now_iso',lambda:NOW.isoformat())
    class Producer:
        def __init__(self,campaign):self.campaign=campaign
        def close(self):pass
        def run(self,job_id):
            journal.run('analysis',request,lambda p:pytest.fail('no fresh analysis'),
                reconcile=lambda old,p:{'state':'verified','data':{'fixed':True}})
            images=journal.run('images',{},lambda p:pytest.fail('reuse images'))
            self.campaign.finalize(job_id,video,children=[Path(images['files'][0]['path'])],metadata={'qa':{'release_ready':True}})
            return {'state':'video_ready'}
    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_complete' and q.summary(NOW)['completed']==1
    assert (directory/'images.json').read_bytes()==saved_images
    assert retry_story(s,j['id'],producer_factory=lambda c:pytest.fail('already completed'),now=lambda:NOW)['state']=='retry_not_needed'


def test_manual_retry_runs_while_automation_is_paused(tmp_path):
    from dataclasses import replace
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    replace(s,enabled=False).save()
    class Producer:
        def __init__(self,campaign):pass
        def close(self):pass
        def run(self,job_id):
            return {'state':'qa_failed','reason':'analysis'}
    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_failed'
    assert result.get('stage')=='analysis'


def test_manual_retry_ignores_daily_scheduler_quota(tmp_path,monkeypatch):
    from agent.thoremix.retry import retry_story
    s,q,j,directory,request=failed_story(tmp_path)
    original_summary=ProductionQueue.summary
    def summary(self,stamp,*args,**kwargs):
        result=original_summary(self,stamp,*args,**kwargs)
        result['completed']=s.daily_production_limit
        return result
    monkeypatch.setattr(ProductionQueue,'summary',summary)
    class Producer:
        def __init__(self,campaign):pass
        def close(self):pass
        def run(self,job_id):
            return {'state':'qa_failed','reason':'analysis'}
    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_failed'


def test_retry_all_snapshots_only_failed_stories_and_waits_after_each_failure(tmp_path,monkeypatch):
    from agent.thoremix import retry
    s,q,j,directory,request=failed_story(tmp_path)
    Image.new('RGB',(30,60),'red').save(Path(s.input_dir)/'second.png')
    second=q.campaign.reserve('production/2026-09-28/second')
    with q.campaign.connect() as db:
        db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status) VALUES(?,?,?,?)',
            (second['id'],'2026-09-28',NOW.isoformat(),'failed'))
    clock=[NOW];calls=[];waits=[]
    def one(settings,job_id,**kw):
        calls.append(job_id);q.finish(job_id,'failed',clock[0]);return {'state':'retry_failed','job_id':job_id}
    def sleep(seconds):waits.append(seconds);clock[0]+=timedelta(seconds=seconds)
    monkeypatch.setattr(retry,'retry_story',one)
    with q.campaign.connect() as db:
        db.execute("UPDATE production_attempts SET status='quarantined' WHERE job_id=?",(second['id'],))
    q.campaign.update(second['id'],'production_quarantined')
    result=retry.retry_failed(s,now=lambda:clock[0],sleep=sleep)
    assert result['state']=='retry_batch_finished' and set(calls)=={j['id'],second['id']}
    assert result['processed']==2 and waits==[]


def test_video_filters_and_production_sort_do_not_use_last_approval_time():
    from agent.thoremix.dashboard import visible_rows
    rows=[{'key':'old','produced_at':'2026-09-27T22:00:00+07:00','created_at':'2026-09-27T20:00:00+07:00',
           'video':'old.mp4','job_state':'video_ready','posted_count':0,'complete':False},
          {'key':'new','produced_at':'2026-09-28T10:00:00+07:00','video':'new.mp4','job_state':'published',
           'posted_count':3,'complete':True},
          {'key':'error','produced_at':None,'created_at':'2026-09-28T15:00:00+07:00',
           'video':None,'job_state':'production_failed','posted_count':0,'complete':False}]
    assert [r['key'] for r in visible_rows(rows,'all','newest')]==['new','old','error']
    assert [r['key'] for r in visible_rows(rows,'produced','oldest')]==['old','new']
    assert [r['key'] for r in visible_rows(rows,'failed','newest')]==['error']
    assert [r['key'] for r in visible_rows(rows,'posted','newest')]==['new']
    assert [r['key'] for r in visible_rows(rows,'ready','newest')]==['old']
