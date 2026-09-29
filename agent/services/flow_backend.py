"""Transport boundary shared by the extension and persistent browser backends."""
from collections.abc import Awaitable, Callable
from typing import Protocol


class FlowBackend(Protocol):
    kind: str
    ready: bool
    paid_dispatch_enabled: bool
    session_owner_key: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def check_readiness(self) -> dict: ...
    async def execute(self, method: str, params: dict, timeout: float = 300) -> dict: ...
    async def open_project(self, project_id: str) -> dict: ...


class ExtensionFlowBackend:
    """Preserve extension routing; the application owns the WS server lifecycle."""

    kind = "extension"
    paid_dispatch_enabled = True
    session_owner_key = "extension"

    def __init__(
        self,
        sender: Callable[[str, dict, float], Awaitable[dict]],
        ready: Callable[[], bool],
    ):
        self._sender = sender
        self._ready = ready

    @property
    def ready(self) -> bool:
        return self._ready()

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def check_readiness(self) -> dict:
        return {
            "backend_kind": self.kind,
            "ready": self.ready,
            "paid_dispatch_enabled": self.paid_dispatch_enabled,
        }

    async def execute(self, method: str, params: dict, timeout: float = 300) -> dict:
        return await self._sender(method, params, timeout)

    async def open_project(self, project_id: str) -> dict:
        return {"status": 501, "error": "Extension project scoping is handled by RPC requests"}
