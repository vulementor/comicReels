"""Read-only adapter for the vi-VN Flow account control observed on 2026-09-27.

No clicks, requests, cookie reads, or inferred authentication from page title/URL.
Unobserved locales/layouts return UNKNOWN. Identity is used only in provider memory.
"""
import re
from urllib.parse import urlsplit

from agent.services.flow_browser_session import AuthObservation

_ACCOUNT_NAME = re.compile(r'^Tài khoản Google: .+\([^\s()@]+@[^\s()@]+\.[^\s()@]+\)$')
_IDENTITY = re.compile(r'^Tài khoản Google: .+\(([^\s()@]+@[^\s()@]+\.[^\s()@]+)\)$')


def observe_flow_account(page) -> AuthObservation:
    """Require exactly one visible scoped account button with explicit identity."""
    try:
        url = urlsplit(page.url)
        if url.scheme != 'https' or url.hostname != 'flow.google.com':
            return AuthObservation()
        container = page.get_by_role('button', name='Thông tin về tài khoản', exact=True)
        if container.count() != 1 or not container.is_visible():
            return AuthObservation()
        account = container.get_by_role('button', name=_ACCOUNT_NAME)
        if account.count() != 1 or not account.is_visible():
            return AuthObservation()
        label = account.get_attribute('aria-label', timeout=1500)
        # The observed DOM label separates display name/email with a newline;
        # Playwright normalizes that whitespace in the accessible name.
        match = _IDENTITY.fullmatch(' '.join((label or '').split()))
        if match:
            return AuthObservation('authenticated', identity=match.group(1).casefold())
    except Exception:  # noqa: BLE001 - never expose account text or browser errors.
        return AuthObservation()
    return AuthObservation()
