# ComicReels — gate offline trên VULE-PC, 26/09/2026

## Phạm vi và môi trường

Người dùng đã xác nhận code và yêu cầu chuyển toàn bộ local test từ Mac sang VULE-PC. Các lệnh dưới đây chạy trên Windows qua Remote Desktop Commander, trong bản sao source riêng để không dùng DB/ảnh của ứng dụng đang chạy.

- Nhánh: `feature/comicreels-segments-03-16`, Draft PR #3, chưa merge.
- Revision ban đầu: `dcb0aa0965ffa7ade43ccbce40557e6fc843d993`.
- Kết quả unit cuối áp dụng revision đó cộng bản sửa Windows trong cùng commit với báo cáo này.
- Windows 10, Python 3.12.7, Node 24.13.0, npm 11.6.2; GPT FullProxy pin `3955affe4de62921398599de70edfa8addfefcf4`.
- Source nằm trong thư mục test do người dùng chọn; runtime, dependencies và bản sao kiểm thử nằm ngoài OneDrive.

## Kết quả

| Kiểm tra | Kết quả |
| --- | --- |
| Chuyển dữ liệu từ Mac | 30 file khớp SHA-256; SQLite integrity OK; chỉ đổi 13 đường dẫn sang Windows |
| Dự án đang dùng | 3 ảnh giữ trạng thái duyệt và đúng hash; 3 kịch bản READY; API trả đúng 3 ảnh |
| Extension | 0.3.2, một kết nối, `flow_url_supported=true` |
| ChatGPT | GPT FullProxy ghi nhận authenticated lúc 16:36:40 +07; dùng lại profile đã có trên PC |
| `python -m pytest tests/unit -q --tb=short` trước sửa | 442 PASS, 17 FAIL |
| Regression tái hiện trước sửa code | 1 FAIL do symlink bị từ chối; 7 kiểm tra prompt/path PASS sau sửa giả định Unix trong test |
| `python -m pytest tests/unit -q --tb=short` sau sửa | **460 PASS**, 35.60 giây, exit 0 |
| `npm ci` | PASS, exit 0 |
| `npm run build` | PASS, exit 0; cảnh báo bundle lớn hơn 500 kB |
| `npm run lint` | PASS, exit 0 |

Build/lint chạy trên frontend của `dcb0aa0`. Bản sửa Windows chỉ thay Python review engine, hai file unit test và tài liệu; không đổi frontend hoặc lockfile.

## Lỗi đã sửa

1. Review video dùng symlink để đánh số lại các frame được chọn. Windows từ chối thao tác đó với `WinError 1314`, làm hỏng 14 kiểm tra trích frame/tạo contact sheet. Nếu symlink không khả dụng, engine sao chép đúng bytes của frame sang tên tuần tự; không yêu cầu quyền quản trị. File đích đã tồn tại vẫn báo lỗi. Regression kiểm tra đủ 20 frame lấy mẫu trong 3 sheet, kể cả khi ép từ chối symlink.
2. Ba assertion trong kiểm tra prompt CLI mặc định dấu `/` của Unix. Chúng nay kiểm tra đúng đường dẫn theo `Path` của hệ điều hành; không sửa nội dung prompt sản phẩm để chiều test.

FFmpeg trên máy này không tải được cấu hình font mặc định cho drawtext. Cơ chế fallback hiện có tạo contact sheet không đóng timestamp và truyền trạng thái đó cho prompt review; các kiểm tra fallback đạt. Chưa đánh giá chất lượng review bằng model thật.

## Còn chờ nghiệm thu

- Kiểm tra UI FlowKit core và thao tác ComicReels trên browser đã đăng nhập.
- Xác nhận đúng Flow project, ba ảnh reference, kịch bản, preset Omni Flash/10s/360p/1 bản trước một lượt tạo có phí.
- Video thật, thoại/giọng/lip-sync, tải file, duyệt/tạo lại và ghép.

Không gửi yêu cầu tạo ảnh/video mới trong gate offline. Bằng chứng XML và log đầy đủ được giữ trong `local-test-data/checks-20260926-1640` trên PC; không đưa dữ liệu dự án hoặc profile đăng nhập lên GitHub.
