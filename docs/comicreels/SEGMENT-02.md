# Phân đoạn 2: Khung giao diện ComicReels Studio

## Phạm vi đã triển khai
- Trang mặc định `/` và `/comicreels` mở giao diện ComicReels tiếng Việt; bảng điều khiển FlowKit gốc vẫn ở `/flowkit` cùng các đường dẫn quản trị cũ.
- Dán ảnh qua Ctrl+V, kéo thả hoặc chọn file PNG/JPG/WebP <=20 MB; xem trước và bỏ/đổi ảnh ngay trên trình duyệt. **Không gửi ảnh lên server, không lưu dự án, không gọi AI**. Phân đoạn 3 mới triển khai nhập/lưu ảnh nguồn.
- Trạng thái phân biệt backend offline, Chrome Extension chưa kết nối, phiên Flow chưa xác thực/chưa có project và sẵn sàng; đọc `/health` và `/api/flow/status`, cập nhật định kỳ và có nút kiểm tra lại. Khi lỗi kết nối vẫn xem trước ảnh bình thường.
- Các bước tách ảnh, duyệt ảnh, tạo prompt/video chỉ hiển thị trạng thái chưa khả dụng, không có nút giả khiến anh tưởng đã chạy.

## Chạy local (theo README FlowKit gốc)
1. Cài Python 3.10+, Node/npm, Chrome và ffmpeg. Trên Windows có thể dùng WSL theo hướng dẫn upstream.
2. Chạy `python -m pip install -r requirements.txt` ở thư mục gốc; khởi động backend `python -m agent.main`.
3. Trong `dashboard/`, chạy `npm install` và `npm run dev`; mở `http://localhost:5173/` để dùng giao diện ComicReels.
4. Nếu muốn kiểm tra kết nối Flow, tải Chrome Extension từ `extension/`, mở `https://flow.google.com/`, đăng nhập và chọn/tạo một project trong UI, thiết lập `FLOW_PROJECT_ID` theo README upstream. Không cần kết nối Flow chỉ để xem trước ảnh.
5. Kiểm tra `http://127.0.0.1:8100/health` có `status: ok`; kiểm tra `/api/flow/status` khi extension đã kết nối.

## Kiểm tra nghiệm thu thủ công
- Dán PNG/JPG/WebP và kéo thả cho xem trước ảnh đúng; thay thế/bỏ ảnh được. Tệp khác loại, trống hoặc >20 MB bị từ chối; ảnh cũ không bị thay thế khi chọn file sai.
- Khi backend tắt, giao diện báo máy chủ chưa hoạt động và vẫn xem trước ảnh; khi bật backend nhưng tắt extension, báo extension chưa kết nối; chỉ báo sẵn sàng khi trạng thái thực tế có authenticated + flow_project_id.
- Tab quản trị FlowKit gốc còn mở ở `/flowkit`, các trang khác không bị sửa.
- Chưa có lời thoại, phân tích, tách khung, xóa chữ, API lưu ảnh, sinh prompt hoặc yêu cầu tạo video có phí.

## Giới hạn môi trường nghiệm thu
Đã viết code trên GitHub; trạng thái build/test thực tế và CI sẽ được báo sau khi kiểm tra. Chưa thử dùng trình duyệt đăng nhập Google Flow của anh và không phát sinh tín dụng.
