"""Thin finite dispatch for the ThoRemix app; the existing app owns its scheduler."""
from __future__ import annotations

from typing import Any

from agent.private_runtime import PrivateRuntime, install_private_runtime


def run_thoremix(
    context: Any, binding: PrivateRuntime, *, operation: str, job_id: str,
) -> dict:
    if binding.app_kind != "thoremix" or operation not in {"tick", "dispatch", "status"}:
        raise ValueError("Unsupported ThoRemix instance operation")
    install_private_runtime(binding)
    from agent.thoremix.sdk import ThoRemixClient

    # Existing Settings.enabled/publication_authorized and campaign locks remain
    # authoritative. No retry, automatic enable, approval or task registration.
    with context.job(job_id):
        return getattr(ThoRemixClient(binding.home), operation)()
