"""The human hand — mouse, typing, scroll, and idle behavior.

Thunder's Body moves like a person because the hand does:
  * Bezier-curve mouse paths with overshoot + micro-corrections
  * Fitts-law click timing (farther = slower, with variance)
  * Keystrokes drawn from a lognormal inter-key distribution
    with realistic bursts, pauses and occasional typos+fixes
  * eased scrolling with reading pauses
  * idle micro-movements (a human never freezes)

    from thunder.human import Hand
    import asyncio
    h = Hand(page)               # a playwright page
    await h.move_to(400, 320)
    await h.click("#login")
    await h.type("#email", "me@x.com")
"""
from __future__ import annotations

import asyncio
import math
import random
from typing import List, Sequence, Tuple

Point = Tuple[float, float]


def bezier_path(start: Point, end: Point, rnd: random.Random,
                overshoot_prob: float = 0.28) -> List[Point]:
    """A human mouse path: bezier curve(s), occasional overshoot
    past the target, then small corrective moves back to it."""
    x0, y0 = start
    x1, y1 = end
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 6:
        return [start, end]

    target = end
    if rnd.random() < overshoot_prob and dist > 80:
        ang = math.atan2(y1 - y0, x1 - x0) + rnd.uniform(-0.35, 0.35)
        over = min(dist * 0.22, 90) * rnd.uniform(0.4, 1.0)
        target = (x1 + math.cos(ang) * over, y1 + math.sin(ang) * over)

    pts: List[Point] = []
    # 1-2 curve segments (humans change curvature mid-move)
    segments = 2 if dist > 300 else 1
    cur = start
    for s in range(segments):
        t_end = target if s == segments - 1 else (
            (start[0] + target[0]) / 2 + rnd.uniform(-dist * 0.18, dist * 0.18),
            (start[1] + target[1]) / 2 + rnd.uniform(-dist * 0.18, dist * 0.18),
        )
        # control points off-axis → natural arc
        c1 = (cur[0] + (t_end[0] - cur[0]) * 0.25 + rnd.uniform(-40, 40),
              cur[1] + (t_end[1] - cur[1]) * 0.25 + rnd.uniform(-30, 30))
        c2 = (cur[0] + (t_end[0] - cur[0]) * 0.75 + rnd.uniform(-40, 40),
              cur[1] + (t_end[1] - cur[1]) * 0.75 + rnd.uniform(-30, 30))
        steps = max(8, int(dist / (14 * segments)) + rnd.randint(0, 8))
        for i in range(1, steps + 1):
            t = i / steps
            # ease in-out: slow start, fast middle, slow landing
            te = t * t * (3 - 2 * t)
            mt = 1 - te
            x = mt**3 * cur[0] + 3 * mt**2 * te * c1[0] + 3 * mt * te**2 * c2[0] + te**3 * t_end[0]
            y = mt**3 * cur[1] + 3 * mt**2 * te * c1[1] + 3 * mt * te**2 * c2[1] + te**3 * t_end[1]
            # human jitter, small and speed-proportional
            jit = 1.0 + te * 1.5
            pts.append((x + rnd.uniform(-1.6, 1.6) * jit,
                        y + rnd.uniform(-1.2, 1.2) * jit))
        cur = t_end
    # corrective sub-moves toward the real target
    if target != end:
        tx, ty = target
        for _ in range(2):
            tx += (end[0] - tx) * rnd.uniform(0.55, 0.9)
            ty += (end[1] - ty) * rnd.uniform(0.55, 0.9)
            pts.append((tx, ty))
        pts.append(end)
    else:
        pts[-1] = end
    return pts


def key_delay_ms(prev: str, cur: str, rnd: random.Random) -> float:
    """Inter-key delay in ms, drawn from human distributions.
    Space and punctuation get small pauses; unfamiliar keys take
    longer; occasionally a real 'thinking' pause."""
    base = rnd.gauss(88, 34)
    if cur in " .,;:'\"":
        base = rnd.gauss(150, 60)
    if cur.isupper() or (prev.islower() and cur.isdigit()):
        base *= 1.35
    if rnd.random() < 0.02:            # micro hesitation
        base += rnd.uniform(220, 700)
    return max(35, base)


class Hand:
    """The human hand bound to a Playwright page."""

    def __init__(self, page, seed: int | None = None):
        self.page = page
        self.rnd = random.Random(seed if seed is not None else random.randint(1, 10**9))
        self._pos: Point = (400.0, 300.0)
        self.speed = 1.0

    # ── low-level primitives ───────────────────────────────────────
    async def _move(self, x: float, y: float, steps_pause: float = 0.004):
        path = bezier_path(self._pos, (x, y), self.rnd)
        for (px, py) in path:
            await self.page.mouse.move(px, py)
            self._pos = (px, py)
            await asyncio.sleep(steps_pause * self.rnd.uniform(0.6, 1.6) * self.speed)

    async def move_to(self, x: float, y: float):
        await self._move(x, y)

    async def hover(self, selector: str):
        box = await self.page.locator(selector).bounding_box()
        if not box:
            raise ValueError(f"no element for {selector!r}")
        await self._move(box["x"] + box["width"] * 0.5 + self.rnd.uniform(-3, 3),
                         box["y"] + box["height"] * 0.5 + self.rnd.uniform(-2, 2))

    async def click(self, selector_or_point, button: str = "left"):
        if isinstance(selector_or_point, str):
            await self.hover(selector_or_point)
        else:
            await self._move(*selector_or_point)
        await asyncio.sleep(self.rnd.uniform(0.02, 0.09))
        await self.page.mouse.down(button=button)
        await asyncio.sleep(self.rnd.uniform(0.045, 0.12))   # human press duration
        await self.page.mouse.up(button=button)

    async def type(self, selector: str, text: str, typo_prob: float = 0.02):
        """Type like a person: bursts, pauses, rare typos fixed with backspace."""
        await self.click(selector)
        prev = ""
        for ch in text:
            if self.rnd.random() < typo_prob and ch not in " .@":
                wrong = self.rnd.choice("qwertyuiopasdfghjklzxcvbnm")
                await self.page.keyboard.type(wrong, delay=int(key_delay_ms(prev, wrong, self.rnd)))
                await asyncio.sleep(self.rnd.uniform(0.15, 0.4))
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(self.rnd.uniform(0.05, 0.15))
            await self.page.keyboard.type(ch, delay=int(key_delay_ms(prev, ch, self.rnd)))
            prev = ch
            if self.rnd.random() < 0.01:                       # thinking pause
                await asyncio.sleep(self.rnd.uniform(0.3, 1.2))

    async def press(self, key: str):
        await asyncio.sleep(self.rnd.uniform(0.1, 0.3))
        await self.page.keyboard.press(key)

    async def scroll(self, amount: int = 600, reads: bool = True):
        """Eased scroll with human reading pauses."""
        remaining = abs(amount)
        direction = -1 if amount < 0 else 1
        while remaining > 0:
            chunk = int(min(remaining, self.rnd.randint(140, 420)))
            await self.page.mouse.wheel(0, chunk * direction)
            remaining -= chunk
            await asyncio.sleep(self.rnd.uniform(0.06, 0.2))
            if reads and self.rnd.random() < 0.4:
                await asyncio.sleep(self.rnd.uniform(0.4, 1.6))  # reading

    async def idle(self, seconds: float = 2.0):
        """A human never freezes — drift the cursor slightly."""
        end = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < end:
            await self._move(
                self._pos[0] + self.rnd.uniform(-90, 90),
                self._pos[1] + self.rnd.uniform(-60, 60),
                steps_pause=0.01)
            await asyncio.sleep(self.rnd.uniform(0.3, 0.9))
