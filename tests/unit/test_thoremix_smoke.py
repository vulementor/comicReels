import hashlib
import importlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.thoremix.config import isolated_stage_settings


REPO_ROOT = Path(__file__).resolve().parents[2]
CRITICAL_IMPORTS = (
    "agent.thoremix.core",
    "agent.thoremix.desktop",
    "agent.thoremix.producer",
    "agent.thoremix.publishing",
    "agent.thoremix.affiliate",
    "agent.thoremix.story_operations",
    "agent.services.flow_browser_session",
    "agent.services.flow_story_browser",
)


def _smoke_module():
    try:
        return importlib.import_module("agent.thoremix.smoke")
    except ModuleNotFoundError:
        pytest.fail("agent.thoremix.smoke must provide the official side-effect-free smoke contract")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_stage(stage: Path) -> tuple[Path, Path]:
    stage.mkdir()
    shutil.copytree(REPO_ROOT / "agent", stage / "source" / "agent")
    settings = isolated_stage_settings(stage)
    settings.save()
    probe = stage / "probe.txt"
    probe.write_text("immutable-stage-probe", encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "source_commit": "a" * 40,
        "validated_base": "b" * 40,
        "source_state": "clean",
        "stage_only": True,
        "promotion_performed": False,
        "stage_path": str(stage.resolve()),
        "dependencies": {},
        "files": {"probe.txt": _sha(probe)},
        "ai_provider": "gpt_fullproxy",
    }
    manifest_path = stage / "build-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings.path, manifest_path


def _snapshot(root: Path) -> dict[str, tuple[str, str | None]]:
    rows = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        rows[relative] = ("dir", None) if path.is_dir() else ("file", _sha(path))
    return rows


def test_official_smoke_cli_is_read_only_and_reports_critical_imports(tmp_path):
    stage = tmp_path / "stage"
    settings_path, manifest_path = _write_stage(stage)
    before = _snapshot(stage)
    manifest_before = _sha(manifest_path)
    settings_before = _sha(settings_path)
    env = dict(
        os.environ,
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPATH=str(stage / "source"),
    )

    completed = subprocess.run(
        [sys.executable, "-m", "agent.thoremix.cli", "--root", str(stage), "smoke"],
        cwd=stage,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["state"] == "smoke_ok"
    assert payload["root"] == str(stage.resolve())
    assert tuple(payload["critical_imports"]) == CRITICAL_IMPORTS
    assert payload["manifest_sha256"] == manifest_before
    assert _sha(manifest_path) == manifest_before
    assert _sha(settings_path) == settings_before
    assert _snapshot(stage) == before
    for forbidden in ("logs", "data", "profiles"):
        assert not (stage / forbidden).exists()


@pytest.mark.parametrize(
    "effect",
    [
        lambda: socket.create_connection(("127.0.0.1", 9), timeout=0.01),
        lambda: sqlite3.connect(":memory:"),
        lambda: threading.Thread(target=lambda: None).start(),
        lambda: subprocess.Popen([sys.executable, "-c", "pass"]),
    ],
    ids=("network", "database", "thread", "process"),
)
def test_critical_import_guard_blocks_external_effects(tmp_path, effect):
    smoke = _smoke_module()
    source_root = REPO_ROOT.resolve()

    def importer(_):
        effect()
        return SimpleNamespace(__file__=str(source_root / "agent" / "thoremix" / "config.py"))

    with pytest.raises(smoke.SmokeSideEffectBlocked, match="SMOKE_SIDE_EFFECT_BLOCKED"):
        smoke.verify_critical_imports(
            source_root,
            modules=("probe.module",),
            importer=importer,
        )


def test_smoke_rejects_non_stage_manifest_without_mutation(tmp_path):
    smoke = _smoke_module()
    stage = tmp_path / "stage"
    _, manifest_path = _write_stage(stage)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stage_only"] = False
    manifest["promotion_performed"] = True
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = _snapshot(stage)

    with pytest.raises(ValueError, match="SMOKE_STAGE_ONLY_REQUIRED"):
        smoke.smoke_bundle(stage, source_root=REPO_ROOT)

    assert _snapshot(stage) == before
