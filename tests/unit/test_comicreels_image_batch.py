import importlib
from types import SimpleNamespace

import pytest
from PIL import Image

from agent.comicreels import image_batch as batch
from agent.comicreels.images import sha256_file
from agent.comicreels.store import ComicStore


@pytest.mark.asyncio
@pytest.mark.parametrize('count', [1, 2, 3, 4, 6])
async def test_one_original_one_prompt_for_any_frame_count(tmp_path, monkeypatch, count):
    source = tmp_path / 'original.png'
    Image.new('RGB', (100, 300)).save(source)
    artifacts = []
    for n in range(count):
        path = tmp_path / f'scene-{n}.png'
        Image.new('RGB', (576, 1024), (n * 20, 10, 20)).save(path)
        artifacts.append(SimpleNamespace(output_path=str(path), sha256=sha256_file(path)))
    calls = []
    def generate(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return SimpleNamespace(state='verified', images=artifacts, conversation_url='https://chatgpt.com/c/new')
    monkeypatch.setattr(batch, '_client', lambda: SimpleNamespace(image=SimpleNamespace(generate_batch=generate)))
    result = await batch.generate_scene_batch(source, tmp_path / 'batch', expected_count=count)
    assert len(calls) == 1
    assert calls[0][0] == batch.SCENE_BATCH_PROMPT
    assert calls[0][1]['attachments'] == [source]
    assert 'conversation' not in calls[0][1]
    assert len(result['images']) == count
    assert len({x['sha256'] for x in result['images']}) == count


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['incomplete', 'duplicate', 'uncertain'])
async def test_bad_batch_preserves_receipt_without_publishing(tmp_path, monkeypatch, mode):
    source = tmp_path / 'original.png'
    Image.new('RGB', (576, 1024)).save(source)
    image = SimpleNamespace(output_path=str(source), sha256=sha256_file(source))
    calls = []
    def generate(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(state='uncertain' if mode == 'uncertain' else 'verified',
                               images=[image] if mode == 'incomplete' else [image, image],
                               conversation_url='https://chatgpt.com/c/new', reason='pending')
    monkeypatch.setattr(batch, '_client', lambda: SimpleNamespace(image=SimpleNamespace(generate_batch=generate)))
    with pytest.raises(RuntimeError):
        await batch.generate_scene_batch(source, tmp_path / 'batch', expected_count=2)
    assert len(calls) == 1
    assert (tmp_path / 'batch' / 'provider-result.json').is_file()


@pytest.mark.asyncio
async def test_store_reserves_one_batch_and_replaces_all_images_atomically(tmp_path, monkeypatch):
    module = importlib.import_module('agent.comicreels.store')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'DB_PATH', tmp_path / 'test.db')
    store = ComicStore()
    project = await store.create_project(name='comic', source_path='/source', sha256='source', mime='image/png', width=100, height=300)
    pid = project['id']
    await store.replace_analysis(pid, [{'x':0,'y':n * 100,'w':100,'h':100} for n in range(2)],
                                 [{'panel_index':0,'speaker_id':'CHAR_1','text':'Ừ, QUÊN.','verified':True}])
    before = await store.get_project(pid)
    snapshot = [(p['id'], p['updated_at']) for p in before['panels']]
    assert await store.reserve_image_batch(pid, 'request-1') is True
    with pytest.raises(ValueError):
        await store.reserve_image_batch(pid, 'request-2')
    images = [{'path':f'/image-{n}', 'sha256':str(n)*64, 'protected':{'x':0,'y':0,'w':576,'h':1024}} for n in range(2)]
    await store.apply_image_batch(pid, 'request-1', snapshot, images)
    after = await store.get_project(pid)
    assert [p['portrait_path'] for p in after['panels']] == ['/image-0','/image-1']
    assert all(p['status'] == 'AI_IMAGE_READY' and p['approved_sha256'] is None for p in after['panels'])
    assert after['panels'][0]['dialogues'] == before['panels'][0]['dialogues']
    assert await store.reserve_image_batch(pid, 'request-1') is False


@pytest.mark.asyncio
async def test_store_does_not_overwrite_an_edited_project(tmp_path, monkeypatch):
    module = importlib.import_module('agent.comicreels.store')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'DB_PATH', tmp_path / 'test.db')
    store = ComicStore()
    project = await store.create_project(name='comic', source_path='/source', sha256='source', mime='image/png', width=100, height=100)
    pid = project['id']
    await store.replace_analysis(pid, [{'x':0,'y':0,'w':100,'h':100}], [])
    panel = (await store.get_project(pid))['panels'][0]
    await store.reserve_image_batch(pid, 'request')
    await store.update_panel(panel['id'], x=1)
    with pytest.raises(ValueError):
        await store.apply_image_batch(pid, 'request', [(panel['id'], panel['updated_at'])],
                                     [{'path':'/image','sha256':'a'*64,'protected':{}}])
    assert (await store.get_project(pid))['panels'][0]['portrait_path'] is None
