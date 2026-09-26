"""Generate the complete scene set from one original comic, in one SDK call."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from agent.comicreels.ai_provider import _client, _VISIBLE, _validate_generated_portrait
from agent.comicreels.images import sha256_file


SCENE_BATCH_PROMPT = (
    'Tự đếm các khung trong ảnh truyện này. Mỗi khung tạo một ảnh bối cảnh 9:16 riêng, '
    'đúng thứ tự; xóa chữ và bong bóng, giữ nguyên nhân vật, tư thế, biểu cảm, '
    'bối cảnh và nét vẽ. Không ghép các khung thành một ảnh.'
)


class BatchNotSubmitted(RuntimeError):
    """The SDK proved that image submission did not happen."""


async def generate_scene_batch(source: Path, output_dir: Path, *, expected_count: int) -> dict:
    if not source.is_file() or expected_count < 1:
        raise RuntimeError('Cần ảnh truyện gốc và danh sách khung đã nhận diện.')
    client = _client()
    if not callable(getattr(client.image, 'generate_batch', None)):
        raise BatchNotSubmitted('Cần cập nhật gpt_fullproxy để nhận nhiều ảnh trong một lượt.')
    output_dir.mkdir(parents=True, exist_ok=True)
    result = await asyncio.to_thread(
        client.image.generate_batch, SCENE_BATCH_PROMPT,
        attachments=[source], output_dir=output_dir / 'artifacts', visible=_VISIBLE,
    )
    receipt = {
        'state': result.state, 'source_sha256': sha256_file(source),
        'prompt': SCENE_BATCH_PROMPT, 'conversation_url': result.conversation_url,
        'reason': getattr(result, 'reason', None),
        'images': [{'path': str(x.output_path), 'sha256': x.sha256} for x in result.images],
    }
    # Keep the actual provider result even when incomplete. Never resend here.
    (output_dir / 'provider-result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    if result.state == 'needs_input':
        raise BatchNotSubmitted(getattr(result, 'reason', '') or 'ChatGPT chưa sẵn sàng để gửi ảnh.')
    if result.state != 'verified':
        raise RuntimeError(f'Chưa nhận đủ kết quả ChatGPT: {result.state}. {getattr(result, "reason", "") or ""}')
    if len(result.images) != expected_count:
        raise RuntimeError(f'ChatGPT trả {len(result.images)}/{expected_count} ảnh. Giữ nguyên bộ ảnh hiện tại; cần kiểm tra lượt này.')
    images, hashes = [], set()
    for index, item in enumerate(result.images):
        path = Path(item.output_path)
        digest = sha256_file(path)
        if digest != item.sha256 or digest in hashes:
            raise RuntimeError('Bộ ảnh trả về bị trùng hoặc không khớp dữ liệu đã tải.')
        protected = _validate_generated_portrait(path)
        hashes.add(digest)
        images.append({'path': str(path), 'sha256': digest, 'protected': protected})
    # Only publish working copies after the complete set passes validation.
    for index, item in enumerate(images):
        dest = output_dir / f'scene-{index + 1}.png'
        shutil.copy2(item['path'], dest)
        item['path'] = str(dest)
    return {'images': images, 'conversation_url': result.conversation_url}
