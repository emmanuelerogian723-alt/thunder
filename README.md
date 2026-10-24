<div align="center">

<img src="site/assets/thunder-logo.png" width="220" alt="Thunder logo"/>

# ⚡ Thunder

**The human engine for AI agents.**

Give any software a human body: a real browser with a real fingerprint,
a mouse that trembles like a hand, keystrokes at human cadence, and a
TLS handshake indistinguishable from Chrome's.

*A bot that walks like a person.*

[![PyPI](https://img.shields.io/pypi/v/thunder-agent?color=%23ffd447&label=pypi%3A%20thunder-agent)](https://pypi.org/project/thunder-agent/)
[![Python](https://img.shields.io/badge/python-3.10%2B-3ddc84)](https://pypi.org/project/thunder-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-4c8dff)](LICENSE)
[![Tests](https://img.shields.io/badge/stealth%20suite-passing-3ddc84) ![Fingerprint](https://img.shields.io/badge/wear%20your%20own%20fingerprint-v0.5-ffd447)](tests/)

**[Install](#-install-in-30-seconds)** · **[Watch the proof](https://emmanuelerogian723-alt.github.io/thunder/)** · **[MCP for any software](#-mcp-give-any-software-a-human-body)**

</div>

---

## Why Thunder exists

Every anti-bot system on Earth looks for the same three tells:

1. *Protocol tells* — a Python scraper's TLS/HTTP-2 handshake screams "bot" before a byte of JS runs.
2. *Fingerprint tells* — `navigator.webdriver`, headless quirks, software-rendered WebGL, empty plugin arrays.
3. *Behavioral tells* — perfectly straight mouse paths, instant typing, zero reading pauses.

Thunder is a body for your AI that has **none of them**. Not patched over — *absent*, the way a real human's browser is.

```python
pip install thunder-agent
```

```python
import thunder

body = thunder.Body(profile="ada")          # a persistent human named Ada
await body.warmup()                         # age the session like a returning user
await body.go("https://protected-site.com")
await body.type("#email", "ada@example.com")   # typed like a person. Typos included.
await body.look("proof.png")                    # screenshot evidence
await body.rest()                              # close, keep the identity
```

Ada comes back tomorrow with the same cookies, same screen, same GPU string, same timezone. The site sees a returning regular.

---

## 📦 Install in 30 seconds

```bash
pip install thunder-agent
```

Works on Linux, macOS, Windows. Real-Chrome engine auto-detected; falls back to bundled Chromium.

```bash
thunder demo        # watch it browse like a human, right now
thunder ghost https://nowsecure.nl    # TLS-level fetch that passes the gate
```

---

## ⚡ The five layers

| Layer | What it does | The tell it kills |
|---|---|---|
| **Body** | Stealth browser: real Google Chrome, persistent profiles | headless shells, disposable identities |
| **Skin** | One consistent identity: UA, platform, GPU, screen, timezone, locale | fingerprint mismatches, `SwiftShader` WebGL |
| **Hand** | Bézier mouse with *hand tremor*, human keystroke cadence, typos it fixes | straight-line paths, machine-perfect timing |
| **Ghost** | Pure HTTP with Chrome's exact TLS/JA3 fingerprint + full header orchestration + human-style retries | Python-scrape handshake = instant 403 |
| **Pool** | Thunder's own proxy pool: auto-fetched, Ghost-validated egress, sticky per profile | shared/flagged datacenter IPs |
| **Warmup** | Organic light browsing before your target | cold first-hit sessions |

Verified live: `bot.sannysoft.com` under Thunder — **WebDriver missing (passed) · WebDriver Advanced passed · Chrome present (passed) · PluginArray passed** — *4 passed, 0 failed* with headed real Chrome. Ghost pulls a **200** from a Cloudflare gate that 403s plain Python, same minute.

---

## 🔌 MCP: give ANY software a human body

**Run the full Thunder app anywhere — one command, no account needed:**

```
pip install thunder-agent[app]
thunder app
```

The Thunder app is a desktop-grade web control room: mission control, a *live monitor* streaming real Chrome as it works, **Autopilot** (the Brain — StewMind 1.7b, falling back to Groq and Pollinations — plans each step and Thunder executes it on camera), and **Recordings**: every session's frames and step log are saved automatically, so you can replay exactly how Thunder navigated and did the task. With `FIREBASE_API_KEY` set it gains full accounts + per-user MCP tokens + cloud history; without it, it runs in local zero-setup mode.

**Hosted MCP endpoint** (connector URL for Claude): `https://thunder-mcp.onrender.com/mcp` — currently re-provisioning; run `thunder app` or the 15-tool local server meanwhile. You get `thunder_search`, `thunder_read`, `thunder_ghost`, `thunder_feel`, `thunder_solve`, `thunder_open` — search, clean extraction and bot-gate-safe fetches through Chrome's exact TLS handshake, from inside Claude.

Want the *full* human body (stealth Chrome, mouse tremor, human typing) under MCP? Run it locally — **15 tools, full parity with the hosted endpoint plus the browser-only ones:**

Thunder ships an MCP server (15 tools). Paste one config and Claude, Cursor, Cline, Windsurf — anything that speaks MCP — browses as a human:

```json
{ "mcpServers": { "thunder": {
    "command": "pipx", "args": ["run", "thunder-agent", "thunder-mcp"] } } }
```

```json
{ "mcpServers": { "thunder": {
    "command": "uvx", "args": ["--from", "thunder-agent", "thunder-mcp"] } } }

Local tools (full set): `thunder_open`, `thunder_read`, `thunder_click`, `thunder_type`, `thunder_scroll`, `thunder_look`, `thunder_ghost`, `thunder_search`, `thunder_feel`, `thunder_captcha`, `thunder_challenge`, `thunder_human_read`, `thunder_identity`, `thunder_think`, `thunder_rest`. Hosted endpoint tools: `thunder_search`, `thunder_read`, `thunder_ghost`, `thunder_feel`, `thunder_solve`, `thunder_open` (guide for running the full body locally). Same core, same code — online and offline behave identically.
```

Tools: `thunder_open` · `thunder_read` · `thunder_search` · `thunder_click` · `thunder_type` · `thunder_scroll` · `thunder_ghost` · `thunder_solve` · `thunder_feel` · `thunder_close` — each one moves like a person, never like a script.

---

## 🚫 The blocker table — what used to stop bots, and Thunder's answer

| Blocker | Thunder's counter |
|---|---|
| Datacenter IP suspicion | `ProxyManager`: sticky per-profile residential proxies, health-checked, auto-rotation — `THUNDER_PROXY` env or `ProxyManager.from_env()` |
| No GPU / software WebGL | Full WebGL1 **and** WebGL2 spoof: vendor + renderer read as a real consumer GPU, on every API path detectors use |
| Headless leaks | Headless-evasion pack: `outerWidth/Height`, `colorDepth`, broken-image dimensions, full `window.chrome` shape, battery API |
| Advanced CAPTCHAs | Keyless `soft_solve` (human-hand click inside challenges) + `ocr_solve` (local OCR for image/math) + CapSolver/2Captcha bridge for the hardest |
| Behavioral ML | Hand tremor + micro-corrections + warmup sessions + thinking pauses — entropy that reads as a person, because it moves like one |

## 🔒 CAPTCHAs without a subscription

```python
from thunder.captcha import soft_solve, ocr_solve
result = await soft_solve(body.page)     # human-hand click, no keys needed
```

Non-interactive challenges often pass on a warmed-up session. For Turnstile/reCAPTCHA Enterprise, wire your own CapSolver or 2Captcha key — Thunder senses the challenge type and routes it.

**v0.5 — ChallengeResolver, Thunder's own bypass system** (no external deps):

```python
from thunder.captcha import ChallengeResolver
verdict = await ChallengeResolver().resolve(body.page, body=body)
# {'solved': True, 'kind': 'turnstile', 'how': 'human-timed checkbox click'}
```

Detects the challenge type — Turnstile, reCAPTCHA v2, hCaptcha, Amazon's text captcha, Cloudflare interstitials — and runs the built-in counter: hand-timed checkbox clicks, patience for interstitials, local OCR for Amazon (retrying like a person squinting). No paid keys, no subscriptions.

---

## 🫆 Wear YOUR OWN fingerprint

The headline feature of v0.5. Open https://browserleaks.com in your normal browser, copy your values, and Thunder wears your machine's ghost — same UA, GPU strings, screen, cores, RAM, timezone, languages:

```python
from thunder.fingerprint import Skin
from thunder.body import Body

me = Skin.imitate({
    "user agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ...",
    "gpu renderer": "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, ...)",
    "timezone": "Europe/London", "screen": "2560x1440",
})
body = Body(skin=me)            # your machine's ghost
```

Or from the terminal:

```bash
thunder identity --out my.json        # export the live fingerprint
thunder identity --imitate my.json    # wear it and verify live
```

Partial data is fine — anything missing stays Thunder-consistent. An imitated skin is *mutually consistent*: your Mac UA will never claim a Windows GPU.

---

## 📖 Reads like a human too

```python
await body.read_like_human(seconds=15)   # burst-scroll, reading pauses,
                                         # idle drift, re-reads
```

Behavioral ML scores dwell patterns. Thunder gives pages a genuine reading signature — pauses at paragraph speed, hands that drift while "reading", occasional scroll-backs.

---

## 🧠 Pair with any mind

Thunder is the body; bring any brain. Works with stewmind, Ollama, LM Studio, vLLM, OpenAI-compatible APIs, or fully offline transformers.

```python
from thunder.mind import Mind
mind = Mind(provider="ollama", model="llama3")
plan = await mind.think("find the pricing page and extract the tiers", body)
```

---

## 🧪 Tested, not promised

```bash
git clone https://github.com/emmanuelerogian723-alt/thunder
cd thunder && pip install -e ".[dev]" && pytest
```

Stealth regression suite: webdriver erased + scan-invisible · genuine PluginArray · headless pack · WebGL skin-consistency · proxy rotation. Each one fails loudly if a future commit breaks the human illusion.

---

## ⚖️ The honest limits (why people trust Thunder)

- No tool on Earth is "undetectable." Anyone selling that is lying to you.
- Cloud IPs still look like clouds — pair Thunder with a residential proxy for the hardest targets.
- Google-scale behavioral ML scores the whole session. Thunder's warmup + hand give you a real chance; it's not a magic key.
- **Use Thunder only where you're authorized.** Your accounts, your tests, your sites. That's the license, and it's the line.

MIT licensed. Built in the open — every claim on this page has a script in `tests/` or a screenshot in `proofs/`.

---

<div align="center">

**Watch Thunder beat the bot-detection gauntlet, live:**

**https://emmanuelerogian723-alt.github.io/thunder/**

⭐ If this saved you a month of anti-detect work, star the repo — it helps others find it.

*Thunder — built so software can finally act human.* 🌩️

</div>
