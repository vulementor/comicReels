# FBR-2 development ledger

Latest continuation: **FBR-2-code-3a — durable upload wiring**, recorded below.
Overall FBR-2 remains **CODE_IN_PROGRESS**. No test, build or runtime acceptance.

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


## FBR-2-code-3a — durable upload wiring

Date: 2026-09-30.
Status: **CODE_COMPLETE for the bounded upload wiring only; NOT VALIDATED**.
Overall FBR-2: **CODE_IN_PROGRESS**, not ready for full build/runtime acceptance.

Continuation base: `bce10f9ce31c42b146a08f2b99ff3b90e9a62748`.
That earlier commit added `test_flow_browser_driver_project_reads.py`; it is
additional authored project/read coverage, not a test execution or implementation.
Branch remains `feat/fbr-2-driver-lifecycle-20260930`.

Source commits for this slice:

- Authored upload coverage: `0eda8b9fc5b18e59906be258b9a80c48dd566b7f`.
- Shared uploader implementation: `19748c956c3b07dde6e8d959752ab902d87e4476`.
- Concrete driver wiring: `f09038d39f2ac1d363040d21db663f20a1855dab`.

### Implemented scope

- `FlowBrowserDriver.execute()` now routes validated non-paid upload commands to
  the shared `flow_browser_upload.execute_upload()` implementation.
- The existing path-based `upload_reference()` signature remains available and
  delegates to that same implementation. Existing persisted keys remain valid:
  `upload:<project UUID>:<source SHA-256>:<file name>`.
- Validate the envelope and the actual image content/MIME before navigation,
  journal mutation or upload. A changed random client request UUID does not
  authorize another upload of the same project/source/file identity.
- New uploads navigate only through the same authenticated leased provider.
  Driver-supplied lease guards run before journal access, dispatch and completion.
- SUBMITTING is durable before browser dispatch. Acknowledgement follows a
  complete matching RPC response, verified project/media UUIDs and durable receipt.
- Retain an observed operation UUID inside the upload receipt for the next
  reconciliation slice. It is not yet promoted to `operation_projects` here.
- Reuse a completed receipt only when its kind, source attributes and project
  binding match. Reuse and pre-existing uncertain intents cause no new browser
  upload, navigation or journal rewrite.
- Incomplete/ambiguous responses, invalid receipts and completion persistence
  failures return `UPLOAD_RECONCILIATION_REQUIRED` with `effect=unknown`.
  UNKNOWN is recorded when possible. Lost lease/disk failure may leave SUBMITTING;
  both states remain non-retryable. Never overwrite a completed receipt.
- Return a minimal envelope derived from verified receipt fields rather than
  passing arbitrary private response fields to application callers.
- Upload availability is now reported with `readiness_scope=project_read_upload`.
  `operation_reconcile`, `operations_implemented` and paid dispatch stay false.

Ruling: reuse the existing browser upload JS and keep its bounded timeout policy;
do not create another browser/profile, duplicate transport or new UI selectors.
Native captcha/session handling remains inside that established browser recipe.

### Authored requirements and deferred validation

`tests/unit/test_flow_browser_driver_upload.py` adds requirements for pre-effect
intent persistence, project binding, completed receipt reuse after restart,
unknown-outcome replay blocking, invalid responses, disk failure, lease loss,
image-content/MIME checks, project isolation, privacy and path-helper compatibility.

Tests executed: **none**. No pytest/import/compile/lint/build/workflow dispatch,
live browser upload, runtime inspection, EXE launch or Stable action occurred.
GitHub source read-back confirmed the driver commit/diff; it is not runtime proof.

The final FBR-2 coverage-integration slice must align historical lifecycle/project
read tests with the accumulated capability/readiness contract, including earlier
upload-unavailable expectations. Do not claim those historical tests pass now.
The async facade/cancellation and full extension/browser parity coverage remain
part of that outstanding integration scope.

Runtime revision, selected backend, physical profile identity/lease/health,
scheduler and existing paid-effect state: **not observed**.
KBS pin unchanged: `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
Main, other branches, PR #12, profiles, production data and Stable are untouched
by this slice. Existing good-video reuse, review gates, logs, TTS/concat and
publishing behavior have not been removed or rewritten.

### Exact next coding task and EXE gate

**FBR-2-code-3b:** implement read-only operation reconciliation, resolving the
operation/project binding from the durable journal and verified upload receipts.
Reject unbound or conflicting operation IDs; do not infer a project from whichever
tab happens to be open. No replay or fabricated resolution of UNKNOWN effects.

Then finish FBR-2 facade/readiness/restart coverage integration and the remaining
approved FBR-3/FBR-4/FBR-5 coding scopes. Only after complete source integration
may the separate validation/build/EXE acceptance pass start. Paid activation and
production default cutover require their own gates; optional FBR-6 deletion is
not authorized by this upload implementation.

Rollback source boundary for this slice: `bce10f9ce31c42b146a08f2b99ff3b90e9a62748`.
No runtime rollback is needed: these changes exist only on the development branch.
Owner continuation authorized coding toward EXE testing, not a runtime PASS.


## FBR-2-code-3b — read-only operation reconciliation

Date: 2026-09-30.
Status: **CODE_COMPLETE for this bounded reconciliation slice; NOT VALIDATED**.
Overall FBR-2 remains **CODE_IN_PROGRESS** pending facade/readiness/restart
integration and accumulated validation.

Source commits:
- Authored reconciliation coverage: `f3eb131e5fff4a844f13216f304ba262a0830c9e`.
- Operation identity in validated command contract:
  `4864ba81a2d98d83405d43f657871606d0870d50`.
- Durable operation/project resolver:
  `801f937977fc5b8a4e7e018cba156ac081e25187`.
- Concrete read-only operation reconciliation:
  `581d950da29c93c2200745a9230a1b3f4e12e2f9`.

### Implemented scope

- Validated `jwpduf` commands now expose their operation UUID explicitly and
  reject caller-supplied project/match bindings.
- The state store resolves an operation only from durable
  `operation_projects` or from exactly one COMPLETED upload receipt carrying
  the same operation UUID.
- SUBMITTING/UNKNOWN upload intents never establish an operation binding.
- Missing bindings return `OPERATION_BINDING_REQUIRED`; conflicting completed
  receipts or an explicit binding conflicting with a completed receipt return
  `OPERATION_BINDING_CONFLICT`.
- A unique completed receipt may be promoted locally into
  `operation_projects` under the held profile lease. This is journal
  reconciliation only; it performs no remote mutation and sends no upload.
- Operation reads navigate to the verified bound project and pass that project
  into the existing browser RPC guard. The current browser tab is never used as
  implicit project authority.
- Returned operation payloads are parsed with the existing Flow batch reader and
  must contain the same operation UUID and project UUID; otherwise the result is
  `OPERATION_RECEIPT_UNVERIFIED` with unknown effect.
- Driver capability reporting now advertises operation reconciliation and the
  complete non-paid driver surface as `readiness_scope=non_paid_parity`.
  Paid dispatch remains false.

### Authored requirements and validation boundary

`tests/unit/test_flow_browser_driver_operation_reconcile.py` records requirements
for explicit binding, completed-receipt promotion, restart reuse, unbound and
conflicting IDs, uncertain receipt exclusion, project-response verification and
capability reporting.

Tests executed: **none**, per the owner-directed development-first workflow.
No pytest/import/compile/lint/build, browser launch, EXE launch, Stable action,
profile inspection or Remote Desktop action occurred.

Ruling: the Superpowers TDD skill normally requires RED/GREEN execution, but the
repository's owner directive explicitly forbids testing until the coding phase is
100% complete. Therefore this slice authors tests before implementation but defers
their execution to the dedicated validation phase.

### Exact next coding task

**FBR-2-code-3c:** finish facade/readiness/restart integration and reconcile older
authored tests with the final non-paid capability contract. Keep extension fallback
selectable and paid dispatch false. After that, continue the remaining approved
FBR-3/FBR-4/FBR-5 coding scopes before starting build/EXE validation.


## FBR-2-code-3c — facade/readiness/restart integration

Date: 2026-09-30.
Status: **CODE_COMPLETE for this bounded integration slice; NOT VALIDATED**.
Overall FBR-2 source implementation is now at the end of the planned non-paid
parity coding scope, but validation remains deferred and no runtime PASS is claimed.

Source commits:
- Authored facade/restart requirements:
  `f5fbcc8140109c234d36a2362c51f30f6babe574`.
- Shared backend protocol completion:
  `79d8e7cbbbe593fbc0b5d64309a21310e70885cd`.
- Pending-reconciliation readiness projection:
  `f5dbfaa62477ca322a5df4acd3443e39b62a7b6d`.
- Lifecycle coverage alignment:
  `495b197453e46701d16546470f3b92540b6331f2`.
- Project/read coverage alignment:
  `100dac1b5175cad866217d2281452717a8d48161`.
- Coverage import cleanup:
  `3328012f70d3b6eb507643bbd954028bceaa2485`,
  `78dcf77e188fdd80a13e1783ef667106643bc675`.

### Implemented integration

- `FlowBackend` now declares `ensure_session_project()` so browser project
  lifecycle is part of the shared transport boundary rather than a browser-only
  undocumented method.
- Extension fallback remains selectable and explicitly returns a non-submitted
  501 result for session-project lifecycle instead of pretending to implement it.
- Browser health keeps `ready=True` when the authenticated leased session is
  healthy even if durable journal entries require reconciliation. The same health
  payload exposes `reconciliation_required=True` and
  `error=RECONCILIATION_REQUIRED`, allowing safe reads/reconciliation while
  still surfacing that mutation replay is blocked.
- Final browser capability projection is
  `readiness_scope=non_paid_parity`, `operations_implemented=True`, with
  project open/resume/create-session, project/media reads, upload and operation
  reconciliation available. `paid_dispatch_enabled=False` remains invariant.
- Authored facade coverage records clean close/new-backend restart behavior using
  the same owner-key derivation and durable state path, including saved project
  resume and paid-dispatch-disabled continuity.
- Historical lifecycle/project-read tests were updated from intermediate
  code-1/code-2 expectations to the accumulated FBR-2 non-paid contract.
  Dedicated upload and operation-reconciliation suites remain separate.

### Validation boundary

Tests executed: **none**. No pytest/import/compile/lint/build/workflow dispatch,
browser/profile launch, EXE launch, Stable update or Remote Desktop action occurred.
The branch therefore has authored validation requirements but no PASS evidence.

Ruling: pending/UNKNOWN intents do not make the browser transport itself unavailable.
They block only mutations whose replay could duplicate an effect; health stays ready
for safe project/media reads and explicit reconciliation while surfacing the warning.

### Exact next coding task

Proceed to the separately scoped **FBR-3 coding preparation** from the approved
browser-first plan: add the one-shot paid submission/idempotency boundary in source
while keeping dispatch disabled until the later explicit paid validation gate.
Do not perform a paid call during coding. FBR-4 parity-matrix source integration and
FBR-5 default-cutover source changes follow before the final build/EXE validation pass.
