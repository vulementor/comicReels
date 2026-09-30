"""Explicit local profile bindings for the installed whole-story producer."""
from dataclasses import dataclass
from pathlib import Path
import json
from uuid import UUID

from agent.private_runtime import current_runtime


@dataclass(frozen=True)
class StoryRuntime:
    chat_profile: str
    chat_profile_dir: str
    chat_home: str
    flow_profile_config: str
    flow_project_id: str
    chat_min_interval_s: int = 90
    chat_rest_after_response_s: int = 30

    @classmethod
    def load(cls, settings):
        value = json.loads((settings.directory/'config'/'production-runtime.json').read_text(encoding='utf-8-sig'))
        runtime = cls(**value)
        if not 30 <= runtime.chat_min_interval_s <= 3600 or not 15 <= runtime.chat_rest_after_response_s <= 3600:
            raise ValueError('INVALID_CHATGPT_REQUEST_SPACING')
        if str(UUID(runtime.flow_project_id)) != runtime.flow_project_id:
            raise ValueError('INVALID_FLOW_PROJECT')
        for name in ('chat_profile_dir', 'chat_home', 'flow_profile_config'):
            path = Path(getattr(runtime, name))
            if not path.is_absolute() or not path.exists():
                raise ValueError('PRODUCTION_PROFILE_MISSING')
        return runtime

    def client(self):
        runtime = current_runtime()
        if runtime is not None:
            return runtime.gpt_client(
                profile=self.chat_profile, profile_dir=self.chat_profile_dir,
                home=self.chat_home, visible=False,
            )
        from gpt_fullproxy import GPTFullProxy
        return GPTFullProxy(profile=self.chat_profile, profile_dir=Path(self.chat_profile_dir),
                            home=Path(self.chat_home), visible=False)
