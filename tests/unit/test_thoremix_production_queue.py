from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess

import pytest
from PIL import Image

from agent.thoremix.config import Settings
from agent.thoremix.core import Campaign

NOW = datetime.fromisoformat('2026-09-27T10:00:00+07:00')


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.thoremix.core.now_iso', lambda: NOW.isoformat())
    source = tmp_path / 'input'
    source.mkdir()
    config = Settings(root=str(tmp_path / 'app'), input_dir=str(source), enabled=True)
    config.save()
    return config


@pytest.fixture(scope='module')
def video(tmp_path_factory):
    from agent.thoremix.media import media_tool
    path = tmp_path_factory.mktemp('queue-media') / 'tiny.mp4'
    subprocess.run([media_tool('ffmpeg', Path('D:/StableApp/ThoRemix')), '-v', 'error',
        '-f', 'lavfi', '-i', 'color=c=blue:s=72x128:r=12:d=0.3', '-f', 'lavfi', '-i',
        'anullsrc=r=44100:cl=mono', '-t', '0.3', '-c:v', 'libx264', '-c:a', 'aac',
        '-pix_fmt', 'yuv420p', str(path)], check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return path


def images(settings, count):
    for index in range(count):
        Image.new('RGB', (24, 36), (index, 50, 80)).save(Path(settings.input_dir) / f'{index}.png')


def factory(video, outcomes=(), after=None):
    results = iter(outcomes)
    class Producer:
        def __init__(self, campaign):
            self.campaign = campaign
        def status(self):
            return {'automatic_story_ready': True}
        def run(self, job_id):
            outcome = next(results, 'video_ready')
            if outcome == 'uncertain':
                raise TimeoutError('private signed URL must not enter report')
            if outcome == 'failed':
                return {'state': 'failed', 'reason': 'private raw provider text'}
            self.campaign.finalize(job_id, video, children=[], metadata={'qa': {'release_ready': True}})
            if after:
                after()
            if outcome == 'crash_after_package':
                raise KeyboardInterrupt('process stopped')
            return {'state': 'video_ready'}
    return Producer


def ahead(settings, limit=5):
    settings = replace(settings, production_mode='ahead', daily_production_limit=limit)
    settings.save()
    return settings


def test_production_defaults_and_legacy_config_migration(settings):
    assert settings.production_mode == 'scheduled'
    assert settings.daily_production_limit == 5
    raw = json.loads(settings.path.read_text())
    raw.pop('production_mode', None)
    raw.pop('daily_production_limit', None)
    settings.path.write_text(json.dumps(raw))
    assert Settings.load(settings.root).daily_production_limit == 5


@pytest.mark.parametrize('limit', [0, 1001, -1, True, 2.5, '5'])
def test_invalid_daily_limit_rejected(settings, limit):
    with pytest.raises(ValueError):
        replace(settings, daily_production_limit=limit).save()


def test_failures_replaced_until_five_verified_packages_and_restart_is_noop(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings)
    images(settings, 9)
    clock = [NOW]
    waits = []
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += timedelta(seconds=seconds)
    result = produce_ahead(settings, producer_factory=factory(video, ['failed', 'failed']), now=lambda: clock[0], sleep=sleep)
    assert sum(waits) == 120
    assert result['completed'] == 5 and result['failed'] == 2
    assert result['state'] == 'quota_reached' and result['ready_count'] == 5
    assert len(Campaign(settings).jobs()) == 7
    assert len(list(Path(settings.input_dir).glob('*.png'))) == 4
    assert 'private' not in json.dumps(result)
    again = produce_ahead(settings, producer_factory=lambda _: pytest.fail('must not produce again'), now=lambda: NOW)
    assert again['completed'] == 5 and len(Campaign(settings).jobs()) == 7


def test_exhaustion_and_invalid_image_are_logged_without_losing_source(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings)
    images(settings, 2)
    bad = Path(settings.input_dir) / 'bad.png'
    bad.write_bytes(b'broken image')
    clock = [NOW]
    def sleep(seconds): clock[0] += timedelta(seconds=seconds)
    result = produce_ahead(settings, producer_factory=factory(video, ['failed']), now=lambda: clock[0], sleep=sleep)
    assert clock[0] == NOW + timedelta(seconds=60)
    assert result['state'] == 'source_exhausted' and result['completed'] == 1
    assert result['failed'] == 1 and result['input_errors']
    assert bad.read_bytes() == b'broken image'
    assert len(list(Path(settings.input_dir).glob('*.png'))) == 2


def test_failure_cooldown_survives_restart_and_pause(settings,video):
    from agent.thoremix.production_queue import produce_ahead
    settings=ahead(settings,1)
    images(settings,3)
    clock=[NOW]
    def interrupted_wait(seconds):
        clock[0]+=timedelta(seconds=seconds)
        raise KeyboardInterrupt('restart while cooling down')
    with pytest.raises(KeyboardInterrupt):
        produce_ahead(settings,producer_factory=factory(video,['failed']),now=lambda:clock[0],sleep=interrupted_wait)
    assert len(Campaign(settings).jobs())==1
    waits=[]
    def pause(seconds):
        waits.append(seconds)
        clock[0]+=timedelta(seconds=seconds)
        replace(settings,enabled=False).save()
    result=produce_ahead(settings,producer_factory=lambda _:pytest.fail('must wait before provider'),now=lambda:clock[0],sleep=pause)
    assert result['state']=='paused' and len(Campaign(settings).jobs())==1
    settings.save()
    def finish_wait(seconds):
        waits.append(seconds)
        clock[0]+=timedelta(seconds=seconds)
    result=produce_ahead(settings,producer_factory=factory(video),now=lambda:clock[0],sleep=finish_wait)
    assert result['completed']==1 and clock[0]==NOW+timedelta(seconds=60)


@pytest.mark.parametrize('downstream',[False,True])
def test_quarantine_retains_unknown_effect_and_never_resumes_it(settings,downstream):
    from agent.thoremix.production_queue import ProductionQueue
    from agent.thoremix.config import atomic_json
    images(settings,2)
    q=ProductionQueue(settings)
    job=q.campaign.reserve('production/uncertain')
    with q.campaign.connect() as db:
        db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status) VALUES(?,?,?,?)',
                   (job['id'],NOW.date().isoformat(),NOW.isoformat(),'unknown'))
    d=settings.data/'production'/job['id']
    atomic_json(d/'images.json',{'state':'UNKNOWN','source_sha256':job['source_sha256']})
    before=(d/'images.json').read_bytes()
    if downstream:
        atomic_json(d/'video.json',{'state':'SUBMITTING'})
        with pytest.raises(ValueError):q.quarantine_preflow(job['id'],NOW)
        assert q.summary(NOW)['blocking_uncertain']==1
        return
    q.quarantine_preflow(job['id'],NOW)
    q=ProductionQueue(settings);q.recover(NOW+timedelta(seconds=60))
    report=q.summary(NOW)
    assert report['uncertain']==1 and report['blocking_uncertain']==0
    assert report['retry_after_s']==60 and (d/'images.json').read_bytes()==before
    assert Path(job['source']).is_file()
    assert q.campaign.reserve('another')['source_sha256']!=job['source_sha256']
    class Never:
        def reconcile(self,_):pytest.fail('quarantine must not auto-resume')
    q.reconcile_unknown(Never(),lambda:NOW)


def test_quarantine_busy_owner_leaves_audit_and_attempt_unchanged(settings):
    from concurrent.futures import ThreadPoolExecutor
    from agent.thoremix.production_queue import ProductionQueue
    from agent.thoremix.core import campaign_operation, RunnerBusyError
    from agent.thoremix.config import atomic_json
    images(settings,1)
    queue=ProductionQueue(settings)
    job=queue.campaign.reserve('production/uncertain')
    with queue.campaign.connect() as db:
        db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status) VALUES(?,?,?,?)',
                   (job['id'],NOW.date().isoformat(),NOW.isoformat(),'unknown'))
    directory=settings.data/'production'/job['id']
    atomic_json(directory/'images.json',{'state':'UNKNOWN','source_sha256':job['source_sha256']})
    before=queue.attempts()
    with ThreadPoolExecutor(max_workers=1) as executor:
        with campaign_operation(settings):
            future=executor.submit(queue.quarantine_preflow,job['id'],NOW)
            with pytest.raises(RunnerBusyError):future.result(timeout=5)
    assert queue.attempts()==before
    assert queue.campaign.get(job['id'])==job
    assert not (directory/'quarantine.json').exists()


def test_uncertain_production_holds_source_and_never_retries_or_overspends(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings)
    images(settings, 6)
    result = produce_ahead(settings, producer_factory=factory(video, ['uncertain']), now=lambda: NOW)
    assert result['state'] == 'reconciliation_required' and result['uncertain'] == 1
    class Reconciler:
        def __init__(self, campaign): pass
        def run(self, job_id): pytest.fail('ambiguous paid retry')
        def reconcile(self, job_id): return {'state':'reconciliation_required'}
    again = produce_ahead(settings, producer_factory=Reconciler, now=lambda: NOW)
    assert again['uncertain'] == 1 and len(Campaign(settings).jobs()) == 1
    assert len(list(Path(settings.input_dir).glob('*.png'))) == 6


def test_crash_after_package_reconciles_quota_without_new_generation(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings, 1)
    images(settings, 2)
    with pytest.raises(KeyboardInterrupt):
        produce_ahead(settings, producer_factory=factory(video, ['crash_after_package']), now=lambda: NOW)
    result = produce_ahead(settings, producer_factory=lambda _: pytest.fail('must reconcile local package'), now=lambda: NOW)
    assert result['completed'] == 1 and result['state'] == 'quota_reached'
    assert len(Campaign(settings).jobs()) == 1


def test_pause_and_mode_change_take_effect_before_next_clip(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings)
    images(settings, 5)
    result = produce_ahead(settings, producer_factory=factory(video,
        after=lambda: replace(Settings.load(settings.root), enabled=False).save()), now=lambda: NOW)
    assert result['completed'] == 1 and result['state'] == 'paused'
    assert len(Campaign(settings).jobs()) == 1


def test_new_day_starts_new_quota_but_existing_queue_is_preserved(settings, video, monkeypatch):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings, 2)
    images(settings, 5)
    first = produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    monkeypatch.setattr('agent.thoremix.core.now_iso',lambda:(NOW+timedelta(days=1)).isoformat())
    second = produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW + timedelta(days=1))
    assert first['completed'] == second['completed'] == 2 and second['ready_count'] == 4


def test_global_provider_block_does_not_consume_images_or_fake_success(settings):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings)
    images(settings, 4)
    class Blocked:
        def __init__(self, _): pass
        def status(self): return {'automatic_story_ready': False}
        def run(self, _): pytest.fail('provider is not ready')
    result = produce_ahead(settings, producer_factory=Blocked, now=lambda: NOW)
    assert result['state'] == 'production_not_ready' and result['completed'] == 0
    assert Campaign(settings).jobs() == []


def test_slot_publishes_one_fifo_package_and_repeat_does_not_drain_queue(settings, video):
    from agent.thoremix.production_queue import produce_ahead, run_slot
    settings = ahead(settings, 3)
    images(settings, 3)
    produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    called = []
    def publisher(config, path):
        job = json.loads((path / 'package.json').read_text())['job_id']
        called.append(job)
        Campaign(config).update(job, 'published')
        return {'complete': True}
    first = run_slot(settings, '11:00', publisher=publisher, now=lambda: NOW)
    repeated = run_slot(settings, '11:00', publisher=publisher, now=lambda: NOW)
    assert first['state'] == repeated['state'] == 'published' and len(called) == 1
    assert first['job_id'] == repeated['job_id']
    run_slot(settings, '18:30', publisher=publisher, now=lambda: NOW)
    assert len(set(called)) == 2


def test_uncertain_publication_keeps_same_slot_job(settings, video):
    from agent.thoremix.production_queue import produce_ahead, run_slot
    settings = ahead(settings, 2)
    images(settings, 2)
    produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    called = []
    def uncertain(config, path):
        called.append(str(path))
        raise TimeoutError('post response unknown')
    first = run_slot(settings, '11:00', publisher=uncertain, now=lambda: NOW)
    second = run_slot(settings, '11:00', publisher=uncertain, now=lambda: NOW)
    assert first['state'] == second['state'] == 'publication_pending'
    assert len(set(called)) == 1


def test_settings_controls_work_while_clip_holds_runner(settings):
    from agent.thoremix.sdk import ThoRemixClient
    from agent.thoremix.core import runner_lock
    with runner_lock(settings.data):
        client = ThoRemixClient(settings.root)
        client.configure_production(mode='ahead', daily_limit=8)
        client.set_enabled(False)
    changed = Settings.load(settings.root)
    assert changed.production_mode == 'ahead' and changed.daily_production_limit == 8
    assert changed.enabled is False


def test_config_cli_saves_mode_and_quota_without_enabling_or_producing(settings, capsys):
    from agent.thoremix.cli import main
    replace(settings, enabled=False).save()
    assert main(['--root', settings.root, 'configure-production', '--mode', 'ahead', '--daily-limit', '5']) == 0
    assert json.loads(capsys.readouterr().out)['daily_production_limit'] == 5
    assert not Settings.load(settings.root).enabled
    assert Campaign(settings).jobs() == []


def test_one_source_is_one_story_package_never_combined_with_other_sources(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings, 2)
    images(settings, 2)
    produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    manifests = [json.loads(p.read_text()) for p in settings.output.glob('*/package.json')]
    assert len(manifests) == 2 and len({m['source_sha256'] for m in manifests}) == 2
    for manifest in manifests:
        assert manifest['story_contract'] == {'source_count': 1, 'output_clips': 1,
            'source_sha256': manifest['source_sha256'], 'join_other_stories': False}


def test_scheduled_mode_produces_and_publishes_one_story(settings, video):
    from agent.thoremix.production_queue import run_slot
    images(settings, 2)
    called = []
    def publisher(config, path):
        called.append(path)
        return {'complete': True}
    result = run_slot(settings, '11:00', producer_factory=factory(video), publisher=publisher, now=lambda: NOW)
    assert result['state'] == 'published' and len(called) == 1
    assert len(Campaign(settings).jobs()) == 1


def test_dispatch_only_catches_recent_slots_not_earlier_days(settings):
    from agent.thoremix.production_queue import due_slots
    assert due_slots(settings, NOW.replace(hour=11, minute=15)) == ['11:00']
    assert due_slots(settings, NOW.replace(hour=19, minute=1)) == []
    assert due_slots(settings, NOW.replace(hour=10, minute=59)) == []


@pytest.mark.parametrize('changes', [{'enabled': False}, {'production_mode': 'scheduled'}, {'daily_production_limit': 1}])
def test_controls_rechecked_after_provider_readiness_wait(settings, video, changes):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings, 2)
    images(settings, 3)
    base = factory(video)
    calls = 0
    class DelayedReadiness(base):
        def status(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                replace(Settings.load(settings.root), **changes).save()
            return super().status()
    result = produce_ahead(settings, producer_factory=DelayedReadiness, now=lambda: NOW)
    assert result['completed'] == 1 and len(Campaign(settings).jobs()) == 1


def test_generation_crossing_posting_slot_by_40_minutes_still_services_one_slot(settings, video):
    from agent.thoremix.production_queue import produce_ahead
    settings = ahead(settings, 1)
    images(settings, 2)
    current = [NOW.replace(hour=10, minute=59)]
    called = []
    result = produce_ahead(settings, producer_factory=factory(video,
        after=lambda: current.__setitem__(0, NOW.replace(hour=11, minute=40))),
        publisher=lambda config, path: called.append(path) or {'complete': True}, now=lambda: current[0])
    assert result['completed'] == 1 and result['ready_count'] == 0
    assert len(called) == 1


def test_scheduled_unknown_after_package_can_recover_and_publish_its_original_slot(settings, video):
    from agent.thoremix.production_queue import run_slot
    images(settings, 2)
    class Producer(factory(video)):
        def run(self, job_id):
            super().run(job_id)
            raise TimeoutError('response lost after local package')
    first = run_slot(settings, '11:00', producer_factory=Producer, now=lambda: NOW)
    assert first['state'] == 'reconciliation_required'
    called = []
    second = run_slot(settings, '11:00', producer_factory=lambda _: pytest.fail('no regeneration'),
        publisher=lambda config, path: called.append(path) or {'complete': True}, now=lambda: NOW)
    assert second['state'] == 'published' and second['job_id'] == first['job_id']
    assert len(called) == 1 and len(Campaign(settings).jobs()) == 1


def test_due_request_survives_busy_runner_past_grace_window(settings, video):
    from agent.thoremix.production_queue import produce_ahead, run_slot, dispatch
    from agent.thoremix.core import runner_lock, RunnerBusyError
    settings = ahead(settings, 1)
    images(settings, 1)
    produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    with runner_lock(settings.data):
        with pytest.raises(RunnerBusyError):
            run_slot(settings, '11:00', now=lambda: NOW.replace(hour=11))
    calls = []
    result = dispatch(settings, producer_factory=lambda _: pytest.fail('quota already filled'),
        publisher=lambda config, path: calls.append(path) or {'complete': True},
        now=lambda: NOW.replace(hour=11, minute=45))
    assert len(calls) == 1 and result['posting_slots'][0]['state'] == 'published'


def test_reserved_source_before_attempt_checkpoint_is_reused(settings, video):
    from agent.thoremix.production_queue import ProductionQueue, produce_ahead
    settings = ahead(settings, 1)
    images(settings, 2)
    queue = ProductionQueue(settings)
    job = queue.campaign.reserve('production/2026-09-27/interrupted-before-attempt')
    result = produce_ahead(settings, producer_factory=factory(video), now=lambda: NOW)
    assert result['completed'] == 1 and len(Campaign(settings).jobs()) == 1
    assert Campaign(settings).get(job['id'])['state'] == 'video_ready'


def test_recovered_story_from_yesterday_can_wait_for_todays_slot(settings, video):
    from agent.thoremix.production_queue import run_slot
    images(settings, 2)
    class Producer(factory(video)):
        def run(self, job_id):
            super().run(job_id)
            raise TimeoutError('response lost')
    first = run_slot(settings, '11:00', producer_factory=Producer, now=lambda: NOW)
    called = []
    second = run_slot(settings, '11:00', producer_factory=lambda _: pytest.fail('use recovered story'),
        publisher=lambda config, path: called.append(path) or {'complete': True}, now=lambda: NOW + timedelta(days=1))
    assert second['state'] == 'published' and second['job_id'] == first['job_id']
    assert len(Campaign(settings).jobs()) == len(called) == 1


def test_pending_credit_block_keeps_its_slot_and_cannot_bind_second_slot(settings, video):
    from agent.thoremix.production_queue import run_slot
    images(settings, 2)
    class NoCredit(factory(video)):
        def run(self, job_id): return {'state': 'no_credit'}
    first = run_slot(settings, '11:00', producer_factory=NoCredit, now=lambda: NOW)
    later = run_slot(settings, '18:30', producer_factory=lambda _: pytest.fail('resume original slot first'), now=lambda: NOW)
    assert first['state'] == 'no_credit' and later['state'] == 'waiting_previous_production'
    assert len(Campaign(settings).jobs()) == 1


def test_pending_quality_counts_toward_quota_but_never_publishes_until_exact_owner_approval(settings,video):
    from concurrent.futures import ThreadPoolExecutor
    from agent.thoremix.production_queue import ProductionQueue,produce_ahead,run_slot
    from agent.thoremix.quality import POLICY,manifest_digest,request_approval
    from agent.thoremix.core import campaign_operation
    from agent.thoremix.publishing import _manifest
    settings=ahead(settings,1);images(settings,2)
    class Pending(factory(video)):
        def run(self,job_id):
            self.campaign.finalize(job_id,video,children=[],metadata={
                'qa':{'release_ready':False,'production_complete':True,'policy':POLICY},
                'review':{'status':'pending','warnings':[{'stage':'video','result':{'accepted':False}}]}})
            return {'state':'awaiting_approval'}
    result=produce_ahead(settings,producer_factory=Pending,now=lambda:NOW)
    assert result['state']=='quota_reached' and result['completed']==1 and result['failed']==0
    assert result['awaiting_approval']==1 and result['ready_count']==0
    q=ProductionQueue(settings);job=q.campaign.jobs()[0]
    manifest=q.campaign.reconcile_package(job['id'])
    assert q.campaign.get(job['id'])['state']=='awaiting_approval'
    with pytest.raises(ValueError,match='chờ'):_manifest(Path(job['package_dir']))
    assert run_slot(settings,'11:00',now=lambda:NOW,publisher=lambda *_:pytest.fail('unapproved'))['state']=='queue_empty'
    digest=manifest_digest(manifest)
    # The real UI may receive the click while another thread owns production.
    with ThreadPoolExecutor(max_workers=1) as pool:
        with campaign_operation(settings):
            assert pool.submit(request_approval,settings,job['id'],digest).result(timeout=5)['state']=='approval_queued'
    q.recover(NOW)
    approved=q.campaign.reconcile_package(job['id'])
    assert approved['qa']['release_ready'] is True and approved['review']['status']=='approved'
    assert approved['review']['warnings']==manifest['review']['warnings']
    assert q.summary(NOW)['completed']==1 and q.summary(NOW)['ready_count']==1
    assert q.campaign.approve(job['id'],digest)==approved
    posted=run_slot(settings,'18:30',now=lambda:NOW,publisher=lambda *_:{'complete':True})
    assert posted['state']=='published' and posted['job_id']==job['id']


def test_scheduled_production_with_qa_warning_does_not_publish_new_clip(settings,video):
    from agent.thoremix.production_queue import run_slot,ProductionQueue
    from agent.thoremix.quality import POLICY
    images(settings,1)
    class Pending(factory(video)):
        def run(self,job_id):
            self.campaign.finalize(job_id,video,children=[],metadata={
                'qa':{'release_ready':False,'production_complete':True,'policy':POLICY},
                'review':{'status':'pending','warnings':[{'stage':'audio'}]}})
            return {'state':'awaiting_approval'}
    result=run_slot(settings,'11:00',producer_factory=Pending,now=lambda:NOW,publisher=lambda *_:pytest.fail('unapproved'))
    assert result['state']=='awaiting_approval'
    assert ProductionQueue(settings).summary(NOW)['completed']==1


def test_owner_click_at_production_finish_does_not_lose_completed_quota(settings,video):
    from agent.thoremix.production_queue import produce_ahead
    from agent.thoremix.quality import POLICY,manifest_digest,request_approval
    settings=ahead(settings,1);images(settings,1)
    class Pending(factory(video)):
        def run(self,job_id):
            package=self.campaign.finalize(job_id,video,children=[],metadata={
                'qa':{'release_ready':False,'production_complete':True,'policy':POLICY},
                'review':{'status':'pending','warnings':[{'stage':'audio'}]}})
            request_approval(settings,job_id,manifest_digest(package))
            return {'state':'awaiting_approval'}
    result=produce_ahead(settings,producer_factory=Pending,now=lambda:NOW)
    assert result['completed']==1 and result['ready_count']==1 and result['blocking_uncertain']==0


def test_resume_quality_stops_reuses_known_artifacts_and_keeps_unknown_isolated(settings):
    from agent.thoremix.production_queue import ProductionQueue
    from agent.thoremix.story_stages import StageJournal,StageRejected
    from agent.thoremix.story_operations import artifact
    images(settings,2);queue=ProductionQueue(settings)
    class Failed:
        def run(self,job_id):
            job=queue.campaign.get(job_id)
            journal=StageJournal(settings.data/'production'/job_id,source_sha256=job['source_sha256'])
            journal.run('analysis',{},lambda _:dict(state='verified',data={}))
            journal.run('images',{},lambda _:dict(state='verified',files=[artifact(Path(job['source']))]))
            with pytest.raises(StageRejected):
                journal.run('image_review',{},lambda _:dict(state='qa_failed',data={'accepted':False}))
            return {'state':'qa_failed','reason':'image_review'}
    _,job_id=queue.produce_one(NOW,Failed(),lambda:NOW)
    before=(settings.data/'production'/job_id/'images.json').read_bytes()
    result=queue.resume_quality_stops(NOW)
    assert result['job_ids']==[job_id] and result['count']==1
    assert queue.attempts()[0]['status']=='blocked'
    assert (settings.data/'production'/job_id/'images.json').read_bytes()==before
    assert queue.resume_quality_stops(NOW)['count']==0
