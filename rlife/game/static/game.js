// Ages of Kingdoms: 3D client (three.js). Everything is modelled procedurally in low-poly style:
// lit terrain with shadows, animated water, instanced forests and rocks, castles whose walls grow,
// houses, farms, temples, markets, and six kinds of people (kings, soldiers, farmers, merchants,
// scholars) going about their lives. Armies march between realms; weather plays over the land.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {LineSegments2} from "three/addons/lines/LineSegments2.js";
import {LineSegmentsGeometry} from "three/addons/lines/LineSegmentsGeometry.js";
import {LineMaterial} from "three/addons/lines/LineMaterial.js";

const $ = id => document.getElementById(id);
const fmt = n => Math.round(n).toLocaleString();
const pct = v => Math.round(v * 100) + "%";
const yr = y => (y < 0 ? `${-y} BCE` : `${y} CE`);
async function api(path, body) {
  const r = await fetch("/game/api/" + path, body === undefined ? {} :
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function rng(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function toast(text, ms = 2600) {
  const el = $("toast"); el.textContent = text; el.style.opacity = 1;
  clearTimeout(toast.t); toast.t = setTimeout(() => (el.style.opacity = 0), ms);
}

const G = {terrain: null, state: null, playing: 0, timer: null, attackMode: false, busy: false, sound: true};

// ================================================================ audio: voice, effects, music
const Audio = {
  ctx: null, music: null,
  init() {
    if (this.ctx) return;
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.master = this.ctx.createGain(); this.master.gain.value = 0.5; this.master.connect(this.ctx.destination);
    this.startMusic();
  },
  tone(freq, dur, type = "sine", vol = 0.2, when = 0) {
    if (!this.ctx || !G.sound) return;
    const t = this.ctx.currentTime + when, o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type; o.frequency.value = freq; g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur); o.connect(g).connect(this.master); o.start(t); o.stop(t + dur + 0.05);
  },
  noise(dur, vol = 0.3, freq = 900) {
    if (!this.ctx || !G.sound) return;
    const n = this.ctx.sampleRate * dur, buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
    const src = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = freq; g.gain.value = vol;
    src.connect(f).connect(g).connect(this.master); src.start();
  },
  sfx(name) {
    if (name === "click") this.tone(660, 0.08, "triangle", 0.12);
    if (name === "coin") { this.tone(988, 0.12, "square", 0.06); this.tone(1319, 0.2, "square", 0.06, 0.08); }
    if (name === "fanfare") [523, 659, 784, 1046].forEach((f, i) => this.tone(f, 0.35, "sawtooth", 0.05, i * 0.12));
    if (name === "drums") for (let i = 0; i < 6; i++) { this.tone(80, 0.18, "sine", 0.35, i * 0.28); this.noise(0.05, 0.1, 300); }
    if (name === "clash") { this.noise(0.4, 0.35, 2500); this.noise(0.6, 0.25, 600); this.tone(110, 0.5, "sawtooth", 0.08); }
    if (name === "error") this.tone(180, 0.25, "square", 0.08);
  },
  startMusic() { // slow generative pads on a pentatonic scale
    const scale = [196, 220, 262, 294, 330, 392, 440];
    const chord = () => {
      if (!G.sound || !this.ctx) return;
      const root = scale[Math.floor(Math.random() * 3)];
      [1, 1.5, 2, 2.5].forEach((m, i) => {
        const t = this.ctx.currentTime, o = this.ctx.createOscillator(), g = this.ctx.createGain(), f = this.ctx.createBiquadFilter();
        o.type = "triangle"; o.frequency.value = root * m * (i === 3 ? 1.0 : 1); f.type = "lowpass"; f.frequency.value = 900;
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.025, t + 2.5); g.gain.linearRampToValueAtTime(0, t + 7.5);
        o.connect(f).connect(g).connect(this.master); o.start(t); o.stop(t + 8);
      });
      if (Math.random() < 0.7) this.tone(scale[3 + Math.floor(Math.random() * 4)] * 2, 1.4, "sine", 0.03, 1 + Math.random() * 3);
    };
    chord(); this.music = setInterval(chord, 7000);
  },
  say(text) {
    if (!G.sound || !("speechSynthesis" in window) || !text) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    const voices = speechSynthesis.getVoices();
    u.voice = voices.find(v => /en-(GB|IN)/.test(v.lang) && /female|Sonia|Libby|Neerja|Hazel|Susan/i.test(v.name)) ||
      voices.find(v => v.lang.startsWith("en")) || null;
    u.rate = 1.0; u.pitch = 1.05; u.volume = 0.9;
    speechSynthesis.speak(u);
  },
};

// ================================================================ menu
let presets = [], chosen = null;
async function initMenu() {
  presets = await api("presets");
  const box = $("regions");
  presets.forEach((p, i) => {
    const el = document.createElement("div");
    el.className = "region" + (i === 0 ? " sel" : "");
    el.innerHTML = `<b>${p.name}</b><p>${p.summary}</p><span class="era">${yr(p.years[0])} to ${yr(p.years[1])}</span>`;
    el.onclick = () => { Audio.init(); Audio.sfx("click"); [...box.children].forEach(c => c.classList.remove("sel")); el.classList.add("sel"); pick(p); };
    box.appendChild(el);
  });
  pick(presets[0]);
  $("pop").oninput = () => ($("popLabel").textContent = fmt(+$("pop").value));
  $("kcount").oninput = () => ($("kLabel").textContent = $("kcount").value);
  $("year").oninput = () => ($("yearLabel").textContent = yr(+$("year").value));
  $("found").onclick = found;
  try { await api("state"); $("continue").classList.remove("hidden"); } catch (e) { /* no saved world */ }
  $("continue").onclick = () => { Audio.init(); start(false); };
  const demo = new URLSearchParams(location.search).get("demo");
  if (demo) {
    const p = presets.find(x => x.id === demo) || presets[0];
    await api("new", {preset: p.id, year: p.default_year, population: 3500, kingdoms: 7, seed: 7});
    await api("player", {id: 0}); await start(false);
    const ins = new URLSearchParams(location.search).get("inspect");
    if (ins !== null) inspect(+ins);
  }
}
function pick(p) {
  chosen = p; const r = $("year"); r.min = p.years[0]; r.max = p.years[1]; r.step = 10; r.value = p.default_year;
  $("yearLabel").textContent = yr(p.default_year);
}
async function found() {
  Audio.init(); Audio.sfx("click");
  $("found").disabled = true; $("loading").classList.remove("hidden"); $("loadingText").textContent = "Shaping the land…";
  try {
    await api("new", {preset: chosen.id, year: +$("year").value, population: +$("pop").value, kingdoms: +$("kcount").value, seed: +$("seed").value});
    await start(true);
  } catch (e) { toast(e.message); } finally { $("found").disabled = false; $("loading").classList.add("hidden"); }
}
async function start(choose) {
  $("menu").classList.add("hidden"); $("loading").classList.remove("hidden"); $("loadingText").textContent = "Raising castles…";
  const [terrain, state] = await Promise.all([api("terrain"), api("state")]);
  G.terrain = terrain; G.state = state;
  World.build();
  $("loading").classList.add("hidden");
  if (choose) chooser(); else play();
}
function chooser() {
  const box = $("dynasties"); box.innerHTML = "";
  G.state.kingdoms.forEach(k => {
    const el = document.createElement("div"); el.className = "dyn";
    const king = k.characters.find(c => c.role === "ruler");
    el.innerHTML = `<b style="color:${k.color}">House of ${k.name}</b><small>King ${king.name} · ${k.laws} laws</small>
      <small>👥 ${fmt(k.population)} · ⚔ ${k.troops} · 🏰 walls ${k.walls}</small>`;
    el.onmouseenter = () => World.focus(k.id, 1.2);
    el.onclick = async () => { Audio.sfx("fanfare"); await api("player", {id: k.id}); G.state.player = k.id; $("chooser").classList.add("hidden"); play(); };
    box.appendChild(el);
  });
  $("chooser").classList.remove("hidden");
}
async function play() {
  $("hud").classList.remove("hidden"); hud(); World.refresh(); World.focus(G.state.player, 1);
  $("navAvatar").innerHTML = portrait({name: "Vira", role: "navigator", age: 30}, "#d79b2b");
  showNavigator(await api("navigator"), true);
}

// ================================================================ HUD
const me = () => G.state.kingdoms[G.state.player];
const RES = [["gold", "🪙", "Gold"], ["food", "🌾", "Grain"], ["armour", "🛡", "Armour"], ["energy", "⚡", "Energy"],
  ["troops", "⚔", "Troops"], ["population", "👥", "People"], ["happiness", "😊", "Mood"]];
let lastRes = {};
function hud() {
  const k = me(); if (!k) return;
  $("crestDot").style.background = k.color; $("myName").textContent = "House of " + k.name;
  $("myLaws").textContent = `${k.laws} laws${k.vassal_of !== null ? " · vassal" : ""}`; $("myKarma").textContent = k.karma;
  $("resources").innerHTML = RES.map(([key, icon, label]) => {
    const v = key === "happiness" ? pct(k.happiness) : fmt(k[key]);
    const meter = key === "energy" ? `<span class="meter"><span style="width:${k.energy}%"></span></span>` :
      key === "happiness" ? `<span class="meter"><span style="width:${k.happiness * 100}%"></span></span>` : "";
    const changed = lastRes[key] !== undefined && lastRes[key] !== k[key] ? " pulse" : "";
    return `<div class="res${changed}" title="${label}"><i>${icon}</i><div><b>${v}</b><small>${label}</small></div>${meter}</div>`;
  }).join("");
  lastRes = Object.fromEntries(RES.map(([key]) => [key, k[key]]));
  $("yearNow").textContent = G.state.label;
  $("wallCost").textContent = k.walls >= 5 ? "max level" : `${250 * (k.walls + 1)} gold`;
  $("realmList").innerHTML = G.state.kingdoms.map(r => `<div class="realm${r.id === G.state.player ? " me" : ""}${r.alive ? "" : " fallen"}" data-id="${r.id}">
      <span class="dot" style="background:${r.color}"></span><div><b>${r.name}</b><small>👥 ${fmt(r.population)} · ⚔ ${r.troops} · ☯ ${r.karma}</small></div>
      <small class="law">${{liberal: "Liberal", authoritarian: "Autocracy", socialist: "Socialist"}[r.laws] || r.laws}</small><div class="hp"><span style="width:${r.happiness * 100}%;background:${r.color}"></span></div></div>`).join("");
  document.querySelectorAll(".realm").forEach(el => (el.onclick = () => { World.focus(+el.dataset.id, 0.9); inspect(+el.dataset.id); }));
  $("chronicle").innerHTML = G.state.chronicle.slice(-16).reverse().map(e => `<div class="${e.kind}"><b>${e.label}</b>${e.text}</div>`).join("");
  if (G.state.quest) $("navTip").textContent = `Quest: ${G.state.quest.goal} (reward ${G.state.quest.reward} gold).`;
}
function apply(res) {
  if (res.state) { G.state = res.state; hud(); World.refresh(); }
  if (res.navigator) showNavigator(res.navigator);
}
async function act(action, extra = {}, button) {
  if (button) button.classList.add("busy");
  try { const res = await api("action", {action, ...extra}); apply(res); return res.result; }
  catch (e) { toast(e.message); Audio.sfx("error"); return null; }
  finally { if (button) button.classList.remove("busy"); }
}
document.querySelectorAll(".act[data-act]").forEach(b => (b.onclick = async () => {
  Audio.sfx("click");
  const a = b.dataset.act, n = a === "train" ? Math.max(10, Math.round(me().population * 0.04)) : 30;
  const r = await act(a, {n}, b); if (!r) return;
  const ok = r.accepted !== false && !/not enough|costs|over budget|cooldown|highest/i.test(r.message || "");
  toast(r.message); Audio.sfx(ok ? (a === "harvest_festival" ? "fanfare" : "coin") : "error");
  if (ok && a === "harvest_festival") World.celebrate(G.state.player);
}));
async function step(years = 1) {
  if (G.busy) return; G.busy = true;
  try { const res = await api("step", {years}); apply(res); World.playEvents(res.events); }
  catch (e) { toast(e.message); } finally { G.busy = false; }
}
function speed(mode) {
  clearInterval(G.timer); G.playing = mode; Audio.sfx("click");
  ["pause", "play", "fast"].forEach(id => $(id).classList.remove("on"));
  $(["pause", "play", "fast"][mode]).classList.add("on");
  if (mode) G.timer = setInterval(() => step(1), mode === 1 ? 3000 : 1200);
}
$("pause").onclick = () => speed(0); $("play").onclick = () => speed(1); $("fast").onclick = () => speed(2);
$("stepBtn").onclick = () => { Audio.sfx("click"); step(1); };
$("sound").onclick = () => { G.sound = !G.sound; $("sound").textContent = G.sound ? "🔊" : "🔇"; if (!G.sound) speechSynthesis.cancel(); };
$("attackBtn").onclick = () => {
  G.attackMode = !G.attackMode; $("attackBtn").classList.toggle("on", G.attackMode); Audio.sfx("click");
  World.showTargets(G.attackMode); toast(G.attackMode ? "Choose a realm within marching range" : "Attack cancelled");
};
$("closeInspector").onclick = () => $("inspector").classList.add("hidden");
$("cancelAttack").onclick = () => $("attackModal").classList.add("hidden");

// navigator
function showNavigator(nav, speak = false) {
  const changed = nav.id !== showNavigator.last;
  $("navText").textContent = nav.text; $("navStep").textContent = `${nav.index + 1} / ${nav.total}`;
  $("navNext").textContent = nav.index + 1 >= nav.total ? "Done" : "Next";
  const tip = nav.tip; $("navTip").classList.toggle("hidden", !tip && !G.state.quest);
  if (tip) $("navTip").textContent = "Tip: " + tip;
  if (changed || speak) Audio.say(nav.text);
  showNavigator.last = nav.id;
}
$("navNext").onclick = async () => { Audio.sfx("click"); showNavigator(await api("navigator", {event: "next"})); };
$("navHide").onclick = () => { $("navigator").classList.add("hidden"); $("navShow").classList.remove("hidden"); speechSynthesis.cancel(); };
$("navShow").onclick = () => { $("navigator").classList.remove("hidden"); $("navShow").classList.add("hidden"); };
$("askForm").onsubmit = async e => {
  e.preventDefault(); const q = $("askInput").value.trim(); if (!q) return;
  $("navText").textContent = "…"; $("askInput").value = "";
  try { const a = await api("navigator/ask", {question: q}); $("navText").textContent = a.answer; Audio.say(a.answer); }
  catch (err) { $("navText").textContent = "I could not hear you over the market noise. Try again?"; }
};

// attack and inspector
async function openAttack(target) {
  const k = G.state.kingdoms[target], r = await act("check_attack", {target}); if (!r) return;
  const row = (label, key) => `<span>${label}</span><span class="${r.have[key] >= r.needs[key] ? "ok" : "no"}">${fmt(r.have[key])}</span><span>need ${fmt(r.needs[key])}</span>`;
  $("attackTitle").textContent = `March on the House of ${k.name}`;
  $("attackBody").innerHTML = `<p>${r.in_reach ? "Within marching range." : "<b class='no'>Too far to march.</b>"}
    Defenders: about ${fmt(k.troops)} troops behind walls level ${k.walls}.</p>
    <div class="req">${row("⚔ Troops sent", "troops")}${row("🌾 Grain", "food")}${row("⚡ Energy", "energy")}${row("🛡 Armour", "armour")}</div>`;
  $("launch").disabled = !r.ok;
  $("launch").onclick = async () => {
    $("attackModal").classList.add("hidden"); G.attackMode = false; $("attackBtn").classList.remove("on"); World.showTargets(false);
    Audio.sfx("drums");
    const result = await act("attack", {target}); if (!result) return;
    if (!result.ok) { toast(result.reason); return; }
    World.march(G.state.player, target, result.won, result);
  };
  $("attackModal").classList.remove("hidden");
}
function portrait(c, color) {
  const r = rng([...c.name].reduce((a, ch) => a + ch.charCodeAt(0), c.age));
  const skin = ["#f1c27d", "#e0ac69", "#c68642", "#8d5524", "#ffdbac"][Math.floor(r() * 5)];
  const hair = ["#2b1b0e", "#4a3020", "#8a5a2b", "#c9a15a", "#9a9a9a"][Math.floor(r() * 5)];
  const hat = {ruler: `<path d="M13 13 l4 -8 l4 6 l4 -7 l4 7 l4 -6 l4 8z" fill="#f4c95d" stroke="#5a3d0a" stroke-width="1"/>`,
    general: `<path d="M11 20 q13 -17 26 0z" fill="#9aa5b1"/>`, sage: `<path d="M9 25 q15 -26 30 0 l0 6 q-15 -8 -30 0z" fill="#3b4a8a"/>`,
    high_priest: `<rect x="15" y="4" width="18" height="12" rx="3" fill="#efe6d4"/>`, merchant: `<ellipse cx="24" cy="14" rx="13" ry="6" fill="#6d3fb8"/>`,
    builder: `<path d="M11 18 h26 v-4 q-13 -8 -26 0z" fill="#d9822b"/>`,
    navigator: `<path d="M10 22 q14 -22 28 0 q-6 -6 -14 -6 q-8 0 -14 6z" fill="#1f5f8b"/><circle cx="24" cy="9" r="3" fill="#f4c95d"/>`}[c.role] || "";
  return `<svg viewBox="0 0 48 48"><defs><radialGradient id="g${c.name}${c.age}" cx="50%" cy="35%"><stop offset="0" stop-color="${color}" stop-opacity=".55"/>
    <stop offset="1" stop-color="${color}" stop-opacity=".15"/></radialGradient></defs><circle cx="24" cy="24" r="23" fill="url(#g${c.name}${c.age})" stroke="${color}"/>
    <path d="M8 46 q16 -16 32 0z" fill="${color}"/><circle cx="24" cy="24" r="11" fill="${skin}"/><path d="M13 22 q11 -14 22 0 q-11 -5 -22 0z" fill="${hair}"/>
    <circle cx="20" cy="25" r="1.5" fill="#222"/><circle cx="28" cy="25" r="1.5" fill="#222"/><path d="M20 30 q4 3 8 0" stroke="#222" fill="none" stroke-width="1.4"/>${hat}</svg>`;
}
const ROLE = {ruler: "King", general: "General", sage: "Sage", high_priest: "High priest", merchant: "Merchant prince", builder: "Master builder"};
async function inspect(id) {
  const k = await api("kingdom/" + id), p = k.people;
  const stat = (l, v) => `<div class="bar">${l}<span><i style="width:${v * 10}%"></i></span>${v}</div>`;
  $("inspectorBody").innerHTML = `<h2 style="color:${k.color}">House of ${k.name}</h2>
    <div class="chips"><span class="chip">${k.laws} laws</span><span class="chip">${k.free_speech ? "free speech" : "speech censored"}</span>
      <span class="chip">🏰 walls ${k.walls}</span><span class="chip">☯ karma ${k.karma}</span><span class="chip">mood ${pct(k.happiness)}</span>
      ${k.vassal_of !== null ? `<span class="chip">vassal of ${G.state.kingdoms[k.vassal_of].name}</span>` : ""}
      ${id === G.state.player ? '<span class="chip gold">your dynasty</span>' : ""}</div>
    <div class="people"><div><b>👑 ${p.king}</b><small>King</small></div><div><b>${fmt(p.soldiers)}</b><small>Soldiers</small></div>
      <div><b>${fmt(p.farmers)}</b><small>Farmers</small></div><div><b>${fmt(p.merchants)}</b><small>Merchants</small></div><div><b>${fmt(p.scholars)}</b><small>Scholars</small></div></div>
    <h3>Court</h3><div class="court">${k.characters.map(c => `<div class="char"><div class="top">${portrait(c, k.color)}
      <div><b>${c.name}</b><small>${ROLE[c.role] || c.role}, ${c.age}</small></div></div>
      <div class="chips"><span class="chip">${c.ideology}</span><span class="chip">☯ ${c.karma}</span></div>
      ${stat("Might", c.might)}${stat("Wisdom", c.wisdom)}${stat("Charisma", c.charisma)}${stat("Craft", c.craft)}
      <div class="chips">${c.knowledge.map(x => `<span class="chip">${x}</span>`).join("")}</div></div>`).join("")}</div>
    <h3>Most respected citizens</h3><table><tr><th>Name</th><th>Work</th><th>Karma</th><th>Wealth</th></tr>
      ${k.top_citizens.map(c => `<tr><td>${c.name}</td><td>${c.profession.replace("_", " ")}</td><td>${c.standing}</td><td>${c.wealth}</td></tr>`).join("")}</table>
    <h3>r/${k.name.toLowerCase()} · town square</h3>
    ${k.feed.slice().reverse().map(post => `<div class="post"><div class="votes">▲<span>${post.score}</span><span class="dn">▼</span></div>
      <div><div class="who">u/${post.author.replace(/ /g, "_").toLowerCase()} · ${post.profession.replace("_", " ")} · ${post.label}</div><p>${post.text}</p></div></div>`).join("") || "<p>Quiet so far.</p>"}
    <p class="fine">Posts are reviewed by this realm's Town Warden; rule-breaking posts are removed and cost karma.</p>`;
  $("inspector").classList.remove("hidden");
}

// ================================================================ the 3D world
const PALETTE = {sea: 0x2a6ea8, river: 0x3a8fd6, snow: 0xf3f6f9, mountain: 0x8e8577, hills: 0x96ab62, desert: 0xe3c27a,
  forest: 0x3f7a35, marsh: 0x5d8a58, plains: 0x86bd4f};
const World = {
  build() {
    if (this.renderer) { this.disposeWorld(); } else this.setup();
    const t = G.terrain; this.W = t.width; this.H = t.height;
    this.heights = new Float32Array(this.W * this.H);
    for (let i = 0; i < this.W * this.H; i++) {
      const b = t.biomes[t.biome[i]], e = t.elevation[i];
      this.heights[i] = b === "sea" ? -1.2 + e * 2 : b === "river" ? -0.35 : 0.15 + Math.max(0, e - 0.12) * 7.5;
    }
    this.root = new THREE.Group(); this.scene.add(this.root);
    this.terrainMesh(); this.water(); this.vegetation(); this.clouds();
    this.kingdomLayer = new THREE.Group(); this.root.add(this.kingdomLayer);
    this.cache = {};
  },
  setup() {
    const r = this.renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: "high-performance"});
    r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.setSize(innerWidth, innerHeight);
    r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05; r.outputColorSpace = THREE.SRGBColorSpace;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    $("scene").appendChild(r.domElement);
    this.scene = new THREE.Scene();
    const sky = document.createElement("canvas"); sky.width = 2; sky.height = 256; const c = sky.getContext("2d");
    const g = c.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, "#5b9bd5"); g.addColorStop(0.6, "#bcdcf2"); g.addColorStop(1, "#f3e3c3");
    c.fillStyle = g; c.fillRect(0, 0, 2, 256);
    this.scene.background = new THREE.CanvasTexture(sky); this.scene.background.colorSpace = THREE.SRGBColorSpace;
    this.scene.fog = new THREE.Fog(0xcfe3f2, 140, 260);
    this.camera = new THREE.PerspectiveCamera(38, innerWidth / innerHeight, 0.5, 600);
    this.camera.position.set(0, 92, 88);
    this.controls = new OrbitControls(this.camera, r.domElement);
    Object.assign(this.controls, {enableDamping: true, dampingFactor: 0.08, maxPolarAngle: 1.22, minDistance: 10, maxDistance: 170,
      screenSpacePanning: false});
    this.controls.mouseButtons = {LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE};
    this.scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x5a4a2a, 0.9));
    const sun = this.sun = new THREE.DirectionalLight(0xfff1d6, 2.4); sun.position.set(-40, 70, 30); sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096); Object.assign(sun.shadow.camera, {left: -80, right: 80, top: 60, bottom: -60, near: 1, far: 200});
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03; this.scene.add(sun);
    this.clock = new THREE.Clock(); this.walkers = []; this.effects = []; this.labels = {};
    this.raycaster = new THREE.Raycaster(); this.mouse = new THREE.Vector2();
    addEventListener("resize", () => {
      this.camera.aspect = innerWidth / innerHeight; this.camera.updateProjectionMatrix(); r.setSize(innerWidth, innerHeight);
      if (this.borderMat) this.borderMat.resolution.set(innerWidth, innerHeight);
    });
    let down = null;
    r.domElement.addEventListener("pointerdown", e => (down = [e.clientX, e.clientY]));
    r.domElement.addEventListener("pointerup", e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const id = this.pick(e); if (id === null) return;
      Audio.sfx("click");
      if (G.attackMode && id !== G.state.player) openAttack(id); else { inspect(id); this.focus(id, 0.9); }
    });
    r.setAnimationLoop(() => this.frame());
  },
  disposeWorld() {
    this.scene.remove(this.root); this.walkers = []; this.effects = [];
    Object.values(this.labels).forEach(l => l.remove()); this.labels = {};
  },
  pos(x, y, lift = 0) { return new THREE.Vector3(x - (this.W - 1) / 2, this.h(x, y) + lift, y - (this.H - 1) / 2); },
  h(x, y) { // bilinear height at fractional tile coordinates
    const W = this.W, H = this.H, cx = Math.max(0, Math.min(W - 1.001, x)), cy = Math.max(0, Math.min(H - 1.001, y));
    const x0 = Math.floor(cx), y0 = Math.floor(cy), fx = cx - x0, fy = cy - y0, hs = this.heights;
    const a = hs[y0 * W + x0], b = hs[y0 * W + x0 + 1], c = hs[(y0 + 1) * W + x0], d = hs[(y0 + 1) * W + x0 + 1];
    return Math.max(0, (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy);
  },
  biome(x, y) { const t = G.terrain; return t.biomes[t.biome[Math.round(y) * this.W + Math.round(x)]]; },

  terrainMesh() {
    const W = this.W, H = this.H, t = G.terrain, r = rng(9);
    let geo = new THREE.PlaneGeometry(W - 1, H - 1, W - 1, H - 1); geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position, colors = new Float32Array(pos.count * 3), col = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      pos.setY(i, this.heights[i] + (r() - 0.5) * 0.12);
      const b = t.biomes[t.biome[i]];
      col.setHex(PALETTE[b]);
      if (b === "sea") col.lerp(new THREE.Color(0xd9c98f), Math.max(0, Math.min(1, (this.heights[i] + 0.4) * 1.4)));
      if (b === "river") col.setHex(0xc9b98a);
      if (b === "mountain" && this.heights[i] > 4.4) col.lerp(new THREE.Color(0xffffff), Math.min(1, (this.heights[i] - 4.4) * 0.8));
      col.offsetHSL(0, 0, (r() - 0.5) * 0.06);
      colors.set([col.r, col.g, col.b], i * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo = geo.toNonIndexed(); geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({vertexColors: true, flatShading: true, roughness: 0.95}));
    mesh.receiveShadow = true; mesh.castShadow = true; this.root.add(mesh);
  },
  water() {
    const geo = new THREE.PlaneGeometry(this.W + 80, this.H + 80, 120, 80); geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({color: 0x2f86d0, transparent: true, opacity: 0.82, roughness: 0.18, metalness: 0.15, flatShading: true});
    mat.onBeforeCompile = shader => {
      shader.uniforms.uTime = this.waterTime = {value: 0};
      shader.vertexShader = "uniform float uTime;\n" + shader.vertexShader.replace("#include <begin_vertex>",
        "#include <begin_vertex>\n transformed.y += sin(position.x*0.55+uTime*1.3)*0.06 + cos(position.z*0.7+uTime*1.1)*0.05;");
    };
    const mesh = new THREE.Mesh(geo, mat); mesh.position.y = -0.08; mesh.receiveShadow = true; this.root.add(mesh);
  },
  vegetation() {
    const W = this.W, H = this.H, r = rng(21), broad = [], pine = [], rocks = [];
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const b = this.biome(x, y);
      if (b === "forest") for (let i = 0; i < 2; i++) (r() < 0.65 ? broad : pine).push([x + (r() - 0.5) * 0.9, y + (r() - 0.5) * 0.9]);
      else if (b === "hills" && r() < 0.35) pine.push([x + (r() - 0.5) * 0.8, y + (r() - 0.5) * 0.8]);
      else if (b === "marsh" && r() < 0.3) broad.push([x, y]);
      else if (b === "plains" && r() < 0.025) broad.push([x + (r() - 0.5), y + (r() - 0.5)]);
      else if ((b === "mountain" || b === "snow") && r() < 0.25) rocks.push([x + (r() - 0.5), y + (r() - 0.5)]);
    }
    const place = (geo, mat, list, lift, scale, tint) => {
      const m = new THREE.InstancedMesh(geo, mat, list.length), o = new THREE.Object3D(), c = new THREE.Color();
      list.forEach(([x, y], i) => {
        const s = scale * (0.75 + r() * 0.6); o.position.copy(this.pos(x, y, lift * s)); o.rotation.y = r() * 6.28; o.scale.setScalar(s);
        o.updateMatrix(); m.setMatrixAt(i, o.matrix); c.setHex(tint[Math.floor(r() * tint.length)]); m.setColorAt(i, c);
      });
      m.castShadow = true; m.receiveShadow = true; this.root.add(m); return m;
    };
    const leaf = new THREE.MeshStandardMaterial({flatShading: true, roughness: 0.9});
    place(new THREE.IcosahedronGeometry(0.42, 0), leaf, broad, 0.62, 1, [0x4f9a3f, 0x3f8a36, 0x67ad4a, 0x7cb342]);
    place(new THREE.ConeGeometry(0.34, 1.0, 6), leaf.clone(), pine, 0.55, 1, [0x2f6e3a, 0x2d6332, 0x3c7d45]);
    const trunks = broad.concat(pine);
    place(new THREE.CylinderGeometry(0.05, 0.07, 0.35, 5), new THREE.MeshStandardMaterial({color: 0x6b4a2b}), trunks, 0.17, 1, [0x6b4a2b]);
    place(new THREE.DodecahedronGeometry(0.35, 0), new THREE.MeshStandardMaterial({flatShading: true, roughness: 1}), rocks, 0.15, 1, [0x8d8579, 0x7a7266, 0xa39a8d]);
  },
  clouds() {
    this.cloudList = [];
    const mat = new THREE.MeshStandardMaterial({color: 0xffffff, flatShading: true, transparent: true, opacity: 0.7, roughness: 1, depthWrite: false});
    const r = rng(5);
    for (let i = 0; i < 12; i++) {
      const g = new THREE.Group();
      for (let j = 0; j < 5; j++) {
        const puff = new THREE.Mesh(new THREE.IcosahedronGeometry(0.7 + r() * 0.8, 1), mat);
        puff.position.set((r() - 0.5) * 3.2, (r() - 0.5) * 0.5, (r() - 0.5) * 1.6); g.add(puff);
      }
      g.position.set((r() - 0.5) * this.W, 26 + r() * 6, (r() - 0.5) * this.H); g.userData.v = 0.6 + r() * 0.8;
      this.root.add(g); this.cloudList.push(g);
    }
  },

  // ---------------------------------------------------------- kingdoms
  refresh() {
    if (!G.state || !this.kingdomLayer) return;
    this.borders();
    G.state.kingdoms.forEach(k => {
      const sig = [k.alive, k.walls, Math.min(40, k.buildings.houses), Math.min(36, k.buildings.farms),
        Math.min(8, Math.ceil(k.people.soldiers / 12)), Math.min(8, Math.ceil(k.people.farmers / 30)),
        Math.min(4, Math.ceil(k.people.merchants / 40)), Math.min(3, Math.ceil(k.people.scholars / 30))].join(",");
      if (this.cache[k.id] && this.cache[k.id].sig === sig) return;
      if (this.cache[k.id]) { this.kingdomLayer.remove(this.cache[k.id].group); this.walkers = this.walkers.filter(w => w.kid !== k.id); }
      const group = this.kingdom(k); this.kingdomLayer.add(group); this.cache[k.id] = {sig, group};
    });
    this.label();
  },
  borders() {
    if (this.borderMesh) this.root.remove(this.borderMesh);
    const own = G.state.owner, W = this.W, H = this.H, pts = [], cols = [], col = new THREE.Color();
    const seg = (x1, y1, x2, y2, k) => {
      const a = this.pos(x1, y1, 0.12), b = this.pos(x2, y2, 0.12); pts.push(a.x, a.y, a.z, b.x, b.y, b.z);
      col.set(G.state.kingdoms[k].color); cols.push(col.r, col.g, col.b, col.r, col.g, col.b);
    };
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const o = own[y * W + x]; if (o < 0) continue;
      if (x + 1 >= W || own[y * W + x + 1] !== o) seg(x + 0.5, y - 0.5, x + 0.5, y + 0.5, o);
      if (x === 0 || own[y * W + x - 1] !== o) seg(x - 0.5, y - 0.5, x - 0.5, y + 0.5, o);
      if (y + 1 >= H || own[(y + 1) * W + x] !== o) seg(x - 0.5, y + 0.5, x + 0.5, y + 0.5, o);
      if (y === 0 || own[(y - 1) * W + x] !== o) seg(x - 0.5, y - 0.5, x + 0.5, y - 0.5, o);
    }
    const geo = new LineSegmentsGeometry(); geo.setPositions(pts); geo.setColors(cols);
    this.borderMat = this.borderMat || new LineMaterial({linewidth: 2.5, vertexColors: true, transparent: true, opacity: 0.85});
    this.borderMat.resolution.set(innerWidth, innerHeight);
    this.borderMesh = new LineSegments2(geo, this.borderMat); this.root.add(this.borderMesh);
  },
  mats: {},
  mat(hex, opts = {}) {
    const key = hex + JSON.stringify(opts);
    return this.mats[key] || (this.mats[key] = new THREE.MeshStandardMaterial({color: hex, flatShading: true, roughness: 0.85, ...opts}));
  },
  mesh(geo, mat, x = 0, y = 0, z = 0) { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; return m; },

  castle(k) {
    const g = new THREE.Group(), stone = this.mat(0xcfc4ad), dark = this.mat(0x8f8573), roof = this.mat(new THREE.Color(k.color).getHex());
    const walls = k.walls, R = 1.35 + walls * 0.22;
    g.add(this.mesh(new THREE.CylinderGeometry(R + 0.35, R + 0.55, 0.3, 14), dark, 0, 0.1, 0));
    const n = 12;
    for (let i = 0; i < n; i++) {
      const a = i / n * Math.PI * 2, seg = this.mesh(new THREE.BoxGeometry(2 * Math.PI * R / n + 0.05, 0.45 + walls * 0.09, 0.22), stone,
        Math.cos(a) * R, 0.45, Math.sin(a) * R);
      seg.rotation.y = -a + Math.PI / 2; g.add(seg);
      if (i % 2 === 0) { const c = this.mesh(new THREE.BoxGeometry(0.12, 0.14, 0.24), stone, Math.cos(a) * R, 0.75 + walls * 0.05, Math.sin(a) * R); c.rotation.y = seg.rotation.y; g.add(c); }
    }
    const towers = 4 + Math.min(4, walls);
    for (let i = 0; i < towers; i++) {
      const a = i / towers * Math.PI * 2 + 0.3, x = Math.cos(a) * R, z = Math.sin(a) * R, th = 1.0 + walls * 0.14;
      g.add(this.mesh(new THREE.CylinderGeometry(0.24, 0.28, th, 8), stone, x, th / 2 + 0.2, z));
      g.add(this.mesh(new THREE.ConeGeometry(0.34, 0.5, 8), roof, x, th + 0.45, z));
    }
    g.add(this.mesh(new THREE.BoxGeometry(1.0, 1.6 + walls * 0.1, 1.0), stone, 0, 1.0, 0));
    const keepRoof = this.mesh(new THREE.ConeGeometry(0.85, 1.0, 4), roof, 0, 2.3 + walls * 0.05, 0); keepRoof.rotation.y = Math.PI / 4; g.add(keepRoof);
    g.add(this.mesh(new THREE.BoxGeometry(0.34, 0.5, 0.06), this.mat(0x3b2a1a), 0, 0.45, R + 0.02));
    const pole = this.mesh(new THREE.CylinderGeometry(0.025, 0.025, 1.0, 5), this.mat(0x5a4632), 0, 3.2, 0); g.add(pole);
    const flag = this.mesh(new THREE.PlaneGeometry(0.6, 0.36, 4, 1), this.mat(new THREE.Color(k.color).getHex(), {side: THREE.DoubleSide}), 0.3, 3.5, 0);
    g.add(flag); g.userData.flag = flag;
    if (!k.alive) g.traverse(o => o.isMesh && (o.material = this.mat(0x5d5d5d)));
    return g;
  },
  homes(k) {
    const own = G.state.owner, W = this.W, [cx, cy] = k.capital, out = [];
    for (let y = Math.max(0, cy - 11); y < Math.min(this.H, cy + 12); y++)
      for (let x = Math.max(0, cx - 11); x < Math.min(W, cx + 12); x++) {
        const b = this.biome(x, y), d = Math.hypot(x - cx, y - cy);
        if (own[y * W + x] === k.id && d >= 2.5 && !["sea", "river", "mountain", "snow", "forest"].includes(b))
          out.push({x, y, d, wet: G.terrain.moisture[y * W + x]});
      }
    return out.sort((a, b) => a.d - b.d);
  },
  kingdom(k) {
    const group = new THREE.Group(), r = rng(k.id * 131 + 7), [cx, cy] = k.capital, here = this.pos(cx, cy);
    const castle = this.castle(k); castle.position.copy(here); castle.userData.kid = k.id; group.add(castle); k._castle = castle;
    castle.traverse(o => (o.userData.kid = k.id));
    if (!k.alive) return group;
    const tiles = this.homes(k), houses = tiles.slice(0, Math.min(40, k.buildings.houses));
    const tint = new THREE.Color(k.color);
    const bodyGeo = new THREE.BoxGeometry(0.42, 0.32, 0.42), roofGeo = new THREE.ConeGeometry(0.38, 0.3, 4);
    const body = new THREE.InstancedMesh(bodyGeo, this.mat(0xead7b0), houses.length), roofs = new THREE.InstancedMesh(roofGeo, this.mat(0xffffff), houses.length);
    const o = new THREE.Object3D(), c = new THREE.Color();
    houses.forEach((t, i) => {
      const x = t.x + (r() - 0.5) * 0.5, y = t.y + (r() - 0.5) * 0.5, s = 0.85 + r() * 0.35;
      o.position.copy(this.pos(x, y, 0.16 * s)); o.rotation.y = r() * 1.5; o.scale.setScalar(s); o.updateMatrix(); body.setMatrixAt(i, o.matrix);
      o.position.y += 0.3 * s; o.rotation.y += Math.PI / 4; o.updateMatrix(); roofs.setMatrixAt(i, o.matrix);
      c.setHex(r() < 0.5 ? 0xb5532a : 0xa65d3a).lerp(tint, 0.35); roofs.setColorAt(i, c);
    });
    [body, roofs].forEach(m => { m.castShadow = true; m.receiveShadow = true; group.add(m); });
    const farms = tiles.filter(t => t.d >= 4 && t.wet > 0.28).slice(0, Math.min(36, k.buildings.farms + 4));
    if (farms.length) {
      const fm = new THREE.InstancedMesh(new THREE.BoxGeometry(0.92, 0.05, 0.92), this.mat(0xffffff), farms.length);
      farms.forEach((t, i) => { o.position.copy(this.pos(t.x, t.y, 0.04)); o.rotation.y = 0; o.scale.setScalar(1); o.updateMatrix(); fm.setMatrixAt(i, o.matrix);
        c.setHex([0xd8b84a, 0xa5c84f, 0xc9a43c, 0x8fbf4a][Math.floor(r() * 4)]); fm.setColorAt(i, c); });
      fm.receiveShadow = true; group.add(fm);
    }
    if (houses[2]) { // temple
      const tp = new THREE.Group(), st = this.mat(0xe7dbc0);
      [[1.1, 0.25], [0.8, 0.25], [0.5, 0.25]].forEach(([w, h], i) => tp.add(this.mesh(new THREE.BoxGeometry(w, h, w), st, 0, 0.12 + i * 0.25, 0)));
      tp.add(this.mesh(new THREE.ConeGeometry(0.2, 0.4, 4), this.mat(0xf4c95d), 0, 0.95, 0));
      tp.position.copy(this.pos(houses[2].x, houses[2].y)); group.add(tp);
    }
    if (houses[5]) { // market
      const mk = new THREE.Group();
      mk.add(this.mesh(new THREE.ConeGeometry(0.5, 0.45, 8), this.mat(0xd0402c), 0, 0.55, 0));
      mk.add(this.mesh(new THREE.CylinderGeometry(0.42, 0.42, 0.3, 8), this.mat(0xead7b0), 0, 0.17, 0));
      mk.position.copy(this.pos(houses[5].x, houses[5].y)); group.add(mk);
    }
    this.people(k, group, tiles, farms, r);
    return group;
  },
  figure(type, color) {
    const g = new THREE.Group(), skin = this.mat(0xe0ac69);
    const bodyCol = {king: 0x6a1b9a, soldier: new THREE.Color(color).getHex(), farmer: 0x6d8b3a, merchant: 0x2e7d7a, scholar: 0x2f4f9a}[type];
    g.add(this.mesh(new THREE.CylinderGeometry(0.07, 0.11, 0.3, 6), this.mat(bodyCol), 0, 0.15, 0));
    g.add(this.mesh(new THREE.SphereGeometry(0.07, 8, 6), skin, 0, 0.37, 0));
    if (type === "king") {
      g.add(this.mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.06, 6), this.mat(0xf4c95d, {metalness: 0.6, roughness: 0.3}), 0, 0.45, 0));
      g.add(this.mesh(new THREE.ConeGeometry(0.16, 0.3, 6), this.mat(0x4a148c), 0, 0.08, 0));
      g.scale.setScalar(1.4);
    } else if (type === "soldier") {
      g.add(this.mesh(new THREE.SphereGeometry(0.075, 8, 4, 0, 6.3, 0, 1.6), this.mat(0x9aa5b1, {metalness: 0.5, roughness: 0.4}), 0, 0.39, 0));
      g.add(this.mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.6, 4), this.mat(0x6b4a2b), 0.11, 0.3, 0));
      const shield = this.mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.02, 10), this.mat(new THREE.Color(color).getHex()), -0.09, 0.2, 0.02);
      shield.rotation.z = Math.PI / 2; g.add(shield);
    } else if (type === "farmer") {
      g.add(this.mesh(new THREE.ConeGeometry(0.14, 0.07, 10), this.mat(0xd9b65a), 0, 0.45, 0));
    } else if (type === "merchant") {
      g.add(this.mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.07, 8), this.mat(0x8e2a5e), 0, 0.45, 0));
      g.add(this.mesh(new THREE.BoxGeometry(0.1, 0.08, 0.06), this.mat(0x8a5a2b), 0.1, 0.18, 0));
    } else if (type === "scholar") {
      g.add(this.mesh(new THREE.ConeGeometry(0.09, 0.14, 8), this.mat(0x23336e), 0, 0.46, 0));
    }
    g.scale.multiplyScalar(1.8);
    return g;
  },
  people(k, group, tiles, farms, r) {
    const [cx, cy] = k.capital, add = (type, count, spots) => {
      for (let i = 0; i < count && spots.length; i++) {
        const f = this.figure(type, k.color), s = spots[Math.floor(r() * spots.length)];
        f.position.copy(this.pos(s.x, s.y)); group.add(f);
        this.walkers.push({kid: k.id, f, type, spots, target: null, speed: type === "soldier" ? 1.4 : type === "king" ? 0.4 : 0.9, wait: r() * 2});
      }
    };
    const ring = []; for (let a = 0; a < 12; a++) ring.push({x: cx + Math.cos(a / 12 * 6.28) * (2.2 + k.walls * 0.25), y: cy + Math.sin(a / 12 * 6.28) * (2.2 + k.walls * 0.25)});
    add("king", 1, [{x: cx, y: cy + 1.7}, {x: cx + 0.6, y: cy + 1.9}, {x: cx - 0.6, y: cy + 1.9}]);
    add("soldier", Math.min(8, Math.ceil(k.people.soldiers / 12)), ring);
    add("farmer", Math.min(8, Math.ceil(k.people.farmers / 30)), farms.length ? farms : tiles.slice(0, 20));
    add("merchant", Math.min(4, Math.ceil(k.people.merchants / 40)), tiles.slice(0, 18));
    add("scholar", Math.min(3, Math.ceil(k.people.scholars / 30)), tiles.slice(0, 12));
  },
  label() {
    G.state.kingdoms.forEach(k => {
      let el = this.labels[k.id];
      if (!el) { el = this.labels[k.id] = document.createElement("div"); el.className = "klabel"; $("labels").appendChild(el); }
      el.innerHTML = `<b style="color:${k.color}">${k.name}${k.id === G.state.player ? " ★" : ""}</b><small>👥 ${fmt(k.population)} · ⚔ ${k.troops}${k.alive ? "" : " · fallen"}</small>`;
    });
  },
  pick(e) {
    this.mouse.set(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const castles = Object.values(this.cache).map(c => c.group.children[0]);
    const hit = this.raycaster.intersectObjects(castles, true)[0];
    return hit ? hit.object.userData.kid : null;
  },
  focus(id, zoom = 1) {
    const k = G.state.kingdoms[id]; if (!k) return;
    const p = this.pos(k.capital[0], k.capital[1]);
    this.flyTo = {target: p, dist: 34 * zoom, t: 0};
  },
  showTargets(on) {
    (this.rings || []).forEach(m => this.root.remove(m)); this.rings = [];
    if (!on) return;
    api("kingdom/" + G.state.player).then(k => k.neighbours.forEach(id => {
      const t = G.state.kingdoms[id], ring = new THREE.Mesh(new THREE.RingGeometry(2.6, 3.0, 40),
        new THREE.MeshBasicMaterial({color: 0xff4a32, transparent: true, opacity: 0.8, side: THREE.DoubleSide}));
      ring.rotation.x = -Math.PI / 2; ring.position.copy(this.pos(t.capital[0], t.capital[1], 0.25)); this.root.add(ring); this.rings.push(ring);
    }));
  },
  floatText(pos3, text, color) {
    const v = pos3.clone().project(this.camera), el = document.createElement("div");
    el.className = "float"; el.style.color = color; el.textContent = text;
    el.style.left = ((v.x + 1) / 2 * innerWidth) + "px"; el.style.top = ((1 - v.y) / 2 * innerHeight) + "px";
    $("labels").appendChild(el); setTimeout(() => el.remove(), 1900);
  },
  burst(pos3, color, n = 60) {
    const geo = new THREE.BufferGeometry(), arr = new Float32Array(n * 3), vel = [];
    for (let i = 0; i < n; i++) { arr.set([pos3.x, pos3.y + 0.6, pos3.z], i * 3); vel.push(new THREE.Vector3((Math.random() - 0.5) * 6, Math.random() * 6, (Math.random() - 0.5) * 6)); }
    geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({color, size: 0.35, transparent: true, opacity: 1}));
    this.root.add(pts); this.effects.push({obj: pts, vel, life: 1.4, kind: "burst"});
  },
  march(from, to, won, result) {
    const a = G.state.kingdoms[from], b = G.state.kingdoms[to];
    const army = new THREE.Group(); this.root.add(army);
    for (let i = 0; i < 14; i++) { const s = this.figure("soldier", a.color); s.position.set((i % 4) * 0.5 - 0.75, 0, Math.floor(i / 4) * 0.5); army.add(s); }
    this.effects.push({obj: army, kind: "march", from: [a.capital[0], a.capital[1]], to: [b.capital[0], b.capital[1]], t: 0, dur: 3.2,
      done: () => {
        const p = this.pos(b.capital[0], b.capital[1]); Audio.sfx("clash"); this.burst(p, 0xffd25a); this.burst(p, 0x888888, 40);
        const mine = from === G.state.player;
        this.floatText(p.clone().setY(p.y + 4), won ? (mine ? "Victory!" : "Raided!") : (mine ? "Repelled!" : "Defended!"), won ? "#f4c95d" : "#ff7a59");
        if (mine && result) toast(won ? `Victory: ${fmt(result.loot.gold)} gold and ${fmt(result.loot.food)} grain taken.` : "Our army was repelled.", 3500);
        if (mine && won) Audio.sfx("fanfare");
      }});
    if (from === G.state.player || to === G.state.player) this.focus(to, 1.3);
  },
  celebrate(id) {
    const k = G.state.kingdoms[id], p = this.pos(k.capital[0], k.capital[1]);
    [0xf4c95d, 0xff7ab6, 0x7ad7ff].forEach(c => this.burst(p.clone().setY(p.y + 2), c, 40));
  },
  playEvents(events) {
    events.filter(e => e.kind === "war").forEach((e, i) => setTimeout(() => { Audio.sfx("drums"); this.march(e.attacker, e.defender, e.won); }, i * 900));
    this.weather(events.filter(e => e.weather));
    const mine = events.filter(e => e.kingdom === G.state.player || e.defender === G.state.player);
    if (mine.length) { const last = mine[mine.length - 1]; toast(last.text, 3600); if (last.kind === "war" || last.kind === "liveops") Audio.say(last.text); }
  },
  weather(events) {
    for (const e of events) {
      const k = G.state.kingdoms[e.kingdom]; if (!k) continue;
      const c = this.pos(k.capital[0], k.capital[1]), n = 500, geo = new THREE.BufferGeometry(), arr = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) arr.set([c.x + (Math.random() - 0.5) * 18, 4 + Math.random() * 10, c.z + (Math.random() - 0.5) * 18], i * 3);
      geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
      const rain = e.weather === "rain";
      const pts = new THREE.Points(geo, new THREE.PointsMaterial({color: rain ? 0xbfe2ff : 0xe0a35a, size: rain ? 0.12 : 0.25, transparent: true, opacity: rain ? 0.8 : 0.5}));
      this.root.add(pts); this.effects.push({obj: pts, kind: rain ? "rain" : "dust", life: 6, base: c});
    }
  },

  // ---------------------------------------------------------- per frame
  frame() {
    const dt = Math.min(0.05, this.clock.getDelta()), time = this.clock.elapsedTime;
    if (this.waterTime) this.waterTime.value = time;
    if (this.flyTo) {
      const f = this.flyTo; f.t = Math.min(1, f.t + dt * 1.6);
      this.controls.target.lerp(f.target, 0.08);
      const dir = this.camera.position.clone().sub(this.controls.target).normalize();
      this.camera.position.lerp(this.controls.target.clone().add(dir.multiplyScalar(f.dist)), 0.06);
      if (f.t >= 1) this.flyTo = null;
    }
    this.controls.update();
    (this.cloudList || []).forEach(c => { c.position.x += c.userData.v * dt; if (c.position.x > this.W / 2 + 15) c.position.x = -this.W / 2 - 15; });
    Object.values(this.cache || {}).forEach(({group}) => { const fl = group.children[0].userData.flag; if (fl) fl.rotation.y = Math.sin(time * 3 + group.id) * 0.25; });
    for (const w of this.walkers) {
      if (w.wait > 0) { w.wait -= dt; continue; }
      if (!w.target) { const s = w.spots[Math.floor(Math.random() * w.spots.length)]; w.target = this.pos(s.x + (Math.random() - 0.5) * 0.6, s.y + (Math.random() - 0.5) * 0.6); }
      const d = w.target.clone().sub(w.f.position); d.y = 0; const dist = d.length();
      if (dist < 0.1) { w.target = null; w.wait = 0.5 + Math.random() * (w.type === "king" ? 4 : 2); continue; }
      d.normalize().multiplyScalar(Math.min(dist, w.speed * dt));
      w.f.position.add(d); w.f.rotation.y = Math.atan2(d.x, d.z);
      const gx = w.f.position.x + (this.W - 1) / 2, gy = w.f.position.z + (this.H - 1) / 2;
      w.f.position.y = this.h(gx, gy) + Math.abs(Math.sin(time * 9 + w.f.id)) * 0.05;
    }
    for (const e of this.effects) {
      if (e.kind === "march") {
        e.t += dt / e.dur; const u = Math.min(1, e.t), x = e.from[0] + (e.to[0] - e.from[0]) * u, y = e.from[1] + (e.to[1] - e.from[1]) * u;
        e.obj.position.copy(this.pos(x, y)); e.obj.rotation.y = Math.atan2(e.to[0] - e.from[0], e.to[1] - e.from[1]);
        e.obj.children.forEach((s, i) => (s.position.y = Math.abs(Math.sin(time * 10 + i)) * 0.1));
        if (u >= 1 && !e.fired) { e.fired = true; e.done(); e.life = 1.2; }
        if (e.fired) e.life -= dt;
      } else if (e.kind === "burst") {
        e.life -= dt; const a = e.obj.geometry.attributes.position;
        e.vel.forEach((v, i) => { v.y -= 9 * dt; a.setXYZ(i, a.getX(i) + v.x * dt, a.getY(i) + v.y * dt, a.getZ(i) + v.z * dt); });
        a.needsUpdate = true; e.obj.material.opacity = Math.max(0, e.life / 1.4);
      } else {
        e.life -= dt; const a = e.obj.geometry.attributes.position;
        for (let i = 0; i < a.count; i++) {
          let yv = a.getY(i) - (e.kind === "rain" ? 14 : 0.4) * dt; if (yv < 0.5) yv = 12;
          a.setY(i, yv); if (e.kind === "dust") a.setX(i, a.getX(i) + Math.sin(time + i) * 0.02);
        }
        a.needsUpdate = true; e.obj.material.opacity = Math.min(e.kind === "rain" ? 0.8 : 0.5, e.life / 2);
      }
    }
    this.effects = this.effects.filter(e => { const alive = e.kind === "march" ? !(e.fired && e.life <= 0) : e.life > 0; if (!alive) this.root.remove(e.obj); return alive; });
    if (G.state) for (const k of G.state.kingdoms) { // labels follow castles
      const el = this.labels[k.id]; if (!el) continue;
      const v = this.pos(k.capital[0], k.capital[1], 4.2).project(this.camera);
      const visible = v.z < 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1;
      el.style.display = visible ? "block" : "none";
      if (visible) { el.style.left = ((v.x + 1) / 2 * innerWidth) + "px"; el.style.top = ((1 - v.y) / 2 * innerHeight) + "px"; }
    }
    this.renderer.render(this.scene, this.camera);
  },
};

initMenu();
