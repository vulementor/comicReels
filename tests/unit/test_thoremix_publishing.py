"""Offline publication contracts using the real KRP SDK and SQLite journal."""
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture
def sdk(monkeypatch):
    # Development fallback only. Releases install KRP into their isolated runtime.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "kabin_reel_poster" / "src"))
    from kabin_reel_poster.sdk import KRPClient
    from kabin_reel_poster.core.models import AuthStatus, OperationResult
    return KRPClient, AuthStatus, OperationResult


@pytest.fixture
def package(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg required for real offline media validation")
    video = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=s=32x32:d=0.2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    manifest = {"schema_version": 1, "source_sha256": "a" * 64,
                "video_path": str(video), "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "title": "Thỏ Remix", "caption": "Một câu chuyện", "description": "Câu chuyện Thỏ",
                "affiliate": {"state": "verified", "url": "https://shopee.vn/product/123/456",
                              "disclosure": "Liên kết tiếp thị liên kết", "comment": "Sản phẩm trong video"},
                "qa": {"release_ready": True}}
    (tmp_path / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


class OfflineAdapter:
    def __init__(self, name, AuthStatus, OperationResult):
        self.name, self.AuthStatus, self.Result = name, AuthStatus, OperationResult
        self.uploads, self.comments, self.reconciles = [], [], []
        self.auth = "ok"
        self.publish_state = self.comment_state = "confirmed"
        self.reconcile_state = "confirmed"

    def auth_status(self, profile, actor):
        return self.AuthStatus(platform=self.name, state=self.auth)

    def publish(self, request, operation_id):
        self.uploads.append(request)
        if self.publish_state == "raise":
            raise RuntimeError("secret cookie=DO_NOT_LEAK")
        return self.Result(state=self.publish_state, permalink=f"https://www.{self.name}.com/video/123",
                           evidence={"cookies": "DO_NOT_LEAK"})

    def comment(self, request, operation_id):
        self.comments.append(request)
        return self.Result(state=self.comment_state, permalink=request.url + "?comment_id=456")

    def reconcile_publish(self, request, operation_id):
        self.reconciles.append(operation_id)
        return self.Result(state=self.reconcile_state, permalink=f"https://www.{self.name}.com/video/123")

    def reconcile_comment(self, request, operation_id):
        self.reconciles.append(operation_id)
        return self.Result(state=self.reconcile_state, permalink=request.url + "?comment_id=456")


@pytest.fixture
def rig(sdk, tmp_path):
    Client, Auth, Result = sdk
    adapters = {p: OfflineAdapter(p, Auth, Result) for p in ("facebook", "tiktok", "youtube")}
    seen = []

    def factory(**kwargs):
        seen.append(kwargs)
        return Client(**kwargs, adapters=adapters)

    module = importlib.import_module("agent.thoremix.publishing")
    return module, adapters, factory, tmp_path / "krp", seen


def run(package, rig):
    mod, _, factory, home, _ = rig
    return mod.publish_package(package, krp_home=home, client_factory=factory)


def test_duplicate_run_recovers_from_journal_without_second_effect(package, rig):
    first = run(package, rig)
    (package / "publication.json").unlink()  # crash/lost projection cannot repeat effects
    second = run(package, rig)
    assert first["complete"] and second["complete"]
    for adapter in rig[1].values():
        assert len(adapter.uploads) == len(adapter.comments) == 1
        assert "Liên kết tiếp thị liên kết" not in adapter.uploads[0].caption
        assert "Liên kết tiếp thị liên kết" not in adapter.comments[0].text
        assert "https://shopee.vn/product/123/456" in adapter.comments[0].text
    assert "DO_NOT_LEAK" not in (package / "publication.json").read_text()


def test_corrected_revision_dispatches_only_facebook_and_tiktok_once(package, rig):
    from unittest.mock import Mock
    manifest = json.loads((package / 'package.json').read_text())
    revision = manifest['video_sha256']
    manifest.update(publication_revision=revision, supersedes_package_sha256='b' * 64,
                    owner_correction='Use AI video on Facebook and TikTok; retain YouTube.',
                    publication_targets=['facebook', 'tiktok'])
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    youtube = rig[1]['youtube']
    youtube.auth_status = Mock(side_effect=AssertionError('YouTube is outside this revision'))
    first = run(package, rig)
    (package / 'publication.json').unlink()
    second = run(package, rig)
    assert first['complete'] and second['complete']
    assert list(second['platforms']) == ['facebook', 'tiktok']
    for platform, item in second['platforms'].items():
        assert len(rig[1][platform].uploads) == len(rig[1][platform].comments) == 1
        for action, receipt in (('publish', item['publication']), ('comment', item['comment'])):
            assert receipt['idempotency_key'] == f"thoremix:{manifest['source_sha256']}:revision:{revision}:{platform}:{action}"
    assert not youtube.uploads and not youtube.comments and not youtube.reconciles
    youtube.auth_status.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'publication_targets': []}, {'publication_targets': ['facebook', 'facebook']},
    {'publication_targets': ['unknown']}, {'publication_targets': 'facebook'},
    {'publication_revision': 'b' * 64, 'owner_correction': 'correct', 'supersedes_package_sha256': 'c' * 64},
])
def test_invalid_revision_scope_or_identity_rejected_before_effects(package, rig, changes):
    manifest = json.loads((package / 'package.json').read_text())
    manifest.update(changes)
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        run(package, rig)
    assert not rig[4]


def test_copy_revision_reuses_verified_edited_facebook_without_reposting(package, rig):
    original=run(package,rig)
    manifest=json.loads((package/'package.json').read_text())
    manifest.update(caption='Owner revised caption',publication_targets=['facebook','tiktok'],
        copy_correction='Remove the automatically inserted footer.',
        prior_copy_package_sha256=original['package_sha256'])
    manifest['affiliate']['comment']='Owner revised product\n'+manifest['affiliate']['url']
    fb=original['platforms']['facebook']
    manifest['retained_operations']={'facebook':{
        'publish':fb['publication']['operation_id'],'comment':fb['comment']['operation_id'],
        'verified_copy_edit':{'state':'verified','caption':manifest['caption'],
            'comment':manifest['affiliate']['comment'],'post_url':fb['permalink'],
            'comment_url':fb['comment']['permalink']}}}
    manifest['publication_copy_revision']=rig[0]._copy_digest(manifest)
    (package/'package.json').write_text(json.dumps(manifest),encoding='utf-8')
    (package/'publication.json').unlink()
    revised=run(package,rig)
    assert revised['complete'] and run(package,rig)['complete']
    assert len(rig[1]['facebook'].uploads)==len(rig[1]['facebook'].comments)==1
    assert len(rig[1]['tiktok'].uploads)==len(rig[1]['tiktok'].comments)==2
    assert len(rig[1]['youtube'].uploads)==len(rig[1]['youtube'].comments)==1
    assert rig[1]['tiktok'].uploads[-1].caption=='Owner revised caption'
    assert 'Liên kết tiếp thị liên kết' not in rig[1]['tiktok'].comments[-1].text
    assert revised['platforms']['facebook']['publication']['operation_id']==fb['publication']['operation_id']
    (package/'publication.json').unlink()
    journal=rig[4][-1]['journal']
    journal.mark(fb['comment']['operation_id'],state='unknown')
    with pytest.raises(ValueError,match='retained operation'):
        run(package,rig)
    assert len(rig[1]['tiktok'].uploads)==2


@pytest.mark.parametrize('audience', [True, False, None])
def test_youtube_audience_uses_only_explicit_frozen_metadata(package, rig, audience):
    manifest = json.loads((package / 'package.json').read_text())
    if audience is not None:
        manifest['youtube'] = {'made_for_kids': audience}
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert run(package, rig)['complete']
    assert rig[1]['youtube'].uploads[0].made_for_kids is audience
    assert rig[1]['facebook'].uploads[0].made_for_kids is None
    assert rig[1]['tiktok'].uploads[0].made_for_kids is None


@pytest.mark.parametrize('audience', ['false', 0, None])
def test_invalid_youtube_audience_blocks_before_all_effects(package, rig, audience):
    manifest = json.loads((package / 'package.json').read_text())
    manifest['youtube'] = {'made_for_kids': audience}
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='made_for_kids'):
        run(package, rig)
    assert not rig[4]


def test_complete_affiliate_comment_keeps_one_link_and_disclosure(package, rig):
    manifest = json.loads((package / 'package.json').read_text())
    affiliate = manifest['affiliate']
    affiliate['comment'] = '\n'.join((affiliate['comment'], affiliate['url'], affiliate['disclosure']))
    (package / 'package.json').write_text(json.dumps(manifest), encoding='utf-8')
    assert run(package, rig)['complete']
    for adapter in rig[1].values():
        comment = adapter.comments[0].text
        assert comment == affiliate['comment']
        assert comment.count(affiliate['url']) == comment.count(affiliate['disclosure']) == 1


def test_exception_after_intent_reconciles_same_operation(package, rig):
    fb = rig[1]["facebook"]
    fb.publish_state = "raise"
    first = run(package, rig)
    assert not first["complete"]
    assert first["platforms"]["youtube"]["status"] == "complete"
    assert "DO_NOT_LEAK" not in (package / "publication.json").read_text()
    second = run(package, rig)
    assert second["complete"]
    assert len(fb.uploads) == 1 and len(fb.reconciles) == 1


def test_changed_video_is_rejected_before_effects(package, rig):
    (package / "clip.mp4").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        run(package, rig)
    assert not rig[4]


def test_changed_frozen_payload_rejected_even_without_projection(package, rig):
    run(package, rig)
    (package / "publication.json").unlink()
    manifest = json.loads((package / "package.json").read_text())
    manifest["caption"] = "Changed after publication"
    (package / "package.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="frozen"):
        run(package, rig)
    assert all(len(a.uploads) == 1 for a in rig[1].values())


def test_login_failure_keeps_independent_channels_and_resumes(package, rig):
    rig[1]["tiktok"].auth = "needs_login"
    first = run(package, rig)
    assert first["platforms"]["tiktok"]["status"] == "needs_login"
    assert first["platforms"]["youtube"]["status"] == "complete"
    rig[1]["tiktok"].auth = "ok"
    assert run(package, rig)["complete"]
    assert all(len(a.uploads) == 1 for a in rig[1].values())


def test_comment_failure_never_repeats_upload(package, rig):
    rig[1]["facebook"].comment_state = "failed"
    first = run(package, rig)
    assert not first["complete"]
    second = run(package, rig)
    assert not second["complete"]
    assert len(rig[1]["facebook"].uploads) == len(rig[1]["facebook"].comments) == 1


@pytest.mark.parametrize("effect,state_field", [("publication", "publish_state"), ("comment", "comment_state")])
def test_needs_input_reconciles_original_operation_without_resubmission(package, rig, effect, state_field):
    fb = rig[1]["facebook"]
    setattr(fb, state_field, "needs_input")
    first = run(package, rig)
    original = first["platforms"]["facebook"][effect]
    assert original["state"] == "needs_input"
    original_id, original_key = original["operation_id"], original["idempotency_key"]
    assert original_id and not first["complete"]

    # A still-blocked read must retain the receipt and never retry either effect.
    fb.reconcile_state = "needs_input"
    pending = run(package, rig)
    assert pending["platforms"]["facebook"][effect]["state"] == "needs_input"
    assert pending["platforms"]["facebook"][effect]["operation_id"] == original_id
    assert not pending["complete"]
    assert fb.reconciles == [original_id]
    assert len(fb.uploads) == 1
    assert len(fb.comments) == (1 if effect == "comment" else 0)

    # After login/actor repair or a manually completed effect, reconcile confirms
    # the same record. A publication may now receive its first affiliate comment.
    fb.reconcile_state = "confirmed"
    repaired = run(package, rig)
    assert repaired["complete"]
    assert repaired["platforms"]["facebook"][effect]["operation_id"] == original_id
    assert repaired["platforms"]["facebook"][effect]["idempotency_key"] == original_key
    assert fb.reconciles == [original_id, original_id]
    assert all(len(adapter.uploads) == len(adapter.comments) == 1 for adapter in rig[1].values())
    journal = rig[4][-1]["journal"]
    assert journal.get_by_key(original_key).operation_id == original_id
    with journal.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM effects").fetchone()[0] == 6


@pytest.mark.parametrize("field,value", [("url", "javascript:alert(1)"), ("disclosure", ""), ("state", "pending")])
def test_invalid_affiliate_blocks_all_effects(package, rig, field, value):
    manifest = json.loads((package / "package.json").read_text())
    manifest["affiliate"][field] = value
    (package / "package.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="affiliate"):
        run(package, rig)
    assert not rig[4]


def test_explicit_actor_mapping_and_home_isolation(package, rig, monkeypatch):
    monkeypatch.setenv("KRP_HOME", "previous")
    run(package, rig)
    config = rig[4][0]["config"]
    assert config.actor("facebook", "thoremix").canonical_url == "https://www.facebook.com/ThoRemixOfficial"
    assert config.actor("facebook", "thoremix").display_name is None
    assert config.actor("tiktok", "thoremix").handle == "thoremixofficial"
    assert config.actor("youtube", "thoremix").handle == "ThoRemixOfficial"
    assert os.environ["KRP_HOME"] == "previous"
    assert all(a.uploads[0].profile == "thoremix-social" and a.uploads[0].actor == "thoremix" for a in rig[1].values())


def test_wrong_config_target_rejected_before_effects(package, rig):
    rig[3].mkdir()
    (rig[3] / "config.yaml").write_text("actors:\n  youtube:\n    thoremix:\n      handle: wrong-channel\n")
    with pytest.raises(ValueError, match="target"):
        run(package, rig)
    assert not rig[4]


def test_corrupt_media_with_matching_hash_still_blocks_effects(package, rig):
    video = package / "clip.mp4"
    video.write_bytes(b"not really a video")
    manifest = json.loads((package / "package.json").read_text())
    manifest["video_sha256"] = hashlib.sha256(video.read_bytes()).hexdigest()
    (package / "package.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="decode"):
        run(package, rig)
    assert not rig[4]


def test_auth_uses_explicit_targets_and_preserves_verified_name(rig, monkeypatch):
    from kabin_reel_poster.sdk import KRPClient
    from kabin_reel_poster.core.models import AuthStatus
    rig[3].mkdir()
    (rig[3] / "config.yaml").write_text("actors:\n  facebook:\n    thoremix:\n      display_name: Verified Page Name\n")
    seen = []

    def status(client, platform):
        seen.append((platform, client.actor, client.service.config.actor(platform, client.actor)))
        return AuthStatus(platform=platform, state="needs_login" if platform == "youtube" else "ok")

    monkeypatch.setattr(KRPClient, "auth_status", status)
    result = rig[0].auth_status(krp_home=rig[3])
    assert result["ready"] is False
    assert result["platforms"]["youtube"]["state"] == "needs_login"
    assert [row[0] for row in seen] == ["facebook", "tiktok", "youtube"]
    assert seen[0][2].display_name == "Verified Page Name"


def test_login_opens_only_three_sites_and_waits_for_user_close(rig, monkeypatch):
    from contextlib import contextmanager
    from kabin_reel_poster.platforms.facebook import FacebookAdapter
    navigated, waits, closed = [], [], []

    class Page:
        def goto(self, url, **kwargs):
            navigated.append(url)
            self.url = url + "?session=DO_NOT_LEAK#private"

        def wait_for_timeout(self, milliseconds):
            waits.append(milliseconds)
            receipt = json.loads((rig[3] / "login-window.json").read_text(encoding="utf-8"))
            assert receipt["state"] == "open"
            assert [tab["url"] for tab in receipt["tabs"]] == navigated
            assert "DO_NOT_LEAK" not in json.dumps(receipt)
            context.pages.clear()  # user closes the browser, no terminal input

    class Context:
        def __init__(self):
            self.pages = []

        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

    context = Context()

    @contextmanager
    def browser(adapter, profile, visible=False):
        assert profile == "thoremix-social" and visible is True
        yield context
        closed.append(True)

    monkeypatch.setattr(FacebookAdapter, "context", browser)
    rig[0].login(krp_home=rig[3])
    assert navigated == ["https://www.facebook.com/", "https://www.tiktok.com/tiktokstudio", "https://studio.youtube.com/"]
    assert waits and closed == [True]
    receipt = json.loads((rig[3] / "login-window.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "closed"
    assert "error_type" not in receipt


def test_login_navigation_error_keeps_window_until_close_and_projects_only_error_type(rig, monkeypatch):
    from contextlib import contextmanager
    from kabin_reel_poster.platforms.facebook import FacebookAdapter
    from playwright.sync_api import TimeoutError
    navigated = []

    class Page:
        url = "https://accounts.google.com/private/DO_NOT_LEAK?session=secret"

        def goto(self, url, **kwargs):
            navigated.append(url)
            if len(navigated) == 1:
                raise TimeoutError("private credential=DO_NOT_LEAK")
            self.url = url

        def wait_for_timeout(self, milliseconds):
            receipt = json.loads((rig[3] / "login-window.json").read_text(encoding="utf-8"))
            assert receipt["state"] == "navigation_failed"
            assert receipt["tabs"][0]["url"] is None
            assert receipt["error_type"] == "TimeoutError"
            assert len(navigated) == 3
            context.pages.clear()

    class Context:
        def __init__(self):
            self.pages = []

        def new_page(self):
            page = Page()
            self.pages.append(page)
            return page

    context = Context()

    @contextmanager
    def browser(adapter, profile, visible=False):
        yield context

    monkeypatch.setattr(FacebookAdapter, "context", browser)
    rig[0].login(krp_home=rig[3])
    receipt_text = (rig[3] / "login-window.json").read_text(encoding="utf-8")
    assert "DO_NOT_LEAK" not in receipt_text
    receipt = json.loads(receipt_text)
    assert receipt["state"] == "closed" and receipt["error_type"] == "TimeoutError"
