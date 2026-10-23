"""StewMind — Thunder's thought layer, powered by stewmind-1.7b.

https://huggingface.co/Erog0291/stewmind-1.7b

The Body is the hands and eyes; StewMind decides what to do next.

Pair Thunder with ANY model:
  * Ollama (fully local):   StewMind.backend_ollama(model="stewmind:1.7b")
  * LM Studio / vLLM:       StewMind(endpoint="http://localhost:1234/v1")
  * Any OpenAI-compatible:  StewMind(endpoint=..., model="gpt-4o-mini")
  * Hugging Face Inference: StewMind.backend_huggingface()
  * Local transformers:     StewMind.backend_local()
Auto-detect via env: STEWMIND_ENDPOINT, OLLAMA_HOST + OLLAMA_MODEL,
or STEWMIND_LOCAL=1. Vision pairing: describe_image() routes a
screenshot to any vision model so the Body's eyes understand.

think() returns a strict JSON action plan:
    {"action": "click|type|scroll|read|wait|done",
     "target": "...", "value": "...", "reason": "..."}
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

SYSTEM = (
    "You are StewMind, the thought engine of Thunder, a human-like web agent. "
    "You are given a GOAL, the visible page (title, url, and an outline of "
    "interactive elements). Decide the single next action. Reply with ONLY "
    "minified JSON: {\"action\":\"click|type|scroll|read|wait|done\", "
    "\"target\":\"css selector or description\", \"value\":\"text to type\", "
    "\"reason\":\"short human-style reasoning\"}. No markdown, no extra keys."
)

DEFAULT_MODEL = "Erog0291/stewmind-1.7b"


class StewMind:
    """The thought layer. Pairs with stewmind-1.7b or ANY model."""

    def __init__(self, endpoint: Optional[str] = None, model: str = DEFAULT_MODEL,
                 api_key: Optional[str] = None, hf_token: Optional[str] = None,
                 local: bool = False, temperature: float = 0.3):
        self.endpoint = endpoint or os.getenv("STEWMIND_ENDPOINT")
        self.model = model or os.getenv("STEWMIND_MODEL", DEFAULT_MODEL)
        self.api_key = api_key or os.getenv("STEWMIND_API_KEY")
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self.temperature = temperature
        self.ollama_base = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._local_pipe = None
        if local or (not self.endpoint and os.getenv("STEWMIND_LOCAL") == "1"):
            self._load_local()
        elif not self.endpoint and os.getenv("OLLAMA_MODEL"):
            # ollama speaks the OpenAI API — zero extra code needed
            self.endpoint = f"{self.ollama_base}/v1"
            self.model = os.getenv("OLLAMA_MODEL")
            self.api_key = self.api_key or "ollama"

    # ── backends ───────────────────────────────────────────────────
    @classmethod
    def backend_ollama(cls, model: str = "stewmind:1.7b", **kw) -> "StewMind":
        """Pair with any local Ollama model — fully offline Thunder."""
        m = cls(**kw)
        m.endpoint = f"{m.ollama_base}/v1"
        m.model = model
        m.api_key = "ollama"
        return m

    @classmethod
    def backend_huggingface(cls, **kw) -> "StewMind":
        return cls(endpoint="https://api-inference.huggingface.co/v1", **kw)

    def _load_local(self):
        from transformers import pipeline  # heavy import, lazy
        self._local_pipe = pipeline("text-generation", model=self.model,
                                    device_map="auto", trust_remote_code=True)

    def _complete(self, prompt: str) -> str:
        if self._local_pipe is not None:
            out = self._local_pipe(
                [{"role": "system", "content": SYSTEM},
                 {"role": "user", "content": prompt}],
                max_new_tokens=220, do_sample=True, temperature=self.temperature)
            return out[0]["generated_text"][-1]["content"]
        import httpx
        if self.endpoint:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            r = httpx.post(
                f"{self.endpoint.rstrip('/')}/chat/completions",
                json={"model": self.model, "temperature": self.temperature,
                      "messages": [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": prompt}]},
                headers=headers, timeout=60)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        if self.hf_token:
            r = httpx.post(
                f"https://router.huggingface.co/hf-inference/models/{self.model}",
                json={"inputs": f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
                                f"<|im_start|>user\n{prompt}<|im_end|>\n"
                                f"<|im_start|>assistant\n",
                      "parameters": {"temperature": self.temperature,
                                     "max_new_tokens": 220,
                                     "return_full_text": False}},
                headers={"Authorization": f"Bearer {self.hf_token}"}, timeout=90)
            if r.status_code == 200:
                return r.json()[0].get("generated_text", "")
            raise RuntimeError(f"stewmind HF inference failed: {r.status_code} {r.text[:160]}")
        raise RuntimeError(
            "No stewmind backend: set STEWMIND_ENDPOINT, OLLAMA_MODEL, "
            "HF_TOKEN, or local=True")

    # ── vision pairing: any vision model becomes Thunder's eyes ────
    def describe_image(self, image_b64: str, prompt: str,
                       vision_endpoint: Optional[str] = None,
                       vision_model: Optional[str] = None) -> str:
        """Route a screenshot to ANY OpenAI-compatible vision model
        (Ollama llava/qwen-vl, LM Studio, GPT-4o…)."""
        import httpx
        ep = vision_endpoint or self.endpoint
        if not ep:
            raise RuntimeError("set vision_endpoint or StewMind(endpoint=...)")
        r = httpx.post(
            f"{ep.rstrip('/')}/chat/completions",
            json={"model": vision_model or self.model,
                  "messages": [{"role": "user", "content": [
                      {"type": "text", "text": prompt},
                      {"type": "image_url",
                       "image_url": {"url": f"data:image/png;base64,{image_b64}"}}]}]},
            headers={"Authorization": f"Bearer {self.api_key or 'ollama'}"},
            timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    # ── public API ────────────────────────────────────────────────
    def think(self, goal: str, page: Dict[str, Any]) -> Dict[str, Any]:
        """Decide the next action. page = {url, title, elements:[...]}"""
        prompt = (f"GOAL: {goal}\nURL: {page.get('url','')}\n"
                  f"TITLE: {page.get('title','')}\nELEMENTS:\n")
        for el in page.get("elements", [])[:40]:
            prompt += (f"- <{el.get('tag')}> {el.get('text','')[:60]} "
                       f"[{el.get('selector','')}] {el.get('meta','')}\n")
        raw = self._complete(prompt)
        return self.parse(raw)

    @staticmethod
    def parse(raw: str) -> Dict[str, Any]:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return {"action": "read", "target": "", "value": "",
                    "reason": raw.strip()[:200], "raw": raw}
        try:
            d = json.loads(m.group(0))
            d.setdefault("action", "read")
            d.setdefault("target", "")
            d.setdefault("value", "")
            d.setdefault("reason", "")
            return d
        except json.JSONDecodeError:
            return {"action": "read", "target": "", "value": "",
                    "reason": "unparseable thought", "raw": raw[:200]}
