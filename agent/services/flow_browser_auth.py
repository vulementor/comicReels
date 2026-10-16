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
    legacy = page.get_by_role(
        'button', name='Thông tin về tài khoản', exact=True
    )
    if legacy.count() == 1 and legacy.is_visible():
        inner = legacy.get_by_role('button', name=_LEGACY_ACCOUNT_NAME)
        if inner.count() != 1 or not inner.is_visible():
            return None
        label = inner.get_attribute('aria-label', timeout=1500)
        match = _LEGACY_IDENTITY.fullmatch(' '.join((label or '').split()))
        return match.group(1).casefold() if match else None

    # The new button is an <a role="button">, not a nested <button>.
    # No broader identity discovery is allowed on other page elements.
    control = page.locator(
        'a[role="button"][aria-label^="Tài khoản Google: "]'
    )
    if control.count() != 1 or not control.is_visible():
        return None
    label = control.get_attribute('aria-label', timeout=1500)
    match = _CURRENT_IDENTITY.fullmatch(' '.join((label or '').split()))
    return match.group(1).casefold() if match else None


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
