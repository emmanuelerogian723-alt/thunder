"""Ghost — Thunder's protocol-level body.

For targets that don't need JavaScript, Ghost moves as pure
HTTP with a REAL browser's TLS (JA3/JA4) and HTTP/2 fingerprint,
via curl_cffi. A Python scraper's handshake betrays it before a
byte of JS runs; Ghost's handshake is Chrome's handshake.

    g = thunder.Ghost(skin)         # optional: match the skin's UA
    r = await g.get("https://site", impersonate="chrome131")
    print(r.status_code)

Also carries a persistent cookie jar so the ghost keeps its
session like a returning human.
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Dict, Optional

from curl_cffi.requests import AsyncSession

CHROME = "chrome"          # always impersonate the newest supported shape


class Ghost:
    """An HTTP body with a browser's handshake."""

    def __init__(self, skin=None, proxy: Optional[str] = None,
                 timeout: int = 30):
        self.skin = skin
        self.proxy = proxy or os.getenv("THUNDER_PROXY")
        self.timeout = timeout
        self._session: Optional[AsyncSession] = None

    async def _s(self) -> AsyncSession:
        if self._session is None:
            kw: Dict[str, Any] = {"timeout": self.timeout, "impersonate": CHROME}
            if self.proxy:
                kw["proxies"] = {"http": self.proxy, "https": self.proxy}
            kw["headers"] = self._browser_headers()
            self._session = AsyncSession(**kw)

    def _browser_headers(self) -> Dict[str, str]:
        """The exact header set a real Chrome sends, in Chrome's order.
        Half-configured header sets are a louder bot tell than none."""
        ua = self.skin.user_agent if self.skin else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
        langs = ",".join(self.skin.languages) if self.skin else "en-US,en;q=0.9"
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                      "image/avif,image/webp,image/apng,*/*;q=0.8,"
                      "application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": langs + ";q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Cache-Control": "max-age=0",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"' if "Windows" in ua else
                                  ('"macOS"' if "Mac" in ua else '"Linux"'),
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

    def _referred_headers(self, url: str) -> Dict[str, str]:
        """Second-hit headers: a human came from somewhere."""
        h = dict(self._browser_headers())
        h["Sec-Fetch-Site"] = "same-origin" if "amazon." in url else "cross-site"
        h["Referer"] = "https://www.google.com/"
        return h

    async def browse(self, url: str, retries: int = 3, timeout: int = 20):
        """Amazon-grade fetch: retry with evolved headers like a real
        browser that follows a link, hits refresh, waits and retries.
        Falls back through chrome impersonation versions, and rotates
        any configured proxy pool. Returns the first clean response."""
        from .proxy import ProxyManager
        pool = ProxyManager.from_env()
        variants = ["chrome", "chrome131", "chrome124", "chrome120"]
        last = None
        for attempt in range(retries):
            headers = self._referred_headers(url) if attempt > 0 else self._browser_headers()
            proxy = pool.pick("ghost") if len(pool) else None
            try:
                s = AsyncSession(
                    impersonate=variants[attempt % len(variants)],
                    timeout=timeout,
                    headers=headers,
                    **({"proxies": {"http": proxy["server"],
                                    "https": proxy["server"]}} if proxy else {}))
                r = await s.get(url)
                await s.close()
                last = r
                if r.status_code == 200 and "captcha" not in r.text[:20000].lower():
                    return r
                # bot wall: human behavior is to wait a moment and retry
                await asyncio.sleep(2.5 * (attempt + 1) + random.uniform(0, 2))
            except Exception:
                if proxy:
                    pool.mark_bad(proxy)
                await asyncio.sleep(1.5 * (attempt + 1))
        return last
        return self._session

    async def get(self, url: str, **kw) -> Any:
        s = await self._s()
        r = await s.get(url, **kw)
        return r

    async def post(self, url: str, **kw) -> Any:
        s = await self._s()
        r = await s.post(url, **kw)
        return r

    async def head(self, url: str, **kw) -> Any:
        s = await self._s()
        return await s.head(url, **kw)

    @property
    def cookies(self) -> Dict[str, str]:
        s = self._session
        if s is None:
            return {}
        return {c.name: c.value for c in s.cookies.jar}

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
