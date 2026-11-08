// Procedural low-poly models: every building at every level in six regional styles, troops, townspeople,
// scaffolding and rubble. Static parts of a model are merged into one mesh ("baked") so a whole town
// renders in a few hundred draw calls; moving parts (flags, windmills, turrets, catapult arms, fires)
// stay separate and are animated through userData.
import * as THREE from "three";
import {RoundedBoxGeometry} from "three/addons/geometries/RoundedBoxGeometry.js";
import {mergeGeometries} from "three/addons/utils/BufferGeometryUtils.js";

export const THEMES = {
  nile: {wall: 0xe8d3a6, trim: 0xb7894c, roof: 0x3d6db4, style: "flat", accent: 0x2a5db0, ground: 0x9fbf63, dirt: 0xcdb27c, stone: 0xd8c49b, field: 0xc9b25a},
  mesopotamia: {wall: 0xd2a878, trim: 0x93643c, roof: 0x2f7fbe, style: "flat", accent: 0x2d7fbf, ground: 0xa3b664, dirt: 0xc9ab78, stone: 0xc9b08c, field: 0xcfb45e},
  indus: {wall: 0xc4744c, trim: 0x8c4a2e, roof: 0x8c4a2e, style: "flat", accent: 0xe0b040, ground: 0x98bd5c, dirt: 0xc4a274, stone: 0xbfa58a, field: 0xd2b45a},
  ganges: {wall: 0xf1e5cd, trim: 0xb5532a, roof: 0xb5532a, style: "gable", accent: 0xe0882b, ground: 0x7cb64d, dirt: 0xb99a6a, stone: 0xd0c3a8, field: 0xc8c050},
  yellow_river: {wall: 0xe3d5b4, trim: 0xa83224, roof: 0x3d5a50, style: "pagoda", accent: 0xc23b22, ground: 0x9cbc58, dirt: 0xc9b07a, stone: 0xc6bba3, field: 0xd6c25c},
  mediterranean: {wall: 0xf5f2ea, trim: 0xbfae8e, roof: 0xc0662f, style: "gable", accent: 0x2f6db5, ground: 0x8cbd54, dirt: 0xc2a576, stone: 0xe2ddd0, field: 0xb9bf55},
};

const BAKED = new THREE.MeshStandardMaterial({vertexColors: true, roughness: 0.82, metalness: 0, envMapIntensity: 0.35});
const mats = {};
export function mat(color, opts = {}) {
  const key = color + JSON.stringify(opts);
  return mats[key] || (mats[key] = new THREE.MeshStandardMaterial({color, roughness: 0.82, metalness: 0, envMapIntensity: opts.metalness ? 1 : 0.35, ...opts}));
}
const GOLD = () => mat(0xf2c14e, {metalness: 0.75, roughness: 0.3});
const DARK = () => mat(0x2b211a);
const WOOD = () => mat(0x8a5a33);
const WOOD_LIGHT = () => mat(0xa8784a);
const IRON = () => mat(0x5c6066, {metalness: 0.5, roughness: 0.45});
const SKIN = [0xf1c27d, 0xe0ac69, 0xc68642, 0x8d5524, 0xd9a066];

const geos = {};
const cached = (key, make) => geos[key] || (geos[key] = make());
export const box = (w, h, d, r = 0.05) => cached(`b${w},${h},${d},${r}`, () => r ? new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 2.1, h / 2.1, d / 2.1)) : new THREE.BoxGeometry(w, h, d));
export const cyl = (rt, rb, h, s = 12) => cached(`c${rt},${rb},${h},${s}`, () => new THREE.CylinderGeometry(rt, rb, h, s));
export const cone = (r, h, s = 12) => cached(`k${r},${h},${s}`, () => new THREE.ConeGeometry(r, h, s));
export const sph = (r, w = 12, h = 9) => cached(`s${r},${w},${h}`, () => new THREE.SphereGeometry(r, w, h));
const dome = r => cached(`d${r}`, () => new THREE.SphereGeometry(r, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2));
const torus = (r, t, arc) => cached(`t${r},${t},${arc}`, () => new THREE.TorusGeometry(r, t, 6, 16, arc));
const gable = (len, width, h) => cached(`g${len},${width},${h}`, () => {
  const s = new THREE.Shape(); s.moveTo(-width / 2, 0); s.lineTo(width / 2, 0); s.lineTo(0, h); s.closePath();
  const g = new THREE.ExtrudeGeometry(s, {depth: len, bevelEnabled: false}); g.translate(0, 0, -len / 2); g.rotateY(Math.PI / 2); return g;
});

function add(parent, geometry, material, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0) {
  const m = new THREE.Mesh(geometry, material); m.position.set(x, y, z); m.rotation.set(rx, ry, rz);
  m.castShadow = true; m.receiveShadow = true; parent.add(m); return m;
}
function live(parent, x = 0, y = 0, z = 0) { const g = new THREE.Group(); g.position.set(x, y, z); g.userData.live = true; parent.add(g); return g; }

/** Merge every static, non-metal, non-glowing mesh under root into one vertex-coloured mesh. */
export function bake(root) {
  root.updateMatrixWorld(true);
  const inv = root.matrixWorld.clone().invert(), parts = [], gone = [];
  root.traverse(o => {
    if (!o.isMesh) return;
    for (let p = o; p && p !== root; p = p.parent) if (p.userData.live) return;
    const m = o.material;
    if (m.metalness > 0.3 || m.transparent || (m.emissive && m.emissive.getHex() !== 0) || m.vertexColors) return;
    const g = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal") g.deleteAttribute(k);
    g.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inv, o.matrixWorld));
    const n = g.attributes.position.count, col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) col.set([m.color.r, m.color.g, m.color.b], i * 3);
    g.setAttribute("color", new THREE.BufferAttribute(col, 3));
    parts.push(g); gone.push(o);
  });
  if (parts.length) {
    gone.forEach(o => o.parent.remove(o));
    const merged = new THREE.Mesh(mergeGeometries(parts), BAKED);
    merged.castShadow = merged.receiveShadow = true; root.add(merged);
  }
  return root;
}

function roof(g, th, w, d, y, color = th.roof, scale = 1) {
  if (th.style === "flat") {
    add(g, box(w + 0.12, 0.12, d + 0.12, 0.03), mat(th.trim), 0, y + 0.06, 0);
    for (const s of [-1, 1]) {
      add(g, box(w + 0.12, 0.16, 0.1, 0.02), mat(th.wall), 0, y + 0.2, s * (d / 2 + 0.01));
      add(g, box(0.1, 0.16, d + 0.12, 0.02), mat(th.wall), s * (w / 2 + 0.01), y + 0.2, 0);
    }
    return y + 0.28;
  }
  if (th.style === "pagoda") {
    add(g, box(w + 0.5, 0.08, d + 0.5, 0.02), mat(color), 0, y + 0.04, 0);
    const r = add(g, cone(Math.max(w, d) * 0.78, 0.7 * scale, 4), mat(color), 0, y + 0.4 * scale, 0); r.rotation.y = Math.PI / 4;
    r.scale.set(1, 1, d / w);
    add(g, sph(0.08, 6, 5), mat(th.accent), 0, y + 0.78 * scale, 0);
    return y + 0.75 * scale;
  }
  add(g, gable(w + 0.25, d + 0.3, 0.62 * scale), mat(color), 0, y, 0);
  return y + 0.62 * scale;
}

function flag(g, x, y, z, color, h = 1.0) {
  add(g, cyl(0.025, 0.03, h, 6), DARK(), x, y + h / 2, z);
  const f = live(g, x, y + h - 0.16, z);
  add(f, box(0.42, 0.24, 0.02, 0), mat(color, {side: THREE.DoubleSide}), 0.21, 0, 0);
  f.userData.flag = true; return f;
}

function windowsRow(g, w, y, z, n, h = 0.18) {
  for (let i = 0; i < n; i++) add(g, box(0.12, h, 0.04, 0.01), DARK(), -w / 2 + (i + 0.5) * w / n, y, z);
}

// ------------------------------------------------------------------ buildings
const BUILD = {
  palace(l, th, kc) {
    const g = new THREE.Group(), h = 1.0 + 0.2 * l;
    add(g, box(3.7, 0.36, 3.7, 0.06), mat(th.stone), 0, 0.18, 0);
    add(g, box(1.2, 0.18, 0.5, 0.03), mat(th.stone), 0, 0.09, 1.95);
    add(g, box(2.6, h, 2.1, 0.06), mat(th.wall), 0, 0.36 + h / 2, 0);
    add(g, box(2.7, 0.12, 2.2, 0.03), mat(th.trim), 0, 0.36 + h * 0.55, 0);
    add(g, box(0.56, 0.72, 0.08, 0.03), DARK(), 0, 0.72, 1.06);
    add(g, box(0.7, 0.1, 0.12, 0.02), mat(th.trim), 0, 1.1, 1.08);
    windowsRow(g, 2.2, 0.36 + h * 0.78, 1.06, 4);
    let top = roof(g, th, 2.6, 2.1, 0.36 + h, th.roof, 1.2);
    if (l >= 2) for (const [x, z] of [[-1.45, -1.45], [1.45, -1.45], [-1.45, 1.45], [1.45, 1.45]]) {
      const th2 = h + 0.55;
      add(g, cyl(0.3, 0.36, th2, 10), mat(th.wall), x, 0.36 + th2 / 2, z);
      add(g, cyl(0.38, 0.38, 0.1, 10), mat(th.trim), x, 0.36 + th2, z);
      add(g, cone(0.4, 0.55, 10), l >= 4 ? GOLD() : mat(th.roof), x, 0.36 + th2 + 0.32, z);
    }
    if (l >= 3) {
      add(g, box(1.0, 0.7, 1.0, 0.05), mat(th.wall), 0, top + 0.3, 0);
      add(g, dome(0.55), l >= 4 ? GOLD() : mat(th.accent), 0, top + 0.65, 0);
      top += 1.2;
    }
    if (l >= 5) { const gem = add(g, new THREE.OctahedronGeometry(0.22), mat(0x6fe3ff, {emissive: 0x2ab7ff, emissiveIntensity: 1.4})); gem.position.set(0, top + 0.25, 0); gem.userData.spin = true; }
    flag(g, -1.45, 0.36 + h + (l >= 2 ? 0.95 : 0), -1.45, kc, 0.9);
    flag(g, 1.45, 0.36 + h + (l >= 2 ? 0.95 : 0), -1.45, kc, 0.9);
    return g;
  },
  farm(l, th) {
    const g = new THREE.Group();
    add(g, box(2.8, 0.14, 2.8, 0.04), mat(0x7a5a36), 0, 0.07, 0);
    const rows = Math.min(7, 3 + l), crop = l >= 3 ? mat(th.field) : mat(0x76a83f);
    for (let r = 0; r < rows; r++) {
      const z = -1.1 + r * (2.2 / (rows - 1));
      add(g, box(2.4, 0.08, 0.16, 0.03), mat(0x5e4528), 0, 0.17, z);
      for (let i = 0; i < 6; i++) add(g, cone(0.09, 0.3, 5), crop, -1.05 + i * 0.42, 0.33, z);
    }
    add(g, box(0.75, 0.5, 0.6, 0.04), mat(th.wall), 1.0, 0.39, -1.05);
    roof(g, th, 0.75, 0.6, 0.64, th.roof, 0.6);
    if (l >= 2) for (let i = 0; i < 8; i++) {
      const a = i / 8 * Math.PI * 2;
      add(g, box(0.06, 0.3, 0.06, 0), WOOD(), Math.cos(a) * 1.42, 0.25, Math.sin(a) * 1.42);
    }
    if (l >= 3) {
      add(g, cyl(0.16, 0.28, 1.6, 8), mat(th.wall), -1.05, 0.9, -1.05);
      add(g, cone(0.24, 0.35, 8), mat(th.roof), -1.05, 1.85, -1.05);
      const blades = live(g, -1.05, 1.5, -0.84); blades.userData.spinZ = 1.6;
      for (let i = 0; i < 4; i++) add(blades, box(0.1, 0.75, 0.02, 0), WOOD_LIGHT());
      blades.children.forEach((b, i) => { b.position.set(Math.sin(i * Math.PI / 2) * 0.38, Math.cos(i * Math.PI / 2) * 0.38, 0); b.rotation.z = -i * Math.PI / 2; });
    }
    return g;
  },
  mine(l, th) {
    const g = new THREE.Group();
    const mound = add(g, new THREE.DodecahedronGeometry(1.05, 0), mat(0x8a7f70), 0, 0.3, -0.25); mound.scale.set(1.25, 0.62, 1.0);
    add(g, new THREE.DodecahedronGeometry(0.55, 0), mat(0x9a8f80), -0.9, 0.25, 0.55);
    add(g, box(0.7, 0.62, 0.32, 0.03), DARK(), 0, 0.42, 0.62);
    for (const x of [-0.38, 0.38]) add(g, box(0.1, 0.75, 0.1, 0.02), WOOD(), x, 0.42, 0.78);
    add(g, box(0.9, 0.1, 0.12, 0.02), WOOD(), 0, 0.82, 0.78);
    for (const x of [-0.18, 0.18]) add(g, box(0.04, 0.04, 1.0, 0), IRON(), x, 0.06, 1.15);
    for (let i = 0; i < 4; i++) add(g, box(0.5, 0.04, 0.08, 0), WOOD(), 0, 0.03, 0.8 + i * 0.22);
    add(g, box(0.48, 0.24, 0.36, 0.04), WOOD(), 0, 0.2, 1.3);
    for (let i = 0; i < 4; i++) add(g, new THREE.DodecahedronGeometry(0.08 + (i % 2) * 0.03, 0), GOLD(), -0.12 + i * 0.08, 0.36, 1.3 + (i % 2 ? 0.06 : -0.06));
    const veins = Math.min(6, l * 1.5);
    for (let i = 0; i < veins; i++) add(g, new THREE.OctahedronGeometry(0.09, 0), GOLD(), -0.7 + i * 0.28, 0.55 + (i % 2) * 0.12, -0.05 + (i % 3) * 0.12);
    if (l >= 3) {
      for (const x of [-0.5, 0.5]) add(g, box(0.08, 1.7, 0.08, 0.01), WOOD(), x, 0.85, -0.9, 0, 0, x > 0 ? 0.25 : -0.25);
      const wheel = live(g, 0, 1.62, -0.88); wheel.userData.spinZ = 1.2;
      add(wheel, torus(0.28, 0.035, Math.PI * 2), WOOD_LIGHT());
      add(wheel, box(0.52, 0.04, 0.04, 0), WOOD_LIGHT()); add(wheel, box(0.04, 0.52, 0.04, 0), WOOD_LIGHT());
    }
    return g;
  },
  granary(l, th) {
    const g = new THREE.Group(), n = l >= 4 ? 3 : l >= 2 ? 2 : 1;
    add(g, box(2.7, 0.16, 2.7, 0.04), mat(th.stone), 0, 0.08, 0);
    const spots = n === 1 ? [[0, 0]] : n === 2 ? [[-0.62, 0.1], [0.62, -0.1]] : [[-0.7, 0.45], [0.7, 0.45], [0, -0.6]];
    for (const [x, z] of spots) {
      const h = 1.0 + 0.12 * l;
      add(g, cyl(0.52, 0.56, h, 14), mat(th.wall), x, 0.16 + h / 2, z);
      add(g, cyl(0.58, 0.58, 0.08, 14), mat(th.trim), x, 0.16 + h * 0.35, z);
      add(g, cone(0.66, 0.55, 14), mat(th.style === "flat" ? 0xd9b65a : th.roof), x, 0.16 + h + 0.27, z);
      add(g, box(0.26, 0.34, 0.05, 0.02), DARK(), x, 0.36, z + 0.54);
    }
    for (let i = 0; i < 3 + l; i++) add(g, sph(0.13, 8, 6), mat(0xe2cfa0), -1.1 + i * 0.3, 0.26, 1.15).scale.set(1, 0.8, 1);
    return g;
  },
  treasury(l, th) {
    const g = new THREE.Group(), h = 0.95 + 0.12 * l;
    add(g, box(2.7, 0.2, 2.5, 0.04), mat(th.stone), 0, 0.1, 0);
    add(g, box(2.1, h, 1.7, 0.05), mat(l >= 3 ? th.stone : th.wall), 0, 0.2 + h / 2, -0.15);
    add(g, box(0.6, 0.66, 0.08, 0.02), IRON(), 0, 0.53, 0.72);
    add(g, gable(2.3, 1.95, 0.5), mat(th.trim), 0, 0.2 + h, -0.15);
    if (l >= 2) for (let i = 0; i < 4; i++) add(g, cyl(0.09, 0.1, h, 10), mat(th.wall), -0.85 + i * 0.57, 0.2 + h / 2, 0.85);
    if (l >= 2) add(g, box(2.2, 0.1, 0.35, 0.02), mat(th.trim), 0, 0.2 + h, 0.82);
    const piles = 2 + l;
    for (let i = 0; i < piles; i++) add(g, cone(0.17, 0.2, 10), GOLD(), -1.05 + (i % 4) * 0.7, 0.3, 1.05 - Math.floor(i / 4) * 2.1);
    if (l >= 4) add(g, dome(0.42), GOLD(), 0, 0.2 + h + 0.48, -0.15);
    return g;
  },
  barracks(l, th, kc) {
    const g = new THREE.Group(), h = 0.85 + 0.1 * l;
    add(g, box(2.8, 0.1, 2.8, 0.03), mat(th.dirt), 0, 0.05, 0);
    add(g, box(2.6, h, 1.3, 0.05), mat(l >= 3 ? th.stone : th.wall), 0, 0.1 + h / 2, -0.7);
    windowsRow(g, 2.2, 0.1 + h * 0.6, -0.04, 5, 0.16);
    add(g, box(0.4, 0.5, 0.05, 0.02), DARK(), 0, 0.35, -0.04);
    roof(g, th, 2.6, 1.3, 0.1 + h, th.roof, 0.8);
    for (const x of [-0.9, 0.9]) {
      add(g, cyl(0.04, 0.04, 0.55, 6), WOOD(), x, 0.33, 0.75);
      add(g, sph(0.13, 8, 6), mat(0xd9b88a), x, 0.66, 0.75);
      add(g, box(0.42, 0.06, 0.06, 0), WOOD(), x, 0.48, 0.75);
    }
    for (let i = 0; i < 4; i++) add(g, cyl(0.015, 0.015, 0.9, 4), WOOD_LIGHT(), -0.2 + i * 0.13, 0.5, 0.95, 0.15, 0, 0);
    flag(g, 1.25, 0.1, 0.25, kc, 1.3);
    return g;
  },
  camp(l, th, kc) {
    const g = new THREE.Group();
    add(g, cyl(1.85, 1.9, 0.06, 28), mat(th.dirt), 0, 0.03, 0);
    for (let i = 0; i < 4; i++) add(g, box(0.45, 0.08, 0.08, 0.02), WOOD(), 0, 0.1, 0, 0, i * Math.PI / 4, 0);
    const fire = live(g, 0, 0.22, 0); fire.userData.flicker = true;
    add(fire, cone(0.17, 0.4, 7), mat(0xff8c2a, {emissive: 0xff5a00, emissiveIntensity: 1.6}));
    add(fire, cone(0.09, 0.28, 6), mat(0xffe08a, {emissive: 0xffc030, emissiveIntensity: 2}), 0, 0.02, 0);
    const tents = l >= 3 ? 4 : 3;
    for (let i = 0; i < tents; i++) {
      const a = i / tents * Math.PI * 2 + 0.4, x = Math.cos(a) * 1.25, z = Math.sin(a) * 1.25;
      const t = add(g, cone(0.5, 0.75, 4), mat(i % 2 ? kc : 0xe8dcc0), x, 0.4, z); t.rotation.y = a;
      add(g, box(0.16, 0.3, 0.02, 0), DARK(), x - Math.cos(a) * 0.3, 0.2, z - Math.sin(a) * 0.3, 0, -a + Math.PI / 2, 0);
    }
    flag(g, 1.6, 0.05, -1.6, kc, 1.2);
    return g;
  },
  archer_tower(l, th, kc) {
    const g = new THREE.Group(), h = 1.6 + 0.25 * l;
    add(g, box(1.55, 0.25, 1.55, 0.04), mat(th.stone), 0, 0.12, 0);
    if (l === 1) for (const [x, z] of [[-0.45, -0.45], [0.45, -0.45], [-0.45, 0.45], [0.45, 0.45]]) add(g, box(0.12, h, 0.12, 0.02), WOOD(), x, 0.25 + h / 2, z);
    else {
      const t = add(g, cyl(0.62, 0.82, h, 4), mat(l >= 4 ? 0xe9e3d6 : th.stone), 0, 0.25 + h / 2, 0); t.rotation.y = Math.PI / 4;
      add(g, box(0.12, 0.35, 0.04, 0.01), DARK(), 0, 0.25 + h * 0.6, 0.62);
    }
    const top = 0.25 + h;
    add(g, box(1.45, 0.14, 1.45, 0.03), l === 1 ? WOOD_LIGHT() : mat(th.stone), 0, top + 0.07, 0);
    for (let i = 0; i < 8; i++) {
      const s = i < 4 ? [-0.6 + i * 0.4, 0.62] : [-0.6 + (i - 4) * 0.4, -0.62];
      add(g, box(0.18, 0.2, 0.12, 0.02), l === 1 ? WOOD() : mat(th.stone), s[0], top + 0.24, s[1]);
      add(g, box(0.12, 0.2, 0.18, 0.02), l === 1 ? WOOD() : mat(th.stone), s[1], top + 0.24, s[0]);
    }
    if (l >= 3) {
      for (const [x, z] of [[-0.6, -0.6], [0.6, -0.6], [-0.6, 0.6], [0.6, 0.6]]) add(g, cyl(0.04, 0.04, 0.6, 6), WOOD(), x, top + 0.45, z);
      const r = add(g, cone(1.1, 0.5, 4), l >= 5 ? GOLD() : mat(th.roof), 0, top + 1.0, 0); r.rotation.y = Math.PI / 4;
    }
    if (l >= 4) add(g, box(1.6, 0.08, 1.6, 0.02), GOLD(), 0, top - 0.02, 0);
    const turret = live(g, 0, top + 0.14, 0); turret.userData.turret = true;
    turret.add(unit("archer", kc, {scale: 0.95}));
    g.userData.muzzle = new THREE.Vector3(0, top + 0.6, 0);
    return g;
  },
  bolt_thrower(l, th) {
    const g = new THREE.Group();
    add(g, cyl(1.2, 1.32, 0.4, 14), mat(l >= 3 ? 0xe2dccd : th.stone), 0, 0.2, 0);
    add(g, cyl(1.24, 1.24, 0.08, 14), mat(th.trim), 0, 0.42, 0);
    add(g, cyl(0.22, 0.3, 0.45, 8), WOOD(), 0, 0.62, 0);
    const turret = live(g, 0, 0.88, 0); turret.userData.turret = true;
    add(turret, box(0.26, 0.2, 1.5, 0.03), l >= 4 ? mat(0x6b4a2b) : WOOD());
    add(turret, torus(0.7, 0.05, Math.PI), l >= 4 ? GOLD() : WOOD_LIGHT(), 0, 0.02, 0.45, Math.PI / 2, 0, 0);
    add(turret, box(1.38, 0.02, 0.02, 0), mat(0xeeeeee), 0, 0.05, 0.42);
    add(turret, cyl(0.035, 0.035, 1.3, 6), IRON(), 0, 0.14, 0.1, Math.PI / 2, 0, 0);
    add(turret, cone(0.07, 0.18, 6), IRON(), 0, 0.14, 0.82, Math.PI / 2, 0, 0);
    g.userData.muzzle = new THREE.Vector3(0, 1.05, 0);
    return g;
  },
  catapult(l, th) {
    const g = new THREE.Group();
    add(g, box(2.4, 0.3, 2.4, 0.05), mat(l >= 3 ? 0xd8d0bf : th.stone), 0, 0.15, 0);
    const turret = live(g, 0, 0.3, 0); turret.userData.turret = true;
    add(turret, box(1.3, 0.16, 1.5, 0.03), WOOD());
    for (const x of [-0.5, 0.5]) {
      add(turret, box(0.12, 1.0, 0.12, 0.02), WOOD(), x, 0.5, 0.25, 0.3, 0, 0);
      add(turret, box(0.12, 1.0, 0.12, 0.02), WOOD(), x, 0.5, -0.25, -0.3, 0, 0);
    }
    add(turret, cyl(0.06, 0.06, 1.15, 8), IRON(), 0, 0.92, 0, 0, 0, Math.PI / 2);
    const arm = new THREE.Group(); arm.position.set(0, 0.92, 0); arm.rotation.x = -0.9; turret.add(arm);
    add(arm, box(0.12, 0.12, 1.9, 0.03), WOOD_LIGHT(), 0, 0, 0.35);
    add(arm, cyl(0.2, 0.16, 0.16, 10), WOOD(), 0, 0.08, 1.25);
    add(arm, sph(0.15, 8, 6), mat(0x8a8a84), 0, 0.2, 1.25);
    add(arm, box(0.35, 0.35, 0.35, 0.04), mat(0x6f665a), 0, -0.1, -0.55);
    turret.userData.arm = arm;
    if (l >= 4) add(turret, box(1.34, 0.05, 1.54, 0.01), GOLD(), 0, 0.1, 0);
    g.userData.muzzle = new THREE.Vector3(0, 1.6, 0);
    return g;
  },
  house(l, th, kc, seed = 1) {
    const g = new THREE.Group(), h = 0.62 + 0.08 * l, w = 1.15, d = 0.95;
    add(g, box(1.6, 0.08, 1.6, 0.02), mat(th.dirt), 0, 0.04, 0);
    add(g, box(w, h, d, 0.04), mat(th.wall), 0, 0.08 + h / 2, 0);
    add(g, box(0.24, 0.38, 0.04, 0.01), DARK(), 0.2, 0.27, d / 2 + 0.01);
    add(g, box(0.18, 0.16, 0.04, 0.01), DARK(), -0.28, 0.42, d / 2 + 0.01);
    let top = roof(g, th, w, d, 0.08 + h, seed % 3 === 0 ? th.trim : th.roof, 0.7);
    if (l >= 3) { add(g, box(0.7, 0.45, 0.6, 0.03), mat(th.wall), -0.1, top + 0.2, -0.05); roof(g, th, 0.7, 0.6, top + 0.43, th.roof, 0.5); }
    add(g, box(0.16, 0.45, 0.16, 0.02), mat(0x8a7f70), 0.38, 0.08 + h + 0.15, -0.25);
    if (l >= 2) for (let i = 0; i < 2; i++) add(g, sph(0.09, 6, 5), mat(i ? 0xd9534f : 0xf0c419), -0.45 + i * 0.25, 0.14, d / 2 + 0.14);
    g.rotation.y = (seed % 4) * Math.PI / 2;
    return g;
  },
  temple(l, th) {
    const g = new THREE.Group();
    [[2.7, 0], [2.25, 1], [1.85, 2]].forEach(([w, i]) => add(g, box(w, 0.24, w, 0.03), mat(i % 2 ? th.wall : th.stone), 0, 0.12 + i * 0.24, 0));
    const base = 0.72, h = 0.95 + 0.1 * l, cols = l >= 2 ? 6 : 4;
    for (let i = 0; i < cols; i++) for (const z of [-0.65, 0.65]) add(g, cyl(0.08, 0.09, h, 10), mat(th.wall), -0.7 + i * (1.4 / (cols - 1)), base + h / 2, z);
    add(g, box(1.7, h * 0.9, 0.9, 0.03), mat(th.stone), 0, base + h * 0.45, 0);
    add(g, box(1.8, 0.1, 1.6, 0.02), mat(th.trim), 0, base + h, 0);
    if (th.style === "flat") add(g, dome(0.6), l >= 4 ? GOLD() : mat(th.accent), 0, base + h + 0.05, 0);
    else add(g, gable(1.85, 1.65, 0.55), l >= 4 ? GOLD() : mat(th.roof), 0, base + h + 0.05, 0);
    const fire = live(g, 0, base + h + (th.style === "flat" ? 0.7 : 0.62), 0); fire.userData.flicker = true;
    add(fire, cyl(0.16, 0.1, 0.12, 10), GOLD(), 0, -0.04, 0);
    add(fire, cone(0.12, 0.32, 7), mat(0xff8c2a, {emissive: 0xff5a00, emissiveIntensity: 1.8}), 0, 0.16, 0);
    return g;
  },
};

export function building(type, level, theme, color, seed = 1) {
  const kc = new THREE.Color(color).getHex();
  const g = BUILD[type](Math.max(level, 1), theme, kc, seed);
  return bake(g);
}

// ------------------------------------------------------------------ walls (all baked into one mesh)
export function wallMesh(walls, theme, toWorld) {
  const root = new THREE.Group(), at = new Map(walls.map(w => [w.x + "," + w.y, w]));
  for (const w of walls) {
    const l = Math.max(w.level, 1), h = 0.62 + 0.1 * l, p = toWorld(w.x + 0.5, w.y + 0.5);
    const m = l === 1 ? WOOD() : l >= 4 ? mat(0xe6dfcf) : mat(theme.stone);
    const g = new THREE.Group(); g.position.copy(p); root.add(g);
    if (l === 1) {
      add(g, cyl(0.12, 0.13, h, 6), m, 0, h / 2, 0); add(g, cone(0.13, 0.2, 6), m, 0, h + 0.1, 0);
    } else {
      add(g, box(0.5, h + 0.12, 0.5, 0.04), m, 0, (h + 0.12) / 2, 0);
      add(g, box(0.56, 0.08, 0.56, 0.02), l >= 4 ? mat(0xe2b84a) : mat(theme.trim), 0, h + 0.14, 0);
    }
    for (const [dx, dy] of [[1, 0], [0, 1]]) {
      const n = at.get((w.x + dx) + "," + (w.y + dy)); if (!n) continue;
      const lh = Math.min(h, 0.62 + 0.1 * Math.max(n.level, 1));
      if (l === 1) for (let i = 1; i < 3; i++) {
        const o = i / 3; add(g, cyl(0.11, 0.12, lh * 0.95, 6), m, dx * o, lh * 0.47, dy * o);
        add(g, cone(0.12, 0.18, 6), m, dx * o, lh * 0.95 + 0.08, dy * o);
      } else {
        add(g, box(dx ? 0.6 : 0.36, lh, dy ? 0.6 : 0.36, 0.03), m, dx * 0.5, lh / 2, dy * 0.5);
        add(g, box(0.14, 0.12, 0.14, 0.02), m, dx * 0.5, lh + 0.06, dy * 0.5);
      }
    }
  }
  return bake(root);
}

// ------------------------------------------------------------------ construction and ruins
export function scaffold(size, h = 1.4) {
  const g = new THREE.Group(), s = size * 0.42;
  for (const [x, z] of [[-s, -s], [s, -s], [-s, s], [s, s], [0, -s], [0, s], [-s, 0], [s, 0]]) add(g, box(0.06, h, 0.06, 0), WOOD_LIGHT(), x, h / 2, z);
  for (const y of [h * 0.4, h * 0.85]) {
    add(g, box(s * 2 + 0.1, 0.05, 0.12, 0), WOOD(), 0, y, -s); add(g, box(s * 2 + 0.1, 0.05, 0.12, 0), WOOD(), 0, y, s);
    add(g, box(0.12, 0.05, s * 2 + 0.1, 0), WOOD(), -s, y, 0); add(g, box(0.12, 0.05, s * 2 + 0.1, 0), WOOD(), s, y, 0);
  }
  add(g, box(0.4, 0.3, 0.4, 0.03), WOOD(), s * 0.6, 0.15, s * 0.9);
  add(g, box(0.3, 0.25, 0.3, 0.03), WOOD_LIGHT(), -s * 0.5, 0.13, s * 0.95);
  return bake(g);
}

export function rubble(size, seed = 3) {
  const g = new THREE.Group(), r = mulberry(seed);
  add(g, cyl(size * 0.45, size * 0.5, 0.04, 16), mat(0x3a3027), 0, 0.02, 0);
  for (let i = 0; i < 6 + size * 3; i++) {
    const s = 0.12 + r() * 0.28;
    add(g, box(s, s * 0.7, s, 0.02), mat([0x7d7468, 0x5e554b, 0x8a6a46, 0x4b443d][Math.floor(r() * 4)]),
      (r() - 0.5) * size * 0.7, s * 0.3, (r() - 0.5) * size * 0.7, r() * 2, r() * 3, r());
  }
  return bake(g);
}

function mulberry(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

// ------------------------------------------------------------------ people and troops
function person(parent, body, opts = {}) {
  const skin = mat(SKIN[opts.skin ?? 1]);
  const g = new THREE.Group(); parent.add(g);
  const legs = [];
  for (const x of [-0.07, 0.07]) {
    const hip = new THREE.Group(); hip.position.set(x, 0.24, 0); g.add(hip);
    add(hip, box(0.09, 0.24, 0.1, 0.03), mat(opts.legs ?? 0x5a4632), 0, -0.12, 0); legs.push(hip);
  }
  add(g, box(0.3, 0.3, 0.2, 0.06), mat(body), 0, 0.38, 0);
  add(g, box(0.31, 0.05, 0.21, 0.01), mat(0x4a3420), 0, 0.27, 0);
  add(g, sph(0.15, 12, 10), skin, 0, 0.64, 0);
  add(g, sph(0.025, 5, 4), DARK(), -0.05, 0.66, 0.135); add(g, sph(0.025, 5, 4), DARK(), 0.05, 0.66, 0.135);
  const arms = [];
  for (const x of [-0.19, 0.19]) {
    const sh = new THREE.Group(); sh.position.set(x, 0.5, 0); g.add(sh);
    add(sh, box(0.08, 0.24, 0.08, 0.03), mat(body), 0, -0.11, 0); add(sh, sph(0.045, 6, 5), skin, 0, -0.24, 0); arms.push(sh);
  }
  g.userData.legs = legs; g.userData.arms = arms;
  return g;
}

export function unit(type, color, opts = {}) {
  const kc = new THREE.Color(color).getHex(), root = new THREE.Group();
  let rig;
  if (type === "spearman" || type === "guard") {
    rig = person(root, kc, {skin: 1});
    add(rig, dome(0.165), mat(0xc9a44a, {metalness: 0.5, roughness: 0.4}), 0, 0.66, 0).scale.set(1, 0.85, 1);
    add(rig, cone(0.03, 0.12, 6), mat(0xc0392b), 0, 0.83, 0);
    add(rig.userData.arms[1], cyl(0.015, 0.015, 0.95, 5), WOOD(), 0, -0.2, 0.1, Math.PI / 2.4, 0, 0);
    add(rig.userData.arms[1], cone(0.035, 0.13, 6), IRON(), 0, -0.04, 0.56, Math.PI / 2.4, 0, 0);
    if (type === "spearman") add(rig.userData.arms[0], cyl(0.15, 0.15, 0.04, 14), mat(kc), -0.05, -0.15, 0.06, 0, 0, Math.PI / 2);
  } else if (type === "archer") {
    rig = person(root, 0x4e6b34, {skin: 2});
    add(rig, cone(0.17, 0.26, 8), mat(0x3e5a2a), 0, 0.78, -0.01);
    add(rig, box(0.22, 0.06, 0.02, 0), mat(kc), 0, 0.34, 0.105);
    add(rig.userData.arms[0], torus(0.22, 0.012, Math.PI), WOOD_LIGHT(), 0, -0.2, 0.1, 0, Math.PI / 2, Math.PI / 2);
    add(rig, cyl(0.05, 0.05, 0.28, 6), mat(0x6b4a2b), 0.08, 0.45, -0.13, 0.4, 0, 0);
  } else if (type === "raider") {
    const horse = new THREE.Group(); root.add(horse);
    add(horse, box(0.28, 0.28, 0.7, 0.08), mat(0x7a4f2a), 0, 0.5, 0);
    add(horse, box(0.14, 0.32, 0.16, 0.05), mat(0x7a4f2a), 0, 0.72, 0.36, -0.5, 0, 0);
    add(horse, box(0.13, 0.13, 0.28, 0.04), mat(0x7a4f2a), 0, 0.85, 0.52);
    add(horse, box(0.06, 0.24, 0.12, 0.02), DARK(), 0, 0.82, 0.28, -0.5, 0, 0);
    add(horse, box(0.05, 0.3, 0.06, 0.02), DARK(), 0, 0.48, -0.38, 0.5, 0, 0);
    add(horse, box(0.3, 0.06, 0.32, 0.02), mat(kc), 0, 0.66, -0.02);
    const legs = [];
    for (const [x, z] of [[-0.09, 0.25], [0.09, 0.25], [-0.09, -0.25], [0.09, -0.25]]) {
      const hip = new THREE.Group(); hip.position.set(x, 0.4, z); horse.add(hip);
      add(hip, box(0.07, 0.4, 0.07, 0.02), mat(0x6a4222), 0, -0.2, 0); legs.push(hip);
    }
    rig = person(horse, kc, {skin: 3}); rig.position.set(0, 0.48, -0.02); rig.scale.setScalar(0.85);
    rig.userData.legs.forEach(l => (l.rotation.x = -1.2));
    add(rig.userData.arms[1], box(0.03, 0.05, 0.45, 0), IRON(), 0, -0.22, 0.2);
    root.userData.legs = legs; root.userData.arms = rig.userData.arms;
    rig = null;
  } else if (type === "ram") {
    add(root, box(0.55, 0.12, 0.85, 0.03), WOOD(), 0, 0.22, 0);
    add(root, gable(0.85, 0.65, 0.42), mat(0x6b4a2b), 0, 0.28, 0);
    add(root, cyl(0.08, 0.08, 1.05, 8), mat(0x5a3a1f), 0, 0.28, 0.15, Math.PI / 2, 0, 0);
    add(root, sph(0.12, 8, 6), IRON(), 0, 0.28, 0.7);
    const wheels = [];
    for (const [x, z] of [[-0.3, 0.28], [0.3, 0.28], [-0.3, -0.28], [0.3, -0.28]]) {
      const w = add(root, cyl(0.13, 0.13, 0.06, 10), WOOD_LIGHT(), x, 0.13, z, 0, 0, Math.PI / 2); wheels.push(w);
    }
    add(root, box(0.15, 0.12, 0.02, 0), mat(kc), 0, 0.5, -0.43);
    root.userData.wheels = wheels;
  } else if (type === "elephant") {
    const body = new THREE.Group(); root.add(body);
    add(body, sph(0.5, 14, 10), mat(0x8e8a86), 0, 0.85, 0).scale.set(0.95, 0.85, 1.25);
    add(body, sph(0.32, 12, 9), mat(0x8e8a86), 0, 1.02, 0.62);
    const trunk = new THREE.Group(); trunk.position.set(0, 0.9, 0.86); body.add(trunk);
    add(trunk, cyl(0.07, 0.1, 0.45, 8), mat(0x85817d), 0, -0.2, 0.05, 0.25, 0, 0);
    add(trunk, cyl(0.05, 0.07, 0.3, 8), mat(0x85817d), 0, -0.5, 0.12, 0.5, 0, 0);
    for (const x of [-1, 1]) {
      add(body, cyl(0.26, 0.26, 0.03, 12), mat(0x9c9792), x * 0.3, 1.02, 0.5, 0, 0, Math.PI / 2 - x * 0.3).scale.set(1, 1, 1.2);
      add(body, cone(0.04, 0.38, 6), mat(0xf4efe4), x * 0.13, 0.82, 0.86, Math.PI / 2.2, 0, 0);
    }
    add(body, box(0.62, 0.32, 0.6, 0.05), mat(kc), 0, 1.38, -0.05);
    add(body, cone(0.48, 0.4, 4), mat(0xf2c14e), 0, 1.75, -0.05).rotation.y = Math.PI / 4;
    const legs = [];
    for (const [x, z] of [[-0.25, 0.35], [0.25, 0.35], [-0.25, -0.35], [0.25, -0.35]]) {
      const hip = new THREE.Group(); hip.position.set(x, 0.55, z); body.add(hip);
      add(hip, cyl(0.12, 0.13, 0.55, 8), mat(0x85817d), 0, -0.27, 0); legs.push(hip);
    }
    root.userData.legs = legs; root.userData.trunk = trunk;
  } else { // townspeople
    const outfit = {farmer: 0x7a9a3a, miner: 0x6b5a4a, priest: 0xf2ece0, merchant: 0x2e7d7a, king: 0x6a1b9a, scholar: 0x2f4f9a}[type] ?? 0x8a6a4a;
    rig = person(root, outfit, {skin: opts.skin ?? 1, legs: type === "priest" ? 0xf2ece0 : 0x5a4632});
    if (type === "farmer") { add(rig, cone(0.26, 0.12, 12), mat(0xe0c060), 0, 0.79, 0); add(rig.userData.arms[1], cyl(0.012, 0.012, 0.6, 4), WOOD(), 0, -0.25, 0.05, 0.3, 0, 0); }
    if (type === "miner") { add(rig, dome(0.155), mat(0x9a7a3a), 0, 0.68, 0); add(rig.userData.arms[1], box(0.3, 0.04, 0.04, 0), IRON(), 0.05, -0.26, 0.05); }
    if (type === "priest") { add(rig, cone(0.22, 0.5, 10), mat(0xf2ece0), 0, 0.2, 0); add(rig, cyl(0.1, 0.12, 0.1, 10), mat(0xc0392b), 0, 0.8, 0); }
    if (type === "merchant") { add(rig, dome(0.17), mat(0xe8e0d0), 0, 0.68, 0); add(rig.userData.arms[0], sph(0.1, 8, 6), mat(0xc9a86a), 0, -0.28, 0.05); }
    if (type === "scholar") { add(rig, cone(0.12, 0.18, 8), mat(0x23336e), 0, 0.83, 0); add(rig.userData.arms[0], box(0.14, 0.18, 0.04, 0), mat(0xe8dcc0), 0, -0.25, 0.08); }
    if (type === "king") {
      add(rig, cyl(0.12, 0.13, 0.09, 8), GOLD(), 0, 0.8, 0);
      for (let i = 0; i < 5; i++) add(rig, cone(0.025, 0.07, 4), GOLD(), Math.cos(i / 5 * 6.28) * 0.11, 0.87, Math.sin(i / 5 * 6.28) * 0.11);
      add(rig, box(0.36, 0.5, 0.04, 0.02), mat(kc), 0, 0.3, -0.12, 0.12, 0, 0);
      root.scale.setScalar(1.15);
    }
  }
  if (rig) { root.userData.legs = rig.userData.legs; root.userData.arms = rig.userData.arms; }
  root.userData.type = type;
  root.scale.multiplyScalar(opts.scale ?? 1);
  root.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = false; } });
  return root;
}

/** Walk or attack animation for any unit made by unit(). */
export function animate(u, t, moving, attacking, speed = 1) {
  const d = u.userData, ph = t * 9 * speed + (u.id % 7);
  if (d.legs) d.legs.forEach((l, i) => (l.rotation.x = moving ? Math.sin(ph + (i % 2 ? Math.PI : 0) + (i > 1 ? Math.PI : 0)) * 0.6 : 0));
  if (d.arms) {
    d.arms[0].rotation.x = moving ? Math.sin(ph + Math.PI) * 0.4 : 0;
    d.arms[1].rotation.x = attacking ? -1.2 + Math.max(0, Math.sin(t * 8)) * 1.4 : moving ? Math.sin(ph) * 0.4 : 0;
  }
  if (d.wheels && moving) d.wheels.forEach(w => (w.rotation.x += 0.2 * speed));
  if (d.trunk) d.trunk.rotation.x = Math.sin(t * 2 + u.id) * 0.2 + (attacking ? Math.sin(t * 6) * 0.4 : 0);
}
