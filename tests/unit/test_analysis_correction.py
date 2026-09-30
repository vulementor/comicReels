"""Local review and deterministic replay only: no clients, browsers or generation."""
import copy
import json
from pathlib import Path

import pytest
from PIL import Image

from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import Campaign, sha256
from agent.thoremix.story_stages import StageJournal, StageRejected, StageUncertain
from agent.thoremix.analysis_correction import review_analysis, reviewed_analysis, canonical
from agent.thoremix.story_operations import normalize_analysis, required_text_regions, text_preservation_verified
from agent.comicreels.prompts import story_timeline, story_video_prompt

POLICY = {"schema":"comicreels.speech-budget.v1", "language":"vi-VN",
          "unit":"whitespace_syllable", "units_per_second":2.7}
WORDS = ["SAO ÔNG CỨ Ủ RŨ SUỐT VẬY?", "MẤY NAY TÔI BUỒN",
         "ĐỂ TÔI KIẾM GÌ CHỌC CHO ÔNG VUI NHÉ", "CÁM ƠN ÔNG"]


def corrected():
    panels = [dict(x=0,y=i*20,w=30,h=20,order=i,confidence=.99,
                   visual_anchor="reviewed source scene",speech_regions=[],text_regions=[]) for i in range(3)]
    panels[2]["text_regions"] = [dict(x=1,y=1,w=20,h=10,kind="sound_effect",text="ĐÙNG",confidence=.99)]
    dialogues = [dict(text=text,panel_index=i//2,display_order=i%2,speaker_id="rabbit" if i%2==0 else "balloon",
                      confidence=.99) for i,text in enumerate(WORDS)]
    return dict(panels=panels,dialogues=dialogues,characters=[],warnings=[])


@pytest.fixture
def failed(tmp_path):
    source = tmp_path/"input"; source.mkdir()
    Image.new("RGB",(30,60),"white").save(source/"story.png")
    settings = Settings(root=str(tmp_path/"app"),input_dir=str(source),enabled=False)
    settings.save()
    campaign = Campaign(settings); job = campaign.reserve("review-test")
    campaign.update(job["id"],"production_failed")
    directory = settings.data/"production"/job["id"]
    request = {"source":job["source"],"source_sha256":job["source_sha256"]}
    journal = StageJournal(directory,source_sha256=job["source_sha256"])
    with pytest.raises(StageRejected):
        journal.run("analysis",request,lambda _p:{"state":"invalid_source","reason":"STORY_DIALOGUE_TOO_LONG"})
    provider = {"state":"verified","assistant_message_id":"original-message",
                "conversation_url":"https://chatgpt.com/c/original","text":"unaltered provider response"}
    atomic_json(directory/"analysis-provider.json",provider)
    spec = {"schema":"thoremix.analysis-review.v1","job_id":job["id"],
            "source_sha256":job["source_sha256"],"analysis_sha256":sha256(directory/"analysis.json"),
            "provider_sha256":sha256(directory/"analysis-provider.json"),
            "reviewed_by":"test reviewer","evidence":"compared source pixels with the saved response",
            "analysis":corrected(),"timing_policy":dict(POLICY)}
    path=settings.directory/"review-spec.json"; atomic_json(path,spec)
    return settings,campaign,job,directory,request,path,spec


def unknown(directory):
    value=json.loads((directory/"analysis.json").read_text())
    value["state"]="UNKNOWN"; atomic_json(directory/"analysis.json",value)


def test_review_is_create_once_preserves_raw_receipts_and_conflicts_fail(failed):
    settings,_,job,directory,_,path,spec=failed
    before={name:(directory/name).read_bytes() for name in ("analysis.json","analysis-provider.json")}
    result=review_analysis(settings,job["id"],path)
    assert result["state"]=="analysis_review_recorded" and result["media_qa"]=="NOT_CHECKED"
    assert {name:(directory/name).read_bytes() for name in before}==before
    receipt=(directory/"analysis-correction.json").read_bytes()
    assert review_analysis(settings,job["id"],path)["state"]=="analysis_review_exists"
    assert (directory/"analysis-correction.json").read_bytes()==receipt
    spec["evidence"]="different correction";atomic_json(path,spec)
    with pytest.raises(ValueError,match="ALREADY_EXISTS"):
        review_analysis(settings,job["id"],path)


def test_review_rejects_wrong_hash_or_downstream_effect(failed):
    settings,_,job,directory,_,path,spec=failed
    original=spec["provider_sha256"];spec["provider_sha256"]="0"*64;atomic_json(path,spec)
    with pytest.raises(ValueError,match="BINDING_CHANGED"):
        review_analysis(settings,job["id"],path)
    spec["provider_sha256"]=original;atomic_json(path,spec)
    (directory/"images.json").write_text('{"state":"UNKNOWN"}')
    with pytest.raises(ValueError,match="DOWNSTREAM_EXISTS"):
        review_analysis(settings,job["id"],path)
    assert not (directory/"analysis-correction.json").exists()


def test_failed_to_unknown_replay_uses_review_without_provider_and_pins_it(failed,monkeypatch):
    from agent.thoremix.story_operations import StoryOperations
    settings,_,job,directory,request,path,_=failed
    review_analysis(settings,job["id"],path);unknown(directory)
    provider_before=(directory/"analysis-provider.json").read_bytes()
    operations=StoryOperations(settings,runtime=object())
    monkeypatch.setattr(operations,"_chat",lambda *_a,**_k:pytest.fail("must not call provider"))
    result=StageJournal(directory,source_sha256=job["source_sha256"]).run(
        "analysis",request,lambda _p:pytest.fail("must reconcile existing stage"),
        reconcile=lambda previous,progress:operations.reconcile("analysis",request,directory,previous,progress))
    assert [d["text"] for d in result["data"]["dialogues"]]==WORDS
    assert len(result["data"]["panels"])==3 and result["data"]["timing_policy"]==POLICY
    assert result["data"]["analysis_correction"]["media_review_required"]
    assert "qa" not in result["data"] and result["files"][0]["sha256"]==sha256(directory/"analysis-correction.json")
    assert (directory/"analysis-provider.json").read_bytes()==provider_before
    (directory/"analysis-correction.json").write_bytes(b"changed")
    with pytest.raises(StageUncertain,match="STAGE_ARTIFACT_CHANGED"):
        StageJournal(directory,source_sha256=job["source_sha256"]).run("analysis",request,lambda _p:None)


def test_replay_refuses_changed_provider_stage_or_new_downstream(failed):
    settings,_,job,directory,request,path,_=failed
    review_analysis(settings,job["id"],path);unknown(directory)
    stage=(directory/"analysis.json").read_bytes()
    record=json.loads(stage);record["request_sha256"]="0"*64;atomic_json(directory/"analysis.json",record)
    with pytest.raises(ValueError,match="STAGE_CHANGED"):
        reviewed_analysis(settings,request,directory)
    (directory/"analysis.json").write_bytes(stage)
    (directory/"flow").mkdir()
    with pytest.raises(ValueError,match="DOWNSTREAM_EXISTS"):
        reviewed_analysis(settings,request,directory)


def test_timing_is_explicit_default_unchanged_and_prompt_uses_same_policy():
    value=corrected()
    with pytest.raises(ValueError,match="STORY_DIALOGUE_TOO_LONG"):
        normalize_analysis(value)
    value["timing_policy"]=POLICY
    with pytest.raises(ValueError,match="STORY_DIALOGUE_TOO_LONG"):
        normalize_analysis(value)  # provider fields never authorize relaxed timing
    normalized=normalize_analysis(value,timing_policy=POLICY)
    timeline=story_timeline(normalized["panels"],timing_policy=POLICY)
    assert timeline==[(0.0,4.42),(4.42,9.21),(9.21,10.0)]
    prompt=story_video_prompt(normalized["panels"],allow_unverified=True,timing_policy=POLICY)
    assert "4.42-9.21s" in prompt and all(prompt.count(text)==1 for text in WORDS)
    assert "ĐÙNG" in prompt and "ĐỪNG" not in prompt
    with pytest.raises(ValueError,match="INVALID_REVIEWED_SPEECH_POLICY"):
        normalize_analysis(value,timing_policy={**POLICY,"units_per_second":4})


def test_sound_effect_needs_exact_preservation_qa_and_review_command_is_bounded():
    from agent.thoremix.managed_desktop import validate_command
    normalized=normalize_analysis(corrected(),timing_policy=POLICY)
    expected=[{"panel_index":2,"kind":"sound_effect","text":"ĐÙNG"}]
    assert required_text_regions(normalized)==expected
    assert not text_preservation_verified(normalized,{})
    assert text_preservation_verified(normalized,{"preserved_text":[{**expected[0],"present":True}]})
    assert not text_preservation_verified(normalized,{"preserved_text":[{**expected[0],"text":"ĐỪNG","present":True}]})
    assert validate_command("review-analysis",["a"*32,"--spec","D:/home/review.json"])
    with pytest.raises(ValueError):
        validate_command("review-analysis",["--root","D:/outside"])
