"""Explicit one-shot paid validation construction seam.

Nothing in normal application startup imports this module. The caller must supply
a fresh opaque object from an explicitly approved validation harness. The same
object is bound into BrowserFlowBackend and later forwarded by this session to
FlowClient; no environment variable, HTTP route, CLI flag, config file or boolean
can manufacture authorization.

Constructing a session does not start a browser and does not submit an effect.
The session permits at most one paid image attempt. The attempt is consumed
before awaiting FlowClient so cancellation/UNKNOWN cannot lead to an automatic
second paid submission from the same validation session.
"""
from __future__ import annotations

from agent.services.flow_browser_backend import BrowserFlowBackend
from agent.services.flow_client import FlowClient

_CONSTRUCTION_KEY = object()


def _require_authorization(value) -> object:
    # Use a plain opaque object so strings/bools/config values cannot be mistaken
    # for authorization. The harness must deliberately create object() in memory.
    if type(value) is not object:
        raise ValueError('PAID_VALIDATION_AUTHORIZATION_REQUIRED')
    return value


class PaidValidationSession:
    """One in-memory authorization capability for one paid image attempt."""

    __slots__ = ('_authorization', '_backend', '_client', '_used')

    def __init__(self, key, authorization, backend):
        if key is not _CONSTRUCTION_KEY:
            raise TypeError('PAID_VALIDATION_FACTORY_REQUIRED')
        self._authorization = _require_authorization(authorization)
        self._backend = backend
        self._client = FlowClient(backend=backend)
        self._used = False

    @classmethod
    def _for_test(cls, authorization, backend):
        """Dependency-injection seam for authored coverage; not a production grant."""
        return cls(_CONSTRUCTION_KEY, authorization, backend)

    @property
    def paid_dispatch_enabled(self) -> bool:
        return self._backend.paid_dispatch_enabled is True

    @property
    def used(self) -> bool:
        return self._used

    async def start(self) -> None:
        """Explicitly start the isolated validation backend; no effect is submitted."""
        await self._client.start_backend()

    async def close(self) -> None:
        await self._client.close_backend()

    async def readiness(self) -> dict:
        """Read-only readiness observation for the validation harness."""
        return await self._client.backend_readiness()

    async def generate_one_image(
        self,
        *,
        prompt: str,
        project_id: str,
        idempotency_key: str,
        aspect_ratio: str = 'IMAGE_ASPECT_RATIO_PORTRAIT',
        character_media_ids: list[str] | None = None,
        image_model: str | None = None,
        seed: int | None = None,
        base_media_id: str | None = None,
    ) -> dict:
        """Consume this validation capability and attempt exactly one paid image."""
        if self._used:
            return {
                'status': 409,
                'error': 'PAID_VALIDATION_SHOT_ALREADY_USED',
                'effect': 'not_submitted',
            }

        # Consume before any await. Cancellation, timeout or UNKNOWN still burns
        # the one-shot validation capability and therefore cannot auto-resubmit.
        self._used = True
        return await self._client.generate_images(
            prompt=prompt,
            project_id=project_id,
            aspect_ratio=aspect_ratio,
            character_media_ids=character_media_ids,
            image_model=image_model,
            count=1,
            seed=seed,
            base_media_id=base_media_id,
            idempotency_key=idempotency_key,
            paid_authorization=self._authorization,
        )


def build_paid_validation_session(
    authorization,
    *,
    config=None,
    state_path=None,
) -> PaidValidationSession:
    """Build, but do not start, an explicitly authorized one-shot validation session.

    This function never creates an authorization object. The validation harness
    must pass a fresh plain object whose identity is kept only in memory.
    """
    authorization = _require_authorization(authorization)
    backend = BrowserFlowBackend(
        config=config,
        state_path=state_path,
        paid_dispatch_enabled=True,
        paid_authorization=authorization,
    )
    return PaidValidationSession(_CONSTRUCTION_KEY, authorization, backend)
