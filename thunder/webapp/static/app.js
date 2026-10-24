/* Thunder OS — desktop shell logic */
const $ = (s) => document.querySelector(s);
const LS = {
  get: (k, d) => localStorage.getItem(k) ?? d,
  set: (k, v) => localStorage.setItem(k, v),
  del: (k) => localStorage.removeItem(k),
};
let TOKEN = null, EMAIL = null, MODE = null, STATUS = null;
const BASE = "";

/* ---------------- boot ---------------- */
async function boot() {
  try {
    const r = await fetch("/api/status");
    STATUS = await r.json();
    MODE = STATUS.mode;
    $("#st-mode").textContent = MODE === "local" ? "LOCAL" : "CLOUD";
    $("#st-ver").textContent = STATUS.version;
    $("#st-brain").textContent = STATUS.brain.chain
      .split("->")[0].trim().toLowerCase();
  } catch { $("#st-mode").textContent = "OFFLINE"; }
  TOKEN = LS.get("thunder_token", null);
  EMAIL = LS.get("thunder_email", null);
  if (TOKEN) await me();
  auth_ui();
  conn_cards();
  setInterval(() => {
    $("#clock").textContent = new Date().toLocaleTimeString();
  }, 1000);
  load_counts();
}

function headers() {
  return TOKEN ? { "X-Thunder-Token": TOKEN, "Content-Type": "application/json" } : { "Content-Type": "application/json" };
}
function tick(msg) { $("#ticker").textContent = "⚡ " + msg; }
function toast(msg, err = false) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

/* ---------------- auth ---------------- */
async function me() {
  try {
    const r = await fetch("/api/history", { headers: headers() });
    if (r.status === 401) { logout(); return; }
    $("#who").textContent = EMAIL || "local user";
    $("#tok-show").textContent = TOKEN || "local";
    auth_ui();
  } catch {}
}
function auth_ui() {
  const signed = !!TOKEN;
  $("#auth-in").style.display = signed ? "none" : "block";
  $("#auth-ok").style.display = signed ? "block" : "none";
  $("#userbadge").textContent = signed ? (EMAIL || "local") : "guest";
  $("#local-note").hidden = MODE !== "local";
  if (MODE === "local" && !signed) { TOKEN = "local-thunder"; LS.set("thunder_token", TOKEN); auth_ui(); }
}
function logout() {
  LS.del("thunder_token"); LS.del("thunder_email");
  TOKEN = null; EMAIL = null; auth_ui(); toast("Signed out");
}
async function sign_up() {
  const r = await fetch("/api/signup", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: $("#a-email").value, password: $("#a-pass").value }) });
  const d = await r.json();
  if (!r.ok) return toast(d.detail || "signup failed", true);
  after_auth(d);
}
async function log_in() {
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: $("#a-email").value, password: $("#a-pass").value }) });
  const d = await r.json();
  if (!r.ok) return toast(d.detail || "login failed", true);
  after_auth(d);
}
function after_auth(d) {
  TOKEN = d.mcpToken; EMAIL = d.email;
  LS.set("thunder_token", TOKEN); LS.set("thunder_email", EMAIL);
  auth_ui(); me(); toast("Welcome, Thunder is yours");
}

/* ---------------- windows ---------------- */
document.querySelectorAll(".dockbtn").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".dockbtn").forEach((x) => x.classList.remove("on"));
    document.querySelectorAll(".win").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    $("#w-" + b.dataset.w).classList.add("on");
    if (b.dataset.w === "recs") load_recs();
    if (b.dataset.w === "hist") load_hist();
  }));

/* ---------------- live engine ---------------- */
let LOG_TIMER = null, LIVE_SID = null;
async function run_task(url, action, goal) {
  if (!TOKEN) return toast("sign in first", true);
  const payload = goal ? { goal } : { url, action, query: url };
  const ep = goal ? "/api/autopilot" : "/api/task";
  tick("launching " + (goal ? "autopilot mission" : action) + "…");
  const r = await fetch(ep, { method: "POST", headers: { ...headers(), ...(TOKEN && !goal ? { Authorization: "Bearer " + (LS.get("thunder_idtoken", "") || "") } : {}) }, body: JSON.stringify(payload) });
  const d = await r.json();
  if (!r.ok) { toast(d.detail || "task failed", true); return; }
  dock("auto", "live");
  attach_stream(d.sessionId, action === "search" ? null : url, goal);
  poll_log(d.sessionId);
  save_task_id(d.taskId);
}
async function run_auto() {
  const goal = $("#auto-goal").value.trim() || $("#m-goal").value.trim();
  if (!goal) return toast("type a goal first", true);
  $("#auto-go").disabled = true;
  const payload = { goal };
  payload.engine = (window.__engine && window.__engine()) || "auto";
  const r = await fetch("/api/autopilot", { method: "POST", headers: headers(), body: JSON.stringify(payload) });
  const d = await r.json();
  $("#auto-go").disabled = false;
  if (!r.ok) return toast(d.detail || "autopilot failed", true);
  attach_stream(d.sessionId, null, goal);
  poll_log2(d.sessionId);
  tick("brain engaged: " + goal);
}
function dock(...ids) {
  document.querySelectorAll(".dockbtn").forEach((x) =>
    x.classList.toggle("on", x.dataset.w === ids[0]));
  document.querySelectorAll(".win").forEach((x) => x.classList.remove("on"));
  ids.forEach((id) => $("#w-" + id)?.classList.add("on"));
}
function attach_stream(sid, url, goal) {
  LIVE_SID = sid;
  $("#screen").src = "/live/" + sid + "?t=" + Date.now();
  $("#screen2").src = "/live/" + sid + "?t=" + Date.now() + "&v=2";
  $("#console").innerHTML = "<div class='step'>// stream attached — " + (goal || url) + "</div>";
  tick("live session " + sid.slice(0, 8) + " running");
}
/* ---------------- Thunder's Mouth (voice) ---------------- */
const VOICE = { on: LS.get("thunder_voice") !== "off", spoken: {}, q: [], busy: false, cur: null };

function vbtn() { $("#voice-btn").textContent = VOICE.on ? "🔊" : "🔇"; }
function voice_toggle() {
  VOICE.on = !VOICE.on; LS.set("thunder_voice", VOICE.on ? "on" : "off");
  vbtn(); toast(VOICE.on ? "Thunder voice on" : "Thunder voice off");
  if (VOICE.on) say("Thunder voice online. Ready when you are.");
}

async function _speak_fetch(text) {
  const r = await fetch("/api/tts", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }) });
  if (!r.ok) { VOICE.on = false; vbtn(); return null; }
  return await r.blob();
}

async function _drain() {
  if (VOICE.busy) return;
  VOICE.busy = true;
  while (VOICE.q.length) {
    const text = VOICE.q.shift();
    try {
      const blob = await _speak_fetch(text);
      if (blob) { await new Promise((res) => {
          const au = new Audio(URL.createObjectURL(blob));
          VOICE.cur = au; au.onended = res; au.play().catch(res);
          setTimeout(res, 22000); }); }
    } catch (e) { /* keep flowing */ }
  }
  VOICE.busy = false;
}

function say(text) {
  if (!VOICE.on) return;
  VOICE.q.push(text); _drain();
}
function speak_new(logArr, key) {
  if (!VOICE.on) return;
  for (const l of logArr.slice(-4)) {
    const id = key + "|" + l;
    if (VOICE.spoken[id]) continue;
    VOICE.spoken[id] = 1;
    if (l.length > 3) say(l);
  }
}

/* mic: speak your mission instead of typing */
function mic_go() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast("mic needs Chrome/Edge", true);
  const rec = new SR(); rec.lang = "en-US"; rec.interimResults = false;
  $("#m-mic").textContent = "🔴";
  rec.onresult = (e) => {
    const t = e.results[0][0].transcript;
    $("#m-goal").value = t; $("#m-goal").focus();
    toast("mission heard — press Launch autopilot");
  };
  rec.onend = () => { $("#m-mic").textContent = "🎙️"; };
  rec.onerror = () => { $("#m-mic").textContent = "🎙️"; toast("mic error", true); };
  rec.start();
}

function log_html(con, L) {
  con.innerHTML = (L.log.length ? L.log : ["// waiting for first step…"])
    .map((l) => "<div class='step'>" + l.replace(/</g, "&lt;") + "</div>").join("");
  con.scrollTop = con.scrollHeight;
}
async function poll_log(sid) {
  clearInterval(LOG_TIMER);
  LOG_TIMER = setInterval(async () => {
    const r = await fetch("/log/" + sid);
    const L = await r.json();
    log_html($("#console"), L);
    speak_new(L.log, sid);
    if (L.done) { clearInterval(LOG_TIMER); tick("task complete — recording saved"); load_counts(); say("Task complete. Recording saved."); }
  }, 1400);
}
async function poll_log2(sid) {
  clearInterval(LOG_TIMER);
  LOG_TIMER = setInterval(async () => {
    const r = await fetch("/log/" + sid);
    const L = await r.json();
    log_html($("#console2"), L);
    speak_new(L.log, sid);
    if (L.done) { clearInterval(LOG_TIMER); tick("autopilot complete — recording saved"); load_counts(); say("Autopilot complete. Recording saved."); }
  }, 1400);
}
async function save_task_id(id) { LS.set("thunder_last", id); }

/* ---------------- recordings ---------------- */
async function load_recs() {
  const r = await fetch("/api/recordings", { headers: headers() });
  if (!r.ok) return;
  const d = await r.json();
  $("#rec-empty").hidden = d.recordings.length > 0;
  $("#rec-grid").innerHTML = d.recordings.map((x) => `
    <div class="rec-card" data-sid="${x.sid}">
      <img src="data:image/jpeg;base64,${x.thumb}" alt="thumb">
      <div class="rec-meta"><b>${(x.meta.goal || x.meta.url || x.meta.action || "session").replace(/</g, "&lt;")}</b>
      ${new Date(x.at).toLocaleString()} · ${x.frames} frames</div>
    </div>`).join("");
  document.querySelectorAll(".rec-card").forEach((c) =>
    c.addEventListener("click", () => open_player(c.dataset.sid)));
  $("#st-recs").textContent = d.recordings.length;
}
let PLYR = null;
async function open_player(sid) {
  const r = await fetch("/api/replay/" + sid, { headers: headers() });
  if (!r.ok) return toast("recording unavailable", true);
  const rec = await r.json();
  PLYR = { rec, i: 0, playing: true, timer: null };
  $("#player").classList.add("on");
  $("#pl-title").textContent = "REPLAY — " + (rec.meta.goal || rec.meta.url || rec.sid.slice(0, 8));
  $("#pl-log").innerHTML = (rec.log || []).map((l) =>
    "<div>· " + l.replace(/</g, "&lt;") + "</div>").join("");
  $("#pl-dl").onclick = () => {
    const b = new Blob([JSON.stringify(rec)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(b); a.download = "thunder-" + sid + ".json"; a.click();
  };
  show_frame();
  play_loop();
}
function show_frame() {
  const f = PLYR.rec.frames[PLYR.i];
  if (!f) return;
  $("#pl-img").src = "data:image/jpeg;base64," + f.jpeg;
  $("#pl-fill").style.width = ((PLYR.i + 1) / PLYR.rec.frames.length * 100) + "%";
  $("#pl-idx").textContent = (PLYR.i + 1) + " / " + PLYR.rec.frames.length;
}
function play_loop() {
  clearInterval(PLYR.timer);
  PLYR.timer = setInterval(() => {
    if (!PLYR.playing) return;
    if (PLYR.i >= PLYR.rec.frames.length - 1) { PLYR.i = 0; }
    else PLYR.i++;
    show_frame();
  }, 550);
}
$("#pl-play").addEventListener("click", () => {
  PLYR.playing = !PLYR.playing;
  $("#pl-play").textContent = PLYR.playing ? "⏸" : "▶";
});
$("#pl-time").addEventListener("click", (e) => {
  const r = e.target.getBoundingClientRect();
  PLYR.i = Math.floor((e.clientX - r.left) / r.width * PLYR.rec.frames.length);
  show_frame();
});
$("#pl-x").addEventListener("click", () => {
  clearInterval(PLYR?.timer);
  $("#player").classList.remove("on");
});

/* ---------------- history ---------------- */
async function load_hist() {
  const r = await fetch("/api/history", { headers: headers() });
  if (!r.ok) return;
  const d = await r.json();
  $("#hist-body").innerHTML = d.tasks.map((t) => `
    <tr><td>${(t.at || "").replace("T", " ").replace("Z", "")}</td>
    <td>${t.action || ""}</td>
    <td class="cut">${(t.url || "").replace(/</g, "&lt;")}</td>
    <td><span class="tag ${String(t.status).startsWith("ok") ? "" : "err"}">${t.status || ""}</span></td>
    <td class="cut">${(t.result || "").replace(/</g, "&lt;")}</td></tr>`).join("")
    || "<tr><td colspan=5 class='hint'>no tasks yet</td></tr>";
  $("#st-tasks").textContent = d.tasks.length;
}
async function load_counts() {
  const r = await fetch("/api/history", { headers: headers() });
  if (r.ok) $("#st-tasks").textContent = (await r.json()).tasks.length;
}

/* ---------------- connect cards ---------------- */
function conn_cards() {
  const origin = location.origin;
  const tok = TOKEN || "YOUR_TOKEN";
  $("#cfg-web").innerHTML = `# Claude → Settings → Connectors → Add custom connector
URL:  ${origin}/mcp
Header:  X-Thunder-Token: ${tok}<button class="cp ghost">Copy</button>`;
  $("#cfg-desktop").innerHTML = `{
  "mcpServers": {
    "thunder": {
      "command": "python", "args": ["-m", "thunder.mcp_server"]
    }
  }
}<button class="cp ghost">Copy</button>`;
  $("#cfg-py").innerHTML = `pip install thunder-agent
python -m thunder.mcp_server          # 15 local tools
thunder app                           # this app, self-hosted<button class="cp ghost">Copy</button>`;
  document.querySelectorAll(".cfg .cp").forEach((b) =>
    b.addEventListener("click", (e) => {
      navigator.clipboard.writeText(e.target.parentElement.textContent.replace("Copy", "").trim());
      toast("copied");
    }));
}

window.__engine = () => {
  const s = document.querySelector("#m-engine");
  return s ? s.value : "auto";
};

/* ---------------- events ---------------- */
$("#m-go").addEventListener("click", () => run_task($("#m-url").value, "browse"));
$("#m-read").addEventListener("click", () => run_task($("#m-url").value, "read"));
$("#m-feel").addEventListener("click", () => run_task($("#m-url").value, "feel"));
$("#m-auto").addEventListener("click", () => {
  const g = $("#m-goal").value.trim();
  if (!g) return toast("type a goal", true);
  $("#auto-goal").value = g; dock("auto"); run_auto();
});
$("#auto-go").addEventListener("click", run_auto);
$("#a-signup").addEventListener("click", sign_up);
$("#a-login").addEventListener("click", log_in);
$("#voice-btn").addEventListener("click", voice_toggle);
$("#m-mic").addEventListener("click", mic_go);
vbtn();
$("#a-out").addEventListener("click", logout);
$("#a-copy").addEventListener("click", () => { navigator.clipboard.writeText(TOKEN); toast("token copied"); });
$("#m-proof").addEventListener("click", async () => {
  tick("running strength proof…");
  const r = await fetch("/api/proof", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: $("#m-url").value || "https://www.amazon.com" }) });
  const d = await r.json();
  dock("live");
  $("#console").innerHTML = "<div class='step'>// STRENGTH PROOF</div>" +
    String(d.report || JSON.stringify(d)).slice(0, 2200).split("\n")
    .map((l) => "<div class='step'>" + l.replace(/</g, "&lt;") + "</div>").join("");
  tick("strength proof done");
});

boot();
