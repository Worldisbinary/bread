// Shared runtime: DOM helpers, the API client, sound and voice, and the Stage that owns the renderer
// and switches between views (town, battle, world map).
import * as THREE from "three";

export const $ = id => document.getElementById(id);
export const fmt = n => Math.round(n).toLocaleString();
export const pct = v => Math.round(v * 100) + "%";
export const yr = y => (y < 0 ? `${-y} BCE` : `${y} CE`);
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const esc = t => String(t ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

export async function api(path, body) {
  const r = await fetch("/game/api/" + path, body === undefined ? {} :
    {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    const err = new Error(typeof detail === "string" ? detail : r.statusText); err.status = r.status; throw err;
  }
  return r.json();
}

export function rng(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
}

export function toast(text, kind = "", ms = 2600) {
  const el = $("toast"); el.textContent = text; el.className = "show " + kind;
  clearTimeout(toast.t); toast.t = setTimeout(() => (el.className = ""), ms);
}

// ------------------------------------------------------------------ sound: effects, music, voice
export const Sound = {
  ctx: null, on: true,
  init() {
    if (this.ctx) { if (this.ctx.state === "suspended") this.ctx.resume(); return; }
    try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return; }
    this.master = this.ctx.createGain(); this.master.gain.value = 0.55; this.master.connect(this.ctx.destination);
    this.music();
  },
  tone(freq, dur, type = "sine", vol = 0.2, when = 0, slide = 0) {
    if (!this.ctx || !this.on) return;
    const t = this.ctx.currentTime + when, o = this.ctx.createOscillator(), g = this.ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t); if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq * slide), t + dur);
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(this.master); o.start(t); o.stop(t + dur + 0.05);
  },
  noise(dur, vol = 0.3, freq = 900, when = 0, q = 1) {
    if (!this.ctx || !this.on) return;
    const n = Math.floor(this.ctx.sampleRate * dur), buf = this.ctx.createBuffer(1, n, this.ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 2);
    const src = this.ctx.createBufferSource(), f = this.ctx.createBiquadFilter(), g = this.ctx.createGain();
    src.buffer = buf; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q; g.gain.value = vol;
    src.connect(f).connect(g).connect(this.master); src.start(this.ctx.currentTime + when);
  },
  last: {},
  sfx(name) {
    const now = performance.now(); // rate-limit noisy effects so a big battle stays pleasant
    const gap = {arrow: 70, hit: 60, boom: 120, bolt: 120, crumble: 150, deploy: 60}[name] || 0;
    if (gap && now - (this.last[name] || 0) < gap) return; this.last[name] = now;
    switch (name) {
      case "click": this.tone(700, 0.07, "triangle", 0.12); break;
      case "open": this.tone(520, 0.08, "triangle", 0.1); this.tone(780, 0.1, "triangle", 0.08, 0.05); break;
      case "coin": [1318, 1568, 2093].forEach((f, i) => this.tone(f, 0.18, "square", 0.04, i * 0.06)); break;
      case "grain": this.noise(0.35, 0.25, 2500, 0, 0.6); this.tone(880, 0.15, "triangle", 0.06, 0.05); break;
      case "build": for (let i = 0; i < 3; i++) { this.noise(0.06, 0.35, 1800, i * 0.16, 3); this.tone(240, 0.08, "square", 0.05, i * 0.16); } break;
      case "deploy": this.tone(330, 0.12, "sawtooth", 0.05, 0, 1.4); break;
      case "arrow": this.noise(0.12, 0.12, 4000, 0, 4); break;
      case "bolt": this.noise(0.18, 0.2, 1500, 0, 2); this.tone(180, 0.15, "square", 0.04); break;
      case "hit": this.noise(0.05, 0.12, 900, 0, 2); break;
      case "boom": this.noise(0.5, 0.45, 220, 0, 0.7); this.tone(70, 0.4, "sine", 0.25, 0, 0.5); break;
      case "crumble": this.noise(0.9, 0.45, 300, 0, 0.5); this.noise(0.5, 0.25, 1200, 0.1, 1); break;
      case "horn": this.tone(220, 0.6, "sawtooth", 0.06); this.tone(330, 0.6, "sawtooth", 0.05, 0.05); break;
      case "victory": [523, 659, 784, 1046, 1318].forEach((f, i) => this.tone(f, 0.45, "triangle", 0.09, i * 0.13)); break;
      case "defeat": [392, 349, 311, 262].forEach((f, i) => this.tone(f, 0.5, "triangle", 0.08, i * 0.18)); break;
      case "error": this.tone(170, 0.22, "square", 0.07); break;
      case "star": this.tone(1046, 0.3, "triangle", 0.1); this.tone(1568, 0.4, "triangle", 0.07, 0.08); break;
    }
  },
  music() { // gentle generative pads on a pentatonic scale
    const scale = [196, 220, 262, 294, 330, 392, 440];
    const chord = () => {
      if (!this.on || !this.ctx || this.quiet) return;
      const root = scale[Math.floor(Math.random() * 3)];
      [1, 1.5, 2, 3].forEach(m => {
        const t = this.ctx.currentTime, o = this.ctx.createOscillator(), g = this.ctx.createGain(), f = this.ctx.createBiquadFilter();
        o.type = "triangle"; o.frequency.value = root * m; f.type = "lowpass"; f.frequency.value = 800;
        g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(0.018, t + 2.5); g.gain.linearRampToValueAtTime(0, t + 7.5);
        o.connect(f).connect(g).connect(this.master); o.start(t); o.stop(t + 8);
      });
      if (Math.random() < 0.7) this.tone(scale[3 + Math.floor(Math.random() * 4)] * 2, 1.4, "sine", 0.025, 1 + Math.random() * 3);
    };
    chord(); setInterval(chord, 7000);
  },
  say(text) {
    if (!this.on || !("speechSynthesis" in window) || !text) return;
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text), voices = speechSynthesis.getVoices();
    u.voice = voices.find(v => /en-(GB|IN)/.test(v.lang) && /female|Sonia|Libby|Neerja|Hazel|Susan|Heera/i.test(v.name)) ||
      voices.find(v => v.lang.startsWith("en")) || null;
    u.rate = 1.0; u.pitch = 1.05; u.volume = 0.9;
    speechSynthesis.speak(u);
  },
};

// ------------------------------------------------------------------ the stage
export const Stage = {
  init() {
    const r = this.renderer = new THREE.WebGLRenderer({antialias: true, powerPreference: "high-performance"});
    r.setPixelRatio(Math.min(devicePixelRatio, 2)); r.setSize(innerWidth, innerHeight);
    r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.0; r.outputColorSpace = THREE.SRGBColorSpace;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    $("scene").appendChild(r.domElement);
    this.clock = new THREE.Clock(); this.view = null; this.shake = 0;
    addEventListener("resize", () => {
      r.setSize(innerWidth, innerHeight);
      if (this.view) { this.view.camera.aspect = innerWidth / innerHeight; this.view.camera.updateProjectionMatrix(); this.view.resize?.(); }
    });
    let down = null, held = null;
    const ndc = e => new THREE.Vector2(e.clientX / innerWidth * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
    r.domElement.addEventListener("pointerdown", e => {
      down = {x: e.clientX, y: e.clientY, t: performance.now()};
      this.view?.onPress?.(ndc(e), e);
      clearInterval(held); held = setInterval(() => down && this.view?.onHold?.(ndc(e)), 140);
    });
    r.domElement.addEventListener("pointermove", e => this.view?.onMove?.(ndc(e), e));
    const up = e => {
      clearInterval(held);
      if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) < 7) this.view?.onTap?.(ndc(e), e);
      this.view?.onRelease?.();
      down = null;
    };
    r.domElement.addEventListener("pointerup", up);
    r.domElement.addEventListener("pointerleave", () => { clearInterval(held); down = null; this.view?.onRelease?.(); });
    r.domElement.addEventListener("contextmenu", e => e.preventDefault());
    r.setAnimationLoop(() => this.frame());
  },
  show(view) {
    if (this.view === view) return;
    if (this.view) { this.view.controls.enabled = false; this.view.hide?.(); }
    this.view = view; view.controls.enabled = true;
    view.camera.aspect = innerWidth / innerHeight; view.camera.updateProjectionMatrix();
    view.show?.();
  },
  frame() {
    const dt = Math.min(0.05, this.clock.getDelta()), t = this.clock.elapsedTime, v = this.view;
    if (!v) return;
    v.update(dt, t);
    v.controls.update();
    let cam = v.camera;
    if (this.shake > 0) { // a brief camera shake for big impacts
      this.shake = Math.max(0, this.shake - dt * 2.5);
      const s = this.shake * 0.35; cam.position.x += (Math.random() - 0.5) * s; cam.position.y += (Math.random() - 0.5) * s;
    }
    this.renderer.render(v.scene, cam);
    v.overlay?.();
  },
  project(vec3, camera) {
    const v = vec3.clone().project(camera);
    return {x: (v.x + 1) / 2 * innerWidth, y: (1 - v.y) / 2 * innerHeight, visible: v.z < 1 && Math.abs(v.x) < 1.15 && Math.abs(v.y) < 1.15};
  },
};
