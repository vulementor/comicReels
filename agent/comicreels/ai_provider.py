"""Browser-native ChatGPT provider for ComicReels via GPT FullProxy.

This adapter deliberately does not use OpenAI API keys. It reuses an authenticated
ChatGPT Web browser identity through the public gpt_fullproxy Python SDK.
"""
from __future__ import annotations

import asyncio
import hashlib
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
_DIALOGUE_VERIFY_REVISION = "v3"
_VISUAL_ANCHOR_REVISION = "v1"
_VISUAL_ANCHOR_VALIDATE_REVISION = "v1"
_IMAGE_GENERATION_REVISION = "v3-panel-crop-reconcile"
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
- Với MỖI panel, visual_anchor phải mô tả CHỈ những gì nhìn thấy trong chính panel đó:
  nhân vật nào xuất hiện, vị trí trái/phải/trước/sau, pose, hướng mặt/hướng nhìn,
  biểu cảm, khoảng cách tương đối, đạo cụ và framing. Không suy diễn cốt truyện.
- visual_anchor phải đủ cụ thể để phân biệt panel này với panel liền trước/liền sau.
- Không dịch, không viết lại, không tự thêm lời.

Schema:
{{
  "panels": [
    {{
      "x": 0, "y": 0, "w": 100, "h": 100, "order": 0,
      "confidence": 0.99,
      "visual_anchor": "mô tả hình học/pose/framing chỉ của panel này",
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




def _dialogue_verification_prompt(dialogues: list[dict[str, Any]]) -> str:
    rows = [
        {
            "panel_index": int(item.get("panel_index", 0)),
            "display_order": int(item.get("display_order", 0)),
            "speaker_id": str(item.get("speaker_id") or "UNKNOWN"),
            "text": str(item.get("text") or ""),
        }
        for item in dialogues
    ]
    return f"""
ComicReels dialogue verification revision: {_DIALOGUE_VERIFY_REVISION}
Dựa CHỈ vào ảnh nguồn đã upload ở TURN ĐẦU của chính conversation này.
KHÔNG yêu cầu upload lại ảnh, KHÔNG dùng ảnh từ chat khác.

Hãy đọc lại TOÀN BỘ lời thoại của mọi panel theo thứ tự đọc và kiểm tra từng ký tự.
Giữ nguyên panel_index, display_order và speaker_id của danh sách ứng viên bên dưới.
Chỉ sửa trường text nếu ảnh nguồn cho thấy ứng viên đọc sai.
Đặc biệt phân biệt chính xác Ô/Ơ/Ổ/Ỗ/Ộ, Ă/Â, Ê, Ư và mọi dấu tiếng Việt.
Không sửa chính tả theo ngữ cảnh, không dịch, không thêm bớt câu.

Ứng viên:
{json.dumps(rows, ensure_ascii=False)}

Trả DUY NHẤT JSON:
{{
  "dialogues": [
    {{
      "panel_index": 0,
      "display_order": 0,
      "speaker_id": "CHAR_1",
      "text": "NGUYÊN VĂN TRONG ẢNH"
    }}
  ]
}}
""".strip()


async def verify_dialogues_in_conversation(
    conversation_url: str,
    dialogues: list[dict[str, Any]],
    *,
    client=None,
) -> list[dict[str, Any]]:
    if not conversation_url:
        raise RuntimeError("Thiếu ChatGPT conversation URL để kiểm tra thoại.")
    if not dialogues:
        return []

    active_client = client or _client()
    prompt = _dialogue_verification_prompt(dialogues)
    payload = json.dumps(
        [
            {
                "panel_index": int(item.get("panel_index", 0)),
                "display_order": int(item.get("display_order", 0)),
                "speaker_id": str(item.get("speaker_id") or "UNKNOWN"),
                "text": str(item.get("text") or ""),
            }
            for item in dialogues
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(
        (conversation_url + "\n" + _DIALOGUE_VERIFY_REVISION + "\n" + payload).encode("utf-8")
    ).hexdigest()[:32]
    idempotency_key = f"comicreels-dialogue-verify-v3:{digest}"

    def _run():
        handle = active_client.chat.open(conversation_url)
        reply = handle.reply(
            text=prompt,
            idempotency_key=idempotency_key,
            visible=_VISIBLE,
        )
        if reply.state != "completed":
            raise RuntimeError(
                f"GPT FullProxy dialogue verify chưa hoàn tất: {reply.state}: {reply.reason or 'không có receipt'}"
            )
        if getattr(reply, "assistant_text", None):
            return str(reply.assistant_text)
        if reply.user_message is None:
            raise RuntimeError("GPT FullProxy dialogue verify thiếu cả assistant receipt và user receipt.")
        anchor = reply.user_message.provider_message_id
        if not anchor:
            raise RuntimeError("GPT FullProxy dialogue verify thiếu provider user-message id.")
        message = handle.wait_for_new_message(
            after_message_id=anchor,
            role="assistant",
            timeout=180.0,
            visible=_VISIBLE,
        )
        if message is None or not message.text:
            raise RuntimeError("ChatGPT không trả transcript verification trong thời gian chờ.")
        return message.text

    verified_text = await asyncio.to_thread(_run)
    parsed = _extract_json(verified_text)
    raw = parsed.get("dialogues")
    if not isinstance(raw, list):
        raise RuntimeError("ChatGPT dialogue verification thiếu mảng dialogues.")

    candidates = {
        (int(item.get("panel_index", 0)), int(item.get("display_order", 0))): item
        for item in dialogues
    }
    verified: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = (int(item.get("panel_index", -1)), int(item.get("display_order", -1)))
        current = candidates.get(key)
        if current is None:
            raise RuntimeError("ChatGPT dialogue verification đổi panel/order ngoài contract.")
        speaker_id = str(item.get("speaker_id") or "")
        if speaker_id != str(current.get("speaker_id") or ""):
            raise RuntimeError("ChatGPT dialogue verification đổi speaker_id ngoài contract.")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("ChatGPT dialogue verification trả text rỗng.")
        row = dict(current)
        row["text"] = text
        row["verified"] = True
        verified.append(row)

    if len(verified) != len(dialogues):
        raise RuntimeError(
            f"ChatGPT dialogue verification trả {len(verified)}/{len(dialogues)} câu; không áp dụng một phần."
        )
    return sorted(
        verified,
        key=lambda item: (int(item.get("panel_index", 0)), int(item.get("display_order", 0))),
    )


def _visual_anchor_prompt(
    panels: list[dict[str, Any]],
    *,
    source_width: int,
    source_height: int,
) -> str:
    rows = [
        {
            "panel_index": int(panel.get("panel_index", panel.get("display_order", 0))),
            "x": int(panel["x"]),
            "y": int(panel["y"]),
            "w": int(panel["w"]),
            "h": int(panel["h"]),
            "dialogues": [
                {
                    "speaker_id": str(item.get("speaker_id") or "UNKNOWN"),
                    "text": str(item.get("text") or ""),
                }
                for item in (panel.get("dialogues") or [])
            ],
        }
        for panel in panels
    ]
    return f"""
ComicReels visual-anchor backfill revision: {_VISUAL_ANCHOR_REVISION}
Dựa CHỈ vào ẢNH NGUỒN đã upload ở TURN ĐẦU của chính conversation này.
KHÔNG upload lại ảnh. KHÔNG dùng bất kỳ ảnh AI nào được generate ở các TURN SAU làm reference.

Ảnh nguồn có kích thước {source_width}x{source_height}px.
Với TỪNG panel ứng viên bên dưới, hãy nhìn đúng bbox của panel đó trong ảnh nguồn và mô tả
visual_anchor đủ cụ thể để khóa pose/composition khi tạo ảnh 9:16 sau này.

Visual anchor phải mô tả CHỈ những gì nhìn thấy:
- nhân vật nào xuất hiện;
- vị trí trái/phải/trước/sau;
- đứng/ngồi/nằm/quay lưng, hướng mặt và hướng nhìn;
- biểu cảm chính;
- khoảng cách tương đối và framing;
- đạo cụ/bối cảnh quan trọng nếu có.
Không suy diễn cốt truyện. Không mượn pose từ panel khác. Không dùng output ảnh AI cũ.

Panels:
{json.dumps(rows, ensure_ascii=False)}

Trả DUY NHẤT JSON:
{{
  "panels": [
    {{"panel_index": 0, "visual_anchor": "mô tả cụ thể panel 1"}}
  ]
}}
""".strip()


async def backfill_visual_anchors_in_conversation(
    conversation_url: str,
    panels: list[dict[str, Any]],
    *,
    source_width: int,
    source_height: int,
    client=None,
) -> dict[int, str]:
    if not conversation_url:
        raise RuntimeError("Thiếu ChatGPT conversation URL để backfill visual anchor.")
    if not panels:
        return {}

    active_client = client or _client()
    prompt = _visual_anchor_prompt(
        panels,
        source_width=source_width,
        source_height=source_height,
    )
    payload = json.dumps(
        [
            {
                "panel_index": int(panel.get("panel_index", panel.get("display_order", 0))),
                "x": int(panel["x"]),
                "y": int(panel["y"]),
                "w": int(panel["w"]),
                "h": int(panel["h"]),
            }
            for panel in panels
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(
        (
            conversation_url
            + "\n"
            + _VISUAL_ANCHOR_REVISION
            + "\n"
            + str(source_width)
            + "x"
            + str(source_height)
            + "\n"
            + payload
        ).encode("utf-8")
    ).hexdigest()[:32]
    idempotency_key = f"comicreels-visual-anchor-v1:{digest}"

    def _run():
        handle = active_client.chat.open(conversation_url)
        reply = handle.reply(
            text=prompt,
            idempotency_key=idempotency_key,
            visible=_VISIBLE,
        )
        if reply.state != "completed":
            raise RuntimeError(
                f"GPT FullProxy visual-anchor backfill chưa hoàn tất: "
                f"{reply.state}: {reply.reason or 'không có receipt'}"
            )
        if getattr(reply, "assistant_text", None):
            return str(reply.assistant_text)
        if reply.user_message is None:
            raise RuntimeError(
                "GPT FullProxy visual-anchor backfill thiếu cả assistant receipt và user receipt."
            )
        anchor = reply.user_message.provider_message_id
        if not anchor:
            raise RuntimeError("GPT FullProxy visual-anchor backfill thiếu provider user-message id.")
        message = handle.wait_for_new_message(
            after_message_id=anchor,
            role="assistant",
            timeout=180.0,
            visible=_VISIBLE,
        )
        if message is None or not message.text:
            raise RuntimeError("ChatGPT không trả visual-anchor backfill trong thời gian chờ.")
        return message.text

    assistant_text = await asyncio.to_thread(_run)
    parsed = _extract_json(assistant_text)
    raw = parsed.get("panels")
    if not isinstance(raw, list):
        raise RuntimeError("ChatGPT visual-anchor backfill thiếu mảng panels.")

    expected = {
        int(panel.get("panel_index", panel.get("display_order", 0)))
        for panel in panels
    }
    anchors: dict[int, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        panel_index = int(item.get("panel_index", -1))
        if panel_index not in expected:
            raise RuntimeError("ChatGPT visual-anchor backfill đổi panel_index ngoài contract.")
        if panel_index in anchors:
            raise RuntimeError("ChatGPT visual-anchor backfill trả panel_index trùng lặp.")
        visual_anchor = str(item.get("visual_anchor") or "").strip()
        if len(visual_anchor) < 20:
            raise RuntimeError("ChatGPT visual-anchor backfill trả anchor quá ngắn hoặc rỗng.")
        if len(visual_anchor) > 1200:
            raise RuntimeError("ChatGPT visual-anchor backfill trả anchor quá dài.")
        anchors[panel_index] = visual_anchor

    if set(anchors) != expected:
        raise RuntimeError(
            f"ChatGPT visual-anchor backfill trả {len(anchors)}/{len(expected)} panel; "
            "không áp dụng một phần."
        )
    return anchors


def _visual_anchor_validation_prompt(
    panels: list[dict[str, Any]],
    *,
    source_width: int,
    source_height: int,
) -> str:
    rows = [
        {
            "panel_index": int(panel.get("panel_index", panel.get("display_order", 0))),
            "x": int(panel["x"]),
            "y": int(panel["y"]),
            "w": int(panel["w"]),
            "h": int(panel["h"]),
            "visual_anchor": str(panel.get("visual_anchor") or "").strip(),
            "dialogues": [
                {
                    "speaker_id": str(item.get("speaker_id") or "UNKNOWN"),
                    "text": str(item.get("text") or ""),
                }
                for item in (panel.get("dialogues") or [])
            ],
        }
        for panel in panels
    ]
    return f"""
ComicReels visual-anchor validation revision: {_VISUAL_ANCHOR_VALIDATE_REVISION}
Dựa CHỈ vào ẢNH NGUỒN đã upload ở TURN ĐẦU của chính conversation này.
KHÔNG upload lại ảnh. KHÔNG dùng bất kỳ ảnh AI nào ở các TURN SAU làm reference.

Ảnh nguồn có kích thước {source_width}x{source_height}px.
Với TỪNG panel dưới đây, hãy nhìn đúng bbox trên ảnh nguồn rồi kiểm tra visual_anchor hiện tại
có mô tả đúng pose, hướng mặt/hướng nhìn, vị trí tương đối và framing của panel đó hay không.

QUY TẮC:
- Nếu anchor hiện tại đúng về hình học/pose/framing, matches_source=true và corrected_anchor="".
- Nếu anchor hiện tại sai BẤT KỲ chi tiết hình học quan trọng nào, matches_source=false và corrected_anchor
  phải là mô tả đầy đủ, chính xác thay thế anchor cũ.
- Đặc biệt kiểm tra hướng quay trái/phải, đứng/ngồi/nằm/quay lưng, vị trí nhân vật và ai nhìn ai.
- Không suy diễn cốt truyện. Không mượn pose từ panel khác. Không dùng output ảnh AI cũ.

Panels cần kiểm tra:
{json.dumps(rows, ensure_ascii=False)}

Trả DUY NHẤT JSON:
{{
  "panels": [
    {{
      "panel_index": 0,
      "matches_source": true,
      "corrected_anchor": "",
      "reason": "ngắn gọn"
    }}
  ]
}}
""".strip()


async def validate_visual_anchors_in_conversation(
    conversation_url: str,
    panels: list[dict[str, Any]],
    *,
    source_width: int,
    source_height: int,
    client=None,
) -> dict[int, dict[str, Any]]:
    if not conversation_url:
        raise RuntimeError("Thiếu ChatGPT conversation URL để validate visual anchor.")
    if not panels:
        return {}
    for panel in panels:
        if not str(panel.get("visual_anchor") or "").strip():
            raise RuntimeError("Không thể validate panel chưa có visual anchor.")

    active_client = client or _client()
    prompt = _visual_anchor_validation_prompt(
        panels,
        source_width=source_width,
        source_height=source_height,
    )
    payload = json.dumps(
        [
            {
                "panel_index": int(panel.get("panel_index", panel.get("display_order", 0))),
                "x": int(panel["x"]),
                "y": int(panel["y"]),
                "w": int(panel["w"]),
                "h": int(panel["h"]),
                "visual_anchor": str(panel.get("visual_anchor") or "").strip(),
            }
            for panel in panels
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(
        (
            conversation_url
            + "\n"
            + _VISUAL_ANCHOR_VALIDATE_REVISION
            + "\n"
            + str(source_width)
            + "x"
            + str(source_height)
            + "\n"
            + payload
        ).encode("utf-8")
    ).hexdigest()[:32]
    idempotency_key = f"comicreels-visual-anchor-validate-v1:{digest}"

    def _run():
        handle = active_client.chat.open(conversation_url)
        reply = handle.reply(
            text=prompt,
            idempotency_key=idempotency_key,
            visible=_VISIBLE,
        )
        if reply.state != "completed":
            raise RuntimeError(
                f"GPT FullProxy visual-anchor validate chưa hoàn tất: "
                f"{reply.state}: {reply.reason or 'không có receipt'}"
            )
        if getattr(reply, "assistant_text", None):
            return str(reply.assistant_text)
        if reply.user_message is None:
            raise RuntimeError(
                "GPT FullProxy visual-anchor validate thiếu cả assistant receipt và user receipt."
            )
        anchor = reply.user_message.provider_message_id
        if not anchor:
            raise RuntimeError("GPT FullProxy visual-anchor validate thiếu provider user-message id.")
        message = handle.wait_for_new_message(
            after_message_id=anchor,
            role="assistant",
            timeout=180.0,
            visible=_VISIBLE,
        )
        if message is None or not message.text:
            raise RuntimeError("ChatGPT không trả visual-anchor validation trong thời gian chờ.")
        return message.text

    assistant_text = await asyncio.to_thread(_run)
    parsed = _extract_json(assistant_text)
    raw = parsed.get("panels")
    if not isinstance(raw, list):
        raise RuntimeError("ChatGPT visual-anchor validation thiếu mảng panels.")

    expected = {
        int(panel.get("panel_index", panel.get("display_order", 0))): str(
            panel.get("visual_anchor") or ""
        ).strip()
        for panel in panels
    }
    validations: dict[int, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        panel_index = int(item.get("panel_index", -1))
        if panel_index not in expected:
            raise RuntimeError("ChatGPT visual-anchor validation đổi panel_index ngoài contract.")
        if panel_index in validations:
            raise RuntimeError("ChatGPT visual-anchor validation trả panel_index trùng lặp.")
        matches_source = item.get("matches_source")
        if not isinstance(matches_source, bool):
            raise RuntimeError("ChatGPT visual-anchor validation thiếu matches_source boolean.")
        corrected_anchor = str(item.get("corrected_anchor") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if matches_source:
            corrected_anchor = ""
        else:
            if len(corrected_anchor) < 20:
                raise RuntimeError(
                    "ChatGPT visual-anchor validation báo sai nhưng corrected_anchor quá ngắn hoặc rỗng."
                )
            if len(corrected_anchor) > 1200:
                raise RuntimeError("ChatGPT visual-anchor validation trả corrected_anchor quá dài.")
        validations[panel_index] = {
            "matches_source": matches_source,
            "current_anchor": expected[panel_index],
            "corrected_anchor": corrected_anchor,
            "reason": reason[:1000],
        }

    if set(validations) != set(expected):
        raise RuntimeError(
            f"ChatGPT visual-anchor validation trả {len(validations)}/{len(expected)} panel; "
            "không áp dụng một phần."
        )
    return validations


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
        safe["visual_anchor"] = str(panel.get("visual_anchor") or "").strip()
        normalized.append(safe)

    parsed["panels"] = normalized
    parsed["dialogues"] = [dict(item) for item in (parsed.get("dialogues") or []) if isinstance(item, dict)]
    for item in parsed["dialogues"]:
        item["verified"] = False
    warnings = [str(item) for item in (parsed.get("warnings") or [])]

    conversation_url = str(result.conversation_url or "").strip()
    if conversation_url and parsed["dialogues"]:
        try:
            parsed["dialogues"] = await verify_dialogues_in_conversation(
                conversation_url,
                parsed["dialogues"],
                client=client,
            )
            warnings.append(
                "Transcript đã được kiểm tra lại trong cùng ChatGPT conversation, không upload lại ảnh."
            )
        except Exception as exc:
            warnings.append(
                f"Transcript follow-up trong cùng conversation chưa xác minh ({type(exc).__name__}); cần review."
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


def _image_generation_intent(
    *,
    conversation_url: str,
    selector: str,
    prompt: str,
    reference_width: int,
    reference_height: int,
) -> str:
    payload = {
        "revision": _IMAGE_GENERATION_REVISION,
        "conversation_url": conversation_url,
        "selector": selector,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "reference_width": int(reference_width),
        "reference_height": int(reference_height),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _generation_cache_paths(output_path: Path, intent_sha256: str) -> tuple[Path, Path]:
    root = output_path.parent / "generation-cache"
    return root / f"{intent_sha256}.json", root / f"{intent_sha256}.png"


def _validate_generated_portrait(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
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
        return {"x": 0, "y": 0, "w": width, "h": height}


def _reuse_generation_cache(
    *,
    receipt_path: Path,
    cache_path: Path,
    output_path: Path,
    intent_sha256: str,
    selector: str,
) -> tuple[Path, dict[str, int], str] | None:
    receipt_exists = receipt_path.is_file()
    cache_exists = cache_path.is_file()
    if not receipt_exists and not cache_exists:
        return None
    if receipt_exists != cache_exists:
        raise RuntimeError(
            "Generation cache không đầy đủ; chặn gửi lại để tránh lặp một intent đã từng chạy."
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("Generation receipt bị lỗi; không được gửi lại intent này.") from exc
    if (
        str(receipt.get("intent_sha256") or "") != intent_sha256
        or str(receipt.get("selector") or "") != selector
    ):
        raise RuntimeError("Generation receipt không khớp intent; không được gửi lại.")
    expected_sha = str(receipt.get("sha256") or "")
    if not expected_sha or sha256_file(cache_path) != expected_sha:
        raise RuntimeError("Generation cache đã thay đổi; không được gửi lại intent này.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache_path, output_path)
    protected = _validate_generated_portrait(output_path)
    return output_path, protected, expected_sha


def _write_generation_cache(
    *,
    generated_path: Path,
    receipt_path: Path,
    cache_path: Path,
    intent_sha256: str,
    selector: str,
    result: Any,
) -> str:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_tmp = cache_path.with_suffix(".tmp.png")
    shutil.copy2(generated_path, cache_tmp)
    digest = sha256_file(cache_tmp)
    os.replace(cache_tmp, cache_path)

    receipt = {
        "schema": "comicreels.image-generation-receipt.v1",
        "intent_sha256": intent_sha256,
        "selector": selector,
        "sha256": digest,
        "cache_path": str(cache_path),
        "conversation_url": str(getattr(result, "conversation_url", "") or ""),
        "assistant_message_id": str(getattr(result, "assistant_message_id", "") or ""),
        "observation_id": str(getattr(result, "observation_id", "") or ""),
        "turn_testid": str(getattr(result, "turn_testid", "") or ""),
    }
    receipt_tmp = receipt_path.with_suffix(".tmp.json")
    receipt_tmp.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(receipt_tmp, receipt_path)
    return digest


def _image_prompt(
    regions: list[dict[str, int]],
    panel_context: str,
    panel_index: int,
    *,
    panel_box: dict[str, int],
    source_width: int,
    source_height: int,
    visual_anchor: str,
    reference_asset_name: str,
    use_local_crop: bool = False,
) -> str:
    region_text = ", ".join(
        f"(x={r['x']},y={r['y']},w={r['w']},h={r['h']})" for r in regions
    ) or "các speech bubble/text nhìn thấy trong ảnh"
    reference_policy = f"""
Reference bắt buộc của request này là attachment provider-side "{reference_asset_name}" đã tồn tại
trong CHÍNH conversation này. Đây là crop của KHUNG {panel_index + 1} từ ảnh nguồn, không phải ảnh
AI generate. Không upload lại bytes và không dùng ảnh từ conversation khác.
Dùng crop đang được đính kèm trong user turn hiện tại làm reference hình học/pose/framing trực tiếp.
Ảnh nguồn ở TURN ĐẦU và bbox bên dưới chỉ dùng để xác nhận provenance của crop.
""".strip()
    if use_local_crop:
        reference_policy = f"""
Ảnh đính kèm "{reference_asset_name}" là crop GỐC chính xác của KHUNG {panel_index + 1}.
Đây là cuộc trò chuyện mới; không có ảnh nguồn hoặc ảnh đã tạo nào ở turn trước để tham chiếu.
Dùng duy nhất ảnh đính kèm này để giữ hình học, tư thế và bố cục nhân vật.
Bbox bên dưới chỉ ghi vị trí crop trên trang truyện gốc; KHÔNG cắt lại bbox đó trên ảnh đính kèm.
""".strip()
    return f"""
{reference_policy}
MỌI ảnh AI đã generate ở các TURN SAU chỉ là OUTPUT CŨ: tuyệt đối không dùng chúng làm
reference hình học, pose, framing hoặc bố cục cho yêu cầu hiện tại.

Chỉ xử lý KHUNG {panel_index + 1}.
Vùng panel mục tiêu trong ẢNH NGUỒN {source_width}x{source_height}px là:
x={panel_box['x']}, y={panel_box['y']}, w={panel_box['w']}, h={panel_box['h']}.

Trước khi tạo ảnh, hãy coi CHÍNH hình ảnh bên trong bbox này là reference hình học bắt buộc.
VISUAL ANCHOR đã được đọc trực tiếp từ ảnh nguồn trong lần phân tích đầu tiên:
{visual_anchor}
Visual anchor này là ràng buộc của KHUNG {panel_index + 1}, không được thay bằng pose từ output cũ.
Tạo lại riêng cảnh của khung đó thành ảnh dọc 9:16 hoàn chỉnh dùng cho video.

BẮT BUỘC:
- Giữ nguyên tuyệt đối thiết kế nhân vật, khuôn mặt, biểu cảm, tỷ lệ cơ thể,
  trang phục, đạo cụ, nét vẽ, palette và phong cách minh họa của ảnh gốc.
- Giữ ĐÚNG pose, hướng nhìn, vị trí tương đối, khoảng cách và framing của nhân vật trong bbox panel mục tiêu.
- TUYỆT ĐỐI KHÔNG mượn pose/composition từ panel khác trong cùng ảnh nguồn.
- Phần hình ảnh gốc bên trong bbox panel mục tiêu phải được xem là protected visual reference;
  chỉ được thay đổi nơi có chữ/bubble hoặc phần cần outpaint để mở rộng ra 9:16.
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


async def recover_historical_portrait(
    output_path: Path,
    *,
    conversation_url: str,
    output_message_id: str,
    expected_sha256: str,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> tuple[Path, dict[str, int], str]:
    if not conversation_url:
        raise RuntimeError("Thiếu ChatGPT conversation để recovery ảnh lịch sử.")
    if not str(output_message_id or "").strip():
        raise RuntimeError("Historical output thiếu provider message id.")
    expected_sha256 = str(expected_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise RuntimeError("Historical output sha256 không hợp lệ.")

    artifact_dir = output_path.parent / "gptfp-history"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    client = _client()
    result = await asyncio.to_thread(
        client.image.recover_existing,
        conversation=conversation_url,
        output_message_id=output_message_id,
        output_dir=artifact_dir,
        expected_sha256=expected_sha256,
        expected_width=expected_width,
        expected_height=expected_height,
        visible=_VISIBLE,
    )
    if result.state != "verified" or not result.output_path:
        raise RuntimeError(
            f"GPT FullProxy historical recovery chưa xác minh: "
            f"{result.state}: {result.reason or 'không có artifact'}"
        )

    recovered_path = Path(result.output_path).expanduser().resolve()
    if not recovered_path.is_file():
        raise RuntimeError("Historical recovery trả artifact path nhưng file không tồn tại.")
    digest = sha256_file(recovered_path)
    if digest.lower() != expected_sha256:
        raise RuntimeError("Historical recovery artifact hash không khớp manifest.")

    protected = _validate_generated_portrait(recovered_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(recovered_path, output_path)
    if sha256_file(output_path).lower() != expected_sha256:
        raise RuntimeError("Historical recovery working copy không khớp manifest.")
    protected = _validate_generated_portrait(output_path)
    return output_path, protected, expected_sha256


async def generate_clean_portrait(
    crop_path: Path,
    regions: list[dict[str, int]],
    output_path: Path,
    *,
    conversation_url: str,
    panel_index: int,
    panel_context: str = "",
    panel_box: dict[str, int] | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
    visual_anchor: str = "",
    force_regenerate: bool = False,
    use_local_crop: bool = False,
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
    visual_anchor = str(visual_anchor or "").strip()
    if not visual_anchor:
        raise RuntimeError(
            "Panel chưa có visual anchor từ ảnh nguồn; chặn Generate để tránh mượn pose từ ảnh AI cũ."
        )

    artifact_dir = output_path.parent / "gptfp-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not panel_box or not source_width or not source_height:
        raise RuntimeError("Thiếu bbox/source size để khóa AI Generate vào đúng panel nguồn.")
    prompt = _image_prompt(
        regions,
        panel_context,
        panel_index,
        panel_box=panel_box,
        source_width=source_width,
        source_height=source_height,
        visual_anchor=visual_anchor,
        reference_asset_name=crop_path.name if use_local_crop else f"p{panel_index}.png",
        use_local_crop=use_local_crop,
    )

    selector = f"local-crop:{sha256_file(crop_path)}" if use_local_crop else f"name:p{panel_index}.png"
    reference_width = int(panel_box["w"])
    reference_height = int(panel_box["h"])
    intent_sha256 = _image_generation_intent(
        conversation_url=conversation_url,
        selector=selector,
        prompt=prompt,
        reference_width=reference_width,
        reference_height=reference_height,
    )
    receipt_path, cache_path = _generation_cache_paths(output_path, intent_sha256)
    if not force_regenerate:
        cached = _reuse_generation_cache(
            receipt_path=receipt_path,
            cache_path=cache_path,
            output_path=output_path,
            intent_sha256=intent_sha256,
            selector=selector,
        )
        if cached is not None:
            return cached

    client = _client()
    # Account/device migration can make the old conversation inaccessible. Only
    # an explicit local-crop request uploads original bytes into a fresh chat;
    # provider errors or uncertain outcomes never trigger an automatic retry.
    reference_args = {"attachments": [crop_path]} if use_local_crop else {
        "conversation": conversation_url,
        "attachments": [],
        "conversation_attachment": selector,
        "reference_width": reference_width,
        "reference_height": reference_height,
    }
    result = await asyncio.to_thread(
        client.image.generate,
        prompt,
        **reference_args,
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

    _validate_generated_portrait(generated_path)
    digest = _write_generation_cache(
        generated_path=generated_path,
        receipt_path=receipt_path,
        cache_path=cache_path,
        intent_sha256=intent_sha256,
        selector=selector,
        result=result,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cache_path, output_path)
    protected = _validate_generated_portrait(output_path)
    return output_path, protected, digest
