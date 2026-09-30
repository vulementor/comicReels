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


## FBR-2-code-2 — session project and non-paid read wiring

Status: **CODE_COMPLETE for this bounded slice on the development branch only**.
Overall FBR-2 remains **CODE_IN_PROGRESS**; upload, operation reconciliation and
facade parity are deliberately deferred to the next coding slices.

Authored project/read coverage: `9f1f75ccf67e6ca45766910f92a997ec6bb13638`.
Project/read implementation: `b9590c4a9cadf3088602ce5e669a420ec1699fd4`.
Lifecycle coverage alignment: `db33b754a5ec2e92e5f191bdb9eca80bb084bb36`.

### Project lifecycle

- `ensure_session_project()` reuses the persisted project id when one exists,
  opens that exact `https://flow.google.com/project/<uuid>` route and requires
  fresh authenticated session evidence after navigation.
- If the active-project pointer was not persisted but a completed create receipt
  exists, the driver recovers the pointer from that immutable receipt without
  resubmitting a remote create effect.
- New session-project creation validates the existing Flow `jHPbke` contract,
  writes a SUBMITTING intent before browser evaluation, verifies the returned
  project UUID/title, writes the completed receipt, then stores the active
  project pointer.
- Ambiguous/unverified create outcomes become UNKNOWN and block later creation
  with `RECONCILIATION_REQUIRED`; they are never retried automatically.
- `force_new=True` gets a distinct deterministic create-intent ordinal after
  prior completed creates. Existing pending/unknown create intents stop the new
  mutation first.
- Raw generic create RPC execution remains disabled in `execute()` because the
  current batch_rpc call surface does not carry a caller idempotency identity.
  The durable session-project method is the only create seam in this slice.

### Read operations

- Reuse the existing validated `flow_browser_rpc.js`; do not add selectors or
  copy Flow request construction.
- `Zzl0ze` project-media reads navigate to and bind the exact requested project.
- `as29s` media reads require the persisted session project and run from that
  verified project page.
- Completed full-body read responses are shape-checked through the existing
  `flow_batch.first_payload` parser before returning to the business layer.
  Existing bounded `match` reads keep their intentionally partial response.
- Reads may continue when the journal contains unrelated pending/unknown intents;
  those intents remain visible as `reconciliation_required` and still block
  mutations that could duplicate an effect.
- `jwpduf` operation reconciliation is still unavailable in code-2 because it
  must be bound to the durable operation/project journal in the next slice.
- Upload and every paid RPC remain explicit 501 / not_submitted capabilities.

### Readiness contract

A freshly authenticated/leased browser session now reports transport
`ready=True` for the implemented project/read subset, with
`readiness_scope=project_read`. The capability map explicitly reports:

- project open/resume: available;
- durable session-project create: available;
- project-media read: available;
- media read: available;
- operation reconciliation: unavailable;
- upload: unavailable;
- paid dispatch: unavailable.

`operations_implemented` remains false so this partial source cannot be mistaken
for all of FBR-2 parity. Extension selection/default behavior is unchanged.

### Authored coverage, NOT executed

`tests/unit/test_flow_browser_driver_project_read.py` covers saved-project
resume, pre-effect create intent persistence, receipt-to-pointer recovery,
unknown-outcome no-replay, exact project-media route binding, saved-project media
reads, explicit operation/upload/raw-create blocking and capability reporting.

The earlier lifecycle coverage was edited only where code-2 intentionally changes
readiness/operation availability. No pytest, workflow, import/compile, lint,
browser session, build or runtime command was executed. These tests are authored
requirements for the later validation pass, not PASS evidence.

No source outside this development branch was changed; no merge/PR was created.
No Remote Desktop, Stable, profile, paid generation, social, scheduler or process
action occurred.

### Next coding slice

**FBR-2-code-3:** wire upload intent/receipt handling and read-only operation
reconciliation into this same driver/state boundary; complete capability/facade
integration and restart/resume authored coverage. Keep paid dispatch false and
extension selectable. After FBR-2 code closure, continue forward through the
remaining approved FBR-3/FBR-4/FBR-5 coding scopes before starting validation.
