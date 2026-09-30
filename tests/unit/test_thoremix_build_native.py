import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HELPER = Path(__file__).resolve().parents[2] / "deployment" / "thoremix" / "Native-Build-Step.ps1"


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
def test_native_build_step_allows_stderr_when_exit_zero():
    command = (
        f". '{HELPER}'; "
        "$ErrorActionPreference='Stop'; "
        f"Invoke-ThoRemixNative -FilePath '{Path(sys.executable)}' "
        "-ArgumentList @('-c','import sys; print("warning", file=sys.stderr)') "
        "-FailureMessage 'native failed'; "
        "Write-Output 'PASS'"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "PASS" in result.stdout


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
def test_native_build_step_fails_on_nonzero_exit():
    command = (
        f". '{HELPER}'; "
        "$ErrorActionPreference='Stop'; "
        f"Invoke-ThoRemixNative -FilePath '{Path(sys.executable)}' "
        "-ArgumentList @('-c','import sys; sys.exit(3)') "
        "-FailureMessage 'native failed'; "
        "Write-Output 'UNREACHABLE'"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode != 0
    assert "native failed" in (result.stderr + result.stdout)
    assert "UNREACHABLE" not in result.stdout
