"""Durable finite story stages; caller holds the campaign's process lease."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .config import atomic_json
from .core import sha256


class StageUncertain(RuntimeError):
    pass


class StageRejected(RuntimeError):
    pass


class StageBlocked(RuntimeError):
    pass


class StageJournal:
    def __init__(self, directory: Path, *, source_sha256: str):
        if not re.fullmatch('[0-9a-f]{64}', source_sha256):
            raise ValueError('INVALID_SOURCE_HASH')
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.source_sha256 = source_sha256

    @staticmethod
    def _validate_files(result):
        for item in result.get('files', []):
            path = Path(item['path'])
            if not path.is_absolute() or not path.is_file() or sha256(path) != item['sha256']:
                raise StageUncertain('STAGE_ARTIFACT_CHANGED')

    def run(self, name: str, request: dict, operation, *, reconcile=None, advisory=False) -> dict:
        if not re.fullmatch('[a-z][a-z0-9_]{0,63}', name):
            raise ValueError('INVALID_STAGE')
        path = self.directory / (name + '.json')
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False,
                                               separators=(',', ':')).encode()).hexdigest()
        replay = path.exists()
        if replay:
            record = json.loads(path.read_text(encoding='utf-8'))
            if (record['source_sha256'] != self.source_sha256 or record['request_sha256'] != fingerprint):
                raise StageUncertain('STAGE_INTENT_CHANGED')
            if record['state'] == 'COMPLETED':
                self._validate_files(record['result'])
                return record['result']
            if (record['state'] == 'FAILED' and advisory and name in {'image_review','video_review','audio'}
                    and record.get('result',{}).get('state')=='qa_failed'):
                audit=self.directory/(name+'-before-advisory-policy.json')
                if not audit.exists():atomic_json(audit,record)
                record['state']='UNKNOWN'
                atomic_json(path,record)
            if record['state'] == 'FAILED':
                raise StageRejected(name)
            if record['state'] == 'BLOCKED':
                replay = False
                record.update(state='SUBMITTING', progress={})
                record.pop('result', None)
                record.pop('error_type', None)
                atomic_json(path, record)
            if reconcile is None:
                raise StageUncertain('RECONCILIATION_REQUIRED')
        else:
            record = {'schema_version': 1, 'stage': name, 'source_sha256': self.source_sha256,
                      'request_sha256': fingerprint, 'state': 'SUBMITTING', 'progress': {}}
            try:
                with path.open('x', encoding='utf-8') as stream:
                    json.dump(record, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                raise StageUncertain('RECONCILIATION_REQUIRED') from None

        def progress(value):
            allowed = {'conversation_url', 'media_id', 'workflow_id', 'project_id', 'run_id', 'preparation_step'}
            if not isinstance(value, dict) or not value.keys() <= allowed:
                raise ValueError('UNSAFE_PROGRESS')
            for key, item in value.items():
                pattern = (r'https://chatgpt\.com/c/[A-Za-z0-9_-]{1,200}' if key == 'conversation_url'
                           else r'[A-Za-z0-9_-]{1,200}')
                if not isinstance(item, str) or re.fullmatch(pattern, item) is None:
                    raise ValueError('UNSAFE_PROGRESS')
            record['progress'].update(value)
            atomic_json(path, record)

        try:
            result = reconcile(record, progress) if replay else operation(progress)
            if not isinstance(result, dict):
                raise StageUncertain('INVALID_STAGE_RESULT')
            state = result.get('state')
            if state == 'blocked' and result.get('not_submitted') is True:
                record.update(state='BLOCKED', result=result)
                atomic_json(path, record)
                raise StageBlocked(name)
            if state in {'failed', 'qa_failed', 'invalid_source'}:
                record.update(state='FAILED', result=result)
                atomic_json(path, record)
                raise StageRejected(name)
            if state != 'verified':
                record.update(state='UNKNOWN', result=result)
                atomic_json(path, record)
                raise StageUncertain('RECONCILIATION_REQUIRED')
            self._validate_files(result)
            record.update(state='COMPLETED', result=result)
            atomic_json(path, record)
            return result
        except (StageRejected, StageBlocked):
            raise
        except Exception as exc:
            # Never store arbitrary exception text (provider errors can contain signed URLs).
            record.update(state='UNKNOWN', error_type=type(exc).__name__)
            atomic_json(path, record)
            raise StageUncertain('RECONCILIATION_REQUIRED') from None
