# ComicReels local test results — 25/09/2026

Status: OFFLINE_LOCAL_TEST_PASS_WITH_EXTERNAL_GATES_PENDING.

## Environment
- macOS Apple Silicon on the user's Mac.
- Source repository is stored under iCloud Drive: Documents/ChatGPT/Kabin Toolkit Test/comicReels.
- Stable test runtime and Python environment were moved outside iCloud cache to avoid File Provider churn.
- Node 22.23.3, Python 3.12.12 for the tested runtime, ffmpeg 9.0.1.

## Automated gates
- Python unit suite: 378/378 PASS.
- Frontend npm ci: PASS.
- TypeScript/Vite production build: PASS.
- ESLint: PASS.
- npm audit after lockfile refresh: 0 vulnerabilities.
- Bash launcher syntax: PASS.
- PowerShell launcher syntax: NOT RUN because pwsh is not installed on this Mac.
- Non-blocking note: production JS bundle is larger than Vite's 500 KB warning threshold.

## Offline API E2E
Synthetic two-panel comic completed import, SHA-256 persistence, heuristic panel detection, dialogue/speaker storage, masks, local cleaning, 9:16 canvas, approval hashes, storyboard, backup/restore, local video registration/review and ffmpeg assembly.

The paid-generation guard returned HTTP 409 when confirm_paid was false. No Google Flow generation was called.

Negative/security checks passed:
- fake image bytes declared as PNG rejected;
- empty image rejected;
- MIME mismatch rejected;
- malicious backup path traversal rejected;
- storyboard before current image approval rejected;
- multi-dialogue add/delete retained correct speaker/order behavior.

Persistence after backend restart preserved project ID, source SHA-256 and panel metadata.

## Browser UI smoke
Chrome headless/CDP performed the real UI sequence:
source file selection -> Save project -> local panel analysis -> two-panel gallery -> dialogue/speaker entry -> mask cleaning -> 9:16 -> approve both images -> storyboard.

The final storyboard showed:
- Shot 1: 4 s, CHAR_BLUE, exact dialogue Xin chào, đây là câu thứ nhất!
- Shot 2: 6 s, CHAR_GREEN, exact dialogue Đây là câu thứ hai, giữ nguyên tiếng Việt.
- prompts include source lock, dialogue lock, lip-sync constraint, camera constraint and no-text constraint.

Routing was also verified: root highlights ComicReels Studio; /flowkit highlights the original FlowKit Dashboard.

## Fixes discovered by local testing
- Corrected ComicStore test module import shadowing.
- Updated deprecated Pillow test API.
- Synchronized package-lock so clean npm ci works.
- Added ESLint exception for existing shadcn helper exports.
- Corrected ComicReels root/sidebar/breadcrumb versus /flowkit routing.
- Updated Vite alias to import.meta.dirname.
- Changed launcher design so runtime, virtualenv, node_modules, DB and output live outside iCloud; committed source remains in the user's requested iCloud folder.

## External gates still pending
1. Real comic image quality on irregular layouts and AI-assisted recognition/inpainting. Current offline cleaner preserves pixels outside a supplied mask but does not reconstruct hidden artwork.
2. Google Flow Extension/project authentication and one real paid video shot.
3. Windows PowerShell execution/fresh-install test on a Windows machine.

Per the user's instruction, testing must stop and ask before using ChatGPT/vision AI for image work or a Google Flow account for real video generation.
