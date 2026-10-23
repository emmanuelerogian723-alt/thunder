"""Browser-level integration test (skipped fast in CI without network)."""
import asyncio
import os
import sys

sys.path.insert(0, ".")

import pytest

from thunder.body import Body


@pytest.mark.asyncio
async def test_body_browses_and_types_like_a_human():
    body = Body(headless=True)
    await body.wake("https://example.com")
    title = await body.page.title()
    assert "Example" in title
    # automation tell is patched away
    wd = await body.page.evaluate("navigator.webdriver")
    assert wd in (None, False)
    shot = await body.look("/tmp/thunder_test_shot.png")
    assert os.path.getsize(shot) > 1000
    await body.rest()


@pytest.mark.asyncio
async def test_profile_persistence_keeps_same_human(tmp_path):
    os.environ["THUNDER_HOME"] = str(tmp_path)
    b1 = Body(profile="p1", headless=True)
    await b1.wake("https://example.com")
    ua1 = await b1.page.evaluate("navigator.userAgent")
    await b1.rest()
    b2 = Body(profile="p1", headless=True)
    await b2.wake("https://example.com")
    ua2 = await b2.page.evaluate("navigator.userAgent")
    assert ua1 == ua2            # same human came back
    await b2.rest()
