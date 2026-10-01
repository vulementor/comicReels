"""Pure startup selection policy for the owner-gated browser default cutover.

Selection is configuration, not evidence of health, parity or paid authorization.
This module never starts a client/browser, changes the environment or falls back
in response to a runtime failure. The application must hold its selected backend
until a controlled close/restart. Startup wiring is a separate FBR-5 slice.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

BACKEND_ENV = 'COMICREELS_FLOW_BACKEND'
BROWSER_DEFAULT_ACCEPTANCE_ENV = 'COMICREELS_FLOW_BROWSER_DEFAULT_ACCEPTED'
BROWSER_DEFAULT_CANDIDATE = 'browser'


@dataclass(frozen=True)
class BackendSelection:
    kind: Literal['extension', 'browser']
    source: Literal['explicit', 'extension_default', 'accepted_browser_default']

    def metadata(self) -> dict:
        """Detached selection-only fields; no health/acceptance/paid verdict."""
        return {
            'backend_kind': self.kind,
            'backend_selection_source': self.source,
            'browser_default_candidate': BROWSER_DEFAULT_CANDIDATE,
            'backend_switch_requires_restart': True,
            'automatic_backend_failover': False,
        }


def resolve_backend_selection(environ: Mapping[str, str] | None = None) -> BackendSelection:
    """Resolve one startup choice without inspecting either backend or profile.

    Explicit selection wins, including extension rollback when a browser default
    marker is broken. An absent override retains extension unless an operator has
    recorded PRIOR owner acceptance with the exact marker ``1``. This parser does
    not verify that acceptance; deployment/operator gates must do so separately.
    An explicit browser selection remains available for non-paid validation.
    """
    environment = os.environ if environ is None else environ
    if not isinstance(environment, Mapping):
        raise ValueError('FLOW_BACKEND_SELECTION_INVALID')

    if BACKEND_ENV in environment:
        explicit = environment[BACKEND_ENV]
        if not isinstance(explicit, str) or explicit not in ('extension', 'browser'):
            raise ValueError('FLOW_BACKEND_SELECTION_INVALID')
        # Do not parse unrelated browser-default configuration on the rollback
        # path. Browser dependencies/profile health cannot block this decision.
        return BackendSelection(kind=explicit, source='explicit')

    accepted = environment.get(BROWSER_DEFAULT_ACCEPTANCE_ENV, '0')
    if not isinstance(accepted, str) or accepted not in ('0', '1'):
        raise ValueError('FLOW_BROWSER_DEFAULT_ACCEPTANCE_INVALID')
    if accepted == '1':
        return BackendSelection(kind='browser', source='accepted_browser_default')
    return BackendSelection(kind='extension', source='extension_default')
