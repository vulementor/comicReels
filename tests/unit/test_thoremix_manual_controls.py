from datetime import datetime

from tests.unit.test_thoremix_retry import failed_story, NOW


def test_manual_retry_bypasses_scheduler_cooldown(tmp_path):
    from agent.thoremix.retry import retry_story

    s,q,j,directory,request=failed_story(tmp_path)
    q.finish(j['id'],'failed',NOW,'recent_failure')
    class Producer:
        def __init__(self,campaign): pass
        def close(self): pass
        def run(self,job_id): return {'state':'qa_failed','reason':'analysis'}

    result=retry_story(s,j['id'],producer_factory=Producer,now=lambda:NOW)
    assert result['state']=='retry_failed'
