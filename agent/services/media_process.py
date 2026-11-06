"""Run media tools without Windows consoles; bound and journal their lifecycle."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import time
from datetime import datetime, timezone

_LOG = logging.getLogger(__name__)


def run_media_command(
    args, *, timeout, cwd=None, check=False, capture_output=False,
    text=False, stdout=None, stderr=None, journal_path=None,
):
    """Return CompletedProcess, with a bounded process tree and optional JSONL receipt.

    The journal contains lifecycle metadata rather than command arguments, which
    may include private input paths or credentials.
    """
    if timeout is None or timeout <= 0:
        raise ValueError("media command requires a positive timeout")
    if capture_output and (stdout is not None or stderr is not None):
        raise ValueError("capture_output is incompatible with stdout/stderr")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    popen_args = {
        "cwd": cwd,
        "text": text,
        "stdout": subprocess.PIPE if capture_output else stdout,
        "stderr": subprocess.PIPE if capture_output else stderr,
        "creationflags": flags,
        "start_new_session": os.name != "nt",
    }
    process = subprocess.Popen(args, **popen_args)
    started = time.monotonic()
    executable = Path(str(args[0])).name
    _LOG.info("media_started executable=%s pid=%d timeout_s=%s", executable, process.pid, timeout)

    def record(state, returncode=None, error=None):
        data = {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "event": state,
            "executable": executable,
            "pid": process.pid,
            "timeout_s": timeout,
            "elapsed_s": round(time.monotonic() - started, 3),
            "returncode": returncode,
        }
        if error:
            data["error_tail"] = str(error)[-512:]
        if journal_path:
            try:
                path = Path(journal_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(data, ensure_ascii=False) + "\n")
            except OSError as exc:
                _LOG.warning("media_journal_write_failed pid=%d reason=%s", process.pid, type(exc).__name__)
        level = logging.ERROR if state in ("timeout", "failed") else logging.INFO
        _LOG.log(level, "media_%s executable=%s pid=%d returncode=%s elapsed_s=%.3f",
                 state, executable, process.pid, returncode, data["elapsed_s"])

    record("started")
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=flags, timeout=15, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                _LOG.warning("media_taskkill_failed pid=%d", process.pid)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _LOG.error("media_pipe_drain_timeout pid=%d", process.pid)
        record("timeout", process.poll(), "timeout")
        raise

    result = subprocess.CompletedProcess(args, process.returncode, out, err)
    if result.returncode != 0:
        tail = err.decode("utf-8", "replace") if isinstance(err, bytes) else err
        record("failed", result.returncode, tail)
    else:
        record("finished", result.returncode)
    if check:
        result.check_returncode()
    return result
