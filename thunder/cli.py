"""Thunder CLI.

    thunder browse https://example.com     # open with the human body
    thunder ghost https://example.com      # TLS-true fetch
    thunder think "find the pricing page"  # stewmind's next action
    thunder serve                          # run the MCP server (stdio)
    thunder demo                           # full showcase run
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


def main(argv=None):
    p = argparse.ArgumentParser(prog="thunder",
                                description="Thunder — the human engine for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("browse", help="open a URL with the human body")
    b.add_argument("url")
    b.add_argument("--shot", default=None)
    b.add_argument("--scroll", type=int, default=0)
    b.add_argument("--record", action="store_true", help="save a video")

    g = sub.add_parser("ghost", help="fetch with a browser TLS fingerprint")
    g.add_argument("url")
    g.add_argument("--head", action="store_true")

    t = sub.add_parser("think", help="stewmind decides the next action")
    t.add_argument("goal")
    t.add_argument("--endpoint", default=None)
    t.add_argument("--local", action="store_true")

    sub.add_parser("serve", help="run the MCP server over stdio")
    sub.add_parser("demo", help="run the full Thunder showcase")

    a = p.parse_args(argv)

    if a.cmd == "serve":
        from thunder.mcp_server import main as serve
        serve()
        return 0

    if a.cmd == "browse":
        from thunder.body import Body

        async def run():
            body = Body(headless=True, record_video=a.record)
            await body.wake(a.url)
            if a.scroll:
                await body.scroll(a.scroll)
            shot = a.shot or "thunder_shot.png"
            await body.look(shot)
            print(json.dumps({"url": body.page.url,
                              "title": await body.page.title(),
                              "screenshot": shot}, indent=2))
            await body.rest()
        asyncio.run(run())
        return 0

    if a.cmd == "ghost":
        from thunder.ghost import Ghost

        async def run():
            gh = Ghost()
            r = await gh.get(a.url)
            if a.head:
                print(json.dumps({"status": r.status_code,
                                  "headers": dict(r.headers)}, indent=2)[:2000])
            else:
                print(r.text[:4000])
            await gh.close()
        asyncio.run(run())
        return 0

    if a.cmd == "think":
        from thunder.body import Body
        from thunder.mind import StewMind

        async def run():
            mind = StewMind(endpoint=a.endpoint, local=a.local)
            body = Body()
            await body.wake()
            page = await body.read()
            print(json.dumps(mind.think(a.goal, page), indent=2))
            await body.rest()
        asyncio.run(run())
        return 0

    if a.cmd == "demo":
        from thunder.demo import run as run_demo
        asyncio.run(run_demo())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
