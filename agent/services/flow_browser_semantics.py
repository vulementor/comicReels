"""Flow-specific composer checks observed on vi-VN Camoufox, 2026-09-27.

These helpers prepare and inspect the visible UI; they never submit generation.
The caller owns the persistent session, paid intent and network observer.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class ExistingReference:
    media_id: str
    file_name: str


def normalized_prompt(value: str) -> str:
    """ProseMirror changes line breaks, but must not change dialogue or punctuation."""
    return " ".join(value.split())


def _validate_references(images: list[ExistingReference]) -> None:
    # Four ordered ingredients were observed together in the native composer.
    # Larger sets need their own live capability evidence; never truncate a story.
    if not 1 <= len(images) <= 4 or len({x.media_id for x in images}) != len(images):
        raise ValueError("REFERENCE_COUNT_OR_DUPLICATE")
    for image in images:
        if str(UUID(image.media_id)) != image.media_id or not image.file_name.strip():
            raise ValueError("INVALID_REFERENCE")


def image_id_from_composer_url(url: str) -> str:
    parsed = urlsplit(url)
    parts = parsed.path.split("/")
    if (parsed.scheme != "https" or parsed.hostname != "flow-content.google"
            or len(parts) != 3 or parts[1] != "image"):
        raise ValueError("UNVERIFIED_REFERENCE_URL")
    media_id = parts[2]
    if str(UUID(media_id)) != media_id:
        raise ValueError("INVALID_REFERENCE_ID")
    return media_id


def composer_reference_ids(page) -> list[str]:
    # Query strings contain signed URLs. Keep them in memory and return only UUIDs.
    chips = page.get_by_role("button", name="Thành phần", exact=True)
    sources = chips.evaluate_all("""nodes => nodes.map(n => {
        const image = n.querySelector('img');
        return n.getAttribute('aria-busy') === 'true' || !image ? null : image.src;
    })""")
    if any(not source for source in sources):
        raise ValueError("REFERENCES_NOT_READY")
    return [image_id_from_composer_url(source) for source in sources]


def verify_reference_composer(page, project_id: str,
                              images: list[ExistingReference], prompt: str) -> dict:
    _validate_references(images)
    if not prompt.strip():
        raise ValueError("EMPTY_PROMPT")
    location = urlsplit(page.url)
    if (location.scheme != "https" or location.hostname != "flow.google.com"
            or location.path != f"/project/{UUID(project_id)!s}"):
        raise ValueError("PROJECT_MISMATCH")
    refs = composer_reference_ids(page)
    if refs != [image.media_id for image in images]:
        raise ValueError("REFERENCE_ORDER_MISMATCH")
    editor = page.locator("div.ProseMirror")
    if editor.count() != 1 or normalized_prompt(editor.inner_text()) != normalized_prompt(prompt):
        raise ValueError("PROMPT_MISMATCH")
    return {"project_id": project_id, "ordered_reference_ids": refs,
            "prompt_sha256": hashlib.sha256(normalized_prompt(prompt).encode()).hexdigest()}


def attach_existing_references(page, images: list[ExistingReference]) -> None:
    """Select filenames, then verify UUIDs; never infer order from the recent grid.

    An option's Enter handler can confirm the previous preview. The observed click
    handler selects the requested preview; verify it before confirming the picker.
    """
    _validate_references(images)
    if composer_reference_ids(page):
        raise ValueError("COMPOSER_REFERENCES_NOT_EMPTY")
    for index, image in enumerate(images):
        page.get_by_role("button", name="Thêm thành phần vào ô nhập câu lệnh", exact=True).press(
            "Enter", timeout=10000)
        option = page.get_by_role("option", name=f"{image.file_name} Hình ảnh", exact=True)
        # The asset picker can contain multiple native uploads under the same
        # filename. Resolve strict-locator ambiguity without trusting the
        # filename: composer_reference_ids MUST verify the exact media UUID
        # against the saved upload receipt before any provider Generate.
        option.first.wait_for(state="visible", timeout=15000)
        count = option.count()
        if not 1 <= count <= 4:
            raise ValueError("REFERENCE_OPTION_COUNT_UNSUPPORTED")
        selected = option.nth(0) if count > 1 else option
        selected.dispatch_event("click", timeout=10000)
        confirm = page.get_by_role("button", name="Thêm vào câu lệnh", exact=True)
        preview = page.get_by_role("img", name=f"Bản xem trước của {image.file_name}", exact=True)
        expected = [x.media_id for x in images[:index + 1]]
        deadline = time.monotonic() + 15
        confirmed = False
        # Picker rendering can be asynchronous; wait for either auto-attachment
        # or this image's preview and confirmation, never an instantaneous branch.
        while time.monotonic() < deadline:
            try:
                actual = composer_reference_ids(page)
            except ValueError as exc:
                if str(exc) != "REFERENCES_NOT_READY":
                    raise
                actual = None
            if actual == expected:
                break
            if actual is not None and actual != expected[:-1]:
                raise ValueError("REFERENCE_ORDER_MISMATCH")
            if not confirmed and confirm.is_visible() and preview.is_visible():
                confirm.press("Enter", timeout=10000)
                confirmed = True
            page.wait_for_timeout(100)
        else:
            raise TimeoutError("REFERENCE_ATTACH_TIMEOUT")


def highest_video_download(labels: list[str]) -> str:
    options = []
    for label in labels:
        if "gif" in label.casefold():
            continue
        match = re.match(r"^(\d{3,4})p(?:\s|$)", label)
        if not match:
            raise ValueError("UNKNOWN_DOWNLOAD_RESOLUTION")
        options.append((int(match[1]), label))
    if not options:
        raise ValueError("NO_VIDEO_DOWNLOAD")
    return max(options, key=lambda item: item[0])[1]
