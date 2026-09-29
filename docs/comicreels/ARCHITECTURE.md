# Kiến trúc đề xuất, chưa triển khai

## Ranh giới
Giữ nguyên FlowKit: `agent/` (FastAPI, SQLite, SDK, queue/polling, image/video endpoints), `dashboard/` (React), `extension/` (cầu nối trình duyệt với Google Flow), `tests/` và các công cụ ghép video. Trên nhánh Phân đoạn 1 **chỉ bổ sung tài liệu**; code bên dưới là thiết kế dự kiến.

```text
ComicReels Studio (React, Việt hóa)
  -> Comic API (FastAPI: ingest, panels, dialogue, image, approval, director)
       -> Immutable source + SQLite metadata + local durable assets
       -> Panel crop & mask (Pillow/OpenCV, no redraw of kept pixels)
       -> Restricted inpaint/outpaint adapter (source+mask+references)
       -> Approval/shot planner with dialogue+speaker lock
       -> FlowKit adapter (existing REST/SDK) -> signed-in Chrome Flow bridge
       -> Video review/concat/export
```

## Dữ liệu dự kiến
`ComicProject(id, source_path, source_sha256, flow_project_id?, status)`; `Panel(id, project_id, bbox, order, source_crop, text_mask, protected_mask, clean_image_version, clean_image_hash, approved_hash?, review_status)`; `Dialogue(id, panel_id, speaker_id, sequence, verbatim_text, confidence, user_verified)`; `Character(id, stable_name, reference_asset, voice_reference?)`; `Shot(id, panel_id, image_hash, dialogue_ids[], speaker_timeline, duration_s, model_family, prompt_version, generation_status, video_path?, review_status)`. Không dùng trực tiếp vị trí trái/phải để gán người nói; không lưu URL signed của Flow như file duy nhất.

## State machine
`IMPORTED -> ANALYZED -> EXTRACTED -> IMAGES_READY -> IMAGE_APPROVED -> PROMPTS_READY -> VIDEO_REQUESTED -> REVIEWED -> EXPORTED`. `IMAGES_READY` cần đủ lời thoại/người nói được xác thực; `IMAGE_APPROVED` phải chứa hash ảnh phiên bản được duyệt. Chỉnh sửa một panel hủy `approved_hash`, prompt và shot video liên quan; các panel khác không bị làm lại.

## API dự kiến, KHÔNG phải endpoint hiện có
`POST /api/comics/import`, `POST /api/comics/{id}/analyze`, `POST /api/comics/{id}/split`, `PATCH /api/comics/{id}/panels/{panel_id}`, `POST /api/comics/{id}/approve`, `POST /api/comics/{id}/storyboard`, `POST /api/comics/{id}/generate-videos`, `GET /api/comics/{id}/status`. Đối với request có phí, yêu cầu lệnh tạo từ người dùng và idempotency key.

## Tái sử dụng FlowKit
- Trước tiên dùng `POST /api/flow/upload-image` với đường dẫn file trên máy **chạy FlowKit** để nhận media ID; không gửi đường dẫn client tùy ý.
- Chỉ gọi `POST /api/flow/edit-image` hoặc `generate-image` khi đã có nguồn, mask và ràng buộc ghép pixel bảo vệ; khả năng của Flow image editing không tự bảo đảm inpaint chính xác vùng mask: kiểm tra provider/mode và có phương án xử lý khác nếu cần.
- `POST /api/flow/generate-video` với ảnh bắt đầu, prompt và model được hỗ trợ; lưu mô tả polling đầy đủ, tải file về ngay và kiểm tra thành phẩm. Không gọi trực tiếp endpoint nội bộ của Google từ UI.
- Chrome Extension cần phiên Flow đang mở; fallback luôn cho phép xuất ảnh+prompt thủ công. Backend localhost không công khai ra Internet; không đưa token/cookie vào Git.

## Tương thích upstream
Giữ LICENSE MIT, giữ root README FlowKit trong Phân đoạn 1, sửa chức năng thành module riêng; tránh sửa sâu cơ chế transport. Khi cần đồng bộ FlowKit: xem diff upstream -> cập nhật nhánh riêng -> chạy regression -> anh duyệt trước merge. GitHub fork đã lưu quan hệ upstream, nhưng mỗi máy local cần `git remote add upstream https://github.com/crisng95/flowkit.git` nếu muốn fetch bằng CLI.
