# ComicReels | Hồ sơ phát triển chính

**25/09/2026:** Fork công khai của [FlowKit](https://github.com/crisng95/flowkit). Mọi chức năng chưa được nghiệm thu đều được ghi là kế hoạch. Xem [CHECKPOINTS.md](CHECKPOINTS.md) trước khi báo cáo hoàn thành.

## Ý tưởng, PRD và kỹ thuật
- [VISION: trải nghiệm, ranh giới và quy tắc bất biến](VISION.md)
- [PRODUCT: PRD đầy đủ, luồng người dùng và tiêu chí kết quả](PRODUCT.md)
- [ARCHITECTURE: kiến trúc dữ liệu và FlowKit](ARCHITECTURE.md)
- [QUALITY: chất lượng, QA và bảo mật](QUALITY.md)
- [RISKS: rủi ro và các quyết định](RISKS.md)
- [ROADMAP: 17 phân đoạn và nghiệm thu](ROADMAP.md)
- [CHECKPOINTS: trạng thái thực, PR và kiểm thử còn thiếu](CHECKPOINTS.md)
- [IMPLEMENTATION-03-16: ma trận code các đoạn 3–16](IMPLEMENTATION-03-16.md)
- [LOCAL-TEST-PLAN: kịch bản test local đang chờ anh yêu cầu](LOCAL-TEST-PLAN.md)
- [CHECKPOINT-TEMPLATE: mẫu báo cáo mỗi đoạn](CHECKPOINT-TEMPLATE.md)

## Checklist và rủi ro từng phân đoạn
- [00. Đặc tả và quyết định mô hình repo](stages/00.md)
- [01. Chuẩn bị mã nguồn nền FlowKit](stages/01.md)
- [02. Khởi động và khung giao diện](stages/02.md)
- [03. Nhập ảnh nguồn](stages/03.md)
- [04. Tách khung thô](stages/04.md)
- [05. Ghi thoại và gán người nói](stages/05.md)
- [06. Cắt ảnh và mask](stages/06.md)
- [07. Xóa chữ có kiểm soát](stages/07.md)
- [08. Tạo ảnh dọc](stages/08.md)
- [09. Duyệt ảnh](stages/09.md)
- [10. Chia shot và khóa thoại](stages/10.md)
- [11. Prompt và xuất thủ công](stages/11.md)
- [12. Cầu nối FlowKit](stages/12.md)
- [13. Kiểm chứng **một** video](stages/13.md)
- [14. Hàng đợi nhiều shot](stages/14.md)
- [15. Kiểm duyệt và ghép video](stages/15.md)
- [16. Đóng gói và bảo trì](stages/16.md)

## Các PR hiện tại
- [PR #1](https://github.com/vulementor/comicReels/pull/1): fork/tài liệu, nhánh `segment/01-foundation`.
- [PR #2](https://github.com/vulementor/comicReels/pull/2): UI tiếng Việt và [báo cáo Đoạn 2](SEGMENT-02.md), nhánh `segment/02-studio-shell`.

PR #1 và #2 còn Draft/chưa merge vào `main`; không tự merge, không tự khởi động Đoạn 3 khi chưa có OK nghiệm thu Đoạn 2. Không commit nguồn truyện/cookie/token/ảnh/video riêng lên repo public.
