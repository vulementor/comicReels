"""Immutable business-level parity contract for the browser-first transport refactor.

This module records what must remain true above the transport boundary. It does
not execute Flow requests and it does not make browser paid generation reachable.
"""
from __future__ import annotations

from types import MappingProxyType

_REQUIRED_NON_PAID = (
    'project_open_resume',
    'project_create_session',
    'project_media_read',
    'media_read',
    'operation_reconcile',
    'upload',
)


def _entry(*paths: str, requirement: str) -> dict:
    return {
        'business_owner': 'flowkit',
        'transport_independent': True,
        'evidence_paths': tuple(paths),
        'browser_requirement': requirement,
    }


MANDATORY_FLOW_PARITY = MappingProxyType({
    'project_story_entity_creation': _entry(
        'skills/fk-create-project.md',
        requirement='Project/story/entity semantics remain above FlowBackend.',
    ),
    'root_continuation_chains': _entry(
        'agent/services/scene_chain.py', 'skills/fk-gen-videos.md',
        requirement='ROOT/CONTINUATION state and cascade semantics do not depend on transport.',
    ),
    'transition_prompts': _entry(
        'skills/fk-gen-videos.md',
        requirement='Continuation video generation keeps transition_prompt semantics.',
    ),
    'multi_reference_video': _entry(
        'skills/fk-creative-mix.md', 'agent/services/flow_batch.py',
        requirement='Reference-video business inputs remain stable across transports.',
    ),
    'creative_mix': _entry(
        'skills/fk-creative-mix.md',
        requirement='Creative scenario composition remains a FlowKit concern.',
    ),
    'pipeline_resume': _entry(
        'skills/fk-pipeline.md',
        requirement='Pipeline stage detection/resume is based on durable business state.',
    ),
    'video_review_selective_regen': _entry(
        'agent/services/video_reviewer.py', 'skills/fk-pipeline.md',
        requirement='Review thresholds and selective regeneration stay transport-independent.',
    ),
    'gallery_logs_status': _entry(
        'frontend/',
        requirement='UI/status surfaces consume business state and selected backend metadata.',
    ),
    'media_refresh_download': _entry(
        'skills/fk-refresh-urls.md', 'agent/services/flow_client.py',
        requirement='Stored media UUIDs remain the durable key for refresh/download behavior.',
    ),
    'tts_concat_branding': _entry(
        'agent/services/post_process.py', 'skills/fk-pipeline.md',
        requirement='TTS/concat/branding remain outside the Flow transport migration.',
    ),
})


NON_FLOW_INVARIANTS = MappingProxyType({
    'tts': 'unchanged',
    'concat': 'unchanged',
    'branding': 'unchanged',
    'review_engine': 'unchanged',
    'project_database_model': 'unchanged',
})


def parity_manifest() -> dict:
    """Return a detached plain-dict projection safe for status/report consumers."""
    return {
        name: {
            'business_owner': item['business_owner'],
            'transport_independent': item['transport_independent'],
            'evidence_paths': list(item['evidence_paths']),
            'browser_requirement': item['browser_requirement'],
        }
        for name, item in MANDATORY_FLOW_PARITY.items()
    }


def validate_browser_parity_readiness(health: dict) -> dict:
    """Check the source-level non-paid prerequisites for later FBR-4 validation.

    This is not a live parity verdict. It only prevents an incomplete or paid-enabled
    browser transport from being presented as eligible for the parity test matrix.
    """
    missing = []
    if not isinstance(health, dict) or health.get('ready') is not True:
        missing.append('browser_ready')
    if health.get('readiness_scope') != 'non_paid_parity':
        missing.append('non_paid_parity_scope')
    if health.get('operations_implemented') is not True:
        missing.append('operations_implemented')

    capabilities = health.get('capabilities')
    if not isinstance(capabilities, dict):
        missing.extend(_REQUIRED_NON_PAID)
    else:
        missing.extend(name for name in _REQUIRED_NON_PAID
                       if capabilities.get(name) is not True)
        if capabilities.get('paid_dispatch') is not False:
            missing.append('paid_dispatch_disabled')

    paid_enabled = health.get('paid_dispatch_enabled')
    if paid_enabled is not False and 'paid_dispatch_disabled' not in missing:
        missing.append('paid_dispatch_disabled')

    # Stable ordering and no duplicates make this suitable for logs/checkpoints.
    missing = list(dict.fromkeys(missing))
    return {
        'ready': not missing,
        'missing': missing,
        'paid_dispatch_enabled': paid_enabled,
    }
