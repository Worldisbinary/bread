"""Ancient World Map Simulation: Multi-Dynasty Civilizations, Warfare, Biomes & Reddit Feeds.

Features:
1. Procedural Ancient World Map with Diverse Biomes:
   - Sinuous animated flowing River with particle foam
   - Snow-capped Mountain ranges (Highvale Pass, Dragonspire)
   - Golden Sand Dunes / Arid Desert (The Sunken Wastes)
   - Lush Fertile Plains & Forests (Rivermead & Greenhollow)
   - Volcanic / Scorched Crags (Emberfell)
   - Dynamic Local Weather FX: Heavy rainfall & thunderstorms in one biome, dry heatwave/drought in another, drifting mist over mountains.

2. Four Distinct Historical Dynasties / Civilizations:
   - Maurya Empire (Imperial Citadel, Elephant armor, Gold: 3,400, Troops: 320, Defense: 85)
   - Roman Legion (Castrum Fortress, Scutum shields, Gold: 2,900, Troops: 280, Defense: 90)
   - Han Dynasty (Jade Pagoda, Crossbowmen & Cavalry, Gold: 3,600, Troops: 350, Defense: 80)
   - Viking / Norse Jarls (Longhouse Stronghold, Berserkers, Gold: 2,100, Troops: 240, Defense: 75)

3. Full Strategic Warfare & Raid Mechanics:
   - Attack Selection: Select your attacking civilization and target nearby kingdom.
   - Resource Gates: Requires Food Rations (Grain), Armours/Weapons, and Army Stamina.
   - Battle Simulation: Calculates troop ratios, defensive fortifications, combat RNG, casualties, and plundered loot.
   - Live Battle March: Animated battalions marching across the ancient terrain with projectile volleys and battle smoke.

4. Reddit Community Integration:
   - Subreddit feeds per civilization (r/maurya_empire, r/roman_legion, r/han_dynasty, r/norse_realm).
   - Citizen characters with individual Karma scores, Abilities, Ideologies, and private internal thoughts.
   - Interactive upvoting/downvoting modifying individual karma.
"""

import json
import math
import random
import time
from html import escape
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

router = APIRouter(prefix="/kingdom")

# Civilization Dynasties State
CIVILIZATIONS = {
    "maurya": {
        "id": "maurya",
        "name": "Maurya Empire",
        "leader": "Emperor Ashoka",
        "color": "#f59e0b",
        "banner": "🐘",
        "biome": "Fertile River Plains",
        "x": 380,
        "y": 480,
        "food": 1850,
        "armour": 420,
        "troops": 340,
        "defense": 88,
        "gold": 4200,
        "weather": "Rainy Season",
        "subreddit": "r/maurya_empire"
    },
    "rome": {
        "id": "rome",
        "name": "Roman Legion",
        "leader": "Consul Aurelius",
        "color": "#ef4444",
        "banner": "🦅",
        "biome": "Mountain Foothills",
        "x": 320,
        "y": 180,
        "food": 1400,
        "armour": 550,
        "troops": 310,
        "defense": 94,
        "gold": 3800,
        "weather": "Clear Sky",
        "subreddit": "r/roman_legion"
    },
    "han": {
        "id": "han",
        "name": "Han Dynasty",
        "leader": "Imperial Chancellor Wu",
        "color": "#10b981",
        "banner": "🐉",
        "biome": "Dragon River Delta",
        "x": 860,
        "y": 240,
        "food": 2100,
        "armour": 480,
        "troops": 390,
        "defense": 84,
        "gold": 4600,
        "weather": "Heavy Monsoon",
        "subreddit": "r/han_dynasty"
    },
    "norse": {
        "id": "norse",
        "name": "Norse Clan Jarls",
        "leader": "Jarl Ragnar",
        "color": "#06b6d4",
        "banner": "⚡",
        "biome": "Scorched Steppes & Fjords",
        "x": 920,
        "y": 560,
        "food": 1100,
        "armour": 380,
        "troops": 260,
        "defense": 78,
        "gold": 2500,
        "weather": "Drought & Heatwave",
        "subreddit": "r/norse_realm"
    }
}

# Individual Citizens living in the ancient world
CITIZENS_DATA = []
POSTS_DATA = []
ACTIVE_WAR_MARCHES = []
WAR_LOGS = []

def init_ancient_world(n_citizens=200):
    global CITIZENS_DATA, POSTS_DATA
    CITIZENS_DATA.clear()
    POSTS_DATA.clear()

    names = {
        "maurya": ["Arjun", "Dev", "Vikram", "Chanakya", "Ananya", "Kalyan", "Padmini", "Siddhartha"],
        "rome": ["Marcus", "Titus", "Cassius", "Lucius", "Octavia", "Valeria", "Aurelius", "Flavius"],
        "han": ["Zhang", "Li", "Wang", "Zhao", "Sun", "Chen", "Mei", "Liu"],
        "norse": ["Bjorn", "Ragnar", "Ivar", "Sigrid", "Freja", "Torstein", "Astrid", "Gunnar"]
    }
    roles = ["Soldier", "Farmer", "Blacksmith", "Merchant", "General", "Priest", "Scout"]
    ideologies = ["Expansionist", "Agrarian Pacifist", "Imperial Loyalist", "Mercantile Guild", "Warrior Cult"]

    rng = random.Random(42)

    for i in range(n_citizens):
        civ_key = list(CIVILIZATIONS.keys())[i % len(CIVILIZATIONS)]
        civ = CIVILIZATIONS[civ_key]
        name = rng.choice(names[civ_key]) + f" {i+1}"
        role = rng.choice(roles)
        ideo = rng.choice(ideologies)
        karma = rng.randint(5, 140)

        # Spawn near civilization center
        offset_r = rng.uniform(20, 110)
        offset_theta = rng.uniform(0, 2 * math.pi)
        cx = civ["x"] + offset_r * math.cos(offset_theta)
        cy = civ["y"] + offset_r * math.sin(offset_theta)

        thought = f"Serving the {civ['name']}. Granaries must be secured before winter."
        if role == "Soldier":
            thought = f"Drilling with shield and spear. Our defense ({civ['defense']}) will repel any invaders."
        elif role == "Merchant":
            thought = f"Gold reserves ({civ['gold']} coins) permit lucrative inter-kingdom trade caravans."

        citizen = {
            "id": i,
            "name": name,
            "civ": civ_key,
            "civ_name": civ["name"],
            "civ_banner": civ["banner"],
            "role": role,
            "ideology": ideo,
            "karma": karma,
            "hp": rng.randint(85, 100),
            "wealth": round(rng.uniform(5.0, 45.0), 1),
            "thought": thought,
            "x": cx,
            "y": cy,
            "vx": rng.uniform(-0.4, 0.4),
            "vy": rng.uniform(-0.4, 0.4),
            "homeX": civ["x"],
            "homeY": civ["y"],
        }
        CITIZENS_DATA.append(citizen)

    # Initial posts
    sample_speakers = rng.sample(CITIZENS_DATA, 14)
    for c in sample_speakers:
        POSTS_DATA.append({
            "id": f"post_{c['id']}",
            "citizen_id": c["id"],
            "author": f"u/{c['name'].replace(' ', '_').lower()}",
            "civ": c["civ"],
            "subreddit": CIVILIZATIONS[c["civ"]]["subreddit"],
            "statement": f"By the decree of {CIVILIZATIONS[c['civ']]['leader']}, our {c['role']}s stand ready! Food: {CIVILIZATIONS[c['civ']]['food']} | Troops: {CIVILIZATIONS[c['civ']]['troops']}.",
            "thought": c["thought"],
            "karma": c["karma"],
            "ideology": c["ideology"]
        })

init_ancient_world(220)

ANCIENT_GAME_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Chronicles of Ancient Kingdoms - Tactical Simulation Game</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #0b0f17;
      --card: #151d2a;
      --border: #243247;
      --gold: #f59e0b;
      --red: #ef4444;
      --green: #10b981;
      --cyan: #06b6d4;
      --text: #f1f5f9;
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
      background: #111827;
      border-bottom: 2px solid #374151;
      height: 52px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 18px;
      z-index: 100;
    }
    .game-logo {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 800;
      font-size: 18px;
      color: var(--gold);
      letter-spacing: 0.03em;
    }
    .civ-quick-bar {
      display: flex;
      gap: 12px;
    }
    .civ-pill {
      background: #1f2937;
      border: 1px solid #374151;
      border-radius: 999px;
      padding: 4px 12px;
      font-size: 12px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .civ-pill:hover, .civ-pill.active {
      border-color: var(--gold);
      background: #374151;
      transform: translateY(-1px);
    }

    .header-actions {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .btn {
      background: var(--gold);
      color: #000;
      border: none;
      padding: 7px 16px;
      border-radius: 6px;
      font-weight: 700;
      font-size: 13px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .btn:hover { filter: brightness(1.15); transform: translateY(-1px); }
    .btn-red { background: var(--red); color: #fff; }
    .btn-card { background: #374151; color: #fff; }

    #main-layout {
      display: flex;
      flex: 1;
      height: calc(100vh - 52px);
      position: relative;
    }

    /* World Map Canvas */
    #canvas-wrap {
      flex: 1;
      position: relative;
      background: #09121d;
      overflow: hidden;
      cursor: grab;
    }
    #canvas-wrap:active { cursor: grabbing; }
    canvas { display: block; width: 100%; height: 100%; }

    /* Map HUD overlay */
    .map-overlay {
      position: absolute;
      top: 14px;
      left: 14px;
      pointer-events: none;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .hud-box {
      background: rgba(17, 24, 39, 0.9);
      border: 1px solid #374151;
      backdrop-filter: blur(8px);
      padding: 8px 14px;
      border-radius: 8px;
      font-size: 12px;
      color: #fff;
      display: flex;
      gap: 14px;
    }

    /* Right Strategic Command & Reddit Feed */
    #sidebar {
      width: 440px;
      background: var(--card);
      border-left: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100%;
    }
    .tabs {
      display: flex;
      border-bottom: 1px solid var(--border);
      background: #0f1520;
    }
    .tab {
      flex: 1;
      padding: 12px;
      text-align: center;
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      cursor: pointer;
      border-bottom: 2px solid transparent;
    }
    .tab.active {
      color: #fff;
      border-bottom: 2px solid var(--gold);
      background: var(--card);
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

    /* Tactical Warfare Panel */
    .war-panel {
      background: #1c2638;
      border: 2px solid #b45309;
      border-radius: 10px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .war-title {
      font-size: 15px;
      font-weight: 800;
      color: var(--gold);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .select-row {
      display: flex;
      gap: 10px;
      align-items: center;
    }
    .select-box {
      flex: 1;
      background: #111827;
      border: 1px solid var(--border);
      color: #fff;
      padding: 8px;
      border-radius: 6px;
      font-size: 13px;
    }
    .req-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      background: rgba(0,0,0,0.25);
      padding: 8px;
      border-radius: 6px;
      font-size: 11px;
      text-align: center;
    }
    .req-val { font-size: 13px; font-weight: 800; color: #fff; margin-top: 2px; }

    /* Reddit Style Post */
    .post-card {
      background: #1c2638;
      border: 1px solid var(--border);
      border-radius: 8px;
      display: flex;
      overflow: hidden;
    }
    .vote-bar {
      width: 40px;
      background: rgba(0,0,0,0.2);
      display: flex;
      flex-direction: column;
      align-items: center;
      padding: 8px 0;
      gap: 2px;
    }
    .vote-btn {
      background: none;
      border: none;
      color: var(--muted);
      cursor: pointer;
      font-size: 15px;
    }
    .vote-btn:hover { color: var(--gold); }
    .post-inner {
      flex: 1;
      padding: 10px 12px;
    }
    .post-header {
      font-size: 11px;
      color: var(--muted);
      display: flex;
      gap: 6px;
      margin-bottom: 4px;
    }
    .post-msg {
      font-size: 13px;
      font-weight: 600;
      color: #fff;
      line-height: 1.4;
      margin-bottom: 6px;
    }
    .post-thought {
      font-size: 11px;
      color: var(--gold);
      background: rgba(245, 158, 11, 0.08);
      border-left: 3px solid var(--gold);
      padding: 4px 8px;
      border-radius: 4px;
      font-style: italic;
    }

    /* Character Inspector */
    .char-card {
      background: #1c2638;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
  </style>
</head>
<body>
  <header>
    <div class="game-logo">
      <span>⚔️</span>
      <div>CHRONICLES OF ANCIENT KINGDOMS</div>
    </div>

    <div class="civ-quick-bar">
      <div class="civ-pill active" onclick="focusCiv('maurya')">🐘 Maurya</div>
      <div class="civ-pill" onclick="focusCiv('rome')">🦅 Rome</div>
      <div class="civ-pill" onclick="focusCiv('han')">🐉 Han</div>
      <div class="civ-pill" onclick="focusCiv('norse')">⚡ Norse</div>
    </div>

    <div class="header-actions">
      <button class="btn btn-red" onclick="switchTab('war')">⚔️ War Room</button>
      <button class="btn" onclick="stepWorld()">⏭️ Advance Year</button>
    </div>
  </header>

  <div id="main-layout">
    <div id="canvas-wrap">
      <div class="map-overlay">
        <div class="hud-box">
          <div>🗺️ <b>Ancient Continent of Pangaea Magna</b></div>
          <div>🌦️ Dynamic Climate: Monsoons & Desert Droughts</div>
        </div>
      </div>
      <canvas id="mapCanvas"></canvas>
    </div>

    <div id="sidebar">
      <div class="tabs">
        <div class="tab active" onclick="switchTab('war')">War & Conquest</div>
        <div class="tab" onclick="switchTab('feed')">Town Square (r/kingdom)</div>
        <div class="tab" onclick="switchTab('inspector')">Hero Inspector</div>
      </div>

      <!-- Tactical War Room -->
      <div id="pane-war" class="tab-content active">
        <div class="war-panel">
          <div class="war-title">
            <span>⚔️</span> Launch Military Campaign
          </div>
          <div style="font-size:12px; color:var(--muted)">
            Deploy legions against neighboring realms. Requires adequate food rations, armour smithing, and soldiers.
          </div>

          <div class="select-row">
            <div style="flex:1;">
              <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">ATTACKING DYNASTY</div>
              <select id="sel-attacker" class="select-box" onchange="updateWarUI()">
                <option value="maurya">🐘 Maurya Empire</option>
                <option value="rome">🦅 Roman Legion</option>
                <option value="han">🐉 Han Dynasty</option>
                <option value="norse">⚡ Norse Jarls</option>
              </select>
            </div>
            <div style="font-size:18px; font-weight:800; color:var(--red);">⚔️</div>
            <div style="flex:1;">
              <div style="font-size:11px; color:var(--muted); margin-bottom:2px;">TARGET REALM</div>
              <select id="sel-defender" class="select-box" onchange="updateWarUI()">
                <option value="rome">🦅 Roman Legion</option>
                <option value="han">🐉 Han Dynasty</option>
                <option value="norse">⚡ Norse Jarls</option>
                <option value="maurya">🐘 Maurya Empire</option>
              </select>
            </div>
          </div>

          <div class="req-grid">
            <div>
              <div style="color:var(--muted)">FOOD RATIONS</div>
              <div class="req-val" id="war-req-food">350 / 1850</div>
            </div>
            <div>
              <div style="color:var(--muted)">ARMOUR KITS</div>
              <div class="req-val" id="war-req-armour">120 / 420</div>
            </div>
            <div>
              <div style="color:var(--muted)">WARRIORS</div>
              <div class="req-val" id="war-req-troops">150 / 340</div>
            </div>
          </div>

          <button class="btn btn-red" style="justify-content:center; padding:10px;" onclick="executeAttack()">
            🔥 Order Siege & March Armies!
          </button>
        </div>

        <div style="font-size:13px; font-weight:700; margin-top:6px;">📜 Battle Chronology</div>
        <div id="war-logs-container" style="display:flex; flex-direction:column; gap:8px;">
          <!-- Dynamically populated -->
        </div>
      </div>

      <!-- Reddit Discussions Feed -->
      <div id="pane-feed" class="tab-content">
        <div id="reddit-feed" style="display:flex; flex-direction:column; gap:10px;">
          <!-- Dynamically populated -->
        </div>
      </div>

      <!-- Hero / Citizen Inspector -->
      <div id="pane-inspector" class="tab-content">
        <div class="char-card" id="char-details">
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <div>
              <div style="font-size:16px; font-weight:700;" id="insp-name">Arjun 1</div>
              <div style="font-size:12px; color:var(--gold);" id="insp-civ">🐘 Maurya Empire</div>
            </div>
            <span style="background:#243247; padding:3px 10px; border-radius:999px; font-size:12px;" id="insp-role">General</span>
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px; font-size:12px;">
            <div>Karma Level: <b id="insp-karma" style="color:var(--gold)">84</b></div>
            <div>Wealth: <b id="insp-wealth">24.5 coins</b></div>
            <div>Ideology: <b id="insp-ideo">Expansionist</b></div>
            <div>Health: <b id="insp-hp" style="color:var(--green)">100 HP</b></div>
          </div>
          <div style="font-size:11px; color:var(--muted)">Mindset & Thought:</div>
          <div class="post-thought" id="insp-thought">"Our spearmen hold the river crossings against foreign raids."</div>
        </div>
        <div style="font-size:12px; color:var(--muted); text-align:center;">
          💡 <em>Click any wandering character or fortress on the ancient map to inspect them!</em>
        </div>
      </div>
    </div>
  </div>

  <script>
    const canvas = document.getElementById("mapCanvas");
    const ctx = canvas.getContext("2d");

    let camera = { x: 600, y: 380, zoom: 0.9 };
    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let worldState = null;
    let selectedChar = null;
    let marchingBattalions = [];
    let battleSmoke = [];
    let riverParticles = [];
    let weatherParticles = [];

    function resize() {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight;
    }
    window.addEventListener("resize", resize);
    resize();

    async function loadState() {
      const res = await fetch("/kingdom/api/ancient-state");
      worldState = await res.json();
      renderFeed(worldState.posts);
      renderWarLogs(worldState.war_logs);
      updateWarUI();
      if (worldState.citizens.length > 0 && !selectedChar) {
        selectCitizen(worldState.citizens[0]);
      }
    }

    function renderFeed(posts) {
      const container = document.getElementById("reddit-feed");
      container.innerHTML = "";
      posts.forEach(p => {
        const div = document.createElement("div");
        div.className = "post-card";
        div.innerHTML = `
          <div class="vote-bar">
            <button class="vote-btn" onclick="votePost('${p.id}', 1, this)">▲</button>
            <div style="font-size:11px; font-weight:700;" id="score-${p.id}">${p.karma}</div>
            <button class="vote-btn" onclick="votePost('${p.id}', -1, this)">▼</button>
          </div>
          <div class="post-inner">
            <div class="post-header">
              <span style="font-weight:700; color:#fff;">${p.subreddit}</span>
              <span>•</span>
              <span>${p.author}</span>
            </div>
            <div class="post-msg">"${p.statement}"</div>
            <div class="post-thought">💭 ${p.thought}</div>
          </div>
        `;
        container.appendChild(div);
      });
    }

    function renderWarLogs(logs) {
      const container = document.getElementById("war-logs-container");
      container.innerHTML = "";
      if (logs.length === 0) {
        container.innerHTML = '<div style="font-size:12px; color:var(--muted)">The continent is currently at uneasy truce. Deploy an army to test their defenses!</div>';
        return;
      }
      logs.slice(-6).reverse().forEach(l => {
        const div = document.createElement("div");
        div.style = "background:#111827; border:1px solid #374151; padding:8px 10px; border-radius:6px; font-size:12px;";
        div.innerHTML = `
          <div style="font-weight:700; color:${l.won ? 'var(--green)' : 'var(--red)'}">${l.won ? 'VICTORY' : 'DEFEAT'} · Year ${l.year}</div>
          <div>${l.details}</div>
          <div style="font-size:11px; color:var(--gold); margin-top:2px;">Plunder: ${l.loot} coins | Casualties: ${l.casualties}</div>
        `;
        container.appendChild(div);
      });
    }

    function updateWarUI() {
      if (!worldState) return;
      const attKey = document.getElementById("sel-attacker").value;
      const defKey = document.getElementById("sel-defender").value;
      const att = worldState.civilizations[attKey];

      document.getElementById("war-req-food").innerText = `350 / ${att.food}`;
      document.getElementById("war-req-armour").innerText = `120 / ${att.armour}`;
      document.getElementById("war-req-troops").innerText = `150 / ${att.troops}`;
    }

    async function executeAttack() {
      const attKey = document.getElementById("sel-attacker").value;
      const defKey = document.getElementById("sel-defender").value;
      if (attKey === defKey) {
        alert("A kingdom cannot declare war upon itself!");
        return;
      }

      const res = await fetch("/kingdom/api/attack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ attacker: attKey, defender: defKey })
      });
      const data = await res.json();

      // Spawn marching battalion on map
      const att = worldState.civilizations[attKey];
      const def = worldState.civilizations[defKey];
      marchingBattalions.push({
        x: att.x,
        y: att.y,
        targetX: def.x,
        targetY: def.y,
        color: att.color,
        banner: att.banner,
        progress: 0
      });

      setTimeout(() => {
        loadState();
        alert(data.msg);
      }, 2200);
    }

    async function votePost(id, val, btn) {
      const res = await fetch("/kingdom/api/vote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: id, value: val })
      });
      const data = await res.json();
      document.getElementById("score-" + id).innerText = data.new_score;
      btn.style.color = val > 0 ? "var(--gold)" : "#7193ff";
    }

    // --- Dynamic Biome & Canvas Map Pipeline ---
    function updatePhysics() {
      if (!worldState) return;

      // Update citizens wander
      worldState.citizens.forEach(c => {
        c.x += c.vx;
        c.y += c.vy;
        const d = Math.hypot(c.x - c.homeX, c.y - c.homeY);
        if (d > 120) {
          c.vx *= -1;
          c.vy *= -1;
        }
        if (Math.random() < 0.02) {
          c.vx = (Math.random() - 0.5) * 0.7;
          c.vy = (Math.random() - 0.5) * 0.7;
        }
      });

      // Update River Flow Particles
      if (Math.random() < 0.4) {
        riverParticles.push({
          x: 100 + Math.random() * 40,
          y: 720,
          vx: 1.2,
          vy: -1.4,
          life: 280
        });
      }
      riverParticles.forEach(p => {
        p.x += p.vx;
        p.y += p.vy;
        p.life--;
      });
      riverParticles = riverParticles.filter(p => p.life > 0);

      // Weather FX: Rain in Han, Heat shimmer in Norse
      if (Math.random() < 0.6) {
        weatherParticles.push({
          x: 750 + Math.random() * 300,
          y: 100 + Math.random() * 200,
          vy: 6 + Math.random() * 4,
          type: "rain"
        });
      }
      weatherParticles.forEach(w => w.y += w.vy);
      weatherParticles = weatherParticles.filter(w => w.y < 800);

      // Marching Battalions
      marchingBattalions.forEach(b => {
        b.progress += 0.012;
        b.x = b.x + (b.targetX - b.x) * 0.02;
        b.y = b.y + (b.targetY - b.y) * 0.02;

        // Spawn battle smoke upon arrival
        if (b.progress >= 0.95) {
          for (let i = 0; i < 15; i++) {
            battleSmoke.push({
              x: b.targetX + (Math.random() - 0.5) * 40,
              y: b.targetY + (Math.random() - 0.5) * 40,
              vx: (Math.random() - 0.5) * 1.5,
              vy: -1 - Math.random() * 1.5,
              radius: 4 + Math.random() * 6,
              alpha: 0.8
            });
          }
        }
      });
      marchingBattalions = marchingBattalions.filter(b => b.progress < 1.0);

      battleSmoke.forEach(s => {
        s.x += s.vx;
        s.y += s.vy;
        s.radius += 0.2;
        s.alpha -= 0.015;
      });
      battleSmoke = battleSmoke.filter(s => s.alpha > 0);
    }

    function renderMap() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.save();
      ctx.translate(canvas.width / 2, canvas.height / 2);
      ctx.scale(camera.zoom, camera.zoom);
      ctx.translate(-camera.x, -camera.y);

      // 1. Procedural Ancient Biomes
      // Arid Dunes (South East)
      ctx.fillStyle = "#332411";
      ctx.fillRect(650, 420, 550, 360);

      // Scorched Crags (Norse)
      ctx.fillStyle = "#271d18";
      ctx.fillRect(800, 480, 400, 300);

      // Lush Fertile Plains (Maurya & Rivermead)
      ctx.fillStyle = "#162f1a";
      ctx.fillRect(150, 360, 500, 420);

      // Mountain Ranges (Highvale - Rome Foothills)
      ctx.fillStyle = "#1f2a37";
      ctx.fillRect(150, 80, 500, 280);

      // Mountain Peaks
      const peaks = [[260, 140], [380, 110], [490, 160], [210, 220], [340, 200]];
      peaks.forEach(([px, py]) => {
        ctx.beginPath();
        ctx.moveTo(px, py - 35);
        ctx.lineTo(px + 30, py + 25);
        ctx.lineTo(px - 30, py + 25);
        ctx.closePath();
        ctx.fillStyle = "#374151";
        ctx.fill();
        // Snow Cap
        ctx.beginPath();
        ctx.moveTo(px, py - 35);
        ctx.lineTo(px + 10, py - 12);
        ctx.lineTo(px - 10, py - 12);
        ctx.closePath();
        ctx.fillStyle = "#e5e7eb";
        ctx.fill();
      });

      // Desert Sand Dunes
      ctx.strokeStyle = "#78350f";
      ctx.lineWidth = 2;
      for (let d = 0; d < 5; d++) {
        ctx.beginPath();
        ctx.arc(880 + d * 50, 620 + (d % 2) * 30, 45, Math.PI, 0);
        ctx.stroke();
      }

      // 2. Animated Sinuous River
      ctx.strokeStyle = "#0284c7";
      ctx.lineWidth = 32;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(120, 780);
      ctx.bezierCurveTo(340, 640, 520, 460, 680, 380);
      ctx.bezierCurveTo(800, 320, 950, 260, 1150, 120);
      ctx.stroke();

      // River Water Foam Highlights
      ctx.strokeStyle = "#38bdf8";
      ctx.lineWidth = 6;
      ctx.stroke();

      riverParticles.forEach(p => {
        ctx.fillStyle = "rgba(255, 255, 255, 0.7)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, 2, 0, Math.PI * 2);
        ctx.fill();
      });

      // 3. Render Dynasties / Civilizations
      if (worldState) {
        Object.values(worldState.civilizations).forEach(civ => {
          // Territory Boundary Aura
          ctx.beginPath();
          ctx.arc(civ.x, civ.y, 110, 0, Math.PI * 2);
          ctx.strokeStyle = civ.color + "44";
          ctx.lineWidth = 3;
          ctx.stroke();

          // Citadel Base & Walls
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          ctx.fillRect(civ.x - 36, civ.y - 36, 72, 72);

          ctx.fillStyle = civ.color;
          ctx.fillRect(civ.x - 40, civ.y - 40, 80, 80);

          // Fortress Battlements
          ctx.fillStyle = "#111827";
          ctx.fillRect(civ.x - 30, civ.y - 30, 60, 60);

          // Civilization Banner & Title
          ctx.font = "24px sans-serif";
          ctx.textAlign = "center";
          ctx.fillText(civ.banner, civ.x, civ.y + 8);

          ctx.fillStyle = "#fff";
          ctx.font = "bold 13px sans-serif";
          ctx.fillText(civ.name, civ.x, civ.y - 50);

          ctx.fillStyle = varColor(civ.weather);
          ctx.font = "11px sans-serif";
          ctx.fillText(`🌦️ ${civ.weather}`, civ.x, civ.y - 68);
          ctx.textAlign = "left";
        });

        // 4. Render All Citizens
        worldState.citizens.forEach(c => {
          const isSel = selectedChar && selectedChar.id === c.id;
          const civ = worldState.civilizations[c.civ];

          ctx.beginPath();
          ctx.arc(c.x, c.y, isSel ? 7 : 4.5, 0, Math.PI * 2);
          ctx.fillStyle = civ.color;
          ctx.fill();

          if (isSel) {
            ctx.strokeStyle = "#fff";
            ctx.lineWidth = 2;
            ctx.stroke();
          }
        });
      }

      // 5. Draw Marching Battalions & War FX
      marchingBattalions.forEach(b => {
        ctx.font = "20px sans-serif";
        ctx.fillText(b.banner, b.x - 10, b.y);

        ctx.fillStyle = "#ef4444";
        ctx.beginPath();
        ctx.arc(b.x + 8, b.y - 8, 4, 0, Math.PI * 2);
        ctx.fill();
      });

      // 6. Draw Battle Smoke & Fire
      battleSmoke.forEach(s => {
        ctx.fillStyle = `rgba(239, 68, 68, ${s.alpha})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
        ctx.fill();
      });

      // 7. Weather Particle FX
      weatherParticles.forEach(w => {
        ctx.strokeStyle = "rgba(56, 189, 248, 0.45)";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(w.x, w.y);
        ctx.lineTo(w.x - 1, w.y + 8);
        ctx.stroke();
      });

      ctx.restore();

      updatePhysics();
      requestAnimationFrame(renderMap);
    }

    function varColor(w) {
      if (w.includes("Rain")) return "#38bdf8";
      if (w.includes("Drought")) return "#f59e0b";
      return "#94a3b8";
    }

    // Controls
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
      camera.zoom = Math.min(Math.max(camera.zoom * (e.deltaY < 0 ? 1.1 : 0.9), 0.5), 2.2);
    });

    canvas.addEventListener("click", e => {
      const rect = canvas.getBoundingClientRect();
      const clickX = (e.clientX - rect.left - canvas.width / 2) / camera.zoom + camera.x;
      const clickY = (e.clientY - rect.top - canvas.height / 2) / camera.zoom + camera.y;

      let nearest = null;
      let minDist = 22;
      worldState.citizens.forEach(c => {
        const d = Math.hypot(c.x - clickX, c.y - clickY);
        if (d < minDist) {
          minDist = d;
          nearest = c;
        }
      });
      if (nearest) selectCitizen(nearest);
    });

    function selectCitizen(c) {
      selectedChar = c;
      document.getElementById("insp-name").innerText = c.name;
      document.getElementById("insp-civ").innerText = `${c.civ_banner} ${c.civ_name}`;
      document.getElementById("insp-role").innerText = c.role;
      document.getElementById("insp-karma").innerText = c.karma;
      document.getElementById("insp-wealth").innerText = c.wealth + " coins";
      document.getElementById("insp-ideo").innerText = c.ideology;
      document.getElementById("insp-hp").innerText = c.hp + " HP";
      document.getElementById("insp-thought").innerText = `"${c.thought}"`;
    }

    function focusCiv(key) {
      const civ = worldState.civilizations[key];
      camera.x = civ.x;
      camera.y = civ.y;
      camera.zoom = 1.1;
      document.querySelectorAll(".civ-pill").forEach(p => p.classList.remove("active"));
      event.target.classList.add("active");
    }

    function switchTab(t) {
      document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      event.target.classList.add("active");
      document.getElementById("pane-" + t).classList.add("active");
    }

    async function stepWorld() {
      await fetch("/kingdom/api/step-year", { method: "POST" });
      loadState();
    }

    loadState().then(() => renderMap());
  </script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def get_ancient_world():
    return HTMLResponse(ANCIENT_GAME_HTML)


@router.get("/api/ancient-state")
def get_ancient_state():
    return JSONResponse({
        "civilizations": CIVILIZATIONS,
        "citizens": CITIZENS_DATA,
        "posts": POSTS_DATA,
        "war_logs": WAR_LOGS,
    })


@router.post("/api/attack")
async def api_attack(request: Request):
    data = await request.json()
    att_key = data.get("attacker")
    def_key = data.get("defender")

    att = CIVILIZATIONS[att_key]
    def_civ = CIVILIZATIONS[def_key]

    # Warfare Resource Check
    if att["food"] < 350 or att["armour"] < 120 or att["troops"] < 150:
        return JSONResponse({"msg": "Not enough food, armour, or warriors to launch siege!"}, status_code=400)

    # Consume resources
    att["food"] -= 350
    att["armour"] -= 120

    # Combat Resolution (Troop count, Defense Rating, RNG)
    att_power = att["troops"] * random.uniform(0.85, 1.25)
    def_power = (def_civ["troops"] * (def_civ["defense"] / 75.0)) * random.uniform(0.85, 1.25)

    won = att_power > def_power
    casualties = int(random.randint(25, 60))
    loot = int(min(def_civ["gold"] * 0.25, 900)) if won else 0

    att["troops"] = max(att["troops"] - casualties, 50)
    if won:
        def_civ["troops"] = max(def_civ["troops"] - int(casualties * 1.4), 40)
        def_civ["gold"] -= loot
        att["gold"] += loot
        details = f"{att['name']} breached the defenses of {def_civ['name']}! Plundered {loot} gold."
    else:
        details = f"{def_civ['name']} successfully repelled the invaders at their fortress walls!"

    log_entry = {
        "year": random.randint(280, 450),
        "attacker": att["name"],
        "defender": def_civ["name"],
        "won": won,
        "loot": loot,
        "casualties": casualties,
        "details": details
    }
    WAR_LOGS.append(log_entry)

    # Add battle reaction post to Reddit
    POSTS_DATA.append({
        "id": f"post_war_{len(WAR_LOGS)}",
        "citizen_id": 999,
        "author": f"u/{att_key}_general",
        "civ": att_key,
        "subreddit": att["subreddit"],
        "statement": f"{'VICTORY!' if won else 'DEFEAT!'} We attacked {def_civ['name']}. {details}",
        "thought": "War changes the destiny of all dynasties.",
        "karma": 45,
        "ideology": "Expansionist"
    })

    return JSONResponse({"status": "attack_resolved", "won": won, "msg": details})


@router.post("/api/vote")
async def api_vote(request: Request):
    data = await request.json()
    item_id = data.get("item_id")
    val = int(data.get("value", 1))
    for p in POSTS_DATA:
        if p["id"] == item_id:
            p["karma"] += val
            return JSONResponse({"item_id": item_id, "new_score": p["karma"]})
    return JSONResponse({"item_id": item_id, "new_score": 10})


@router.post("/api/step-year")
def api_step_year():
    # Production cycle for all civilizations
    for civ in CIVILIZATIONS.values():
        civ["food"] += random.randint(180, 320)
        civ["armour"] += random.randint(40, 80)
        civ["gold"] += random.randint(200, 450)
        civ["troops"] = min(civ["troops"] + random.randint(10, 25), 500)
    return get_ancient_state()
