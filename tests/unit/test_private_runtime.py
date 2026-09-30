"""App ownership contracts only; no live browser, media tool or model execution."""
from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent import private_runtime as private


@pytest.fixture
def binding(tmp_path, monkeypatch):
    monkeypatch.setattr(private, "_binding", None)
    monkeypatch.delitem(sys.modules, "agent.config", raising=False)
    home = tmp_path / "data" / "channel-a"
    home.mkdir(parents=True)
    native = tmp_path / "release" / "native"
    native.mkdir(parents=True)
    for name in ("camoufox", "ffmpeg", "ffprobe", "tts-python"):
        (native / name).write_text("fixture executable; never run")
    (native / "version.json").write_text('{"version":"135.0"}')
    models = tmp_path / "models"
    models.mkdir()
    (models / "whisper-small").mkdir()
    (models / "omnivoice").mkdir()
    profiles = {role: tmp_path / "profiles" / role
                for role in ("chatgpt", "flow", "social", "affiliate")}
    for path in profiles.values():
        path.mkdir(parents=True)
    events = []

    @contextmanager
    def owner(path):
        events.append(("owner-enter", path, threading.get_ident()))
        active = True

        class Borrow:
            profile_dir = path
            lease_id = "actual-common-borrow"

            def require_active(self):
                assert active

        @contextmanager
        def borrow():
            events.append("borrow-enter")
            try:
                yield Borrow()
            finally:
                events.append("borrow-exit")

        try:
            yield SimpleNamespace(borrow=borrow)
        finally:
            active = False
            events.append("owner-exit")

    config = home / "flow.json"
    config.write_text(json.dumps({
        "schema_version": 1, "browser_kind": "camoufox",
        "profile_logical_name": "flow-a", "user_data_dir": str(profiles["flow"]),
    }))
    value = private.PrivateRuntime(
        instance_id="channel-a", app_kind="thoremix", home=home, profiles=profiles,
        tool_resolver=lambda name: native / name, profile_lease_factory=owner,
        model_resolver=lambda name: models / name, chat_profile_name="chat-a",
        flow_profile_config=config,
    )
    private.install_private_runtime(value)
    return value, events


def test_binding_is_process_owned_and_profiles_are_immutable(binding):
    value, _ = binding
    with pytest.raises(TypeError):
        value.profiles["chatgpt"] = value.home / "other"
    with pytest.raises(private.PrivateRuntimeError, match="ALREADY_BOUND"):
        private.install_private_runtime(replace(value, instance_id="channel-b"))


def test_foreign_profile_or_state_does_not_create_a_replacement(binding):
    value, _ = binding
    foreign = value.home.parent / "other-profile"
    with pytest.raises(private.PrivateRuntimeError, match="MISMATCH"):
        value.profile("chatgpt", foreign)
    with pytest.raises(private.PrivateRuntimeError, match="FOREIGN_APP_DATA"):
        value.data_path(foreign)
    assert not foreign.exists()


def test_gpt_call_borrows_on_worker_and_finishes_before_release(binding, monkeypatch):
    value, events = binding
    options = []
    calls = []

    def send(text, **kwargs):
        assert events[-1] == "borrow-enter"
        calls.append((text, kwargs))
        events.append("complete-response-and-files")
        return {"state": "completed"}

    def factory(**kwargs):
        options.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(send=send))

    monkeypatch.setattr(private, "_require_gpt_method", lambda namespace, method: None)
    monkeypatch.setitem(sys.modules, "gpt_fullproxy", SimpleNamespace(
        BrowserProfileHandle=lambda **kwargs: SimpleNamespace(**kwargs), GPTFullProxy=factory,
    ))
    client = value.gpt_client()
    result = []
    callback = lambda value: None
    worker = threading.Thread(target=lambda: result.append(
        client.chat.send("same frozen prompt", on_progress=callback)))
    worker.start()
    worker.join()
    assert result == [{"state": "completed"}]
    assert calls == [("same frozen prompt", {"on_progress": callback})]
    assert events[0][2] == worker.ident
    assert events[-3:] == ["complete-response-and-files", "borrow-exit", "owner-exit"]
    assert options[0]["browser_profile"].lease_id == "actual-common-borrow"
    assert options[0]["browser_profile"].user_data_dir == value.profiles["chatgpt"]
    assert options[0]["inherit_environment"] is False
    assert options[0]["home"] == value.chat_home
    assert options[0]["browser_executable"] == value.tool("camoufox")


def test_missing_gpt_capability_is_not_advertised(binding, monkeypatch):
    value, events = binding
    monkeypatch.setattr(private.importlib, "import_module",
                        lambda name: SimpleNamespace(ImageAPI=type("ImageAPI", (), {})))
    with pytest.raises(AttributeError, match="generate_batch"):
        getattr(value.gpt_client().image, "generate_batch")
    assert events == []


def flow_provider(binding, monkeypatch):
    from agent.services import flow_browser_session as flow

    value, events = binding
    monkeypatch.setattr(private.PrivateRuntime, "camoufox_kwargs", lambda self: {
        "executable_path": str(self.tool("camoufox")), "ff_version": 135, "exclude_addons": [],
    })
    monkeypatch.setitem(sys.modules, "kabin_browser_semantic", SimpleNamespace(
        BrowserSession=SimpleNamespace(from_page=lambda page: SimpleNamespace(page=page)),
    ))

    class Lease:
        held = False

        def __init__(self, config):
            pass

        def acquire(self):
            self.held = True
            events.append("legacy-enter")

        def release(self):
            self.held = False
            events.append("legacy-exit")

    monkeypatch.setattr(flow, "FlowProfileLease", Lease)
    seen = []

    class Manager:
        fail_close = False

        def __enter__(self):
            self.page = SimpleNamespace(
                goto=lambda *args, **kwargs: None, is_closed=lambda: False,
                url="https://flow.google.com/",
            )
            return SimpleNamespace(pages=[self.page])

        def __exit__(self, *args):
            events.append("browser-close-attempt")
            if self.fail_close:
                raise RuntimeError("close incomplete")
            events.append("browser-closed")

    manager = Manager()

    def factory(**kwargs):
        seen.append(kwargs)
        return manager

    provider = flow.FlowBrowserSessionProvider(flow.FlowProfileConfig.load(),
                                               context_factory=factory)
    return provider, manager, seen


def test_flow_holds_common_borrow_until_browser_and_legacy_close(binding, monkeypatch):
    value, events = binding
    provider, _, seen = flow_provider(binding, monkeypatch)
    with provider:
        assert seen[0]["executable_path"] == str(value.tool("camoufox"))
        assert provider._lease.held
        assert "borrow-exit" not in events
    assert events[-5:] == ["browser-close-attempt", "browser-closed", "legacy-exit",
                          "borrow-exit", "owner-exit"]


def test_uncertain_flow_close_retains_common_and_legacy_owner(binding, monkeypatch):
    from agent.services.flow_browser_session import FlowBrowserError

    _, events = binding
    provider, manager, _ = flow_provider(binding, monkeypatch)
    provider.open()
    manager.fail_close = True
    with pytest.raises(FlowBrowserError, match="CLOSE_UNCERTAIN"):
        provider.close()
    assert provider._lease.held
    assert provider._private_scope is not None
    assert "borrow-exit" not in events and "owner-exit" not in events
    with pytest.raises(FlowBrowserError, match="CLOSE_UNCERTAIN"):
        provider.open()
    manager.fail_close = False
    provider.close()
    assert events[-1] == "owner-exit"


def test_thoremix_settings_preserve_disabled_state_and_use_instance_output(binding):
    from agent.thoremix.config import Settings

    value, _ = binding
    settings = Settings(root=str(value.home), input_dir=str(value.home.parent / "originals"))
    settings.validate()
    assert settings.enabled is False
    assert settings.directory == value.home
    assert settings.output == value.home / "output"
    assert settings.affiliate_profile_dir == ""


def test_model_and_media_do_not_fallback_to_ambient_caches(binding, monkeypatch):
    from agent.thoremix.media import media_tool

    value, _ = binding
    assert media_tool("ffmpeg") == str(value.tool("ffmpeg"))
    value.tool("ffprobe").unlink()
    with pytest.raises(private.PrivateRuntimeError, match="PRIVATE_TOOL_UNAVAILABLE"):
        media_tool("ffprobe")
    with pytest.raises(private.PrivateRuntimeError, match="PRIVATE_MODEL_UNAVAILABLE"):
        value.model("missing-model")


def test_tts_subprocess_receives_only_local_model_and_private_python(binding, monkeypatch):
    from agent.services import tts

    value, _ = binding
    seen = []

    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"ok":true}', stderr="")

    monkeypatch.setattr(tts.subprocess, "run", run)
    result = tts._run_tts_subprocess({"model": "ambient/hub-model", "text": "fixture",
                                    "output": str(value.home / "voice.wav")})
    assert result["ok"] is True
    command, options = seen[0]
    assert command[:2] == [str(value.tool("tts-python")), "-I"]
    assert json.loads(command[-1])["model"] == str(value.model("omnivoice"))
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert options["env"]["TRANSFORMERS_OFFLINE"] == "1"
