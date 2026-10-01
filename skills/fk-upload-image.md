Upload a local image file to Google Flow and get a media_id (UUID).

Usage: `/fk-upload-image <file_path> [--project <project_id>] [--entity <entity_id>]`

Useful for: setting channel icons, covers, or any local image as an entity reference or scene image.

## Step 1: Check browser transport health

```bash
curl -s http://127.0.0.1:8100/health
curl -s http://127.0.0.1:8100/api/flow/backend-status
```

Require `backend_ready=true`, `browser_session_ready=true`,
`authentication=authenticated` and `lease_held=true`. Upload uses the same
leased browser session and durable upload receipt path. It does not require paid
generation authorization.

The upload is scoped to a Flow project: pass `project_id`, or let the current
session-project resolver provide one. Do not create/replace browser profiles or
export credentials to make upload work.

## Step 2: Upload image

```bash
curl -s -X POST http://127.0.0.1:8100/api/flow/upload-image \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/absolute/path/to/image.png",
    "project_id": "<PID>",
    "file_name": "descriptive_name.png"
  }'
```

**Parameters:**
- `file_path` (required): Absolute path to local image file (PNG, JPG, WebP)
- `project_id` (optional): Project to associate the upload with
- `file_name` (optional): Descriptive filename, defaults to `image.png`

**Response:**
```json
{
  "media_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "raw": { "media": { "name": "uuid", ... } }
}
```

The `media_id` is the UUID you use everywhere (entity refs, scene images, video start frames).

## Step 3: Apply the media_id

### Option A: Set as entity reference image

```bash
curl -s -X PATCH http://127.0.0.1:8100/api/characters/<ENTITY_ID> \
  -H "Content-Type: application/json" \
  -d '{"media_id": "<MEDIA_ID>"}'
```

### Option B: Set as scene image

```bash
curl -s -X PATCH http://127.0.0.1:8100/api/scenes/<SCENE_ID> \
  -H "Content-Type: application/json" \
  -d '{
    "horizontal_image_media_id": "<MEDIA_ID>",
    "horizontal_image_status": "COMPLETED"
  }'
```
(Use `${ori}_image_media_id` / `${ori}_image_status` matching project orientation.)

### Option C: Create new entity with uploaded image

```bash
# 1. Create entity
curl -s -X POST http://127.0.0.1:8100/api/characters \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Asset Name",
    "entity_type": "visual_asset",
    "description": "What the image shows",
    "media_id": "<MEDIA_ID>"
  }'

# 2. Link to project
curl -s -X POST http://127.0.0.1:8100/api/projects/<PID>/characters/<ENTITY_ID>
```

## Step 4: Verify

```bash
# For entity:
curl -s http://127.0.0.1:8100/api/characters/<ENTITY_ID> | python3 -c "
import sys,json; c=json.load(sys.stdin)
print(f'{c[\"name\"]}: media_id={c.get(\"media_id\",\"none\")}')"

# For scene:
curl -s http://127.0.0.1:8100/api/scenes/<SCENE_ID> | python3 -c "
import sys,json; s=json.load(sys.stdin)
print(f'img_status={s.get(\"horizontal_image_status\")} mid={s.get(\"horizontal_image_media_id\")}')"
```

## Common Workflows

### Upload channel branding assets
```bash
# Upload icon
/fk-upload-image youtube/channels/<channel>/<channel>_icon.png --project <PID>
# Upload cover
/fk-upload-image youtube/channels/<channel>/<channel>_cover.png --project <PID>
```

### Replace a scene image with a local file
```bash
# Upload the image
/fk-upload-image /path/to/better_image.png --project <PID>
# Patch the scene with the returned media_id
# Then regenerate video from the new image
```

## Notes

- Upload executes through `BrowserFlowBackend` in the same leased signed-in Flow browser session.
- Durable upload intent/receipt state is authoritative across restart.
- Supported formats: PNG, JPG, JPEG, WebP.
- The returned `media_id` is the stable UUID used by later Flow operations.
- If upload outcome is uncertain, reconcile durable state before any replay.
- Browser/profile data, cookies and credentials must remain in the existing profile and must not be copied into the repository.
