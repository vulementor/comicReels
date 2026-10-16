"""Strict, read-only Flow account identity adapter for observed vi-VN layouts.

Accepts the original September 2026 nested account control and the current
October 2026 standalone Google-account anchor. Both require a live scoped
identity label and unique visible control on the official HTTPS Flow origin.

No clicking, cookies, token reads, title-only or PRO-badge authentication.
Unknown/ambiguous layouts return UNKNOWN.
"""
import re
from urllib.parse import urlsplit

from agent.services.flow_browser_session import AuthObservation

_LEGACY_ACCOUNT_NAME = re.compile(
    r'^Tài khoản Google: .+\([^\s()@]+@[^\s()@]+\.[^\s()@]+\)$'
)
_LEGACY_IDENTITY = re.compile(
    r'^Tài khoản Google: .+\(([^\s()@]+@[^\s()@]+\.[^\s()@]+)\)$'
)
_CURRENT_IDENTITY = re.compile(
    r'^Tài khoản Google: .+ \(([^\s()@]+@[^\s()@]+\.[^\s()@]+)\), '
    r'Gói thành viên của Google$'
)


def _account_email_from_scoped_control(page) -> str | None:
    legacy_identity = None
    legacy = page.get_by_role(
        'button', name='Thông tin về tài khoản', exact=True
    )
    if legacy.count() == 1 and legacy.is_visible():
        inner = legacy.get_by_role('button', name=_LEGACY_ACCOUNT_NAME)
        if inner.count() == 1 and inner.is_visible():
            label = inner.get_attribute('aria-label', timeout=1500)
            match = _LEGACY_IDENTITY.fullmatch(' '.join((label or '').split()))
            if match:
                legacy_identity = match.group(1).casefold()

    # The new standalone account anchor often lives inside the SAME old
    # account-header wrapper. An unmatched legacy child must not short-circuit
    # current-UI authentication. Never use PRO or the header itself as proof.
    current_identity = None
    control = page.locator(
        'a[role="button"][aria-label^="Tài khoản Google: "]'
    )
    if control.count() == 1 and control.is_visible():
        label = control.get_attribute('aria-label', timeout=1500)
        match = _CURRENT_IDENTITY.fullmatch(' '.join((label or '').split()))
        if match:
            current_identity = match.group(1).casefold()

    # Two independently valid but conflicting identity labels fail closed.
    if legacy_identity and current_identity and legacy_identity != current_identity:
        return None
    return legacy_identity or current_identity


def observe_flow_account(page) -> AuthObservation:
    """Require one visible account identity on the exact official origin."""
    try:
        url = urlsplit(page.url)
        if (url.scheme != 'https' or url.hostname != 'flow.google.com'
                or url.username or url.password or url.port not in (None, 443)):
            return AuthObservation()
        identity = _account_email_from_scoped_control(page)
        if identity:
            return AuthObservation('authenticated', identity=identity)
    except Exception:  # noqa: BLE001 - no leaked account labels or browser errors
        pass
    return AuthObservation()


_CURRENT_CREDIT = re.compile(r'^(\d{1,3}(?:\.\d{3})*|\d+) tín dụng Google Flow$')


def read_current_flow_balance(page) -> dict:
    """Read credits from authenticated account panel, never click Generate.

    Only supports the strictly observed standalone October 2026 account
    control. Unfamiliar UI or ambiguous balance fails closed; no network API,
    cookie, browser profile modification, upload or paid operation.
    """
    if observe_flow_account(page).state != 'authenticated':
        raise ValueError('FLOW_ACCOUNT_NOT_VERIFIED')
    url = urlsplit(page.url)
    if (url.hostname != 'flow.google.com' or url.scheme != 'https'
            or not url.path.startswith('/project/')):
        raise ValueError('FLOW_PROJECT_NOT_VERIFIED')
    control = page.locator('a[role="button"][aria-label^="Tài khoản Google: "]')
    if control.count() != 1 or not control.is_visible():
        raise ValueError('FLOW_ACCOUNT_BUTTON_MISSING')
    label = control.get_attribute('aria-label', timeout=1500)
    if _CURRENT_IDENTITY.fullmatch(' '.join((label or '').split())) is None:
        raise ValueError('FLOW_ACCOUNT_LABEL_CHANGED')
    # Native Playwright press/click on a nested anchor can time out even
    # though the account control is visible. This is NOT a paid action.
    control.evaluate('(account) => account.click()')
    dialog = page.get_by_role('dialog', name='Cài đặt tài khoản', exact=True)
    dialog.wait_for(state='visible', timeout=10000)
    link = dialog.get_by_role('link', name=_CURRENT_CREDIT)
    if link.count() != 1 or not link.is_visible():
        raise ValueError('FLOW_BALANCE_UNVERIFIED')
    label = ' '.join(link.inner_text(timeout=1500).split())
    match = _CURRENT_CREDIT.fullmatch(label)
    if match is None:
        raise ValueError('FLOW_BALANCE_UNVERIFIED')
    balance = int(match.group(1).replace('.', ''))
    if not 0 <= balance <= 10000000:
        raise ValueError('FLOW_BALANCE_OUT_OF_RANGE')
    return {'balance_credits': balance, 'source': 'authenticated_ui_account_dialog',
            'paid_generate_called': False}
