"""Thỏ Remix publication boundary over KRP's sole external-effect journal.

Call from the controller's single-runner child process. KRP_HOME is process-global;
these entry points must not be run concurrently in different threads.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit

from .media import media_tool


ACTOR = "thoremix"
TARGETS = {
    "facebook": {"canonical_url": "https://www.facebook.com/ThoRemixOfficial"},
    "tiktok": {"handle": "thoremixofficial", "canonical_url": "https://www.tiktok.com/@thoremixofficial"},
    "youtube": {"handle": "ThoRemixOfficial", "canonical_url": "https://www.youtube.com/@ThoRemixOfficial"},
}
LOGIN_URLS = (
    "https://www.facebook.com/",
    "https://www.tiktok.com/tiktokstudio",
    "https://studio.youtube.com/",
)


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _https_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return bool(url.scheme == "https" and url.hostname and "." in url.hostname
                    and not url.username and not url.password
                    and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


def _manifest(package_dir: Path) -> tuple[dict, str]:
    if (package_dir/'edits/pending.json').exists():
        raise ValueError('Video đang được xử lý; cần hoàn tất hồ sơ trước khi đăng.')
    data = json.loads((package_dir / "package.json").read_text(encoding="utf-8"))
    from .quality import package_state
    if package_state(data)!='video_ready':
        raise ValueError('Clip đang chờ chủ kênh duyệt cảnh báo chất lượng.')
    if data.get("schema_version") != 1 or data.get("qa", {}).get("release_ready") is not True:
        raise ValueError("package schema/QA is not release ready")
    for field in ("source_sha256", "video_sha256"):
        if not isinstance(data.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", data[field]):
            raise ValueError(f"invalid {field} hash")
    if 'publication_revision' in data:
        if data['publication_revision'] != data['video_sha256']:
            raise ValueError('publication revision must bind the exact corrected video hash')
        _text(data.get('owner_correction'), 'owner correction')
        if not re.fullmatch(r'[0-9a-f]{64}', str(data.get('supersedes_package_sha256', ''))):
            raise ValueError('corrected package must identify its preserved predecessor')
    if 'publication_copy_revision' in data:
        if data['publication_copy_revision'] != _copy_digest(data):
            raise ValueError('copy revision must bind the exact public text')
        _text(data.get('copy_correction'), 'owner copy correction')
        if not re.fullmatch(r'[0-9a-f]{64}', str(data.get('prior_copy_package_sha256', ''))):
            raise ValueError('copy correction must identify the preserved prior manifest')
    elif data.get('retained_operations'):
        raise ValueError('retained operations require an explicit copy revision')
    selected = data.get('publication_targets', list(TARGETS))
    if (not isinstance(selected, list) or not selected or any(p not in TARGETS for p in selected)
            or len(set(selected)) != len(selected)):
        raise ValueError('publication targets must be a nonempty unique subset of authorized channels')
    for field in ("title", "caption", "description"):
        _text(data.get(field), field)
    youtube = data.get('youtube', {})
    if not isinstance(youtube, dict) or ('made_for_kids' in youtube and type(youtube['made_for_kids']) is not bool):
        raise ValueError('youtube.made_for_kids must be an explicit boolean when supplied')
    tiktok = data.get('tiktok', {})
    if not isinstance(tiktok, dict) or ('resume_matching_unsaved' in tiktok and type(tiktok['resume_matching_unsaved']) is not bool):
        raise ValueError('tiktok.resume_matching_unsaved must be an explicit boolean')
    video = Path(_text(data.get("video_path"), "video_path"))
    if not video.is_absolute() or not video.is_file():
        raise ValueError("video_path must be an existing absolute file")
    if _digest_file(video) != data["video_sha256"]:
        raise ValueError("video hash does not match frozen package")
    affiliate = data.get("affiliate")
    if not isinstance(affiliate, dict) or affiliate.get("state") != "verified":
        raise ValueError("affiliate must be verified")
    if not _https_url(_text(affiliate.get("url"), "affiliate URL")):
        raise ValueError("affiliate URL must be an absolute credential-free HTTPS URL")
    _text(affiliate.get("disclosure"), "affiliate disclosure")
    _text(affiliate.get("comment"), "affiliate comment")
    if "targets" in data and data["targets"] != TARGETS:
        raise ValueError("package target bindings do not match authorized channels")
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    return data, digest


def _copy_digest(data: dict) -> str:
    public = {name: data.get(name) for name in ('title', 'caption', 'description')}
    public['comment'] = data.get('affiliate', {}).get('comment')
    return hashlib.sha256(json.dumps(public, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _validate_media(video: Path, *, tool_root: Path | None = None) -> None:
    executable = media_tool('ffmpeg', tool_root)
    result = subprocess.run(
        [executable, "-nostdin", "-v", "error", "-xerror", "-i", str(video),
         "-map", "0:v:0", "-map", "0:a?", "-f", "null", "-"],
        capture_output=True, timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError("video failed full media decode validation")


@contextmanager
def _home(krp_home: Path, profile: str):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", profile):
        raise ValueError("invalid isolated social profile name")
    home = Path(krp_home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    previous = os.environ.get("KRP_HOME")
    os.environ["KRP_HOME"] = str(home)
    try:
        yield home
    finally:
        if previous is None:
            os.environ.pop("KRP_HOME", None)
        else:
            os.environ["KRP_HOME"] = previous


def _config(home: Path, profile: str, visible: bool):
    from kabin_reel_poster.runtime.config import ActorConfig, AppConfig

    config = AppConfig.load(home / "config.yaml")
    config.default_profile = profile
    config.browser.headless = not visible
    config.repair.enabled = False  # No implicit ChatGPT dependency or profile sharing.
    for platform, binding in TARGETS.items():
        configured = config.actor(platform, ACTOR)
        for field, expected in binding.items():
            actual = getattr(configured, field)
            if actual and actual != expected:
                raise ValueError(f"{platform} target binding conflicts with authorized channel")
        # Facebook's current SDK requires a verified display name: preserve an
        # explicit setting, never manufacture one from the vanity URL.
        actor = ActorConfig(**binding, display_name=configured.display_name)
        config.actors.setdefault(platform, {})[ACTOR] = actor
    return config


def _client(home: Path, profile: str, visible: bool, factory=None):
    from kabin_reel_poster.sdk import KRPClient
    from kabin_reel_poster.storage.sqlite import EffectJournal

    config = _config(home, profile, visible)
    journal = EffectJournal(home / "state.sqlite3")
    client = (factory or KRPClient)(profile=profile, actor=ACTOR, config=config, journal=journal)
    if not callable(getattr(client, "recover_pre_submit", None)):
        raise RuntimeError("KRP runtime is too old: durable pre-submit recovery is required")
    return client, journal


def _write_projection(path: Path, projection: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=".publication-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(projection, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _safe_permalink(value, platform: str) -> str | None:
    if not isinstance(value, str) or not _https_url(value):
        return None
    parsed = urlsplit(value)
    if parsed.hostname not in {f"www.{platform}.com", f"{platform}.com", "youtu.be" if platform == "youtube" else ""}:
        return None
    # Allow only public reference query fields; never project session query data.
    from urllib.parse import parse_qsl, urlencode
    query = urlencode([(key, val) for key, val in parse_qsl(parsed.query)
                       if key in {"v", "comment_id", "reply_comment_id", "lc"}])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _receipt(record, platform: str, key: str) -> dict:
    state = getattr(record, "state", "unknown")
    reason = None if state == "confirmed" else f"KRP effect is {state}; inspect its journal receipt"
    if state == "needs_input":
        reason = "Repair the login/actor checkpoint, then rerun to reconcile this same effect without resubmitting"
    return {"state": state, "operation_id": getattr(record, "operation_id", None),
            "idempotency_key": key,
            "permalink": _safe_permalink(getattr(record, "permalink", None), platform),
            "reason": reason}


def _effect(client, journal, *, key: str, platform: str, action: str, kwargs: dict) -> dict:
    record = journal.get_by_key(key)
    try:
        if record:
            record = client.inspect(record.operation_id)
            if record.state == "needs_input":
                # First reconcile read-only: a manually repaired/completed effect must
                # win over any retry. Only durable KRP pre-submit proof may re-enable
                # the same idempotent request, and at most once per invocation.
                client.reconcile(record.operation_id)
                record = client.inspect(record.operation_id)
                if record.state == "needs_input":
                    recover = getattr(client, "recover_pre_submit", None)
                    if recover is not None:
                        recover(record.operation_id)
                        getattr(client, action)(
                            platform=platform,
                            idempotency_key=key,
                            **kwargs,
                        )
            elif record.state not in {"confirmed", "failed"}:
                client.reconcile(record.operation_id)
        else:
            getattr(client, action)(platform=platform, idempotency_key=key, **kwargs)
    except Exception:
        # Raw browser exceptions may contain cookies or session-bearing URLs.
        # Read the committed journal state, never infer failure before submit.
        pass
    record = journal.get_by_key(key)
    if record is None:
        return {"state": "needs_input", "idempotency_key": key, "operation_id": None,
                "permalink": None, "reason": "KRP did not persist an effect; inspect runtime diagnostics"}
    return _receipt(record, platform, key)


def _auth(client, platform: str) -> dict:
    try:
        status = client.auth_status(platform)
        state = status.state
    except Exception:
        state = "unknown"
    return {"state": state, "target": dict(TARGETS[platform]),
            "reason": None if state == "ok" else
            "KRP requires verified login and actor configuration for this target"}


def publish_package(package_dir: Path, *, krp_home: Path, profile: str = "thoremix-social",
                    visible: bool = False, client_factory=None, tool_root: Path | None = None,
                    only_platforms: list[str] | tuple[str, ...] | None = None,
                    stop_after_publication: bool = False) -> dict:
    """Publish each destination independently and project only journal-confirmed effects."""
    package_dir = Path(package_dir).resolve()
    manifest, digest = _manifest(package_dir)
    receipt_path = package_dir / "publication.json"
    prior = None
    if receipt_path.exists():
        prior = json.loads(receipt_path.read_text(encoding="utf-8"))
        if prior.get("package_sha256") != digest:
            raise ValueError("frozen package changed after publication intent")
    _validate_media(Path(manifest["video_path"]), tool_root=tool_root)
    projection = (json.loads(json.dumps(prior, ensure_ascii=False)) if isinstance(prior, dict) else
                  {"schema_version": 1, "package_sha256": digest,
                   "source_sha256": manifest["source_sha256"], "complete": False, "platforms": {}})
    projection["complete"] = False
    projection.setdefault("platforms", {})
    affiliate = manifest["affiliate"]
    active_platforms = manifest.get('publication_targets', list(TARGETS))
    if only_platforms is None:
        selected_platforms = list(active_platforms)
    else:
        if (not isinstance(only_platforms, (list, tuple)) or not only_platforms
                or len(set(only_platforms)) != len(only_platforms)
                or any(p not in active_platforms for p in only_platforms)):
            raise ValueError('single-platform publish scope must be a nonempty unique subset of package targets')
        selected_platforms = list(only_platforms)
    if stop_after_publication and len(selected_platforms) != 1:
        raise ValueError('stop-after-publication requires exactly one selected platform')
    for platform in active_platforms:
        projection["platforms"].setdefault(
            platform, {"status": "pending", "target": dict(TARGETS[platform])})
    caption = manifest["caption"]
    description = manifest["description"]
    comment_lines = affiliate['comment'].strip().splitlines()
    for required_line in (affiliate['url'],):
        if required_line not in [line.strip() for line in comment_lines]:
            comment_lines.append(required_line)
    comment = '\n'.join(comment_lines)
    with _home(krp_home, profile) as home:
        client, journal = _client(home, profile, visible, client_factory)
        identity = f"thoremix:{manifest['source_sha256']}"
        if manifest.get('publication_revision'):
            identity += f":revision:{manifest['publication_revision']}"
        if manifest.get('publication_copy_revision'):
            identity += f":copy:{manifest['publication_copy_revision']}"
        keys = {p: {a: f"{identity}:{p}:{a}" for a in ("publish", "comment")}
                for p in active_platforms}
        retained = manifest.get('retained_operations', {})
        if not isinstance(retained, dict) or any(p not in active_platforms for p in retained):
            raise ValueError('retained publication scope is invalid')
        for platform, entry in retained.items():
            if not isinstance(entry, dict):
                raise ValueError('retained publication binding is invalid')
            edit = entry.get('verified_copy_edit', {})
            if (edit.get('state') != 'verified' or edit.get('caption') != caption
                    or edit.get('comment') != comment):
                raise ValueError('retained publication requires verified edited text')
            for action, krp_action in (('publish', 'publish_reel'), ('comment', 'create_comment')):
                record = journal.get(entry.get(action, ''))
                expected_url = edit.get('post_url' if action == 'publish' else 'comment_url')
                if (not record or record.state != 'confirmed' or record.action != krp_action
                        or record.platform != platform or record.actor != ACTOR or record.profile != profile
                        or record.payload.get('extra', {}).get('package_sha256') != manifest['prior_copy_package_sha256']
                        or _safe_permalink(record.permalink, platform) != expected_url
                        or (action == 'publish' and record.asset_sha256 != manifest['video_sha256'])
                        or (action == 'comment' and record.payload.get('url') != edit.get('post_url'))):
                    raise ValueError('retained operation is not the confirmed same-media publication')
                keys[platform][action] = record.idempotency_key
        # Validate all persisted bindings before any new destination can act.
        for platform in active_platforms:
            for action, key in keys[platform].items():
                existing = journal.get_by_key(key)
                expected_digest = manifest['prior_copy_package_sha256'] if platform in retained else digest
                if existing and (existing.payload.get("extra", {}).get("package_sha256") != expected_digest
                                 or existing.actor != ACTOR or existing.profile != profile):
                    raise ValueError("frozen package or social profile conflicts with existing journal effect")
        _write_projection(receipt_path, projection)
        for platform in selected_platforms:
            item = projection["platforms"][platform] = {"status": "pending", "target": dict(TARGETS[platform])}
            publish_key = keys[platform]["publish"]
            # Confirmed and uncertain journal entries take precedence over login
            # preflight; this also repairs interrupted local projection writes.
            if journal.get_by_key(publish_key) is None:
                auth = _auth(client, platform)
                item["auth"] = auth
                if auth["state"] != "ok":
                    item["status"] = auth["state"]
                    _write_projection(receipt_path, projection)
                    continue
            item["publication"] = _effect(client, journal, key=publish_key, platform=platform, action="publish",
                kwargs={"video": Path(manifest["video_path"]), "caption": caption, "title": manifest["title"],
                        "description": description, "visibility": "public", "allow_comments": True,
                        "made_for_kids": manifest.get('youtube', {}).get('made_for_kids') if platform == 'youtube' else None,
                        "extra": {"package_sha256": digest, **(
                            {"resume_matching_unsaved": True} if platform == 'tiktok'
                            and manifest.get('tiktok', {}).get('resume_matching_unsaved') is True else {})}})
            published = item["publication"]
            item["status"] = published["state"]
            item["permalink"] = published["permalink"]
            _write_projection(receipt_path, projection)
            if published["state"] != "confirmed" or not published["permalink"]:
                if published["state"] == "confirmed":
                    item["status"] = "needs_input"
                continue
            if stop_after_publication:
                item["status"] = "confirmed"
                _write_projection(receipt_path, projection)
                continue
            comment_key = keys[platform]["comment"]
            if journal.get_by_key(comment_key) is None:
                auth = _auth(client, platform)
                if auth["state"] != "ok":
                    item["status"], item["auth"] = auth["state"], auth
                    _write_projection(receipt_path, projection)
                    continue
            item["comment"] = _effect(client, journal, key=comment_key, platform=platform, action="comment",
                kwargs={"url": published["permalink"], "text": comment, "extra": {"package_sha256": digest}})
            item["status"] = "complete" if item["comment"]["state"] == "confirmed" else item["comment"]["state"]
            _write_projection(receipt_path, projection)
        projection["complete"] = all(
            projection["platforms"].get(platform, {}).get("status") == "complete"
            for platform in active_platforms
        )
        _write_projection(receipt_path, projection)
    return projection


def auth_status(*, krp_home: Path, profile: str = "thoremix-social") -> dict:
    with _home(krp_home, profile) as home:
        client, _ = _client(home, profile, False)
        platforms = {platform: _auth(client, platform) for platform in TARGETS}
        return {"profile": profile, "platforms": platforms, "observed_at": datetime.now(timezone.utc).isoformat(),
                "ready": all(item["state"] == "ok" for item in platforms.values())}


def login(*, krp_home: Path, profile: str = "thoremix-social") -> None:
    """Keep KRP's leased native context alive until the user closes its browser."""
    from kabin_reel_poster.platforms.facebook import FacebookAdapter
    from playwright.sync_api import Error

    with _home(krp_home, profile) as home:
        adapter = FacebookAdapter(_config(home, profile, True))
        receipt_path = home / "login-window.json"
        receipt = {"state": "opening", "tabs": []}
        _write_projection(receipt_path, receipt)
        try:
            with adapter.context(profile, visible=True) as context:
                for url in LOGIN_URLS:
                    page = context.new_page()
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    except Error as exc:
                        # A failed navigation must not dispose the user's login
                        # window; let them complete it manually and close it.
                        receipt.setdefault("error_type", type(exc).__name__)
                    try:
                        observed = urlsplit(page.url)
                        sanitized = urlunsplit((observed.scheme, observed.netloc, observed.path, "", ""))
                    except (ValueError, Error):
                        sanitized = None
                    receipt["tabs"].append({"requested_url": url,
                        "url": sanitized if sanitized in LOGIN_URLS else None})
                receipt["state"] = "navigation_failed" if "error_type" in receipt else "open"
                _write_projection(receipt_path, receipt)
                while context.pages:
                    page = context.pages[0]
                    try:
                        page.wait_for_timeout(250)
                    except Error:
                        if page in context.pages:
                            raise
        finally:
            receipt["state"] = "closed"
            _write_projection(receipt_path, receipt)
