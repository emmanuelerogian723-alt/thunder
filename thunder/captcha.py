"""CAPTCHA bridge — detect, classify, and solve.

Thunder's stance on CAPTCHAs:
  1. AVOID: with a good Skin, human hands and a residential IP,
     most challenges never fire. That is the first line.
  2. DETECT: senses() reports exactly which challenge (if any)
     is on the page, so an agent can decide.
  3. SOLVE: on your own accounts, plug in your existing solver
     subscription (CapSolver or 2Captcha API key). Thunder formats
     the task, polls, and injects the token.
  4. VISION (experimental): an LLM vision hook describes the
     challenge — the beginning of stewmind-native solving.

Thunder does not ship solver keys and is not a mass-solving
service. Use it where you have authorization.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Any, Dict, Optional

DETECT_JS = """(() => {
  const out = {found: false, type: null, sitekey: null, selector: null};
  const q = (sel) => document.querySelector(sel);
  const cf = q('.cf-turnstile, [data-sitekey]');
  if (cf) { out.found = true; out.type = 'turnstile';
            out.sitekey = cf.getAttribute('data-sitekey'); out.selector = '.cf-turnstile'; return out; }
  const rc = q('iframe[src*="recaptcha"]');
  if (rc) { out.found = true; out.type = 'recaptcha';
            const m = document.documentElement.innerHTML.match(/sitekey["']?\\s*[:=]\\s*["']([\\w-]{40})/);
            out.sitekey = m ? m[1] : null; out.selector = 'iframe[src*="recaptcha"]'; return out; }
  const hc = q('iframe[src*="hcaptcha"], [data-hcaptcha-sitekey]');
  if (hc) { out.found = true; out.type = 'hcaptcha';
            const m = document.documentElement.innerHTML.match(/sitekey["']?\\s*[:=]\\s*["']([\\w-]{30,})/);
            out.sitekey = m ? m[1] : null; return out; }
  const slide = q('.slider, .geetest_slider, [class*=slider]');
  if (slide) { out.found = true; out.type = 'slider'; return out; }
  return out;
})()"""


async def senses(page) -> Dict[str, Any]:
    """Look at the page and report any CAPTCHA challenge found."""
    try:
        return await page.evaluate(DETECT_JS)
    except Exception:
        return {"found": False, "type": None}


class SolverBridge:
    """Routes a challenge to your solver subscription."""

    def __init__(self, capsolver_key: Optional[str] = None,
                 twocaptcha_key: Optional[str] = None):
        self.capsolver = capsolver_key or os.getenv("CAPSOLVER_API_KEY", "")
        self.twocaptcha = twocaptcha_key or os.getenv("TWOCAPTCHA_API_KEY", "")

    def available(self) -> bool:
        return bool(self.capsolver or self.twocaptcha)

    async def solve(self, page, challenge: Dict[str, Any],
                    page_url: Optional[str] = None) -> Dict[str, Any]:
        """Solve the given challenge and inject the token."""
        import httpx

        url = page_url or page.url
        ctype = challenge.get("type")
        sitekey = challenge.get("sitekey") or ""
        if not self.available():
            return {"solved": False,
                    "error": "no solver key: set CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY",
                    "hint": "Thunder avoids most challenges with a good skin + human hand"}
        if not sitekey:
            return {"solved": False, "error": "no sitekey found on page"}

        async with httpx.AsyncClient(timeout=120) as c:
            token = None
            if self.capsolver and ctype == "turnstile":
                task = {"type": "AntiTurnstileTaskProxyLess",
                        "websiteURL": url, "websiteKey": sitekey}
                token = await self._capsolver(c, task)
            elif self.capsolver and ctype == "recaptcha":
                token = await self._capsolver(c, {
                    "type": "ReCaptchaV2TaskProxyLess",
                    "websiteURL": url, "websiteKey": sitekey})
            elif self.capsolver and ctype == "hcaptcha":
                token = await self._capsolver(c, {
                    "type": "HCaptchaTaskProxyLess",
                    "websiteURL": url, "websiteKey": sitekey})
            elif self.twocaptcha:
                token = await self._twocaptcha(c, ctype, url, sitekey)
            if not token:
                return {"solved": False, "error": "solver returned no token"}
            inject = {
                "turnstile": "document.querySelector('[name=cf-turnstile-response]'"
                             ",input[name=cf-turnstile-response]').value = t;"
                             "window.turnbridge_token = t;",
                "recaptcha": "document.getElementById('g-recaptcha-response')"
                             ".innerHTML = t; window.turnbridge_token = t;",
                "hcaptcha": "document.querySelector('[name=h-captcha-response]'"
                            ",textarea[name=g-recaptcha-response]').value = t;",
            }.get(ctype, "window.turnbridge_token = t;")
            await page.evaluate(f"(() => {{ const t = {token!r}; {inject} }})()")
            return {"solved": True, "type": ctype, "token": token[:24] + "..."}

    async def _capsolver(self, c, task: dict) -> Optional[str]:
        r = await c.post("https://api.capsolver.com/createTask",
                         json={"clientKey": self.capsolver, "task": task})
        d = r.json()
        if d.get("errorId"):
            return None
        tid = d["taskId"]
        for _ in range(40):
            await asyncio.sleep(3)
            r = await c.post("https://api.capsolver.com/getTaskResult",
                             json={"clientKey": self.capsolver, "taskId": tid})
            g = r.json().get("solution", {})
            if g.get("gRecaptchaResponse") or g.get("token"):
                return g.get("gRecaptchaResponse") or g.get("token")
        return None

    async def _twocaptcha(self, c, ctype: str, url: str, sitekey: str) -> Optional[str]:
        kind = {"recaptcha": "userrecaptcha", "hcaptcha": "hcaptcha"}.get(ctype)
        if not kind:
            return None
        r = await c.post("https://2captcha.com/in.php",
                        data={"key": self.twocaptcha, "method": kind,
                              "sitekey": sitekey, "pageurl": url, "json": 1})
        tid = r.json().get("request")
        if not tid:
            return None
        for _ in range(60):
            await asyncio.sleep(5)
            r = await c.get("https://2captcha.com/res.php",
                            params={"key": self.twocaptcha,
                                    "action": "get", "id": tid, "json": 1})
            d = r.json()
            if d.get("status") == 1:
                return d["request"]
        return None


async def describe_challenge(page, mind=None) -> str:
    """Experimental: stewmind vision describing a challenge."""
    shot = await page.screenshot()
    prompt = ("Describe this CAPTCHA challenge and the exact steps a human "
              "would take to solve it. Be brief.")
    if mind is None:
        return prompt  # caller routes screenshot + prompt to a vision model
    return prompt
