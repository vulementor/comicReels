"""Durable spacing for new ChatGPT turns; never retry a provider effect here."""
import hashlib
import json
import re
import time
from pathlib import Path

from .config import Settings, atomic_json
from .core import root_operation


class PacingDeferred(RuntimeError):
    pass


class ChatPacer:
    def __init__(self, settings, runtime, *, clock=time.time, sleep=time.sleep):
        self.settings, self.runtime, self.clock, self.sleep = settings, runtime, clock, sleep
        key = hashlib.sha256(str(Path(runtime.chat_profile_dir).resolve()).casefold().encode()).hexdigest()[:20]
        self.directory = Path(runtime.chat_home)/'request-spacing'/key
        self.path = self.directory/'state.json'

    def read(self):
        return json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}

    def call(self, operation):
        with root_operation(self.directory):
            state = self.read()
            while self.clock() < state.get('next_request_at', 0):
                if self.settings.path.exists() and not Settings.load(self.settings.directory).enabled:
                    raise PacingDeferred('CHATGPT_WAIT_PAUSED')
                atomic_json(self.settings.data/'chatgpt-pacing.json', state)
                self.sleep(min(5, state['next_request_at'] - self.clock()))
            if self.settings.path.exists() and not Settings.load(self.settings.directory).enabled:
                raise PacingDeferred('CHATGPT_WAIT_PAUSED')
            start = self.clock()
            state = {'last_started_at': start, 'next_request_at': start + self.runtime.chat_min_interval_s,
                     'state': 'request_in_progress'}
            atomic_json(self.path, state)
            atomic_json(self.settings.data/'chatgpt-pacing.json', state)
            response = None
            try:
                response = operation()
                return response
            finally:
                state['last_finished_at'] = self.clock()
                state['next_request_at'] = max(state['next_request_at'], self.clock() + self.runtime.chat_rest_after_response_s)
                state['state'] = 'resting'
                if isinstance(response, dict) and rate_limited(response):
                    delay = response.get('retry_after_s', response.get('retry_after_seconds', 3600))
                    if not isinstance(delay, (int, float)) or delay <= 0:
                        delay = 3600
                    state.update(state='rate_limit_wait', next_request_at=max(state['next_request_at'], self.clock()+delay))
                atomic_json(self.path, state)
                atomic_json(self.settings.data/'chatgpt-pacing.json', state)


def rate_limited(response):
    if response.get('status_code') == 429 or response.get('code') in {'rate_limit_exceeded', 'rate_limited'}:
        return True
    if response.get('state') in {'verified', 'completed'}:
        return False
    text = ' '.join(str(response.get(k) or '') for k in ('reason', 'error'))
    return bool(re.search(r'rate[ _-]?limit|too many requests|you.ve (?:hit|reached).*limit|'
                         r'bạn đã (?:đạt|chạm|vượt).{0,40}giới hạn', text, re.I))
