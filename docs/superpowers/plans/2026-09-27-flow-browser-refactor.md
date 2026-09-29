# Flow Browser-First Refactor Execution Plan

Status: **OWNER APPROVED — CHECKPOINTED EXECUTION**
Date: 2026-09-27
Architecture authority: `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`

## Global execution rules

These rules apply to every checkpoint:

1. **LOCAL-SOURCE-FIRST (owner update 27/09).** Implement/debug/test directly in the canonical local source checkout on VULE-PC, on a checkpoint branch. GitHub is durable checkpoint history; do not push every small fix.
2. **Source-to-runtime validation.** Deploy/sync the actual local source through supported tooling, then run the checkpoint's bounded live validation. Dirty local source is allowed; regression must cover those exact bytes.
3. **No runtime-only fixes.** AppData runtime is a deployment target, never source development. Fix source and deploy again.
4. **One checkpoint at a time.** Do not mix FBR scopes.
5. **Regression before live.** Unit/integration/build/lint must pass before browser live validation.
6. **Sanitized evidence only.** Never commit cookies, tokens, browser profile contents or raw auth.
7. **No paid generation as diagnostics.** Paid calls exist only at the explicit paid checkpoint.
8. **No uncertain resend.** Unknown paid outcome must be reconciled before any retry.
9. **Preserve FlowKit creative capabilities.** Do not remove or rewrite scenario/creative/pipeline skills merely because transport changes.
10. **Owner confirmation required.** After a coherent checkpoint passes, update docs, commit and push its branch, review the diff, and wait for explicit owner confirmation before merge. Sync and verify the exact merged revision, close out, then stop for separate permission before the next checkpoint. Never merge BLOCKED.

## Checkpoint status vocabulary

- `PLANNED` — scope documented, no code accepted.
- `IN_PROGRESS` — local implementation exists but checkpoint not yet validated; a GitHub push is not required for local iteration.
- `LOCAL_PASS` — regression + VULE-PC non-paid live test pass.
- `LIVE_PASS` — required external live behavior is proven.
- `BLOCKED` — stop condition hit; do not advance.
- `ACCEPTED` — owner explicitly accepts checkpoint.
- `ROLLED_BACK` — checkpoint reverted to recorded rollback revision.

Each closeout record must include:
- checkpoint id;
- source commit;
- KBS pin/commit;
- runtime backend kind;
- profile logical name;
- tests executed;
- live evidence;
- known gaps;
- rollback revision;
- next checkpoint;
- owner decision.

---

## FBR-0 — Profile/session bootstrap

### Goal

Open `flow.google.com` using one persistent signed-in Flow browser profile under an explicit lease,
wrap the existing page with `kabin_browser_semantic.BrowserSession`, and prove session continuity.

### Allowed changes

- add browser session provider abstraction;
- add Flow profile configuration by logical name/path;
- add profile lease/lock;
- add KBS dependency pin;
- add read-only health/session diagnostics;
- add browser backend skeleton with no generation effects.

### Forbidden changes

- no removal of extension/WS code;
- no paid Flow generation;
- no rewrite of FlowKit creative skills;
- no creation of temporary replacement profiles;
- no copying cookies/auth into app state.

### Required tests

- session provider unit tests;
- profile lock conflict test;
- same-profile reopen test;
- KBS `BrowserSession.from_page` contract test;
- full current ComicReels regression;
- frontend build/lint.

### VULE-PC live evidence

- launch the canonical Flow profile;
- authenticated `flow.google.com` page loads;
- KBS semantic snapshot/surface succeeds;
- close and reopen through controlled lease;
- authentication survives;
- profile identity/path has not changed.

### Acceptance gate

`FBR-0 LOCAL_PASS` + owner confirms before FBR-1.

### Rollback

Switch backend selection to current extension transport; no database migration required.

---

## FBR-1 — Read-only KBS discovery

### Goal

Map Flow's current browser/network behavior without paid effects.

### Allowed changes

- KBS NetworkObserver integration;
- bounded body capture for selected Flow requests;
- sanitized request/response shape evidence;
- Flow-specific capability map/recipes in ComicReels/FlowKit adapter;
- read-only project/media inspection.

### Required capability evidence

- identify project-list/read behavior;
- identify media read/refresh behavior;
- identify project creation request shape if safely observable;
- identify upload request shape without submitting generation;
- classify what can use authenticated replay vs semantic UI.

### Required tests

- no credential persistence;
- body redaction/budget tests;
- stale recipe invalidation tests;
- read-only replay tests;
- full regression.

### Stop conditions

Any read-only discovery unexpectedly triggers a paid generation or destructive mutation.

### Acceptance gate

`FBR-1 LOCAL_PASS` + owner confirms before FBR-2.

---

## FBR-2 — Browser-native non-paid Flow backend parity

### Goal

Implement browser-native Flow operations that do not consume generation credit and prove parity with
the extension path where applicable.

### Target operations

- health/readiness;
- create/open/resume project;
- upload image;
- inspect/refresh media;
- project/media polling/lookup;
- browser-side reconciliation.

### Key requirement

Backend selection is behind a stable `FlowBackend` boundary. FlowKit business/creative code does
not branch on extension internals.

### Required tests

- contract tests run against extension fake and browser backend fake;
- idempotent project/session reuse;
- upload media UUID validation;
- restart/resume persistence;
- extension fallback still works;
- full regression.

### VULE-PC live evidence

Use the same persistent Flow profile. Create or use a disposable Flow **project only**, upload a
non-sensitive test image, verify media read/refresh, then close/reopen and prove continuity.

### Acceptance gate

`FBR-2 LIVE_PASS` + owner confirms before FBR-3.

---

## FBR-3 — One paid single-shot browser generation

### Goal

Prove one browser-native paid generation path with full receipt/idempotency safety.

### Preconditions

- FBR-0, FBR-1, FBR-2 are ACCEPTED;
- no active Google unusual-activity cooldown/block;
- browser session continuity is healthy;
- exact request cost/preset is confirmed;
- owner explicitly authorizes this paid checkpoint.

### Scope

Exactly one shot, one variant, approved preset. No batch.

### Rules

- persist intent before submission;
- capture browser/network receipt;
- reconcile before retry;
- no automatic resend on timeout/unknown;
- structured explicit rejection may become FAILED;
- anti-abuse response is terminal for this checkpoint.

### Acceptance gate

One job is submitted, polled, and reconciled to a final state with a durable receipt.
Owner confirms before FBR-4.

---

## FBR-4 — ComicReels/FlowKit parity matrix

### Goal

Prove that moving transport does not remove FlowKit product behavior.

### Mandatory preserved scenarios

- project/story/entity creation;
- ROOT/CONTINUATION chains;
- transition prompts;
- multi-reference video flow used by ComicReels;
- creative mix scenarios;
- pipeline resume from partial state;
- video review and selective regeneration;
- gallery/log/status visibility;
- media URL refresh/download;
- TTS/concat/branding remain unaffected.

### Test approach

For every scenario, compare business-level inputs/state transitions/output records between the old
extension backend and browser backend where safe. Paid parity tests must be minimal and explicitly
approved.

### Acceptance gate

Required matrix passes or documented exceptions are owner-accepted.
Owner confirms before FBR-5.

---

## FBR-5 — Default cutover

### Goal

Make browser-first backend the default while retaining an immediate rollback switch.

### Required changes

- browser backend becomes default;
- extension backend remains selectable fallback;
- health/preflight docs stop requiring extension when browser backend is active;
- UI/status reports selected transport explicitly;
- migration docs and operator instructions are updated.

### Required validation

- fresh restart on VULE-PC;
- same persistent Flow profile;
- project resume;
- one approved end-to-end ComicReels run to final video;
- no creative-skill regression;
- rollback switch demonstrated.

### Acceptance gate

Owner explicitly approves browser-first as production default.

---

## FBR-6 — Extension cleanup (separate optional checkpoint)

### Goal

Remove extension/WebSocket transport only after FBR-5 has been stable and owner requests cleanup.

### Important

This checkpoint is intentionally separate. FBR-5 success does **not** automatically authorize code
deletion.

Potential removals after approval:
- Chrome extension bridge;
- WS transport glue used only by the extension;
- stale-tab/revive/content-script transport paths;
- extension-specific health checks.

Do not remove shared FlowKit creative/orchestration code.

---

## Continuity / handoff protocol

At the end of every work session:

1. update `docs/comicreels/CHECKPOINTS.md`;
2. record exact GitHub commit(s);
3. record current FBR checkpoint and status;
4. record VULE-PC runtime revision;
5. record KBS pin;
6. record browser backend selection;
7. state whether Flow profile session is healthy/leased/released;
8. state whether any paid job is pending/unknown;
9. state the exact next command/test allowed;
10. state explicit forbidden actions for the next session.

A future conversation must be able to continue from repository state without relying on chat memory.
