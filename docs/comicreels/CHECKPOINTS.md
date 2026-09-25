# CHECKPOINTS | Trạng thái triển khai ComicReels

**Cập nhật 25/09/2026 theo chỉ đạo mới của anh:** không dừng chờ OK từng đoạn nữa. Em được phép triển khai liên tục Đoạn 3–16, nhưng anh yêu cầu chưa test trên máy local cho tới khi toàn bộ code hoàn tất và anh ra yêu cầu test cụ thể.

Vì vậy có 4 trạng thái: ACCEPTED_WITH_GAPS, CODE_COMPLETE_LOCAL_TEST_PENDING, IN_PROGRESS, PLANNED. **CODE_COMPLETE không có nghĩa runtime pass.**

| Đoạn | Trạng thái | Code / hiện vật | Local test |
|---|---|---|---|
| 0 | ACCEPTED_WITH_GAPS | VISION, PRD, kiến trúc, roadmap | Không áp dụng runtime |
| 1 | ACCEPTED_WITH_GAPS | Public fork + PR #1 + docs | Backend/dashboard smoke còn thiếu |
| 2 | CODE_COMPLETE_LOCAL_TEST_PENDING | PR #2 + Studio tiếng Việt; Flow status cũ được thay bằng API ComicReels status ở nhánh tổng | CHƯA CHẠY |
| 3 | CODE_COMPLETE_LOCAL_TEST_PENDING | Import multipart, validate MIME/size, source SHA-256, SQLite project storage | CHƯA CHẠY |
| 4 | CODE_COMPLETE_LOCAL_TEST_PENDING | Heuristic gutter detector, manual/vision analysis, bbox PATCH + UI chỉnh x/y/w/h | CHƯA CHẠY |
| 5 | CODE_COMPLETE_LOCAL_TEST_PENDING | Vision transcript optional, multi-dialogue CRUD, stable speaker ID + UI kiểm tra nguyên văn | CHƯA CHẠY |
| 6 | CODE_COMPLETE_LOCAL_TEST_PENDING | Crop PNG, mask rectangles, protected source contract, pixel-preservation tests đã viết | CHƯA CHẠY |
| 7 | CODE_COMPLETE_LOCAL_TEST_PENDING | Local mask compositor chỉ đổi pixel trong mask; không dùng unsafe whole-image edit | CHƯA CHẠY chất lượng xóa chữ |
| 8 | CODE_COMPLETE_LOCAL_TEST_PENDING | Canvas 9:16 giữ source pixels, protected-region manifest/hash | CHƯA CHẠY |
| 9 | CODE_COMPLETE_LOCAL_TEST_PENDING | Approval theo SHA-256, sửa ảnh/bbox hủy approval và storyboard phụ thuộc | CHƯA CHẠY bypass/race |
| 10 | CODE_COMPLETE_LOCAL_TEST_PENDING | Split exact substring, 4/6/8/10s Omni hoặc 8s Veo, speaker/lip-sync lock | CHƯA CHẠY |
| 11 | CODE_COMPLETE_LOCAL_TEST_PENDING | Prompt có source/dialogue/lip-sync locks, copy prompt + backup ZIP | CHƯA CHẠY |
| 12 | CODE_COMPLETE_LOCAL_TEST_PENDING | Flow preflight dùng đúng extension + project, manual fallback giữ được | CHƯA CHẠY với Flow thật |
| 13 | CODE_COMPLETE_LOCAL_TEST_PENDING | Single-shot upload/generate/poll, confirm_paid, idempotency, lưu MP4 từ signed URL | CHƯA CHẠY, KHÔNG phát sinh phí |
| 14 | CODE_COMPLETE_LOCAL_TEST_PENDING | Batch endpoint có batch key/idempotency, per-shot error/result; UI cố ý chưa bật batch one-click | CHƯA CHẠY, KHÔNG phát sinh phí |
| 15 | CODE_COMPLETE_LOCAL_TEST_PENDING | Video register/poll, APPROVED/REJECTED, UI review, ffmpeg assemble chỉ khi mọi shot APPROVED | CHƯA CHẠY |
| 16 | CODE_COMPLETE_LOCAL_TEST_PENDING | Windows/WSL launchers, backup/restore manifest/source+analysis, deferred local test plan | CHƯA CHẠY fresh install/restore |

## Nhánh triển khai tổng
- Branch: feature/comicreels-segments-03-16.
- Base: nhánh Đoạn 2, vì PR #1/#2 vẫn Draft và chưa merge vào main.
- Không thay đổi main, không gọi Google Flow có phí, không test local trong giai đoạn code theo chỉ đạo của anh.
- Test files đã viết nhưng chưa thực thi: tests/unit/test_comicreels_images.py, test_comicreels_prompts.py, test_comicreels_store.py.
- Kịch bản test sau cùng: LOCAL-TEST-PLAN.md.

## Điều kiện để đổi sang ACCEPTED
Sau khi anh yêu cầu test local: dependency install + Python tests + TypeScript build/lint + browser workflow + dữ liệu thật + Flow preflight; sau đó chỉ khi anh cho phép mới test một shot có phí. Bug tìm thấy phải sửa trên nhánh tổng rồi chạy regression. Không đổi trạng thái sang ACCEPTED chỉ dựa vào code review.
