"""Thunder web search — shared by the local MCP server and the hosted
remote MCP, so online and offline behave identically.

Multi-engine: DuckDuckGo (POST-first), Bing and Google (plus its
privacy mirror Startpage) through the browse() retry engine. Pass
engine="google" / "bing" / "duckduckgo" or "auto" (ddg -> bing ->
google). The first result line names the engine that answered.
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
_BING = re.compile(
    r'<li class="b_algo".*?<h2[^>]*><a[^>]+href="(https?://[^"]+)"[^>]*>'
    r'(.*?)</a>', re.S)


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


def _relevant(title: str, url: str, query: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9]{4,}", query.lower())
             if len(w) >= 5]
    blob = (title + " " + url).lower()
    return not words or any(w in blob for w in words)


def _parse(text: str, limit: int, query: str = "") -> List[str]:
    out = []
    links = _RESULT_A.findall(text)
    if not links:
        links = [(u, "") for u in _LITE.findall(text)]
    if not links:
        links = _BING.findall(text)
    for url, title in links:
        title = _html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        url = _unwrap(url.strip())
        if title and url and "duckduckgo.com" not in url \
                and _relevant(title, url, query):
            out.append(f"{title}\n{url}")
    return out[:limit]


async def web_search(query: str, limit: int = 5,
                      engine: str = "auto") -> str:
    """Search the web with Thunder's ghost (browser-true TLS).

    engine: "google" | "bing" | "duckduckgo" | "auto" (tries ddg -> bing
    -> google, whichever answers first from this egress IP).
    The first line of the result names the engine that answered.
    """
    from .ghost import Ghost

    _gq = [query]

    def _google(text: str) -> List[str]:
        out = []
        for url, title in re.findall(
                r'<a[^>]+href="(https?://[^"]+)"[^>]*>(?:[^<]*<[^>]+>\s*)*'
                r'<h3[^>]*>(.*?)</h3>', text, re.S):
            title = _html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if not title or any(x in url for x in
                                ("google.", "gstatic", "policies.",
                                 "support.google", "accounts.google")):
                continue
            if not _relevant(title, url, _gq[0]):
                continue
            out.append(f"{title}\n{url}")
        return out

    async def _run_engine(g: Ghost, eng: str) -> List[str]:
        if eng == "duckduckgo":
            for attempt in range(2):
                try:
                    r = await g.post("https://html.duckduckgo.com/html/",
                                     data={"q": query}, timeout=20)
                    if r is not None and getattr(r, "status_code", 0) == 200 \
                            and "result__a" in r.text:
                        return _parse(r.text, limit, query)
                except Exception:
                    pass
                await asyncio.sleep(1.5 * (attempt + 1))
            for ep in ("https://lite.duckduckgo.com/lite/?q=" + quote(query),):
                try:
                    r = await g.browse(ep, retries=2, timeout=20)
                except Exception:
                    continue
                if r is not None and getattr(r, "status_code", 0) == 200:
                    hits = _parse(r.text, limit, query)
                    if hits:
                        return hits
            return []
        if eng == "bing":
            try:
                r = await g.browse(
                    "https://www.bing.com/search?q=" + quote(query)
                    + "&count=" + str(limit + 5), retries=2, timeout=20)
                if r is not None and getattr(r, "status_code", 0) == 200:
                    return _parse(r.text, limit, query)
            except Exception:
                pass
            return []
        # google — and its privacy mirror startpage as a relay
        for ep in ("https://www.google.com/search?q=" + quote(query)
                   + "&num=" + str(limit + 5),
                   "https://www.startpage.com/sp/search?query=" + quote(query)):
            try:
                r = await g.browse(ep, retries=2, timeout=20)
            except Exception:
                continue
            if r is not None and getattr(r, "status_code", 0) == 200:
                hits = _google(r.text) or _parse(r.text, limit, query)
                if hits:
                    return hits
        return []

    order = ([engine] if engine in ("google", "bing", "duckduckgo")
             else ["duckduckgo", "bing", "google"])
    g = Ghost()
    try:
        for eng in order:
            try:
                results = await _run_engine(g, eng)
            except Exception:
                results = []
            if results:
                head = (f"[engine: {eng}]\n\n")
                return head + "\n\n".join(results)
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
