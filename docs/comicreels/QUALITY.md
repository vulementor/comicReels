# Chất lượng, bảo mật và kế hoạch kiểm thử

## Cấp kiểm thử
- Unit: kiểm tra crop bằng bbox, thứ tự đọc, phiên bản/sha256 và gate OK; bảo đảm dialogue verbatim, speaker_id và phân bổ shot <=10s; sửa một panel chỉ vô hiệu hóa shot thuộc panel đó.
- Pixel-preservation: so sánh ảnh đầu ra với vùng source không nằm trong mask ở cùng tọa độ, không chỉ nhìn bằng mắt. Resize ảnh gốc để nhét 9:16 không được coi là pixel-identical; canvas mở rộng/padding phải không phá tỷ lệ/nhân vật.
- Contract/integration: API upload ảnh, dự trữ file trên máy backend, lỗi mất tab Flow, project id thiếu, model không hỗ trợ, URL signed hết hạn, retry chống request có phí trùng.
- Manual creator acceptance: truyện 2/3/4/5+ khung, vùng không viền/chồng, chữ ngoài bóng, bong bóng che mặt, thoại dài/đổi vị trí, tiếng Việt nhiều dấu và cảnh im lặng giữ nhịp gây cười.

## Test fixtures công khai
Chỉ commit ảnh mẫu do dự án tự tạo/có quyền dùng. Không commit truyện riêng của anh, dữ liệu login, API key, voice samples. Có fixture tiêu chuẩn với bbox, thứ tự, lời thoại gốc, speaker mapping và mask kỳ vọng.

## Cửa chất lượng
1. Không mất ảnh gốc và thoại trước khi xóa chữ.
2. Không tạo prompt trước khi tất cả phiên bản ảnh liên quan được anh duyệt OK.
3. Không âm thầm thay đổi người nói, câu thoại hoặc model mode.
4. Mỗi shot <=10 giây, lời thoại dài tách và nối chính xác.
5. Video phải xem/nghe được; nhận diện lỗi tự động chỉ hỗ trợ, không thay sự duyệt cuối của anh.

## Phân đoạn 1: giới hạn xác minh
Fork phải có cùng upstream commit gốc, LICENSE giữ nguyên và PR docs-only. Kiểm tra CI unit tests Python 3.10/3.13 nếu GitHub Actions thực sự chạy. Không tuyên bố đã build dashboard hoặc mở Flow tab nếu không chạy được; tuyệt đối không phát sinh chi phí video khi kiểm tra nền.
