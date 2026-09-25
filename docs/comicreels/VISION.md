# Ý tưởng, hành trình và ranh giới ComicReels

## Đầu bài của anh
Dán **một ảnh truyện** có 2/3/4/nhiều khung. Tự tìm thứ tự đọc và lưu nguyên văn thoại + ID người nói **trước** khi xóa chữ. Cắt ra **mỗi khung một ảnh không chữ 9:16**; giữ nét vẽ, nhân vật, biểu cảm, màu, bối cảnh, props và phần pixel gốc; anh xem/sửa riêng từng ảnh rồi nhấn `OK` cho version cụ thể. Chỉ **sau OK** mới chia shot <=10 giây, sinh prompt đúng người nói và có thể tự xuất sang Google Flow thủ công. Tạo video tự động qua FlowKit chỉ khi anh chủ động cho phép phí, cần QA khẩu hình và giọng từng shot, lỗi nào tạo lại shot đó.

## Tính đúng trước tiện lợi
- Không tự đổi nhân vật, thoại nguyên văn, thêm narrator, rút ngắn thoại cho vừa 10 giây hoặc bắt người nghe cử động miệng.
- Không giả định truyện đều là Câu/Mèo Léo; nhân vật theo từng ảnh input.
- Pixel ngoài vùng mask giữ nguyên; chỗ ảnh bị bong bóng che không có dữ liệu thật, AI tái tạo chỉ là phỏng đoán phải đánh dấu cho anh duyệt.
- Mở rộng 9:16 bằng canvas/padding/outpaint **ngoài nguồn**, không biến yêu cầu giữ nguyên thành tạo tranh mới.
- Prompt đúng chưa bảo đảm video sinh ra đúng phát âm/lip-sync: phải xem và nghe thực tế.

## MVP và ngoài phạm vi
MVP kết thúc ở ảnh 9:16 được duyệt, transcript và speaker mapping đã xác minh, shot plan + prompt và xuất thủ công. Tích hợp Flow có phí, video batch, ghép và đóng gói là các đoạn riêng. Tận dụng nền FastAPI/React/Chrome Extension của FlowKit, không viết lại toàn app và không âm thầm đăng YouTube.

## Bảo mật
Ảnh truyện, bản audio/video, cookie, token và dữ liệu riêng không commit lên public fork. Mọi chi phí Google Flow cần bấm lệnh có thông tin rõ, không tự chạy retry cả loạt.
