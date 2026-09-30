"""Explicit resources for independent ComicReels and ThoRemix app instances.

This module has no platform dependency and performs no browser/model work on
import or installation. Callbacks are supplied by the trusted, verified host.
"""
from __future__ import annotations

import importlib
import json
import re
import sys
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, ContextManager, Iterator


class PrivateRuntimeError(RuntimeError):
    pass


def absolute_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise PrivateRuntimeError("PRIVATE_PATH_REQUIRED")
    for part in (path, *path.parents):
        if part.is_symlink() or (
            part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 1024
        ):
            raise PrivateRuntimeError("PRIVATE_PATH_LINK")
    return path.resolve()


@dataclass(frozen=True, slots=True)
class PrivateRuntime:
    instance_id: str
    app_kind: str
    home: Path
    profiles: Mapping[str, Path]
    tool_resolver: Callable[[str], Path]
    profile_lease_factory: Callable[[Path], ContextManager[Any]]
    model_resolver: Callable[[str], Path]
    chat_profile_name: str
    flow_profile_config: Path | None = None
    visible: bool = False
    api_port: int = 8100
    websocket_port: int = 9222
    affiliate_session_provider: Any | None = None

    def __post_init__(self) -> None:
        if (self.app_kind not in {"comic", "thoremix"}
                or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", self.instance_id) is None):
            raise PrivateRuntimeError("INVALID_APP_INSTANCE")
        if (not self.chat_profile_name or self.chat_profile_name in {".", ".."}
                or any(char in self.chat_profile_name for char in "/\\\0")):
            raise PrivateRuntimeError("INVALID_CHAT_PROFILE_NAME")
        object.__setattr__(self, "home", absolute_path(self.home))
        profiles = {role: absolute_path(path) for role, path in self.profiles.items()}
        if not profiles or set(profiles) - {"chatgpt", "flow", "social", "affiliate"}:
            raise PrivateRuntimeError("INVALID_PROFILE_ROLES")
        object.__setattr__(self, "profiles", MappingProxyType(profiles))
        if any(not callable(provider) for provider in (
            self.tool_resolver, self.profile_lease_factory, self.model_resolver,
        )):
            raise PrivateRuntimeError("PRIVATE_PROVIDER_REQUIRED")
        if self.flow_profile_config is not None:
            object.__setattr__(self, "flow_profile_config", self.data_path(self.flow_profile_config))
        if any(type(port) is not int or not 1 <= port <= 65535
               for port in (self.api_port, self.websocket_port)):
            raise PrivateRuntimeError("INVALID_APP_PORT")
        if self.api_port == self.websocket_port:
            raise PrivateRuntimeError("APP_PORT_CONFLICT")

    def data_path(self, path: str | Path) -> Path:
        resolved = absolute_path(path)
        if not resolved.is_relative_to(self.home):
            raise PrivateRuntimeError("FOREIGN_APP_DATA")
        return resolved

    def profile(self, role: str, requested: str | Path | None = None) -> Path:
        if role not in self.profiles:
            raise PrivateRuntimeError("PROFILE_ROLE_NOT_BOUND")
        path = absolute_path(self.profiles[role])
        if requested is not None and absolute_path(requested) != path:
            raise PrivateRuntimeError("PHYSICAL_PROFILE_MISMATCH")
        return path

    def tool(self, name: str) -> Path:
        path = absolute_path(self.tool_resolver(name))
        if not path.is_file():
            raise PrivateRuntimeError("PRIVATE_TOOL_UNAVAILABLE")
        return path

    def model(self, name: str) -> Path:
        path = absolute_path(self.model_resolver(name))
        if not path.is_dir():
            raise PrivateRuntimeError("PRIVATE_MODEL_UNAVAILABLE")
        return path

    @contextmanager
    def borrow(self, role: str, requested: str | Path | None = None) -> Iterator[Any]:
        path = self.profile(role, requested)
        with self.profile_lease_factory(path) as owner:
            with owner.borrow() as borrowed:
                borrowed.require_active()
                if Path(borrowed.profile_dir).resolve() != path:
                    raise PrivateRuntimeError("BORROWED_PROFILE_MISMATCH")
                yield borrowed
                borrowed.require_active()

    def camoufox_kwargs(self) -> dict[str, Any]:
        executable = self.tool("camoufox")
        version_file = absolute_path(executable.parent / "version.json")
        try:
            if version_file.stat().st_size > 4096:
                raise ValueError
            version = json.loads(version_file.read_text(encoding="utf-8"))["version"]
            if not isinstance(version, str) or re.fullmatch(r"[1-9][0-9]{1,3}(?:\.[0-9]+)*", version) is None:
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise PrivateRuntimeError("PRIVATE_BROWSER_VERSION_INVALID") from None
        from camoufox.addons import DefaultAddons

        return {"executable_path": str(executable), "ff_version": int(version.split(".")[0]),
                "exclude_addons": list(DefaultAddons)}

    @property
    def chat_home(self) -> Path:
        return self.data_path(self.home / "gpt_fullproxy")

    def gpt_client(
        self, *, profile: str | None = None, profile_dir: str | Path | None = None,
        home: str | Path | None = None, visible: bool | None = None,
    ) -> "OwnedGPTClient":
        self.profile("chatgpt", profile_dir)
        if profile is not None and profile != self.chat_profile_name:
            raise PrivateRuntimeError("CHAT_PROFILE_NAME_MISMATCH")
        if home is not None and absolute_path(home) != self.chat_home:
            raise PrivateRuntimeError("CHAT_JOURNAL_MISMATCH")
        return OwnedGPTClient(self, self.visible if visible is None else visible)


_binding: PrivateRuntime | None = None
_guard = threading.Lock()


def install_private_runtime(binding: PrivateRuntime) -> None:
    """Install once, before importing agent.config or starting any app workers."""
    if not isinstance(binding, PrivateRuntime):
        raise TypeError("Expected an app PrivateRuntime binding")
    global _binding
    with _guard:
        if _binding is not None and _binding is not binding:
            raise PrivateRuntimeError("APP_PROCESS_ALREADY_BOUND")
        config = sys.modules.get("agent.config")
        if config is not None and (
            Path(config.BASE_DIR).resolve() != binding.home
            or config.API_PORT != binding.api_port or config.WS_PORT != binding.websocket_port
        ):
            raise PrivateRuntimeError("APP_CONFIG_ALREADY_IMPORTED")
        _binding = binding


def current_runtime() -> PrivateRuntime | None:
    return _binding


def media_tool(name: str) -> str:
    runtime = current_runtime()
    return str(runtime.tool(name)) if runtime is not None else name


_GPT_APIS = {
    "chat": ("gpt_fullproxy.sdk.chat", "ChatAPI",
             frozenset({"send", "read_message_text"})),
    "image": ("gpt_fullproxy.sdk.image", "ImageAPI",
              frozenset({"generate", "recover_existing", "generate_batch", "reconcile_batch"})),
    "conversation": ("gpt_fullproxy.sdk.conversations", "ConversationHandle",
                     frozenset({"reply", "tail", "wait_for_new_message"})),
}


def _require_gpt_method(namespace: str, name: str) -> None:
    module_name, class_name, allowed = _GPT_APIS[namespace]
    if name not in allowed or not callable(getattr(
        getattr(importlib.import_module(module_name), class_name), name, None,
    )):
        raise AttributeError(f"Required GPTFP capability is unavailable: {namespace}.{name}")


class _OwnedNamespace:
    def __init__(self, owner: "OwnedGPTClient", namespace: str, conversation: str | None = None):
        self._owner, self._namespace, self._conversation = owner, namespace, conversation

    def __getattr__(self, name: str):
        _require_gpt_method(self._namespace, name)

        def invoke(*args, **kwargs):
            return self._owner.call(self._namespace, name, self._conversation, args, kwargs)

        return invoke


class _OwnedChat(_OwnedNamespace):
    def open(self, conversation: str) -> _OwnedNamespace:
        # The public SDK validates the exact conversation inside the leased call.
        # This descriptor contains no live page, browser, or lease.
        return _OwnedNamespace(self._owner, "conversation", conversation)


class OwnedGPTClient:
    """Bound public calls acquire on the calling worker, and finish before release.

    Only materialized chat/image operations used by these apps are exposed.
    No lazy iterator, browser handle or background stream leaves the lease scope.
    Call results and exceptions are not interpreted as authorization to retry.
    """
    def __init__(self, binding: PrivateRuntime, visible: bool):
        self.binding, self.visible = binding, visible
        self.chat = _OwnedChat(self, "chat")
        self.image = _OwnedNamespace(self, "image")

    def call(self, namespace: str, method: str, conversation: str | None, args, kwargs):
        _require_gpt_method(namespace, method)
        from gpt_fullproxy import BrowserProfileHandle, GPTFullProxy

        with self.binding.borrow("chatgpt") as borrowed:
            handle = BrowserProfileHandle(
                id=self.binding.chat_profile_name, user_data_dir=borrowed.profile_dir,
                downloads_dir=self.binding.chat_home / "downloads",
                lock_mode="external", lease_id=borrowed.lease_id,
                metadata={"owner": self.binding.app_kind, "instance": self.binding.instance_id},
            )
            client = GPTFullProxy(
                browser_profile=handle, home=self.binding.chat_home, visible=self.visible,
                browser_executable=self.binding.tool("camoufox"),
                ffmpeg_executable=self.binding.tool("ffmpeg"),
                ffprobe_executable=self.binding.tool("ffprobe"), inherit_environment=False,
            )
            api = client.chat.open(conversation) if namespace == "conversation" else getattr(client, namespace)
            return getattr(api, method)(*args, **kwargs)


def configuration_file(name: str) -> Path:
    """Per-instance editable configuration; installed package defaults stay immutable.

    The final cutover (or explicit fresh-instance setup) seeds these files. Missing
    configuration is not silently recreated over an interrupted migration.
    """
    if name not in {"models.json", "providers.json"}:
        raise PrivateRuntimeError("UNKNOWN_CONFIGURATION_FILE")
    runtime = current_runtime()
    if runtime is None:
        return Path(__file__).parent / name
    return runtime.data_path(runtime.home / "config" / name)
