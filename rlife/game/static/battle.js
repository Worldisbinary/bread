// Raids. The rival town is rendered by a TownView; this module runs the fight on top of it:
// deploying troops outside the red zone, troop AI (targets by preference, A* paths, wall breaking),
// defenses with real projectiles (arrows, bolts, catapult stones with splash), damage, loot taken as
// buildings are hit, rubble, stars, and the report sent to the server (which checks it).
import * as THREE from "three";
import {Stage, Sound, $, fmt, api, toast, clamp} from "./core.js";
import * as M from "./models.js";
import {astar, rectDist} from "./path.js";

const RES_TYPES = new Set(["farm", "mine", "granary", "treasury"]);
const ICONS = {spearman: "🛡️", archer: "🏹", raider: "🐎", ram: "🪵", elephant: "🐘"};
const projGeo = {
  arrow: new THREE.CylinderGeometry(0.02, 0.02, 0.6, 4).rotateX(Math.PI / 2),
  bolt: new THREE.CylinderGeometry(0.05, 0.05, 1.0, 5).rotateX(Math.PI / 2),
  stone: new THREE.DodecahedronGeometry(0.24, 0),
};
const projMat = {arrow: M.mat(0x4a3420), bolt: M.mat(0x3a3a3e), stone: M.mat(0x8a8378)};
const debrisGeo = new THREE.BoxGeometry(0.16, 0.16, 0.16);
const puffTex = (() => {
  const c = document.createElement("canvas"); c.width = c.height = 64; const x = c.getContext("2d");
  const g = x.createRadialGradient(32, 32, 2, 32, 32, 30); g.addColorStop(0, "rgba(255,255,255,0.95)"); g.addColorStop(1, "rgba(255,255,255,0)");
  x.fillStyle = g; x.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c);
})();

export class Battle {
  constructor(view, catalog, data, myColor, onEnd) {
    Object.assign(this, {view, catalog, data, myColor, onEnd});
    this.grid = data.grid; this.seconds = data.seconds; this.time = 0; this.started = false; this.ended = false;
    this.left = {...data.army}; this.deployed = {}; this.selected = Object.keys(this.left).find(t => this.left[t] > 0);
    this.loot = {gold: 0, food: 0}; this.troops = []; this.shots = []; this.fx = []; this.pathBudget = 0;
    this.b = data.buildings.map(b => ({...b, maxHp: b.hp, alive: true, taken: {gold: 0, food: 0}, cd: Math.random(), target: null}));
    this.byId = new Map(this.b.map(b => [b.id, b]));
    this.targets = this.b.filter(b => b.type !== "wall");
    this.total = this.targets.length; this.destroyed = 0; this.palaceDown = false; this.stars = 0;
    view.setTheme(data.preset, data.target.color);
    view.sync(data.buildings, {villagers: true, army: null});
    view.walkers.forEach(w => (w.speed = (w.speed || 0.9) * 0.6));
    this.occ = view.occ; this.zone(); this.hud();
    view.tick = (dt, t) => this.update(dt, t);
    view.overlayTick = () => this.bars();
    view.onTap = ndc => this.deploy(ndc);
    view.onHold = ndc => this.deploy(ndc, true);
    view.onPress = null; view.onMove = null; view.onRelease = null;
    view.controls.target.set(0, 0, 0); view.camera.position.set(23, 34, 23);
  }

  // ---------------------------------------------------------------- deploy zone
  zone() {
    const n = this.grid, f = this.forbidden = new Uint8Array(n * n);
    for (const b of this.b) for (let y = b.y - 1; y < b.y + b.size + 1; y++) for (let x = b.x - 1; x < b.x + b.size + 1; x++)
      if (x >= 0 && y >= 0 && x < n && y < n) f[y * n + x] = 1;
    const px = 8, cv = document.createElement("canvas"); cv.width = cv.height = n * px; const c = cv.getContext("2d");
    c.fillStyle = "rgba(255,50,30,0.55)";
    for (let i = 0; i < n * n; i++) if (f[i]) c.fillRect((i % n) * px, Math.floor(i / n) * px, px, px);
    c.strokeStyle = "rgba(255,255,255,0.55)"; c.lineWidth = 2; c.strokeRect(1, 1, n * px - 2, n * px - 2);
    const tex = new THREE.CanvasTexture(cv); tex.magFilter = THREE.NearestFilter;
    this.zoneMesh = new THREE.Mesh(new THREE.PlaneGeometry(n, n), new THREE.MeshBasicMaterial({map: tex, transparent: true, depthWrite: false, opacity: 0.7}));
    this.zoneMesh.rotation.x = -Math.PI / 2; this.zoneMesh.position.y = 0.05; this.zoneMesh.renderOrder = 2; this.view.scene.add(this.zoneMesh);
  }

  deploy(ndc, holding = false) {
    if (this.ended) return;
    const hit = this.view.tileAt(ndc); if (!hit) return;
    this.deployAt(hit[2], hit[3], holding);
  }

  deployAt(fx, fy, holding = false) {
    const n = this.grid, tx = Math.floor(fx), ty = Math.floor(fy);
    if (fx < 0 || fy < 0 || fx >= n || fy >= n) return;
    if (this.forbidden[ty * n + tx]) { if (!holding) { this.zoneMesh.material.opacity = 1; toast("Deploy outside the red zone", "warn", 1400); Sound.sfx("error"); } return; }
    const type = this.selected;
    if (!type || !(this.left[type] > 0)) { if (!holding) toast("Choose a troop below", "warn", 1400); return; }
    this.left[type]--; this.deployed[type] = (this.deployed[type] || 0) + 1;
    const spec = this.catalog.troops[type], j = holding ? 0.6 : 0.15;
    const tr = {type, spec, x: fx + (Math.random() - 0.5) * j, y: fy + (Math.random() - 0.5) * j, hp: spec.hp, maxHp: spec.hp,
      target: null, wall: null, path: null, cd: 0.3 + Math.random() * 0.4, dead: false, t: 0};
    tr.mesh = M.unit(type, this.myColor, {scale: type === "elephant" ? 0.85 : 1.15});
    tr.mesh.position.copy(this.view.toWorld(tr.x, tr.y)); this.view.scene.add(tr.mesh);
    this.troops.push(tr); this.puff(tr.mesh.position, 0xffffff, 3, 0.5);
    Sound.sfx("deploy");
    if (!this.started) { this.started = true; Sound.sfx("horn"); }
    if (this.left[type] === 0) this.selected = Object.keys(this.left).find(t => this.left[t] > 0) || type;
    this.hud();
  }

  // ---------------------------------------------------------------- troop brain
  choose(tr) {
    const alive = this.targets.filter(b => b.alive);
    let pool = alive;
    if (tr.spec.prefers === "resource") pool = alive.filter(b => RES_TYPES.has(b.type));
    if (tr.spec.prefers === "defense") pool = alive.filter(b => b.defense);
    if (tr.spec.prefers === "wall") {
      const walls = this.b.filter(b => b.type === "wall" && b.alive && rectDist(tr.x, tr.y, b) < 14);
      if (walls.length) pool = walls;
    }
    if (!pool.length) pool = alive;
    let best = null, bd = Infinity;
    for (const b of pool) { const d = rectDist(tr.x, tr.y, b); if (d < bd) { bd = d; best = b; } }
    return best;
  }
  route(tr) {
    const n = this.grid, target = tr.target, range = tr.spec.range;
    const cost = i => {
      const id = this.occ[i]; if (id === -1) return 1;
      const b = this.byId.get(id); if (!b || !b.alive) return 1.2;
      if (b.type === "wall") return tr.spec.prefers === "wall" ? Infinity : 4 + b.hp / 60;
      return Infinity;
    };
    return astar(n, Math.floor(tr.x), Math.floor(tr.y), (x, y) => rectDist(x + 0.5, y + 0.5, target) <= range + 0.05,
      (x, y) => rectDist(x + 0.5, y + 0.5, target), cost, 7000);
  }
  wallAt(x, y) { const id = this.occ[y * this.grid + x]; const b = id >= 0 ? this.byId.get(id) : null; return b && b.type === "wall" && b.alive ? b : null; }

  moveTroop(tr, dt, t) {
    if (!tr.target || !tr.target.alive) { tr.target = this.choose(tr); tr.path = null; tr.wall = null; if (!tr.target) { M.animate(tr.mesh, t, false, false); return; } }
    if (tr.wall && !tr.wall.alive) tr.wall = null;
    const aim = tr.wall || tr.target;
    if (rectDist(tr.x, tr.y, aim) <= tr.spec.range + 0.05) return this.strike(tr, aim, dt, t);
    if (!tr.path) {
      if (this.pathBudget <= 0) { M.animate(tr.mesh, t, false, false); return; }
      this.pathBudget--; tr.path = this.route(tr) || [];
    }
    let gx, gy;
    if (tr.path.length) {
      const [nx, ny] = tr.path[0], wall = this.wallAt(nx, ny);
      if (wall) { tr.wall = wall; return; }
      gx = nx + 0.5; gy = ny + 0.5;
      if (Math.hypot(gx - tr.x, gy - tr.y) < 0.12) { tr.path.shift(); return; }
    } else { gx = aim.x + aim.size / 2; gy = aim.y + aim.size / 2; }
    const dx = gx - tr.x, dy = gy - tr.y, d = Math.hypot(dx, dy) || 1, step = Math.min(d, tr.spec.speed * dt);
    tr.x += dx / d * step; tr.y += dy / d * step;
    tr.mesh.rotation.y = Math.atan2(dx, dy);
    M.animate(tr.mesh, t, true, false, tr.spec.speed / 1.4);
  }

  strike(tr, b, dt, t) {
    const cx = b.x + b.size / 2, cy = b.y + b.size / 2;
    tr.mesh.rotation.y = Math.atan2(cx - tr.x, cy - tr.y);
    M.animate(tr.mesh, t, false, true);
    tr.cd -= dt; if (tr.cd > 0) return;
    tr.cd = 1.0;
    if (tr.type === "ram") { // smash: heavy damage to walls nearby, a little to anything else, and the ram is spent
      const r = tr.spec.blast_radius;
      for (const o of this.b) if (o.alive && rectDist(tr.x, tr.y, o) <= r) this.damage(o, o.type === "wall" ? tr.spec.blast : tr.spec.blast * 0.08);
      this.boom(this.view.toWorld(tr.x, tr.y, 0.3), 1.0); this.kill(tr); return;
    }
    const dmg = tr.spec.dps * (tr.spec.bonus && RES_TYPES.has(b.type) ? tr.spec.bonus : 1);
    if (tr.type === "archer") this.fire("arrow", this.view.toWorld(tr.x, tr.y, 0.7), {building: b}, dmg, 0, 16);
    else { this.damage(b, dmg); this.sparks(this.view.toWorld(tr.x + (cx - tr.x) * 0.5, tr.y + (cy - tr.y) * 0.5, 0.5)); Sound.sfx("hit"); }
  }

  damage(b, dmg) {
    if (!b.alive) return;
    const dealt = Math.min(b.hp, dmg); b.hp -= dmg; b.hit = 0.2;
    for (const res of ["gold", "food"]) {
      const take = (b.loot?.[res] || 0) * dealt / b.maxHp;
      if (take > 0) { b.taken[res] += take; this.loot[res] += take; }
    }
    if (b.hp <= 0) this.destroy(b);
  }

  destroy(b) {
    b.alive = false; b.hp = 0;
    for (const res of ["gold", "food"]) { const rest = (b.loot?.[res] || 0) - b.taken[res]; if (rest > 0) { this.loot[res] += rest; b.taken[res] += rest; } }
    const pos = this.view.center(b, 0.3);
    if (b.type === "wall") {
      this.wallsDirty = true; Sound.sfx("hit"); this.burst(pos, 0x8a8378, 6);
    } else {
      const m = this.view.models.get(b.id);
      if (m) { m.group.clear(); m.group.add(M.rubble(b.size, b.id)); m.group.scale.setScalar(1); }
      this.destroyed++; if (b.type === "palace") this.palaceDown = true;
      Sound.sfx("crumble"); Stage.shake = Math.min(1, Stage.shake + (b.size >= 4 ? 0.9 : 0.35));
      this.burst(pos, 0x7d7468, 10 + b.size * 4); this.puff(pos, 0xc9b8a0, 6 + b.size * 2, b.size * 0.5);
      if ((b.loot?.gold || 0) + (b.loot?.food || 0) > 0) this.floater(pos, `+${fmt(b.taken.gold)} 🪙  +${fmt(b.taken.food)} 🌾`);
      this.checkStars();
    }
    for (const tr of this.troops) if (tr.target === b || tr.wall === b) { tr.target = tr.target === b ? null : tr.target; tr.wall = null; tr.path = null; }
    if (b.type === "wall") for (const tr of this.troops) tr.path = null;
  }

  checkStars() {
    const pct = this.destroyed / Math.max(this.total, 1) * 100;
    const stars = (pct >= 50) + (this.palaceDown ? 1 : 0) + (pct >= 99.5);
    while (this.stars < stars) { this.stars++; Sound.sfx("star"); toast("★".repeat(this.stars) + "  star earned!", "good", 1500); }
    if (pct >= 99.5) this.finish();
  }

  kill(tr) {
    if (tr.dead) return; tr.dead = true; tr.deathT = 1.2;
    this.puff(tr.mesh.position, 0xffffff, 3, 0.3);
  }

  // ---------------------------------------------------------------- defenses
  defend(b, dt) {
    const def = b.defense; b.cd -= dt;
    const cx = b.x + b.size / 2, cy = b.y + b.size / 2;
    const ok = tr => { if (tr.dead) return false; const d = Math.hypot(tr.x - cx, tr.y - cy); return d <= def.range + b.size / 2 && d >= def.min_range; };
    if (!b.target || !ok(b.target)) {
      b.target = null; let bd = Infinity;
      for (const tr of this.troops) { if (!ok(tr)) continue; const d = Math.hypot(tr.x - cx, tr.y - cy); if (d < bd) { bd = d; b.target = tr; } }
    }
    const m = this.view.models.get(b.id); if (!m || !m.model) return;
    if (!m.turret) m.model.traverse(o => { if (o.userData.turret) m.turret = o; });
    if (b.target && m.turret) {
      const want = Math.atan2(b.target.x - cx, b.target.y - cy), cur = m.turret.rotation.y;
      m.turret.rotation.y = cur + Math.atan2(Math.sin(want - cur), Math.cos(want - cur)) * Math.min(1, dt * 8);
    }
    if (m.turret?.userData.arm) { const arm = m.turret.userData.arm; arm.rotation.x += ((b.fling > 0 ? 0.9 : -0.9) - arm.rotation.x) * Math.min(1, dt * (b.fling > 0 ? 14 : 2)); b.fling = Math.max(0, (b.fling || 0) - dt); }
    if (!b.target || b.cd > 0) return;
    b.cd = def.interval;
    const from = this.view.center(b).add(m.model.userData.muzzle || new THREE.Vector3(0, 2, 0));
    if (b.type === "catapult") {
      b.fling = 0.25; Sound.sfx("bolt");
      this.fire("stone", from, {x: b.target.x, y: b.target.y}, def.damage, def.splash, 0, 1.4);
    } else if (b.type === "bolt_thrower") { Sound.sfx("bolt"); this.fire("bolt", from, {troop: b.target}, def.damage, 0, 26); }
    else { Sound.sfx("arrow"); this.fire("arrow", from, {troop: b.target}, def.damage, 0, 22); }
  }

  fire(kind, from, to, dmg, splash, speed, flight = 0) {
    const mesh = new THREE.Mesh(projGeo[kind], projMat[kind]); mesh.castShadow = true; mesh.position.copy(from);
    this.view.scene.add(mesh);
    this.shots.push({kind, mesh, from: from.clone(), to, dmg, splash, speed, flight, t: 0});
  }

  shotTarget(s) {
    if (s.to.troop) return this.view.toWorld(s.to.troop.x, s.to.troop.y, 0.45);
    if (s.to.building) return this.view.center(s.to.building, 1.0);
    return this.view.toWorld(s.to.x, s.to.y, 0.1);
  }

  moveShot(s, dt) {
    const end = this.shotTarget(s);
    if (s.flight) { // a lobbed stone: fixed landing point, parabolic arc
      s.t += dt / s.flight; const u = Math.min(1, s.t);
      const p = s.from.clone().lerp(end, u); p.y += Math.sin(u * Math.PI) * 5; s.mesh.position.copy(p); s.mesh.rotation.x += dt * 8;
      if (u >= 1) { this.land(s, end); return true; }
      return false;
    }
    const d = end.clone().sub(s.mesh.position), dist = d.length();
    if (dist < 0.3 || s.t > 3) { this.land(s, end); return true; }
    s.t += dt; d.normalize();
    s.mesh.position.addScaledVector(d, Math.min(dist, s.speed * dt)); s.mesh.lookAt(end);
    return false;
  }

  land(s, at) {
    this.view.scene.remove(s.mesh);
    if (s.to.troop) { if (!s.to.troop.dead) this.hurt(s.to.troop, s.dmg); this.sparks(at); }
    else if (s.to.building) { this.damage(s.to.building, s.dmg); this.sparks(at); }
    else { // stone: splash everything nearby
      for (const tr of this.troops) if (!tr.dead && Math.hypot(tr.x - s.to.x, tr.y - s.to.y) <= s.splash) this.hurt(tr, s.dmg);
      this.boom(at, 0.55);
    }
  }

  hurt(tr, dmg) { tr.hp -= dmg; tr.hit = 0.15; if (tr.hp <= 0) this.kill(tr); }

  // ---------------------------------------------------------------- effects
  burst(pos, color, n) {
    for (let i = 0; i < n; i++) {
      const m = new THREE.Mesh(debrisGeo, M.mat(color)); m.position.copy(pos); m.castShadow = true;
      m.scale.setScalar(0.6 + Math.random()); this.view.scene.add(m);
      this.fx.push({m, v: new THREE.Vector3((Math.random() - 0.5) * 5, 2 + Math.random() * 5, (Math.random() - 0.5) * 5), life: 1.1, kind: "debris"});
    }
  }
  puff(pos, color, n, spread) {
    for (let i = 0; i < n; i++) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({map: puffTex, color, transparent: true, opacity: 0.8, depthWrite: false}));
      s.position.copy(pos).add(new THREE.Vector3((Math.random() - 0.5) * spread * 2, Math.random() * 0.5, (Math.random() - 0.5) * spread * 2));
      s.scale.setScalar(0.6 + Math.random() * 0.6); this.view.scene.add(s);
      this.fx.push({m: s, v: new THREE.Vector3((Math.random() - 0.5) * 0.6, 0.6 + Math.random() * 0.6, (Math.random() - 0.5) * 0.6), life: 1.4, kind: "puff"});
    }
  }
  sparks(pos) { this.puff(pos, 0xffe2a0, 2, 0.15); }
  boom(pos, size) {
    Sound.sfx("boom"); Stage.shake = Math.min(1, Stage.shake + 0.25 * size);
    this.puff(pos, 0xd8c8a8, 8, size); this.burst(pos, 0x6f665a, 6);
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.2, 0.45, 32), new THREE.MeshBasicMaterial({color: 0xfff1c0, transparent: true, opacity: 0.9, depthWrite: false}));
    ring.rotation.x = -Math.PI / 2; ring.position.copy(pos).setY(0.08); this.view.scene.add(ring);
    this.fx.push({m: ring, life: 0.5, kind: "ring", grow: 6 * size});
  }
  floater(pos, text) {
    const el = document.createElement("div"); el.className = "floater"; el.textContent = text;
    this.view.overlayRoot.appendChild(el); this.fx.push({el, pos: pos.clone().setY(2.5), life: 1.6, kind: "text"});
  }

  // ---------------------------------------------------------------- the loop
  /** Run the fight forward without drawing (demos, screenshots, tests). */
  simulate(seconds, step = 0.05) {
    this.simT = this.simT || 0;
    for (let s = 0; s < seconds && !(this.ended && !this.troops.length); s += step) { this.simT += step; this.update(step, this.simT); }
  }

  update(dt, t) {
    if (this.ended && !this.troops.length && !this.shots.length && !this.fx.length) return;
    if (this.started && !this.ended) { this.time += dt; if (this.time >= this.seconds) this.finish(); }
    this.pathBudget = 5;
    for (const b of this.b) if (b.alive && b.defense && !this.ended) this.defend(b, dt);
    for (const tr of this.troops) if (!tr.dead && !this.ended) this.moveTroop(tr, dt, t);
    for (let i = 0; i < this.troops.length; i++) { // keep troops from piling onto one spot
      const a = this.troops[i]; if (a.dead) continue;
      for (let j = i + 1; j < this.troops.length; j++) {
        const b = this.troops[j]; if (b.dead) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy), min = (a.type === "elephant" || b.type === "elephant") ? 0.8 : 0.32;
        if (d > 0 && d < min) { const push = (min - d) / 2 / d; a.x -= dx * push; a.y -= dy * push; b.x += dx * push; b.y += dy * push; }
      }
    }
    for (const tr of this.troops) {
      tr.mesh.position.copy(this.view.toWorld(tr.x, tr.y));
      if (tr.hit > 0) { tr.hit -= dt; tr.mesh.position.y += 0.05; }
      if (tr.dead) { tr.deathT -= dt; tr.mesh.rotation.z = Math.min(1.5, (1.2 - tr.deathT) * 4); tr.mesh.position.y -= (1.2 - tr.deathT) * 0.3; }
    }
    this.troops = this.troops.filter(tr => { if (tr.dead && tr.deathT <= 0) { this.view.scene.remove(tr.mesh); return false; } return true; });
    this.shots = this.shots.filter(s => !this.moveShot(s, dt));
    for (const f of this.fx) {
      f.life -= dt;
      if (f.kind === "debris") { f.v.y -= 14 * dt; f.m.position.addScaledVector(f.v, dt); if (f.m.position.y < 0.08) { f.m.position.y = 0.08; f.v.multiplyScalar(0.5); } f.m.scale.multiplyScalar(0.985); }
      if (f.kind === "puff") { f.m.position.addScaledVector(f.v, dt); f.m.scale.multiplyScalar(1 + dt * 0.9); f.m.material.opacity = Math.max(0, f.life / 1.4) * 0.8; }
      if (f.kind === "ring") { f.m.scale.multiplyScalar(1 + dt * f.grow); f.m.material.opacity = Math.max(0, f.life / 0.5); }
      if (f.kind === "text") f.pos.y += dt * 0.8;
      if (f.life <= 0) { if (f.el) f.el.remove(); else this.view.scene.remove(f.m); }
    }
    this.fx = this.fx.filter(f => f.life > 0);
    for (const [, m] of this.view.models) { const b = this.byId.get(m.b.id); if (b?.hit > 0) { b.hit -= dt; m.group.position.x = this.view.center(b).x + Math.sin(t * 60) * 0.05; } }
    if (this.wallsDirty && (t - (this.wallT || 0)) > 0.25) {
      this.wallsDirty = false; this.wallT = t;
      const alive = this.b.filter(b => b.type === "wall" && b.alive);
      for (const w of this.b) if (w.type === "wall" && !w.alive) for (let i = 0; i < this.occ.length; i++) if (this.occ[i] === w.id) this.occ[i] = -1;
      this.view.layer.remove(this.view.wallObj); this.view.wallObj = M.wallMesh(alive, this.view.theme, (x, y) => this.view.toWorld(x, y)); this.view.layer.add(this.view.wallObj);
    }
    const zoneTarget = this.ended ? 0 : this.started ? 0.35 : 0.7; this.zoneMesh.material.opacity += (zoneTarget - this.zoneMesh.material.opacity) * Math.min(1, dt * 2);
    if (this.started && !this.ended && !this.troops.some(tr => !tr.dead) && !Object.values(this.left).some(n => n > 0)) this.finish();
    this.hudTick();
  }

  bars() {
    const root = this.view.overlayRoot;
    this.barEls = this.barEls || new Map();
    const want = new Set();
    for (const b of this.b) if (b.alive && b.hp < b.maxHp && b.type !== "wall") want.add("b" + b.id);
    for (const [k, el] of this.barEls) if (!want.has(k)) { el.remove(); this.barEls.delete(k); }
    for (const k of want) {
      const b = this.byId.get(+k.slice(1));
      let el = this.barEls.get(k); if (!el) { el = document.createElement("div"); el.className = "hpbar"; el.innerHTML = "<i></i>"; root.appendChild(el); this.barEls.set(k, el); }
      const s = Stage.project(this.view.center(b, 2.4), this.view.camera);
      el.style.display = s.visible ? "" : "none"; el.style.transform = `translate(${s.x}px, ${s.y}px)`;
      el.firstChild.style.width = (100 * b.hp / b.maxHp) + "%";
    }
    for (const f of this.fx) if (f.el) { const s = Stage.project(f.pos, this.view.camera); f.el.style.transform = `translate(${s.x}px, ${s.y}px)`; f.el.style.opacity = Math.min(1, f.life); }
  }

  // ---------------------------------------------------------------- HUD and the end
  hud() {
    $("bTarget").innerHTML = `<span class="dot" style="background:${this.data.target.color}"></span>House of ${this.data.target.name} <small>Palace ${this.data.palace} · ${this.data.target.laws}</small>`;
    $("bAvail").innerHTML = `Available: <b>🪙 ${fmt(this.data.loot.gold)}</b> <b>🌾 ${fmt(this.data.loot.food)}</b>`;
    $("troopBar").innerHTML = Object.entries(this.data.army).filter(([, n]) => n > 0).map(([t]) => `
      <button class="troop${t === this.selected ? " sel" : ""}${this.left[t] ? "" : " empty"}" data-t="${t}">
        <span class="ti">${ICONS[t]}</span><b>x${this.left[t]}</b><small>${this.catalog.troops[t].name}</small></button>`).join("");
    document.querySelectorAll("#troopBar .troop").forEach(el => (el.onclick = () => { Sound.sfx("click"); this.selected = el.dataset.t; this.hud(); }));
  }
  hudTick() {
    const left = Math.max(0, this.seconds - this.time), m = Math.floor(left / 60), s = Math.floor(left % 60);
    $("bTimer").textContent = this.started ? `${m}:${String(s).padStart(2, "0")}` : "Deploy to begin";
    const pct = Math.floor(this.destroyed / Math.max(this.total, 1) * 100);
    $("bPct").textContent = pct + "%";
    $("bStars").innerHTML = [0, 1, 2].map(i => `<span class="${i < this.stars ? "on" : ""}">★</span>`).join("");
    $("bLoot").innerHTML = `<b>🪙 ${fmt(this.loot.gold)}</b><b>🌾 ${fmt(this.loot.food)}</b>`;
  }

  async finish() {
    if (this.ended) return; this.ended = true;
    const report = {battle_id: this.data.battle_id, deployed: this.deployed, destruction: this.destroyed / Math.max(this.total, 1) * 100,
      palace_destroyed: this.palaceDown, loot: {gold: Math.floor(this.loot.gold), food: Math.floor(this.loot.food)}};
    try { const res = await api("battle/end", report); this.onEnd(res, report); }
    catch (e) { toast(e.message, "bad"); this.onEnd(null, report); }
  }

  dispose() {
    for (const tr of this.troops) this.view.scene.remove(tr.mesh);
    for (const s of this.shots) this.view.scene.remove(s.mesh);
    for (const f of this.fx) { if (f.el) f.el.remove(); else this.view.scene.remove(f.m); }
    this.barEls?.forEach(el => el.remove());
    this.view.scene.remove(this.zoneMesh);
    this.view.tick = null; this.view.overlayTick = null; this.view.onTap = this.view.onHold = null;
    for (const [, m] of this.view.models) this.view.layer.remove(m.group);
    this.view.models.clear(); this.view.wallKey = null; this.view.peopleSig = null;
  }
}
