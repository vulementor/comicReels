# FBR-5 development ledger

Authority: `FLOW-BROWSER-FIRST-ARCHITECTURE.md` and
`../superpowers/plans/2026-09-27-flow-browser-refactor.md`.
Base: `607ec0a482de544c1175ae7bf636d6f30a0b9b16`.
Branch: `feat/fbr-2-driver-lifecycle-20260930`.

Overall status: **CODE_IN_PROGRESS — production default NOT accepted here**.
Latest slice: **FBR-5-code-2a — singleton selection wired, NOT VALIDATED**.

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

## Exact next task

**FBR-5-code-2b — selected-backend status/readiness/preflight integration.**
Expose metadata from the frozen startup selection, not a newly resolved environment
snapshot. Keep configuration, current backend readiness and production acceptance
separate. Browser readiness must not require an extension connection. Keep API/UI
changes inside that next slice, retain explicit extension rollback and paid gates.
Do not run tests/build/EXE until the full approved coding pass is complete.

KBS source dependency is unchanged by this slice. Runtime backend/revision,
physical profile identity/lease, active jobs and scheduler state remain unobserved.
Main and Stable were not changed by this work. Rollback source boundary for code-2a
is `179f90b9b00c7844937be5c15964ee8858694810`; no runtime rollback is needed.
