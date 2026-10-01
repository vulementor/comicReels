"""Offline lifecycle coverage for the owner-driven Flow login helper."""
from types import SimpleNamespace

import pytest

from agent.services import flow_browser_login as login
from agent.services.flow_browser_session import FlowBrowserError


class Page:
    def __init__(self):
        self.closed = False

    def is_closed(self):
        return self.closed


class Provider:
    def __init__(self, config, *, health=None, capture_error=None, close_error=None):
        self.config = config
        self.session = SimpleNamespace(page=Page())
        self.health = health or {
            'authentication': 'unknown',
            'ready': False,
            'semantic_node_count': 2,
            'observed_at': '2026-10-01T16:24:48+00:00',
            'error': 'BROWSER_NOT_READY',
        }
        self.capture_error = capture_error
        self.close_error = close_error
        self.open_calls = 0
        self.close_calls = 0
        self.capture_calls = 0

    def open(self):
        self.open_calls += 1
        return self

    def capture_health(self):
        self.capture_calls += 1
        if self.capture_error is not None:
            raise self.capture_error
        return dict(self.health)

    def close(self):
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error


@pytest.fixture
def config(monkeypatch):
    value = SimpleNamespace(profile_logical_name='flow-browser')
    monkeypatch.setattr(login.FlowProfileConfig, 'load', lambda *args, **kwargs: value)
    return value


def factory_for(provider, seen):
    def factory(config, *, auth_probe, visible):
        seen.append({'config': config, 'auth_probe': auth_probe, 'visible': visible})
        return provider
    return factory


def test_authenticated_readiness_finishes_and_closes_exactly_once(config):
    provider = Provider(config, health={
        'authentication': 'authenticated',
        'ready': True,
        'semantic_node_count': 17,
        'observed_at': '2026-10-01T16:24:48+00:00',
        'error': None,
    })
    seen = []
    result = login.run_flow_login_session(
        provider_factory=factory_for(provider, seen),
        sleep=lambda _: pytest.fail('authenticated readiness must finish without another wait'),
    )
    assert result == {
        'state': 'authenticated',
        'profile': 'flow-browser',
        'authentication': 'authenticated',
        'ready': True,
        'semantic_node_count': 17,
        'observed_at': '2026-10-01T16:24:48+00:00',
        'error': None,
    }
    assert provider.open_calls == provider.capture_calls == provider.close_calls == 1
    assert seen[0]['config'] is config and seen[0]['visible'] is True
    assert seen[0]['auth_probe'] is login.observe_flow_account


def test_owner_window_close_returns_last_read_only_auth_and_closes_once(config):
    provider = Provider(config)
    seen = []

    def close_window(_):
        provider.session.page.closed = True

    result = login.run_flow_login_session(
        provider_factory=factory_for(provider, seen),
        sleep=close_window,
    )
    assert result['state'] == 'window_closed'
    assert result['authentication'] == 'unknown'
    assert result['ready'] is False
    assert provider.capture_calls == 1
    assert provider.close_calls == 1


def test_session_exception_still_closes_exactly_once(config):
    provider = Provider(config, capture_error=RuntimeError('private browser detail'))
    with pytest.raises(RuntimeError, match='private browser detail'):
        login.run_flow_login_session(
            provider_factory=factory_for(provider, []),
            sleep=lambda _: None,
        )
    assert provider.open_calls == 1
    assert provider.capture_calls == 1
    assert provider.close_calls == 1


def test_keyboard_interrupt_returns_status_and_closes_exactly_once(config):
    provider = Provider(config)

    def interrupt(_):
        raise KeyboardInterrupt

    result = login.run_flow_login_session(
        provider_factory=factory_for(provider, []),
        sleep=interrupt,
    )
    assert result['state'] == 'interrupted'
    assert result['authentication'] == 'unknown'
    assert provider.capture_calls == 1
    assert provider.close_calls == 1


def test_close_uncertain_is_surfaced_instead_of_swallowed(config):
    provider = Provider(
        config,
        health={
            'authentication': 'authenticated',
            'ready': True,
            'semantic_node_count': 4,
            'observed_at': '2026-10-01T16:24:48+00:00',
            'error': None,
        },
        close_error=FlowBrowserError('CLOSE_UNCERTAIN'),
    )
    with pytest.raises(FlowBrowserError, match='CLOSE_UNCERTAIN'):
        login.run_flow_login_session(
            provider_factory=factory_for(provider, []),
            sleep=lambda _: None,
        )
    assert provider.close_calls == 1


def test_helper_has_no_interactive_login_surface(config):
    provider = Provider(config, health={
        'authentication': 'authenticated',
        'ready': True,
        'semantic_node_count': 1,
        'observed_at': '2026-10-01T16:24:48+00:00',
        'error': None,
    })
    # Page intentionally exposes no click/fill/goto/account-selection methods.
    result = login.run_flow_login_session(
        provider_factory=factory_for(provider, []),
        sleep=lambda _: None,
    )
    assert result['state'] == 'authenticated'
    assert provider.close_calls == 1


def test_flow_login_cli_returns_read_only_status(monkeypatch, capsys):
    from agent.thoremix import cli

    expected = {
        'state': 'authenticated',
        'profile': 'flow-browser',
        'authentication': 'authenticated',
        'ready': True,
        'semantic_node_count': 3,
        'observed_at': '2026-10-01T16:24:48+00:00',
        'error': None,
    }
    monkeypatch.setattr(login, 'run_flow_login_session', lambda: expected)
    assert cli.main(['flow-login']) == 0
    assert __import__('json').loads(capsys.readouterr().out) == expected


def test_flow_login_cli_surfaces_close_uncertain_code(monkeypatch, capsys):
    from agent.thoremix import cli

    def fail():
        raise FlowBrowserError('CLOSE_UNCERTAIN')

    monkeypatch.setattr(login, 'run_flow_login_session', fail)
    assert cli.main(['flow-login']) == 2
    result = __import__('json').loads(capsys.readouterr().out)
    assert result['state'] == 'needs_input'
    assert result['error_type'] == 'FlowBrowserError'
    assert result['reason'] == 'CLOSE_UNCERTAIN'
