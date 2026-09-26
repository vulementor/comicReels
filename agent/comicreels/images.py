"""Deterministic image operations for ComicReels.

The safe default never redraws protected source pixels. AI inpaint/outpaint can
be added later behind masks, but the compositor always has a local fallback.
"""
from __future__ import annotations

import hashlib
import io
import math
import zipfile
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageStat, UnidentifiedImageError


ALLOWED_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_DIMENSION = 16000


class ImageValidationError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_image(data: bytes, mime: str) -> tuple[int, int, str]:
    if mime not in ALLOWED_MIME:
        raise ImageValidationError("Chỉ hỗ trợ PNG, JPG/JPEG hoặc WebP.")
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise ImageValidationError("Ảnh nguồn phải từ 1 byte đến 30 MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as im:
            width, height = im.size
            actual = (im.format or "").upper()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError("Tệp không phải ảnh hợp lệ.") from exc
    expected = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[mime]
    if actual != expected:
        raise ImageValidationError(f"MIME khai báo là {mime} nhưng dữ liệu là {actual or 'không xác định'}.")
    if width < 16 or height < 16 or width > MAX_DIMENSION or height > MAX_DIMENSION:
        raise ImageValidationError("Kích thước ảnh không hợp lệ hoặc vượt giới hạn an toàn.")
    return width, height, expected


def save_source(data: bytes, mime: str, directory: Path) -> tuple[Path, int, int, str]:
    width, height, _ = validate_image(data, mime)
    directory.mkdir(parents=True, exist_ok=True)
    digest = sha256_bytes(data)
    path = directory / f"source{ALLOWED_MIME[mime]}"
    path.write_bytes(data)
    return path, width, height, digest


def _runs(values: list[bool], min_len: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    start: int | None = None
    for i, value in enumerate(values + [False]):
        if value and start is None:
            start = i
        elif not value and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def _gutter_splits(im: Image.Image, axis: str) -> list[int]:
    gray = im.convert("L")
    width, height = gray.size
    pix = gray.load()
    length = height if axis == "row" else width
    cross = width if axis == "row" else height
    sample_step = max(1, cross // 700)
    flags: list[bool] = []
    for pos in range(length):
        vals = [pix[x, pos] if axis == "row" else pix[pos, x] for x in range(0, cross, sample_step)]
        if not vals:
            flags.append(False)
            continue
        bright = sum(v >= 245 for v in vals) / len(vals)
        dark = sum(v <= 10 for v in vals) / len(vals)
        flags.append(bright >= 0.94 or dark >= 0.97)
    min_len = max(3, int(length * 0.004))
    runs = _runs(flags, min_len)
    edge = max(4, int(length * 0.03))
    mids = [int((a + b) / 2) for a, b in runs if a > edge and b < length - edge]
    # Prevent dozens of splits created by white speech bubbles: keep at most the
    # strongest structural candidates with minimum panel size.
    mids.sort()
    filtered: list[int] = []
    minimum = max(20, int(length * 0.12))
    last = 0
    for mid in mids:
        if mid - last >= minimum:
            filtered.append(mid)
            last = mid
        if len(filtered) >= 5:
            break
    if filtered and length - filtered[-1] < minimum:
        filtered.pop()
    return filtered


def detect_panels(path: Path) -> list[dict[str, int]]:
    """Conservative gutter detector.

    It intentionally returns one panel when no structural gutters are found.
    The UI/API supports manual boxes and optional vision analysis for irregular
    comic pages.
    """
    with Image.open(path) as src:
        im = src.convert("RGB")
        width, height = im.size
        xs = [0, *_gutter_splits(im, "col"), width]
        ys = [0, *_gutter_splits(im, "row"), height]
    boxes: list[dict[str, int]] = []
    for y0, y1 in zip(ys, ys[1:]):
        for x0, x1 in zip(xs, xs[1:]):
            w, h = x1 - x0, y1 - y0
            if w >= max(20, width // 10) and h >= max(20, height // 10):
                boxes.append({"x": x0, "y": y0, "w": w, "h": h})
    return boxes[:16] or [{"x": 0, "y": 0, "w": width, "h": height}]


def clamp_box(box: dict[str, int], width: int, height: int) -> dict[str, int]:
    x = max(0, min(int(box["x"]), width - 1))
    y = max(0, min(int(box["y"]), height - 1))
    w = max(1, min(int(box["w"]), width - x))
    h = max(1, min(int(box["h"]), height - y))
    return {"x": x, "y": y, "w": w, "h": h}


def crop_panel(source: Path, box: dict[str, int], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        safe = clamp_box(box, *im.size)
        cropped = im.crop((safe["x"], safe["y"], safe["x"] + safe["w"], safe["y"] + safe["h"]))
        cropped.save(output, format="PNG")
    return output


def _border_color(im: Image.Image, rect: tuple[int, int, int, int]) -> tuple[int, int, int]:
    x0, y0, x1, y1 = rect
    samples: list[Image.Image] = []
    if y0 > 0:
        samples.append(im.crop((x0, max(0, y0 - 3), x1, y0)))
    if y1 < im.height:
        samples.append(im.crop((x0, y1, x1, min(im.height, y1 + 3))))
    if x0 > 0:
        samples.append(im.crop((max(0, x0 - 3), y0, x0, y1)))
    if x1 < im.width:
        samples.append(im.crop((x1, y0, min(im.width, x1 + 3), y1)))
    if not samples:
        return (255, 255, 255)
    strip = Image.new("RGB", (sum(s.width for s in samples), max(s.height for s in samples)), "white")
    x = 0
    for sample in samples:
        strip.paste(sample.convert("RGB"), (x, 0))
        x += sample.width
    mean = ImageStat.Stat(strip).mean[:3]
    return tuple(int(v) for v in mean)


def clean_with_rect_masks(crop: Path, rects: Iterable[dict[str, int]], output: Path) -> tuple[Path, list[dict[str, int]]]:
    """Local privacy-safe fallback.

    Rectangles are filled with mean edge colour. This is intentionally simple;
    it preserves every pixel outside the rectangles exactly. A future masked
    inpaint provider can replace only the masked pixels without changing this
    invariant.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(crop) as src:
        im = src.convert("RGB")
        applied: list[dict[str, int]] = []
        for raw in rects:
            safe = clamp_box(raw, im.width, im.height)
            x0, y0 = safe["x"], safe["y"]
            x1, y1 = x0 + safe["w"], y0 + safe["h"]
            colour = _border_color(im, (x0, y0, x1, y1))
            patch = Image.new("RGB", (safe["w"], safe["h"]), colour)
            im.paste(patch, (x0, y0))
            applied.append(safe)
        im.save(output, format="PNG")
    return output, applied


def portrait_9_16(source: Path, output: Path) -> tuple[Path, dict[str, int], str]:
    """Put source pixels unchanged on the smallest integer 9:16 canvas."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as src:
        im = src.convert("RGB")
        k = max(math.ceil(im.width / 9), math.ceil(im.height / 16))
        target_w, target_h = 9 * k, 16 * k
        edge = ImageStat.Stat(im.resize((1, 1))).mean[:3]
        colour = tuple(int(v) for v in edge)
        canvas = Image.new("RGB", (target_w, target_h), colour)
        left = (target_w - im.width) // 2
        top = (target_h - im.height) // 2
        canvas.paste(im, (left, top))
        canvas.save(output, format="PNG")
    protected = {"x": left, "y": top, "w": im.width, "h": im.height}
    return output, protected, sha256_file(output)


def build_backup(project_dir: Path, manifest: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    import json
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for path in project_dir.rglob("*"):
            if path.is_file() and path != output:
                zf.write(path, path.relative_to(project_dir))
    return output
