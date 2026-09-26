import pytest

from agent.comicreels.prompts import build_shots, reference_video_prompt, split_for_model


def test_uneven_word_lengths_never_exceed_the_ten_second_dialogue_budget():
    text = " ".join(["ừ"] * 48 + ["nghiêngngả" * 20]) + "  "
    pieces = split_for_model(text)
    assert "".join(piece for piece, _ in pieces) == text
    assert all(len(piece.split()) <= 22 for piece, _ in pieces)


def test_split_preserves_verbatim():
    text = "Câu một có dấu. Câu hai vẫn giữ nguyên từng ký tự và khoảng trắng."
    pieces = split_for_model(text, "omni_flash")
    assert "".join(part for part, _ in pieces) == text
    assert all(duration in {4, 6, 8, 10} for _, duration in pieces)
    assert all(duration <= 10 for _, duration in pieces)


def test_build_shots_locks_speaker_and_approved_hash():
    panels = [{
        "id": "p1", "display_order": 0, "approved_sha256": "abc",
        "dialogues": [{"display_order": 0, "speaker_id": "CHAR_A", "text": "Xin chào.", "verified": 1}],
    }]
    shots = build_shots("project", panels, "omni_flash")
    assert shots
    assert all(s["speaker_id"] == "CHAR_A" for s in shots)
    assert all(s["image_sha256"] == "abc" for s in shots)
    assert "Không thêm, bớt" in shots[0]["prompt"]
    assert "người không nói không chép miệng" in shots[0]["prompt"]



def test_video_prompt_embeds_dialogue_audio_without_external_tts():
    panels = [{
        "id": "p1", "display_order": 0, "approved_sha256": "abc",
        "dialogues": [{"display_order": 0, "speaker_id": "CHAR_A", "text": "Nói đúng câu này.", "verified": 1}],
    }]
    shot = build_shots("project", panels, "omni_flash")[0]
    assert 'Nói đúng câu này.' in shot["prompt"]
    assert "Tạo luôn lời thoại nói trong chính video" in shot["prompt"]
    assert "Không chờ, không yêu cầu và không giả định có file TTS" in shot["prompt"]


def test_reference_video_prompt_locks_three_images_and_character_design():
    prompt = reference_video_prompt("BASE SCRIPT WITH DIALOGUE", 3)
    assert "REFERENCE IMAGES: 3 ảnh" in prompt
    assert "Bám sát tuyệt đối thiết kế nhân vật" in prompt
    assert "Không redesign" in prompt
    assert "Lời thoại phải được tạo trực tiếp trong video" in prompt
    assert "BASE SCRIPT WITH DIALOGUE" in prompt


@pytest.mark.parametrize("count", [0, 4])
def test_reference_video_prompt_rejects_reference_count_outside_one_to_three(count):
    with pytest.raises(ValueError, match="1 to 3"):
        reference_video_prompt("script", count)



def test_build_shots_fixed_omni_duration_is_ten_seconds():
    panels = [{
        "id": "p1",
        "display_order": 0,
        "approved_sha256": "abc",
        "dialogues": [
            {"display_order": 0, "speaker_id": "CHAR_A", "text": "Câu ngắn.", "verified": 1},
            {"display_order": 1, "speaker_id": "CHAR_B", "text": "Câu thứ hai cũng phải giữ nguyên.", "verified": 1},
        ],
    }]
    shots = build_shots(
        "project",
        panels,
        "omni_flash",
        fixed_duration_s=10,
    )
    assert shots
    assert all(shot["duration_s"] == 10 for shot in shots)
    assert all("DURATION: 10 seconds maximum." in shot["prompt"] for shot in shots)
