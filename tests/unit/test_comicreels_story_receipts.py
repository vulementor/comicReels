import json
import hashlib

import pytest

from agent.comicreels.story import StoryReceipt

PROJECT = '487247a1-00f4-4de3-83c1-4c16ce834b93'
MEDIA = 'c0262f5c-3091-47c5-905e-14c97b08e4cf'
WORKFLOW = '7fd70aab-f6b7-4da6-982b-267063b0e026'
REFS = ['1a8271d1-283a-483b-84bc-f036897dd45e', '8a282727-0063-4130-a589-5833e85b2e74']
SOURCE_HASH = hashlib.sha256(b'original source').hexdigest()


def package(tmp_path):
    video = tmp_path/'story.mp4'
    video.write_bytes(b'validated test fixture')
    original = tmp_path/'source.png'
    original.write_bytes(b'original source')
    value = dict(source_sha256=SOURCE_HASH, source_path=str(original), video_path=str(video),
                 video_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),
                 qa={'release_ready': True}, media={'full_decode': True},
                 flow={'media_id': MEDIA, 'project_id': PROJECT, 'workflow_id': WORKFLOW},
                 story_contract={'source_count': 1, 'output_clips': 1,
                                 'source_sha256': SOURCE_HASH, 'join_other_stories': False})
    path = tmp_path/'package.json'
    path.write_text(json.dumps(value))
    return path, value


def test_complete_requires_the_same_reviewed_and_frozen_story(tmp_path):
    journal = StoryReceipt(tmp_path/'story.json')
    journal.begin(intent())
    journal.submitted(dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=PROJECT))
    path, value = package(tmp_path)
    journal.complete(path)
    assert journal.load()['state'] == 'COMPLETED'
    assert journal.load()['release_ready'] is True
    journal.complete(path)
    (tmp_path/'story.mp4').write_bytes(b'changed video')
    with pytest.raises(ValueError, match='PACKAGE_UNVERIFIED'):
        journal.complete(path)


@pytest.mark.parametrize('field,changes', [
    ('qa', {'release_ready': False}), ('flow', {'media_id': WORKFLOW}),
    ('story_contract', {'source_count': 2}), ('media', {'full_decode': False}),
    ('story_contract', {'source_sha256': 'b' * 64}),
])
def test_wrong_story_or_unreviewed_package_cannot_complete(tmp_path, field, changes):
    journal = StoryReceipt(tmp_path/'story.json')
    journal.begin(intent())
    journal.submitted(dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=PROJECT))
    path, value = package(tmp_path)
    value[field].update(changes)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='PACKAGE_UNVERIFIED'):
        journal.complete(path)
    assert journal.load()['state'] == 'PROCESSING'


def intent():
    return dict(source_sha256=SOURCE_HASH, project_id=PROJECT,
                ordered_reference_ids=REFS, prompt='Full story', duration_s=10,
                model='Omni 1.1 Flash', resolution='360p', aspect='9:16', variants=1)


@pytest.mark.parametrize('missing', [False, True])
def test_changed_or_missing_original_blocks_completion(tmp_path, missing):
    journal = StoryReceipt(tmp_path/'story.json')
    journal.begin(intent())
    journal.submitted(dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=PROJECT))
    path, _ = package(tmp_path)
    original = tmp_path/'source.png'
    if missing:
        original.unlink()
    else:
        original.write_bytes(b'wrong story')
    with pytest.raises(ValueError, match='PACKAGE_UNVERIFIED'):
        journal.complete(path)
    assert journal.load()['state'] == 'PROCESSING'


def test_crash_after_intent_never_allows_a_second_submit(tmp_path):
    path = tmp_path / 'story.json'
    StoryReceipt(path).begin(intent())
    assert json.loads(path.read_text())['state'] == 'SUBMITTING'
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        StoryReceipt(path).begin(intent())


def test_native_receipt_binds_media_workflow_project_without_raw_response(tmp_path):
    journal = StoryReceipt(tmp_path / 'story.json')
    journal.begin(intent())
    journal.submitted(dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=PROJECT))
    data = journal.load()
    assert data['state'] == 'PROCESSING'
    assert data['media_id'] == MEDIA and data['workflow_id'] == WORKFLOW
    with pytest.raises(ValueError, match='RECONCILIATION_REQUIRED'):
        journal.begin(intent())


def test_wrong_project_response_is_not_adopted(tmp_path):
    journal = StoryReceipt(tmp_path / 'story.json')
    journal.begin(intent())
    with pytest.raises(ValueError, match='RECEIPT_PROJECT_MISMATCH'):
        journal.submitted(dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=WORKFLOW))
    assert journal.load()['state'] == 'SUBMITTING'


def test_same_receipt_can_be_reconciled_but_different_media_is_rejected(tmp_path):
    journal = StoryReceipt(tmp_path / 'story.json')
    journal.begin(intent())
    receipt = dict(media_id=MEDIA, workflow_id=WORKFLOW, project_id=PROJECT)
    journal.submitted(receipt)
    journal.submitted(receipt)
    with pytest.raises(ValueError, match='RECEIPT_MISMATCH'):
        journal.submitted(receipt | {'media_id': WORKFLOW})


@pytest.mark.parametrize('changes', [{'ordered_reference_ids': REFS * 2}, {'variants': 2},
                                   {'source_sha256': ''}, {'prompt': ''}])
def test_invalid_story_intent_has_no_effect_record(tmp_path, changes):
    path = tmp_path / 'story.json'
    with pytest.raises(ValueError):
        StoryReceipt(path).begin(intent() | changes)
    assert not path.exists()
