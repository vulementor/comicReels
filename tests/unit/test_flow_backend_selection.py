"""FBR-5-code-1 authored requirements; execution is deferred until validation."""
from dataclasses import FrozenInstanceError

import pytest

from agent.services.flow_backend_selection import (
    BACKEND_ENV,
    BROWSER_DEFAULT_ACCEPTANCE_ENV,
    BROWSER_DEFAULT_CANDIDATE,
    resolve_backend_selection,
)


@pytest.mark.parametrize('marker,expected,source', [
    (None, 'extension', 'extension_default'),
    ('0', 'extension', 'extension_default'),
    ('1', 'browser', 'accepted_browser_default'),
])
def test_absent_override_uses_only_explicit_default_acceptance(marker, expected, source):
    environ = {} if marker is None else {BROWSER_DEFAULT_ACCEPTANCE_ENV: marker}
    selected = resolve_backend_selection(environ)
    assert selected.kind == expected
    assert selected.source == source
    assert BROWSER_DEFAULT_CANDIDATE == 'browser'


@pytest.mark.parametrize('explicit', ['extension', 'browser'])
@pytest.mark.parametrize('marker', [None, '0', '1', 'broken-browser-setting'])
def test_explicit_backend_wins_without_parsing_default_marker(explicit, marker):
    environ = {BACKEND_ENV: explicit}
    if marker is not None:
        environ[BROWSER_DEFAULT_ACCEPTANCE_ENV] = marker
    selected = resolve_backend_selection(environ)
    assert selected.kind == explicit
    assert selected.source == 'explicit'


@pytest.mark.parametrize('bad', ['', ' ', 'Browser', 'auto', 'extension ', True, None, 1])
def test_invalid_explicit_backend_never_silently_selects_a_default(bad):
    with pytest.raises(ValueError, match='^FLOW_BACKEND_SELECTION_INVALID$'):
        resolve_backend_selection({
            BACKEND_ENV: bad,
            BROWSER_DEFAULT_ACCEPTANCE_ENV: '1',
        })


@pytest.mark.parametrize('bad', ['', ' ', 'true', 'yes', '01', '1 ', True, None, 1])
def test_invalid_acceptance_marker_without_override_fails_closed(bad):
    with pytest.raises(ValueError, match='^FLOW_BROWSER_DEFAULT_ACCEPTANCE_INVALID$'):
        resolve_backend_selection({BROWSER_DEFAULT_ACCEPTANCE_ENV: bad})


def test_rollback_works_even_when_browser_default_configuration_is_invalid():
    class RollbackEnvironment(dict):
        def get(self, key, default=None):
            if key == BROWSER_DEFAULT_ACCEPTANCE_ENV:
                raise AssertionError('rollback must not inspect browser-default settings')
            return super().get(key, default)

    selected = resolve_backend_selection(RollbackEnvironment({BACKEND_ENV: 'extension'}))
    assert selected.kind == 'extension'
    assert selected.source == 'explicit'


def test_configuration_errors_never_echo_user_supplied_values():
    private = 'private-profile@example.test token=private'
    for environ, expected in [
        ({BACKEND_ENV: private}, 'FLOW_BACKEND_SELECTION_INVALID'),
        ({BROWSER_DEFAULT_ACCEPTANCE_ENV: private}, 'FLOW_BROWSER_DEFAULT_ACCEPTANCE_INVALID'),
    ]:
        with pytest.raises(ValueError) as error:
            resolve_backend_selection(environ)
        assert str(error.value) == expected
        assert private not in str(error.value)


def test_process_environment_is_read_only(monkeypatch):
    monkeypatch.delenv(BACKEND_ENV, raising=False)
    monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, '1')
    assert resolve_backend_selection().kind == 'browser'
    monkeypatch.setenv(BACKEND_ENV, 'extension')
    assert resolve_backend_selection().kind == 'extension'


def test_supplied_empty_environment_does_not_fall_back_to_process_environment(monkeypatch):
    monkeypatch.setenv(BACKEND_ENV, 'browser')
    monkeypatch.setenv(BROWSER_DEFAULT_ACCEPTANCE_ENV, '1')
    assert resolve_backend_selection({}).kind == 'extension'


def test_supplied_configuration_is_not_mutated_or_shared_in_metadata():
    environ = {BACKEND_ENV: 'browser', 'UNRELATED_SECRET': 'private'}
    original = dict(environ)
    selected = resolve_backend_selection(environ)
    assert environ == original
    metadata = selected.metadata()
    assert metadata == {
        'backend_kind': 'browser',
        'backend_selection_source': 'explicit',
        'browser_default_candidate': 'browser',
        'backend_switch_requires_restart': True,
        'automatic_backend_failover': False,
    }
    assert not {'ready', 'backend_ready', 'operations_implemented',
                'paid_dispatch_enabled', 'owner_accepted'} & metadata.keys()
    assert 'private' not in str(metadata)
    metadata['backend_kind'] = 'extension'
    assert selected.metadata()['backend_kind'] == 'browser'
    with pytest.raises(FrozenInstanceError):
        selected.kind = 'extension'
