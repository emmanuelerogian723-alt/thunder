/* Thunder app — auth, dashboard, live streaming */
const API = "";
let USER = JSON.parse(localStorage.getItem("thunderUser") || "null");
let authMode = "signup";
let hbTimer = null;
let logTimer = null;

function el(id){return document.getElementById(id)}
function show(id,on){el(id).classList.toggle("hidden",!on)}

window.addEventListener("DOMContentLoaded", ()=>{
  if(USER){ enterDash(); } else { show("authBox",true); }
});

function toggleAuth(){ el("authBox").scrollIntoView({behavior:"smooth"}); }
function switchAuth(m){
  authMode = m;
  el("authTitle").textContent = m==="signup" ? "Create your Thunder account" : "Welcome back";
  el("authSubmit").textContent = m==="signup" ? "Sign up" : "Sign in";
  el("authSwitch").innerHTML = m==="signup"
    ? 'Have an account? <a href="#" onclick="switchAuth(\'login\')">Sign in</a>'
    : 'New here? <a href="#" onclick="switchAuth(\'signup\')">Create an account</a>';
}

async function doAuth(ev){
  ev.preventDefault();
  const email = el("email").value.trim(), password = el("password").value;
  const r = await fetch(API+"/api/"+(authMode==="signup"?"signup":"login"),{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({email,password})});
  const d = await r.json();
  if(!r.ok){ el("authMsg").textContent = d.detail || "failed"; return false; }
  USER = {uid:d.uid, email:d.email, mcpToken:d.mcpToken, idToken:d.idToken};
  localStorage.setItem("thunderUser", JSON.stringify(USER));
  enterDash();
  return false;
}

function enterDash(){
  show("authBox",false); show("dash",true);
  el("navBtn").textContent = USER.email.split("@")[0];
  el("mcpToken").value = USER.mcpToken;
  el("claudeCfg").value = JSON.stringify({mcpServers:{thunder:{
    command:"pipx", args:["run","thunder-agent","thunder-mcp"]}}},null,2)
    + "\n\n// Claude web/desktop → custom connector:\n"
    + "url: https://thunder-mcp.onrender.com/mcp\n"
    + "header: X-Thunder-Token: " + USER.mcpToken;
  heartbeat(); hbTimer = setInterval(heartbeat, 4*60*1000);
  loadHistory();
}

function logout(){
  localStorage.removeItem("thunderUser"); clearInterval(hbTimer);
  location.href = "/";
}

async function heartbeat(){
  if(!USER) return;
  try{ await fetch(API+"/api/heartbeat",{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({mcpToken:USER.mcpToken, idToken:USER.idToken})}); }catch(e){}
}

function copyEl(elm,msg){
  elm.select(); navigator.clipboard.writeText(elm.value);
  const old = elm.style.borderColor; elm.style.borderColor = "var(--acc)";
  setTimeout(()=>elm.style.borderColor=old, 700);
}

/* ---------------- live tasks ---------------- */
async function runTask(action){
  if(!USER){ show("authBox",true); return; }
  const url = el("testUrl").value.trim() || "https://en.wikipedia.org/wiki/Thunder";
  el("liveLog").textContent = "starting Thunder's live body…";
  el("resultBox").classList.add("hidden");
  const r = await fetch(API+"/api/task",{
    method:"POST",headers:{"Content-Type":"application/json",
      "Authorization":"Bearer "+USER.idToken},
    body:JSON.stringify({url, action, query:url})});
  if(!r.ok){ el("liveLog").textContent = "task failed ("+r.status+") — sign in again"; return; }
  const d = await r.json();
  // live video
  el("idleMsg").style.display = "none";
  el("liveImg").src = API+"/live/"+d.sessionId+"?t="+Date.now();
  // live log
  clearInterval(logTimer);
  logTimer = setInterval(async ()=>{
    const L = await (await fetch(API+"/log/"+d.sessionId)).json();
    el("liveLog").textContent = (L.log||[]).join("\n") || "…";
    if(L.done){
      clearInterval(logTimer);
      showResult(d.taskId);
    }
  }, 1200);
}

async function showResult(taskId){
  const d = await fetchTask(taskId);
  const box = el("resultBox");
  box.classList.remove("hidden");
  box.textContent = d ? ("[" + d.action + "] " + (d.title || "") +
    "\n\n" + (d.result || "").slice(0,600)) : "task logged";
  loadHistory();
}

async function fetchTask(taskId){
  try{
    const r = await fetch(API+"/api/history?taskId="+taskId,{
      headers:{"X-Thunder-Token":USER.mcpToken}});
    const d = await r.json();
    return (d.tasks||[])[0] || null;
  }catch(e){ return null; }
}

async function loadHistory(){
  if(!USER) return;
  try{
    const r = await fetch(API+"/api/history",{
      headers:{"X-Thunder-Token":USER.mcpToken}});
    const d = await r.json();
    const list = (d.tasks||[]).slice(0,20);
    el("historyList").innerHTML = list.length ? list.map(t=>
      `<div class="task"><b>${(t.action||"")}</b> ${(t.url||"").slice(0,60)}<br>
       <span class="${(t.status||"").startsWith("ok")?"ok":"err"}">${(t.status||"")}</span>
       <span class="tiny"> · ${(t.at||"")}</span></div>`).join("")
      : "no tasks yet — run a live test above";
  }catch(e){ el("historyList").textContent = "history unavailable"; }
}

/* ---------------- strength proof ---------------- */
async function strengthTest(){
  const url = el("testUrl").value.trim() || "https://nowsecure.nl";
  el("proofOut").textContent = "running…";
  runTask("feel");  // visual
  const r = await fetch(API+"/api/proof",{
    method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({url})});
  el("proofOut").textContent = await r.text();
}
