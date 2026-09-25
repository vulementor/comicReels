# CHECKPOINTS | Trạng thái triển khai ComicReels

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
| 8 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL_AI_PENDING | Đã có AI edit canvas/mask 9:16 + source-pixel re-lock; chưa gọi provider thật vì chưa có API credential. |
| 9 | OFFLINE_LOCAL_TEST_PASS | SHA approval gate và dependency invalidation PASS. |
| 10 | OFFLINE_LOCAL_TEST_PASS | Shot split/duration/speaker lock, exact dialogue PASS. |
| 11 | OFFLINE_LOCAL_TEST_PASS | Prompt locks, backup/restore và UI storyboard PASS. |
| 12 | EXTERNAL_TEST_PENDING | Offline preflight đúng ready=false; cần Flow Extension/project thật để test tiếp. |
| 13 | EXTERNAL_TEST_PENDING | Paid guard 409 PASS; chưa gửi video thật, chưa phát sinh phí. |
| 14 | EXTERNAL_TEST_PENDING | Batch code có guard/idempotency; chưa chạy batch thật trước single-shot Flow pass. |
| 15 | OFFLINE_LOCAL_TEST_PASS + EXTERNAL QA PENDING | Register/review/ffmpeg assemble PASS với video synthetic; video AI thật chưa kiểm tra lip-sync/voice. |
| 16 | OFFLINE_LOCAL_TEST_PASS_WITH_GAPS | Backup/restore PASS; launcher macOS đã chạy thực tế từ source iCloud và dựng runtime cache ngoài iCloud; PowerShell/Windows chưa test. |

## Regression evidence
- Python unit tests: 380/380 PASS.
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
- a real comic plus ChatGPT/vision/inpaint capability for AI-assisted panel/dialogue/image reconstruction testing; or
- the user's Google Flow account/Extension/project for a real video generation test.

Do not cross either gate without notifying anh first. No paid Google Flow request has been made in this local-test cycle.
