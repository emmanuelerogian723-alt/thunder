"""Thunder Brain — the thinking layer that plans browsing actions.

Model chain (first that answers wins):
  1. StewMind 1.7b  — Emmanuel's own model, via HF Inference router
  2. Groq           — llama-3.3-70b-versatile (fast JSON brain)
  3. Pollinations   — keyless open fallback

The Brain is asked for ONE action at a time given the current page state.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Optional

import httpx

HF_ROUTER = "https://router.huggingface.co/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("THUNDER_GROQ_MODEL", "openai/gpt-oss-120b")
POLL_URL = "https://text.pollinations.ai/openai"

STEWMIND = os.getenv("THUNDER_BRAIN_MODEL", "Erog0291/stewmind-1.7b")

SYSTEM = """You are the Brain of Thunder, a browser automation agent.
Given the current page state and a goal, reply with ONE JSON object only:
{"action":"goto|click|scroll|type|search|done","value":"...","reason":"..."}
Rules: click takes link text or #n from links; scroll is down unless "top";
type takes "text -> selector" or just text into the main search box; search
takes a query; done when the goal is satisfied. Reply with JSON only."""

VALID = {"goto", "click", "scroll", "type", "search", "done"}


def _parse(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("action") not in VALID:
        return None
    d["value"] = str(d.get("value", ""))[:300]
    d["reason"] = str(d.get("reason", ""))[:200]
    return d


def _msgs(state: dict, goal: str, history: list) -> list:
    hist = "\n".join(history[-8:]) or "(start)"
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content":
            f"GOAL: {goal}\nPREVIOUS ACTIONS:\n{hist}\n"
            f"PAGE:\nurl: {state.get('url','')}\n"
            f"title: {state.get('title','')}\n"
            f"text: {state.get('text','')[:900]}\n"
            f"links: {json.dumps(state.get('links', [])[:18])}\n"
            "Next action JSON:"},
    ]


async def _hf(client, key: str, msgs: list) -> Optional[dict]:
    try:
        r = await client.post(HF_ROUTER, headers={"Authorization": f"Bearer {key}"},
                              json={"model": STEWMIND, "messages": msgs,
                                    "max_tokens": 200, "temperature": 0.2},
                              timeout=25)
        if r.status_code != 200:
            return None
        return _parse(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


async def _groq(client, key: str, msgs: list) -> Optional[dict]:
    try:
        r = await client.post(GROQ_URL, headers={"Authorization": f"Bearer {key}"},
                              json={"model": GROQ_MODEL,
                                    "messages": msgs, "max_tokens": 200,
                                    "temperature": 0.2,
                                    "response_format": {"type": "json_object"}},
                              timeout=25)
        if r.status_code != 200:
            return None
        return _parse(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


async def _poll(client, msgs: list) -> Optional[dict]:
    try:
        r = await client.post(POLL_URL, json={"model": "openai",
                                              "messages": msgs},
                              timeout=35)
        if r.status_code != 200:
            return None
        return _parse(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


class Brain:
    """Decides the next browser action. Reports which model answered."""

    def __init__(self):
        self.hf = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or ""
        self.groq = os.getenv("GROQ_API_KEY") or ""
        self.model = "none"

    async def next_action(self, state: dict, goal: str,
                          history: list) -> dict:
        msgs = _msgs(state, goal, history)
        for attempt in range(2):          # one patient retry on rate limits
            async with httpx.AsyncClient() as c:
                if self.hf:
                    d = await _hf(c, self.hf, msgs)
                    if d:
                        self.model = STEWMIND
                        return d
                if self.groq:
                    d = await _groq(c, self.groq, msgs)
                    if d:
                        self.model = f"groq/{GROQ_MODEL.split('/')[-1]}"
                        return d
                d = await _poll(c, msgs)
                if d:
                    self.model = "pollinations/openai"
                    return d
            await asyncio.sleep(2.5)
        return {"action": "done", "value": "",
                "reason": "no brain model reachable — set GROQ_API_KEY "
                          "or HF_TOKEN (StewMind)"}
