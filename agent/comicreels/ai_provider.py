"""OpenAI-backed ComicReels analysis and AI image generation."""
from __future__ import annotations

import base64
import json
import math
import os
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

from agent.comicreels.images import clamp_box, sha256_file


OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
VISION_MODEL = os.environ.get("COMICREELS_OPENAI_VISION_MODEL", "gpt-5.5")
IMAGE_MODEL = os.environ.get("COMICREELS_OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")


def provider_status() -> dict[str, Any]:
    return {
        "provider": "openai",
        "configured": bool(os.environ.get("OPENAI_API_KEY")),
        "vision_model": VISION_MODEL,
        "image_model": IMAGE_MODEL,
    }


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "Chưa cấu hình OPENAI_API_KEY cho ComicReels AI. "
            "Đăng nhập ChatGPT trên trình duyệt không tự cấp API key cho app local."
        )
    return {"Authorization": f"Bearer {key}"}


def _extract_output_text(payload: dict[str, Any]) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    texts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                value = part.get("text")
                if isinstance(value, str):
                    texts.append(value)
    if texts:
        return "\n".join(texts)
    raise RuntimeError("OpenAI analysis response không có output text.")


def _extract_json(text: str) -> dict[str, Any]:
    clean = text.strip()
    fence = chr(96) * 3
    if clean.startswith(fence):
        clean = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*" + re.escape(fence) + r"$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            raise RuntimeError("AI không trả JSON hợp lệ.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("AI analysis phải trả JSON object.")
    return value


async def analyze_comic(path: Path, mime: str, width: int, height: int) -> dict[str, Any]:
    data_url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
    prompt = f"""
Bạn là bộ phân tích truyện tranh cho ComicReels. Phân tích ảnh {width}x{height}px.
Trả DUY NHẤT JSON, không markdown.

Yêu cầu:
- Tự nhận toàn bộ panel theo thứ tự đọc.
- Chép NGUYÊN VĂN mọi lời thoại, giữ nguyên dấu câu/viết hoa/tiếng Việt.
- Gán speaker_id ổn định theo nhân vật, dựa vào đuôi bong bóng, vị trí và ngữ cảnh.
- Tự nhận vùng speech bubble, caption, chữ, watermark cần xóa trong từng panel.
- speech_regions là bbox TƯƠNG ĐỐI VỚI CROP PANEL.
- Bbox panel là tọa độ pixel ảnh nguồn.

Schema:
{{
  "panels": [
    {{
      "x":0,"y":0,"w":100,"h":100,"order":0,"confidence":0.99,
      "speech_regions":[{{"x":10,"y":10,"w":50,"h":30,"kind":"speech_bubble"}}]
    }}
  ],
  "dialogues":[
    {{"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"NGUYÊN VĂN","confidence":0.99}}
  ],
  "characters":[{{"speaker_id":"CHAR_1","description":"mô tả nhận diện"}}],
  "warnings":[]
}}
"""
    body = {
        "model": VISION_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url},
            ],
        }],
    }
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{OPENAI_BASE}/responses",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=body,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI analysis HTTP {response.status_code}: {response.text[:1000]}")
    result = _extract_json(_extract_output_text(response.json()))

    panels = sorted(result.get("panels") or [], key=lambda p: int(p.get("order", 0)))
    if not panels:
        raise RuntimeError("AI không nhận diện được panel nào.")
    normalized: list[dict[str, Any]] = []
    for panel in panels:
        safe = clamp_box(panel, width, height)
        regions: list[dict[str, int]] = []
        for region in panel.get("speech_regions") or []:
            try:
                regions.append(clamp_box(region, safe["w"], safe["h"]))
            except Exception:
                continue
        safe["mask"] = regions
        safe["confidence"] = panel.get("confidence")
        normalized.append(safe)
    result["panels"] = normalized
    return result


def _round16(value: float) -> int:
    return max(16, int(math.ceil(value / 16.0) * 16))


def prepare_edit_assets(
    crop_path: Path,
    regions: list[dict[str, int]],
    base_path: Path,
    mask_path: Path,
) -> tuple[dict[str, int], float]:
    with Image.open(crop_path) as src:
        original = src.convert("RGBA")
        source_w, source_h = original.size

        target_w = _round16(max(source_w, 1024))
        target_h = _round16(target_w * 16 / 9)
        if target_h > 3840:
            target_h = 3840
            target_w = _round16(target_h * 9 / 16)

        scale = min(1.0, target_w / source_w, target_h / source_h)
        placed = original if scale == 1.0 else original.resize(
            (max(1, int(source_w * scale)), max(1, int(source_h * scale))),
            Image.Resampling.LANCZOS,
        )
        left = (target_w - placed.width) // 2
        top = (target_h - placed.height) // 2

        base = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 0))
        base.alpha_composite(placed, (left, top))
        base_path.parent.mkdir(parents=True, exist_ok=True)
        base.save(base_path, "PNG")

        preserve = Image.new("L", (target_w, target_h), 0)
        draw = ImageDraw.Draw(preserve)
        draw.rectangle((left, top, left + placed.width - 1, top + placed.height - 1), fill=255)
        pad = max(8, int(min(source_w, source_h) * 0.012))
        for raw in regions:
            safe = clamp_box(raw, source_w, source_h)
            x0 = max(0, safe["x"] - pad)
            y0 = max(0, safe["y"] - pad)
            x1 = min(source_w, safe["x"] + safe["w"] + pad)
            y1 = min(source_h, safe["y"] + safe["h"] + pad)
            draw.rectangle((
                left + int(x0 * scale),
                top + int(y0 * scale),
                left + int(x1 * scale),
                top + int(y1 * scale),
            ), fill=0)

        mask = Image.new("RGBA", (target_w, target_h), (255, 255, 255, 255))
        mask.putalpha(preserve)
        mask.save(mask_path, "PNG")
    return {"x": left, "y": top, "w": placed.width, "h": placed.height}, scale


async def generate_clean_portrait(
    crop_path: Path,
    regions: list[dict[str, int]],
    output_path: Path,
    *,
    panel_context: str = "",
) -> tuple[Path, dict[str, int], str]:
    if not regions:
        raise RuntimeError("AI chưa xác định vùng chữ/bong bóng. Hãy chạy AI phân tích trước.")

    work = output_path.parent
    base_path = work / "ai-base.png"
    mask_path = work / "ai-mask.png"
    raw_path = work / "ai-raw.png"
    protected, _scale = prepare_edit_assets(crop_path, regions, base_path, mask_path)

    prompt = f"""
Edit this comic panel into a finished vertical 9:16 video background.
Preserve exact character designs, faces, expressions, proportions, props, line art, palette and visual style.
Remove all speech bubbles, text, captions and bubble tails inside editable regions.
Reconstruct hidden artwork naturally where text/bubbles covered the scene.
Outpaint only the empty areas needed for 9:16. Do not crop any original character or important prop.
Do not add characters, text, logos, subtitles, watermarks or speech bubbles.
Keep the story moment and spatial relationships unchanged.
Unmasked source artwork is reference-locked and must stay visually identical.
{panel_context}
"""
    with Image.open(base_path) as prepared:
        requested_size = f"{prepared.width}x{prepared.height}"
    files = [
        ("image[]", ("panel-9x16-base.png", base_path.read_bytes(), "image/png")),
        ("mask", ("panel-9x16-mask.png", mask_path.read_bytes(), "image/png")),
    ]
    data = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "quality": "high",
        "size": requested_size,
        "output_format": "png",
    }
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{OPENAI_BASE}/images/edits",
            headers=_auth_headers(),
            data=data,
            files=files,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"OpenAI image edit HTTP {response.status_code}: {response.text[:1200]}")
    items = response.json().get("data") or []
    if not items:
        raise RuntimeError("OpenAI image edit không trả ảnh.")
    item = items[0]
    if isinstance(item.get("b64_json"), str) and item["b64_json"]:
        raw = base64.b64decode(item["b64_json"])
    elif isinstance(item.get("url"), str) and item["url"]:
        async with httpx.AsyncClient(timeout=120) as client:
            image_response = await client.get(item["url"])
            image_response.raise_for_status()
            raw = image_response.content
    else:
        raise RuntimeError("OpenAI image edit không có b64_json hoặc URL.")

    raw_path.write_bytes(raw)
    with Image.open(raw_path) as generated:
        result = generated.convert("RGB")
        with Image.open(base_path) as base:
            base_rgba = base.convert("RGBA")
        with Image.open(mask_path) as mask_im:
            preserve_mask = mask_im.getchannel("A")
        if result.size != base_rgba.size:
            result = result.resize(base_rgba.size, Image.Resampling.LANCZOS)

        source_rgb = Image.new("RGB", base_rgba.size, (255, 255, 255))
        source_rgb.paste(base_rgba.convert("RGB"), (0, 0), base_rgba.getchannel("A"))
        result.paste(source_rgb, (0, 0), preserve_mask)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(output_path, "PNG")

    return output_path, protected, sha256_file(output_path)
