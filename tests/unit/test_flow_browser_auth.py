"""Observed Vietnamese account UI; auth must fail closed as the surface changes."""
from unittest.mock import Mock

import pytest


def surface(label='Tài khoản Google: Test User (test@example.invalid)', *, count=1,
            visible=True, host='https://flow.google.com/'):
    account = Mock()
    account.count.return_value = count
    account.is_visible.return_value = visible
    account.get_attribute.return_value = label
    container = Mock()
    container.count.return_value = 1
    container.is_visible.return_value = True
    container.get_by_role.return_value = account
    page = Mock(url=host)
    page.get_by_role.return_value = container
    return page, container, account


def probe(page):
    from agent.services.flow_browser_auth import observe_flow_account
    return observe_flow_account(page)


def test_observed_account_identity_is_private_and_requires_scoped_visible_control():
    page, container, account = surface()
    result = probe(page)
    assert result.state == 'authenticated'
    assert result.identity == 'test@example.invalid'
    assert result.identity not in repr(result)
    page.get_by_role.assert_called_once_with('button', name='Thông tin về tài khoản', exact=True)
    assert container.get_by_role.call_args.args == ('button',)
    account.get_attribute.assert_called_once_with('aria-label', timeout=1500)


@pytest.mark.parametrize('options', [
    {'count': 0}, {'count': 2}, {'visible': False},
    {'label': None}, {'label': 'Tài khoản Google: Test User'},
    {'label': 'Tài khoản Google: Test User (not-an-email)'},
    {'label': 'Unverified (test@example.invalid)'},
    {'host': 'https://example.invalid/'}, {'host': 'http://flow.google.com/'},
])
def test_missing_ambiguous_hidden_or_changed_evidence_stays_unknown(options):
    result = probe(surface(**options)[0])
    assert result.state == 'unknown'
    assert result.identity is None


def test_disconnected_page_is_sanitized():
    page, _, _ = surface()
    page.get_by_role.side_effect = RuntimeError('private URL and account')
    assert probe(page).state == 'unknown'


def test_live_aria_label_line_break_is_normalized_like_accessible_name():
    page, _, _ = surface(label='Tài khoản Google: Test User\n(test@example.invalid)')
    assert probe(page).identity == 'test@example.invalid'


def test_ambiguous_or_hidden_account_container_is_not_trusted():
    page, container, _ = surface()
    container.count.return_value = 2
    assert probe(page).state == 'unknown'
    container.count.return_value = 1
    container.is_visible.return_value = False
    assert probe(page).state == 'unknown'
