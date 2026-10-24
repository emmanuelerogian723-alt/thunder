"""Thunder CLI.

    thunder browse https://example.com     # open with the human body
    thunder ghost https://example.com      # TLS-true fetch
    thunder think "find the pricing page"  # stewmind's next action
    thunder serve                          # run the MCP server (stdio)
    thunder demo                           # full showcase run
    thunder app                            # launch the full web app
    thunder identity --out my.json         # export your fingerprint
    thunder identity --imitate my.json     # wear YOUR fingerprint
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

    i = sub.add_parser("identity", help="export or imitate a real fingerprint")
    i.add_argument("--out", default=None, help="save the exported fingerprint JSON")
    i.add_argument("--imitate", default=None,
                   help="wear this fingerprint JSON (yours, from browserleaks etc.)")

    sub.add_parser("serve", help="run the MCP server over stdio")
    sub.add_parser("demo", help="run the full Thunder showcase")

    a = p.parse_args(argv)

    if a.cmd == "serve":
        from thunder.mcp_server import main as serve
        serve()
        return 0

    if a.cmd == "app":
        try:
            import uvicorn  # noqa: F401
        except ImportError:
            print("The web app needs server deps. Install them first:\n"
                  "    pip install thunder-agent[app]")
            return 1
        import threading, webbrowser
        from thunder.webapp.server import app as webapp
        url = f"http://127.0.0.1:{a.port}"
        if not a.no_browser:
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        print(f"\n⚡ Thunder app running at {url}\n"
              "   Ctrl+C to stop.\n")
        import uvicorn
        uvicorn.run(webapp, host="127.0.0.1", port=a.port, log_level="warn")
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

    if a.cmd == "identity":
        from thunder.body import Body
        from thunder.fingerprint import Skin

        async def run():
            if a.imitate:
                skin = Skin.imitate(json.load(open(a.imitate)))
                body = Body(skin=skin)
                await body.wake("https://example.com")
                fp = await body.export_fingerprint()
                print(json.dumps(fp, indent=2))
                ok = fp.get("webdriver") in (None, False)
                print("\nimitation live:", "OK" if ok else "FAIL")
                await body.rest()
                return 0 if ok else 1
            body = Body()
            await body.wake("https://example.com")
            fp = await body.export_fingerprint()
            print(json.dumps(fp, indent=2))
            if a.out:
                json.dump(fp, open(a.out, "w"), indent=2)
                print(f"\nsaved -> {a.out}")
                print("reuse anywhere: Body(skin=Skin.imitate(json.load(open('%s'))))" % a.out)
            await body.rest()
        rc = asyncio.run(run())
        return rc if isinstance(rc, int) else 0

    if a.cmd == "demo":
        from thunder.demo import run as run_demo
        asyncio.run(run_demo())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
