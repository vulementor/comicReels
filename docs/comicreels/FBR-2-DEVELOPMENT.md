# FBR-2 development ledger

## Authority and execution boundary

- Architecture: `FLOW-BROWSER-FIRST-ARCHITECTURE.md`.
- Approved plan: `../superpowers/plans/2026-09-27-flow-browser-refactor.md`.
- Current execution directive: `AGENTS.md`, Development execution rule (2026-09-30).
- Continue the approved GitHub coding pass before running tests, rebuilds, runtime
  observations or validation/fix loops. Do not use Remote Desktop Commander.
- This ledger supplements the historical `CHECKPOINTS.md` and the A3.10-1 source
  reconciliation recorded on PR #7. Historical runtime results are not current acceptance.

## FBR-2-code-1 — concrete lifecycle and state boundary

Status: **CODE_COMPLETE for this bounded slice on the development branch only**.
Overall FBR-2 status: **CODE_IN_PROGRESS**, not ready for validation or merge.

Base: `373e0a2e416819774fa88df0517b71868832b138` (canonical main at start).
Branch: `feat/fbr-2-driver-lifecycle-20260930`.
Authored coverage commit: `a868a53c1ad38a43a4627fadb6ccdcbe431c640c`.
Lifecycle implementation: `b88e36f8f45693fff4f30b3c3fa5129ea1c25a3f`.
Lease-observation completion: `320b4dcad7ec3f0d393218b579aa999845cbbe7e`.

### Implemented source

`agent/services/flow_browser_driver.py` now supplies the concrete class imported
by `BrowserFlowBackend._start()` when no fake driver factory is supplied.
Its constructor matches the existing positional config/state-path/owner-key seam.
No existing backend or extension-selection code is changed in this slice.

- Reuse `FlowBrowserSessionProvider`, `observe_flow_account`, `FlowProfileConfig`
  and `BrowserStateStore`; do not copy their browser/lease/journal implementations.
- Constructor/import does not launch a browser. `start()` binds the existing owner
  thread and verifies the original profile directory before provider creation.
- Read state only while the provider reports an open, held profile lease.
- Validate saved owner/schema through the existing store. Corrupt/foreign state
  fails closed and is not rewritten, deleted or treated as an empty successful run.
- Preserve existing SUBMITTING/UNKNOWN receipts. No resend, reconciliation mutation
  or fabricated completion occurs in start/health/close.
- Request fresh, read-only authentication/semantic observations. Project only
  bounded public fields; do not expose account identity, profile path, raw journal
  contents or native browser exception messages.
- Retain the same provider on uncertain close for an explicit same-owner close
  retry. Do not independently release its lease or create a replacement context.
- Unobserved lease state, especially after CLOSE_UNCERTAIN, stays null/unknown;
  it is not reported as released. Clean close is idempotent and terminal.

### Deliberately unavailable operations

`health().session_ready` describes fresh session evidence only. `health().ready`
remains false and `operations_implemented` remains false until the next coding
slices wire the required operations. `paid_dispatch_enabled` remains false.

`execute` and `open_project` return explicit 501 / not_submitted results;
`ensure_session_project` raises a fixed capability-not-implemented error.
They do not navigate, create projects, upload, fetch media, mutate receipts or pay.
The async facade therefore cannot advertise this partial driver as a ready backend.
These are explicit remaining implementation boundaries, not completed FBR-2 parity.

### Authored coverage, NOT executed

`tests/unit/test_flow_browser_driver_lifecycle.py` covers constructor side effects,
canonical profile/auth wiring, real journal preservation, invalid/foreign state,
fresh auth observations, lease loss, start failure, close uncertainty/retry,
wrong-thread rejection and blocked operations.

The default-path test instantiates the real driver through BrowserFlowBackend
without supplying driver_factory. Only the browser/session provider is replaced
with a deterministic fake. No live browser/profile is used by that test design.

No pytest, import smoke, compile, lint, build, workflow dispatch/rerun or other
runtime validation was executed for this development checkpoint. Coverage being
written does not mean the tests pass. Branch commits carry [skip ci]; no new PR is
opened during this slice because the current workflow triggers on pull_request.

KBS dependency unchanged: `requirements-flow-browser.txt` pins
`b539e9820d433c8c9d667b4e5d9007b6a80b8abd`. Compatibility with that declared pin
and the later Stable dependency set is a deferred validation obligation, not
silently inferred from old runtime observations.

Runtime backend, physical profile health/lease, runtime revision, scheduler state
and existing paid-effect state were NOT inspected. No Stable deployment, source
hotfix, browser launch, paid generation or social publication was performed.

### Forward continuation

1. **FBR-2-code-2:** connect non-paid project create/open/resume and read/media
   operations through existing validated contracts, discovery/semantic helpers
   and the same leased provider. Reuse persisted project identity; do not guess
   undocumented browser selectors or refresh stale paid results by resubmitting.
2. Complete upload intent/receipt binding and explicit read-only reconciliation;
   preserve source hashes, media UUID/project binding and uncertain outcomes.
3. Complete facade readiness/capability reporting, restart/resume integration and
   authored coverage for concrete operations before declaring all FBR-2 code done.
4. Continue the separately scoped FBR-3/FBR-4/FBR-5 coding requirements from the
   approved plan. No paid activation, production default cutover or FBR-6 extension
   deletion follows from this lifecycle slice.
5. Only after the complete approved coding pass, request/perform the separate
   non-Remote-Desktop validation phase with fresh results at its actual revision.

Concurrent PR #12 (KAT staging) and other feature branches remain untouched.
This slice is unrelated to diagnosing or repairing the old Stable source-directory
move denial; it does not justify resuming the stale A3.9 rebuild sequence.

Rollback: main is unchanged. Leave this unmerged development branch unused;
no runtime/profile/data rollback or destructive reset is needed.
