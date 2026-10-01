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


## Browser-only Task 4d — controlled validation authorization + Task 4 source closure

Date: 2026-10-01.
Status: **TASK 4 SOURCE_COMPLETE; NOT VALIDATED; PRODUCTION PAID DISPATCH LOCKED**.

Source commits:
- Authored controlled-validation seam requirements:
  `5498bb572c23d63c28290363bb354edfbefed481`.
- Explicit one-shot validation construction seam:
  `6e4004d45a90e07a39751a921627e9db3b964760`.

### Controlled validation authorization contract

- New `agent/services/flow_paid_validation.py` is isolated from normal startup.
  Neither `agent/main.py` nor `get_flow_client()` imports it.
- Normal production singleton still constructs plain `BrowserFlowBackend()`
  with no paid-enable flag and no authorization object. Production therefore
  remains `paid_dispatch_enabled=False`.
- The validation factory does **not** create authorization. Its caller must
  deliberately supply a fresh in-memory plain `object()`; strings, booleans,
  numbers, bytes, config values and environment text are rejected.
- There is no env var, HTTP endpoint, FastAPI route, CLI switch or config-file
  activation surface for validation paid dispatch.
- The supplied opaque object is bound by identity into the explicitly constructed
  `BrowserFlowBackend` and retained privately by `PaidValidationSession`.
  The session forwards that same object to `FlowClient.generate_images()`.
- The validation factory builds but does not start the browser. `start()`,
  readiness observation, paid one-shot and `close()` are explicit harness calls.
- `PaidValidationSession.generate_one_image()` consumes the one-shot capability
  **before the first await**. Cancellation, timeout, UNKNOWN or any ambiguous
  result therefore burns that validation session and cannot trigger a second paid
  attempt through it.
- A second call returns `PAID_VALIDATION_SHOT_ALREADY_USED` with
  `effect=not_submitted`.
- The validation session does not expose public `client` or `authorization`
  properties. Its private references exist only in process memory.

### Task 4 source closure

Task 4 source obligations are now represented:
1. browser-native one-image paid recipe bound to the same leased session;
2. durable SUBMITTING intent before CAPTCHA/fetch effect;
3. completed project/media receipt before business success;
4. FlowClient one-shot route with historical response shape;
5. durable DB request-id idempotency propagation from worker/SDK;
6. UNKNOWN/reconciliation automatic retry prohibition;
7. normal production paid dispatch locked by default;
8. explicit validation-only one-shot authorization seam with no automatic grant.

This is **source closure only**, not proof that the current live Flow frontend,
reCAPTCHA recipe, response parsing or packaging works. No paid shot has been run.

### Deferred validation

Tests executed: **none**. No live CAPTCHA/paid request, pytest/import smoke/
compile/lint/build, browser/profile launch, EXE launch, Stable/ThoRemix mutation
or Remote Desktop action occurred.

The KAT/ThoRemix acceptance performed in another conversation is not acceptance
evidence for this browser-only revision.

### Next plan task

Proceed to **Task 5 — browser-only polling/media/operation state alignment**.
Reconcile FlowClient's remaining in-memory operation caches with the durable
browser journal, preserve response shapes and restart/resume semantics, and do not
run tests/build/Stable until the full browser-only source plan is complete.


## Browser-only Task 5a — durable operation/project binding authority

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 5 still in progress**.

Source commits:
- Authored durable operation-binding requirements:
  `2584221bb2d5848e6fed80d982a736644131cf75`.
- Add durable binding methods to the backend protocol:
  `06290f703315f8dce5dcb75d87335c4b07851310`.
- Driver read/write binding under the existing profile lease:
  `a39850730ec5ae2cbee0870bb5ec4799bbb5e6b1`.
- Async backend routing for operation binding:
  `8d1c1b47fec3ee0ac4053138380a87a44896563d`.
- Make FlowClient durable binding authoritative:
  `dcf034ff4a97da223c27a4c9133b01518f75372f`.

### Binding contract

- `FlowClient` no longer owns an in-memory `_operation_projects` map.
- After a generation submit returns an operation id, FlowClient persists
  `operation_id -> project_id` through `FlowBackend.bind_operation()`.
- On browser backend this write runs on the single owner executor, requires the
  existing profile lease and writes `BrowserStateStore.operation_projects`.
- A conflicting durable binding fails with the fixed
  `OPERATION_BINDING_CONFLICT` code and is never overwritten.
- Poll/restart lookup uses `FlowBackend.operation_project()`; browser driver
  resolves only the durable store/receipt evidence. FlowClient no longer falls
  back to `FLOW_PROJECT_ID` or a process-local operation/project cache.
- If a remote submit appears successful but durable binding cannot be recorded,
  FlowClient returns `effect=unknown` with `OPERATION_BINDING_REQUIRED`.
  It does not imply that the remote effect was not submitted or safe to replay.
- When an operation poll returns a project id, it must agree with the existing
  durable binding. A mismatch is treated as `OPERATION_BINDING_CONFLICT`.
- Business operation response shapes remain unchanged:
  pending entries still use `data.operations[].operation.name` and successful
  polling still uses the existing media metadata shape.
- Paid-image intent/receipt/idempotency code is untouched by Task 5a. Production
  paid dispatch remains locked and UNKNOWN remains non-retryable.

### Restart boundary

A new FlowClient process no longer needs the previous process's operation/project
map. With the same persisted browser state file and owner/profile identity, the
backend can resolve the operation's project after restart. Media-id and poll-round
caches remain process-local for now; removing those restart assumptions belongs to
Task 5b.

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred.

### Next short sub-task

**Task 5b — restart-safe media discovery/poll cache behavior.** Remove correctness
dependence on process-local `_operation_media` / `_operation_polls`: durable
binding + current browser project listing/media reads must be sufficient after
restart, while disposable caches may remain optimization-only. Preserve the
existing pending/success response shape and never turn read uncertainty into a
paid resubmit.


## Browser-only Task 5b — restart-safe media discovery and polling

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 5 still in progress**.

Source commits:
- Authored restart-safe polling requirements:
  `642d7b7665d3ac5fcaf2af826b1e2b1fc916910d`.
- Restart-safe polling/media source rewrite:
  `7b6e02316a10c8063e9607629b8a7bec89621d38`.
- Authored explicit durable-project media-read requirement:
  `9e5a17ee3884855d94fc77bb0b19bb1049dc189f`.
- Browser media reads prefer explicit durable project scope:
  `a2e54491b40bb465ea762dc7dca0ad297f5f94f1`.
- Tighten authored contract so RAM operation caches are forbidden:
  `53a7824b9a62910026da66eccb4de7cf6fd5705d`.
- Remove RAM operation caches from correctness path:
  `2ae2dc6f33c6b15311816e752d12caf16d4fd527`.
- Authored operation/project mismatch fail-closed requirement:
  `9c4c8be19e56211129fa47635767d642d66a8079`.
- Fail closed on operation project binding conflict:
  `0f153f7043f85d28c26bb0ae0d6c56df02b97ac4`.
- Correct source assertion to target instance cache fields:
  `c6068413882547b068e6e76fac282b008e9a6a63`.

### Restart-safe polling contract

- `FlowClient` no longer has `self._operation_polls` or
  `self._operation_media` correctness state.
- Every poll round first resolves the operation's project from durable browser
  state, then consults the current project listing for the operation/media
  mapping. A new process therefore does not need any prior RAM poll count or
  media-id cache to discover completion.
- Operation RPC status remains diagnostic. An unreadable/decayed operation poll
  does not block the authoritative project-listing lookup.
- A project id returned by the operation RPC must agree with the durable binding.
  Mismatch returns `OPERATION_BINDING_CONFLICT` and does not proceed to a
  success decision from a different project listing.
- Media reads used by operation polling now carry the durable project id down to
  the browser command. The driver explicitly prefers that project scope for
  `RPC_MEDIA`, opens the exact project route and reuses the same leased browser
  session rather than whichever project happened to be last active.
- SUCCESS is emitted only after the current listing yields a media id and the
  current media record yields a video URL. Listing miss, incomplete media URL or
  read uncertainty remains the existing PENDING business shape.
- There is no generation submit, retry, CAPTCHA mint or paid authorization in
  the polling path. Read uncertainty cannot create a paid resend.
- Production paid dispatch remains locked and Task 4 UNKNOWN/idempotency rules
  are unchanged.

### Trade-off ruling

Ruling: remove the old "every third poll" listing cadence rather than preserving
it as process-local optimization. Restart correctness now has no hidden warm-up
round. Cost if wrong: polling performs more project-listing reads; however the
browser path already returns only the bounded operation match window to Python,
and correctness/restart safety takes precedence during this cutover.

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred.

### Next short sub-task

**Task 5c — response-shape/restart-resume source closure.** Reconcile the remaining
operation/media public response paths and restart/resume handoff against the Task 5
plan, remove stale extension-era assumptions/comments in this area, author the
restart/resume contract, and then mark Task 5 source-complete. Do not enter Task 6
validation or run build/Stable actions.


## Browser-only Task 5c — response shape + restart/resume source closure

Date: 2026-10-01.
Status: **TASK 5 SOURCE_COMPLETE; NOT VALIDATED**.

Source commits:
- Authored restart/resume and response-shape contract:
  `720a3fa4704987758c7b1084f610392544e68588`.
- Sanitize restart poll diagnostics to fixed public codes:
  `2fba6bd6db2b84ebcd8093d78f9f06a6802b3b74`.
- Authored shared resume-guard requirement:
  `a848c3a09f35847514c1c00faac1dcfec8e75309`.
- Centralize durable operation resume guard in OperationService:
  `9eb6235a4eedaf11d66a82ff58dbed3d59a55247`.

### Public response-shape contract

- Pending operations retain the existing structure:
  `operation.name`, optional `operation.metadata.video.mediaId`,
  `status=MEDIA_GENERATION_STATUS_PENDING`, optional fixed-code `complaint`.
- Successful operations retain:
  `operation.name`, `operation.metadata.video.mediaId`,
  `operation.metadata.video.fifeUrl`, and
  `status=MEDIA_GENERATION_STATUS_SUCCESSFUL`.
- `check_video_status()` continues returning
  `{"status": 200, "data": {"operations": [...]}}`; downstream SDK/worker
  parsers do not need a transport-specific schema.
- Poll exceptions and media-read failures no longer expose arbitrary exception
  text through `complaint`. They are projected to bounded fixed codes such as
  `POLL_READ_UNAVAILABLE`, `MEDIA_READ_UNAVAILABLE`,
  `OPERATION_BINDING_REQUIRED` or `OPERATION_BINDING_CONFLICT`.

### Restart/resume contract

- SQLite `request.request_id` remains the durable business record of the remote
  operation id.
- Browser state `operation_projects` remains the durable mapping from that
  remote operation id to its Flow project.
- `OperationService._resume_saved_operation()` is now the shared guard for
  scene-video, reference-video and upscale operation workflows.
- If the request row already has a remote operation id, the service constructs
  the historical pending-operation shape and sends it directly to the poller
  **before any submit branch can execute**.
- Process restart may reset a stale PROCESSING request to PENDING, but its
  persisted remote operation id remains available. Reprocessing therefore
  resumes polling instead of intentionally creating another operation.
- Polling correctness itself is independent of process-local caches after Task
  5b: durable binding + current project listing + current media read reconstruct
  the state required after restart.
- UNKNOWN/no-resend protection is unchanged. A binding write uncertainty or paid
  UNKNOWN remains non-retryable and is never converted into permission to submit.
- All browser reads continue through the same single-owner backend executor and
  existing profile lease/session checks.
- Production paid dispatch remains locked by default.

### Task 5 source closure

The Task 5 source obligations are now represented:
1. submitted operation/project binding is persisted durably;
2. poll/media lookup resolves the durable binding and uses the current leased
   browser session/project route;
3. existing pending/success business response shapes are preserved;
4. restart/resume uses durable DB request id + browser journal rather than RAM
   operation state.

Ruling: restart correctness uses a DB/business record and browser transport
journal as two complementary durable authorities. The DB tells the worker which
remote operation to resume; the browser journal tells the browser which project
owns it. Neither RAM cache is allowed to substitute for either. Cost if wrong:
an inconsistent/corrupt durable pair fails closed into pending/reconciliation
instead of guessing a project or resubmitting.

### Deferred validation

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred. Source read-back is not runtime acceptance.

External KAT/ThoRemix final acceptance from another conversation remains
non-authoritative for this browser-only branch.

### Next plan task

Proceed to **Task 6 — remove extension-specific API/status/preflight surfaces**.
Remove extension readiness/session/token fields and messages from Flow status,
make browser session readiness the only transport preflight, and continue exposing
reconciliation and paid-dispatch state independently. Source GitHub first; no
tests/build/Stable until the complete browser-only source plan is finished.


## Browser-only Task 6a — status projection/service

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 6 still in progress**.

Source commits:
- Authored browser-only status projection requirements:
  `92e5ab81929017360fa206b81052b60d9e5c166f`.
- Keep extension-compatibility assertion source-only:
  `5d2c6238be6ffdacabe0103364874380760dbfd7`.
- Browser-session-only backend status service:
  `48dcfde5c5370f2b148ac013de84501d87076891`.

### Status contract

- `flow_backend_status.py` now has one transport: `browser`.
- Selection metadata recognizes only the browser-only source. Historical
  `extension_default`, `accepted_browser_default` and extension readiness
  branches are removed from this service.
- Browser transport readiness requires all current positive evidence:
  backend `ready=True`, `session_ready=True`, authenticated session and held
  profile lease.
- `preflight` is browser-only:
  `{ready, transport: "browser", session_required: True}`.
  It no longer contains `extension_required`.
- Status projection no longer exposes `extension_connected` or
  `browser_default_candidate`.
- `read_backend_status()` no longer reads `client.extension_connected` or
  `client.ws_stats`; status cannot accidentally depend on the removed
  extension compatibility surface.
- A non-browser actual backend is treated as
  `BACKEND_SELECTION_MISMATCH`; there is no fallback/alternate transport.
- `RECONCILIATION_REQUIRED` is visible independently and does not mark an
  otherwise healthy browser read/session transport as down.
- `paid_dispatch_enabled` is also independent. It reports only the explicit
  backend switch and is never inferred from session readiness or reconciliation.
- On readiness read failure, a known disabled paid switch may remain `False`;
  an enabled switch is projected as unknown rather than claiming it is usable.
- Private/unrecognized observation fields and errors remain allowlisted/sanitized.

### Deferred validation

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred.

### Next short sub-task

**Task 6b — direct Flow API preflight/messages.** Replace every
`"Extension not connected"`, extension status field and Flow-key/extension-session
diagnostic in `agent/api/flow.py` with browser session readiness semantics. Keep
generation paid lock/reconciliation explicit and do not create a validation
authorization route.


## Browser-only Task 6b — direct Flow API browser preflight

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 6 still in progress**.

Source commits:
- Authored direct-API browser preflight requirements:
  `b016441f642472553a3d22b72f627ab218a1c82a`.
- Replace extension preflight/status surface in `agent/api/flow.py`:
  `8c69a2f756d31645050c59644ab8c7e136e2b499`.

### Direct API preflight contract

- All direct Flow routes that previously checked cached `client.connected` and
  returned `"Extension not connected"` now call one
  `_require_browser_session(client)` helper.
- The helper reads fresh `read_backend_status()` evidence and requires
  `backend_ready=True`. It returns a fixed HTTP 503
  `"Browser session not ready"` when the current browser session preflight is
  not satisfied.
- Browser readiness remains transport/session-only. A visible
  `RECONCILIATION_REQUIRED` warning does not by itself block safe read/session
  preflight while the browser lease/auth/session remain healthy.
- `/api/flow/status` is now browser-only and exposes:
  browser session readiness, authentication, lease state, reconciliation,
  pending intents, explicit paid-dispatch switch, browser preflight, generation
  throttle and session-project state.
- The old `extension_connected`, `extension_session`, `flow_key_present`,
  `client.ws_stats`, `client._flow_key` and extension wording are removed
  from `agent/api/flow.py`.
- Normal HTTP routes do not import `flow_paid_validation`, do not create a
  validation session and do not pass `paid_authorization`. Browser readiness
  therefore cannot manufacture paid authorization.
- Production paid generation remains locked by the Task 4 boundary. A ready
  browser session means only that the transport/session is usable; it does not
  mean paid dispatch is approved.

### Source read-back

At this checkpoint `agent/api/flow.py` contains:
- 0 occurrences of `Extension not connected`;
- 0 `extension_connected` / `extension_session` / `flow_key_present`;
- 0 `client.ws_stats` or `client._flow_key`;
- 0 `if not client.connected` legacy preflights;
- 0 paid-validation imports or `paid_authorization=` calls;
- 15 direct route calls to `await _require_browser_session(client)`.

### Deferred validation

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred.

### Next short sub-task

**Task 6c — root health/status API surface and Task 6 source closure.** Remove
extension-specific fields/wording from `agent/main.py` health/dashboard snapshot
and the remaining `agent/api/flow_backend_status.py` legacy description. Keep
the independent dashboard event WebSocket itself. Then reconcile Task 6 checklist
and mark Task 6 source-complete.


## Browser-only Task 6c — root health/dashboard snapshot + Task 6 source closure

Date: 2026-10-01.
Status: **TASK 6 SOURCE_COMPLETE; NOT VALIDATED**.

Source commits:
- Authored root health/dashboard snapshot requirements:
  `4d567fff78d23891ff74be58166f06806abcc073`.
- Browser-only root health + dashboard initial snapshot:
  `10660ce316b7b9837586b25a781690a5dc35ddea`.
- Browser-only backend-status route description:
  `5b6a06d2f8e72b7dc7a84253a9f0eae1e3b883e7`.

### Root health contract

- `/health` no longer exposes `extension_connected`, legacy `ws_stats` or
  cached `client.connected` as Flow readiness.
- Root health calls the same fresh `read_backend_status()` projection used by
  Flow API preflight and reports browser transport/session fields:
  `backend_ready`, `browser_session_ready`, authentication, lease,
  reconciliation, pending intents and explicit paid-dispatch switch.
- Root health does not import or construct the paid validation seam and cannot
  manufacture paid authorization.

### Dashboard snapshot contract

- `/ws/dashboard` remains present as an **independent dashboard event channel**.
  It continues using `event_bus.subscribe()/unsubscribe()` and existing client
  origin handling; Task 6 does not remove this non-Flow event facility.
- Its initial health snapshot now comes from fresh browser backend status rather
  than `extension_connected` or cached `client.connected`.
- The snapshot carries browser transport/session readiness, reconciliation and
  paid-dispatch state independently.
- The dashboard event WebSocket docstring no longer describes itself as a Flow
  extension side panel/transport. UI wording and presentation are Task 7.

### Backend status route

- `agent/api/flow_backend_status.py` is described as browser transport status
  and preflight projection. It retains `Cache-Control: no-store` and performs
  no authorization/effect.

### Task 6 source closure

Task 6 source obligations are now represented:
1. Flow readiness no longer depends on `extension_connected`;
2. selected-backend status no longer exposes extension session/token fields;
3. direct API 503 messages use browser-session readiness wording;
4. reconciliation and paid-dispatch state remain independent status dimensions;
5. root health/dashboard snapshot use fresh browser readiness evidence.

Ruling: keep the dashboard WebSocket itself, including its existing client-origin
compatibility, because it is an event-bus channel independent from the removed
Flow extension transport. Cost if wrong: Task 7/8 may further narrow dashboard
client compatibility, but deleting the channel in Task 6 would break unrelated
UI event delivery.

### Deferred validation

Tests executed: **none**. No pytest/import smoke/compile/lint/build, browser/profile
launch, paid/CAPTCHA request, EXE launch, Stable/ThoRemix mutation or Remote
Desktop action occurred.

### Next plan task

Proceed to **Task 7 — remove extension-specific dashboard UI**. Update dashboard
types/copy/status rendering to browser session readiness, reconciliation and paid
state while preserving the independent dashboard WebSocket/event indicator. Source
GitHub first; no build/test/Stable until the full browser-only source plan closes.


## Browser-only Task 7 — dashboard UI/types/copy

Date: 2026-10-01.
Status: **TASK 7 SOURCE_COMPLETE; NOT VALIDATED**.

Source commits:
- Authored dashboard browser-status UI contract:
  `edaa0213a48154fa8efa7fd611b08994add7fd0d`.
- Browser-only Flow status panel with schema v2:
  `65a6d3e0ebe2bf07a2bf7ca3f6d3c6d59669fb75`.
- Label header WebSocket as dashboard event channel:
  `11e2e2b0aea34132c2ce4b44ce8172666189767d`.
- Add dashboard-live/offline i18n copy:
  `583119bacfa7ad343b6ce992202251f8c9abbb5f`.
- Explicit numeric/type narrowing in status decoder:
  `0b982d83a90441217968c88e4c631dee6103f955`.
- Clarify dashboard WebSocket context is not Flow transport:
  `66498f026784bb2130ee00453d817afaf5b4167a`,
  `ed55962d52909c5b5e5380d3921cc32b65e91ba1`.
- Final decoder type-safety narrowing:
  `088d1948523315e0cf6fa4bace11cbc0f36a9b76`.

### Flow status panel contract

- `FlowBackendStatus.tsx` now decodes backend status schema v2 only.
- Flow transport kind is fixed to `browser`; there is no Browser/Extension
  switch, extension-default source, extension-required preflight or extension
  connection wording in this component.
- Readiness is shown from independent browser-session evidence:
  backend ready + preflight ready + session ready + authenticated + lease held.
- Reconciliation is rendered separately from readiness, including bounded pending
  intent count when present.
- Paid dispatch is rendered separately from readiness/reconciliation:
  disabled production state is labeled **Locked** / **Đang khóa**; an explicitly
  enabled validation state is labeled separately and is not presented as normal
  production authorization.
- The panel explicitly notes that browser readiness does not authorize paid
  generation.
- Failed/invalid status observations clear stale green readiness rather than
  keeping a previous optimistic state visible.

### Dashboard event WebSocket contract

- The header's independent `useWebSocketContext().isConnected` indicator remains.
- Its user-facing copy is now **DASHBOARD LIVE / DASHBOARD OFFLINE**, not a Flow
  extension/transport status.
- `WebSocketContext` comments explicitly identify `/ws/dashboard` as an
  independent dashboard event/snapshot channel, not Flow transport.
- Worker event/active-slot behavior is unchanged.

### Source read-back

At this checkpoint:
- `FlowBackendStatus.tsx`: 0 occurrences of `extension`;
- `App.tsx`: 0 occurrences of `extension`;
- App uses `app.dashboardLive` / `app.dashboardDisconnected`, not the old
  generic WS labels;
- browser readiness, reconciliation, pending intents and paid lock all remain
  independently rendered.

Legacy extension copy elsewhere in the Guide/translations is intentionally deferred
to Task 8 because it is operator/runtime documentation, not the Task 7 live status
surface.

### Deferred validation

Dashboard TypeScript build/lint/tests executed: **none**. No pytest/import
smoke/build, browser/profile launch, paid/CAPTCHA request, EXE launch,
Stable/ThoRemix mutation or Remote Desktop action occurred.

### Next plan task

Proceed to **Task 8 — remove extension runtime package/code and stale docs/build
references**. Audit runtime/package/config/operator/Guide references, retire the
Flow extension package only after references are removed, preserve the independent
dashboard WebSocket/event channel, and update browser-profile/session preflight
documentation. Source GitHub first; no test/build/Stable before source closure.


## Browser-only Task 8a — retire verified Flow-extension runtime/package

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 8 still in progress**.

Source commits:
- Authored runtime-retirement contract:
  `13f9ff62aa2a58b4996401b0bed55a72831a900b`.
- Remove extension-only WS config from `agent/config.py`:
  `4daae03fbff49388194e15ef14736a4f590502ce`.
- Remove FlowClient extension status compatibility shims:
  `8ea115f521b824029a08e0b89893fb48f676921a`.
- Update browser-session module transport description:
  `83d97b108ecb1ab846ff7f2324c4af2cd967fdb3`.
- Replace unpacked-extension setup step with existing persistent-profile handoff:
  `99ea3cfdfa522b83133cf6bd7d29066bf50742a3`.
- Remove retired extension metadata ignore:
  `139647950ccbaa73adcc4f16d35fe4f764e50890`.
- Delete the 12 verified files under `extension/`:
  `8ac11c7` through `eb62253`.
- Align Task-3 authored coverage with fully retired compatibility shims:
  `81480e53d865951fda13b50a4a456758892fed5b`.

### Verified deletion scope

The removed `extension/` tree was inspected file-by-file before deletion:
- background service worker connected to `ws://127.0.0.1:9222` and proxied Flow RPC/CAPTCHA;
- content/injected/hijack scripts bridged Chrome isolated/main worlds and Flow reCAPTCHA;
- manifest/rules registered Flow/labs host permissions, service worker, DNR and side panel;
- popup/side-panel files presented extension connection/request UI;
- bundled reCAPTCHA loader/runtime existed only for that Chrome extension package.

Current source tree at this checkpoint contains **no `extension/` path**.

### Runtime/config cleanup

- `WS_HOST` and `WS_PORT` were removed from `agent/config.py`; they served the
  retired Flow extension socket and have no remaining Flow lifecycle consumer.
- Stale config comments saying Flow RPCs execute through the extension were
  rewritten to the leased browser-session authority.
- `FlowClient._flow_key`, `extension_connected` and `ws_stats` compatibility
  shims were removed after Tasks 6/7 stopped consuming them.
- `setup.sh` no longer instructs loading an unpacked extension. It only points
  the operator at an **existing** persistent browser-profile config via
  `COMICREELS_FLOW_PROFILE_CONFIG`; it explicitly does not create, clear or
  replace that profile.
- No browser profile directory, cookie/storage state, sign-in state or user data
  was read, mutated or deleted in this task.

### Preserved non-Flow WebSocket facilities

Ruling: keep `websockets>=12.0` in `requirements.txt`. The project still ships
the independent `/ws/dashboard` channel and `uvicorn` is installed without the
`[standard]` extra, so removing the WebSocket implementation dependency here
could break dashboard events. Cost if wrong: one dependency remains broader than
strictly necessary; removing it prematurely risks losing dashboard connectivity.

Ruling: keep the existing `chrome-extension://` origin compatibility on
`/ws/dashboard` for now. It belongs to the independent dashboard event channel,
not to the deleted Flow RPC transport, and this task deletes only references
verified as Flow-extension-only. Cost if wrong: an obsolete allowed origin may
remain until a later security-specific cleanup; removing it now could break an
unrelated dashboard client.

### Remaining Task 8 work

Legacy operator/docs/generated-copy references still exist outside runtime,
including `setup.py` generated AGENTS content, `AGENTS.md`, `CLAUDE.md`,
README/operator docs, Guide/i18n copy and historical skills/checkpoints. These are
**not** evidence that the extension runtime still exists; they are the next Task 8
documentation/preflight cleanup slice.

Tests/builds executed: **none**. No browser/profile launch, paid/CAPTCHA request,
EXE launch, Stable/ThoRemix mutation or Remote Desktop action occurred.

### Next short sub-task

**Task 8b — browser-only operator docs/Guide/generated preflight.** Rewrite
`setup.py` generated AGENTS source, checked-in AGENTS/CLAUDE/README/operator and
dashboard Guide copy so setup/preflight uses the persistent browser profile/session
and current browser health fields. Remove extension/token/9222/load-unpacked
instructions while preserving historical development ledgers where they are
explicitly marked historical.


## Browser-only Task 8b — generated/operator docs + Guide/preflight cutover

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; Task 8 still in progress**.

### Source scope completed

- `setup.py` now generates browser-only AGENTS preflight and invariants.
- Checked-in `AGENTS.md` is synchronized to that browser-only contract.
- `CLAUDE.md` now uses current browser/session readiness and separates paid
  authorization/reconciliation from transport health.
- `README.md` current operator sections now describe the persistent browser
  profile, browser-only architecture, browser health fields, paid lock, and
  no-resend reconciliation policy. Extension-era changelog entries were moved
  under an explicit **Historical migration notes** heading rather than rewritten
  as if they were current instructions.
- Dashboard `GuidePage.tsx` now reads the current `/health` schema:
  browser readiness, authentication, lease, reconciliation, paid dispatch and
  the independent dashboard event channel.
- Guide i18n canonical English and Vietnamese copy were rewritten browser-only.
  Other locales intentionally fall back to canonical English for Guide copy
  rather than retaining stale extension-era instructions.
- `scripts/statusline.sh` now reports browser readiness plus paid-lock and
  reconciliation state. It no longer reads extension WS counters or Flow-key
  status.
- Changed Claude command artifacts were normalized back to the `setup.py`
  generated stub format so they read current skills instead of embedding stale
  copies.
- Operator skills updated in this slice:
  `fk-doctor`, `fk-dashboard`, `fk-status`, `fk-pipeline`,
  `fk-gen-refs`, `fk-monitor`, `fk-refresh-urls`,
  `fk-review-video`, and `fk-upload-image`.
- Root/current architecture docs were aligned:
  `ARCHITECTURE.md`, `docs/CAPTURE.md`, `docs/OMNI_FLASH.md`,
  `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`.
- Legacy root `PLAN.md` is preserved for history but now begins with a clear
  **HISTORICAL / SUPERSEDED** warning and points to the 2026-10-01 browser-only
  cutover plan.

### Current operator preflight

Safe transport readiness requires all current positive evidence:
- `backend_ready=true`;
- `browser_session_ready=true`;
- `authentication=authenticated`;
- `lease_held=true`.

`paid_dispatch_enabled`, `reconciliation_required` and
`pending_intents` are separate dimensions. A healthy browser session never
grants paid authorization.

### Profile/data preservation

No source in this slice instructs operators to delete/reset profile data as a
recovery action. Current guidance explicitly says to preserve the existing bound
profile, cookies/storage and credentials. If authentication is signed out, stop
effects and use the approved interactive sign-in on the same profile rather than
creating/replacing one.

No browser profile, cookies, storage, credentials or user data were read or
modified during this GitHub-only source pass.

### Dashboard channel preservation

`/ws/dashboard` remains an independent event channel. Statusline/Guide/health
do not treat it as Flow readiness and no Flow transport fallback points to it.

### Source-only audit observations

Targeted operator surfaces now contain zero positive stale preflight references
to `extension_connected`, `flow_key_present`, `NO_FLOW_KEY`, port 9222,
load-unpacked/reload-extension recovery, or extension WebSocket transport.
Negative phrases such as “do not clear cookies/storage” are intentional safety
requirements, not legacy recovery instructions.

### Deferred validation

Tests, TypeScript build/lint, shell execution, browser/profile launch,
paid/CAPTCHA calls, EXE build, Stable/ThoRemix mutation and Remote Desktop
actions executed: **none**.

### Next short sub-task

**Task 8c — repo-wide stale-reference audit + Task 8 source closure.** Scan
remaining non-historical docs/generated artifacts/config/package references for
Flow-extension transport strings; classify explicit historical records versus
current operator/runtime references; repair only current stale references. Then
mark Task 8 source-complete and hand off to Task 9 final integration audit.


## Browser-only Task 8c — repo-wide stale-reference audit + Task 8 source closure

Date: 2026-10-01.
Status: **TASK 8 SOURCE_COMPLETE; NOT VALIDATED**.

### Audit method

GitHub code search does not reliably index the feature-branch head, so Task 8c
did not treat repository search returning zero results as evidence. The audit used
the exact branch ref/tree and read the relevant blobs from that revision.

Audited categories:
- Flow runtime/lifecycle/API/backend/session/worker/SDK source;
- dashboard Flow status/Guide/event-channel source;
- setup/run/statusline/build/package/config surfaces;
- generated Claude command artifacts with anomalous embedded content;
- current root/operator/architecture/capture/Omni documentation;
- current Flow/operator skills;
- browser-only/legacy Flow test contracts that could otherwise require deleted
  extension behavior in Phase 3.

### Runtime result

At the audit head:
- repository tree contains **no `extension/` path**;
- `agent/main.py`, `agent/config.py`, Flow API/services, worker and SDK live
  paths contain no retired extension protocol markers such as
  `extension_connected`, `flow_key_present`, `NO_FLOW_TAB`,
  port 9222, extension lifecycle methods, extension callback route or WS server;
- stale worker and `flow_batch.py` comments that still named the Chrome
  extension as active transport were corrected to browser-only wording;
- setup/scripts/deployment/workflow/package surfaces contain no Flow extension
  launch/bundle/config dependency;
- `websockets>=12.0` remains intentionally for the independent dashboard event
  WebSocket, per Task 8a ruling.

### Generated artifact result

Four checked-in Claude command files still embedded stale copies after their
source skills were fixed:
- `fk-monitor`;
- `fk-refresh-urls`;
- `fk-review-video`;
- `fk-upload-image`.

They were normalized to the generated stub form that delegates to the current
`skills/fk-*.md` source. Earlier Task 8b had already normalized the stale
dashboard/doctor/status/pipeline artifacts.

Large remaining command artifacts were inspected for the retired transport
markers and did not contain extension preflight references.

### Test-contract result

Retired:
- `tests/unit/test_extension_hijack_bypass.py`: tested files deleted with the
  extension package;
- `tests/unit/test_flow_backend_integration.py`: encoded default-extension,
  extension socket and extension lifespan behavior superseded by the browser-only
  selection/lifecycle/status suites.

Updated:
- global-throttle status coverage now checks browser readiness/reconciliation/
  paid-lock state instead of extension version/socket metadata;
- the old `CAPTCHA_FAILED: NO_FLOW_TAB` image case was removed from the legacy
  batch test because the one-shot paid browser contract has dedicated Task 4
  coverage;
- new authored audit coverage protects live Flow surfaces from retired protocol
  markers and confirms the old explicit `extension` backend setting is rejected.

Remaining extension words in active tests are negative assertions such as
"ExtensionFlowBackend must not exist" or "extension_connected must not appear";
those are regression guards, not runtime dependencies.

### Documentation classification

**Current authority/current operator docs** were repaired:
- root `ARCHITECTURE.md`, README current sections, AGENTS/CLAUDE;
- `docs/CAPTURE.md`, `docs/OMNI_FLASH.md`;
- `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`;
- current Dashboard Guide/i18n/statusline and Flow/operator skills;
- current ComicReels `VISION.md`.

**Historical/superseded records are intentionally preserved**:
- root `PLAN.md` is explicitly marked **HISTORICAL / SUPERSEDED**;
- `docs/comicreels/ARCHITECTURE.md` Segment-1 proposal is explicitly marked
  **HISTORICAL / SUPERSEDED** and points to current browser-only authority;
- `docs/comicreels/FOUNDATION.md` is a dated 2026-09-24 Segment-1 evidence
  snapshot and is not rewritten;
- FBR development ledgers, old superpowers plans/checkpoints, dated local-test
  results and migration/changelog sections remain historical evidence rather
  than being cosmetically rewritten.

Safety prohibitions such as **do not clear cookies/storage**, **do not replace
the profile**, and statements that the old extension transport is **retired/not
supported** are intentionally retained. They are not classified as stale
operational references.

### Independent dashboard channel

`/ws/dashboard` remains in `agent/main.py`, its event bus subscription remains,
and dashboard WebSocket source remains in the tree. The existing
`chrome-extension://` origin compatibility is intentionally preserved under the
Task 8a ruling because the evidence does not prove it belongs exclusively to the
removed Flow RPC transport. It is not used as Flow readiness.

### Profile/data boundary

Task 8c read and changed repository source only. It did **not** read, create,
copy, clear, rename, sign out of or otherwise mutate any browser profile,
cookies/storage, credentials or user data.

### Known Task 9 source-audit obligation

`tests/unit/test_flow_client_batch.py` still contains pre-cutover behavioral
expectations unrelated to extension transport, notably multi-wave image generation
and process-local poll-cache cadence. Tasks 4/5 authored replacement one-shot and
restart-safe contracts. Task 9 must reconcile those legacy behavioral tests
against current source before Phase 3 is entered. They were not rewritten under
Task 8 because they are not extension runtime/docs references.

### Task 8 source closure

All Task 8 plan obligations are represented:
1. Flow extension runtime/package code removed;
2. extension-only callback/WS configuration removed;
3. current preflight/docs/Guide/skills use persistent browser profile/session
   readiness;
4. independent dashboard event WebSocket preserved;
5. current generated/operator docs audited and checkpointed.

Tests/builds executed: **none**. No shell/statusline execution, pytest,
TypeScript build/lint, browser/profile launch, paid/CAPTCHA effect, EXE launch,
Stable/ThoRemix mutation or Remote Desktop action occurred.

### Next plan task

Proceed to **Task 9 — final source integration and validation handoff**. Task 9
must reconcile this long-lived browser-only branch with then-current `main`
without overwriting main, preserve PR #12 staged-KAT changes and later main
changes, reconcile remaining stale behavioral test contracts, update
`CHECKPOINTS.md`, record exact source/KBS/rollback revisions, and only after
Task 9 source closure authorize Phase 3 validation.


## Browser-only Task 9a — then-current main/diff integration audit

Date: 2026-10-01.
Status: **SOURCE AUDIT COMPLETE; NO MERGE YET; NOT VALIDATED**.

### Exact revisions observed

- Browser-only branch pre-9a source head:
  `0680645484fa311a76173ebeb39b688ade006092`.
- Then-current `main`:
  `5aecee7ef007b34e1ec732a3a382c80ff393546c`.
- Common merge base:
  `373e0a2e416819774fa88df0517b71868832b138`.
- Branch relation to current main:
  **211 commits ahead / 17 commits behind**.
- PR #12 staged-KAT merge:
  `18553d3fda9b26105f99951b2c752bc7fe5ca568`.
- PR #12 remains an ancestor of current main. Current main is exactly **3 commits
  ahead** of that merge.
- Browser/KBS pin is identical on current main and the browser branch:
  `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.

### Main-only preservation set

From merge base `373e0a2...` to current main, the complete file delta is only
these eight files:

1. `.github/workflows/tests.yml`;
2. `.github/workflows/thoremix-kat-staging.yml`;
3. `agent/thoremix/publishing.py`;
4. `deployment/thoremix/Build-Stable.ps1`;
5. `deployment/thoremix/Test-KatStagingContract.ps1`;
6. `deployment/thoremix/verify_upgrade_lock.py`;
7. `requirements-dev.txt`;
8. `tests/unit/test_setup.py`.

The browser-only branch did **not** intentionally modify any of those eight files
relative to the common merge base. Their branch blobs are older/missing only
because the branch diverged before those 17 main commits. Therefore the
integration rule is unambiguous: current-main versions of all eight files must be
preserved verbatim unless a later explicit source reconciliation proves a
browser-only change is required. No such requirement exists at this checkpoint.

### PR #12 / post-PR12 details that must survive

PR #12 source `18553d3...` introduced/preserved:
- portable hosted-test workflow exclusions and local-final-acceptance warning;
- ThoRemix KAT staging workflow;
- Python 3.10-compatible publication hashing;
- canonical KAT refresh in both normal and `-SkipRuntime` Stable builds;
- fail-closed KAT staging contract;
- `numpy` dev-test dependency.

The three commits after PR #12 additionally preserve:
- canonical sibling KAT source in staged ThoRemix upgrade smoke
  (`deployment/thoremix/verify_upgrade_lock.py`);
- explicit UTF-8 fixture reads/writes on Windows
  (`tests/unit/test_setup.py`).

Ruling: integration is **main-preserving**, never branch-overwrite. The rollback
source candidate for the later final integration is current pre-integration main
`5aecee7...`; Task 9 final closure will record the actual rollback revision only
after the integration source commit is created.

### Legacy behavioral-test reconciliation set for Task 9b

`tests/unit/test_flow_client_batch.py` predates Tasks 4/5 and still encodes
behavior deliberately removed by the browser-only cutover.

Image-generation expectations to retire/migrate:
- direct `generate_images()` without durable idempotency;
- multi-variant/count=2/count=4 wave dispatch;
- `IMAGE_UI_SUBMIT_OFFSETS_S` cadence;
- transient RPC [8] paid resubmit after cooldown;
- partial-success multi-wave aggregation;
- old direct batch/CAPTCHA transport assumptions for image/edit.

The authoritative replacement contract is
`tests/unit/test_flow_client_paid_one_shot.py`: one paid image, one durable
idempotency key, one backend paid call, no wave/retry, UNKNOWN no-resend and
historical media response shape.

Operation/poll expectations to retire/migrate:
- process-local `client._operation_projects`;
- every-third-poll listing cadence;
- process-local known-media cache skipping later listing/poll reads.

The authoritative replacements are
`tests/unit/test_flow_operation_durable_binding.py`,
`test_flow_poll_restart_safe.py` and
`test_flow_restart_resume_contract.py`: durable operation/project binding,
current listing/media reads after restart, no RAM correctness cache and
response-shape preservation.

Tests in `test_flow_client_batch.py` that still cover unrelated valid contracts
(video payloads, unsupported/degraded modes, media parsing, upload, project/credit
shape, URL refresh) should be preserved or moved rather than deleting the file
wholesale.

### Integration order

Task 9 source integration will proceed in short slices:
1. **9b** reconcile the stale multi-wave/poll-cache tests on the browser branch;
2. **9c** merge/reconcile then-current main into the browser branch with current
   main winning the eight-file preservation set;
3. **9d** re-audit browser-only production paths, paid gate/no-resend, source
   references and exact KBS pin after integration;
4. **9e** update `CHECKPOINTS.md`, final ledgers and plan with exact integrated
   source SHA + rollback SHA, then declare source closure.

No Phase 3 test/build/browser/EXE/Stable execution is authorized before 9e.

Tests/builds executed in 9a: **none**. No browser/profile, paid/CAPTCHA,
Stable/ThoRemix runtime or Remote Desktop action occurred.


## Browser-only Task 9b — reconcile legacy FlowClient batch tests

Date: 2026-10-01.
Status: **SOURCE_AUTHORED; NOT VALIDATED; integration with main not started**.

Source commits:
- Migrate image payload/edit/project contracts into paid one-shot suite:
  `76ea6f8b2e2ec652ec2e5d857f08ca027fcc51c2`.
- Migrate valid polling semantics into durable/restart-safe suite:
  `0011f5caef72488d7d2b8abf5c1024ff9cc6958c`.
- Reconcile legacy `test_flow_client_batch.py` with one-shot + durable state:
  `ec88af22d9ce5ad4100390fbd732a90b18d48048`.

### Coverage migration — paid image/edit

The old `TestGenerateImages` / `TestEditImage` classes were not merely deleted.
Their still-valid contracts were moved to
`tests/unit/test_flow_client_paid_one_shot.py` before removal:

- historical business media response shape remains covered;
- exact `ogiZ0b` RPC + image CAPTCHA action + target project remain covered;
- image model wire id is preserved rather than silently replaced;
- explicit seed remains in the paid one-shot request;
- character references remain in Flow's REFERENCE_IMAGE slots;
- image edit source remains BASE_IMAGE and is deduplicated from reference inputs;
- the legacy configured project fallback remains covered for callers passing the
  historical sentinel project id;
- no configured/explicit project fails before paid submission;
- known `effect=not_submitted` provider rejection is returned after exactly one
  paid backend call with no media read/retry.

Superseded behavior is now explicitly covered by the replacement one-shot suite:
- count > 1 fails with `PAID_SINGLE_SHOT_REQUIRED`;
- missing durable key fails with `PAID_IDEMPOTENCY_REQUIRED`;
- no `IMAGE_UI_SUBMIT_OFFSETS_S` / multi-wave cadence;
- no transient RPC paid resubmit;
- UNKNOWN/backend exception maps to reconciliation and no second submission;
- a completed durable receipt with no fresh signed URL stays completed rather
  than causing paid regeneration.

Therefore old multi-wave, count-2/count-4, partial-wave and retry-after-[8]
expectations were removed because keeping them would require reintroducing behavior
the browser-only safety contract explicitly forbids.

### Coverage migration — durable polling/restart

Valid poll behaviors were migrated/strengthened in
`tests/unit/test_flow_poll_restart_safe.py`:

- restart with empty RAM state discovers the current listing on the first poll;
- a listing media id with only a poster remains PENDING;
- a Flow operation complaint remains visible while listing is still pending;
- project listing lookup still requests an operation-specific match window rather
  than requiring the full large listing payload;
- unreadable/decayed operation polling still consults the durable project listing;
- a finished operation remains successful when re-polled, with each round rebuilt
  from durable binding/current reads rather than RAM media cache.

The legacy suite was updated accordingly:
- `_operation_projects` assertion became durable backend binding assertion plus
  a negative assertion that the RAM map does not exist;
- the old every-third-poll listing cadence became first-poll listing authority;
- tests requiring quiet-poll listing suppression or cached media-id bypass were
  removed because they directly contradict restart-safe correctness.

### Contracts intentionally retained in test_flow_client_batch.py

The file still covers non-superseded contracts:
- synchronous image upscale request/response shape;
- video submit response and durable operation binding;
- documented unsupported/degraded video mode behavior;
- current operation success/pending/complaint/listing-window/nameless shapes;
- media reads and validation;
- upload request/response shape;
- project creation/project-id/tier behavior;
- signed URL refresh behavior including partial failures.

Its fixture now uses a minimal browser backend stub with durable
operation→project binding. Paid image submission through that fixture is forbidden,
so a future test cannot accidentally fall back to the removed direct image path.

### Source-only verification

Readback of `test_flow_client_batch.py` at this checkpoint:
- `generate_images(`: 0 calls;
- `edit_image(`: 0 calls;
- `IMAGE_UI_SUBMIT_OFFSETS_S`: 0;
- `IMAGE_TRANSIENT_RETRY_DELAY_S`: 0;
- `_operation_media`: 0;
- `_operation_polls`: 0;
- `_operation_projects`: one occurrence, solely the negative
  `not hasattr(...)` regression assertion.

Tests executed: **none**. No pytest/import/compile/lint, browser/profile,
paid/CAPTCHA, build/EXE/Stable or Remote Desktop action occurred.

### Next short sub-task

**Task 9c — integrate then-current main into the browser-only branch.** Re-read
`main` immediately before integration, then reconcile from current main rather
than overwriting it. Preserve current-main versions of the eight-file main-only
set (including PR #12 staged-KAT and post-PR12 Windows fixes) while carrying
browser-only Flow changes forward. Record the actual integration commit and new
branch/main ancestry. Do not run Phase 3 validation.


## Browser-only Task 9c — integrate current main into browser branch

Date: 2026-10-01.
Status: **SOURCE INTEGRATED; NOT VALIDATED; Task 9 still in progress**.

### Exact integration revisions

- Browser branch before integration:
  `cb8c970744ab9aed0bb767bb8a359b40297b344d`.
- Then-current `main` immediately before integration:
  `5aecee7ef007b34e1ec732a3a382c80ff393546c`.
- Integration merge commit:
  `dc6d468fc8057b951440c534315fe962a38bbeda`.
- Merge tree:
  `776731c7c20eb7bd8c0c63e63dec832389f0597d`.
- Merge parents, in order:
  1. browser branch `cb8c970...`;
  2. current main `5aecee7...`.

GitHub initially reported the temporary main→feature integration PR as
non-mergeable. Rather than force a branch overwrite, Task 9c created an explicit
two-parent merge commit whose tree was built from the browser branch plus the
eight audited current-main blobs. The feature ref was then fast-forwarded to that
merge commit. Main itself was never moved.

The temporary integration PR #14 is now closed/recognized as merged against
`dc6d468...`; it was only an integration vehicle and does not alter main.

### Ancestry result

Post-integration compare:
- `main 5aecee7...` → browser merge `dc6d468...`:
  **ahead, 217 ahead / 0 behind**, merge-base exactly `5aecee7...`.
- PR #12 `18553d3...` → browser merge:
  **ahead, 220 ahead / 0 behind**, merge-base exactly `18553d3...`.

Therefore current main and PR #12 are both true ancestors of the integrated
browser branch.

### Eight-file main preservation proof

Post-integration branch blob SHA equals current-main blob SHA for all eight
main-only files:

| File | Preserved blob SHA |
|---|---|
| `.github/workflows/tests.yml` | `5b183976286294912fbf6c4774c5bc3228820125` |
| `.github/workflows/thoremix-kat-staging.yml` | `795b15d5bf44103343e0822a3ecc919373e05ba8` |
| `agent/thoremix/publishing.py` | `c571aecad820b2fb102941ceff031b7db552e2c6` |
| `deployment/thoremix/Build-Stable.ps1` | `4ad5f9858911a2ed11bd495007310565e3d20cf1` |
| `deployment/thoremix/Test-KatStagingContract.ps1` | `c239c01dfceef3b22d81dd94db9fa36811bc16b9` |
| `deployment/thoremix/verify_upgrade_lock.py` | `3ef4b0e54f9d478a6869a66855aa63afd760a1c8` |
| `requirements-dev.txt` | `4a9facf17e60dc722011863ae8595fa278ecc103` |
| `tests/unit/test_setup.py` | `4e4e7f0c037638cf0f965c712e14b939d748e992` |

This proves PR #12 staged-KAT protections, Python 3.10 publication hashing,
canonical KAT staged refresh, post-PR12 canonical sibling KAT smoke, and explicit
UTF-8 Windows fixture fixes were not overwritten by the browser branch.

### Browser-only source preservation proof

Critical browser-only blobs are unchanged across the integration commit:

- `flow_backend_selection.py`:
  `1374d5dc185d1d2908a7ed5ae069ce9cfb8bed94`;
- `flow_client.py`:
  `8c72f78fe1aade34c8b3c50b4973546e278a30cf`;
- `flow_browser_paid.py`:
  `f6a21624aa2c2738754dad46c8403a6eaab57e41`;
- `flow_paid_validation.py`:
  `f5f95cd87dff5c073d41b13e13e52576861e7f07`;
- `requirements-flow-browser.txt`:
  `467cb51367526c670df78e1bdc0b365de815c326`.

KBS pin remains:
`b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.

### Main-preserving ruling

Ruling: main wins verbatim for the complete eight-file main-only delta, while the
browser branch wins for browser-only Flow source because current main had no
independent changes to those browser-only files after the common merge base.
The two-parent merge records both histories rather than synthesizing a fake
linear overwrite.

Cost if wrong: a hidden cross-file semantic dependency could still surface only
during Phase 3 validation; Task 9d therefore performs a post-integration source
audit before validation is authorized.

Tests/builds executed: **none**. No pytest/import/compile/lint, browser/profile,
paid/CAPTCHA, EXE/Stable/ThoRemix runtime or Remote Desktop action occurred.

### Next short sub-task

**Task 9d — post-integration source audit.** Re-read the integrated source tree
and confirm:
1. no production path can select/call extension Flow transport;
2. browser paid path exists but normal production remains locked;
3. UNKNOWN/no-resend and durable restart binding remain intact;
4. worker/startup/status/UI/docs remain browser-only after main integration;
5. KBS pin and current main ancestry are still exact.

Then record any remaining source-only validation obligations for 9e. Do not enter
Phase 3 yet.


## Browser-only Task 9d — post-integration source audit

Date: 2026-10-01.
Status: **AUDIT COMPLETE; SOURCE CLOSURE NOT READY; NOT VALIDATED**.

Audited integrated branch head:
`6f90784cbe920576e2ceee979b53bc3fcd742745`.

Current-main ancestor remains:
`5aecee7ef007b34e1ec732a3a382c80ff393546c`.

KBS pin remains exact:
`b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.

Owner also reported a separate live canonical KAT PASS at `b89c2b71`.
That evidence is explicitly **not** a PASS for this browser-only branch and does
not satisfy any Phase 3 browser validation gate.

### Confirmed-good source boundaries

- Backend selection is browser-only. Explicit `COMICREELS_FLOW_BACKEND=extension`
  fails with `FLOW_EXTENSION_BACKEND_REMOVED`; there is no
  `ExtensionFlowBackend`.
- Normal `BrowserFlowBackend()` construction keeps
  `paid_dispatch_enabled=False`.
- The only explicit paid authorization source currently implemented is the
  isolated one-shot `flow_paid_validation.py` seam; normal HTTP/startup does
  not import it or manufacture authorization.
- Paid image gate writes durable intent before browser fetch, persists receipt
  before business success, and projects ambiguous post-submit outcomes as
  `PAID_RECONCILIATION_REQUIRED/effect=unknown`.
- Paid image replay of SUBMITTING/UNKNOWN is blocked.
- Browser session requires the existing profile, fresh authentication evidence
  and held lease; profile replacement/credential persistence is not introduced.
- Operation polling itself uses durable operation→project binding and no
  process-local operation/media correctness cache.
- Root health/backend-status/dashboard Flow status are browser-only and keep
  readiness, reconciliation and paid lock independent.
- `/ws/dashboard` remains a separate event channel.
- Current main/PR #12 ancestry and the eight-file preservation set survived
  Task 9c integration.

### Source-closure blockers

#### B1 — worker paid-lock check disables restart/reconciliation work

`WorkerController.start()` returns immediately whenever the normal backend has
`paid_dispatch_enabled=False`.

This conflicts with the plan's Task 2/Review Focus contract that queue processing
continues under browser-only mode and that existing pre-cutover jobs remain usable.
A saved remote operation can be resumed read-only by
`OperationService._resume_saved_operation()`, but the worker never reaches that
code while normal paid dispatch is locked.

Required repair: let the worker lifecycle run independently from the paid switch.
Keep paid authorization at the actual new-effect submit boundary. Existing saved
operations must remain pollable/reconcilable while new paid submits stay locked.

#### B2 — new video/Omni paid submits have no browser paid-dispatch boundary

`FlowClient.generate_video()` and all Omni submit modes still call
`_batch_payload(..., CAPTCHA_VIDEO)`, which goes through generic
`BrowserFlowBackend.execute()`.

The generic browser contract allowlist intentionally excludes all paid video RPCs,
so these production routes currently resolve to `RPC_NOT_ALLOWED`. There is no
video equivalent of the paid image intent/authorization/receipt gate.

This is not a request for a new product feature: video generation, R2V/Omni and
pipeline behavior are existing FlowKit business capabilities that the cutover
contract says must remain transport-independent.

Required repair before source closure: route the already-supported video submit
modes through a dedicated browser paid boundary with the same invariants as paid
image:
- durable business idempotency/intent before effect;
- explicit authorization, disabled in normal source;
- no generic CAPTCHA/effect retry;
- completed/unknown/not_submitted effect classification;
- durable receipt sufficient for restart/polling;
- no extension fallback.

Do not broaden this repair into unsupported video upscale or unrelated model work.

#### B3 — Omni operation binding calls omit `await`

Both `_submit_omni_frame_video()` and the operation-receipt branch of
`generate_omni_flash_video()` call:

`client._remember_operation(operation.operation_id, pid)`

without `await`, even though `_remember_operation()` is async.

If the submit path were reachable, the durable operation→project mapping would
not be persisted, making subsequent browser polling/restart fail with
`OPERATION_BINDING_REQUIRED`.

Required repair: await the durable bind and preserve fail-closed UNKNOWN/no-resend
semantics if binding cannot be committed after a remote submit.

#### B4 — direct session-project helper bypasses the durable browser create path

`flow_project_session.ensure_session_project()` calls
`client.create_project()`. `FlowClient.create_project()` uses generic raw
`RPC_CREATE_PROJECT`.

The browser driver deliberately returns
`BROWSER_CAPABILITY_NOT_IMPLEMENTED` for raw create because safe project creation
belongs to `BrowserFlowBackend.ensure_session_project()`, which journals the
create intent/receipt.

Therefore project-less direct Flow endpoints and
`/session-project/rotate` cannot use the browser driver's implemented durable
create/reuse path.

Required repair: route the business/session helper through
`client.backend.ensure_session_project()` (via a stable FlowClient method), not
through raw generic create. Preserve the existing external response shape and
session-project convenience state without creating a second remote-effect path.

#### B5 — project-scoped media reads lose project scope in two restart paths

Two current read paths know the correct project id but discard it:

1. `FlowClient.refresh_project_urls(project_id)` calls
   `_batch_media_urls(media_id)` without `project_id`.
2. Omni workflow polling resolves `resolved_project_id` but calls
   `client.get_media(media_id)` without project scope.

`RPC_MEDIA` then falls back to whichever project is saved/active in the browser
state. After restart or multi-project activity this can read against the wrong
project.

Required repair: make `get_media` accept an optional project scope, propagate
the known project id through refresh/Omni/paid-receipt read paths, and keep
unscoped behavior only for callers that genuinely have no project context.

### Required cleanup before closure, not capability expansion

#### C1 — live worker still contains extension-era transient retry strings

`_handle_failure()` still has a reachable branch matching
“extension reconnected/disconnected/not connected”. It is obsolete in a
browser-only runtime and contradicts the Task 8 source-retirement claim.

Remove this compatibility branch. Do not replace it with browser effect retry.
Browser readiness failures should follow fixed browser codes and must never turn
an uncertain effect into a resend.

#### C2 — KBS requirements header still says FBR-0 shadow/optional browser

The pin itself is correct and exact, but the comments in
`requirements-flow-browser.txt` still describe an “Optional FBR-0 shadow
browser”. Update wording to browser-only/current authority without changing the
KBS SHA.

### Non-blockers / intentionally deferred behavior

- Normal production paid image dispatch being locked is **expected**, not a
  blocker. Source closure is for a validation-ready branch, not implicit
  production authorization.
- Normal HTTP generation routes not manufacturing the paid validation capability
  is **correct**.
- `RECONCILIATION_REQUIRED` not making safe read transport “down” is deliberate.
- Dashboard event WebSocket is independent and remains intentionally present.
- Explicitly unsupported video-upscale behavior is not expanded by this audit.
- No KAT result, including owner-reported canonical PASS `b89c2b71`, is used as
  browser-branch acceptance evidence.

### Source-closure readiness verdict

**NOT READY FOR TASK 9e / PHASE 3.**

The five blockers above are source correctness gaps inside the already-approved
browser-only cutover scope. They must be repaired on GitHub first, with authored
regression coverage, before the final checkpoint can truthfully state source
completion.

Recommended next short sub-task:
**Task 9d-repair-1 — worker/resume boundary.**
Remove the paid-switch early return from worker startup, preserve read-only resume
of saved operations while paid dispatch is locked, remove the obsolete extension
retry branch, and author source regression coverage. Do not yet implement the
video paid bridge in the same sub-task.

Tests/builds executed during 9d audit: **none**. No browser/profile launch,
paid/CAPTCHA call, EXE/Stable/ThoRemix runtime or Remote Desktop action occurred.
