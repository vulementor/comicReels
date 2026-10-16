"""Safety/unit tests for exact Flow quote proof, never a paid submit."""
from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from agent.services.flow_current_quote import inspect_current_video_quote

PROJECT = "project123"
REAL = "https://flow.google.com/project/" + PROJECT

def example(*, price="7 tín dụng", model="omni 1.1 flash", selected=True):
    return {"ready":selected, "agent_count":0,"model_count":1,"model":model,
            "matches":[{"key":k,"selected":"true" if selected else "false"}
                       for k in ("video","thanh phan","9:16","360p","10 giay","x1")],
            "prices":[price]}


class Locator:
    def __init__(self, owner, query):
        self.owner, self.query=owner, query
    def count(self):return 1 if self.query!="flow-creative-agent-prompt-box" else self.owner.agent_count
    def is_visible(self):return True
    def evaluate(self, code):
        self.owner.events.append(("evaluation",self.query))
        if self.query=="flow-agent-mode-toggle-chip button.agent-mode-chip":
            if "contains" in code and "click" not in code:return self.owner.agent_active
            if "click" in code:
                self.owner.agent_active=False
                return None
        if self.query==".base-prompt-box .bottom-controls":
            return True
        raise AssertionError("unexpected quote UI evaluation")


class Keyboard:
    def __init__(self, owner):self.owner=owner
    def press(self,key):
        assert key=="Escape"
        self.owner.events.append(("escape",key))


class Page:
    def __init__(self, evidence=None, url=REAL):
        self.url=url
        self.evidence=evidence if evidence is not None else example()
        self.events=[]
        self.keyboard=Keyboard(self)
        self.agent_active=True
        self.agent_count=0
    def locator(self, query):
        return Locator(self, query)
    def evaluate(self, code):
        assert "querySelectorAll" in code
        self.events.append(("read-presets",""))
        return self.evidence


class FlowQuoteNoPaidEffectsTests(unittest.TestCase):
    def call(self, page=None, *, balance=1050, cap=7):
        page=page or Page()
        with patch("agent.services.flow_current_quote.observe_flow_account",
                   return_value=SimpleNamespace(state="authenticated",identity="sample@example.com")), \
             patch("agent.services.flow_current_quote.read_current_flow_balance",
                   return_value={"balance_credits":balance,"paid_generate_called":False}) as reader:
            value=inspect_current_video_quote(page,PROJECT,credit_cap=cap)
        reader.assert_called_once_with(page)
        return value,page

    def test_exact_one_session_seven_credit_quote(self):
        receipt,page=self.call()
        self.assertEqual(receipt["quoted_cost"],7)
        self.assertEqual(receipt["credits"],1050)
        self.assertEqual(receipt["duration_s"],10)
        self.assertEqual(receipt["variants"],1)
        self.assertEqual(receipt["model"],"Omni 1.1 Flash")
        self.assertEqual(receipt["resolution"],"360p")
        self.assertFalse(receipt["paid_generate_called"])
        self.assertEqual(page.events[-1],("escape","Escape"))
        self.assertNotIn("Generate",repr(page.events))

    def test_price_exceeds_user_cap_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"COST_EXCEEDS_AUTHORIZED_CAP"):
            self.call(Page(example(price="8 tín dụng")))

    def test_changed_model_is_not_quote(self):
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_PRESET_UNVERIFIED"):
            self.call(Page(example(model="veo 3.1 fast")))

    def test_mismatched_duration_or_variant_is_not_quote(self):
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_PRESET_UNVERIFIED"):
            self.call(Page(example(selected=False)))

    def test_ambiguous_price_fails_closed(self):
        proof=example()
        proof["prices"]=["7 tín dụng","10 tín dụng"]
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_PRICE_AMBIGUOUS"):
            self.call(Page(proof))

    def test_wrong_project_does_not_inspect_or_generate(self):
        page=Page(url="https://flow.google.com/project/otherproject")
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_PROJECT_MISMATCH"):
            inspect_current_video_quote(page,PROJECT,credit_cap=7)
        self.assertEqual(page.events,[])

    def test_true_is_not_an_integer_credit_cap(self):
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_INPUT_INVALID"):
            inspect_current_video_quote(Page(),PROJECT,credit_cap=True)

    def test_balance_below_cap_blocks(self):
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_BALANCE_INSUFFICIENT"):
            self.call(balance=3)

    def test_no_auth_identity_blocks_before_balance(self):
        page=Page()
        with patch("agent.services.flow_current_quote.observe_flow_account",
                   return_value=SimpleNamespace(state="unknown",identity=None)), \
             patch("agent.services.flow_current_quote.read_current_flow_balance") as reader:
            with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_ACCOUNT_NOT_VERIFIED"):
                inspect_current_video_quote(page,PROJECT,credit_cap=7)
        reader.assert_not_called()

    def test_agent_composer_still_visible_blocks(self):
        page=Page()
        page.agent_count=1
        with self.assertRaisesRegex(ValueError,"FLOW_QUOTE_AGENT_COMPOSER_ACTIVE"):
            self.call(page)


if __name__=="__main__":
    unittest.main()
