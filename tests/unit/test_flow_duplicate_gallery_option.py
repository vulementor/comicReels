"""Duplicate gallery filenames never replace durable native media identity."""
from unittest.mock import MagicMock, patch

import pytest

from agent.services.flow_browser_semantics import ExistingReference, attach_existing_references


EXPECTED = "7d283cf8-1a10-40fa-a342-3e2bd34d1e9e"
WRONG = "fb91dee1-a683-4bb2-907c-e2068c6aae98"
FILENAME = "fd9a2f367618-source-scene-03.png"


def _page(count):
    page = MagicMock()
    options = MagicMock()
    options.count.return_value = count
    options.first = MagicMock()
    selected = MagicMock()
    options.nth.return_value = selected

    def role(kind, name, exact=True):
        if kind == "option":
            assert name == f"{FILENAME} Hình ảnh"
            return options
        if kind == "img":
            assert name == f"Bản xem trước của {FILENAME}"
            item = MagicMock()
            item.is_visible.return_value = True
            return item
        if kind == "button" and name == "Thêm vào câu lệnh":
            item = MagicMock()
            item.is_visible.return_value = True
            return item
        if kind == "button" and name == "Thêm thành phần vào ô nhập câu lệnh":
            return MagicMock()
        raise AssertionError(f"Unexpected locator: {kind}:{name}")

    page.get_by_role.side_effect = role
    return page, options, selected


def test_duplicate_gallery_filename_can_attach_only_verified_native_uuid():
    page, options, selected = _page(2)
    with patch(
        "agent.services.flow_browser_semantics.composer_reference_ids",
        side_effect=[[], [], [EXPECTED]],
    ):
        attach_existing_references(page, [ExistingReference(EXPECTED, FILENAME)])
    options.first.wait_for.assert_called_once_with(state="visible", timeout=15000)
    options.nth.assert_called_once_with(0)
    selected.dispatch_event.assert_called_once_with("click", timeout=10000)
    options.dispatch_event.assert_not_called()


def test_duplicate_gallery_filename_wrong_uuid_fails_closed():
    page, options, selected = _page(2)
    with patch(
        "agent.services.flow_browser_semantics.composer_reference_ids",
        side_effect=[[], [WRONG]],
    ):
        with pytest.raises(ValueError, match="REFERENCE_ORDER_MISMATCH"):
            attach_existing_references(page, [ExistingReference(EXPECTED, FILENAME)])
    options.nth.assert_called_once_with(0)
    selected.dispatch_event.assert_called_once()


def test_gallery_ambiguity_is_bounded_not_silently_truncated():
    page, options, selected = _page(5)
    with patch(
        "agent.services.flow_browser_semantics.composer_reference_ids",
        return_value=[],
    ):
        with pytest.raises(ValueError, match="REFERENCE_OPTION_COUNT_UNSUPPORTED"):
            attach_existing_references(page, [ExistingReference(EXPECTED, FILENAME)])
    selected.dispatch_event.assert_not_called()
