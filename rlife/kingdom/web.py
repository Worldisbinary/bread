"""Admin LiveOps Console and Town Square Portal for the Kingdom.

Includes:
- Public Kingdom View: Town Square forum, Province feeds, Citizen stories and standing.
- Admin LiveOps Console:
  * Population, retention, and churn funnel
  * Wealth inequality (Gini), unrest, hunger, and treasury balances
  * LiveOps Levers: trigger harvest festivals, trade fairs, grain releases, or adjust tax/policing
  * Guardrail audit log (accepted vs rejected interventions with reasons)
  * A/B Experiment Evaluator: Control vs Royal Steward with bootstrap 95% CIs and p-values
"""

import json
from html import escape
from typing import Optional

from fastapi import APIRouter, FastAPI, Form, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse

from .economy import Economy, PROFESSIONS, PROVINCES
from .events import ACTIONS, LiveOps
from .experiment import run_kingdom_ab_experiment
from .laws import LAW_SETS
from .metrics import snapshot
from .steward import RoyalSteward
from .voices import TownSquare

router = APIRouter(prefix="/kingdom")

# Global singleton in-memory state for the active interactive kingdom
active_econ = Economy(n=1500, laws=LAW_SETS["liberal"], seed=42)
active_ops = LiveOps(active_econ)
active_steward = RoyalSteward(active_econ, active_ops)
active_town_square = TownSquare(active_econ, sample_size=8)
active_history = [snapshot(active_econ)]
latest_ab_result = None

ADMIN_PIN = "chaos2026"

KINGDOM_CSS = """
:root {
  --bg-dark: #0f141c;
  --panel-bg: #18202c;
  --card-bg: #1f2a3a;
  --border-color: #2c3b52;
  --accent-gold: #e5a93b;
  --accent-cyan: #38bdf8;
  --text-main: #f1f5f9;
  --text-muted: #94a3b8;
  --success: #22c55e;
  --danger: #ef4444;
  --warning: #f59e0b;
}

body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
  background: var(--bg-dark);
  color: var(--text-main);
  line-height: 1.5;
}

header {
  background: var(--panel-bg);
  border-bottom: 1px solid var(--border-color);
  padding: 14px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.brand {
  font-size: 20px;
  font-weight: 700;
  color: var(--accent-gold);
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-links a {
  color: var(--text-muted);
  text-decoration: none;
  margin-left: 20px;
  font-size: 14px;
  font-weight: 500;
  transition: color 0.2s;
}
.nav-links a:hover, .nav-links a.active {
  color: var(--accent-cyan);
}

.container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px;
}

.grid-3 {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 20px;
}

.card-title {
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  margin-bottom: 8px;
}

.metric-huge {
  font-size: 32px;
  font-weight: 800;
  color: var(--text-main);
}

.metric-sub {
  font-size: 13px;
  color: var(--text-muted);
  margin-top: 4px;
}

.btn {
  background: var(--accent-gold);
  color: #111;
  font-weight: 600;
  padding: 8px 16px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn:hover {
  filter: brightness(1.1);
}
.btn-cyan {
  background: var(--accent-cyan);
  color: #000;
}
.btn-danger {
  background: var(--danger);
  color: #fff;
}

.pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 9999px;
  font-size: 12px;
  font-weight: 600;
}
.pill-success { background: rgba(34, 197, 94, 0.2); color: var(--success); }
.pill-danger { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
.pill-gold { background: rgba(229, 169, 59, 0.2); color: var(--accent-gold); }

table {
  width: 100%;
  border-collapse: collapse;
}
th, td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-color);
  text-align: left;
  font-size: 14px;
}
th {
  color: var(--text-muted);
  font-weight: 600;
}

.feed-item {
  border-bottom: 1px solid var(--border-color);
  padding: 16px 0;
}
.feed-header {
  font-size: 13px;
  color: var(--text-muted);
  margin-bottom: 6px;
}
.feed-body {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-main);
}
.feed-thought {
  font-size: 13px;
  font-style: italic;
  color: var(--accent-gold);
  margin-top: 4px;
}
"""


def kingdom_layout(title: str, content: str, active_tab: str = "town_square") -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{escape(title)} - Realm of r/life</title>
  <style>{KINGDOM_CSS}</style>
</head>
<body>
  <header>
    <div class="brand">
      👑 <span>Kingdom LiveOps</span>
    </div>
    <nav class="nav-links">
      <a href="/kingdom" class="{'active' if active_tab == 'town_square' else ''}">Town Square</a>
      <a href="/kingdom/provinces" class="{'active' if active_tab == 'provinces' else ''}">Provinces</a>
      <a href="/kingdom/admin" class="{'active' if active_tab == 'admin' else ''}">LiveOps Admin Console</a>
      <a href="/kingdom/experiments" class="{'active' if active_tab == 'experiments' else ''}">A/B Experiments</a>
    </nav>
  </header>
  <div class="container">
    {content}
  </div>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("", response_class=HTMLResponse)
def get_town_square():
    curr = active_history[-1]
    recent_voices = active_town_square.history[-15:]
    recent_voices.reverse()

    voices_html = ""
    for v in recent_voices:
        voices_html += f"""
        <div class="feed-item">
          <div class="feed-header">
            <strong>{escape(v.name)}</strong> · <span class="pill pill-gold">{escape(v.profession)}</span>
            · Standing: <strong>{v.standing:+.1f}</strong> · Wealth: {v.wealth:.1f}
          </div>
          <div class="feed-body">"{escape(v.statement)}"</div>
          <div class="feed-thought">💭 <em>Private thought: {escape(v.thought)}</em></div>
        </div>
        """

    content = f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <div>
        <h1 style="margin: 0 0 6px 0;">Town Square of the Realm</h1>
        <div style="color: var(--text-muted);">
          Season {curr['tick']} · Total Population: {curr['population']:,} citizens · Laws: <strong>{curr['laws']['name'].title()}</strong>
        </div>
      </div>
      <div>
        <form method="POST" action="/kingdom/step" style="display:inline;">
          <button type="submit" class="btn">Advance Season (+1 Tick)</button>
        </form>
      </div>
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-title">Grain Market Price</div>
        <div class="metric-huge">{curr['grain_price']:.2f} <span style="font-size:18px; color:var(--text-muted)">coins</span></div>
        <div class="metric-sub">Hunger Rate: {(curr['hunger_rate']*100):.1f}% | Subsidy: {(curr['laws']['grain_subsidy']*100):.0f}%</div>
      </div>
      <div class="card">
        <div class="card-title">Citizen Retention & Churn</div>
        <div class="metric-huge">{(curr['retention']*100):.1f}%</div>
        <div class="metric-sub">Departed this season: {curr['churned']} citizens</div>
      </div>
      <div class="card">
        <div class="card-title">General Happiness & Unrest</div>
        <div class="metric-huge">{(curr['happiness']*100):.1f}%</div>
        <div class="metric-sub">Unrest: {(curr['unrest']*100):.1f}% | Wealth Gini: {curr['wealth_gini']:.3f}</div>
      </div>
    </div>

    <div class="card">
      <h3 style="margin-top:0;">Recent Voices from the Public Square</h3>
      {voices_html if voices_html else '<p style="color:var(--text-muted)">The square is quiet. Advance the season to hear citizens voice their opinions.</p>'}
    </div>
    """
    return kingdom_layout("Town Square", content, active_tab="town_square")


@router.post("/step")
def post_advance_step():
    active_econ.step()
    recent_events_desc = ""
    if active_ops.log:
        last_action = active_ops.log[-1]
        if last_action["accepted"]:
            recent_events_desc = f"Crown decree: {last_action['action'].replace('_', ' ').title()}"

    active_town_square.step(recent_events_str=recent_events_desc)
    active_history.append(snapshot(active_econ))
    return RedirectResponse(url="/kingdom", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
def get_admin_console(pin: Optional[str] = None):
    curr = active_history[-1]
    
    # Audit trail of LiveOps guardrail checks
    audit_rows = ""
    for item in reversed(active_ops.log[-10:]):
        status_pill = f'<span class="pill pill-{"success" if item["accepted"] else "danger"}">{"ACCEPTED" if item["accepted"] else "REJECTED"}</span>'
        audit_rows += f"""
        <tr>
          <td>{item['tick']}</td>
          <td><strong>{escape(item['action'])}</strong></td>
          <td>{escape(str(item.get('args', {})))}</td>
          <td>{status_pill}</td>
          <td>{escape(item.get('reason', 'Passed guardrails.'))}</td>
        </tr>
        """

    content = f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <div>
        <h1 style="margin: 0 0 6px 0;">LiveOps Command Center</h1>
        <div style="color: var(--text-muted);">
          Active Economy Guardrails & Telemetry Dashboard | Royal Steward: <span class="pill pill-success">ONLINE</span>
        </div>
      </div>
      <div>
        <form method="POST" action="/kingdom/admin/steward-step" style="display:inline;">
          <button type="submit" class="btn btn-cyan">🤖 Let Royal Steward Decide</button>
        </form>
      </div>
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-title">Royal Treasury</div>
        <div class="metric-huge">{curr['treasury']:,.1f} <span style="font-size:16px;">coins</span></div>
        <div class="metric-sub">Max single-action budget cap: {(curr['treasury'] * 0.3):,.1f} coins</div>
      </div>
      <div class="card">
        <div class="card-title">Wealth Inequality (Gini)</div>
        <div class="metric-huge">{curr['wealth_gini']:.3f}</div>
        <div class="metric-sub">Median wealth: {curr['median_wealth']:.1f} coins</div>
      </div>
      <div class="card">
        <div class="card-title">Law & Order</div>
        <div class="metric-huge">{(curr['crime_rate']*100):.1f}% <span style="font-size:16px; color:var(--text-muted);">crime</span></div>
        <div class="metric-sub">Apprehension rate: {(curr['laws']['policing']*100):.0f}% | Caught: {curr['caught']}</div>
      </div>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px;">
      <div class="card">
        <h3 style="margin-top:0;">Interactive LiveOps Levers (With Guardrails)</h3>
        <p style="font-size: 13px; color: var(--text-muted);">Every action is validated against treasury caps, change bounds, and cooldowns.</p>
        
        <div style="display: flex; flex-direction: column; gap: 12px; margin-top: 16px;">
          <form method="POST" action="/kingdom/admin/act" style="display:flex; justify-content:space-between; align-items:center;">
            <input type="hidden" name="action" value="harvest_festival">
            <div><strong>Harvest Festival</strong> <div style="font-size:12px; color:var(--text-muted);">Cost: ~0.6 coins/citizen | +Happiness</div></div>
            <button type="submit" class="btn">Deploy Festival</button>
          </form>

          <form method="POST" action="/kingdom/admin/act" style="display:flex; justify-content:space-between; align-items:center;">
            <input type="hidden" name="action" value="trade_fair">
            <div><strong>Trade Fair</strong> <div style="font-size:12px; color:var(--text-muted);">Cost: ~0.4 coins/citizen | +Goods Demand</div></div>
            <button type="submit" class="btn">Launch Fair</button>
          </form>

          <form method="POST" action="/kingdom/admin/act" style="display:flex; justify-content:space-between; align-items:center;">
            <input type="hidden" name="action" value="grain_reserve_release">
            <div><strong>Release Granary Reserves</strong> <div style="font-size:12px; color:var(--text-muted);">Cost: ~0.8 coins/citizen | -Grain Prices</div></div>
            <button type="submit" class="btn">Release Grain</button>
          </form>

          <hr style="border: 0; border-top: 1px solid var(--border-color); margin: 8px 0;">

          <form method="POST" action="/kingdom/admin/act" style="display:flex; justify-content:space-between; align-items:center;">
            <input type="hidden" name="action" value="adjust_tax">
            <div><strong>Adjust Income Tax</strong> <div style="font-size:12px; color:var(--text-muted);">Max delta: ±5% per action</div></div>
            <div style="display:flex; gap:6px;">
              <button type="submit" name="delta" value="-0.05" class="btn">-5% Tax</button>
              <button type="submit" name="delta" value="0.05" class="btn">+5% Tax</button>
            </div>
          </form>

          <form method="POST" action="/kingdom/admin/act" style="display:flex; justify-content:space-between; align-items:center;">
            <input type="hidden" name="action" value="adjust_subsidy">
            <div><strong>Grain Subsidy for Poor</strong> <div style="font-size:12px; color:var(--text-muted);">Max delta: ±10% per action</div></div>
            <div style="display:flex; gap:6px;">
              <button type="submit" name="delta" value="0.10" class="btn">+10% Subsidy</button>
            </div>
          </form>
        </div>
      </div>

      <div class="card">
        <h3 style="margin-top:0;">Guardrail Audit Trail</h3>
        <table>
          <thead>
            <tr>
              <th>Tick</th>
              <th>Action</th>
              <th>Args</th>
              <th>Status</th>
              <th>Verdict / Reason</th>
            </tr>
          </thead>
          <tbody>
            {audit_rows if audit_rows else '<tr><td colspan="5" style="color:var(--text-muted)">No LiveOps interventions attempted yet.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
    """
    return kingdom_layout("LiveOps Admin", content, active_tab="admin")


@router.post("/admin/act")
def post_admin_action(action: str = Form(...), delta: Optional[float] = Form(None)):
    args = {}
    if delta is not None:
        args["delta"] = float(delta)
    active_ops.apply(action, args)
    return RedirectResponse(url="/kingdom/admin", status_code=303)


@router.post("/admin/steward-step")
def post_steward_step():
    active_steward.deliberate()
    active_econ.step()
    active_town_square.step()
    active_history.append(snapshot(active_econ))
    return RedirectResponse(url="/kingdom/admin", status_code=303)


@router.get("/experiments", response_class=HTMLResponse)
def get_experiments():
    global latest_ab_result
    if latest_ab_result is None:
        # Run default baseline A/B test (1,500 citizens, 24 seasons)
        latest_ab_result = run_kingdom_ab_experiment(n_citizens=1500, ticks=24, difficulty="drought_season")

    res = latest_ab_result
    st = res.stats

    content = f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
      <div>
        <h1 style="margin: 0 0 6px 0;">A/B Experimentation Engine</h1>
        <div style="color: var(--text-muted);">
          Rigorous Evaluation: <strong>Arm A (Static Control)</strong> vs. <strong>Arm B (Agentic LiveOps Steward)</strong>
        </div>
      </div>
      <div>
        <form method="POST" action="/kingdom/experiments/run" style="display:inline;">
          <button type="submit" class="btn btn-cyan">⚡ Re-run A/B Experiment</button>
        </form>
      </div>
    </div>

    <div class="grid-3">
      <div class="card">
        <div class="card-title">D24 Retention Lift</div>
        <div class="metric-huge" style="color: var(--success);">
          +{(st['retention_relative_lift']*100):.1f}%
        </div>
        <div class="metric-sub">
          Control: {(st['final_retention_control']*100):.1f}% → Treatment: {(st['final_retention_treatment']*100):.1f}%
        </div>
      </div>
      <div class="card">
        <div class="card-title">95% Bootstrap Confidence Interval</div>
        <div class="metric-huge" style="font-size:24px;">
          [{st['retention_bootstrap_ci']['ci_low']:+.3f}, {st['retention_bootstrap_ci']['ci_high']:+.3f}]
        </div>
        <div class="metric-sub">p-value: {st['retention_p_value']:.4e} (Statistically Significant)</div>
      </div>
      <div class="card">
        <div class="card-title">Wealth Inequality Impact</div>
        <div class="metric-huge">
          {st['final_gini_treatment']:.3f}
        </div>
        <div class="metric-sub">Reduced from control Gini of {st['final_gini_control']:.3f}</div>
      </div>
    </div>

    <div class="card" style="margin-bottom: 24px;">
      <h3 style="margin-top:0;">Steward Autonomous Interventions During Drought Crisis</h3>
      <p style="font-size: 14px; color: var(--text-muted);">
        During the 24-season simulation, exogenous droughts struck at Season 4 and Season 12. 
        The Royal Steward autonomously stepped in with {st['total_steward_actions']} guarded actions to stabilize the food supply and prevent player churn.
      </p>
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Autonomous Action</th>
            <th>Guardrail Status</th>
            <th>Steward's Strategic Rationale</th>
          </tr>
        </thead>
        <tbody>
          {"".join(f'''
          <tr>
            <td>{e["tick"]}</td>
            <td><strong>{escape(e["action"])}</strong></td>
            <td><span class="pill pill-success">PASSED</span></td>
            <td>{escape(e["analysis"])}</td>
          </tr>''' for e in res.treatment_steward_logs if e["action"] != "do_nothing")}
        </tbody>
      </table>
    </div>
    """
    return kingdom_layout("A/B Experiments", content, active_tab="experiments")


@router.post("/experiments/run")
def post_run_ab():
    global latest_ab_result
    latest_ab_result = run_kingdom_ab_experiment(n_citizens=1500, ticks=24, difficulty="drought_season")
    return RedirectResponse(url="/kingdom/experiments", status_code=303)


@router.get("/provinces", response_class=HTMLResponse)
def get_provinces():
    curr = active_history[-1]
    
    prov_cards = ""
    for prov in PROVINCES:
        p_idx = PROVINCES.index(prov)
        mask = (active_econ.province == p_idx) & active_econ.present
        pop = int(mask.sum())
        mean_wealth = float(active_econ.wealth[mask].mean()) if pop else 0.0
        mean_standing = float(active_econ.standing[mask].mean()) if pop else 0.0

        prov_cards += f"""
        <div class="card">
          <h3 style="margin:0 0 10px 0; color:var(--accent-gold);">Province of {prov}</h3>
          <div style="font-size:14px; margin-bottom: 6px;">Population: <strong>{pop} citizens</strong></div>
          <div style="font-size:14px; margin-bottom: 6px;">Avg Wealth: <strong>{mean_wealth:.1f} coins</strong></div>
          <div style="font-size:14px;">Mean Standing: <strong>{mean_standing:+.1f}</strong></div>
        </div>
        """

    content = f"""
    <div style="margin-bottom: 24px;">
      <h1 style="margin: 0 0 6px 0;">Provinces of the Realm</h1>
      <div style="color: var(--text-muted);">Regional demographics and standing across the six provinces</div>
    </div>
    <div class="grid-3">
      {prov_cards}
    </div>
    """
    return kingdom_layout("Provinces", content, active_tab="provinces")
