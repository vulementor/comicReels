"""Non-paid/read batch response contracts that remain after browser-only cutover.

Paid image/edit submission moved to the dedicated one-shot/idempotency suites.
This file keeps valid response/payload contracts for the remaining batch/read
paths without reintroducing multi-wave paid retry or RAM poll-cache behavior.
"""
import json

import pytest

from agent.services import flow_batch as fb
from agent.services.flow_client import FlowClient
from agent.worker._parsing import _extract_media_id, _extract_output_url, _is_error

PROJECT = "11111111-2222-3333-4444-555555555555"
MEDIA = "12345678-1234-1234-1234-1234567890ab"
OPERATION = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
IMAGE_URL = f"https://{fb.MEDIA_HOST}/image/{MEDIA}?sig=x"
VIDEO_URL = f"https://{fb.MEDIA_HOST}/video/{MEDIA}?sig=x"


def envelope(rpcid: str, payload) -> str:
    chunk = json.dumps([["wrb.fr", rpcid, json.dumps(payload)]])
    return f")]}}'\n{len(chunk)}\n{chunk}"


class BatchBackendStub:
    kind = "browser"
    ready = True
    paid_dispatch_enabled = False
    session_owner_key = "browser:test-owner"

    def __init__(self):
        self.bindings = {OPERATION: PROJECT}

    async def bind_operation(self, operation_id, project_id):
        existing = self.bindings.get(operation_id)
        if existing and existing != project_id:
            return {
                "status": 409,
                "error": "OPERATION_BINDING_CONFLICT",
                "effect": "not_submitted",
            }
        self.bindings[operation_id] = project_id
        return {
            "status": 200,
            "data": {"operationId": operation_id, "projectId": project_id},
            "effect": "completed",
        }

    async def operation_project(self, operation_id):
        project_id = self.bindings.get(operation_id)
        if not project_id:
            return {
                "status": 409,
                "error": "OPERATION_BINDING_REQUIRED",
                "effect": "not_submitted",
            }
        return {
            "status": 200,
            "data": {"operationId": operation_id, "projectId": project_id},
            "effect": "completed",
        }

    async def execute(self, method, params, timeout=300):
        raise AssertionError("batch_rpc is replaced by the fixture")

    async def submit_paid_image(self, *args, **kwargs):
        raise AssertionError("paid image path belongs to dedicated one-shot tests")

    async def start(self):
        pass

    async def close(self):
        pass

    async def check_readiness(self):
        return {"ready": True}

    async def open_project(self, project_id):
        return {"status": 200, "data": {"projectId": project_id}}

    async def ensure_session_project(self, *, title=None, force_new=False):
        return {"status": 200}


@pytest.fixture
def client(monkeypatch):
    """A FlowClient whose transport replays canned RPC responses.

    `calls` records what each rpc was asked, so a test can assert on the
    envelope as well as on what came back.
    """
    import agent.services.flow_client as module
    monkeypatch.setattr(module, "FLOW_PROJECT_ID", PROJECT)
    monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", False)

    c = FlowClient(backend=BatchBackendStub())
    c.responses = {}
    c.calls = []

    async def fake_batch_rpc(
        rpcid, freq, captcha_action=None, match=None, timeout=300, project_id=None
    ):
        c.calls.append({"rpcid": rpcid, "freq": freq,
                        "captcha": captcha_action, "match": match,
                        "project_id": project_id})
        canned = c.responses.get(rpcid, {"data": ""})
        return canned(match) if callable(canned) else canned

    c.batch_rpc = fake_batch_rpc
    return c


class TestUpscaleImage:
    async def test_2k_upscale_uses_sprcad_and_returns_encoded_image(self, client):
        encoded = "A" * 200
        client.responses[fb.RPC_UPSCALE_IMAGE] = {
            "data": envelope(fb.RPC_UPSCALE_IMAGE, [["media-record"], encoded])
        }
        result = await client.upscale_image(MEDIA, PROJECT, "2K")
        assert result["data"]["encodedImage"] == encoded
        assert result["data"]["resolution"] == "2K"
        assert client.calls[0]["rpcid"] == fb.RPC_UPSCALE_IMAGE
        assert client.calls[0]["captcha"] == fb.CAPTCHA_IMAGE
        payload = json.loads(json.loads(client.calls[0]["freq"])[0][0][1])
        assert payload[0] == MEDIA
        assert payload[1] == 1


class TestGenerateVideo:
    def _submitted(self, client):
        return {"data": envelope(fb.RPC_GEN_VIDEO, [None, 50, [[OPERATION, PROJECT, "scene", None]]])}

    async def test_returns_an_operation_the_poller_can_carry(self, client):
        client.responses[fb.RPC_GEN_VIDEO] = self._submitted(client)
        result = await client.generate_video("mid", "go", PROJECT, "scene-1")

        ops = result["data"]["operations"]
        assert ops[0]["operation"]["name"] == OPERATION
        assert ops[0]["status"] == "MEDIA_GENERATION_STATUS_PENDING"

    async def test_persists_operation_project_binding_through_backend(self, client):
        client.responses[fb.RPC_GEN_VIDEO] = self._submitted(client)
        await client.generate_video("mid", "go", PROJECT, "scene-1")
        assert client.backend.bindings[OPERATION] == PROJECT
        assert not hasattr(client, "_operation_projects")

    async def test_chaining_fails_loudly_rather_than_dropping_the_end_frame(self, client):
        result = await client.generate_video("mid", "go", PROJECT, "scene-1",
                                             end_image_media_id="end-mid")
        assert "UNSUPPORTED_ON_BATCH_API" in result["error"]
        assert not client.calls, "nothing should have been sent"

    async def test_degraded_mode_runs_i2v_off_the_start_frame(self, client, monkeypatch):
        import agent.services.flow_client as module
        monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", True)
        client.responses[fb.RPC_GEN_VIDEO] = self._submitted(client)

        result = await client.generate_video("start-mid", "go", PROJECT, "scene-1",
                                             end_image_media_id="end-mid")
        assert not _is_error(result)
        payload = json.loads(json.loads(client.calls[0]["freq"])[0][0][1])
        assert payload[0][0][4][1] == "start-mid"

    async def test_r2v_fails_loudly_by_default(self, client):
        result = await client.generate_video_from_references(["a", "b"], "go", PROJECT, "s")
        assert "UNSUPPORTED_ON_BATCH_API" in result["error"]

    async def test_degraded_r2v_uses_the_first_reference_as_the_start_frame(self, client, monkeypatch):
        import agent.services.flow_client as module
        monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", True)
        client.responses[fb.RPC_GEN_VIDEO] = self._submitted(client)

        await client.generate_video_from_references(["ref-a", "ref-b"], "go", PROJECT, "s")
        payload = json.loads(json.loads(client.calls[0]["freq"])[0][0][1])
        assert payload[0][0][4][1] == "ref-a"

    async def test_upscale_is_unported_and_has_no_fallback(self, client, monkeypatch):
        import agent.services.flow_client as module
        monkeypatch.setattr(module, "FLOW_ALLOW_DEGRADED", True)
        result = await client.upscale_video(MEDIA, "scene-1")
        assert "UNSUPPORTED_ON_BATCH_API" in result["error"]


class TestCheckVideoStatus:
    def _poll(self, status=None, complaint=None, outcome=None):
        detail = [None] * 8 + [[outcome]] if outcome is not None else None
        if complaint:
            detail = [None] * 8 + [[fb.OUTCOME_COMPLAINT, [None, complaint]]]
        record = [OPERATION, PROJECT, "scene", status, None, detail]
        return {"data": envelope(fb.RPC_OPERATION, [None, 50, [record]])}

    def _listing(self, found=True):
        text = (f'["{OPERATION}",null,null,["t",1,2,null,null,"{MEDIA}"]' if found else "")
        return lambda match: {"data": text}

    async def _status(self, client):
        result = await client.check_video_status([{"operation": {"name": OPERATION}}])
        return result["data"]["operations"][0]

    async def test_successful_once_a_video_url_exists(self, client):
        client.responses[fb.RPC_OPERATION] = self._poll(status="CAE", outcome=fb.OUTCOME_OK)
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing()
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL])}

        op = await self._status(client)
        assert op["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        assert _extract_media_id({"data": {"operations": [op]}}, "GENERATE_VIDEO") == MEDIA
        assert _extract_output_url({"data": {"operations": [op]}}, "GENERATE_VIDEO") == VIDEO_URL

    async def test_a_media_id_with_only_a_poster_is_still_pending(self, client):
        """Downloading on the id alone would save a still picture."""
        client.responses[fb.RPC_OPERATION] = self._poll(status="CAE", outcome=fb.OUTCOME_OK)
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing()
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [IMAGE_URL])}

        assert (await self._status(client))["status"] == "MEDIA_GENERATION_STATUS_PENDING"

    async def test_a_complaint_is_carried_but_does_not_fail_the_job(self, client):
        """Jobs report "Media not found." and still deliver a finished clip."""
        client.responses[fb.RPC_OPERATION] = self._poll(complaint="Media not found.")
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing(found=False)

        op = await self._status(client)
        assert op["status"] == "MEDIA_GENERATION_STATUS_PENDING"
        assert op["complaint"] == "Media not found."

    async def test_the_listing_decides_on_the_first_poll_even_when_poll_never_says_done(self, client):
        """Durable project listing is authoritative on every poll round."""
        client.responses[fb.RPC_OPERATION] = self._poll(status=None)
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing()
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL])}

        assert (await self._status(client))["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"

    async def test_the_listing_is_asked_for_a_window_not_the_whole_thing(self, client):
        client.responses[fb.RPC_OPERATION] = self._poll(status="CAE", outcome=fb.OUTCOME_OK)
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing(found=False)

        await self._status(client)
        listing = next(c for c in client.calls if c["rpcid"] == fb.RPC_PROJECT_MEDIA)
        assert listing["match"] == OPERATION

    async def test_an_unreadable_poll_still_consults_the_listing(self, client):
        """Old operations decay to a bare id but stay in the listing."""
        client.responses[fb.RPC_OPERATION] = {"error": "boom"}
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing()
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL])}

        assert (await self._status(client))["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"

    async def test_a_finished_operation_stays_finished_when_re_polled(self, client):
        """A batch re-polls its finished operations alongside its pending ones."""
        client.responses[fb.RPC_OPERATION] = self._poll(status="CAE", outcome=fb.OUTCOME_OK)
        client.responses[fb.RPC_PROJECT_MEDIA] = self._listing()
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL])}

        assert (await self._status(client))["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"
        assert (await self._status(client))["status"] == "MEDIA_GENERATION_STATUS_SUCCESSFUL"

    async def test_a_nameless_operation_fails_instead_of_polling_forever(self, client):
        result = await client.check_video_status([{"operation": {}}])
        assert result["data"]["operations"][0]["status"] == "MEDIA_GENERATION_STATUS_FAILED"


class TestMediaAndUpload:
    async def test_get_media_reports_the_signed_urls(self, client):
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL, IMAGE_URL])}
        result = await client.get_media(MEDIA)
        assert result["status"] == 200
        assert result["data"]["video"]["fifeUrl"] == VIDEO_URL

    async def test_a_media_id_with_no_urls_reads_as_404(self, client):
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [])}
        assert (await client.get_media(MEDIA))["status"] == 404

    async def test_validate_media_id_follows_the_status(self, client):
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL])}
        assert await client.validate_media_id(MEDIA) is True
        client.responses[fb.RPC_MEDIA] = {"data": envelope(fb.RPC_MEDIA, [])}
        assert await client.validate_media_id(MEDIA) is False

    async def test_upload_returns_the_media_id_the_callers_look_for(self, client):
        client.responses[fb.RPC_UPLOAD_IMAGE] = {
            "data": envelope(fb.RPC_UPLOAD_IMAGE, [[MEDIA, PROJECT, OPERATION, "CAE"]])
        }
        result = await client.upload_image("Ym9keQ==", project_id=PROJECT)
        assert result["_mediaId"] == MEDIA
        assert result["data"]["media"]["name"] == MEDIA

    async def test_upload_carries_a_captcha_like_a_generate(self, client):
        client.responses[fb.RPC_UPLOAD_IMAGE] = {
            "data": envelope(fb.RPC_UPLOAD_IMAGE, [[MEDIA, PROJECT, OPERATION, "CAE"]])
        }
        await client.upload_image("Ym9keQ==", project_id=PROJECT)
        assert client.calls[0]["captcha"] == fb.CAPTCHA_IMAGE


class TestProjectAndCredits:
    async def test_create_project_uses_current_batch_rpc(self, client):
        client.responses[fb.RPC_CREATE_PROJECT] = {
            "data": envelope(fb.RPC_CREATE_PROJECT, [PROJECT, ["My Film"]])
        }
        result = await client.create_project("My Film")
        assert result["data"]["projectId"] == PROJECT
        assert result["data"]["title"] == "My Film"
        assert client.calls[0]["rpcid"] == fb.RPC_CREATE_PROJECT
        outer = json.loads(client.calls[0]["freq"])
        inner = json.loads(outer[0][0][1])
        assert inner == ["projects/*", [None, ["My Film"]], [None, fb.SURFACE_ID]]

    async def test_flow_project_id_only_accepts_explicit_ids(self, client):
        assert client.flow_project_id(PROJECT) == PROJECT
        assert client.flow_project_id("") is None
        assert client.flow_project_id("not-a-project") is None

    async def test_credits_answers_the_configured_tier_rather_than_guessing(self, client):
        result = await client.get_credits()
        assert result["data"]["userPaygateTier"]
        assert not client.calls, "there is no credits rpc to call"


class TestRefreshProjectUrls:
    """Re-signing every stored media id — what `/fk-refresh-urls` runs."""

    @pytest.fixture
    def db(self, monkeypatch):
        """A stand-in for the crud layer, recording what got written."""
        from agent.db import crud

        state = {
            "videos": [{"id": "vid-1"}],
            "scenes": [{
                "id": "scene-1",
                "vertical_image_media_id": MEDIA,
                "vertical_video_media_id": "22222222-2222-2222-2222-222222222222",
                "horizontal_image_media_id": "CAMSnot-a-uuid",
            }],
            "characters": [{"id": "char-1", "media_id": "33333333-3333-3333-3333-333333333333"}],
            "writes": [],
        }

        async def list_videos(pid): return state["videos"]
        async def list_scenes(vid): return state["scenes"]
        async def get_project_characters(pid): return state["characters"]
        async def update_scene(sid, **kw): state["writes"].append(("scene", sid, kw))
        async def update_character(cid, **kw): state["writes"].append(("character", cid, kw))

        for name, fn in [("list_videos", list_videos), ("list_scenes", list_scenes),
                         ("get_project_characters", get_project_characters),
                         ("update_scene", update_scene), ("update_character", update_character)]:
            monkeypatch.setattr(crud, name, fn)
        return state

    async def test_writes_a_fresh_url_into_each_field_that_holds_the_id(self, client, db):
        def media(match):
            return {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL, IMAGE_URL])}
        client.responses[fb.RPC_MEDIA] = media

        result = await client.refresh_project_urls(PROJECT)

        assert result["found"] == 3, "the CAMS id is not a media id and is skipped"
        assert result["refreshed"] == 3
        written = {(table, tuple(kw)[0]) for table, _, kw in db["writes"]}
        assert written == {
            ("scene", "vertical_image_url"),
            ("scene", "vertical_video_url"),
            ("character", "reference_image_url"),
        }

    async def test_an_image_field_takes_the_image_url_not_the_video_one(self, client, db):
        client.responses[fb.RPC_MEDIA] = lambda m: {
            "data": envelope(fb.RPC_MEDIA, [VIDEO_URL, IMAGE_URL])}

        await client.refresh_project_urls(PROJECT)
        by_field = {tuple(kw)[0]: tuple(kw.values())[0] for _, _, kw in db["writes"]}
        assert by_field["vertical_image_url"] == IMAGE_URL
        assert by_field["vertical_video_url"] == VIDEO_URL

    async def test_one_dead_media_id_does_not_sink_the_rest(self, client, db):
        seen = []

        def media(match):
            seen.append(1)
            if len(seen) == 1:
                return {"error": "NOT_FOUND"}
            return {"data": envelope(fb.RPC_MEDIA, [VIDEO_URL, IMAGE_URL])}
        client.responses[fb.RPC_MEDIA] = media

        result = await client.refresh_project_urls(PROJECT)
        assert result["found"] == 3 and result["refreshed"] == 2
