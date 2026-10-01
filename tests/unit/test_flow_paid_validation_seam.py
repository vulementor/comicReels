"""Task 4d authored controlled paid-validation authorization requirements.

Source-only coverage. No test or paid effect is executed during development.
"""
from pathlib import Path

import pytest

from agent.services.flow_paid_validation import (
    PaidValidationSession,
    build_paid_validation_session,
)


class BackendStub:
    kind = 'browser'
    ready = True
    paid_dispatch_enabled = True
    session_owner_key = 'validation-owner'

    def __init__(self):
        self.started = 0
        self.closed = 0
        self.calls = []

    async def start(self):
        self.started += 1

    async def close(self):
        self.closed += 1

    async def check_readiness(self):
        return {'ready': True, 'paid_dispatch_enabled': True}

    async def open_project(self, project_id):
        return {'status': 200}

    async def ensure_session_project(self, *, title=None, force_new=False):
        return {'status': 200}

    async def execute(self, method, params, timeout=300):
        return {'status': 404, 'error': 'unused'}

    async def submit_paid_image(self, params, *, idempotency_key,
                                authorization=None, timeout=300):
        self.calls.append((params, idempotency_key, authorization, timeout))
        return {
            'status': 409,
            'error': 'PAID_RECONCILIATION_REQUIRED',
            'effect': 'unknown',
        }


def test_production_singleton_has_no_validation_import_or_paid_enablement():
    source = Path('agent/services/flow_client.py').read_text(encoding='utf-8')
    main = Path('agent/main.py').read_text(encoding='utf-8')

    assert 'flow_paid_validation' not in source
    assert 'flow_paid_validation' not in main
    assert 'paid_dispatch_enabled=True' not in source
    assert 'paid_authorization=' not in main


@pytest.mark.parametrize('bad', [None, True, False, 1, 'owner-approved', b'token'])
def test_validation_session_requires_caller_owned_opaque_object(bad):
    with pytest.raises(ValueError, match='^PAID_VALIDATION_AUTHORIZATION_REQUIRED$'):
        build_paid_validation_session(bad)


def test_validation_session_does_not_expose_authorization_or_client_publicly():
    authorization = object()
    backend = BackendStub()
    session = PaidValidationSession._for_test(authorization, backend)

    assert not hasattr(session, 'authorization')
    assert not hasattr(session, 'client')
    assert session.paid_dispatch_enabled is True
    assert session.used is False


@pytest.mark.asyncio
async def test_validation_session_forwards_same_object_and_consumes_one_shot_before_await():
    authorization = object()
    backend = BackendStub()
    session = PaidValidationSession._for_test(authorization, backend)

    result = await session.generate_one_image(
        prompt='approved validation image',
        project_id='11111111-2222-3333-4444-555555555555',
        idempotency_key='validation-shot-1',
    )

    assert result['effect'] == 'unknown'
    assert session.used is True
    assert len(backend.calls) == 1
    assert backend.calls[0][1] == 'validation-shot-1'
    assert backend.calls[0][2] is authorization


@pytest.mark.asyncio
async def test_validation_session_never_auto_retries_or_allows_second_paid_attempt():
    authorization = object()
    backend = BackendStub()
    session = PaidValidationSession._for_test(authorization, backend)

    first = await session.generate_one_image(
        prompt='approved validation image',
        project_id='11111111-2222-3333-4444-555555555555',
        idempotency_key='validation-shot-1',
    )
    second = await session.generate_one_image(
        prompt='should not submit',
        project_id='11111111-2222-3333-4444-555555555555',
        idempotency_key='validation-shot-2',
    )

    assert first['effect'] == 'unknown'
    assert second == {
        'status': 409,
        'error': 'PAID_VALIDATION_SHOT_ALREADY_USED',
        'effect': 'not_submitted',
    }
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_validation_lifecycle_is_explicit_and_not_started_by_factory():
    authorization = object()
    backend = BackendStub()
    session = PaidValidationSession._for_test(authorization, backend)

    assert backend.started == 0
    await session.start()
    assert backend.started == 1
    await session.close()
    assert backend.closed == 1


def test_no_environment_or_http_activation_surface_is_added():
    source = Path('agent/services/flow_paid_validation.py').read_text(encoding='utf-8')
    assert 'os.environ' not in source
    assert 'FastAPI' not in source
    assert 'APIRouter' not in source
    assert '@router' not in source
