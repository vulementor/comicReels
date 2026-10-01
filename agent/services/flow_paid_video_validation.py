"""Explicit one-shot paid-video validation construction seam.

Normal application startup never imports this module. The validation harness must
supply a fresh opaque in-memory object; no env/config/HTTP surface can mint it.
"""
from __future__ import annotations

from agent.services.flow_browser_backend import BrowserFlowBackend
from agent.services.flow_client import FlowClient

_CONSTRUCTION_KEY = object()


def _require_authorization(value) -> object:
    if type(value) is not object:
        raise ValueError("PAID_VALIDATION_AUTHORIZATION_REQUIRED")
    return value


class PaidVideoValidationSession:
    """One in-memory capability for exactly one paid video effect attempt."""

    __slots__ = ("_authorization", "_backend", "_client", "_used")

    def __init__(self, key, authorization, backend):
        if key is not _CONSTRUCTION_KEY:
            raise TypeError("PAID_VALIDATION_FACTORY_REQUIRED")
        self._authorization = _require_authorization(authorization)
        self._backend = backend
        self._client = FlowClient(backend=backend)
        self._used = False

    @classmethod
    def _for_test(cls, authorization, backend):
        return cls(_CONSTRUCTION_KEY, authorization, backend)

    @property
    def paid_dispatch_enabled(self) -> bool:
        return self._backend.paid_dispatch_enabled is True

    @property
    def used(self) -> bool:
        return self._used

    async def start(self) -> None:
        await self._client.start_backend()

    async def close(self) -> None:
        await self._client.close_backend()

    async def readiness(self) -> dict:
        return await self._client.backend_readiness()

    async def submit_one_video(
        self,
        *,
        rpcid: str,
        freq: str,
        project_id: str,
        idempotency_key: str,
        timeout: float = 120,
    ) -> dict:
        """Consume the capability before attempting one paid video effect."""
        if self._used:
            return {
                "status": 409,
                "error": "PAID_VALIDATION_SHOT_ALREADY_USED",
                "effect": "not_submitted",
            }
        self._used = True
        return await self._client.submit_paid_video(
            rpcid=rpcid,
            freq=freq,
            project_id=project_id,
            idempotency_key=idempotency_key,
            paid_authorization=self._authorization,
            timeout=timeout,
        )


def build_paid_video_validation_session(
    authorization,
    *,
    config=None,
    state_path=None,
) -> PaidVideoValidationSession:
    """Build, but do not start, an explicitly authorized one-shot video session."""
    authorization = _require_authorization(authorization)
    backend = BrowserFlowBackend(
        config=config,
        state_path=state_path,
        paid_dispatch_enabled=True,
        paid_authorization=authorization,
    )
    return PaidVideoValidationSession(
        _CONSTRUCTION_KEY, authorization, backend,
    )
