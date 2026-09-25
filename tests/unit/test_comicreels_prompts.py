from agent.comicreels.prompts import build_shots, split_for_model


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
