# CHECKPOINTS | Trạng thái triển khai ComicReels

## Chỉ đạo mới nhất — 26/09/2026, 20:36 Asia/Saigon

Code/fix phải lên GitHub trước. VULE-PC chỉ để test qua command của Remote Desktop Commander; mọi test ChatGPT chỉ qua `gpt_fullproxy`, không thao tác web trực tiếp.

Luồng tạo ảnh được sửa từ gốc: một ảnh truyện nguyên bản + một prompt ngắn yêu cầu ChatGPT tự đếm khung, tạo mỗi khung một ảnh 9:16 riêng theo thứ tự. Không ấn định hai/ba ảnh, không gửi crop từng khung, không lặp Generate từng panel. SDK mới trả danh sách ảnh; ComicReels chỉ thay bộ ảnh khi nhận đủ, không trùng và đúng định dạng. Thoại giữ nguyên; bộ ảnh mới cần duyệt lại. FlowKit core và cửa duyệt video giữ nguyên.

SDK được pin tại `d580dc7729a6943ef419d1b960519e27e8911875`. Trạng thái ở thời điểm push: **chưa chạy regression/live test cho thay đổi batch**. Báo cáo cũ bên dưới là lịch sử, không chứng minh revision mới. Xem [kế hoạch sửa luồng](../superpowers/plans/2026-09-26-source-image-batch.md).

Việc tạo lại ảnh đã được người dùng cho phép; không yêu cầu xác nhận lại. Dừng các lượt thao tác web thủ công. Bộ ảnh hiện tại vẫn IMAGE_QA_FAILED, chưa có live batch mới được nghiệm thu; chưa merge PR #3, chưa tạo Flow video.

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

**Bước tiếp theo:** cần anh đồng ý tạo lại riêng hai ảnh sai từ đúng crop khung 2/3. Phạm vi bước 4 trước đó chỉ đối chiếu ảnh sẵn có; chưa gửi lượt Generate mới hoặc tác vụ Flow có phí. Tiếp tục bằng RDC và Chrome đăng nhập sẵn.

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
