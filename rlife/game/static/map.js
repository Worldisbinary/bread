// The world map: the river valley with every kingdom's capital. Used to choose which rival to raid.
import * as THREE from "three";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {LineSegments2} from "three/addons/lines/LineSegments2.js";
import {LineSegmentsGeometry} from "three/addons/lines/LineSegmentsGeometry.js";
import {LineMaterial} from "three/addons/lines/LineMaterial.js";
import {Stage, rng, fmt, $} from "./core.js";
import * as M from "./models.js";

const PALETTE = {sea: 0x2a6ea8, river: 0x3a8fd6, snow: 0xf3f6f9, mountain: 0x8e8577, hills: 0x96ab62, desert: 0xe3c27a,
  forest: 0x3f7a35, marsh: 0x5d8a58, plains: 0x86bd4f};

export class WorldMap {
  constructor() {
    this.scene = new THREE.Scene();
    const sky = document.createElement("canvas"); sky.width = 2; sky.height = 256; const c = sky.getContext("2d");
    const g = c.createLinearGradient(0, 0, 0, 256); g.addColorStop(0, "#5b9bd5"); g.addColorStop(0.6, "#bcdcf2"); g.addColorStop(1, "#f3e3c3");
    c.fillStyle = g; c.fillRect(0, 0, 2, 256);
    this.scene.background = new THREE.CanvasTexture(sky); this.scene.background.colorSpace = THREE.SRGBColorSpace;
    this.scene.fog = new THREE.Fog(0xcfe3f2, 140, 260);
    this.camera = new THREE.PerspectiveCamera(36, innerWidth / innerHeight, 0.5, 600); this.camera.position.set(0, 90, 80);
    this.controls = new OrbitControls(this.camera, Stage.renderer.domElement);
    Object.assign(this.controls, {enableDamping: true, dampingFactor: 0.08, maxPolarAngle: 1.2, minDistance: 15, maxDistance: 160, screenSpacePanning: false, enabled: false});
    this.controls.mouseButtons = {LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE};
    this.controls.touches = {ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE};
    this.scene.add(new THREE.HemisphereLight(0xcfe8ff, 0x5a4a2a, 0.9));
    const sun = new THREE.DirectionalLight(0xfff1d6, 2.3); sun.position.set(-40, 70, 30); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048); Object.assign(sun.shadow.camera, {left: -80, right: 80, top: 60, bottom: -60, near: 1, far: 200});
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.03; this.scene.add(sun);
    this.raycaster = new THREE.Raycaster(); this.labels = {};
    this.overlayRoot = document.createElement("div"); this.overlayRoot.className = "view-overlay"; $("labels").appendChild(this.overlayRoot);
  }

  build(terrain) {
    if (this.root) this.scene.remove(this.root);
    this.terrain = terrain; this.W = terrain.width; this.H = terrain.height;
    this.heights = new Float32Array(this.W * this.H);
    for (let i = 0; i < this.W * this.H; i++) {
      const b = terrain.biomes[terrain.biome[i]], e = terrain.elevation[i];
      this.heights[i] = b === "sea" ? -1.2 + e * 2 : b === "river" ? -0.35 : 0.15 + Math.max(0, e - 0.12) * 7.5;
    }
    this.root = new THREE.Group(); this.scene.add(this.root);
    this.ground(); this.water(); this.trees();
    this.castles = new THREE.Group(); this.root.add(this.castles);
  }
  pos(x, y, lift = 0) { return new THREE.Vector3(x - (this.W - 1) / 2, this.h(x, y) + lift, y - (this.H - 1) / 2); }
  h(x, y) {
    const W = this.W, H = this.H, cx = Math.max(0, Math.min(W - 1.001, x)), cy = Math.max(0, Math.min(H - 1.001, y));
    const x0 = Math.floor(cx), y0 = Math.floor(cy), fx = cx - x0, fy = cy - y0, hs = this.heights;
    const a = hs[y0 * W + x0], b = hs[y0 * W + x0 + 1], c = hs[(y0 + 1) * W + x0], d = hs[(y0 + 1) * W + x0 + 1];
    return Math.max(0, (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy);
  }
  biome(x, y) { const t = this.terrain; return t.biomes[t.biome[Math.round(y) * this.W + Math.round(x)]]; }
  ground() {
    const W = this.W, H = this.H, t = this.terrain, r = rng(9);
    let geo = new THREE.PlaneGeometry(W - 1, H - 1, W - 1, H - 1); geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position, colors = new Float32Array(pos.count * 3), col = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      pos.setY(i, this.heights[i] + (r() - 0.5) * 0.12);
      const b = t.biomes[t.biome[i]]; col.setHex(PALETTE[b]);
      if (b === "sea") col.lerp(new THREE.Color(0xd9c98f), Math.max(0, Math.min(1, (this.heights[i] + 0.4) * 1.4)));
      if (b === "river") col.setHex(0xc9b98a);
      if (b === "mountain" && this.heights[i] > 4.4) col.lerp(new THREE.Color(0xffffff), Math.min(1, (this.heights[i] - 4.4) * 0.8));
      col.offsetHSL(0, 0, (r() - 0.5) * 0.06); colors.set([col.r, col.g, col.b], i * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3)); geo = geo.toNonIndexed(); geo.computeVertexNormals();
    const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({vertexColors: true, flatShading: true, roughness: 0.95}));
    mesh.receiveShadow = true; this.root.add(mesh);
  }
  water() {
    const geo = new THREE.PlaneGeometry(this.W + 80, this.H + 80, 120, 80); geo.rotateX(-Math.PI / 2);
    const mat = new THREE.MeshStandardMaterial({color: 0x2f86d0, transparent: true, opacity: 0.82, roughness: 0.18, metalness: 0.15, flatShading: true});
    mat.onBeforeCompile = sh => {
      sh.uniforms.uTime = this.waterTime = {value: 0};
      sh.vertexShader = "uniform float uTime;\n" + sh.vertexShader.replace("#include <begin_vertex>",
        "#include <begin_vertex>\n transformed.y += sin(position.x*0.55+uTime*1.3)*0.06 + cos(position.z*0.7+uTime*1.1)*0.05;");
    };
    const mesh = new THREE.Mesh(geo, mat); mesh.position.y = -0.08; this.root.add(mesh);
  }
  trees() {
    const r = rng(21), broad = [], pine = [];
    for (let y = 0; y < this.H; y++) for (let x = 0; x < this.W; x++) {
      const b = this.biome(x, y);
      if (b === "forest") for (let i = 0; i < 2; i++) (r() < 0.65 ? broad : pine).push([x + (r() - 0.5) * 0.9, y + (r() - 0.5) * 0.9]);
      else if (b === "hills" && r() < 0.3) pine.push([x, y]); else if (b === "plains" && r() < 0.02) broad.push([x, y]);
    }
    const place = (geo, list, lift, tint) => {
      const m = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({flatShading: true, roughness: 0.9}), list.length), o = new THREE.Object3D(), c = new THREE.Color();
      list.forEach(([x, y], i) => { const s = 0.75 + r() * 0.6; o.position.copy(this.pos(x, y, lift * s)); o.rotation.y = r() * 6; o.scale.setScalar(s); o.updateMatrix(); m.setMatrixAt(i, o.matrix); c.setHex(tint[Math.floor(r() * tint.length)]); m.setColorAt(i, c); });
      m.castShadow = true; this.root.add(m);
    };
    place(new THREE.IcosahedronGeometry(0.42, 0), broad, 0.62, [0x4f9a3f, 0x3f8a36, 0x67ad4a]);
    place(new THREE.ConeGeometry(0.34, 1.0, 6), pine, 0.55, [0x2f6e3a, 0x2d6332]);
  }

  /** Castles, borders and labels for the current state; rivals gives palace levels and loot. */
  show_state(state, rivals) {
    this.state = state; this.rivals = new Map(rivals.map(r => [r.id, r]));
    this.castles.clear();
    const th = M.THEMES[state.preset] || M.THEMES.ganges;
    for (const k of state.kingdoms) {
      const level = k.id === state.player ? 3 : (this.rivals.get(k.id)?.palace || 1);
      const g = M.building("palace", level, th, k.color, k.id);
      g.scale.setScalar(0.9); g.position.copy(this.pos(k.capital[0], k.capital[1]));
      g.traverse(o => (o.userData.kid = k.id));
      if (!k.alive) g.traverse(o => { if (o.isMesh) o.material = M.mat(0x5d5d5d); });
      this.castles.add(g);
    }
    this.borders();
    for (const el of Object.values(this.labels)) el.remove(); this.labels = {};
    for (const k of state.kingdoms) {
      const el = document.createElement("div"); el.className = "klabel" + (k.id === state.player ? " me" : "");
      const r = this.rivals.get(k.id);
      el.innerHTML = `<b style="color:${k.color}">${k.name}${k.id === state.player ? " (you)" : ""}</b>` +
        (r ? `<small>Palace ${r.palace} · 🪙 ${fmt(r.loot.gold)} · 🌾 ${fmt(r.loot.food)}</small>` : `<small>👥 ${fmt(k.population)}</small>`);
      el.onclick = () => this.onPick?.(k.id);
      this.overlayRoot.appendChild(el); this.labels[k.id] = el;
    }
  }
  borders() {
    if (this.borderMesh) this.root.remove(this.borderMesh);
    const own = this.state.owner, W = this.W, H = this.H, pts = [], cols = [], col = new THREE.Color();
    const seg = (x1, y1, x2, y2, k) => { const a = this.pos(x1, y1, 0.12), b = this.pos(x2, y2, 0.12); pts.push(a.x, a.y, a.z, b.x, b.y, b.z); col.set(this.state.kingdoms[k].color); cols.push(col.r, col.g, col.b, col.r, col.g, col.b); };
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
  }
  focus(id, dist = 40) { const k = this.state.kingdoms[id]; if (k) this.flyTo = {target: this.pos(k.capital[0], k.capital[1]), dist}; }
  onTap(ndc) {
    this.raycaster.setFromCamera(ndc, this.camera);
    const hit = this.raycaster.intersectObjects(this.castles.children, true)[0];
    if (hit && hit.object.userData.kid !== undefined) this.onPick?.(hit.object.userData.kid);
  }
  resize() { this.borderMat?.resolution.set(innerWidth, innerHeight); }
  update(dt, t) {
    if (this.waterTime) this.waterTime.value = t;
    if (this.flyTo) {
      const f = this.flyTo; this.controls.target.lerp(f.target, 0.08);
      const dir = this.camera.position.clone().sub(this.controls.target).normalize();
      this.camera.position.lerp(this.controls.target.clone().add(dir.multiplyScalar(f.dist)), 0.06);
      if (this.controls.target.distanceTo(f.target) < 0.1) this.flyTo = null;
    }
    this.castles?.children.forEach((g, i) => g.traverse(o => { if (o.userData.flag) o.rotation.y = Math.sin(t * 3 + i) * 0.3; }));
  }
  overlay() {
    if (!this.state) return;
    for (const k of this.state.kingdoms) {
      const el = this.labels[k.id]; if (!el) continue;
      const s = Stage.project(this.pos(k.capital[0], k.capital[1], 5.2), this.camera);
      el.style.display = s.visible ? "" : "none"; el.style.transform = `translate(${s.x}px, ${s.y}px)`;
    }
  }
  show() { this.overlayRoot.style.display = ""; }
  hide() { this.overlayRoot.style.display = "none"; }
}
