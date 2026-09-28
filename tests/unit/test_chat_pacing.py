from types import SimpleNamespace

import pytest

from agent.thoremix.chat_pacing import ChatPacer,PacingDeferred,rate_limited
from agent.thoremix.config import Settings,change_settings


def setup(tmp_path):
    settings=Settings(root=str(tmp_path/'app'),input_dir=str(tmp_path/'input'),enabled=True)
    settings.save()
    runtime=SimpleNamespace(chat_profile_dir=str(tmp_path/'profile'),chat_home=str(tmp_path/'home'),
                            chat_min_interval_s=90,chat_rest_after_response_s=30)
    now=[1000.0]
    sleep=lambda delay:now.__setitem__(0,now[0]+delay)
    return settings,runtime,now,sleep


def test_restart_keeps_spacing_and_rest_after_slow_answer(tmp_path):
    settings,runtime,now,sleep=setup(tmp_path)
    def slow():
        now[0]+=120
        return {'state':'verified'}
    ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep).call(slow)
    starts=[]
    ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep).call(lambda:starts.append(now[0]))
    assert starts==[1150]
    ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep).call(lambda:starts.append(now[0]))
    assert starts==[1150,1240]


def test_explicit_limit_persists_backoff_and_pause_never_sends(tmp_path):
    settings,runtime,now,sleep=setup(tmp_path)
    pacer=ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep)
    pacer.call(lambda:{'status_code':429,'retry_after_s':7200})
    assert pacer.read()['next_request_at']==8200
    change_settings(settings.directory,enabled=False)
    with pytest.raises(PacingDeferred):
        pacer.call(lambda:pytest.fail('must not send'))
    assert now[0]==1000


def test_exception_still_requires_rest_and_never_retries(tmp_path):
    settings,runtime,now,sleep=setup(tmp_path)
    pacer=ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep)
    calls=[]
    def interrupted():
        calls.append(1)
        raise RuntimeError('uncertain request')
    with pytest.raises(RuntimeError):pacer.call(interrupted)
    assert calls==[1] and pacer.read()['next_request_at']==1090


def test_ordinary_source_words_are_not_provider_quota_evidence():
    assert not rate_limited({'state':'verified','text':'{"text":"Thử lại sau nhé! Rate limit"}'})
    assert rate_limited({'state':'needs_input','reason':'You have reached the rate limit'})


def test_pause_during_final_wait_never_crosses_submit_boundary(tmp_path):
    settings,runtime,now,sleep=setup(tmp_path)
    pacer=ChatPacer(settings,runtime,clock=lambda:now[0],sleep=sleep)
    pacer.call(lambda:{'state':'verified'})
    now[0]=1088
    def pause(delay):
        sleep(delay)
        change_settings(settings.directory,enabled=False)
    pacer.sleep=pause
    with pytest.raises(PacingDeferred):
        pacer.call(lambda:pytest.fail('paused at deadline'))
