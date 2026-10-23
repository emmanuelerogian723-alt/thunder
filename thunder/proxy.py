"""ProxyManager — Thunder's answer to datacenter-IP blocking.

A datacenter IP with no history is suspicious before Thunder even moves.
The fix is not code magic — it is clean egress. This module makes plugging
one in trivial and safe:

    from thunder.proxy import ProxyManager

    pm = ProxyManager.from_env()          # THUNDER_PROXY=... or
                                         # THUNDER_PROXY_LIST=a,b,c
    proxy = await pm.pick(profile="ada")  # sticky per profile
    await pm.check(proxy)                 # health-check via the Ghost
    body = Body(profile="ada", proxy=proxy)

Supported forms:
    http://user:pass@host:port   https://...   socks5://...
    user:pass@host:port          host:port
Rotation policy: sticky per profile (a human keeps the same IP for a
session), round-robin across the pool when a proxy fails, with backoff.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

from curl_cffi.requests import AsyncSession
from typing import Dict, List, Optional


def _normalize(raw: str) -> Optional[Dict[str, str]]:
    """Accept the many forms people write proxies in, return playwright form."""
    raw = raw.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    scheme, rest = raw.split("://", 1)
    if scheme not in ("http", "https", "socks5", "socks4"):
        return None
    server = rest
    username = password = ""
    if "@" in rest:
        creds, server = rest.rsplit("@", 1)
        if ":" in creds:
            username, password = creds.split(":", 1)
    out = {"server": f"{scheme}://{server}"}
    if username:
        out["username"] = username
        out["password"] = password
    return out


class ProxyManager:
    """Pool of egress proxies with sticky per-profile rotation."""

    def __init__(self, proxies: Optional[List[Dict[str, str]]] = None):
        self.proxies: List[Dict[str, str]] = [p for p in (proxies or []) if p]
        self._cursor = 0
        self._sticky: Dict[str, Dict[str, str]] = {}
        self._cooldown: Dict[str, float] = {}   # server -> until ts

    # ── construction ────────────────────────────────────────────
    @classmethod
    def from_env(cls) -> "ProxyManager":
        proxies: List[Dict[str, str]] = []
        one = os.getenv("THUNDER_PROXY", "").strip()
        if one:
            proxies.append(_normalize(one))
        list_ref = os.getenv("THUNDER_PROXY_LIST", "").strip()
        if list_ref:
            src = Path(list_ref)
            items = src.read_text().split() if src.exists() else list_ref.split(",")
            proxies.extend(p for p in (_normalize(i) for i in items) if p)
        return cls(proxies)

    def __len__(self) -> int:
        return len(self.proxies)

    # ── selection ───────────────────────────────────────────────
    def pick(self, profile: str = "default") -> Optional[Dict[str, str]]:
        """Sticky per profile: same human keeps the same egress all session."""
        if not self.proxies:
            return None
        if profile in self._sticky:
            return self._sticky[profile]
        for _ in range(len(self.proxies)):
            p = self.proxies[self._cursor % len(self.proxies)]
            self._cursor += 1
            if self._cooldown.get(p["server"], 0) > time.time():
                continue
            self._sticky[profile] = p
            return p
        return None

    def mark_bad(self, proxy: Dict[str, str], cooldown: float = 300.0):
        self._cooldown[proxy["server"]] = time.time() + cooldown
        for k, v in list(self._sticky.items()):
            if v["server"] == proxy["server"]:
                del self._sticky[k]          # next pick() rotates

    # ── Thunder's own pool: validated free egress, zero accounts ──
    @classmethod
    async def free_pool(cls, limit: int = 12, want: int = 5,
                        test_url: str = "https://example.com",
                        timeout: int = 8) -> "ProxyManager":
        """Fetch public proxy lists, validate each through a browser-true
        Ghost request, keep only the ones that actually egress.
        No account, no signup — Thunder's own starter pool. For
        hard targets (Amazon etc.) plug a residential proxy via
        THUNDER_PROXY; free pools are shared and low-reputation."""
        import httpx
        import asyncio
        raw: List[str] = []
        sources = [
            "https://api.proxyscrape.com/v3/free-proxy-list/get?request=displayproxies&protocol=http&timeout=8000&country=all&ssl=all&anonymity=all",
            "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        ]
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                for src in sources:
                    try:
                        r = await c.get(src)
                        raw.extend(f"http://{l.strip()}"
                                   for l in r.text.split()
                                   if l.count(".") >= 2 and ":" in l)
                    except Exception:
                        continue
                    if len(raw) >= limit * 3:
                        break
            random.shuffle(raw)
            raw = raw[:limit * 2]
        except Exception:
            pass
        if not raw:
            return cls([])

        async def _works(url: str) -> bool:
            try:
                s = AsyncSession(impersonate="chrome", timeout=timeout,
                                  proxies={"http": url, "https": url})
                ok = False
                r = await s.get(test_url)
                ok = r.status_code == 200
                await s.close()
                return ok
            except Exception:
                return False

        checks = await asyncio.gather(*[_works(u) for u in raw])
        good = [dict(server=u) for u, ok in zip(raw, checks) if ok]
        return cls(good[:want])

    # ── health check ────────────────────────────────────────────
    async def check(self, proxy: Optional[Dict[str, str]] = None,
                    timeout: int = 15) -> Dict[str, object]:
        """Egress check through the Ghost: my own IP + latency."""
        from .ghost import Ghost
        url = None
        if proxy:
            url = proxy["server"].replace(
                "://", f"://{proxy.get('username','')}:{proxy.get('password','')}@", 1
            ) if proxy.get("username") else proxy["server"]
        g = Ghost(proxy=url)
        try:
            t0 = time.time()
            r = await g.get("https://api.ipify.org?format=json", timeout=timeout)
            dt = round((time.time() - t0) * 1000)
            ip = (r.json().get("ip") if r.status_code == 200 else None)
            return {"ok": ip is not None, "ip": ip, "latency_ms": dt}
        except Exception as e:
            return {"ok": False, "ip": None, "error": str(e)[:120]}
        finally:
            await g.close()
