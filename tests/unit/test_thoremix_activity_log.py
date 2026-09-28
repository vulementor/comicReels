import json
import sqlite3
from pathlib import Path

from agent.thoremix.activity_log import build_activity
from agent.thoremix.config import Settings


def write_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def test_activity_timeline_combines_production_repair_and_platform_effects(tmp_path):
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'))
    job_id='1'*32
    source_hash='a'*64
    package=settings.output/'clip-one'
    jobs=[{'id':job_id,'source':str(tmp_path/'input'/'comic.png'),
           'package_dir':str(package),'state':'awaiting_approval',
           'created_at':'2026-09-28T08:00:00+00:00','updated_at':'2026-09-28T10:00:00+00:00',
           'detail':json.dumps({'production_stage':'finishing'})}]
    rows=[{'job_id':job_id,'title':'Clip one','folder':package,
           'manifest':{'source_sha256':source_hash}}]

    write_json(settings.data/'production'/job_id/'video_review.json',{
        'state':'COMPLETED','result':{'state':'verified','data':{
            'accepted':False,'issues':['Sai cảnh ở đoạn cuối.']}}})
    write_json(settings.data/'audio-repairs'/job_id/'repair.json',{
        'state':'promoted_awaiting_approval'})
    journal=settings.data/'krp'/'state.sqlite3'
    journal.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(journal) as db:
        db.execute('CREATE TABLE effects(operation_id TEXT,idempotency_key TEXT,action TEXT,platform TEXT,state TEXT,reason TEXT,attempts INTEGER,updated_at TEXT)')
        db.execute('INSERT INTO effects VALUES(?,?,?,?,?,?,?,?)',(
            'op1',f'thoremix:{source_hash}:facebook:publish','publish_reel','facebook',
            'needs_input','session=https://private.example/path token=SECRET',1,
            '2026-09-28T11:00:00+00:00'))

    events=build_activity(settings,jobs,rows)
    publication=next(e for e in events if e['category']=='publishing')
    assert publication['clip']=='Clip one'
    assert publication['channel']=='Facebook'
    assert publication['action']=='Đăng video'
    assert publication['level']=='attention'
    assert 'https://' not in publication['detail']
    assert 'SECRET' not in publication['detail']
    assert '[đã ẩn]' in publication['detail']

    assert any(e['category']=='repair' and e['action']=='Sửa âm thanh'
               and e['status']=='Đã sửa · chờ duyệt' for e in events)
    qa=next(e for e in events if e['action']=='QA video')
    assert qa['status']=='Đã xác minh'
    assert qa['detail']=='Sai cảnh ở đoạn cuối.'
    job=next(e for e in events if e['action']=='Trạng thái công việc')
    assert job['status']=='Chờ duyệt'


def test_activity_journal_failure_is_visible_without_mutation(tmp_path):
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'))
    journal=settings.data/'krp'/'state.sqlite3'
    journal.parent.mkdir(parents=True,exist_ok=True)
    journal.write_bytes(b'not sqlite')
    before=journal.read_bytes()
    events=build_activity(settings,[],[])
    assert len(events)==1
    assert events[0]['level']=='error'
    assert events[0]['action']=='Đọc nhật ký đăng kênh'
    assert journal.read_bytes()==before
