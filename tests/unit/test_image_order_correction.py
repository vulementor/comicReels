"""Image permutation recovery uses local fixtures; no browser or provider calls."""
import json
from pathlib import Path

import pytest
from PIL import Image

from agent.thoremix import image_order_correction as order
from agent.thoremix.config import Settings, atomic_json
from agent.thoremix.core import Campaign, sha256
from agent.thoremix.story_assets import save_working_assets, validate_draft
from agent.thoremix.story_stages import StageUncertain
from agent.services.flow_browser_state import BrowserStateStore


@pytest.fixture
def ready(tmp_path):
    inputs=tmp_path/"input";inputs.mkdir()
    Image.new("RGB",(30,60),"white").save(inputs/"source.png")
    settings=Settings(root=str(tmp_path/"app"),input_dir=str(inputs),enabled=False);settings.save()
    campaign=Campaign(settings);job=campaign.reserve("order-review")
    directory=settings.data/"production"/job["id"]
    images=directory/"images";images.mkdir(parents=True)
    files=[]
    for index,color in enumerate(("red","green","blue"),1):
        path=images/f"scene-{index:02d}.png";Image.new("RGB",(30,60),color).save(path)
        files.append({"path":str(path),"sha256":sha256(path)})
    result={"state":"verified","files":files,"data":{"conversation_url":"https://chatgpt.com/c/original"}}
    atomic_json(directory/"images.json",{"state":"COMPLETED","source_sha256":job["source_sha256"],"result":result})
    atomic_json(images/"provider.json",{"state":"verified","images":files})
    atomic_json(directory/"image_review.json",{"state":"COMPLETED","source_sha256":job["source_sha256"],"result":{"state":"verified"}})
    for name in ("prompt","provider","upload"):
        atomic_json(directory/("image_review-"+name+".json"),{"original":name})
    atomic_json(directory/"video.json",{"state":"BLOCKED","source_sha256":job["source_sha256"],"result":{"state":"blocked","not_submitted":True,"reason":"FLOW_PREPARATION_ATTACH_REFERENCES"}})
    flow=directory/"flow";flow.mkdir()
    uploads=BrowserStateStore(flow/"uploads.json","thoremix-"+job["source_sha256"][:20])
    project="00000000-0000-0000-0000-000000000001"
    for i,item in enumerate(files,2):
        key=f"upload:{project}:{item['sha256']}:{Path(item['path']).name}"
        uploads.begin(key,"upload",{"project_id":project,"image_sha256":item["sha256"],
            "file_name":Path(item["path"]).name,"mime_type":"image/png"})
        uploads.complete(key,{"project_id":project,"media_id":f"00000000-0000-0000-0000-{i:012d}"})
    atomic_json(flow/"preparation-error.json",{"step":"attach_references","not_submitted":True})
    save_working_assets(settings,job,files)
    spec={"schema":order.SCHEMA,"job_id":job["id"],"source_sha256":job["source_sha256"],
          "images_sha256":sha256(directory/"images.json"),"provider_sha256":sha256(images/"provider.json"),
          "order":[1,2,0],"reviewed_by":"reviewer","evidence":"three original images inspected against source"}
    path=settings.directory/"order-spec.json";atomic_json(path,spec)
    return settings,job,directory,result,path,spec


def test_order_preserves_originals_upload_ids_and_retires_old_qa(ready):
    settings,job,directory,images,path,_=ready
    retained=[directory/"images.json",directory/"images/provider.json",directory/"flow/uploads.json",
              *[Path(item["path"]) for item in images["files"]]]
    before={p:p.read_bytes() for p in retained}
    qa={p.name:p.read_bytes() for p in directory.glob("image_review*.json")}
    video=(directory/"video.json").read_bytes()
    assert order.review_image_order(settings,job["id"],path)["state"]=="image_order_applied"
    assert {p:p.read_bytes() for p in retained}==before
    for name,raw in qa.items():
        assert not (directory/name).exists()
        assert (directory/order.AUDIT/"retired"/name).read_bytes()==raw
    assert (directory/order.AUDIT/"retired/video.json").read_bytes()==video
    corrected=order.reviewed_image_order(settings,job,images)
    assert corrected["files"]==[images["files"][i] for i in (1,2,0)]
    save_working_assets(settings,job,corrected["files"])
    assert [i["sha256"] for i in validate_draft(job["package_dir"],job)["frames"]]==[i["sha256"] for i in corrected["files"]]
    assert "qa" not in corrected


@pytest.mark.parametrize("uncertainty",["video","paid","upload"])
def test_refuses_uncertain_or_paid_flow_before_retiring_any_receipt(ready,uncertainty):
    settings,job,directory,_,path,_=ready
    if uncertainty=="video":
        atomic_json(directory/"video.json",{"state":"SUBMITTING"})
    elif uncertainty=="paid":
        atomic_json(directory/"flow/story-receipt.json",{"state":"SUBMITTING"})
    else:
        p=directory/"flow/uploads.json";value=json.loads(p.read_text())
        next(iter(value["intents"].values()))["state"]="UNKNOWN";atomic_json(p,value)
    with pytest.raises(ValueError):
        order.review_image_order(settings,job["id"],path)
    assert (directory/"image_review.json").exists()
    assert not (directory/order.AUDIT/"plan.json").exists()


def test_interrupted_draft_swap_blocks_pipeline_and_resumes_without_reupload(ready,monkeypatch):
    settings,job,directory,images,path,_=ready
    original=order.os.replace;calls=[]
    def interrupted(src,dst):
        if str(src).endswith(".tmp") and "frame-" in Path(src).name:
            calls.append(str(src))
            if len(calls)==2:
                raise OSError("simulated local interruption")
        return original(src,dst)
    uploads=(directory/"flow/uploads.json").read_bytes()
    monkeypatch.setattr(order.os,"replace",interrupted)
    with pytest.raises(OSError):
        order.review_image_order(settings,job["id"],path)
    with pytest.raises(StageUncertain,match="APPLY_INCOMPLETE"):
        order.ensure_image_order_ready(settings,job)
    monkeypatch.setattr(order.os,"replace",original)
    assert order.review_image_order(settings,job["id"],path)["state"]=="image_order_applied"
    assert (directory/"flow/uploads.json").read_bytes()==uploads
    assert order.reviewed_image_order(settings,job,images)["files"]==[images["files"][i] for i in (1,2,0)]


def test_applied_order_is_immutable_and_corruption_never_reinterprets_assets(ready):
    settings,job,directory,_,path,spec=ready
    order.review_image_order(settings,job["id"],path)
    assert order.review_image_order(settings,job["id"],path)["state"]=="image_order_already_applied"
    spec["order"]=[2,0,1];atomic_json(path,spec)
    with pytest.raises(ValueError,match="ALREADY_REVIEWED"):
        order.review_image_order(settings,job["id"],path)
    (directory/"images/provider.json").write_text('{"changed":true}')
    with pytest.raises(ValueError,match="BINDING_CHANGED"):
        order.ensure_image_order_ready(settings,job)
