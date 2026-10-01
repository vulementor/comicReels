"""Stable business transport boundary for browser-only FlowKit."""
from typing import Protocol


class FlowBackend(Protocol):
    """Business-facing Flow transport contract.

    BrowserFlowBackend is the sole production implementation. Business/creative
    code depends on this protocol rather than browser internals.
    """

    kind: str
    ready: bool
    paid_dispatch_enabled: bool
    session_owner_key: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def check_readiness(self) -> dict: ...
    async def execute(self, method: str, params: dict, timeout: float = 300) -> dict: ...
    async def open_project(self, project_id: str) -> dict: ...
    async def ensure_session_project(self, *, title=None, force_new=False) -> dict: ...
