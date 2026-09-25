# IMPLEMENTATION 03–16 | Ma trận code đã hoàn thành, test local đang chờ

Đây là bản bàn giao code trước vòng kiểm thử local. Mục tiêu là giúp anh nhìn nhanh mỗi phân đoạn nằm ở đâu.

| Đoạn | Backend | Frontend / vận hành |
|---|---|---|
| 3 | POST /api/comicreels/projects/import, ComicStore, SHA-256, source file | Import từ paste/drag/file, mở lại project |
| 4 | detect_panels, Vision/manual analysis, PATCH bbox | Chỉnh x/y/w/h, heuristic/Vision selection |
| 5 | comic_dialogue, multi CRUD, Vision speaker IDs | Nhiều câu/speaker theo thứ tự, lưu/xóa |
| 6 | crop_panel, mask model | Mask JSON per panel, crop asset |
| 7 | clean_with_rect_masks | Before/clean asset và regenerate panel |
| 8 | portrait_9_16, protected region + hash | Nút tạo 9:16 |
| 9 | SHA approval + dependency invalidation | OK từng ảnh, trạng thái đúng version |
| 10 | build_shots, exact substring, supported durations | Shot cards + duration/speaker |
| 11 | video_prompt, backup ZIP | Copy prompt / Backup |
| 12 | /flow/preflight, /comicreels/status | Extension/project readiness |
| 13 | /shots/{id}/generate, /poll, video persistence | Paid consent + tạo một shot + poll |
| 14 | /generate-batch + idempotency/error isolation | Batch API có sẵn; UI cố ý không có nút one-click trước local test |
| 15 | review API, register video, ffmpeg assemble | Approve/Reject shot + ghép khi tất cả đạt |
| 16 | backup/restore, launcher scripts | PowerShell/WSL launcher + LOCAL-TEST-PLAN |

## Những điểm cố ý bảo thủ
1. Xóa chữ: code hiện dùng compositor local theo mask, giữ chính xác pixel ngoài mask. Nó chưa hứa khôi phục chi tiết bị speech bubble che. Test local sẽ quyết định có cần provider inpaint khác.
2. 9:16: code tạo canvas không resize tranh gốc. Chưa bật generative outpaint toàn ảnh vì điều đó có thể làm biến dạng nhân vật. Có thể nâng cấp sau khi kiểm chứng pixel lock.
3. Vision: chỉ gửi ảnh ra Anthropic khi caller chọn mode=vision và có API key; heuristic/manual vẫn offline.
4. Google Flow: không auto-submit. Single/batch endpoints đều yêu cầu confirm_paid, và UI single-shot yêu cầu checkbox.
5. Batch: API hoàn thiện nhưng UI chưa bật “tạo tất cả” để ngăn chi phí hàng loạt trước khi single-shot local test pass.

## Cần xác minh trong vòng local test
Xem LOCAL-TEST-PLAN.md. Đặc biệt cần kiểm tra response thực tế của Google Flow upload/poll sau migration, ffmpeg concat trên Windows/WSL, chất lượng gutter detection và mask compositor trên các comic thực.
