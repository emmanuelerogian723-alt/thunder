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

import os
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
            if self.skin and self.skin.user_agent:
                kw["headers"] = {
                    "User-Agent": self.skin.user_agent,
                    "Accept-Language": ",".join(self.skin.languages),
                }
            self._session = AsyncSession(**kw)
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
