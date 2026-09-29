# Phân đoạn 1: Bản ghi triển khai và điều kiện nghiệm thu

Ngày: 24/09/2026. Phạm vi được duyệt: fork công khai FlowKit thành ComicReels, đưa tài liệu nền vào nhánh riêng, kiểm tra có mã nguồn và giấy phép, kiểm tra baseline nếu có môi trường; **không viết chức năng tách khung, không tạo video, không merge tự động**.

## Kết quả đã xác minh từ GitHub
- `vulementor/comicReels` là repo public và có `fork=true`, `parent=crisng95/flowkit`.
- Cả upstream và fork đều ở SHA `e6407be45ce5640b20600c50ef259224fb7efe49` trước khi thêm tài liệu; cây code cùng SHA và `LICENSE` MIT nguyên bản.
- Nhánh tài liệu `segment/01-foundation` xuất phát từ SHA trên. Danh sách các file đã đổi/CI/PR chỉ được xác nhận sau khi tạo và kiểm tra trên GitHub.

## Cách anh nghiệm thu
Xem PR trên GitHub, kiểm tra nhánh chỉ bổ sung `docs/comicreels/`, không sửa code/runtime/extension/README/LICENSE gốc. Xem kết quả CI nếu đã có; không yêu cầu tài khoản Flow, ảnh riêng, token hoặc phát sinh phí video. Sau báo cáo kết quả, anh nhắn `OK` mới cho phép Đoạn 2.

## Hạn chế môi trường cần báo đúng
GitHub connector truy cập/ghi nội dung được nhưng môi trường shell hiện tại không phân giải DNS `github.com` nên không thể clone repository, khởi động backend hoặc build dashboard trực tiếp tại đây. Repo có workflow `.github/workflows/tests.yml` chạy unit tests khi mở PR; trạng thái CI phải được xem sau khi PR được tạo, không đoán trước. Chrome extension/phiên Google Flow không có trong môi trường này; không có smoke test trả phí.
