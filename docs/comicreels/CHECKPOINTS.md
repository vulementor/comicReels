# CHECKPOINTS | Trạng thái triển khai ComicReels

## Hiện tại — 26/09/2026, sau chỉ đạo “ComicReels Latest”

**Trạng thái: CODE_READY_FOR_REVIEW — LOCAL_TEST_AWAITING_USER_CONFIRMATION.**
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

**Bằng chứng vòng này:** review source/diff và independent static review; thêm regression tests cho trạng thái, preset, thoại dài, gửi trùng, timeout, polling, review cũ và sửa dữ liệu khi job đang chạy. Chưa chạy test/build/backend/browser trên máy anh hoặc trong workspace ở vòng này. Kết quả GitHub Actions, nếu có, phải báo riêng theo commit.

**Bước tiếp theo:** anh duyệt code trên GitHub, sau đó mới bắt đầu từng bước local test bằng Remote Desktop Commander, chờ anh OK giữa các bước. Dùng lại Chrome đăng nhập sẵn; không tự mở profile khác, không gửi tác vụ Flow có phí trước bước được duyệt.

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
