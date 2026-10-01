"""FBR-4 authored parity-matrix requirements; not executed during coding."""
from agent.services.flow_parity import (
    MANDATORY_FLOW_PARITY,
    NON_FLOW_INVARIANTS,
    parity_manifest,
    validate_browser_parity_readiness,
)


def test_manifest_contains_every_owner_mandatory_scenario():
    assert set(MANDATORY_FLOW_PARITY) == {
        'project_story_entity_creation',
        'root_continuation_chains',
        'transition_prompts',
        'multi_reference_video',
        'creative_mix',
        'pipeline_resume',
        'video_review_selective_regen',
        'gallery_logs_status',
        'media_refresh_download',
        'tts_concat_branding',
    }


def test_each_parity_entry_has_business_evidence_and_transport_rule():
    manifest = parity_manifest()
    assert set(manifest) == set(MANDATORY_FLOW_PARITY)
    for key, item in manifest.items():
        assert item['business_owner'] == 'flowkit'
        assert item['transport_independent'] is True
        assert item['evidence_paths']
        assert all(path.startswith(('agent/', 'skills/', 'frontend/')) for path in item['evidence_paths'])
        assert item['browser_requirement']


def test_non_flow_invariants_remain_outside_transport_cutover():
    assert NON_FLOW_INVARIANTS == {
        'tts': 'unchanged',
        'concat': 'unchanged',
        'branding': 'unchanged',
        'review_engine': 'unchanged',
        'project_database_model': 'unchanged',
    }


def test_browser_parity_requires_complete_non_paid_capabilities():
    good = {
        'ready': True,
        'readiness_scope': 'non_paid_parity',
        'operations_implemented': True,
        'paid_dispatch_enabled': False,
        'capabilities': {
            'project_open_resume': True,
            'project_create_session': True,
            'project_media_read': True,
            'media_read': True,
            'operation_reconcile': True,
            'upload': True,
            'paid_dispatch': False,
        },
    }
    assert validate_browser_parity_readiness(good) == {
        'ready': True,
        'missing': [],
        'paid_dispatch_enabled': False,
    }


def test_browser_parity_reports_missing_without_enabling_paid_dispatch():
    bad = {
        'ready': True,
        'readiness_scope': 'non_paid_parity',
        'operations_implemented': True,
        'paid_dispatch_enabled': True,
        'capabilities': {
            'project_open_resume': True,
            'project_create_session': True,
            'project_media_read': True,
            'media_read': False,
            'operation_reconcile': True,
            'upload': True,
            'paid_dispatch': True,
        },
    }
    result = validate_browser_parity_readiness(bad)
    assert result['ready'] is False
    assert 'media_read' in result['missing']
    assert 'paid_dispatch_disabled' in result['missing']
    assert result['paid_dispatch_enabled'] is True
