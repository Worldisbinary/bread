"""Reddit-Themed Clash of Clans Kingdom Simulation (r/kingdom).

Fuses:
1. Reddit-style feeds, upvoting/downvoting karma mechanics, subreddits (r/wheatfields, r/bazaar, r/garrison, r/chancery).
2. Clash-of-Clans style isometric/2D kingdom view with Town Hall, Elixir/Gold collectors, Barracks, and isometric building structures.
3. RPG Character Agents:
   - Real-world cities (Bengaluru, Mumbai, Delhi, Tokyo, London, New York)
   - Real timestamps (epoch to calendar simulation)
   - Individual abilities, health, special powers, and explicit political/economic ideologies (Capitalist, Socialist, Anarchist, Authoritarian, Technocrat).
   - Dynamic Karma system: karma rises when agents contribute, build, or receive upvotes, and falls when they engage in crime or toxic behavior.
4. Setup Modal: Allows user to configure initial population (50 to 2,000), starting real-world location/city, and starting timestamp/era.
"""

import json
import time
from html import escape
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .economy import Economy, PROFESSIONS, PROVINCES
from .events import ACTIONS, LiveOps
from .experiment import run_kingdom_ab_experiment
from .laws import LAW_SETS
from .metrics import snapshot
from .steward import RoyalSteward
from .voices import TownSquare

router = APIRouter(prefix="/kingdom")

# Available Real-world Origins
REAL_WORLD_CITIES = [
    {"name": "Bengaluru", "region": "Karnataka, India", "lore": "City of tech builders and bold artisans"},
    {"name": "Mumbai", "region": "Maharashtra, India", "lore": "Capital of commerce, sea trade and hustle"},
    {"name": "Delhi", "region": "NCR, India", "lore": "Ancient seat of power, politics and law"},
    {"name": "London", "region": "UK", "lore": "Old-world guilds, parliament and maritime banking"},
    {"name": "Tokyo", "region": "Japan", "lore": "High craftsmanship, discipline and advanced order"},
    {"name": "New York", "region": "USA", "lore": "Free markets, high ambition and diverse cultures"},
]

IDEOLOGIES = [
    {"name": "Free-Market Capitalist", "color": "#f59e0b", "icon": "📈", "belief": "Prosperity through deregulation, trade, and low royal taxes."},
    {"name": "Democratic Socialist", "color": "#ef4444", "icon": "🤝", "belief": "Equal grain distribution, state subsidies, and worker solidarity."},
    {"name": "Authoritarian Loyalist", "color": "#8b5cf6", "icon": "🛡️", "belief": "Order, heavy policing, and absolute obedience to the Crown."},
    {"name": "Technocrat Builder", "color": "#06b6d4", "icon": "⚙️", "belief": "Scientific agriculture, infrastructure, and merit-based rank."},
    {"name": "Communal Traditionalist", "color": "#84cc16", "icon": "🌾", "belief": "Harmony with the land, agrarian guild rules, and quiet village life."}
]

HERO_ABILITIES = {
    "farmer": {"name": "Bountiful Harvest", "power": "+35% grain yield", "icon": "🌾"},
    "labourer": {"name": "Rapid Construction", "power": "Accelerates building repairs", "icon": "🔨"},
    "artisan": {"name": "Mastercraft", "power": "+50% goods market value", "icon": "✨"},
    "merchant": {"name": "Market Arbitrage", "power": "Steals trade margins during spikes", "icon": "💰"},
    "clerk": {"name": "Ledger Audit", "power": "Detects embezzlement and tax fraud", "icon": "📜"},
    "soldier": {"name": "Shield Wall", "power": "Deters district crime and quells unrest", "icon": "⚔️"},
    "civil_servant": {"name": "Royal Edict", "power": "Boosts local province compliance", "icon": "👑"},
    "teacher": {"name": "Inspire Youth", "power": "+20% citizen skill progression", "icon": "📖"}
}

# In-memory World Instance
CURRENT_CITY = "Bengaluru"
STARTING_TIMESTAMP = "2026-11-08 12:00:00"
ACTIVE_POPULATION = 300

active_econ = Economy(n=ACTIVE_POPULATION, laws=LAW_SETS["liberal"], seed=42)
active_ops = LiveOps(active_econ)
active_steward = RoyalSteward(active_econ, active_ops)
active_town_square = TownSquare(active_econ, sample_size=10)
active_history = [snapshot(active_econ)]
citizen_metadata: Dict[int, Dict[str, Any]] = {}
user_votes: Dict[str, int] = {}  # item_id -> vote value

# CoC Style Buildings
COC_BUILDINGS = [
    {"type": "Town Hall (Level 9)", "x": 580, "y": 320, "w": 90, "h": 90, "color": "#d97706", "roof": "#b45309", "sub": "r/all"},
    {"type": "Gold Storage & Bank", "x": 780, "y": 360, "w": 65, "h": 65, "color": "#eab308", "roof": "#ca8a04", "sub": "r/economy"},
    {"type": "Elixir Granary Silo", "x": 260, "y": 360, "w": 65, "h": 65, "color": "#ec4899", "roof": "#db2777", "sub": "r/wheatfields"},
    {"type": "Barracks & Drill Yard", "x": 820, "y": 140, "w": 75, "h": 75, "color": "#ef4444", "roof": "#dc2626", "sub": "r/garrison"},
    {"type": "Laboratory & Academy", "x": 240, "y": 140, "w": 75, "h": 75, "color": "#3b82f6", "roof": "#2563eb", "sub": "r/academy"},
    {"type": "Artisan Guild Forge", "x": 480, "y": 120, "w": 70, "h": 70, "color": "#06b6d4", "roof": "#0891b2", "sub": "r/artisan"},
    {"type": "Merchant Trading Post", "x": 660, "y": 120, "w": 70, "h": 70, "color": "#10b981", "roof": "#059669", "sub": "r/bazaar"},
]


def init_citizen_metadata(n: int, city: str):
    global citizen_metadata
    citizen_metadata.clear()
    rng = np.random.default_rng(42)
    names = [
        "Aarav", "Rohan", "Vikram", "Kabir", "Arjun", "Aditya", "Dev", "Reyansh",
        "Ananya", "Diya", "Isha", "Mira", "Pooja", "Sanya", "Tara", "Zoya",
        "Marcus", "Leo", "Sora", "Kenji", "Arthur", "Chloe", "Freja", "Astrid"
    ]
    for cid in range(n):
        prof = PROFESSIONS[active_econ.profession[cid]]
        ideo = IDEOLOGIES[int(rng.integers(0, len(IDEOLOGIES)))]
        ability = HERO_ABILITIES[prof]
        handle = f"u/{names[cid % len(names)].lower()}_{cid}"
        citizen_metadata[cid] = {
            "name": f"{names[cid % len(names)]} of {city}",
            "handle": handle,
            "origin_city": city,
            "ideology": ideo,
            "ability": ability,
            "hp": int(rng.integers(85, 120)),
            "max_hp": 120,
            "upvotes_given": 0,
            "upvotes_received": int(rng.integers(2, 45)),
            "karma": int(active_econ.standing[cid] * 10 + rng.integers(10, 50)),
        }


init_citizen_metadata(ACTIVE_POPULATION, CURRENT_CITY)

REDDIT_COC_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>r/kingdom - Reddit & Clash of Clans Agentic World</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --reddit-orange: #ff4500;
      --reddit-dark: #0e1113;
      --reddit-card: #181c1f;
      --reddit-border: #282f34;
      --reddit-text: #d7dadc;
      --reddit-muted: #818384;
      --reddit-gold: #ffd700;
      --coc-grass: #1b381e;
      --coc-border: #2b592f;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--reddit-dark);
      color: var(--reddit-text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      overflow: hidden;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }

    /* Reddit-Style Navigation Bar */
    header {
      background: #1a1a1b;
      border-bottom: 1px solid var(--reddit-border);
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      z-index: 100;
    }
    .reddit-logo {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 700;
      font-size: 17px;
      color: #fff;
      text-decoration: none;
    }
    .reddit-icon {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: var(--reddit-orange);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 20px;
    }
    .community-tag {
      font-size: 14px;
      color: var(--reddit-text);
      background: #272729;
      padding: 4px 10px;
      border-radius: 999px;
      border: 1px solid var(--reddit-border);
    }
    .header-actions {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .btn-reddit {
      background: var(--reddit-orange);
      color: #fff;
      border: none;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: filter 0.2s;
    }
    .btn-reddit:hover { filter: brightness(1.15); }
    .btn-secondary {
      background: #272729;
      color: #fff;
      border: 1px solid var(--reddit-border);
    }
    .btn-secondary:hover { background: #343536; }

    /* Main Screen Split: Left = Clash of Clans Canvas, Right = Reddit Feed & Inspector */
    #layout-split {
      display: flex;
      flex: 1;
      height: calc(100vh - 48px);
      position: relative;
    }

    #game-canvas-container {
      flex: 1;
      position: relative;
      background: var(--coc-grass);
      overflow: hidden;
      cursor: grab;
    }
    #game-canvas-container:active { cursor: grabbing; }
    canvas { display: block; width: 100%; height: 100%; }

    /* Clash of Clans HUD overlay */
    .coc-hud {
      position: absolute;
      top: 14px;
      left: 14px;
      display: flex;
      gap: 12px;
      pointer-events: none;
    }
    .coc-pill {
      background: rgba(14, 17, 19, 0.9);
      border: 2px solid #5a4a2b;
      box-shadow: 0 4px 10px rgba(0,0,0,0.5);
      border-radius: 12px;
      padding: 6px 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
      color: #fff;
    }

    /* Reddit Feed & Character Inspector Drawer */
    #reddit-sidebar {
      width: 440px;
      background: var(--reddit-dark);
      border-left: 1px solid var(--reddit-border);
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .sub-tabs {
      display: flex;
      border-bottom: 1px solid var(--reddit-border);
      background: #121417;
    }
    .sub-tab {
      flex: 1;
      padding: 12px 8px;
      text-align: center;
      font-size: 13px;
      font-weight: 700;
      color: var(--reddit-muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .sub-tab.active {
      color: #fff;
      border-bottom: 2px solid var(--reddit-orange);
      background: var(--reddit-card);
    }
    .tab-content {
      flex: 1;
      overflow-y: auto;
      padding: 14px;
      display: none;
      flex-direction: column;
      gap: 12px;
    }
    .tab-content.active { display: flex; }

    /* Reddit Post Card */
    .reddit-post {
      background: var(--reddit-card);
      border: 1px solid var(--reddit-border);
      border-radius: 8px;
      display: flex;
      overflow: hidden;
      transition: border-color 0.2s;
    }
    .reddit-post:hover { border-color: #4f5356; }
    .vote-sidebar {
      width: 42px;
      background: rgba(0,0,0,0.15);
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 0;
      gap: 4px;
    }
    .vote-btn {
      background: none;
      border: none;
      color: var(--reddit-muted);
      cursor: pointer;
      font-size: 16px;
      transition: color 0.15s;
    }
    .vote-btn:hover { color: var(--reddit-orange); }
    .vote-btn.down:hover { color: #7193ff; }
    .vote-score { font-size: 12px; font-weight: 700; color: #fff; }
    .post-content {
      flex: 1;
      padding: 10px 12px;
    }
    .post-meta {
      font-size: 11px;
      color: var(--reddit-muted);
      display: flex;
      gap: 6px;
      align-items: center;
      margin-bottom: 6px;
      flex-wrap: wrap;
    }
    .sub-pill {
      font-weight: 700;
      color: #fff;
    }
    .post-author { color: var(--reddit-muted); }
    .post-title {
      font-size: 14px;
      font-weight: 600;
      color: #fff;
      margin-bottom: 6px;
      line-height: 1.4;
    }
    .post-thought {
      font-size: 12px;
      color: #ffd700;
      background: rgba(255, 215, 0, 0.08);
      border-left: 3px solid #ffd700;
      padding: 6px 8px;
      border-radius: 4px;
      margin-top: 6px;
      font-style: italic;
    }
    .ideology-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
      color: #fff;
    }

    /* CoC RPG Character Sheet */
    .character-sheet {
      background: var(--reddit-card);
      border: 2px solid #5a4a2b;
      border-radius: 12px;
      padding: 16px;
    }
    .char-avatar-row {
      display: flex;
      gap: 14px;
      align-items: center;
      margin-bottom: 14px;
    }
    .char-avatar {
      width: 60px;
      height: 60px;
      border-radius: 12px;
      border: 3px solid var(--reddit-gold);
      background: #2a3547;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 28px;
    }
    .hp-bar-bg {
      background: #331515;
      border: 1px solid #662020;
      border-radius: 6px;
      height: 12px;
      width: 100%;
      overflow: hidden;
      margin-top: 4px;
    }
    .hp-bar-fill {
      background: linear-gradient(90deg, #22c55e, #84cc16);
      height: 100%;
      width: 85%;
    }
    .stat-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      font-size: 13px;
      margin: 12px 0;
    }
    .stat-item {
      background: rgba(0,0,0,0.25);
      border: 1px solid var(--reddit-border);
      border-radius: 6px;
      padding: 8px;
    }
    .stat-label { font-size: 11px; color: var(--reddit-muted); }
    .stat-num { font-size: 14px; font-weight: 700; color: #fff; }

    /* Setup Modal */
    #setup-modal {
      position: fixed;
      top: 0; left: 0; width: 100vw; height: 100vh;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(5px);
      z-index: 1000;
      display: none;
      align-items: center;
      justify-content: center;
    }
    .modal-box {
      background: #1a1a1b;
      border: 2px solid var(--reddit-border);
      border-radius: 12px;
      width: 480px;
      max-width: 90vw;
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .form-group label {
      font-size: 13px;
      font-weight: 700;
      color: var(--reddit-text);
    }
    .form-control {
      background: #272729;
      border: 1px solid var(--reddit-border);
      color: #fff;
      padding: 10px 12px;
      border-radius: 6px;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <header>
    <div style="display:flex; align-items:center; gap:12px;">
      <a href="/kingdom" class="reddit-logo">
        <div class="reddit-icon">🛡️</div>
        <span>r/kingdom</span>
      </a>
      <div class="community-tag" id="city-badge">📍 Bengaluru, India</div>
      <div class="community-tag" id="time-badge">⏳ Season 0 · 2026-11-08</div>
    </div>

    <div class="header-actions">
      <button class="btn-reddit btn-secondary" onclick="openSetupModal()">⚙️ World Config</button>
      <button class="btn-reddit" onclick="stepSeason()">⏭️ Advance Season</button>
      <button class="btn-reddit" style="background:#8b5cf6;" onclick="triggerSteward()">🤖 Steward LiveOps</button>
      <button class="btn-reddit" style="background:#eab308; color:#000;" onclick="triggerFestival()">🎉 Harvest Feast</button>
    </div>
  </header>

  <div id="layout-split">
    <!-- Clash of Clans Canvas World -->
    <div id="game-canvas-container">
      <div class="coc-hud">
        <div class="coc-pill">🏰 Town Hall 9</div>
        <div class="coc-pill">👥 Citizens: <span id="hud-pop">300</span></div>
        <div class="coc-pill">💰 Treasury: <span id="hud-gold">4,500</span></div>
        <div class="coc-pill">🌾 Granary: <span id="hud-elixir">1.00</span></div>
      </div>
      <canvas id="cocCanvas"></canvas>
    </div>

    <!-- Reddit Post Feed & Inspector Drawer -->
    <div id="reddit-sidebar">
      <div class="sub-tabs">
        <div class="sub-tab active" onclick="switchTab('feed')">Hot Discussions</div>
        <div class="sub-tab" onclick="switchTab('character')">Character Sheet</div>
        <div class="sub-tab" onclick="switchTab('ideology')">Ideology Compass</div>
      </div>

      <div id="pane-feed" class="tab-content active">
        <!-- Rendered Reddit Posts -->
        <div id="posts-container" style="display:flex; flex-direction:column; gap:10px;"></div>
      </div>

      <div id="pane-character" class="tab-content">
        <div id="character-detail" class="character-sheet">
          <div class="char-avatar-row">
            <div class="char-avatar" id="c-avatar">⚔️</div>
            <div style="flex:1;">
              <div style="font-size:16px; font-weight:700;" id="c-name">Aarav of Bengaluru</div>
              <div style="font-size:12px; color:var(--reddit-muted);" id="c-handle">u/aarav_0</div>
              <div class="hp-bar-bg">
                <div class="hp-bar-fill" id="c-hp-fill"></div>
              </div>
            </div>
          </div>

          <div style="margin-bottom:10px;">
            <span class="ideology-badge" id="c-ideo" style="background:#f59e0b;">📈 Free-Market Capitalist</span>
          </div>

          <div class="stat-row">
            <div class="stat-item">
              <div class="stat-label">HERO ABILITY</div>
              <div class="stat-num" id="c-ability">Mastercraft</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">KARMA SCORE</div>
              <div class="stat-num" id="c-karma" style="color:var(--reddit-orange)">124</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">COINS / WEALTH</div>
              <div class="stat-num" id="c-wealth">18.5</div>
            </div>
            <div class="stat-item">
              <div class="stat-label">HUNGER STATUS</div>
              <div class="stat-num" id="c-hunger" style="color:#22c55e">Well-Fed</div>
            </div>
          </div>

          <div style="font-size:12px; color:var(--reddit-muted); margin-bottom:4px;">Secret Agent Thought:</div>
          <div class="post-thought" id="c-thought">"Grain prices hold strong. Time to reinvest my trade margin."</div>
        </div>

        <div style="font-size:12px; color:var(--reddit-muted); text-align:center;">
          💡 <em>Click any Clash of Clans character roaming the base to inspect their abilities!</em>
        </div>
      </div>

      <div id="pane-ideology" class="tab-content">
        <div style="font-size:14px; font-weight:700; margin-bottom:8px;">Faction Ideology Breakdown</div>
        <div id="ideology-list" style="display:flex; flex-direction:column; gap:10px;"></div>
      </div>
    </div>
  </div>

  <!-- World Setup Modal -->
  <div id="setup-modal">
    <div class="modal-box">
      <h3 style="color:#fff;">⚙️ Configure Living Kingdom</h3>
      
      <div class="form-group">
        <label>Initial Population</label>
        <select class="form-control" id="cfg-pop">
          <option value="150">150 Citizens (Fastest)</option>
          <option value="300" selected>300 Citizens (Balanced)</option>
          <option value="600">600 Citizens</option>
          <option value="1500">1,500 Citizens (Full Realm)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Real-World Origin & Culture</label>
        <select class="form-control" id="cfg-city">
          <option value="Bengaluru" selected>Bengaluru, India (Tech & Trade Hub)</option>
          <option value="Mumbai">Mumbai, India (Financial & Sea Port)</option>
          <option value="Delhi">Delhi, India (Imperial Seat of Governance)</option>
          <option value="Tokyo">Tokyo, Japan (Discipline & High Tech)</option>
          <option value="London">London, UK (Old-world Guilds & Royal Bank)</option>
          <option value="New York">New York, USA (Free-Market Capital)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Starting Timestamp</label>
        <input type="datetime-local" class="form-control" id="cfg-time" value="2026-11-08T12:00">
      </div>

      <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:10px;">
        <button class="btn-reddit btn-secondary" onclick="closeSetupModal()">Cancel</button>
        <button class="btn-reddit" onclick="applyConfig()">Apply & Re-Seed World</button>
      </div>
    </div>
  </div>

  <script>
    const canvas = document.getElementById("cocCanvas");
    const ctx = canvas.getContext("2d");

    let camera = { x: 550, y: 350, zoom: 0.95 };
    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let citizens = [];
    let buildings = [];
    let selectedAgent = null;
    let particles = [];
    let floatingBubbles = [];

    const HERO_ICONS = {
      farmer: "🌾",
      labourer: "🔨",
      artisan: "⚒️",
      merchant: "💰",
      clerk: "📜",
      soldier: "⚔️",
      civil_servant: "👑",
      teacher: "📖"
    };

    function resize() {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight;
    }
    window.addEventListener("resize", resize);
    resize();

    // Fetch World State
    async function loadKingdom() {
      const res = await fetch("/kingdom/api/coc-state");
      const data = await res.json();
      citizens = data.citizens;
      buildings = data.buildings;
      document.getElementById("hud-pop").innerText = data.snapshot.population;
      document.getElementById("hud-gold").innerText = Math.round(data.snapshot.treasury);
      document.getElementById("hud-elixir").innerText = data.snapshot.grain_price.toFixed(2);
      document.getElementById("city-badge").innerText = "📍 " + data.city;
      document.getElementById("time-badge").innerText = `⏳ Season ${data.snapshot.tick} · ${data.timestamp}`;

      renderFeed(data.posts);
      renderIdeologies(data.ideology_counts);
      if (citizens.length > 0) selectAgent(citizens[0]);
    }

    function renderFeed(posts) {
      const container = document.getElementById("posts-container");
      container.innerHTML = "";
      posts.forEach(p => {
        const div = document.createElement("div");
        div.className = "reddit-post";
        div.innerHTML = `
          <div class="vote-sidebar">
            <button class="vote-btn" onclick="voteItem('${p.id}', 1, this)">▲</button>
            <div class="vote-score" id="score-${p.id}">${p.karma}</div>
            <button class="vote-btn down" onclick="voteItem('${p.id}', -1, this)">▼</button>
          </div>
          <div class="post-content">
            <div class="post-meta">
              <span class="sub-pill">${p.subreddit}</span>
              <span>•</span>
              <span class="post-author">${p.author}</span>
              <span class="ideology-badge" style="background:${p.ideology_color}">${p.ideology_icon} ${p.ideology}</span>
            </div>
            <div class="post-title">"${p.statement}"</div>
            <div class="post-thought">💭 <em>Private Thought: ${p.thought}</em></div>
          </div>
        `;
        container.appendChild(div);

        // Also add floating speech bubble to game canvas
        const ag = citizens.find(c => c.id === p.citizen_id);
        if (ag && Math.random() < 0.6) {
          floatingBubbles.push({
            id: ag.id,
            text: p.statement.slice(0, 32) + "...",
            timer: 240
          });
        }
      });
    }

    function renderIdeologies(counts) {
      const container = document.getElementById("ideology-list");
      container.innerHTML = "";
      for (const [name, count] of Object.entries(counts)) {
        const item = document.createElement("div");
        item.className = "stat-item";
        item.innerHTML = `
          <div class="stat-label">${name}</div>
          <div class="stat-num">${count} Citizens (${((count/citizens.length)*100).toFixed(0)}%)</div>
        `;
        container.appendChild(item);
      }
    }

    async function voteItem(itemId, val, btn) {
      const res = await fetch("/kingdom/api/vote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: itemId, value: val })
      });
      const data = await res.json();
      document.getElementById(`score-${itemId}`).innerText = data.new_score;
      btn.style.color = val > 0 ? "var(--reddit-orange)" : "#7193ff";
    }

    // Animation & Physics Loop
    function update() {
      citizens.forEach(c => {
        c.x += c.vx;
        c.y += c.vy;
        if (c.x < c.minX || c.x > c.maxX) c.vx *= -1;
        if (c.y < c.minY || c.y > c.maxY) c.vy *= -1;

        if (Math.random() < 0.015) {
          c.vx = (Math.random() - 0.5) * 1.1;
          c.vy = (Math.random() - 0.5) * 1.1;
        }
        c.bob = Math.sin(Date.now() * 0.007 + c.id) * 2;
      });

      floatingBubbles.forEach(b => b.timer--);
      floatingBubbles = floatingBubbles.filter(b => b.timer > 0);

      particles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
        p.alpha -= 0.015;
      });
      particles = particles.filter(p => p.alpha > 0);
    }

    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();
      ctx.translate(canvas.width / 2, canvas.height / 2);
      ctx.scale(camera.zoom, camera.zoom);
      ctx.translate(-camera.x, -camera.y);

      // 1. Draw Clash of Clans Checkerboard Grass Grid
      const gridCount = 28;
      const tileSize = 42;
      for (let r = 0; r < gridCount; r++) {
        for (let col = 0; col < gridCount; col++) {
          ctx.fillStyle = (r + col) % 2 === 0 ? "#1b3d1f" : "#1f4724";
          ctx.fillRect(col * tileSize, r * tileSize, tileSize, tileSize);
        }
      }

      // Stone Walls surrounding base
      ctx.strokeStyle = "#475569";
      ctx.lineWidth = 6;
      ctx.strokeRect(100, 70, 960, 680);

      // 2. Draw Clash of Clans Buildings
      buildings.forEach(b => {
        // Base Drop Shadow
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        ctx.fillRect(b.x + 8, b.y + 8, b.w, b.h);

        // Building Walls
        ctx.fillStyle = b.color;
        ctx.fillRect(b.x, b.y, b.w, b.h);

        // Building Roof Accent
        ctx.fillStyle = b.roof;
        ctx.fillRect(b.x + 4, b.y + 4, b.w - 8, b.h * 0.4);

        // Subreddit Signboard
        ctx.fillStyle = "rgba(0,0,0,0.8)";
        ctx.fillRect(b.x, b.y - 18, b.w, 16);
        ctx.fillStyle = "#ff4500";
        ctx.font = "bold 11px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(b.sub, b.x + b.w / 2, b.y - 6);
        ctx.textAlign = "left";
      });

      // 3. Draw All Characters
      citizens.forEach(c => {
        const isSel = selectedAgent && selectedAgent.id === c.id;

        // Shadow
        ctx.beginPath();
        ctx.ellipse(c.x, c.y + 8, 6, 3, 0, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0,0,0,0.35)";
        ctx.fill();

        // Character Body (CoC Barbarian / Archer / Wizard styled circle)
        ctx.beginPath();
        ctx.arc(c.x, c.y + c.bob, isSel ? 9 : 6.5, 0, Math.PI * 2);
        ctx.fillStyle = c.color;
        ctx.fill();

        // Border highlighting ideology
        ctx.strokeStyle = c.ideology_color;
        ctx.lineWidth = isSel ? 3 : 1.5;
        ctx.stroke();

        // Hero Icon
        ctx.font = "10px sans-serif";
        ctx.fillText(HERO_ICONS[c.profession] || "⚔️", c.x - 5, c.y + c.bob - 9);

        // Karma Pill Indicator
        if (c.karma > 50) {
          ctx.fillStyle = "rgba(255, 215, 0, 0.85)";
          ctx.beginPath();
          ctx.arc(c.x + 8, c.y - 2, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      });

      // 4. Floating Speech Bubbles
      floatingBubbles.forEach(b => {
        const ag = citizens.find(c => c.id === b.id);
        if (!ag) return;
        ctx.font = "11px sans-serif";
        const width = ctx.measureText(b.text).width + 16;
        ctx.fillStyle = "rgba(24, 28, 31, 0.95)";
        ctx.strokeStyle = "#ff4500";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(ag.x - width / 2, ag.y - 24, width, 20, 6);
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = "#fff";
        ctx.textAlign = "center";
        ctx.fillText(b.text, ag.x, ag.y - 10);
        ctx.textAlign = "left";
      });

      // 5. Particles
      particles.forEach(p => {
        ctx.fillStyle = p.color;
        ctx.globalAlpha = p.alpha;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 1.0;
      });

      ctx.restore();

      update();
      requestAnimationFrame(draw);
    }

    // Controls & Selection
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
      camera.zoom = Math.min(Math.max(camera.zoom * (e.deltaY < 0 ? 1.1 : 0.9), 0.4), 2.2);
    });

    canvas.addEventListener("click", e => {
      const rect = canvas.getBoundingClientRect();
      const clickX = (e.clientX - rect.left - canvas.width / 2) / camera.zoom + camera.x;
      const clickY = (e.clientY - rect.top - canvas.height / 2) / camera.zoom + camera.y;

      let nearest = null;
      let minDist = 22;
      citizens.forEach(c => {
        const d = Math.hypot(c.x - clickX, c.y - clickY);
        if (d < minDist) {
          minDist = d;
          nearest = c;
        }
      });
      if (nearest) selectAgent(nearest);
    });

    function selectAgent(ag) {
      selectedAgent = ag;
      document.getElementById("c-name").innerText = ag.name;
      document.getElementById("c-handle").innerText = ag.handle;
      document.getElementById("c-avatar").innerText = HERO_ICONS[ag.profession] || "⚔️";
      document.getElementById("c-hp-fill").style.width = (ag.hp / ag.max_hp * 100) + "%";
      document.getElementById("c-ideo").innerText = `${ag.ideology_icon} ${ag.ideology}`;
      document.getElementById("c-ideo").style.background = ag.ideology_color;
      document.getElementById("c-ability").innerText = ag.ability.name;
      document.getElementById("c-karma").innerText = ag.karma;
      document.getElementById("c-wealth").innerText = ag.wealth.toFixed(1);
      document.getElementById("c-hunger").innerText = ag.hunger === 0 ? "Well-Fed" : "Hungry";
      document.getElementById("c-hunger").style.color = ag.hunger === 0 ? "#22c55e" : "#ef4444";
      document.getElementById("c-thought").innerText = `"${ag.thought}"`;
    }

    function switchTab(tab) {
      document.querySelectorAll(".sub-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      event.target.classList.add("active");
      document.getElementById("pane-" + tab).classList.add("active");
    }

    function openSetupModal() {
      document.getElementById("setup-modal").style.display = "flex";
    }
    function closeSetupModal() {
      document.getElementById("setup-modal").style.display = "none";
    }

    async function applyConfig() {
      const pop = parseInt(document.getElementById("cfg-pop").value);
      const city = document.getElementById("cfg-city").value;
      const time = document.getElementById("cfg-time").value;

      await fetch("/kingdom/api/reconfigure", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ population: pop, city: city, timestamp: time })
      });
      closeSetupModal();
      loadKingdom();
    }

    async function stepSeason() {
      await fetch("/kingdom/api/step", { method: "POST" });
      loadKingdom();
    }

    async function triggerSteward() {
      const res = await fetch("/kingdom/api/steward", { method: "POST" });
      const data = await res.json();
      alert(`🤖 Royal Steward Decree: ${data.action.replace('_', ' ').toUpperCase()}\nRationale: ${data.analysis}`);
      loadKingdom();
    }

    async function triggerFestival() {
      for (let i = 0; i < 90; i++) {
        particles.push({
          x: 580 + (Math.random() - 0.5) * 300,
          y: 350 + (Math.random() - 0.5) * 200,
          vx: (Math.random() - 0.5) * 5,
          vy: (Math.random() - 0.5) * 5 - 2,
          size: Math.random() * 4 + 2,
          color: ["#ff4500", "#ffd700", "#38bdf8", "#22c55e"][Math.floor(Math.random() * 4)],
          alpha: 1.0
        });
      }
      await fetch("/kingdom/api/act", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "harvest_festival" })
      });
      loadKingdom();
    }

    loadKingdom().then(() => draw());
  </script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def get_reddit_coc_world():
    return HTMLResponse(REDDIT_COC_HTML)


@router.get("/api/coc-state")
def get_coc_state():
    snap = snapshot(active_econ)
    citizens_data = []

    # Map occupations to districts
    for cid in range(active_econ.n_initial):
        if not active_econ.present[cid]:
            continue
        meta = citizen_metadata.get(cid, {})
        prof = PROFESSIONS[active_econ.profession[cid]]

        # Anchor around thematic CoC buildings
        if prof in ("farmer", "labourer"):
            bx, by = 260, 360  # Near granaries
        elif prof in ("merchant", "artisan"):
            bx, by = 550, 150  # Near market forge
        elif prof in ("soldier", "civil_servant"):
            bx, by = 780, 240  # Near fortress
        else:
            bx, by = 580, 320  # Near Town Hall

        rng = active_econ.rng
        cx = bx + (hash(f"{cid}_x") % 180) - 90
        cy = by + (hash(f"{cid}_y") % 180) - 90

        thought = meta.get("thought", "Tending to my station in the realm.")
        if int(active_econ.hunger[cid]) > 0:
            thought = f"Food is too scarce ({active_econ.grain_price:.1f} coins). The crown must act!"
        elif active_econ.happiness[cid] > 0.7:
            thought = "My guild thrives under these current laws. Long live the realm!"

        citizens_data.append({
            "id": int(cid),
            "name": meta.get("name", f"Citizen {cid}"),
            "handle": meta.get("handle", f"u/citizen_{cid}"),
            "profession": prof,
            "ideology": meta.get("ideology", {}).get("name", "Capitalist"),
            "ideology_icon": meta.get("ideology", {}).get("icon", "📈"),
            "ideology_color": meta.get("ideology", {}).get("color", "#f59e0b"),
            "ability": meta.get("ability", {}),
            "hp": meta.get("hp", 100),
            "max_hp": meta.get("max_hp", 120),
            "karma": int(active_econ.standing[cid] * 10 + meta.get("upvotes_received", 0)),
            "wealth": float(active_econ.wealth[cid]),
            "hunger": int(active_econ.hunger[cid]),
            "thought": thought,
            "x": float(cx),
            "y": float(cy),
            "vx": float((rng.random() - 0.5) * 0.7),
            "vy": float((rng.random() - 0.5) * 0.7),
            "minX": max(cx - 70, 110),
            "maxX": min(cx + 70, 1040),
            "minY": max(cy - 70, 80),
            "maxY": min(cy + 70, 730),
            "color": "#e2e8f0"
        })

    # Generate Reddit discussions from voices
    posts = []
    subreddits = {
        "farmer": "r/wheatfields",
        "labourer": "r/wheatfields",
        "merchant": "r/bazaar",
        "artisan": "r/artisan",
        "clerk": "r/economy",
        "soldier": "r/garrison",
        "civil_servant": "r/chancery",
        "teacher": "r/academy"
    }

    for v in active_town_square.history[-16:]:
        meta = citizen_metadata.get(v.citizen_id, {})
        item_id = f"post_{v.citizen_id}_{v.tick}"
        score = user_votes.get(item_id, meta.get("karma", 15))
        posts.append({
            "id": item_id,
            "citizen_id": v.citizen_id,
            "author": meta.get("handle", f"u/citizen_{v.citizen_id}"),
            "subreddit": subreddits.get(v.profession, "r/all"),
            "statement": v.statement,
            "thought": v.thought,
            "ideology": meta.get("ideology", {}).get("name", "Capitalist"),
            "ideology_icon": meta.get("ideology", {}).get("icon", "📈"),
            "ideology_color": meta.get("ideology", {}).get("color", "#f59e0b"),
            "karma": score,
            "tick": v.tick
        })

    # Ideology count distribution
    ideology_counts = {}
    for meta in citizen_metadata.values():
        name = meta.get("ideology", {}).get("name", "Capitalist")
        ideology_counts[name] = ideology_counts.get(name, 0) + 1

    return JSONResponse({
        "snapshot": snap,
        "city": CURRENT_CITY,
        "timestamp": STARTING_TIMESTAMP,
        "citizens": citizens_data,
        "buildings": COC_BUILDINGS,
        "posts": posts,
        "ideology_counts": ideology_counts,
    })


@router.post("/api/vote")
async def api_vote(request: Request):
    data = await request.json()
    item_id = data.get("item_id")
    val = int(data.get("value", 1))
    user_votes[item_id] = user_votes.get(item_id, 10) + val
    return JSONResponse({"item_id": item_id, "new_score": user_votes[item_id]})


@router.post("/api/reconfigure")
async def api_reconfigure(request: Request):
    global active_econ, active_ops, active_steward, active_town_square, CURRENT_CITY, STARTING_TIMESTAMP, ACTIVE_POPULATION
    data = await request.json()
    ACTIVE_POPULATION = int(data.get("population", 300))
    CURRENT_CITY = data.get("city", "Bengaluru")
    STARTING_TIMESTAMP = data.get("timestamp", "2026-11-08 12:00:00")

    active_econ = Economy(n=ACTIVE_POPULATION, laws=LAW_SETS["liberal"], seed=int(time.time()))
    active_ops = LiveOps(active_econ)
    active_steward = RoyalSteward(active_econ, active_ops)
    active_town_square = TownSquare(active_econ, sample_size=10)
    init_citizen_metadata(ACTIVE_POPULATION, CURRENT_CITY)

    return JSONResponse({"status": "reconfigured", "population": ACTIVE_POPULATION, "city": CURRENT_CITY})


@router.post("/api/step")
def api_step():
    active_econ.step()
    recent = ""
    if active_ops.log and active_ops.log[-1]["accepted"]:
        recent = f"Decree: {active_ops.log[-1]['action']}"
    active_town_square.step(recent_events_str=recent)
    active_history.append(snapshot(active_econ))
    return get_coc_state()


@router.post("/api/steward")
def api_steward():
    entry = active_steward.deliberate()
    return JSONResponse({
        "action": entry.proposed_action,
        "analysis": entry.analysis,
        "reason": entry.decision.reason
    })


@router.post("/api/act")
async def api_act(request: Request):
    data = await request.json()
    action = data.get("action", "")
    decision = active_ops.apply(action)
    return JSONResponse({"action": decision.action, "accepted": decision.accepted})
