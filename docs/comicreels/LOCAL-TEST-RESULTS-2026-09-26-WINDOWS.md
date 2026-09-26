# ComicReels — gate offline và UI smoke trên VULE-PC, 26/09/2026

## Phạm vi và môi trường

Người dùng đã xác nhận code và yêu cầu chuyển toàn bộ local test từ Mac sang VULE-PC. Gate offline chạy trên Windows qua Remote Desktop Commander, trong bản sao source riêng để không dùng DB/ảnh của ứng dụng đang chạy. Sau khi người dùng OK bước 3, UI smoke chạy trên app hiện có và cửa sổ Chrome đã đăng nhập trên VULE-PC.

- Nhánh: `feature/comicreels-segments-03-16`, Draft PR #3, chưa merge.
- Revision ban đầu: `dcb0aa0965ffa7ade43ccbce40557e6fc843d993`.
- Kết quả unit cuối và UI smoke áp dụng revision `8c3dfcb7e5da04fb9a86e6f60740c16990c1f7a6`, gồm bản sửa Windows.
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

## Bước 3 — UI smoke trực tiếp, 17:11–17:22 +07

Điều khiển Chrome hiện có bằng Windows UI Automation và bàn phím/chuột qua Remote Desktop Commander, đọc cây giao diện và xem ảnh chụp thực tế. Không dùng kết quả HTTP 200 để thay cho kiểm tra render/tương tác. Không mở profile Chrome mới hoặc yêu cầu đăng nhập lại.

| Kiểm tra | Kết quả |
| --- | --- |
| Sidebar FlowKit | Mở được Dashboard, Projects, Gallery, Logs, Guide, Settings; bố cục và nội dung hiển thị |
| Kết nối trong UI | `WS LIVE`, extension connected; Guide hiển thị agent 1.3.1 và extension đã nối |
| Projects/detail/videos/pipeline | Bấm thẻ dự án, mở Overview, Videos và Pipeline; thấy đủ REFS/IMAGES/VIDEOS/UPSCALE; đổi sang VIDEOS và mở bảng chi tiết cảnh |
| Mẫu kiểm tra core | Một project/video/scene tạm chỉ trong DB local, không tạo Flow project; đã xóa sau kiểm tra, core trở về 0 project, 0 request |
| ComicReels | Mở qua sidebar; mở dự án đã lưu với 3 khung, gallery có trạng thái duyệt; màn video hiển thị đủ 3 ảnh reference |
| Chuyển core/ComicReels | Link Dashboard FlowKit và Mở Projects & công cụ video hoạt động; quay lại ComicReels tự mở dự án gần nhất |
| Reload | Tải lại trang vẫn mở đúng dự án, đủ 3 ảnh; preset hiển thị Omni Flash/10s/360p/1 phiên bản; nút tạo chưa được bật khi chưa xác nhận chi phí |
| Tác vụ ngoài | 0 yêu cầu tạo ảnh/video mới; không bấm Retry stage hoặc chạy pipeline |

Bằng chứng nằm tại `local-test-data/checks-20260926-1640` trên VULE-PC: ảnh/cây UI `ui-01` đến `ui-20`, manifest mẫu tạm và `STAGE-3-UI-RESULT.json`. Ảnh chụp và dữ liệu dự án không đưa lên repo public. Những trang core không có dữ liệu sản xuất được kiểm tra ở trạng thái rỗng hoặc bằng mẫu tạm; kết quả này không chứng minh một lượt render Flow thành công. Không thay đổi source sản phẩm trong bước 3.

## Còn chờ nghiệm thu

- Bước 4: tải từng ảnh cũ và đối chiếu khung gốc/ảnh 9:16; bước 5: kiểm tra duyệt và nội dung kịch bản.
- Xác nhận đúng Flow project, ba ảnh reference, kịch bản, preset Omni Flash/10s/360p/1 bản trước một lượt tạo có phí.
- Video thật, thoại/giọng/lip-sync, tải file, duyệt/tạo lại và ghép.

Không gửi yêu cầu tạo ảnh/video mới trong gate offline. Bằng chứng XML và log đầy đủ được giữ trong `local-test-data/checks-20260926-1640` trên PC; không đưa dữ liệu dự án hoặc profile đăng nhập lên GitHub.
