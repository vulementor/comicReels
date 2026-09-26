# ComicReels FlowKit completion plan

> Implementation: execute inline using executing-plans; request one independent final code review.

**Goal:** Complete the already approved ComicReels feature on top of FlowKit.
**Architecture:** Keep FlowKit navigation, APIs, transport, throttling and browser extension intact. ComicReels owns image approval, exact dialogue, job persistence and review, and delegates uploads/generation/polling to FlowKit.
**Stack:** FastAPI, SQLite, React/TypeScript, existing FlowKit.
**Spec:** `docs/comicreels/PRODUCT.md`, superseded where stated by the user's latest instructions below.

## Current instructions

- FlowKit is the core; ComicReels remains at `/comicreels`.
- Select exactly three approved images and one component script; generate dialogue within the video.
- ComicReels preset: Omni Flash, 10 seconds, 360p, exactly one variant. Preserve FlowKit's other modes.
- Reuse the connected Chrome/profile. Do not launch another browser or request another login.
- Finish and push code first. Run local tests on Remote Desktop Commander only after the user's explicit confirmation. Do not merge.
- Tests may be authored now; local execution is deferred. GitHub Actions results must be reported separately from local/live verification.

## Review focus

Concurrent clicks must not create duplicate paid jobs; a timeout after submit must preserve uncertainty.
An image changed after approval must block submission; the script's source panel must be among references.
Legacy FlowKit operation receipts and workflow receipts must both download actual video, never thumbnails.
Regeneration must clear the old review and video; a processing or uncertain job cannot be forced again.
Leaving/reopening ComicReels must recover saved images and project state without regenerating them.

## Task 1: Status, preset and exact transcript

- [x] Add regression cases for `/status`, preset validation, three unique references and long verbatim dialogue splitting.
- [x] Delegate status/preflight to FlowKit and preserve its defaults outside ComicReels.
- [x] Lock ComicReels generation routes to the approved preset and map the source panel to its reference.

## Task 2: Durable video lifecycle

- [x] Add regression cases using an isolated real SQLite store for concurrent reservation, retries, changed images, ambiguous submission, poll/download and preview.
- [x] Atomically reserve submissions before network calls; retain receipts before response validation; never auto-retry a paid submit.
- [x] Read FlowKit's video URL/status shapes; persist completion/failure and expose a video asset route.

## Task 3: Usable UI and preserved images

- [x] Keep all existing FlowKit routes and features; add no new browser launcher.
- [x] Restore the last saved ComicReels project; show source/clean previews and image downloads.
- [x] Show the exact three-reference choice, submit states, polling, video playback/download, reject/retry, and review/assembly controls.
- [x] Keep partial image-generation results visible when a later panel fails.

## Task 4: Review and GitHub handoff

- [x] Review the diff and regression cases without running local tests.
- [x] Update current checkpoint/test plan; retain historical results as historical only.
- [ ] Push to the existing PR #3 branch, inspect GitHub CI if available, report the commit and remaining local gate.

## Execution record

- Baseline: `564129916d90ff30889d5d108754eaa1c665b551`.
- User's no-local-test instruction overrides TDD/skill execution steps. No local PASS claims may be made for this revision.

- Independent static review found mutation/late-poll/stale-review/manual-registration races; addressed with database guards and conditional updates. Review also found workflow receipt validation/test gaps; those are addressed in the same pass.
- No runtime results are inferred from this review. Local tests remain deferred by user instruction.
