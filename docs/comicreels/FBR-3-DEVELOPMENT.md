# FBR-3 development ledger

## FBR-3-code-1 — disabled one-shot paid image safety boundary

Date: 2026-09-30.
Status: **CODE_COMPLETE for preparation only; NOT VALIDATED; DISPATCH DISABLED**.

Authority:
- `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`.
- `docs/superpowers/plans/2026-09-27-flow-browser-refactor.md`.
- Owner development-first directive in `AGENTS.md`.

Source commits:
- Authored paid-gate requirements:
  `e5908e0f0b41a4857a12e47b8fcbf22b12d6bcb8`.
- Durable journal support for paid-image intents:
  `c1f5a173572edac685873987a00f19045a28c447`.
- Disabled paid single-shot gate:
  `661054343a8a6da631ce8362a72606334c26b07a`.

### Boundary implemented

- New `FlowPaidImageGate` is isolated from `FlowBrowserDriver.execute()`.
  Creating this source does not make browser paid dispatch reachable.
- `dispatch_enabled` defaults false. A disabled call returns
  `PAID_DISPATCH_DISABLED` before validation, journal creation or dispatch.
- Even when explicitly enabled in a later validation harness, an exact in-memory
  authorization object is required before any paid intent can be created.
- Only `ogiZ0b` image generation is accepted, with one variant exactly.
  Video, multi-variant and malformed recipes fail closed.
- Paid request state stores only project UUID, RPC id and SHA-256 fingerprints.
  Prompt text, captcha token, auth/session data and signed URLs are not persisted.
- Idempotency keys are hashed before journal storage. Reusing the same key with a
  different request fingerprint returns `PAID_IDEMPOTENCY_CONFLICT`.
- A new authorized submission writes SUBMITTING before the injected dispatcher.
  COMPLETED receipts contain only project/media UUIDs.
- SUBMITTING or UNKNOWN intents return `PAID_RECONCILIATION_REQUIRED` and never
  call the dispatcher again automatically.
- Timeout, malformed response, exception, missing/ambiguous media receipt or
  persistence uncertainty becomes UNKNOWN when possible and never auto-retries.
- Completed receipts are reusable after restart without another external effect.

### Important separation from existing extension generation

`FlowClient.generate_images()` currently contains extension-era cadence/retry
logic. FBR-3 browser paid one-shot does not reuse that retry loop. This preparation
module accepts exactly one variant and has no automatic retry path.

The gate currently receives an injected dispatcher but no browser-paid dispatch
recipe is supplied or wired. That is intentional: actual paid browser submission
belongs to the later explicit FBR-3 validation gate after FBR-0/1/2 acceptance,
session continuity evidence, cost/preset confirmation and owner authorization.

### Authored requirements and deferred validation

`tests/unit/test_flow_browser_paid_gate.py` records requirements for:
- default disabled behavior;
- exact authorization identity;
- intent-before-effect ordering;
- single dispatch only;
- completed receipt reuse;
- idempotency conflict;
- SUBMITTING/UNKNOWN replay prevention;
- ambiguous outcome handling;
- multi-variant/non-image rejection.

Tests executed: **none**. No pytest/import/compile/lint/build, browser launch,
paid Flow request, EXE launch, Stable action or Remote Desktop action occurred.

Ruling: Superpowers TDD normally requires RED/GREEN execution, but the owner's
repository directive explicitly defers all tests until the complete coding pass.
Tests were authored before implementation and execution is deferred to validation.

### Next coding task

Proceed to **FBR-4 parity-matrix source integration**: encode business-level
extension/browser parity expectations for preserved ComicReels/FlowKit scenarios,
without running paid generation and without changing browser backend to default.

FBR-3 paid dispatch remains disabled until the separate paid validation gate.


## Supersession update — browser-only Task 4 source closure

Date: 2026-10-01.

The preparation-only limitations documented above are historical. Under
`docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`, Task 4 has now
source-authored the dedicated browser paid recipe, leased-session bridge,
FlowClient one-shot routing, durable request-id propagation, UNKNOWN no-retry
handling and an isolated explicit validation authorization seam.

Normal application startup remains paid-disabled. No paid request or validation
test has run, so this update does **not** change FBR-3/Task 4 acceptance status.
Live paid validation remains a later owner-authorized Phase 3 action after the
entire browser-only source plan is complete.
