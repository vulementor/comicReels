# Rủi ro và các quyết định đã khóa

## Quyết định đã xử lý
- **Công khai:** Anh đồng ý public fork; `vulementor/comicReels` đã là fork chính thức của `crisng95/flowkit` (GitHub metadata, 24/09/2026). Không đổi lại quyền truy cập hoặc xóa repo cũ.
- **Thực hiện từng đoạn:** Anh duyệt `OK` cho **một** đoạn, báo cáo rồi dừng; không tự làm tiếp hoặc merge thay anh.
- **Thứ tự nội dung:** Ảnh gốc -> ghi thoại và speaker -> tách, xóa chữ, tạo 9:16 -> duyệt ảnh OK -> prompt -> video; không đảo thứ tự.

## Rủi ro ảnh/truyện
- Bong bóng che nhân vật: mất dữ liệu thật; inpaint chỉ ước đoán, hiển thị mask và yêu cầu anh duyệt.
- AI làm đổi nét: giới hạn vùng được vẽ lại, ghép nguyên pixel bảo vệ; nếu model/provider không hỗ trợ inpaint có mask đáng tin, không dùng chỉnh sửa toàn cảnh thay thế.
- Nhận diện thoại sai dấu/người nói: lưu transcript bản gốc + bản anh đã xác nhận, gắn speaker_id ổn định; trường hợp không chắc phải khóa bước prompt cho tới khi sửa.
- Ảnh nguồn không vừa tỷ lệ 9:16: pad hoặc outpaint vùng ngoài khung, không crop làm mất nhân vật, so sánh ảnh nguồn sau ghép.

## Rủi ro Google Flow
- FlowKit phụ thuộc phiên Chrome/Flow và transport ứng dụng web có thể thay đổi; có đường xuất ảnh + prompt để dùng thủ công.
- Một số mode Veo chưa được port trong README upstream; không tự fallback sang mode khác mà không thông báo.
- Không lưu token, cookie, ảnh người dùng trong repo public. Backend chỉ bind localhost; nếu chạy remote phải có xác thực và mạng riêng.
- Tín dụng video có chi phí: chỉ tạo khi anh chủ động nhấn, hiển thị ước tính và giới hạn retry; kiểm thử Phân đoạn 1 không tạo video.
- Signed media URL có hạn: lưu nội dung ảnh/video thành file bền vững, không chỉ lưu link.

## Câu hỏi để xử lý ở đúng phân đoạn (không chặn Phân đoạn 1)
- Ở Đoạn 2: cách đóng gói cài đặt Windows (WSL, container hay native) và trạng thái kết nối Flow trên giao diện.
- Ở Đoạn 4-5: chọn provider vision/OCR cho tiếng Việt và quy trình sửa mapping người nói.
- Ở Đoạn 7-8: giải pháp inpaint/outpaint có mask thực sự; đo pixel bị thay đổi trước khi chọn provider.
- Ở Đoạn 12-13: chọn model/mode video thật sự có sẵn trong tài khoản Flow và xin duyệt chi phí thử một shot.
