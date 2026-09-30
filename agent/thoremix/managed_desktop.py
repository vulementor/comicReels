"""ThoRemix desktop children launched through retained Stable Runtime contracts.

No scheduler, subprocess shell, provider fallback or implicit action retry lives here.
"""
from __future__ import annotations

import contextlib
import io
import json
import time
import uuid
from pathlib import Path

COMMANDS = frozenset({
    "status", "login", "auth-status", "affiliate", "configure-facebook",
    "pause", "resume", "configure-production", "produce-ahead", "produce-one",
    "dispatch", "tick", "reconcile-production", "resume-quality-stops",
    "retry-production", "review-analysis", "review-image-order", "retry-failed", "finish-unpublished", "repair-audio",
    "repair-audio-all", "repair-source-text", "prepare-media-correction",
    "approve-correction", "cleanup-tiktok-stale-editor", "approve",
    "import-source", "reconcile-package", "publish", "publish-platform",
    "finalize", "prepare-package",
})
REQUEST_KEY = "desktop_command"
TERMINAL = {"STOPPED", "FAILED", "RECONCILE_REQUIRED"}


def validate_command(command, arguments):
    if (type(command) is not str or command not in COMMANDS
            or type(arguments) not in (list, tuple) or len(arguments) > 32):
        raise ValueError("DESKTOP_COMMAND_UNAVAILABLE")
    if any(type(arg) is not str or not arg or len(arg) > 4096 or "\0" in arg
           or arg in {"--root", "--help", "-h"} or arg.startswith("--root=")
           for arg in arguments):
        raise ValueError("INVALID_DESKTOP_ARGUMENTS")
    if sum(len(arg) for arg in arguments) > 8192:
        raise ValueError("INVALID_DESKTOP_ARGUMENTS")
    return list(arguments)


def _platform():
    from stable_toolkit_runtime.context import atomic_json
    from stable_toolkit_runtime.instances import Deployment, prepare_deployment
    from stable_toolkit_runtime.launcher import start_host
    from stable_toolkit_runtime.lifecycle import inspect_instance
    from stable_toolkit_runtime.registry import Registry, canonical, json_bytes
    return (atomic_json, Deployment, prepare_deployment, start_host,
            inspect_instance, Registry, canonical, json_bytes)


def desktop_namespace(binding):
    return "|".join((binding.consumer_kind, binding.consumer_name,
                     binding.instance_id, str(binding.home).casefold()))


class ManagedCommandRunner:
    def __init__(self, context):
        self.context = context
        self.deployment = context.deployment().require_application("thoremix")
        if context.entrypoint not in {"desktop", "desktop-smoke"}:
            raise ValueError("DESKTOP_PARENT_REQUIRED")
        self.last_result = None

    def __call__(self, command, *arguments):
        arguments = validate_command(command, arguments)
        if self.context.is_draining():
            raise ValueError("DESKTOP_DRAINING")
        (write, Deployment, prepare, start, inspect, Registry, canonical, read) = _platform()
        value = self.deployment.as_dict()
        if value["entries"].get("desktop-command") != "desktop-command":
            raise ValueError("DESKTOP_CHILD_ENTRY_REQUIRED")
        if REQUEST_KEY in value["settings"]:
            raise ValueError("NESTED_DESKTOP_COMMAND")
        child_id = "tho-command-" + uuid.uuid4().hex
        request = {
            "schema": "thoremix.desktop.command.v1", "command": command, "arguments": arguments,
            "parent": self.context.identity, "child_launch_id": child_id,
            "deployment_instance_id": self.deployment.instance_id,
            "release_id": value["release_id"],
        }
        value["settings"] = {**value["settings"], REQUEST_KEY: request}
        retained = Deployment(self.deployment.root, canonical(value))
        spec = prepare(Registry(self.deployment.root), retained, "desktop-command", launch_id=child_id)
        path = self.context.instance_dir / "desktop-commands" / (child_id + ".json")
        receipt = {"schema": "thoremix.desktop.dispatch.v1", **request, "status": "START_REQUESTED"}
        write(path, receipt)
        # An ambiguous start is retained, never retried here.
        try:
            started = start(spec).as_dict()
        except Exception as error:
            receipt.update(status="START_UNCERTAIN", error_type=type(error).__name__)
            write(path, receipt)
            self.last_result = receipt
            raise
        receipt.update(status="STARTED", host=started)
        write(path, receipt)
        if started["status"] == "FAILED":
            receipt.update(status="FAILED")
            write(path, receipt)
            self.last_result = receipt
            return 2, json.dumps({"state": "needs_input", "reason": "DESKTOP_CHILD_START_FAILED"})
        while True:
            observed = inspect(self.deployment.root, child_id)
            if (observed.get("instance_id") != child_id
                    or observed.get("release_id") != value["release_id"]):
                raise ValueError("DESKTOP_CHILD_IDENTITY_MISMATCH")
            if observed["status"] in TERMINAL and not observed.get("process_alive"):
                break
            time.sleep(0.25)
        result_path = self.deployment.root / "state/jobs/launches" / child_id / "app-result.json"
        try:
            result = read(result_path, limit=1024 * 1024)
        except Exception as error:
            receipt.update(status=observed["status"], host=observed,
                           error="DESKTOP_CHILD_RESULT_UNAVAILABLE", error_type=type(error).__name__)
            write(path, receipt)
            self.last_result = receipt
            return 2, json.dumps({"state": "needs_input", "reason": "DESKTOP_CHILD_RESULT_UNAVAILABLE"})
        if (result.get("schema") != "thoremix.desktop.command-result.v1"
                or result.get("request") != request
                or result.get("child", {}).get("instance_id") != child_id
                or result.get("child", {}).get("release_id") != value["release_id"]):
            raise ValueError("DESKTOP_CHILD_RESULT_MISMATCH")
        receipt.update(status=observed["status"], host=observed, result=result)
        write(path, receipt)
        self.last_result = receipt
        code = result["exit_code"]
        if type(code) is not int or code not in (0, 2) or type(result["stdout"]) is not str:
            raise ValueError("INVALID_DESKTOP_RESULT")
        if observed["status"] != "STOPPED":
            code = 2
        return code, result["stdout"]


class _Output(io.StringIO):
    """Match the existing desktop's bounded diagnostic tail."""
    def write(self, value):
        written = super().write(value)
        if self.tell() > 32768:
            tail = self.getvalue()[-32768:]
            self.seek(0)
            self.truncate(0)
            super().write(tail)
        return written


def run_child_command(context, binding):
    write, *_ = _platform()
    deployment = context.deployment().require_application("thoremix")
    value = deployment.as_dict()
    request = deployment.settings.get(REQUEST_KEY)
    expected = {"schema", "command", "arguments", "parent", "child_launch_id",
                "deployment_instance_id", "release_id"}
    if (type(request) is not dict or set(request) != expected
            or request["schema"] != "thoremix.desktop.command.v1"
            or request["child_launch_id"] != context.identity["instance_id"]
            or request["deployment_instance_id"] != deployment.instance_id
            or request["release_id"] != context.identity["release_id"]
            or type(request["parent"]) is not dict
            or request["parent"].get("release_id") != request["release_id"]
            or request["parent"].get("consumer_id") != context.identity["consumer_id"]):
        raise ValueError("INVALID_DESKTOP_COMMAND_BINDING")
    arguments = validate_command(request["command"], request["arguments"])
    output = _Output()
    code = 2
    result = {"schema": "thoremix.desktop.command-result.v1", "request": request,
              "child": context.identity, "home": str(deployment.home)}
    with context.job("desktop-command"):
        try:
            from agent.private_runtime import install_private_runtime
            install_private_runtime(binding)
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                from agent.thoremix.cli import main
                code = main(["--root", str(deployment.home), request["command"], *arguments])
            if code not in (0, 2):
                code = 2
        except Exception as error:
            output.write(json.dumps({"state": "needs_input", "error_type": type(error).__name__}))
            raise
        finally:
            result.update(exit_code=code, stdout=output.getvalue())
            write(context.instance_dir / "app-result.json", result)
        if code != 0:
            raise RuntimeError("DESKTOP_COMMAND_FAILED")
    return 0


def reserve_smoke_source(context, binding, settings):
    """Only the explicit smoke entry may create one idempotent local reservation."""
    if context.entrypoint != "desktop-smoke":
        raise ValueError("SMOKE_ENTRY_REQUIRED")
    requested = context.deployment().settings.get("smoke_source")
    if requested is None:
        return None
    if type(requested) is not str:
        raise ValueError("INVALID_SMOKE_SOURCE")
    directory = binding.data_path(Path(settings.input_dir))
    source = Path(requested)
    source = binding.data_path(source if source.is_absolute() else binding.home / source)
    if directory != binding.home / "input" or source.parent != directory or not source.is_file():
        raise ValueError("INVALID_SMOKE_SOURCE")
    from agent.thoremix.sdk import ThoRemixClient
    with context.job("desktop-smoke-reserve"):
        return ThoRemixClient(binding.home).reserve("desktop-smoke", source=source)


def run_managed_desktop(context, binding, *, smoke=False):
    from agent.private_runtime import install_private_runtime
    install_private_runtime(binding)
    from agent.thoremix.config import Settings
    from agent.thoremix.desktop import PAGES, run_desktop

    write, *_ = _platform()
    settings = Settings.load(binding.home)
    reservation = reserve_smoke_source(context, binding, settings) if smoke else None
    runner = ManagedCommandRunner(context)
    result = {"schema": "thoremix.desktop.session.v1", "host": context.identity,
              "deployment_instance_id": binding.instance_id, "home": str(binding.home),
              "mode": "smoke" if smoke else "desktop", "status": "STARTING",
              "local_reservation": reservation}
    failed = []
    smoke_done = []

    def on_ready(app):
        title = context.deployment().settings.get("display_title")
        if title is not None and (type(title) is not str or not 1 <= len(title) <= 120):
            raise ValueError("INVALID_DESKTOP_TITLE")
        app.window.title(title or ("Thỏ Remix — " + binding.instance_id))
        app.window.update_idletasks()
        context.report_readiness(True, "DESKTOP_READY")
        result.update(status="OPEN", title=app.window.title(),
                      width=app.window.winfo_width(), height=app.window.winfo_height())
        write(context.instance_dir / "app-result.json", result)
        if not smoke:
            return
        deadline = time.monotonic() + 600
        views = []
        pending = list(PAGES)

        def stop(error=None):
            if error:
                failed.append(error)
            result.update(status="FAILED" if failed else "SMOKE_PASSED",
                          error=error, views=views, child=runner.last_result,
                          rows=len(app.snapshot.get("rows", [])),
                          enabled=app.snapshot.get("enabled"))
            write(context.instance_dir / "app-result.json", result)
            smoke_done.append(True)
            app.quit()

        def visit():
            try:
                if not pending:
                    app.refresh()
                    if not app.launch("status"):
                        stop("SMOKE_STATUS_NOT_STARTED")
                        return
                    app.window.after(200, observe)
                    return
                name = pending.pop(0)
                app.show_page(name)
                app.window.update_idletasks()
                from PIL import ImageGrab
                x, y = app.window.winfo_rootx(), app.window.winfo_rooty()
                width, height = app.window.winfo_width(), app.window.winfo_height()
                screenshot = context.instance_dir / ("desktop-" + name + ".png")
                ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True).save(screenshot)
                views.append({"name": name, "heading": str(app.heading.cget("text")),
                              "width": width, "height": height, "screenshot": str(screenshot)})
                app.window.after(200, visit)
            except Exception as error:
                stop(type(error).__name__)

        def observe():
            if not app.alive:
                return
            if time.monotonic() > deadline:
                stop("SMOKE_STATUS_TIMEOUT")
                return
            if runner.last_result is not None and not app.active_groups:
                child = runner.last_result
                if child.get("status") != "STOPPED" or child.get("result", {}).get("exit_code") != 0:
                    stop("SMOKE_STATUS_FAILED")
                else:
                    stop()
                return
            app.window.after(200, observe)

        app.window.after(300, visit)

    started = run_desktop(settings, command_runner=runner,
                          instance_namespace=desktop_namespace(binding),
                          on_ready=on_ready, is_draining=context.is_draining)
    if not started:
        if smoke:
            failed.append("EXISTING_DESKTOP_NOT_SMOKE_TESTED")
            result.update(status="FAILED", error=failed[-1])
        else:
            result.update(status="EXISTING_DESKTOP_ACTIVATED")
    elif not smoke:
        result.update(status="CLOSED")
    elif not smoke_done:
        failed.append("SMOKE_INTERRUPTED")
        result.update(status="FAILED", error="SMOKE_INTERRUPTED")
    write(context.instance_dir / "app-result.json", result)
    return 2 if failed else 0



