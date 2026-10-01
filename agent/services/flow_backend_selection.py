"""Browser-only Flow transport selection policy.

FlowKit no longer supports the Chrome extension transport. Selection exists only
as a compatibility/configuration guard so obsolete extension settings fail closed
instead of silently reviving the old transport.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

BACKEND_ENV = 'COMICREELS_FLOW_BACKEND'
# Legacy configuration name only. It no longer gates or changes transport.
BROWSER_DEFAULT_ACCEPTANCE_ENV = 'COMICREELS_FLOW_BROWSER_DEFAULT_ACCEPTED'


@dataclass(frozen=True)
class BackendSelection:
    kind: Literal['browser'] = 'browser'
    source: Literal['browser_only'] = 'browser_only'

    def metadata(self) -> dict:
        """Detached selection fields; never imply readiness or paid approval."""
        return {
            'backend_kind': 'browser',
            'backend_selection_source': 'browser_only',
            'backend_switch_requires_restart': True,
            'automatic_backend_failover': False,
            'extension_transport_supported': False,
        }


def resolve_backend_selection(environ: Mapping[str, str] | None = None) -> BackendSelection:
    """Return the sole browser transport or reject obsolete backend overrides.

    The legacy acceptance marker is ignored: the owner directive supersedes the
    old browser-default/extension-fallback model. Explicit browser remains valid
    for compatibility. Explicit extension is a fixed configuration error.
    """
    environment = os.environ if environ is None else environ
    if not isinstance(environment, Mapping):
        raise ValueError('FLOW_BACKEND_SELECTION_INVALID')

    if BACKEND_ENV in environment:
        explicit = environment[BACKEND_ENV]
        if explicit == 'extension':
            raise ValueError('FLOW_EXTENSION_BACKEND_REMOVED')
        if not isinstance(explicit, str) or explicit != 'browser':
            raise ValueError('FLOW_BACKEND_SELECTION_INVALID')

    return BackendSelection()
