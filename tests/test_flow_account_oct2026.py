"""Current Flow account UI must prove exact identity, never infer from badge."""
from __future__ import annotations

import unittest

from agent.services.flow_browser_auth import observe_flow_account

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


if __name__=="__main__":
    unittest.main()
