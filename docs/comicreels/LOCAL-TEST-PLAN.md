# Kế hoạch test local sau khi anh xác nhận code

**Chưa chạy trong vòng code 26/09/2026.** Chỉ bắt đầu bằng Remote Desktop Commander sau khi anh xác nhận xong. Làm từng bước nhỏ, báo kết quả và đợi anh OK trước bước tiếp theo.

1. **Đối chiếu revision và dữ liệu.** Kiểm tra commit nhánh PR #3, giữ lại DB/ảnh/video hiện tại; dùng runtime cache đã có, không xóa dữ liệu. Không tạo Chrome/profile mới. Giữ extension và Chrome đang đăng nhập.
2. **Gate code offline.** Chạy `python -m pytest tests/unit -q`; `npm ci`, `npm run build`, `npm run lint` trong dashboard. Báo kết quả riêng với revision; chưa gửi job ngoài.
3. **FlowKit core.** Mở `/`, Projects/detail/pipeline, Gallery, Logs, Guide, Settings; xác minh các công cụ gốc còn hoạt động. Mở ComicReels qua sidebar, quay lại core và mở lại ComicReels.
4. **Ảnh cũ và trạng thái.** `/api/comicreels/status` trả 200 cả khi extension chưa kết nối; dự án gần nhất và các ảnh đã Generate vẫn hiện. Tải từng ảnh, so với khung gốc; không Generate lại ảnh sẵn có.
5. **Cửa duyệt/kịch bản.** Chưa OK phải chặn; ảnh đã đổi hash phải chặn gửi. Kịch bản dùng lời thoại nguyên văn, đúng người nói; câu dài chia các shot 10s, không cắt bớt. Bấm tạo kịch bản lần nữa không xóa các shot hiện có.
6. **Chuẩn bị một video.** Dùng project/extension có sẵn. Chọn đúng ba ảnh đã duyệt, có ảnh của cảnh đang chọn; xem một kịch bản. Kiểm tra preset Omni Flash/10s/360p/1 bản. Không có bước TTS riêng. Chưa bấm tạo ở bước này.
7. **Một video thật sau khi được duyệt chi phí.** Gửi đúng một lượt. Cùng key/click lặp không phát sinh job thứ hai; các request upload/video chung Flow project. Nếu timeout, chỉ kiểm tra receipt/Flow, không bấm tạo lại tùy tiện.
8. **Poll và review.** Poll tới khi tải MP4; xem/nghe trong UI, tải file, kiểm thoại/giọng/người nói/lip-sync/nét vẽ. Phân biệt FAILED và trạng thái chưa rõ. Mọi thao tác sửa nguồn phải bị chặn khi còn job chưa kết thúc.
9. **Tạo lại shot lỗi nếu anh yêu cầu.** Đánh dấu lỗi; tạo lại riêng shot đó, vẫn 10s/360p/1 bản. Bản cũ không còn được coi là đã duyệt; tab cũ không thể duyệt nhầm bản mới. Không tự chạy batch.
10. **Ghép và khởi động lại.** Chỉ ghép khi mọi video đã xem/nghe và được duyệt. Kiểm tra thứ tự, âm thanh, 9:16; khởi động lại vẫn giữ ảnh/job/video.

Các kiểm tra concurrency/receipt lỗi dùng regression tests offline, không cố tạo job thật chỉ để kiểm lỗi. Không suy ra PASS của bước này từ kết quả lịch sử hoặc từ static review.
