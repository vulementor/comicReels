from pathlib import Path
import json

import pytest

from agent.comicreels.image_history import (
    conversation_id_from_url,
    find_project_artifact_by_sha256,
    image_history_decision,
)
from agent.comicreels.images import sha256_file


def _write_manifest(root: Path, conversation_id: str, panels: list[dict]):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{conversation_id}.image-history.json"
    path.write_text(
        json.dumps(
            {
                "schema": "comicreels.conversation-image-history.v1",
                "conversation_id": conversation_id,
                "panels": panels,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_conversation_id_from_url():
    assert conversation_id_from_url("https://chatgpt.com/c/abc-123") == "abc-123"


def test_history_decision_reads_accepted_and_rejected_candidates(tmp_path):
    conversation_id = "abc-123"
    history_dir = tmp_path / "history"
    _write_manifest(
        history_dir,
        conversation_id,
        [
            {
                "panel_index": 1,
                "state": "accepted_existing_output",
                "candidates": [
                    {
                        "output_message_id": "msg-good",
                        "artifact_sha256": "a" * 64,
                        "width": 941,
                        "height": 1672,
                        "verdict": "accepted",
                    },
                    {
                        "output_message_id": "msg-bad",
                        "artifact_sha256": "b" * 64,
                        "verdict": "rejected",
                    },
                ],
            }
        ],
    )

    decision = image_history_decision(
        f"https://chatgpt.com/c/{conversation_id}",
        1,
        history_dir=history_dir,
    )

    assert decision.present is True
    assert decision.state == "accepted_existing_output"
    assert decision.accepted_sha256 == "a" * 64
    assert decision.accepted_output_message_id == "msg-good"
    assert decision.accepted_width == 941
    assert decision.accepted_height == 1672
    assert decision.rejected_sha256 == frozenset({"b" * 64})


def test_history_decision_without_manifest_is_non_blocking(tmp_path):
    decision = image_history_decision(
        "https://chatgpt.com/c/no-history",
        0,
        history_dir=tmp_path / "missing",
    )

    assert decision.present is False
    assert decision.accepted_sha256 is None
    assert decision.rejected_sha256 == frozenset()


def test_history_decision_rejects_multiple_accepted_outputs(tmp_path):
    history_dir = tmp_path / "history"
    _write_manifest(
        history_dir,
        "abc",
        [
            {
                "panel_index": 0,
                "candidates": [
                    {"artifact_sha256": "a" * 64, "verdict": "accepted"},
                    {"artifact_sha256": "b" * 64, "verdict": "accepted"},
                ],
            }
        ],
    )

    with pytest.raises(RuntimeError, match="multiple accepted"):
        image_history_decision(
            "https://chatgpt.com/c/abc",
            0,
            history_dir=history_dir,
        )


def test_find_project_artifact_by_sha256(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    image = project / "nested" / "artifact.png"
    image.parent.mkdir()
    image.write_bytes(b"not-a-real-png-but-hash-search-does-not-decode")

    found = find_project_artifact_by_sha256(project, sha256_file(image))

    assert found == image.resolve()
