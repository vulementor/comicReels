Re-sign expired media URLs for all scenes in a video (images, videos, upscale videos) and character reference images.

Usage: `/fk-refresh-urls <video_id> [--project-id <PID>]`

## When to use

- Before `/fk-review-video` if videos were generated hours ago (GCS signed URLs expire)
- Before `/fk-concat-fit-narrator` if downloading from URLs instead of local files
- After any long gap between generation and consumption of media URLs

## Pre-flight

```bash
curl -s http://127.0.0.1:8100/health
curl -s http://127.0.0.1:8100/api/flow/backend-status
```

Require browser/session/authentication/lease readiness. URL refresh is read-only
with respect to paid generation and does not require enabling paid dispatch.
Preserve the existing bound profile; do not clear cookies/storage or replace it.

## Step 1: Get project_id from video

```bash
VID="<video_id>"
PID=$(curl -s "http://127.0.0.1:8100/api/videos/${VID}" | python3 -c "import sys,json; print(json.load(sys.stdin)['project_id'])")
echo "Project: $PID"
```

## Step 2: Bulk re-sign every stored media id

This walks the project's scenes and entities, asks Flow's media rpc to re-sign
each `*_media_id` it holds, and writes the fresh urls back to the DB. It is a
call per media id, so a large project takes a moment.

```bash
curl -s -X POST "http://127.0.0.1:8100/api/flow/refresh-urls/${PID}" | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f\"Refreshed: {r.get('refreshed', 0)} URLs (found {r.get('found', 0)} total)\")
if r.get('error'):
    print(f\"ERROR: {r['error']}\")
"
```

**What gets updated:**
- `horizontal_image_url` / `vertical_image_url` — scene images
- `horizontal_video_url` / `vertical_video_url` — scene videos (original)
- `horizontal_upscale_url` / `vertical_upscale_url` — 4K upscaled videos
- `reference_image_url` — character/entity reference images

The server matches each URL's media_id against `*_media_id` fields on scenes and characters, updating whichever orientation/type matches.

## Step 3: Verify refresh worked

```bash
# Check a few scenes have valid URLs
curl -s "http://127.0.0.1:8100/api/scenes?video_id=${VID}" | python3 -c "
import sys, json
scenes = sorted(json.load(sys.stdin), key=lambda s: s['display_order'])

# Auto-detect orientation
ori = 'horizontal'
for s in scenes:
    if s.get('horizontal_video_status') == 'COMPLETED' and s.get('horizontal_video_url'):
        ori = 'horizontal'; break
    if s.get('vertical_video_status') == 'COMPLETED' and s.get('vertical_video_url'):
        ori = 'vertical'; break

ok = 0; expired = 0
for s in scenes:
    url = s.get(f'{ori}_video_url') or ''
    if url and 'Expires=' in url:
        import re, time
        m = re.search(r'Expires=(\d+)', url)
        if m and int(m.group(1)) > time.time():
            ok += 1
        else:
            expired += 1
    elif url:
        ok += 1
    else:
        expired += 1

print(f'Orientation: {ori.upper()}')
print(f'Valid URLs: {ok}/{len(scenes)}')
if expired:
    print(f'Still expired: {expired} — inspect browser session readiness and media ids')
else:
    print('All URLs refreshed successfully!')
"
```

## Step 4: Per-media fallback (for anything the bulk pass missed)

If a media id was not covered — because it is not stored on a scene or entity
row — re-sign it directly:

```bash
curl -s "http://127.0.0.1:8100/api/flow/media/<MEDIA_ID>"
# Returns: {"video": {"fifeUrl": "https://flow-content.google/video/…"},
#           "image": {"fifeUrl": "https://flow-content.google/image/…"}}
```

A record with only `image` and no `video` means the clip is not finished being
written yet — the poster arrives before the video url does. Wait and retry;
do not save the poster as the video.

Then update the scene manually:

```bash
curl -X PATCH "http://127.0.0.1:8100/api/scenes/<SID>" \
  -H "Content-Type: application/json" \
  -d '{"horizontal_video_url": "<FRESH_URL>"}'
```

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `BROWSER_NOT_READY` | Browser session evidence is not ready | Inspect `/api/flow/backend-status`; preserve the existing profile |
| `PROFILE_BUSY` / `PROFILE_RECONCILE_REQUIRED` | Profile ownership/lease conflict | Stop competing owner and reconcile lease; do not delete profile data |
| `refreshed: 0`, `found: 0` | No media ids stored for this project | Nothing to refresh — check the project id |
| `refreshed: 0`, `found: N` | Current media reads failed | Inspect browser session/auth/lease and stable media ids; retry reads only |
| Some URLs still expired after refresh | media_id mismatch or media not ready | Use per-media read with the correct stable media UUID |
| `get_media` returns missing media | Media is unavailable on Flow | Surface the missing media state; do not treat read failure as permission to regenerate automatically |
