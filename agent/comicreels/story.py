"""Durable receipt for one source story and one native Flow generation.

The caller holds the Flow profile lease and verifies the observed request against
the intent before adopting its response. Nothing here sends or retries a request.
"""
from __future__ import annotations

import hashlib
import json

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

import os
import re
import tempfile
from pathlib import Path
from uuid import UUID


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('INVALID_UUID')
    return value


class StoryReceipt:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding='utf-8'))

    def begin(self, intent: dict) -> dict:
        if self.path.exists():
            raise ValueError('RECONCILIATION_REQUIRED')
        if (not re.fullmatch(r'[0-9a-f]{64}', intent.get('source_sha256', ''))
                or not isinstance(intent.get('prompt'), str) or not intent['prompt'].strip()
                or len(intent['prompt']) > 30000
                or type(intent.get('variants')) is not int or intent['variants'] != 1
                or intent.get('duration_s') != 10 or intent.get('aspect') != '9:16'
                or intent.get('resolution') not in {'360p', '720p'}
                or intent.get('model') != 'Omni 1.1 Flash'):
            raise ValueError('INVALID_STORY_INTENT')
        _uuid(intent['project_id'])
        refs = intent.get('ordered_reference_ids', [])
        if not 1 <= len(refs) <= 32 or len(set(refs)) != len(refs):
            raise ValueError('INVALID_STORY_REFERENCES')
        for media_id in refs:
            _uuid(media_id)
        allowed = {'source_sha256', 'project_id', 'ordered_reference_ids', 'prompt',
                   'duration_s', 'model', 'resolution', 'aspect', 'variants'}
        if set(intent) != allowed:
            raise ValueError('INVALID_STORY_INTENT')
        record = {'schema_version': 1, 'state': 'SUBMITTING', 'intent': intent,
                  'prompt_sha256': hashlib.sha256(intent['prompt'].encode()).hexdigest(),
                  'source_count': 1, 'output_clips': 1, 'release_ready': False}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.path.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            raise ValueError('RECONCILIATION_REQUIRED') from None
        return record

    def submitted(self, receipt: dict) -> dict:
        record = self.load()
        clean = {key: _uuid(receipt[key]) for key in ('media_id', 'workflow_id', 'project_id')}
        if clean['project_id'] != record['intent']['project_id']:
            raise ValueError('RECEIPT_PROJECT_MISMATCH')
        if record['state'] == 'PROCESSING':
            if any(record.get(key) != clean[key] for key in clean):
                raise ValueError('RECEIPT_MISMATCH')
            return record
        if record['state'] != 'SUBMITTING':
            raise ValueError('RECONCILIATION_REQUIRED')
        record.update(clean, state='PROCESSING')
        self._write(record)
        return record

    def _write(self, record):
        fd, temporary = tempfile.mkstemp(prefix=self.path.name, suffix='.tmp', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def complete(self, package_path: Path) -> dict:
        """Bind the package produced by Campaign.finalize after operator content QA.

        This records that reviewed artifact, not an automatic quality judgement.
        The package producer owns full decode; hashes bind its exact frozen bytes.
        """
        record = self.load()
        if record['state'] not in {'PROCESSING', 'COMPLETED'}:
            raise ValueError('RECONCILIATION_REQUIRED')
        try:
            path = Path(package_path).resolve(strict=True)
            raw = path.read_bytes()
            package = json.loads(raw)
            contract = package['story_contract']
            video = Path(package['video_path']).resolve(strict=True)
            original = Path(package['source_path']).resolve(strict=True)
            if (package['source_sha256'] != record['intent']['source_sha256']
                    or contract['source_sha256'] != package['source_sha256']
                    or type(contract['source_count']) is not int or contract['source_count'] != 1
                    or type(contract['output_clips']) is not int or contract['output_clips'] != 1
                    or contract['join_other_stories'] is not False
                    or package['qa']['release_ready'] is not True
                    or package['media']['full_decode'] is not True
                    or video.parent != path.parent or original.parent != path.parent
                    or any(package['flow'][key] != record[key]
                           for key in ('media_id', 'workflow_id', 'project_id'))):
                raise ValueError
            video_hash = _file_sha256(video)
            source_hash = _file_sha256(original)
            if video_hash != package['video_sha256'] or source_hash != package['source_sha256']:
                raise ValueError
            artifact = {'package_path': str(path), 'package_sha256': hashlib.sha256(raw).hexdigest(),
                        'video_path': str(video), 'video_sha256': video_hash}
            if record['state'] == 'COMPLETED' and record.get('artifact') != artifact:
                raise ValueError
        except (OSError, KeyError, ValueError, TypeError):
            raise ValueError('PACKAGE_UNVERIFIED') from None
        if record['state'] != 'COMPLETED':
            record.update(state='COMPLETED', release_ready=True, artifact=artifact)
            self._write(record)
        return record
