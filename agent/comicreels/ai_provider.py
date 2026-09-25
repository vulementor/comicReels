"""Browser-native ChatGPT provider for ComicReels via GPT FullProxy.

This adapter deliberately does not use OpenAI API keys. It reuses an authenticated
ChatGPT Web browser identity through the public gpt_fullproxy Python SDK.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from agent.comicreels.images import clamp_box, sha256_file


_PROVIDER = "gpt_fullproxy"
_PROFILE_NAME = os.environ.get("COMICREELS_GPTFP_PROFILE", "zaloconnect-chatgpt")
_VISIBLE = os.environ.get("COMICREELS_GPTFP_VISIBLE", "1").strip().lower() not in {
    "0", "false", "no", "off",
}


def _default_profile_dir() -> Path | None:
    explicit = (os.environ.get("COMICREELS_GPTFP_PROFILE_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    mac_default = (
        Path.home()
        / "Library"
        / "Application Support"
        / "ZaloConnect"
        / "chatgpt-web-profile"
    )
    return mac_default.resolve() if mac_default.exists() else None


def _home_dir() -> Path:
    explicit = (os.environ.get("COMICREELS_GPTFP_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path.home() / ".cache" / "comicreels" / "gpt_fullproxy").resolve()


def _downloads_dir() -> Path:
    explicit = (os.environ.get("COMICREELS_GPTFP_DOWNLOADS_DIR") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (_home_dir() / "downloads").resolve()


def _sdk_available() -> bool:
    return importlib.util.find_spec("gpt_fullproxy") is not None


def provider_status() -> dict[str, Any]:
    profile_dir = _default_profile_dir()
    return {
        "provider": _PROVIDER,
        "configured": bool(_sdk_available() and profile_dir and profile_dir.is_dir()),
        "sdk_available": _sdk_available(),
        "profile_name": _PROFILE_NAME,
        "profile_dir": str(profile_dir) if profile_dir else None,
        "profile_exists": bool(profile_dir and profile_dir.is_dir()),
        "visible": _VISIBLE,
        # Keep these compatibility fields for the current dashboard contract.
        "vision_model": "ChatGPT Web",
        "image_model": "ChatGPT Create image",
    }


def _client():
    if not _sdk_available():
        raise RuntimeError(
            "Chưa cài gpt_fullproxy SDK. Cài repo vulementor/gpt_fullproxy với extra [browser]."
        )
    profile_dir = _default_profile_dir()
    if profile_dir is None or not profile_dir.is_dir():
        raise RuntimeError(
            "Không tìm thấy profile ChatGPT. Cấu hình COMICREELS_GPTFP_PROFILE_DIR "
            "hoặc dùng profile ZaloConnect/chatgpt-web-profile trên macOS."
        )
    from gpt_fullproxy import GPTFullProxy

    home = _home_dir()
    home.mkdir(parents=True, exist_ok=True)
    downloads = _downloads_dir()
    downloads.mkdir(parents=True, exist_ok=True)
    # GPT FullProxy owns the physical-profile lock. ComicReels never reads cookies,
    # tokens or browser storage directly.
    return GPTFullProxy(
        profile=_PROFILE_NAME,
        profile_dir=profile_dir,
        home=home,
        visible=_VISIBLE,
    )


def _extract_json(text: str) -> dict[str, Any]:
    clean = (text or "").strip()
    fence = chr(96) * 3
    if clean.startswith(fence):
        clean = re.sub(r"^" + re.escape(fence) + r"(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*" + re.escape(fence) + r"$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            raise RuntimeError("ChatGPT không trả JSON hợp lệ.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise RuntimeError("ChatGPT analysis phải trả JSON object.")
    return value


def _analysis_prompt(width: int, height: int) -> str:
    return f"""
Bạn là bộ phân tích truyện tranh cho ComicReels. Phân tích chính xác ảnh đính kèm
kích thước {width}x{height}px. Trả DUY NHẤT JSON, không markdown.

Yêu cầu bắt buộc:
- Tự nhận toàn bộ panel theo thứ tự đọc.
- Chép NGUYÊN VĂN mọi lời thoại, giữ nguyên dấu câu, viết hoa và tiếng Việt.
- Gán speaker_id ổn định theo nhân vật bằng đuôi bong bóng, vị trí và ngữ cảnh.
- Tự nhận mọi vùng speech bubble, caption, chữ và watermark cần xóa trong từng panel.
- speech_regions là bbox TƯƠNG ĐỐI VỚI CROP PANEL.
- bbox panel là tọa độ pixel trên toàn ảnh nguồn.
- Không dịch, không viết lại, không tự thêm lời.

Schema:
{{
  "panels": [
    {{
      "x": 0, "y": 0, "w": 100, "h": 100, "order": 0,
      "confidence": 0.99,
      "speech_regions": [
        {{"x": 10, "y": 10, "w": 50, "h": 30, "kind": "speech_bubble"}}
      ]
    }}
  ],
  "dialogues": [
    {{
      "panel_index": 0, "display_order": 0,
      "speaker_id": "CHAR_1", "text": "NGUYÊN VĂN",
      "confidence": 0.99
    }}
  ],
  "characters": [
    {{"speaker_id": "CHAR_1", "description": "mô tả ngắn để nhận diện nhất quán"}}
  ],
  "warnings": []
}}
""".strip()




async def analyze_comic(path: Path, mime: str, width: int, height: int) -> dict[str, Any]:
    del mime  # ChatGPT Web infers the uploaded file type from the attachment.
    client = _client()
    prompt = _analysis_prompt(width, height)

    result = await asyncio.to_thread(
        client.chat.send,
        prompt,
        attachments=[path],
        visible=_VISIBLE,
    )
    if result.state != "verified" or not result.text:
        raise RuntimeError(
            f"GPT FullProxy analysis chưa xác minh: {result.state}: {result.reason or 'không có reply'}"
        )

    parsed = _extract_json(result.text)
    panels = sorted(parsed.get("panels") or [], key=lambda item: int(item.get("order", 0)))
    if not panels:
        raise RuntimeError("ChatGPT không nhận diện được panel nào.")

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

    parsed["panels"] = normalized
    parsed["dialogues"] = [dict(item) for item in (parsed.get("dialogues") or []) if isinstance(item, dict)]
    for item in parsed["dialogues"]:
        item["verified"] = False
    warnings = [str(item) for item in (parsed.get("warnings") or [])]
    warnings.append(
        "Transcript là kết quả một lượt trong cùng conversation; hãy review nếu câu thoại quan trọng tuyệt đối."
    )
    parsed["warnings"] = warnings
    parsed["provider_receipt"] = {
        "provider": _PROVIDER,
        "conversation_url": result.conversation_url,
        "assistant_message_id": result.assistant_message_id,
        "attachments": [
            {
                "name": item.name,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
            }
            for item in result.attachment_receipts
        ],
    }
    return parsed


def _image_prompt(
    regions: list[dict[str, int]],
    panel_context: str,
    panel_index: int,
) -> str:
    region_text = ", ".join(
        f"(x={r['x']},y={r['y']},w={r['w']},h={r['h']})" for r in regions
    ) or "các speech bubble/text nhìn thấy trong ảnh"
    return f"""
Dùng CHÍNH ảnh nguồn đã được upload ở TURN ĐẦU của conversation này làm reference bắt buộc.
Không yêu cầu upload lại ảnh và không dùng ảnh từ conversation khác.

Chỉ xử lý KHUNG {panel_index + 1} của ảnh nguồn.
Tạo lại riêng cảnh của khung đó thành ảnh dọc 9:16 hoàn chỉnh dùng cho video.

BẮT BUỘC:
- Giữ nguyên tuyệt đối thiết kế nhân vật, khuôn mặt, biểu cảm, tỷ lệ cơ thể,
  trang phục, đạo cụ, nét vẽ, palette và phong cách minh họa của ảnh gốc.
- Xóa toàn bộ chữ, speech bubble, caption và đuôi bong bóng.
- Các vùng AI đã nhận cần xóa: {region_text}.
- Tái tạo tự nhiên phần nền/nhân vật vốn bị bong bóng hoặc chữ che mất.
- Outpaint phần còn thiếu để thành bố cục dọc 9:16, không dùng khung trắng/padding.
- Không cắt mất nhân vật hoặc đạo cụ quan trọng.
- Không thêm nhân vật mới.
- Không thêm chữ, subtitle, logo, watermark hoặc speech bubble.
- Giữ đúng khoảnh khắc truyện và quan hệ vị trí giữa các nhân vật.
- Kết quả phải là MỘT ảnh 9:16 sạch, không phải collage hay before/after.

{panel_context}
""".strip()


async def generate_clean_portrait(
    crop_path: Path,
    regions: list[dict[str, int]],
    output_path: Path,
    *,
    conversation_url: str,
    panel_index: int,
    panel_context: str = "",
) -> tuple[Path, dict[str, int], str]:
    if not crop_path.is_file():
        raise RuntimeError("Không tìm thấy crop panel local để đối chiếu kết quả.")
    if not conversation_url:
        raise RuntimeError("Project chưa có ChatGPT conversation từ lần phân tích đầu.")
    if not regions:
        raise RuntimeError(
            "AI chưa xác định vùng chữ/bong bóng cho panel này. "
            "Hãy chạy AI phân tích hoặc sửa nhận diện trước."
        )

    client = _client()
    artifact_dir = output_path.parent / "gptfp-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    prompt = _image_prompt(regions, panel_context, panel_index)

    result = await asyncio.to_thread(
        client.image.generate,
        prompt,
        conversation=conversation_url,
        attachments=[],
        output_dir=artifact_dir,
        visible=_VISIBLE,
    )
    if result.state != "verified" or not result.output_path:
        raise RuntimeError(
            f"GPT FullProxy image chưa xác minh: {result.state}: {result.reason or 'không có artifact'}"
        )

    generated_path = Path(result.output_path).expanduser().resolve()
    if not generated_path.is_file():
        raise RuntimeError("GPT FullProxy trả artifact path nhưng file không tồn tại.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated_path, output_path)

    with Image.open(output_path) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise RuntimeError("Ảnh ChatGPT trả về có kích thước không hợp lệ.")
        ratio = width / height
        target = 9 / 16
        if abs(ratio - target) > 0.08:
            raise RuntimeError(
                f"ChatGPT trả ảnh {width}x{height}, chưa đạt tỷ lệ 9:16; "
                "không tự kéo/đệm ảnh để che lỗi."
            )
        protected = {"x": 0, "y": 0, "w": width, "h": height}

    return output_path, protected, sha256_file(output_path)
