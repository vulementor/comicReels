"""Managed desktop contracts only; no GUI, browsers, providers or subprocesses."""
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.thoremix import managed_desktop as managed


class Deployment:
    def __init__(self, root, raw):
        self.root = root
        self.raw = raw

    def as_dict(self):
        return json.loads(self.raw)

    @property
    def settings(self):
        return self.as_dict()["settings"]

    @property
    def instance_id(self):
        return self.as_dict()["instance_id"]

    @property
    def home(self):
        return self.root / self.as_dict()["data_relative"]

    def require_application(self, name):
        assert self.as_dict()["kind"] == "app" and self.as_dict()["name"] == name
        return self


@pytest.fixture
def host(tmp_path, monkeypatch):
    value = {"kind": "app", "name": "thoremix", "instance_id": "ui-a",
             "release_id": "a" * 64, "channel": "candidate", "consumer_id": "thoremix",
             "data_relative": "state/jobs/consumers/app/thoremix/ui-a",
             "profiles": {"social": "shared/browser-profiles/thoremix/ui-a/social"},
             "entries": {"desktop": "desktop", "desktop-command": "desktop-command"},
             "enabled": True, "settings": {"chat_profile_name": "ui-a", "api_port": 8100}}
    canonical = lambda data: json.dumps(data).encode()
    context = SimpleNamespace(
        entrypoint="desktop", identity={"instance_id": "ui-parent", "release_id": "a" * 64,
            "consumer_id": "thoremix", "generation": 1, "channel": "candidate"},
        instance_dir=tmp_path / "state/jobs/launches/ui-parent", is_draining=lambda: False,
    )
    context.deployment = lambda: Deployment(tmp_path, canonical(value))
    jobs = []
    @contextmanager
    def job(name):
        jobs.append(("start", name))
        try:
            yield
        except Exception:
            jobs.append(("failed", name))
            raise
        else:
            jobs.append(("complete", name))
    context.job = job
    state = {"jobs": jobs, "value": value}

    def write(path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def read(path, **_kwargs):
        return json.loads(path.read_text(encoding="utf-8"))

    def prepare(registry, deployment, operation, *, launch_id):
        state.update(deployment=deployment.as_dict(), operation=operation, child_id=launch_id)
        return SimpleNamespace(launch_id=launch_id)

    def start(spec):
        state["starts"] = state.get("starts", 0) + 1
        return SimpleNamespace(as_dict=lambda: {"status": "STARTING", "instance_id": spec.launch_id})

    def inspect(root, child_id):
        request = state["deployment"]["settings"][managed.REQUEST_KEY]
        child = {**context.identity, "instance_id": child_id}
        write(root / "state/jobs/launches" / child_id / "app-result.json",
              {"schema": "thoremix.desktop.command-result.v1", "request": request,
               "child": child, "exit_code": 0, "stdout": '{"enabled":false}'})
        return {**child, "status": "STOPPED", "process_alive": False}

    monkeypatch.setattr(managed, "_platform", lambda: (
        write, Deployment, prepare, start, inspect, lambda root: root, canonical, read))
    return context, state, write


def test_bounded_command_rejects_root_escape_or_recursive_desktop():
    for command, arguments in (("desktop", []), ("desktop-command", []), ("init", []),
                               ("status", ["--root", "D:/foreign"]),
                               ("status", ["--root=D:/foreign"]), ("status", ["--help"])):
        with pytest.raises(ValueError):
            managed.validate_command(command, arguments)
    assert managed.validate_command("status", []) == []
    assert managed.validate_command("configure-facebook", ["--name", "A Page"]) == ["--name", "A Page"]


def test_runner_retains_exact_deployment_and_launches_one_child(host):
    context, state, _ = host
    original = context.deployment().as_dict()
    runner = managed.ManagedCommandRunner(context)
    code, stdout = runner("status")
    assert (code, json.loads(stdout)) == (0, {"enabled": False})
    child = state["deployment"]
    for key in ("release_id", "channel", "consumer_id", "instance_id", "data_relative", "profiles"):
        assert child[key] == original[key]
    assert context.deployment().as_dict() == original
    assert state["operation"] == "desktop-command" and state["starts"] == 1
    assert runner.last_result["result"]["request"]["parent"] == context.identity
    assert runner.last_result["status"] == "STOPPED"


def child_context(host, monkeypatch, code=0):
    import sys
    from agent import private_runtime
    context, state, _ = host
    context.entrypoint = "desktop-command"
    context.identity = {**context.identity, "instance_id": "child-a"}
    request = {"schema": "thoremix.desktop.command.v1", "command": "status", "arguments": [],
               "parent": {**context.identity, "instance_id": "parent-a"},
               "child_launch_id": "child-a", "deployment_instance_id": "ui-a",
               "release_id": "a" * 64}
    state["value"]["settings"][managed.REQUEST_KEY] = request
    binding = object()
    monkeypatch.setattr(private_runtime, "_binding", None)
    def install(actual):
        assert actual is binding
        monkeypatch.setattr(private_runtime, "_binding", actual)
    monkeypatch.setattr(private_runtime, "install_private_runtime", install)
    def cli_main(argv):
        assert private_runtime.current_runtime() is binding
        assert state["jobs"] == [("start", "desktop-command")]
        assert argv == ["--root", str(context.deployment().home), "status"]
        print('{"state":"ok"}')
        return code
    monkeypatch.setitem(sys.modules, "agent.thoremix.cli", SimpleNamespace(main=cli_main))
    return context, state, binding


def test_child_binds_before_cli_and_uses_fixed_home_under_job(host, monkeypatch):
    context, state, binding = child_context(host, monkeypatch)
    assert managed.run_child_command(context, binding) == 0
    assert state["jobs"][-1] == ("complete", "desktop-command")
    result = json.loads((context.instance_dir / "app-result.json").read_text())
    assert result["child"] == context.identity
    assert result["exit_code"] == 0 and json.loads(result["stdout"]) == {"state": "ok"}


def test_child_failure_retains_result_and_fails_job_without_retry(host, monkeypatch):
    context, state, binding = child_context(host, monkeypatch, code=2)
    with pytest.raises(RuntimeError, match="DESKTOP_COMMAND_FAILED"):
        managed.run_child_command(context, binding)
    result = json.loads((context.instance_dir / "app-result.json").read_text())
    assert result["exit_code"] == 2
    assert state["jobs"] == [("start", "desktop-command"), ("failed", "desktop-command")]


def test_namespaces_and_private_guard_preserve_legacy_boundary(monkeypatch):
    from agent import private_runtime
    from agent.thoremix.desktop import _validate_command_runner
    from agent.thoremix.tray import instance_names

    assert instance_names() == (r"Local\ThoRemixDesktop", r"Local\ThoRemixDesktopActivate")
    first = instance_names("app|thoremix|a|d:/one")
    assert first == instance_names("app|thoremix|a|d:/one")
    assert first != instance_names("app|thoremix|b|d:/two")
    assert first != instance_names()
    monkeypatch.setattr(private_runtime, "_binding", object())
    with pytest.raises(private_runtime.PrivateRuntimeError, match="BOUND_CHILD_LAUNCH_UNAVAILABLE"):
        _validate_command_runner(None)
    _validate_command_runner(lambda *_: None)
    monkeypatch.setattr(private_runtime, "_binding", None)
    _validate_command_runner(None)
    with pytest.raises(ValueError, match="PRIVATE_DESKTOP_RUNNER_REQUIRES_BINDING"):
        _validate_command_runner(lambda *_: None)


def test_smoke_reservation_never_accepts_normal_entry_or_foreign_source(host):
    context, state, _ = host
    home = context.deployment().home
    binding = SimpleNamespace(home=home, data_path=lambda path: Path(path).resolve())
    settings = SimpleNamespace(input_dir=str(home / "input"))
    with pytest.raises(ValueError, match="SMOKE_ENTRY_REQUIRED"):
        managed.reserve_smoke_source(context, binding, settings)
    context.entrypoint = "desktop-smoke"
    state["value"]["settings"]["smoke_source"] = "outside.jpg"
    with pytest.raises(ValueError, match="INVALID_SMOKE_SOURCE"):
        managed.reserve_smoke_source(context, binding, settings)
    assert state["jobs"] == []



def test_existing_desktop_activation_cannot_pass_smoke(host, monkeypatch):
    from agent import private_runtime
    from agent.thoremix import config, desktop
    context, state, _ = host
    binding = SimpleNamespace(instance_id="ui-a", consumer_kind="app", consumer_name="thoremix",
                              home=context.deployment().home)
    monkeypatch.setattr(private_runtime, "install_private_runtime", lambda _binding: None)
    monkeypatch.setattr(config.Settings, "load", lambda _root: SimpleNamespace())
    monkeypatch.setattr(desktop, "run_desktop", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(managed, "reserve_smoke_source", lambda *_args: None)
    context.entrypoint = "desktop-smoke"
    assert managed.run_managed_desktop(context, binding, smoke=True) == 2
    result = json.loads((context.instance_dir / "app-result.json").read_text())
    assert result["status"] == "FAILED"
    assert result["error"] == "EXISTING_DESKTOP_NOT_SMOKE_TESTED"
    assert "starts" not in state
    context.entrypoint = "desktop"
    assert managed.run_managed_desktop(context, binding) == 0
    result = json.loads((context.instance_dir / "app-result.json").read_text())
    assert result["status"] == "EXISTING_DESKTOP_ACTIVATED"

def test_runner_retries_verified_observation_without_restarting_child(host, monkeypatch):
    context, state, _ = host
    api = managed._platform()
    observed = []
    waits = []
    def inspect(root, child_id):
        observed.append((root, child_id))
        if len(observed) == 1:
            raise RegistryError("UNVERIFIED_ARTIFACT")
        return api[4](root, child_id)
    monkeypatch.setattr(managed, "_platform", lambda: (*api[:4], inspect, *api[5:]))
    monkeypatch.setattr(managed.time, "sleep", waits.append)
    runner = managed.ManagedCommandRunner(context)
    assert runner("status") == (0, '{"enabled":false}')
    assert state["starts"] == 1
    assert len(observed) == 2 and observed[0] == observed[1]
    assert waits == [0.1]
    assert runner.last_result["status"] == "STOPPED"
    assert runner.last_result["observation_retries"] == 1


def test_observation_exhaustion_retains_uncertain_child_without_relaunch(host, monkeypatch):
    context, state, _ = host
    api = managed._platform()
    observed = []
    waits = []
    def inspect(root, child_id):
        observed.append((root, child_id))
        raise RegistryError("UNVERIFIED_ARTIFACT")
    monkeypatch.setattr(managed, "_platform", lambda: (*api[:4], inspect, *api[5:]))
    monkeypatch.setattr(managed.time, "sleep", waits.append)
    runner = managed.ManagedCommandRunner(context)
    code, output = runner("status")
    assert code == 2
    result = json.loads(output)
    assert result["state"] == "needs_input"
    assert result["reason"] == "DESKTOP_CHILD_OBSERVATION_UNAVAILABLE"
    assert result["child_launch_id"] == state["child_id"]
    assert result["action_retry_allowed"] is False
    assert state["starts"] == 1 and len(observed) == 5 and len(set(observed)) == 1
    assert waits == [0.1] * 4
    assert runner.last_result["status"] == "OBSERVATION_UNAVAILABLE"
    assert "result" not in runner.last_result
    retained = json.loads((context.instance_dir / "desktop-commands" / (state["child_id"] + ".json")).read_text())
    assert retained == runner.last_result


@pytest.mark.parametrize("failure", ["unsafe", "identity"])
def test_observation_retry_never_bypasses_path_or_identity_validation(host, monkeypatch, failure):
    context, state, _ = host
    api = managed._platform()
    count = []
    def inspect(root, child_id):
        count.append(child_id)
        if failure == "unsafe":
            raise RegistryError("UNSAFE_PATH")
        if len(count) == 1:
            raise RegistryError("UNVERIFIED_ARTIFACT")
        return {**api[4](root, child_id), "release_id": "b" * 64}
    monkeypatch.setattr(managed, "_platform", lambda: (*api[:4], inspect, *api[5:]))
    monkeypatch.setattr(managed.time, "sleep", lambda _: None)
    with pytest.raises((RegistryError, ValueError),
                       match="UNSAFE_PATH" if failure == "unsafe" else "DESKTOP_CHILD_IDENTITY_MISMATCH"):
        managed.ManagedCommandRunner(context)("status")
    assert state["starts"] == 1
    assert len(count) == (1 if failure == "unsafe" else 2)
