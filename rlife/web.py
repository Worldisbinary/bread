"""Web UI for browsing runs: a Reddit-style feed, threads with measurements, and the compass.

    /                          runs and their headline numbers
    /run/<run>/                communities, karma leaderboard, labels
    /run/<run>/r/<community>   feed (sorted by hot, new or engagement)
    /run/<run>/p/<id>          thread; every item shows its judged position and flags
    /run/<run>/u/<handle>      an agent: persona, karma, position over time, writing
    /run/<run>/compass         every agent's position, animated tick by tick
    /api/run/<run>/snapshots   JSON behind the compass
    /metrics                   Prometheus

Server-rendered HTML with escaping on every user-generated string (agents write it).
"""

import json
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import metrics
from .feed import rank
from .game.api import router as game_router
from .ideology import classify
from .kingdom.web import router as kingdom_router
from .world import World

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1a1a1b;--muted:#6b7280;--line:#e5e7eb;--accent:#ff4500;--chip:#eef2ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--ink:#e6e6e6;--muted:#9aa3b2;
--line:#262b36;--chip:#1e2433}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;
background:var(--bg);color:var(--ink)}
a{color:inherit}header{background:var(--card);border-bottom:1px solid var(--line);padding:10px 16px;
display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header b{color:var(--accent);font-size:18px}main{max-width:980px;margin:0 auto;padding:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:0 0 10px}
.muted{color:var(--muted);font-size:13px}.score{font-weight:600;min-width:38px;text-align:center}
.row{display:flex;gap:12px}.chip{display:inline-block;background:var(--chip);border-radius:999px;
padding:1px 8px;font-size:12px;margin-right:4px}.flag{background:#fee2e2;color:#991b1b}
.c{margin-left:18px;border-left:2px solid var(--line);padding-left:10px}
table{border-collapse:collapse;width:100%}td,th{padding:6px 8px;border-bottom:1px solid var(--line);
text-align:left;font-size:14px}
nav a{margin-right:10px}.removed{opacity:.55}
"""


def page(title: str, body: str, run: str | None = None) -> HTMLResponse:
    nav = ""
    if run:
        nav = (
            f'<nav><a href="/run/{escape(run)}/">overview</a><a href="/run/{escape(run)}/compass">compass</a>'
            f'<a href="/run/{escape(run)}/r/r/life">r/life</a></nav>'
        )
    return HTMLResponse(
        f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' "
        f"content='width=device-width,initial-scale=1'><title>{escape(title)}</title><style>{CSS}</style>"
        f"</head><body><header><a href='/' style='text-decoration:none'><b>r/life</b></a>{nav}</header>"
        f"<main>{body}</main></body></html>"
    )


def chips(score: dict | None) -> str:
    if not score:
        return '<span class="chip">not yet judged</span>'
    if not score["political"] or score["economic"] is None:
        return '<span class="chip">non-political</span>'
    label = classify(score["economic"], score["social"], set(score["flags"]))
    out = (
        f'<span class="chip">economic {score["economic"]:+.2f}</span>'
        f'<span class="chip">social {score["social"]:+.2f}</span><span class="chip">{escape(label)}</span>'
    )
    out += "".join(f'<span class="chip flag">{escape(f)}</span>' for f in score["flags"])
    return out


def create_app(run_paths: list[str]) -> FastAPI:
    runs = {
        Path(p).stem if Path(p).parent.name == "runs" else f"{Path(p).parent.name}-{Path(p).stem}": p
        for p in run_paths
    }
    app = FastAPI(title="r/life")
    app.include_router(kingdom_router)
    app.include_router(game_router)

    def world(run: str) -> World:
        if run not in runs:
            raise HTTPException(404, "unknown run")
        return World(runs[run])

    @app.get("/metrics")
    def prometheus():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", response_class=HTMLResponse)
    def index():
        rows = []
        for name in runs:
            w = world(name)
            snaps = w.snapshots()
            last = snaps[-1] if snaps else {}
            cfg = w.meta("config", {})
            pol = last.get("polarization")
            rows.append(
                f"<tr><td><a href='/run/{escape(name)}/'>{escape(name)}</a></td>"
                f"<td>{escape(str(cfg.get('ranking', '')))}</td><td>{len(snaps)}</td>"
                f"<td>{len(w.all_items())}</td><td>{'' if pol is None else f'{pol:.3f}'}</td>"
                f"<td>{escape(str(w.meta('code_version', '')))}</td></tr>"
            )
        return page(
            "r/life runs",
            "<h2>Runs</h2><div class='card'><table><tr><th>Run</th><th>Ranking</th>"
            "<th>Ticks</th><th>Items</th><th>Polarization</th><th>Code</th></tr>"
            + "".join(rows)
            + "</table></div>",
        )

    @app.get("/run/{run}/", response_class=HTMLResponse)
    def overview(run: str):
        w = world(run)
        karma = w.karma_table()
        agents = {a["id"]: a for a in w.agents()}
        pos = metrics.positions(metrics.political_scores(w))
        board = sorted(karma.items(), key=lambda kv: -kv[1])
        rows = "".join(
            f"<tr><td><a href='/run/{escape(run)}/u/{escape(agents[a]['handle'])}'>u/{escape(agents[a]['handle'])}"
            f"</a></td><td>{escape(agents[a]['persona']['city'])}</td>"
            f"<td>{escape(agents[a]['persona']['profession'])}</td><td>{k}</td>"
            f"<td>{escape(pos[a]['label']) if a in pos else ''}</td></tr>"
            for a, k in board
        )
        comms = "".join(
            f"<a class='chip' href='/run/{escape(run)}/r/{escape(c['name'])}'>{escape(c['name'])}</a>"
            for c in w.communities()
        )
        cfg = w.meta("config", {})
        res = w.meta("result") or {}
        body = (
            f"<h2>{escape(run)}</h2><div class='card'>{comms}</div>"
            f"<div class='card muted'>ranking {escape(str(cfg.get('ranking')))} · seed {cfg.get('seed')} · "
            f"agent model {escape(str(cfg.get('agent_model')))} · judge {escape(str(cfg.get('judge_model')))} · "
            f"agent requests {res.get('agent_requests', 'running')}</div>"
            f"<div class='card'><h3>Karma</h3><table><tr><th>Agent</th><th>City</th><th>Work</th><th>Karma</th>"
            f"<th>Measured position</th></tr>{rows}</table></div>"
        )
        return page(run, body, run)

    @app.get("/run/{run}/r/{community:path}", response_class=HTMLResponse)
    def feed(run: str, community: str, sort: str = "hot"):
        w = world(run)
        now = w.meta("next_tick", 0)
        posts = rank(
            w.posts([community], include_removed=True),
            sort if sort in ("hot", "new", "engagement") else "hot",
            now,
        )
        scores = w.scores()
        cards = "".join(
            f"<div class='card row {'removed' if p.removed else ''}'><div class='score'>{p.score}</div><div>"
            f"<a href='/run/{escape(run)}/p/{p.id}'><b>{escape(p.title or '')}</b></a>"
            f"<div class='muted'>u/{escape(p.author)} · tick {p.tick} · {p.comments} comments"
            f"{' · removed: ' + escape(p.removed) if p.removed else ''}</div>"
            f"<div>{escape(p.body[:280])}</div><div>{chips(scores.get(p.id))}</div></div></div>"
            for p in posts
        )
        sorts = " ".join(f"<a href='?sort={s}'>{s}</a>" for s in ("hot", "new", "engagement"))
        return page(
            community,
            f"<h2>{escape(community)}</h2><p class='muted'>sort: {sorts}</p>{cards or 'empty'}",
            run,
        )

    @app.get("/run/{run}/p/{post_id}", response_class=HTMLResponse)
    def thread(run: str, post_id: int):
        w = world(run)
        post = w.item(post_id)
        if not post or post.kind != "post":
            raise HTTPException(404)
        scores = w.scores()
        comments = w.thread(post_id, include_removed=True)
        children: dict = {}
        for c in comments:
            children.setdefault(c.parent_id, []).append(c)

        def render(parent_id) -> str:
            return "".join(
                f"<div class='c {'removed' if c.removed else ''}'><div class='muted'>u/{escape(c.author)} · "
                f"{c.score} points · tick {c.tick}{' · removed: ' + escape(c.removed) if c.removed else ''}</div>"
                f"<div>{escape(c.body)}</div><div>{chips(scores.get(c.id))}</div>{render(c.id)}</div>"
                for c in children.get(parent_id, [])
            )

        body = (
            f"<div class='card'><div class='muted'>{escape(post.community)} · u/{escape(post.author)} · "
            f"{post.score} points</div><h2>{escape(post.title or '')}</h2><p>{escape(post.body)}</p>"
            f"{chips(scores.get(post.id))}</div><div class='card'>{render(None) or 'No comments yet.'}</div>"
        )
        return page(post.title or "thread", body, run)

    @app.get("/run/{run}/u/{handle}", response_class=HTMLResponse)
    def user(run: str, handle: str):
        w = world(run)
        agent = next((a for a in w.agents() if a["handle"] == handle), None)
        if not agent:
            raise HTTPException(404)
        scores = w.scores()
        items = [i for i in w.all_items() if i.author_id == agent["id"]]
        persona = agent["persona"]
        trail = [s["positions"].get(str(agent["id"])) for s in w.snapshots()]
        trail_txt = (
            " → ".join(f"({p['economic']:+.2f}, {p['social']:+.2f})" for p in trail if p) or "no position yet"
        )
        writing = "".join(
            f"<div class='card'><div class='muted'>{escape(i.community)} · tick {i.tick} · {i.score} points</div>"
            f"<div>{escape((i.title + ': ') if i.title else '')}{escape(i.body)}</div>{chips(scores.get(i.id))}</div>"
            for i in items
        )
        body = (
            f"<h2>u/{escape(handle)}</h2><div class='card'>{escape(persona['name'])}, {persona['age']}, "
            f"{escape(persona['profession'])} in {escape(persona['city'])}; {escape(persona['income'])}, "
            f"{escape(persona['family'])}. Interests: {escape(', '.join(persona['interests']))}. "
            f"Temperament: {escape(persona['temperament'])}.<br><b>Karma {w.karma(agent['id'])}</b></div>"
            f"<div class='card'><b>Position over time</b> (economic, social): <span class='muted'>"
            f"{escape(trail_txt)}</span></div>{writing}"
        )
        return page(handle, body, run)

    @app.get("/api/run/{run}/snapshots")
    def snapshots(run: str):
        w = world(run)
        agents = {str(a["id"]): {"handle": a["handle"], "city": a["persona"]["city"]} for a in w.agents()}
        return JSONResponse(
            {
                "agents": agents,
                "snapshots": [
                    {"tick": s["tick"], "positions": s["positions"], "polarization": s["polarization"]}
                    for s in w.snapshots()
                ],
            }
        )

    @app.get("/run/{run}/compass", response_class=HTMLResponse)
    def compass(run: str):
        world(run)
        html = (Path(__file__).parent / "web" / "compass.html").read_text()
        return page("compass", html.replace("__RUN__", json.dumps(run)), run)

    return app
