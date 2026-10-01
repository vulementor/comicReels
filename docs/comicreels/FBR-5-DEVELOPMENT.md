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
