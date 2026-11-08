// The town view: one town on its grid, seen from a fixed isometric camera. Used for your own town
// (build, upgrade, collect, watch your people) and, by battle.js, for the rival town you raid.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {RoomEnvironment} from "three/addons/environments/RoomEnvironment.js";
import {Stage, rng, clamp, $} from "./core.js";
import * as M from "./models.js";
import {astar, rectDist} from "./path.js";

const ICON = {food: "🌾", gold: "🪙"};

export class TownView {
  constructor({grid = 44, name = "town"} = {}) {
    this.grid = grid; this.name = name;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 1, 500);
    this.camera.position.set(21, 31, 21);
    this.controls = new OrbitControls(this.camera, Stage.renderer.domElement);
    Object.assign(this.controls, {enableRotate: false, enableDamping: true, dampingFactor: 0.12, screenSpacePanning: false,
      minDistance: 16, maxDistance: 92, enabled: false, zoomSpeed: 1.1});
    this.controls.mouseButtons = {LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN};
    this.controls.touches = {ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN};
    this.overlayRoot = document.createElement("div"); this.overlayRoot.className = "view-overlay"; $("labels").appendChild(this.overlayRoot);
    this.models = new Map(); this.walkers = []; this.bubbles = new Map(); this.timers = new Map();
    this.raycaster = new THREE.Raycaster(); this.groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    this.lights();
    this.layer = new THREE.Group(); this.scene.add(this.layer);
    this.people = new THREE.Group(); this.scene.add(this.people);
  }

  toWorld(x, y, lift = 0) { return new THREE.Vector3(x - this.grid / 2, lift, y - this.grid / 2); }
  center(b, lift = 0) { return this.toWorld(b.x + b.size / 2, b.y + b.size / 2, lift); }

  lights() {
    const s = this.scene;
    const sky = document.createElement("canvas"); sky.width = 2; sky.height = 256; const c = sky.getContext("2d");
    const g = c.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, "#7fb6e6"); g.addColorStop(0.55, "#cfe6f5"); g.addColorStop(1, "#f6ead2");
    c.fillStyle = g; c.fillRect(0, 0, 2, 256);
    s.background = new THREE.CanvasTexture(sky); s.background.colorSpace = THREE.SRGBColorSpace;
    s.fog = new THREE.Fog(0xdfeaf0, 70, 150);
    const pmrem = new THREE.PMREMGenerator(Stage.renderer);
    s.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    s.add(new THREE.HemisphereLight(0xe3f1ff, 0x5a4a2a, 0.75));
    const sun = this.sun = new THREE.DirectionalLight(0xfff0d8, 2.3);
    sun.position.set(-26, 44, 18); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, {left: -34, right: 34, top: 34, bottom: -34, near: 1, far: 120});
    sun.shadow.bias = -0.0005; sun.shadow.normalBias = 0.04;
    s.add(sun); s.add(sun.target);
  }

  setTheme(preset, color) {
    if (this.themeKey === preset + color) return;
    this.themeKey = preset + color; this.preset = preset; this.color = color;
    this.theme = M.THEMES[preset] || M.THEMES.ganges;
    if (this.land) this.scene.remove(this.land);
    this.land = new THREE.Group(); this.scene.add(this.land);
    const th = this.theme, r = rng(preset.length * 977);
    // grass with painted variation
    const cv = document.createElement("canvas"); cv.width = cv.height = 512; const c = cv.getContext("2d");
    const base = new THREE.Color(th.ground); c.fillStyle = "#" + base.getHexString(); c.fillRect(0, 0, 512, 512);
    for (let i = 0; i < 2600; i++) {
      const col = base.clone().offsetHSL((r() - 0.5) * 0.04, (r() - 0.5) * 0.12, (r() - 0.5) * 0.12);
      c.fillStyle = "#" + col.getHexString(); c.globalAlpha = 0.35 + r() * 0.4;
      const x = r() * 512, y = r() * 512, s = 2 + r() * 10; c.beginPath(); c.ellipse(x, y, s, s * (0.4 + r() * 0.6), r() * 3, 0, 7); c.fill();
    }
    c.globalAlpha = 0.5;
    for (let i = 0; i < 3000; i++) { c.fillStyle = r() < 0.5 ? "#ffffff22" : "#00000018"; c.fillRect(r() * 512, r() * 512, 1, 3 + r() * 4); }
    const tex = new THREE.CanvasTexture(cv); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(14, 14); tex.colorSpace = THREE.SRGBColorSpace;
    tex.anisotropy = 8;
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(220, 220), new THREE.MeshStandardMaterial({map: tex, roughness: 1, envMapIntensity: 0.2}));
    ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; this.land.add(ground);
    // a raised, slightly lighter town plateau with a soft edge
    const half = this.grid / 2 + 1.5;
    const plateau = new THREE.Mesh(M.box(half * 2, 0.4, half * 2, 0.35), new THREE.MeshStandardMaterial({color: base.clone().offsetHSL(0, -0.02, 0.02), roughness: 1, envMapIntensity: 0.2}));
    plateau.position.y = -0.19; plateau.receiveShadow = true; this.land.add(plateau);
    // a river along one side, with a bridge
    const river = new THREE.Mesh(new THREE.PlaneGeometry(220, 9, 80, 4), new THREE.MeshStandardMaterial({color: 0x3c8fd0, roughness: 0.15, metalness: 0.1, transparent: true, opacity: 0.88}));
    river.material.onBeforeCompile = sh => {
      sh.uniforms.uTime = this.waterTime = {value: 0};
      sh.vertexShader = "uniform float uTime;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        "#include <begin_vertex>\n transformed.z += sin(position.x*0.6+uTime*1.5)*0.05 + cos(position.y*1.4+uTime)*0.04;");
    };
    river.rotation.x = -Math.PI / 2; river.position.set(0, 0.02, -half - 9); this.land.add(river);
    for (const s of [-1, 1]) {
      const bank = new THREE.Mesh(M.box(220, 0.3, 1.2, 0.1), M.mat(new THREE.Color(th.dirt).getHex()));
      bank.position.set(0, 0.05, -half - 9 + s * 4.8); bank.receiveShadow = true; this.land.add(bank);
    }
    const bridge = new THREE.Group(); bridge.position.set(6, 0.25, -half - 9); this.land.add(bridge);
    for (let i = 0; i < 9; i++) { const p = new THREE.Mesh(M.box(2.4, 0.12, 1.0, 0.02), M.mat(0x8a5a33)); p.position.set(0, 0.2, -4.4 + i * 1.1); p.castShadow = p.receiveShadow = true; bridge.add(p); }
    for (const x of [-1.2, 1.2]) { const rail = new THREE.Mesh(M.box(0.12, 0.4, 10, 0.03), M.mat(0x6b4a2b)); rail.position.set(x, 0.45, 0); bridge.add(rail); }
    // forest, rocks and hills around the town
    const trees = [], pines = [], rocks = [], bushes = [];
    for (let i = 0; i < 2600; i++) {
      const a = r() * Math.PI * 2, dist = half * 1.05 + 1 + Math.pow(r(), 1.6) * 70, x = Math.cos(a) * dist, z = Math.sin(a) * dist;
      if (Math.abs(x) < half + 2.5 && Math.abs(z) < half + 2.5) continue;
      if (Math.abs(z + half + 9) < 6.5) continue;
      const k = r(); (k < 0.45 ? trees : k < 0.75 ? pines : k < 0.88 ? bushes : rocks).push([x, z]);
    }
    const place = (geo, colors, list, lift, scale) => {
      const m = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({roughness: 0.9}), list.length), o = new THREE.Object3D(), col = new THREE.Color();
      list.forEach(([x, z], i) => { const s = scale * (0.7 + r() * 0.7); o.position.set(x, lift * s, z); o.rotation.set(0, r() * 6.3, 0); o.scale.setScalar(s); o.updateMatrix(); m.setMatrixAt(i, o.matrix); col.setHex(colors[Math.floor(r() * colors.length)]); m.setColorAt(i, col); });
      m.castShadow = true; m.receiveShadow = true; this.land.add(m);
    };
    const leaf = preset === "nile" || preset === "mesopotamia" ? [0x6f9a3a, 0x7fa848, 0x5e8a34] : [0x4f9a3f, 0x3f8a36, 0x67ad4a, 0x7cb342];
    place(new THREE.IcosahedronGeometry(1.1, 1), leaf, trees, 1.9, 1);
    place(new THREE.ConeGeometry(0.9, 2.6, 7), [0x2f6e3a, 0x2d6332, 0x3c7d45], pines, 1.6, 1);
    place(new THREE.IcosahedronGeometry(0.6, 0), [0x5a9a3a, 0x6aa84a], bushes, 0.35, 1);
    place(new THREE.DodecahedronGeometry(0.8, 0), [0x8d8579, 0x7a7266, 0xa39a8d], rocks, 0.3, 1);
    const trunks = trees.concat(pines);
    place(new THREE.CylinderGeometry(0.16, 0.22, 1.4, 6), [0x6b4a2b], trunks, 0.5, 1);
    for (let i = 0; i < 9; i++) {
      const a = i / 9 * Math.PI * 2, d = 95 + r() * 20;
      const hill = new THREE.Mesh(new THREE.IcosahedronGeometry(18 + r() * 14, 1), M.mat(base.clone().offsetHSL(0, -0.1, -0.08).getHex(), {flatShading: true}));
      hill.position.set(Math.cos(a) * d, -6, Math.sin(a) * d); hill.scale.y = 0.45; this.land.add(hill);
    }
    // grid lines for building mode
    const pts = [], h2 = this.grid / 2;
    for (let i = 0; i <= this.grid; i++) { pts.push(-h2 + i, 0.03, -h2, -h2 + i, 0.03, h2, -h2, 0.03, -h2 + i, h2, 0.03, -h2 + i); }
    const gg = new THREE.BufferGeometry(); gg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    this.gridLines = new THREE.LineSegments(gg, new THREE.LineBasicMaterial({color: 0xffffff, transparent: true, opacity: 0.18}));
    this.gridLines.visible = false; this.land.add(this.gridLines);
  }

  /** Paint worn earth under and around buildings so the town reads as lived-in. */
  paths(buildings) {
    const px = 16, size = this.grid * px, cv = this.pathCanvas || (this.pathCanvas = document.createElement("canvas"));
    cv.width = cv.height = size; const c = cv.getContext("2d"); c.clearRect(0, 0, size, size);
    const dirt = "#" + new THREE.Color(this.theme.dirt).getHexString();
    c.fillStyle = dirt;
    for (const b of buildings) {
      if (b.type === "wall") continue;
      const m = b.type === "farm" ? 0.1 : 0.45, r = 10;
      c.globalAlpha = 0.85; c.beginPath(); c.roundRect((b.x - m) * px, (b.y - m) * px, (b.size + 2 * m) * px, (b.size + 2 * m) * px, r); c.fill();
    }
    const palace = buildings.find(b => b.type === "palace");
    if (palace) { // roads from the palace out to each building
      c.strokeStyle = dirt; c.lineCap = "round"; c.globalAlpha = 0.7; c.lineWidth = px * 0.9;
      const cx = (palace.x + 2) * px, cy = (palace.y + 2) * px;
      for (const b of buildings) {
        if (b.type === "wall" || b === palace) continue;
        c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx, (b.y + b.size / 2) * px); c.lineTo((b.x + b.size / 2) * px, (b.y + b.size / 2) * px); c.stroke();
      }
    }
    if (!this.pathMesh) {
      this.pathTex = new THREE.CanvasTexture(cv); this.pathTex.colorSpace = THREE.SRGBColorSpace;
      this.pathMesh = new THREE.Mesh(new THREE.PlaneGeometry(this.grid, this.grid), new THREE.MeshStandardMaterial({map: this.pathTex, transparent: true, roughness: 1, depthWrite: false, envMapIntensity: 0.2}));
      this.pathMesh.rotation.x = -Math.PI / 2; this.pathMesh.position.y = 0.015; this.pathMesh.receiveShadow = true; this.scene.add(this.pathMesh);
    }
    this.pathTex.needsUpdate = true;
  }

  /** Bring the scene in line with a list of buildings (from the server or a battle layout). */
  sync(buildings, {villagers = true, army = null} = {}) {
    this.buildings = buildings;
    const seen = new Set();
    for (const b of buildings) {
      if (b.type === "wall") continue;
      seen.add(b.id);
      const key = [b.type, b.level, b.target, b.x, b.y].join("|"), had = this.models.get(b.id);
      if (had && had.key === key) { had.b = b; continue; }
      if (had) this.layer.remove(had.group);
      const group = new THREE.Group(); group.position.copy(this.center(b));
      let model = null;
      if (b.level > 0) { model = M.building(b.type, b.level, this.theme, this.color, b.id); group.add(model); }
      if (b.target) group.add(M.scaffold(b.size, b.level > 0 ? 2.2 : 1.2));
      group.traverse(o => (o.userData.bid = b.id));
      group.userData.bid = b.id;
      this.layer.add(group);
      this.models.set(b.id, {key, group, model, b});
    }
    for (const [id, m] of this.models) if (!seen.has(id)) { this.layer.remove(m.group); this.models.delete(id); }
    this.walls = buildings.filter(b => b.type === "wall");
    const wkey = this.walls.map(w => `${w.x},${w.y},${w.level}`).join(";");
    if (wkey !== this.wallKey) {
      this.wallKey = wkey; if (this.wallObj) this.layer.remove(this.wallObj);
      this.wallObj = M.wallMesh(this.walls, this.theme, (x, y) => this.toWorld(x, y)); this.layer.add(this.wallObj);
    }
    this.occupancy();
    this.paths(buildings);
    if (villagers) this.populate(army);
  }

  occupancy() {
    const n = this.grid, occ = this.occ = new Int32Array(n * n).fill(-1);
    for (const b of this.buildings) for (let dy = 0; dy < b.size; dy++) for (let dx = 0; dx < b.size; dx++) {
      const x = b.x + dx, y = b.y + dy; if (x >= 0 && y >= 0 && x < n && y < n) occ[y * n + x] = b.id;
    }
  }

  // ---------------------------------------------------------------- townspeople
  populate(army) {
    const sig = this.buildings.filter(b => b.level > 0 && b.type !== "wall").map(b => b.type + b.id).join() + JSON.stringify(army || {});
    if (sig === this.peopleSig) return; this.peopleSig = sig;
    this.people.clear(); this.walkers = [];
    const r = rng(this.buildings.length * 31 + 7), skinOf = () => Math.floor(r() * 5);
    const spawn = (type, home, opts = {}) => {
      const u = M.unit(type, this.color, {skin: skinOf(), scale: opts.scale ?? 1});
      const spot = this.freeNear(home, r, 2.5) || [home.x - 1, home.y - 1];
      u.position.copy(this.toWorld(spot[0] + 0.5, spot[1] + 0.5));
      this.people.add(u);
      this.walkers.push({u, home, path: null, wait: r() * 3, speed: opts.speed ?? 0.9, idle: !!opts.idle, roam: opts.roam ?? 3});
    };
    for (const b of this.buildings) {
      if (!b.level) continue;
      if (b.type === "house") for (let i = 0; i < 2; i++) spawn(["merchant", "farmer", "scholar", "merchant"][Math.floor(r() * 4)], b);
      if (b.type === "farm") spawn("farmer", b, {roam: 1.5});
      if (b.type === "mine") spawn("miner", b, {roam: 1.5});
      if (b.type === "temple") { spawn("priest", b, {roam: 1.5}); spawn("scholar", b, {roam: 2}); }
      if (b.type === "palace") { spawn("king", b, {speed: 0.5, roam: 2}); spawn("guard", b, {roam: 2}); }
      if (b.type === "barracks") spawn("spearman", b, {roam: 2});
    }
    if (army) { // the army waits around its camps
      const camps = this.buildings.filter(b => b.type === "camp" && b.level);
      const list = Object.entries(army).flatMap(([t, n]) => Array(Math.min(n, t === "elephant" ? 2 : 8)).fill(t)).slice(0, 26);
      list.forEach((t, i) => {
        const camp = camps[i % Math.max(camps.length, 1)]; if (!camp) return;
        const u = M.unit(t, this.color, {scale: t === "elephant" ? 0.9 : 1}), a = (i / list.length) * Math.PI * 2 * 1.7 + i, rad = 0.9 + (i % 3) * 0.35;
        u.position.copy(this.center(camp)).add(new THREE.Vector3(Math.cos(a) * rad, 0, Math.sin(a) * rad));
        u.lookAt(this.center(camp)); this.people.add(u);
        this.walkers.push({u, home: camp, idle: true, wait: 0});
      });
    }
  }

  freeNear(b, r, radius) {
    for (let k = 0; k < 30; k++) {
      const x = Math.floor(b.x - radius + r() * (b.size + 2 * radius)), y = Math.floor(b.y - radius + r() * (b.size + 2 * radius));
      if (x < 0 || y < 0 || x >= this.grid || y >= this.grid) continue;
      if (this.occ[y * this.grid + x] === -1) return [x, y];
    }
    return null;
  }

  walk(w, dt, t) {
    if (w.idle) { w.u.position.y = Math.abs(Math.sin(t * 2 + w.u.id)) * 0.02; M.animate(w.u, t, false, false); return; }
    if (w.wait > 0) { w.wait -= dt; M.animate(w.u, t, false, false); return; }
    if (!w.path || !w.path.length) {
      const goal = this.freeNear(w.home, Math.random, w.roam);
      if (!goal) { w.wait = 2; return; }
      const n = this.grid, sx = Math.floor(w.u.position.x + n / 2), sy = Math.floor(w.u.position.z + n / 2);
      w.path = astar(n, sx, sy, (x, y) => x === goal[0] && y === goal[1], (x, y) => Math.hypot(x - goal[0], y - goal[1]),
        i => (this.occ[i] === -1 ? 1 : Infinity), 1500) || [];
      if (!w.path.length) { w.wait = 1 + Math.random() * 2; return; }
    }
    const [tx, ty] = w.path[0], target = this.toWorld(tx + 0.5, ty + 0.5), d = target.clone().sub(w.u.position); d.y = 0;
    const dist = d.length();
    if (dist < 0.06) { w.path.shift(); if (!w.path.length) w.wait = 1 + Math.random() * 4; return; }
    d.multiplyScalar(Math.min(1, (w.speed * dt) / dist)); w.u.position.add(d);
    w.u.rotation.y = Math.atan2(d.x, d.z);
    M.animate(w.u, t, true, false, w.speed);
  }

  // ---------------------------------------------------------------- picking and placing
  rayTo(ndc) { this.raycaster.setFromCamera(ndc, this.camera); return this.raycaster; }
  pickBuilding(ndc) {
    const hits = this.rayTo(ndc).intersectObjects(this.layer.children, true);
    for (const h of hits) { let o = h.object; while (o && o.userData.bid === undefined) o = o.parent; if (o) return o.userData.bid; }
    const tile = this.tileAt(ndc); if (!tile) return null; // walls and footprints by tile
    const id = this.occ?.[tile[1] * this.grid + tile[0]]; return id >= 0 ? id : null;
  }
  tileAt(ndc, size = 1) {
    const p = new THREE.Vector3(); if (!this.rayTo(ndc).ray.intersectPlane(this.groundPlane, p)) return null;
    const x = Math.floor(p.x + this.grid / 2 - (size - 1) / 2), y = Math.floor(p.z + this.grid / 2 - (size - 1) / 2);
    return [x, y, p.x + this.grid / 2, p.z + this.grid / 2];
  }
  fits(type, size, x, y, ignore = null) {
    if (x < 1 || y < 1 || x + size > this.grid - 1 || y + size > this.grid - 1) return false;
    for (let dy = 0; dy < size; dy++) for (let dx = 0; dx < size; dx++) {
      const id = this.occ[(y + dy) * this.grid + x + dx]; if (id !== -1 && id !== ignore) return false;
    }
    return true;
  }
  startGhost(type, size, level = 1, ignore = null) {
    this.endGhost();
    const g = this.ghost = new THREE.Group();
    const pad = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({color: 0x3ddc84, transparent: true, opacity: 0.45, depthWrite: false}));
    pad.rotation.x = -Math.PI / 2; pad.position.y = 0.05; g.add(pad); g.userData.pad = pad;
    if (type !== "wall") g.add(M.building(type, level, this.theme, this.color));
    else g.add(new THREE.Mesh(M.box(0.6, 0.9, 0.6, 0.05), M.mat(this.theme.stone)));
    g.userData = {...g.userData, type, size, ignore}; this.scene.add(g); this.gridLines.visible = true;
    const c = this.controls.target; this.moveGhost(Math.round(c.x + this.grid / 2 - size / 2), Math.round(c.z + this.grid / 2 - size / 2));
  }
  moveGhost(x, y) {
    const g = this.ghost; if (!g) return;
    const {size, type, ignore} = g.userData;
    x = clamp(x, 1, this.grid - 1 - size); y = clamp(y, 1, this.grid - 1 - size);
    g.userData.x = x; g.userData.y = y; g.userData.ok = this.fits(type, size, x, y, ignore);
    g.position.copy(this.toWorld(x + size / 2, y + size / 2, 0.15));
    g.userData.pad.material.color.setHex(g.userData.ok ? 0x3ddc84 : 0xff4a3d);
  }
  endGhost() { if (this.ghost) this.scene.remove(this.ghost); this.ghost = null; if (this.gridLines) this.gridLines.visible = false; }

  select(id) {
    if (this.ring) { this.scene.remove(this.ring); this.ring = null; }
    this.selected = id;
    const m = this.models.get(id) || null, b = m?.b || this.walls?.find(w => w.id === id);
    if (!b) return;
    this.ring = new THREE.Mesh(new THREE.RingGeometry(b.size * 0.62, b.size * 0.7, 40), new THREE.MeshBasicMaterial({color: 0xffd34d, transparent: true, opacity: 0.9, depthWrite: false}));
    this.ring.rotation.x = -Math.PI / 2; this.ring.position.copy(this.center(b, 0.06)); this.scene.add(this.ring);
    if (m) m.bounce = 0.35;
  }

  focus(x, y) { const p = this.toWorld(x, y); this.panTo = p; }

  // ---------------------------------------------------------------- per frame
  update(dt, t) {
    if (this.waterTime) this.waterTime.value = t;
    const tg = this.controls.target, lim = this.grid / 2 + 4;
    if (this.panTo) { tg.lerp(this.panTo, 0.12); if (tg.distanceTo(this.panTo) < 0.05) this.panTo = null; }
    const before = tg.clone(); tg.x = clamp(tg.x, -lim, lim); tg.z = clamp(tg.z, -lim, lim); tg.y = 0;
    this.camera.position.add(tg.clone().sub(before));
    for (const [, m] of this.models) {
      if (m.bounce > 0) { m.bounce = Math.max(0, m.bounce - dt); m.group.scale.setScalar(1 + Math.sin(m.bounce * 18) * m.bounce * 0.15); }
      m.group.traverse(o => {
        const d = o.userData;
        if (d.flag) o.rotation.y = Math.sin(t * 3 + m.b.id) * 0.35;
        if (d.spinZ) o.rotation.z += dt * d.spinZ;
        if (d.spin) o.rotation.y += dt * 1.5;
        if (d.flicker) o.scale.set(1 + Math.sin(t * 17 + m.b.id) * 0.08, 1 + Math.sin(t * 23) * 0.15, 1 + Math.cos(t * 19) * 0.08);
      });
    }
    if (this.ring) this.ring.material.opacity = 0.6 + Math.sin(t * 5) * 0.3;
    for (const w of this.walkers) this.walk(w, dt, t);
    this.tick?.(dt, t);
  }

  // ---------------------------------------------------------------- HTML overlays (bubbles, timers)
  setBubbles(list, onTap) {
    const want = new Set(list.map(b => b.id));
    for (const [id, el] of this.bubbles) if (!want.has(id)) { el.remove(); this.bubbles.delete(id); }
    for (const b of list) {
      let el = this.bubbles.get(b.id);
      if (!el) { el = document.createElement("button"); el.className = "bubble"; el.onclick = e => { e.stopPropagation(); onTap(b.id); }; this.overlayRoot.appendChild(el); this.bubbles.set(b.id, el); }
      el.innerHTML = `<span>${ICON[b.res]}</span>`; el.classList.toggle("full", b.full);
    }
  }
  setTimers(list) {
    const want = new Set(list.map(b => b.id));
    for (const [id, el] of this.timers) if (!want.has(id)) { el.remove(); this.timers.delete(id); }
    for (const b of list) {
      let el = this.timers.get(b.id);
      if (!el) { el = document.createElement("div"); el.className = "timer"; el.innerHTML = "<i></i><b></b>"; this.overlayRoot.appendChild(el); this.timers.set(b.id, el); }
      el.dataset.until = b.until; el.dataset.total = b.total;
    }
  }
  overlay() {
    const now = performance.now() / 1000;
    for (const [id, el] of this.bubbles) {
      const m = this.models.get(id); if (!m) continue;
      const s = Stage.project(this.center(m.b, 3.0 + Math.sin(now * 3 + id) * 0.12), this.camera);
      el.style.display = s.visible ? "" : "none"; el.style.transform = `translate(${s.x}px, ${s.y}px)`;
    }
    for (const [id, el] of this.timers) {
      const m = this.models.get(id); if (!m) continue;
      const s = Stage.project(this.center(m.b, 2.6), this.camera), left = Math.max(0, +el.dataset.until - now);
      el.style.display = s.visible ? "" : "none"; el.style.transform = `translate(${s.x}px, ${s.y}px)`;
      el.firstChild.style.width = (100 * (1 - left / Math.max(+el.dataset.total, 1))) + "%";
      el.lastChild.textContent = left > 60 ? `${Math.floor(left / 60)}m ${Math.ceil(left % 60)}s` : `${Math.ceil(left)}s`;
    }
    this.overlayTick?.();
  }
  show() { this.overlayRoot.style.display = ""; }
  hide() { this.overlayRoot.style.display = "none"; }
}
