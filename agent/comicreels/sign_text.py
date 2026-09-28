"""Preserve source writing separately from dialogue; overlay verified static signs.

No OCR guesses or scene detection happen here. An overlay requires source text and
an unobstructed stationary text box verified against the actual video frames.
Moving/perspective signs need a separately verified track, not a static fallback.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from fractions import Fraction

from PIL import ImageFont

PRESERVED_KINDS = frozenset({'signage', 'prop_text', 'narrative_caption'})
REMOVED_KINDS = frozenset({'speech_bubble', 'dialogue_caption', 'watermark'})


def normalize_panel_text_regions(panel: dict) -> dict:
    """Fail safe on legacy/ambiguous text: keep it visible and flag source review."""
    result = dict(panel)
    removed, preserved, warnings = [], [], list(panel.get('text_warnings') or [])
    for row in [*(panel.get('speech_regions') or []), *(panel.get('text_regions') or [])]:
        if not isinstance(row, dict):
            warnings.append('TEXT_REGION_INVALID_REQUIRES_SOURCE_REVIEW')
            continue
        region = dict(row)
        kind = str(region.get('kind') or '').strip().lower()
        if kind in REMOVED_KINDS:
            region['kind'] = kind
            removed.append(region)
        else:
            if kind not in PRESERVED_KINDS:
                region['source_kind'] = kind
                kind = 'unclassified'
                warnings.append('TEXT_REGION_UNCLASSIFIED_REQUIRES_SOURCE_REVIEW')
            region['kind'] = kind
            preserved.append(region)
    result.update(speech_regions=removed, text_regions=preserved,
                  text_warnings=list(dict.fromkeys(warnings)))
    return result


def validate_overlay(spec: dict) -> dict:
    if spec.get('kind') not in PRESERVED_KINDS:
        raise ValueError('SIGN_OVERLAY_KIND_INVALID')
    if spec.get('source_verified') is not True or spec.get('geometry_verified') is not True:
        raise ValueError('SIGN_OVERLAY_UNVERIFIED')
    if not isinstance(spec.get('evidence'), str) or not spec['evidence'].strip():
        raise ValueError('SIGN_OVERLAY_EVIDENCE_REQUIRED')
    text = spec.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError('SIGN_OVERLAY_TEXT_INVALID')
    if any(ord(c) < 32 and c != '\n' for c in text) or any(not line.strip() for line in text.split('\n')):
        raise ValueError('SIGN_OVERLAY_TEXT_INVALID')
    for key in ('source_sha256', 'video_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(spec.get(key, ''))):
            raise ValueError('SIGN_OVERLAY_HASH_INVALID')
    for key in ('width', 'height', 'start_frame', 'end_frame'):
        if type(spec.get(key)) is not int:
            raise ValueError('SIGN_OVERLAY_GEOMETRY_INVALID')
    if not 0 <= spec['start_frame'] < spec['end_frame'] or min(spec['width'], spec['height']) < 1:
        raise ValueError('SIGN_OVERLAY_INTERVAL_INVALID')
    box = spec.get('box') or {}
    if any(type(box.get(k)) is not int for k in ('x', 'y', 'w', 'h')):
        raise ValueError('SIGN_OVERLAY_BOX_INVALID')
    if (min(box['x'], box['y']) < 0 or min(box['w'], box['h']) < 1
            or box['x'] + box['w'] > spec['width'] or box['y'] + box['h'] > spec['height']):
        raise ValueError('SIGN_OVERLAY_BOX_INVALID')
    fps = float(spec.get('fps', 24))
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError('SIGN_OVERLAY_FPS_INVALID')
    return dict(spec, box=dict(box), fps=fps)


def overlay_filters(spec: dict, directory: Path, font_path: Path) -> tuple[list[str], dict]:
    """FFmpeg reads UTF-8 files with expansion disabled; source text is never code."""
    spec = validate_overlay(spec)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    font_copy = directory / 'sign-font.ttf'
    shutil.copyfile(font_path, font_copy)
    box, lines = spec['box'], spec['text'].split('\n')
    size = min(96, box['h'] // len(lines))
    while size >= 12:
        font = ImageFont.truetype(str(font_copy), size)
        widths = [math.ceil(font.getlength(line)) for line in lines]
        ascent, descent = font.getmetrics()
        line_height = ascent + descent + max(4, size // 5)
        if max(widths) <= box['w'] and line_height * len(lines) <= box['h']:
            break
        size -= 1
    else:
        raise ValueError('SIGN_OVERLAY_TEXT_DOES_NOT_FIT')
    top = box['y'] + (box['h'] - line_height * len(lines)) // 2
    filters, layout = [], []
    for index, (line, width) in enumerate(zip(lines, widths)):
        textfile = directory / f'sign-line-{index}.txt'
        textfile.write_text(line, encoding='utf-8')
        y = top + index * line_height
        filters.append(
            f"drawtext=fontfile=sign-font.ttf:textfile={textfile.name}:expansion=none:"
            f"fontsize={size}:fontcolor=black:x={box['x']}+({box['w']}-text_w)/2:y={y}:"
            f"enable='gte(n,{spec['start_frame']})*lt(n,{spec['end_frame']})'"
        )
        layout.append({'textfile': str(textfile), 'width': width, 'y': y})
    return filters, {'font_size': size, 'line_height': line_height, 'lines': layout}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _run(args: list[str], **kwargs):
    return subprocess.run(args, check=True, capture_output=True, timeout=180, **kwargs)


def render_sign_text(source_video: Path, source_image: Path, output: Path, directory: Path,
                     spec: dict, *, ffmpeg: Path, ffprobe: Path, font: Path) -> dict:
    """Write a new local candidate plus receipt. Does not touch live package state."""
    spec = validate_overlay(spec)
    source_video, source_image, output = map(lambda p: Path(p).resolve(), (source_video, source_image, output))
    if output == source_video or output.exists():
        raise ValueError('SIGN_OVERLAY_OUTPUT_MUST_BE_NEW')
    if _sha256(source_video) != spec['video_sha256'] or _sha256(source_image) != spec['source_sha256']:
        raise ValueError('SIGN_OVERLAY_SOURCE_CHANGED')
    before = json.loads(_run([str(ffprobe), '-v', 'error', '-show_streams', '-of', 'json',
                             str(source_video)]).stdout)
    stream = next(s for s in before['streams'] if s['codec_type'] == 'video')
    fps = float(Fraction(stream['r_frame_rate']))
    if ((stream['width'], stream['height']) != (spec['width'], spec['height'])
            or abs(fps - spec['fps']) > 0.0001
            or abs(float(Fraction(stream['avg_frame_rate'])) - fps) > 0.0001
            or spec['end_frame'] > round(float(stream['duration']) * fps)):
        raise ValueError('SIGN_OVERLAY_VIDEO_GEOMETRY_CHANGED')
    filters, layout = overlay_filters(spec, directory, font)
    directory = Path(directory).resolve()
    filter_file = directory / 'sign-overlay.ffscript'
    filter_file.write_text(','.join(filters), encoding='utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    pending = output.with_name(output.stem + '.pending.mp4')
    if pending.exists():
        raise ValueError('SIGN_OVERLAY_PENDING_REQUIRES_RECONCILIATION')
    receipt = {'state': 'rendering', 'spec': spec, 'layout': layout, 'output': str(output),
               'pending': str(pending), 'font_sha256': _sha256(Path(font)), 'audio': 'stream_copy'}
    receipt_path = directory / 'sign-overlay-receipt.json'

    def record():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')

    record()
    try:
        _run([str(ffmpeg), '-v', 'error', '-n', '-i', str(source_video), '-filter_script:v',
              filter_file.name, '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'medium',
              '-crf', '16', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart',
              str(pending)], cwd=directory)
        _run([str(ffmpeg), '-v', 'error', '-xerror', '-i', str(pending), '-map', '0', '-f', 'null', '-'])
        if _sha256(source_video) != spec['video_sha256']:
            raise ValueError('SIGN_OVERLAY_SOURCE_CHANGED_DURING_RENDER')
        os.replace(pending, output)
        receipt.update(state='complete', full_decode=True, output_sha256=_sha256(output))
        record()
        return receipt
    except Exception as error:
        receipt.update(state='incomplete', error=str(error))
        record()
        raise
