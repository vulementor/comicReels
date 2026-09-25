# CHECKPOINTS | Tiến độ thực và cửa nghiệm thu

**Cập nhật 25/09/2026.** `OK` trong cuộc trò chuyện không có nghĩa CI/build đã chạy hoặc PR đã merge. Mỗi xác nhận chỉ cho phép **một** phân đoạn tiếp theo.

| Đoạn | Trạng thái | Hiện vật đã có | Chưa hoàn tất |
|---|---|---|---|
| 0 | ACCEPTED_WITH_GAPS | Anh thống nhất ý tưởng và public fork; [VISION](VISION.md), [PRD](PRODUCT.md). | Chỉ là tài liệu thiết kế, chưa có app xử lý ảnh. |
| 1 | ACCEPTED_WITH_GAPS | Anh duyệt cho làm Đoạn 2; public fork SHA gốc đã kiểm tra; [PR #1](https://github.com/vulementor/comicReels/pull/1) `segment/01-foundation`. | PR #1 còn Draft, chưa merge; backend/dashboard smoke chưa xác minh. |
| 2 | IN_PROGRESS | Code UI tiếng Việt, preview ảnh và Flow status ở [PR #2](https://github.com/vulementor/comicReels/pull/2) `segment/02-studio-shell`. | PR #2 Draft, chưa merge; build TypeScript/Vite, browser smoke và Flow thật **CHƯA CHẠY**. Anh **CHƯA OK nghiệm thu Đoạn 2**. |
| 3–16 | PLANNED | Xem [roadmap](ROADMAP.md) và [đặc tả từng phân đoạn](stages/). | Chưa được anh cho phép, chưa thực hiện code/test của các đoạn này. |

## Cửa chặn trước khi bắt đầu Đoạn 3
1. Anh kiểm tra giao diện Đoạn 2, các mục build/browser/API được xác nhận hoặc ghi rõ thiếu và anh chấp nhận thiếu.
2. PR #1/#2 chưa merge nên không gọi code/tài liệu nhánh `main` là đã phát hành.
3. Chỉ khi anh nói **OK nghiệm thu Đoạn 2, bắt đầu Đoạn 3** thì mới triển khai lưu ảnh nguồn và tạo dự án.

## Mẫu cập nhật mỗi phân đoạn
Ghi phạm vi được duyệt, ngày, PR/branch/SHA, file thực đổi, test command + log + PASS/FAIL hoặc CHƯA CHẠY, QA thủ công đã/chưa, lỗi còn lại, tác vụ có phí nếu có, lời OK thực tế của anh và chỉ **một** bước kế tiếp. Nếu lớn, chia a/b, dừng từng phần; không tự làm xuyên đoạn. `ACCEPTED_WITH_GAPS` chỉ khi anh cho qua dù còn hạn chế; `ACCEPTED` cần đủ Definition of Done và anh xác nhận.
