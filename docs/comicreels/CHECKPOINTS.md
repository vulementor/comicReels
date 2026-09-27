# CHECKPOINTS | Trạng thái triển khai ComicReels

## FBR-0 — LOCAL_PASS / LIVE_PASS; OWNER_CONFIRM_REQUIRED before merge

Latest verified state: **2026-09-27 13:17 Asia/Saigon**. Owner reported login complete;
the login helper closed cleanly and released its lease before the provider acquired ownership.
The following record supersedes the historical blocked entries below.

- WORKING_BRANCH: `fbr/0-flow-browser-bootstrap`; checkpoint source is the commit containing
  this record (resolve with `git log -1 -- docs/comicreels/CHECKPOINTS.md`). Tested working-tree
  base: `e3f140800a858de507c373137a1cba37779a208a`; exact tested source digest:
  `8a7e2bccd5176da8ef86fcf5325fb0df0e6b93b77703de4fac6c75bfb271719c`.
- MERGED_HEAD / rollback: `fbcf8560bb6c68b831535e8fe7a1d904446ee0c6`, on
  `feature/comicreels-segments-03-16`. No implementation merge yet.
- KBS_HEAD / KBS_PIN / remote main: `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
  Canonical KBS checkout is clean; live import provenance was checked against the installed
  distribution's direct_url commit. Runtime versions: KBS 0.1.4, Camoufox 0.5.6, Playwright 1.62.0.
- FLOW_BACKEND: active application remains extension/batch. FBR-0 provider is `browser_shadow`,
  explicitly opted into only for the bounded read-only smoke. No worker was started.
- PROFILE_LOGICAL_NAME: `flow-browser`; PROFILE_PATH_CONFIGURED: true in local-only JSON;
  persistent directory and identity unchanged across both opens. No profile/auth data copied.
- SESSION_STATE: authenticated during both fresh captures, same account across controlled reopen.
  Browser now closed; passive health correctly returns unknown rather than cached readiness.
  LEASE_STATE: released; owned durable markers removed; competing acquisition returned PROFILE_BUSY
  in each live cycle. FLOW_HOST: `flow.google.com`; no project selected or modified.
- TESTS: 528 ComicReels unit PASS (21 provider/lease, 13 observed-auth, 4 source snapshot);
  GPT FullProxy SDK 30 PASS / 7 SKIP; fresh npm ci, frontend build/lint PASS. Targeted Python
  Ruff PASS. Generated AGENTS.md was regenerated twice with a clean second diff.
- LIVE_EVIDENCE: two cycles at 06:17:35Z and 06:17:41Z, each authenticated/ready=true,
  KBS supported nonempty semantic capture (2 interactive nodes at depth 4), unchanged profile,
  conflict lock verified, page closed, lease released, marker removed. Same provider retained
  the verified identity in memory to compare the reopened account; receipt contains no identity.
- SOURCE_TO_RUNTIME: a fresh isolated test deployment of the actual local working tree was
  regression-tested and used for live imports. Both provider/auth module hashes matched its
  manifest. Active application runtime remains untouched. Only these checkpoint/ledger docs
  changed after the final gate; implementation/test bytes match the tested snapshot.
- Local detailed evidence: `local-test-data/source-batch-e3f1408-5e90b33ed52e4f9ca7de76a6eaebc39f/`
  contains `result.json`, `flow-live.json`, JUnit and build/lint logs (ignored, not published).
  This record retains the sanitized acceptance results for a fresh checkout.
- REVIEW: independent foundation review repaired with regression tests; separate review of the
  newly observed auth adapter found no blocking issue. Actual DOM label newline caused the first
  auth smoke to remain UNKNOWN; its regression failed first, then passed after whitespace
  normalization. The final full gate and live smoke above validate the repaired implementation.
- PAID_EFFECT_STATE: none submitted. PENDING_OR_UNKNOWN_JOB: historical application state has
  not been reconciled; FBR-0 did not start jobs or inspect/mutate that queue.
- KNOWN_GAPS: auth adapter supports only the observed vi-VN account control; other/changed
  layouts remain UNKNOWN. This is profile bootstrap, not a browser generation backend.
  Existing frontend chunk-size advisory remains. Optional review suggestions (outer-container
  zero-count fixture and explicit selector-regex assertion) are deferred, not blockers.
- NEXT_ALLOWED_ACTION: owner confirms this concrete FBR-0 checkpoint for merge and closeout;
  then merge into the integration branch, verify exact merged SHA and final smoke/regression.
- FORBIDDEN_NEXT_ACTIONS: merge without that confirmation, FBR-1, paid generation, parallel
  profile owners, auth export, or declaring the whole browser migration complete.
- OWNER_CONFIRM_REQUIRED: **merge and close FBR-0**. The owner login confirmation is already
  satisfied. See [implementation ledger](FBR-0-IMPLEMENTATION.md) for decisions and adapter use.

## FBR-0 local implementation — historical state before owner login

**STATUS: BLOCKED on live login; offline foundation implemented and validated locally.** The owner-authorized dedicated
`flow-browser` binding is now known, so offline foundation work can proceed without guessing
the earlier Chrome identity. At the latest inspection the new profile directory was empty and
no login-helper process was running. Automatic launch remains tool-policy blocked; no retry.

- Local provider/OS lease and KBS page wrapper implemented on `fbr/0-flow-browser-bootstrap`;
  source changes are uncommitted. Base LOCAL_HEAD / REMOTE_HEAD remains
  `e3f140800a858de507c373137a1cba37779a208a`. MERGED_HEAD/rollback remains
  `fbcf8560bb6c68b831535e8fe7a1d904446ee0c6`.
- KBS_HEAD / optional exact KBS_PIN: `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
  An isolated test install consumes the Git commit; application runtime dependencies unchanged.
- FLOW_BACKEND remains extension/batch. New provider is an opt-in read-only shadow foundation.
- PROFILE_LOGICAL_NAME: `flow-browser`; PROFILE_PATH_CONFIGURED: true, local-only.
  LEASE_STATE: not acquired for the actual profile; SESSION_STATE: awaiting manual sign-in.
  FLOW_HOST target: `flow.google.com`; FLOW_PROJECT_ID: not selected.
- TESTS: final local-source regression PASS: 515 unit tests (including 21 provider/lease and
  4 snapshot tests); GPT FullProxy SDK 30 PASS / 7 SKIP; fresh npm ci, frontend build and lint
  PASS. Targeted Python Ruff and compile checks PASS. Generated AGENTS.md is idempotent.
  The frontend build has an existing chunk-size advisory; it did not fail the build.
- Final tested working-tree digest:
  `e1bb144297509591a966566df21c270bcbcaf35f5db0f994af49e3e521d7bfbf`.
  Local evidence: `local-test-data/source-batch-e3f1408-03c6289030ce4ab7b522cc8c2e703558/result.json`.
  This digest covers the snapshot before this evidence-note update; no implementation/test
  bytes were changed after the final gate. The snapshot is a local test deployment, not a
  replacement for the active application runtime.
- Independent review repairs: durable owner marker retained after crash/uncertain close;
  passive diagnostics never report cached authentication as current readiness; identity changes
  latch the block. Regression includes the failed-then-passing reproductions.
- LIVE_EVIDENCE: none yet. Default auth probe deliberately returns UNKNOWN; a real Flow adapter
  must be grounded in the owner-signed-in surface before declaring readiness.
- PAID_EFFECT_STATE: no new job. PENDING_OR_UNKNOWN_JOB: historical state not reconciled.
- LOCAL-SOURCE-FIRST now encoded in setup.py/generated AGENTS.md, CLAUDE.md and execution plan.
  Working-tree regression snapshots current bytes instead of stale HEAD, with a source digest.
- NEXT_ALLOWED_ACTION: owner opens the prepared login helper
  and signs in, then implement/validate the observed auth probe and controlled same-profile reopen.
- Source changes remain local/uncommitted pending that live step; no checkpoint implementation
  push or merge performed. The earlier documentation-only remote branch remains unchanged.
- FORBIDDEN_NEXT_ACTIONS: claim LIVE_PASS from fakes, merge, FBR-1, paid generation, parallel
  profile owners or auth export. OWNER_CONFIRM_REQUIRED: login completion; merge gate later.
- Detailed decisions/tests/remaining work: [FBR-0-IMPLEMENTATION.md](FBR-0-IMPLEMENTATION.md).

## FBR-0 local follow-up — owner authorizes a dedicated profile

The owner explicitly authorized creation of one separate profile for manual sign-in on 27/09.
This supersedes the earlier prohibition on creating a profile for this specific bootstrap.
Logical binding: `flow-browser`; browser kind: Camoufox. The dedicated directory was created
and its local JSON configuration validated. Physical paths remain outside Git in local config.
No existing Chrome or other service profile was copied, modified or closed.

- STATUS: BLOCKED pending manual browser launch and owner sign-in; no FBR-0 LIVE_PASS.
- WORKING_BRANCH: `fbr/0-flow-browser-bootstrap`.
- LOCAL_HEAD / REMOTE_BRANCH_HEAD before this local note:
  `e3f140800a858de507c373137a1cba37779a208a` (documentation-only pre-flight).
- MERGED_HEAD / KBS_HEAD / KBS_PIN / FLOW_BACKEND: unchanged from pre-flight below.
- PROFILE_LOGICAL_NAME: `flow-browser`; PROFILE_PATH_CONFIGURED: true in local-only config.
- LEASE_STATE: not acquired; SESSION_STATE: awaiting manual sign-in; FLOW_HOST target:
  `flow.google.com`; no Flow project selected.
- The automatic launch command was rejected by tool policy (`blocked by policy`, no more
  specific reason supplied). No equivalent automatic launch was retried.
- An ignored local launcher was prepared with an exclusive profile lock, persistent Camoufox
  context, fixed Flow entry URL and no credential inspection. It is a login helper, not the
  implemented/tested FlowBrowserSessionProvider.
- TESTS: helper Python compilation, local JSON binding/directory validation, and Git exclusion
  checks PASS. Browser launch/authentication/reopen and full product regression NOT RUN.
- PAID_EFFECT_STATE: none submitted; existing pending/unknown jobs remain unreconciled.
- NEXT_ALLOWED_ACTION: owner opens the local login helper and signs in; then verify the same
  profile and perform a controlled lease handoff before implementation/live bootstrap tests.
- FORBIDDEN_NEXT_ACTIONS: parallel profile owners, profile replacement, auth extraction, paid
  generation, FBR-1 or merge. OWNER_CONFIRM_REQUIRED: manual login completion now; checkpoint
  acceptance remains a later gate. This local note is intentionally not a checkpoint push.

## FBR-0 pre-flight — 27/09/2026: canonical profile unresolved

**CHECKPOINT: FBR-0; STATUS: BLOCKED; implementation and browser live validation NOT STARTED.**

Owner activated FBR-0 in the 27/09 handoff. The stop is missing canonical Flow profile identity,
not missing permission to implement FBR-0. The handoff explicitly requires stopping and asking
the owner when the canonical profile cannot be determined safely. No replacement profile may
be created or inferred from whichever Chrome process happens to be running.

### Repository provenance at pre-flight

- WORKING_BRANCH: `fbr/0-flow-browser-bootstrap`, created from the clean integration baseline.
- INTEGRATION_BRANCH: `feature/comicreels-segments-03-16`.
- LOCAL_HEAD at inspection, before this documentation-only checkpoint:
  `fbcf8560bb6c68b831535e8fe7a1d904446ee0c6`.
- REMOTE_BRANCH_HEAD: FBR branch did not exist at inspection; its documentation commit is to be
  pushed separately. Resolve the latest branch SHA with `git rev-parse HEAD` / `git ls-remote`
  when resuming; do not mistake the pre-flight SHA for an implementation revision.
- MERGED_HEAD / rollback baseline:
  `fbcf8560bb6c68b831535e8fe7a1d904446ee0c6`; no FBR-0 merge performed.
- KBS_BRANCH: `main`.
- KBS_HEAD: `b539e9820d433c8c9d667b4e5d9007b6a80b8abd`.
- KBS_PIN: not configured in ComicReels yet. The existing GPT FullProxy SDK pin is not a KBS pin.
- Fresh `git fetch origin --prune` succeeded for both repositories. Both local baseline HEADs
  matched their respective remote branches, with ahead/behind `0/0`; both worktrees were clean
  before this record.
- RUNTIME_HEAD: not verified against running process source. A local `running.json` receipt
  reported `b28fc4a0b08267e9946eea82c3ab12728c68e55b`; that receipt alone is not live provenance.

### Profile and live evidence

- FLOW_BACKEND: existing extension / `batch`; no browser backend implemented or selected.
- PROFILE_LOGICAL_NAME: UNRESOLVED.
- PROFILE_PATH_CONFIGURED: no verified Flow binding found in the inspected workspace registry,
  repository config or current-shell Flow profile configuration.
- Workspace `profile-bindings.json` contains only `github-review-reel` and `shopee-affiliate`.
  The inspected workspace profile directory also contains `kfgt-facebook-main`; none proves a
  canonical Flow binding.
- Historical `LOCAL-TEST-RESULTS-2026-09-26-WINDOWS.md` records reuse of signed-in Chrome but
  does not bind it to a physical/logical Flow profile.
- A running Chrome process has a profile-directory argument, but it is only an unverified
  candidate. Do not use it as authority or commit its physical profile path.
- Available browser-tool inventory exposed only the Codex in-app browser with no tabs; it did
  not expose the existing Chrome Flow surface for profile/identity verification.
- LEASE_STATE: NOT_ACQUIRED_BY_THIS_TASK; existing browser ownership not changed.
- SESSION_STATE: NOT_VERIFIED_FOR_BROWSER_BACKEND; no login, logout, close or reopen performed.
- FLOW_HOST: target `flow.google.com`; authenticated browser page not observed by this task.
- FLOW_PROJECT_ID: not selected or verified for FBR-0.
- Read-only local `GET /health`: `status=ok`, `extension_connected=true`.
- Read-only local `GET /api/flow/status`: `transport=batch`. Extension health does not prove
  browser-provider readiness or same-profile authentication continuity.

### Validation and limits

- TESTS: Git provenance/status checks and read-only local health probes completed. Provider
  tests, full regression, frontend build/lint and browser live smoke NOT RUN: implementation
  stopped before profile selection. This is not LOCAL_PASS or LIVE_PASS.
- LIVE_EVIDENCE: no canonical-profile lease/capture/close/reopen evidence acquired.
- PAID_EFFECT_STATE: no paid requests submitted by this task. Historical
  `PUBLIC_ERROR_UNUSUAL_ACTIVITY` remains unresolved; do not assume recovery.
- PENDING_OR_UNKNOWN_JOB: not reconciled against live job records in this pre-flight; no new
  job created by this task. Historical checkpoint records remain the only job-state evidence.
- No source code, KBS code, generated AGENTS.md, runtime deployment, profile data or auth values
  changed by this pre-flight. Only this checkpoint record was edited.

### Resume contract

- NEXT_ALLOWED_ACTION: owner identifies the canonical existing Flow profile and its local
  configuration/binding; then verify ownership and continue FBR-0 on this branch. Keep physical
  profile paths in local configuration, not committed documentation.
- The owner's latest explicit working policy is LOCAL-SOURCE-FIRST: develop/test in the
  canonical local source repo, deploy through supported tooling, and push a coherent checkpoint.
  Older GitHub-first / Remote Desktop-only paragraphs below and in generated operating rules
  are historical. Before implementation, reconcile the authority source (`setup.py`), generated
  `AGENTS.md`, and execution plan with this policy; preserve historical evidence.
- Known validation gap: `scripts/verify_windows_batch.ps1` archives `HEAD`, so it cannot validate
  uncommitted local changes. Resolve that mismatch before claiming LOCAL-SOURCE-FIRST regression
  coverage; an old committed snapshot is not evidence for current local edits.
- FORBIDDEN_NEXT_ACTIONS: choose/create/copy/replace a profile, clear storage, close an unrelated
  browser, paid generation, unknown-job retry, extension deletion, FBR-1, or merge this BLOCKED
  checkpoint.
- OWNER_CONFIRM_REQUIRED: canonical Flow profile identification now; checkpoint merge acceptance
  only after FBR-0 implementation and required live evidence pass. No merge approval requested
  for this blocked pre-flight.

## Closeout chuẩn hoá tài liệu — 27/09/2026

**DOC/FBR BASELINE = LOCAL_PASS; FBR-0 = PLANNED; OWNER_CONFIRM_REQUIRED trước khi implement.**

Đã chuẩn hoá và commit authority set cho browser-first Flow refactor:

- `docs/comicreels/FLOW-BROWSER-FIRST-ARCHITECTURE.md`: kiến trúc, ownership boundaries, persistent-profile/session continuity, paid-effect semantics, extension retirement policy và FlowKit creative preservation matrix.
- `docs/superpowers/plans/2026-09-27-flow-browser-refactor.md`: FBR-0 → FBR-6 với entry criteria, allowed/forbidden scope, regression/live evidence, rollback, stop conditions và OWNER_CONFIRM_REQUIRED giữa từng checkpoint.
- `setup.py`: nguồn sinh `AGENTS.md` đã encode Browser-First Flow Refactor Contract; không sửa generated artifact bằng tay.
- `AGENTS.md`: regenerated từ source và verified idempotent trên VULE-PC.
- `CLAUDE.md`: liên kết authority docs và ghi rõ extension vẫn là fallback trước FBR-5.

Điều khoản bảo toàn FlowKit đã được đóng thành invariant: không bỏ `fk-create-project`, scene ROOT/CONTINUATION, transition prompts, `fk-creative-mix`, `fk-pipeline`, `fk-gen-videos`, review/regen, Gallery/Logs/Guide/Settings, TTS/concat/branding/SEO/YouTube chỉ vì đổi transport.

**Evidence trên VULE-PC:** source `5f1b229f6433a0fba5bd44bb766dde67c8f17ae6`; `python -m py_compile setup.py` PASS; regenerate `AGENTS.md` bằng `setup.py --tool codex` cho `AGENTS_ZERO_DIFF=True`; full `verify_windows_batch.ps1` PASS (`unit_and_frontend`), SDK pin vẫn `19414dd270d5d55aed48cda3cf8b259049d688c4`.

**Session continuity policy đã thành repository authority:** một persistent signed-in Flow profile + explicit lease/lock; không clear cookie/storage, không logout, không silent profile replacement, không commit token/cookie/profile content. Mỗi cuối phiên phải ghi source commit, KBS pin, backend kind, profile logical name, lease/session health, paid-job uncertainty và exact next allowed action.

**Next allowed action:** chỉ bắt đầu **FBR-0 — Profile/session bootstrap** sau owner confirmation. Chưa được paid generation bằng browser backend mới.


## Chỉ đạo kiến trúc mới — 27/09/2026: Flow browser-first refactor

**OWNER APPROVED — FBR-0 PLANNED.** Refactor phần transport/runtime làm việc với Google Flow theo hướng mở `https://flow.google.com/` bằng một persistent browser profile đã đăng nhập, sau đó dùng `kabin_browser_semantic` (KBS) cho browser semantics, resolver, network observation, body capture, authenticated replay và settle.

Đây **không phải** là rewrite FlowKit creative layer. Các kịch bản và năng lực hiện có của FlowKit phải giữ nguyên: `fk-create-project`, project/story/entity semantics, ROOT/CONTINUATION chain, transition prompts, `fk-creative-mix`, `fk-pipeline`, `fk-gen-videos`, review/regen, Gallery/Logs/Guide/Settings, TTS/concat/branding/SEO/YouTube và các skill liên quan.

Authority mới:
- kiến trúc: [FLOW-BROWSER-FIRST-ARCHITECTURE.md](FLOW-BROWSER-FIRST-ARCHITECTURE.md);
- kế hoạch checkpoint: [2026-09-27-flow-browser-refactor.md](../superpowers/plans/2026-09-27-flow-browser-refactor.md);
- operational agent rules được sinh từ `setup.py` vào `AGENTS.md`.

**Nguyên tắc thực thi bắt buộc:** GitHub trước → sync VULE-PC → regression → live evidence → cập nhật checkpoint → báo cáo → **OWNER_CONFIRM_REQUIRED** trước khi sang checkpoint kế tiếp. Không sửa runtime tay làm nguồn sự thật. Không dùng paid generation làm diagnostic.

**Session continuity:** một persistent Flow profile + explicit lease/lock; không xoá cookie/storage, không logout, không tự tạo profile thay thế, không commit profile/token/cookie. KBS chỉ giữ live browser handles; Flow-specific selector/RPC/product semantics ở FlowKit/ComicReels adapter.

**Extension preservation:** FBR-0..FBR-4 vẫn giữ extension/WebSocket transport làm fallback. Browser-first chỉ thành default sau FBR-5 được owner chấp thuận. Xoá extension là FBR-6 riêng, không tự động đi kèm cutover.

**Checkpoint hiện tại:** FBR-0 chưa code. Việc được phép tiếp theo là thiết kế + implement browser session provider/profile lease/KBS pin/read-only health. Chưa được phép paid generation bằng backend mới.


## Cập nhật Flow live — 27/09/2026

**Trạng thái: FLOW_R2V_BLOCKED_BY_GOOGLE; không resend tự động.** UI Windows đã được sửa từ gốc: launcher hiện dọn stale ComicReels listeners/Vite cache trước khi start; revision `e61c4cb` và regression kế tiếp tại `6948c432` đều PASS trên VULE-PC. Vite `/src/App.tsx` trả HTTP 200 sau restart sạch.

Live Flow được gửi đúng preset đã chốt: Omni Flash, 10s, 360p, 1 variant, ba ảnh reference đã approved. Ba reference media của shot 1 upload thành công vào cùng Flow project và còn truy xuất được qua Flow media API. Tuy nhiên RPC Ingredients/R2V `MZZa6b` bị Google trả `PUBLIC_ERROR_UNUSUAL_ACTIVITY` hai lần, đều không có operation/workflow receipt hợp lệ. Shot 2/3 chưa được gửi.

State machine đã sửa trên GitHub: explicit unusual-activity rejection là definitive server rejection và về `FAILED`, còn timeout/mất receipt vẫn giữ `SUBMISSION_UNKNOWN`; retry sau definitive rejection tái sử dụng ba media reference cũ thay vì upload trùng. Regression mới tại `6948c43220ff2c4ab4c778311624a26791ca103e` PASS. Sau lần retry live, Google vẫn chặn R2V nên dừng, không tự degrade sang single-image/first-frame mode và không gửi thêm paid generation.

## Cập nhật prompt + bộ ảnh đã duyệt — 27/09/2026

**Trạng thái: IMAGES_APPROVED + PROMPTS_READY; dừng trước Flow generation có credit.** Người dùng xác nhận prompt batch ổn định hơn khi thêm câu bắt buộc giữ thứ tự và biểu cảm. Canonical prompt trong code hiện kết thúc bằng: `Yêu cầu bắt buộc: Giữ đúng thứ tự ảnh, biểu cảm nhân vật.` tại revision `9eac3eb12b38f0800dda68c5741e84b98995ebcf`.

Từ conversation ChatGPT do người dùng cung cấp, VULE-PC dùng Remote Desktop Commander + `gpt_fullproxy` ở chế độ read-only để tách đúng gallery mới nhất, không resubmit prompt. Ba ảnh 941x1672 mới được lấy theo DOM order, QA trực quan khớp ba panel tốt hơn: khung 1 ngựa há miệng; khung 2 ngựa ngậm miệng và thỏ dựng/đưa tay; khung 3 ngựa quay trái, ngậm miệng. Bộ này đã được import atomic bằng `reserve_image_batch -> apply_image_batch`, sau đó cả ba ảnh được duyệt qua API guard thành `AI_IMAGE_APPROVED`.

Storyboard đã được dựng lại với `omni_flash`, 10 giây; 3/3 shot ở trạng thái `READY`, project `PROMPTS_READY`. Flow preflight trả `ready=true`, extension 0.3.2 kết nối. Chưa gửi bất kỳ Flow generation job nào trong vòng này, vì bước đó vẫn là paid/external hard stop.

Windows launcher cũng sửa `npm` thành `npm.cmd`; full regression tại revision `9eac3eb` PASS SDK tests, ComicReels unit tests, frontend build và lint. Runtime VULE-PC đã restart đúng revision này với profile ChatGPT local và status `ai.configured=true`.

## Cập nhật live batch — 27/09/2026, VULE-PC

**Trạng thái: SOURCE_BATCH_LIVE_PASS + IMAGE_QA_REVIEW_PENDING.** Một ảnh truyện gốc được gửi đúng một lần qua `gpt_fullproxy` với prompt ngắn tự đếm khung; không crop input, không loop Generate từng panel, không thao tác web thủ công. Live test trên source truyện 3 khung đã trả **3 PNG 941x1672 riêng, đúng thứ tự**, không chữ/bong bóng, trong cùng một conversation receipt.

Lỗi gốc của lượt trước nằm ở collector: sau ảnh đầu tiên, gallery có thể tạm yên hơn 2 giây rồi mới thêm ảnh 2/3. SDK revision `19414dd270d5d55aed48cda3cf8b259049d688c4` đổi completion gate sang quiet window 30 giây kể từ thay đổi gallery cuối; mỗi blob mới reset timer. Regression trên VULE-PC tại ComicReels `3a5426b9302bc5efeea02b56b3da8ed80c16f99b` + SDK này PASS cả SDK tests, unit tests, frontend build và lint. Live batch sau sửa exit code 0 và ghi đủ `scene-1.png`, `scene-2.png`, `scene-3.png` ngay lần đầu, không cần resubmit/reconcile cứu hộ.

QA nội dung vẫn tách khỏi PASS kỹ thuật. Scene 1/2 bám panel nguồn tương đối tốt; scene 3 giữ đúng nhân vật/bối cảnh nhưng tư thế/hướng con ngựa chưa sát tuyệt đối panel gốc, nên **chưa tự duyệt ảnh vào project**. Bộ ảnh cũ vẫn giữ verdict IMAGE_QA_FAILED; bộ live mới đang chờ cửa duyệt hình ảnh. Chưa merge PR #3, chưa gửi Google Flow, chưa tạo video thật.

## Chỉ đạo mới nhất — 26/09/2026, 20:36 Asia/Saigon

Code/fix phải lên GitHub trước. VULE-PC chỉ để test qua command của Remote Desktop Commander; mọi test ChatGPT chỉ qua `gpt_fullproxy`, không thao tác web trực tiếp.

Luồng tạo ảnh được sửa từ gốc: một ảnh truyện nguyên bản + một prompt ngắn yêu cầu ChatGPT tự đếm khung, tạo mỗi khung một ảnh 9:16 riêng theo thứ tự. Không ấn định hai/ba ảnh, không gửi crop từng khung, không lặp Generate từng panel. SDK mới trả danh sách ảnh; ComicReels chỉ thay bộ ảnh khi nhận đủ, không trùng và đúng định dạng. Thoại giữ nguyên; bộ ảnh mới cần duyệt lại. FlowKit core và cửa duyệt video giữ nguyên.

SDK hiện được pin tại `19414dd270d5d55aed48cda3cf8b259049d688c4`. Regression và live batch đã PASS trên VULE-PC như cập nhật 27/09 ở trên. Báo cáo cũ bên dưới là lịch sử; xem [kế hoạch sửa luồng](../superpowers/plans/2026-09-26-source-image-batch.md).

Việc tạo lại ảnh đã được người dùng cho phép; không yêu cầu xác nhận lại. Dừng các lượt thao tác web thủ công. Bộ ảnh cũ vẫn IMAGE_QA_FAILED; live batch mới đã chạy thành công nhưng chưa được duyệt vào project. Chưa merge PR #3, chưa tạo Flow video.

## Hiện tại — 26/09/2026, sau chỉ đạo “ComicReels Latest”

**Trạng thái: IMAGE_QA_FAILED — KHUNG 2/3 ĐÃ THU HỒI DUYỆT; LIVE_VIDEO_PENDING.**
Nhánh `feature/comicreels-segments-03-16`, Draft PR #3. Chưa merge.

- FlowKit vẫn là core tại `/`; giữ Projects, Gallery, Logs, Guide, Settings và API/worker/extension gốc. ComicReels tại `/comicreels`.
- Sửa status ComicReels dùng trạng thái FlowKit; AI image không bị mất kết nối giả do tham chiếu hàm đã xóa.
- Chọn đúng 3 ảnh đã duyệt + một kịch bản thành phần. Khóa cảnh theo ảnh của kịch bản; thoại giữ nguyên, chỉ một người nói, không TTS riêng.
- Preset ComicReels: Omni Flash, 10s, 360p, 1 phiên bản. Các preset/mode khác của FlowKit giữ nguyên.
- Upload/generate/poll dùng API FlowKit hiện có. Project của lượt upload đầu được dùng thống nhất cho cả ba ảnh và video.
- Lưu lượt gửi atomic trước network; cùng lượt không gửi trùng. Lưu receipt kể cả response bất thường, không tự retry khi chưa rõ kết quả.
- Database chặn sửa/xóa ảnh, thoại, kịch bản trong khi còn job chưa kết thúc. Poll và review gắn đúng lượt/video; phản hồi cũ không đè lượt mới.
- Đọc cả operation và workflow receipt, tải video, xem/nghe và tải MP4 trong UI; từ chối rồi tạo lại riêng shot lỗi, hủy duyệt cũ trước khi ghép.
- Quay lại ComicReels sẽ mở dự án gần nhất; ảnh hiện có không tự Generate lại. Lỗi ở khung sau vẫn làm mới gallery các khung đã xong.
- Không tạo Chrome/profile mới; tiếp tục dùng extension và cấu hình profile đã có.

**Bằng chứng vòng này:** đã chuyển môi trường sang VULE-PC theo yêu cầu. Bản sao 30 file khớp SHA-256; giữ 3 ảnh được duyệt và 3 shot READY. Extension 0.3.2 kết nối; GPT FullProxy ghi nhận đăng nhập ChatGPT. Gate offline chạy qua Remote Desktop Commander: 460 unit tests PASS sau sửa lỗi symlink trên Windows; frontend build và lint PASS. Bước 3 cũng đã kiểm tra trực tiếp Chrome trên VULE-PC qua RDC: sáu trang FlowKit, chi tiết dự án/video/pipeline, bảng chi tiết cảnh, sidebar và mở lại ComicReels sau chuyển trang/reload đều đạt. Dùng lại cửa sổ/profile Chrome đang đăng nhập; không gửi job tạo ảnh/video. Chi tiết và giới hạn ở [LOCAL-TEST-RESULTS-2026-09-26-WINDOWS.md](LOCAL-TEST-RESULTS-2026-09-26-WINDOWS.md). UI smoke không thay thế QA ảnh hoặc video thật.

**Cập nhật bước 4:** người dùng phát hiện ba ảnh gần như một. Đối chiếu ảnh thật trên VULE-PC xác nhận khung 2 lặp bố cục/tư thế khung 1, khung 3 quay sai hướng. Đã sao lưu DB, bỏ duyệt riêng khung 2/3; giữ nguyên ba file và ba kịch bản. Verdict lịch sử được sửa; code bổ sung chặn ảnh đã bị loại ở approval, storyboard, video và kết quả provider/cache. Revision `c76f7a9` đạt 467 unit tests trên Windows và đã cập nhật runtime; API thật chặn duyệt lại cả hai ảnh bằng HTTP 409. Reload Chrome qua RDC: chỉ ảnh 1 còn được chọn làm reference, tạo video bị chặn do thiếu ảnh đã duyệt. Xem [IMAGE-QA-2026-09-26.md](IMAGE-QA-2026-09-26.md) để phân biệt kết quả kiểm tra code với chất lượng ảnh.

**Bước tiếp theo hiện tại:** không quay lại cách Generate riêng từng crop. Dùng bộ batch 3 ảnh mới để QA từng khung; chỉ sau khi ảnh đạt mới áp vào project và duyệt hash. Google Flow/video vẫn giữ hard stop riêng.

## Lịch sử ngày 25/09/2026 (không chứng minh revision hiện tại)


**Cập nhật 25/09/2026 sau vòng test local trên máy Mac của anh.** Anh đã cho phép triển khai liên tục và test local, nhưng yêu cầu báo trước khi cần tài khoản Google Flow hoặc ChatGPT/vision AI.

Trạng thái mới: OFFLINE_LOCAL_TEST_PASS = code và workflow local đã chạy thực tế; EXTERNAL_TEST_PENDING = cần dịch vụ/tài khoản ngoài; ACCEPTED_WITH_GAPS = đã được anh cho chuyển bước dù còn khoảng trống.

| Đoạn | Trạng thái | Bằng chứng / khoảng trống |
|---|---|---|
| 0 | ACCEPTED_WITH_GAPS | VISION, PRD, kiến trúc, roadmap đã được anh duyệt định hướng. |
| 1 | ACCEPTED_WITH_GAPS | Public fork và docs có trên GitHub; lịch sử/parent đã xác minh. |
| 2 | OFFLINE_LOCAL_TEST_PASS | Studio tiếng Việt, route root và /flowkit, upload UI, build/lint/browser smoke đều PASS. |
| 3 | OFFLINE_LOCAL_TEST_PASS | Import, MIME/size validation, SHA-256, SQLite persistence và restart PASS. |
| 4 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL_AI_PENDING | Heuristic nhận đúng synthetic 2-panel và comic thật 3-panel; luồng chính đã đổi sang AI tự nhận panel/thứ tự. |
| 5 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL_AI_PENDING | CRUD exact dialogue/speaker PASS; UI chính không còn bắt nhập tay, AI tự nhận thoại/speaker khi provider được kết nối. |
| 6 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL_AI_PENDING | AI speech-region mask được lưu tự động; chỉnh tay chỉ còn trong mục nâng cao. |
| 7 | EXTERNAL_AI_PENDING | Compositor local bị loại khỏi luồng chính sau test comic thật; ảnh sạch phải do AI Generate/inpaint. |
| 8 | EXTERNAL_AI_PENDING | Luồng chính đã chuyển sang GPT FullProxy + ChatGPT Web Create image với reference attachment; cần live-test profile ZaloConnect và chất lượng 9:16 thật. |
| 9 | OFFLINE_LOCAL_TEST_PASS | SHA approval gate và dependency invalidation PASS. |
| 10 | OFFLINE_LOCAL_TEST_PASS | Shot split/duration/speaker lock, exact dialogue PASS. |
| 11 | OFFLINE_LOCAL_TEST_PASS | Prompt locks, backup/restore và UI storyboard PASS. |
| 12 | EXTERNAL_TEST_PENDING | Offline preflight đúng ready=false; cần Flow Extension/project thật để test tiếp. |
| 13 | EXTERNAL_TEST_PENDING | Paid guard 409 PASS; chưa gửi video thật, chưa phát sinh phí. |
| 14 | EXTERNAL_TEST_PENDING | Batch code có guard/idempotency; chưa chạy batch thật trước single-shot Flow pass. |
| 15 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL QA PENDING | Register/review/ffmpeg assemble PASS với video synthetic; video AI thật chưa kiểm tra lip-sync/voice. |
| 16 | OFFLINE_LOCAL_TEST_PASS_WITH_GAPS | Backup/restore PASS; launcher macOS đã chạy thực tế từ source iCloud và dựng runtime cache ngoài iCloud; PowerShell/Windows chưa test. |

## Regression evidence
- Python unit tests: **cần chạy lại sau provider swap sang GPT FullProxy**; mốc trước đó 380/380 PASS.
- npm ci: PASS.
- Vite production build: PASS.
- ESLint: PASS.
- npm audit: 0 vulnerabilities after lockfile refresh.
- Offline API E2E and browser/CDP E2E: PASS.
- Backend restart persistence: PASS.
- Bash launcher syntax: PASS; PowerShell execution is pending because pwsh is unavailable on this Mac.
- Full detail: [LOCAL-TEST-RESULTS-2026-09-25.md](LOCAL-TEST-RESULTS-2026-09-25.md).

## Current hard stop
The next meaningful quality gates require either:
- live GPT FullProxy validation với profile ZaloConnect cho auto-analysis + reference-image generation; or
- the user's Google Flow account/Extension/project for a real video generation test.

Anh đã yêu cầu dùng GPT FullProxy + profile ZaloConnect cho gate ChatGPT, nên gate này được phép test. Google Flow vẫn phải báo anh trước khi tạo video thật.
