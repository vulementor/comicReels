"""Consequential desktop state interpretation and passive rendering boundaries."""
import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from agent.thoremix.config import Settings
from agent.thoremix.dashboard import (build_snapshot, publication_view, safe_link,
                                      selected_key, PLATFORMS, state_text)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def receipt(state='confirmed'):
    return {'complete': True, 'platforms': {p: {'status': 'complete',
        'publication': {'state': state, 'permalink': f'https://www.{p}.com/video/123'},
        'comment': {'state': state, 'permalink': f'https://www.{p}.com/video/123?comment_id=42'}} for p in PLATFORMS}}


@pytest.mark.parametrize('state', ['submitted_unverified', 'unknown', 'unknown_after_submit', 'submitted_processing'])
def test_uncertain_effect_never_becomes_published(state):
    result = publication_view(receipt(state))
    assert not result['complete']
    assert result['confirmed'] == 0
    assert result['links'] == []
    assert all(v['publication'] == 'Chờ xác minh' for v in result['channels'].values())


def test_completion_requires_six_individual_confirmations():
    raw = receipt()
    assert publication_view(raw)['complete']
    raw['platforms']['facebook']['comment']['state'] = 'needs_input'
    result = publication_view(raw)
    assert not result['complete'] and result['confirmed'] == 5
    assert result['channels']['facebook'] == {'publication': 'Đã xác nhận', 'comment': 'Cần xử lý'}
    assert len(result['links']) == 5
    del raw['platforms']['youtube']
    assert publication_view(raw)['confirmed'] == 3


def test_platform_complete_flag_without_effects_is_not_evidence():
    result = publication_view({'complete': True, 'platforms': {p: {'status': 'complete'} for p in PLATFORMS}})
    assert result['confirmed'] == 0 and not result['complete']


@pytest.mark.parametrize('url', ['http://www.facebook.com/reel/1', 'https://facebook.com.evil.test/reel/1',
    'https://user:secret@www.facebook.com/reel/1', 'https://www.facebook.com/reel/1?sid=secret',
    'https://www.facebook.com/reel/1?session=secret', 'https://www.facebook.com/reel/1#token',
    'https://www.facebook.com:bad/reel/1', 'https://www.facebook.com:9000/reel/1',
    'https://www.facebook.com/reel/1\n', 'https://www.facebook.com\\evil.test/reel/1'])
def test_reject_unsafe_public_links(url):
    assert safe_link(url, 'facebook') is None


def test_known_public_query_and_shopee_short_link():
    assert safe_link('https://www.youtube.com/watch?v=abc&lc=123', 'youtube')
    assert safe_link('https://s.shopee.vn/40gqvxUcFk', 'shopee')
    assert not safe_link('https://s.shopee.vn/40gqvxUcFk?sid=123', 'shopee')


def test_empty_snapshot_does_not_create_root_or_campaign(tmp_path):
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    before = list(tmp_path.rglob('*'))
    snap = build_snapshot(settings)
    assert snap['rows'] == [] and snap['enabled'] is False
    assert list(tmp_path.rglob('*')) == before


def test_existing_db_and_package_read_only_with_exact_binding(tmp_path):
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    folder = settings.output / 'clip'
    manifest = {'title': 'A frozen clip', 'caption': 'Caption'}
    write_json(folder / 'package.json', manifest)
    raw = receipt()
    raw['package_sha256'] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    write_json(folder / 'publication.json', raw)
    settings.data.mkdir(parents=True)
    with sqlite3.connect(settings.data / 'campaign.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT, source TEXT, package_dir TEXT, state TEXT, updated_at TEXT)')
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', ('job', 'input.png', str(folder), 'published', 'now'))
    paths = [folder / 'package.json', folder / 'publication.json', settings.data / 'campaign.sqlite3']
    before = {p: p.read_bytes() for p in paths}
    snap = build_snapshot(settings)
    assert len(snap['rows']) == 1 and snap['rows'][0]['complete']
    assert snap['rows'][0]['job_id'] == 'job'
    assert snap['rows'][0]['folder'] == folder.resolve()
    assert {p: p.read_bytes() for p in paths} == before
    manifest['caption'] = 'changed'
    write_json(folder / 'package.json', manifest)
    snap = build_snapshot(settings)
    assert not snap['rows'][0]['complete'] and not snap['rows'][0]['links']
    assert 'không khớp' in snap['issues'][0]


def test_partial_cache_and_wrong_profile_remain_unverified(tmp_path):
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    write_json(settings.output / 'clip' / 'package.json', {'frames': [None], 'title': 'Partial'})
    write_json(settings.data / 'auth-status.json', {'profile': 'other', 'platforms': {'facebook': {'state': 'ok'}}})
    write_json(settings.data / 'affiliate-selection.json', [])
    snap = build_snapshot(settings)
    assert snap['auth'] == {}
    assert snap['affiliate'] == {} and snap['issues']
    assert snap['rows'][0]['preview'] is None and not snap['rows'][0]['complete']


def test_superseded_package_is_not_an_active_publication_or_action(tmp_path):
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    old, current, orphan = (settings.output / name for name in ('old', 'current', 'orphan'))
    for folder, job_id in ((old, 'job'), (current, 'job'), (orphan, 'other')):
        manifest = {'job_id': job_id, 'title': folder.name}
        write_json(folder / 'package.json', manifest)
        raw = receipt()
        raw['package_sha256'] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        write_json(folder / 'publication.json', raw)
    settings.data.mkdir(parents=True)
    with sqlite3.connect(settings.data / 'campaign.sqlite3') as db:
        db.execute('CREATE TABLE jobs(id TEXT, package_dir TEXT, updated_at TEXT)')
        db.execute('INSERT INTO jobs VALUES(?,?,?)', ('job', str(current), 'now'))
    paths = [p for p in tmp_path.rglob('*') if p.is_file()]
    before = {p: p.read_bytes() for p in paths}
    rows = build_snapshot(settings)['rows']
    assert {row['folder'] for row in rows} == {current.resolve(), orphan.resolve()}
    assert next(row for row in rows if row['title'] == 'current')['job_id'] == 'job'
    assert {p: p.read_bytes() for p in paths} == before


def test_selection_preserved_across_refresh_and_falls_back_only_when_removed():
    rows = [{'key': 'a'}, {'key': 'b'}]
    assert selected_key(rows, 'b') == 'b'
    assert selected_key(list(reversed(rows)), 'b') == 'b'
    assert selected_key(rows[:1], 'b') == 'a'
    assert selected_key([], 'b') is None


def test_ui_action_groups_allow_safe_control_but_block_conflicting_runner(tmp_path, monkeypatch):
    from agent.thoremix import desktop
    app = object.__new__(desktop.DesktopWindow)
    app.active, app.active_groups, app.status, app.progress = None, {}, Mock(), Mock()
    app.settings = Settings(root=str(tmp_path))
    seen = []
    class Thread:
        def __init__(self, **kwargs):
            seen.append(dict(app.active_groups))
        def start(self):
            seen.append(dict(app.active_groups))
    monkeypatch.setattr(desktop.threading, 'Thread', Thread)

    assert app.launch('login') is True
    assert app.launch('status', '--probe') is True
    assert app.launch('publish', 'package') is False

    assert app.active == 'login'
    assert app.active_groups == {'browser': 'login', 'inspect': 'status'}
    assert len(seen) == 4
    assert not list(tmp_path.iterdir())


def test_finishing_and_retry_buttons_only_follow_their_conflicting_action_group(tmp_path):
    from agent.thoremix import desktop
    app = object.__new__(desktop.DesktopWindow)
    app.active, app.active_groups = 'status', {'inspect': 'status'}

    assert app._action_busy('retry-failed') is False
    assert app._action_busy('retry-production') is False
    assert app._action_busy('finish-unpublished') is False
    assert app._action_busy('publish') is False

    app.active, app.active_groups = 'login', {'browser': 'login'}
    assert app._action_busy('publish') is True
    assert app._action_busy('retry-production') is True


def test_finishing_inspection_group_keeps_browser_group_active():
    from agent.thoremix import desktop
    app = object.__new__(desktop.DesktopWindow)
    app.active_groups = {'browser': 'login', 'inspect': 'status'}
    app.active = 'login'

    app._release_action('status')

    assert app.active_groups == {'browser': 'login'}
    assert app.active == 'login'



def test_status_cli_is_read_only_and_does_not_take_campaign_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from agent.thoremix import cli
    settings = Settings(root=str(tmp_path/'app'), input_dir=str(tmp_path/'input'))
    Path(settings.input_dir).mkdir(parents=True)
    settings.save()

    @contextmanager
    def forbidden_campaign_lock(*args, **kwargs):
        pytest.fail('read-only status must not take the campaign runner lock')
        yield

    monkeypatch.setattr(cli, 'campaign_operation', forbidden_campaign_lock)
    assert cli.main(['--root', str(settings.directory), 'status']) == 0

def test_close_never_terminates_owned_child():
    from agent.thoremix.desktop import DesktopWindow
    app = object.__new__(DesktopWindow)
    app.window, app.active, app.alive = Mock(), Mock(), True
    app.tray = None
    app.close()
    app.window.destroy.assert_called_once()
    app.active.terminate.assert_not_called()
    app.active.kill.assert_not_called()


def test_close_hides_only_when_tray_is_available_and_quit_keeps_child_alive():
    from agent.thoremix.desktop import DesktopWindow
    app = object.__new__(DesktopWindow)
    app.window, app.active, app.alive = Mock(), Mock(), True
    app.tray = Mock(available=True)
    app.close()
    app.window.withdraw.assert_called_once()
    app.window.destroy.assert_not_called()
    assert app.alive
    app.show_window()
    app.window.deiconify.assert_called_once()
    app.quit()
    app.tray.stop.assert_called_once()
    app.window.destroy.assert_called_once()
    assert not app.alive
    app.active.terminate.assert_not_called()
    app.active.kill.assert_not_called()


def test_unavailable_tray_never_hides_window_and_failure_recovers_hidden_window():
    from agent.thoremix.desktop import DesktopWindow
    app = object.__new__(DesktopWindow)
    app.window, app.status, app.alive = Mock(), Mock(), True
    app.tray = Mock(available=False)
    app._tray_command('tray_unavailable')
    app.window.deiconify.assert_called_once()
    app.close()
    app.window.withdraw.assert_not_called()
    app.window.destroy.assert_called_once()


def test_tray_routes_only_explicit_actions_and_does_not_resume_or_publish():
    from agent.thoremix.desktop import DesktopWindow
    app = object.__new__(DesktopWindow)
    app.show_window, app.show_page, app.launch, app.toggle_automation = Mock(), Mock(), Mock(), Mock()
    app._tray_command('schedule')
    app.show_page.assert_called_once_with('schedule')
    app.launch.assert_not_called()
    app._tray_command('pause')
    app.toggle_automation.assert_called_once_with(False)
    app._tray_command('show')
    app._tray_command('publish')
    app._tray_command('resume')
    app.launch.assert_not_called()


def test_second_desktop_launch_signals_first_instead_of_opening_duplicate(monkeypatch):
    import os
    import uuid
    from agent.thoremix.tray import DesktopInstance
    if os.name != 'nt':
        pytest.skip('Windows kernel event integration')
    prefix = 'Local\\ThoRemixTest-' + uuid.uuid4().hex
    monkeypatch.setattr(DesktopInstance, 'MUTEX', prefix)
    monkeypatch.setattr(DesktopInstance, 'ACTIVATE', prefix + '-activate')
    first = DesktopInstance()
    second = None
    try:
        assert first.primary and not first.activation_pending()
        second = DesktopInstance()
        assert not second.primary
        assert first.activation_pending()
        assert not first.activation_pending()
    finally:
        if second:
            second.close()
        first.close()
    replacement = DesktopInstance()
    try:
        assert replacement.primary
    finally:
        replacement.close()


def test_malformed_states_are_not_confirmations():
    assert state_text(['confirmed']) == 'Chưa thực hiện'
    assert publication_view({'platforms': {'facebook': None}})['confirmed'] == 0


def test_tk_all_pages_are_passive_and_selection_survives_refresh(tmp_path, monkeypatch):
    import tkinter as tk
    from agent.thoremix import desktop
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable')
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    def forbidden(*args, **kwargs):
        pytest.fail('Rendering must not launch commands, open links or write settings')
    monkeypatch.setattr(desktop.subprocess, 'Popen', forbidden)
    monkeypatch.setattr(desktop.webbrowser, 'open', forbidden)
    monkeypatch.setattr(Settings, 'save', forbidden)
    app = None
    try:
        app = desktop.DesktopWindow(settings, window=window, poll=False)
        for case in ('empty', 'partial'):
            if case == 'partial':
                for name in ('a', 'b'):
                    write_json(settings.output / name / 'package.json', {'title': name, 'frames': [None]})
                app.refresh()
                app.selected = str((settings.output / 'b').resolve())
                app.refresh()
                assert app.selected.endswith('b')
            for size in ('1240x820', '1080x740'):
                window.geometry(size)
                for page in desktop.PAGES:
                    app.show_page(page)
                    window.update()
                    assert app.active is None
                    if page == 'videos':
                        assert app.table.winfo_height() >= 350
                        assert app.inspector.winfo_rootx() >= app.table.winfo_rootx() + app.table.winfo_width()
        assert not settings.directory.exists()
    finally:
        if app:
            app.close()
        else:
            window.destroy()


def test_human_result_handles_partial_json_and_separates_comments():
    from agent.thoremix.desktop import readable_result
    assert 'CÔNG VIỆC' in readable_result('status', {'jobs': [None]})
    raw = receipt()
    raw['platforms']['facebook']['comment']['state'] = 'unknown'
    assert 'Facebook: bài Đã xác nhận · bình luận Chờ xác minh' in readable_result('publish', raw)


def test_failed_finishing_is_not_presented_as_success():
    from agent.thoremix.desktop import readable_result
    assert 'Chưa xử lý xong' in readable_result('finish-unpublished',{'state':'needs_input'})
    assert 'Đang có lượt sản xuất' in readable_result('finish-unpublished',{'state':'busy'})
    assert 'Đã xử lý 4 clip' in readable_result('finish-unpublished',{'state':'processed','count':4})


def test_two_target_revision_counts_only_its_requested_effects():
    raw = receipt()
    # A legacy YouTube confirmation must not count or expose a link for this revision.
    view = publication_view(raw, ['facebook', 'tiktok'])
    assert view['complete'] and view['confirmed'] == view['required'] == 4
    assert view['channels']['youtube'] == {'publication': 'Không yêu cầu', 'comment': 'Không yêu cầu'}
    assert len(view['links']) == 4
    assert not any('YouTube' in link['label'] for link in view['links'])
    raw['platforms']['tiktok']['comment']['state'] = 'unknown'
    view = publication_view(raw, ['facebook', 'tiktok'])
    assert not view['complete'] and view['confirmed'] == 3 and view['required'] == 4
    assert view['channels']['tiktok']['comment'] == 'Chờ xác minh'
    assert publication_view(receipt())['required'] == 6


@pytest.mark.parametrize('targets', [[], None, ['facebook', 'facebook'], ['facebook', 'other'], [None]])
def test_invalid_target_scope_never_counts_as_complete(targets):
    view = publication_view(receipt(), targets)
    assert not view['complete'] and not view['scope_valid']
    assert view['confirmed'] == 0 and not view['links']


def test_snapshot_uses_manifest_target_scope_and_preserves_legacy_default(tmp_path):
    settings = Settings(root=str(tmp_path / 'app'), input_dir=str(tmp_path / 'input'))
    for name, fields in [('revision', {'publication_targets': ['facebook', 'tiktok'], 'publication_revision': 'a' * 64}),
                         ('legacy', {})]:
        manifest = {'title': name, 'video_sha256': 'a' * 64, **fields}
        folder = settings.output / name
        write_json(folder / 'package.json', manifest)
        raw = receipt()
        del raw['platforms']['youtube']
        raw['package_sha256'] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        write_json(folder / 'publication.json', raw)
    rows = {row['title']: row for row in build_snapshot(settings)['rows']}
    assert rows['revision']['complete'] and rows['revision']['state'] == 'Hoàn tất 2 kênh yêu cầu'
    assert rows['revision']['required'] == 4
    assert rows['revision']['channels']['youtube']['publication'] == 'Không yêu cầu'
    assert not rows['legacy']['complete'] and rows['legacy']['state'] == '4/6 mục đã xác nhận'
    from agent.thoremix.desktop import readable_result
    assert 'YouTube' not in readable_result('publish', raw)
