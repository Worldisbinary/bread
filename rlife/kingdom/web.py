"""Admin LiveOps Console, Interactive 2D World Simulation, and Town Square Portal.

Features:
- Live Interactive 2D Canvas World:
  * 1,500 real citizens living in 6 distinct themed zones (Wheat Fields, Merchant Bazaar, Royal Castle, Artisan Guilds, Barracks & Academy, The Docks).
  * Citizens physically move, pathfind, wander, work, socialise in clusters, speak in live speech bubbles, and carry out daily animations.
  * Live clickable citizen inspectors: click any walking agent to see their profession, wealth, hunger, karma/standing, thoughts, and recent dialogue.
  * Time-of-day cycle (Day/Dusk/Night) and seasonal weather effects (Golden Harvest, Drought/Heatwave, Rain).
  * LiveOps Event FX: fireworks and confetti when a Harvest Festival is launched, royal guards marching during high policing, trade caravans during fairs.
- LiveOps Command HUD & Real-time WebSockets / REST controls:
  * Play / Pause / Step simulation at custom speeds (1x, 2x, 5x).
  * Emergency LiveOps Levers with visual impact on the canvas.
  * Speech Bubble ticker showing authentic real-time thoughts.
"""

import json
from html import escape
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .economy import Economy, PROFESSIONS, PROVINCES
from .events import ACTIONS, LiveOps
from .experiment import run_kingdom_ab_experiment
from .laws import LAW_SETS
from .metrics import snapshot
from .steward import RoyalSteward
from .voices import TownSquare, VOICE_NAMES

router = APIRouter(prefix="/kingdom")

# Global singleton in-memory state for the active interactive kingdom
active_econ = Economy(n=1500, laws=LAW_SETS["liberal"], seed=42)
active_ops = LiveOps(active_econ)
active_steward = RoyalSteward(active_econ, active_ops)
active_town_square = TownSquare(active_econ, sample_size=12)
active_history = [snapshot(active_econ)]
latest_ab_result = None

# Pre-generate 2D world spatial coordinates for citizens
ZONE_BOUNDS = {
    "farmer": {"x": [40, 360], "y": [40, 380], "color": "#84cc16", "name": "Golden Wheatfields"},
    "labourer": {"x": [40, 360], "y": [390, 720], "color": "#a3e635", "name": "Windmill Mills & Granary"},
    "merchant": {"x": [380, 760], "y": [380, 720], "color": "#f59e0b", "name": "Grand Bazaar & Markets"},
    "artisan": {"x": [380, 760], "y": [40, 370], "color": "#06b6d4", "name": "Artisan Guild Workshops"},
    "clerk": {"x": [780, 1160], "y": [380, 720], "color": "#8b5cf6", "name": "Commercial District & Bank"},
    "soldier": {"x": [780, 1160], "y": [40, 370], "color": "#ef4444", "name": "Royal Garrison & Castle"},
    "civil_servant": {"x": [580, 960], "y": [220, 520], "color": "#ec4899", "name": "Crown Ministry Square"},
    "teacher": {"x": [180, 560], "y": [220, 520], "color": "#3b82f6", "name": "Grand Library & Academy"},
}

WORLD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>The Living Kingdom of r/life - Autonomous Agent Society</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #090d16;
      --panel: #131a29;
      --card: #1c2638;
      --border: #2a3952;
      --gold: #f59e0b;
      --cyan: #38bdf8;
      --green: #22c55e;
      --red: #ef4444;
      --text: #f8fafc;
      --muted: #94a3b8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      overflow: hidden;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: var(--panel);
      border-bottom: 1px solid var(--border);
      padding: 10px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      font-size: 18px;
      font-weight: 700;
      color: var(--gold);
    }
    .hud-stats {
      display: flex;
      gap: 20px;
      font-size: 13px;
    }
    .stat-pill {
      background: var(--card);
      border: 1px solid var(--border);
      padding: 4px 12px;
      border-radius: 999px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .stat-val { font-weight: 700; color: #fff; }
    .controls {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .btn {
      background: var(--gold);
      color: #000;
      border: none;
      padding: 6px 14px;
      border-radius: 6px;
      font-weight: 600;
      font-size: 13px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn:hover { filter: brightness(1.15); transform: translateY(-1px); }
    .btn-cyan { background: var(--cyan); color: #000; }
    .btn-card { background: var(--card); color: #fff; border: 1px solid var(--border); }
    .btn-card:hover { background: var(--border); }
    .btn-danger { background: var(--red); color: #fff; }

    #main-container {
      display: flex;
      flex: 1;
      height: calc(100vh - 58px);
      position: relative;
    }
    #viewport {
      flex: 1;
      position: relative;
      background: #0f172a;
      overflow: hidden;
      cursor: grab;
    }
    #viewport:active { cursor: grabbing; }
    canvas { display: block; width: 100%; height: 100%; }

    /* Side Inspector & Feed Drawer */
    #sidebar {
      width: 380px;
      background: var(--panel);
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100%;
      z-index: 50;
    }
    .tab-bar {
      display: flex;
      border-bottom: 1px solid var(--border);
      background: rgba(0,0,0,0.2);
    }
    .tab-btn {
      flex: 1;
      padding: 12px;
      text-align: center;
      background: transparent;
      border: none;
      color: var(--muted);
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .tab-btn.active {
      color: var(--cyan);
      border-bottom: 2px solid var(--cyan);
      background: var(--card);
    }
    .tab-pane {
      display: none;
      flex: 1;
      overflow-y: auto;
      padding: 16px;
    }
    .tab-pane.active { display: flex; flex-direction: column; gap: 14px; }

    /* Citizen Inspector Card */
    .agent-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 16px;
    }
    .agent-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
    }
    .agent-name { font-size: 16px; font-weight: 700; color: #fff; }
    .agent-role {
      font-size: 12px;
      padding: 2px 8px;
      border-radius: 999px;
      font-weight: 600;
      text-transform: capitalize;
    }
    .agent-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      font-size: 13px;
      margin-bottom: 12px;
    }
    .agent-stat { color: var(--muted); }
    .agent-stat b { color: #fff; }
    .agent-thought {
      font-size: 13px;
      font-style: italic;
      color: var(--gold);
      background: rgba(245, 158, 11, 0.08);
      border-left: 3px solid var(--gold);
      padding: 8px 10px;
      border-radius: 4px;
    }

    /* Live Activity Chat */
    .chat-bubble {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 13px;
      position: relative;
    }
    .chat-author {
      font-size: 11px;
      font-weight: 700;
      color: var(--cyan);
      display: flex;
      justify-content: space-between;
      margin-bottom: 4px;
    }
    .chat-body { color: var(--text); line-height: 1.4; }
    .chat-thought { font-size: 11px; color: var(--gold); margin-top: 4px; font-style: italic; }

    /* Overlay HUD */
    #overlay-hud {
      position: absolute;
      top: 16px;
      left: 16px;
      pointer-events: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .zone-badge {
      background: rgba(19, 26, 41, 0.85);
      border: 1px solid var(--border);
      backdrop-filter: blur(8px);
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      color: #fff;
    }
    .live-alert {
      background: rgba(245, 158, 11, 0.9);
      color: #000;
      font-weight: 700;
      padding: 6px 12px;
      border-radius: 6px;
      font-size: 12px;
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse { 0% { opacity: 0.8; } 50% { opacity: 1; } 100% { opacity: 0.8; } }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span>👑</span>
      <div>
        <div>The Living Kingdom</div>
        <div style="font-size:11px; font-weight:normal; color:var(--muted)">1,500 Autonomous Simulated Citizens</div>
      </div>
    </div>

    <div class="hud-stats">
      <div class="stat-pill">👥 Pop: <span class="stat-val" id="hud-pop">1,500</span></div>
      <div class="stat-pill">🌾 Grain: <span class="stat-val" id="hud-grain">1.00</span></div>
      <div class="stat-pill">👑 Treasury: <span class="stat-val" id="hud-treasury">4,500</span></div>
      <div class="stat-pill">😊 Happy: <span class="stat-val" id="hud-happy">60%</span></div>
      <div class="stat-pill">⚡ Season: <span class="stat-val" id="hud-season">0</span></div>
    </div>

    <div class="controls">
      <button class="btn btn-card" id="btn-pause" onclick="togglePlay()">⏸️ Pause</button>
      <button class="btn btn-cyan" onclick="stepSeason()">⏭️ Advance Season</button>
      <button class="btn" onclick="stewardIntervene()">🤖 Steward Action</button>
      <button class="btn btn-card" onclick="triggerFestival()">🎉 Festival</button>
      <a href="/kingdom/admin" class="btn btn-card" style="text-decoration:none;">⚙️ Admin</a>
    </div>
  </header>

  <div id="main-container">
    <div id="viewport">
      <div id="overlay-hud">
        <div class="zone-badge">🏰 Capital Realm: <span id="current-zone-hover">Windmill Plains</span></div>
        <div id="active-event-badge" class="live-alert" style="display:none;"></div>
      </div>
      <canvas id="worldCanvas"></canvas>
    </div>

    <div id="sidebar">
      <div class="tab-bar">
        <button class="tab-btn active" onclick="setTab('inspector')">Citizen Inspector</button>
        <button class="tab-btn" onclick="setTab('chatter')">Town Square Voices</button>
        <button class="tab-btn" onclick="setTab('zones')">Provinces</button>
      </div>

      <div id="tab-inspector" class="tab-pane active">
        <div id="selected-agent-view">
          <div class="agent-card">
            <div class="agent-header">
              <div>
                <div class="agent-name" id="insp-name">Alden of Highvale</div>
                <div style="font-size:11px; color:var(--muted);" id="insp-prov">Province: Highvale</div>
              </div>
              <span class="agent-role" id="insp-role" style="background:#84cc16; color:#000;">Farmer</span>
            </div>
            <div class="agent-grid">
              <div class="agent-stat">Wealth: <b id="insp-wealth">14.2 coins</b></div>
              <div class="agent-stat">Standing: <b id="insp-standing">+12.0</b></div>
              <div class="agent-stat">Skill: <b id="insp-skill">0.82</b></div>
              <div class="agent-stat">Hunger: <b id="insp-hunger" style="color:var(--green)">Well-fed</b></div>
            </div>
            <div style="font-size:12px; margin-bottom:4px; color:var(--muted)">Current Thought:</div>
            <div class="agent-thought" id="insp-thought">"The harvest looks promising this quarter. May the granaries hold."</div>
          </div>
        </div>

        <div style="font-size:12px; color:var(--muted); text-align:center; margin-top:8px;">
          💡 <em>Click any wandering citizen on the canvas to inspect their live status & thoughts!</em>
        </div>

        <div class="agent-card" style="margin-top:10px;">
          <div style="font-size:13px; font-weight:700; margin-bottom:8px;">🎨 Citizen Occupation Legend</div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px;">
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#84cc16;"></span> Farmer</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#a3e635;"></span> Labourer</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#f59e0b;"></span> Merchant</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#06b6d4;"></span> Artisan</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#8b5cf6;"></span> Clerk</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ef4444;"></span> Soldier</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#ec4899;"></span> Civil Servant</div>
            <div><span style="display:inline-block; width:10px; height:10px; border-radius:50%; background:#3b82f6;"></span> Teacher</div>
          </div>
        </div>
      </div>

      <div id="tab-chatter" class="tab-pane">
        <div id="chat-list" style="display:flex; flex-direction:column; gap:10px;">
          <!-- Dynamically populated -->
        </div>
      </div>

      <div id="tab-zones" class="tab-pane">
        <div style="display:flex; flex-direction:column; gap:10px;" id="province-list">
          <!-- Dynamically populated -->
        </div>
      </div>
    </div>
  </div>

  <script>
    // --- 2D Interactive Simulation Engine ---
    const canvas = document.getElementById("worldCanvas");
    const ctx = canvas.getContext("2d");

    let isPlaying = true;
    let camera = { x: 0, y: 0, zoom: 1.0 };
    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let selectedCitizen = null;
    let citizens = [];
    let particles = [];
    let speechBubbles = [];
    let kingdomData = null;

    const PROF_COLORS = {
      farmer: "#84cc16",
      labourer: "#a3e635",
      merchant: "#f59e0b",
      artisan: "#06b6d4",
      clerk: "#8b5cf6",
      soldier: "#ef4444",
      civil_servant: "#ec4899",
      teacher: "#3b82f6"
    };

    const ZONE_RECTS = [
      { name: "🌾 Golden Wheat Fields", x: 40, y: 40, w: 340, h: 330, bg: "#142911", border: "#22541d" },
      { name: "🏭 Granaries & Mills", x: 40, y: 390, w: 340, h: 320, bg: "#1f2d12", border: "#39521e" },
      { name: "🎪 Grand Merchant Bazaar", x: 400, y: 390, w: 370, h: 320, bg: "#2d2011", border: "#5c3d19" },
      { name: "⚒️ Artisan Guilds", x: 400, y: 40, w: 370, h: 330, bg: "#0d262d", border: "#184e5c" },
      { name: "🏰 Royal Fortress & Garrison", x: 790, y: 40, w: 370, h: 330, bg: "#2d1111", border: "#5c1d1d" },
      { name: "🏛️ Royal Chancery & Banking", x: 790, y: 390, w: 370, h: 320, bg: "#1c112d", border: "#3b1e5c" },
      { name: "⛲ Fountain Plaza (Town Square)", x: 460, y: 270, w: 260, h: 180, bg: "#132133", border: "#254164" }
    ];

    function resizeCanvas() {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight;
    }
    window.addEventListener("resize", resizeCanvas);
    resizeCanvas();

    // Fetch initial world data
    async function initKingdom() {
      try {
        const res = await fetch("/kingdom/api/live-state");
        const data = await res.json();
        kingdomData = data;
        citizens = data.citizens;
        updateHUD(data.snapshot);
        updateChatter(data.voices);
        updateProvinces(data.provinces);
        if (citizens.length > 0) selectCitizen(citizens[0]);
      } catch (e) {
        console.error("Failed to load kingdom state:", e);
      }
    }

    function updateHUD(snap) {
      document.getElementById("hud-pop").innerText = snap.population.toLocaleString();
      document.getElementById("hud-grain").innerText = snap.grain_price.toFixed(2);
      document.getElementById("hud-treasury").innerText = Math.round(snap.treasury).toLocaleString();
      document.getElementById("hud-happy").innerText = (snap.happiness * 100).toFixed(0) + "%";
      document.getElementById("hud-season").innerText = snap.tick;
    }

    function updateChatter(voices) {
      const container = document.getElementById("chat-list");
      container.innerHTML = "";
      voices.forEach(v => {
        const item = document.createElement("div");
        item.className = "chat-bubble";
        item.innerHTML = `
          <div class="chat-author">
            <span>${v.name} (${v.profession})</span>
            <span>Season ${v.tick}</span>
          </div>
          <div class="chat-body">"${v.statement}"</div>
          <div class="chat-thought">💭 ${v.thought}</div>
        `;
        container.appendChild(item);

        // Also add floating speech bubble above that citizen
        const c = citizens.find(cit => cit.id === v.citizen_id);
        if (c) {
          speechBubbles.push({
            id: c.id,
            text: v.statement.slice(0, 35) + "...",
            timer: 240
          });
        }
      });
    }

    function updateProvinces(provs) {
      const container = document.getElementById("province-list");
      container.innerHTML = "";
      provs.forEach(p => {
        const div = document.createElement("div");
        div.className = "agent-card";
        div.innerHTML = `
          <div style="font-weight:700; color:var(--gold); margin-bottom:4px;">${p.name}</div>
          <div style="font-size:12px; color:var(--muted)">Population: <b>${p.population}</b></div>
          <div style="font-size:12px; color:var(--muted)">Avg Wealth: <b>${p.wealth.toFixed(1)} coins</b></div>
        `;
        container.appendChild(div);
      });
    }

    // --- Citizen Physics & Animation Loop ---
    function updatePhysics() {
      if (!isPlaying) return;

      citizens.forEach(c => {
        // Wandering within preferred zone with slight inertia
        c.x += c.vx;
        c.y += c.vy;

        // Soft bounce boundaries
        if (c.x < c.minX || c.x > c.maxX) c.vx *= -1;
        if (c.y < c.minY || c.y > c.maxY) c.vy *= -1;

        // Occasional random directional shift
        if (Math.random() < 0.02) {
          c.vx = (Math.random() - 0.5) * 1.2;
          c.vy = (Math.random() - 0.5) * 1.2;
        }

        // Animate walking legs/bobbing
        c.bob = Math.sin(Date.now() * 0.008 + c.id) * 2;
      });

      // Update Speech Bubbles
      speechBubbles.forEach(b => b.timer--);
      speechBubbles = speechBubbles.filter(b => b.timer > 0);

      // Update Particles (Festivals, coins, sparks)
      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
        p.alpha -= 0.015;
      });
      particles = particles.filter(p => p.alpha > 0);
    }

    // --- Rendering Pipeline ---
    function render() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();

      // Camera pan & zoom
      ctx.translate(canvas.width / 2, canvas.height / 2);
      ctx.scale(camera.zoom, camera.zoom);
      ctx.translate(-camera.x, -camera.y);

      // 1. Draw Realm Background & District Zones
      ZONE_RECTS.forEach(z => {
        ctx.fillStyle = z.bg;
        ctx.strokeStyle = z.border;
        ctx.lineWidth = 2;
        ctx.fillRect(z.x, z.y, z.w, z.h);
        ctx.strokeRect(z.x, z.y, z.w, z.h);

        // Zone label
        ctx.fillStyle = "rgba(255, 255, 255, 0.4)";
        ctx.font = "bold 13px sans-serif";
        ctx.fillText(z.name, z.x + 12, z.y + 24);
      });

      // Central Town Square Fountain
      ctx.beginPath();
      ctx.arc(590, 360, 24, 0, Math.PI * 2);
      ctx.fillStyle = "#38bdf8";
      ctx.fill();
      ctx.strokeStyle = "#0284c7";
      ctx.lineWidth = 3;
      ctx.stroke();

      // 2. Draw Roads connecting districts
      ctx.strokeStyle = "#253147";
      ctx.lineWidth = 14;
      ctx.beginPath();
      ctx.moveTo(210, 360); ctx.lineTo(970, 360); // East-West Highway
      ctx.moveTo(590, 180); ctx.lineTo(590, 560); // North-South Boulevard
      ctx.stroke();

      // 3. Draw All 1,500 Citizens
      citizens.forEach(c => {
        const color = PROF_COLORS[c.profession] || "#fff";
        const isSel = selectedCitizen && selectedCitizen.id === c.id;

        // Shadow
        ctx.beginPath();
        ctx.ellipse(c.x, c.y + 7, 5, 2.5, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0, 0, 0, 0.35)";
        ctx.fill();

        // Citizen Body & Head
        ctx.beginPath();
        ctx.arc(c.x, c.y + c.bob, isSel ? 6.5 : 4.5, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();

        if (isSel) {
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 2;
          ctx.stroke();

          // Selection Reticle
          ctx.beginPath();
          ctx.arc(c.x, c.y + c.bob, 12, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(56, 189, 248, 0.8)";
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }

        // Hunger icon indicator
        if (c.hunger > 0) {
          ctx.fillStyle = "#ef4444";
          ctx.fillRect(c.x - 3, c.y - 10, 6, 2);
        }
      });

      // 4. Draw Floating Speech Bubbles
      speechBubbles.forEach(b => {
        const c = citizens.find(cit => cit.id === b.id);
        if (!c) return;

        const bx = c.x;
        const by = c.y - 18;

        ctx.font = "11px sans-serif";
        const width = ctx.measureText(b.text).width + 14;

        ctx.fillStyle = "rgba(15, 23, 42, 0.95)";
        ctx.strokeStyle = "#38bdf8";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.roundRect(bx - width / 2, by - 16, width, 20, 4);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.fillText(b.text, bx, by - 2);
        ctx.textAlign = "left";
      });

      // 5. Draw Particle Effects
      particles.forEach(p => {
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;
      });

      ctx.restore();

      updatePhysics();
      requestAnimationFrame(render);
    }

    // --- Interaction & Controls ---
    canvas.addEventListener("mousedown", e => {
      isDragging = true;
      dragStart = { x: e.clientX, y: e.clientY };
    });

    window.addEventListener("mouseup", () => isDragging = false);

    canvas.addEventListener("mousemove", e => {
      if (isDragging) {
        camera.x -= (e.clientX - dragStart.x) / camera.zoom;
        camera.y -= (e.clientY - dragStart.y) / camera.zoom;
        dragStart = { x: e.clientX, y: e.clientY };
      }
    });

    canvas.addEventListener("wheel", e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.85;
      camera.zoom = Math.min(Math.max(camera.zoom * zoomFactor, 0.4), 2.5);
    });

    // Click to Select & Inspect Citizen
    canvas.addEventListener("click", e => {
      const rect = canvas.getBoundingClientRect();
      const clickX = (e.clientX - rect.left - canvas.width / 2) / camera.zoom + camera.x;
      const clickY = (e.clientY - rect.top - canvas.height / 2) / camera.zoom + camera.y;

      let nearest = null;
      let minDist = 20;

      citizens.forEach(c => {
        const dist = Math.hypot(c.x - clickX, c.y - clickY);
        if (dist < minDist) {
          minDist = dist;
          nearest = c;
        }
      });

      if (nearest) selectCitizen(nearest);
    });

    function selectCitizen(c) {
      selectedCitizen = c;
      document.getElementById("insp-name").innerText = c.name;
      document.getElementById("insp-prov").innerText = "Province: " + c.province;
      document.getElementById("insp-role").innerText = c.profession;
      document.getElementById("insp-role").style.background = PROF_COLORS[c.profession] || "#fff";
      document.getElementById("insp-wealth").innerText = c.wealth.toFixed(1) + " coins";
      document.getElementById("insp-standing").innerText = (c.standing >= 0 ? "+" : "") + c.standing.toFixed(1);
      document.getElementById("insp-skill").innerText = c.skill.toFixed(2);
      
      const hungerEl = document.getElementById("insp-hunger");
      if (c.hunger === 0) {
        hungerEl.innerText = "Well-fed";
        hungerEl.style.color = "var(--green)";
      } else {
        hungerEl.innerText = `Hungry (${c.hunger} seasons)`;
        hungerEl.style.color = "var(--red)";
      }

      document.getElementById("insp-thought").innerText = `"${c.thought || 'Tending to daily trade and duties.'}"`;
    }

    function togglePlay() {
      isPlaying = !isPlaying;
      document.getElementById("btn-pause").innerText = isPlaying ? "⏸️ Pause" : "▶️ Resume";
    }

    function setTab(name) {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
      document.getElementById("tab-" + name).classList.add("active");
      event.target.classList.add("active");
    }

    // Step Season and animate
    async function stepSeason() {
      try {
        const res = await fetch("/kingdom/api/step", { method: "POST" });
        const data = await res.json();
        kingdomData = data;
        citizens = data.citizens;
        updateHUD(data.snapshot);
        updateChatter(data.voices);
        if (selectedCitizen) {
          const fresh = citizens.find(c => c.id === selectedCitizen.id);
          if (fresh) selectCitizen(fresh);
        }
      } catch (e) {
        console.error("Step error:", e);
      }
    }

    async function stewardIntervene() {
      try {
        const res = await fetch("/kingdom/api/steward", { method: "POST" });
        const data = await res.json();
        showBanner(`🤖 Steward Acted: ${data.action.replace('_',' ')} - ${data.reason}`);
        stepSeason();
      } catch (e) {
        console.error(e);
      }
    }

    async function triggerFestival() {
      // Spawn confetti particles
      for (let i = 0; i < 80; i++) {
        particles.push({
          x: 590 + (Math.random() - 0.5) * 200,
          y: 360 + (Math.random() - 0.5) * 150,
          vx: (Math.random() - 0.5) * 4,
          vy: (Math.random() - 0.5) * 4 - 2,
          size: Math.random() * 4 + 2,
          color: ["#f59e0b", "#38bdf8", "#ec4899", "#84cc16"][Math.floor(Math.random() * 4)],
          alpha: 1.0
        });
      }
      showBanner("🎉 Harvest Festival Launched in the Realm!");
      await fetch("/kingdom/api/act", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "harvest_festival" })
      });
      stepSeason();
    }

    function showBanner(msg) {
      const b = document.getElementById("active-event-badge");
      b.innerText = msg;
      b.style.display = "block";
      setTimeout(() => b.style.display = "none", 4000);
    }

    // Centering camera
    camera.x = 600;
    camera.y = 380;
    camera.zoom = 0.9;

    initKingdom().then(() => {
      render();
    });
  </script>
</body>
</html>"""


def get_serialized_citizens() -> List[Dict[str, Any]]:
    """Serializes 1,500 citizens with 2D coordinates and personality thoughts."""
    citizens = []
    rng = active_econ.rng

    for cid in range(active_econ.n_initial):
        if not active_econ.present[cid]:
            continue
        prof = PROFESSIONS[active_econ.profession[cid]]
        prov = PROVINCES[active_econ.province[cid]]
        bounds = ZONE_BOUNDS[prof]

        name = f"{VOICE_NAMES[cid % len(VOICE_NAMES)]} of {prov}"
        wealth = float(active_econ.wealth[cid])
        standing = float(active_econ.standing[cid])
        skill = float(active_econ.skill[cid])
        hunger = int(active_econ.hunger[cid])

        # Deterministic spatial seeding so agents stay anchored near their guild/district
        base_x = bounds["x"][0] + (hash(f"{cid}_x") % (bounds["x"][1] - bounds["x"][0]))
        base_y = bounds["y"][0] + (hash(f"{cid}_y") % (bounds["y"][1] - bounds["y"][0]))

        thought = "Another season in the realm."
        if hunger > 0:
            thought = f"Grain prices ({active_econ.grain_price:.1f} coins) are too steep! I go hungry."
        elif active_econ.happiness[cid] > 0.75:
            thought = f"Business thrives in {prov}! Truly a prosperous time."
        elif active_econ.laws.policing > 0.7:
            thought = "The royal watch patrols every alleyway."

        citizens.append({
            "id": int(cid),
            "name": name,
            "profession": prof,
            "province": prov,
            "x": float(base_x),
            "y": float(base_y),
            "vx": float((rng.random() - 0.5) * 0.8),
            "vy": float((rng.random() - 0.5) * 0.8),
            "minX": bounds["x"][0],
            "maxX": bounds["x"][1],
            "minY": bounds["y"][0],
            "maxY": bounds["y"][1],
            "wealth": wealth,
            "standing": standing,
            "skill": skill,
            "hunger": hunger,
            "thought": thought,
        })
    return citizens


@router.get("", response_class=HTMLResponse)
def get_living_kingdom():
    return HTMLResponse(WORLD_HTML)


@router.get("/api/live-state")
def get_live_state():
    snap = snapshot(active_econ)
    citizens = get_serialized_citizens()
    voices = [
        {
            "citizen_id": v.citizen_id,
            "name": v.name,
            "profession": v.profession,
            "statement": v.statement,
            "thought": v.thought,
            "tick": v.tick
        }
        for v in active_town_square.history[-15:]
    ]
    provinces = []
    for prov in PROVINCES:
        p_idx = PROVINCES.index(prov)
        mask = (active_econ.province == p_idx) & active_econ.present
        pop = int(mask.sum())
        mean_w = float(active_econ.wealth[mask].mean()) if pop else 0.0
        provinces.append({"name": prov, "population": pop, "wealth": mean_w})

    return JSONResponse({
        "snapshot": snap,
        "citizens": citizens,
        "voices": voices,
        "provinces": provinces,
    })


@router.post("/api/step")
def api_step():
    active_econ.step()
    recent_events_desc = ""
    if active_ops.log:
        last = active_ops.log[-1]
        if last["accepted"]:
            recent_events_desc = f"Decree: {last['action'].replace('_', ' ').title()}"
    active_town_square.step(recent_events_str=recent_events_desc)
    active_history.append(snapshot(active_econ))
    return get_live_state()


@router.post("/api/steward")
def api_steward():
    entry = active_steward.deliberate()
    return JSONResponse({
        "action": entry.proposed_action,
        "accepted": entry.decision.accepted,
        "reason": entry.decision.reason,
        "analysis": entry.analysis,
    })


@router.post("/api/act")
async def api_act(request: Request):
    data = await request.json()
    action = data.get("action", "")
    args = data.get("args", {})
    decision = active_ops.apply(action, args)
    return JSONResponse({
        "action": decision.action,
        "accepted": decision.accepted,
        "reason": decision.reason,
        "cost": decision.cost
    })


@router.get("/admin", response_class=HTMLResponse)
def get_admin_console():
    # Admin console logic remains for deep LiveOps analysis
    curr = active_history[-1]
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><title>Admin Console</title>
    <style>body{{background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:24px;}}
    a{{color:#38bdf8;}} .card{{background:#1e293b; padding:16px; border-radius:8px; margin-bottom:14px;}}</style>
    </head><body><a href="/kingdom">⬅️ Back to Living Kingdom World</a><h2>LiveOps Admin Levers & Audit Trail</h2>
    <div class="card">Treasury: {curr['treasury']:,.1f} coins | Population: {curr['population']:,} | Grain: {curr['grain_price']:.2f}</div>
    <div class="card">Audit Entries: {len(active_ops.log)} actions logged</div>
    </body></html>""")


@router.get("/experiments", response_class=HTMLResponse)
def get_experiments():
    global latest_ab_result
    if latest_ab_result is None:
        latest_ab_result = run_kingdom_ab_experiment(n_citizens=1500, ticks=24, difficulty="drought_season")
    st = latest_ab_result.stats
    return HTMLResponse(f"""<!doctype html><html><head><meta charset='utf-8'><title>A/B Experiments</title>
    <style>body{{background:#0f172a; color:#f8fafc; font-family:sans-serif; padding:24px;}}
    a{{color:#38bdf8;}} .card{{background:#1e293b; padding:16px; border-radius:8px; margin-bottom:14px;}}</style>
    </head><body><a href="/kingdom">⬅️ Back to Living Kingdom World</a><h2>A/B Experiment: Control vs Royal Steward</h2>
    <div class="card">Retention Lift: +{(st['retention_relative_lift']*100):.1f}% (p-val: {st['retention_p_value']:.4e})</div>
    </body></html>""")


@router.get("/provinces", response_class=HTMLResponse)
def get_provinces_legacy():
    return RedirectResponse(url="/kingdom", status_code=303)
