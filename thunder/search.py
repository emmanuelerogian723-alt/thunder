"""Thunder web search — shared by the local MCP server and the hosted
remote MCP, so online and offline behave identically.

DDG POST-first (its official html method; GET returns a form-only
shell from datacenter IPs), then lite.duckduckgo and Bing fallbacks
through the browse() retry engine. Bing redirect URLs are unwrapped.
"""
from __future__ import annotations

import asyncio
import base64
import html as _html
import re
from typing import List
from urllib.parse import quote, unquote

_RESULT_A = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_LITE = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*class="result-link"')
_BING = re.compile(r'<h2><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.S)


def _unwrap(url: str) -> str:
    url = url.replace("&amp;", "&")
    m = re.search(r"[?&]uddg=([^&]+)", url)
    if m:
        return unquote(m.group(1))
    if "bing.com/ck/a" in url:
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", url)
        if m:
            b = m.group(1)
            b += "=" * (-len(b) % 4)
            try:
                return base64.urlsafe_b64decode(b).decode("utf-8", "replace")
            except Exception:
                pass
    return url


def _parse(text: str, limit: int) -> List[str]:
    out = []
    links = _RESULT_A.findall(text)
    if not links:
        links = [(u, "") for u in _LITE.findall(text)]
    if not links:
        links = _BING.findall(text)
    for url, title in links:
        title = _html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        url = _unwrap(url.strip())
        if title and url and "duckduckgo.com" not in url:
            out.append(f"{title}\n{url}")
    return out[:limit]


async def web_search(query: str, limit: int = 5) -> str:
    """Search the web with Thunder's ghost (browser-true TLS)."""
    from .ghost import Ghost
    g = Ghost()
    try:
        results: List[str] = []
        for attempt in range(2):
            try:
                r = await g.post("https://html.duckduckgo.com/html/",
                                 data={"q": query}, timeout=20)
                if r is not None and getattr(r, "status_code", 0) == 200 \
                        and "result__a" in r.text:
                    results = _parse(r.text, limit)
                    break
            except Exception:
                pass
            await asyncio.sleep(1.5 * (attempt + 1))
        if not results:
            for ep in ("https://lite.duckduckgo.com/lite/?q=" + quote(query),
                       "https://www.bing.com/search?q=" + quote(query)):
                try:
                    r = await g.browse(ep, retries=2, timeout=20)
                except Exception:
                    continue
                if r is not None and getattr(r, "status_code", 0) == 200:
                    results = _parse(r.text, limit)
                    if results:
                        break
        if results:
            return "\n\n".join(results)
        return ("search failed: all engines blocked this egress IP. "
                "Pair Thunder with a residential proxy (THUNDER_PROXY) "
                "for reliable search from datacenter IPs.")
    finally:
        await g.close()


async def feel(url: str) -> str:
    """Check a target's bot posture: plain request vs thunder ghost."""
    import httpx
    from .ghost import Ghost
    plain_status = None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            plain = await c.get(url)
            plain_status = plain.status_code
    except Exception:
        plain_status = "blocked/failed"
    g = Ghost()
    try:
        try:
            r = await g.browse(url, retries=2)
            th_status = r.status_code if r is not None else "blocked/failed"
            wall = "captcha" in (r.text[:3000].lower() if r is not None else "")
        except Exception:
            th_status, wall = "blocked/failed", False
    finally:
        await g.close()
    verdict = ("site shows a CAPTCHA wall to this request's IP" if wall
               else "site appears open")
    return (f"plain python request: {plain_status}\n"
            f"thunder ghost request: {th_status}\n"
            f"bot-wall: {'yes' if wall else 'no'} — {verdict}\n"
            "note: hard targets (Amazon, Google) weigh IP reputation; "
            "pair Thunder with a residential proxy for those.")
