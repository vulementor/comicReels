"""Explicit one-story continuation. Failed receipts reopen for reconciliation only."""
from __future__ import annotations

import json
import math
import re
import shutil
import uuid
from pathlib import Path

from .config import Settings,atomic_json
from .core import campaign_operation,sha256

STAGES=('analysis','images','image_review','video','video_review','highest','audio','copy','affiliate','finishing')
STAGE_NAMES=dict(zip(STAGES,('phân tích truyện','tạo ảnh con','kiểm tra ảnh','tạo video',
    'kiểm tra video','tải video','kiểm tra âm thanh','viết nội dung','chọn sản phẩm','xử lý video')))
REASONS={
    'STORY_DIALOGUE_TOO_LONG':'Lời thoại vượt thời lượng 10 giây. Thử lại sẽ kiểm tra phân tích đã lưu; không tự cắt lời thoại.',
    'STORY_REFERENCE_CAPACITY_OR_ORDER':'Truyện vượt giới hạn 4 ảnh tham chiếu hoặc thứ tự cảnh chưa hợp lệ.',
    'UNCERTAIN_SOURCE_PANEL':'Chưa xác định rõ một cảnh trong ảnh nguồn.',
    'INVALID_SOURCE_DIALOGUE':'Chưa đọc đủ lời thoại hoặc người nói trong ảnh nguồn.',
    'DIALOGUE_PANEL_UNKNOWN':'Chưa ghép được lời thoại với đúng cảnh.',
    'SOURCE_NOT_SUPPORTED_OR_UNCERTAIN':'Chưa xác minh được phân tích ảnh nguồn; cần đối chiếu lại kết quả đã lưu.',
    'PROMPT_CHANGED':'Nội dung xử lý đã thay đổi; cần đối chiếu lượt cũ trước khi tiếp tục.',
    'NO_FLOW_CREDIT':'Flow đã hết credit; chờ bổ sung rồi tiếp tục.',
    'FLOW_AUTH_REQUIRED':'Phiên Google Flow cần đăng nhập lại.',
    'SOURCE_CHANGED':'Ảnh nguồn hoặc dữ liệu đã lưu đã thay đổi; chưa thể tiếp tục tự động.',
}


def failure_message(stage,record):
    result=record.get('result')
    reason=result.get('reason','') if isinstance(result,dict) else ''
    if not isinstance(reason,str):reason=''
    if reason in REASONS:return REASONS[reason]
    if record.get('state') in {'UNKNOWN','SUBMITTING'}:
        return 'Chưa xác nhận được kết quả lượt trước. App sẽ đối soát trước khi tiếp tục.'
    if record.get('state') in {'BLOCKED','FAILED'}:
        return f"Bước {STAGE_NAMES.get(stage,'sản xuất')} chưa hoàn tất. Có thể thử lại từ dữ liệu đã lưu."
    return ''


def retry_story(settings,job_id,*,producer_factory=None,now=None):
    from .production_queue import ProductionQueue,local_now
    from .producer import FlowKitProducer
    from .story_stages import StageJournal
    if not re.fullmatch('[0-9a-f]{32}',job_id):raise ValueError('Công việc không hợp lệ.')
    producer_factory=producer_factory or FlowKitProducer
    with campaign_operation(settings):
        settings=Settings.load(settings.directory)
        now=now or (lambda:local_now(settings));stamp=now()
        q=ProductionQueue(settings);q.recover(stamp);job=q.campaign.get(job_id)
        base={'job_id':job_id}
        if job['state'] in {'video_ready','awaiting_approval','published','publishing','wrong_media_blocked'}:
            return dict(base,state='retry_not_needed')
        if not settings.enabled:return dict(base,state='retry_paused')
        attempt=next((a for a in q.attempts() if a['job_id']==job_id),None)
        if not attempt or attempt['status'] not in {'failed','blocked','unknown','quarantined'}:
            return dict(base,state='retry_rejected')
        remaining=q.cooldown_remaining(stamp)
        if remaining>0:return dict(base,state='retry_cooldown',seconds=math.ceil(remaining))
        if q.summary(stamp)['completed']>=settings.daily_production_limit:
            return dict(base,state='retry_quota_reached')
        directory=settings.data/'production'/job_id
        records={}
        try:
            if sha256(Path(job['source']))!=job['source_sha256']:raise ValueError('SOURCE_CHANGED')
            for name in STAGES:
                path=directory/(name+'.json')
                if not path.exists():continue
                record=json.loads(path.read_text(encoding='utf-8'))
                if record['source_sha256']!=job['source_sha256']:raise ValueError('SOURCE_CHANGED')
                if record['state']=='COMPLETED':StageJournal._validate_files(record['result'])
                records[name]=record
        except (OSError,ValueError,KeyError,TypeError,RuntimeError):
            return dict(base,state='retry_rejected',reason='SOURCE_CHANGED')
        audit=directory/'manual-retries'/uuid.uuid4().hex
        audit.mkdir(parents=True)
        atomic_json(audit/'intent.json',{'job_before':job,'attempt_before':attempt,'requested_at':stamp.isoformat()})
        for name,record in records.items():
            if record['state']!='FAILED':continue
            path=directory/(name+'.json');backup=audit/path.name
            shutil.copy2(path,backup)
            if sha256(backup)!=sha256(path):raise ValueError('Biên nhận thay đổi trong lúc tiếp tục.')
            # UNKNOWN calls the saved stage's reconcile callback, never a fresh operation.
            record['state']='UNKNOWN';atomic_json(path,record)
        q.finish(job_id,'blocked',stamp,'owner_requested_resume')
        q.campaign.update(job_id,'production_pending',manual_retry=str(audit))
        producer=producer_factory(q.campaign)
        try:state,_=q.produce_one(stamp,producer,now,resume_job_id=job_id)
        finally:
            close=getattr(producer,'close',None)
            if callable(close):close()
        if state=='reconciliation_required' and attempt['status']=='quarantined':
            q.finish(job_id,'quarantined',now(),'image_submission_awaiting_reconciliation')
            q.campaign.update(job_id,'production_quarantined')
        result=dict(base,state={'complete':'retry_complete','failed':'retry_failed',
            'reconciliation_required':'retry_uncertain'}.get(state,'retry_blocked'))
        for name in STAGES:
            path=directory/(name+'.json')
            if path.exists():
                record=json.loads(path.read_text(encoding='utf-8'))
                if record['state']!='COMPLETED':
                    result.update(stage=name,reason=record.get('result',{}).get('reason',''),
                                  message=failure_message(name,record));break
        atomic_json(audit/'result.json',result)
        q.report(now(),state='waiting_schedule' if state=='complete' else state)
        return result
