# ComicReels: Đặc tả ý tưởng và trải nghiệm người dùng

**Trạng thái:** Đã fork công khai từ `crisng95/flowkit`; tài liệu mô tả chức năng dự kiến, chưa phải tính năng đã lập trình hoặc kiểm thử.

## 1. Mục tiêu của anh
Anh dán một tấm truyện tranh chứa 2, 3, 4 hoặc nhiều khung. ComicReels phải tự hiểu trình tự truyện, tình huống gây cười, nhận diện nhân vật và ghi lại nguyên văn thoại. Ứng dụng tách thành từng khung rồi tạo mỗi khung một ảnh **bối cảnh dọc 9:16, không chữ**, giữ đúng nhân vật, bối cảnh, phong cách và tỷ lệ gốc. Anh xem ảnh, có thể sửa riêng một khung, và **chỉ khi anh nhấn OK** thì hệ thống mới viết prompt video. Mỗi shot dài tối đa 10 giây, đúng nhân vật nói, đúng nguyên văn, tại mỗi thời điểm chỉ một người nói; người không nói phải ngậm miệng. Từ ảnh và prompt đã duyệt, anh có thể tự đưa sang Google Flow hoặc chọn chế độ tự động thông qua FlowKit. Kết quả video phải được kiểm tra và cho phép tạo lại riêng cảnh lỗi.

## 2. Quy trình thành phẩm
1. **Dán ảnh:** Ctrl+V hoặc kéo thả. Tạo dự án và lưu ảnh gốc bất biến.
2. **Phân tích:** Tìm ranh giới khung, thứ tự đọc, nhân vật, bong bóng thoại, câu thoại và người nói. Anh có thể chỉnh vùng cắt và người nói nếu AI nhận nhầm.
3. **Xử lý ảnh:** Cắt trực tiếp từ ảnh gốc, xóa chữ/bong bóng bằng mask; tái tạo vùng nền bị che nếu cần; giữ các pixel nằm ngoài vùng được phép sửa; mở rộng khung đến 9:16 mà không làm biến dạng nhân vật.
4. **Duyệt ảnh:** Xem trước/sau, sửa từng khung, tải bộ ảnh. Cần anh xác nhận OK cho **đúng phiên bản ảnh hiện tại**; nếu sửa ảnh sau đó phải duyệt lại ảnh liên quan.
5. **Đạo diễn:** Sử dụng lời thoại đã lưu, gán ID nhân vật ổn định, chia nhiều shot nếu lời thoại dài, tạo prompt về biểu cảm/hành động/nhịp hài. Không sáng tác lời mới, không làm mất thoại để cố nhét vào giới hạn thời lượng.
6. **Sản xuất video:** Cho phép tải ảnh+prompt để làm thủ công trong Google Flow; về sau hỗ trợ nút Tạo video trong ComicReels qua FlowKit, có báo trạng thái, dự kiến tín dụng và tạo lại một shot.
7. **Kiểm duyệt thành phẩm:** Nghe và xem đúng người nói, thoại, khẩu hình, biểu cảm, nền và nhịp hài; sau đó ghép thành video dọc. Prompt chuẩn không tự động bảo đảm video do AI tạo ra sẽ chuẩn.

## 3. Những gì tuyệt đối không được tự thay đổi
- Không thiết kế lại nhân vật, đổi trang phục, màu sắc, tỷ lệ, đường nét hoặc đạo cụ vốn có.
- Không đổi nội dung hoặc thứ tự thoại, không đổi người nói, không tự thêm giọng thuyết minh.
- Không tự ý tạo prompt video **trước OK duyệt ảnh**.
- Không tự ý tạo video có tính phí hoặc âm thầm tạo lại hàng loạt video.
- Không báo hoàn thành khi có ảnh hỏng hoặc video chưa kiểm tra, dù Google Flow trả về kết quả.

## 4. Hiểu đúng về “giữ nguyên tuyệt đối”
Vùng hình gốc không bị chữ che có thể được bảo toàn chính xác theo từng pixel bằng cách cắt/ghép ảnh truyền thống. Phần tranh vốn bị bong bóng thoại che khuất là dữ liệu không tồn tại trong ảnh nguồn, AI chỉ có thể dự đoán; cần tô rõ vùng được AI tái tạo và để anh duyệt. Khi mở rộng 9:16, chỉ thêm nội dung ngoài vùng ảnh gốc, không cho AI dựng lại nhân vật. Nếu ảnh gốc thiếu dữ liệu quá nhiều, hiển thị lựa chọn nền đơn giản thay vì bịa chi tiết.

## 5. Giao diện mục tiêu
Một trang làm việc tiếng Việt với vùng Dán ảnh ở đầu trang, danh sách ảnh dọc theo thứ tự khung, nút Sửa ảnh này/Tải ảnh, nút OK duyệt ảnh, sau đó mới mở khóa tab Prompt và Video. Thanh trạng thái Google Flow không được cản trở quy trình xử lý ảnh: nếu mất kết nối Flow, người dùng vẫn tạo ảnh và xuất prompt thủ công được. Một lần cài đặt kỹ thuật ban đầu được chấp nhận; sử dụng thường ngày không đòi gõ lệnh.

## 6. Trường hợp khó cần hỗ trợ
Khung truyện không có đường viền, khung chồng nhau, chữ ngoài bong bóng, hai người trong một khung, nhân vật đổi vị trí trái/phải, thoại nhiều hơn 10 giây, bong bóng che mắt/mặt nhân vật, cảnh không thể mở rộng mà không thêm nền, âm thanh AI đọc sai tiếng Việt và video cử động nhầm miệng người nghe. Mọi trường hợp chưa chắc chắn phải được thông báo, có phương án sửa cụ thể.