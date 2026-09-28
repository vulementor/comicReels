"""Read-only activity timeline assembled from durable ThoRemix/KRP evidence.

The desktop uses this projection to explain where each clip is in production,
repair, review and publication.  No browser session or SDK is opened here.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

STAGE_LABELS = {
    'analysis': 'Phân tích truyện',
    'images': 'Tạo cảnh',
    'image_review': 'QA ảnh',
    'video': 'Tạo video Flow',
    'video_review': 'QA video',
    'highest': 'Tải bản chất lượng cao',
    'audio': 'Kiểm tra âm thanh',
    'copy': 'Soạn nội dung',
    'affiliate': 'Chọn affiliate',
    'finishing': 'Xử lý video cuối',
}
PLATFORM_NAMES = {'facebook': 'Facebook', 'tiktok': 'TikTok', 'youtube': 'YouTube'}
ACTION_NAMES = {'publish_reel': 'Đăng video', 'create_comment': 'Đăng bình luận'}

_URL = re.compile(r'https?://\S+', re.I)
_SECRET = re.compile(
    r'(?i)\b(cookie|authorization|bearer|token|session|password|secret)\b\s*[:=]\s*[^\s,;]+'
)


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _file_time(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return None


def _safe_reason(value) -> str:
    if not isinstance(value, str):
        return ''
    text = ' '.join(value.split())
    text = _URL.sub('[URL]', text)
    text = _SECRET.sub(lambda m: m.group(1) + '=[đã ẩn]', text)
    return text[:360]


def _level(state: str | None) -> str:
    value = str(state or '').strip().lower()
    if value in {'failed', 'production_failed', 'qa_failed', 'invalid_source', 'rejected'}:
        return 'error'
    if value in {
        'needs_input', 'unknown', 'unknown_after_submit', 'submitted_unverified',
        'reconciliation_required', 'awaiting_approval', 'production_quarantined',
        'candidate_ready_revision_required', 'promoted_awaiting_approval',
    }:
        return 'attention'
    if value in {
        'confirmed', 'complete', 'completed', 'verified', 'ok', 'video_ready',
        'published', 'source_text_already_repaired', 'native_audio_already_preserved',
    }:
        return 'ok'
    return 'waiting'


def _state_text(state: str | None) -> str:
    value = str(state or '').strip()
    lower = value.lower()
    labels = {
        'confirmed': 'Đã xác nhận', 'complete': 'Hoàn tất', 'completed': 'Hoàn tất',
        'verified': 'Đã xác minh', 'ok': 'Đã xác minh', 'failed': 'Lỗi',
        'production_failed': 'Sản xuất lỗi', 'needs_input': 'Cần xử lý',
        'unknown': 'Chờ đối soát', 'unknown_after_submit': 'Chờ đối soát',
        'submitted_unverified': 'Đã gửi · chờ xác minh', 'awaiting_approval': 'Chờ duyệt',
        'video_ready': 'Sẵn sàng đăng', 'published': 'Đã đăng đủ',
        'publishing': 'Đang đăng', 'production_pending': 'Đang sản xuất',
        'reserved': 'Đã nhận ảnh', 'producing': 'Đang sản xuất',
        'candidate_ready_revision_required': 'Có bản sửa · cần revision',
        'promoted_awaiting_approval': 'Đã sửa · chờ duyệt',
        'source_text_already_repaired': 'Chữ nguồn đã sửa',
        'native_audio_already_preserved': 'Âm gốc đã giữ',
    }
    return labels.get(lower, value or 'Chưa rõ')


def _event(*, key: str, timestamp: str | None, job_id: str | None, clip: str,
           category: str, action: str, state: str | None, detail: str = '',
           platform: str | None = None, source: str | None = None) -> dict:
    return {
        'key': key, 'timestamp': timestamp, 'job_id': job_id, 'clip': clip,
        'category': category, 'action': action,
        'platform': platform, 'channel': PLATFORM_NAMES.get(platform or '', ''),
        'state': state, 'status': _state_text(state), 'level': _level(state),
        'detail': _safe_reason(detail), 'source': source,
    }


def _result_detail(data: dict) -> str:
    result = data.get('result')
    result = result if isinstance(result, dict) else {}
    payload = result.get('data')
    payload = payload if isinstance(payload, dict) else {}
    issues = payload.get('issues')
    if isinstance(issues, list) and issues:
        return _safe_reason(str(issues[0]))
    return _safe_reason(payload.get('reason') or result.get('reason') or data.get('reason'))


def _stage_state(data: dict) -> str | None:
    state = data.get('state')
    result = data.get('result')
    result = result if isinstance(result, dict) else {}
    if str(state).upper() == 'COMPLETED':
        nested = result.get('state')
        return nested if isinstance(nested, str) else 'completed'
    return state if isinstance(state, str) else result.get('state')


def _job_clip(job: dict) -> str:
    source = job.get('source')
    if isinstance(source, str) and source:
        return Path(source).stem
    package = job.get('package_dir')
    return Path(package).name if isinstance(package, str) and package else str(job.get('id') or 'Không rõ clip')


def build_activity(settings, jobs: list[dict], rows: list[dict]) -> list[dict]:
    events: list[dict] = []
    source_to_clip: dict[str, tuple[str | None, str]] = {}
    for row in rows:
        source_hash = (row.get('manifest') or {}).get('source_sha256')
        if isinstance(source_hash, str):
            source_to_clip[source_hash] = (row.get('job_id'), row.get('title') or row['folder'].name)

    for job in jobs:
        job_id = job.get('id')
        clip = _job_clip(job)
        state = job.get('state')
        detail = ''
        try:
            detail_data = json.loads(job.get('detail') or '{}')
            if isinstance(detail_data, dict):
                detail = detail_data.get('reason') or detail_data.get('error') or detail_data.get('production_stage') or ''
        except (ValueError, TypeError):
            pass
        events.append(_event(
            key=f'job:{job_id}:{job.get("updated_at")}', timestamp=job.get('updated_at') or job.get('created_at'),
            job_id=job_id, clip=clip, category='production', action='Trạng thái công việc',
            state=state, detail=str(detail), source='campaign.sqlite3'))

        production = settings.data / 'production' / str(job_id)
        for stage, label in STAGE_LABELS.items():
            path = production / f'{stage}.json'
            if not path.is_file():
                continue
            data = _json(path)
            events.append(_event(
                key=f'stage:{job_id}:{stage}:{_file_time(path)}', timestamp=_file_time(path),
                job_id=job_id, clip=clip, category='production', action=label,
                state=_stage_state(data), detail=_result_detail(data), source=str(path)))

        for kind, label in (('audio-repairs', 'Sửa âm thanh'),
                            ('source-text-repairs', 'Phục hồi chữ nguồn')):
            path = settings.data / kind / str(job_id) / 'repair.json'
            if not path.is_file():
                continue
            data = _json(path)
            events.append(_event(
                key=f'repair:{job_id}:{kind}:{_file_time(path)}', timestamp=_file_time(path),
                job_id=job_id, clip=clip, category='repair', action=label,
                state=data.get('state'), detail=data.get('reason') or '', source=str(path)))

    journal = settings.data / 'krp' / 'state.sqlite3'
    if journal.is_file():
        try:
            with sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=0.2) as db:
                db.row_factory = sqlite3.Row
                for raw in db.execute(
                    'SELECT operation_id,idempotency_key,action,platform,state,reason,attempts,updated_at '
                    'FROM effects ORDER BY updated_at DESC'
                ):
                    item = dict(raw)
                    match = re.match(r'^thoremix:([0-9a-f]{64})(?::|$)', str(item.get('idempotency_key') or ''))
                    source_hash = match.group(1) if match else None
                    job_id, clip = source_to_clip.get(source_hash, (None, (source_hash or 'KRP')[:12]))
                    platform = item.get('platform')
                    action = ACTION_NAMES.get(str(item.get('action')), str(item.get('action') or 'Hành động'))
                    detail = item.get('reason') or ''
                    if item.get('attempts'):
                        detail = (detail + ' · ' if detail else '') + f"Lần thử: {item['attempts']}"
                    events.append(_event(
                        key='krp:' + str(item.get('operation_id')), timestamp=item.get('updated_at'),
                        job_id=job_id, clip=clip, category='publishing', action=action,
                        platform=platform, state=item.get('state'), detail=detail,
                        source='krp/state.sqlite3'))
        except sqlite3.Error:
            events.append(_event(
                key='krp:journal-error', timestamp=None, job_id=None, clip='KRP',
                category='publishing', action='Đọc nhật ký đăng kênh', state='failed',
                detail='Không đọc được KRP journal; dữ liệu có thể đang bận.',
                source='krp/state.sqlite3'))

    def sort_key(item):
        try:
            return datetime.fromisoformat(str(item.get('timestamp')).replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError, OverflowError):
            return float('-inf')

    events.sort(key=lambda item: (sort_key(item), item['key']), reverse=True)
    return events
