"""Real boundary contract: resumed video cannot submit without exact job grant."""
import hashlib
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.services.flow_story_browser import FlowStoryBrowser

JID='9dced947b3694d7096bd86c1f7d96de7'
SOURCE='b'*64
EVIDENCE='c'*64
PROFILE='flow_account'
ACCOUNT='a'*64
PROJECT='project123'


def digest(value):
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,ensure_ascii=False,separators=(',',':')
    ).encode()).hexdigest()


def envelope():
    auth_id='ui_resume_'+'d'*32
    grant={'schema_version':3,'currency':'flow_credits',
           'batch_id':auth_id,'scope':'single_reviewed_job',
           'job_ids':[JID],'reviewed_job_ids':[JID],
           'allocations':{JID:7},'cap_credits':7}
    budget={'provider':'google_flow','action':'native_video_generate',
            'currency':'flow_credits','operation':'resume_blocked_story',
            'stage':'video','job_id':JID,'source_sha256':SOURCE,
            'evidence_sha256':EVIDENCE,'operation_id':auth_id,
            'quote_id':'verified-readiness-'+'e'*32,
            'quoted_cost_credits':7,'max_cost_credits':7,
            'aggregate_id':grant['batch_id'],
            'aggregate_authorization_sha256':digest(grant),
            'profile_logical_name':PROFILE,
            'account_identity_sha256':ACCOUNT,'project_id':PROJECT}
    auth={'schema_version':1,'action':'resume_blocked_story',
          'authorization_id':auth_id,'job_id':JID,
          'authorized_by':'operator-confirmed',
          'authorized_at':datetime.now(timezone.utc).isoformat(),
          'source_sha256':SOURCE,'attempt_reason':'production_not_ready',
          'evidence_sha256':EVIDENCE,'budget':budget,
          'seven_job_budget':grant}
    req={'resume_job_id':JID,'source_sha256':SOURCE,
         'resume_evidence_sha256':EVIDENCE}
    return auth,req


class FakeLocator:
    def __init__(self):self.first=self
    def wait_for(self,*,state=None,timeout=None):return None


class FakePage:
    def __init__(self):self.url='https://flow.google.com/project/'+PROJECT
    def goto(self,*args,**kwargs):return None
    def locator(self,*args,**kwargs):return FakeLocator()


class ExactResumedPaidBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.runtime=SimpleNamespace(flow_profile_config='unused',
                                     flow_project_id=PROJECT)
        self.browser=FlowStoryBrowser(SimpleNamespace(directory=None),
                                      self.runtime)

    def test_missing_grant_denies_before_opening_browser(self):
        _,req=envelope()
        with patch('agent.services.flow_story_browser.FlowBrowserSessionProvider') as provider:
            r=self.browser.run('video',req,self.directory,lambda _:None)
        self.assertEqual(r['state'],'blocked')
        self.assertEqual(r['reason'],'NATIVE_VIDEO_BUDGET_INVALID')
        self.assertTrue(r['not_submitted'])
        provider.assert_not_called()

    def test_grant_for_wrong_job_denies_without_flow(self):
        auth,req=envelope()
        auth['job_id']='f'*32
        with patch('agent.services.flow_story_browser.FlowBrowserSessionProvider') as provider:
            r=self.browser.run('video',req,self.directory,lambda _:None,
                               authorization=auth)
        self.assertEqual(r['reason'],'NATIVE_VIDEO_BUDGET_JOB_BINDING_INVALID')
        provider.assert_not_called()

    def test_budget_project_change_denies_without_browser(self):
        auth,req=envelope()
        auth['budget']['project_id']='differentproject'
        with patch('agent.services.flow_story_browser.FlowBrowserSessionProvider') as provider:
            r=self.browser.run('video',req,self.directory,lambda _:None,
                               authorization=auth)
        self.assertEqual(r['reason'],'NATIVE_VIDEO_BUDGET_PROJECT_MISMATCH')
        provider.assert_not_called()

    def test_valid_grant_still_blocks_drifted_live_quote_before_upload(self):
        auth,req=envelope()
        fake=SimpleNamespace(session=SimpleNamespace(page=FakePage()),close=Mock())
        bal={'quote_source':'verified_live_google_flow_ui',
             'quoted_cost':7,'credits':1050,'account_identity_sha256':'f'*64,
             'model':'Omni 1.1 Flash','duration_s':10,'resolution':'360p',
             'variants':1}
        with patch('agent.services.flow_story_browser.FlowProfileConfig.load',
                   return_value=SimpleNamespace()), \
             patch('agent.services.flow_story_browser.FlowBrowserSessionProvider') as provider, \
             patch('agent.services.flow_story_browser.observe_flow_account',
                   return_value=SimpleNamespace(state='authenticated')), \
             patch.object(self.browser,'_prepare',return_value=bal), \
             patch('agent.services.flow_story_browser.upload_reference') as upload:
            provider.return_value.open.return_value=fake
            r=self.browser.run('video',req,self.directory,lambda _:None,
                               authorization=auth)
        self.assertEqual(r['reason'],'NATIVE_VIDEO_LIVE_QUOTE_GRANT_MISMATCH')
        self.assertTrue(r['not_submitted'])
        upload.assert_not_called()
        fake.close.assert_called_once()


if __name__=='__main__':
    unittest.main()
