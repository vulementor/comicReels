"""Read-only isolated bundle smoke contract.

This command never acquires a runner lease, creates campaign state, opens a
browser, starts workers, or performs network/database operations.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import multiprocessing
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import webbrowser
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from .config import Settings


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


class SmokeSideEffectBlocked(RuntimeError):
    """A critical import tried to cross a forbidden smoke boundary."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path | str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root)
        return True
    except ValueError:
        return False


def _blocked(kind: str):
    def deny(*_args, **_kwargs):
        raise SmokeSideEffectBlocked("SMOKE_SIDE_EFFECT_BLOCKED:" + kind)
    return deny


def verify_critical_imports(source_root, *, modules=CRITICAL_IMPORTS, importer=importlib.import_module):
    """Import critical modules while hard-blocking external-effect primitives."""
    source_root = Path(source_root).resolve(strict=True)
    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    imported = []
    try:
        with ExitStack() as stack:
            stack.enter_context(patch("socket.create_connection", _blocked("network")))
            stack.enter_context(patch.object(socket.socket, "connect", _blocked("network")))
            stack.enter_context(patch("sqlite3.connect", _blocked("database")))
            stack.enter_context(patch.object(threading.Thread, "start", _blocked("thread")))
            stack.enter_context(patch.object(multiprocessing.Process, "start", _blocked("process")))
            stack.enter_context(patch("subprocess.Popen", _blocked("process")))
            stack.enter_context(patch("subprocess.run", _blocked("process")))
            stack.enter_context(patch("os.system", _blocked("process")))
            stack.enter_context(patch("webbrowser.open", _blocked("browser")))
            stack.enter_context(patch("webbrowser.open_new", _blocked("browser")))
            stack.enter_context(patch("webbrowser.open_new_tab", _blocked("browser")))
            for name in modules:
                module = importer(name)
                module_file = getattr(module, "__file__", None)
                if not module_file or not _inside(module_file, source_root):
                    raise ValueError("SMOKE_IMPORT_OUTSIDE_SOURCE")
                imported.append(name)
    finally:
        sys.dont_write_bytecode = previous_bytecode
    return imported


def _load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        raise ValueError("SMOKE_MANIFEST_INVALID") from None
    if (value.get("schema_version") != 2
            or value.get("stage_only") is not True
            or value.get("promotion_performed") is not False
            or not isinstance(value.get("files"), dict)
            or not value["files"]):
        raise ValueError("SMOKE_STAGE_ONLY_REQUIRED")
    return value


def smoke_bundle(root, *, source_root=None) -> dict:
    """Validate an isolated StageOnly bundle without creating operational state."""
    root = Path(root).resolve(strict=True)
    source_root = Path(source_root).resolve(strict=True) if source_root is not None else (root / "source").resolve(strict=True)
    settings_path = root / "config" / "settings.json"
    manifest_path = root / "build-manifest.json"
    if not settings_path.is_file():
        raise ValueError("SMOKE_SETTINGS_MISSING")
    if not manifest_path.is_file():
        raise ValueError("SMOKE_MANIFEST_MISSING")

    settings_before = _sha256(settings_path)
    manifest_before = _sha256(manifest_path)
    settings = Settings.load(root)
    if (settings.enabled is not False
            or settings.publication_authorized is not False
            or settings.paid_operations_authorized is not False):
        raise ValueError("SMOKE_STAGE_NOT_LOCKED")
    if (not _inside(settings.input_dir, root)
            or not _inside(settings.data, root)
            or not settings.affiliate_profile_dir
            or not _inside(settings.affiliate_profile_dir, root)):
        raise ValueError("SMOKE_STAGE_PATH_ESCAPED")

    manifest = _load_manifest(manifest_path)
    try:
        manifest_stage = Path(manifest["stage_path"]).resolve()
    except (KeyError, TypeError, OSError):
        raise ValueError("SMOKE_MANIFEST_INVALID") from None
    if manifest_stage != root:
        raise ValueError("SMOKE_MANIFEST_ROOT_MISMATCH")

    for relative, expected in manifest["files"].items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("SMOKE_MANIFEST_INVALID")
        candidate = (root / relative).resolve()
        if (not _inside(candidate, root) or not candidate.is_file()
                or _sha256(candidate) != expected.casefold()):
            raise ValueError("SMOKE_MANIFEST_HASH_MISMATCH")

    imported = verify_critical_imports(source_root)
    if _sha256(settings_path) != settings_before:
        raise RuntimeError("SMOKE_SETTINGS_MUTATED")
    if _sha256(manifest_path) != manifest_before:
        raise RuntimeError("SMOKE_MANIFEST_MUTATED")

    return {
        "state": "smoke_ok",
        "root": str(root),
        "manifest_sha256": manifest_before,
        "settings_sha256": settings_before,
        "critical_imports": imported,
        "stage_only": True,
        "paid_operations_authorized": False,
        "publication_authorized": False,
    }
