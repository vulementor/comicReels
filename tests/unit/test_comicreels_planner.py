import pytest
from agent.comicreels.planner import _duration_for, _split_preserving


@pytest.mark.parametrize("text,max_words", [
    ("Xin chào anh em!", 2),
    ("  Giữ nguyên   khoảng trắng và dấu câu.  ", 3),
    ("Một", 20),
])
def test_split_preserves_exact_dialogue(text: str, max_words: int):
    assert "".join(_split_preserving(text, max_words)) == text


def test_duration_uses_supported_bucket():
    assert _duration_for(4, [4,6,8,10], 2.6) == 4
    assert _duration_for(15, [4,6,8,10], 2.6) in {6,8,10}
    assert _duration_for(20, [8], 2.6) == 8
