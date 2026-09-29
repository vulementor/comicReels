from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


_REPO_ROOT = Path(__file__).resolve().parents[2]
_HISTORY_DIR = _REPO_ROOT / "research" / "conversations"
_SCHEMA = "comicreels.conversation-image-history.v1"


@dataclass(frozen=True)
class ImageHistoryDecision:
    present: bool
    state: str | None
    accepted_sha256: str | None
    accepted_output_message_id: str | None
    accepted_width: int | None
    accepted_height: int | None
    rejected_sha256: frozenset[str]
    manifest_path: Path | None


def conversation_id_from_url(conversation_url: str) -> str:
    parsed = urlparse(str(conversation_url or "").strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[-2] != "c" or not parts[-1]:
        raise ValueError("invalid ChatGPT conversation URL")
    return parts[-1]


def _manifest_path(
    conversation_url: str,
    *,
    history_dir: Path | None = None,
) -> Path:
    conversation_id = conversation_id_from_url(conversation_url)
    root = Path(history_dir) if history_dir is not None else _HISTORY_DIR
    return root / f"{conversation_id}.image-history.json"


def image_history_decision(
    conversation_url: str,
    panel_index: int,
    *,
    history_dir: Path | None = None,
) -> ImageHistoryDecision:
    path = _manifest_path(conversation_url, history_dir=history_dir)
    if not path.is_file():
        return ImageHistoryDecision(
            present=False,
            state=None,
            accepted_sha256=None,
            accepted_output_message_id=None,
            accepted_width=None,
            accepted_height=None,
            rejected_sha256=frozenset(),
            manifest_path=None,
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("Conversation image-history manifest is unreadable.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
        raise RuntimeError("Conversation image-history manifest schema is invalid.")

    conversation_id = conversation_id_from_url(conversation_url)
    if str(payload.get("conversation_id") or "") != conversation_id:
        raise RuntimeError("Conversation image-history manifest targets a different conversation.")

    panels = payload.get("panels")
    if not isinstance(panels, list):
        raise RuntimeError("Conversation image-history manifest has no panels list.")
    row = next(
        (
            item
            for item in panels
            if isinstance(item, dict) and int(item.get("panel_index", -1)) == int(panel_index)
        ),
        None,
    )
    if row is None:
        return ImageHistoryDecision(
            present=True,
            state="panel_not_recorded",
            accepted_sha256=None,
            accepted_output_message_id=None,
            accepted_width=None,
            accepted_height=None,
            rejected_sha256=frozenset(),
            manifest_path=path,
        )

    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError("Conversation image-history panel candidates are invalid.")

    accepted = [
        item for item in candidates
        if isinstance(item, dict) and str(item.get("verdict") or "") == "accepted"
    ]
    if len(accepted) > 1:
        raise RuntimeError("Conversation image-history has multiple accepted outputs for one panel.")

    rejected = frozenset(
        str(item.get("artifact_sha256") or "")
        for item in candidates
        if isinstance(item, dict)
        and str(item.get("verdict") or "") == "rejected"
        and str(item.get("artifact_sha256") or "")
    )

    accepted_sha256 = None
    accepted_output_message_id = None
    accepted_width = None
    accepted_height = None
    if accepted:
        accepted_sha256 = str(accepted[0].get("artifact_sha256") or "").strip() or None
        accepted_output_message_id = (
            str(accepted[0].get("output_message_id") or "").strip() or None
        )
        try:
            accepted_width = int(accepted[0].get("width") or 0) or None
            accepted_height = int(accepted[0].get("height") or 0) or None
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Accepted historical output dimensions are invalid.") from exc
        if accepted_sha256 is None:
            raise RuntimeError("Accepted historical output is missing artifact sha256.")

    return ImageHistoryDecision(
        present=True,
        state=str(row.get("state") or "") or None,
        accepted_sha256=accepted_sha256,
        accepted_output_message_id=accepted_output_message_id,
        accepted_width=accepted_width,
        accepted_height=accepted_height,
        rejected_sha256=rejected,
        manifest_path=path,
    )


def find_project_artifact_by_sha256(project_root: Path, expected_sha256: str) -> Path | None:
    expected = str(expected_sha256 or "").strip().lower()
    if len(expected) != 64:
        raise ValueError("expected sha256 must be a 64-character hex digest")
    from agent.comicreels.images import sha256_file

    for suffix in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for path in project_root.rglob(suffix):
            if not path.is_file():
                continue
            try:
                if sha256_file(path).lower() == expected:
                    return path.resolve()
            except OSError:
                continue
    return None


__all__ = [
    "ImageHistoryDecision",
    "conversation_id_from_url",
    "find_project_artifact_by_sha256",
    "image_history_decision",
]
