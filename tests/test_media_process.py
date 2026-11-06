"""Cross-platform regression tests for bounded headless media subprocesses."""
import json
import subprocess
import sys

import pytest

from agent.services.media_process import run_media_command


def test_media_process_lifecycle_and_capture(tmp_path):
    journal = tmp_path / "media.jsonl"
    result = run_media_command(
        [sys.executable, "-c", "print('ready')"],
        timeout=15, check=True, text=True, capture_output=True,
        journal_path=journal,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ready"
    events = [json.loads(row) for row in journal.read_text(encoding="utf-8").splitlines()]
    assert [event["event"] for event in events] == ["started", "finished"]
    assert events[0]["pid"] > 0
    assert events[0]["pid"] == events[1]["pid"]


def test_media_timeout_terminates_process_and_records_receipt(tmp_path):
    journal = tmp_path / "media.jsonl"
    with pytest.raises(subprocess.TimeoutExpired):
        run_media_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.15, text=True, capture_output=True,
            journal_path=journal,
        )
    events = [json.loads(row) for row in journal.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "timeout"
    assert events[-1]["pid"] == events[0]["pid"]


def test_media_failure_preserves_completed_process(tmp_path):
    result = run_media_command(
        [sys.executable, "-c", "import sys; sys.exit(17)"],
        timeout=15, text=True, capture_output=True,
        journal_path=tmp_path / "media.jsonl",
    )
    assert result.returncode == 17
    assert json.loads((tmp_path / "media.jsonl").read_text(encoding="utf-8").splitlines()[-1])["event"] == "failed"
