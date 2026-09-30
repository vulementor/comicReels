from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import Settings, atomic_json, change_settings
from .core import Campaign, RunnerBusyError, campaign_operation, root_operation
from .producer import FlowKitProducer


def status(settings: Settings, *, probe: bool = False) -> dict:
    campaign = Campaign(settings)
    rows = campaign.jobs()
    result = {'root': settings.root, 'input_dir': settings.input_dir, 'output_dir': str(settings.output),
              'enabled': settings.enabled, 'slots': settings.slots, 'timezone': settings.timezone,
              'production_mode': settings.production_mode, 'daily_production_limit': settings.daily_production_limit,
              'social_profile': str(settings.data / 'krp' / 'profiles' / settings.social_profile / 'browser'),
              'affiliate_profile': settings.affiliate_profile_dir,
              'affiliate_selection': {'max_price_vnd': settings.affiliate_max_price,
                                      'min_observed_sold': settings.affiliate_min_sold,
                                      'priority': 'commission_percentage'},
              'ai_provider': settings.ai_provider,
              'jobs': rows}
    auth_path = settings.data / 'auth-status.json'
    if auth_path.is_file():
        try:
            auth = json.loads(auth_path.read_text(encoding='utf-8'))
            if isinstance(auth, dict) and auth.get('profile') == settings.social_profile:
                result['last_auth_check'] = auth
        except (OSError, ValueError):
            pass
    if probe:
        result['flowkit'] = FlowKitProducer(campaign).status()
    return result


def publish(settings: Settings, package: Path) -> dict:
    with campaign_operation(settings):
        return _publish(settings, package)


def _publish(settings: Settings, package: Path, *, only_platforms=None,
             stop_after_publication: bool = False) -> dict:
    from .publishing import publish_package

    if not settings.publication_authorized:
        raise ValueError('Chưa có quyền đăng cho chiến dịch này.')
    package = package.resolve(strict=True)
    if package.parent != settings.output.resolve():
        raise ValueError('Chỉ đăng hồ sơ trong thư mục video của chiến dịch.')
    manifest = json.loads((package / 'package.json').read_text(encoding='utf-8'))
    campaign = Campaign(settings)
    try:
        job = campaign.get(manifest.get('job_id', ''))
    except KeyError:
        raise ValueError('Hồ sơ chưa gắn với công việc của chiến dịch này.') from None
    if (Path(job['package_dir']).resolve() != package
            or job['source_sha256'] != manifest.get('source_sha256')):
        raise ValueError('Hồ sơ không khớp công việc và ảnh nguồn đã giữ chỗ.')
    if job['state'] == 'wrong_media_blocked':
        raise ValueError('Clip này đã bị loại vì chọn sai bản; cần hoàn tất hồ sơ AI thay thế.')
    from .media_correction import correction_approval_valid
    if isinstance(manifest.get('correction'), dict) and not correction_approval_valid(settings, job['id'], manifest):
        raise ValueError('Correction revision đang chờ anh duyệt trước khi được phép đăng.')
    from .finishing import recover_pending,complete_story_receipt
    recover_pending(campaign,job['id'])
    manifest=json.loads((package/'package.json').read_text(encoding='utf-8'))
    from .quality import package_state
    if package_state(manifest)!='video_ready':
        raise ValueError('Clip có cảnh báo QA đang chờ anh duyệt trước khi đăng.')
    complete_story_receipt(settings,job['id'],package/'package.json')
    campaign.update(job['id'], 'publishing')
    report = publish_package(
        package, krp_home=settings.data / 'krp', profile=settings.social_profile,
        tool_root=settings.directory, only_platforms=only_platforms,
        stop_after_publication=stop_after_publication)
    campaign.update(job['id'], 'published' if report.get('complete') is True else 'publishing', publication=report)
    return report


def tick(settings: Settings, clock: str | None = None) -> dict:
    from .production_queue import run_slot
    return run_slot(settings, clock)


def main(argv=None) -> int:
    # Windows launchers may inherit a legacy console code page. A successful
    # UTF-8 operation must not be reported as failed only because diagnostics
    # contain Vietnamese characters.
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
        except (AttributeError, ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(description='Thỏ Remix — FlowKit + KRP stable controller')
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('THOREMIX_ROOT', 'D:/StableApp/ThoRemix')))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    commands.add_parser('desktop')
    s = commands.add_parser('status')
    s.add_argument('--probe', action='store_true')
    commands.add_parser('login')
    commands.add_parser('auth-status')
    commands.add_parser('affiliate')
    fb = commands.add_parser('configure-facebook')
    fb.add_argument('--name', required=True)
    commands.add_parser('pause')
    commands.add_parser('resume')
    commands.add_parser('produce-ahead')
    one=commands.add_parser('produce-one')
    one.add_argument('--job-id')
    commands.add_parser('reconcile-production')
    commands.add_parser('resume-quality-stops')
    retry=commands.add_parser('retry-production')
    retry.add_argument('job_id')
    commands.add_parser('retry-failed')
    commands.add_parser('finish-unpublished')
    repair_audio=commands.add_parser('repair-audio')
    repair_audio.add_argument('job_id')
    repair_audio.add_argument('--force',action='store_true')
    repair_all=commands.add_parser('repair-audio-all')
    repair_all.add_argument('--force',action='store_true')
    repair_text=commands.add_parser('repair-source-text')
    repair_text.add_argument('job_id')
    repair_text.add_argument('--spec',type=Path,required=True)
    correction=commands.add_parser('prepare-media-correction')
    correction.add_argument('job_id')
    correction_approval=commands.add_parser('approve-correction')
    correction_approval.add_argument('job_id')
    correction_approval.add_argument('--manifest-sha256',required=True)
    cleanup_tiktok=commands.add_parser('cleanup-tiktok-stale-editor')
    cleanup_tiktok.add_argument('current_job_id')
    cleanup_tiktok.add_argument('stale_job_id')
    approval=commands.add_parser('approve')
    approval.add_argument('job_id')
    approval.add_argument('--manifest-sha256',required=True)
    commands.add_parser('dispatch')
    production = commands.add_parser('configure-production')
    production.add_argument('--mode', required=True, choices=('scheduled', 'ahead'))
    production.add_argument('--daily-limit', required=True, type=int)
    run = commands.add_parser('tick')
    run.add_argument('--clock')
    imp = commands.add_parser('import-source')
    imp.add_argument('--slot', required=True)
    rec = commands.add_parser('reconcile-package')
    rec.add_argument('job_id')
    pub = commands.add_parser('publish')
    pub.add_argument('package', type=Path)
    single_pub = commands.add_parser('publish-platform')
    single_pub.add_argument('package', type=Path)
    single_pub.add_argument('--platform', required=True, choices=('facebook','tiktok','youtube'))
    single_pub.add_argument('--stop-after-publication', action='store_true')
    final = commands.add_parser('finalize')
    final.add_argument('job_id')
    final.add_argument('--video', type=Path, required=True)
    final.add_argument('--metadata', type=Path, required=True)
    final.add_argument('--frame', type=Path, action='append', default=[])
    prepare = commands.add_parser('prepare-package')
    prepare.add_argument('--slot', required=True)
    prepare.add_argument('--source', type=Path, required=True)
    prepare.add_argument('--video', type=Path, required=True)
    prepare.add_argument('--metadata', type=Path, required=True)
    prepare.add_argument('--frame', type=Path, action='append', default=[])
    args = parser.parse_args(argv)
    try:
        if args.command=='retry-production':
            from .retry import retry_story
            result=retry_story(Settings.load(args.root),args.job_id)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='retry-failed':
            from .retry import retry_failed
            result=retry_failed(Settings.load(args.root))
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='repair-audio':
            from .audio_repair import repair_audio
            result=repair_audio(Settings.load(args.root),args.job_id,force=args.force)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='repair-audio-all':
            from .audio_repair import repair_all_finished
            result=repair_all_finished(Settings.load(args.root),force=args.force)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='repair-source-text':
            from .text_repair import repair_source_text_from_file
            result=repair_source_text_from_file(Settings.load(args.root),args.job_id,args.spec)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='prepare-media-correction':
            from .media_correction import prepare_media_correction
            result=prepare_media_correction(Settings.load(args.root),args.job_id)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='approve-correction':
            from .media_correction import approve_media_correction
            result=approve_media_correction(Settings.load(args.root),args.job_id,args.manifest_sha256)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='cleanup-tiktok-stale-editor':
            from .social_cleanup import cleanup_tiktok_stale_editor
            result=cleanup_tiktok_stale_editor(
                Settings.load(args.root),args.current_job_id,args.stale_job_id)
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command=='approve':
            from .quality import request_approval,apply_approvals
            settings=Settings.load(args.root)
            result=request_approval(settings,args.job_id,args.manifest_sha256)
            try:
                with campaign_operation(settings):
                    campaign=Campaign(settings)
                    apply_approvals(campaign)
                    result['state']=campaign.get(args.job_id)['state']
                    saved=json.loads((settings.data/'review-requests'/(args.job_id+'.json')).read_text(encoding='utf-8'))
                    if saved.get('state')=='rejected':
                        result['state']='approval_rejected'
            except RunnerBusyError:
                pass
            print(json.dumps(result,ensure_ascii=False))
            return 0
        if args.command in {'configure-production', 'pause', 'resume'}:
            changes = ({'production_mode': args.mode, 'daily_production_limit': args.daily_limit}
                       if args.command == 'configure-production' else {'enabled': args.command == 'resume'})
            settings = change_settings(args.root, **changes)
            print(json.dumps({'state': 'configured', 'enabled': settings.enabled,
                'production_mode': settings.production_mode, 'daily_production_limit': settings.daily_production_limit},
                ensure_ascii=False))
            return 0
        if args.command in {'produce-ahead', 'dispatch', 'tick'}:
            from .production_queue import produce_ahead, dispatch
            settings = Settings.load(args.root)
            result = tick(settings, args.clock) if args.command == 'tick' else (
                produce_ahead if args.command == 'produce-ahead' else dispatch)(settings)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == 'desktop':
            settings = Settings.load(args.root)
            from .desktop import run_desktop
            run_desktop(settings)
            return 0
        if args.command == 'status':
            settings = Settings.load(args.root)
            result = status(settings, probe=getattr(args, 'probe', False))
            print(json.dumps(result, ensure_ascii=False, default=str))
            return 0
        with root_operation(args.root.resolve() / 'data'):
            settings = Settings.load(args.root, create=args.command == 'init')
            with campaign_operation(settings):
                if args.command == 'init':
                    result = status(settings, probe=False)
                elif args.command == 'login':
                    from .publishing import login
                    login(krp_home=settings.data / 'krp', profile=settings.social_profile)
                    result = {'state': 'login_closed'}
                elif args.command in {'produce-one', 'reconcile-production'}:
                    from .production_queue import ProductionQueue, local_now
                    queue = ProductionQueue(settings)
                    queue.recover(local_now(settings))
                    producer = FlowKitProducer(queue.campaign)
                    try:
                        if args.command == 'reconcile-production':
                            result = queue.reconcile_unknown(producer, lambda: local_now(settings))
                        elif queue.summary(local_now(settings))['blocking_uncertain']:
                            result = {'state':'reconciliation_required'}
                        else:
                            state, job_id = queue.produce_one(local_now(settings), producer, lambda: local_now(settings),resume_job_id=args.job_id)
                            result = queue.report(local_now(settings), state=state) | {'job_id':job_id}
                    finally:
                        producer.close()
                elif args.command=='resume-quality-stops':
                    from .production_queue import ProductionQueue,local_now
                    result=ProductionQueue(settings).resume_quality_stops(local_now(settings))
                elif args.command=='finish-unpublished':
                    from .finishing import apply_unpublished
                    result=apply_unpublished(settings)
                elif args.command == 'auth-status':
                    from .publishing import auth_status
                    result = auth_status(krp_home=settings.data / 'krp', profile=settings.social_profile)
                    atomic_json(settings.data / 'auth-status.json', result)
                elif args.command == 'configure-facebook':
                    import yaml
                    config_path = settings.data / 'krp' / 'config.yaml'
                    config = yaml.safe_load(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
                    config = config or {}
                    actor = config.setdefault('actors', {}).setdefault('facebook', {}).setdefault('thoremix', {})
                    actor.update(display_name=args.name.strip(), canonical_url='https://www.facebook.com/ThoRemixOfficial')
                    # JSON is also valid YAML, allowing the shared atomic writer.
                    atomic_json(config_path, config)
                    result = {'state': 'configured', 'facebook_display_name': args.name.strip(),
                              'reason': 'KRP sẽ xác minh tên và URL trong trình duyệt trước khi đăng.'}
                elif args.command == 'affiliate':
                    from .affiliate import acquire_affiliate
                    result = acquire_affiliate(settings)
                    atomic_json(settings.data / 'affiliate-selection.json', result)
                elif args.command == 'publish':
                    result = publish(settings, args.package)
                elif args.command == 'publish-platform':
                    result = _publish(
                        settings, args.package, only_platforms=[args.platform],
                        stop_after_publication=args.stop_after_publication)
                elif args.command == 'import-source':
                    campaign = Campaign(settings)
                    job = campaign.reserve(args.slot)
                    result = FlowKitProducer(campaign).import_source(job['id'])
                elif args.command == 'finalize':
                    result = Campaign(settings).finalize(args.job_id, args.video, children=args.frame,
                        metadata=json.loads(args.metadata.read_text(encoding='utf-8-sig')))
                elif args.command == 'prepare-package':
                    result = Campaign(settings).prepare_package(args.slot, args.source, args.video,
                        children=args.frame, metadata=json.loads(args.metadata.read_text(encoding='utf-8-sig')))
                elif args.command == 'reconcile-package':
                    result = Campaign(settings).reconcile_package(args.job_id)
                atomic_json(settings.data / 'last-result.json', {'command': args.command, 'result': result})
                print(json.dumps(result, ensure_ascii=False, default=str))
                return 0
    except Exception as exc:  # noqa: BLE001 - sanitize external browser/provider exceptions at the CLI boundary.
        # Toolkit/browser exceptions can carry private URLs. Keep only a bounded
        # local error type in general CLI logs; adapter receipts carry safe reasons.
        result = {'state': 'needs_input', 'error_type': type(exc).__name__}
        if isinstance(exc, RunnerBusyError):
            result.update(state='busy', reason='Một lượt Thỏ Remix hoặc cửa sổ đăng nhập đang mở; chờ lượt đó hoàn tất.')
        elif isinstance(exc, (ValueError, FileNotFoundError, KeyError)):
            result['reason'] = str(exc)[:300]
        # A failed lock grants no right to write state during another operation
        # or bundle promotion. The invoking controller receives this JSON.
        print(json.dumps(result, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
