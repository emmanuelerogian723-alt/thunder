"""Stealth regression: every known tell must stay covered. (sync, no pytest-asyncio)"""
import asyncio
import pytest
from thunder.body import Body
from thunder.proxy import _normalize, ProxyManager

@pytest.fixture(scope="module")
def body():
    b = Body(profile="stealth-test", headless=True)
    asyncio.run(b.wake("https://example.com"))
    yield b
    asyncio.run(b.rest())

def test_webdriver_erased(body):
    r = asyncio.run(body.page.evaluate(
        "(() => ({w: navigator.webdriver, scan: (() => { let f=null;"
        " for (const k in navigator) if (/web/i.test(k)&&/driver/i.test(k)) f=k;"
        " return f; })()}))()"))
    assert r["w"] in (None, False) and r["scan"] is None

def test_plugins(body):
    r = asyncio.run(body.page.evaluate(
        "(() => ({pa: navigator.plugins instanceof PluginArray,"
        " l: navigator.plugins.length}))()"))
    assert r["pa"] is True and r["l"] == 5

def test_headless_pack(body):
    r = asyncio.run(body.page.evaluate(
        "(() => ({ow: window.outerWidth, oh: window.outerHeight,"
        " cd: screen.colorDepth, ch: !!window.chrome,"
        " bt: typeof navigator.getBattery}))()"))
    assert r["ow"] > 0 and r["oh"] > 0 and r["cd"] == 24 and r["ch"] is True
    assert r["bt"] == "function"

def test_webgl(body):
    r = asyncio.run(body.page.evaluate(
        """(() => { const c=document.createElement('canvas');
        const gl=c.getContext('webgl2')||c.getContext('webgl');
        const ext=gl.getExtension('WEBGL_debug_renderer_info');
        return {v: gl.getParameter(ext.UNMASKED_VENDOR_WEBGL),
                r: gl.getParameter(ext.UNMASKED_RENDERER_WEBGL),
                d: gl.getParameter(37446)}; })()"""))
    assert r["v"] == body.skin.webgl_vendor
    assert r["d"] == r["r"]
    assert "SwiftShader" not in r["r"]

def test_proxy_normalize():
    assert _normalize("host:1234")["server"] == "http://host:1234"
    p = _normalize("user:pass@1.2.3.4:8080")
    assert p["server"] == "http://1.2.3.4:8080" and p["username"] == "user"
    assert _normalize("socks5://h:1")["server"] == "socks5://h:1"

def test_proxy_sticky_rotation():
    pm = ProxyManager([{"server": "http://a:1"}, {"server": "http://b:2"}])
    a = pm.pick("ada"); b = pm.pick("ada")
    assert a == b
    c = pm.pick("bob")
    assert c["server"] != a["server"]
    pm.mark_bad(a, cooldown=9999)
    assert pm.pick("ada")["server"] == c["server"]
