# Ý tưởng, hành trình và ranh giới ComicReels

## Đầu bài của anh
Dán **một ảnh truyện** có 2/3/4/nhiều khung. Tự tìm thứ tự đọc và lưu nguyên văn thoại + ID người nói **trước** khi xóa chữ. Cắt ra **mỗi khung một ảnh không chữ 9:16**; giữ nét vẽ, nhân vật, biểu cảm, màu, bối cảnh, props và phần pixel gốc; anh xem/sửa riêng từng ảnh rồi nhấn `OK` cho version cụ thể. Chỉ **sau OK** mới chia shot <=10 giây, sinh prompt đúng người nói và có thể tự xuất sang Google Flow thủ công. Tạo video tự động qua FlowKit chỉ khi anh chủ động cho phép phí, cần QA khẩu hình và giọng từng shot, lỗi nào tạo lại shot đó.

## Tính đúng trước tiện lợi
- Không tự đổi nhân vật, thoại nguyên văn, thêm narrator, rút ngắn thoại cho vừa 10 giây hoặc bắt người nghe cử động miệng.
- Không giả định truyện đều là Câu/Mèo Léo; nhân vật theo từng ảnh input.
- AI phải tự nhận panel, thứ tự đọc, nguyên văn thoại, speaker và toàn bộ vùng chữ/bong bóng cần xóa; người dùng chỉ sửa khi AI nhận sai.
- Ảnh sạch 9:16 là kết quả **AI Generate**: AI xóa text/bubble, tái tạo phần tranh bị che và outpaint thành 9:16. Không dùng compositor tô rectangle/padding làm đầu ra chính.
- Sau khi AI Generate, hệ thống ghép trả các pixel nguồn không thuộc vùng AI-edit để khóa nhân vật/nét vẽ/bố cục gốc ở mức deterministic.
- Chỗ bong bóng che mất dữ liệu gốc là phần AI phải tái tạo và luôn cần anh review trước khi OK.
- Prompt đúng chưa bảo đảm video sinh ra đúng phát âm/lip-sync: phải xem và nghe thực tế.

## MVP và ngoài phạm vi
MVP kết thúc ở ảnh 9:16 được duyệt, transcript và speaker mapping đã xác minh, shot plan + prompt và xuất thủ công. Tích hợp Flow có phí, video batch, ghép và đóng gói là các đoạn riêng. Tận dụng nền FastAPI/React/Chrome Extension của FlowKit, không viết lại toàn app và không âm thầm đăng YouTube.

## Bảo mật
Ảnh truyện, bản audio/video, cookie, token và dữ liệu riêng không commit lên public fork. Mọi chi phí Google Flow cần bấm lệnh có thông tin rõ, không tự chạy retry cả loạt.
