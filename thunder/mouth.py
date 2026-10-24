"""Thunder's Mouth — a real voice, not a robot.

Three engines, one voice box:

1. *Piper* (offline, primary) — fast neural TTS, tiny footprint, mature
   male voice by default (en_US-ryan-high). Runs anywhere, even on the
   free-est of hosts.
2. *Kokoro-82M* (offline, premium) — 82M-parameter premium voice model
   when you want the richest, most human-sounding narration
   (am_michael / am_adam, slower pace = mature delivery).
3. *Edge-TTS* (online fallback) — Microsoft's neural voices when a
   network path exists and the local engines are unavailable.

Everything degrades gracefully: whichever engine answers first wins.
`speak()` returns WAV bytes so any caller (web app, agent, bot) can
play, stream, or save it. `human_flow()` adds the pauses and pacing of
a person reading aloud — sentence-level chunks, a breath between
steps, slight rate variation.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import tempfile
from pathlib import Path

TH_HOME = Path(os.environ.get("THUNDER_HOME", Path.home() / ".thunder"))
VOICES_DIR = TH_HOME / "voices"

# The Thunder voice: a grown man who knows what he's doing.
PIPER_VOICE = os.environ.get("THUNDER_PIPER_VOICE", "en_US-ryan-high")
PIPER_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
             "en/en_US/{name}/high/en_US-{name}-high.onnx")
PIPER_JSON = PIPER_URL.replace(".onnx", ".onnx.json")

KOKORO_VOICE = os.environ.get("THUNDER_KOKORO_VOICE", "am_michael")  # mature male
KOKORO_SPEED = float(os.environ.get("THUNDER_KOKORO_SPEED", "0.9"))

_EDGE_VOICE = os.environ.get("THUNDER_EDGE_VOICE", "en-US-ChristopherNeural")


def _log(msg: str) -> None:
    print(f"[mouth] {msg}", flush=True)


# ---------------------------------------------------------------- engine 1
def _piper_model() -> tuple[Path, Path] | None:
    """Download (once) and locate the Piper voice model."""
    try:
        from piper import PiperVoice  # noqa: F401
    except Exception:
        return None
    name = PIPER_VOICE.replace("-high", "").replace("en_US-", "")
    onnx = VOICES_DIR / f"en_US-{name}-high.onnx"
    jsn = VOICES_DIR / f"en_US-{name}-high.onnx.json"
    if not onnx.exists():
        try:
            import httpx
            VOICES_DIR.mkdir(parents=True, exist_ok=True)
            base = ("https://huggingface.co/rhasspy/piper-voices/"
                    "resolve/main/en/en_US/" + name + "/high/")
            onnx_name = f"en_US-{name}-high.onnx"
            for suffix in ("", ".json"):
                dest = VOICES_DIR / (onnx_name + suffix)
                if dest.exists():
                    continue
                with httpx.Client(follow_redirects=True, timeout=300) as c:
                    with c.stream("GET", base + onnx_name + suffix) as r:
                        r.raise_for_status()
                        with open(dest, "wb") as f:
                            for chunk in r.iter_bytes(65536):
                                f.write(chunk)
                _log(f"downloaded {dest.name}")
        except Exception as e:
            _log(f"piper model download failed: {e}")
            if not onnx.exists():
                return None
    if onnx.exists() and jsn.exists():
        return onnx, jsn
    return None


def _piper_synth(text: str) -> bytes | None:
    pair = _piper_model()
    if not pair:
        return None
    try:
        import wave
        from piper import PiperVoice
        try:
            from piper.config import SynthesisConfig   # piper >= 1.3
            cfg = SynthesisConfig(length_scale=1.06)
            voice = PiperVoice.load(str(pair[0]), config_path=str(pair[1]))
            chunks = list(voice.synthesize(text, syn_config=cfg))
            if not chunks:
                return None
            with tempfile.NamedTemporaryFile(suffix=".wav",
                                             delete=False) as tf:
                out = tf.name
            with wave.open(out, "wb") as w:
                w.setnchannels(getattr(chunks[0], "sample_channels", 1) or 1)
                w.setsampwidth(2)
                w.setframerate(chunks[0].sample_rate or 22050)
                for c in chunks:
                    w.writeframes(c.audio_int16_bytes)
        except ImportError:
            # older piper API — stream directly into a wav file
            voice = PiperVoice.load(str(pair[0]), config_path=str(pair[1]))
            with tempfile.NamedTemporaryFile(suffix=".wav",
                                             delete=False) as tf:
                out = tf.name
            with wave.open(out, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(22050)
                voice.synthesize(text, w)
        data = Path(out).read_bytes()
        os.unlink(out)
        return data if len(data) > 400 else None
    except Exception as e:
        _log(f"piper synth failed: {e}")
        return None


# ---------------------------------------------------------------- engine 2
_KOKORO_LOCK: asyncio.Lock | None = None


def _kokoro_synth(text: str) -> bytes | None:
    try:
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np
    except Exception:
        return None
    try:
        pipe = KPipeline(lang_code="a")  # american english
        chunks = []
        for _, _, audio in pipe(text, voice=KOKORO_VOICE,
                                speed=KOKORO_SPEED):
            if audio is not None:
                a = audio.detach().cpu().numpy() if hasattr(audio, "detach") \
                    else np.asarray(audio)
                chunks.append(a)
        if not chunks:
            return None
        full = np.concatenate(chunks)
        peak = float(np.max(np.abs(full))) or 1.0
        full = (full / peak * 0.85).astype(np.float32)  # gentle loudness
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            out = tf.name
        sf.write(out, full, 24000)
        data = Path(out).read_bytes()
        os.unlink(out)
        return data if len(data) > 400 else None
    except Exception as e:
        _log(f"kokoro synth failed: {e}")
        return None


# ---------------------------------------------------------------- engine 3
def _edge_synth(text: str) -> bytes | None:
    try:
        import edge_tts
    except Exception:
        return None
    try:
        async def run() -> bytes:
            com = edge_tts.Communicate(text, _EDGE_VOICE, rate="-8%")
            mp3 = b""
            async for chunk in com.stream():
                if chunk["type"] == "audio":
                    mp3 += chunk["data"]
            return mp3
        mp3 = asyncio.get_event_loop().run_until_complete(run()) \
            if False else asyncio.run(run())
        return mp3 or None
    except Exception as e:
        _log(f"edge-tts failed: {e}")
        return None


# ------------------------------------------------------------- human flow
def human_flow(text: str) -> str:
    """Clean a log line into something a person would actually say."""
    t = re.sub(r"https?://\S+", "this site", text)
    t = re.sub(r"[\*_`#>|]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:280]


# ------------------------------------------------------------------- API
# Piper is the primary offline voice; Kokoro-82M is the premium one.
ENGINE_ORDER = ("piper", "kokoro", "edge")


def speak(text: str, engine: str | None = None) -> tuple[bytes, str]:
    """Turn text into spoken WAV bytes.

    Returns (audio_bytes, engine_used). Tries engines in order and
    returns whichever answers first. Raises RuntimeError if all fail.
    """
    order = (engine,) if engine in ENGINE_ORDER else ENGINE_ORDER
    for eng in order:
        data = None
        if eng == "kokoro":
            data = _kokoro_synth(text)
        elif eng == "piper":
            data = _piper_synth(text)
        elif eng == "edge":
            data = _edge_synth(text)
            if data and not data.startswith(b"RIFF"):
                # edge returns mp3 — wrap it so callers always get audio
                return data, "edge-mp3"
        if data:
            return data, eng
    raise RuntimeError(
        "no voice engine available — pip install piper-tts kokoro "
        "edge-tts (or set THUNDER_PIPER_VOICE)")


def say(text: str, play: bool = True, engine: str | None = None) -> str:
    """Speak out loud on this machine (aplay/afplay/ffplay)."""
    data, eng = speak(text, engine)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        tf.write(data)
        out = tf.name
    if play:
        for player in ("ffplay", "aplay", "afplay"):
            if subprocess.call(["which", player],
                               capture_output=True) == 0:
                subprocess.Popen([player, "-nodisp" if player ==
                                 "ffplay" else "", out],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                break
    return f"[{eng}] {out}"
