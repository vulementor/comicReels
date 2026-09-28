"""Finite FlowKit bridge. Unsupported capability is not a successful production."""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path

import httpx

from .core import Campaign, sha256


class FlowKitProducer:
    def __init__(self, campaign: Campaign, client=None):
        self.campaign = campaign
        self._owns_client = client is None
        self.client = client or httpx.Client(base_url=campaign.settings.flowkit_url, timeout=30)

    def close(self):
        if self._owns_client:
            self.client.close()

    def status(self) -> dict:
        from .story_runtime import StoryRuntime
        try:
            runtime = StoryRuntime.load(self.campaign.settings)
            from agent.services.flow_browser_session import FlowProfileConfig
            FlowProfileConfig.load(Path(runtime.flow_profile_config))
            client = runtime.client()
            if not callable(getattr(client.image, 'generate_batch', None)):
                raise ValueError('IMAGE_BATCH_SDK_MISSING')
            return {'connected': None, 'images_configured': True,
                    'credits': None, 'credit_verified': False, 'automatic_story_ready': True,
                    'reason': 'Đã cài đủ runner; phiên đăng nhập và credit được xác minh trước khi tạo.',
                    'runtime': 'native_whole_story', 'authentication': 'checked_at_operation'}
        except (OSError, ValueError, ImportError, TypeError, KeyError):
            pass
        try:
            response = self.client.get('/api/comicreels/status')
            response.raise_for_status()
            state = response.json()
            credits_response = self.client.get('/api/flow/credits')
            credits = credits_response.json() if credits_response.status_code == 200 else {}
            balance = next((credits[key] for key in ('creditsRemaining', 'availableCredits', 'credits')
                            if type(credits.get(key)) in (int, float)), None)
            return {'connected': bool(state.get('flow', {}).get('ready')),
                    'images_configured': bool(state.get('ai', {}).get('configured')),
                    'credits': balance, 'credit_verified': balance is not None,
                    'automatic_story_ready': False,
                    'reason': 'Chưa hoàn thiện luồng tạo cả truyện trong một clip, kiểm tra nội dung và tải bản cao nhất.',
                    'credit_reason': None if balance is not None else 'FlowKit chưa trả số dư credit đã xác minh.'}
        except (httpx.HTTPError, ValueError, TypeError):
            return {'connected': False, 'credits': None, 'credit_verified': False,
                    'automatic_story_ready': False, 'reason': 'Không đọc được trạng thái FlowKit localhost.'}

    def import_source(self, job_id: str) -> dict:
        """Import once, reconcile import by source hash on an interrupted response."""
        job = self.campaign.get(job_id)
        detail = json.loads(job['detail'])
        if detail.get('flowkit_project_id'):
            return job
        source = Path(job['source'])
        if sha256(source) != job['source_sha256']:
            raise ValueError('Ảnh nguồn đã đổi.')
        if job['state'] == 'importing':
            response = self.client.get('/api/comicreels/projects')
            response.raise_for_status()
            rows = response.json()
            if isinstance(rows, dict):
                rows = rows.get('projects', [])
            matches = [r for r in rows if r.get('source_sha256') == job['source_sha256']]
            if len(matches) != 1:
                raise RuntimeError('Lần import trước chưa đối soát được; không import lại.')
            project_id = matches[0]['id']
        else:
            if job['state'] != 'reserved':
                raise RuntimeError('Trạng thái hiện tại không cho import mới.')
            self.campaign.update(job_id, 'importing')
            with source.open('rb') as stream:
                response = self.client.post('/api/comicreels/projects/import',
                    files={'file': (source.name, stream, mimetypes.guess_type(source.name)[0] or 'image/jpeg')},
                    data={'name': source.stem})
            response.raise_for_status()
            project_id = response.json()['project']['id']
        return self.campaign.update(job_id, 'production_pending', flowkit_project_id=project_id)

    def run(self, job_id: str) -> dict:
        state = self.status()
        if state.get('automatic_story_ready') and state.get('runtime') == 'native_whole_story':
            from .story_pipeline import StoryPipeline
            from .story_operations import StoryOperations
            return StoryPipeline(self.campaign, operations=StoryOperations(self.campaign.settings)).run(job_id)
        if not state['connected']:
            return {'state': 'needs_input', 'reason': state['reason']}
        if not state['credit_verified']:
            return {'state': 'credit_unknown', 'reason': state['credit_reason']}
        if state['credits'] <= 0:
            return {'state': 'no_credit', 'reason': 'Hết credit; ghép frame và thoại ChatGPT thuộc bản nâng cấp sau.'}
        # The current per-panel API would produce multiple ten-second clips. Do not
        # call it while claiming it implements the owner's single-story contract.
        return {'state': 'production_integration_pending', 'reason': state['reason']}

    def reconcile(self, job_id: str) -> dict:
        # The pipeline reuses completed stages and reconciles every uncertain stage read-only.
        return self.run(job_id)
