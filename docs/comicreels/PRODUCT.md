# Đặc tả sản phẩm ComicReels (PRD)

## 1. Kết quả anh cần
Giao diện tiếng Việt đơn giản: dán/Ctrl+V/kéo thả một ảnh có 2/3/4/nhiều khung truyện, tự tách thành số ảnh 9:16 tương ứng không có text và bong bóng thoại. Hiểu mạch truyện, trật tự đọc và cú chốt gây cười; giữ nguyên nhân vật, biểu cảm, bối cảnh, phục trang, đạo cụ, bố cục và nét vẽ trong phần ảnh gốc. Đây là truyện do anh nhập, **không phải** một câu chuyện mới do hệ thống sáng tác.

## 2. Cửa duyệt bắt buộc
Ảnh gốc, lời thoại gốc, tọa độ khung và ảnh sau chỉnh sửa lưu riêng. Trước khi xóa chữ, ghi lại nguyên văn từng câu cùng `panel_id`, `speaker_id` ổn định, thứ tự; trường hợp nhận diện mơ hồ phải để anh sửa. Anh duyệt gallery ảnh qua `OK` **trước khi sinh prompt video**. Duyệt gắn với hash/phiên bản ảnh cụ thể; sửa ảnh thì hủy duyệt và vô hiệu hóa prompt/video phụ thuộc.

## 3. Màn hình và thao tác
1. **Nhập ảnh:** kéo thả, dán, chọn file; trạng thái kết nối Flow không chặn workflow ảnh.
2. **Phân tích:** xem ảnh gốc, hộp ranh giới từng khung; sửa đường cắt, thứ tự, thoại và người nói.
3. **Ảnh bối cảnh:** preview gốc/sau xử lý, mask vùng sửa và từng ảnh 9:16; tạo lại riêng ảnh lỗi, tải một ảnh/toàn bộ.
4. **Duyệt:** nút OK chỉ bật khi không còn lỗi chặn; chưa OK thì tab Prompt và Video bị khóa.
5. **Đạo diễn:** ảnh đã duyệt + lời thoại bất biến, chia nhiều shot khi cần; prompt hành động, biểu cảm, camera, thời điểm và lời thoại đúng nhân vật.
6. **Sản xuất:** xuất ảnh+prompt để dùng thủ công trên Google Flow; tùy chọn gọi FlowKit khi anh chủ động bấm Tạo và đã xem chi phí dự kiến.
7. **Kiểm duyệt:** nghe xem từng shot, đánh dấu sai người nói, khẩu hình, giọng, thoại, nét vẽ; chỉ tạo lại shot lỗi rồi ghép video dọc.

## 4. Quy tắc bất biến
- Đúng một ảnh 9:16 cho mỗi khung gốc; một khung có thể có nhiều shot video. Không thay thế bằng crop mất nhân vật hoặc AI vẽ lại toàn bộ tranh.
- Không tự thêm/xóa/đổi chữ hoặc đổi nhân vật nói, không thêm lời dẫn chuyện, nhạc, người mới; người không nói ngậm miệng.
- Shot tối đa 10 giây và phải chọn thời lượng thực tế model hỗ trợ; thoại dài chia shot thay vì rút gọn/đọc nhanh bất thường. Nếu thoại xong sớm, có thể bổ sung phản ứng im lặng để giữ nhịp hài.
- Vùng pixel gốc ngoài mask và phần mở rộng phải được ghép bảo toàn; nội dung đã bị bong bóng che **không thể** phục hồi đúng tuyệt đối từ ảnh nguồn, phải đánh dấu để anh duyệt.
- Prompt tốt không bảo đảm model video phát âm và lip-sync đúng; sản phẩm phải kiểm tra kết quả, không tự nhận đã đạt.
- Không thực hiện request video có phí nếu anh chưa bấm lệnh rõ ràng. Hạn chế tạo trùng, có retry riêng shot và ước tính tín dụng.

## 5. Ngoài MVP
Chưa bao gồm tự động đăng YouTube, huấn luyện model riêng, voice cloning, đa người dùng/SaaS, kiểm chứng lip-sync tự động tuyệt đối, 4K bắt buộc. MVP kết thúc ở bộ ảnh đã duyệt + prompt và xuất thủ công; tích hợp video tự động thuộc phân đoạn sau.

## 6. Tiêu chí sản phẩm
Kiểm tra truyện có 2/3/4/>4 khung, bố cục dọc/ngang/lệch; không lẫn người nói dù hai nhân vật đổi vị trí; thoại lưu đủ và có thể sửa; từng vùng tranh bảo vệ khớp ảnh gốc; không vượt cửa OK; cảnh lỗi tạo lại riêng; người không biết code dùng được sau lần cài đặt đầu.
