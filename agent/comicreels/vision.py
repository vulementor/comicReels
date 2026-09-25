"""Optional Vision analysis for irregular comics.

Disabled unless ANTHROPIC_API_KEY is configured and the caller explicitly asks
for mode=vision. The source image leaves the local machine in that mode, so the
UI must disclose it.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("Vision provider không trả JSON.")
    return json.loads(match.group(0))


async def analyze(path: Path, mime: str, width: int, height: int) -> dict[str, Any]:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("Thiếu ANTHROPIC_API_KEY. Dùng heuristic/manual hoặc cấu hình provider trước.")
    model = os.environ.get("COMICREELS_VISION_MODEL", "claude-haiku-4-5-20251001")
    image_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    prompt = f"""
Phân tích trang truyện tranh {width}x{height}px. Trả DUY NHẤT JSON.
Không dịch, không sửa, không thêm hoặc rút gọn lời thoại. BBox tính theo pixel ảnh gốc.
Thứ tự đọc Việt Nam/Latin: trên xuống, trái sang phải, nhưng ưu tiên mạch truyện trực quan.
Mỗi character phải có speaker_id ổn định trong toàn ảnh. Nếu không chắc speaker dùng UNKNOWN và confidence thấp.
Schema:
{{
  "panels":[{{"x":0,"y":0,"w":100,"h":100,"order":0,"confidence":0.0}}],
  "dialogues":[{{"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"nguyên văn","confidence":0.0}}],
  "characters":[{{"speaker_id":"CHAR_1","description":"mô tả nhận diện ngắn"}}],
  "warnings":["..."]
}}
"""
    client = AsyncAnthropic(api_key=key)
    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        temperature=0,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": image_b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = "".join(getattr(part, "text", "") for part in response.content)
    return _extract_json(text)
