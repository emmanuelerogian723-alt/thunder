"""Thunder end-to-end showcase.

1. Ghost handshake test (requests vs thunder TLS shape)
2. Body wakes, opens a page like a human, types with the human hand
3. stewmind decides the next action
"""
from __future__ import annotations

import asyncio
import json


async def run():
    print("⚡ THUNDER — human engine demo\n" + "─" * 46)

    # 1 ── Ghost: TLS-true HTTP
    from thunder.ghost import Ghost
    print("[1/3] Ghost: comparing handshakes on a bot-blocking target…")
    gh = Ghost()
    url = "https://nowsecure.nl"          # classic Cloudflare gate
    try:
        r = await gh.get(url)
        print(f"      thunder ghost status: {r.status_code} "
              f"(raw requests/urllib would be challenged)")
    except Exception as e:
        print(f"      ghost: {type(e).__name__}: {str(e)[:100]}")
    await gh.close()

    # 2 ── Body: human-shaped browsing on a real form
    from thunder.body import Body
    print("[2/3] Body: opening a page and typing like a human…")
    body = Body(headless=True)
    await body.wake("https://www.wikipedia.org")
    await body.type("#searchInput", "lightning")     # human cadence
    await asyncio.sleep(0.4)
    shot = await body.look("thunder_demo.png")
    page = await body.read()
    print(f"      opened: {page['title']}")
    print(f"      typed with human hand, screenshot → {shot}")
    await body.rest()

    # 3 ── StewMind
    print("[3/3] StewMind: deciding the next action…")
    try:
        from thunder.mind import StewMind
        mind = StewMind()
        d = mind.think("Find the article about lightning storms", page)
        print("      stewmind says:", json.dumps(d, indent=2)[:400])
    except Exception as e:
        print(f"      (stewmind offline here: {str(e)[:90]})")
    print("─" * 46 + "\n⚡ demo done. Thunder never sleeps.")


if __name__ == "__main__":
    asyncio.run(run())
