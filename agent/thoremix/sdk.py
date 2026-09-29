"""Finite toolkit operations shared by the desktop and CLI."""
from pathlib import Path

from .config import Settings
from .core import Campaign, campaign_operation


class ThoRemixClient:
    def __init__(self, root: Path | str):
        self.root = Path(root)

    @property
    def settings(self) -> Settings:
        return Settings.load(self.root)

    def status(self, *, probe: bool = False) -> dict:
        from .cli import status
        return status(self.settings, probe=probe)

    def reserve(self, slot: str, *, source: Path | None = None) -> dict:
        settings = self.settings
        with campaign_operation(settings):
            return Campaign(settings).reserve(slot, source=source)

    def prepare_package(self, slot: str, source: Path, video: Path, *, children: list[Path], metadata: dict) -> dict:
        settings = self.settings
        with campaign_operation(settings):
            return Campaign(settings).prepare_package(slot, source, video, children=children, metadata=metadata)

    def finalize(self, job_id: str, video: Path, *, children: list[Path], metadata: dict) -> dict:
        settings = self.settings
        with campaign_operation(settings):
            return Campaign(settings).finalize(job_id, video, children=children, metadata=metadata)

    def publish(self, package: Path) -> dict:
        from .cli import publish
        settings = self.settings
        with campaign_operation(settings):
            return publish(settings, package)

    def revise_package(self, job_id: str, video: Path, *, metadata: dict) -> dict:
        from .revisions import revise_package
        return revise_package(self.settings, job_id, video, metadata)

    def tick(self, *, clock: str | None = None) -> dict:
        from .cli import tick
        settings = self.settings
        return tick(settings, clock)

    def affiliate(self) -> dict:
        from .affiliate import acquire_affiliate
        settings = self.settings
        with campaign_operation(settings):
            return acquire_affiliate(settings)

    def configure_production(self, *, mode: str, daily_limit: int) -> Settings:
        from .config import change_settings
        return change_settings(self.root, production_mode=mode, daily_production_limit=daily_limit)

    def set_enabled(self, enabled: bool) -> Settings:
        from .config import change_settings
        if type(enabled) is not bool:
            raise ValueError('Trạng thái tự động phải là true hoặc false.')
        return change_settings(self.root, enabled=enabled)

    def produce_ahead(self) -> dict:
        from .production_queue import produce_ahead
        return produce_ahead(self.settings)

    def dispatch(self) -> dict:
        from .production_queue import dispatch
        return dispatch(self.settings)

    def request_approval(self,job_id: str,manifest_sha256: str) -> dict:
        from .quality import request_approval
        return request_approval(self.settings,job_id,manifest_sha256)

    def retry_story(self,job_id: str) -> dict:
        from .retry import retry_story
        return retry_story(self.settings,job_id)

    def configure_finishing(self,**changes) -> Settings:
        from dataclasses import replace
        import shutil
        from .core import sha256
        from .config import change_settings
        allowed={'mask_enabled','mask_top_percent','mask_bottom_percent','laugh_enabled','laugh_path','laugh_volume'}
        if set(changes)-allowed:raise ValueError('Cài đặt xử lý video không hợp lệ.')
        candidate=replace(self.settings,**changes);candidate.validate()
        if candidate.laugh_enabled:
            source=Path(candidate.laugh_path).resolve(strict=True)
            target=self.settings.directory/'assets/laugh'/(sha256(source)+source.suffix.lower())
            target.parent.mkdir(parents=True,exist_ok=True)
            if source!=target:
                part=target.with_suffix('.part')
                shutil.copy2(source,part)
                if sha256(part)!=sha256(source):raise ValueError('File tiếng cười thay đổi khi sao chép.')
                import os
                os.replace(part,target)
            changes['laugh_path']=str(target)
        return change_settings(self.root,**changes)
