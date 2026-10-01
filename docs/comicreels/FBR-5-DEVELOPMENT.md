# FBR-5 development ledger

Authority: `FLOW-BROWSER-FIRST-ARCHITECTURE.md` and
`../superpowers/plans/2026-09-27-flow-browser-refactor.md`.
Base: `607ec0a482de544c1175ae7bf636d6f30a0b9b16`.
Branch: `feat/fbr-2-driver-lifecycle-20260930`.

Overall status: **SUPERSEDED BY BROWSER-ONLY CUTOVER PLAN — CODE_IN_PROGRESS, NOT VALIDATED**.
Latest authority: `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`.

> **Supersession notice (2026-10-01):** every earlier section in this ledger that
> describes the Flow extension as a default, fallback, rollback target or supported
> transport is historical only. The owner directive is browser-only: extension is
> no longer a valid FlowKit transport. Do not implement or restore those old paths.

## Forward coding breakdown

1. **FBR-5-code-1: backend selection/rollback policy.** Add a pure resolver and
   authored requirements. Preserve the existing explicit backend environment
   variable. Separate the browser default candidate from production acceptance.
   Export bounded selection metadata without claiming browser health or parity.
2. **FBR-5-code-2: startup and status wiring.** Connect the resolver to the existing
   `get_flow_client()` singleton. Keep the selected backend stable until restart.
   Wire selected-transport metadata and backend-specific readiness/preflight into
   the API/UI. A browser startup error must not silently select the extension.
3. **FBR-5-code-3: operator/source handoff.** Align preflight/operator instructions,
   document the explicit rollback setting and reconcile the full coding checklist
   before the separate validation/build/EXE phase. Preserve the extension and all
   existing creative/workflow capabilities.

These are implementation slices of the approved FBR-5 plan, not authorization to
run tests, build/launch an EXE, switch Stable, activate paid dispatch, or remove the
extension. Each slice ends at its checkpoint.

## FBR-5-code-1 design and source handoff

Status: **CODE_COMPLETE for the isolated selection policy; NOT VALIDATED**.
This is not completion of startup wiring, all FBR-5, or the full development plan.

Files: `agent/services/flow_backend_selection.py`,
`tests/unit/test_flow_backend_selection.py`, and this ledger.

Source commits:
- Scope/design: `dc473bad0434df3aaaff13724e464ba7faea73e4`.
- Authored requirements: `66981010fb5cdd93aecc6aa86fab2490fafbcae4`.
- Policy implementation: `db140451fb6081d4791d6bb5bbad9d04c4b0ad8a`.

Precedence:

- Explicit `COMICREELS_FLOW_BACKEND=extension` always selects extension, including
  rollback when a browser default has previously been accepted. It does not need
  to parse the browser-default acceptance marker or inspect a browser profile.
- Explicit `COMICREELS_FLOW_BACKEND=browser` retains the existing opt-in browser
  route. Selection by itself does not enable paid generation.
- Without an explicit backend, `COMICREELS_FLOW_BROWSER_DEFAULT_ACCEPTED=1` selects
  the browser candidate. This marker is an operator acknowledgement of PRIOR
  acceptance; it is not proof of tests, parity, session health or owner approval.
  No code in this slice sets it. Operators must not set it before the separate
  owner-approved FBR-5 acceptance.
- Without an explicit backend, an absent acceptance marker or exact `0` retains
  the existing extension default. An invalid marker fails with a fixed error.
- An invalid explicit backend fails with a fixed error rather than guessing or
  silently falling back. Preserve the existing case-sensitive backend tokens.

The resolver is read-only: no environment writes, imports of browser/client
implementations, network calls, profile discovery, journal mutation or retry.
Selection metadata must not contain `ready`, `operations_implemented`, or paid
activation claims. Runtime capability/health remains the backend's responsibility.

Authored requirements: precedence matrix, default opt-in, rollback precedence,
invalid configuration handling, sanitized errors, immutable selection metadata,
and no mutation of the supplied environment. These tests have NOT been run.

Ruling: preparing the browser default in source is not permission to change an
unaccepted production default. Preserve extension until explicit configuration or
prior acceptance. Cost: an additional operator setting during later cutover,
rather than an accidental production change before parity is demonstrated.

## Remaining acceptance boundaries

FBR-3 currently contains a disabled control-plane gate with an injected dispatcher;
a concrete paid browser recipe and its application wiring have not been delivered
by that preparation slice. They are a remaining source/integration obligation,
not merely a deferred test command. Do not claim the complete development plan is
100% done while required browser generation is still unreachable.

FBR-4's source manifest is a list of requirements, not executed business parity
comparisons or proof that all required scenarios work on the browser backend.

At the code-1 baseline, `get_flow_client()` still selected its backend directly.
The code-2a slice below wires the resolver into that function. No deployment or
production-default acceptance follows from committing this source.

Tests/builds executed: **none**. Test source is authored during development;
execution is deferred by the owner's phased workflow. No runtime/profile/Stable
state is inspected. No paid request or Remote Desktop action occurred.

## FBR-5-code-2a — singleton startup selection

Date: 2026-10-01.
Status: **CODE_COMPLETE for this bounded startup wiring; NOT VALIDATED**.
Continuation base: `179f90b9b00c7844937be5c15964ee8858694810`.

Files: `agent/services/flow_client.py`,
`tests/unit/test_flow_client_backend_selection.py`, and this ledger.

Source commits:
- Authored singleton requirements: `0e8abb1b6d1a25a621dbb9b590d6a8542171b343`.
- Startup wiring: `bcfa3385951499a3f8948fda97b914079865abef`.
- Preserve original non-startup lines: `d473cf0705d83660267718d8ee80d183ed71c9b6`.

Implementation:
- `get_flow_client()` uses the existing `resolve_backend_selection()` policy.
  It stores the first valid immutable selection before backend construction.
- A process-local lock serializes singleton construction. Repeated getters reuse
  the same client; environment edits do not reselect a running or closed client.
- Browser-only imports and profile configuration occur only on the selected
  browser construction path. Explicit extension rollback does not import the
  browser backend or consult its profile.
- Constructing the singleton does not call `start_backend()` or open a browser.
  The existing application lifespan remains responsible for start/close.
- Construction/import failures store only the fixed
  `FLOW_BACKEND_INITIALIZATION_FAILED` code. Subsequent getters fail with that
  code instead of constructing another backend or automatically retrying.
  Raw exceptions/tracebacks are not stored in the singleton error cache.
- An asynchronous browser start failure remains associated with the same client;
  this wiring adds no replacement, fallback or new lifecycle retry.
- `FlowClient(backend=...)` injection is unchanged and does not resolve environment
  settings. Existing extension business behavior and paid flags are unchanged.
- No reset/reselection API is introduced. Operator rollback is explicit extension
  configuration followed by controlled process restart, not an in-place switch.

Authored coverage uses real `get_flow_client()`/FlowClient/resolver behavior with
only browser construction replaced. It covers extension import isolation,
explicit/browser-default precedence, construction without launch, stable selection,
invalid configuration, cached construction failure, async start failure, close and
fresh-process rollback, concurrent getters, and direct backend injection.

Ruling: cache a backend construction failure until process restart, rather than
retrying configuration/profile construction from subsequent API getters. This
prevents an implicit second initialization/fallback. Cost: an operator must correct
configuration and restart; the public fixed error offers less detail than a native
exception and is not a substitute for safe diagnostics in the later status slice.

Source read-back found two accidental unrelated line changes while assembling the
full-file API update. The preservation commit restores the original UUID matcher
and generation comment. The net business/creative/media code is unchanged by this
slice; only startup imports and singleton selection are intended changes.

Tests executed: **none**. No pytest/import smoke/compile/lint/build/workflow
execution, browser/profile launch, EXE launch, Stable update or paid request.
GitHub commit/diff read-back proves source persistence only, not a runtime PASS.
Older tests that reset the singleton must isolate `_client_selection` and
`_client_initialization_error` along with `_client` when simulating a fresh process;
this is a deferred test-suite integration/validation obligation, not a live reset.

## Historical handoff from code-2a

The next task at that checkpoint was code-2b, implemented below. KBS dependency,
runtime/backend revision, physical profile identity/lease, active jobs and scheduler
were unobserved. Main and Stable were not changed by code-2a. Its source rollback
boundary is `179f90b9b00c7844937be5c15964ee8858694810`.

## FBR-5-code-2b — selected-backend API, readiness and sidebar

Date: 2026-10-01.
Status: **CODE_COMPLETE for this bounded status slice; NOT VALIDATED**.
Continuation base: `47dea841ec52f0f7a75a2c88f3c86f3d03e846b4`.

Source commits:
- Authored requirements: `7189531beba09e05d0990f4cd667cfc422591dc7`.
- Bounded status projection: `d1524c6188c6f6a5c4184e0b26cb1c37fa0eb2f5`.
- Same-owner readiness observation: `f1572718003f8f0ab989aaad2875de51ad54c564`.
- Read-only status route: `1e40faa41e847279dde5bf9207ff04acfb9d936a`.
- Sidebar status component: `82118108f0be2ed9f52f32bcf294dfcbea5c8b59`.
- Sidebar integration: `746a3a2182c2b1be4a664bca71ea5cd980e83ca2`.
- Route mount and /health integration: `98bba5c704e48e5cae975b442cf66ee87a088670`.

### Implementation

- New GET `/api/flow/backend-status` returns schema-versioned, allowlisted status
  with `Cache-Control: no-store`. `/health` includes the same projection under
  `backend_status` and uses its observed `backend_ready` value.
- `read_backend_status()` snapshots the existing client, immutable selection and
  fixed initialization error under the singleton lock, then releases the lock
  before awaiting observation. It never calls get_flow_client or the resolver.
  An uninitialized client is reported without creating a client/browser.
- Selection source comes from the startup snapshot even after environment edits.
  A selected/actual-kind mismatch reports an explicit error, never fallback.
- Readiness, paid-dispatch switch and production acceptance are separate fields.
  `production_acceptance=not_verified` always: even an accepted-default setting is
  not proof that tests or owner acceptance occurred.
- Browser preflight requires observed ready/session-ready/authenticated/held-lease
  evidence; extension connectivity is informational for browser mode. Extension
  preflight still requires its connection. Reconciliation warnings remain visible
  without disabling safe-read preflight. No warning authorizes replay.
- Readiness observation has a two-second HTTP wait budget. Failure/timeout returns
  a fixed code and no positive readiness; raw errors, account fields, paths and
  arbitrary response fields are excluded. Existing backend queue bounds remain.
- BrowserFlowBackend can reobserve an existing driver after cached readiness went
  false, on the same owner thread. It does not restart the driver, change profiles,
  navigate, mutate receipts or admit work during closing/closed states.
- `dashboard/src/components/FlowBackendStatus.tsx` replaces the extension-only
  sidebar light. It displays selected transport, selection source, readiness,
  paid-dispatch switch, reconciliation warning and restart/preflight guidance.
  Vietnamese labels have English fallback; existing navigation/language controls,
  workers and the independent dashboard-WebSocket indicator remain intact.
- Sidebar observations are serialized (15 seconds after completion), with a
  five-second abort deadline and unmount cleanup. Invalid/missing/failed responses
  clear the old ready indicator instead of leaving stale green status visible.

### Scope and rulings

Ruling: use an additive backend-status endpoint and a nested /health projection,
not a rewrite of legacy GET `/api/flow/status` or generation routes. Existing
extension diagnostics/response contracts are retained. Cost: operator docs must
point selected-backend preflight to the new endpoint, not legacy extension fields.
This slice does not replace every old extension-specific error message or card.

Ruling: keep the singleton snapshot compatibility seam in one status adapter
rather than copying it into API/UI code or changing selection on GET. Cost: this
adapter and its tests must move together if the singleton internals are renamed.

The application lifespan still controls startup failure. If startup aborts before
serving HTTP, the endpoint cannot magically diagnose that stopped process; this
slice adds no emergency startup, hidden retry, fallback or profile repair.

Authored tests cover pure projection, browser/extension preflight, unknown/error
handling, warning visibility, privacy, selection mismatch, frozen environment
selection, no-construction status reads, HTTP no-store, bounded timeout and
same-owner reobservation. Source-wiring assertions are NOT rendered UI tests.
Rendered layout, localization, polling/abort behavior and application integration
must be exercised during the separate final validation pass.

Tests executed: **none**. No import smoke, compile, pytest, frontend build/lint,
workflow dispatch, browser launch, EXE launch, Stable change or paid request.
GitHub main/sidebar commit read-back confirms intended source diffs only.
Main branch, backend defaults, generation gates, KBS pin, database, media files and
other branches are untouched. No Remote Desktop action occurred. Runtime revision,
profile/lease health, scheduler and active production jobs remain unobserved.

## Exact next task

**FBR-5-code-3 — operator preflight and remaining-source handoff.** Document the
new backend-status schema, explicit extension rollback plus restart, and the
remaining source obligations before the full coding-completion gate. Reconcile
rather than conceal the unfinished concrete paid-browser dispatch/application
wiring, scenario-level parity coverage and packaging obligations. Do not start
validation/build/EXE merely because status/UI code is present. FBR-6 extension
removal and production default acceptance remain separate, unactivated gates.

Source rollback boundary for code-2b is
`47dea841ec52f0f7a75a2c88f3c86f3d03e846b4`. No runtime rollback is needed.


## Browser-only Task 1 — sole backend selection

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED**.
Plan: `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`.

Source commits:
- Browser-only plan: `e6db6bf7035c6e41ff496c722055116c0507862a`.
- Authored selection requirements: `b6596b57d665f1c06db07b671c5d8ab284ac6c69`.
- Authored singleton requirements: `a9cfd12cb5060a607bf4154c7a6c25ca5bf3ce65`.
- Browser-only selection resolver: `f8abddb9d3e773a0163f131fd9ab309ada74b067`.
- Browser-only singleton construction: `91968dc421cb3c142d01b88369beb17b1a6f4d2a`.

### Browser-only selection contract

- No configuration means browser.
- Explicit `COMICREELS_FLOW_BACKEND=browser` remains accepted for compatibility.
- Explicit `COMICREELS_FLOW_BACKEND=extension` now fails with
  `FLOW_EXTENSION_BACKEND_REMOVED`; it is not a rollback path.
- Any other backend token fails with the fixed
  `FLOW_BACKEND_SELECTION_INVALID` code.
- The old `COMICREELS_FLOW_BROWSER_DEFAULT_ACCEPTED` marker no longer controls
  transport selection. It may remain in old deployments without changing browser-only
  behavior.
- Selection metadata declares `extension_transport_supported=False` and never
  claims runtime readiness or paid authorization.
- `get_flow_client()` constructs only `BrowserFlowBackend`, caches a fixed
  initialization failure, and never creates an extension fallback.
- Browser construction remains side-effect bounded: the getter constructs the
  backend object but does not start the persistent browser; application lifespan
  remains responsible for start/close.
- Direct `FlowClient(backend=...)` dependency injection remains temporarily
  available for authored tests and later Task 3 cleanup; no production selection
  path uses extension.

### Deferred validation

Tests executed: **none**, by owner development-first rule. No pytest/import
smoke/compile/lint/build, browser/profile launch, EXE launch, Stable/ThoRemix
mutation, paid request or Remote Desktop action occurred.

Ruling: old extension fallback/rollback semantics are superseded rather than
maintained for backward compatibility. Cost if wrong: old deployments that still
force `COMICREELS_FLOW_BACKEND=extension` will fail fast and require config cleanup;
this is intentional under the browser-only directive.

### Next task

**Browser-only Task 2 — application lifecycle.** Keep the queue worker running for
browser mode, remove the Flow extension WebSocket startup/callback lifecycle, and
preserve graceful worker/browser shutdown. The already-authored worker-start fix
must be reconciled into this browser-only lifecycle task; no local test or Stable
restart is authorized until all source tasks are complete.


## Browser-only Task 2 — application lifecycle

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED**.
Plan: `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`.

Source lineage:
- Pre-plan worker root-cause requirement: `c60d3688db37eacb8627f75a422ff11533b5574c`.
- Pre-plan worker startup fix retained by this task:
  `296c8dca0aba1114b3bd497a5b13279335cc2684`.
- Browser-only lifecycle requirements:
  `9803f58c4a0d3540d6a4f028aafe354915a58ed6`.
- Browser-only lifespan authored coverage:
  `5d7a5d3cf1b8965c8413bc208e648f9208cc4f4f`.
- Extension lifecycle/callback removal:
  `b02533aec839c4c355aff584b36ff331d6274e6d`.

### Lifecycle contract

- Application startup obtains the browser-only Flow client, initializes the DB,
  starts the browser backend, initializes the SDK, then starts the business queue
  worker unconditionally. Queue consumption is not tied to extension transport.
- The old Flow extension `ws_handler` and `run_ws_server` are removed from
  `agent/main.py`; the application no longer opens that Flow extension WebSocket
  server during startup.
- The old `/api/ext/callback` endpoint and callback-secret lifecycle are removed
  from `agent/main.py`.
- The independent dashboard event WebSocket `/ws/dashboard` remains. It is not
  the removed Flow extension transport and is preserved for the existing UI event
  channel; extension-specific wording/status on that channel is a later Task 6/7
  cleanup.
- Shutdown requests the worker to stop, awaits `controller.drain()`, cancels
  application tasks, closes the browser backend, then closes the DB.
- Browser startup failure still aborts startup; no extension fallback/retry is
  introduced.
- No intent/receipt/idempotency code is changed in this task. Unknown paid outcomes
  retain the existing no-auto-resend safety boundary.

### External acceptance isolation

The separate KAT/ThoRemix conversation is performing its own final acceptance.
Its results are **not evidence for this browser-only branch** and must not be copied
into this ledger as PASS. This branch remains NOT VALIDATED until its own source is
100% complete and the owner-authorized validation/build/EXE/Stable phase runs at
the actual browser-only revision.

### Deferred validation

Tests executed: **none**, per owner phased workflow. No pytest/import smoke/compile/
lint/frontend build/workflow dispatch, browser/profile launch, EXE launch,
Stable/ThoRemix mutation, paid request or Remote Desktop action occurred.

Ruling: retain the dashboard WebSocket while removing only the Flow extension
transport. Cost if wrong: Task 7/8 will need to move or remove the dashboard event
channel; removing it here would unnecessarily break the UI before its independent
ownership is audited.

### Next task

**Browser-only Task 3 — remove extension transport implementation from
FlowClient/backend layer.** Remove `ExtensionFlowBackend`, extension WS pending
maps/session/failover/token machinery and extension send path while preserving the
FlowClient business API consumed by worker/API. Do not test/build/launch Stable
until the full browser-only source plan is complete.


## Browser-only Task 3 — remove extension transport implementation

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED**.
Plan: `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`.

Source commits:
- Authored browser-only transport requirements:
  `a732bae7fe1776fd19330b0a919b867128a4f54a`.
- Remove `ExtensionFlowBackend` implementation:
  `41ee23b453d57cfeff7a9166a74a6d92813702c5`.
- Remove extension socket/token/pending/failover/send machinery from `FlowClient`:
  `b5d6df861bbed2cef9d4eb8dc718194767ab010c`.
- Remove stale extension transport comments:
  `f9ab4d9eac54ad8c980539816fc29521d314de92`.

### Implemented boundary

- `agent/services/flow_backend.py` now contains only the stable `FlowBackend`
  protocol. `ExtensionFlowBackend` is removed.
- `FlowClient` no longer owns or exposes extension connection objects, profile
  candidate selection, pending WebSocket requests, request/socket correlation,
  token capture, extension message handling, extension failover, or
  `_send_extension()`.
- `FlowClient._send()` remains the single business dispatch seam and delegates
  only to its injected `FlowBackend`.
- Direct `FlowClient()` construction now creates `BrowserFlowBackend`, preserving
  the historical no-argument business API while making its transport browser-only.
  Production singleton construction remains owned by `get_flow_client()`.
- Existing business method names and response shaping for project/media/generation/
  polling are retained in this task. Task 4/5 will replace the remaining
  extension-era generation/poll assumptions with durable browser-native paths.
- Temporary compatibility readouts remain only to avoid breaking the still-old
  status endpoints before Task 6:
  `extension_connected=False`, `_flow_key=None`, and an immutable empty
  `ws_stats` shape with `transport_removed=True`. They contain no live socket,
  token, sender, failover or extension transport capability.
- Intent/receipt/idempotency state and no-auto-resend rules are untouched by this
  task.

### Main/PR #12 integration preservation gate

Do **not** merge this browser-only branch into main during the development phase.

Live GitHub observation at this checkpoint:
- current `main`: `5aecee7ef007b34e1ec732a3a382c80ff393546c`;
- PR #12 merge/KAT refresh commit:
  `18553d3fda9b26105f99951b2c752bc7fe5ca568`;
- `18553d3` is confirmed an ancestor of current main (main is 3 commits ahead of it);
- current browser-only branch vs main: **diverged, 67 ahead / 17 behind**;
- merge base remains `373e0a2e416819774fa88df0517b71868832b138`.

At final source integration, merge/rebase against the then-current `main` and
preserve the full PR #12 staged-KAT refresh plus subsequent main changes. In
particular, do not overwrite:
- `.github/workflows/tests.yml`;
- `.github/workflows/thoremix-kat-staging.yml`;
- `agent/thoremix/publishing.py`;
- `deployment/thoremix/Build-Stable.ps1`;
- `deployment/thoremix/Test-KatStagingContract.ps1`;
- `requirements-dev.txt`;
and also preserve subsequent main changes such as the current
`deployment/thoremix/verify_upgrade_lock.py` / `tests/unit/test_setup.py`
updates unless a later explicit source reconciliation proves otherwise.

Ruling: integration must reconcile browser-only work *into* current main, never
replace main with this long-lived branch. Cost if wrong: staged-KAT refresh,
Python 3.10 hashing compatibility, portable-validation policy, ThoRemix build
behavior or later main fixes could be lost.

### Acceptance isolation

The KAT/ThoRemix final acceptance running in another chat is not acceptance evidence
for this browser-only branch. No result from that flow can mark these Task 3 changes
PASS. This branch requires validation at its own final source revision.

### Deferred validation

Tests executed: **none**. No pytest/import smoke/compile/lint/build/workflow
dispatch, browser/profile launch, EXE launch, Stable/ThoRemix mutation, paid request
or Remote Desktop action occurred.

### Next task

**Browser-only Task 4 — concrete browser paid-dispatch integration.** Wire the
existing durable paid intent/receipt gate to the same leased browser session and
route the business single-shot path through it without extension-era retry/cadence
semantics. Paid dispatch remains disabled by default and unknown outcomes remain
non-retryable until explicit reconciliation.


## Browser-only Task 4a — paid gate to leased browser bridge

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; PAID DISPATCH DEFAULT OFF**.
Parent task: browser-only Task 4 — concrete browser paid-dispatch integration.

Source commits:
- Authored leased paid bridge requirements:
  `60c77d27c7c2a4ce1a46dd353c4012d70e0c700e`.
- Single-shot browser paid image recipe:
  `d93371c00b60d1dee3c3a54c0dfc9c4266b7bf9f`.
- Driver bridge on the owned browser/profile lease:
  `a610adc610a4de3ffa90e863d6abad826ca566d4a`.
- Async backend bridge with default lock:
  `6c09640f293e4f2a3c4cf60c85afc57a945ed92d`.
- Stable backend protocol addition:
  `cbc25b952b4031dd9dd175b65a14540ca3b94cdc`.
- Paid-gate documentation alignment:
  `e31db0dadb433073faf9f637d91751bf8da690ad`.

### Source contract

- Paid image submission is **not** routed through generic
  `FlowBrowserDriver.execute()`. It has a dedicated
  `submit_paid_image(..., idempotency_key=..., authorization=...)` boundary.
- `BrowserFlowBackend` and `FlowBrowserDriver` both default
  `paid_dispatch_enabled=False`. The normal application construction path does
  not pass an enabling flag or authorization object.
- Disabled calls return `PAID_DISPATCH_DISABLED` before project navigation,
  journal creation or browser evaluation.
- The explicitly constructed validation-only path requires exact in-memory
  authorization-object identity; wrong/missing authorization cannot submit.
- Before the durable paid gate is entered, the driver validates the one-shot
  recipe, confirms the existing authenticated leased browser session, navigates
  to the exact Flow project and loads the static browser recipe.
- `FlowPaidImageGate` writes the paid `SUBMITTING` intent before its dispatch
  callback can mint reCAPTCHA or execute the paid fetch.
- The dispatch callback re-checks the same profile lease/session and refuses a
  page-object change. It never opens a second browser/profile.
- `flow_browser_paid_image.js` accepts only `ogiZ0b`, exactly one image
  variant, the exact project route and the expected CAPTCHA placeholders. It
  mints one `IMAGE_GENERATION` token using the page's native enterprise
  reCAPTCHA runtime and performs one fetch only. There is no submit retry loop.
- A complete HTTP-200 body is returned as `effect=completed`. Once fetch may
  have started, HTTP rejection/body failure/exception is `effect=unknown`.
  The durable gate then records UNKNOWN when possible and never auto-resends it.
- Successful response parsing still requires exactly one generated media UUID;
  only project/media UUIDs are persisted as the paid receipt. Prompt, CAPTCHA,
  auth/session data and signed URLs are not stored.
- Health/capability projection reflects paid dispatch only when an explicitly
  constructed driver/backend has the paid flag enabled; default application
  health remains paid-disabled.

### Validation and safety boundary

No paid request was executed. Tests executed: **none**. No pytest/import
smoke/compile/lint/build, browser/profile launch, EXE launch, Stable/ThoRemix
mutation or Remote Desktop action occurred.

The native page CAPTCHA recipe is source-authored only and has not been proven
against the live current Flow frontend. A later explicitly authorized validation
checkpoint must verify session/captcha/receipt behavior with exactly one approved
paid shot. Any ambiguous result remains UNKNOWN and is not retried.

The separate KAT/ThoRemix acceptance conversation remains external evidence only
and does not validate this browser-only branch.

### Next short sub-task

**Task 4b — FlowClient one-shot business routing.** Add an explicit
idempotency-key/authorization business seam that maps the existing one-image
generation request into `BrowserFlowBackend.submit_paid_image()`, shapes the
verified media receipt back into the current FlowClient business response, and
bypasses the old extension-era multi-wave/retry logic for the browser paid path.
Keep the normal application paid flag locked and do not run tests or a paid call.


## Browser-only Task 4b — FlowClient paid one-shot business routing

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; PAID DISPATCH DEFAULT OFF**.
Parent task: browser-only Task 4 — concrete browser paid-dispatch integration.

Source commits:
- Authored FlowClient one-shot contract:
  `fe9a9d264be3a391a7eadb93c3f9e939fc6c070c`.
- Route `FlowClient.generate_images()` through
  `BrowserFlowBackend.submit_paid_image()`:
  `4dbd767a58a0b427fdc19b59b10b554daa3d93af`.
- Authored fixed-UNKNOWN backend-exception requirement:
  `91f0ace75428f5ae452eaf5dfc150a6650325abd`.
- Map unexpected paid bridge exceptions to fixed UNKNOWN without retry:
  `da65b4c3acb443d8846cc04ee411e1014e79082f`.

### Business contract

- `FlowClient.generate_images()` is now an explicit one-shot paid seam.
  `count != 1` fails before submission with `PAID_SINGLE_SHOT_REQUIRED`.
- A non-empty caller-provided `idempotency_key` is mandatory before the
  backend is called. Missing keys fail with `PAID_IDEMPOTENCY_REQUIRED`.
  The durable gate still performs its stricter key validation/fingerprinting.
- The method builds exactly one `ogiZ0b` request and calls
  `BrowserFlowBackend.submit_paid_image()` exactly once. The old image
  `run_wave`, cadence and transient-[8] resubmit policy were removed from this
  business path.
- `paid_authorization` is forwarded by identity to the backend/gate. Normal
  application construction still has no enabling authorization and remains
  `paid_dispatch_enabled=False`.
- Backend UNKNOWN/error results are returned without media lookup or paid retry.
  Unexpected backend exceptions are mapped to fixed
  `PAID_RECONCILIATION_REQUIRED` + `effect=unknown`; private browser/profile
  exception text is not forwarded and there is no second submission.
- After a verified COMPLETED receipt, FlowClient performs only a read-only
  media lookup for a fresh signed image URL. Failure to obtain that URL does not
  downgrade the paid receipt or trigger another paid call.
- The historical business response shape is retained:
  `data.media[0].name`, `image.generatedImage.mediaId`,
  `image.generatedImage.fifeUrl`, plus requested/generated/complete counts.
  The completed response also carries `effect=completed` and receipt reuse state.
- `edit_image()` forwards the same idempotency/authorization seam to
  `generate_images()`; callers that do not yet supply a key fail closed rather
  than silently using the removed extension-era paid path.

### Remaining Task 4 obligation

Task 4 is **not complete**. Worker/SDK/direct API callers still need to provide a
stable business idempotency key (normally the durable request id) and the explicit
authorization capability must remain isolated from normal production construction.
UNKNOWN/reconciliation results must be classified as non-retryable by the worker so
generic retry handling cannot manufacture a second key/submission.

### Deferred validation

Tests executed: **none**. No paid/CAPTCHA call, pytest/import smoke/compile/lint/
build, browser/profile launch, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred. KAT/ThoRemix acceptance in another conversation remains
non-authoritative for this branch.

### Next short sub-task

**Task 4c — durable caller idempotency and UNKNOWN no-retry propagation.** Wire
worker/SDK image generation calls to use the durable request id (or an equally
stable persisted business key), keep normal paid authorization unavailable by
default, and make `PAID_RECONCILIATION_REQUIRED/effect=unknown` terminal for
automatic retry while remaining visible for explicit reconciliation.


## Browser-only Task 4c — durable caller idempotency + UNKNOWN no-retry

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; PAID DISPATCH DEFAULT OFF**.
Parent task: browser-only Task 4 — concrete browser paid-dispatch integration.

Source commits:
- Authored durable request-id propagation requirements:
  `d1dd08e424f1a2b3f97b2b317b550ccd14f36cf3`.
- Normalize UNKNOWN expectation to reconciliation:
  `46bb7ebdaee4d773e62880d3cec8130c818be18f`.
- SDK image operations accept/forward durable `request_id`:
  `3f70e68ee4303e6cb05a7d791e74005e53aa2f2a`.
- Authored parser guard for `effect=unknown`:
  `aaca8fa6372267b7180c1a893db396117d8a30f1`.
- Worker parser treats UNKNOWN as an error:
  `2149a993b36c04daf357a67c2f136e27ed4fc71a`.
- Worker dispatch propagates DB request id and blocks UNKNOWN retries:
  `659e8005c7cac823913c5978463db99d07bbe6e6`.

### Durable idempotency contract

- The queue request row id (`rid`) is the paid image business idempotency key.
  Retry count, current time, process lifetime and browser session state are never
  used to derive a replacement key.
- Scene generate/regenerate image, scene edit image, character
  generate/regenerate image and character edit image all propagate the same
  durable request id into `FlowClient.generate_images()/edit_image()`.
- `OperationService.generate_scene_image()`,
  `edit_scene_image()`, and `generate_reference_image()` expose a
  `request_id` seam and forward it as `idempotency_key`.
- Queue-based SDK wrappers already persist a request row and return its id; when
  that row is later consumed by the worker, the same id reaches the paid gate.
- Direct SDK calls that bypass the durable request queue and omit a request id
  remain fail-closed at `FlowClient` with `PAID_IDEMPOTENCY_REQUIRED`.
- No caller in this task creates or receives a paid authorization object.
  Normal application construction therefore remains dispatch-locked.

### UNKNOWN / reconciliation retry contract

- Worker parsing now treats `effect=unknown` as an error regardless of HTTP
  status or response body.
- `_handle_failure()` checks UNKNOWN/reconciliation before media recovery,
  CAPTCHA retry and generic retry/backoff logic.
- Any `effect=unknown` or exact `PAID_RECONCILIATION_REQUIRED` is normalized
  to the fixed persisted error `PAID_RECONCILIATION_REQUIRED`, marked FAILED
  for automatic queue processing, and surfaced for explicit reconciliation.
- Existing retry-after state for that request is removed. Retry count is not
  incremented and status is never returned to PENDING by this branch.
- The scene failure marker is updated through the existing business helper so
  UI/business state does not present an unresolved paid effect as completed.
- Other clearly-not-submitted errors continue through the existing policy. This
  task does not weaken the paid gate or manufacture authorization.

### Receipt and live-effect boundary

The paid receipt contract from 4a/4b is unchanged: durable paid state remains
SUBMITTING/UNKNOWN/COMPLETED with project/media UUID receipts only, and UNKNOWN
never causes a second paid submit.

Tests executed: **none**. No paid/CAPTCHA call, pytest/import smoke/compile/lint/
build, browser/profile launch, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred. External KAT/ThoRemix acceptance remains non-authoritative
for this branch.

### Remaining Task 4 obligation

Task 4 is still **not complete**. The source still needs a controlled paid
authorization/activation seam that can be used only during the later explicitly
approved validation path while normal application startup remains locked. Task 4
must then be reconciled against the full plan before proceeding to Task 5.

### Next short sub-task

**Task 4d — controlled paid validation authorization seam and Task 4 source
closure.** Define the explicit opt-in construction/config boundary that can supply
the exact authorization object to backend + business caller only for an approved
single-shot validation. Normal production startup remains locked. Do not execute a
paid request or test/build/Stable action.
