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
from tempfile import TemporaryDirectory
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



def _panel_dialogues(dialogues: list[dict[str, Any]], panel_index: int) -> list[dict[str, Any]]:
    return sorted(
        [item for item in dialogues if int(item.get("panel_index", -1)) == panel_index],
        key=lambda item: int(item.get("display_order", 0)),
    )


def _transcription_prompt(panel_index: int, candidates: list[dict[str, Any]]) -> str:
    candidate_rows = [
        {
            "display_order": int(item.get("display_order", index)),
            "text": str(item.get("text") or ""),
        }
        for index, item in enumerate(candidates)
    ]
    return f"""
Bạn là bộ CHÉP NGUYÊN VĂN cho ComicReels. Ảnh đính kèm chỉ chứa KHUNG {panel_index + 1}.

Nhiệm vụ duy nhất:
- Đọc mọi lời thoại/caption nhìn thấy trong khung theo thứ tự đọc.
- Chép ĐÚNG TỪNG KÝ TỰ, đặc biệt dấu tiếng Việt: Ă Â Ê Ô Ơ Ư, dấu sắc/huyền/hỏi/ngã/nặng.
- Giữ nguyên chữ hoa, dấu câu, số lần dấu chấm than và cách viết trong ảnh.
- Không sửa chính tả, không đoán câu "hợp lý hơn", không dịch, không thêm bớt chữ.
- Danh sách pass 1 bên dưới CHỈ là ứng viên để đối chiếu, không phải đáp án:
{json.dumps(candidate_rows, ensure_ascii=False)}

Trả DUY NHẤT JSON:
{{
  "dialogues": [
    {{"display_order": 0, "text": "NGUYÊN VĂN TRONG ẢNH"}}
  ],
  "confidence": 0.99
}}
""".strip()


def _adjudication_prompt(
    panel_index: int,
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> str:
    first_rows = [
        {"display_order": int(item.get("display_order", index)), "text": str(item.get("text") or "")}
        for index, item in enumerate(first)
    ]
    second_rows = [
        {"display_order": int(item.get("display_order", index)), "text": str(item.get("text") or "")}
        for index, item in enumerate(second)
    ]
    return f"""
Bạn là lượt KIỂM ĐỊNH CUỐI transcript ComicReels cho KHUNG {panel_index + 1}.
Hãy nhìn trực tiếp ảnh đính kèm, không suy luận từ ngữ cảnh.

Pass 1:
{json.dumps(first_rows, ensure_ascii=False)}

Pass 2:
{json.dumps(second_rows, ensure_ascii=False)}

Hai pass đang không hoàn toàn giống nhau. Hãy đọc lại từng ký tự trong ảnh và trả bản đúng.
Đặc biệt phân biệt chính xác dấu tiếng Việt, không sửa chính tả, không viết lại câu.

Trả DUY NHẤT JSON:
{{
  "dialogues": [
    {{"display_order": 0, "text": "NGUYÊN VĂN TRONG ẢNH"}}
  ],
  "confidence": 0.99
}}
""".strip()


def _transcript_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("dialogues")
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            order = int(item.get("display_order", index))
        except (TypeError, ValueError):
            order = index
        rows.append({"display_order": order, "text": text})
    return sorted(rows, key=lambda item: item["display_order"])


def _same_transcript(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    if len(left) != len(right):
        return False
    return all(
        int(a.get("display_order", index)) == int(b.get("display_order", index))
        and str(a.get("text") or "") == str(b.get("text") or "")
        for index, (a, b) in enumerate(zip(left, right, strict=True))
    )


def _save_verification_crop(
    source: Image.Image,
    panel: dict[str, Any],
    target: Path,
) -> None:
    x, y, w, h = (int(panel[key]) for key in ("x", "y", "w", "h"))
    crop = source.crop((x, y, x + w, y + h)).convert("RGB")
    longest = max(crop.size)
    scale = min(2.0, 3000 / longest) if longest else 1.0
    if scale > 1.05:
        crop = crop.resize(
            (max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    crop.save(target, "PNG")


async def _cross_check_dialogues(
    client,
    source_path: Path,
    panels: list[dict[str, Any]],
    dialogues: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    """Cross-check exact transcript per deterministic panel crop.

    Pass 1 owns panel/speaker mapping. Pass 2 only transcribes the enlarged panel.
    A third adjudication runs only when the exact strings disagree. We never mark a
    dialogue verified merely because the first broad analysis returned a confidence.
    """

    for item in dialogues:
        item["verified"] = False

    verification_root = _home_dir() / "transcript-verification"
    verification_root.mkdir(parents=True, exist_ok=True)
    with Image.open(source_path) as source, TemporaryDirectory(
        prefix="comicreels-", dir=verification_root
    ) as temp_dir:
        temp = Path(temp_dir)
        for panel_index, panel in enumerate(panels):
            first = _panel_dialogues(dialogues, panel_index)
            crop_path = temp / f"panel-{panel_index + 1:03d}-verification.png"
            _save_verification_crop(source, panel, crop_path)

            try:
                second_result = await asyncio.to_thread(
                    client.chat.send,
                    _transcription_prompt(panel_index, first),
                    attachments=[crop_path],
                    visible=_VISIBLE,
                )
                if second_result.state != "verified" or not second_result.text:
                    warnings.append(
                        f"Khung {panel_index + 1}: lượt đối chiếu transcript chưa xác minh; cần review."
                    )
                    continue
                second = _transcript_rows(_extract_json(second_result.text))
            except Exception as exc:
                warnings.append(
                    f"Khung {panel_index + 1}: không đối chiếu được transcript ({type(exc).__name__}); cần review."
                )
                continue

            if _same_transcript(first, second):
                for item in first:
                    item["verified"] = True
                continue

            # A count mismatch cannot preserve speaker mapping safely.
            if len(first) != len(second):
                warnings.append(
                    f"Khung {panel_index + 1}: AI không thống nhất số câu thoại "
                    f"({len(first)} so với {len(second)}); cần review."
                )
                continue

            try:
                third_result = await asyncio.to_thread(
                    client.chat.send,
                    _adjudication_prompt(panel_index, first, second),
                    attachments=[crop_path],
                    visible=_VISIBLE,
                )
                if third_result.state != "verified" or not third_result.text:
                    warnings.append(
                        f"Khung {panel_index + 1}: lượt phân xử transcript chưa xác minh; cần review."
                    )
                    continue
                third = _transcript_rows(_extract_json(third_result.text))
            except Exception as exc:
                warnings.append(
                    f"Khung {panel_index + 1}: không phân xử được transcript ({type(exc).__name__}); cần review."
                )
                continue

            if _same_transcript(third, second):
                chosen = second
                source_label = "pass 2 + kiểm định"
            elif _same_transcript(third, first):
                chosen = first
                source_label = "pass 1 + kiểm định"
            else:
                warnings.append(
                    f"Khung {panel_index + 1}: ba lượt transcript vẫn không thống nhất; cần review."
                )
                continue

            changed: list[str] = []
            for current, resolved in zip(first, chosen, strict=True):
                before = str(current.get("text") or "")
                after = str(resolved.get("text") or "")
                if before != after:
                    changed.append(f"{before!r} → {after!r}")
                current["text"] = after
                current["verified"] = True
            if changed:
                warnings.append(
                    f"Khung {panel_index + 1}: transcript được sửa sau {source_label}: "
                    + "; ".join(changed)
                )


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

Chỉ xử lý KHUNG ${panel_index + 1} của ảnh nguồn.
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
