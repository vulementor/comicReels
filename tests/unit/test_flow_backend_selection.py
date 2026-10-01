"""Browser-only backend selection requirements.

Authored during the development-first coding phase; execution is deferred until
the dedicated validation phase.
"""
from dataclasses import FrozenInstanceError

import pytest

from agent.services.flow_backend_selection import (
    BACKEND_ENV,
    BROWSER_DEFAULT_ACCEPTANCE_ENV,
    resolve_backend_selection,
)


@pytest.mark.parametrize('environ', [
    {},
    {BACKEND_ENV: 'browser'},
    {BROWSER_DEFAULT_ACCEPTANCE_ENV: '0'},
    {BROWSER_DEFAULT_ACCEPTANCE_ENV: '1'},
    {BROWSER_DEFAULT_ACCEPTANCE_ENV: 'legacy-value-is-ignored'},
    {BACKEND_ENV: 'browser', BROWSER_DEFAULT_ACCEPTANCE_ENV: '0'},
])
def test_browser_is_the_only_valid_runtime_selection(environ):
    selected = resolve_backend_selection(environ)
    assert selected.kind == 'browser'
    assert selected.source == 'browser_only'


def test_extension_backend_is_rejected_as_removed():
    with pytest.raises(ValueError, match='^FLOW_EXTENSION_BACKEND_REMOVED$'):
        resolve_backend_selection({BACKEND_ENV: 'extension'})


@pytest.mark.parametrize('bad', ['', ' ', 'Browser', 'auto', 'extension ', True, None, 1])
def test_invalid_backend_is_rejected_without_guessing(bad):
    with pytest.raises(ValueError, match='^FLOW_BACKEND_SELECTION_INVALID$'):
        resolve_backend_selection({BACKEND_ENV: bad})


def test_errors_never_echo_private_backend_values():
    private = 'private-profile@example.test token=private'
    with pytest.raises(ValueError) as error:
        resolve_backend_selection({BACKEND_ENV: private})
    assert str(error.value) == 'FLOW_BACKEND_SELECTION_INVALID'
    assert private not in str(error.value)


def test_legacy_acceptance_marker_is_read_only_and_has_no_transport_effect(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, 'anything')
    assert resolve_backend_selection().kind == 'browser'
    assert resolve_backend_selection().source == 'browser_only'


def test_supplied_empty_environment_does_not_consult_process_backend(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    selected = resolve_backend_selection({})
    assert selected.kind == 'browser'


def test_supplied_configuration_is_not_mutated_and_metadata_is_browser_only():
    environ = {BACKEND_ENV: 'browser', 'UNRELATED_SECRET': 'private'}
    original = dict(environ)
    selected = resolve_backend_selection(environ)
    assert environ == original
    metadata = selected.metadata()
    assert metadata == {
        'backend_kind': 'browser',
        'backend_selection_source': 'browser_only',
        'backend_switch_requires_restart': True,
        'automatic_backend_failover': False,
        'extension_transport_supported': False,
    }
    assert not {'ready', 'backend_ready', 'operations_implemented',
                'paid_dispatch_enabled', 'owner_accepted'} & metadata.keys()
    assert 'private' not in str(metadata)
    metadata['backend_kind'] = 'extension'
    assert selected.metadata()['backend_kind'] == 'browser'
    with pytest.raises(FrozenInstanceError):
        selected.kind = 'extension'
