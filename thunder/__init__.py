"""Thunder — the human engine for AI agents.

Thunder gives agents a human-shaped presence on the web:
a stealth browser body, a fingerprint skin, a human hand
(mouse + typing), a ghost-mode TLS layer, a CAPTCHA bridge,
and a mind (stewmind-1.7b).

    import thunder

    body = thunder.Body()                      # a human-shaped browser
    await body.wake("https://example.com")    # open like a person
    await body.type("#q", "hello world")      # type like a person
    shot = await body.look()                  # see the page

Dual-licensed spirit: MIT core, optional AGPL engines (nodriver).
Use Thunder on systems and accounts you are authorized to use.
"""
try:  # optional strongest engine (needs real Chrome + pip install nodriver)
    from thunder.nodriver_body import NodriverBody
except Exception:  # pragma: no cover
    NodriverBody = None
from thunder.body import Body
from thunder.ghost import Ghost
from thunder.mind import StewMind
from thunder.fingerprint import Skin, random_skin

__version__ = "0.5.1"
__all__ = ["Body", "Ghost", "StewMind", "Skin", "random_skin", "NodriverBody", "__version__"]
