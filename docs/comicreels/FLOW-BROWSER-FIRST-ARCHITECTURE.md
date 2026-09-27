# Flow Browser-First Refactor Architecture

Status: **OWNER APPROVED — DESIGN BASELINE**  
Date: 2026-09-27  
Scope: ComicReels / FlowKit transport refactor only.

## 1. Goal

Replace the Chrome-extension/WebSocket Flow transport with a browser-profile-first backend that
opens and works through a signed-in `https://flow.google.com/` browser session, while preserving
FlowKit's creative, scenario, scene, prompt, review, pipeline, and orchestration capabilities.

The browser integration must reuse `kabin_browser_semantic` (KBS) for browser semantics,
perception, deterministic target resolution, network observation, body capture, authenticated
request replay, settling, and later recipe/discovery reuse.

This is a **transport/runtime refactor**, not a rewrite of FlowKit's creative product.

## 2. Non-negotiable preservation contract

The following FlowKit capabilities remain canonical and MUST NOT be removed or simplified as part
of the browser refactor:

- project/story/entity creation semantics in `skills/fk-create-project.md`;
- scene-chain rules, ROOT/CONTINUATION semantics, transition prompts, dialogue and timing rules;
- `skills/fk-creative-mix.md` creative techniques and scenario composition;
- `skills/fk-pipeline.md` stage orchestration, resume semantics, review gates, concat/TTS/branding;
- `skills/fk-gen-videos.md` video-generation and chain-cascade semantics;
- existing project/video/scene/entity database model unless a checkpoint explicitly proves a
  migration is necessary;
- review, regeneration, idempotency, receipt persistence, and downstream invalidation rules;
- existing FlowKit UI, Gallery, Logs, Guide, Settings, skills, and non-Flow integrations.

Transport-specific code may change. Creative scenario logic does not disappear with the extension.

## 3. Ownership boundaries

```text
ComicReels / FlowKit
  owns workflow, creative scenarios, project state, idempotency,
  paid-effect gates, receipts, retries, review and recovery
        ↓
FlowBrowserBackend
  owns Flow-specific browser workflow and Flow-specific selectors/recipes
        ↓
FlowBrowserSessionProvider
  owns one persistent signed-in browser profile lease and page lifecycle
        ↓
kabin_browser_semantic
  owns generic browser perception, semantics, resolver, network observation,
  body capture, authenticated replay, settling and recipe machinery
        ↓
flow.google.com
```

KBS must remain application-agnostic. Flow-specific selectors, labels, RPC meanings, media/project
rules and generation semantics belong in ComicReels/FlowKit adapters, never KBS core.

## 4. Browser/profile model

The target runtime uses one persistent Flow profile.

Required invariants:

1. Never create a temporary replacement profile when the canonical Flow profile exists.
2. Never clear cookies/storage, sign out, or delete the profile as part of normal recovery.
3. Acquire an explicit profile lease before opening the persistent browser context.
4. Only the lease owner may close the context it opened.
5. Do not serialize cookies, auth headers, CSRF tokens or other live credentials into ComicReels
   state. KBS `BrowserSession` retains live handles only.
6. Browser recovery may reopen `flow.google.com` using the same profile after a clean lease
   transition; it must not silently switch identity/profile.
7. The local profile path is configuration, not repository data, and must not be committed.
8. A checkpoint must prove session continuity before paid generation is allowed.

Reference implementation direction already exists in the Kabin workspace:
persistent Camoufox context + `user_data_dir` + profile lock, then
`BrowserSession.from_page(page)`.

## 5. Runtime strategy

Browser-first does not mean click-only automation.

Preferred strategy for each Flow capability:

```text
known validated browser-authenticated recipe
  → deterministic browser action when required
  → network observation / body capture for discovery
  → authenticated replay inside the browser session
  → semantic resolver when UI state/target is needed
  → bounded visual/AI repair only if later explicitly approved
```

The target is to keep Flow authentication/session/captcha inside the real browser lifecycle while
using the least fragile reliable execution channel.

## 6. Transport interface

ComicReels/FlowKit should depend on a stable backend protocol rather than extension details.

Target capability surface:

```python
class FlowBackend(Protocol):
    def health(...) -> FlowHealth: ...
    def open_or_resume_project(...) -> FlowProject: ...
    def create_project(...) -> FlowProject: ...
    def upload_image(...) -> FlowMedia: ...
    def generate_image(...) -> FlowSubmission: ...
    def generate_video_refs(...) -> FlowSubmission: ...
    def poll_submission(...) -> FlowPollResult: ...
    def refresh_media(...) -> FlowMedia: ...
    def download_media(...) -> FlowDownload: ...
```

The current extension transport may implement the same interface temporarily as a fallback during
migration. No FlowKit creative skill should need to know which transport is active.

## 7. Paid-effect and receipt rules

Generation remains a consequential external effect.

- No automatic retry after timeout, disconnect, or unknown receipt.
- Persist intent/idempotency state before submission.
- Persist provider receipt/error before changing workflow state.
- Structured provider rejection with proof of non-acceptance may become `FAILED`.
- Unknown outcome remains `SUBMISSION_UNKNOWN` until reconciled.
- Browser recovery must reconcile visible/network state before any paid resend.
- Changing transport must not weaken existing idempotency or approval gates.
- Never use repeated paid calls as a transport diagnostic.

## 8. Session continuity evidence

Every live browser checkpoint must record only sanitized evidence:

- source commit;
- KBS commit/pin;
- browser backend kind;
- profile logical name (not secrets);
- whether the same signed-in Flow identity/session remained authenticated;
- Flow page URL host;
- project id(s) intentionally used;
- active profile lease state;
- capability/readiness summary;
- test/live result;
- rollback point.

Never store cookies, tokens, raw auth headers, local browser databases or profile archives in Git.

## 9. Extension retirement policy

The extension is **not deleted at the start**.

- FBR-0 through FBR-2: extension remains the known fallback; browser backend is shadow/read-only or
  capability-limited.
- FBR-3: browser backend may perform one explicitly approved paid single-shot test.
- FBR-4: parity is proven for the required ComicReels/FlowKit capability matrix.
- FBR-5: owner explicitly approves browser backend as default.
- Only after FBR-5 may extension/WebSocket transport code be removed in a separate cleanup change.
- Rollback must remain possible until the cleanup checkpoint is accepted.

## 10. FlowKit creative preservation matrix

| Capability | During refactor | After cutover |
|---|---|---|
| Story/entity creation | unchanged | unchanged |
| Scene creation and chains | unchanged | unchanged |
| Creative mix/scenario rules | unchanged | unchanged |
| Prompt/timing/dialogue rules | unchanged | unchanged |
| Review/regen loops | unchanged | unchanged |
| Pipeline/resume | unchanged | unchanged |
| Gallery/Logs/Guide/Settings | unchanged | unchanged |
| TTS/concat/branding/SEO/YT | unchanged | unchanged |
| Flow transport | extension fallback + browser shadow | browser-first |
| Extension/WS bridge | retained | removable only after FBR-5 |

## 11. Stop conditions

Stop the current checkpoint and do not advance when:

- profile identity/session is lost or a new unintended profile appears;
- KBS/browser integration requires storing credentials outside the browser profile;
- browser backend produces an uncertain paid submission;
- Flow returns an anti-abuse/safety/account block;
- creative FlowKit behavior regresses;
- required regression suite fails;
- rollback cannot be demonstrated.

## 12. Authority and continuity

Execution authority:
- this document defines the browser-first architecture;
- `docs/superpowers/plans/2026-09-27-flow-browser-refactor.md` defines checkpoint execution;
- `docs/comicreels/CHECKPOINTS.md` records current accepted state;
- generated `AGENTS.md` carries operational invariants for agents;
- FlowKit creative skills remain their own source of truth.

No conversation-only decision is considered durable until recorded in one of these repository
documents.
