# ComicReels | Tài liệu phát triển

> Trạng thái: **Phân đoạn 1, nền tảng và tài liệu**. Đây là một fork công khai của [FlowKit](https://github.com/crisng95/flowkit), **chưa** có tính năng ComicReels chạy được. Tài liệu này không đồng nghĩa với việc đã tạo ảnh/video.

## Mục tiêu
Anh dán ảnh truyện nhiều khung → hệ thống phân tích và lưu lời thoại/người nói → tách từng khung, xóa chữ có kiểm soát, tạo ảnh 9:16 giữ nguyên phần tranh gốc → anh duyệt đúng phiên bản ảnh (`OK`) → sinh prompt/shot <=10 giây khóa thoại → xuất thủ công hoặc tạo video qua FlowKit sau khi anh yêu cầu → xem, sửa riêng cảnh lỗi và ghép thành Reel.

## Đọc theo thứ tự
- [Đặc tả nghiệp vụ](PRODUCT.md)
- [Kiến trúc và hợp đồng dữ liệu](ARCHITECTURE.md)
- [Chất lượng và kiểm thử](QUALITY.md)
- [Lộ trình và các cửa nghiệm thu](ROADMAP.md)
- [Rủi ro và quyết định](RISKS.md)
- [Báo cáo Phân đoạn 1](FOUNDATION.md)
- [Tổng quan tiếng Việt, tài liệu nền](06-TONG-QUAN-TIENG-VIET.md)
- [Lộ trình 17 phân đoạn, tài liệu nền](07-LO-TRINH-CHIA-NHO-TIENG-VIET.md)

## Phạm vi và nguồn
- Upstream: `crisng95/flowkit`, commit gốc đã đối chiếu `e6407be45ce5640b20600c50ef259224fb7efe49`, nhánh `main`.
- Giữ nguyên mã nguồn, `LICENSE`, README và hướng dẫn FlowKit hiện có trong nhánh này.
- Mọi tính năng mới thuộc ComicReels sẽ nằm trong phân đoạn được anh duyệt sau này, không được coi là có sẵn từ FlowKit.
- Không commit ảnh truyện cá nhân, cookie/token, khóa API hoặc đầu ra có bản quyền không có quyền chia sẻ vào repo public.

## Quy tắc làm việc
Một lần anh nhắn `OK` chỉ cho phép **một** phân đoạn kế tiếp. Kết thúc phải báo đường dẫn nhánh/PR/commit, danh sách file đổi, kiểm thử đã chạy/chưa chạy, vướng mắc, tiêu chí nghiệm thu rồi **dừng**. Không tự merge, không chạy tác vụ Flow tốn phí, không tiếp tục phân đoạn khác khi chưa có OK.
