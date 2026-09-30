from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@dataclass(frozen=True)
class Settings:
    root: str
    input_dir: str = 'D:\\Thỏ Remix'
    timezone: str = 'Asia/Ho_Chi_Minh'
    slots: tuple[str, ...] = ('11:00', '18:30')
    enabled: bool = False
    production_mode: str = 'scheduled'
    daily_production_limit: int = 5
    publication_authorized: bool = True
    flowkit_url: str = 'http://127.0.0.1:8100'
    social_profile: str = 'thoremix-social'
    affiliate_mode: str = 'required'
    affiliate_profile_dir: str = ''
    affiliate_queries: tuple[str, ...] = ('gia dụng', 'đồ dùng học tập', 'phụ kiện điện thoại')
    affiliate_max_price: int = 200000
    affiliate_min_sold: int = 1000
    ai_provider: str = 'gpt_fullproxy'
    mask_enabled: bool = True
    mask_top_percent: float = 11
    mask_bottom_percent: float = 12
    laugh_enabled: bool = False
    laugh_path: str = ''
    laugh_volume: float = 0.8
    schema_version: int = 1

    @property
    def directory(self) -> Path:
        from agent.private_runtime import current_runtime
        runtime = current_runtime()
        if runtime is not None:
            root = runtime.data_path(self.root)
            if (root != runtime.home
                    or (runtime.consumer_kind, runtime.consumer_name) != ("app", "thoremix")):
                raise ValueError("THOREMIX_INSTANCE_MISMATCH")
            return root
        return Path(self.root).resolve()

    @property
    def data(self) -> Path:
        return self.directory / 'data'

    @property
    def output(self) -> Path:
        from agent.private_runtime import current_runtime
        runtime = current_runtime()
        if runtime is not None:
            return runtime.data_path(self.directory / "output")
        return Path(self.input_dir).resolve() / 'video'

    @property
    def path(self) -> Path:
        return self.directory / 'config' / 'settings.json'

    def validate(self) -> None:
        from agent.private_runtime import current_runtime
        runtime = current_runtime()
        if runtime is not None:
            self.directory  # Validate instance identity without changing settings.
            if self.affiliate_profile_dir:
                runtime.profile("affiliate", self.affiliate_profile_dir)
        from datetime import time
        from zoneinfo import ZoneInfo

        if self.schema_version != 1 or not Path(self.root).is_absolute() or not Path(self.input_dir).is_absolute():
            raise ValueError('Cấu hình thư mục hoặc phiên bản không hợp lệ.')
        if not self.slots or len(self.slots) != len(set(self.slots)):
            raise ValueError('Lịch chạy phải có các giờ riêng biệt.')
        for slot in self.slots:
            if time.fromisoformat(slot).strftime('%H:%M') != slot:
                raise ValueError('Giờ chạy phải có dạng HH:MM.')
        ZoneInfo(self.timezone)
        if self.production_mode not in {'scheduled', 'ahead'}:
            raise ValueError('Chế độ sản xuất không hợp lệ.')
        if type(self.daily_production_limit) is not int or not 1 <= self.daily_production_limit <= 1000:
            raise ValueError('Hạn mức phải là số nguyên từ 1 đến 1000 clip hoàn thành mỗi ngày.')
        parsed = urlsplit(self.flowkit_url)
        if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.username:
            raise ValueError('FlowKit phải là dịch vụ localhost.')
        if self.affiliate_mode != 'required':
            raise ValueError('Chiến dịch này yêu cầu affiliate đầy đủ.')
        if self.ai_provider != 'gpt_fullproxy':
            raise ValueError('AI của Thỏ Remix chỉ sử dụng gpt_fullproxy.')
        if type(self.mask_enabled) is not bool or type(self.laugh_enabled) is not bool:
            raise ValueError('Bật/tắt xử lý video phải là true hoặc false.')
        if any(type(v) not in (float,int) or not 0 <= v <= 35
               for v in (self.mask_top_percent,self.mask_bottom_percent)):
            raise ValueError('Dải che trên/dưới phải từ 0 đến 35% chiều cao.')
        if type(self.laugh_volume) not in (float,int) or not 0 <= self.laugh_volume <= 2:
            raise ValueError('Âm lượng tiếng cười phải từ 0 đến 200%.')
        if self.laugh_enabled and (not self.laugh_path or not Path(self.laugh_path).is_absolute()):
            raise ValueError('Chọn đường dẫn tuyệt đối tới file tiếng cười.')
        if self.affiliate_profile_dir and not Path(self.affiliate_profile_dir).is_absolute():
            raise ValueError('Profile Affiliate phải là đường dẫn tuyệt đối.')
        if self.affiliate_max_price <= 0 or self.affiliate_min_sold < 1:
            raise ValueError('Giới hạn giá và lượng bán Affiliate không hợp lệ.')
        if not self.social_profile or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in self.social_profile):
            raise ValueError('Tên profile không hợp lệ.')

    def save(self) -> None:
        self.validate()
        atomic_json(self.path, asdict(self))

    @classmethod
    def load(cls, root: Path | str, *, create: bool = False) -> Settings:
        root = Path(root).resolve()
        path = root / 'config' / 'settings.json'
        if not path.exists():
            if not create:
                raise FileNotFoundError(path)
            settings = cls(root=str(root))
            settings.save()
        else:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            if Path(value['root']).resolve() != root:
                raise ValueError('Cấu hình thuộc một bản cài đặt khác.')
            value['slots'] = tuple(value['slots'])
            if 'affiliate_queries' in value:
                value['affiliate_queries'] = tuple(value['affiliate_queries'])
            settings = cls(**value)
        settings.validate()
        return settings


def change_settings(root, **changes):
    """Small control writes remain available while a production clip owns the runner."""
    from dataclasses import replace
    from .core import root_operation

    if set(changes) - {'enabled', 'production_mode', 'daily_production_limit','mask_enabled',
                      'mask_top_percent','mask_bottom_percent','laugh_enabled','laugh_path','laugh_volume'}:
        raise ValueError('Không hỗ trợ thay đổi cấu hình này.')
    with root_operation(Path(root).resolve() / 'config'):
        settings = replace(Settings.load(root), **changes)
        settings.save()
        return settings

