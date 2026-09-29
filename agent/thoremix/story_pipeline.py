"""Finite one-source ComicReels production; durable stages own all effect decisions."""
from __future__ import annotations

from pathlib import Path

from .core import sha256
from .story_stages import StageJournal, StageRejected, StageUncertain, StageBlocked
from .quality import POLICY, package_state, advisory


class StoryPipeline:
    def __init__(self, campaign, *, operations):
        self.campaign = campaign
        self.operations = operations

    def run(self, job_id: str) -> dict:
        job = self.campaign.get(job_id)
        directory = self.campaign.settings.data/'production'/job_id
        journal = StageJournal(directory, source_sha256=job['source_sha256'])
        package_path = Path(job['package_dir'])/'package.json'
        if package_path.is_file():
            from .finishing import recover_pending,complete_story_receipt
            recover_pending(self.campaign,job_id)
            package=self.campaign.reconcile_package(job_id)
            complete_story_receipt(self.campaign.settings,job_id,package_path)
            return {'state': package_state(package), 'job_id': job_id, 'package': str(package_path)}
        source = Path(job['source'])
        if not source.is_file() or sha256(source) != job['source_sha256']:
            return {'state': 'invalid_source', 'reason': 'source_changed'}

        def stage(name, **inputs):
            request = {'source': str(source), 'source_sha256': job['source_sha256'], **inputs}
            self.campaign.update(job_id, 'production_pending', production_stage=name,
                                 production_receipts=str(directory))
            def call(progress,previous=None):
                result=(self.operations.reconcile(name,request,directory,previous,progress)
                        if previous is not None else self.operations.execute(name,request,directory,progress))
                return advisory(result) if name in {'image_review','video_review'} else result
            return journal.run(name, request,
                lambda progress: call(progress),
                reconcile=lambda previous, progress: call(progress,previous),
                advisory=name in {'image_review','video_review','audio'})

        try:
            analysis = stage('analysis')['data']
            panels = analysis['panels']
            if (not 1 <= len(panels) <= 4 or
                    [p['display_order'] for p in panels] != list(range(len(panels)))):
                return {'state': 'invalid_source', 'reason': 'story_reference_capacity_or_order'}
            images = stage('images', analysis=analysis)
            if len(images['files']) != len(panels):
                raise StageRejected('image_count_mismatch')
            from .story_assets import save_working_assets
            save_working_assets(self.campaign.settings, job, images['files'])
            image_qa = stage('image_review', analysis=analysis, images=images)
            video = stage('video', analysis=analysis, images=images, image_review=image_qa)
            video_qa = stage('video_review', analysis=analysis, images=images, video=video)
            highest = stage('highest', video=video)
            audio = stage('audio', analysis=analysis, video=highest)
            copy = stage('copy', analysis=analysis)['data']
            affiliate = stage('affiliate', analysis=analysis)['data']
            if affiliate.get('state') != 'verified':
                raise StageUncertain('AFFILIATE_UNVERIFIED')
            if len(audio['files']) != 1:
                raise StageUncertain('OUTPUT_NOT_ONE_CLIP')
            for key in ('title', 'caption', 'description'):
                if not isinstance(copy.get(key), str) or not copy[key].strip():
                    raise StageRejected('copy_incomplete')
            metadata = {key: copy[key] for key in ('title', 'caption', 'description')}
            warnings=[{'stage':name,'result':value['data']} for name,value in
                      [('images',image_qa),('video',video_qa),('audio',audio)]
                      if value['data'].get('accepted') is not True]
            metadata.update(affiliate=affiliate, qa={'release_ready': not warnings,
                'policy':POLICY,'production_complete':True,
                'image_review': image_qa['data'], 'video_review': video_qa['data'],
                'audio_review': audio['data']}, flow=video['data'],
                review={'status':'pending' if warnings else 'not_required','warnings':warnings},
                generation={'kind': 'native_flow_video', 'source_count': 1, 'output_clips': 1,
                            'highest_download': highest.get('data', {})},
                copy_provider=copy.get('provider_receipt', {}),
                youtube={'made_for_kids': False}, publication_targets=['facebook', 'tiktok', 'youtube'])
            final_video=Path(audio['files'][0]['path'])
            if hasattr(self.campaign.settings,'mask_enabled'):
                finished=stage('finishing',video=audio)
                final_video=Path(finished['files'][0]['path'])
                metadata['finishing']=finished['data']
            package = self.campaign.finalize(job_id, final_video,
                children=[Path(item['path']) for item in images['files']], metadata=metadata)
            from .finishing import complete_story_receipt
            if package_path.is_file():complete_story_receipt(self.campaign.settings,job_id,package_path)
            return {'state': package_state(package), 'job_id': job_id,
                    'video_path': package['video_path'], 'package': str(package_path)}
        except StageRejected as exc:
            return {'state': 'qa_failed', 'reason': str(exc)}
        except StageBlocked as exc:
            return {'state': 'production_not_ready', 'reason': str(exc)}
        except StageUncertain:
            return {'state': 'reconciliation_required', 'job_id': job_id}
