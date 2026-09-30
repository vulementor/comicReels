# FBR-4 development ledger

## FBR-4-code-1 — parity matrix source integration

Date: 2026-09-30.
Status: **CODE_COMPLETE for parity-matrix source integration; NOT VALIDATED**.

Authority:
- `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`.
- `docs/superpowers/plans/2026-09-27-flow-browser-refactor.md`.
- Owner development-first directive in `AGENTS.md`.

Source commits:
- Authored parity requirements:
  `a7001f251517bfaf2a7a9a2ee23396c776c5956e`.
- Immutable parity contract:
  `5a2cea38b8ef7312def98fbd90fb5ce0643dbd8d`.

### Integrated parity matrix

The source now records every mandatory FBR-4 scenario:

- project/story/entity creation;
- ROOT/CONTINUATION scene chains;
- transition-prompt behavior;
- multi-reference video;
- creative mix;
- pipeline resume;
- video review + selective regeneration;
- Gallery/Logs/Status;
- media refresh/download;
- TTS/concat/branding.

Each item is explicitly owned by FlowKit/business logic and marked
transport-independent. Evidence paths point to the existing canonical source or
skill that owns the behavior; this refactor does not duplicate those workflows
inside the browser transport.

`NON_FLOW_INVARIANTS` records TTS, concat, branding, review engine and project
DB model as unchanged by the transport migration.

### Browser eligibility guard

`validate_browser_parity_readiness()` provides a source-level eligibility check
for the later parity validation pass. A browser backend is not eligible unless:

- browser health is ready;
- readiness scope is `non_paid_parity`;
- accumulated non-paid operations are implemented;
- project lifecycle, project/media reads, upload and operation reconciliation
  capabilities are all available;
- paid dispatch remains disabled in both capability projection and backend state.

This helper is intentionally not a parity PASS verdict; it only prevents an
incomplete or prematurely paid-enabled backend from entering FBR-4 validation.

### Preservation ruling

Ruling: FBR-4 source integration must not rewrite existing creative/product
workflows merely to make them transport-aware. Their current modules/skills stay
canonical, and the matrix records those ownership boundaries instead. If this
ruling were wrong, the cost would be duplicate business logic and divergent
extension/browser behavior—the exact regression the architecture forbids.

### Validation boundary

`tests/unit/test_flow_parity_matrix.py` records the mandatory scenario set,
business ownership/evidence requirements, non-Flow invariants and browser
eligibility guard.

Tests executed: **none**. No pytest/import/compile/lint/build, browser launch,
paid generation, EXE launch, Stable action or Remote Desktop action occurred.

Ruling: Superpowers TDD normally requires RED/GREEN execution, but owner policy
defers all test execution until the coding pass is complete. Tests were authored
before implementation and execution is deferred to final validation.

### Exact next coding task

Proceed to **FBR-5 default-cutover source preparation**: browser becomes the
configurable/default candidate in source while retaining an immediate extension
fallback/rollback switch, updating health/preflight/status semantics accordingly.
Do not launch the app, switch Stable, or perform runtime acceptance yet.
