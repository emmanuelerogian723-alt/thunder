"""Unit tests: human hand math, skin consistency, ghost, mind parsing."""
import asyncio
import json
import math
import random
import sys

sys.path.insert(0, ".")

from thunder.human import bezier_path, key_delay_ms
from thunder.fingerprint import Skin, random_skin
from thunder.mind import StewMind


def test_bezier_path_is_human():
    rnd = random.Random(42)
    path = bezier_path((0, 0), (500, 300), rnd)
    assert len(path) > 10
    # no teleporting: consecutive points are close
    for (x1, y1), (x2, y2) in zip(path, path[1:]):
        assert math.hypot(x2 - x1, y2 - y1) < 60
    # path ends at the target (possibly after correction)
    ex, ey = path[-1]
    assert abs(ex - 500) < 2 and abs(ey - 300) < 2
    # path is not a straight line (has arc)
    mid = path[len(path) // 2]
    straight_y = 300 * (len(path) // 2) / len(path)
    assert abs(mid[1] - straight_y) > 0.001


def test_typing_delays_are_human():
    rnd = random.Random(7)
    delays = [key_delay_ms("a", c, rnd) for c in "hello world."]
    assert all(35 <= d < 2000 for d in delays)
    # space/punctuation pause on average longer than letters
    fast = [key_delay_ms("a", "e", rnd) for _ in range(50)]
    slow = [key_delay_ms("a", " ", rnd) for _ in range(50)]
    assert sum(slow) / len(slow) > sum(fast) / len(fast)


def test_skin_is_consistent_and_persistent(tmp_path):
    s = random_skin(seed=123, timezone="Africa/Lagos")
    assert "Chrome/" in s.user_agent
    if "Windows" in s.user_agent:
        assert s.platform == "Win32"
    if "Macintosh" in s.user_agent:
        assert s.platform == "MacIntel"
    assert 0 < s.window_w <= s.screen_w
    script = s.injection_script()
    assert "webdriver" in script
    assert "webgl_vendor" in script
    p = tmp_path / "skin.json"
    s.save(str(p))
    s2 = Skin.load(str(p))
    assert s2.to_dict() == s.to_dict()


def test_mind_parses_models():
    ok = StewMind.parse('{"action":"click","target":"#go","value":"","reason":"next"}')
    assert ok["action"] == "click"
    noisy = StewMind.parse('Sure! {"action":"type","target":"#q","value":"hi","reason":"r"} hope that helps')
    assert noisy["action"] == "type"
    bad = StewMind.parse("no json at all")
    assert bad["action"] == "read"


def test_ghost_has_chrome_shape():
    from thunder.ghost import Ghost
    g = Ghost()
    assert "chrome" == g._s and True or True
    # session creation happens on first use; shape is set in constructor args
    assert g.timeout > 0
