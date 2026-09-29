"""Runtime proof that finishing keeps the native audio track.

This module never decides what speech should be removed.  It only compares the
already selected clean/native input with the finished output and rejects a
render when an audible pre-laugh region no longer contains the native signal.
"""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import subprocess
import sys

from .core import media_tool

RATE = 16000


def decode_pcm(settings, path: Path, *, rate: int = RATE) -> array:
    path = Path(path).resolve(strict=True)
    result = subprocess.run(
        [media_tool('ffmpeg', settings.directory), '-nostdin', '-v', 'error',
         '-i', str(path), '-map', '0:a:0', '-vn', '-ac', '1', '-ar', str(rate),
         '-f', 's16le', '-'],
        capture_output=True, timeout=120,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    if result.returncode or len(result.stdout) < 2:
        raise ValueError('AUDIO_STREAM_REQUIRED')
    samples = array('h')
    samples.frombytes(result.stdout)
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples


def signal_stats(samples) -> dict:
    count = len(samples)
    if not count:
        return {'samples': 0, 'peak': 0, 'rms': 0.0, 'all_zero': True}
    peak = max(abs(value) for value in samples)
    energy = sum(float(value) * float(value) for value in samples)
    return {'samples': count, 'peak': peak, 'rms': math.sqrt(energy / count),
            'all_zero': peak == 0}


def _fit(source, output) -> dict:
    count = min(len(source), len(output))
    if count <= 0:
        return {'samples': 0, 'gain': None, 'correlation': None}
    source = source[:count]
    output = output[:count]
    xx = sum(float(x) * float(x) for x in source)
    yy = sum(float(y) * float(y) for y in output)
    xy = sum(float(x) * float(y) for x, y in zip(source, output))
    if xx <= 0 or yy <= 0:
        return {'samples': count, 'gain': None, 'correlation': None}
    return {'samples': count, 'gain': xy / xx,
            'correlation': xy / math.sqrt(xx * yy)}


def verify_native_audio(settings, source: Path, output: Path, *, laugh_start_s: float | None = None) -> dict:
    """Reject a finished render that drops an audible native pre-laugh signal.

    AAC re-encoding is allowed, so the check is signal based rather than byte
    based.  When the native track is genuinely silent before the laugh starts,
    the receipt records that limitation instead of inventing evidence.
    """
    native = decode_pcm(settings, source)
    finished = decode_pcm(settings, output)
    native_stats = signal_stats(native)
    finished_stats = signal_stats(finished)
    if native_stats['all_zero']:
        return {'native': native_stats, 'output': finished_stats,
                'checked_region': 'native_track_silent', 'preserved': True}

    end = min(len(native), len(finished))
    region = 'full_track'
    if laugh_start_s is not None:
        end = min(end, max(0, int((float(laugh_start_s) - 0.08) * RATE)))
        region = 'before_laugh'
    if end < RATE // 5 or signal_stats(native[:end])['all_zero']:
        # No clean comparison window exists.  At minimum the final file must
        # still contain audio; the mixer regression is covered separately by
        # deterministic unit tests.
        if finished_stats['all_zero']:
            raise ValueError('NATIVE_AUDIO_DROPPED')
        return {'native': native_stats, 'output': finished_stats,
                'checked_region': 'no_audible_pre_laugh_window',
                'preserved': True, 'fit': None}

    fit = _fit(native[:end], finished[:end])
    if (fit['gain'] is None or fit['correlation'] is None
            or not 0.75 <= fit['gain'] <= 1.25 or fit['correlation'] < 0.90):
        raise ValueError('NATIVE_AUDIO_NOT_PRESERVED')
    return {'native': native_stats, 'output': finished_stats,
            'checked_region': region, 'preserved': True, 'fit': fit}
