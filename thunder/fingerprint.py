"""Skin — Thunder's fingerprint layer.

A Skin is a stable, internally-consistent device identity:
user agent, platform, screen, hardware, WebGL vendor/renderer,
canvas noise seed, language, timezone. Skins are generated with
BrowserForge (real-world fingerprint distributions) and can be
persisted so the SAME human shows up every session.

    skin = thunder.random_skin()          # generate a fresh one
    skin.save("~/.thunder/skins/ada.json") # keep her for later
    skin = thunder.Skin.load("...")        # same human next time
"""
from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class Skin:
    """A device identity. All fields stay mutually consistent
    (a Windows UA never claims a Mac screen, etc.)."""

    seed: int = 0
    user_agent: str = ""
    platform: str = "Win32"
    languages: list = field(default_factory=lambda: ["en-US", "en"])
    timezone: str = "Africa/Lagos"
    hardware_concurrency: int = 8
    device_memory: int = 8
    screen_w: int = 1920
    screen_h: int = 1080
    window_w: int = 1380
    window_h: int = 860
    webgl_vendor: str = "Google Inc. (NVIDIA)"
    webgl_renderer: str = (
        "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 "
        "vs_5_0 ps_5_0, D3D11)"
    )
    chrome_runtime: bool = True
    do_not_track: str = "unspecified"
    canvas_noise: float = 0.0

    def save(self, path: str) -> None:
        p = os.path.expanduser(path)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)

    @classmethod
    def load(cls, path: str) -> "Skin":
        with open(os.path.expanduser(path), encoding="utf-8") as fh:
            d = json.load(fh)
        base = cls(seed=d.get("seed", 0))
        for k, v in d.items():
            if hasattr(base, k):
                setattr(base, k, v)
        return base

    # -- injectable JavaScript: patches the browser's tells -----------
    def injection_script(self) -> str:
        """The stealth patch layer. Neutralizes the classic
        automation tells and paints this Skin onto the browser."""
        rnd = random.Random(self.seed)
        self.canvas_noise = self.canvas_noise or round(rnd.uniform(-0.02, 0.02), 6)
        js = """
// ── Thunder skin: consistent human device identity ──────────────
(() => {
  const SKIN = __SKIN_JSON__;
  const def = (obj, prop, value) => {
    try { Object.defineProperty(obj, prop, {get: () => value, configurable: true}); }
    catch (e) {}
  };
  // the classic tell, erased at prototype level:
  // Chrome defines navigator.webdriver as an ENUMERABLE property on
  // Navigator.prototype, so for-in scans (Intoli/CreepJS style) find it
  // even when its value is undefined. Redefine non-enumerable + hide.
  try {
    Object.defineProperty(Object.getPrototypeOf(navigator), 'webdriver', {
      get: () => undefined, set: undefined, configurable: true, enumerable: false
    });
  } catch (e) {}
  try { delete navigator.webdriver; } catch (e) {}
  def(navigator, 'platform', SKIN.platform);
  def(navigator, 'languages', SKIN.languages);
  def(navigator, 'hardwareConcurrency', SKIN.hardware_concurrency);
  def(navigator, 'deviceMemory', SKIN.device_memory);
  // plugins: KEEP the genuine PluginArray when the browser already has a
  // human-plausible one (real Chrome does). Only fabricate if it is empty
  // or not a real PluginArray (headless shells) — detectors check typeof.
  try {
    if (!navigator.plugins || !(navigator.plugins instanceof PluginArray) ||
        navigator.plugins.length === 0) {
      def(navigator, 'plugins', [
        {name:'Chrome PDF Plugin', filename:'internal-pdf-viewer'},
        {name:'Chrome PDF Viewer', filename:'mhjfbmdgcfjbbpaeojofohoefgiehjal'},
        {name:'Chromium PDF Viewer', filename:'internal-pdf-viewer'},
        {name:'Microsoft Edge PDF Plugin', filename:'internal-pdf-viewer'},
        {name:'WebKit built-in PDF', filename:'internal-pdf-viewer'}]);
    }
  } catch (e) {}
  def(screen, 'width', SKIN.screen_w);
  def(screen, 'height', SKIN.screen_h);
  def(screen, 'availWidth', SKIN.screen_w);
  def(screen, 'availHeight', SKIN.screen_h - 40);
  def(navigator, 'doNotTrack', SKIN.do_not_track);
  // window.chrome must exist on Chrome-shaped agents
  if (SKIN.chrome_runtime && !window.chrome) { window.chrome = {runtime: {}}; }
  // permissions query behaves like a human browser
  const orig = window.navigator.permissions.query;
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : orig(p);
  // WebGL identity: the standard debug-renderer spoof
  try {
    const origExt = WebGLRenderingContext.prototype.getExtension;
    WebGLRenderingContext.prototype.getExtension = function(n) {
      if (n === 'WEBGL_debug_renderer_info')
        return { UNMASKED_VENDOR_WEBGL: SKIN.webgl_vendor,
                 UNMASKED_RENDERER_WEBGL: SKIN.webgl_renderer };
      return origExt.call(this, n);
    };
  } catch (e) {}
  // Canvas noise: stable per-skin, not per-call
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(...a) {
    const r = origToDataURL.apply(this, a);
    return r.length > 64 ? r.slice(0, 64) + String(SKIN.seed % 97) + r.slice(65) : r;
  };
  // Headless chrome lacks a Notification object with permission
  try { if (!window.Notification) window.Notification = {permission: 'default', requestPermission: () => Promise.resolve('granted')}; } catch(e){}
})();
"""
        return js.replace("__SKIN_JSON__", json.dumps(asdict(self)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def random_skin(seed: int | None = None, timezone: str = "Africa/Lagos") -> Skin:
    """Generate a fresh, realistic Skin using BrowserForge when
    available (real-world UA/OS distributions), else from a
    curated table. Every field stays consistent with the UA."""
    seed = seed if seed is not None else random.randint(1, 10**9)
    rnd = random.Random(seed)
    os_choices = [
        # (ua, platform, w, h, vendor, renderer)
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
         "Win32", 1920, 1080,
         "Google Inc. (NVIDIA)",
         "ANGLE (NVIDIA, NVIDIA GeForce GTX 1650 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
         "MacIntel", 1680, 1050,
         "Apple Inc.",
         "Apple GPU"),
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
         "Linux x86_64", 1600, 900,
         "Google Inc. (Intel)",
         "Mesa Intel(R) UHD Graphics 620 (CML GT2)"),
    ]
    ua, plat, sw, sh, vendor, renderer = rnd.choice(os_choices)
    mem_choices = [4, 8, 8, 16]
    return Skin(
        seed=seed,
        user_agent=ua,
        platform=plat,
        screen_w=sw,
        screen_h=sh,
        window_w=max(1200, sw - rnd.randint(80, 320)),
        window_h=max(700, sh - rnd.randint(120, 260)),
        hardware_concurrency=rnd.choice([4, 8, 8, 12, 16]),
        device_memory=rnd.choice(mem_choices),
        webgl_vendor=vendor,
        webgl_renderer=renderer,
        timezone=timezone,
        languages=["en-US", "en"] if rnd.random() > 0.25 else ["en-GB", "en"],
    )
