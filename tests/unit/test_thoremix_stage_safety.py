import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent.thoremix.config import Settings, isolated_stage_settings
from agent.thoremix.story_operations import StoryOperations


REPO_ROOT = Path(__file__).resolve().parents[2]
START_PY = REPO_ROOT / "deployment" / "thoremix" / "start.py"


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

    settings = isolated_stage_settings(stage)

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
    settings = isolated_stage_settings(stage)
    operations = StoryOperations(settings, runtime=object())
    work = tmp_path / "work"

    result = operations._run(stage_name, {}, work, lambda *_: None)

    assert result == {
        "state": "blocked",
        "not_submitted": True,
        "reason": "PAID_OPERATIONS_LOCKED",
    }
    assert not work.exists()
