# Thỏ Remix — toolkit và ứng dụng Windows

Nguồn chuẩn: `comicReels/agent/thoremix`. Bản cài riêng:
`D:\StableApp\ThoRemix\ThoRemix.exe`. CLI, SDK và GUI dùng chung trạng thái.
Không có Agent hay vòng suy luận tự trị. AI khi cần phải dùng `gpt_fullproxy`.
Nhánh ghép frame/ChatGPT Web audio khi hết credit chưa triển khai.

## Đường dẫn

- Ảnh đầu vào: `D:\Thỏ Remix` (chỉ ảnh trực tiếp trong thư mục).
- Hồ sơ: `D:\Thỏ Remix\video\<tên ảnh>\`, gồm MP4 cùng tên, ảnh gốc,
  ảnh con trong `frames`, `package.json`, `publication.json`.
- Profile KRP riêng: `D:\StableApp\ThoRemix\data\krp\profiles\thoremix-social\browser`.
- Affiliate tái sử dụng profile KDVT:
  `C:\Users\vulem\OneDrive\Documents\ChatGPT\Kabin Toolkit Test\profiles\shopee-affiliate`.
- Cấu hình: `D:\StableApp\ThoRemix\config\settings.json`.
- KRP: `D:\StableApp\ThoRemix\data\krp\config.yaml` và `state.sqlite3`.

Không sao chép cookies/profile. Một chủ sở hữu giữ profile trong mỗi phiên.

## Đăng nhập và đăng bài

Mở EXE, chọn **Đăng nhập 3 kênh**. Đăng nhập Facebook, TikTok Studio, YouTube Studio.
Đóng trình duyệt khi xong rồi chọn **Kiểm tra đăng nhập**.
Ngày 27/09/2026 đã kiểm tra trực tiếp cả ba kênh: Facebook, TikTok và YouTube đều `ok`.
Kết quả là bằng chứng tại thời điểm kiểm tra; KRP vẫn kiểm tra actor trước từng bài đăng.
**Tên Page Facebook** lưu tên hiển thị quan sát được của Page `ThoRemixOfficial`;
KRP vẫn xác minh actor trước khi đăng, không coi tên đã nhập là bằng chứng đăng nhập.

**Đăng hồ sơ video** nhận thư mục đã hoàn tất manifest, video giải mã được và Affiliate đủ bằng chứng.
Từng bài đăng và bình luận có ID riêng; lỗi một kênh không đăng lại kênh đã xác nhận.
Kết quả chưa rõ chỉ được đối soát cùng ID. Kênh cố định: Facebook `/ThoRemixOfficial`,
TikTok `@thoremixofficial`, YouTube `@ThoRemixOfficial`.
Không suy luận thiết lập “dành cho trẻ em” từ việc video là hoạt hình.

## Affiliate

Mặc định lọc giá <=200.000 VND và lượng bán quan sát >=1.000, rồi xếp tỷ lệ hoa hồng
đã xác minh từ cao xuống thấp; giá thấp và lượng bán phân hạng khi bằng tỷ lệ.
Giá/hoa hồng/lượng bán cần bằng chứng mới. Không suy diễn số thiếu thành 0,
không tuyên bố “đang hot” chỉ từ tổng lượng bán. Ngưỡng chỉnh trong settings.json.
Link phải đúng sản phẩm và không mang dữ liệu phiên. Theo yêu cầu owner ngày27/09,
ứng dụng không tự chèn câu về tiếp thị liên kết/hoa hồng vào caption, mô tả hoặc bình luận.
Trường disclosure trong hồ sơ chỉ giữ thông tin nội bộ; nội dung đăng lấy từ văn bản đã chốt.

Luồng source hiện chuyển sang **catalog-first**: mỗi lượt đọc tối đa 20 thẻ Product Offer
trên trang đầu và lấy trực tiếp tên, giá, lượng bán cùng “Tỉ lệ hoa hồng” đang hiển thị trên thẻ.
Nếu có thẻ đủ bằng chứng, việc xếp hạng dùng trực tiếp tỷ lệ này và không mở trang chi tiết
(`detail_count=0`). Chỉ khi toàn bộ nhóm đủ điều kiện không có tỷ lệ đọc được, hệ thống mới
fallback có giới hạn sang tối đa 12 bảng chi tiết để tránh mất hoàn toàn khả năng chọn sản phẩm.

Sau khi chọn, intent khóa đúng `catalog_offer`/product ID và thao tác “Lấy link” quay lại đúng
thẻ Product Offer; không cần mở detail chỉ để bấm link. Short link chỉ được chấp nhận sau khi
redirect trình duyệt xác minh đúng product ID; `shop_id` được học từ destination thật, không
được suy đoán từ card. Phạm vi này chưa tìm theo các từ khóa `affiliate_queries`; các giá trị đó
được giữ để tương thích cấu hình, không được trình bày như kết quả tìm kiếm từ khóa hay toàn thị trường.

Live test 27/09/2026 là baseline của luồng detail-first cũ: 20 thẻ, 4 trang chi tiết; chọn sản phẩm `11074180896` của shop
`579713807`, giá 130.000đ, lượng bán hiển thị 6.000+, tỷ lệ 17,5% / Facebook Reels 20%.
Một lần tạo link được đối soát về đúng sản phẩm; biên nhận `data/task-7-live-acquisition.json`.
Lần tạo chưa rõ kết quả không được lặp lại. Nếu đã nhận URL nhưng chưa xác minh đích,
chỉ mở lại chính URL đã lưu để kiểm tra; không tạo link mới.

## Lịch và sản xuất

Hai task Windows `ThoRemix-1100`, `ThoRemix-1830` dùng múi giờ Việt Nam, tài khoản
Windows đang đăng nhập, quyền thường. Máy cần đang bật; không chạy bù giờ đã bỏ lỡ.
**Tạm dừng** ngăn lượt mới, không hủy lượt đang chạy. Đóng GUI không hủy tiến trình con.

Bản cài tối 27/09/2026 đã có runner tạo toàn bộ truyện: phân tích ảnh gốc bằng GPT FullProxy,
tạo các ảnh con trong một yêu cầu, kiểm tra ảnh, tạo một video native Flow 10 giây,
kiểm tra 40 khung hình, tải bản cao nhất, kiểm tra thoại, soạn nội dung và chọn Affiliate.
Mỗi bước lưu hash ảnh nguồn, yêu cầu và kết quả; tiếp tục công việc dùng lại bước đã hoàn tất.
Flow kiểm tra phiên đăng nhập, số dư và giá ngay trước khi tạo; số dư trong báo cáo cũ không
thay cho kiểm tra này. Chưa có fallback ghép frame khi hết credit.

Ảnh con được lưu ngay vào `video/<tên ảnh>/frames`, kèm ảnh gốc và `draft.json`;
không cần chờ video xong mới xem được ảnh trong app. Chỉ hồ sơ có `package.json`
đã xác minh mới được đăng. Danh sách và khung chi tiết có thanh chia kích thước,
khung chi tiết cuộn riêng và hiển thị ảnh gốc/các cảnh theo thứ tự.

ChatGPT dùng khoảng cách ít nhất 90 giây giữa hai lượt gửi và nghỉ ít nhất 30 giây
sau phản hồi. Lỗi sản xuất nghỉ 60 giây trước ảnh tiếp theo; thời hạn được lưu bền
qua khởi động lại. Phản hồi giới hạn tần suất giữ thời gian chờ dài hơn của nhà cung cấp.
Các trình duyệt trong sản xuất, Affiliate và đăng tự động chạy headless; cửa sổ đăng
nhập do người dùng mở vẫn hiển thị.

Đã đối soát lỗi JSON do giao diện ChatGPT làm mất ký tự escape bằng cách đọc phản hồi
API nguyên văn của đúng conversation/assistant message, không gửi lại prompt.
Kết quả chưa rõ sau khi tạo ảnh được giữ nguyên; chỉ cách ly trước Flow khi có đầy đủ
kiểm tra và audit, không tự gửi lại. Tiến độ nghiệm thu thực tế ghi trong kế hoạch
`2026-09-27-thoremix-automatic-story.md`; unit test không thay cho MP4 hoàn chỉnh.

## SDK / CLI / build

```python
from agent.thoremix import ThoRemixClient
client = ThoRemixClient(r'D:\StableApp\ThoRemix')
status = client.status(probe=True)
```

Entry `app/start.py` chuẩn bị import path và ffmpeg. Các lệnh: `status`, `login`,
`auth-status`, `affiliate`, `configure-facebook`, `pause`, `resume`, `tick`,
`import-source`, `prepare-package`, `finalize`, `reconcile-package`, `publish`,
`produce-one`, `reconcile-production`.
`prepare-package --slot <lượt> --source <ảnh gốc> --video <video đã duyệt>
--metadata <JSON> --frame <ảnh con 1> --frame <ảnh con 2> ...` nhập một video có sẵn
bằng đúng ảnh gốc trực tiếp trong thư mục nguồn. Cùng lượt tiếp tục đúng công việc cũ;
ảnh/lượt xung đột bị từ chối. SDK có `prepare_package` cùng tham số.
Metadata có thể ghi rõ `youtube: {made_for_kids: false}` hoặc `true` theo nội dung đã
kiểm tra; chương trình không suy đoán lựa chọn này từ định dạng hoạt hình.
`finalize` chỉ chuyển ảnh gốc sau khi bản sao video/ảnh được kiểm tra và manifest hoàn tất.
Hồ sơ sao chép dở được giữ để đối soát, không ghi đè hoặc tự tạo video tính phí lần nữa.
SDK ưu tiên FFmpeg/FFprobe trong `runtime/bin` của bản cài, không cần thêm chúng vào PATH.
Lệnh đăng thủ công và lịch cùng cập nhật lịch sử công việc từ biên nhận KRP; kết quả từng kênh
chưa đủ thì trạng thái vẫn là đang đăng, chỉ hoàn tất khi mọi bài/bình luận đã xác nhận.

Bản sửa nội dung dùng publication_copy_revision ràng buộc hash của văn bản công khai.
Thao tác đã đăng chỉ được kế thừa khi KRP xác nhận cùng profile, actor, video, bài/bình luận
và có bằng chứng chỉnh sửa đúng văn bản. Các kênh chưa đăng dùng ý định mới; ý định cũ
chưa gửi được ghi rõ đã bị thay thế. Không ghi đè hoặc phát lại kết quả chưa rõ.
publication_targets giới hạn đúng kênh cần làm; bảng điều khiển đếm theo phạm vi đó.

`deployment/thoremix/Build-Stable.ps1` đóng gói runtime riêng, KRP/KAT/GPTFP/KBS wheels,
native launcher và source hash manifest. Nâng cấp có khóa một runner, kiểm tra import và hash
trước khi thay bundle, giữ bản cũ để khôi phục. `-SkipRuntime` dùng runtime đang có;
`-InstallSchedule` cài ba task đăng/sản xuất. Không sửa GithubReview/KabinDrama.
`Verify-Desktop.ps1` chụp cửa sổ ứng dụng và kiểm tra hash/lịch thực tế.
Unit test, EXE chạy được và lịch đã cài không phải bằng chứng video đã được đăng;
nghiệm thu cần URL/ID được KRP xác nhận và biên nhận Affiliate trên đúng các kênh.

## Bản cài kiểm tra ngày 27/09/2026

Trong **Sản xuất & lịch**, chọn **Theo lịch đăng** hoặc **Sản xuất sớm**, nhập hạn mức rồi
bấm **Lưu cấu hình**. Hạn mức 1–1000, mặc định 5, tính theo clip hoàn thành trong ngày Việt Nam;
không tính lượt lỗi. Lưu cấu hình không tự bật chiến dịch đang tạm dừng. **Bật tự động** cho
phép task nền kiểm tra trong vòng 5 phút; **Tạm dừng** có hiệu lực trước clip tiếp theo.

Mỗi ảnh gốc là một truyện, kể cả ảnh có nhiều cảnh. Một truyện tạo một clip riêng; không nối
clip của các ảnh khác nhau. Clip xong được lưu thành hồ sơ và chờ lượt đăng. Mỗi giờ 11:00/18:30
lấy tối đa một clip; gọi lại cùng lượt không lấy tiếp clip khác. Clip lỗi giữ ảnh và mã lỗi,
lấy ảnh mới tới khi đủ hạn mức hoặc hết nguồn. **Xem log sản xuất** mở báo cáo trong
data/reports/production/YYYY-MM-DD.json. Kết quả chưa rõ giữ để đối soát, không tự tạo lại.

SDK: configure_production(mode='ahead', daily_limit=5), set_enabled(bool), produce_ahead(),
dispatch(). CLI: configure-production --mode ahead --daily-limit 5; produce-ahead; dispatch.
Windows task ThoRemix-Production gọi --dispatch mỗi 5 phút và sau đăng nhập; không phụ thuộc
cửa sổ desktop đang mở hay nằm ở tray. Regression mới nhất: 1006 test ComicReels qua,
557 test GPT FullProxy qua (49 bỏ qua). Kiểm thử tự động không thay cho nghiệm thu clip thật.
Từ yêu cầu ngày 28/09, QA nội dung chỉ tham khảo. Clip có file hoàn chỉnh vẫn tính vào hạn mức
sản xuất; nếu ảnh/cảnh/thoại bị cảnh báo hoặc chưa kiểm tra được thì hiện **Sản xuất thành công ·
chờ anh duyệt**. Chọn truyện, bấm **Xem & duyệt clip**, rồi **Duyệt clip để đăng**. Chỉ clip đạt QA hoặc
đã được chủ kênh duyệt mới vào hàng chờ đăng. Yêu cầu duyệt gắn với đúng hồ sơ/file đang xem;
nếu runner bận, yêu cầu được lưu và áp dụng sau clip hiện tại. Cảnh báo gốc được giữ trong log.
Lỗi kỹ thuật thật vẫn giữ ảnh, nghỉ ít nhất 60 giây rồi chọn ảnh khác. Kết quả gửi chưa rõ được
đối soát đúng cuộc trò chuyện/media đã lưu, không phát lại yêu cầu tạo.

`resume-quality-stops` khôi phục các truyện từng dừng do QA khi ảnh nguồn và ảnh con đã xác minh;
tiếp tục từ ảnh/video đã lưu. Lệnh này không phát lại lượt gửi ảnh/video chưa rõ kết quả.

System tray: biểu tượng thỏ trắng nền tím xuất hiện trong khay hệ thống (có thể nằm dưới
mũi tên ^ của Windows). Bấm X để ẩn cửa sổ; bấm biểu tượng hoặc mở EXE lần nữa để hiện lại
cùng cửa sổ. Chuột phải có Mở Thỏ Remix, Lịch chạy, Tạm dừng lịch và Thoát Thỏ Remix.
Thoát chỉ đóng desktop; lệnh đã chạy giữ quyền sở hữu runner và tiếp tục. Tạm dừng lịch
không bật lại lịch hoặc dừng đột ngột tác vụ. Bản thân việc ẩn/mở app không đổi cấu hình lịch.
77 test dashboard/core và kiểm tra native EXE đã qua; xem data/verification/tray.json.

913 unit tests qua với một cảnh báo luồng aiosqlite khi đóng Flow; sau đó 86 test đăng/Affiliate,
34 test dashboard và 304 test KRP qua. Các phần giao diện/thay thế hồ sơ đã được rà soát độc lập;
các sửa đổi đối soát TikTok và nội dung cuối được kiểm tra bằng test và kết quả đăng thực tế.
Runtime KRP/KAT và giao diện năm trang đã cài. Lần kiểm tra EXE lúc 18:51 ngày 27/09 xác nhận
hash bundle khớp, hai lịch đúng và chỉ một hồ sơ AI hiện hành. Hồ sơ bị thay thế vẫn giữ trên đĩa.

Clip AI đúng đã đăng tại Facebook Reel1782565249836475 và TikTok video7690178796233706770;
bình luận sản phẩm cả hai kênh đã xác nhận. Câu tự thêm về tiếp thị liên kết đã được bỏ khỏi
caption/bình luận Facebook và không có trong bản TikTok. YouTube x0fmyfJ-DgA giữ nguyên theo
yêu cầu sau đó của chủ kênh. Hồ sơ ghép frame cũ bị chặn, không dùng để đăng tiếp.

Gọi lại lệnh publish qua SDK đã cài trả về complete, số hiệu ứng/lượt xử lý giữ nguyên [9,17].
Biên nhận nằm trong data/review/corrected-ai-publication-result.json, data/review/copy-removal
và data/verification. Các URL này thuộc lượt đăng đã xác nhận trước khi nâng cấp runner tự sản xuất.

## Xử lý video và xem trực tiếp — 28/09/2026

Trang **Xử lý video** bật mặc định dải đen trên 11%, dưới 12% chiều cao. Đây là lớp che;
không cắt, phóng to hay giảm độ phân giải video. Có thể đổi tỷ lệ hoặc tắt. Tiếng cười là
tùy chọn bật/tắt, chọn file và âm lượng; bản cài Thỏ Remix đã bật file hahaha.MP3 của chủ kênh
ở mức 80%. File được sao chép vào assets/laugh của app. Âm thanh trộn vào cuối, không kéo dài clip.

**Lưu cài đặt** áp dụng cho lần sản xuất tiếp theo. **Áp dụng cho clip chưa đăng** xử lý các
hồ sơ đã có MP4 nhưng chưa có ý định đăng. Video gốc ở edits/original.mp4, hồ sơ cũ được lưu
theo hash trong edits/history. Lặp lại cùng cài đặt dùng đúng bản đã xử lý; thay cài đặt luôn
bắt đầu từ video gốc, không chồng tiếng cười. Giao dịch dở được phục hồi trước duyệt/đăng.
Hồ sơ đã duyệt cần duyệt lại nếu bytes thay đổi; mọi biên nhận Flow tính phí được giữ nguyên.

Bấm đúp một hàng hoặc **Xem & duyệt clip** để mở trình phát trong app: phát/tạm dừng, tua,
bật/tắt âm thanh, các tab nhận xét/nội dung/ảnh nguồn và nút duyệt cố định. Space điều khiển
phát/tạm dừng. Nút duyệt báo đang gửi/đã nhận/thất bại; không duyệt nhầm hồ sơ mới khi cửa sổ
đang hiển thị bản cũ. QA chỉ tham khảo, cảnh báo gốc được giữ và chỉ owner bấm duyệt.

CLI: finish-unpublished. SDK: configure_finishing(mask_enabled, mask_top_percent,
mask_bottom_percent, laugh_enabled, laugh_path, laugh_volume). Bước finishing mới có journal
và cài đặt/input bất biến riêng, tiếp tục đúng render khi gián đoạn sau khi xuất video.
Verify-Review.py kiểm tra trình phát của bản cài với video thật, không gọi duyệt/đăng.
