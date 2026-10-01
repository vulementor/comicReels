# Flow Browser-Only Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the FlowKit transport migration as browser-only: all Flow work runs through the persistent browser/KBS path, all extension/WebSocket transport dependencies are removed, and the app/worker/status/UI no longer depend on extension state.

**Architecture:** `FlowClient` remains the business API. `BrowserFlowBackend` becomes the only Flow backend. The persistent signed-in Flow profile remains the single auth/session authority. Extension/WebSocket transport, failover, health requirements, callbacks and UI indicators are removed from FlowKit. No automatic resend of uncertain paid effects is introduced.

**Tech Stack:** Python/FastAPI/asyncio, existing Flow browser driver/session/state modules, kabin_browser_semantic dependency, React/Vite dashboard, existing worker/DB pipeline.

**Spec:** `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md` as amended by owner directive on 2026-10-01: FlowKit no longer uses the extension transport at all.

## Global Constraints

- Browser-only Flow transport. Extension is not a fallback, rollback target, health dependency or valid production backend.
- Keep one persistent signed-in Flow browser profile under explicit lease.
- Do not clear cookies/storage, sign out, create replacement profiles or persist credentials.
- Keep FlowKit creative/business logic unchanged: project/story/entity, scene chains, prompts, review/regen, pipeline resume, gallery/logs/status, media refresh/download, TTS/concat/branding.
- Unknown paid outcomes remain non-retryable until reconciled.
- Paid generation is never used as a diagnostic.
- Finish GitHub development first. No local test/build/EXE/Stable validation until all coding tasks below are complete.
- Remote Desktop Commander remains forbidden during coding and is only eligible for final acceptance testing after source completion, per owner rules.
- Each response executes exactly one sub-task and stops for owner confirmation.

## Review Focus

1. Browser backend startup fails: app must fail explicitly, never silently recreate/fallback to extension.
2. Worker startup under browser-only mode: queue processing must still run; only obsolete extension WS tasks disappear.
3. Existing extension-only health/preflight strings: none may gate Flow work after removal.
4. Paid submission uncertainty: removal of extension code must not bypass durable intent/receipt/reconciliation gates.
5. Existing jobs/state created before cutover: business DB records must remain usable without extension metadata.

---

### Task 1: Replace backend selection policy with browser-only policy

**Files:**
- Modify: `agent/services/flow_backend_selection.py`
- Modify: `agent/services/flow_client.py`
- Test: `tests/unit/test_flow_backend_selection.py`
- Test: `tests/unit/test_flow_client_backend_selection.py`

**Interfaces:**
- Produces: one immutable browser-only startup selection.
- Removes: extension/default/rollback selection as runtime options.

- [x] Write authored tests asserting browser is the only accepted backend and extension configuration is rejected as obsolete.
- [x] Remove extension fallback/default branches from selection.
- [x] Make `get_flow_client()` construct only `BrowserFlowBackend`.
- [x] Keep construction/start failures fixed and non-retrying.
- [x] Update checkpoint docs.

### Task 2: Make application lifecycle browser-only

**Files:**
- Modify: `agent/main.py`
- Test: `tests/unit/test_worker_starts_with_browser_backend.py`
- Test: add browser-only lifespan coverage.

**Interfaces:**
- Consumes: browser-only singleton from Task 1.
- Produces: worker startup independent of extension transport.

- [x] Keep queue worker startup unconditional after backend start.
- [x] Remove extension WebSocket server startup and shutdown paths.
- [x] Remove extension callback lifecycle from application startup.
- [x] Preserve graceful worker shutdown.
- [x] Update checkpoint docs.

### Task 3: Remove extension transport implementation from FlowClient/backend layer

**Files:**
- Modify: `agent/services/flow_backend.py`
- Modify: `agent/services/flow_client.py`
- Delete or archive-from-runtime: extension-only transport helpers that are no longer referenced.
- Test: update backend contract coverage.

**Interfaces:**
- Produces: one Flow backend contract implemented by browser only.
- Removes: `ExtensionFlowBackend`, extension WS pending maps, extension failover/session selection.

- [x] Remove extension backend implementation and extension-specific send/failover paths.
- [x] Remove extension connection/token state from FlowClient where no longer used by non-Flow features.
- [x] Preserve business method signatures consumed by worker/API.
- [x] Confirm no business logic starts depending on browser internals.
- [x] Update checkpoint docs.

### Task 4: Complete concrete browser paid-dispatch integration

**Files:**
- Modify: `agent/services/flow_browser_paid.py`
- Modify: `agent/services/flow_browser_driver.py`
- Modify: `agent/services/flow_browser_backend.py`
- Modify: `agent/services/flow_client.py`
- Test: paid gate/driver/business authored coverage.

**Interfaces:**
- Consumes: durable paid intent/receipt gate already authored.
- Produces: browser-native one-shot generation path with idempotency and reconciliation.
- Keeps: dispatch disabled unless explicit later validation authorization allows it.

- [x] Add browser-authenticated paid image dispatch recipe bound to the same leased session.
- [x] Persist intent before effect and receipt before business-state success.
- [x] Route FlowClient single-shot image generation through browser paid gate without extension retry/cadence behavior.
- [x] Keep unknown outcomes non-retryable.
- [x] Keep validation authorization disabled by default in normal source config.
- [x] Update checkpoint docs.

### Task 5: Align polling/media/operation flow with browser-only state

**Files:**
- Modify: `agent/services/flow_client.py`
- Modify as needed: `agent/services/flow_browser_driver.py`, `flow_browser_state.py`
- Tests: operation/media/polling parity coverage.

**Interfaces:**
- Produces: browser-only operation project binding and polling.
- Removes: extension-era in-memory assumptions where durable browser journal is authoritative.

- [x] Ensure submitted browser operations persist project binding.
- [x] Ensure poll/media lookup uses durable binding and current browser session.
- [x] Preserve existing returned business response shapes.
- [x] Preserve restart/resume behavior.
- [x] Update checkpoint docs.

### Task 6: Remove extension-specific API/status/preflight surfaces

**Files:**
- Modify: `agent/api/flow.py`
- Modify: `agent/api/flow_backend_status.py`
- Modify: `agent/services/flow_backend_status.py`
- Modify: `agent/main.py`
- Tests: status/preflight source coverage.

**Interfaces:**
- Produces: browser-only health/preflight semantics.

- [ ] Remove `extension_connected` as a Flow readiness requirement.
- [ ] Remove extension session/token fields from selected-backend status where obsolete.
- [ ] Replace extension-specific 503 messages with browser/session readiness messages.
- [ ] Keep reconciliation and paid-dispatch states separately visible.
- [ ] Update checkpoint docs.

### Task 7: Remove extension-specific dashboard UI

**Files:**
- Modify: `dashboard/src/App.tsx`
- Modify: `dashboard/src/components/FlowBackendStatus.tsx`
- Modify translations/types if needed.
- Tests/build validation deferred to final phase.

**Interfaces:**
- Produces: browser-only status UX.

- [ ] Remove extension-connected/disconnected wording from Flow status.
- [ ] Show browser session readiness, reconciliation warning and paid-dispatch state.
- [ ] Preserve independent dashboard WebSocket indicator if it is used only for dashboard events.
- [ ] Do not label dashboard WS as Flow extension transport.
- [ ] Update checkpoint docs.

### Task 8: Remove extension runtime package/code and stale docs

**Files:**
- Delete/retire: `extension/` Flow transport code once no runtime references remain.
- Modify: `AGENTS.md`, `CLAUDE.md`, README/operator docs, skills with extension-only preflight instructions.
- Modify: dependency/build/package files if extension artifacts are bundled.

**Interfaces:**
- Produces: no shipped extension dependency for FlowKit.

- [ ] Remove extension build/package/runtime references.
- [ ] Remove obsolete callback/WS configuration used solely by Flow extension transport.
- [ ] Rewrite preflight to browser profile/session readiness.
- [ ] Preserve non-Flow dashboard/websocket facilities that remain independently required.
- [ ] Update checkpoint docs.

### Task 9: Final source integration and validation handoff

**Files:**
- Modify: `docs/comicreels/CHECKPOINTS.md`
- Modify: FBR development ledgers.
- No runtime execution yet.

**Interfaces:**
- Produces: source-complete browser-only revision ready for Phase 3 validation.

- [ ] Audit repository references for extension Flow transport.
- [ ] Confirm no production path can select or call extension transport.
- [ ] Confirm browser paid path exists but remains gated for explicit validation.
- [ ] Confirm worker/startup/status/UI/docs are browser-only.
- [ ] Record exact source revision, KBS pin, known validation obligations and rollback source commit.
- [ ] Only then enter Phase 3: tests/build/EXE/Stable validation.

## Self-Review

- Spec coverage: the owner directive supersedes the older extension-fallback/FBR-6-optional model. Every extension transport dependency now has an explicit removal task.
- Type consistency: `FlowClient` remains the business API; `BrowserFlowBackend` is the sole transport implementation.
- Safety: paid idempotency/reconciliation constraints are preserved and remain independently gated.
- Validation separation: no task above authorizes local testing, EXE launch or Stable mutation until Task 9 source closure.
- Scope: dashboard event WebSocket may remain if it is independent of the Flow extension transport; only Flow extension transport is removed.
