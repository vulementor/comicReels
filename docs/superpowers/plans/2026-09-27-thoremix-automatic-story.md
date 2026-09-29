# Finish Thỏ Remix automatic story production

Owner: continue to completion, using the successful one-source live ComicReels flow.
One source image = one story = one native AI video. No concatenation across sources.
All AI requests use GPT FullProxy. Keep toolkit state/quotas/retries deterministic.

## Execution ledger

1. [x] Repair canonical GPT FullProxy compatibility needed by attachment analysis and image batches.
   Combine the already implemented batch collector with current text recovery without replacing
   unrelated SDK changes; recognize modern semantic assistant roots and Vietnamese stop controls.
   Persist exact per-stage intents, provider IDs and complete local artifact hashes.
2. [x] Add a finite ComicReels whole-story runner with injectable production adapters.
   Stages: import/reconcile source, analyze, generate all child images, image QA, Flow upload,
   native one-clip generation/reconciliation, original-video QA, highest download, audio QA,
   GPTFP publication copy and verified affiliate, frozen package promotion.
   Known content failures skip source; uncertain remote effects stop and reconcile, never resend.
3. [x] Implement observed Camoufox operations in a product-specific adapter. Keep the existing
   FBR backend selection unchanged; this is the owner's expressly requested story workflow.
   Persist exact native submit before waiting and require complete bytes before releasing owner.
4. [x] Wire the stable producer and readiness to real installed capabilities. Add bounded
   reconciliation of interrupted work. Preserve successful/day quota, FIFO and posting dedupe.
5. [x] Run regression, fresh final review, repair findings, build/install from canonical source.
   Run an actual unattended source through the installed producer; verify package, app status,
   task definitions and no duplicate effects on resume. Enable the owner's monitored production
   after installed pre-submit and image-quality gates pass; do not claim completion until an
   actual automatic package has passed every remaining stage.
6. [x] Update checkpoint and give exact artifact/status, with any genuine remaining blocker.

Ruling: Earlier plan's no-paid-test scope was for the previous configuration-only task.
The owner has since repeatedly authorized real production and now requested full completion.
No permission is re-requested for necessary implementation, generation, app deployment or
the previously authorized publishing workflow. FBR checkpoint merge/cutover remains separate.

Current baseline: full suite977 passed, final affected43+JS4 passed; latest KBS source102
compatibility tests passed. Canonical ComicReels has preserved dirty FBR/ThỏRemix work.
Prior real story is `7edf50707f5746c0b3f8b6f2b69af913`, native media
`e0fc2531-f0b0-4c61-bfad-5fd4f8f10c5d`, packaged and waiting publication.

Initial finding: automatic producer is a stub. Canonical GPTFP has modern text recovery but
the earlier ComicReels image-batch feature is on another branch. Installed GPTFP batch branch
misses modern semantic assistant roots and Vietnamese Ngừng generation control. Fix source,
not AppData runtime. Both physical profiles stay under their existing exclusive leases.

Implementation checkpoint, 21:40 Asia/Saigon:
- Finite StageJournal + StoryPipeline + native FlowStoryBrowser and GPTFP-backed operations implemented.
- Final independent review fixed attachment binding, positive gallery membership, route drift,
  paid variant/model/aspect validation, download identity/promotion recovery, quota date and
  proven pre-submit BLOCKED versus uncertain side effects. Reviewer reports no remaining important
  code finding; live gallery and derivative acceptance remain necessary.
- GPTFP 549 tests passed before the final tool-activation helpers were brought from the existing
  image-attachments feature branch. Those helpers' 30 focused tests pass. ComicReels full run:
  1000 passed, two fixture/deployment failures addressed; final full rerun still due.
- Actual production job 333a07dd97b74806b26c7368bf83ea2f: source analysis completed, exact convo
  6ab9289a-8cc4-83ec-849c-e8a9f42ed4ca, assistant 0a0f1f7f-0658-4b57-96fa-b57b3f3a533d.
  Source has two panels (tattoo rabbit/hippo). Image tool activation blocked before prompt;
  preserve receipts, resume this same source after canonical SDK tool guard repair. No Flow charge.
- App settings temporarily disabled for upgrade; previous enabled=true/ahead/5 saved in
  D:/StableApp/ThoRemix/data/automatic-story-controls-before.json. Restore after acceptance.
- Build stages entire ComicReels helpers, GPTFP and KBS wheels, direct dependencies. First staged
  validation caught missing aiosqlite before promotion; fixed source build and rerunning.
- Both canonical refs fetched and verified: ComicReels 4ddd23f equals tracked feature remote;
  KBS b1a78e1 equals origin/main. No FBR default-backend cutover or merge claimed.

Installed acceptance, 22:11 Asia/Saigon:
- Canonical regression: 1006 ComicReels tests passed; latest GPTFP 562 passed / 49 skipped.
  Additional changed queue/dashboard tests: 68 passed under the required UTF-8 runtime;
  story/image-batch tests: 13 passed. No synthetic test is counted as a production clip.
- Actual image request submitted once at conversation `6ab92d99-c414-83ec-a742-07169b01a228`.
  New ChatGPT UI places only the selected preview in generated-image-gallery; full ordered
  batch is in sibling semantic group `Hình ảnh đã tạo`. SDK now reads every numbered thumbnail
  in that positive group, including hidden thumbnails, never unrelated same-sized images.
  Read-only recovery downloaded both original full-resolution blobs. First hash matches the
  earlier captured preview. Audit: production/333a.../gallery-collector-repair.json.
- Multi-attachment QA exposed native duplicate renaming after upload: source(4).jfif,
  scene-01(2).png. SDK matches exact original stem/extension plus native numeric suffix,
  requires a unique remove control inside current composer, excludes historical messages,
  and waits for upload progress to finish. Pre-submit failures remain safely resumable.
- New image prompt forbids invented props/furniture/body extensions; portrait padding uses
  existing flat background. Existing two-image batch is preserved for independent QA.
- Stable build promoted with verified imports and preserved prior bundle. Actual installed
  produce-one is again resuming image QA for the same source. Automatic controls remain paused
  until the live runner acceptance progresses; no paid Flow request yet for this source.

Monitored production, 22:13 Asia/Saigon:
- Installed image QA completed in `6ab93203-6778-83ec-b5d4-18c2a5bc4586`, assistant
  `ab166d89-8444-4d1c-9ca4-df70a12607c0`. Both original images were examined. Rejected invented
  lamp/stool/body extension before any Flow payment. Source remains preserved; failed count1.
- Restored owner settings enabled=true / ahead / 5 completed per day. Native EXE started;
  desktop bundle hashes and three task definitions verified. Tray hide/restore, same-instance
  reopen, native menu exit/restart passed with unchanged settings; final app hidden in tray.
- Started installed produce-ahead. It independently skipped source40735... (dialogue too long
  for the current ten-second story) and selected b81c6... without human source selection.
  Scheduled 22:16 dispatch returned busy under the existing runner, so no duplicate producer.
- Final SDK attachment and numbered-thumbnail fixes have no important independent review finding.
  Real automatic MP4 acceptance remains in progress, not inferred from unit/UI test results.

Installed acceptance, 22:30 Asia/Saigon:
- Job c3673... generated and downloaded all three full-resolution children from one source.
  QA rejected newly introduced gradient/shading before paid Flow. Prompt now explicitly
  forbids redrawing/beautification/gradient/new shadows; rejected content is not overridden.
- Shared speech-aware timeline fixes false rejection of 69e2dad5...: intervals 0-4.78,
  4.78-5.77,5.77-8.08,8.08-10 seconds, all20 source words retained. Original failed journal,
  attempt and job preserved in speech-budget-repair.json; cached response reconciled read-only.
- Full ComicReels1008 passed; GPTFP563 passed/49 skipped. Reviewer caught missing project-route
  early URL checkpoint; fixed same-origin canonical parser and17 focused tests passed.
  Reviewer confirmed no remaining important timing/checkpoint finding.
- New stable bundle installed transactionally; previous bundle retained. Restored enabled=true,
  ahead5, started EXE and installed produce-ahead. First full automatic artifact is still pending.

Reliability and background execution, 23:50 Asia/Saigon:
-12 existing frames from4 stories now live in source-named video/<stem>/frames with original
 copies and hash-bound draft.json. Final manifest is promoted atomically last; crash recovery
 keeps drafts intact. GUI list/detail panes resize separately; selected original and3 frames
 were verified in installed screenshot data/verification/desktop.png.
- ChatGPT durable profile pacing90s between starts plus30s rest; failure cooldown60s persists
 across restart, honors pause and does not consume successful/day quota.
- Semantic image QA and exact assistant API JSON recovery repaired false rejection of c3673.
 Original QA journal, source hashes and prior attempt retained in image-review-original-audit.
 Unknown image effect5a6ca remains UNKNOWN in quarantine, no new request for that source.
- Headless Flow generated c3673 once, media7ea36ff9-387d-434a-859e-24918ec5f34c /
 workflow10f7a6eb-510a-4721-a55f-cc5321373a21. Downloaded original.mp4 SHA256
 5c996a4e8cec7ef39f85170f310f9ec3f11864ad6645ec670dbd433800f07709,360x640,10.005s/full decode.
 Exact native editor route and newline-normalized download menu repaired read-only recovery;
 no paid resend. Native720p is the highest observed option, reserved for candidates passing QA.
- GPTFP headless upload readiness passed on bounded pre-submit retry; no prompt had been sent
 in the failed attachment attempt. Actual QA conversation6ab94884-4b5c-83ec-a1cf-8868b4f2d92f /
 assistantaf27b8f7-61ce-435a-a8cd-cd4a0d60d428 rejected merged scenes/changed hand poses.
 This source remains failed, excluded from quota/publication. Do not call this package complete.
- Future prompts now preserve limb poses and hard-cut at each scene boundary; literal line
 separators are interpreted as whitespace without rewriting source words or stored scripts.
- Independent review fixed quarantine lease acquisition and unsuccessful raw-read caching;
 confirmed pre-paid retry boundary, immutable upload receipts and headless production settings.
- Fresh fetch: canonicalComicReelsHEAD4ddd23f equals origin/feature/comicreels-segments-03-16;
 KBS cleanmain b1a78e1 equalsorigin/main. Existing dirty FBR/Thoremix work preserved.

## Owner steering 2026-09-28: advisory QA and manual approval

The owner explicitly changed content QA to reference-only. A generated, fully downloaded,
valid clip counts as production complete even when image/video/audio QA warns. It must be
packaged with the unchanged QA report, marked awaiting_approval, and excluded from automatic
and manual publication until the owner clicks Duyệt clip để đăng for the exact manifest.
Passed clips retain automatic publication. This supersedes earlier content-failure skip rules.
Technical failure, incomplete/corrupt bytes and unknown paid outcomes remain recoverable errors.
Resume all four existing quality-stopped stories from verified images/native video; never
regenerate completed images or replay the quarantined uncertain image submission.

Implementation accepted 28/09: quality.py, pending manifest state/counts, hash-bound approval queue,
advisory stage migration and resume-quality-stops are installed. Real c367 completed at00:17 local
with highest720p native video, preserved source/three children and advisory QA. 333a and69e2 also
completed; their saved stages and source-named packages were verified on disk. The Windows EXE
media-validation locale failure was repaired with explicit UTF-8, including a legacy-codepage
regression using a Vietnamese path. Owner approval remains mandatory for warnings.
Finishing and the direct player supersede the old narrow inspector; see the 28/09 execution plan.
