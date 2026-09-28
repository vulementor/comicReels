import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from agent.thoremix.config import Settings
from agent.thoremix.core import Campaign, RunnerBusyError, campaign_operation, runner_lock, sha256
from agent.thoremix import core
from agent.thoremix.cli import tick
from agent.thoremix.producer import FlowKitProducer


@pytest.fixture
def settings(tmp_path):
    source = tmp_path / 'input'
    source.mkdir()
    config = Settings(root=str(tmp_path / 'app'), input_dir=str(source))
    config.save()
    return config


def picture(settings, name='one.png', color='blue'):
    path = Path(settings.input_dir) / name
    Image.new('RGB', (48, 72), color).save(path)
    return path


def test_reservation_survives_restart_and_deduplicates_content(settings):
    first = picture(settings)
    duplicate = picture(settings, 'same.png')
    job = Campaign(settings).reserve('2026-09-27/11:00')
    again = Campaign(settings).reserve('2026-09-27/11:00')
    assert again['id'] == job['id']
    assert first.exists() and duplicate.exists()
    with pytest.raises(RuntimeError, match='Không còn ảnh'):
        Campaign(settings).reserve('2026-09-27/18:30')


def test_owner_approval_rejects_changed_manifest_and_recovers_after_manifest_commit(settings, monkeypatch, tmp_path):
    from agent.thoremix.quality import POLICY,manifest_digest
    from agent.thoremix.config import atomic_json
    from agent.comicreels.story import StoryReceipt
    picture(settings)
    video=tmp_path/'video.mp4';video.write_bytes(b'fixture')
    monkeypatch.setattr(core,'validate_media',lambda *a,**k:{'full_decode':True})
    campaign=Campaign(settings);job=campaign.reserve('production/review')
    package=campaign.finalize(job['id'],video,children=[],metadata={
        'qa':{'release_ready':False,'production_complete':True,'policy':POLICY},
        'review':{'status':'pending','warnings':[{'stage':'video_review'}]}})
    path=Path(job['package_dir'])/'package.json'
    stale=manifest_digest(package)
    package['caption']='Updated caption';atomic_json(path,package)
    with pytest.raises(ValueError,match='thay đổi'):campaign.approve(job['id'],stale)
    assert campaign.get(job['id'])['state']=='awaiting_approval'
    receipt=settings.data/'production'/job['id']/'flow/story-receipt.json'
    atomic_json(receipt,{'state':'PROCESSING'})
    calls=[]
    def complete(self,path):
        calls.append(path)
        if len(calls)==1:raise OSError('interrupted after approval manifest commit')
    monkeypatch.setattr(StoryReceipt,'complete',complete)
    expected=manifest_digest(package)
    with pytest.raises(OSError):campaign.approve(job['id'],expected)
    approved=campaign.approve(job['id'],expected)
    assert approved['review']['status']=='approved' and len(calls)==2
    assert campaign.get(job['id'])['state']=='video_ready'
    campaign.update(job['id'],'published')
    campaign.approve(job['id'],expected)
    assert campaign.get(job['id'])['state']=='published'


def test_owner_can_refresh_and_approve_after_stale_request_rejected(settings):
    from agent.thoremix.quality import request_approval
    from agent.thoremix.config import atomic_json
    job_id='a'*32
    first='1'*64;second='2'*64
    request_approval(settings,job_id,first)
    path=settings.data/'review-requests'/(job_id+'.json')
    with pytest.raises(ValueError):request_approval(settings,job_id,second)
    rejected=json.loads(path.read_text());rejected['state']='rejected';atomic_json(path,rejected)
    request_approval(settings,job_id,second)
    current=json.loads(path.read_text())
    assert current['manifest_sha256']==second and current['state']=='pending'
    archived=list((path.parent/'history').glob('*.json'))
    assert len(archived)==1 and json.loads(archived[0].read_text())==rejected


def test_reservation_ignores_subfolders_and_invalid_images(settings):
    (Path(settings.input_dir) / 'bad.png').write_text('bad')
    nested = Path(settings.input_dir) / 'archived'
    nested.mkdir()
    Image.new('RGB', (20, 30)).save(nested / 'old.png')
    with pytest.raises(RuntimeError):
        Campaign(settings).reserve('slot')


def test_output_collision_preserves_existing_package(settings):
    source = picture(settings)
    existing = settings.output / source.stem
    existing.mkdir(parents=True)
    (existing / 'sentinel').write_text('keep')
    job = Campaign(settings).reserve('slot')
    assert Path(job['package_dir']).name == f'{source.stem}-{sha256(source)[:12]}'
    assert (existing / 'sentinel').read_text() == 'keep'


def test_failed_media_validation_preserves_source_and_reservation(settings, monkeypatch, tmp_path):
    source = picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    video = tmp_path / 'invalid.mp4'
    video.write_bytes(b'invalid video')
    def fail(staged, **kwargs):
        assert staged != video and staged.read_bytes() == video.read_bytes()
        raise ValueError('decode failed')
    monkeypatch.setattr(core, 'validate_media', fail)
    with pytest.raises(ValueError, match='decode'):
        campaign.finalize(job['id'], video, children=[], metadata={'qa': {'release_ready': True}})
    assert source.exists()
    assert campaign.get(job['id'])['state'] == 'reserved'
    assert not Path(job['package_dir']).exists()


def test_source_change_cannot_move_new_content(settings, monkeypatch, tmp_path):
    source = picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='thay đổi'):
        campaign.finalize(job['id'], tmp_path / 'video.mp4', children=[], metadata={})
    assert source.read_bytes() == b'changed'


def test_package_move_follows_verified_copies(settings, monkeypatch, tmp_path):
    source = picture(settings)
    original_hash = sha256(source)
    video = tmp_path / 'render.mp4'
    video.write_bytes(b'fixture video')
    child = tmp_path / 'child.png'
    Image.new('RGB', (24, 48)).save(child)
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    result = campaign.finalize(job['id'], video, children=[child], metadata={'qa': {'release_ready': True}})
    assert not source.exists()
    assert sha256(Path(result['source_path'])) == original_hash
    assert sha256(Path(result['video_path'])) == sha256(video)
    assert Path(result['video_path']).name == 'one.mp4'
    assert campaign.get(job['id'])['state'] == 'video_ready'
    assert json.loads((Path(job['package_dir']) / 'package.json').read_text())['frames'][0]['sha256'] == sha256(child)
    assert campaign.finalize(job['id'], video, children=[child], metadata={'qa': {'release_ready': True}}) == result


def test_archive_recovers_crash_after_complete_manifest(settings, monkeypatch, tmp_path):
    source = picture(settings)
    video = tmp_path / 'render.mp4'
    video.write_bytes(b'fixture')
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    original_update = campaign.update
    def crash_on_complete(job_id, state, **details):
        if state == 'video_ready':
            raise OSError('simulated abrupt interruption')
        return original_update(job_id, state, **details)
    monkeypatch.setattr(campaign, 'update', crash_on_complete)
    with pytest.raises(OSError):
        campaign.finalize(job['id'], video, children=[], metadata={'qa': {'release_ready': True}})
    assert source.exists()
    restarted = Campaign(settings)
    package = restarted.reconcile_package(job['id'])
    assert not source.exists()
    assert Path(package['source_path']).is_file()
    assert restarted.get(job['id'])['state'] == 'video_ready'


def test_single_runner_lock_releases_on_exception(settings):
    with pytest.raises(ValueError):
        with runner_lock(settings.data):
            with pytest.raises((RuntimeError, OSError)):
                with runner_lock(settings.data):
                    pass
            raise ValueError('stopped')
    with runner_lock(settings.data):
        pass


def test_wrong_slot_and_paused_do_not_touch_input(settings):
    source = picture(settings)
    assert tick(settings)['state'] == 'paused'
    with pytest.raises(ValueError):
        tick(replace(settings, enabled=True), '12:30')
    assert Campaign(settings).jobs() == []
    assert source.exists()


def test_only_gpt_fullproxy_can_be_configured(settings):
    with pytest.raises(ValueError, match='gpt_fullproxy'):
        replace(settings, ai_provider='another-ai').save()
    assert Settings.load(settings.directory).ai_provider == 'gpt_fullproxy'


def test_import_unknown_outcome_reconciles_by_hash_without_resubmit(settings):
    picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    campaign.update(job['id'], 'importing')
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {'projects': [{'id': 'project-1', 'source_sha256': job['source_sha256']}]}
    class Client:
        def get(self, path):
            assert path == '/api/comicreels/projects'
            return Response()
        def post(self, *args, **kwargs):
            pytest.fail('must not repeat uncertain import')
    resumed = FlowKitProducer(campaign, Client()).import_source(job['id'])
    assert json.loads(resumed['detail'])['flowkit_project_id'] == 'project-1'


@pytest.mark.parametrize('previous_effect', ['confirmed', 'unknown_after_submit'])
def test_second_root_cannot_publish_existing_package_with_new_journal(settings, tmp_path, monkeypatch, previous_effect):
    from agent.thoremix.sdk import ThoRemixClient
    from agent.thoremix import publishing
    Campaign(settings)
    package = settings.output / 'existing'
    package.mkdir(parents=True)
    (package / 'package.json').write_text(json.dumps({'prior_effect': previous_effect}))
    journal = settings.data / 'krp/state.sqlite3'
    journal.parent.mkdir(parents=True)
    journal.write_bytes(previous_effect.encode())
    owner_bytes = (Path(settings.input_dir) / '.thoremix/owner.json').read_bytes()
    owner = json.loads(owner_bytes)
    assert owner['effect_journal'] == core._canonical(journal)
    other = replace(settings, root=str(tmp_path / 'other-app'))
    other.save()
    monkeypatch.setattr(publishing, 'publish_package', lambda *a, **k: pytest.fail('new publication/journal forbidden'))
    with pytest.raises(ValueError, match='chủ sở hữu'):
        ThoRemixClient(other.directory).publish(package)
    assert not (other.data / 'campaign.sqlite3').exists()
    assert not (other.data / 'krp').exists()
    assert journal.read_bytes() == previous_effect.encode()
    assert (Path(settings.input_dir) / '.thoremix/owner.json').read_bytes() == owner_bytes


def test_second_root_cli_import_cannot_create_an_identity(settings, tmp_path, monkeypatch, capsys):
    from agent.thoremix.cli import main
    picture(settings)
    job = Campaign(settings).reserve('original')
    Campaign(settings).update(job['id'], 'importing')
    other = replace(settings, root=str(tmp_path / 'other-app'))
    other.save()
    monkeypatch.setattr(FlowKitProducer, 'import_source', lambda *a, **k: pytest.fail('must not import'))
    assert main(['--root', str(other.directory), 'import-source', '--slot', 'second']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['state'] == 'needs_input'
    assert not (other.data / 'campaign.sqlite3').exists()
    assert len(Campaign(settings).jobs()) == 1
    assert Campaign(settings).get(job['id'])['state'] == 'importing'


def test_core_reserve_rejects_second_owner_sequentially(settings, tmp_path):
    picture(settings)
    Campaign(settings).reserve('first')
    other = replace(settings, root=str(tmp_path / 'other-app'))
    with pytest.raises(ValueError, match='chủ sở hữu'):
        Campaign(other)
    assert not (other.data / 'campaign.sqlite3').exists()


def test_source_os_lock_blocks_different_root_even_with_independent_root_lock(settings, tmp_path):
    other = replace(settings, root=str(tmp_path / 'other-app'))
    with runner_lock(Path(settings.input_dir) / '.thoremix'):
        with pytest.raises(RunnerBusyError):
            with campaign_operation(other):
                pytest.fail('source lock bypass')
    assert not (Path(settings.input_dir) / '.thoremix/owner.json').exists()


def test_owner_is_canonical_and_nested_operations_reuse_one_lock(settings):
    picture(settings)
    aliased = replace(settings, input_dir=str(Path(settings.input_dir) / '..' / 'input'))
    with campaign_operation(settings):
        job = Campaign(aliased).reserve('one')
        Campaign(settings).update(job['id'], 'reserved')
    owner = json.loads((Path(settings.input_dir) / '.thoremix/owner.json').read_text())
    assert owner['source'] == core._canonical(settings.input_dir)
    assert len(Campaign(settings).jobs()) == 1


def test_cli_busy_is_safe_and_writes_nothing_while_lock_owned(settings, capsys):
    from agent.thoremix.cli import main
    marker = settings.data / 'last-result.json'
    settings.data.mkdir(parents=True, exist_ok=True)
    marker.write_text('preserve prior result')
    with runner_lock(settings.data):
        assert main(['--root', str(settings.directory), 'affiliate']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {'state': 'busy', 'error_type': 'RunnerBusyError',
                      'reason': 'Một lượt Thỏ Remix hoặc cửa sổ đăng nhập đang mở; chờ lượt đó hoàn tất.'}
    assert marker.read_text() == 'preserve prior result'


def test_other_runtime_errors_do_not_expose_private_messages(settings, capsys, monkeypatch):
    from agent.thoremix import cli
    def fail(*a, **k):
        raise RuntimeError('Cookie: private token')
    monkeypatch.setattr(cli, 'status', fail)
    assert cli.main(['--root', str(settings.directory), 'status']) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {'state': 'needs_input', 'error_type': 'RuntimeError'}


def test_video_replaced_during_copy_never_archives_source(settings, tmp_path, monkeypatch):
    source = picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    video = tmp_path / 'render.mp4'
    video.write_bytes(b'previously valid video')
    original_copy = core.shutil.copy2
    def replace_before_copy(origin, target):
        if Path(origin) == video:
            video.write_bytes(b'new invalid video')
        return original_copy(origin, target)
    monkeypatch.setattr(core.shutil, 'copy2', replace_before_copy)
    monkeypatch.setattr(core, 'validate_media', lambda p, **kwargs: pytest.fail('unstable copy must not be accepted'))
    with pytest.raises(ValueError, match='sao chép'):
        campaign.finalize(job['id'], video, children=[], metadata={'qa': {'release_ready': True}})
    assert source.exists()
    assert campaign.get(job['id'])['state'] == 'reserved'
    assert not Path(job['package_dir']).exists()


def test_only_frozen_copy_is_decoded_even_if_caller_video_changes_later(settings, tmp_path, monkeypatch):
    picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    video = tmp_path / 'render.mp4'
    video.write_bytes(b'good frozen bytes')
    digest = sha256(video)
    def decode(staged, **kwargs):
        assert staged != video and staged.name == 'frozen.mp4'
        assert sha256(staged) == digest
        video.write_bytes(b'caller overwrote its render')
        return {'full_decode': True, 'tested_digest': sha256(staged)}
    monkeypatch.setattr(core, 'validate_media', decode)
    package = campaign.finalize(job['id'], video, children=[], metadata={'qa': {'release_ready': True}})
    assert package['video_sha256'] == package['media']['tested_digest'] == digest
    assert sha256(Path(package['video_path'])) == digest


def test_staged_video_modified_during_decode_is_rejected(settings, tmp_path, monkeypatch):
    source = picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot')
    video = tmp_path / 'render.mp4'
    video.write_bytes(b'good before decode')
    def decode(staged, **kwargs):
        staged.write_bytes(b'bad changed during decode')
        return {'full_decode': True}
    monkeypatch.setattr(core, 'validate_media', decode)
    with pytest.raises(ValueError, match='giải mã'):
        campaign.finalize(job['id'], video, children=[], metadata={'qa': {'release_ready': True}})
    assert source.exists() and campaign.get(job['id'])['state'] == 'reserved'


@pytest.mark.skipif(core.os.name != 'nt', reason='Windows byte-range lock interoperability')
def test_upgrade_refuses_python_only_owner_without_install_writes(tmp_path):
    import importlib.util
    helper = Path(__file__).resolve().parents[2] / 'deployment/thoremix/verify_upgrade_lock.py'
    spec = importlib.util.spec_from_file_location('verify_upgrade_lock', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify(tmp_path / 'offline-installed')
    assert result['blocked_with_python_owner'] and result['files_unchanged']
    assert result['available_after_release']


@pytest.mark.skipif(core.os.name != 'nt' or not Path('D:/StableApp/ThoRemix/runtime/python/python.exe').is_file(),
                    reason='Windows staged validation uses installed interpreter read-only')
def test_real_staged_build_validation_from_canonical_checkout_cwd(tmp_path):
    import importlib.util
    helper = Path(__file__).resolve().parents[2] / 'deployment/thoremix/verify_upgrade_lock.py'
    spec = importlib.util.spec_from_file_location('verify_upgrade_stage', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify_staged_validation(tmp_path / 'stage')
    assert result['staged_validation_passed'] and result['canonical_cwd_restored']
    assert not result['installed_files_written']


def test_exact_source_reservation_does_not_select_another_image(settings):
    picture(settings, 'other.png', color='red')
    selected = picture(settings, 'selected.png', color='blue')
    campaign = Campaign(settings)
    job = campaign.reserve('ready-import', source=selected)
    assert Path(job['source']) == selected.resolve()
    assert campaign.reserve('ready-import', source=selected)['id'] == job['id']
    with pytest.raises(ValueError, match='khác'):
        campaign.reserve('ready-import', source=Path(settings.input_dir) / 'other.png')
    with pytest.raises(ValueError, match='đã có công việc'):
        campaign.reserve('another-slot', source=selected)
    assert len(campaign.jobs()) == 1


@pytest.mark.parametrize('location', ['outside', 'nested'])
def test_exact_source_cannot_escape_direct_source_directory(settings, tmp_path, location):
    directory = tmp_path if location == 'outside' else Path(settings.input_dir) / 'nested'
    directory.mkdir(exist_ok=True)
    source = directory / 'image.png'
    Image.new('RGB', (48, 72)).save(source)
    campaign = Campaign(settings)
    with pytest.raises(ValueError, match='trực tiếp'):
        campaign.reserve('slot', source=source)
    assert campaign.jobs() == [] and source.exists()


def test_exact_prepared_package_retries_same_reservation_and_archives_once(settings, tmp_path, monkeypatch):
    from agent.thoremix.sdk import ThoRemixClient
    from agent.thoremix.cli import main
    selected = picture(settings, 'selected.png')
    other = picture(settings, 'other.png', color='red')
    video = tmp_path / 'reviewed.mp4'
    video.write_bytes(b'frozen reviewed video')
    metadata = {'qa': {'release_ready': True}, 'title': 'Reviewed clip'}
    meta = tmp_path / 'metadata.json'
    meta.write_text(json.dumps(metadata), encoding='utf-8')
    client = ThoRemixClient(settings.directory)
    def fail(_, **kwargs):
        raise ValueError('media rejected')
    monkeypatch.setattr(core, 'validate_media', fail)
    with pytest.raises(ValueError, match='media rejected'):
        client.prepare_package('ready-import', selected, video, children=[], metadata=metadata)
    job_id = Campaign(settings).jobs()[0]['id']
    assert selected.exists() and other.exists()
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    assert main(['--root', str(settings.directory), 'prepare-package', '--slot', 'ready-import',
                 '--source', str(selected), '--video', str(video), '--metadata', str(meta)]) == 0
    job = Campaign(settings).jobs()[0]
    assert job['id'] == job_id and job['state'] == 'video_ready'
    assert not selected.exists() and other.exists()
    package = client.prepare_package('ready-import', selected, video, children=[], metadata=metadata)
    assert package['job_id'] == job_id and len(Campaign(settings).jobs()) == 1


def test_unapproved_ready_import_does_not_reserve(settings, tmp_path):
    source = picture(settings)
    campaign = Campaign(settings)
    with pytest.raises(ValueError, match='chất lượng'):
        campaign.prepare_package('slot', source, tmp_path / 'unused.mp4', children=[],
                                 metadata={'qa': {'release_ready': False}})
    assert campaign.jobs() == [] and source.exists()


@pytest.mark.parametrize('failure', ['missing', 'copy'])
def test_frame_copy_failure_can_resume_same_import_without_partial_final_folder(settings, tmp_path, monkeypatch, failure):
    from agent.thoremix.sdk import ThoRemixClient
    source = picture(settings)
    video = tmp_path / 'reviewed.mp4'
    video.write_bytes(b'reviewed video')
    first, second = tmp_path / 'first.png', tmp_path / 'second.png'
    Image.new('RGB', (24, 48), 'red').save(first)
    if failure == 'copy':
        Image.new('RGB', (24, 48), 'blue').save(second)
    actual_copy = core.shutil.copy2
    def fail_second(origin, destination):
        if Path(origin) == second and failure == 'copy':
            raise OSError('simulated frame read failure')
        return actual_copy(origin, destination)
    monkeypatch.setattr(core.shutil, 'copy2', fail_second)
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    client = ThoRemixClient(settings.directory)
    metadata = {'qa': {'release_ready': True}}
    with pytest.raises(OSError):
        client.prepare_package('import', source, video, children=[first, second], metadata=metadata)
    job = Campaign(settings).jobs()[0]
    assert source.exists() and not Path(job['package_dir']).exists()
    monkeypatch.setattr(core.shutil, 'copy2', actual_copy)
    Image.new('RGB', (24, 48), 'blue').save(second)
    result = client.prepare_package('import', source, video, children=[first, second], metadata=metadata)
    assert result['job_id'] == job['id'] and len(Campaign(settings).jobs()) == 1
    assert not source.exists()
    assert [f['sha256'] for f in result['frames']] == [sha256(first), sha256(second)]
    assert [Path(f['path']).name for f in result['frames']] == ['01.png', '02.png']


def test_dashboard_saved_auth_evidence_is_explicitly_dated_and_profile_bound(settings):
    from agent.thoremix.cli import status
    from agent.thoremix.desktop import readable_result
    from agent.thoremix.config import atomic_json
    report = {'profile': settings.social_profile, 'observed_at': '2026-09-27T09:00:00+00:00',
              'platforms': {p: {'state': 'ok'} for p in ('facebook', 'tiktok', 'youtube')}, 'ready': True}
    atomic_json(settings.data / 'auth-status.json', report)
    observed = status(settings)
    assert observed['last_auth_check'] == report
    text = readable_result('status', observed)
    assert 'Lần kiểm tra đã lưu: 2026-09-27T09:00:00+00:00' in text
    assert 'youtube: ok' in text and 'kiểm tra lại trước mỗi lần đăng' in text
    atomic_json(settings.data / 'auth-status.json', dict(report, profile='unrelated'))
    assert 'last_auth_check' not in status(settings)


@pytest.mark.parametrize('approval', ['false', 1, {'yes': True}])
def test_direct_finalize_rejects_truthy_non_boolean_qa_without_archival(settings, tmp_path, approval):
    source = picture(settings)
    campaign = Campaign(settings)
    job = campaign.reserve('slot', source=source)
    with pytest.raises(ValueError, match='chất lượng'):
        campaign.finalize(job['id'], tmp_path / 'unread.mp4', children=[],
                          metadata={'qa': {'release_ready': approval}})
    assert source.exists() and not Path(job['package_dir']).exists()
    assert campaign.get(job['id'])['state'] == 'reserved'


def test_manual_cli_and_sdk_publish_project_partial_and_complete_reports(settings, tmp_path, monkeypatch):
    from agent.thoremix import publishing
    from agent.thoremix.cli import main
    from agent.thoremix.sdk import ThoRemixClient
    source = picture(settings)
    video = tmp_path / 'reviewed.mp4'
    video.write_bytes(b'reviewed bytes')
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    client = ThoRemixClient(settings.directory)
    package = client.prepare_package('import', source, video, children=[], metadata={'qa': {'release_ready': True}})
    directory = Path(package['video_path']).parent
    report = {'complete': False, 'platforms': {'facebook': {'status': 'confirmed'}}}
    calls = []
    def publish(path, **kwargs):
        calls.append((path, kwargs))
        return report
    monkeypatch.setattr(publishing, 'publish_package', publish)
    assert main(['--root', str(settings.directory), 'publish', str(directory)]) == 0
    job = Campaign(settings).get(package['job_id'])
    assert job['state'] == 'publishing' and json.loads(job['detail'])['publication'] == report
    report = {'complete': True, 'platforms': {p: {'status': 'complete'} for p in ('facebook', 'tiktok', 'youtube')}}
    assert client.publish(directory) == report
    job = Campaign(settings).get(package['job_id'])
    assert job['state'] == 'published' and json.loads(job['detail'])['publication'] == report
    assert all(kwargs['tool_root'] == settings.directory for _, kwargs in calls)


@pytest.mark.parametrize('field,value', [('job_id', 'another-job'), ('source_sha256', 'f' * 64)])
def test_manual_publish_rejects_mismatched_job_before_effect(settings, tmp_path, monkeypatch, field, value):
    from agent.thoremix import publishing
    from agent.thoremix.sdk import ThoRemixClient
    source = picture(settings)
    video = tmp_path / 'reviewed.mp4'
    video.write_bytes(b'reviewed bytes')
    monkeypatch.setattr(core, 'validate_media', lambda _, **kwargs: {'full_decode': True})
    client = ThoRemixClient(settings.directory)
    package = client.prepare_package('import', source, video, children=[], metadata={'qa': {'release_ready': True}})
    job_id = package['job_id']
    directory = Path(package['video_path']).parent
    package[field] = value
    (directory / 'package.json').write_text(json.dumps(package), encoding='utf-8')
    monkeypatch.setattr(publishing, 'publish_package', lambda *a, **k: pytest.fail('external effect forbidden'))
    with pytest.raises(ValueError, match='công việc'):
        client.publish(directory)
    assert Campaign(settings).get(job_id)['state'] == 'video_ready'


def test_direct_sdk_uses_real_bundled_media_tools_without_ambient_path(settings, tmp_path, monkeypatch):
    import os
    import shutil
    import subprocess
    from agent.thoremix import publishing
    from agent.thoremix.media import media_tool
    from agent.thoremix.sdk import ThoRemixClient
    names = ('ffmpeg', 'ffprobe')
    executables = {name: shutil.which(name) for name in names}
    if not all(executables.values()):
        pytest.skip('real media binaries required')
    bin_dir = settings.directory / 'runtime' / 'bin'
    bin_dir.mkdir(parents=True)
    for name, origin in executables.items():
        target = bin_dir / (name + ('.exe' if os.name == 'nt' else ''))
        try:
            os.link(origin, target)
        except OSError:
            shutil.copyfile(origin, target)
    video = tmp_path / 'real.mp4'
    subprocess.run([executables['ffmpeg'], '-v', 'error', '-f', 'lavfi', '-i', 'color=s=32x64:d=0.2',
                    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '0.2',
                    '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p', str(video)], check=True)
    source = picture(settings)
    monkeypatch.setenv('PATH', '')
    assert all(Path(media_tool(name, settings.directory)).parent == bin_dir for name in names)
    client = ThoRemixClient(settings.directory)
    package = client.prepare_package('sdk', source, video, children=[], metadata={'qa': {'release_ready': True}})
    assert package['media']['full_decode'] and not source.exists()
    def external_boundary(directory, **kwargs):
        assert kwargs['tool_root'] == settings.directory
        publishing._validate_media(Path(package['video_path']), tool_root=kwargs['tool_root'])
        return {'complete': True}
    monkeypatch.setattr(publishing, 'publish_package', external_boundary)
    assert client.publish(Path(package['video_path']).parent)['complete']
    assert os.environ['PATH'] == ''
