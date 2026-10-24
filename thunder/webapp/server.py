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

try:                                   # packaged (thunder.webapp) or repo run
    from .brain import Brain
except ImportError:
    from brain import Brain

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

# LOCAL MODE: no FIREBASE_API_KEY -> one zero-setup user (thunder app).
LOCAL_MODE = not FB_KEY
LOCAL_TOKEN = os.getenv("THUNDER_LOCAL_TOKEN", "local-thunder")
LOCAL_USER = {"uid": "local-user", "email": "local@thunder",
              "idToken": "", "mcpToken": LOCAL_TOKEN}
TASKS: list = []            # local-mode task history (memory)

REC_DIR = Path(os.environ.get(
    "THUNDER_HOME", str(Path.home() / ".thunder"))) / "recordings"
REC_DIR.mkdir(parents=True, exist_ok=True)
HF_REPO = os.getenv("THUNDER_REC_REPO", "Erog0291/thunder-recordings")


async def save_recording(sid: str):
    """Persist a finished session's frames + log so users can replay it.
    Disk first (fast), then the private HF dataset (durable)."""
    st = FRAMES.get(sid)
    if not st or not st.get("replay"):
        return
    rec = {"sid": sid, "uid": st.get("uid") or "anon",
           "meta": st.get("meta", {}),
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "log": st["log"], "frames": st["replay"]}
    try:
        (REC_DIR / f"{sid}.json").write_text(json.dumps(rec))
    except Exception:
        pass
    tok = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or ""
    if tok:
        try:
            nd = json.dumps({
                "operation": "add", "path": f"{sid}.json",
                "content": base64.b64encode(
                    json.dumps(rec).encode()).decode()})
            async with httpx.AsyncClient() as c:
                await c.post(
                    f"https://huggingface.co/api/datasets/{HF_REPO}"
                    "/commit/main",
                    headers={"Authorization": f"Bearer {tok}"},
                    content=nd, timeout=60)
        except Exception:
            pass


async def load_recording(sid: str) -> Optional[dict]:
    p = REC_DIR / f"{sid}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    tok = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_KEY") or ""
    if not tok:
        return None
    try:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"https://huggingface.co/api/datasets/{HF_REPO}"
                f"/resolve/main/{sid}.json",
                headers={"Authorization": f"Bearer {tok}"}, timeout=60)
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None

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


def local_task_write(fields: dict):
    TASKS.insert(0, {**fields, "id": f"task-{len(TASKS)+1:04d}"})
    del TASKS[50:]


async def fs_write(client: httpx.AsyncClient, path: str, id_token: str,
                  fields: dict) -> bool:
    if not id_token:                      # local mode: keep in memory
        local_task_write(fields)
        return True
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
    if LOCAL_MODE:
        return LOCAL_USER
    if not mcp_token:
        return None
    return await refresh_session(mcp_token)


def bearer(request: Request) -> Optional[str]:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


# ---------------------------------------------------------------- accounts
@app.post("/api/signup")
async def api_signup(req: Request):
    if LOCAL_MODE:
        return {"email": LOCAL_USER["email"], "local": True,
                "idToken": "", "mcpToken": LOCAL_TOKEN}
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
    if LOCAL_MODE:
        return {"email": LOCAL_USER["email"], "local": True,
                "idToken": "", "mcpToken": LOCAL_TOKEN}
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
    if len(FRAMES) > 50:            # keep memory bounded
        for old in [k for k, v in FRAMES.items() if v.get("done")][:20]:
            FRAMES.pop(old, None)
    st = FRAMES.setdefault(sid, {"jpeg": None, "log": [], "done": False,
                                 "replay": []})
    st["jpeg"] = jpeg
    if jpeg:        # keep every frame for the session recording
        st["replay"].append({
            "t": round(time.time(), 1),
            "jpeg": base64.b64encode(jpeg).decode(),
            "note": note})
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
        FRAMES.setdefault(sid, {"jpeg": None, "log": [], "done": False,
                               "replay": []})
        FRAMES[sid]["done"] = True
    await save_recording(sid)
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
    FRAMES[sid] = {"jpeg": None, "log": [], "done": False, "replay": [],
                   "uid": uid,
                   "meta": {"action": action, "url": url,
                            "query": body.get("query", "")}}

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
                return
            await asyncio.sleep(0.55)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}")


@app.get("/log/{sid}")
async def live_log(sid: str):
    st = FRAMES.get(sid)
    if st:
        return {"log": st["log"], "done": st["done"]}
    rec = await load_recording(sid)      # session finished & cached away
    if rec:
        return {"log": rec.get("log", []), "done": True}
    return {"log": [], "done": True}


@app.get("/api/history")
async def api_history(request: Request, taskId: str = ""):
    """Task history for the session's user (filtered by uid)."""
    tok = request.headers.get("x-thunder-token") or (
        LOCAL_TOKEN if LOCAL_MODE else None)
    s = await session_from_token(tok)
    if not s:
        raise HTTPException(401, "log in first")
    if LOCAL_MODE:
        return {"tasks": [t for t in TASKS if not taskId or t["id"] == taskId]}
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
    tasks.sort(key=lambda t: t.get("at", ""), reverse=True)
    return {"tasks": tasks[:20]}


# ------------------------------------------------------------ autopilot
async def run_autopilot(goal: str, sid: str,
                        engine: str = "auto") -> dict:
    """The Brain (StewMind -> Groq -> Pollinations) plans; Thunder acts."""
    from thunder.body import Body
    brain = Brain()
    result = {"goal": goal, "status": "error", "steps": 0,
              "text": "", "model": "none"}
    async with BROWSE_LOCK:
        body = None
        try:
            body = Body(profile=f"auto-{sid[:8]}", headless=True)
            await body.wake()
            await push_frame(sid, await _shot(body.page),
                             f"brain booting — goal: {goal[:60]}")
            history: list = []
            started = False
            for step in range(8):
                if not started:
                    state = {"url": "", "title": "(start)",
                             "text": "no page open yet — goto or search first",
                             "links": []}
                else:
                    state = await body.page.evaluate(
                        """() => {const a=[...document.querySelectorAll('a')]
                        .slice(0,25).map(x=>({t:(x.innerText||'').trim()
                        .slice(0,60),h:(x.href||'').slice(0,140)}))
                        .filter(x=>x.t);
                        return {url:location.href.slice(0,180),
                        title:document.title.slice(0,120),
                        text:(document.body.innerText||'').slice(0,900),
                        links:a}}""")
                act = await brain.next_action(state, goal, history)
                result["model"] = brain.model
                if history[-3:-1] and all(
                        h.split(" (")[0] == f"{act['action']}: {act['value']}"
                        for h in history[-2:]) and act["action"] != "done":
                    act = {"action": "done", "value": "",
                           "reason": "avoiding a repeat loop — reading here"}
                val = act["value"]
                history.append(f"{act['action']}: {val} ({act['reason']})")
                await push_frame(sid, await _shot(body.page),
                                 f"brain: {act['action']} {val[:40]} — "
                                 f"{act['reason'][:40]}")
                result["steps"] += 1
                if act["action"] == "done" or not val and \
                        act["action"] not in ("scroll", "done"):
                    break
                if act["action"] == "goto":
                    await body.go(val if val.startswith("http")
                                  else "https://" + val)
                    started = True
                elif act["action"] == "search":
                    eng = engine if engine != "auto" else "auto"
                    low = val.lower()
                    for e in ("google", "bing", "duckduckgo"):
                        if e in low:
                            eng = e
                            val = re.sub(
                                r"\b(on\s+)?" + e + r"(\s+for|\s+search)?\b",
                                "", val, flags=re.I).strip(" ,:.-")
                            break
                    hits = await web_search(val, 5, engine=eng)
                    first = ""
                    for ln in hits.splitlines():
                        m2 = re.search(r"https?://\S+", ln)
                        if m2 and not first and "duckduckgo" not in m2.group(0):
                            first = m2.group(0).rstrip(")")
                        await push_frame(sid, None,
                                         "🔍 " + ln.strip()[:90])
                    if first:
                        await body.go(first)
                        started = True
                    else:
                        await push_frame(sid, None,
                                         "no results — brain re-plans")
                elif act["action"] == "click":
                    ok = await body.page.evaluate(
                        """(txt) => {const a=[...document.querySelectorAll('a')]
                        .find(x => (x.innerText||'').toLowerCase().includes(
                        txt.toLowerCase()));
                        if (a) {a.click(); return true;} return false;}""",
                        val)
                    if not ok:
                        await push_frame(sid, None, "link not found — brain "
                                     "will re-plan")
                elif act["action"] == "scroll":
                    if "top" in val.lower():
                        await body.page.evaluate(
                            "window.scrollTo(0,0)")
                    else:
                        await body.scroll(520)
                elif act["action"] == "type":
                    await body.page.evaluate(
                        """(txt) => {const i=[...document.querySelectorAll(
                        'input[type=text],input[type=search],input:not([type]),'
                        + 'textarea')][0]; if (i) {i.focus(); return true;}
                        return false;}""", val)
                    await body.page.keyboard.type(val.split("->")[0].strip(),
                                                  delay=70)
                await asyncio.sleep(1.4)
                await push_frame(sid, await _shot(body.page),
                                 f"step {step + 1}/8 done")
            if started:
                info = await body.read()
                if isinstance(info, dict):
                    result["text"] = ((info.get("text") or
                                       info.get("summary") or ""))[:1200]
                    result["title"] = (info.get("title") or "")[:200]
            result["status"] = "ok"
            await push_frame(sid, await _shot(body.page),
                             f"autopilot finished — {result['steps']} steps, "
                             f"brain: {brain.model}")
        except Exception as e:
            result["status"] = f"error: {e}"[:300]
            await push_frame(sid, None, f"autopilot error: {e}")
        finally:
            if body:
                try:
                    await body.rest()
                except Exception:
                    pass
        FRAMES.setdefault(sid, {"jpeg": None, "log": [], "done": False,
                               "replay": []})
        FRAMES[sid]["done"] = True
    await save_recording(sid)
    return result


@app.post("/api/autopilot")
async def api_autopilot(req: Request):
    """Give Thunder a goal — the Brain plans every step, live on video."""
    body = await req.json()
    goal = (body.get("goal") or "").strip()[:300]
    if not goal:
        raise HTTPException(400, "goal required")
    id_token = bearer(req) or ""
    s = await session_from_token(req.headers.get("x-thunder-token"))
    if not s and id_token and not LOCAL_MODE:
        key = next((k for k, v in ACTIVE.items()
                    if v.get("idToken") == id_token), None)
        if key:
            s = await refresh_session(key)
    if not s:
        raise HTTPException(401, "log in first (or send X-Thunder-Token)")
    uid, id_token = s["uid"], s["idToken"]
    sid = secrets.token_hex(16)
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    engine = str(body.get("engine", "auto"))
    if engine not in ("auto", "google", "bing", "duckduckgo"):
        engine = "auto"
    FRAMES[sid] = {"jpeg": None, "log": [], "done": False, "replay": [],
                   "uid": uid, "meta": {"action": "autopilot", "goal": goal,
                                        "engine": engine}}

    async def execute():
        res = await run_autopilot(goal, sid, engine)
        async with httpx.AsyncClient() as c:
            await fs_write(c, f"thunder_tasks/{task_id}", id_token, {
                "uid": uid, "url": "autopilot", "action": "autopilot",
                "status": res["status"][:80],
                "title": (res.get("title") or res.get("model", ""))[:120],
                "result": (f"brain {res.get('model','')}: "
                           + (res.get("text") or ""))[:150],
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        return res

    task = asyncio.create_task(execute())
    for _ in range(40):
        await asyncio.sleep(0.25)
        if FRAMES[sid]["jpeg"]:
            break
    return {"sessionId": sid, "taskId": task_id}


@app.get("/api/recordings")
async def api_recordings(request: Request):
    """Saved sessions this user can replay."""
    tok = request.headers.get("x-thunder-token") or (
        LOCAL_TOKEN if LOCAL_MODE else None)
    s = await session_from_token(tok)
    if not s:
        raise HTTPException(401, "log in first")
    out = []
    for p in sorted(REC_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime,
                    reverse=True)[:30]:
        try:
            rec = json.loads(p.read_text())
            if rec.get("uid") == s["uid"]:
                out.append({"sid": rec["sid"], "at": rec.get("at"),
                            "meta": rec.get("meta", {}),
                            "frames": len(rec.get("frames", [])),
                            "thumb": (rec.get("frames") or [{}])[0]
                            .get("jpeg", "")})
        except Exception:
            continue
    return {"recordings": out}


@app.get("/api/replay/{sid}")
async def api_replay(sid: str, request: Request):
    tok = request.headers.get("x-thunder-token") or (
        LOCAL_TOKEN if LOCAL_MODE else None)
    s = await session_from_token(tok)
    if not s:
        raise HTTPException(401, "log in first")
    rec = await load_recording(sid)
    if not rec:
        raise HTTPException(404, "recording not found")
    if rec.get("uid") not in (s["uid"], "anon", None):
        raise HTTPException(403, "not your recording")
    return rec


@app.get("/api/status")
async def api_status():
    brain = Brain()
    return {"mode": "local" if LOCAL_MODE else "cloud",
            "version": thunder.__version__,
            "brain": {"stewmind": brain.hf != "",
                      "groq": brain.groq != "",
                      "chain": "StewMind 1.7b -> Groq -> Pollinations"}}


_TTS_CACHE: dict = {}


@app.post("/api/tts")
async def api_tts(request: Request):
    """Thunder's Mouth: speak text with the matured-man voice.
    Engines: kokoro (premium) -> piper (offline) -> edge (online)."""
    body = await request.json()
    text = str(body.get("text") or "").strip()[:280]
    if not text:
        raise HTTPException(400, "text required")
    engine = body.get("engine") or None
    from thunder.mouth import speak, human_flow, ENGINE_ORDER
    text = human_flow(text)
    key = (engine or "any") + "|" + text
    if key in _TTS_CACHE:
        data, eng = _TTS_CACHE[key]
        return Response(data, media_type="audio/wav",
                        headers={"X-Thunder-Voice": eng})
    try:
        data, eng = await asyncio.get_event_loop().run_in_executor(
            None, lambda: speak(text, engine))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if len(_TTS_CACHE) > 40:
        _TTS_CACHE.clear()
    _TTS_CACHE[key] = (data, eng)
    mt = "audio/mpeg" if eng == "edge-mp3" else "audio/wav"
    return Response(data, media_type=mt,
                    headers={"X-Thunder-Voice": eng})


@app.get("/api/voices")
async def api_voices():
    from thunder.mouth import ENGINE_ORDER
    avail = []
    import importlib
    for e in ENGINE_ORDER:
        try:
            if e == "kokoro":
                importlib.import_module("kokoro")
            elif e == "piper":
                importlib.import_module("piper")
            elif e == "edge":
                importlib.import_module("edge_tts")
            avail.append(e)
        except Exception:
            pass
    return {"engines": avail, "default": "kokoro premium male"}


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
async def thunder_search(query: str, limit: int = 5,
                         engine: str = "auto") -> str:
    """Search the web and return top results (browser-true TLS).
    engine: google | bing | duckduckgo | auto (ddg -> bing -> google
    fallback). The first line names the engine that answered."""
    return await web_search(query, limit, engine=engine)


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
