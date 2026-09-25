"""Shot planning and prompt generation with verbatim dialogue locks."""
from __future__ import annotations

import math
import uuid
from typing import Iterable


SUPPORTED_DURATIONS = {
    "omni_flash": (4, 6, 8, 10),
    "veo": (8,),
}


def split_exact(text: str, max_chars: int) -> list[str]:
    if not text:
        return [""]
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            candidates = [text.rfind(ch, start + 1, end + 1) for ch in (" ", ",", ".", "!", "?", ";", ":")]
            cut = max(candidates)
            if cut > start + max_chars // 2:
                end = cut + 1
        out.append(text[start:end])
        start = end
    assert "".join(out) == text
    return out


def choose_duration(text: str, model_family: str = "omni_flash") -> int:
    durations = SUPPORTED_DURATIONS.get(model_family, (8,))
    words = max(1, len(text.strip().split()))
    estimate = 1.2 + words / 2.6
    for duration in durations:
        if duration >= estimate:
            return duration
    return durations[-1]


def split_for_model(text: str, model_family: str = "omni_flash") -> list[tuple[str, int]]:
    durations = SUPPORTED_DURATIONS.get(model_family, (8,))
    max_duration = max(durations)
    # Conservative budget. The substring boundary is exact; leading/trailing
    # spaces remain in stored dialogue_text and only prompt display is stripped.
    max_words = max(4, int((max_duration - 1.2) * 2.6))
    words = text.strip().split()
    if len(words) <= max_words:
        return [(text, choose_duration(text, model_family))]
    avg = max(1, len(text) // max(1, math.ceil(len(words) / max_words)))
    pieces = split_exact(text, avg)
    return [(piece, choose_duration(piece, model_family)) for piece in pieces if piece]


def video_prompt(*, speaker_id: str | None, text: str, duration_s: int,
                 panel_order: int, silent: bool = False) -> str:
    if silent:
        dialogue = "KHÔNG CÓ LỜI THOẠI. Tất cả nhân vật giữ miệng đóng."
    else:
        dialogue = (
            f'CHỈ {speaker_id or "UNKNOWN"} nói đúng nguyên văn: "{text.strip()}". '
            "Không thêm, bớt, diễn giải hay đổi ngôn ngữ. Những nhân vật khác giữ miệng đóng."
        )
    return f"""COMICREELS SHOT · PANEL {panel_order + 1}
DURATION: {duration_s} seconds maximum.
SOURCE LOCK: Giữ nguyên tuyệt đối thiết kế nhân vật, trang phục, màu, đạo cụ, bối cảnh và nét vẽ từ ảnh tham chiếu. Không thêm nhân vật.
DIALOGUE LOCK: {dialogue}
ACTION: Chuyển động nhỏ, tự nhiên và đúng cảm xúc của khung; ưu tiên nhịp hài gốc. Nếu thoại kết thúc sớm, phần còn lại chỉ là phản ứng im lặng.
LIP SYNC: Chỉ người đang nói cử động miệng trong thời gian câu thoại; người không nói không chép miệng.
CAMERA: Giữ bố cục nguồn; chuyển động máy rất nhẹ, không che hoặc cắt nhân vật quan trọng.
NO TEXT: Không tạo chữ, subtitle, speech bubble, watermark hoặc caption trong video."""
    

def build_shots(project_id: str, panels: list[dict], model_family: str = "omni_flash") -> list[dict]:
    shots: list[dict] = []
    order = 0
    for panel in panels:
        dialogues = sorted(panel.get("dialogues", []), key=lambda d: d.get("display_order", 0))
        if not dialogues:
            duration = min(SUPPORTED_DURATIONS.get(model_family, (8,)))
            shots.append({
                "id": uuid.uuid4().hex, "project_id": project_id, "panel_id": panel["id"],
                "display_order": order, "speaker_id": None, "dialogue_text": "", "duration_s": duration,
                "model_family": model_family, "prompt": video_prompt(
                    speaker_id=None, text="", duration_s=duration,
                    panel_order=panel["display_order"], silent=True,
                ),
                "image_sha256": panel["approved_sha256"],
            })
            order += 1
            continue
        for dialogue in dialogues:
            for piece, duration in split_for_model(dialogue["text"], model_family):
                shots.append({
                    "id": uuid.uuid4().hex, "project_id": project_id, "panel_id": panel["id"],
                    "display_order": order, "speaker_id": dialogue["speaker_id"],
                    "dialogue_text": piece, "duration_s": duration, "model_family": model_family,
                    "prompt": video_prompt(
                        speaker_id=dialogue["speaker_id"], text=piece, duration_s=duration,
                        panel_order=panel["display_order"],
                    ),
                    "image_sha256": panel["approved_sha256"],
                })
                order += 1
    return shots
