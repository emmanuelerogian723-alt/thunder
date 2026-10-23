"""Body — Thunder's browser body.

A Body is a full human-shaped browser session:
  * a Skin (consistent device fingerprint)
  * stealth patches injected on every page (init script)
  * a Hand (human mouse/typing/scroll)
  * eyes (screenshots, structured page reading)
  * optional video recording of everything it does
  * persistent context (cookies/localStorage) per profile

Engines:
  * "playwright-stealth"  — default, zero heavy deps, works everywhere
  * "nodriver"            — optional, strongest anti-detection (AGPL-3
                             engine; see README license notes)

    import thunder
    body = thunder.Body(profile="ada")     # persistent human profile
    await body.wake("https://example.com")
    await body.type("input[name=q]", "thunder agent")
    shot_path = await body.look()
    await body.rest()

Run Thunder only on systems and accounts you are authorized to use.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .fingerprint import Skin, random_skin
from .human import Hand

THUNDER_HOME = Path(os.getenv("THUNDER_HOME", Path.home() / ".thunder"))


class Body:
    def __init__(self, profile: str = "default", skin: Optional[Skin] = None,
                 engine: str = "playwright-stealth", headless: bool = True,
                 record_video: bool = False, viewport: Optional[dict] = None,
                 locale: str = "en-US", timezone: str = "Africa/Lagos"):
        self.profile = profile
        self.engine = engine
        self.headless = headless
        self.viewport = viewport
        self.record = record_video
        self.locale = locale
        self.timezone = timezone
        self.user_data_dir = THUNDER_HOME / "profiles" / profile
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        skin_path = self.user_data_dir / "skin.json"
        if skin is None:
            if skin_path.exists():
                self.skin = Skin.load(str(skin_path))
            else:
                self.skin = random_skin(timezone=timezone)
                self.skin.save(str(skin_path))
        else:
            self.skin = skin
            self.skin.save(str(skin_path))
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.hand: Optional[Hand] = None
        self._video_dir = THUNDER_HOME / "videos"

    # ── lifecycle ──────────────────────────────────────────────────
    async def wake(self, url: Optional[str] = None):
        """Start the body's browser; optionally open a first page."""
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        launch_kw: Dict[str, Any] = dict(
            headless=self.headless,
            record_video_dir=str(self._video_dir) if self.record else None,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox", "--disable-dev-shm-usage",
                "--disable-infobars", "--window-size=1380,860",
                f"--window-position={random.randint(0,60)},{random.randint(0,40)}",
            ])
        if self.engine == "nodriver":
            # nodriver is a stronger, separate engine; supported via
            # thunder.nodriver_engine when installed (AGPL-3).
            raise ValueError("use thunder.nodriver_engine.NodriverBody for the nodriver engine")
        self._browser = await self._pw.chromium.launch_persistent_context(
            str(self.user_data_dir), **launch_kw)
        ctx = self._browser
        vp = self.viewport or {"width": self.skin.window_w, "height": self.skin.window_h}
        try:
            await ctx.add_init_script(self.skin.injection_script())
        except Exception:
            pass
        self.page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await self.page.set_viewport_size(vp)
        try:
            await self.page.set_locale(self.locale)
        except Exception:
            pass
        try:
            await ctx.set_default_timeout(20000)
        except Exception:
            pass
        # pages created later must also wear the skin
        ctx.on("page", lambda p: asyncio.ensure_future(self._dress(p)))
        self.hand = Hand(self.page, seed=self.skin.seed)
        if self.record:
            self._video_dir.mkdir(parents=True, exist_ok=True)
        if url:
            await self.go(url)
        return self

    async def _dress(self, page):
        try:
            await page.add_init_script(self.skin.injection_script())
        except Exception:
            pass

    async def rest(self):
        """Close the body gracefully (context persists to disk)."""
        try:
            if self.page and self.record:
                await self.page.wait_for_timeout(300)
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        finally:
            self._browser = None
            self.page = None

    # ── actions (human-shaped) ─────────────────────────────────────
    async def go(self, url: str, human: bool = True):
        """Navigate like a person: sometimes pause before, sometimes
        read the page after."""
        if human and random.random() < 0.4:
            await asyncio.sleep(random.uniform(0.4, 1.8))
        r = await self.page.goto(url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass          # heavy sites never go idle; a human keeps reading anyway
        await asyncio.sleep(random.uniform(0.3, 0.9))
        return r

    async def look(self, path: Optional[str] = None) -> str:
        """Eyes: full-page screenshot."""
        p = path or str(self._video_dir / f"see_{int(time.time())}.png") \
            if self.record else path
        if not p:
            import tempfile
            fd, p = tempfile.mkstemp(suffix=".png")
            os.close(fd)
        await self.page.screenshot(path=p, full_page=False)
        return p

    async def read(self) -> Dict[str, Any]:
        """Eyes + understanding: structured outline of the page for
        LLMs (title, url, text excerpt, interactive elements)."""
        return await self.page.evaluate(
            "(() => {" + _read.__doc__ + "})()" if False else """(() => {
            const els = [];
            for (const el of document.querySelectorAll(
                    "a, button, input, textarea, select, [role=button], [contenteditable=true]")) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                let sel = el.id ? "#" + el.id : "";
                if (!sel && el.name) sel = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
                if (!sel && el.className && typeof el.className === "string") {
                    const c = el.className.trim().split(/\\s+/)[0];
                    if (c) sel = el.tagName.toLowerCase() + "." + c;
                }
                els.push({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText || el.value || el.placeholder || "").slice(0, 80),
                    selector: sel,
                    meta: el.getAttribute("href") || el.getAttribute("type") || "",
                });
                if (els.length >= 60) break;
            }
            return {
                title: document.title,
                url: location.href,
                text: document.body ? document.body.innerText.slice(0, 4000) : "",
                elements: els,
            };
        })()""")

    async def click(self, selector: str):
        await self.hand.click(selector)

    async def type(self, selector: str, text: str):
        await self.hand.type(selector, text)

    async def scroll(self, amount: int = 600):
        await self.hand.scroll(amount)

    async def extract(self, selector: str = "body") -> str:
        loc = self.page.locator(selector).first
        return await loc.inner_text()

    async def wait_human(self, seconds: float = 1.5):
        await self.hand.idle(seconds)

    # ── persistence ───────────────────────────────────────────────
    async def save_state(self):
        st = self.user_data_dir / "state.json"
        if self.page:
            st.write_text(json.dumps({
                "storage": await self.page.evaluate(
                    "JSON.stringify({l: localStorage, s: sessionStorage})"),
            }, indent=2))
        return str(st)
