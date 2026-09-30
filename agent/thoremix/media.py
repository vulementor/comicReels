"""Resolve owned media tools without modifying the caller's environment."""
import os
import shutil
from pathlib import Path

from agent.private_runtime import current_runtime


def media_tool(name: str, root: Path | None = None) -> str:
    if name not in {'ffmpeg', 'ffprobe'}:
        raise ValueError('Unknown media tool')
    runtime = current_runtime()
    if runtime is not None:
        return str(runtime.tool(name))
    if root is not None:
        bundled = Path(root).resolve() / 'runtime' / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        if bundled.is_file():
            return str(bundled)
    # Development callers may use explicitly configured PATH tools when there is
    # no installed bundle. An installed tool always wins over an ambient copy.
    fallback = shutil.which(name)
    if fallback:
        return fallback
    raise RuntimeError(f'{name} is required for media validation')
