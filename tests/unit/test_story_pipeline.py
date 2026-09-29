import json
from pathlib import Path
from types import SimpleNamespace


class Campaign:
    def __init__(self, directory):
        from agent.thoremix.core import sha256
        source = directory/'original.png'
        source.write_bytes(b'one source')
        self.settings = SimpleNamespace(data=directory/'data', directory=directory,
                                        input_dir=str(directory), output=directory/'video')
        self.job = {'id': 'job', 'source': str(source), 'source_sha256': sha256(source),
                    'package_dir': str(directory/'video'/'package'), 'state': 'reserved'}
        self.finalized = []
    def get(self, job_id): return self.job
    def update(self, job_id, state, **detail): self.job['state'] = state
    def finalize(self, job_id, video, *, children, metadata):
        assert Path(video).is_file()
        self.finalized.append((video, children, metadata))
        from agent.thoremix.quality import package_state
        self.job['state'] = package_state(metadata)
        return {'video_path': str(video),**metadata}


class Operations:
    def __init__(self, *, bad_stage=None):
        self.calls, self.bad_stage = [], bad_stage
    def execute(self, stage, request, directory, progress):
        self.calls.append(stage)
        if stage == self.bad_stage:
            return {'state': 'qa_failed'}
        if stage == 'analysis':
            return {'state': 'verified', 'data': {'panels': [{'display_order': i, 'dialogues': []} for i in range(4)]}}
        if stage in {'images', 'video', 'highest', 'audio'}:
            from agent.thoremix.core import sha256
            files = []
            for i in range(4 if stage == 'images' else 1):
                path = directory/f'{stage}-{i}.bin'
                path.write_bytes((stage+str(i)).encode())
                files.append({'path': str(path), 'sha256': sha256(path)})
            return {'state': 'verified', 'files': files, 'data': {'accepted': True, 'media_id': 'native'}}
        if stage.endswith('review'): return {'state': 'verified', 'data': {'accepted': True}}
        if stage == 'copy': return {'state': 'verified', 'data': {'title': 'One story', 'caption': 'caption', 'description': 'description'}}
        if stage == 'affiliate': return {'state': 'verified', 'data': {'state': 'verified', 'comment': 'product'}}
        raise AssertionError(stage)
    def reconcile(self, stage, request, directory, previous, progress):
        raise AssertionError('No reconciliation was needed')


def test_one_source_is_one_package_and_every_stage_reuses_its_receipt(tmp_path):
    from agent.thoremix.story_pipeline import StoryPipeline
    campaign, ops = Campaign(tmp_path), Operations()
    result = StoryPipeline(campaign, operations=ops).run('job')
    assert result['state'] == 'video_ready'
    assert len(campaign.finalized) == 1
    assert len(campaign.finalized[0][1]) == 4
    assert campaign.finalized[0][2]['qa']['release_ready'] is True
    assert ops.calls == ['analysis', 'images', 'image_review', 'video', 'video_review', 'highest', 'audio', 'copy', 'affiliate']
    receipts = list((tmp_path/'data'/'production'/'job').glob('*.json'))
    assert len(receipts) == 9 and all(json.loads(p.read_text())['state'] == 'COMPLETED' for p in receipts)


def test_failed_image_qa_completes_video_for_manual_owner_approval(tmp_path):
    from agent.thoremix.story_pipeline import StoryPipeline
    campaign, ops = Campaign(tmp_path), Operations(bad_stage='image_review')
    result = StoryPipeline(campaign, operations=ops).run('job')
    assert result['state'] == 'awaiting_approval'
    assert 'video' in ops.calls and len(campaign.finalized)==1
    metadata=campaign.finalized[0][2]
    assert metadata['qa']['release_ready'] is False
    assert metadata['review']['status']=='pending' and metadata['review']['warnings']
    assert Path(campaign.job['source']).exists()


def test_paid_uncertainty_stops_before_another_effect_and_resumes_read_only(tmp_path):
    from agent.thoremix.story_pipeline import StoryPipeline
    campaign, ops = Campaign(tmp_path), Operations()
    actual = ops.execute
    ops.execute = lambda stage, *a: {'state': 'uncertain'} if stage == 'video' else actual(stage, *a)
    assert StoryPipeline(campaign, operations=ops).run('job')['state'] == 'reconciliation_required'
    prior = list(ops.calls)
    def read_only(stage, request, directory, previous, progress):
        assert stage == 'video'
        return {'state': 'uncertain'}
    ops.reconcile = read_only
    assert StoryPipeline(campaign, operations=ops).run('job')['state'] == 'reconciliation_required'
    assert ops.calls == prior


def test_pause_during_quality_check_stops_before_paid_video(tmp_path):
    from agent.thoremix.story_pipeline import StoryPipeline
    campaign,ops=Campaign(tmp_path),Operations()
    original=ops.execute
    ops.execute=lambda name,*a: ({'state':'blocked','not_submitted':True,'reason':'CHATGPT_WAIT_PAUSED'}
                                if name=='image_review' else original(name,*a))
    assert StoryPipeline(campaign,operations=ops).run('job')['state']=='production_not_ready'
    assert 'video' not in ops.calls and not campaign.finalized
