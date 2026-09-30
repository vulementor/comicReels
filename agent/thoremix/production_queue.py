"""Finite production batches and durable one-story publication slots; no AI loop."""
from __future__ import annotations

import json
import uuid
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings, atomic_json
from .core import Campaign, SourceExhausted, campaign_operation, root_operation, runner_lock
from .producer import FlowKitProducer

KNOWN_FAILURES = {'failed', 'qa_failed', 'invalid_source', 'production_failed'}
PRE_SUBMIT_BLOCKS = {'no_credit', 'credit_unknown', 'production_integration_pending', 'production_not_ready'}


def local_now(settings):
    return datetime.now(ZoneInfo(settings.timezone))


class ProductionQueue:
    def __init__(self, settings):
        self.settings = settings
        self.campaign = Campaign(settings)
        with campaign_operation(settings), self.campaign.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS production_attempts(
                job_id TEXT PRIMARY KEY REFERENCES jobs(id), started_day TEXT NOT NULL,
                started_at TEXT NOT NULL, status TEXT NOT NULL, completed_day TEXT,
                completed_at TEXT, reason TEXT NOT NULL DEFAULT '')''')
            db.execute('''CREATE TABLE IF NOT EXISTS publication_slots(
                slot TEXT PRIMARY KEY, job_id TEXT, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}')''')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_slot_per_story ON publication_slots(job_id) WHERE job_id IS NOT NULL')

    def attempts(self):
        with self.campaign.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM production_attempts ORDER BY started_at, job_id')]

    def finish(self, job_id, state, stamp, reason=''):
        with self.campaign.connect() as db:
            db.execute('UPDATE production_attempts SET status=?,completed_day=?,completed_at=?,reason=? WHERE job_id=?',
                (state, stamp.date().isoformat() if state == 'complete' else None,
                 stamp.isoformat(), reason, job_id))

    def cooldown_remaining(self, stamp):
        failed = [datetime.fromisoformat(a['completed_at']) for a in self.attempts()
                  if a['status'] in {'failed','quarantined'} and a.get('completed_at')]
        return max(0, 60 - (stamp - max(failed)).total_seconds()) if failed else 0

    def quarantine_preflow(self, job_id, stamp):
        """Explicit operator action: isolate an unresolved image turn, never replay it."""
        with campaign_operation(self.settings):
            return self._quarantine_preflow(job_id, stamp)

    def _quarantine_preflow(self, job_id, stamp):
        from .core import sha256
        job = self.campaign.get(job_id)
        attempt = next(a for a in self.attempts() if a['job_id'] == job_id)
        directory = self.settings.data/'production'/job_id
        stage = directory/'images.json'
        record = json.loads(stage.read_text(encoding='utf-8'))
        forbidden = ['image_review.json','video.json','video_review.json','highest.json','audio.json',
                     'copy.json','affiliate.json','flow']
        if (attempt['status'] != 'unknown' or record.get('state') != 'UNKNOWN'
                or record.get('source_sha256') != job['source_sha256']
                or sha256(Path(job['source'])) != job['source_sha256']
                or any((directory/name).exists() for name in forbidden)
                or (Path(job['package_dir'])/'package.json').exists()):
            raise ValueError('PRE_FLOW_QUARANTINE_NOT_ELIGIBLE')
        audit = directory/'quarantine.json'
        if audit.exists():
            raise ValueError('QUARANTINE_ALREADY_RECORDED')
        atomic_json(audit, {'job_id':job_id,'source_sha256':job['source_sha256'],
            'images_receipt_sha256':sha256(stage),'recorded_at':stamp.isoformat(),
            'reason':'Unresolved image submission isolated; no downstream intent. Never auto-resume or resubmit.',
            'attempt_before':attempt,'job_before':job})
        self.finish(job_id,'quarantined',stamp,'image_submission_awaiting_reconciliation')
        self.campaign.update(job_id,'production_quarantined',production_stage='images')

    def resume_quality_stops(self, stamp):
        """Owner-requested policy migration; reuse verified images and existing video."""
        from .core import sha256
        from .story_stages import StageJournal
        resumed=[]
        with campaign_operation(self.settings):
            for attempt in self.attempts():
                if attempt['status']!='failed':continue
                job=self.campaign.get(attempt['job_id'])
                directory=self.settings.data/'production'/job['id']
                records={name:json.loads((directory/(name+'.json')).read_text(encoding='utf-8'))
                         for name in ('analysis','images','image_review','video_review','audio')
                         if (directory/(name+'.json')).is_file()}
                failed=[name for name in ('image_review','video_review','audio')
                        if records.get(name,{}).get('state')=='FAILED'
                        and records[name].get('result',{}).get('state')=='qa_failed']
                if not failed or any(records.get(name,{}).get('state')!='COMPLETED' for name in ('analysis','images')):
                    continue
                if sha256(Path(job['source']))!=job['source_sha256']:
                    raise ValueError('Ảnh nguồn đã đổi; không tiếp tục tự động.')
                for name in ('analysis','images'):
                    if records[name]['source_sha256']!=job['source_sha256']:
                        raise ValueError('Biên nhận ảnh không khớp truyện.')
                    StageJournal._validate_files(records[name]['result'])
                audit=directory/'advisory-resume.json'
                if not audit.exists():atomic_json(audit,{'recorded_at':stamp.isoformat(),
                    'reason':'Owner changed content QA to advisory with manual publication approval.',
                    'job_before':job,'attempt_before':attempt,'quality_stages':failed})
                self.finish(job['id'],'blocked',stamp,'owner_advisory_policy_resume_existing_assets')
                self.campaign.update(job['id'],'production_pending',production_stage=failed[0])
                resumed.append(job['id'])
        return {'state':'quality_stops_resumed','job_ids':resumed,'count':len(resumed)}

    def recover(self, stamp):
        from .finishing import recover_pending
        for job in self.campaign.jobs():recover_pending(self.campaign,job['id'])
        from .quality import apply_approvals
        apply_approvals(self.campaign)
        with self.campaign.connect() as db:
            orphans = db.execute("""SELECT * FROM jobs WHERE slot LIKE 'production/%'
                AND id NOT IN (SELECT job_id FROM production_attempts)""").fetchall()
            for job in orphans:
                started = datetime.fromisoformat(job['created_at']).astimezone(ZoneInfo(self.settings.timezone))
                db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status,reason) VALUES(?,?,?,?,?)',
                           (job['id'], started.date().isoformat(), job['created_at'],
                            'blocked' if job['state'] == 'reserved' else 'unknown', 'interrupted_before_attempt_checkpoint'))
            # A generation-only slot from yesterday cannot publish retroactively. Its story
            # may enter today's queue after reconciliation; no social effect existed here.
            for row in db.execute("SELECT * FROM publication_slots WHERE state='production_pending' AND substr(slot,1,10)<?",
                                  (stamp.date().isoformat(),)).fetchall():
                previous = json.loads(row['result'])
                previous.update(state='expired_production_slot', job_id=row['job_id'])
                db.execute("UPDATE publication_slots SET job_id=NULL,state='expired',result=? WHERE slot=?",
                           (json.dumps(previous), row['slot']))
                _slot_requests(self.settings, remove=row['slot'])
        for attempt in self.attempts():
            if attempt['status'] not in {'running', 'unknown', 'blocked'}:
                continue
            job = self.campaign.get(attempt['job_id'])
            path = Path(job['package_dir']) / 'package.json'
            if path.is_file():
                try:
                    package = self.campaign.reconcile_package(job['id'])
                    self.validate_story(package, job)
                    completed = datetime.fromisoformat(package['created_at']).astimezone(ZoneInfo(self.settings.timezone))
                    receipt = self.settings.data/'production'/job['id']/'flow/story-receipt.json'
                    if receipt.is_file() and package.get('qa',{}).get('release_ready') is True:
                        from .finishing import complete_story_receipt
                        complete_story_receipt(self.settings,job['id'],path)
                    self.finish(job['id'], 'complete', completed)
                    continue
                except (OSError, ValueError, KeyError):
                    self.finish(job['id'], 'unknown', stamp, 'package_reconciliation_failed')
            elif attempt['status'] == 'running':
                self.finish(job['id'], 'unknown', stamp, 'interrupted_production')

    @staticmethod
    def validate_story(package, job):
        expected = {'source_count': 1, 'output_clips': 1,
                    'source_sha256': job['source_sha256'], 'join_other_stories': False}
        from .quality import package_state
        package_state(package)
        if package.get('story_contract') != expected:
            raise ValueError('Unverified one-source story package')

    def summary(self, stamp, *, state='idle', reason=None):
        day = stamp.date().isoformat()
        attempts = self.attempts()
        errors = []
        for attempt in attempts:
            if attempt['started_day'] == day and attempt['status'] in {'failed', 'unknown', 'blocked','quarantined'}:
                job = self.campaign.get(attempt['job_id'])
                errors.append({'job_id': job['id'], 'source': job['source'],
                               'state': attempt['status'], 'reason': attempt['reason'],
                               'recorded_at': attempt['completed_at']})
        with self.campaign.connect() as db:
            input_errors = [dict(row) for row in db.execute('SELECT * FROM source_errors ORDER BY observed_at DESC')]
        jobs = self.campaign.jobs()
        return {'state': state, 'reason': reason, 'day': day,
                'mode': self.settings.production_mode, 'limit': self.settings.daily_production_limit,
                'completed': sum(a['status'] == 'complete' and a['completed_day'] == day for a in attempts),
                'failed': sum(a['status'] == 'failed' and a['started_day'] == day for a in attempts),
                'uncertain': sum(a['status'] in {'running', 'unknown','quarantined'} for a in attempts),
                'blocking_uncertain': sum(a['status'] in {'running','unknown'} for a in attempts),
                'retry_after_s': self.cooldown_remaining(stamp),
                'ready_count': sum(j['state'] == 'video_ready' for j in jobs),
                'awaiting_approval': sum(j['state']=='awaiting_approval' for j in jobs),
                'errors': errors, 'input_errors': input_errors,
                'report_path': str(self.settings.data / 'reports' / 'production' / f'{day}.json')}

    def report(self, stamp, **fields):
        result = self.summary(stamp, **fields)
        atomic_json(Path(result['report_path']), result)
        atomic_json(self.settings.data / 'production-status.json', result)
        return result

    def produce_one(self, stamp, producer, now, *, resume_job_id=None, ignore_cooldown=False):
        if not ignore_cooldown and self.cooldown_remaining(stamp) > 0:
            return 'failure_cooldown', None
        blocked = next((a for a in self.attempts() if a['status'] == 'blocked'
                        and (resume_job_id is None or a['job_id'] == resume_job_id)), None)
        if resume_job_id is not None and blocked is None:
            raise ValueError('Công việc được chỉ định không ở trạng thái chờ tiếp tục.')
        if blocked:
            job = self.campaign.get(blocked['job_id'])
            with self.campaign.connect() as db:
                db.execute("UPDATE production_attempts SET status='running',reason='' WHERE job_id=?", (job['id'],))
        else:
            job = self.campaign.reserve(f'production/{stamp.date().isoformat()}/{uuid.uuid4().hex}')
            with self.campaign.connect() as db:
                db.execute('INSERT INTO production_attempts(job_id,started_day,started_at,status) VALUES(?,?,?,?)',
                           (job['id'], stamp.date().isoformat(), stamp.isoformat(), 'running'))
        self.report(stamp, state='producing')
        try:
            result = producer.run(job['id'])
        except Exception as exc:
            self.finish(job['id'], 'unknown', now(), type(exc).__name__)
            return 'reconciliation_required', job['id']
        from .quality import apply_approvals
        apply_approvals(self.campaign)
        current = self.campaign.get(job['id'])
        if (result.get('state') in {'video_ready','awaiting_approval'}
                and current['state'] in {'video_ready','awaiting_approval'}):
            try:
                package = self.campaign.reconcile_package(job['id'])
                self.validate_story(package, job)
                completed = datetime.fromisoformat(package['created_at']).astimezone(ZoneInfo(self.settings.timezone))
                self.finish(job['id'], 'complete', completed)
                return 'complete', job['id']
            except (OSError, ValueError, KeyError):
                self.finish(job['id'], 'unknown', now(), 'package_validation_failed')
                return 'reconciliation_required', job['id']
        state = result.get('state')
        if state in KNOWN_FAILURES:
            stage = result.get('reason')
            reason = state + ':' + stage if stage in {'analysis','images','image_review','video','video_review',
                                                      'highest','audio','copy','affiliate'} else state
            self.finish(job['id'], 'failed', now(), reason)
            self.campaign.update(job['id'], 'production_failed', production_error=state)
            return 'failed', job['id']
        if state in PRE_SUBMIT_BLOCKS:
            self.finish(job['id'], 'blocked', now(), state)
            return state, job['id']
        self.finish(job['id'], 'unknown', now(), 'unverified_production_result')
        return 'reconciliation_required', job['id']

    def reconcile_unknown(self, producer, now):
        unresolved = [a for a in self.attempts() if a['status'] == 'unknown']
        if len(unresolved) != 1:
            return self.report(now(), state='reconciliation_required' if unresolved else 'idle')
        job_id = unresolved[0]['job_id']
        self.report(now(), state='producing', reason='reconciling_saved_story')
        result = producer.reconcile(job_id)
        if result.get('state') in {'video_ready','awaiting_approval'}:
            job = self.campaign.get(job_id)
            package = self.campaign.reconcile_package(job_id)
            self.validate_story(package, job)
            completed = datetime.fromisoformat(package['created_at']).astimezone(ZoneInfo(self.settings.timezone))
            self.finish(job_id, 'complete', completed)
        elif result.get('state') in PRE_SUBMIT_BLOCKS:
            self.finish(job_id, 'blocked', now(), result['state'])
        elif result.get('state') in KNOWN_FAILURES:
            self.finish(job_id, 'failed', now(), result['state'])
            self.campaign.update(job_id, 'production_failed', production_error=result['state'])
        return self.report(now(), state=result.get('state','reconciliation_required'))


def _latest(settings):
    return Settings.load(settings.directory) if settings.path.exists() else settings


def _slot_requests(settings, *, add=None, remove=None):
    # Intent control is independent of the media/browser runner, like the pause control.
    # A Windows posting trigger can persist its due slot even while a clip owns that runner.
    with root_operation(settings.data / 'slot-control'):
        path = settings.data / 'slot-requests.json'
        entries = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if add is not None:
            entries[add] = True
        if remove is not None:
            entries.pop(remove, None)
        if add is not None or remove is not None:
            atomic_json(path, entries)
        return entries


def pending_slots(settings, stamp):
    entries = _slot_requests(settings)
    return [clock for clock in settings.slots if f'{stamp:%Y-%m-%d}/{clock}' in entries]


def _close_producer(producer):
    close = getattr(producer, 'close', None)
    if callable(close):
        close()


def produce_ahead(settings, *, producer_factory=FlowKitProducer, now=None, publisher=None, sleep=time.sleep):
    now = now or (lambda: local_now(settings))
    day = now().date()
    serviced = set()
    last_check = now()
    def service_slots(current, stamp):
        nonlocal last_check
        crossed = []
        if stamp.date() == last_check.date():
            crossed = [clock for clock in current.slots
                       if last_check.strftime('%H:%M') < clock <= stamp.strftime('%H:%M')]
        if current.enabled:
            for clock in sorted(set(due_slots(current, stamp) + pending_slots(current, stamp) + crossed)):
                if clock not in serviced:
                    run_slot(current, clock, now=now, publisher=publisher)
                    serviced.add(clock)
        last_check = stamp
    with runner_lock(settings.data / 'production-batch'):
        while True:
            settings = _latest(settings)
            stamp = now()
            with campaign_operation(settings):
                queue = ProductionQueue(settings)
                queue.recover(stamp)
                report = queue.summary(stamp)
                if not settings.enabled:
                    return queue.report(stamp, state='paused')
                if settings.production_mode != 'ahead':
                    return queue.report(stamp, state='scheduled_mode')
                if stamp.date() != day:
                    return queue.report(stamp, state='day_changed')
                service_slots(settings, stamp)
                if report['blocking_uncertain']:
                    producer = producer_factory(queue.campaign)
                    try:
                        if callable(getattr(producer, 'reconcile', None)):
                            queue.reconcile_unknown(producer, now)
                            if not queue.summary(now())['blocking_uncertain']:
                                continue
                    finally:
                        _close_producer(producer)
                    return queue.report(stamp, state='reconciliation_required')
                if report['completed'] >= settings.daily_production_limit:
                    return queue.report(stamp, state='quota_reached')
                remaining = queue.cooldown_remaining(stamp)
                if remaining > 0:
                    queue.report(stamp, state='failure_cooldown')
                    sleep(min(5, remaining))
                    continue
                producer = producer_factory(queue.campaign)
                try:
                    try:
                        readiness = producer.status()
                    except Exception:
                        return queue.report(stamp, state='production_not_ready', reason='provider_status_failed')
                    # Publication/status may have waited while the user changed controls.
                    # Re-enter the loop before reserving any source under stale controls.
                    if _latest(settings) != settings or now().date() != stamp.date():
                        continue
                    if not readiness.get('automatic_story_ready'):
                        return queue.report(stamp, state='production_not_ready', reason='automatic_story_not_ready')
                    try:
                        state, _ = queue.produce_one(stamp, producer, now)
                    except SourceExhausted:
                        return queue.report(stamp, state='source_exhausted')
                finally:
                    _close_producer(producer)
                service_slots(_latest(settings), now())
                queue.report(now(), state='producing' if state in {'complete', 'failed'} else state)
                if state not in {'complete', 'failed'}:
                    return queue.report(now(), state=state)
            # Campaign lease is released between clips; the batch lease prevents a second producer.


def run_slot(settings, clock=None, *, producer_factory=FlowKitProducer, publisher=None, now=None):
    if clock is not None and clock not in settings.slots:
        raise ValueError('Giờ chạy không thuộc lịch đã cấu hình.')
    now = now or (lambda: local_now(settings))
    stamp = now()
    slot = f'{stamp:%Y-%m-%d}/{clock}' if clock else f'manual/{stamp:%Y-%m-%dT%H:%M}'
    if not settings.enabled:
        return {'state': 'paused'}
    if clock:
        _slot_requests(settings, add=slot)
    with campaign_operation(settings):
        settings = _latest(settings)
        if not settings.enabled:
            return {'state': 'paused'}
        queue = ProductionQueue(settings)
        queue.recover(stamp)
        if settings.production_mode == 'scheduled' and queue.summary(stamp)['uncertain']:
            producer = producer_factory(queue.campaign)
            try:
                if callable(getattr(producer, 'reconcile', None)):
                    queue.reconcile_unknown(producer, now)
            finally:
                _close_producer(producer)
        with queue.campaign.connect() as db:
            existing = db.execute('SELECT * FROM publication_slots WHERE slot=?', (slot,)).fetchone()
            if existing and existing['state'] in {'published', 'empty', 'failed'}:
                if clock:
                    _slot_requests(settings, remove=slot)
                return json.loads(existing['result'])
            job = queue.campaign.get(existing['job_id']) if existing and existing['job_id'] else None
            pending_retry = False
            if (job and existing['state'] == 'production_pending'
                    and job['state'] not in {'video_ready','awaiting_approval'}):
                attempt = next(a for a in queue.attempts() if a['job_id'] == job['id'])
                pending_retry = attempt['status'] == 'blocked' and settings.production_mode == 'scheduled'
                if not pending_retry:
                    return {'state': 'reconciliation_required', 'slot': slot, 'job_id': job['id']}
            if not job:
                row = db.execute("""SELECT * FROM jobs WHERE state='video_ready'
                    AND id NOT IN (SELECT job_id FROM publication_slots WHERE job_id IS NOT NULL)
                    ORDER BY created_at,id LIMIT 1""").fetchone()
                job = dict(row) if row else None
        if (not job or pending_retry) and settings.production_mode == 'scheduled':
            if queue.summary(stamp)['blocking_uncertain']:
                return queue.report(stamp, state='reconciliation_required')
            if not pending_retry:
                with queue.campaign.connect() as db:
                    prior = db.execute("""SELECT p.job_id FROM publication_slots p JOIN production_attempts a
                        ON a.job_id=p.job_id WHERE p.state='production_pending' AND a.status='blocked'
                        AND p.slot<>? LIMIT 1""", (slot,)).fetchone()
                if prior:
                    return {'state': 'waiting_previous_production', 'slot': slot, 'job_id': prior['job_id']}
            producer = producer_factory(queue.campaign)
            try:
                readiness = producer.status()
                if _latest(settings) != settings:
                    return {'state': 'controls_changed', 'slot': slot}
                if not readiness.get('automatic_story_ready'):
                    return queue.report(stamp, state='production_not_ready', reason='automatic_story_not_ready')
                try:
                    state, job_id = queue.produce_one(stamp, producer, now, resume_job_id=job['id'] if pending_retry else None)
                except SourceExhausted:
                    state, job_id = 'source_exhausted', None
            finally:
                _close_producer(producer)
            if state != 'complete':
                result = {'state': state, 'slot': slot, 'job_id': job_id}
                with queue.campaign.connect() as db:
                    db.execute('INSERT OR REPLACE INTO publication_slots VALUES(?,?,?,?)',
                               (slot, job_id, 'failed' if state in {'failed', 'source_exhausted'} else 'production_pending', json.dumps(result)))
                if state in {'failed', 'source_exhausted'} and clock:
                    _slot_requests(settings, remove=slot)
                return result
            job = queue.campaign.get(job_id)
        if not job:
            result = {'state': 'queue_empty', 'slot': slot}
            with queue.campaign.connect() as db:
                db.execute('INSERT OR REPLACE INTO publication_slots VALUES(?,?,?,?)', (slot, None, 'empty', json.dumps(result)))
            if clock:
                _slot_requests(settings, remove=slot)
            return result
        if job['state'] in {'video_ready','awaiting_approval'}:
            package = queue.campaign.reconcile_package(job['id'])
            from .media_correction import correction_approval_valid
            if isinstance(package.get('correction'), dict) and not correction_approval_valid(
                    settings, job['id'], package):
                if job['state'] != 'awaiting_approval':
                    queue.campaign.update(job['id'], 'awaiting_approval',
                                          correction_approval_required=True)
                    job = queue.campaign.get(job['id'])
                result={'state':'awaiting_correction_approval','slot':slot,'job_id':job['id']}
                with queue.campaign.connect() as db:
                    db.execute('INSERT OR REPLACE INTO publication_slots VALUES(?,?,?,?)',
                               (slot,None,'empty',json.dumps(result)))
                if clock:_slot_requests(settings,remove=slot)
                return result
        if job['state']=='awaiting_approval':
            result={'state':'awaiting_approval','slot':slot,'job_id':job['id']}
            with queue.campaign.connect() as db:
                # A pending review never holds a posting slot or publishes later
                # outside a fresh authorized schedule selection.
                db.execute('INSERT OR REPLACE INTO publication_slots VALUES(?,?,?,?)',
                           (slot,None,'empty',json.dumps(result)))
            if clock:_slot_requests(settings,remove=slot)
            return result
        with queue.campaign.connect() as db:
            db.execute('INSERT OR REPLACE INTO publication_slots VALUES(?,?,?,?)', (slot, job['id'], 'publishing', '{}'))
        if not _latest(settings).enabled:
            return {'state': 'paused', 'slot': slot, 'job_id': job['id']}
        queue.campaign.update(job['id'], 'publishing')
        if publisher is None:
            from .cli import publish
            publisher = publish
        try:
            receipt = publisher(settings, Path(job['package_dir']))
        except Exception as exc:
            receipt = {'complete': False, 'error_type': type(exc).__name__}
        result = {'state': 'published' if receipt.get('complete') is True else 'publication_pending',
                  'slot': slot, 'job_id': job['id'], 'publication': receipt}
        with queue.campaign.connect() as db:
            db.execute('UPDATE publication_slots SET state=?,result=? WHERE slot=?',
                       (result['state'], json.dumps(result, ensure_ascii=False), slot))
        queue.campaign.update(job['id'], 'published' if result['state'] == 'published' else 'publishing')
        queue.report(now(), state='waiting_schedule' if result['state'] == 'published' else 'publication_pending')
        if result['state'] == 'published' and clock:
            _slot_requests(settings, remove=slot)
        return result


def due_slots(settings, stamp):
    minute = stamp.hour * 60 + stamp.minute
    return [clock for clock in sorted(settings.slots)
            if 0 <= minute - sum(int(v) * m for v, m in zip(clock.split(':'), (60, 1))) <= 30]


def dispatch(settings, *, now=None, producer_factory=FlowKitProducer, publisher=None):
    now = now or (lambda: local_now(settings))
    settings = _latest(settings)
    if not settings.enabled:
        return {'state': 'paused'}
    posts = [run_slot(settings, clock, now=now, producer_factory=producer_factory, publisher=publisher)
             for clock in sorted(set(due_slots(settings, now()) + pending_slots(settings, now())))]
    if settings.production_mode == 'ahead':
        result = produce_ahead(settings, now=now, producer_factory=producer_factory, publisher=publisher)
        return result | {'posting_slots': posts}
    return {'state': 'scheduled_mode', 'posting_slots': posts}
