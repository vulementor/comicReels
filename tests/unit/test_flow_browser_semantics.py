from unittest.mock import MagicMock

import pytest

from agent.services.flow_browser_semantics import (
    ExistingReference,
    attach_existing_references,
    highest_video_download,
    image_id_from_composer_url,
    verify_reference_composer,
)

REFS = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 4)]
PROJECT = "10000000-0000-4000-8000-000000000001"


def composer(refs=REFS, prompt="Câu một.\nCâu hai."):
    page = MagicMock()
    page.url = f"https://flow.google.com/project/{PROJECT}"
    page.get_by_role.return_value.evaluate_all.return_value = [
        f"https://flow-content.google/image/{ref}?Signature=must-not-escape" for ref in refs]
    page.locator.return_value.count.return_value = 1
    page.locator.return_value.inner_text.return_value = prompt
    return page


def references():
    return [ExistingReference(ref, f"ref-{i}.png") for i, ref in enumerate(REFS, 1)]


def test_composer_evidence_keeps_order_and_drops_signed_urls():
    receipt = verify_reference_composer(composer(), PROJECT, references(), "Câu một. Câu hai.")
    assert receipt["ordered_reference_ids"] == REFS
    assert "Signature" not in str(receipt)


def test_recent_grid_reverse_order_cannot_pass_as_story_order():
    with pytest.raises(ValueError, match="REFERENCE_ORDER_MISMATCH"):
        verify_reference_composer(composer(list(reversed(REFS))), PROJECT, references(), "Câu một. Câu hai.")


def test_four_scene_story_verifies_every_reference_instead_of_dropping_the_last():
    ids = REFS + ['00000000-0000-4000-8000-000000000004']
    images = [ExistingReference(mid, f'scene-{i}.png') for i, mid in enumerate(ids)]
    assert verify_reference_composer(composer(ids), PROJECT, images, 'Câu một. Câu hai.')['ordered_reference_ids'] == ids


def test_changed_dialogue_fails_even_if_whitespace_matches():
    with pytest.raises(ValueError, match="PROMPT_MISMATCH"):
        verify_reference_composer(composer(prompt="Câu khác."), PROJECT, references(), "Câu một.")


def test_wrong_project_fails():
    page = composer()
    page.url += "/tools"
    with pytest.raises(ValueError, match="PROJECT_MISMATCH"):
        verify_reference_composer(page, PROJECT, references(), "Câu một. Câu hai.")


@pytest.mark.parametrize("url", [
    f"https://evil.example/image/{REFS[0]}",
    f"https://flow-content.google/video/{REFS[0]}",
    "https://flow-content.google/image/CAMS-not-a-uuid",
])
def test_preview_from_wrong_asset_or_host_fails(url):
    with pytest.raises(ValueError):
        image_id_from_composer_url(url)


def test_highest_download_is_selected_without_choosing_gif():
    assert highest_video_download(["270p Ảnh GIF động", "720p Đã tăng độ phân giải", "360p Kích thước gốc"]) == "720p Đã tăng độ phân giải"


def test_unknown_download_option_needs_fresh_observation():
    with pytest.raises(ValueError, match="UNKNOWN_DOWNLOAD_RESOLUTION"):
        highest_video_download(["360p Original", "4K Enhanced"])


def test_delayed_picker_confirmation_is_awaited_before_attachment(monkeypatch):
    from agent.services import flow_browser_semantics as semantics

    page = MagicMock()
    confirm = MagicMock()
    preview = MagicMock()
    confirm.is_visible.side_effect = [False, True]
    preview.is_visible.return_value = True
    page.get_by_role.side_effect = lambda role, name, exact: (
        confirm if name == "Thêm vào câu lệnh" else preview if role == "img" else MagicMock()
    )
    states = iter([[], [], [], [REFS[0]]])
    monkeypatch.setattr(semantics, "composer_reference_ids", lambda _: next(states))
    attach_existing_references(page, references()[:1])
    confirm.press.assert_called_once_with("Enter", timeout=10000)


def test_auto_attached_image_does_not_press_stale_confirmation(monkeypatch):
    from agent.services import flow_browser_semantics as semantics

    page = MagicMock()
    states = iter([[], [REFS[0]]])
    monkeypatch.setattr(semantics, "composer_reference_ids", lambda _: next(states))
    attach_existing_references(page, references()[:1])
    # Only the button opening the picker was pressed.
    assert page.get_by_role.return_value.press.call_count == 1


def test_stale_preview_is_never_confirmed_and_wait_is_bounded(monkeypatch):
    from agent.services import flow_browser_semantics as semantics

    page = MagicMock()
    confirm = MagicMock()
    preview = MagicMock()
    confirm.is_visible.return_value = True
    preview.is_visible.return_value = False
    page.get_by_role.side_effect = lambda role, name, exact: (
        confirm if name == "Thêm vào câu lệnh" else preview if role == "img" else MagicMock()
    )
    monkeypatch.setattr(semantics, "composer_reference_ids", lambda _: [])
    ticks = iter(range(30))
    monkeypatch.setattr(semantics.time, "monotonic", lambda: next(ticks))
    with pytest.raises(TimeoutError, match="REFERENCE_ATTACH_TIMEOUT"):
        attach_existing_references(page, references()[:1])
    confirm.press.assert_not_called()
