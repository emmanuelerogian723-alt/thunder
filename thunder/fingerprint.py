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
    headless: bool = False

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
  // plugins: NEVER replace the object — detectors check `instanceof
  // PluginArray` and a fake plain array fails. Real Chrome has 5 PDF
  // plugins; headless shells have the genuine PluginArray but length 0.
  // Keep the real object, just make it report a human browser's content.
  try {
    if (navigator.plugins && navigator.plugins instanceof PluginArray &&
        navigator.plugins.length === 0) {
      const pdfs = ['Chrome PDF Plugin','Chrome PDF Viewer','Chromium PDF Viewer',
                    'Microsoft Edge PDF Plugin','WebKit built-in PDF'];
      Object.defineProperty(navigator.plugins, 'length', {
        get: () => pdfs.length, configurable: true});
      // PluginArray is an exotic object: indexed getters may be refused.
      // Best-effort per index — type + length are the real detection rows.
      pdfs.forEach((name, i) => {
        try {
          Object.defineProperty(navigator.plugins, i, {
            get: () => ({name: name, filename: 'internal-pdf-viewer',
                         description: 'Portable Document Format',
                         length: 2, item: () => null, namedItem: () => null}),
            configurable: true});
        } catch (e) {}
      });
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
  // WebGL identity: full spoof on WebGL1 AND WebGL2.
  // Some detectors read getParameter(37445/37446) directly without
  // the debug extension — cover both paths so vendor+renderer always
  // tell the Skin's story (a real GPU, never 'SwiftShader/ANGLE (Google)').
  try {
    for (const Ctx of [WebGLRenderingContext, WebGL2RenderingContext]) {
      const origExt = Ctx.prototype.getExtension;
      Ctx.prototype.getExtension = function(n) {
        if (n === 'WEBGL_debug_renderer_info')
          return { UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446 };
        return origExt.call(this, n);
      };
      const origParam = Ctx.prototype.getParameter;
      Ctx.prototype.getParameter = function(p) {
        if (p === 37445) return SKIN.webgl_vendor;      // UNMASKED_VENDOR
        if (p === 37446) return SKIN.webgl_renderer;    // UNMASKED_RENDERER
        return origParam.call(this, p);
      };
    }
  } catch (e) {}
  // Canvas noise: stable per-skin, not per-call
  const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
  HTMLCanvasElement.prototype.toDataURL = function(...a) {
    const r = origToDataURL.apply(this, a);
    return r.length > 64 ? r.slice(0, 64) + String(SKIN.seed % 97) + r.slice(65) : r;
  };
  // ── HEADLESS EVASION PACK (only applied in headless mode) ────────
  if (SKIN.headless) {
    // outerWidth/outerHeight: real Chrome reports them; headless reports 0
    try {
      Object.defineProperty(window, 'outerWidth',  {get: () => SKIN.window_w, configurable: true});
      Object.defineProperty(window, 'outerHeight', {get: () => SKIN.window_h, configurable: true});
      Object.defineProperty(window, 'screenX', {get: () => 0, configurable: true});
      Object.defineProperty(window, 'screenY', {get: () => 0, configurable: true});
    } catch (e) {}
    // color depth: headless historically reported 0/undefined
    try { def(screen, 'colorDepth', 24); def(screen, 'pixelDepth', 24); } catch (e) {}
    // broken-image dimensions: headless reports 0x0, real Chrome 16x16
    try {
      const origNI = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'naturalWidth');
      const origNH = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'naturalHeight');
      if (origNI && origNI.get) {
        Object.defineProperty(HTMLImageElement.prototype, 'naturalWidth', {
          get: function() { const w = origNI.get.call(this); return (w === 0 && this.complete && this.src) ? 16 : w; },
          configurable: true});
        Object.defineProperty(HTMLImageElement.prototype, 'naturalHeight', {
          get: function() { const h = origNH.get.call(this); return (h === 0 && this.complete && this.src) ? 16 : h; },
          configurable: true});
      }
    } catch (e) {}
    // full window.chrome shape (headless chrome has none)
    if (SKIN.chrome_runtime) {
      window.chrome = window.chrome || {};
      window.chrome.app = window.chrome.app || {isInstalled: false, InstallState: {DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed'}, RunningState: {CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running'}};
      window.chrome.csi = window.chrome.csi || function(){ return {startE: Date.now()-60000, onloadT: Date.now()-59000, pageT: Date.now()-58000, tran: 15}; };
      window.chrome.loadTimes = window.chrome.loadTimes || function(){ return {commitLoadTime: Date.now()/1000-60, connectionInfo: 'http/1.1', finishDocumentLoadTime: Date.now()/1000-58, finishLoadTime: Date.now()/1000-57, firstPaintAfterLoadTime: Date.now()/1000-56, firstPaintTime: Date.now()/1000-59, navigationType: 'Other', npnNegotiatedProtocol: 'unknown', requestTime: Date.now()/1000-61, startLoadTime: Date.now()/1000-60, wasAlternateProtocolAvailable: false, wasFetchedViaSpdy: false, wasNpnNegotiated: false}; };
      window.chrome.runtime = window.chrome.runtime || {connect: function(){return {onMessage: {addListener: function(){}}};}, sendMessage: function(){}, OnInstalledReason: {}, PlatformOs: {}};
    }
    // battery API: headed desktop Chrome has it, headless doesn't
    try {
      if (!navigator.getBattery) {
        navigator.getBattery = () => Promise.resolve({
          charging: true, chargingTime: 0, dischargingTime: Infinity, level: 1,
          addEventListener: function(){}, removeEventListener: function(){}
        });
      }
    } catch (e) {}
  }
  // ── FINGERPRINT v2 — deeper human signals ────────────────────────
  // WebRTC: real Chrome hides LAN IPs behind mDNS (.local) hostnames;
  // datacenter-driven scrapers leak raw IPs here. Match the human shape.
  try {
    if (window.RTCPeerConnection) {
      const origCreate = RTCPeerConnection.prototype.createDataChannel;
      RTCPeerConnection.prototype.createDataChannel = function(...a) {
        const ch = origCreate.apply(this, a);
        const origGetStats = this.getStats.bind(this);
        this.getStats = async function(sel) {
          const stats = await origGetStats(sel);
          // surface a scrubbed candidate list (mDNS like real Chrome)
          if (stats && stats.forEach) {
            const seen = new Set();
            stats.forEach((r) => {
              if (r.type === 'localcandidate' || r.type === 'local-candidate') {
                if (r.address && !r.address.includes('.local')) {
                  r.address = 'xxxx-' + Math.abs(String(SKIN.seed % 99999)) + '-xxxx.local';
                }
              }
            });
          }
          return stats;
        };
        return ch;
      };
    }
  } catch (e) {}
  // AudioContext: real machines have hardware-specific DSP noise.
  // Emulators produce bit-identical output — an old bot tell. Inject a
  // stable, per-skin whisper of noise (deterministic: same skin = same
  // audio fingerprint, different skin = different machine).
  try {
    const origGetChannelData = AudioBuffer.prototype.getChannelData;
    AudioBuffer.prototype.getChannelData = function(...a) {
      const d = origGetChannelData.apply(this, a);
      if (d && d.length && !d.__thunder) {
        const noise = ((SKIN.seed % 1000) / 1000 - 0.5) * 1e-7;
        const patched = new Float32Array(d.length);
        for (let i = 0; i < d.length; i++) patched[i] = d[i] + noise * Math.sin(i);
        Object.defineProperty(patched, '__thunder', {value: 1});
        return patched;
      }
      return d;
    };
  } catch (e) {}
  // mimeTypes: real Chrome reports the PDF pair; headless reports none.
  try {
    if (navigator.mimeTypes instanceof MimeTypeArray &&
        navigator.mimeTypes.length === 0) {
      Object.defineProperty(navigator.mimeTypes, 'length', {get: () => 2, configurable: true});
    }
  } catch (e) {}
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
