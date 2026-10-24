"""Thunder MCP server — let ANY AI agent drive a human body.

Hand-rolled Model Context Protocol (JSON-RPC 2.0 over stdio),
zero exotic dependencies. Works with Claude Desktop, Cursor,
STEW, and any MCP client:

    # claude_desktop_config.json / any MCP config
    {
      "mcpServers": {
        "thunder": {
          "command": "python", "args": ["-m", "thunder.mcp_server"]
        }
      }
    }

Tools exposed:
  thunder_open(url)          open a page in a human-shaped browser
  thunder_read()             structured page outline (for the LLM)
  thunder_click(selector)    human-hand click (bezier + timing)
  thunder_type(selector,text) human-hand typing (cadence + typos)
  thunder_scroll(amount)     eased scroll with reading pauses
  thunder_look()            screenshot path
  thunder_ghost(url)         TLS-true HTTP fetch (curl_cffi)
  thunder_captcha()          detect the challenge on this page
  thunder_think(goal)        stewmind decides the next action
  thunder_rest()             close the body (state persists)
  thunder_search(query, engine=auto|google|bing|duckduckgo)
  thunder_feel(url)          target's bot posture: plain vs ghost
  thunder_identity(file?)    export / wear a real fingerprint
  thunder_human_read(sec)    read the page like a human
  thunder_challenge()        keyless CAPTCHA counter (v0.5)

Run Thunder only on systems and accounts you are authorized to use.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from thunder.body import Body
from thunder.captcha import senses, SolverBridge
from thunder.ghost import Ghost
from thunder.mind import StewMind

TOOLS = [
    {"name": "thunder_open",
     "description": "Open a URL in Thunder's human-shaped browser body.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": ["url"]}},
    {"name": "thunder_read",
     "description": "Read the current page: title, url, text, clickable elements.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "thunder_click",
     "description": "Click like a human (bezier mouse path + human timing).",
     "inputSchema": {"type": "object",
                     "properties": {"selector": {"type": "string"}},
                     "required": ["selector"]}},
    {"name": "thunder_type",
     "description": "Type like a human (inter-key delays, rare typos, pauses).",
     "inputSchema": {"type": "object",
                     "properties": {"selector": {"type": "string"},
                                    "text": {"type": "string"}},
                     "required": ["selector", "text"]}},
    {"name": "thunder_scroll",
     "description": "Scroll with human easing and reading pauses.",
     "inputSchema": {"type": "object",
                     "properties": {"amount": {"type": "number",
                                               "default": 600}}}},
    {"name": "thunder_look",
     "description": "Take a screenshot of the current page; returns the file path.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "thunder_ghost",
     "description": "Fetch a URL with a real browser TLS fingerprint (curl_cffi).",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": ["url"]}},
    {"name": "thunder_captcha",
     "description": "Detect CAPTCHA challenges on the current page.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "thunder_think",
     "description": "Ask stewmind-1.7b for the next action toward a goal.",
     "inputSchema": {"type": "object",
                     "properties": {"goal": {"type": "string"}},
                     "required": ["goal"]}},
    {"name": "thunder_rest",
     "description": "Close the body. Cookies/fingerprint persist for next time.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "thunder_search",
     "description": "Search the web (Google, Bing or DuckDuckGo — auto "
                    "falls back ddg->bing->google) with a browser-true "
                    "TLS handshake. The result names the engine used.",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string"},
                                    "limit": {"type": "number",
                                              "default": 5},
                                    "engine": {"type": "string",
                                               "enum": ["auto", "google",
                                                        "bing",
                                                        "duckduckgo"],
                                               "default": "auto"}},
                     "required": ["query"]}},
    {"name": "thunder_feel",
     "description": "Probe a URL's bot posture: plain request vs thunder "
                    "ghost (TLS-true) request.",
     "inputSchema": {"type": "object",
                     "properties": {"url": {"type": "string"}},
                     "required": ["url"]}},
    {"name": "thunder_identity",
     "description": "Export the live fingerprint, or wear one from a "
                    "fingerprint JSON file (Skin.imitate).",
     "inputSchema": {"type": "object",
                     "properties": {"imitate_file": {"type": "string"}}}},
    {"name": "thunder_human_read",
     "description": "Read the current page like a human: burst scroll, "
                    "reading pauses, idle hand drift.",
     "inputSchema": {"type": "object",
                     "properties": {"seconds": {"type": "number",
                                                "default": 12}}}},
    {"name": "thunder_challenge",
     "description": "Detect and counter any CAPTCHA/challenge on the "
                    "current page (Turnstile/reCAPTCHA/hCaptcha/Amazon/"
                    "CF interstitial) — keyless.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class ThunderMCP:
    def __init__(self):
        self.body: Body | None = None
        self.ghost: Ghost | None = None
        self.mind: StewMind | None = None

    async def _ensure_body(self):
        if self.body is None or self.body.page is None:
            self.body = Body(profile=os.getenv("THUNDER_PROFILE", "agent"))
            await self.body.wake()

    async def call(self, name: str, args: dict) -> dict:
        if name == "thunder_open":
            await self._ensure_body()
            await self.body.go(args["url"])
            return {"ok": True, "url": self.body.page.url,
                    "title": await self.body.page.title()}
        if name == "thunder_read":
            await self._ensure_body()
            return await self.body.read()
        if name == "thunder_click":
            await self._ensure_body()
            await self.body.click(args["selector"])
            await asyncio.sleep(1.0)
            return {"ok": True, "url": self.body.page.url}
        if name == "thunder_type":
            await self._ensure_body()
            await self.body.type(args["selector"], args["text"])
            return {"ok": True}
        if name == "thunder_scroll":
            await self._ensure_body()
            await self.body.scroll(args.get("amount", 600))
            return {"ok": True}
        if name == "thunder_look":
            await self._ensure_body()
            return {"ok": True, "screenshot": await self.body.look()}
        if name == "thunder_ghost":
            if self.ghost is None:
                self.ghost = Ghost()
            r = await self.ghost.get(args["url"])
            text = r.text if hasattr(r, "text") else str(r)
            return {"ok": True, "status": getattr(r, "status_code", None),
                    "body": text[:6000]}
        if name == "thunder_captcha":
            await self._ensure_body()
            ch = await senses(self.body.page)
            ch["solver"] = SolverBridge().available()
            return ch
        if name == "thunder_think":
            if self.mind is None:
                self.mind = StewMind()
            await self._ensure_body()
            page = await self.body.read()
            d = self.mind.think(args["goal"], page)
            return d
        if name == "thunder_rest":
            if self.body:
                await self.body.rest()
            return {"ok": True}
        if name == "thunder_search":
            from thunder.search import web_search
            return {"ok": True, "results": await web_search(
                args["query"], int(args.get("limit", 5)),
                engine=str(args.get("engine", "auto")))}
        if name == "thunder_feel":
            from thunder.search import feel
            return {"ok": True, "report": await feel(args["url"])}
        if name == "thunder_identity":
            from thunder.fingerprint import Skin
            await self._ensure_body()
            if args.get("imitate_file"):
                skin = Skin.imitate(json.load(open(args["imitate_file"])))
                await self.body.rest()
                self.body = Body(
                    profile=os.getenv("THUNDER_PROFILE", "agent"), skin=skin)
                await self.body.wake()
            fp = await self.body.export_fingerprint()
            return {"ok": True, "fingerprint": fp}
        if name == "thunder_human_read":
            await self._ensure_body()
            await self.body.read_like_human(float(args.get("seconds", 12)))
            return {"ok": True}
        if name == "thunder_challenge":
            from thunder.captcha import ChallengeResolver
            await self._ensure_body()
            verdict = await ChallengeResolver().resolve(self.body.page,
                                                        body=self.body)
            return verdict
        raise ValueError(f"unknown tool {name}")


async def serve_stdio():
    api = ThunderMCP()
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    proto = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: proto, sys.stdin)

    def send(obj: dict):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "thunder", "version": __import__("thunder").__version__}}})
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            try:
                result = await api.call(req["params"]["name"],
                                        req["params"].get("arguments", {}))
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text",
                                 "text": json.dumps(result, default=str)[:20000]}]}})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": rid, "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": f"thunder error: {e}"}]}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})


def main():
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
