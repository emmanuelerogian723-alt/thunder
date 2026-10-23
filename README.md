# Thunder — the human engine for AI agents

<div align="center">

⚡ **THUNDER**

*A body, a skin, a human hand, a ghost, and a mind — for any AI agent.*

`pip install thunder-agent` · MCP-native · Powered by [stewmind-1.7b](https://huggingface.co/Erog0291/stewmind-1.7b)

</div>

---

AI agents browse like robots and get blocked. Thunder gives an agent a
**human-shaped presence** on the web:

| Layer | What it is | How |
|---|---|---|
| 🦾 **Body** | a stealth browser session | Playwright engine + persistent profiles, zero heavy deps |
| 🎭 **Skin** | a consistent device fingerprint | UA / platform / screen / WebGL / canvas-noise, saved per profile so the *same human* returns |
| ✋ **Hand** | human motion | bezier-curve mouse with overshoot, Fitts-law clicks, lognormal keystrokes with typos, eased scroll, idle drift |
| 👻 **Ghost** | protocol-level body | curl_cffi — a real browser's TLS (JA3/JA4) + HTTP/2 shape, no browser needed |
| 🧠 **Mind** | the thought layer | stewmind-1.7b (or ANY model: Ollama, LM Studio, vLLM, GPT, HF) returns strict JSON next-actions |
| 👁️ **Vision** | eyes that understand | route screenshots to any vision model |
| 🛡️ **CAPTCHA bridge** | detect → avoid → solve | senses challenges; plugs into your CapSolver/2Captcha key on your own accounts |
| 🔌 **MCP server** | any agent can drive it | Claude Desktop, Cursor, STEW, anything that speaks MCP |

## Quickstart

```bash
pip install thunder-agent
thunder browse https://example.com          # human-shaped browsing
thunder ghost https://nowsecure.nl          # TLS-true fetch
thunder demo                                # full showcase
```

```python
import thunder, asyncio

async def main():
    body = thunder.Body(profile="ada")            # persistent human
    await body.wake("https://en.wikipedia.org")
    await body.type("#searchInput", "lightning")  # types like a person
    print(await body.read())                     # structured page for your LLM
    await body.rest()

asyncio.run(main())
```

## Pair with ANY model (local or remote)

```python
from thunder.mind import StewMind

mind = StewMind.backend_ollama("stewmind:1.7b")   # fully offline
mind = StewMind(endpoint="http://localhost:1234/v1")  # LM Studio / vLLM
mind = StewMind.backend_huggingface()             # stewmind on HF
mind = StewMind.backend_local()                    # transformers, offline
mind = StewMind(endpoint="https://api.openai.com/v1",
                model="gpt-4o-mini", api_key=KEY)  # any OpenAI-compatible

plan = mind.think(goal="log in and download the invoice",
                  page=await body.read())
# {"action": "type", "target": "#email", "value": "…", "reason": "…"}
```

Offline pairing: `OLLAMA_HOST` + `OLLAMA_MODEL` (or `STEWMIND_LOCAL=1`)
are auto-detected. stewmind-1.7b runs on a laptop CPU/GPU.

## MCP — give every agent a human body

**Copy-paste configs (Thunder is on PyPI):**

```json
{ "mcpServers": { "thunder": {
    "command": "pipx", "args": ["run", "thunder-agent", "thunder-mcp"] } } }
```

```json
{ "mcpServers": { "thunder": {
    "command": "uvx", "args": ["--from", "thunder-agent", "thunder-mcp"] } } }
```

Any OpenAI-style config, any software that speaks MCP — Thunder gives it a human body.

Tools: `thunder_open`, `thunder_read`, `thunder_click`, `thunder_type`,
`thunder_scroll`, `thunder_look`, `thunder_ghost`, `thunder_captcha`,
`thunder_think`, `thunder_rest`.

## CAPTCHAs, honestly

1. **Avoid:** good skin + human hand + clean IP avoids most challenges.
2. **Detect:** `thunder_captcha` reports type + sitekey.
3. **Solve:** bring your own solver key (`CAPSOLVER_API_KEY` /
   `TWOCAPTCHA_API_KEY`) for your own accounts.
4. **Vision (experimental):** `describe_image()` routes challenges to a
   vision model you choose.

Thunder is not a mass-solving service.

## Run it in the cloud (or on your box)

```bash
docker build -t thunder .
docker run -p 8000:8000 thunder          # or run natively, fully offline
```

## Responsible use

Thunder is for agents acting on systems and accounts their operator is
authorized to use: QA, testing, personal automation, public-data research.
Not for fraud, mass account abuse, or deceiving people. Respect site ToS.

MIT © 2026 Emmanuel Ene Rejoice · MUTYINT · Nigeria 🇳🇬
