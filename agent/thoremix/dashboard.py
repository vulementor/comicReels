"""Read-only desktop projections; never construct Campaign or invoke an SDK."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .config import Settings

PLATFORMS = ('facebook', 'tiktok', 'youtube')
NAMES = {'facebook': 'Facebook', 'tiktok': 'TikTok', 'youtube': 'YouTube'}


def mapping(value):
    return value if isinstance(value, dict) else {}


def read_json(path: Path, issues: list[str]) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (OSError, ValueError):
        issues.append(f'Không đọc được {path.name}; chưa thể xác nhận dữ liệu này.')
        return {}


def state_text(state) -> str:
    state = state if isinstance(state, str) else None
    if state == 'confirmed':
        return 'Đã xác nhận'
    if state in {'unknown', 'unknown_after_submit', 'submitted_unverified', 'submitted_processing', 'submitted', 'running', 'intent'}:
        return 'Chờ xác minh'
    return {'needs_input': 'Cần xử lý', 'failed': 'Thất bại', 'pending': 'Chưa thực hiện',
            'ok': 'Đã xác minh', 'video_ready': 'Video sẵn sàng', 'published': 'Chờ biên nhận',
            'production_failed': 'Sản xuất lỗi · đã bỏ qua',
            'awaiting_approval': 'Sản xuất thành công · chờ anh duyệt',
            'production_quarantined': 'Giữ riêng · chờ đối soát ảnh',
            'production_pending': 'Đang sản xuất / chờ tiếp tục', 'reserved': 'Đã chọn ảnh nguồn',
            'producing': 'Đang sản xuất', 'imported': 'Đã nhập ảnh',
            'paused': 'Tạm dừng', 'busy': 'Đang bận'}.get(str(state), 'Chưa xác minh' if state else 'Chưa thực hiện')


def safe_link(value, platform: str) -> str | None:
    """Only public, credential-free HTTPS references from the expected service."""
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value:
        return None
    hosts = {platform + '.com', 'www.' + platform + '.com'}
    if platform == 'youtube':
        hosts.add('youtu.be')
    if platform == 'shopee':
        hosts = {'s.shopee.vn', 'shopee.vn', 'www.shopee.vn'}
    try:
        url = urlsplit(value)
        allowed = {'v', 'comment_id', 'reply_comment_id', 'lc'} if platform != 'shopee' else set()
        if (url.scheme != 'https' or url.hostname not in hosts or url.username or url.password
                or url.port not in (None, 443) or url.fragment or not url.path.strip('/')
                or any(key not in allowed for key, _ in parse_qsl(url.query, keep_blank_values=True))):
            return None
        return value
    except ValueError:
        return None


def publication_view(receipt: dict, targets=PLATFORMS) -> dict:
    channels, links = {}, []
    confirmed = 0
    valid_scope = (isinstance(targets, (list, tuple)) and bool(targets)
                   and all(isinstance(p, str) and p in PLATFORMS for p in targets)
                   and len(set(targets)) == len(targets))
    active = tuple(targets) if valid_scope else ()
    for platform in PLATFORMS:
        if platform not in active:
            label = 'Không yêu cầu' if valid_scope else 'Phạm vi chưa rõ'
            channels[platform] = {'publication': label, 'comment': label}
            continue
        item = mapping(mapping(receipt.get('platforms')).get(platform))
        effects = {}
        for action in ('publication', 'comment'):
            effect = mapping(item.get(action))
            state = effect.get('state')
            # An auth preflight failure is not a publication confirmation.
            if not state and action == 'publication' and item.get('status') not in (None, 'complete', 'confirmed'):
                state = item.get('status')
            confirmed += state == 'confirmed'
            effects[action] = state_text(state)
            if state == 'confirmed' and (url := safe_link(effect.get('permalink'), platform)):
                links.append({'label': NAMES[platform] + (' · bài đăng' if action == 'publication' else ' · bình luận'), 'url': url})
        channels[platform] = effects
    required = len(active) * 2
    return {'channels': channels, 'links': links, 'confirmed': confirmed, 'required': required,
            'active_platforms': active, 'scope_valid': valid_scope,
            'complete': valid_scope and confirmed == required}


def selected_key(rows: list[dict], previous: str | None) -> str | None:
    keys = [row['key'] for row in rows]
    return previous if previous in keys else (keys[0] if keys else None)


def _timestamp(value) -> float | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (ValueError, TypeError, OverflowError):
        return None


def visible_rows(rows: list[dict], filter_name: str = 'all', order: str = 'newest') -> list[dict]:
    """Filter the video list and sort by production time, never approval/update time."""
    filters = {
        'all': lambda row: True,
        'produced': lambda row: bool(row.get('video')),
        'failed': lambda row: row.get('job_state') == 'production_failed',
        'posted': lambda row: int(row.get('posted_count') or 0) > 0,
        'ready': lambda row: (bool(row.get('video')) and int(row.get('posted_count') or 0) == 0
                              and row.get('job_state') in {'video_ready', 'awaiting_approval'}),
    }
    predicate = filters.get(filter_name, filters['all'])
    selected = [row for row in rows if predicate(row)]
    reverse = order != 'oldest'
    produced = [(stamp, row) for row in selected
                if (stamp := _timestamp(row.get('produced_at'))) is not None]
    pending = [row for row in selected if _timestamp(row.get('produced_at')) is None]
    produced.sort(key=lambda item: (item[0], item[1].get('key', '')), reverse=reverse)
    pending.sort(key=lambda row: (_timestamp(row.get('created_at')) or float('-inf'),
                                  row.get('key', '')), reverse=reverse)
    return [row for _, row in produced] + pending


def date_text(value) -> str:
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone().strftime('%d/%m/%Y · %H:%M %Z')
    except (ValueError, TypeError):
        return 'Chưa ghi thời gian'


def local_asset(value, folder: Path) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = folder / path
    path = path.resolve()
    return path if path.is_relative_to(folder.resolve()) and path.is_file() else None


def build_snapshot(settings: Settings) -> dict:
    issues: list[str] = []
    try:
        if settings.path.exists():
            settings = Settings.load(settings.directory)
    except (OSError, ValueError, TypeError, KeyError):
        issues.append('Cấu hình không đọc được; đang hiển thị cấu hình của phiên mở cửa sổ.')
    jobs = []
    attempts = {}
    database = settings.data / 'campaign.sqlite3'
    if database.is_file():
        try:
            with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=0.2) as db:
                db.row_factory = sqlite3.Row
                jobs = [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY updated_at DESC')]
                try:
                    attempts = {r['job_id']: dict(r) for r in db.execute(
                        'SELECT * FROM production_attempts ORDER BY started_at,job_id')}
                except sqlite3.Error:
                    attempts = {}
        except sqlite3.Error:
            issues.append('Chưa đọc được hàng đợi; cơ sở dữ liệu có thể đang bận.')
    folders = {str(Path(j['package_dir']).resolve()): j for j in jobs if j.get('package_dir')}
    current_packages = {j['id']: path for path, j in folders.items()}
    if settings.output.is_dir():
        try:
            for manifest in settings.output.glob('*/package.json'):
                folders.setdefault(str(manifest.parent.resolve()), {})
        except OSError:
            issues.append('Chưa đọc được thư mục video.')
    rows = []
    for folder_text, job in folders.items():
        folder = Path(folder_text)
        manifest = read_json(folder / 'package.json', issues)
        manifest_job = manifest.get('job_id')
        # Keep old revisions on disk, but only the campaign's current package is actionable.
        if (not job and isinstance(manifest_job, str) and manifest_job in current_packages
                and current_packages[manifest_job] != folder_text):
            continue
        receipt = read_json(folder / 'publication.json', issues)
        digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if receipt and (not manifest or receipt.get('package_sha256') != digest):
            issues.append(f'{folder.name}: biên nhận không khớp hồ sơ; cần đối soát.')
            receipt = {}
        view = publication_view(receipt, manifest.get('publication_targets', PLATFORMS))
        if not view['scope_valid']:
            issues.append(f'{folder.name}: phạm vi kênh đăng không hợp lệ; chưa thể xác nhận hoàn tất.')
        draft = read_json(folder / 'draft.json', issues) if not manifest else {}
        if draft and (draft.get('job_id') != job.get('id') or draft.get('source_sha256') != job.get('source_sha256')):
            issues.append(f'{folder.name}: ảnh làm việc chưa khớp công việc.')
            draft = {}
        frames = manifest.get('frames', draft.get('frames'))
        saved_frames = []
        preview = None
        for frame in frames if isinstance(frames, list) else []:
            asset = local_asset(mapping(frame).get('path'), folder)
            if asset:
                saved_frames.append(asset)
        original = local_asset(manifest.get('source_path') or mapping(draft.get('source')).get('path'), folder)
        if original is None and job.get('source'):
            candidate = Path(job['source']).resolve()
            if candidate.parent == Path(settings.input_dir).resolve() and candidate.is_file():
                original = candidate
        preview = (saved_frames[0] if saved_frames else None) or original
        detail = {}
        try:
            detail = mapping(json.loads(job.get('detail') or '{}'))
        except (ValueError, TypeError):
            pass
        stage = detail.get('production_stage')
        qa_issues = []
        for warning in mapping(manifest.get('review')).get('warnings',[]):
            result=mapping(mapping(warning).get('result'))
            qa_issues.extend(result.get('issues') or [result.get('reason') or 'Cần xem lại chất lượng.'])
        saved_stage={}
        if job.get('id') and stage in {'analysis','images','image_review','video','video_review','highest','audio','copy','affiliate','finishing'}:
            saved_stage = read_json(settings.data/'production'/job['id']/(stage+'.json'), issues)
            if not manifest:
                qa_issues = mapping(mapping(saved_stage.get('result')).get('data')).get('issues', [])
        from .retry import failure_message
        retry_label=''
        if not manifest and not receipt and job.get('id'):
            if job.get('state')=='production_failed':retry_label='Thử lại sản xuất'
            elif job.get('state') in {'production_pending','production_quarantined','reserved'}:
                retry_label='Đối soát & tiếp tục' if saved_stage.get('state') in {'UNKNOWN','SUBMITTING'} else 'Tiếp tục sản xuất'
        attempt = attempts.get(job.get('id'), {})
        produced_at = (manifest.get('created_at') if manifest else None)
        if not produced_at and attempt.get('status') == 'complete':
            produced_at = attempt.get('completed_at')
        posted_count = sum(view['channels'][p]['publication'] == 'Đã xác nhận' for p in PLATFORMS)
        rows.append({'key': folder_text, 'folder': folder, 'job_id': job.get('id'),
                     'created_at': job.get('created_at') or manifest.get('created_at'),
                     'produced_at': produced_at, 'job_state': job.get('state'),
                     'posted_count': posted_count,
                     'retry_label':retry_label,'failure_message':failure_message(stage,saved_stage),
                     'title': str(manifest.get('title') or Path(job.get('source') or folder.name).stem),
                     'caption': str(manifest.get('caption') or 'Chưa có nội dung đã chốt.'),
                     'state': (f"Hoàn tất {len(view['active_platforms'])} kênh yêu cầu" if view['complete'] else
                               ('Phạm vi kênh cần xử lý' if not view['scope_valid'] else
                                (f"{view['confirmed']}/{view['required']} mục đã xác nhận" if receipt else state_text(job.get('state'))))),
                     'preview': preview, 'original': original, 'frames': saved_frames,
                     'production_stage': stage, 'qa_issues': qa_issues if isinstance(qa_issues,list) else [],
                     'video': local_asset(manifest.get('video_path'), folder),
                     'manifest': manifest, 'publication': receipt, **view})
    auth = read_json(settings.data / 'auth-status.json', issues)
    if auth.get('profile') != settings.social_profile:
        auth = {}
    return {'rows': rows, 'auth': auth, 'affiliate': read_json(settings.data / 'affiliate-selection.json', issues),
            'production': read_json(settings.data / 'production-status.json', issues),
            'chatgpt_pacing': read_json(settings.data / 'chatgpt-pacing.json', issues),
            'production_mode': settings.production_mode, 'daily_production_limit': settings.daily_production_limit,
            'last': read_json(settings.data / 'last-result.json', issues), 'issues': issues,
            'enabled': settings.enabled, 'slots': settings.slots, 'input': Path(settings.input_dir),
            'output': settings.output, 'config': settings.path}
