"""Durable source reservation and package finalization; no browser effects."""
from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from .config import Settings, atomic_json
from .media import media_tool

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.jfif'}
_LOCK_STATE = threading.local()


class RunnerBusyError(RuntimeError):
    """Safe fixed diagnostic, distinct from arbitrary provider RuntimeErrors."""


class SourceExhausted(RuntimeError):
    """No unused, readable source remains; distinct from a provider failure."""


def _canonical(path):
    return os.path.normcase(str(Path(path).resolve()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def runner_lock(directory: Path):
    """OS-owned lock: a process crash releases it without deleting another PID's lock."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'runner.lock'
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RunnerBusyError('Một lượt Thỏ Remix hoặc cửa sổ đăng nhập đang mở; chờ lượt đó hoàn tất.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RunnerBusyError('Một lượt Thỏ Remix hoặc cửa sổ đăng nhập đang mở; chờ lượt đó hoàn tất.') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def root_operation(directory: Path):
    """Reentrant only within this thread, with one real OS lock for its lifetime."""
    key = _canonical(directory)
    held = getattr(_LOCK_STATE, 'roots', set())
    if key in held:
        yield
        return
    with runner_lock(directory):
        _LOCK_STATE.roots = held | {key}
        try:
            yield
        finally:
            _LOCK_STATE.roots = held


@contextmanager
def campaign_operation(settings: Settings):
    """One source owner and journal across all roots, not just simultaneous runs."""
    source = Path(settings.input_dir).resolve(strict=True)
    if not source.is_dir():
        raise ValueError('Thư mục nguồn không hợp lệ.')
    owner = {'schema_version': 1, 'source': _canonical(source),
             'root': _canonical(settings.directory),
             'database': _canonical(settings.data / 'campaign.sqlite3'),
             'krp_home': _canonical(settings.data / 'krp'),
             'effect_journal': _canonical(settings.data / 'krp' / 'state.sqlite3')}
    key = (owner['source'], owner['root'])
    held = getattr(_LOCK_STATE, 'campaigns', set())
    with root_operation(settings.data):
        if key in held:
            yield
            return
        control = source / '.thoremix'
        with runner_lock(control):
            owner_path = control / 'owner.json'
            if owner_path.exists():
                if json.loads(owner_path.read_text(encoding='utf-8')) != owner:
                    raise ValueError('Thư mục nguồn đã thuộc một bản Thỏ Remix khác; cần đối soát chủ sở hữu và nhật ký trước khi dùng.')
            else:
                atomic_json(owner_path, owner)
            _LOCK_STATE.campaigns = held | {key}
            try:
                yield
            finally:
                _LOCK_STATE.campaigns = held


def _campaign_method(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with campaign_operation(self.settings):
            return method(self, *args, **kwargs)
    return guarded


class Campaign:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.database = settings.data / 'campaign.sqlite3'
        with campaign_operation(settings), self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, slot TEXT UNIQUE NOT NULL, source TEXT NOT NULL,
                source_sha256 TEXT UNIQUE NOT NULL, package_dir TEXT UNIQUE NOT NULL,
                state TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS source_errors(
                path TEXT PRIMARY KEY, reason TEXT NOT NULL, observed_at TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def jobs(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM jobs ORDER BY created_at DESC')]

    def get(self, job_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    @_campaign_method
    def update(self, job_id: str, state: str, **details) -> dict:
        current = self.get(job_id)
        detail = json.loads(current['detail']) | details
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,detail=?,updated_at=? WHERE id=?',
                       (state, json.dumps(detail, ensure_ascii=False), now_iso(), job_id))
        return self.get(job_id)

    @_campaign_method
    def reserve(self, slot: str, *, source: Path | None = None) -> dict:
        directory = Path(self.settings.input_dir).resolve(strict=True)
        selected = Path(source).absolute() if source is not None else None
        if selected is not None and (selected.is_symlink() or selected.resolve().parent != directory
                                     or selected.suffix.lower() not in IMAGE_SUFFIXES):
            raise ValueError('Ảnh được chọn phải là ảnh trực tiếp trong thư mục nguồn.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM jobs WHERE slot=?', (slot,)).fetchone()
            if existing:
                if selected is not None and _canonical(existing['source']) != _canonical(selected):
                    raise ValueError('Lượt này đã gắn với ảnh nguồn khác.')
                return dict(existing)
            consumed = {r[0] for r in db.execute('SELECT source_sha256 FROM jobs')}
            if selected is not None:
                if not selected.is_file():
                    raise ValueError('Ảnh nguồn được chọn không tồn tại.')
                candidates = [selected.resolve(strict=True)]
            else:
                candidates = [p for p in directory.iterdir() if p.is_file() and not p.is_symlink()
                              and p.suffix.lower() in IMAGE_SUFFIXES]
                random.SystemRandom().shuffle(candidates)
            for path in candidates:
                def source_error(reason):
                    db.execute('INSERT OR REPLACE INTO source_errors VALUES(?,?,?)',
                               (str(path), reason, now_iso()))
                try:
                    digest = sha256(path)
                except OSError:
                    source_error('source_unreadable')
                    continue
                if digest in consumed:
                    if selected is not None:
                        raise ValueError('Ảnh này đã có công việc; tiếp tục công việc đó, không tạo lượt mới.')
                    continue
                from PIL import Image
                try:
                    with Image.open(path) as image:
                        image.verify()
                except (OSError, ValueError):
                    source_error('invalid_image')
                    continue
                folder = self.settings.output / path.stem
                if folder.exists() or db.execute('SELECT 1 FROM jobs WHERE package_dir=?', (str(folder),)).fetchone():
                    folder = self.settings.output / f'{path.stem}-{digest[:12]}'
                if folder.exists():
                    source_error('output_collision')
                    continue
                job_id = uuid.uuid4().hex
                stamp = now_iso()
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)',
                           (job_id, slot, str(path), digest, str(folder), 'reserved', '{}', stamp, stamp))
                return dict(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone())
        raise SourceExhausted('Không còn ảnh mới hợp lệ trong thư mục nguồn.')

    @_campaign_method
    def prepare_package(self, slot: str, source: Path, video: Path, *, children: list[Path], metadata: dict) -> dict:
        """Adopt an independently reviewed video with its exact original source."""
        from .quality import package_state
        package_state(metadata)
        job = self.reserve(slot, source=source)
        return self.finalize(job['id'], video, children=children, metadata=metadata)

    @_campaign_method
    def finalize(self, job_id: str, video: Path, *, children: list[Path], metadata: dict) -> dict:
        job = self.get(job_id)
        folder = Path(job['package_dir'])
        expected_parent = self.settings.output.resolve()
        if folder.resolve().parent != expected_parent:
            raise ValueError('Đường dẫn đầu ra vượt phạm vi chiến dịch.')
        draft = None
        if folder.exists() and not (folder / 'package.json').is_file():
            if not (folder / 'draft.json').is_file():
                raise FileExistsError('Hồ sơ đang sao chép dở; giữ nguyên ảnh nguồn để đối soát.')
            from .story_assets import validate_draft
            draft = validate_draft(folder, job, video=video)
            if [sha256(p) for p in children] != [item['sha256'] for item in draft['frames']]:
                raise ValueError('Ảnh con khác bộ ảnh đã lưu trong hồ sơ.')
        elif folder.exists():
            existing = json.loads((folder / 'package.json').read_text(encoding='utf-8'))
            if sha256(video) != existing.get('video_sha256') or any(existing.get(k) != v for k, v in metadata.items()):
                raise ValueError('Hồ sơ đã đóng băng khác nội dung được cung cấp.')
            return self.reconcile_package(job_id)
        source = Path(job['source'])
        if not source.is_file() or sha256(source) != job['source_sha256']:
            raise ValueError('Ảnh gốc đã thay đổi hoặc không còn ở đường dẫn đã giữ chỗ.')
        from .quality import package_state
        final_state=package_state(metadata)
        target = folder / f'{source.stem}.mp4'
        self.settings.output.mkdir(parents=True, exist_ok=True)
        # Validate the exact privately staged bytes. The caller may keep writing
        # its render; stable before/after hashes must agree with our frozen copy.
        with tempfile.TemporaryDirectory(prefix='.thoremix-video-', dir=self.settings.output) as staging:
            staged = Path(staging) / 'frozen.mp4'
            video_digest = sha256(video)
            shutil.copy2(video, staged)
            if sha256(video) != video_digest or sha256(staged) != video_digest:
                raise ValueError('Video thay đổi trong khi sao chép.')
            probe = validate_media(staged, tool_root=self.settings.directory)
            if sha256(staged) != video_digest:
                raise ValueError('Video thay đổi trong khi giải mã.')
            staged_folder = Path(staging) / 'package'
            staged_folder.mkdir()
            staged_target = staged_folder / target.name
            os.replace(staged, staged_target)
            atomic_json(staged_folder / 'source.json', {'job_id': job_id, 'source_sha256': job['source_sha256'],
                                                       'original_name': source.name, 'slot': job['slot']})
            child_dir = staged_folder / 'frames'
            child_dir.mkdir()
            child_receipts = []
            for index, child in enumerate(children, 1):
                destination = child_dir / f'{index:02d}{child.suffix.lower()}'
                shutil.copy2(child, destination)
                if sha256(child) != sha256(destination):
                    raise ValueError('Bản sao ảnh con không khớp.')
                child_receipts.append({'path': str(folder / 'frames' / destination.name),
                                       'sha256': sha256(destination)})
            original = folder / source.name
            staged_original = staged_folder / source.name
            if original == target or staged_original.exists():
                raise FileExistsError('Trùng tên file trong hồ sơ.')
            shutil.copy2(source, staged_original)
            if sha256(staged_original) != job['source_sha256']:
                raise ValueError('Bản sao ảnh gốc không khớp.')
            package = dict(metadata) | {
                'schema_version': 1, 'job_id': job_id, 'source_sha256': job['source_sha256'],
                'video_path': str(target), 'video_sha256': video_digest,
                'source_path': str(original), 'frames': child_receipts, 'media': probe,
                'created_at': now_iso(),
                'story_contract': {'source_count': 1, 'output_clips': 1,
                                   'source_sha256': job['source_sha256'], 'join_other_stories': False},
            }
            # Promote only the complete package. Copy failures leave no final directory,
            # so repairing an input and retrying resumes the same reservation.
            if (source.resolve().parent != Path(self.settings.input_dir).resolve()
                    or staged_folder.resolve().parent != Path(staging).resolve()
                    or Path(staging).resolve().parent != expected_parent
                    or folder.resolve().parent != expected_parent):
                raise ValueError('Đường dẫn hồ sơ vượt phạm vi chiến dịch.')
            if sha256(source) != job['source_sha256'] or sha256(staged_target) != video_digest:
                raise ValueError('Ảnh/video thay đổi trước bước lưu trữ.')
            atomic_json(staged_folder / 'package.json', package)
            if folder.exists() and draft is None:
                raise FileExistsError('Thư mục đích xuất hiện trong khi lưu; giữ nguyên thư mục đó.')
            self.update(job_id, 'package_pending')
            if draft is None:
                os.rename(staged_folder, folder)
            else:
                validate_draft(folder, job, video=staged_target)
                # The atomic manifest is the publication boundary. Working images stay
                # visible; interrupted local promotion can resume only identical bytes.
                for staged_file in staged_folder.rglob('*'):
                    if not staged_file.is_file() or staged_file.name == 'package.json':
                        continue
                    destination = folder/staged_file.relative_to(staged_folder)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        if sha256(destination) != sha256(staged_file):
                            raise ValueError('Tệp hồ sơ đã thay đổi trong khi lưu.')
                    else:
                        os.rename(staged_file, destination)
                os.replace(staged_folder/'package.json', folder/'package.json')
        self.update(job_id, final_state, package=str(folder / 'package.json'))
        if sha256(source) != job['source_sha256']:
            raise ValueError('Ảnh nguồn đã đổi sau khi lưu hồ sơ; giữ nguyên ảnh đó.')
        source.unlink()
        return package

    @_campaign_method
    def reconcile_package(self, job_id: str) -> dict:
        """Finish an interrupted local archive from hash-verified durable files."""
        from .finishing import recover_pending
        recover_pending(self,job_id)
        job = self.get(job_id)
        folder = Path(job['package_dir']).resolve(strict=True)
        if folder.parent != self.settings.output.resolve():
            raise ValueError('Hồ sơ nằm ngoài thư mục đầu ra.')
        package = json.loads((folder / 'package.json').read_text(encoding='utf-8'))
        from .quality import package_state
        final_state=package_state(package)
        if package.get('job_id') != job_id or package.get('source_sha256') != job['source_sha256']:
            raise ValueError('Hồ sơ không thuộc ảnh đã giữ chỗ.')
        video, original = Path(package['video_path']), Path(package['source_path'])
        if video.resolve().parent != folder or original.resolve().parent != folder:
            raise ValueError('Tệp trong hồ sơ nằm ngoài thư mục được phép.')
        if sha256(video) != package['video_sha256'] or sha256(original) != job['source_sha256']:
            raise ValueError('Tệp trong hồ sơ đã thay đổi.')
        for child in package.get('frames', []):
            path = Path(child['path'])
            if path.resolve().parent != folder / 'frames' or sha256(path) != child['sha256']:
                raise ValueError('Ảnh con đã thay đổi.')
        validate_media(video, tool_root=self.settings.directory)
        if sha256(video) != package['video_sha256']:
            raise ValueError('Video thay đổi trong khi giải mã.')
        source = Path(job['source'])
        if source.exists():
            if source.resolve().parent != Path(self.settings.input_dir).resolve() or sha256(source) != job['source_sha256']:
                raise ValueError('Ảnh nguồn đã thay đổi; không di chuyển.')
            source.unlink()
        if job['state'] not in {final_state, 'publishing', 'published'}:
            self.update(job_id, final_state, package=str(folder / 'package.json'), archive_reconciled=True)
        return package

    @_campaign_method
    def approve(self, job_id, expected_digest):
        from .quality import manifest_digest, package_state
        job=self.get(job_id)
        folder=Path(job['package_dir'])
        package=self.reconcile_package(job_id)
        review=package.get('review',{})
        already_approved=(review.get('status')=='approved'
                          and review.get('approved_manifest_sha256')==expected_digest)
        if not already_approved:
            if (package_state(package)!='awaiting_approval' or manifest_digest(package)!=expected_digest
                    or (folder/'publication.json').exists()):
                raise ValueError('Hồ sơ thay đổi hoặc không còn chờ duyệt; cần xem lại video hiện tại.')
            atomic_json(folder/'qa-before-owner-approval.json',package)
            package['review']=dict(review,status='approved',approved_at=now_iso(),
                approved_manifest_sha256=expected_digest,approved_video_sha256=package['video_sha256'],
                approved_source_sha256=package['source_sha256'])
            package['qa']['release_ready']=True
            atomic_json(folder/'package.json',package)
        receipt=self.settings.data/'production'/job_id/'flow/story-receipt.json'
        if receipt.is_file():
            from .finishing import complete_story_receipt
            complete_story_receipt(self.settings,job_id,folder/'package.json')
        if self.get(job_id)['state'] not in {'publishing','published'}:
            self.update(job_id,'video_ready',owner_approved=True)
        return package


def validate_media(path: Path, *, tool_root: Path | None = None) -> dict:
    if not path.is_file() or path.stat().st_size < 1024:
        raise ValueError('Chưa có video hoàn chỉnh.')
    probe = subprocess.run([media_tool('ffprobe', tool_root), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', check=True, timeout=60,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    info = json.loads(probe.stdout)
    videos = [s for s in info['streams'] if s['codec_type'] == 'video']
    audio = [s for s in info['streams'] if s['codec_type'] == 'audio']
    if len(videos) != 1 or not audio or videos[0]['height'] <= videos[0]['width']:
        raise ValueError('Video cần khung dọc và có âm thanh.')
    decode = subprocess.run([media_tool('ffmpeg', tool_root), '-nostdin', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, check=False,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if decode.returncode or decode.stderr.strip():
        raise ValueError('Video không qua kiểm tra giải mã toàn bộ.')
    return {'duration_s': float(info['format']['duration']), 'width': videos[0]['width'],
            'height': videos[0]['height'], 'full_decode': True}
