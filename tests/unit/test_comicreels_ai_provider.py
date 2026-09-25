from types import SimpleNamespace

import pytest
from PIL import Image

import agent.comicreels.ai_provider as provider
import agent.api.comicreels as comic_api
from fastapi import HTTPException


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
    )

    assert calls["kwargs"]["conversation"] == conversation
    assert calls["kwargs"]["attachments"] == []
    assert "TURN ĐẦU" in calls["prompt"]
    assert "KHUNG 1" in calls["prompt"]
    assert "9:16" in calls["prompt"]
    assert path == output
    assert protected == {"x": 0, "y": 0, "w": 576, "h": 1024}
    assert len(digest) == 64


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
        )

    assert len(calls) == 3
    assert all(call["conversation"] == conversation for call in calls)
    assert all(call["attachments"] == [] for call in calls)
    assert ["KHUNG 1" in calls[0]["prompt"], "KHUNG 2" in calls[1]["prompt"], "KHUNG 3" in calls[2]["prompt"]] == [True, True, True]


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
