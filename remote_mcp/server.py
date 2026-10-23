"""Thunder Remote MCP — a hosted, account-free MCP endpoint.

Paste this URL into Claude (Settings → Connectors → Add custom
connector, or claude.ai/mcp):

    https://thunder-mcp.onrender.com/mcp

No account. No signup. Claude connects straight to Thunder's
protocol-level tools. Full human-browser browsing runs locally via
`pip install thunder-agent` — this server is the always-on brainstem
anyone can test in seconds.
"""
import os
import re
from urllib.parse import quote, unquote

from fastmcp import FastMCP

import thunder
from thunder.ghost import Ghost

mcp = FastMCP("Thunder", instructions=(
    "Thunder is a human engine for AI agents. Use thunder_search to find "
    "pages, thunder_read to extract clean text through a browser-true TLS "
    "handshake (passes gates that 403 plain scrapers), thunder_ghost for "
    "raw protocol-level fetches, thunder_feel to check a target's bot "
    "posture, and thunder_solve for CAPTCHA tokens via your solver key. "
    "For full human-like browsing with mouse tremor and typing cadence, "
    "the user runs Thunder locally: pip install thunder-agent."))


def _clean_text(html: str, limit: int = 4000) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


RESULT_A = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
LITE_LINK = re.compile(
    r'<a[^>]+href="(https?://[^"]+)"[^>]*class="result-link"')
BING_LINK = re.compile(
    r'<h2><a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', re.S)


def _unwrap(url: str) -> str:
    url = url.replace("&amp;", "&")
    m = re.search(r"[?&]uddg=([^&]+)", url)
    if m:
        return unquote(m.group(1))
    # bing wraps destinations as .../ck/a?...&u=a1<base64>
    if "bing.com/ck/a" in url:
        m = re.search(r"[?&]u=a1([A-Za-z0-9_\-]+)", url)
        if m:
            import base64
            b = m.group(1)
            b += "=" * (-len(b) % 4)
            try:
                return base64.urlsafe_b64decode(b).decode("utf-8", "replace")
            except Exception:
                pass
    return url


def _parse_results(text: str, limit: int):
    out = []
    links = RESULT_A.findall(text)
    if not links:
        links = LITE_LINK.findall(text)
        links = [(u, "") for u in links]
    if not links:
        links = BING_LINK.findall(text)
    for url, title in links:
        import html as _html
        title = _html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        url = _unwrap(url.strip())
        if title and url and "duckduckgo.com" not in url:
            out.append(f"{title}\n{url}")
    return out[:limit]


@mcp.tool
async def thunder_search(query: str, limit: int = 5) -> str:
    """Search the web and return top results. Uses a browser-true
    TLS handshake; POSTs to DuckDuckGo (its official html method —
    GET now returns a form-only shell) with lite/Bing fallbacks,
    so datacenter IPs don't get stranded."""
    import asyncio
    g = Ghost()
    try:
        results = []
        # 1) DDG POST — official method for the html endpoint
        for attempt in range(2):
            try:
                r = await g.post("https://html.duckduckgo.com/html/",
                                 data={"q": query}, timeout=20)
                if r is not None and r.status_code == 200 and \
                        "result__a" in r.text:
                    results = _parse_results(r.text, limit)
                    break
            except Exception:
                pass
            await asyncio.sleep(1.5 * (attempt + 1))
        # 2) fallbacks: lite + bing via the browse() retry engine
        if not results:
            for ep in ("https://lite.duckduckgo.com/lite/?q=" + quote(query),
                       "https://www.bing.com/search?q=" + quote(query)):
                try:
                    r = await g.browse(ep, retries=2, timeout=20)
                except Exception:
                    continue
                if r is not None and getattr(r, "status_code", 0) == 200:
                    results = _parse_results(r.text, limit)
                    if results:
                        break
        if results:
            return "\n\n".join(results)
        return ("search failed: all engines blocked this egress IP. "
                "Thunder's local run with a residential proxy "
                "(THUNDER_PROXY) resolves this.")
    except Exception as e:
        return f"search failed: {e}"
    finally:
        await g.close()


@mcp.tool
async def thunder_read(url: str, limit: int = 5000) -> str:
    """Fetch a page and extract its clean readable text through a
    Chrome-true TLS handshake — passes bot gates that block normal
    scrapers. Use this instead of plain HTTP fetchers."""
    g = Ghost()
    try:
        r = await g.browse(url, retries=3)
        if r is None:
            return "fetch failed: no response"
        m = re.search(r"<title>(.*?)</title>", r.text[:8000], re.S)
        title = m.group(1).strip() if m else ""
        return f"status: {r.status_code}\ntitle: {title}\n\n{_clean_text(r.text, limit)}"
    except Exception as e:
        return f"read failed: {e}"
    finally:
        await g.close()


@mcp.tool
async def thunder_ghost(url: str) -> str:
    """Protocol-level fetch: raw response status + headers, with Chrome's
    exact TLS/JA3 fingerprint. Use to check a page's real behavior under
    browser-grade conditions."""
    g = Ghost()
    try:
        r = await g.browse(url, retries=2)
        if r is None:
            return "no response"
        interesting = {k: v for k, v in (r.headers or {}).items()
                        if k.lower() in ("server", "cf-ray", "cf-mitigated",
                                         "content-type", "set-cookie",
                                         "x-frame-options", "location")}
        return (f"status: {r.status_code}\n"
                f"handshake: chrome-true TLS (curl_cffi)\n"
                f"headers: {interesting}")
    except Exception as e:
        return f"ghost fetch failed: {e}"
    finally:
        await g.close()


@mcp.tool
async def thunder_feel(url: str) -> str:
    """Check a target's bot posture: what a site does to a browser-true
    request vs a plain one. Returns the verdict for both."""
    import httpx
    g = Ghost()
    plain_status = None
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            plain = await c.get(url)
            plain_status = plain.status_code
    except Exception:
        plain_status = "blocked/failed"
    try:
        r = await g.browse(url, retries=2)
        th_status = r.status_code if r is not None else "blocked/failed"
        wall = "captcha" in (r.text[:3000].lower() if r is not None else "")
    except Exception:
        th_status, wall = "blocked/failed", False
    finally:
        await g.close()
    verdict = ("site appears open" if not wall else
               "site shows a CAPTCHA wall to this request's IP")
    return (f"plain python request: {plain_status}\n"
            f"thunder ghost request: {th_status}\n"
            f"bot-wall: {'yes' if wall else 'no'} — {verdict}\n"
            "note: hard targets (Amazon, Google) weigh IP reputation; "
            "pair Thunder with a residential proxy for those.")


@mcp.tool
async def thunder_solve(page_url: str, sitekey: str,
                        challenge_type: str = "recaptcha") -> str:
    """Solve a CAPTCHA and return the token, using the solver key
    configured on this server (CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY).
    challenge_type: recaptcha | hcaptcha | turnstile."""
    from thunder.captcha import SolverBridge
    bridge = SolverBridge()
    if not bridge.available():
        return ("no solver key configured on this endpoint. "
                "Owner: set CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY. "
                "Users: Thunder still avoids most challenges locally with "
                "skin + hand — pip install thunder-agent.")
    import httpx

    class FakePage:
        url = page_url

        async def evaluate(self, _):
            return True

    async with httpx.AsyncClient(timeout=120) as c:
        if bridge.capsolver:
            types = {"recaptcha": "ReCaptchaV2TaskProxyLess",
                     "hcaptcha": "HCaptchaTaskProxyLess",
                     "turnstile": "AntiTurnstileTaskProxyLess"}
            token = await bridge._capsolver(c, {
                "type": types.get(challenge_type, types["recaptcha"]),
                "websiteURL": page_url, "websiteKey": sitekey})
        else:
            token = await bridge._twocaptcha(c, challenge_type,
                                             page_url, sitekey)
    if not token:
        return "solver returned no token — check the sitekey or key balance"
    return f"solved. token:\n{token}"


@mcp.tool
async def thunder_open(url: str) -> str:
    """Full human-browser automation (stealth Chrome, mouse tremor, human
    typing) runs on YOUR machine, not this shared endpoint. This tool
    returns exactly how: one pip command + one MCP config. The hosted
    tools thunder_read / thunder_search / thunder_ghost cover
    protocol-level work right now."""
    return (
        "Thunder's full human body runs locally:\n\n"
        "  pip install thunder-agent\n"
        "  thunder demo\n\n"
        "MCP config for Claude Desktop / any MCP client:\n"
        '{ "mcpServers": { "thunder": {\n'
        '    "command": "pipx",\n'
        '    "args": ["run", "thunder-agent", "thunder-mcp"] } } }\n\n'
        "This hosted endpoint gives you thunder_search, thunder_read, "
        "thunder_ghost, thunder_feel and thunder_solve with zero setup.")


if __name__ == "__main__":
    mcp.run(transport="streamable-http",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "8000")),
            path="/mcp")
