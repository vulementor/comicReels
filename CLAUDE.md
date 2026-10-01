# Flow Kit

Base URL: `http://127.0.0.1:8100`

## Pre-flight

```bash
curl -s http://127.0.0.1:8100/health
# Require:
#   "backend_ready": true
#   "browser_session_ready": true
#   "authentication": "authenticated"
#   "lease_held": true

curl -s http://127.0.0.1:8100/api/flow/backend-status
# "paid_dispatch_enabled" and "reconciliation_required" are separate state.
```

FlowKit uses the existing persistent signed-in Flow browser profile bound by
`COMICREELS_FLOW_PROFILE_CONFIG` (or the default local config path). Do not
clear cookies/storage, sign out, create a replacement profile, or copy profile
credentials into the repository.

## Browser-only transport status

The Chrome-extension/WebSocket Flow RPC bridge is retired. `FlowClient` uses
`BrowserFlowBackend` only, backed by the persistent signed-in
`flow.google.com` profile and the pinned `kabin_browser_semantic` dependency.

This remains a transport refactor, not a creative/scenario rewrite. Project/story
creation, scene chains, transition prompts, creative mix, pipeline/resume,
review/regen, Gallery/Logs/Guide/Settings, TTS/concat/branding and related
`/fk-*` skills remain canonical.

Browser readiness is not paid authorization. Normal source startup keeps paid
dispatch locked. Unknown paid outcomes and `RECONCILIATION_REQUIRED` are
non-retryable until explicitly reconciled. The `/ws/dashboard` socket is an
independent dashboard event channel, not Flow transport.

Architecture: `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`
Current cutover plan: `docs/superpowers/plans/2026-10-01-flow-browser-only-cutover.md`
Current state: `docs/comicreels/CHECKPOINTS.md`

## How to work

- Always use `/fk-*` skills — all rules and workflows live inside each skill
- Never write scripts to loop API calls — use `POST /api/requests/batch`
- `media_id` is always UUID format (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`), never `CAMS...` strings
- **On any pipeline error** (request `FAILED`, stuck `PROCESSING`, `BROWSER_NOT_READY`, `PROFILE_*`, `RECONCILIATION_REQUIRED`, HTTP 4xx/5xx from `:8100`, YouTube `HttpError`, or Flow-native safety/quota/entity errors): invoke `/fk-doctor` before guessing a fix
- Treat `paid_dispatch_enabled` as a separate authorization gate. Browser/session readiness never grants paid generation.

## Since Flow moved (September 2026)

Flow lives at `flow.google.com` and signs every call in the page. Consequences
that change how you work:

- **Projects are not created by Flow Kit any more.** Make one in the Flow UI and
  pin its uuid as `FLOW_PROJECT_ID`, or pass `flow_project_id` to `POST /api/projects`.
- **Three capabilities are unported**, all on the Veo path, because their
  payloads were never captured: **video** upscale (not image export, which
  works), Veo r2v, and Veo start+end-frame chaining. They fail with
  `UNSUPPORTED_ON_BATCH_API` rather than silently producing the wrong thing.
  Omni covers frame, first+last and reference modes — use
  `model_family=omni_flash`. `FLOW_ALLOW_DEGRADED=1` drops Veo chaining and r2v
  to plain i2v; video upscale has no fallback. See `docs/CAPTURE.md`.
- **A poll saying "Media not found." is not a failure.** Finished jobs report it.

## Skills

| Skill | When to use |
|-------|-------------|
| `/fk-create-project` | New project with entities + scenes |
| `/fk-research` | Fact-check before scripting |
| `/fk-gen-refs` | Generate reference images for entities |
| `/fk-gen-images` | Generate scene images |
| `/fk-gen-videos` | Generate scene videos |
| `/fk-gen-chain-videos` | Videos with scene chaining transitions |
| `/fk-review-video` | Review video quality before upscale |
| `/fk-review-board` | Visual scene review board for feedback |
| `/fk-concat` | Download + concat final video |
| `/fk-concat-fit-narrator` | Concat trimmed to narrator duration |
| `/fk-gen-narrator` | Generate narrator text + TTS |
| `/fk-gen-text-overlays` | Generate text overlays from narrator text |
| `/fk-gen-tts-template` | Create voice template for narration |
| `/fk-gen-music` | Generate music via Suno |
| `/fk-creative-mix` | Creative video mixing techniques |
| `/fk-pipeline` | Full pipeline orchestration |
| `/fk-monitor` | Monitor running pipeline |
| `/fk-status` | Project status dashboard |
| `/fk-switch-project` | Switch active project |
| `/fk-fix-uuids` | Fix non-UUID media_ids |
| `/fk-refresh-urls` | Refresh expired signed media URLs |
| `/fk-doctor` | Diagnose Flow/browser-session/reconciliation/worker/YT errors |
| `/fk-add-material` | Set image material style |
| `/fk-change-model` | Change video/image model |
| `/fk-change-provider` | View & switch the AI CLI, model and effort per role (claude/agy/codex) |
| `/fk-insert-scene` | Insert scenes into chain |
| `/fk-upload-image` | Upload local image to get media_id |
| `/fk-thumbnail` | Generate YouTube thumbnails |
| `/fk-brand-logo` | Apply channel logo watermark |
| `/fk-youtube-seo` | Generate YouTube metadata |
| `/fk-youtube-upload` | Upload to YouTube |
| `/fk-camera-guide` | Cinematic camera reference |
| `/fk-thumbnail-guide` | Thumbnail design reference |
| `/fk-import-voice` | Import existing voice template |
| `/fk-dashboard` | Live statusline setup |
