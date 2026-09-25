"""Optional vision analysis. Local layout detection remains available without an API key."""
from __future__ import annotations
import base64
import json
import re
from pathlib import Path
from anthropic import AsyncAnthropic
from agent.config import ANTHROPIC_API_KEY, REVIEW_MODEL

def _json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(text[start:end+1])
            return data if isinstance(data, dict) else {}
        raise

async def analyze_comic(path: str | Path, width: int, height: int) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY chưa được cấu hình; dùng detector local và nhập thoại thủ công.")
    raw = Path(path).read_bytes()
    mime = "image/png"
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    prompt = f"""
Bạn là bộ phân tích truyện tranh cho ComicReels. Ảnh có kích thước {width}x{height}px.
Trả về JSON THUẦN, không markdown, schema:
{{
  "panels":[{{
    "display_order":0,
    "bbox":{{"x":0,"y":0,"width":100,"height":100}},
    "confidence":0.0,
    "dialogues":[{{
      "sequence":0,
      "speaker_key":"character-1",
      "speaker_name":"Tên nhân vật nếu biết",
      "verbatim_text":"CHÉP NGUYÊN VĂN 100%, giữ dấu và dấu câu",
      "bbox":{{"x":0,"y":0,"width":10,"height":10}},
      "confidence":0.0
    }}]
  }}],
  "characters":[{{"stable_key":"character-1","name":"Tên/nhãn ngắn","description":"đặc điểm nhận diện trong chính ảnh"}}],
  "reading_note":"mô tả ngắn"
}}
Quy tắc: bbox panel và dialogue dùng tọa độ tuyệt đối toàn ảnh.
Không tự sửa chính tả, không dịch, không thêm hoặc bỏ lời thoại. Nếu không chắc người nói, speaker_key=null và confidence thấp.
Chỉ mô tả nhân vật từ ảnh, không sáng tác tuyến nhân vật mới.
"""
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=REVIEW_MODEL,
        max_tokens=5000,
        temperature=0,
        messages=[{
            "role":"user",
            "content":[
                {"type":"image","source":{"type":"base64","media_type":mime,"data":base64.b64encode(raw).decode()}},
                {"type":"text","text":prompt},
            ],
        }],
    )
    text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
    data = _json_object(text)
    if not isinstance(data.get("panels"), list):
        raise RuntimeError("Vision không trả danh sách panels hợp lệ")
    return data
