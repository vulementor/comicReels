# Kế hoạch test local ComicReels — CHƯA CHẠY

Tài liệu này chuẩn bị cho lần anh yêu cầu test local. Không mục nào được coi là PASS trước khi chạy trên máy local.

## A. Cài đặt và khởi động
1. Windows có Python 3.10+, Node/npm, Chrome, ffmpeg.
2. Chạy scripts/comicreels_setup.bat.
3. Chạy scripts/comicreels_start.bat; backend /health trả ok, Vite mở trang chủ.
4. Load unpacked extension/, mở flow.google.com và kiểm tra trạng thái Flow.

## B. Workflow ảnh không dùng Flow
1. Import PNG/JPG/WebP, kiểm tra SHA, reload/restart vẫn mở dự án.
2. Truyện mẫu 2/3/4/5+ panel: detector, sửa bbox và reading order.
3. Transcript tiếng Việt, speaker đổi vị trí và bbox bong bóng.
4. Crop + mask + local inpaint: pixel ngoài mask giữ nguyên.
5. Ảnh 9:16 không resize/crop vùng tranh gốc.
6. Sửa panel sau OK phải hủy approval/hash và shot phụ thuộc.
7. Chưa OK thì API plan-shot phải từ chối.

## C. Prompt và xuất thủ công
1. Thoại dài chia shot nhưng nối lại đúng nguyên văn.
2. Mỗi shot <=10 giây và duration model hỗ trợ.
3. Prompt một speaker nói, người khác đóng miệng, không narrator/subtitle.
4. ZIP export có ảnh approved, manifest.json và prompts.md.

## D. Google Flow có phí — chỉ chạy khi anh duyệt riêng
1. Không confirm cost thì request bị từ chối.
2. Tạo đúng một shot trước, kiểm tra upload/operation/file MP4.
3. Test pause/resume, double click/idempotency, cancel QUEUED và retry riêng.
4. Không tự retry job có phí.

## E. Review, ghép và phục hồi
1. Review video cạnh transcript/speaker; APPROVED/REJECTED.
2. Chỉ mọi shot APPROVED mới concat.
3. Backup, restart/restore, kiểm tra hash/transcript/asset/shot.
4. Backup lỗi/path traversal/ZIP lớn phải bị chặn.
5. Đồng bộ upstream trên branch thử nghiệm rồi chạy regression.

## F. Lệnh test dự kiến
- python -m pytest tests/unit -q
- cd dashboard && npm run build
- cd dashboard && npm run lint

Checkpoint phải ghi PASS/FAIL/CHƯA CHẠY cùng log/screenshot. Code có mặt không đồng nghĩa đã test.
