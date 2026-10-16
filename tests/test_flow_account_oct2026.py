"""Current Flow account UI must prove exact identity, never infer from badge."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.services.flow_browser_auth import observe_flow_account, read_current_flow_balance

LABEL = "Tài khoản Google: Sample User  \n(sample@example.com), Gói thành viên của Google"
LEGACY = "Tài khoản Google: Sample User  \n(sample@example.com)"


class Element:
    def __init__(self, count=1, visible=True, label=None, nested=None):
        self._count=count
        self._visible=visible
        self.label=label
        self.nested=nested

    def count(self):return self._count
    def is_visible(self):return self._visible
    def get_attribute(self,key,timeout=1500):
        assert key == "aria-label"
        return self.label
    def get_by_role(self,role,name=None):
        assert role=="button"
        return self.nested or Element(count=0)


class Page:
    def __init__(self, url="https://flow.google.com/project/id",
                 current=None, old=None):
        self.url=url
        self.current=current if current is not None else Element(count=1,label=LABEL)
        self.old=old if old is not None else Element(count=0)

    def get_by_role(self,role,name=None,exact=False):
        assert role=="button"
        return self.old

    def locator(self,query):
        assert query == 'a[role="button"][aria-label^="Tài khoản Google: "]'
        return self.current


class FlowAccountOct2026Tests(unittest.TestCase):
    def test_visible_standalone_button_proves_exact_identity(self):
        x=observe_flow_account(Page())
        self.assertEqual(x.state,"authenticated")
        self.assertEqual(x.identity,"sample@example.com")

    def test_standalone_current_account_inside_legacy_header_wrapper(self):
        # Real October 2026 UI retains the old account-header div, but the
        # nested old-style button no longer exists. Current anchor is valid.
        wrapper=Element(nested=Element(count=0))
        result=observe_flow_account(Page(old=wrapper))
        self.assertEqual(result.state,"authenticated")
        self.assertEqual(result.identity,"sample@example.com")

    def test_two_conflicting_account_identity_labels_fail_closed(self):
        legacy=Element(nested=Element(label=LEGACY))
        current=Element(label=LABEL.replace("sample@example.com","other@example.com"))
        result=observe_flow_account(Page(old=legacy,current=current))
        self.assertNotEqual(result.state,"authenticated")

    def test_original_nested_button_still_supported(self):
        child=Element(label=LEGACY)
        container=Element(nested=child)
        x=observe_flow_account(Page(old=container,current=Element(count=0)))
        self.assertEqual(x.state,"authenticated")
        self.assertEqual(x.identity,"sample@example.com")

    def test_badge_only_never_authenticates(self):
        for lab in ("PRO","Tài khoản Google: Sample User",
                    "Tài khoản Google: Sample User (sample@example.com)",
                    "Tài khoản Google: Sample User (sample@example.com), "
                    "Không phải gói thành viên của Google"):
            self.assertNotEqual(observe_flow_account(Page(current=Element(label=lab))).state,
                                "authenticated")

    def test_ambiguous_or_hidden_standalone_refused(self):
        for current in (Element(count=2,label=LABEL),
                        Element(count=0,label=LABEL),
                        Element(visible=False,label=LABEL)):
            self.assertNotEqual(observe_flow_account(Page(current=current)).state,
                                "authenticated")

    def test_wrong_origin_protocol_and_embedded_credentials_refused(self):
        for url in ("http://flow.google.com/project/1",
                    "https://example.com/project/1",
                    "https://flow.google.com.evil.example/project/1",
                    "https://user:pass@flow.google.com/project/1"):
            self.assertNotEqual(observe_flow_account(Page(url=url)).state,
                                "authenticated")

    def test_legacy_wrong_child_fails_closed(self):
        old=Element(nested=Element(count=2,label=LEGACY))
        self.assertNotEqual(observe_flow_account(Page(old=old)).state,
                            "authenticated")




class CurrentFlowBalanceTests(unittest.TestCase):
    class BalanceLink:
        def __init__(self, label):
            self.label=label
        def count(self):return 1
        def is_visible(self):return True
        def inner_text(self, timeout=1500):return self.label

    class Dialog:
        def __init__(self, link):self.link=link
        def wait_for(self, state=None, timeout=None):
            assert state == 'visible'
        def get_by_role(self, role, name=None):
            assert role == 'link'
            return self.link

    class Account(Element):
        def __init__(self, owner):
            super().__init__(label=LABEL)
            self.owner=owner
        def evaluate(self, expression):
            assert expression == '(account) => account.click()'
            self.owner.opened=True

    class CreditPage(Page):
        def __init__(self, balance='1.050 tín dụng Google Flow'):
            super().__init__(current=Element(count=0))
            self.opened=False
            self.current=CurrentFlowBalanceTests.Account(self)
            self.dialog=CurrentFlowBalanceTests.Dialog(
                CurrentFlowBalanceTests.BalanceLink(balance))
        def get_by_role(self, role, name=None, exact=False):
            if role=='dialog':
                assert name == 'Cài đặt tài khoản'
                assert self.opened
                return self.dialog
            return super().get_by_role(role,name=name,exact=exact)

    def test_verified_live_balance_vietnamese_thousands(self):
        p=self.CreditPage()
        row=read_current_flow_balance(p)
        self.assertEqual(row['balance_credits'],1050)
        self.assertEqual(row['source'],'authenticated_ui_account_dialog')
        self.assertFalse(row['paid_generate_called'])

    def test_balance_label_changed_must_block(self):
        p=self.CreditPage('1050 credits')
        with self.assertRaisesRegex(ValueError,'FLOW_BALANCE_UNVERIFIED'):
            read_current_flow_balance(p)

    def test_wrong_origin_never_opens_account(self):
        p=self.CreditPage()
        p.url='https://other.example.com/project/id'
        with self.assertRaisesRegex(ValueError,'FLOW_ACCOUNT_NOT_VERIFIED'):
            read_current_flow_balance(p)
        self.assertFalse(p.opened)

    def test_zero_balance_is_valid_read_only_observation(self):
        p=self.CreditPage('0 tín dụng Google Flow')
        row=read_current_flow_balance(p)
        self.assertEqual(row['balance_credits'],0)


class SafeFlowPrepareTests(unittest.TestCase):
    class AbsentLegacy:
        def count(self):return 0
        def is_visible(self):return False

    class CurrentPage:
        def locator(self, selector):
            assert selector == 'flow-creative-agent-prompt-box'
            return SafeFlowPrepareTests.AbsentLegacy()

        def get_by_role(self, role, name=None, exact=False):
            assert role=="button"
            assert name=="Thông tin về tài khoản"
            assert exact is True
            return SafeFlowPrepareTests.AbsentLegacy()

    def test_new_composer_refuses_paid_quote_without_price(self):
        from agent.services.flow_story_browser import FlowStoryBrowser
        browser=FlowStoryBrowser(settings=None,runtime=None)
        with patch("agent.services.flow_story_browser.read_current_flow_balance",
                   return_value={"balance_credits":1050}) as check:
            with self.assertRaisesRegex(ValueError,"FLOW_GENERATION_PRESET_UI_CHANGED"):
                browser._prepare(self.CurrentPage())
        check.assert_called_once()
        self.assertFalse(hasattr(self.CurrentPage(),"paid_generate_called"))

    def test_agent_composer_blocks_even_with_legacy_account_wrapper(self):
        from agent.services.flow_story_browser import FlowStoryBrowser
        class AgentPage(self.CurrentPage):
            def locator(self, selector):
                assert selector == 'flow-creative-agent-prompt-box'
                class Present:
                    def count(self):return 1
                return Present()
            def get_by_role(self, role, name=None, exact=False):
                raise AssertionError('legacy account UI should never be used')
        browser=FlowStoryBrowser(settings=None,runtime=None)
        with patch("agent.services.flow_story_browser.read_current_flow_balance") as reader:
            with self.assertRaisesRegex(ValueError,"FLOW_GENERATION_PRESET_UI_CHANGED"):
                browser._prepare(AgentPage())
        reader.assert_not_called()

    def test_failed_live_balance_also_blocks(self):
        from agent.services.flow_story_browser import FlowStoryBrowser
        browser=FlowStoryBrowser(settings=None,runtime=None)
        with patch("agent.services.flow_story_browser.read_current_flow_balance",
                   side_effect=ValueError("FLOW_BALANCE_UNVERIFIED")):
            with self.assertRaisesRegex(ValueError,"FLOW_BALANCE_UNVERIFIED"):
                browser._prepare(self.CurrentPage())

if __name__=="__main__":
    unittest.main()
