"""NodriverBody — Thunder's strongest body: real Chrome, driven raw.

nodriver (github.com/ultrafunkamsterdam/nodriver) drives a REAL
Google Chrome over the DevTools protocol with no automation-shim
fingerprint in the control plane — in 2026 anti-detect benchmarks
it was the only tool passing every production gate (31 Cloudflare
targets, zero blocks).

This engine is AGPL-3.0 (nodriver's license). Thunder's core stays
MIT; importing this module opts you into AGPL for the combination.

    from thunder.nodriver_body import NodriverBody

    body = NodriverBody(headless=False)     # real Chrome window
    await body.wake("https://nowsecure.nl")
    print(await body.read())
    await body.rest()

Requires: pip install nodriver  and Google Chrome installed.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .fingerprint import Skin, random_skin
from .human import Hand  # typing only; nodriver pages get a light hand

THUNDER_HOME = Path(os.getenv("THUNDER_HOME", Path.home() / ".thunder"))

CHROME_HINTS = [
    "google-chrome", "google-chrome-stable",
    "/usr/bin/google-chrome", "/opt/google/chrome/chrome",
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
]


def find_chrome() -> Optional[str]:
    for hint in CHROME_HINTS:
        p = shutil.which(hint) or (hint if os.path.isfile(hint) else None)
        if p:
            return p
    return None


class NodriverBody:
    """Real Chrome + raw CDP control. The strongest Thunder engine."""

    def __init__(self, profile: str = "chrome", headless: bool = False,
                 skin: Optional[Skin] = None,
                 browser_executable: Optional[str] = None,
                 proxy: Optional[str] = None):
        import nodriver  # lazy: optional engine
        self.nd = nodriver
        self.profile = profile
        self.headless = headless
        self.browser_executable = browser_executable or find_chrome()
        self.proxy = proxy or os.getenv("THUNDER_PROXY")
        if not self.browser_executable:
            raise RuntimeError(
                "NodriverBody needs real Chrome. Install it: "
                "https://www.google.com/chrome or set browser_executable.")
        self.user_data_dir = THUNDER_HOME / "profiles" / profile
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        skin_path = self.user_data_dir / "skin.json"
        if skin is None and skin_path.exists():
            self.skin = Skin.load(str(skin_path))
        else:
            self.skin = skin or random_skin()
            self.skin.save(str(skin_path))
        self.browser = None
        self.tab = None

    async def wake(self, url: Optional[str] = None):
        kw: Dict[str, Any] = dict(
            headless=self.headless,
            browser_executable_path=self.browser_executable,
            user_data_dir=str(self.user_data_dir),
            browser_args=[
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={self.skin.user_agent}",
                "--no-first-run", "--no-default-browser-check",
            ],
        )
        if self.proxy:
            kw["proxy"] = self.proxy
        self.browser = await self.nd.start(**kw)
        self.tab = await self.browser.get(url) if url else await self.browser.get("about:blank")
        return self

    async def go(self, url: str):
        self.tab = await self.browser.get(url)
        await asyncio.sleep(1.0)          # human settling beat
        return self.tab

    async def read(self) -> Dict[str, Any]:
        data = await self.tab.evaluate(
            "JSON.stringify({title: document.title, url: location.href,"
            " text: document.body ? document.body.innerText.slice(0, 4000) : ''})"
        )
        return json.loads(data)

    async def look(self, path: str) -> str:
        await self.tab.save_screenshot(path)
        return path

    async def click(self, selector: str):
        el = await self.tab.query_selector(selector)
        if el is None:
            raise ValueError(f"no element for {selector!r}")
        await el.mouse_click()

    async def type(self, selector: str, text: str):
        el = await self.tab.query_selector(selector)
        if el is None:
            raise ValueError(f"no element for {selector!r}")
        await el.click()
        await asyncio.sleep(0.3)
        for ch in text:
            await self.tab.send_key(ch if ch != "\n" else "\r")
            await asyncio.sleep(0.06 + 0.02 * (ord(ch) % 7))

    async def rest(self):
        if self.browser:
            try:
                self.browser.stop()
            except Exception:
                pass
