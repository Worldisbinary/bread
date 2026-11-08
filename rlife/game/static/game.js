// r/life: Ages of Kingdoms. Browser client (Phaser 3).
// All art is drawn procedurally at load time: terrain with hillshade, rivers, forests,
// mountains, castles in each dynasty's colours, houses, farms, villagers, armies, weather.
"use strict";

const T = 20; // pixels per tile
const API = (path, body) =>
  fetch("/game/api/" + path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body),
  }).then(async r => { if (!r.ok) throw new Error((await r.json()).detail || r.statusText); return r.json(); });

const $ = id => document.getElementById(id);
const fmt = n => Math.round(n).toLocaleString();
const PALETTE = {
  sea: "#2c6db0", river: "#3f93db", snow: "#eef3f7", mountain: "#8b8276", hills: "#9db36b",
  desert: "#e6c47a", forest: "#3d7a35", marsh: "#5b8758", plains: "#8cc152",
};
const ROLE_ICON = {ruler: "👑", general: "⚔️", sage: "📜", high_priest: "🔥", merchant: "⚖️", builder: "🔨"};

function rng(seed) { // mulberry32: deterministic layout per kingdom
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}
function shade(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map(v => Math.max(0, Math.min(255, Math.round(v * f))));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}
function toast(text, ms = 2200) {
  const el = $("toast"); el.textContent = text; el.style.opacity = 1;
  clearTimeout(toast.t); toast.t = setTimeout(() => (el.style.opacity = 0), ms);
}

const G = {terrain: null, state: null, scene: null, attackMode: false, playing: 0, timer: null, lastYear: null};

// ---------------------------------------------------------------- menu
let presets = [], chosenPreset = null;
async function initMenu() {
  presets = await API("presets");
  const box = $("regions");
  presets.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "card" + (i === 0 ? " sel" : "");
    card.innerHTML = `<h4>${p.name}</h4><p>${p.summary}</p><div class="meta">${yr(p.years[0])} to ${yr(p.years[1])}</div>`;
    card.onclick = () => { [...box.children].forEach(c => c.classList.remove("sel")); card.classList.add("sel"); pick(p); };
    box.appendChild(card);
  });
  pick(presets[0]);
  $("pop").oninput = () => ($("popLabel").textContent = fmt(+$("pop").value));
  $("kcount").oninput = () => ($("kLabel").textContent = $("kcount").value);
  $("year").oninput = () => ($("yearLabel").textContent = yr(+$("year").value));
  $("found").onclick = found;
  try { await API("state"); $("continue").classList.remove("hidden"); } catch (e) { /* no saved world */ }
  $("continue").onclick = () => startGame(false);
  const demo = new URLSearchParams(location.search).get("demo"); // /game?demo=indus founds a world and starts
  if (demo) {
    const p = presets.find(x => x.id === demo) || presets[0];
    await API("new", {preset: p.id, year: p.default_year, population: 2400, kingdoms: 5, seed: 7});
    await API("player", {id: 0});
    await startGame(false);
  }
}
function yr(y) { return y < 0 ? `${-y} BCE` : `${y} CE`; }
function pick(p) {
  chosenPreset = p;
  const r = $("year"); r.min = p.years[0]; r.max = p.years[1]; r.step = 10; r.value = p.default_year;
  $("yearLabel").textContent = yr(p.default_year);
}
async function found() {
  $("found").disabled = true; $("found").textContent = "Shaping the land…";
  await API("new", {preset: chosenPreset.id, year: +$("year").value, population: +$("pop").value,
                    kingdoms: +$("kcount").value, seed: +$("seed").value});
  $("found").disabled = false; $("found").textContent = "Found the world";
  await startGame(true);
}
async function startGame(choose) {
  $("menu").classList.add("hidden");
  G.terrain = await API("terrain");
  G.state = await API("state");
  if (!G.scene) new Phaser.Game(config); else G.scene.scene.restart();
  if (choose) showChooser(); else enterPlay();
}
function showChooser() {
  const box = $("dynasties"); box.innerHTML = "";
  G.state.kingdoms.forEach(k => {
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<h4 style="color:${k.color};-webkit-text-stroke:1px #2a1a07">House of ${k.name}</h4>
      <p>${k.population} people · ${k.laws} laws · walls ${k.walls}</p>
      <div class="meta">Aggression ${pct(k.traits.aggression)} · Trade ${pct(k.traits.trade)} ·
      Learning ${pct(k.traits.learning)}</div>`;
    card.onclick = async () => { await API("player", {id: k.id}); G.state.player = k.id; $("chooser").classList.add("hidden"); enterPlay(); };
    box.appendChild(card);
  });
  $("chooser").classList.remove("hidden");
}
const pct = v => Math.round(v * 100) + "%";
function enterPlay() {
  $("hud").classList.remove("hidden");
  updateHud();
  if (G.scene) G.scene.focusPlayer();
}

// ---------------------------------------------------------------- HUD and controls
function me() { return G.state.kingdoms[G.state.player]; }
function updateHud() {
  const k = me(); if (!k) return;
  $("crestDot").style.background = k.color; $("myName").textContent = "House of " + k.name;
  $("myLaws").textContent = k.laws + (k.vassal_of !== null ? " · vassal" : ""); $("myKarma").textContent = k.karma;
  $("gold").textContent = fmt(k.gold); $("food").textContent = fmt(k.food); $("armour").textContent = fmt(k.armour);
  $("energy").textContent = k.energy; $("energyBar").style.width = k.energy + "%";
  $("troops").textContent = fmt(k.troops); $("people").textContent = fmt(k.population);
  $("happy").textContent = pct(k.happiness); $("yearNow").textContent = G.state.label;
  $("wallCost").textContent = k.walls >= 5 ? "max level" : `${250 * (k.walls + 1)} gold`;
  $("chronicle").innerHTML = G.state.chronicle.slice(-14).reverse()
    .map(e => `<div class="${e.kind}"><b>${e.label}</b> ${e.text}</div>`).join("");
}
async function act(action, extra = {}) {
  const res = await API("action", {action, ...extra});
  G.state = res.state; updateHud(); G.scene.refresh();
  return res.result;
}
document.querySelectorAll("#actions [data-act]").forEach(b => (b.onclick = async () => {
  const a = b.dataset.act;
  const n = a === "train" ? Math.max(10, Math.round(me().population * 0.04)) : 30;
  const r = await act(a, {n}); toast(r.message);
}));
async function step(years = 1) {
  const res = await API("step", {years});
  G.state = res.state; updateHud(); G.scene.refresh(); G.scene.playEvents(res.events);
}
function setSpeed(mode) {
  clearInterval(G.timer); G.playing = mode;
  ["pause", "play", "fast"].forEach(id => $(id).classList.remove("on"));
  $(mode === 0 ? "pause" : mode === 1 ? "play" : "fast").classList.add("on");
  if (mode) G.timer = setInterval(() => step(1).catch(() => {}), mode === 1 ? 2600 : 1100);
}
$("pause").onclick = () => setSpeed(0); $("play").onclick = () => setSpeed(1); $("fast").onclick = () => setSpeed(2);
$("stepBtn").onclick = () => step(1);
$("attackBtn").onclick = () => {
  G.attackMode = !G.attackMode; G.scene.showTargets(G.attackMode);
  toast(G.attackMode ? "Choose a kingdom within reach to attack" : "Attack cancelled");
};
$("closeInspector").onclick = () => $("inspector").classList.add("hidden");
$("cancelAttack").onclick = () => $("attackModal").classList.add("hidden");

async function openAttack(target) {
  const k = G.state.kingdoms[target];
  const res = await act("check_attack", {target});
  const r = res; const row = (label, key, unit = "") => {
    const ok = r.have[key] >= r.needs[key];
    return `<span>${label}</span><span class="${ok ? "ok" : "no"}">${fmt(r.have[key])}${unit}</span><span>need ${fmt(r.needs[key])}${unit}</span>`;
  };
  $("attackTitle").textContent = `Attack the House of ${k.name}`;
  $("attackBody").innerHTML = `<p>${r.in_reach ? "Within marching range." : "<b class='no'>Too far to march.</b>"}
    Defenders: about ${fmt(k.troops)} troops behind walls level ${k.walls}.</p>
    <div class="req">${row("⚔️ Troops sent", "troops")}${row("🌾 Food", "food")}${row("⚡ Energy", "energy")}${row("🛡️ Armour", "armour")}</div>`;
  $("launch").disabled = !r.ok;
  $("launch").onclick = async () => {
    $("attackModal").classList.add("hidden"); G.attackMode = false; G.scene.showTargets(false);
    const result = await act("attack", {target});
    if (!result.ok) return toast(result.reason);
    G.scene.march(G.state.player, target, result.won);
  };
  $("attackModal").classList.remove("hidden");
}

function face(c, color) { // procedural portrait
  const r = rng([...c.name].reduce((a, ch) => a + ch.charCodeAt(0), c.age));
  const skins = ["#f1c27d", "#e0ac69", "#c68642", "#8d5524", "#ffdbac"];
  const hairs = ["#2b1b0e", "#4a3020", "#8a5a2b", "#c9a15a", "#9a9a9a"];
  const skin = skins[Math.floor(r() * skins.length)], hair = hairs[Math.floor(r() * hairs.length)];
  const hat = {ruler: `<path d="M12 12 l4 -7 l4 5 l4 -6 l4 6 l4 -5 l4 7z" fill="#ffd84a" stroke="#2a1a07" stroke-width="1.5"/>`,
    general: `<path d="M10 20 q14 -18 28 0z" fill="#9aa5b1" stroke="#2a1a07" stroke-width="1.5"/>`,
    sage: `<path d="M9 24 q15 -24 30 0 l0 6 q-15 -8 -30 0z" fill="#3b4a8a" stroke="#2a1a07" stroke-width="1.5"/>`,
    high_priest: `<rect x="15" y="4" width="18" height="12" rx="3" fill="#f0e6d0" stroke="#2a1a07" stroke-width="1.5"/>`,
    merchant: `<ellipse cx="24" cy="14" rx="13" ry="6" fill="#7a3fd0" stroke="#2a1a07" stroke-width="1.5"/>`,
    builder: `<path d="M11 18 h26 v-4 q-13 -8 -26 0z" fill="#d9822b" stroke="#2a1a07" stroke-width="1.5"/>`}[c.role] || "";
  return `<svg class="face" viewBox="0 0 48 48"><circle cx="24" cy="24" r="23" fill="${color}" opacity=".35"/>
    <path d="M8 46 q16 -16 32 0z" fill="${color}" stroke="#2a1a07" stroke-width="1.5"/>
    <circle cx="24" cy="24" r="11" fill="${skin}" stroke="#2a1a07" stroke-width="1.5"/>
    <path d="M13 22 q11 -14 22 0 q-11 -5 -22 0z" fill="${hair}"/>
    <circle cx="20" cy="25" r="1.6"/><circle cx="28" cy="25" r="1.6"/>
    <path d="M20 30 q4 3 8 0" stroke="#2a1a07" fill="none" stroke-width="1.5"/>${hat}</svg>`;
}
const statBar = (label, v) => `<div class="stat">${label}<span><i style="width:${v * 10}%"></i></span>${v}</div>`;
async function openInspector(id) {
  const k = await API("kingdom/" + id);
  const mine = id === G.state.player;
  $("inspectorBody").innerHTML = `
    <h2 style="color:${k.color};-webkit-text-stroke:1px #2a1a07">House of ${k.name}</h2>
    <div class="chips"><span class="chip">${k.laws} laws</span><span class="chip">${k.free_speech ? "free speech" : "speech censored"}</span>
      <span class="chip">👥 ${fmt(k.population)}</span><span class="chip">⚔️ ${k.troops}</span><span class="chip">🏰 walls ${k.walls}</span>
      <span class="chip">☯ karma ${k.karma}</span>${k.vassal_of !== null ? `<span class="chip">vassal of ${G.state.kingdoms[k.vassal_of].name}</span>` : ""}
      ${mine ? '<span class="chip" style="background:#ffd84a">your dynasty</span>' : ""}</div>
    <h3>Court</h3><div class="chars">${k.characters.map(c => `<div class="char">${face(c, k.color)}
      <b>${ROLE_ICON[c.role] || ""} ${c.name}</b><br>${c.role.replace("_", " ")}, ${c.age}<br>
      <span class="chip">${c.ideology}</span> <span class="chip">☯ ${c.karma}</span>
      <div style="clear:both"></div>${statBar("Might", c.might)}${statBar("Wisdom", c.wisdom)}${statBar("Charisma", c.charisma)}${statBar("Craft", c.craft)}
      <div class="chips">${c.knowledge.map(x => `<span class="chip">${x}</span>`).join("")}</div></div>`).join("")}</div>
    <h3>Most respected citizens (karma)</h3>
    <table class="mini"><tr><th>Name</th><th>Work</th><th>Karma</th><th>Wealth</th></tr>
      ${k.top_citizens.map(c => `<tr><td>${c.name}</td><td>${c.profession.replace("_", " ")}</td><td>${c.standing}</td><td>${c.wealth}</td></tr>`).join("")}</table>
    <h3>r/${k.name.toLowerCase()}: town square</h3>
    ${k.feed.slice().reverse().map(p => `<div class="post"><div class="votes"><span>▲</span>${p.score}<span class="down">▼</span></div>
      <div><div class="who">u/${p.author.replace(/ /g, "_").toLowerCase()} · ${p.profession.replace("_", " ")} · ${p.label}</div>${p.text}</div></div>`).join("") || "<p>Quiet so far.</p>"}`;
  $("inspector").classList.remove("hidden");
}

// ---------------------------------------------------------------- the world scene
class WorldScene extends Phaser.Scene {
  constructor() { super("world"); }

  create() {
    G.scene = this;
    const t = G.terrain; this.W = t.width; this.H = t.height;
    this.buildTextures();
    this.add.image(0, 0, "terrain").setOrigin(0);
    this.territory = this.add.graphics();
    this.settlements = this.add.layer();
    this.walkers = this.add.layer();
    this.fx = this.add.layer();
    this.clouds = this.add.layer();
    this.labels = this.add.layer();
    this.makeRiverFlow();
    this.makeClouds();
    this.cameras.main.setBounds(0, 0, this.W * T, this.H * T).setBackgroundColor("#1f4f80");
    this.input.on("pointermove", p => {
      if (!p.isDown) return;
      const cam = this.cameras.main;
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom; cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    this.input.on("wheel", (p, objs, dx, dy) => {
      const cam = this.cameras.main; cam.setZoom(Phaser.Math.Clamp(cam.zoom * (dy > 0 ? 0.9 : 1.1), 0.45, 2.6));
    });
    this.refresh();
    this.focusPlayer();
  }

  px(x) { return x * T + T / 2; }

  // ---------- textures
  buildTextures() {
    const t = G.terrain, W = t.width, H = t.height;
    const e = (x, y) => t.elevation[Math.min(H - 1, Math.max(0, y)) * W + Math.min(W - 1, Math.max(0, x))];
    const biome = (x, y) => t.biomes[t.biome[y * W + x]];
    const base = document.createElement("canvas"); base.width = W * T; base.height = H * T;
    const c = base.getContext("2d"); const r = rng(42);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const b = biome(x, y);
      const light = 1 + (e(x - 1, y - 1) - e(x + 1, y + 1)) * 1.8 + (b === "sea" ? (e(x, y) - 0.1) * 1.2 : 0);
      c.fillStyle = shade(PALETTE[b], light); c.fillRect(x * T, y * T, T, T);
      for (let i = 0; i < 4; i++) { // texture speckles
        c.fillStyle = shade(PALETTE[b], light * (0.9 + r() * 0.2));
        c.fillRect(x * T + r() * T, y * T + r() * T, 3 + r() * 4, 3 + r() * 4);
      }
    }
    const soft = document.createElement("canvas"); soft.width = base.width; soft.height = base.height;
    const s = soft.getContext("2d"); s.filter = "blur(6px)"; s.drawImage(base, 0, 0); s.filter = "none";
    s.globalAlpha = 0.45; s.drawImage(base, 0, 0); s.globalAlpha = 1;
    // coast foam
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      if (biome(x, y) !== "sea") continue;
      const near = [[1, 0], [-1, 0], [0, 1], [0, -1]].some(([dx, dy]) => {
        const nx = x + dx, ny = y + dy; return nx >= 0 && ny >= 0 && nx < W && ny < H && biome(nx, ny) !== "sea";
      });
      if (near) { s.fillStyle = "rgba(255,255,255,0.18)"; s.beginPath(); s.arc(x * T + T / 2, y * T + T / 2, T * 0.6, 0, 7); s.fill(); }
    }
    // rivers: banks, water, highlight
    for (const path of t.rivers) {
      const pts = path.map(([x, y]) => [x * T + T / 2, y * T + T / 2]);
      for (const [w0, w1, col] of [[7, 18, "#2a5f8f"], [5, 14, "#49a2e6"], [1.5, 4, "rgba(200,235,255,0.7)"]]) {
        s.strokeStyle = col; s.lineCap = "round"; s.lineJoin = "round";
        for (let i = 1; i < pts.length; i++) {
          s.lineWidth = w0 + (w1 - w0) * i / pts.length; s.beginPath(); s.moveTo(...pts[i - 1]); s.lineTo(...pts[i]); s.stroke();
        }
      }
    }
    // decorations
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const b = biome(x, y), cx = x * T + T / 2, cy = y * T + T / 2;
      if (b === "forest" || (b === "marsh" && r() < 0.3)) {
        for (let i = 0; i < 2 + (r() < 0.5); i++) this.tree(s, cx + (r() - 0.5) * T, cy + (r() - 0.5) * T, 6 + r() * 4, r);
      } else if (b === "mountain" || b === "snow") {
        if (r() < 0.75) this.peak(s, cx + (r() - 0.5) * 8, cy + 6, T * (1.1 + r() * 0.7), b === "snow" || e(x, y) > 0.78);
      } else if (b === "hills" && r() < 0.6) {
        s.fillStyle = "rgba(60,80,30,0.35)"; s.beginPath(); s.ellipse(cx, cy + 4, 11, 6, 0, Math.PI, 0); s.fill();
        s.fillStyle = "rgba(255,255,255,0.15)"; s.beginPath(); s.ellipse(cx - 3, cy + 2, 6, 3, 0, Math.PI, 0); s.fill();
      } else if (b === "desert" && r() < 0.5) {
        s.strokeStyle = "rgba(150,100,40,0.45)"; s.lineWidth = 1.5; s.beginPath();
        s.arc(cx, cy + 8, 9, Math.PI * 1.15, Math.PI * 1.85); s.stroke();
      } else if (b === "marsh") {
        s.strokeStyle = "rgba(40,70,30,0.8)"; s.lineWidth = 1;
        for (let i = 0; i < 4; i++) { const rx = cx + (r() - 0.5) * T; s.beginPath(); s.moveTo(rx, cy + 6); s.lineTo(rx + 1, cy - 2); s.stroke(); }
      } else if (b === "plains" && r() < 0.18) {
        const fl = ["#f7e36b", "#f5f0e6", "#e98ab5", "#b7a6ff"][Math.floor(r() * 4)];
        for (let i = 0; i < 3; i++) { s.fillStyle = fl; s.beginPath(); s.arc(cx + (r() - 0.5) * T, cy + (r() - 0.5) * T, 1.3, 0, 7); s.fill(); }
      }
      if (b === "plains" && r() < 0.12) {
        s.strokeStyle = "rgba(60,110,30,0.6)"; s.lineWidth = 1.2;
        for (let i = 0; i < 3; i++) { const gx = cx + (r() - 0.5) * T; s.beginPath(); s.moveTo(gx, cy + 4); s.lineTo(gx - 2, cy - 2); s.moveTo(gx, cy + 4); s.lineTo(gx + 2, cy - 1); s.stroke(); }
      }
    }
    this.textures.addCanvas("terrain", soft);
    this.makeSpriteTextures();
  }

  tree(c, x, y, size, r) {
    c.fillStyle = "rgba(0,0,0,0.25)"; c.beginPath(); c.ellipse(x + 2, y + size * 0.9, size * 0.9, size * 0.35, 0, 0, 7); c.fill();
    c.fillStyle = "#5a3a1c"; c.fillRect(x - 1.5, y, 3, size * 0.8);
    const g = c.createRadialGradient(x - size * 0.3, y - size * 0.6, 1, x, y - size * 0.3, size);
    const green = ["#3f8f3a", "#2f7a32", "#4fa046"][Math.floor(r() * 3)];
    g.addColorStop(0, "#8fd16a"); g.addColorStop(1, green);
    c.fillStyle = g; c.beginPath(); c.arc(x, y - size * 0.3, size, 0, 7); c.fill();
    c.strokeStyle = "rgba(20,50,20,0.6)"; c.lineWidth = 1; c.stroke();
  }

  peak(c, x, y, size, snow) {
    c.fillStyle = "rgba(0,0,0,0.25)"; c.beginPath(); c.ellipse(x + 4, y, size * 0.6, size * 0.18, 0, 0, 7); c.fill();
    c.fillStyle = "#a59b8e"; c.beginPath(); c.moveTo(x - size * 0.55, y); c.lineTo(x, y - size); c.lineTo(x, y); c.fill();
    c.fillStyle = "#6f675d"; c.beginPath(); c.moveTo(x, y - size); c.lineTo(x + size * 0.55, y); c.lineTo(x, y); c.fill();
    if (snow) {
      c.fillStyle = "#fbfdff"; c.beginPath(); c.moveTo(x - size * 0.2, y - size * 0.62); c.lineTo(x, y - size);
      c.lineTo(x + size * 0.2, y - size * 0.62); c.lineTo(x + size * 0.07, y - size * 0.68); c.lineTo(x - size * 0.05, y - size * 0.58); c.fill();
    }
    c.strokeStyle = "rgba(40,30,20,0.6)"; c.lineWidth = 1; c.beginPath(); c.moveTo(x - size * 0.55, y); c.lineTo(x, y - size); c.lineTo(x + size * 0.55, y); c.stroke();
  }

  canvasTexture(key, w, h, draw) {
    if (this.textures.exists(key)) return;
    const cv = document.createElement("canvas"); cv.width = w; cv.height = h; draw(cv.getContext("2d")); this.textures.addCanvas(key, cv);
  }

  makeSpriteTextures() {
    this.canvasTexture("house", 22, 22, c => {
      c.fillStyle = "rgba(0,0,0,.25)"; c.beginPath(); c.ellipse(12, 19, 9, 3, 0, 0, 7); c.fill();
      c.fillStyle = "#e8d3a8"; c.fillRect(4, 10, 14, 9); c.strokeStyle = "#5a3a1c"; c.lineWidth = 1.5; c.strokeRect(4, 10, 14, 9);
      c.fillStyle = "#b5532a"; c.beginPath(); c.moveTo(2, 11); c.lineTo(11, 2); c.lineTo(20, 11); c.closePath(); c.fill(); c.stroke();
      c.fillStyle = "#5a3a1c"; c.fillRect(9, 13, 4, 6);
    });
    this.canvasTexture("hut", 20, 20, c => {
      c.fillStyle = "rgba(0,0,0,.25)"; c.beginPath(); c.ellipse(10, 17, 8, 3, 0, 0, 7); c.fill();
      c.fillStyle = "#d9b98a"; c.beginPath(); c.arc(10, 13, 6, Math.PI, 0); c.fill();
      c.fillStyle = "#c9a14a"; c.beginPath(); c.moveTo(2, 13); c.lineTo(10, 3); c.lineTo(18, 13); c.closePath(); c.fill();
      c.strokeStyle = "#5a3a1c"; c.lineWidth = 1.2; c.stroke();
    });
    this.canvasTexture("farm", 26, 18, c => {
      for (let i = 0; i < 5; i++) { c.fillStyle = i % 2 ? "#d7b843" : "#9fc44a"; c.fillRect(1, 1 + i * 3.2, 24, 3.2); }
      c.strokeStyle = "#6b4a1c"; c.lineWidth = 1.5; c.strokeRect(1, 1, 24, 16);
    });
    this.canvasTexture("temple", 30, 26, c => {
      c.fillStyle = "rgba(0,0,0,.25)"; c.beginPath(); c.ellipse(15, 23, 13, 3, 0, 0, 7); c.fill();
      [[2, 16, 26, 7], [6, 10, 18, 6], [10, 5, 10, 5]].forEach(([x, y, w, h], i) => {
        c.fillStyle = ["#d8c08a", "#e6d2a0", "#f2e2b8"][i]; c.fillRect(x, y, w, h); c.strokeStyle = "#5a3a1c"; c.lineWidth = 1.2; c.strokeRect(x, y, w, h);
      });
    });
    this.canvasTexture("market", 26, 22, c => {
      c.fillStyle = "rgba(0,0,0,.25)"; c.beginPath(); c.ellipse(13, 19, 11, 3, 0, 0, 7); c.fill();
      for (let i = 0; i < 6; i++) { c.fillStyle = i % 2 ? "#fff" : "#d0402c"; c.beginPath(); c.moveTo(2 + i * 4, 9); c.lineTo(6 + i * 4, 9); c.lineTo(13, 2); c.fill(); }
      c.fillStyle = "#8a5a2b"; c.fillRect(4, 9, 18, 8); c.strokeStyle = "#3a2410"; c.lineWidth = 1.2; c.strokeRect(4, 9, 18, 8);
    });
    this.canvasTexture("cloud", 120, 60, c => {
      c.fillStyle = "rgba(255,255,255,0.85)";
      [[30, 35, 20], [55, 25, 26], [82, 34, 20], [60, 40, 22]].forEach(([x, y, r]) => { c.beginPath(); c.arc(x, y, r, 0, 7); c.fill(); });
    });
    this.canvasTexture("dot", 4, 4, c => { c.fillStyle = "rgba(255,255,255,.85)"; c.beginPath(); c.arc(2, 2, 1.6, 0, 7); c.fill(); });
    this.canvasTexture("rain", 2, 10, c => { c.fillStyle = "rgba(190,220,255,.8)"; c.fillRect(0, 0, 1.5, 10); });
    this.canvasTexture("dust", 8, 8, c => { c.fillStyle = "rgba(210,160,90,.6)"; c.beginPath(); c.arc(4, 4, 3.5, 0, 7); c.fill(); });
    this.canvasTexture("spark", 6, 6, c => { c.fillStyle = "#ffd84a"; c.beginPath(); c.arc(3, 3, 2.6, 0, 7); c.fill(); });
    this.canvasTexture("smoke", 16, 16, c => { c.fillStyle = "rgba(90,90,90,.55)"; c.beginPath(); c.arc(8, 8, 7, 0, 7); c.fill(); });
  }

  kingdomTextures(k) {
    const col = k.color, dark = shade(col, 0.6);
    this.canvasTexture("castle" + k.id, 80, 80, c => {
      c.fillStyle = "rgba(0,0,0,.3)"; c.beginPath(); c.ellipse(40, 72, 34, 8, 0, 0, 7); c.fill();
      const stone = c.createLinearGradient(0, 30, 0, 72); stone.addColorStop(0, "#d9d2c5"); stone.addColorStop(1, "#9b9284");
      c.fillStyle = stone; c.fillRect(14, 38, 52, 32); c.strokeStyle = "#3a2e22"; c.lineWidth = 2; c.strokeRect(14, 38, 52, 32);
      for (let i = 0; i < 6; i++) { c.fillStyle = "#bdb4a5"; c.fillRect(15 + i * 9, 32, 5, 7); c.strokeRect(15 + i * 9, 32, 5, 7); }
      c.strokeStyle = "rgba(60,50,40,.35)"; c.lineWidth = 1;
      for (let yy = 44; yy < 70; yy += 6) { c.beginPath(); c.moveTo(14, yy); c.lineTo(66, yy); c.stroke(); }
      [[8, 30], [60, 30]].forEach(([x, y]) => { // side towers
        c.fillStyle = stone; c.fillRect(x, y, 12, 40); c.strokeStyle = "#3a2e22"; c.lineWidth = 2; c.strokeRect(x, y, 12, 40);
        c.fillStyle = col; c.beginPath(); c.moveTo(x - 3, y); c.lineTo(x + 6, y - 14); c.lineTo(x + 15, y); c.closePath(); c.fill(); c.stroke();
      });
      c.fillStyle = stone; c.fillRect(30, 18, 20, 26); c.strokeRect(30, 18, 20, 26); // keep
      c.fillStyle = col; c.beginPath(); c.moveTo(26, 18); c.lineTo(40, -2 + 6); c.lineTo(54, 18); c.closePath(); c.fill(); c.stroke();
      c.fillStyle = dark; c.beginPath(); c.moveTo(34, 70); c.lineTo(34, 58); c.arc(40, 58, 6, Math.PI, 0); c.lineTo(46, 70); c.fill();
      c.fillStyle = "#2a2018"; c.fillRect(38, 26, 4, 7);
      c.strokeStyle = "#3a2e22"; c.lineWidth = 1.5; c.beginPath(); c.moveTo(40, 4); c.lineTo(40, -4 + 6); c.stroke();
    });
    this.canvasTexture("flag" + k.id, 18, 12, c => {
      c.fillStyle = col; c.beginPath(); c.moveTo(0, 0); c.lineTo(18, 3); c.lineTo(0, 11); c.fill();
      c.strokeStyle = "#2a1a07"; c.lineWidth = 1; c.stroke();
    });
    this.canvasTexture("person" + k.id, 10, 16, c => {
      c.fillStyle = "rgba(0,0,0,.3)"; c.beginPath(); c.ellipse(5, 15, 4, 1.5, 0, 0, 7); c.fill();
      c.fillStyle = col; c.fillRect(2, 6, 6, 7); c.strokeStyle = "#2a1a07"; c.lineWidth = 1; c.strokeRect(2, 6, 6, 7);
      c.fillStyle = "#e0ac69"; c.beginPath(); c.arc(5, 4, 2.8, 0, 7); c.fill(); c.stroke();
      c.fillStyle = "#3a2a1a"; c.fillRect(3, 13, 1.5, 2); c.fillRect(5.5, 13, 1.5, 2);
    });
    this.canvasTexture("soldier" + k.id, 14, 18, c => {
      c.fillStyle = "rgba(0,0,0,.3)"; c.beginPath(); c.ellipse(7, 17, 5, 1.6, 0, 0, 7); c.fill();
      c.strokeStyle = "#6b4a1c"; c.lineWidth = 1.5; c.beginPath(); c.moveTo(11, 0); c.lineTo(11, 16); c.stroke();
      c.fillStyle = "#c0c6cc"; c.beginPath(); c.moveTo(11, 0); c.lineTo(9.5, 3); c.lineTo(12.5, 3); c.fill();
      c.fillStyle = "#8a8f96"; c.fillRect(4, 6, 6, 8); c.fillStyle = "#e0ac69"; c.beginPath(); c.arc(7, 4, 2.8, 0, 7); c.fill();
      c.fillStyle = "#9aa5b1"; c.beginPath(); c.arc(7, 3.2, 3, Math.PI, 0); c.fill();
      c.fillStyle = col; c.beginPath(); c.ellipse(4, 10, 3.2, 4.2, 0, 0, 7); c.fill(); c.strokeStyle = "#2a1a07"; c.lineWidth = 1; c.stroke();
    });
  }

  // ---------- living layers
  makeRiverFlow() {
    this.flow = [];
    for (const path of G.terrain.rivers) {
      const pts = path.map(([x, y]) => [x * T + T / 2, y * T + T / 2]);
      for (let i = 0; i < Math.max(12, pts.length / 3); i++) {
        const dot = this.add.image(0, 0, "dot").setAlpha(0.7);
        this.flow.push({dot, pts, t: Math.random() * (pts.length - 1), speed: 0.025 + Math.random() * 0.03});
      }
    }
  }
  makeClouds() {
    this.cloudList = [];
    for (let i = 0; i < 9; i++) {
      const x = Math.random() * this.W * T, y = Math.random() * this.H * T, s = 0.8 + Math.random() * 1.2;
      const shadow = this.add.image(x + 40, y + 60, "cloud").setScale(s).setTint(0x000000).setAlpha(0.12);
      const cloud = this.add.image(x, y, "cloud").setScale(s).setAlpha(0.75);
      this.clouds.add([shadow, cloud]);
      this.cloudList.push({cloud, shadow, v: 6 + Math.random() * 10});
    }
  }
  update(time, delta) {
    for (const f of this.flow) {
      f.t += f.speed * delta / 16; if (f.t >= f.pts.length - 1) f.t = 0;
      const i = Math.floor(f.t), a = f.pts[i], b = f.pts[i + 1], u = f.t - i;
      f.dot.setPosition(a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u);
    }
    for (const c of this.cloudList) {
      c.cloud.x += c.v * delta / 1000; c.shadow.x = c.cloud.x + 40; c.shadow.y = c.cloud.y + 60;
      if (c.cloud.x > this.W * T + 150) c.cloud.x = -150;
    }
  }

  // ---------- kingdoms
  refresh() {
    const st = G.state, W = this.W, H = this.H; if (!st) return;
    const g = this.territory; g.clear();
    const own = st.owner;
    st.kingdoms.forEach(k => this.kingdomTextures(k));
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const o = own[y * W + x]; if (o < 0) continue;
      const k = st.kingdoms[o]; const col = Phaser.Display.Color.HexStringToColor(k.color).color;
      g.fillStyle(col, k.alive ? 0.12 : 0.04).fillRect(x * T, y * T, T, T);
      if (x + 1 < W && own[y * W + x + 1] !== o) g.lineStyle(2, col, 0.75).lineBetween((x + 1) * T, y * T, (x + 1) * T, (y + 1) * T);
      if (x > 0 && own[y * W + x - 1] !== o) g.lineStyle(2, col, 0.75).lineBetween(x * T, y * T, x * T, (y + 1) * T);
      if (y + 1 < H && own[(y + 1) * W + x] !== o) g.lineStyle(2, col, 0.75).lineBetween(x * T, (y + 1) * T, (x + 1) * T, (y + 1) * T);
      if (y > 0 && own[(y - 1) * W + x] !== o) g.lineStyle(2, col, 0.75).lineBetween(x * T, y * T, (x + 1) * T, y * T);
    }
    this.drawRoads(g);
    this.settlements.removeAll(true); this.walkers.removeAll(true); this.labels.removeAll(true);
    this.castles = {};
    st.kingdoms.forEach(k => this.drawKingdom(k));
    this.applyWeather();
  }

  drawRoads(g) {
    const ks = G.state.kingdoms.filter(k => k.alive), done = new Set();
    for (const a of ks) for (const b of ks) {
      if (a.id >= b.id || Math.hypot(a.capital[0] - b.capital[0], a.capital[1] - b.capital[1]) > 46) continue;
      const ax = this.px(a.capital[0]), ay = this.px(a.capital[1]), bx = this.px(b.capital[0]), by = this.px(b.capital[1]);
      const mx = (ax + bx) / 2 + (by - ay) * 0.12, my = (ay + by) / 2 - (bx - ax) * 0.12;
      const curve = new Phaser.Curves.QuadraticBezier(new Phaser.Math.Vector2(ax, ay), new Phaser.Math.Vector2(mx, my), new Phaser.Math.Vector2(bx, by));
      g.lineStyle(7, 0x6b4a1c, 0.35); curve.draw(g, 40);
      g.lineStyle(4, 0xc9a46a, 0.75); curve.draw(g, 40);
      done.add(a.id + "-" + b.id);
    }
  }

  homeTiles(k) {
    const t = G.terrain, own = G.state.owner, W = this.W, [cx, cy] = k.capital, tiles = [];
    for (let y = Math.max(0, cy - 15); y < Math.min(this.H, cy + 16); y++)
      for (let x = Math.max(0, cx - 15); x < Math.min(W, cx + 16); x++) {
        const b = t.biomes[t.biome[y * W + x]];
        if (own[y * W + x] === k.id && !["sea", "river", "mountain", "snow"].includes(b))
          tiles.push({x, y, d: Math.hypot(x - cx, y - cy), wet: t.moisture[y * W + x]});
      }
    return tiles.sort((a, b) => a.d - b.d);
  }

  drawKingdom(k) {
    const r = rng(k.id * 977 + 13), [cx, cy] = k.capital, tiles = this.homeTiles(k).filter(t => t.d >= 2);
    const b = k.buildings, place = (key, tile, s = 1) => {
      const img = this.add.image(this.px(tile.x) + (r() - 0.5) * 10, this.px(tile.y) + (r() - 0.5) * 10, key).setScale(s);
      img.setDepth(img.y); this.settlements.add(img); return img;
    };
    if (k.alive) {
      tiles.filter(t => t.d >= 4 && t.wet > 0.3).slice(0, Math.min(48, b.farms + 6)).forEach(t => place("farm", t, 1.1 + r() * 0.4));
      const homes = tiles.slice(0, Math.min(70, b.houses));
      homes.forEach((t, i) => place(i % 3 ? "house" : "hut", t, 0.8 + r() * 0.35));
      if (homes[1]) place("temple", homes[1], 1);
      for (let i = 0; i < Math.min(3, b.markets); i++) if (homes[2 + i * 2]) place("market", homes[2 + i * 2], 1);
    }
    // walls ring
    const ring = this.add.graphics(); this.settlements.add(ring);
    const radius = 34 + k.walls * 7;
    if (k.alive && k.walls > 0) {
      ring.lineStyle(4 + k.walls, 0x8a7f6e, 1).strokeCircle(this.px(cx), this.px(cy) + 8, radius);
      ring.lineStyle(2, 0x3a2e22, 1).strokeCircle(this.px(cx), this.px(cy) + 8, radius + 2 + k.walls / 2);
      for (let a = 0; a < Math.PI * 2; a += Math.PI * 2 / (4 + k.walls * 2))
        ring.fillStyle(0xbdb4a5, 1).fillCircle(this.px(cx) + Math.cos(a) * radius, this.px(cy) + 8 + Math.sin(a) * radius, 4 + k.walls * 0.8);
    }
    const castle = this.add.image(this.px(cx), this.px(cy), "castle" + k.id).setScale(0.75 + k.walls * 0.08)
      .setInteractive({useHandCursor: true}).setDepth(this.px(cy) + 30);
    if (!k.alive) castle.setTint(0x555555).setAlpha(0.6);
    castle.on("pointerup", p => {
      if (p.getDistance() > 6) return; // was a drag
      if (G.attackMode && k.id !== G.state.player) openAttack(k.id); else openInspector(k.id);
    });
    this.settlements.add(castle); this.castles[k.id] = castle;
    const flag = this.add.image(this.px(cx) + 3, this.px(cy) - 34, "flag" + k.id).setOrigin(0, 0.5).setDepth(castle.depth + 1);
    this.tweens.add({targets: flag, scaleX: 0.75, duration: 500 + r() * 300, yoyo: true, repeat: -1, ease: "Sine.inOut"});
    this.settlements.add(flag);
    const label = this.add.text(this.px(cx), this.px(cy) + 44, `${k.name}${k.id === G.state.player ? " ★" : ""}`, {
      fontFamily: "Lilita One", fontSize: "20px", color: "#ffffff", stroke: "#2a1a07", strokeThickness: 5,
    }).setOrigin(0.5).setDepth(1e6);
    const sub = this.add.text(this.px(cx), this.px(cy) + 63, `👥 ${k.population}  ⚔️ ${k.troops}  ☯ ${k.karma}`, {
      fontFamily: "Nunito", fontStyle: "800", fontSize: "13px", color: "#fff", stroke: "#2a1a07", strokeThickness: 4,
    }).setOrigin(0.5).setDepth(1e6);
    this.labels.add([label, sub]);
    if (k.alive) this.spawnWalkers(k, tiles.slice(0, 50), r);
  }

  spawnWalkers(k, tiles, r) {
    if (!tiles.length) return;
    const n = Math.min(14, 4 + Math.floor(k.population / 60));
    for (let i = 0; i < n; i++) {
      const start = tiles[Math.floor(r() * tiles.length)];
      const p = this.add.image(this.px(start.x), this.px(start.y), "person" + k.id).setScale(1.2);
      this.walkers.add(p);
      const walk = () => {
        const to = tiles[Math.floor(Math.random() * tiles.length)];
        const tx = this.px(to.x) + (Math.random() - 0.5) * 10, ty = this.px(to.y) + (Math.random() - 0.5) * 10;
        const d = Math.hypot(tx - p.x, ty - p.y);
        p.setFlipX(tx < p.x);
        this.tweens.add({targets: p, x: tx, y: ty, duration: d * 45 + 400, onUpdate: () => p.setDepth(p.y),
          onComplete: () => this.time.delayedCall(400 + Math.random() * 2500, walk)});
      };
      this.tweens.add({targets: p, scaleY: 1.1, duration: 220, yoyo: true, repeat: -1});
      walk();
    }
  }

  applyWeather() {
    (this.weatherFx || []).forEach(o => o.destroy()); this.weatherFx = [];
    const st = G.state, now = st.chronicle.filter(e => e.year === st.year - 1 && e.weather);
    for (const e of now) {
      const k = st.kingdoms[e.kingdom]; if (!k) continue;
      const x = this.px(k.capital[0]), y = this.px(k.capital[1]), R = 11 * T;
      if (e.weather === "rain") {
        const em = this.add.particles(0, 0, "rain", {x: {min: x - R, max: x + R}, y: y - R, lifespan: 900,
          speedY: {min: 380, max: 520}, speedX: -60, quantity: 3, frequency: 25, alpha: {start: 0.8, end: 0.2}});
        this.fx.add(em); this.weatherFx.push(em);
      } else {
        const glow = this.add.circle(x, y, R, 0xff8a2a, 0.13); this.fx.add(glow); this.weatherFx.push(glow);
        this.tweens.add({targets: glow, alpha: 0.05, duration: 1200, yoyo: true, repeat: -1});
        const em = this.add.particles(0, 0, "dust", {x: {min: x - R, max: x + R}, y: {min: y - R, max: y + R},
          lifespan: 2500, speedX: {min: 10, max: 40}, alpha: {start: 0.6, end: 0}, scale: {start: 0.6, end: 1.6}, frequency: 120});
        this.fx.add(em); this.weatherFx.push(em);
      }
    }
  }

  // ---------- war and focus
  showTargets(on) {
    (this.targetRings || []).forEach(r => r.destroy()); this.targetRings = [];
    if (!on) return;
    API("kingdom/" + G.state.player).then(k => k.neighbours.forEach(id => {
      const c = this.castles[id]; if (!c) return;
      const ring = this.add.circle(c.x, c.y + 8, 46, 0xff3b2a, 0.15).setStrokeStyle(4, 0xff3b2a, 1).setDepth(1e6 - 1);
      this.tweens.add({targets: ring, scale: 1.15, alpha: 0.6, duration: 600, yoyo: true, repeat: -1});
      this.fx.add(ring); this.targetRings.push(ring);
    }));
  }

  march(fromId, toId, won) {
    const a = this.castles[fromId], b = this.castles[toId]; if (!a || !b) return;
    const army = [];
    for (let i = 0; i < 12; i++) {
      const s = this.add.image(a.x + (i % 4) * 9 - 14, a.y + 30 + Math.floor(i / 4) * 9, "soldier" + fromId).setScale(1.4).setDepth(1e6 - 2);
      s.setFlipX(b.x < a.x); this.fx.add(s); army.push(s);
      this.tweens.add({targets: s, y: s.y - 2, duration: 160, yoyo: true, repeat: -1});
      this.tweens.add({targets: s, x: b.x + (i % 4) * 9 - 14, y: b.y + 30 + Math.floor(i / 4) * 9, duration: 2200, ease: "Sine.inOut",
        onComplete: () => { if (i === 0) this.battle(b, won, fromId); this.tweens.add({targets: s, alpha: 0, delay: 900, duration: 500, onComplete: () => s.destroy()}); }});
    }
    if (fromId === G.state.player || toId === G.state.player) this.cameras.main.pan((a.x + b.x) / 2, (a.y + b.y) / 2, 1200, "Sine.inOut");
  }

  battle(target, won, fromId) {
    const x = target.x, y = target.y + 20;
    const sparks = this.add.particles(x, y, "spark", {speed: {min: 60, max: 200}, lifespan: 600, quantity: 30, emitting: false, scale: {start: 1.2, end: 0}});
    const smoke = this.add.particles(x, y, "smoke", {speed: {min: 10, max: 50}, lifespan: 1600, quantity: 16, emitting: false,
      scale: {start: 1, end: 3}, alpha: {start: 0.7, end: 0}});
    this.fx.add([sparks, smoke]); sparks.explode(40); smoke.explode(18);
    this.cameras.main.shake(300, 0.006);
    const mine = fromId === G.state.player;
    const text = this.add.text(x, y - 70, won ? (mine ? "VICTORY!" : "RAIDED!") : (mine ? "REPELLED!" : "DEFENDED!"), {
      fontFamily: "Lilita One", fontSize: "34px", color: won ? "#ffd84a" : "#ff7a59", stroke: "#2a1a07", strokeThickness: 7,
    }).setOrigin(0.5).setDepth(1e7);
    this.tweens.add({targets: text, y: y - 110, alpha: 0, delay: 900, duration: 1100, onComplete: () => text.destroy()});
    this.time.delayedCall(2500, () => { sparks.destroy(); smoke.destroy(); });
  }

  playEvents(events) {
    events.filter(e => e.kind === "war").forEach((e, i) => this.time.delayedCall(i * 700, () => this.march(e.attacker, e.defender, e.won)));
    const mine = events.filter(e => e.kingdom === G.state.player || e.defender === G.state.player);
    if (mine.length) toast(mine[mine.length - 1].text, 3500);
  }

  focusPlayer() {
    const k = G.state && G.state.kingdoms[G.state.player]; if (!k) return;
    this.cameras.main.centerOn(this.px(k.capital[0]), this.px(k.capital[1])).setZoom(1.1);
  }
}

const config = {
  type: Phaser.AUTO, parent: "game", backgroundColor: "#1f4f80",
  scale: {mode: Phaser.Scale.RESIZE, width: window.innerWidth, height: window.innerHeight},
  scene: [WorldScene], render: {antialias: true},
};

initMenu();
