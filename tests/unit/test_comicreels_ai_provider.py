import importlib
from types import SimpleNamespace

import pytest
from PIL import Image

import agent.comicreels.ai_provider as provider
import agent.api.comicreels as comic_api
from agent.comicreels.store import ComicStore
from fastapi import HTTPException

store_module = importlib.import_module("agent.comicreels.store")


def test_provider_status_uses_explicit_profile_without_session_secrets(tmp_path, monkeypatch):
    profile = tmp_path / "chatgpt-profile"
    profile.mkdir()
    monkeypatch.setenv("COMICREELS_GPTFP_PROFILE_DIR", str(profile))
    monkeypatch.setattr(provider, "_sdk_available", lambda: True)

    status = provider.provider_status()

    assert status["provider"] == "gpt_fullproxy"
    assert status["configured"] is True
    assert status["profile_dir"] == str(profile.resolve())
    assert "cookie" not in repr(status).lower()
    assert "token" not in repr(status).lower()


def test_extract_json_accepts_fenced_payload():
    payload = provider._extract_json(
        """```json
{"panels":[{"x":0,"y":0,"w":10,"h":20,"order":0}],"dialogues":[]}
```"""
    )
    assert payload["panels"][0]["h"] == 20


@pytest.mark.asyncio
async def test_analyze_comic_uploads_source_once_and_returns_conversation(tmp_path, monkeypatch):
    source = tmp_path / "page.png"
    Image.new("RGB", (200, 300), (255, 255, 255)).save(source)

    attachment = SimpleNamespace(name="page.png", size_bytes=source.stat().st_size, sha256="a" * 64)
    first = SimpleNamespace(
        state="verified",
        text='''{
          "panels":[
            {"x":10,"y":20,"w":100,"h":120,"order":0,
             "visual_anchor":"CHAR_1 đứng bên trái, quay mặt sang phải, cận trung.",
             "speech_regions":[{"x":5,"y":6,"w":40,"h":30,"kind":"speech_bubble"}]}
          ],
          "dialogues":[
            {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"Xin chào","confidence":0.9}
          ],
          "characters":[],
          "warnings":[]
        }''',
        reason=None,
        conversation_url="https://chatgpt.com/c/test",
        assistant_message_id="assistant-1",
        attachment_receipts=(attachment,),
    )
    calls = []

    class FakeChat:
        def send(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return first

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(chat=FakeChat()))

    result = await provider.analyze_comic(source, "image/png", 200, 300)

    assert len(calls) == 1
    assert calls[0][1]["attachments"] == [source]
    assert result["panels"][0]["mask"] == [{"x": 5, "y": 6, "w": 40, "h": 30}]
    assert result["panels"][0]["visual_anchor"] == "CHAR_1 đứng bên trái, quay mặt sang phải, cận trung."
    assert "visual_anchor" in calls[0][0]
    assert result["dialogues"][0]["text"] == "Xin chào"
    assert result["dialogues"][0]["verified"] is False
    assert result["provider_receipt"]["conversation_url"] == "https://chatgpt.com/c/test"
    assert result["provider_receipt"]["attachments"][0]["sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_analyze_comic_preserves_exact_single_pass_transcript(tmp_path, monkeypatch):
    source = tmp_path / "comic.png"
    Image.new("RGB", (300, 200), (255, 255, 255)).save(source)
    attachment = SimpleNamespace(name="comic.png", size_bytes=source.stat().st_size, sha256="b" * 64)
    first = SimpleNamespace(
        state="verified",
        text='''{
          "panels":[{"x":0,"y":0,"w":300,"h":200,"order":0,
                     "visual_anchor":"CHAR_1 chính diện, khung ngang.",
                     "speech_regions":[{"x":10,"y":10,"w":180,"h":80}]}],
          "dialogues":[{"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"LŨ KHỐN NẠN","confidence":0.99}],
          "characters":[],"warnings":[]
        }''',
        reason=None,
        conversation_url="https://chatgpt.com/c/first",
        assistant_message_id="a1",
        attachment_receipts=(attachment,),
    )
    calls = []

    class FakeChat:
        def send(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return first

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(chat=FakeChat()))

    result = await provider.analyze_comic(source, "image/png", 300, 200)

    assert len(calls) == 1
    assert result["dialogues"][0]["text"] == "LŨ KHỐN NẠN"
    assert result["dialogues"][0]["verified"] is False


@pytest.mark.asyncio
async def test_generate_clean_portrait_reuses_source_conversation_without_reupload(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (120, 130, 140)).save(crop)
    artifact = tmp_path / "generated.png"
    Image.new("RGB", (576, 1024), (10, 20, 30)).save(artifact)
    output = tmp_path / "out" / "portrait.png"

    calls = {}

    class FakeImage:
        def generate(self, prompt, **kwargs):
            calls["prompt"] = prompt
            calls["kwargs"] = kwargs
            return SimpleNamespace(
                state="verified",
                output_path=str(artifact),
                reason=None,
            )

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(image=FakeImage()))

    conversation = "https://chatgpt.com/c/existing-comic"
    path, protected, digest = await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        conversation_url=conversation,
        panel_index=0,
        panel_context="CHAR_1: Xin chào",
        panel_box={"x": 10, "y": 20, "w": 800, "h": 500},
        source_width=1200,
        source_height=1600,
        visual_anchor="CHAR_1 đứng trái, quay phải; nhân vật còn lại ở giường bên phải.",
    )

    assert calls["kwargs"]["conversation"] == conversation
    assert calls["kwargs"]["attachments"] == []
    assert calls["kwargs"]["conversation_attachment"] == "name:p0.png"
    assert calls["kwargs"]["reference_width"] == 800
    assert calls["kwargs"]["reference_height"] == 500
    assert 'p0.png' in calls["prompt"]
    assert "KHUNG 1" in calls["prompt"]
    assert "9:16" in calls["prompt"]
    assert path == output
    assert protected == {"x": 0, "y": 0, "w": 576, "h": 1024}
    assert len(digest) == 64


@pytest.mark.asyncio
async def test_generate_clean_portrait_reuses_exact_intent_cache_without_provider(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (120, 130, 140)).save(crop)
    artifact = tmp_path / "generated.png"
    Image.new("RGB", (576, 1024), (10, 20, 30)).save(artifact)
    output = tmp_path / "panel" / "portrait.png"
    calls = []

    class FakeImage:
        def generate(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return SimpleNamespace(
                state="verified",
                output_path=str(artifact),
                reason=None,
                conversation_url="https://chatgpt.com/c/existing-comic",
                assistant_message_id="image-message",
                observation_id="image-observation",
                turn_testid="conversation-turn-10",
            )

    monkeypatch.setattr(
        provider,
        "_client",
        lambda: SimpleNamespace(image=FakeImage()),
    )

    kwargs = dict(
        conversation_url="https://chatgpt.com/c/existing-comic",
        panel_index=2,
        panel_context="CHAR_1: dialogue",
        panel_box={"x": 10, "y": 20, "w": 800, "h": 500},
        source_width=1200,
        source_height=1600,
        visual_anchor="Bò quay sang trái; thỏ ngồi bên phải.",
    )

    first = await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        **kwargs,
    )
    assert len(calls) == 1
    first_sha = first[2]

    def forbidden_client():
        raise AssertionError("cached intent must not open GPT FullProxy")

    monkeypatch.setattr(provider, "_client", forbidden_client)
    output.unlink()

    second = await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        **kwargs,
    )

    assert second[2] == first_sha
    assert output.is_file()
    assert len(calls) == 1
    receipts = list((output.parent / "generation-cache").glob("*.json"))
    artifacts = list((output.parent / "generation-cache").glob("*.png"))
    assert len(receipts) == 1
    assert len(artifacts) == 1


@pytest.mark.asyncio
async def test_force_regenerate_is_the_only_cache_bypass(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (120, 130, 140)).save(crop)
    artifact = tmp_path / "generated.png"
    Image.new("RGB", (576, 1024), (10, 20, 30)).save(artifact)
    output = tmp_path / "panel" / "portrait.png"
    calls = []

    class FakeImage:
        def generate(self, prompt, **kwargs):
            calls.append((prompt, kwargs))
            return SimpleNamespace(
                state="verified",
                output_path=str(artifact),
                reason=None,
            )

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(image=FakeImage()))
    kwargs = dict(
        conversation_url="https://chatgpt.com/c/existing-comic",
        panel_index=2,
        panel_context="",
        panel_box={"x": 10, "y": 20, "w": 800, "h": 500},
        source_width=1200,
        source_height=1600,
        visual_anchor="Bò quay sang trái; thỏ ngồi bên phải.",
    )

    await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        **kwargs,
    )
    await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        force_regenerate=True,
        **kwargs,
    )

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_generation_cache_corruption_fails_closed_without_resend(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (120, 130, 140)).save(crop)
    artifact = tmp_path / "generated.png"
    Image.new("RGB", (576, 1024), (10, 20, 30)).save(artifact)
    output = tmp_path / "panel" / "portrait.png"

    class FakeImage:
        def generate(self, prompt, **kwargs):
            return SimpleNamespace(
                state="verified",
                output_path=str(artifact),
                reason=None,
            )

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(image=FakeImage()))
    kwargs = dict(
        conversation_url="https://chatgpt.com/c/existing-comic",
        panel_index=1,
        panel_context="",
        panel_box={"x": 10, "y": 20, "w": 800, "h": 500},
        source_width=1200,
        source_height=1600,
        visual_anchor="Thỏ ngồi giữa khung và quay sang trái.",
    )
    await provider.generate_clean_portrait(
        crop,
        [{"x": 20, "y": 30, "w": 100, "h": 60}],
        output,
        **kwargs,
    )
    cache_file = next((output.parent / "generation-cache").glob("*.png"))
    cache_file.write_bytes(b"tampered")

    monkeypatch.setattr(
        provider,
        "_client",
        lambda: (_ for _ in ()).throw(AssertionError("must not resend corrupt cached intent")),
    )

    with pytest.raises(RuntimeError, match="không được gửi lại"):
        await provider.generate_clean_portrait(
            crop,
            [{"x": 20, "y": 30, "w": 100, "h": 60}],
            output,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_ai_generate_reuses_accepted_history_without_provider(tmp_path, monkeypatch):
    portrait = tmp_path / "portrait.png"
    Image.new("RGB", (576, 1024), (1, 2, 3)).save(portrait)
    digest = comic_api.sha256_file(portrait)
    panel = {
        "id": "panel-history",
        "project_id": "project-history",
        "display_order": 1,
        "visual_anchor": "anchor đủ chi tiết cho panel hai",
        "status": "AI_IMAGE_READY",
        "portrait_path": str(portrait),
        "portrait_sha256": digest,
    }

    async def fake_panel(_panel_id):
        return dict(panel)

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-history",
                "ai_conversation_url": "https://chatgpt.com/c/history-chat",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [],
        }

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "_safe_file", lambda _value: portrait)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256=digest,
            accepted_output_message_id="msg-history",
            rejected_sha256=frozenset(),
        ),
    )
    monkeypatch.setattr(
        comic_api,
        "generate_clean_portrait",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("accepted historical output must not call provider")
        ),
    )

    result = await comic_api.ai_generate_panel(
        "panel-history",
        comic_api.AIImageBody(confirm_paid=True),
    )

    assert result["deduplicated"] is True
    assert result["reconcile_source"] == "history"
    assert result["portrait_sha256"] == digest


@pytest.mark.asyncio
@pytest.mark.parametrize("use_local_crop", [False, True])
async def test_ai_generate_invalidates_rejected_active_hash_before_provider(tmp_path, monkeypatch, use_local_crop):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (100, 110, 120)).save(crop)
    rejected = "b" * 64
    replacement = "c" * 64
    panel = {
        "id": "panel-rejected",
        "project_id": "project-rejected",
        "display_order": 2,
        "visual_anchor": "bò quay đầu rõ sang trái, thỏ nằm bên phải",
        "status": "AI_IMAGE_READY",
        "portrait_path": str(tmp_path / "wrong.png"),
        "portrait_sha256": rejected,
        "approved_sha256": None,
        "protected_json": "{}",
        "crop_path": str(crop),
        "mask_json": "[]",
        "x": 10,
        "y": 20,
        "w": 800,
        "h": 500,
    }
    cleared = []

    async def fake_panel(_panel_id):
        return dict(panel)

    async def fake_update(_panel_id, **changes):
        panel.update(changes)

    async def fake_clear(project_id):
        cleared.append(project_id)

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-rejected",
                "ai_conversation_url": "https://chatgpt.com/c/history-chat",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [{"id": "panel-rejected", "dialogues": []}],
        }

    async def fake_generate(*_args, **_kwargs):
        assert _kwargs.get("use_local_crop", False) is use_local_crop
        assert panel["status"] == "EXTRACTED"
        assert panel["portrait_path"] is None
        assert panel["portrait_sha256"] is None
        return tmp_path / "new.png", {"x": 0, "y": 0, "w": 576, "h": 1024}, replacement

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api.store, "update_panel", fake_update)
    monkeypatch.setattr(comic_api.store, "clear_shots", fake_clear)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "_safe_file", lambda _value: crop)
    monkeypatch.setattr(comic_api, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256=None,
            accepted_output_message_id=None,
            rejected_sha256=frozenset({rejected}),
        ),
    )
    monkeypatch.setattr(comic_api, "generate_clean_portrait", fake_generate)

    result = await comic_api.ai_generate_panel(
        "panel-rejected",
        comic_api.AIImageBody(confirm_paid=True, use_local_crop=use_local_crop),
    )

    assert result["portrait_sha256"] == replacement
    assert panel["status"] == "AI_IMAGE_READY"
    assert rejected not in {panel.get("portrait_sha256")}
    assert cleared


@pytest.fixture
def local_crop_generation(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (80, 50), (12, 34, 56)).save(crop)
    artifact = tmp_path / "generated.png"
    calls = []

    class ImageService:
        def generate(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            with Image.open(crop) as source:
                Image.new("RGB", (90, 160), source.getpixel((0, 0))).save(artifact)
            return SimpleNamespace(state="verified", output_path=str(artifact), reason=None,
                                   conversation_url="https://chatgpt.com/c/new-image-session")

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(image=ImageService()))
    kwargs = dict(conversation_url="https://chatgpt.com/c/inaccessible-old-session",
                  panel_index=2, panel_box={"x": 10, "y": 20, "w": 80, "h": 50},
                  source_width=120, source_height=160,
                  visual_anchor="Bò quay đầu sang TRÁI, miệng KHÉP; thỏ dựng thân trên.",
                  use_local_crop=True)
    return SimpleNamespace(crop=crop, regions=[{"x": 1, "y": 2, "w": 10, "h": 8}],
                           output=tmp_path / "panel" / "portrait.png", kwargs=kwargs, calls=calls)


@pytest.mark.asyncio
async def test_local_crop_generation_uses_original_bytes_in_new_conversation(local_crop_generation):
    case = local_crop_generation
    path, _, digest = await provider.generate_clean_portrait(case.crop, case.regions, case.output, **case.kwargs)
    call, = case.calls
    assert call["attachments"] == [case.crop]
    assert not call.get("conversation") and not call.get("conversation_attachment")
    assert case.kwargs["visual_anchor"] in call["prompt"]
    assert "KHUNG 3" in call["prompt"] and "9:16" in call["prompt"]
    assert "TURN ĐẦU" not in call["prompt"] and "Không upload lại bytes" not in call["prompt"]
    assert path == case.output and digest == provider.sha256_file(path)


@pytest.mark.asyncio
async def test_local_crop_cache_is_bound_to_exact_source_bytes(local_crop_generation):
    case = local_crop_generation
    first = await provider.generate_clean_portrait(case.crop, case.regions, case.output, **case.kwargs)
    case.output.unlink()
    repeat = await provider.generate_clean_portrait(case.crop, case.regions, case.output, **case.kwargs)
    assert repeat[2] == first[2] and len(case.calls) == 1
    Image.new("RGB", (80, 50), (90, 80, 70)).save(case.crop)
    changed = await provider.generate_clean_portrait(case.crop, case.regions, case.output, **case.kwargs)
    assert changed[2] != first[2] and len(case.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["uncertain", "needs_input"])
async def test_local_crop_generation_does_not_retry_missing_receipt(local_crop_generation, monkeypatch, state):
    case = local_crop_generation
    calls = []

    class UnavailableService:
        def generate(self, *args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(state=state, output_path=None, reason="Missing receipt")

    monkeypatch.setattr(provider, "_client", lambda: SimpleNamespace(image=UnavailableService()))
    with pytest.raises(RuntimeError, match=state):
        await provider.generate_clean_portrait(case.crop, case.regions, case.output, **case.kwargs)
    assert len(calls) == 1 and not case.output.exists()


@pytest.mark.asyncio
async def test_ai_generate_recovers_missing_accepted_history_without_generate(
    tmp_path, monkeypatch
):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (100, 110, 120)).save(crop)
    recovered = tmp_path / "recovered.png"
    Image.new("RGB", (576, 1024), (4, 5, 6)).save(recovered)
    digest = comic_api.sha256_file(recovered)
    panel = {
        "id": "panel-missing-history",
        "project_id": "project-history",
        "display_order": 1,
        "visual_anchor": "anchor đủ chi tiết cho panel hai",
        "status": "EXTRACTED",
        "portrait_path": None,
        "portrait_sha256": None,
        "crop_path": str(crop),
        "mask_json": "[]",
        "x": 10,
        "y": 20,
        "w": 800,
        "h": 500,
    }
    updates = []

    async def fake_panel(_panel_id):
        return dict(panel)

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-history",
                "ai_conversation_url": "https://chatgpt.com/c/history-chat",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [{"id": "panel-missing-history", "dialogues": []}],
        }

    async def fake_recover(output_path, **kwargs):
        assert kwargs["conversation_url"] == "https://chatgpt.com/c/history-chat"
        assert kwargs["output_message_id"] == "msg-history"
        assert kwargs["expected_sha256"] == digest
        assert kwargs["expected_width"] == 576
        assert kwargs["expected_height"] == 1024
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(recovered.read_bytes())
        return output_path, {"x": 0, "y": 0, "w": 576, "h": 1024}, digest

    async def fake_update(_panel_id, **changes):
        updates.append(changes)

    async def fake_clear(_project_id):
        return None

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api.store, "update_panel", fake_update)
    monkeypatch.setattr(comic_api.store, "clear_shots", fake_clear)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256=digest,
            accepted_output_message_id="msg-history",
            accepted_width=576,
            accepted_height=1024,
            rejected_sha256=frozenset(),
        ),
    )
    monkeypatch.setattr(
        comic_api,
        "find_project_artifact_by_sha256",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(comic_api, "recover_historical_portrait", fake_recover)
    monkeypatch.setattr(
        comic_api,
        "generate_clean_portrait",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("historical recovery must not Generate")
        ),
    )

    result = await comic_api.ai_generate_panel(
        "panel-missing-history",
        comic_api.AIImageBody(confirm_paid=True),
    )

    assert result["deduplicated"] is True
    assert result["reconcile_source"] == "history_remote"
    assert result["portrait_sha256"] == digest
    assert updates[-1]["status"] == "AI_IMAGE_READY"


@pytest.mark.asyncio
async def test_ai_generate_blocks_when_accepted_history_recovery_fails(
    tmp_path, monkeypatch
):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (100, 110, 120)).save(crop)
    panel = {
        "id": "panel-missing-history",
        "project_id": "project-history",
        "display_order": 1,
        "visual_anchor": "anchor đủ chi tiết cho panel hai",
        "status": "EXTRACTED",
        "portrait_path": None,
        "portrait_sha256": None,
        "crop_path": str(crop),
        "mask_json": "[]",
        "x": 10,
        "y": 20,
        "w": 800,
        "h": 500,
    }

    async def fake_panel(_panel_id):
        return dict(panel)

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-history",
                "ai_conversation_url": "https://chatgpt.com/c/history-chat",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [{"id": "panel-missing-history", "dialogues": []}],
        }

    async def failed_recovery(*_args, **_kwargs):
        raise RuntimeError("not provable")

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256="a" * 64,
            accepted_output_message_id="msg-history",
            accepted_width=576,
            accepted_height=1024,
            rejected_sha256=frozenset(),
        ),
    )
    monkeypatch.setattr(
        comic_api,
        "find_project_artifact_by_sha256",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(comic_api, "recover_historical_portrait", failed_recovery)
    monkeypatch.setattr(
        comic_api,
        "generate_clean_portrait",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("failed historical recovery must not Generate")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await comic_api.ai_generate_panel(
            "panel-missing-history",
            comic_api.AIImageBody(confirm_paid=True),
        )

    assert exc_info.value.status_code == 409
    assert "chặn resend" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_ai_generate_force_bypasses_missing_accepted_history(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (800, 500), (100, 110, 120)).save(crop)
    panel = {
        "id": "panel-force-history",
        "project_id": "project-history",
        "display_order": 1,
        "visual_anchor": "anchor đủ chi tiết cho panel hai",
        "status": "EXTRACTED",
        "portrait_path": None,
        "portrait_sha256": None,
        "crop_path": str(crop),
        "mask_json": "[]",
        "x": 10,
        "y": 20,
        "w": 800,
        "h": 500,
    }

    async def fake_panel(_panel_id):
        return dict(panel)

    async def fake_update(_panel_id, **changes):
        panel.update(changes)

    async def fake_clear(_project_id):
        return None

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-history",
                "ai_conversation_url": "https://chatgpt.com/c/history-chat",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [{"id": "panel-force-history", "dialogues": []}],
        }

    async def fake_generate(*_args, **kwargs):
        assert kwargs["force_regenerate"] is True
        return tmp_path / "new.png", {"x": 0, "y": 0, "w": 576, "h": 1024}, "d" * 64

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api.store, "update_panel", fake_update)
    monkeypatch.setattr(comic_api.store, "clear_shots", fake_clear)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "_safe_file", lambda _value: crop)
    monkeypatch.setattr(comic_api, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256="a" * 64,
            accepted_output_message_id="msg-history",
            rejected_sha256=frozenset(),
        ),
    )
    monkeypatch.setattr(comic_api, "generate_clean_portrait", fake_generate)

    result = await comic_api.ai_generate_panel(
        "panel-force-history",
        comic_api.AIImageBody(confirm_paid=True, force=True),
    )

    assert result["portrait_sha256"] == "d" * 64


@pytest.mark.asyncio
async def test_ai_generate_blocks_missing_visual_anchor_before_provider(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(crop)

    async def fake_panel(_panel_id):
        return {
            "id": "panel-legacy",
            "project_id": "project-1",
            "crop_path": str(crop),
            "mask_json": '[{"x":1,"y":2,"w":20,"h":10}]',
            "display_order": 0,
            "visual_anchor": None,
        }

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(
        comic_api,
        "generate_clean_portrait",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider must not run")),
    )

    with pytest.raises(HTTPException) as exc_info:
        await comic_api.ai_generate_panel(
            "panel-legacy",
            comic_api.AIImageBody(confirm_paid=True),
        )

    assert exc_info.value.status_code == 409
    assert "visual anchor" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_approve_panel_does_not_require_visual_anchor_prose(tmp_path, monkeypatch):
    portrait = tmp_path / "portrait.png"
    Image.new("RGB", (576, 1024), (1, 2, 3)).save(portrait)

    async def fake_panel(_panel_id):
        return {
            "id": "panel-legacy",
            "project_id": "project",
            "display_order": 0,
            "portrait_path": str(portrait),
            "portrait_sha256": comic_api.sha256_file(portrait),
            "visual_anchor": None,
            "status": "AI_IMAGE_READY",
        }

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, '_safe_file', lambda path: portrait)
    async def details(_):
        return {'project': {'id':'project', 'ai_conversation_url':None}}
    changes = []
    async def update(*args, **kwargs):
        changes.append(kwargs)
    monkeypatch.setattr(comic_api, '_details', details)
    monkeypatch.setattr(comic_api.store, 'update_panel', update)
    result = await comic_api.approve_panel('panel-legacy')
    assert result['status'] == 'AI_IMAGE_APPROVED'
    assert changes[0]['approved_sha256'] == comic_api.sha256_file(portrait)


@pytest.mark.asyncio
async def test_ai_generate_requires_source_conversation(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    Image.new("RGB", (100, 100), (255, 255, 255)).save(crop)

    async def fake_panel(_panel_id):
        return {
            "id": "panel-1",
            "project_id": "project-1",
            "crop_path": str(crop),
            "mask_json": '[{"x":1,"y":2,"w":20,"h":10}]',
            "display_order": 0,
            "visual_anchor": "CHAR_1 đứng bên trái.",
        }

    async def fake_details(_project_id):
        return {
            "project": {"id": "project-1", "ai_conversation_url": None},
            "panels": [],
        }

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "project_dir", lambda _project_id: tmp_path)
    monkeypatch.setattr(comic_api, "_safe_file", lambda _value: crop)

    with pytest.raises(HTTPException) as exc_info:
        await comic_api.ai_generate_panel(
            "panel-1",
            comic_api.AIImageBody(confirm_paid=True),
        )

    assert exc_info.value.status_code == 409
    assert "conversation" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_three_panels_reuse_one_conversation_without_reupload(tmp_path, monkeypatch):
    artifact = tmp_path / "generated.png"
    Image.new("RGB", (576, 1024), (20, 30, 40)).save(artifact)
    calls = []

    class FakeImage:
        def generate(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            return SimpleNamespace(
                state="verified",
                output_path=str(artifact),
                reason=None,
            )

    client = SimpleNamespace(image=FakeImage())
    monkeypatch.setattr(provider, "_client", lambda: client)

    conversation = "https://chatgpt.com/c/one-comic-session"
    for panel_index in range(3):
        crop = tmp_path / f"crop-{panel_index}.png"
        Image.new("RGB", (800, 500), (100 + panel_index, 120, 140)).save(crop)
        output = tmp_path / f"out-{panel_index}.png"
        await provider.generate_clean_portrait(
            crop,
            [{"x": 20, "y": 30, "w": 100, "h": 60}],
            output,
            conversation_url=conversation,
            panel_index=panel_index,
            panel_context=f"CHAR_{panel_index + 1}: dialogue",
            panel_box={"x": 10, "y": 20 + panel_index * 100, "w": 800, "h": 500},
            source_width=1200,
            source_height=1600,
            visual_anchor=f"ANCHOR_PANEL_{panel_index + 1}",
        )

    assert len(calls) == 3
    assert all(call["conversation"] == conversation for call in calls)
    assert all(call["attachments"] == [] for call in calls)
    assert [call["conversation_attachment"] for call in calls] == [
        "name:p0.png",
        "name:p1.png",
        "name:p2.png",
    ]
    assert all(call["reference_width"] == 800 for call in calls)
    assert all(call["reference_height"] == 500 for call in calls)
    assert ["KHUNG 1" in calls[0]["prompt"], "KHUNG 2" in calls[1]["prompt"], "KHUNG 3" in calls[2]["prompt"]] == [True, True, True]
    for index, call in enumerate(calls, start=1):
        assert f"ANCHOR_PANEL_{index}" in call["prompt"]
        for other in range(1, 4):
            if other != index:
                assert f"ANCHOR_PANEL_{other}" not in call["prompt"]


@pytest.mark.asyncio
async def test_backfill_visual_anchors_uses_one_text_reply_in_same_conversation(monkeypatch):
    calls = {"open": [], "reply": 0, "wait": 0}

    class FakeHandle:
        def reply(self, *, text, idempotency_key, visible):
            calls["reply"] += 1
            assert "TURN ĐẦU" in text
            assert "output ảnh AI cũ" in text
            assert idempotency_key.startswith("comicreels-visual-anchor-v1:")
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "panels":[
                    {"panel_index":0,"visual_anchor":"Bò đứng bên trái quay sang phải; thỏ và bò sữa nằm trên giường bên phải."},
                    {"panel_index":1,"visual_anchor":"Thỏ ngồi thẳng ở giữa giường quay sang trái nhìn bò; bò sữa nằm bên phải."},
                    {"panel_index":2,"visual_anchor":"Bò ở bên trái quay lưng bước sang trái; thỏ ngồi trên giường ở giữa và bò sữa nằm bên phải."}
                  ]
                }''',
                user_message=None,
            )

        def wait_for_new_message(self, **_kwargs):
            calls["wait"] += 1
            raise AssertionError("stable assistant receipt must avoid second wait")

    class FakeChat:
        def open(self, conversation):
            calls["open"].append(conversation)
            return FakeHandle()

    panels = [
        {"panel_index": i, "x": 0, "y": i * 100, "w": 800, "h": 500, "dialogues": []}
        for i in range(3)
    ]
    conversation = "https://chatgpt.com/c/existing-comic"

    anchors = await provider.backfill_visual_anchors_in_conversation(
        conversation,
        panels,
        source_width=1200,
        source_height=1600,
        client=SimpleNamespace(chat=FakeChat()),
    )

    assert calls == {"open": [conversation], "reply": 1, "wait": 0}
    assert set(anchors) == {0, 1, 2}
    assert "Thỏ ngồi thẳng" in anchors[1]
    assert "quay lưng" in anchors[2]


@pytest.mark.asyncio
async def test_backfill_visual_anchors_rejects_partial_receipt(monkeypatch):
    class FakeHandle:
        def reply(self, **_kwargs):
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "panels":[
                    {"panel_index":0,"visual_anchor":"Panel zero has a sufficiently detailed source visual anchor."},
                    {"panel_index":1,"visual_anchor":"Panel one has a sufficiently detailed source visual anchor."}
                  ]
                }''',
                user_message=None,
            )

    class FakeChat:
        def open(self, _conversation):
            return FakeHandle()

    panels = [
        {"panel_index": i, "x": 0, "y": i * 100, "w": 800, "h": 500, "dialogues": []}
        for i in range(3)
    ]

    with pytest.raises(RuntimeError, match="2/3"):
        await provider.backfill_visual_anchors_in_conversation(
            "https://chatgpt.com/c/existing-comic",
            panels,
            source_width=1200,
            source_height=1600,
            client=SimpleNamespace(chat=FakeChat()),
        )


@pytest.mark.asyncio
async def test_validate_visual_anchors_marks_only_wrong_panel(monkeypatch):
    calls = {"open": [], "reply": 0}

    class FakeHandle:
        def reply(self, *, text, idempotency_key, visible):
            calls["reply"] += 1
            assert "TURN ĐẦU" in text
            assert "matches_source" in text
            assert idempotency_key.startswith("comicreels-visual-anchor-validate-v1:")
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "panels":[
                    {"panel_index":0,"matches_source":true,"corrected_anchor":"","reason":"đúng"},
                    {"panel_index":1,"matches_source":true,"corrected_anchor":"","reason":"đúng"},
                    {"panel_index":2,"matches_source":false,
                     "corrected_anchor":"Bò cam ở bên trái đã quay đầu và thân sang trái; thỏ trắng ngồi trên giường giữa-phải, bò sữa nằm bên phải.",
                     "reason":"anchor cũ ghi sai hướng bò"}
                  ]
                }''',
                user_message=None,
            )

    class FakeChat:
        def open(self, conversation):
            calls["open"].append(conversation)
            return FakeHandle()

    panels = [
        {
            "panel_index": index,
            "x": 0,
            "y": index * 100,
            "w": 800,
            "h": 500,
            "visual_anchor": f"CURRENT_ANCHOR_PANEL_{index + 1} đủ dài để validate.",
            "dialogues": [],
        }
        for index in range(3)
    ]
    conversation = "https://chatgpt.com/c/existing-comic"

    result = await provider.validate_visual_anchors_in_conversation(
        conversation,
        panels,
        source_width=1200,
        source_height=1600,
        client=SimpleNamespace(chat=FakeChat()),
    )

    assert calls == {"open": [conversation], "reply": 1}
    assert result[0]["matches_source"] is True
    assert result[1]["matches_source"] is True
    assert result[2]["matches_source"] is False
    assert "quay đầu và thân sang trái" in result[2]["corrected_anchor"]


@pytest.mark.asyncio
async def test_validate_visual_anchors_rejects_partial_response():
    class FakeHandle:
        def reply(self, **_kwargs):
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "panels":[
                    {"panel_index":0,"matches_source":true,"corrected_anchor":"","reason":"ok"}
                  ]
                }''',
                user_message=None,
            )

    panels = [
        {
            "panel_index": index,
            "x": 0,
            "y": index * 100,
            "w": 800,
            "h": 500,
            "visual_anchor": f"CURRENT_ANCHOR_PANEL_{index + 1} đủ dài để validate.",
            "dialogues": [],
        }
        for index in range(2)
    ]

    with pytest.raises(RuntimeError, match="1/2"):
        await provider.validate_visual_anchors_in_conversation(
            "https://chatgpt.com/c/existing-comic",
            panels,
            source_width=1200,
            source_height=1600,
            client=SimpleNamespace(chat=SimpleNamespace(open=lambda _url: FakeHandle())),
        )


@pytest.mark.asyncio
async def test_verify_dialogues_reuses_exact_conversation_without_attachments(monkeypatch):
    calls = {"open": [], "reply": [], "wait": []}

    class FakeHandle:
        def reply(self, *, text, idempotency_key, visible):
            calls["reply"].append({
                "text": text,
                "idempotency_key": idempotency_key,
                "visible": visible,
            })
            return SimpleNamespace(
                state="completed",
                reason=None,
                user_message=SimpleNamespace(provider_message_id="user-msg-1"),
            )

        def wait_for_new_message(self, *, after_message_id, role, timeout, visible):
            calls["wait"].append({
                "after_message_id": after_message_id,
                "role": role,
                "timeout": timeout,
                "visible": visible,
            })
            return SimpleNamespace(
                text='''{
                  "dialogues":[
                    {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"LŨ KHỐN NẠN"},
                    {"panel_index":1,"display_order":0,"speaker_id":"CHAR_2","text":"NHƯNG ÔNG CÓ SỪNG SẴN RỒI MÀ"},
                    {"panel_index":2,"display_order":0,"speaker_id":"CHAR_1","text":"Ừ, QUÊN."}
                  ]
                }'''
            )

    class FakeChat:
        def open(self, conversation):
            calls["open"].append(conversation)
            return FakeHandle()

    conversation = "https://chatgpt.com/c/one-comic-session"
    rows = [
        {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"LŨ KHỐN NẠN","verified":False},
        {"panel_index":1,"display_order":0,"speaker_id":"CHAR_2","text":"NHƯNG ỔNG CÓ SỪNG SẴN RỒI MÀ","verified":False},
        {"panel_index":2,"display_order":0,"speaker_id":"CHAR_1","text":"Ừ, QUÊN.","verified":False},
    ]

    result = await provider.verify_dialogues_in_conversation(
        conversation,
        rows,
        client=SimpleNamespace(chat=FakeChat()),
    )

    assert calls["open"] == [conversation]
    assert len(calls["reply"]) == 1
    assert calls["reply"][0]["idempotency_key"].startswith("comicreels-dialogue-verify-v3:")
    assert "upload" in calls["reply"][0]["text"].lower()
    assert calls["wait"][0]["after_message_id"] == "user-msg-1"
    assert calls["wait"][0]["role"] == "assistant"
    assert [row["text"] for row in result] == [
        "LŨ KHỐN NẠN",
        "NHƯNG ÔNG CÓ SỪNG SẴN RỒI MÀ",
        "Ừ, QUÊN.",
    ]
    assert all(row["verified"] is True for row in result)


@pytest.mark.asyncio
async def test_verify_dialogues_consumes_stable_assistant_receipt_without_second_wait():
    calls = {"open": [], "reply": 0, "wait": 0}

    class FakeHandle:
        def reply(self, *, text, idempotency_key, visible):
            calls["reply"] += 1
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "dialogues":[
                    {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"LŨ KHỐN NẠN"},
                    {"panel_index":1,"display_order":0,"speaker_id":"CHAR_2","text":"NHƯNG ÔNG CÓ SỪNG SẴN RỒI MÀ"}
                  ]
                }''',
                user_message=None,
            )

        def wait_for_new_message(self, **_kwargs):
            calls["wait"] += 1
            raise AssertionError("assistant receipt should avoid a second browser wait")

    class FakeChat:
        def open(self, conversation):
            calls["open"].append(conversation)
            return FakeHandle()

    rows = [
        {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"LŨ KHỐN NẠN"},
        {"panel_index":1,"display_order":0,"speaker_id":"CHAR_2","text":"NHƯNG ỔNG CÓ SỪNG SẴN RỒI MÀ"},
    ]

    result = await provider.verify_dialogues_in_conversation(
        "https://chatgpt.com/c/existing",
        rows,
        client=SimpleNamespace(chat=FakeChat()),
    )

    assert calls["open"] == ["https://chatgpt.com/c/existing"]
    assert calls["reply"] == 1
    assert calls["wait"] == 0
    assert [row["text"] for row in result] == [
        "LŨ KHỐN NẠN",
        "NHƯNG ÔNG CÓ SỪNG SẴN RỒI MÀ",
    ]
    assert all(row["verified"] is True for row in result)


@pytest.mark.asyncio
async def test_verify_dialogues_rejects_partial_assistant_receipt():
    class FakeHandle:
        def reply(self, *, text, idempotency_key, visible):
            return SimpleNamespace(
                state="completed",
                reason=None,
                assistant_text='''{
                  "dialogues":[
                    {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"ONE"}
                  ]
                }''',
                user_message=None,
            )

    class FakeChat:
        def open(self, _conversation):
            return FakeHandle()

    rows = [
        {"panel_index":0,"display_order":0,"speaker_id":"CHAR_1","text":"ONE"},
        {"panel_index":1,"display_order":0,"speaker_id":"CHAR_2","text":"TWO"},
    ]

    with pytest.raises(RuntimeError, match="1/2"):
        await provider.verify_dialogues_in_conversation(
            "https://chatgpt.com/c/existing",
            rows,
            client=SimpleNamespace(chat=FakeChat()),
        )


@pytest.mark.asyncio
async def test_ai_generate_deduplicates_existing_ready_portrait(tmp_path, monkeypatch):
    portrait = tmp_path / "portrait.png"
    Image.new("RGB", (576, 1024), (12, 34, 56)).save(portrait)
    digest = comic_api.sha256_file(portrait)

    async def fake_panel(_panel_id):
        return {
            "id": "panel-ready",
            "project_id": "project-1",
            "display_order": 0,
            "status": "AI_IMAGE_READY",
            "portrait_path": str(portrait),
            "portrait_sha256": digest,
            "visual_anchor": "CHAR_1 đứng bên trái, quay sang phải.",
        }

    async def fake_details(_project_id):
        return {
            "project": {
                "id": "project-1",
                "ai_conversation_url": "https://chatgpt.com/c/no-history",
                "source_width": 1200,
                "source_height": 1600,
            },
            "panels": [],
        }

    async def forbidden_generate(*_args, **_kwargs):
        raise AssertionError("provider must not run for an already generated panel")

    monkeypatch.setattr(comic_api.store, "panel", fake_panel)
    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "provider_status", lambda: {"configured": True})
    monkeypatch.setattr(comic_api, "_safe_file", lambda value: portrait if value else portrait)
    monkeypatch.setattr(
        comic_api,
        "image_history_decision",
        lambda *_args, **_kwargs: SimpleNamespace(
            accepted_sha256=None,
            accepted_output_message_id=None,
            rejected_sha256=frozenset(),
        ),
    )
    monkeypatch.setattr(comic_api, "generate_clean_portrait", forbidden_generate)

    result = await comic_api.ai_generate_panel(
        "panel-ready",
        comic_api.AIImageBody(confirm_paid=True, force=False),
    )

    assert result["deduplicated"] is True
    assert result["portrait_sha256"] == digest
    assert result["status"] == "AI_IMAGE_READY"


def test_image_prompt_locks_exact_source_panel_geometry():
    prompt = provider._image_prompt(
        [{"x": 5, "y": 6, "w": 40, "h": 30}],
        "CHAR_2: dialogue",
        1,
        panel_box={"x": 205, "y": 741, "w": 1379, "h": 563},
        source_width=1780,
        source_height=2048,
        visual_anchor="Thỏ ngồi thẳng ở giữa, quay sang trái nhìn bò; bò sữa nằm bên phải.",
        reference_asset_name="p1.png",
    )

    assert "KHUNG 2" in prompt
    assert "x=205, y=741, w=1379, h=563" in prompt
    assert "1780x2048" in prompt
    assert 'p1.png' in prompt
    assert "KHÔNG mượn pose/composition từ panel khác" in prompt
    assert "Thỏ ngồi thẳng ở giữa, quay sang trái nhìn bò" in prompt
    assert "MỌI ảnh AI đã generate ở các TURN SAU chỉ là OUTPUT CŨ" in prompt


@pytest.mark.asyncio
async def test_backfill_route_applies_all_anchors_atomically(monkeypatch):
    details = {
        "project": {
            "id": "project-anchor",
            "ai_conversation_url": "https://chatgpt.com/c/existing",
            "source_width": 1200,
            "source_height": 1600,
        },
        "panels": [
            {
                "id": f"panel-{index}",
                "display_order": index,
                "x": 0,
                "y": index * 500,
                "w": 1200,
                "h": 500,
                "dialogues": [
                    {"speaker_id": f"CHAR_{index + 1}", "text": f"line-{index}"}
                ],
            }
            for index in range(3)
        ],
        "shots": [],
    }
    calls = {"provider": [], "apply": []}

    async def fake_details(_project_id):
        return details

    async def fake_backfill(conversation_url, panels, *, source_width, source_height):
        calls["provider"].append(
            (conversation_url, panels, source_width, source_height)
        )
        return {
            0: "Anchor zero with enough panel-specific geometry for generation.",
            1: "Anchor one with enough panel-specific geometry for generation.",
            2: "Anchor two with enough panel-specific geometry for generation.",
        }

    async def fake_apply(project_id, anchors):
        calls["apply"].append((project_id, anchors))

    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(
        comic_api,
        "backfill_visual_anchors_in_conversation",
        fake_backfill,
    )
    monkeypatch.setattr(
        comic_api.store,
        "apply_visual_anchors_and_invalidate_portraits",
        fake_apply,
    )

    result = await comic_api.backfill_project_visual_anchors("project-anchor")

    assert result is details
    assert len(calls["provider"]) == 1
    assert calls["provider"][0][0] == "https://chatgpt.com/c/existing"
    assert calls["provider"][0][2:] == (1200, 1600)
    assert len(calls["provider"][0][1]) == 3
    assert calls["apply"] == [(
        "project-anchor",
        {
            0: "Anchor zero with enough panel-specific geometry for generation.",
            1: "Anchor one with enough panel-specific geometry for generation.",
            2: "Anchor two with enough panel-specific geometry for generation.",
        },
    )]


@pytest.mark.asyncio
async def test_validate_visual_anchor_route_changes_only_reported_panel(monkeypatch):
    details = {
        "project": {
            "id": "project-anchor-validate",
            "ai_conversation_url": "https://chatgpt.com/c/existing",
            "source_width": 1200,
            "source_height": 1600,
        },
        "panels": [
            {
                "id": f"panel-{index}",
                "display_order": index,
                "x": 0,
                "y": index * 500,
                "w": 1200,
                "h": 500,
                "visual_anchor": f"current anchor {index} with enough source geometry",
                "dialogues": [],
            }
            for index in range(3)
        ],
        "shots": [],
    }
    calls = {"provider": [], "apply": []}

    async def fake_details(_project_id):
        return details

    async def fake_validate(conversation_url, panels, *, source_width, source_height):
        calls["provider"].append((conversation_url, panels, source_width, source_height))
        return {
            0: {
                "matches_source": True,
                "current_anchor": details["panels"][0]["visual_anchor"],
                "corrected_anchor": "",
                "reason": "ok",
            },
            1: {
                "matches_source": True,
                "current_anchor": details["panels"][1]["visual_anchor"],
                "corrected_anchor": "",
                "reason": "ok",
            },
            2: {
                "matches_source": False,
                "current_anchor": details["panels"][2]["visual_anchor"],
                "corrected_anchor": "corrected panel 3 anchor: orange bull turns left, bed remains on right",
                "reason": "wrong direction",
            },
        }

    async def fake_apply(project_id, validations):
        calls["apply"].append((project_id, validations))
        return [2]

    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(
        comic_api,
        "validate_visual_anchors_in_conversation",
        fake_validate,
    )
    monkeypatch.setattr(
        comic_api.store,
        "apply_visual_anchor_validation",
        fake_apply,
    )

    result = await comic_api.validate_project_visual_anchors("project-anchor-validate")

    assert len(calls["provider"]) == 1
    assert len(calls["apply"]) == 1
    assert result["visual_anchor_validation"]["changed_panel_indexes"] == [2]
    assert result["visual_anchor_validation"]["panels"] == [
        {"panel_index": 0, "matches_source": True, "reason": "ok"},
        {"panel_index": 1, "matches_source": True, "reason": "ok"},
        {"panel_index": 2, "matches_source": False, "reason": "wrong direction"},
    ]


@pytest.mark.asyncio
async def test_verify_endpoint_persists_only_fully_verified_transcript(monkeypatch):
    details = {
        "project": {
            "id": "project-1",
            "ai_conversation_url": "https://chatgpt.com/c/existing",
        },
        "panels": [
            {
                "id": "panel-1",
                "display_order": 0,
                "dialogues": [
                    {
                        "id": "dialogue-1",
                        "panel_id": "panel-1",
                        "display_order": 0,
                        "speaker_id": "CHAR_1",
                        "text": "OLD",
                        "verified": 0,
                        "confidence": 0.9,
                    }
                ],
            }
        ],
    }
    writes = []
    clears = []

    async def fake_details(_project_id):
        return details

    async def fake_verify(_conversation_url, _candidates):
        return [{
            "panel_index": 0,
            "display_order": 0,
            "speaker_id": "CHAR_1",
            "text": "NEW",
            "verified": True,
        }]

    async def fake_upsert(panel_id, **kwargs):
        writes.append((panel_id, kwargs))
        return {}

    async def fake_clear(project_id):
        clears.append(project_id)

    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "verify_dialogues_in_conversation", fake_verify)
    monkeypatch.setattr(comic_api.store, "upsert_dialogue", fake_upsert)
    monkeypatch.setattr(comic_api.store, "clear_shots", fake_clear)

    await comic_api.verify_project_dialogues("project-1")

    assert writes == [(
        "panel-1",
        {
            "dialogue_id": "dialogue-1",
            "order": 0,
            "speaker_id": "CHAR_1",
            "text": "NEW",
            "verified": True,
            "confidence": 0.9,
        },
    )]
    assert clears == ["project-1"]


@pytest.mark.asyncio
async def test_verify_endpoint_rejects_unverified_result_without_partial_commit(monkeypatch):
    details = {
        "project": {
            "id": "project-1",
            "ai_conversation_url": "https://chatgpt.com/c/existing",
        },
        "panels": [
            {
                "id": "panel-1",
                "display_order": 0,
                "dialogues": [
                    {
                        "id": "dialogue-1",
                        "panel_id": "panel-1",
                        "display_order": 0,
                        "speaker_id": "CHAR_1",
                        "text": "NHƯNG ỔNG CÓ SỪNG SẴN RỒI MÀ",
                        "verified": 0,
                        "confidence": 0.9,
                    }
                ],
            }
        ],
    }
    writes = []
    clears = []

    async def fake_details(_project_id):
        return details

    async def fake_verify(_conversation_url, _candidates):
        return [{
            "panel_index": 0,
            "display_order": 0,
            "speaker_id": "CHAR_1",
            "text": "NHƯNG ỔNG CÓ SỪNG SẴN RỒI MÀ",
            "verified": False,
        }]

    async def fake_upsert(*args, **kwargs):
        writes.append((args, kwargs))
        return {}

    async def fake_clear(project_id):
        clears.append(project_id)

    monkeypatch.setattr(comic_api, "_details", fake_details)
    monkeypatch.setattr(comic_api, "verify_dialogues_in_conversation", fake_verify)
    monkeypatch.setattr(comic_api.store, "upsert_dialogue", fake_upsert)
    monkeypatch.setattr(comic_api.store, "clear_shots", fake_clear)

    with pytest.raises(HTTPException) as exc_info:
        await comic_api.verify_project_dialogues("project-1")

    assert exc_info.value.status_code == 422
    assert "không cập nhật" in str(exc_info.value.detail)
    assert writes == []
    assert clears == []


async def _seed_three_dialogue_verify_project(tmp_path, monkeypatch, project_id: str):
    monkeypatch.setattr(store_module, "ROOT", tmp_path / "comicreels")
    monkeypatch.setattr(store_module, "DB_PATH", tmp_path / "comicreels" / "comicreels.db")
    test_store = ComicStore()
    monkeypatch.setattr(comic_api, "store", test_store)

    await test_store.create_project(
        project_id=project_id,
        name="verify-regression",
        source_path=str(tmp_path / "source.png"),
        sha256="a" * 64,
        mime="image/png",
        width=1200,
        height=1800,
    )
    conversation_url = "https://chatgpt.com/c/6ab651a6-9940-83ec-87d9-854057fa2af0"
    await test_store.set_project_ai_session(
        project_id,
        conversation_url=conversation_url,
        assistant_message_id="analysis-message",
    )
    texts = [
        "LŨ KHỐN NẠN, SAO TỤI MÀY DÁM CẮM SỪNG TAO!!",
        "NHƯNG ỔNG CÓ SỪNG SẴN RỒI MÀ",
        "Ừ, QUÊN.",
    ]
    speakers = ["CHAR_1", "CHAR_2", "CHAR_1"]
    await test_store.replace_analysis(
        project_id,
        panels=[
            {"x": 0, "y": 0, "w": 1200, "h": 600},
            {"x": 0, "y": 600, "w": 1200, "h": 600},
            {"x": 0, "y": 1200, "w": 1200, "h": 600},
        ],
        dialogues=[
            {
                "panel_index": index,
                "display_order": 0,
                "speaker_id": speaker,
                "text": text,
                "confidence": 0.95,
                "verified": False,
            }
            for index, (speaker, text) in enumerate(zip(speakers, texts, strict=True))
        ],
    )
    seeded = await test_store.get_project(project_id)
    first_panel_id = seeded["panels"][0]["id"]
    await test_store.insert_shot({
        "id": "stale-shot",
        "project_id": project_id,
        "panel_id": first_panel_id,
        "display_order": 0,
        "speaker_id": "CHAR_1",
        "dialogue_text": texts[0],
        "duration_s": 8,
        "model_family": "omni_flash",
        "prompt": "stale prompt",
        "image_sha256": "b" * 64,
    })
    return test_store, conversation_url, texts, speakers


@pytest.mark.asyncio
async def test_verify_endpoint_three_panel_receipt_persists_all_verified_and_clears_stale_shots(
    tmp_path, monkeypatch
):
    project_id = "project-three-panel-success"
    test_store, conversation_url, texts, speakers = await _seed_three_dialogue_verify_project(
        tmp_path, monkeypatch, project_id
    )

    async def fake_verify(observed_conversation_url, candidates):
        assert observed_conversation_url == conversation_url
        assert candidates == [
            {
                "panel_index": index,
                "display_order": 0,
                "speaker_id": speaker,
                "text": text,
            }
            for index, (speaker, text) in enumerate(zip(speakers, texts, strict=True))
        ]
        return [
            {
                "panel_index": index,
                "display_order": 0,
                "speaker_id": speaker,
                "text": text,
                "verified": True,
            }
            for index, (speaker, text) in enumerate(zip(speakers, texts, strict=True))
        ]

    monkeypatch.setattr(comic_api, "verify_dialogues_in_conversation", fake_verify)

    response = await comic_api.verify_project_dialogues(project_id)

    assert response["project"]["ai_conversation_url"] == conversation_url
    persisted = await test_store.get_project(project_id)
    assert [
        (panel["dialogues"][0]["speaker_id"], panel["dialogues"][0]["text"], panel["dialogues"][0]["verified"])
        for panel in persisted["panels"]
    ] == [
        (speaker, text, 1)
        for speaker, text in zip(speakers, texts, strict=True)
    ]
    assert persisted["shots"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_mode", ["partial", "false_row"])
async def test_verify_endpoint_three_panel_invalid_receipt_is_atomic(
    tmp_path, monkeypatch, invalid_mode
):
    project_id = f"project-three-panel-{invalid_mode}"
    test_store, conversation_url, texts, speakers = await _seed_three_dialogue_verify_project(
        tmp_path, monkeypatch, project_id
    )

    async def fake_verify(observed_conversation_url, candidates):
        assert observed_conversation_url == conversation_url
        rows = [
            {
                "panel_index": index,
                "display_order": 0,
                "speaker_id": speaker,
                "text": text,
                "verified": True,
            }
            for index, (speaker, text) in enumerate(zip(speakers, texts, strict=True))
        ]
        if invalid_mode == "partial":
            return rows[:2]
        rows[1]["verified"] = False
        return rows

    monkeypatch.setattr(comic_api, "verify_dialogues_in_conversation", fake_verify)

    with pytest.raises(HTTPException) as exc_info:
        await comic_api.verify_project_dialogues(project_id)

    assert exc_info.value.status_code == 422
    persisted = await test_store.get_project(project_id)
    assert [
        (panel["dialogues"][0]["speaker_id"], panel["dialogues"][0]["text"], panel["dialogues"][0]["verified"])
        for panel in persisted["panels"]
    ] == [
        (speaker, text, 0)
        for speaker, text in zip(speakers, texts, strict=True)
    ]
    assert [shot["id"] for shot in persisted["shots"]] == ["stale-shot"]
