# Kế hoạch test local sau khi code hoàn thành

**Trạng thái:** CHƯA CHẠY theo yêu cầu của anh. Tài liệu này là kịch bản kiểm thử cho lần anh yêu cầu test local.

## Chuẩn bị
- Windows PowerShell: `./scripts/run_comicreels.ps1`; WSL/Linux: `./scripts/run_comicreels.sh`.
- Không cấu hình Google Flow ở vòng 1. Test local data/image/state trước.
- Dùng fixture tự tạo hoặc ảnh anh có quyền sử dụng; không commit ảnh riêng.
- Sau khi test offline pass mới cấu hình Extension + `FLOW_PROJECT_ID`; tác vụ video có phí chỉ chạy đúng một shot sau khi anh xác nhận.

## Gate A — cài đặt/build
1. `python -m pip install -r requirements.txt -r requirements-dev.txt`.
2. `python -m pytest tests/unit -q`.
3. `cd dashboard && npm install && npm run build && npm run lint`.
4. Khởi động backend, GET `/health` và `/api/comicreels/status`; mở `http://localhost:5173/`.

## Gate B — Đoạn 2–5
- Paste/drag/select PNG, JPEG, WebP; file fake MIME/0 byte/>30MB phải bị chặn.
- Import -> restart backend -> mở lại project, source SHA không đổi.
- Tách 2/3/4/5+ panel. Với layout khó thử Vision sau khi đồng ý gửi ảnh provider.
- So panel bbox/reading order; nhập/đổi speaker và thoại, xác minh Unicode/dấu.

## Gate C — Đoạn 6–11
- Khai báo mask speech bubble; lưu clean. So pixel-diff ngoài mask = 0.
- Tạo portrait, kiểm tra width*16 == height*9 và crop protected region pixel-identical.
- Thử gọi storyboard trước OK phải 409; OK hết rồi mới tạo shot.
- Sửa ảnh sau OK phải hủy approval/shot.
- Nối `dialogue_text` shot phải bằng transcript gốc, duration thuộc 4/6/8/10 và <=10.
- Backup ZIP có manifest/source/panel assets; restore tạo project mới.

## Gate D — Đoạn 12–15 (Flow, có thể tốn phí)
- Extension off/on, project thiếu/đúng: preflight phản ánh chính xác.
- Chưa tick `confirm_paid` phải bị 409.
- Sau anh duyệt, tạo đúng một shot và kiểm tra idempotency cùng key không submit lần hai.
- Poll tới lúc lưu MP4 local hoặc log chính xác lỗi Flow. Kiểm tra lời thoại, đúng người nói, lip-sync và nhân vật.
- Reject/approve shot; register/retry riêng shot lỗi. Chỉ assemble khi toàn bộ shot APPROVED.
- Mở MP4 ghép, kiểm tra thứ tự, audio và 9:16.

## Gate E — Đoạn 16
- Tắt/mở lại app, restore backup, fresh install trên máy khác.
- Kiểm tra dữ liệu/source không nằm trong git status.
- Fetch upstream FlowKit, xem diff trước merge và chạy lại Gate A–D tương ứng.
