from types import SimpleNamespace

import pytest
from PIL import Image

import agent.comicreels.ai_provider as provider


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
            {"x":10,"y":20,"w":100,"h":120,"order":0,"speech_regions":[
              {"x":5,"y":6,"w":40,"h":30,"kind":"speech_bubble"}
            ]}
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
          "panels":[{"x":0,"y":0,"w":300,"h":200,"order":0,"speech_regions":[{"x":10,"y":10,"w":180,"h":80}]}],
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
async def test_generate_clean_portrait_reuses_source_conversation_without_attachment(tmp_path, monkeypatch):
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
    )

    assert calls["kwargs"]["conversation"] == conversation
    assert "attachments" not in calls["kwargs"]
    assert "TURN ĐẦU" in calls["prompt"]
    assert "KHUNG 1" in calls["prompt"]
    assert "9:16" in calls["prompt"]
    assert path == output
    assert protected == {"x": 0, "y": 0, "w": 576, "h": 1024}
    assert len(digest) == 64
