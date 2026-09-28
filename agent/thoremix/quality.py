"""Advisory content QA and explicit, hash-bound owner approval for publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

POLICY = 'advisory_manual_approval'


def package_state(package):
    qa = package.get('qa', {})
    if qa.get('policy')==POLICY:
        review=package.get('review',{})
        if qa.get('production_complete') is not True:
            raise ValueError('Video chưa hoàn thành sản xuất.')
        if review.get('status')=='pending':
            if qa.get('release_ready') is not False:
                raise ValueError('Clip chờ duyệt chưa được phép đăng.')
            return 'awaiting_approval'
        if review.get('status')=='approved':
            if (review.get('approved_video_sha256')!=package.get('video_sha256')
                    or review.get('approved_source_sha256')!=package.get('source_sha256')):
                raise ValueError('Quyết định duyệt không khớp video hiện tại.')
        elif review.get('status')!='not_required' or review.get('warnings'):
            raise ValueError('Clip có cảnh báo chưa được chủ kênh duyệt.')
    if qa.get('release_ready') is True:
        return 'video_ready'
    raise ValueError('Hồ sơ chưa hoàn thành sản xuất hoặc chưa có trạng thái duyệt chất lượng hợp lệ.')


def advisory(result, *, accepted=None):
    if (result.get('state')=='blocked' and result.get('not_submitted') is True
            and result.get('reason') in {'CHATGPT_WAIT_PAUSED','PRODUCTION_PAUSED'}):
        return result
    data = dict(result['data']) if isinstance(result.get('data'),dict) else {}
    okay = result.get('state') == 'verified' and data.get('accepted') is True
    if accepted is not None:
        okay = okay and accepted
    data['accepted'] = bool(okay)
    if not okay and not data.get('issues'):
        data['issues'] = [data.get('reason') or result.get('reason') or 'Chưa xác minh được chất lượng; cần chủ kênh xem lại.']
    data['advisory'] = True
    data['observed_state'] = result.get('state')
    return dict(result, state='verified', data=data)


def manifest_digest(package):
    return hashlib.sha256(json.dumps(package,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def request_approval(settings, job_id, expected_digest):
    """Accept a click while production owns the campaign; apply at the next safe boundary."""
    from .config import atomic_json
    from .core import root_operation, now_iso
    import re
    if not re.fullmatch('[0-9a-f]{32}',job_id) or not re.fullmatch('[0-9a-f]{64}',expected_digest):
        raise ValueError('Yêu cầu duyệt không hợp lệ.')
    folder=settings.data/'review-requests'
    with root_operation(folder):
        path=folder/(job_id+'.json')
        if path.exists():
            prior=json.loads(path.read_text(encoding='utf-8'))
            if prior['manifest_sha256']!=expected_digest:
                if prior.get('state')!='rejected':
                    raise ValueError('Yêu cầu duyệt cũ không khớp hồ sơ hiện tại.')
                import time
                history=folder/'history'
                history.mkdir(exist_ok=True)
                path.rename(history/(job_id+'-'+str(time.time_ns())+'.json'))
        if not path.exists():
            atomic_json(path,{'job_id':job_id,'manifest_sha256':expected_digest,'requested_at':now_iso(),'state':'pending'})
    return {'state':'approval_queued','job_id':job_id}


def apply_approvals(campaign):
    from .config import atomic_json
    from .core import root_operation, now_iso
    folder=campaign.settings.data/'review-requests'
    with root_operation(folder):
        for path in sorted(folder.glob('*.json')):
            request=json.loads(path.read_text(encoding='utf-8'))
            if request.get('state')!='pending':continue
            try:
                campaign.approve(request['job_id'],request['manifest_sha256'])
            except (ValueError,KeyError,FileNotFoundError) as error:
                request.update(state='rejected',error_type=type(error).__name__)
            else:
                request.update(state='approved',applied_at=now_iso())
            atomic_json(path,request)
