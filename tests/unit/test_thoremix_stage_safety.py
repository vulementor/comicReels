import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.thoremix import config as thoremix_config
from agent.thoremix.config import Settings
from agent.thoremix.story_operations import StoryOperations


REPO_ROOT = Path(__file__).resolve().parents[2]
START_PY = REPO_ROOT / "deployment" / "thoremix" / "start.py"


def _isolated_settings(stage: Path):
    helper = getattr(thoremix_config, "isolated_stage_settings", None)
    assert callable(helper), "isolated_stage_settings must exist for StageOnly bundles"
    return helper(stage)


def _fake_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    app = bundle / "app"
    package = bundle / "source" / "agent" / "thoremix"
    app.mkdir(parents=True)
    package.mkdir(parents=True)
    shutil.copyfile(START_PY, app / "start.py")
    (bundle / "source" / "agent" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text(
        "import json\n"
        "from pathlib import Path\n"
        "def main(argv):\n"
        "    root = Path(argv[1])\n"
        "    (root / 'seen-argv.json').write_text(json.dumps(argv), encoding='utf-8')\n"
        "    return 0\n",
        encoding="utf-8",
    )
    return bundle


def _run_entrypoint(bundle: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    completed = subprocess.run(
        [sys.executable, str(bundle / "app" / "start.py"), *args],
        cwd=bundle,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    seen = json.loads((bundle / "seen-argv.json").read_text(encoding="utf-8"))
    return completed, seen


def test_installed_entrypoint_preserves_top_level_help_without_log_side_effect(tmp_path):
    bundle = _fake_bundle(tmp_path)

    completed, seen = _run_entrypoint(bundle, "--help")

    assert completed.returncode == 0
    assert seen == ["--root", str(bundle.resolve()), "--help"]
    assert not (bundle / "logs").exists()


def test_installed_entrypoint_keeps_legacy_double_dash_desktop_compatibility(tmp_path):
    bundle = _fake_bundle(tmp_path)

    completed, seen = _run_entrypoint(bundle, "--desktop")

    assert completed.returncode == 0
    assert seen == ["--root", str(bundle.resolve()), "desktop"]


def test_isolated_stage_settings_are_stage_local_disabled_and_paid_locked(tmp_path):
    stage = (tmp_path / "stage").resolve()

    settings = _isolated_settings(stage)

    assert settings.directory == stage
    assert Path(settings.input_dir).resolve().is_relative_to(stage)
    assert settings.data.is_relative_to(stage)
    assert Path(settings.affiliate_profile_dir).resolve().is_relative_to(stage)
    assert settings.enabled is False
    assert settings.publication_authorized is False
    assert settings.paid_operations_authorized is False
    settings.validate()


def test_default_settings_preserve_non_stage_paid_semantics(tmp_path):
    settings = Settings(root=str((tmp_path / "live").resolve()))

    assert settings.paid_operations_authorized is True
    assert settings.publication_authorized is True


@pytest.mark.parametrize("stage_name", ["images", "video", "highest"])
def test_paid_story_stages_fail_closed_before_runtime_or_filesystem_use(tmp_path, stage_name):
    stage = (tmp_path / "stage").resolve()
    settings = _isolated_settings(stage)
    operations = StoryOperations(settings, runtime=object())
    work = tmp_path / "work"

    result = operations._run(stage_name, {}, work, lambda *_: None)

    assert result == {
        "state": "blocked",
        "not_submitted": True,
        "reason": "PAID_OPERATIONS_LOCKED",
    }
    assert not work.exists()


def test_installed_entrypoint_smoke_has_no_launcher_log_side_effect(tmp_path):
    bundle = _fake_bundle(tmp_path)

    completed, seen = _run_entrypoint(bundle, "smoke")

    assert completed.returncode == 0
    assert seen == ["--root", str(bundle.resolve()), "smoke"]
    assert not (bundle / "logs").exists()


def test_paid_authorized_image_unknown_receipt_does_not_resubmit(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    settings = Settings(root=str((tmp_path / "live").resolve()))
    client = MagicMock()
    operations = StoryOperations(settings, runtime=SimpleNamespace(client=lambda: client))
    work = tmp_path / "work"
    images = work / "images"
    images.mkdir(parents=True)
    receipt = images / "provider.json"
    receipt.write_text(json.dumps({"state": "uncertain", "conversation_url": "https://example.invalid/existing"}), encoding="utf-8")
    before = receipt.read_bytes()

    result = operations._run(
        "images",
        {"source": str(tmp_path / "source.png")},
        work,
        lambda *_: None,
    )

    assert settings.paid_operations_authorized is True
    assert result == {"state": "uncertain", "reason": "BATCH_INCOMPLETE"}
    assert receipt.read_bytes() == before
    client.image.generate_batch.assert_not_called()


@pytest.mark.parametrize("stage_name", ["images", "video", "highest"])
def test_paid_lock_during_unknown_reconcile_preserves_checkpoint_and_never_resubmits(
    tmp_path, monkeypatch, stage_name
):
    from types import SimpleNamespace

    import agent.services.flow_story_browser as flow_story_browser
    import agent.thoremix.story_operations as story_operations
    from agent.thoremix.story_stages import StageBlocked, StageJournal, StageUncertain

    source = tmp_path / "source.png"
    source.write_bytes(b"source")
    directory = tmp_path / "journal"
    request = {
        "source": str(source),
        "source_sha256": "a" * 64,
        "analysis": {"panels": [{}]},
    }
    progress_checkpoint = {
        "conversation_url": "https://chatgpt.com/c/existing",
        "run_id": "rid-existing",
    }
    journal = StageJournal(directory, source_sha256="a" * 64)

    def seed_unknown(progress):
        progress(progress_checkpoint)
        return {"state": "uncertain", "reason": "REMOTE_RESULT_UNKNOWN"}

    with pytest.raises(StageUncertain):
        journal.run(stage_name, request, seed_unknown)

    if stage_name == "images":
        assert not (directory / "images" / "provider.json").exists()

    counters = {"new_submit": 0, "reconcile": 0}

    class Result:
        def __init__(self, payload):
            self.payload = payload

        def model_dump(self, mode="json"):
            assert mode == "json"
            return dict(self.payload)

    class ImageClient:
        def generate_batch(self, *_args, **_kwargs):
            counters["new_submit"] += 1
            return Result({
                "state": "uncertain",
                "conversation_url": progress_checkpoint["conversation_url"],
            })

        def reconcile_batch(self, url, **_kwargs):
            counters["reconcile"] += 1
            assert url == progress_checkpoint["conversation_url"]
            return Result({"state": "uncertain", "conversation_url": url})

    client = SimpleNamespace(image=ImageClient())
    runtime = SimpleNamespace(
        client=lambda: client,
        chat_profile_dir=tmp_path / "chat-profile",
        chat_home=tmp_path / "chat-home",
        chat_min_interval_s=0,
        chat_rest_after_response_s=0,
    )
    settings = SimpleNamespace(
        paid_operations_authorized=False,
        path=tmp_path / "missing-settings.json",
        directory=tmp_path,
        data=tmp_path / "data",
    )

    class DirectPacer:
        def __init__(self, *_args, **_kwargs):
            pass

        def call(self, operation):
            return operation()

    monkeypatch.setattr(story_operations, "ChatPacer", DirectPacer)

    class FakeFlowStoryBrowser:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self, _name, _request, _directory, _progress, *, reconcile=False):
            if reconcile:
                counters["reconcile"] += 1
            else:
                counters["new_submit"] += 1
            return {"state": "uncertain", "reason": "REMOTE_RESULT_UNKNOWN"}

    monkeypatch.setattr(flow_story_browser, "FlowStoryBrowser", FakeFlowStoryBrowser)
    operations = StoryOperations(settings, runtime=runtime)

    def execute(progress):
        return operations.execute(stage_name, request, directory, progress)

    def reconcile(previous, progress):
        return operations.reconcile(stage_name, request, directory, previous, progress)

    locked_error = None
    try:
        journal.run(stage_name, request, execute, reconcile=reconcile)
    except (StageUncertain, StageBlocked) as exc:
        locked_error = type(exc).__name__
    locked_record = json.loads((directory / f"{stage_name}.json").read_text(encoding="utf-8"))

    settings.paid_operations_authorized = True
    with pytest.raises(StageUncertain):
        journal.run(stage_name, request, execute, reconcile=reconcile)
    final_record = json.loads((directory / f"{stage_name}.json").read_text(encoding="utf-8"))

    assert counters["new_submit"] == 0
    assert counters["reconcile"] >= 1
    assert locked_error == "StageUncertain"
    assert locked_record["state"] == "UNKNOWN"
    assert locked_record["progress"] == progress_checkpoint
    assert locked_record["result"]["state"] == "uncertain"
    assert locked_record["result"]["reason"] == "REMOTE_RESULT_UNKNOWN"
    assert "not_submitted" not in locked_record["result"]
    assert final_record["state"] == "UNKNOWN"
    assert final_record["progress"] == progress_checkpoint
