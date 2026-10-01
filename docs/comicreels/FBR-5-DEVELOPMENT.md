# FBR-5 development ledger

Authority: `FLOW-BROWSER-FIRST-ARCHITECTURE.md` and
`../superpowers/plans/2026-09-27-flow-browser-refactor.md`.
Base: `607ec0a482de544c1175ae7bf636d6f30a0b9b16`.
Branch: `feat/fbr-2-driver-lifecycle-20260930`.

Overall status: **CODE_IN_PROGRESS — production default NOT accepted here**.
Latest slice: **FBR-5-code-1 — policy source authored, NOT VALIDATED**.

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

The current `get_flow_client()` implementation still selects its backend directly.
FBR-5-code-1 does not wire this new resolver into that function; that is code-2.
No production behavior changes simply because this policy module is added.

Tests/builds executed: **none**. Test source is authored during development;
execution is deferred by the owner's phased workflow. No runtime/profile/Stable
state is inspected. No paid request or Remote Desktop action occurred.

## Exact next task

**FBR-5-code-2a — wire selection into singleton startup**, including authored
requirements for explicit extension rollback, opt-in browser construction, fixed
startup selection until restart, and no automatic fallback on browser failure.
Keep status/UI wiring as the subsequent bounded code-2b slice. Do not run tests.

KBS source dependency is unchanged by this slice. Runtime backend/revision,
physical profile identity/lease, active jobs and scheduler state remain unobserved.
Main and Stable were not changed. Rollback source boundary for this policy-only
slice is `607ec0a482de544c1175ae7bf636d6f30a0b9b16`; no runtime rollback is needed.
