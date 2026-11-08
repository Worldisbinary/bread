// Ages of Kingdoms: the app. Menus, your town (build, upgrade, collect, train), raids, news, the Navigator.
import * as THREE from "three";
import {Stage, Sound, $, api, toast, fmt, yr, pct, esc, clamp} from "./core.js";
import * as M from "./models.js";
import {TownView} from "./town.js";
import {Battle} from "./battle.js";
import {WorldMap} from "./map.js";

const AGE_WHERE = {founding: 0.15, expansion: 0.5, empire: 0.85};
const ICON = {palace: "🏛️", farm: "🌾", mine: "⛏️", granary: "🛖", treasury: "💰", barracks: "⚔️", camp: "⛺", archer_tower: "🗼",
  bolt_thrower: "🎯", catapult: "🪨", wall: "🧱", house: "🏠", temple: "🛕", spearman: "🛡️", archer: "🏹", raider: "🐎", ram: "🪵", elephant: "🐘"};
const SHOP = {Resources: ["farm", "mine", "granary", "treasury"], Army: ["barracks", "camp"], Defense: ["archer_tower", "bolt_thrower", "catapult", "wall"], Town: ["house", "temple"]};
const RES = {gold: "🪙", food: "🌾"};
const LAWS = {liberal: "Liberal laws", authoritarian: "Autocracy", socialist: "Common-wealth laws"};
const G = {catalog: null, presets: [], pick: {preset: null, age: "expansion", rivals: 6, difficulty: "balanced"}, town: null, state: null,
  mode: "menu", news: [], unread: 0, placing: null, selected: null, battle: null, yearSeconds: 40};

Stage.init();
const home = new TownView({name: "home"}), raid = new TownView({name: "raid"}), world = new WorldMap();
[home, raid, world].forEach(v => v.hide());

// ------------------------------------------------------------------ thumbnails of real models for the shop
const thumbs = {};
let thumbRenderer = null;
function thumb(kind, type, level = 1) {
  const key = `${kind}:${type}:${level}:${G.state?.preset}`; if (thumbs[key]) return thumbs[key];
  try {
    if (!thumbRenderer) {
      thumbRenderer = new THREE.WebGLRenderer({antialias: true, alpha: true, preserveDrawingBuffer: true});
      thumbRenderer.setSize(200, 150); thumbRenderer.outputColorSpace = THREE.SRGBColorSpace; thumbRenderer.toneMapping = THREE.ACESFilmicToneMapping;
    }
    const scene = new THREE.Scene(); scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7050, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2); sun.position.set(-3, 6, 4); scene.add(sun);
    const theme = M.THEMES[G.state?.preset] || M.THEMES.ganges, color = myColor();
    const obj = kind === "unit" ? M.unit(type, color, {scale: type === "elephant" ? 1 : 2.2}) :
      type === "wall" ? new THREE.Mesh(M.box(0.7, 0.9, 0.7, 0.05), M.mat(theme.stone)) : M.building(type, level, theme, color);
    scene.add(obj);
    const bounds = new THREE.Box3().setFromObject(obj), size = bounds.getSize(new THREE.Vector3()), mid = bounds.getCenter(new THREE.Vector3());
    const cam = new THREE.PerspectiveCamera(30, 4 / 3, 0.1, 100), d = Math.max(size.x, size.y, size.z) * 2.3;
    cam.position.set(mid.x + d * 0.6, mid.y + d * 0.55, mid.z + d * 0.6); cam.lookAt(mid);
    thumbRenderer.render(scene, cam);
    return (thumbs[key] = thumbRenderer.domElement.toDataURL());
  } catch (e) { return null; }
}
const art = (kind, type, level) => { const src = thumb(kind, type, level); return src ? `<img src="${src}" alt="">` : ICON[type]; };
const myColor = () => G.town?.kingdom?.color || "#d9472c";

// ------------------------------------------------------------------ menu
async function boot() {
  [G.presets, G.catalog] = await Promise.all([api("presets"), api("catalog")]);
  G.pick.preset = G.presets[0].id;
  renderMenu();
  try { await api("town"); $("continue").classList.remove("hidden"); } catch (e) { /* no saved kingdom */ }
  const q = new URLSearchParams(location.search), demo = q.get("demo");
  if (demo) {
    const preset = G.presets.find(p => p.id === demo) ? demo : G.presets[0].id;
    await api("new", {preset, age: q.get("age") || "expansion", rivals: 6, difficulty: "balanced", seed: 7});
    await api("player", {id: 0}); await enterHome();
    const view = q.get("view");
    if (view === "shop") openShop(); if (view === "army") openArmy(); if (view === "news") openNews();
    if (view === "map") enterMap();
    if (view === "battle") {
      const rivals = await api("rivals"); await startBattle(rivals[1].id); autoDeploy();
      if (q.get("sim")) G.battle.simulate(+q.get("sim"));
    }
  }
}

function renderMenu() {
  const p = G.presets.find(x => x.id === G.pick.preset);
  $("regions").innerHTML = G.presets.map(r => {
    const th = M.THEMES[r.id] || M.THEMES.ganges, sw = [th.ground, th.wall, th.roof].map(c => `<i style="background:#${new THREE.Color(c).getHexString()}"></i>`).join("");
    return `<div class="region${r.id === G.pick.preset ? " sel" : ""}" data-id="${r.id}"><span class="sw">${sw}</span><b>${esc(r.name)}</b><p>${esc(r.summary)}</p>
      <span class="era">${yr(r.years[0])} – ${yr(r.years[1])}</span></div>`;
  }).join("");
  document.querySelectorAll(".region").forEach(el => (el.onclick = () => { Sound.init(); Sound.sfx("click"); G.pick.preset = el.dataset.id; renderMenu(); }));
  const unlock = {founding: ["Spearmen", "Archers", "Archer towers"], expansion: ["+ Horse raiders", "+ Bolt throwers", "+ Temple"], empire: ["+ Battering rams", "+ War elephants", "+ Catapults"]};
  $("ages").innerHTML = Object.entries(G.catalog.ages).map(([id, a]) => {
    const year = Math.round(p.years[0] + (p.years[1] - p.years[0]) * AGE_WHERE[id]);
    return `<div class="age${id === G.pick.age ? " sel" : ""}" data-id="${id}"><b>${a.name}</b><p>${a.summary}</p>
      <span class="era">from c. ${yr(year)} · palace level ${a.palace}</span><div class="unl">${unlock[id].map(u => `<span>${u}</span>`).join("")}</div></div>`;
  }).join("");
  document.querySelectorAll(".age").forEach(el => (el.onclick = () => { Sound.init(); Sound.sfx("click"); G.pick.age = el.dataset.id; renderMenu(); }));
}
$("rivals").oninput = () => { G.pick.rivals = +$("rivals").value; $("rivLabel").textContent = G.pick.rivals; };
const DIFF = {peaceful: "Rivals rarely raid. Time to build.", balanced: "Rivals raid when they see weakness.", warlike: "Rivals raid often. Build walls early."};
document.querySelectorAll("#difficulty button").forEach(b => (b.onclick = () => {
  Sound.init(); Sound.sfx("click"); G.pick.difficulty = b.dataset.v;
  document.querySelectorAll("#difficulty button").forEach(x => x.classList.toggle("on", x === b)); $("diffHint").textContent = DIFF[b.dataset.v];
}));
$("found").onclick = async () => {
  Sound.init(); Sound.sfx("open"); loading("Shaping the valley…");
  try {
    await api("new", {...G.pick, seed: Math.floor(Math.random() * 99999)});
    G.state = await api("state"); chooser();
  } catch (e) { toast(e.message, "bad"); } finally { loading(null); }
};
$("continue").onclick = async () => { Sound.init(); loading("Returning home…"); try { await enterHome(); } finally { loading(null); } };
function loading(text) { $("loading").classList.toggle("hidden", !text); if (text) $("loadingText").textContent = text; }

function chooser() {
  $("menu").classList.add("hidden");
  $("dynasties").innerHTML = G.state.kingdoms.map(k => {
    const king = k.characters.find(c => c.role === "ruler"), traits = Object.entries(k.traits).sort((a, b) => b[1] - a[1]).slice(0, 2);
    return `<div class="dyn" data-id="${k.id}"><b style="color:${k.color}">House of ${esc(k.name)}</b><small>King ${esc(king.name)} · ${LAWS[k.laws] || k.laws}</small>
      <small>👥 ${fmt(k.population)} people · ${k.free_speech ? "free speech" : "speech censored"}</small>
      <div class="traits">${traits.map(([t, v]) => `<span>${t} ${Math.round(v * 100)}</span>`).join("")}</div></div>`;
  }).join("");
  document.querySelectorAll(".dyn").forEach(el => (el.onclick = async () => {
    Sound.sfx("victory"); loading("Raising your town…");
    try { await api("player", {id: +el.dataset.id}); $("chooser").classList.add("hidden"); await enterHome(); } catch (e) { toast(e.message, "bad"); } finally { loading(null); }
  }));
  $("chooser").classList.remove("hidden");
}

// ------------------------------------------------------------------ home
async function enterHome() {
  ["menu", "chooser", "mapHud", "battleHud", "result"].forEach(id => $(id).classList.add("hidden"));
  const [town, state] = await Promise.all([api("town"), api("state")]);
  G.state = state; G.mode = "home";
  home.setTheme(state.preset, town.kingdom.color);
  applyTown(town, true);
  Stage.show(home);
  $("home").classList.remove("hidden"); $("navigator").classList.remove("hidden");
  $("navAvatar").innerHTML = portrait();
  clearInterval(G.poll); G.poll = setInterval(() => G.mode === "home" && refresh(), 4000);
}
async function refresh() { try { applyTown(await api("town")); } catch (e) { /* transient */ } }

function applyTown(town, first = false) {
  const prev = G.town; G.town = town; G.receivedAt = performance.now() / 1000;
  if (town.next_year_in) G.yearSeconds = Math.max(G.yearSeconds, town.next_year_in);
  home.sync(town.buildings, {army: town.army});
  for (const n of town.news || []) { G.news.unshift(n); G.unread++; if (n.kind === "war" || n.kind === "liveops") toast(n.text, n.kind === "war" ? "bad" : "good", 4200); }
  G.news = G.news.slice(0, 80);
  renderHud(prev);
  showNavigator(town.navigator, first);
  const soon = Math.min(...town.buildings.filter(b => b.target).map(b => b.ready_in), ...town.queue.map(q => q.ready_in), 99);
  clearTimeout(G.soon); if (soon < 99) G.soon = setTimeout(refresh, (soon + 0.4) * 1000);
}

function renderHud(prev) {
  const t = G.town, k = t.kingdom;
  $("crestDot").style.background = k.color; $("myName").textContent = "House of " + k.name; $("myName").style.color = k.color;
  $("myLaws").textContent = `${LAWS[k.laws] || k.laws} · ${fmt(k.population)} people · mood ${pct(k.happiness)}`;
  $("myPalace").textContent = t.palace; $("myGlory").textContent = t.glory; $("myKarma").textContent = Math.round(k.karma);
  $("yearNow").textContent = t.label;
  const bar = (cls, icon, value, max, label) => `<div class="bar ${cls}"><span class="ic">${icon}</span><div class="body"><b>${value}</b><small>${label}</small>
    <div class="fill"><i style="width:${clamp(max ? 100 * parseFloat(String(value).replace(/,/g, "")) / max : 0, 0, 100)}%"></i></div></div></div>`;
  $("bars").innerHTML = bar("gold", "🪙", fmt(t.gold), t.capacity.gold, `/ ${fmt(t.capacity.gold)}`) +
    bar("food", "🌾", fmt(t.food), t.capacity.food, `/ ${fmt(t.capacity.food)}`) +
    bar("army", "⚔️", t.army_size, t.housing, `/ ${t.housing} army${t.queued_size ? ` (+${t.queued_size})` : ""}`) +
    bar("build", "🔨", t.builders.total - t.builders.busy, t.builders.total, `/ ${t.builders.total} builders free`);
  if (prev) ["gold", "food"].forEach((r, i) => { if (prev[r] !== t[r]) $("bars").children[i].classList.add("pulse"); });
  const ready = t.buildings.filter(b => b.stored >= Math.max(1, 0.1 * (b.capacity || 1)) && b.level && !b.target && (b.type === "farm" || b.type === "mine"))
    .map(b => ({id: b.id, res: b.type === "farm" ? "food" : "gold", full: b.stored >= b.capacity * 0.95}));
  home.setBubbles(ready, collect);
  const now = performance.now() / 1000;
  home.setTimers(t.buildings.filter(b => b.target).map(b => ({id: b.id, until: now + b.ready_in, total: G.catalog.buildings[b.type].time[b.target - 1] || 1})));
  $("newsBadge").textContent = G.unread; $("newsBadge").classList.toggle("hidden", !G.unread);
  if (G.selected) panel(G.selected);
}
setInterval(() => { // the year ring and timers keep moving between server updates
  if (G.mode !== "home" || !G.town) return;
  const left = Math.max(0, G.town.next_year_in - (performance.now() / 1000 - G.receivedAt));
  $("yearRing").style.setProperty("--p", (100 * (1 - left / G.yearSeconds)) + "%");
}, 500);

async function collect(id) {
  Sound.init();
  try {
    const res = await api("town/collect", {id}), b = G.town.buildings.find(x => x.id === id);
    if (res.result.amount > 0) { Sound.sfx(b?.type === "farm" ? "grain" : "coin"); floatAt(home, b, `+${fmt(res.result.amount)} ${b?.type === "farm" ? "🌾" : "🪙"}`); }
    applyTown(res.town);
  } catch (e) { toast(e.message, "warn"); Sound.sfx("error"); }
}
function floatAt(view, b, text) {
  if (!b) return toast(text);
  const el = document.createElement("div"); el.className = "floater"; el.textContent = text; view.overlayRoot.appendChild(el);
  const start = performance.now(), base = view.center(b, 3);
  const tick = () => {
    const u = (performance.now() - start) / 1200; if (u >= 1) return el.remove();
    const s = Stage.project(base.clone().setY(3 + u * 1.5), view.camera); el.style.transform = `translate(${s.x}px, ${s.y}px)`; el.style.opacity = 1 - u * u;
    requestAnimationFrame(tick);
  };
  tick();
}

// selecting and the building panel
home.onTap = ndc => {
  if (G.placing) { const g = home.ghost.userData, tile = home.tileAt(ndc, g.size); if (tile) home.moveGhost(tile[0], tile[1]); return; }
  const id = home.pickBuilding(ndc);
  if (id === null || id === undefined) { G.selected = null; home.select(null); $("selPanel").classList.add("hidden"); return; }
  Sound.sfx("click"); G.selected = id; home.select(id); panel(id);
};
home.onMove = (ndc, e) => {
  if (!G.placing || e.pointerType !== "mouse" || e.buttons) return;
  const g = home.ghost.userData, tile = home.tileAt(ndc, g.size); if (tile) home.moveGhost(tile[0], tile[1]);
};
function panel(id) {
  const b = G.town.buildings.find(x => x.id === id); if (!b) { $("selPanel").classList.add("hidden"); return; }
  const spec = G.catalog.buildings[b.type], lim = G.town.limits[b.type];
  const next = b.level + 1, [res, costs] = spec.cost, cost = costs[next - 1], secs = spec.time[next - 1];
  const chips = [`❤️ ${fmt(b.hp)} HP`];
  if (b.rate) chips.push(`${b.type === "farm" ? "🌾" : "🪙"} ${b.rate}/min`, `holds ${fmt(b.capacity)}`);
  else if (b.capacity) chips.push(`stores ${fmt(b.capacity)}`);
  if (b.housing) chips.push(`⚔️ ${b.housing} army space`);
  if (b.defense) chips.push(`💥 ${Math.round(b.defense.damage / b.defense.interval)} dmg/s`, `🎯 range ${b.defense.range}`);
  if (b.type === "barracks") chips.push(`unlocks ${Object.values(G.catalog.troops).filter(t => t.barracks <= b.level).map(t => t.name).join(", ")}`);
  let up = "";
  if (b.target) up = `<button class="btn ghost" disabled>Building… ${Math.ceil(b.ready_in)}s</button>`;
  else if (b.level >= 5) up = `<button class="btn ghost" disabled>Highest level</button>`;
  else if (b.level >= lim.max_level) up = `<button class="btn ghost" disabled>Upgrade palace first</button>`;
  else up = `<button class="btn blue" id="upBtn">Upgrade ${RES[res]} ${fmt(cost)}${secs ? ` · ${secs < 60 ? secs + "s" : Math.round(secs / 60) + "m"}` : ""}</button>`;
  const acts = [up];
  if (b.rate && b.stored >= 1) acts.unshift(`<button class="btn green" id="colBtn">Collect ${b.type === "farm" ? "🌾" : "🪙"} ${fmt(b.stored)}</button>`);
  if (b.type === "barracks" || b.type === "camp") acts.push(`<button class="btn gold" id="trainBtn">Train troops</button>`);
  if (b.type !== "palace") acts.push(`<button class="btn ghost" id="moveBtn">Move</button>`);
  $("selPanel").innerHTML = `<h3>${spec.name}<span class="lv">Level ${b.level || "…"}</span></h3><p>${spec.about}</p>
    <div class="stats">${chips.map(c => `<span class="chip">${c}</span>`).join("")}</div><div class="acts">${acts.join("")}</div>`;
  $("selPanel").classList.remove("hidden");
  $("upBtn") && ($("upBtn").onclick = () => townAct("upgrade", {id}, "build"));
  $("colBtn") && ($("colBtn").onclick = () => collect(id));
  $("trainBtn") && ($("trainBtn").onclick = openArmy);
  $("moveBtn") && ($("moveBtn").onclick = () => startPlacing(b.type, b.id));
}
async function townAct(op, body, sound) {
  try {
    const res = await api("town/" + op, body); Sound.sfx(sound || "click"); applyTown(res.town); return res.result;
  } catch (e) { toast(e.message, "warn"); Sound.sfx("error"); return null; }
}

// placing new buildings and moving old ones
function startPlacing(type, moving = null) {
  closeSheets(); G.placing = {type, moving};
  const spec = G.catalog.buildings[type], b = moving && G.town.buildings.find(x => x.id === moving);
  home.startGhost(type, spec.size, b ? b.level : 1, moving);
  $("placeText").textContent = moving ? `Move the ${spec.name.toLowerCase()}: tap a spot` : `Place your ${spec.name.toLowerCase()}: tap a spot`;
  $("placeBar").classList.remove("hidden"); $("selPanel").classList.add("hidden");
  ["attackBtn", "rightBtns"].forEach(id => $(id).classList.add("hidden"));
}
function stopPlacing() {
  G.placing = null; home.endGhost(); $("placeBar").classList.add("hidden"); ["attackBtn", "rightBtns"].forEach(id => $(id).classList.remove("hidden"));
}
$("placeCancel").onclick = () => { Sound.sfx("click"); stopPlacing(); };
$("placeOk").onclick = async () => {
  const g = home.ghost?.userData; if (!g) return;
  if (!g.ok) { toast("There is no room there.", "warn"); Sound.sfx("error"); return; }
  const {type, moving} = G.placing;
  const r = moving ? await townAct("move", {id: moving, x: g.x, y: g.y}, "click") : await townAct("build", {type, x: g.x, y: g.y}, "build");
  if (r === null) return;
  if (type === "wall" && !moving && G.town.limits.wall.built < G.town.limits.wall.limit) { home.startGhost("wall", 1, 1); home.moveGhost(g.x + 1, g.y); return; }
  stopPlacing();
};

// ------------------------------------------------------------------ sheets
function closeSheets() { ["shop", "army", "news"].forEach(id => $(id).classList.add("hidden")); }
document.querySelectorAll("[data-close]").forEach(b => (b.onclick = () => { Sound.sfx("click"); $(b.dataset.close).classList.add("hidden"); }));
document.querySelectorAll(".modal").forEach(m => m.addEventListener("pointerdown", e => { if (e.target === m && m.id !== "result") m.classList.add("hidden"); }));

let shopTab = "Resources";
function openShop() { Sound.init(); Sound.sfx("open"); closeSheets(); renderShop(); $("shop").classList.remove("hidden"); }
function renderShop() {
  $("shopTabs").innerHTML = Object.keys(SHOP).map(t => `<button class="${t === shopTab ? "on" : ""}" data-t="${t}">${t}</button>`).join("");
  document.querySelectorAll("#shopTabs button").forEach(b => (b.onclick = () => { Sound.sfx("click"); shopTab = b.dataset.t; renderShop(); }));
  const t = G.town;
  $("shopItems").innerHTML = SHOP[shopTab].map(type => {
    const spec = G.catalog.buildings[type], lim = t.limits[type], [res, costs] = spec.cost, cost = costs[0], secs = spec.time[0];
    const nextPalace = spec.limit.findIndex(n => n > lim.limit) + 1;
    const locked = lim.limit === 0 ? `Palace ${nextPalace}` : lim.built >= lim.limit ? (nextPalace ? `Palace ${nextPalace} for more` : "All built") : "";
    const poor = t[res] < cost;
    return `<div class="item${locked ? " locked" : ""}" data-type="${type}">${locked ? `<span class="lock">${locked}</span>` : ""}
      <div class="art">${art("building", type, 1)}</div><b>${spec.name}</b><p>${spec.about}</p>
      <div class="row"><span class="cost${poor ? " no" : ""}">${RES[res]} ${fmt(cost)}</span><span>${secs ? "⏱ " + (secs < 60 ? secs + "s" : Math.round(secs / 60) + "m") : "instant"}</span></div>
      <span class="count">${lim.built} / ${lim.limit} built</span></div>`;
  }).join("");
  document.querySelectorAll("#shopItems .item").forEach(el => (el.onclick = () => {
    if (el.classList.contains("locked")) { Sound.sfx("error"); toast("Upgrade your palace to unlock more.", "warn"); return; }
    Sound.sfx("click"); startPlacing(el.dataset.type);
  }));
}
$("shopBtn").onclick = openShop;

function openArmy() { Sound.init(); Sound.sfx("open"); closeSheets(); renderArmy(); $("army").classList.remove("hidden"); }
function renderArmy() {
  const t = G.town, used = t.army_size + t.queued_size;
  $("armyCap").innerHTML = `<div class="cap">⚔️ ${used} / ${t.housing} army space<div class="fill"><i style="width:${100 * used / Math.max(t.housing, 1)}%"></i></div></div>`;
  $("troopCards").innerHTML = Object.entries(G.catalog.troops).map(([id, s]) => {
    const locked = t.barracks < s.barracks;
    return `<div class="item${locked ? " locked" : ""}" data-t="${id}">${locked ? `<span class="lock">Barracks ${s.barracks}</span>` : ""}
      <div class="art">${art("unit", id)}</div><b>${s.name}</b><p>${s.about}</p>
      <div class="stat"><span>❤️ ${s.hp}</span><span>${s.dps ? `💥 ${s.dps}/s` : `💥 ${s.blast} vs walls`}</span><span>👣 ${s.speed}</span><span>⚔️ ${s.housing} space</span></div>
      <div class="row"><span class="cost${t.food < s.cost ? " no" : ""}">🌾 ${s.cost}</span><span>⏱ ${s.time}s</span></div>
      ${locked ? "" : `<div class="train"><button data-n="1">+1</button><button data-n="5">+5</button><button data-n="10">+10</button></div>`}</div>`;
  }).join("");
  document.querySelectorAll("#troopCards .train button").forEach(b => (b.onclick = async e => {
    e.stopPropagation(); const type = b.closest(".item").dataset.t;
    const r = await townAct("train", {type, n: +b.dataset.n}, "deploy"); if (r) { toast(`Training ${r.trained} ${G.catalog.troops[type].name.toLowerCase()}${r.trained > 1 ? "s" : ""}`, "good", 1500); renderArmy(); }
  }));
  const q = {}; t.queue.forEach(x => (q[x.type] = (q[x.type] || 0) + 1));
  $("queue").innerHTML = Object.keys(q).length ? Object.entries(q).map(([k, n]) => `<span class="pill">${ICON[k]} ${n} ${G.catalog.troops[k].name}</span>`).join("") +
    `<p class="hint">Ready in ${Math.ceil(Math.max(...t.queue.map(x => x.ready_in)))}s</p>` : `<p class="hint">Nothing in training.</p>`;
  $("armyList").innerHTML = Object.entries(t.army).filter(([, n]) => n).map(([k, n]) => `<span class="pill">${ICON[k]} ${n} ${G.catalog.troops[k].name}</span>`).join("") || `<p class="hint">No troops yet.</p>`;
}
$("armyBtn").onclick = openArmy;

let newsTab = "chronicle";
async function openNews() {
  Sound.init(); Sound.sfx("open"); closeSheets(); G.unread = 0; $("newsBadge").classList.add("hidden");
  G.state = await api("state"); renderNews(); $("news").classList.remove("hidden");
}
function renderNews() {
  document.querySelectorAll("#newsTabs button").forEach(b => { b.classList.toggle("on", b.dataset.tab === newsTab); b.onclick = () => { Sound.sfx("click"); newsTab = b.dataset.tab; renderNews(); }; });
  const s = G.state, me = s.player;
  if (newsTab === "chronicle") {
    $("newsBody").innerHTML = s.chronicle.slice().reverse().map(e => `<div class="ev ${e.kind}${e.kingdom === me || e.defender === me ? " mine" : ""}"><b>${e.label}</b>${esc(e.text)}</div>`).join("");
  } else if (newsTab === "square") {
    const posts = s.feed.filter(p => p.kingdom === me).slice().reverse();
    $("newsBody").innerHTML = `<p class="hint">r/${esc(s.kingdoms[me].name.toLowerCase())}: what your people are saying. Town Wardens remove hate, threats, spam and manipulation; breaking the rules costs karma.</p>` +
      (posts.map(p => `<div class="post"><div class="votes">▲<br>${p.score}</div><div><div class="who">u/${esc(p.author.replace(/ /g, "_").toLowerCase())} · ${p.profession.replace("_", " ")} · ${p.label}</div><p>${esc(p.text)}</p></div></div>`).join("") || "<p class='hint'>Quiet so far.</p>");
  } else {
    $("newsBody").innerHTML = `<table><tr><th>Dynasty</th><th>Laws</th><th>People</th><th>Mood</th><th>Troops</th><th>Karma</th></tr>` +
      s.kingdoms.map(k => `<tr><td style="color:${k.color}">${esc(k.name)}${k.id === me ? " (you)" : ""}${k.alive ? "" : " · fallen"}</td><td>${LAWS[k.laws] || k.laws}</td><td>${fmt(k.population)}</td><td>${pct(k.happiness)}</td><td>${k.troops}</td><td>${k.karma}</td></tr>`).join("") + "</table>";
  }
}
$("newsBtn").onclick = openNews;
$("soundBtn").onclick = () => { Sound.on = !Sound.on; $("soundBtn").textContent = Sound.on ? "🔊" : "🔇"; if (!Sound.on) speechSynthesis.cancel(); };

// ------------------------------------------------------------------ attack: choose a town on the map
async function enterMap() {
  if (!Object.values(G.town.army).some(n => n > 0)) { toast("You have no troops. Train some first.", "warn"); openArmy(); return; }
  Sound.sfx("open"); loading("Scouting the valley…");
  try {
    const [rivals, state] = await Promise.all([api("rivals"), api("state")]);
    if (!world.terrain) world.build(await api("terrain"));
    G.state = state; G.rivals = rivals; G.mode = "map";
    world.show_state(state, rivals); world.onPick = id => pickRival(id);
    Stage.show(world); world.focus(state.player, 70);
    $("home").classList.add("hidden"); $("mapHud").classList.remove("hidden");
    renderRivals();
  } catch (e) { toast(e.message, "bad"); } finally { loading(null); }
}
function renderRivals(sel = null) {
  $("rivalList").innerHTML = G.rivals.map(r => `<div class="rival${r.id === sel ? " sel" : ""}" data-id="${r.id}">
    <div class="top"><span class="dot" style="background:${r.color}"></span><b>${esc(r.name)}</b><span class="badge" style="margin-left:auto">🏛 Palace ${r.palace}</span></div>
    <div class="meta"><span class="badge">🪙 ${fmt(r.loot.gold)}</span><span class="badge">🌾 ${fmt(r.loot.food)}</span><span class="badge">${LAWS[r.laws] || r.laws}</span>
      ${r.raided_you ? `<span class="badge good">raided you: fair target</span>` : `<span class="badge warn">unprovoked: −karma</span>`}</div>
    <button class="btn red" data-raid="${r.id}">⚔️ Raid</button></div>`).join("");
  document.querySelectorAll(".rival").forEach(el => (el.onclick = () => pickRival(+el.dataset.id)));
  document.querySelectorAll("[data-raid]").forEach(b => (b.onclick = e => { e.stopPropagation(); startBattle(+b.dataset.raid); }));
}
function pickRival(id) { if (id === G.state.player) return; Sound.sfx("click"); world.focus(id, 34); renderRivals(id); document.querySelector(`.rival[data-id="${id}"]`)?.scrollIntoView({block: "nearest", behavior: "smooth"}); }
$("attackBtn").onclick = () => { Sound.init(); enterMap(); };
$("homeBtn").onclick = () => { Sound.sfx("click"); $("mapHud").classList.add("hidden"); enterHome(); };

// ------------------------------------------------------------------ battle
async function startBattle(target) {
  loading("Marching…");
  try {
    const data = await api("battle/start", {target});
    G.mode = "battle"; $("mapHud").classList.add("hidden"); $("home").classList.add("hidden"); $("navigator").classList.add("hidden"); $("navShow").classList.add("hidden");
    G.battle?.dispose();
    G.battle = new Battle(raid, G.catalog, data, myColor(), battleOver);
    Stage.show(raid); $("battleHud").classList.remove("hidden"); Sound.sfx("horn");
  } catch (e) { toast(e.message, "bad"); } finally { loading(null); }
}
$("endBattle").onclick = () => { Sound.sfx("click"); G.battle?.finish(); };
function autoDeploy() { // for demos and screenshots: spread the army around the town
  const b = G.battle; if (!b) return;
  const spots = [[0.3, 20], [43.2, 24], [20, 0.3], [24, 43.2], [0.3, 30], [43.2, 12]];
  let i = 0;
  for (const [t, n] of Object.entries(b.left)) for (let k = 0; k < n; k++) {
    b.selected = t; const [x, y] = spots[i++ % spots.length];
    b.deployAt(x + Math.random(), y + Math.random(), true);
  }
}
function battleOver(res, report) {
  const o = res?.outcome;
  setTimeout(() => {
    $("battleHud").classList.add("hidden");
    const stars = o ? o.stars : 0;
    $("rTitle").textContent = stars ? "Victory!" : "Defeat";
    $("rStars").innerHTML = [0, 1, 2].map(i => `<span class="${i < stars ? "on" : ""}" style="animation-delay:${0.25 + i * 0.35}s">★</span>`).join("");
    if (o) {
      const left = {gold: o.loot.gold - o.gained.gold, food: o.loot.food - o.gained.food};
      $("rBody").innerHTML = `<div class="big">${Math.round(o.destruction)}% destroyed</div>
        <div class="big">🪙 +${fmt(o.gained.gold)} &nbsp; 🌾 +${fmt(o.gained.food)}</div>
        ${left.gold + left.food > 0 ? `<p class="note">Your storehouses were full: ${fmt(left.gold)} gold and ${fmt(left.food)} grain were left behind. Build or upgrade storage.</p>` : ""}
        <p>🏆 Glory ${o.glory >= 0 ? "+" : ""}${o.glory} (now ${o.glory_total})</p>
        ${o.stars ? `<p class="note">${o.provoked ? "They raided you first: your people call it justice (karma +1)." : "An unprovoked raid: your people are uneasy (karma −2)."}</p>` : ""}
        ${o.bonus ? `<p class="note">LiveOps bounty quest complete: +${fmt(o.bonus)} gold.</p>` : ""}
        ${o.corrected.length ? `<p class="note">The server adjusted this report: ${o.corrected.join("; ")}.</p>` : ""}`;
      Sound.sfx(stars ? "victory" : "defeat");
    } else $("rBody").innerHTML = `<p class="note">The report could not be sent. Your town is unchanged.</p>`;
    $("result").classList.remove("hidden");
  }, 900);
}
$("rHome").onclick = async () => {
  Sound.sfx("click"); $("result").classList.add("hidden");
  G.battle?.dispose(); G.battle = null;
  loading("Marching home…"); try { await enterHome(); } finally { loading(null); }
};

// ------------------------------------------------------------------ the Navigator
function showNavigator(nav, speak = false) {
  if (!nav) return;
  const changed = nav.id !== showNavigator.last;
  $("navText").textContent = nav.text; $("navStep").textContent = `${nav.index + 1} / ${nav.total}`;
  $("navNext").textContent = nav.index + 1 >= nav.total ? "Done" : "Next";
  const tip = nav.tip || (G.town?.quest ? `Bounty quest: ${G.town.quest.goal} (reward ${G.town.quest.reward} gold).` : "");
  $("navTip").classList.toggle("hidden", !tip); if (tip) $("navTip").textContent = tip;
  if (changed || speak) Sound.say(nav.text);
  showNavigator.last = nav.id;
}
$("navNext").onclick = async () => { Sound.init(); Sound.sfx("click"); showNavigator(await api("navigator", {event: "next"})); };
$("navHide").onclick = () => { $("navigator").classList.add("hidden"); $("navShow").classList.remove("hidden"); speechSynthesis.cancel(); };
$("navShow").onclick = () => { $("navigator").classList.remove("hidden"); $("navShow").classList.add("hidden"); };
$("askForm").onsubmit = async e => {
  e.preventDefault(); const q = $("askInput").value.trim(); if (!q) return;
  $("navText").textContent = "…"; $("askInput").value = "";
  try { const a = await api("navigator/ask", {question: q}); $("navText").textContent = a.answer; Sound.say(a.answer); }
  catch (err) { $("navText").textContent = "I could not hear you over the market noise. Try again?"; }
};
function portrait() {
  return `<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="23" fill="#2a5f8a" stroke="#ffcf4a" stroke-width="2"/>
    <path d="M8 46 q16 -16 32 0z" fill="#1f5f8b"/><circle cx="24" cy="24" r="11" fill="#e0ac69"/><path d="M13 22 q11 -14 22 0 q-11 -5 -22 0z" fill="#2b1b0e"/>
    <circle cx="20" cy="25" r="1.5" fill="#222"/><circle cx="28" cy="25" r="1.5" fill="#222"/><path d="M20 30 q4 3 8 0" stroke="#222" fill="none" stroke-width="1.4"/>
    <path d="M10 22 q14 -22 28 0 q-6 -6 -14 -6 q-8 0 -14 6z" fill="#1f5f8b"/><circle cx="24" cy="9" r="3" fill="#ffcf4a"/></svg>`;
}

addEventListener("keydown", e => { if (e.key === "Escape") { if (G.placing) stopPlacing(); closeSheets(); } });
boot().catch(e => { console.error(e); toast("Could not load the game: " + e.message, "bad", 8000); });
