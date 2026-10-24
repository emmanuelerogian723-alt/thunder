"""Thunder — the full web application.

One service, four powers:
  /            — landing + signup/login + dashboard (static/)
  /api/*       — accounts (Firebase REST) + live browse tasks
  /live/{sid}  — MJPEG live video stream of Thunder browsing
  /mcp         — per-user hosted MCP (X-Thunder-Token header)

Accounts live in Firebase (project ominiassist-ai) via pure REST:
  thunder_users/{uid}   profile {email, mcpToken, createdAt}
  thunder_tasks/{id}    task history {uid, url, action, status, result}
A user's MCP token identifies them. Live sessions are streamed while
the user's dashboard session is active (idToken cached server-side,
auto-refreshed).
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse, JSONResponse, Response, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastmcp import FastMCP

import thunder
from thunder.ghost import Ghost
from thunder.search import web_search, feel

FB_KEY = os.environ.get("FIREBASE_API_KEY", "")
FB_AUTH = "https://identitytoolkit.googleapis.com/v1/accounts:"
FB_FIRE = ("https://firestore.googleapis.com/v1/projects/ominiassist-ai"
           "/databases/(default)/documents")

mcp = FastMCP("Thunder", instructions=(
    "Thunder is a human engine for AI agents. thunder_search finds pages; "
    "thunder_read fetches clean text through a browser-true TLS handshake "
    "(and, with a per-user token, as a real human-shaped browser session "
    "the user can watch live); thunder_ghost inspects protocol behavior; "
    "thunder_feel checks a target's bot posture; thunder_solve returns "
    "CAPTCHA tokens via the configured solver key."))

mcp_http = mcp.http_app()

app = FastAPI(title="Thunder — the human engine",
              lifespan=mcp_http.lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"])

STATIC = Path(__file__).parent / "static"

# ---------------------------------------------------------------- sessions
# mcp_token -> session (per-user live identity, idToken auto-refreshed)
ACTIVE: dict = {}

# session_id -> live task state
FRAMES: dict = {}          # sid -> {"jpeg": b, "log": [...], "done": bool}


def fb(action: str, payload: dict) -> dict:
    """Firebase Auth REST call."""
    r = httpx.post(fb_action_url(action), params={"key": FB_KEY},
                   json=payload, timeout=20)
    return r.json()


def fb_action_url(action: str) -> str:
    return FB_AUTH + action


async def fb_async(client: httpx.AsyncClient, action: str, payload: dict):
    r = await client.post(fb_action_url(action), params={"key": FB_KEY},
                           json=payload, timeout=20)
    return r.json()


async def fs_write(client: httpx.AsyncClient, path: str, id_token: str,
                  fields: dict) -> bool:
    """Write a Firestore doc via REST with the user's idToken."""
    vals = {}
    for k, v in fields.items():
        if isinstance(v, bool):
            vals[k] = {"booleanValue": v}
        elif isinstance(v, int):
            vals[k] = {"integerValue": str(v)}
        else:
            vals[k] = {"stringValue": str(v)}
    try:
        r = await client.patch(f"{FB_FIRE}/{path}", json={"fields": vals},
                         headers={"Authorization": f"Bearer {id_token}"},
                         timeout=20)
        return r.status_code == 200
    except Exception:
        return False


async def refresh_session(tok: str) -> Optional[dict]:
    """Refresh the idToken of an active session if expired."""
    s = ACTIVE.get(tok)
    if not s:
        return None
    if s.get("exp", 0) - 60 > time.time():
        return s
    try:
        async with httpx.AsyncClient() as c:
            d = await fb_async(c, "signInWithPassword", {
                "email": s["email"], "password": s["password"],
                "returnSecureToken": True})
        if "idToken" in d:
            s["idToken"] = d["idToken"]
            s["exp"] = time.time() + int(d.get("expiresIn", "3600"))
            return s
    except Exception:
        pass
    return s if s.get("idToken") else None


async def session_from_token(mcp_token: Optional[str]) -> Optional[dict]:
    if not mcp_token:
        return None
    return await refresh_session(mcp_token)


def bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


# ---------------------------------------------------------------- accounts
@app.post("/api/signup")
async def api_signup(req: Request):
    body = await req.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email) or len(password) < 8:
        raise HTTPException(400, "valid email + 8+ char password required")
    async with httpx.AsyncClient() as c:
        d = await fb_async(c, "signUp", {
            "email": email, "password": password,
            "returnSecureToken": True})
    if "error" in d:
        msg = d["error"].get("message", "signup failed")
        raise HTTPException(400, msg)
    uid, id_token = d["localId"], d["idToken"]
    mcp_token = secrets.token_urlsafe(24)
    async with httpx.AsyncClient() as c:
        await fs_write(c, f"thunder_users/{uid}", id_token, {
            "email": email, "mcpToken": mcp_token,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    ACTIVE[mcp_token] = {
        "uid": uid, "email": email, "password": password,
        "idToken": id_token,
        "exp": time.time() + int(d.get("expiresIn", "3600"))}
    return {"uid": uid, "email": email, "mcpToken": mcp_token,
            "idToken": id_token}


@app.post("/api/login")
async def api_login(req: Request):
    body = await req.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    async with httpx.AsyncClient() as c:
        d = await fb_async(c, "signInWithPassword", {
            "email": email, "password": password,
            "returnSecureToken": True})
    if "idToken" not in d:
        raise HTTPException(401, "invalid email or password")
    uid, id_token = d["localId"], d["idToken"]
    # fetch the profile to recover the mcp token (written at signup)
    mcp_token = None
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{FB_FIRE}/thunder_users/{uid}",
                            headers={"Authorization": f"Bearer {id_token}"},
                            timeout=20)
            if r.status_code == 200:
                f = r.json().get("fields", {})
                mcp_token = f.get("mcpToken", {}).get("stringValue")
    except Exception:
        pass
    if not mcp_token:            # profile lost (rules/deleted) — reissue
        mcp_token = secrets.token_urlsafe(24)
        async with httpx.AsyncClient() as c:
            await fs_write(c, f"thunder_users/{uid}", id_token,
                     {"email": email, "mcpToken": mcp_token,
                      "createdAt": time.strftime(
                          "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    ACTIVE[mcp_token] = {
        "uid": uid, "email": email, "password": password,
        "idToken": id_token,
        "exp": time.time() + int(d.get("expiresIn", "3600"))}
    return {"uid": uid, "email": email, "mcpToken": mcp_token,
            "idToken": id_token}


@app.post("/api/heartbeat")
async def api_heartbeat(req: Request):
    """Keep the server-side session map alive (dashboard sends every 5 min)."""
    tok = (await req.json()).get("mcpToken", "")
    s = await refresh_session(tok)
    if not s:
        raise HTTPException(404, "session not active — log in again")
    return {"ok": True}


# ------------------------------------------------------------ browse engine
BROWSE_LOCK = asyncio.Semaphore(1)     # one real browser at a time (512MB)


async def _shot(page) -> bytes:
    return await page.screenshot(type="jpeg", quality=50)


async def push_frame(sid: str, jpeg: bytes, note: str = ""):
    st = FRAMES.setdefault(sid, {"jpeg": None, "log": [], "done": False})
    st["jpeg"] = jpeg
    if note:
        st["log"].append(
            f"{time.strftime('%H:%M:%S', time.gmtime())} — {note}")


async def run_browse(url: str, sid: str, mode: str = "browse") -> dict:
    """Open a real (headless) Chrome, browse the page like a human,
    streaming screenshots the whole way. mode: browse | read | feel."""
    from thunder.body import Body
    result = {"url": url, "title": "", "text": "",
              "status": "error", "steps": 0}
    async with BROWSE_LOCK:
        body = None
        try:
            body = Body(profile=f"live-{sid[:8]}", headless=True)
            await body.wake()
            await push_frame(sid, await _shot(body.page), f"opening {url}")
            result["steps"] += 1
            await body.go(url)
            await asyncio.sleep(1.2)
            await push_frame(sid, await _shot(body.page), "page loaded")
            result["steps"] += 1
            # human read: burst scroll + pauses, frames all the way
            for i in range(3):
                await body.scroll(350 + i * 60)
                await asyncio.sleep(0.9)
                await push_frame(sid, await _shot(body.page),
                                 f"reading… (scroll {i + 1}/3)")
                result["steps"] += 1
            info = await body.read()
            if isinstance(info, dict):
                result["title"] = (info.get("title") or "")[:200]
                txt = (info.get("text") or info.get("summary") or "")[:1200]
                result["text"] = txt
            else:
                result["text"] = str(info)[:1200]
            result["status"] = "ok"
            await push_frame(sid, await _shot(body.page), "done — page read")
        except Exception as e:
            result["status"] = f"error: {e}"[:300]
            await push_frame(sid, None, f"task error: {e}")
        finally:
            if body:
                try:
                    await body.rest()
                except Exception:
                    pass
        FRAMES.setdefault(sid, {"jpeg": None, "log": [], "done": False})
        FRAMES[sid]["done"] = True
    return result


@app.post("/api/task")
async def api_task(req: Request):
    """Run a live browse task. Requires Bearer idToken (dashboard) or a
    valid X-Thunder-Token (per-user MCP traffic)."""
    body = await req.json()
    url = (body.get("url") or "").strip()
    action = body.get("action", "browse")
    id_token = bearer(req) or ""
    s = await session_from_token(req.headers.get("x-thunder-token"))
    if not s and id_token:            # dashboard: find session by idToken
        key = next((k for k, v in ACTIVE.items()
                    if v.get("idToken") == id_token), None)
        if key:
            s = await refresh_session(key)
    if not s:
        raise HTTPException(401, "log in first (or send X-Thunder-Token)")
    uid, id_token = s["uid"], s["idToken"]
    if not url.startswith("http"):
        url = "https://" + url
    sid = secrets.token_hex(16)
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    FRAMES[sid] = {"jpeg": None, "log": [], "done": False}

    async def execute():
        if action in ("browse", "read", "feel"):
            res = await run_browse(url, sid, action)
            if action == "feel":
                res["title"] = "Bot-posture report (live video above)"
                res["text"] = (await feel(url)) + "\n\n" + (
                    res.get("text") or "")[:600]
        elif action == "search":
            res = {"url": url, "status": "ok",
                   "text": await web_search(body.get("query", url), 5)}
        else:
            res = {"status": "error: unknown action"}
        async with httpx.AsyncClient() as c:
            await fs_write(c, f"thunder_tasks/{task_id}", id_token, {
                "uid": uid, "url": url, "action": action,
                "status": res["status"][:80],
                "title": res.get("title", "")[:120],
                "result": (res.get("text") or "")[:150],
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return res

    task = asyncio.create_task(execute())
    # give the browser a moment to produce the first frame
    for _ in range(40):
        await asyncio.sleep(0.25)
        if FRAMES[sid]["jpeg"]:
            break
    return {"sessionId": sid, "taskId": task_id}


@app.get("/live/{sid}")
async def live_stream(sid: str):
    """MJPEG live video of the task."""
    boundary = "tframe"

    async def gen():
        last = None
        idle = 0
        while True:
            st = FRAMES.get(sid)
            if not st:
                yield (f"--{boundary}\r\nContent-Type: text/plain\r\n\r\n"
                       "session expired\r\n").encode()
                return
            if st["jpeg"] and st["jpeg"] is not last:
                last = st["jpeg"]
                idle = 0
                yield (f"--{boundary}\r\nContent-Type: image/jpeg\r\n"
                       f"Content-Length: {len(st['jpeg'])}\r\n\r\n"
                       ).encode() + st["jpeg"] + b"\r\n"
            else:
                idle += 1
            if st["done"] and idle > 6:
                yield (f"--{boundary}--\r\n").encode()
                FRAMES.pop(sid, None)
                return
            await asyncio.sleep(0.55)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}")


@app.get("/log/{sid}")
async def live_log(sid: str):
    st = FRAMES.get(sid)
    return {"log": st["log"] if st else [], "done": st["done"] if st else True}


@app.get("/api/history")
async def api_history(request: Request, taskId: str = ""):
    """Task history for the session's user (filtered by uid)."""
    tok = request.headers.get("x-thunder-token")
    s = await session_from_token(tok)
    if not s:
        raise HTTPException(401, "log in first")
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{FB_FIRE}/thunder_tasks",
                params={"pageSize": "100"},
                headers={"Authorization": f"Bearer {s['idToken']}"},
                timeout=20)
            docs = r.json().get("documents", [])
    except Exception:
        docs = []
    tasks = []
    for doc in docs:
        f = {k: list(v.values())[0] for k, v in
             doc.get("fields", {}).items()}
        if f.get("uid") != s["uid"]:
            continue
        if taskId and not doc.get("name", "").endswith(taskId):
            continue
        tasks.append(f)
    tasks.reverse()
    return {"tasks": tasks[:20]}


@app.post("/api/proof")
async def api_proof(request: Request):
    """Public strength proof: plain request vs thunder ghost."""
    url = ((await request.json()).get("url") or "").strip()
    if not url.startswith("http"):
        url = "https://" + url
    report = await feel(url)
    return report


# ---------------------------------------------------------------- the MCP
def _hdr(name: str) -> Optional[str]:
    """Read a request header from inside an MCP tool."""
    try:
        from fastmcp.server.dependencies import get_http_headers
        return get_http_headers().get(name)
    except Exception:
        return None


@mcp.tool
async def thunder_search(query: str, limit: int = 5) -> str:
    """Search the web and return top results (browser-true TLS,
    DDG POST-first with lite/Bing fallbacks)."""
    return await web_search(query, limit)


@mcp.tool
async def thunder_read(url: str, limit: int = 5000) -> str:
    """Fetch a page and extract clean readable text. With the user's
    X-Thunder-Token this runs in a real human-shaped browser they can
    watch live on their Thunder dashboard; otherwise via the ghost."""
    tok = _hdr("x-thunder-token")
    s = await session_from_token(tok)
    if s:
        sid = secrets.token_hex(16)
        FRAMES[sid] = {"jpeg": None, "log": [], "done": False}
        task = asyncio.create_task(run_browse(url, sid, "read"))
        for _ in range(30):
            await asyncio.sleep(0.25)
            if FRAMES[sid]["jpeg"] or FRAMES[sid]["done"]:
                break
        try:
            await asyncio.wait_for(task, timeout=90)
            res = task.result()
        except asyncio.TimeoutError:
            res = await _ghost_read(url, limit)
            res = {"status": res[0], "text": res[1]}
        async with httpx.AsyncClient() as c:
            await fs_write(c, f"thunder_tasks/task-{uuid.uuid4().hex[:12]}",
                     s["idToken"], {
                         "uid": s["uid"], "url": url, "action": "read",
                         "status": res["status"][:80],
                         "title": res.get("title", "")[:120],
                         "result": (res.get("text") or "")[:150],
                         "at": time.strftime(
                             "%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return (f"status: {res['status']}\ntitle: {res.get('title','')}"
                f"\n\n{(res.get('text') or '')[:limit]}\n\n"
                f"(live video was streamed to the user's dashboard)")
    status, text = await _ghost_read(url, limit)
    return f"status: {status}\n{text}"


async def _ghost_read(url: str, limit: int):
    g = Ghost()
    try:
        r = await g.browse(url, retries=3)
        if r is None:
            return "fetch failed: no response", ""
        m = re.search(r"<title>(.*?)</title>", r.text[:8000], re.S)
        title = m.group(1).strip() if m else ""
        html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ",
                      r.text, flags=re.S | re.I)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()
        return str(r.status_code), f"title: {title}\n{text[:limit]}"
    except Exception as e:
        return f"read failed: {e}", ""
    finally:
        await g.close()


@mcp.tool
async def thunder_ghost(url: str) -> str:
    """Protocol-level fetch: status + headers with Chrome's exact TLS."""
    g = Ghost()
    try:
        r = await g.browse(url, retries=2)
        if r is None:
            return "no response"
        interesting = {k: v for k, v in (r.headers or {}).items()
                       if k.lower() in ("server", "cf-ray", "cf-mitigated",
                                        "content-type", "set-cookie",
                                        "x-frame-options", "location")}
        return (f"status: {r.status_code}\nhandshake: chrome-true TLS "
                f"(curl_cffi)\nheaders: {interesting}")
    except Exception as e:
        return f"ghost fetch failed: {e}"
    finally:
        await g.close()


@mcp.tool
async def thunder_feel(url: str) -> str:
    """Check a target's bot posture: plain request vs thunder ghost."""
    return await feel(url)


@mcp.tool
async def thunder_solve(page_url: str, sitekey: str,
                        challenge_type: str = "recaptcha") -> str:
    """Solve a CAPTCHA and return the token (solver key configured on the
    server). challenge_type: recaptcha | hcaptcha | turnstile."""
    from thunder.captcha import SolverBridge
    bridge = SolverBridge()
    if not bridge.available():
        return ("no solver key configured on this endpoint. "
                "Owner: set CAPSOLVER_API_KEY or TWOCAPTCHA_API_KEY. "
                "Thunder still avoids most challenges locally with "
                "skin + hand — pip install thunder-agent.")
    import httpx

    class FakePage:
        url = page_url

        async def evaluate(self, _):
            return True

    async with httpx.AsyncClient(timeout=120) as c:
        if bridge.capsolver:
            types = {"recaptcha": "ReCaptchaV2TaskProxyLess",
                     "hcaptcha": "HCaptchaTaskProxyLess",
                     "turnstile": "AntiTurnstileTaskProxyLess"}
            token = await bridge._capsolver(c, {
                "type": types.get(challenge_type, types["recaptcha"]),
                "websiteURL": page_url, "websiteKey": sitekey})
        else:
            token = await bridge._twocaptcha(c, challenge_type,
                                             page_url, sitekey)
    if not token:
        return "solver returned no token — check the sitekey or key balance"
    return f"solved. token:\n{token}"


@mcp.tool
async def thunder_open(url: str) -> str:
    """Guide for running Thunder's full human body locally (the hosted
    shared browser has one body; locals get unlimited)."""
    return (
        "Thunder's full human body runs locally:\n\n"
        "  pip install thunder-agent\n  thunder demo\n\n"
        "MCP config for Claude Desktop / any MCP client:\n"
        '{ "mcpServers": { "thunder": {\n'
        '    "command": "pipx",\n'
        '    "args": ["run", "thunder-agent", "thunder-mcp"] } } }\n\n'
        "Hosted endpoint (this server): 6 tools, zero setup. Per-user "
        "tokens connect Claude traffic to your Thunder dashboard.")


# ---------------------------------------------------------------- static
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


# MCP's internal path is /mcp; ROOT MOUNT LAST so every FastAPI route
# above wins and the public endpoint stays at exactly /mcp.
app.mount("/", mcp_http)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT",
                                                             "8000")))
