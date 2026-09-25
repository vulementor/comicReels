# Kế hoạch phát triển chia phân đoạn, dừng chờ anh duyệt

**Quy tắc chung:** Mỗi lần anh xác nhận `OK` chỉ cho phép làm **một phân đoạn kế tiếp**. Hoàn thành xong phải báo kết quả thực tế, file/commit đã đổi, cách anh tự kiểm tra, test đã chạy/chưa chạy, lỗi tồn tại và đề xuất **đúng một** bước tiếp. Chưa có OK thì không làm bước mới. Nếu bước quá lớn, chia tiếp thành bước a/b rồi dừng xin OK. Không dùng việc “sắp hoàn thành” thay cho kết quả đã kiểm chứng.

| Đoạn | Chỉ thực hiện việc gì | Điều kiện nghiệm thu để dừng |
|---|---|---|
| 0 | Đặc tả và quyết định mô hình repo | Có tài liệu, nhận diện vướng mắc fork/public/private; **chưa** sửa repo |
| 1 | Chuẩn bị mã nguồn nền FlowKit | Tạo fork công khai hoặc nhập đủ lịch sử vào repo private theo lựa chọn đã duyệt; giữ MIT, ghi upstream SHA; backend/dashboard bản gốc chạy thử; đưa tài liệu vào repo; **chưa** viết bộ tách khung |
| 2 | Khởi động và khung giao diện | Mở ứng dụng dễ dùng trên Windows sau thiết lập lần đầu; giao diện tiếng Việt có vùng Dán ảnh; báo đúng trạng thái Google Flow |
| 3 | Nhập ảnh nguồn | Ctrl+V/kéo thả PNG/JPG/WebP, kiểm tra loại/kích thước, lưu ảnh gốc, tạo ID dự án, tránh gửi hai lần |
| 4 | Tách khung thô | Nhận diện hộp vùng khung, thứ tự đọc, hiển thị overlay và cho phép anh sửa vùng cắt/thứ tự; fixture có 2/3/4/>4 khung |
| 5 | Ghi thoại và gán người nói | Lưu nguyên văn tiếng Việt, ID người nói, thứ tự lời thoại, giao diện sửa lỗi; trường hợp mơ hồ phải hiện cảnh báo |
| 6 | Cắt ảnh và mask | Cắt ảnh không vẽ lại, tạo vùng mask chữ/bong bóng, đo pixel vùng bảo vệ không đổi |
| 7 | Xóa chữ có kiểm soát | Tích hợp chỉnh sửa vùng mask, ghép lại với ảnh gốc, tạo lại riêng một khung, đánh dấu vùng bị che mất hình gốc |
| 8 | Tạo ảnh dọc | Từ ảnh sạch thành mỗi khung một ảnh 9:16; giữ nguyên vùng tranh gốc, kiểm tra không cắt nhân vật/đạo cụ |
| 9 | Duyệt ảnh | Gallery trước/sau, nút sửa riêng từng khung, nút OK có khóa phiên bản; sửa ảnh phải hủy duyệt của khung tương ứng; cấm viết prompt nếu chưa duyệt |
| 10 | Chia shot và khóa thoại | Giữ nguyên mỗi ký tự thoại đã duyệt, ánh xạ ID người nói, mỗi shot <=10 giây và đúng độ dài model hỗ trợ; thoại dài tự tách nhiều shot |
| 11 | Prompt và xuất thủ công | Tạo prompt hành động, biểu cảm, khẩu hình và nhịp; giao diện sao chép prompt/tải ảnh và manifest cho Google Flow; chưa cần automation video |
| 12 | Cầu nối FlowKit | Kiểm tra đăng nhập, tab Flow, extension, project UUID, model/time mode; báo lỗi tiếng Việt và không tự hạ cấp sang mode khác |
| 13 | Kiểm chứng **một** video | Anh chủ động phê duyệt chi phí và nhấn tạo; upload một ảnh đã duyệt, tạo đúng một shot, lưu file video bền vững, kiểm tra thông tin thất bại nếu có |
| 14 | Hàng đợi nhiều shot | Tạo loạt theo thao tác anh chọn; không gọi trùng có phí, tách retry theo shot, theo dõi tiến trình/cost |
| 15 | Kiểm duyệt và ghép video | Đối chiếu thoại/nhân vật bằng công cụ hỗ trợ + anh nghe xem; lỗi được tạo lại riêng; chỉ ghép các shot đạt yêu cầu |
| 16 | Đóng gói và bảo trì | Hướng dẫn sử dụng, cách backup, phục hồi kết nối, kiểm tra cập nhật upstream, checklist bản phát hành |

## Checkpoint chính thức
Đoạn 0/1 đã được anh đồng ý cho chuyển bước, vẫn thiếu kiểm thử runtime; Đoạn 2 có PR #2 đang chờ nghiệm thu kỹ thuật và anh duyệt; Đoạn 3–16 chưa được phép triển khai. PR #1/#2 vẫn Draft, chưa merge vào main. Xem [CHECKPOINTS.md](CHECKPOINTS.md) và [đặc tả từng đoạn](stages/).

## Mẫu báo cáo kết thúc một đoạn
- Phạm vi đã được anh duyệt; những gì thực sự hoàn thành.
- Nhánh/commit hoặc đường dẫn hiện vật, kèm những file thay đổi.
- Lệnh kiểm thử và kết quả chính xác; phần chưa kiểm thử.
- Minh chứng trực quan/chạy được khi có thể.
- Vấn đề còn lại, rủi ro bảo mật và chi phí.
- Đề xuất **một** phân đoạn tiếp theo; dừng chờ anh nhắn `OK`.