import json

import pytest


def journal(tmp_path):
    from agent.thoremix.story_stages import StageJournal
    return StageJournal(tmp_path, source_sha256='a' * 64)


def test_successful_stage_is_reused_without_another_effect(tmp_path):
    state = journal(tmp_path)
    calls = []
    effect = lambda progress: calls.append(1) or {'state': 'verified', 'data': {'panels': 4}}
    assert state.run('analysis', {'prompt': 'one'}, effect)['data']['panels'] == 4
    assert state.run('analysis', {'prompt': 'one'}, effect)['data']['panels'] == 4
    assert calls == [1]


def test_crash_after_remote_intent_never_runs_write_again(tmp_path):
    from agent.thoremix.story_stages import StageUncertain
    state = journal(tmp_path)
    calls = []
    def effect(progress):
        calls.append(1)
        progress({'preparation_step':'attach_references'})
        progress({'conversation_url': 'https://chatgpt.com/c/exact'})
        raise TimeoutError('secret signed URL must not enter the receipt')
    with pytest.raises(StageUncertain):
        state.run('images', {}, effect)
    with pytest.raises(StageUncertain):
        state.run('images', {}, effect)
    assert calls == [1]
    raw = (tmp_path/'images.json').read_text()
    assert 'secret signed' not in raw
    assert json.loads(raw)['progress']['conversation_url'].endswith('/exact')
    assert json.loads(raw)['progress']['preparation_step']=='attach_references'


def test_uncertain_stage_can_adopt_only_a_read_only_reconciliation(tmp_path):
    from agent.thoremix.story_stages import StageUncertain
    state = journal(tmp_path)
    with pytest.raises(StageUncertain):
        state.run('video', {}, lambda progress: {'state': 'uncertain'})
    result = state.run('video', {}, lambda _: pytest.fail('must not submit'),
                       reconcile=lambda previous, progress: {'state': 'verified', 'media_id': 'same'})
    assert result['media_id'] == 'same'


def test_changed_request_or_completed_artifact_cannot_be_reused(tmp_path):
    from agent.thoremix.story_stages import StageUncertain
    from agent.thoremix.core import sha256
    file = tmp_path/'result.png'
    file.write_bytes(b'first')
    state = journal(tmp_path)
    state.run('images', {}, lambda _: {'state': 'verified', 'files': [{'path': str(file), 'sha256': sha256(file)}]})
    with pytest.raises(StageUncertain):
        state.run('images', {'changed': True}, lambda _: pytest.fail('not resent'))
    file.write_bytes(b'second')
    with pytest.raises(StageUncertain):
        state.run('images', {}, lambda _: pytest.fail('not resent'))


def test_known_quality_rejection_is_terminal_and_has_no_repeat_effect(tmp_path):
    from agent.thoremix.story_stages import StageRejected
    state = journal(tmp_path)
    with pytest.raises(StageRejected):
        state.run('image_review', {}, lambda _: {'state': 'qa_failed', 'reason': 'wrong_scene'})
    with pytest.raises(StageRejected):
        state.run('image_review', {}, lambda _: pytest.fail('not resent'))


def test_owner_advisory_policy_resumes_saved_rejection_read_only(tmp_path):
    from agent.thoremix.story_stages import StageRejected
    state=journal(tmp_path)
    with pytest.raises(StageRejected):
        state.run('video_review',{},lambda _: {'state':'qa_failed','data':{'accepted':False,'issues':['pose']}})
    result=state.run('video_review',{},lambda _:pytest.fail('no new QA request'),advisory=True,
        reconcile=lambda previous,progress:{'state':'verified','data':previous['result']['data']})
    assert result['data']['accepted'] is False
    assert json.loads((tmp_path/'video_review-before-advisory-policy.json').read_text())['state']=='FAILED'
    assert json.loads((tmp_path/'video_review.json').read_text())['state']=='COMPLETED'
