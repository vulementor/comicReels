# Thỏ Remix stable application

## Owner scope

Build a stable Windows EXE, following the existing KDVT deployment/controller pattern, with
FlowKit production and KRP publication to Facebook ThoRemixOfficial, TikTok
@thoremixofficial and YouTube @ThoRemixOfficial. Each day at 11:00 and 18:30 Vietnam time,
choose one unused random image from D:\Thỏ Remix. Keep a complete package at
D:\Thỏ Remix\video\<source-stem>\: original, generated child images, final video named after
the source, metadata and independent platform receipts. Move the input original only after
the video is complete and validated. Do not overwrite collisions or lose an input on failure.

Prioritize the stable controller, durable queue and publication before enhancing production.
The future zero-credit fallback is ChatGPT Web direct AAC synthesis with distinct resolved
provider voice IDs by character, followed by frame assembly. That fallback is explicitly
deferred. For now insufficient or unknown Flow credit blocks new generation truthfully.

Affiliate is required. Owner permits reuse of the GRR or KDVT Affiliate profile; use KDVT's
configured Shopee Affiliate path without copying it. Autonomously select high commission
percentage, low price and observed strong sales. Default configurable bounds: price <=200000
VND and sold >=1000, then rank verified percentage descending, price ascending, sold descending.
These are internal selection criteria, not claims of market-wide best price or trending status.
All AI must use gpt_fullproxy. Deterministic SDK/CLI toolkit, never an agent loop.
Preserve the spoken script and no-bubble requirement.

## Execution policy update — 2026-09-30

This plan uses two separate passes and the first pass has priority:

1. **Development pass:** implement every remaining code/integration item on GitHub until the
   complete Thỏ Remix development plan is 100% coded. Do not interleave tests, Stable rebuilds,
   runtime inspection, launch checks, or fix loops between coding phases.
2. **Validation pass:** only after development completion, execute Task 5 and all accumulated
   regression/build/runtime/live checks. Defects found there are fixed back on GitHub.
3. **Remote Desktop Commander is prohibited for this workflow at every stage**, including
   coding, testing, rebuilding, launching, inspecting, or repairing.
4. Development checkpoints describe code scope only. They are not runtime PASS claims.

This policy overrides older local-first or per-checkpoint-test instructions where they conflict.

## Design and global constraints

- Source belongs in canonical ComicReels, under agent/thoremix; existing unfinished FBR-2
  changes remain intact. This application work does not close or deploy the FBR-2 backend.
- Stable root D:\StableApp\ThoRemix, EXE ThoRemix.exe. Source/runtime/config/data/logs separate.
  Do not modify existing GithubReview/KabinDrama apps or the independent platform playbook.
- Follow KDVT's small native EXE plus Python desktop/controller packaging. GRR is a reference,
  not a runtime dependency (its product contract excludes KRP).
- KRP is the sole social SDK/effect journal. Social profile, Flow profile, ChatGPT profile and
  affiliate profile must remain separate. No credential export, profile copying or cookies in logs.
- Desktop is a controller, Windows Scheduled Tasks own the two daily one-shot runs.
  Single-runner OS lock and SQLite slot/source dedupe; no duplicate scheduler loop.
- Persist intent before external effects; unknown generation/publication is reconciled, never
  retried with a fresh identity. Each platform/comment has its own stable idempotency key.
- No fake approvals or success states. Existing API/SDK verification and actual media decode
  are required; login/affiliate absence remains visible and blocks dependent publishing.
- Standalone app and public SDK/CLI use the same state/core. No production dependence on skills.
- No unrelated repo changes, commits or merges by subagents; root owns integration/release.

## Task 1: Durable application core (root)

Config, SQLite slots/assets/jobs/platform projections, source scan/random unused reservation,
atomic package finalization with original move, media validation, one-runner lock, CLI and
typed producer/publisher contracts. Tests cover restart, duplicates, collisions, failure and
unchanged-source hashes. Use source_sha256 as immutable identity, not filename alone.

## Task 2: KRP publication/auth adapter (delegated)

Create agent/thoremix/publishing.py and tests/unit/test_thoremix_publishing.py only.
Public API:
  publish_package(package_dir: Path, *, krp_home: Path, profile: str='thoremix-social',
                  visible: bool=False, client_factory=None) -> dict
  auth_status(*, krp_home: Path, profile: str='thoremix-social') -> dict
  login(*, krp_home: Path, profile: str='thoremix-social') -> None

Input package.json schema_version=1 with source_sha256, video_path (absolute), video_sha256,
title, caption, description, affiliate={state:'verified',url,disclosure,comment},
qa={release_ready:true}. Validate actual video hash, target bindings and affiliate URL/disclosure
before effects. The app has standing authority for the three exact named targets. Do not infer
login/account from the URLs. Keep actor verification in KRP; configure each platform explicitly.
Facebook canonical_url=https://www.facebook.com/ThoRemixOfficial; TikTok handle=thoremixofficial,
canonical_url=https://www.tiktok.com/@thoremixofficial; YouTube handle=ThoRemixOfficial,
canonical_url=https://www.youtube.com/@ThoRemixOfficial. No guessed display names needed.

Use KRPClient and isolated EffectJournal. KRP_HOME controls profile/artifact paths; caller runs
in one-shot process, do not race environment changes in threads. Sequential FB/TikTok/YT,
continuing independent destinations when one needs login. KRP owns journal. Frozen package
content forms stable identity; existing journal effects are inspected/reconciled using same ID,
not resubmitted. Frozen affiliate is a separate comment on confirmed publication; comment
failure never repeats upload. Description/caption also carry disclosure as appropriate. Persist
atomic publication.json safe projections after each effect (no credentials). Return per-platform
status/permalink plus overall complete only if all required publications/comments confirmed.
Respect confirmed effects from journal even if local projection write was interrupted.
Native KRP login context should open only Facebook, TikTok Studio and YouTube Studio and stay
open until user closes browser (desktop runs it as child), no terminal input dependency.

Read current KRP SDK/config/journal code in sibling kabin_reel_poster; do not edit that repo.
Use injected clients for offline tests. Test duplicate run, unknown-state reconcile, changed
video rejection, partial-channel failure, comment independence, auth/actor mapping.

## Task 3: Desktop and stable packaging (root)

Tk desktop with status/history, input/output folder actions, KRP login, settings, run once,
publish prepared package, pause/resume and scheduler controls. Native EXE launcher and owned
Scheduled Tasks with exact 11:00/18:30 local Vietnam slots. No silent terminal prompts.
Config does not get overwritten on upgrade. Build and launch actual EXE, verify profile and
commands; UI must remain responsive while subprocesses run.

## Task 4: FlowKit producer integration (root)

Reuse ComicReels/GPTFP analysis/image batch and FlowKit production contracts; represent one
story clip explicitly rather than generating three ten-second clips. Credit/receipt/artifact
checks remain independent. Freeze original/child frames, exact dialogue and request intent.
Production gaps remain blocked with concrete diagnostics instead of pretending ready video.
Do not add the frame/audio fallback in this phase. Permit verified ready-video import so the
publication/controller can be exercised before remaining generation enhancement.

## Task 5: Review and deployment verification

Independent code/spec review, meaningful unit tests, stable bundle/import/EXE smoke, scheduler
inspection and one profile login/readiness pass. Real publication only with a verified package,
required affiliate and live expected actor. User already authorized these effects; do not ask
for redundant permission. If login or source data is missing, finish independent implementation
and identify the exact missing input without falsely claiming live publication complete.
