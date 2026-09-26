# Source image batch correction

**Goal:** One original comic image and one short prompt; ChatGPT counts the frames and creates that many separate 9:16 scenes, in reading order.

**Architecture:** ComicReels sends the original source through one public `gpt_fullproxy.image.generate_batch` call. The SDK collects all images from that response. Panel crops remain previews; masks and visual-anchor prose are not generation inputs. Transcript analysis remains separate so original dialogue is preserved.

**User constraints (26/09/2026, 20:31–20:36 Asia/Saigon):**
- Code and fixes must be pushed to GitHub before execution.
- Desktop is for tests only, on VULE-PC through Remote Desktop Commander.
- Live ChatGPT tests must run commands through gpt_fullproxy; no direct browser interaction or UI scripts.
- No fixed two/three-image prompt, no per-panel generation loop, no collage splitting.
- Keep FlowKit core. Do not merge PR #3 or submit Flow video jobs.

**Prompt:** “Tự đếm các khung trong ảnh truyện này. Mỗi khung tạo một ảnh bối cảnh 9:16 riêng, đúng thứ tự; xóa chữ và bong bóng, giữ nguyên nhân vật, tư thế, biểu cảm, bối cảnh và nét vẽ. Không ghép các khung thành một ảnh.”

- [ ] Add SDK batch results and collect every generated image in response order; preserve single-image compatibility and uncertain-submit behavior.
- [ ] Replace ComicReels' frontend per-panel loop with a project batch endpoint. Validate the complete returned set before replacing any active image; preserve original dialogue and require fresh approval.
- [ ] Push both repositories, then run SDK/app regression and frontend checks on VULE-PC only.
- [ ] Run one real SDK command with the original source; report actual image count/quality separately from unit test results.

Review focus: 1/2/3/4+ frames; source attachment excluded from outputs; incomplete or duplicate outputs never published as a complete set; repeat clicks do not resubmit an uncertain request; existing images/transcript survive a failed batch.
