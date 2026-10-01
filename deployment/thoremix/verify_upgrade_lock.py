"""Offline .NET/Python lock interop check; never targets the installed application."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def verify(root: Path) -> dict:
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    root = root.resolve()
    if root == Path('D:/StableApp/ThoRemix').resolve():
        raise ValueError('Offline verification must not target the installed application')
    root.mkdir(parents=True, exist_ok=False)
    for name in ('build-manifest.json', 'source/agent/thoremix/core.py', 'runtime/python/python.exe', 'ThoRemix.exe'):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'offline original installed fixture')
    def snapshot():
        return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file() and p.name != 'runner.lock'}
    before = snapshot()
    # An independent python.exe process with no desktop/native launcher owns the
    # same byte used by core.runner_lock. Stdin closure releases it gracefully.
    child_code = """
import msvcrt, pathlib, sys
path = pathlib.Path(sys.argv[1]) / 'data/runner.lock'
path.parent.mkdir(parents=True, exist_ok=True)
with path.open('a+b') as stream:
    stream.write(b'0'); stream.flush(); stream.seek(0)
    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    print('locked', flush=True)
    sys.stdin.readline()
    stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
"""
    shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    if not shell:
        raise RuntimeError('PowerShell is required')
    command = [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
               '-File', str(Path(__file__).with_name('Build-Stable.ps1')), '-Root', str(root), '-LockCheckOnly']
    child = subprocess.Popen([sys.executable, '-u', '-c', child_code, str(root)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert child.stdout.readline().strip() == 'locked'
        blocked = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        assert blocked.returncode != 0
        assert 'bundle upgrade refused' in blocked.stdout + blocked.stderr
        assert snapshot() == before
    finally:
        child.communicate(input='release\n', timeout=10)
    available = subprocess.run(command, capture_output=True, text=True, timeout=30,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    assert available.returncode == 0, available.stderr
    assert snapshot() == before
    return {'blocked_with_python_owner': True, 'files_unchanged': True, 'available_after_release': True}


def verify_staged_validation(stage: Path) -> dict:
    """Execute the build's actual validation block from canonical repo cwd.

    Copies source/media binaries into a temporary stage and uses the installed
    interpreter read-only with bytecode disabled. Never executes the build's
    lease, promotion, scheduler or cleanup paths.
    """
    repo = Path(__file__).resolve().parents[2]
    installed = Path('D:/StableApp/ThoRemix')
    observed_installed = [installed / 'build-manifest.json', installed / 'config/settings.json',
                          installed / 'ThoRemix.exe', *list((installed / 'source').rglob('*.py'))]
    def installed_snapshot():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in observed_installed}
    installed_before = installed_snapshot()
    stage = stage.resolve()
    if stage == installed.resolve() or installed.resolve() in stage.parents:
        raise ValueError('Smoke staging must be outside the installed application')
    stage.mkdir(parents=True, exist_ok=False)
    source = stage / 'source/agent'
    source.mkdir(parents=True)
    shutil.copy2(repo / 'agent/__init__.py', source / '__init__.py')
    shutil.copy2(repo / 'agent/config.py', source / 'config.py')
    shutil.copy2(repo / 'agent/models.json', source / 'models.json')
    shutil.copy2(repo / 'agent/providers.json', source / 'providers.json')
    shutil.copytree(repo / 'agent/thoremix', source / 'thoremix',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for module in ('comicreels','services'):
        shutil.copytree(repo/'agent'/module,source/module,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    local_kat = repo.parent / 'kabin_affiliate_toolkit' / 'src'
    if not local_kat.is_dir():
        raise FileNotFoundError(f'Canonical sibling KAT source is required for staged smoke: {local_kat}')
    binaries = stage / 'runtime/bin'
    binaries.mkdir(parents=True)
    for name in ('ffmpeg.exe', 'ffprobe.exe'):
        shutil.copy2(installed / 'runtime/bin' / name, binaries / name)
    shutil.copy2(installed / 'ThoRemix.exe', stage / 'ThoRemix.exe')
    env = os.environ.copy()
    env.update(PYTHONPATH=os.pathsep.join((str(stage / 'source'), str(local_kat))),
               PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONTZPATH=str(installed / 'runtime/python/Lib/site-packages/tzdata/zoneinfo'),
               THOREMIX_BUILD_ROOT=str(stage / 'settings-target'), THOREMIX_BUILD_STAGE=str(stage),
               THOREMIX_AFF_PROFILE='', THOREMIX_SMOKE_RUNTIME=str(installed / 'runtime/python'),
               THOREMIX_SMOKE_BUILD=str(Path(__file__).with_name('Build-Stable.ps1')))
    # Read and execute exactly the harmless validation assignment and cwd wrapper
    # from Build-Stable.ps1. This tests the actual changed PowerShell code without
    # invoking its deployment transaction or reproducing its import-path logic.
    script = r"""
$ErrorActionPreference = 'Stop'
$stage = $env:THOREMIX_BUILD_STAGE
$runtime = $env:THOREMIX_SMOKE_RUNTIME
$original = (Get-Location).Path
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:THOREMIX_SMOKE_BUILD, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'Build script parse failed' }
$assignment = $ast.Find({param($node) $node -is [Management.Automation.Language.AssignmentStatementAst] -and $node.Left.Extent.Text -eq '$validation'}, $true)
if ($null -eq $assignment) { throw 'Validation assignment absent' }
. ([scriptblock]::Create($assignment.Extent.Text))
$text = [IO.File]::ReadAllText($env:THOREMIX_SMOKE_BUILD)
$start = $text.IndexOf('Push-Location -LiteralPath')
$endMarker = '} finally { Pop-Location }'
$end = $text.IndexOf($endMarker, $start)
if ($start -lt 0 -or $end -lt $start) { throw 'Staged cwd wrapper absent' }
$wrapper = $text.Substring($start, $end - $start + $endMarker.Length)
. ([scriptblock]::Create($wrapper))
if ((Get-Location).Path -ne $original) { throw 'Working directory not restored' }
Write-Output 'staged-validation-passed-and-cwd-restored'
"""
    shell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
    result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
                            cwd=repo, env=env, capture_output=True, text=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'staged-validation-passed-and-cwd-restored' in result.stdout
    assert (stage / 'config/settings.json').is_file()
    assert not (stage / 'settings-target').exists()
    assert installed_snapshot() == installed_before
    return {'staged_validation_passed': True, 'canonical_cwd_restored': True,
            'installed_files_written': False}


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='thoremix-upgrade-test-') as directory:
        action = verify_staged_validation if '--stage-smoke' in sys.argv else verify
        print(json.dumps(action(Path(directory) / 'installed')))
