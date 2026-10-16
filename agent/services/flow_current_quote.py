"""Read-only strict 2026 vi-VN Google Flow video quote from one authenticated page.

This observer never uploads, fills a prompt, reserves credits, creates an
authorization, starts generation, polls, publishes or writes app state.
It requires a complete exact UI match for a *single* 10-second Omni 1.1 Flash
360p portrait component-reference video. Caller must issue a native owner grant
separately and must not use this observer as permission to submit.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from agent.services.flow_browser_auth import (
    observe_flow_account, read_current_flow_balance,
)

_PRICE = re.compile(r"^([1-9][0-9]*) tín dụng$")
_TARGET = {"video":"end", "thanh phan":"end", "9:16":"end",
           "360p":"start", "10 giay":"start", "x1":"start"}


def inspect_current_video_quote(page, project_id: str, *, credit_cap: int) -> dict:
    """Inspect live account, balance, exact preset and price in one UI session.

    Raises ValueError before any paid effect if a control is missing,
    ambiguous, hidden, unverified or beyond the caller's explicit cap.
    """
    if (type(project_id) is not str or not re.fullmatch(r"[a-zA-Z0-9_-]{5,150}", project_id)
            or type(credit_cap) is not int or not 1 <= credit_cap <= 10000):
        raise ValueError("FLOW_QUOTE_INPUT_INVALID")
    parsed = urlsplit(page.url)
    if (parsed.scheme != "https" or parsed.hostname != "flow.google.com"
            or parsed.path != "/project/" + project_id or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        raise ValueError("FLOW_QUOTE_PROJECT_MISMATCH")
    account = observe_flow_account(page)
    if account.state != "authenticated" or not account.identity:
        raise ValueError("FLOW_QUOTE_ACCOUNT_NOT_VERIFIED")
    identity_hash = hashlib.sha256(account.identity.casefold().encode("utf-8")).hexdigest()
    balance = read_current_flow_balance(page)["balance_credits"]
    if type(balance) is not int or balance < credit_cap:
        raise ValueError("FLOW_QUOTE_BALANCE_INSUFFICIENT")
    page.keyboard.press("Escape")

    toggle = page.locator("flow-agent-mode-toggle-chip button.agent-mode-chip")
    if toggle.count() != 1 or not toggle.is_visible():
        raise ValueError("FLOW_QUOTE_STANDARD_MODE_MISSING")
    is_enabled = toggle.evaluate("(x)=>x.classList.contains('agent-mode-chip-checked')")
    if is_enabled:
        toggle.evaluate("(x)=>x.click()")
    if toggle.evaluate("(x)=>x.classList.contains('agent-mode-chip-checked')"):
        raise ValueError("FLOW_QUOTE_AGENT_MODE_ACTIVE")
    if page.locator("flow-creative-agent-prompt-box").count() != 0:
        raise ValueError("FLOW_QUOTE_AGENT_COMPOSER_ACTIVE")

    bar = page.locator(".base-prompt-box .bottom-controls")
    if bar.count() != 1 or not bar.is_visible():
        raise ValueError("FLOW_QUOTE_TOOLBAR_MISSING")
    # Only this uniquely scoped configuration button; never Generate.
    opened = bar.evaluate("""(box)=>{
      const btns=[...box.querySelectorAll('button')].filter(e=>
        e.getBoundingClientRect().width>95&&(e.innerText||'').includes('Video'));
      if(btns.length!==1)return false;btns[0].click();return true;
    }""")
    if opened is not True:
        raise ValueError("FLOW_QUOTE_SETTINGS_MISSING")

    evidence = page.evaluate("""() => {
      const norm=s=>(s||'').normalize('NFD')
        .replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
      const keys=[['video','end'],['thanh phan','end'],['9:16','end'],
        ['360p','start'],['10 giay','start'],['x1','start']];
      const radios=[...document.querySelectorAll('[role=radio]')].filter(e=>
        e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0);
      let matched=[];
      for(const [key,position] of keys){
        const elements=radios.filter(e=>position==='end' ?
          norm(e.innerText).endsWith(key):norm(e.innerText).startsWith(key));
        if(elements.length!==1)return {ready:false,reason:'FLOW_QUOTE_RADIO_AMBIGUOUS'};
        if(elements[0].getAttribute('aria-checked')!=='true')
          elements[0].click();
        matched.push({key,selected:elements[0].getAttribute('aria-checked')});
      }
      const model=[...document.querySelectorAll('button')].filter(e=>
        e.getBoundingClientRect().width>0&&
        norm(e.getAttribute('aria-label')).includes('chon nhom mo hinh'));
      const prices=[...document.querySelectorAll('a,[role=link]')].filter(e=>{
        const x=(e.innerText||'').trim();
        return e.getBoundingClientRect().width>0&&x.length<30&&
          x.endsWith('t\u00edn d\u1ee5ng');
      }).map(e=>(e.innerText||'').trim());
      return {ready:matched.every(x=>x.selected==='true'),
        matches:matched,model_count:model.length,
        model:model.length===1?norm(model[0].innerText).split(String.fromCharCode(10))[0]:null,
        prices,
        agent_count:document.querySelectorAll('flow-creative-agent-prompt-box').length};
    }""")
    if (type(evidence) is not dict or evidence.get("ready") is not True
            or evidence.get("agent_count") != 0 or evidence.get("model_count") != 1
            or evidence.get("model") != "omni 1.1 flash"):
        raise ValueError("FLOW_QUOTE_PRESET_UNVERIFIED")
    prices = evidence.get("prices")
    if type(prices) is not list or len(prices) != 1:
        raise ValueError("FLOW_QUOTE_PRICE_AMBIGUOUS")
    matched = _PRICE.fullmatch(prices[0])
    if matched is None:
        raise ValueError("FLOW_QUOTE_PRICE_UNVERIFIED")
    cost = int(matched.group(1))
    if cost > credit_cap or cost > balance:
        raise ValueError("FLOW_QUOTE_COST_EXCEEDS_AUTHORIZED_CAP")
    page.keyboard.press("Escape")
    return {
        "credits": balance, "quoted_cost": cost,
        "duration_s": 10, "model": "Omni 1.1 Flash",
        "resolution": "360p", "variants": 1, "aspect": "9:16",
        "source_mode": "component", "account_identity_sha256": identity_hash,
        "quote_source": "verified_live_google_flow_ui", "paid_generate_called": False,
    }
