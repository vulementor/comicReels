"""Deterministic shot planning and prompt generation."""
from __future__ import annotations
import math
import re
from agent.comicreels import repository as repo

OMNI_DURATIONS = [4, 6, 8, 10]
VEO_DURATIONS = [8]

def _tokens_preserving_text(text: str) -> list[str]:
    parts = re.findall(r"\s*\S+(?:\s+|$)", text)
    return parts or ([text] if text else [])

def _split_preserving(text: str, max_words: int) -> list[str]:
    tokens = _tokens_preserving_text(text)
    if not tokens:
        return [""]
    return ["".join(tokens[i:i+max_words]) for i in range(0, len(tokens), max_words)]

def _duration_for(words: int, allowed: list[int], words_per_second: float) -> int:
    need = max(1, math.ceil(words / words_per_second + 0.7))
    for d in sorted(allowed):
        if d >= need:
            return d
    return max(allowed)

def _escape_dialogue(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')

async def plan_project(project_id: str, *, model_family: str = "omni_flash",
                       allowed_durations: list[int] | None = None,
                       words_per_second: float = 2.6) -> list[dict]:
    allowed = sorted(set(allowed_durations or (OMNI_DURATIONS if model_family == "omni_flash" else VEO_DURATIONS)))
    if not allowed or any(d <= 0 or d > 10 for d in allowed):
        raise ValueError("Thời lượng shot phải nằm trong 1..10 giây")
    project = await repo.get_project(project_id)
    if not project:
        raise ValueError("Không tìm thấy dự án")
    characters = {c["id"]: c for c in await repo.list_characters(project_id)}
    panels = await repo.list_panels(project_id)
    if not panels:
        raise ValueError("Dự án chưa có panel")
    all_shots: list[dict] = []
    max_words = max(1, math.floor(max(allowed) * words_per_second))
    for panel in panels:
        if not panel.get("vertical_sha256") or panel.get("approved_sha256") != panel.get("vertical_sha256"):
            raise ValueError(f"Panel {panel['display_order']+1} chưa được duyệt đúng phiên bản ảnh hiện tại")
        dialogues = await repo.list_dialogues(panel["id"])
        if dialogues and any((not d.get("user_verified")) or not d.get("speaker_id") for d in dialogues):
            raise ValueError(f"Panel {panel['display_order']+1} còn thoại/người nói chưa xác minh")
        shots: list[dict] = []
        shot_order = 0
        if not dialogues:
            prompt = (
                "STYLE: Preserve the approved comic artwork exactly.\n"
                "CHARACTERS: Keep every visible character identical to the approved image.\n"
                "RULES: No dialogue. All mouths remain closed. Do not add text, speech bubbles, characters or props.\n"
                "ACTIONS: Subtle silent reaction and natural micro-movement only; preserve composition and comedic timing.\n"
                f"DURATION: {min(allowed)} seconds."
            )
            shots.append({"display_order":0,"speaker_id":None,"dialogue_ids":[],"verbatim_text":"",
                          "duration_s":min(allowed),"model_family":model_family,"prompt":prompt,
                          "image_sha256":panel["vertical_sha256"]})
        else:
            for d in dialogues:
                chunks = _split_preserving(d["verbatim_text"], max_words)
                speaker = characters.get(d["speaker_id"])
                speaker_name = speaker["name"] if speaker else "SPEAKER"
                for chunk in chunks:
                    words = max(1, len(re.findall(r"\S+", chunk)))
                    duration = _duration_for(words, allowed, words_per_second)
                    prompt = (
                        "STYLE: Preserve the approved comic artwork, character design, colors, clothing, props and background.\n"
                        f"CHARACTERS: Speaker is {speaker_name}. Every non-speaking character keeps their mouth closed.\n"
                        "RULES: Exactly one character speaks at this time. Do not add narrator, captions, subtitles, text or speech bubbles. "
                        "Do not paraphrase, translate, shorten, repeat or invent dialogue. Lip-sync only the named speaker.\n"
                        f'ACTIONS: {speaker_name} speaks exactly: "{_escape_dialogue(chunk)}". '
                        "Use expression and body motion consistent with the approved panel. After speech ends, hold a silent reaction if time remains.\n"
                        f"DURATION: {duration} seconds."
                    )
                    shots.append({"display_order":shot_order,"speaker_id":d["speaker_id"],
                                  "dialogue_ids":[d["id"]],"verbatim_text":chunk,"duration_s":duration,
                                  "model_family":model_family,"prompt":prompt,
                                  "image_sha256":panel["vertical_sha256"]})
                    shot_order += 1
        stored = await repo.replace_shots(panel["id"], shots)
        all_shots.extend(stored)
    await repo.update_project(project_id, status="PROMPTS_READY")
    return all_shots
