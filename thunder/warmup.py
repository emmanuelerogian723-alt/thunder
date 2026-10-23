"""Warmup — Thunder's answer to behavioral-ML blocking.

Big targets score the WHOLE session: a profile that lands on the target
as its first-ever action, with no history and no reading behavior, reads
as automation no matter how good the fingerprint is. Warmup makes the
arrival look organic:

    body = Body(profile="ada")
    await body.warmup()              # 2-4 light reads, idle drift, real scroll
    await body.go("https://target.com")   # now arrives like a returning human

Light, low-bandwidth sites only — no account footprint, no side effects.
"""
from __future__ import annotations

import asyncio
import random

from .body import Body

WARMUP_SITES = [
    "https://en.wikipedia.org/wiki/Special:Random",
    "https://example.com",
    "https://www.wikipedia.org",
    "https://httpbin.org/html",
]


async def warmup(body: Body, visits: int = 2) -> dict:
    """Age a fresh session with organic-looking light browsing."""
    result = {"visits": 0, "sites": []}
    for url in random.sample(WARMUP_SITES, min(visits, len(WARMUP_SITES))):
        try:
            await body.go(url)
            result["visits"] += 1
            result["sites"].append(url)
            await body.hand.idle(random.uniform(1.0, 2.5))
            if random.random() < 0.6:
                await body.hand.scroll(random.randint(200, 700))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        except Exception:
            continue          # warmup is best-effort; never block the mission
    return result
