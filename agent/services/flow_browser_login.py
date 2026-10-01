"""Owner-driven Flow login helper with explicit, read-only lifecycle semantics.

The helper never selects an account, enters credentials, handles OAuth/CAPTCHA,
or enables paid dispatch.  It only opens the already-bound persistent Flow
profile, observes the existing authentication surface, and exits cleanly after
fresh authenticated readiness, owner window close, or KeyboardInterrupt.
"""
from __future__ import annotations

import time
from collections.abc import Callable

from agent.services.flow_browser_auth import observe_flow_account
from agent.services.flow_browser_session import (
    FlowBrowserError,
    FlowBrowserSessionProvider,
    FlowProfileConfig,
)


def _auth_projection(health: dict | None) -> dict:
    health = health if isinstance(health, dict) else {}
    authentication = health.get('authentication')
    if authentication not in {'authenticated', 'signed_out', 'unknown'}:
        authentication = 'unknown'
    count = health.get('semantic_node_count')
    if type(count) is not int or count < 0:
        count = 0
    observed_at = health.get('observed_at')
    if not isinstance(observed_at, str) or len(observed_at) > 64:
        observed_at = None
    return {
        'authentication': authentication,
        'ready': bool(health.get('ready') is True and authentication == 'authenticated'),
        'semantic_node_count': count,
        'observed_at': observed_at,
        'error': health.get('error') if isinstance(health.get('error'), str) else None,
    }


def run_flow_login_session(
    *,
    provider_factory: Callable = FlowBrowserSessionProvider,
    sleep: Callable[[float], None] = time.sleep,
    poll_seconds: float = 0.5,
) -> dict:
    """Run one visible owner-login session and always release its provider lease.

    The browser is intentionally passive.  The owner performs every interactive
    sign-in step.  Fresh provider health is observed while the page is open.  As
    soon as authenticated readiness is proven the helper returns and closes its
    owned browser context.  Closing the window or pressing Ctrl+C are also clean
    terminal conditions.

    Any close failure is deliberately not swallowed: FlowBrowserSessionProvider
    raises the fixed public code CLOSE_UNCERTAIN and the CLI surfaces that code.
    """
    if not isinstance(poll_seconds, (int, float)) or poll_seconds <= 0:
        raise ValueError('poll_seconds must be positive')

    config = FlowProfileConfig.load()
    provider = provider_factory(
        config,
        auth_probe=observe_flow_account,
        visible=True,
    )
    opened = False
    state = 'window_closed'
    last = _auth_projection(None)

    try:
        provider.open()
        opened = True
        while True:
            session = getattr(provider, 'session', None)
            page = getattr(session, 'page', None)
            if page is None:
                raise FlowBrowserError('FLOW_PAGE_UNAVAILABLE')
            if page.is_closed():
                state = 'window_closed'
                break

            health = provider.capture_health()
            last = _auth_projection(health)
            if last['ready']:
                state = 'authenticated'
                break
            sleep(float(poll_seconds))
    except KeyboardInterrupt:
        state = 'interrupted'
    finally:
        if opened:
            # Exactly one close call belongs to this helper after a successful
            # open.  Do not catch CLOSE_UNCERTAIN or manually touch lease files.
            provider.close()

    return {
        'state': state,
        'profile': config.profile_logical_name,
        **last,
    }
