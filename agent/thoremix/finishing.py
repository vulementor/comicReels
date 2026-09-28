"""Local, reversible masks/audio mix. Never alters a package with posting intent."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import Settings, atomic_json
from .core import Campaign, campaign_operation, media_tool, now_iso, sha256, validate_media
from .quality import manifest_digest, package_state


def options(settings):
    settings.validate()
    spec={'version':1,'mask_enabled':settings.mask_enabled,'top_percent':settings.mask_top_percent,
          'bottom_percent':settings.mask_bottom_percent,'laugh_enabled':settings.laugh_enabled,
          'laugh_volume':settings.laugh_volume}
    if settings.laugh_enabled:
        audio=Path(settings.laugh_path).resolve(strict=True)
        spec.update(laugh_path=str(audio),laugh_sha256=sha256(audio))
    return spec


def _run(settings, args, *, probe=False):
    result=subprocess.run([media_tool('ffprobe' if probe else 'ffmpeg',settings.directory),*args],
        capture_output=True,timeout=240,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise ValueError('Không xử lý được video/âm thanh; tệp gốc vẫn được giữ.')
    return result.stdout


def _archive(source, target, expected):
    if target.exists():
        if sha256(target)!=expected:raise ValueError('Bản lưu hồ sơ không khớp.')
        return
    temporary=target.with_suffix('.part')
    shutil.copy2(source,temporary)
    if sha256(temporary)!=expected:raise ValueError('Bản sao hồ sơ không khớp.')
    os.replace(temporary,target)


def render(settings, base, directory, spec=None):
    """Cache by immutable input + settings; always render from the original, never stack laughs."""
    base=Path(base).resolve(strict=True);directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    spec=spec or options(settings)
    base_hash=sha256(base)
    key=manifest_digest({'base_sha256':base_hash,'options':spec})
    target=directory/(key+'.mp4');receipt=directory/(key+'.json')
    if receipt.exists():
        data=json.loads(receipt.read_text(encoding='utf-8'))
        if data['base_sha256']!=base_hash or data['options']!=spec or sha256(target)!=data['video_sha256']:
            raise ValueError('Bản xử lý đã lưu thay đổi; không ghi đè.')
        validate_media(target,tool_root=settings.directory)
        return target,data
    original=validate_media(base,tool_root=settings.directory)
    duration=original['duration_s'];part=target.with_suffix('.part.mp4')
    args=['-nostdin','-y','-v','error','-i',str(base)]
    filters=[]
    if spec['mask_enabled']:
        h=original['height'];top=round(h*spec['top_percent']/100);bottom=round(h*spec['bottom_percent']/100)
        if top:filters.append(f'drawbox=x=0:y=0:w=iw:h={top}:color=black:t=fill')
        if bottom:filters.append(f'drawbox=x=0:y={h-bottom}:w=iw:h={bottom}:color=black:t=fill')
    laugh={}
    if spec['laugh_enabled']:
        audio=Path(spec['laugh_path'])
        if sha256(audio)!=spec['laugh_sha256']:raise ValueError('File tiếng cười đã thay đổi.')
        probe=json.loads(_run(settings,['-v','error','-show_entries','format=duration',
                                        '-of','json',str(audio)],probe=True))
        length=min(duration,float(probe['format']['duration']))
        if length<=0:raise ValueError('File tiếng cười không có âm thanh hợp lệ.')
        start=max(0,duration-length)
        args+=['-i',str(audio)]
        graph=(f'[1:a:0]atrim=duration={length:.6f},asetpts=PTS-STARTPTS,'
               f'volume={spec["laugh_volume"]},afade=t=out:st={max(0,length-.08):.6f}:d=0.08,'
               f'adelay={round(start*1000)}:all=1[laugh];'
               f'[0:a:0][laugh]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,'
               f'alimiter=limit=0.98:level=false:latency=true,atrim=duration={duration:.6f}[audio]')
        args+=['-filter_complex',graph,'-map','0:v:0','-map','[audio]','-c:a','aac','-b:a','192k']
        laugh={'start_s':start,'duration_s':length,'end_s':duration}
    else:args+=['-map','0:v:0','-map','0:a:0','-c:a','copy']
    if filters:args+=['-vf',','.join(filters),'-c:v','libx264','-crf','18','-preset','medium','-pix_fmt','yuv420p']
    else:args+=['-c:v','copy']
    args+=['-t',f'{duration:.6f}','-movflags','+faststart',str(part)]
    _run(settings,args)
    media=validate_media(part,tool_root=settings.directory)
    if ((media['width'],media['height'])!=(original['width'],original['height'])
            or abs(media['duration_s']-duration)>.05 or sha256(base)!=base_hash):
        raise ValueError('Xử lý video đã thay đổi kích thước/thời lượng hoặc tệp gốc.')
    if spec['laugh_enabled'] and sha256(Path(spec['laugh_path']))!=spec['laugh_sha256']:
        raise ValueError('File tiếng cười thay đổi trong khi xử lý.')
    from .audio_guard import verify_native_audio
    audio_guard=verify_native_audio(settings,base,part,
        laugh_start_s=laugh.get('start_s') if laugh else None)
    os.replace(part,target)
    data={'base_path':str(base),'base_sha256':base_hash,'options':spec,'media':media,
          'video_sha256':sha256(target),'render_key':key,'laugh':laugh,
          'audio_guard':audio_guard,'created_at':now_iso()}
    atomic_json(receipt,data)
    return target,data


def _promote(campaign, job, folder, transaction):
    """Recover either side of the video/manifest swap under the campaign lease."""
    path=folder/'package.json';before=transaction['before'];after=transaction['after']
    current=json.loads(path.read_text(encoding='utf-8'))
    if manifest_digest(current) not in {manifest_digest(before),manifest_digest(after)}:
        raise ValueError('Hồ sơ thay đổi trong lúc xử lý video.')
    target=Path(after['video_path']);rendered=Path(transaction['rendered'])
    if target.resolve().parent!=folder.resolve() or not rendered.resolve().is_relative_to((folder/'edits').resolve()):
        raise ValueError('Đường dẫn bản xử lý không hợp lệ.')
    if sha256(target) not in {before['video_sha256'],after['video_sha256']}:
        raise ValueError('Video thay đổi ngoài lượt xử lý.')
    if sha256(target)!=after['video_sha256']:
        if sha256(rendered)!=after['video_sha256']:raise ValueError('Bản xử lý không khớp.')
        part=folder/(target.stem+'.finishing.part.mp4')
        shutil.copy2(rendered,part)
        if sha256(part)!=after['video_sha256']:raise ValueError('Bản sao xử lý không khớp.')
        os.replace(part,target)
    validate_media(target,tool_root=campaign.settings.directory)
    atomic_json(path,after)
    campaign.update(job['id'],package_state(after),finishing_applied=True)
    complete_story_receipt(campaign.settings,job['id'],path)
    # A previous click cannot approve different media. Preserve the request as history.
    from .core import root_operation
    requests=campaign.settings.data/'review-requests'
    with root_operation(requests):
        request_path=requests/(job['id']+'.json')
        if request_path.exists():
            request=json.loads(request_path.read_text(encoding='utf-8'))
            old_digest=manifest_digest(before)
            approved_digest=before.get('review',{}).get('approved_manifest_sha256')
            if request.get('manifest_sha256') in {old_digest,approved_digest}:
                history=requests/'history';history.mkdir(exist_ok=True)
                import time
                os.replace(request_path,history/(job['id']+'-before-finish-'+str(time.time_ns())+'.json'))
    atomic_json(folder/'edits'/('applied-'+transaction['key']+'.json'),transaction)
    (folder/'edits'/'pending.json').unlink(missing_ok=True)
    return after


def apply_package(campaign, job_id, *, spec=None):
    with campaign_operation(campaign.settings):
        job=campaign.get(job_id);folder=Path(job['package_dir']).resolve()
        if folder.parent!=campaign.settings.output.resolve():raise ValueError('Hồ sơ ngoài thư mục video.')
        if job['state'] in {'publishing','published','wrong_media_blocked'} or (folder/'publication.json').exists():
            return {'state':'skipped_publication','job_id':job_id}
        path=folder/'package.json'
        if not path.is_file():return {'state':'not_produced','job_id':job_id}
        edits=folder/'edits';pending=edits/'pending.json'
        if pending.is_file():_promote(campaign,job,folder,json.loads(pending.read_text(encoding='utf-8')))
        package=campaign.reconcile_package(job_id)
        spec=spec or options(campaign.settings)
        if package.get('finishing',{}).get('options')==spec:
            complete_story_receipt(campaign.settings,job_id,path)
            return {'state':'unchanged','job_id':job_id,'package':package}
        edits.mkdir(exist_ok=True);history=edits/'history';history.mkdir(exist_ok=True)
        prior_hash=sha256(path);audit=history/(prior_hash+'.json')
        _archive(path,audit,prior_hash)
        base=edits/'original.mp4';base_meta=edits/'original.json'
        if not base_meta.exists():
            previous=package.get('finishing',{})
            original=Path(previous.get('base_path',package['video_path'])).resolve(strict=True)
            original_hash=previous.get('base_sha256',package['video_sha256'])
            allowed=(folder,campaign.settings.data/'production'/job_id)
            if not any(original.is_relative_to(p.resolve()) for p in allowed):
                raise ValueError('Video gốc nằm ngoài hồ sơ truyện.')
            shutil.copy2(original,base)
            if sha256(base)!=original_hash:raise ValueError('Bản lưu video gốc không khớp.')
            atomic_json(base_meta,{'sha256':original_hash,'package_sha256':prior_hash})
        else:
            expected=json.loads(base_meta.read_text(encoding='utf-8'))
            if sha256(base)!=expected['sha256']:raise ValueError('Video gốc đã thay đổi.')
        rendered,data=render(campaign.settings,base,edits,spec)
        updated=json.loads(json.dumps(package));updated.update(video_sha256=data['video_sha256'],
            media=data['media'],finishing=data)
        review=updated.get('review',{})
        if review.get('status')=='approved':
            updated['review']={'status':'pending','warnings':review.get('warnings',[]),
                               'reason':'Video đã được xử lý lại; xem bản mới trước khi duyệt.'}
            updated['qa']['release_ready']=False
        transaction={'key':data['render_key'],'before':package,'after':updated,'rendered':str(rendered)}
        atomic_json(pending,transaction)
        final=_promote(campaign,job,folder,transaction)
        return {'state':'processed','job_id':job_id,'package':final}


def apply_unpublished(settings):
    with campaign_operation(settings):
        campaign=Campaign(settings);spec=options(settings);results=[]
        for job in campaign.jobs():
            result=apply_package(campaign,job['id'],spec=spec)
            results.append({k:v for k,v in result.items() if k!='package'})
        return {'state':'processed','count':sum(r['state']=='processed' for r in results),'results':results}


def recover_pending(campaign, job_id):
    with campaign_operation(campaign.settings):
        job=campaign.get(job_id);folder=Path(job['package_dir'])
        pending=folder/'edits/pending.json'
        if pending.exists():
            if folder.resolve().parent!=campaign.settings.output.resolve() or (folder/'publication.json').exists():
                raise ValueError('Không thể phục hồi bản chỉnh sửa sau ý định đăng.')
            if job['state'] in {'publishing','published','wrong_media_blocked'}:
                raise ValueError('Không xử lý video đã bắt đầu đăng.')
            return _promote(campaign,job,folder,json.loads(pending.read_text(encoding='utf-8')))


def complete_story_receipt(settings, job_id, package_path):
    """Keep a paid receipt immutable; bind local finishing revisions to its archived manifest."""
    from agent.comicreels.story import StoryReceipt
    receipt=settings.data/'production'/job_id/'flow/story-receipt.json'
    if not receipt.is_file():return
    package=json.loads(package_path.read_text(encoding='utf-8'))
    if package_state(package)!='video_ready':return
    story=StoryReceipt(receipt)
    if not package.get('finishing'):
        story.complete(package_path)
        return
    record=story.load()
    if (record['state']=='COMPLETED' and package.get('finishing')
            and record.get('artifact',{}).get('package_sha256')!=sha256(package_path)):
        prior=package_path.parent/'edits/history'/(record['artifact']['package_sha256']+'.json')
        if not prior.is_file() or sha256(prior)!=record['artifact']['package_sha256']:
            raise ValueError('Thiếu biên nhận trước khi xử lý video.')
        old=json.loads(prior.read_text(encoding='utf-8'))
        if old['source_sha256']!=package['source_sha256'] or old['flow']!=package['flow']:
            raise ValueError('Video xử lý không cùng truyện Flow.')
        if sha256(Path(package['video_path']))!=package['video_sha256']:
            raise ValueError('Video xử lý đã thay đổi.')
        atomic_json(package_path.parent/'edits/flow-binding.json',{'native_receipt_sha256':sha256(receipt),
            'native_artifact':record['artifact'],'package_sha256':sha256(package_path),'video_sha256':package['video_sha256']})
    else:story.complete(package_path)
