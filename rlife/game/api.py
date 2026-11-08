"""HTTP API for the game client and the admin console.

    /game                       the game (browser client)
    /game/admin                 the admin console (metrics, LiveOps): needs the admin token
    /game/api/presets           regions and eras to start from
    /game/api/new               create a world {preset, population, year, kingdoms, seed}
    /game/api/terrain           the map (sent once)
    /game/api/state             kingdoms, territory, chronicle, town square
    /game/api/step              advance {years}
    /game/api/player            choose which dynasty you rule {id}
    /game/api/action            act as your kingdom {action, n, target, delta}
    /game/api/navigator         the Navigator's current tutorial step (POST {event} to advance)
    /game/api/navigator/ask     ask the Navigator a question {question}
    /game/api/kingdom/{id}      one kingdom: characters, top citizens by karma, its town square
    /game/api/admin/state       everything, including metric histories (admin only)
    /healthz                    liveness for the hosting platform

Every visitor plays their own world, keyed by a session cookie, so a public deployment is not one
shared game. Live worlds are kept in memory up to RLIFE_MAX_WORLDS (least recently played are
evicted, and reload from disk if their owner comes back).

LLM use is bounded for public hosting: a daily request budget (RLIFE_LLM_DAILY_CAP) after which the
agents fall back to their rules, and no waiting on an exhausted provider quota.

The admin token comes from RLIFE_ADMIN_TOKEN; if unset, one is generated at startup and
printed in the server log. The public game never receives admin-only metrics.
"""

import datetime as dt
import hmac
import os
import pickle
import re
import secrets
import threading
import time
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ..llm import LLMError
from . import town as T
from .agents import Navigator, moderation_metrics
from .presets import PRESETS, describe, year_label
from .world import GameWorld

STATIC = Path(__file__).parent / "static"
SAVE_DIR = Path(os.environ.get("RLIFE_GAME_DIR", "runs/worlds"))
MAX_WORLDS = int(os.environ.get("RLIFE_MAX_WORLDS", "40"))
LLM_DAILY_CAP = int(os.environ.get("RLIFE_LLM_DAILY_CAP", "800"))
YEAR_SECONDS = float(os.environ.get("RLIFE_YEAR_SECONDS", "40"))  # one world year per this many real seconds
ADMIN_TOKEN = os.environ.get("RLIFE_ADMIN_TOKEN") or secrets.token_urlsafe(12)
COOKIE = "rlife_sid"
SID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")

router = APIRouter()
_lock = threading.RLock()
SESSIONS: "OrderedDict[str, dict]" = OrderedDict()
_shared: dict = {"llm": None}
TELEMETRY: dict = {
    "latency_ms": {},
    "actions": {},
    "funnel": {},
    "sessions": 0,
    "questions": 0,
    "llm": {"day": "", "calls": 0, "refused": 0},
    "battles": {"count": 0, "stars": [0, 0, 0, 0], "destruction": [], "corrected": 0, "reasons": {}},
    "town": {},
}


# ----------------------------------------------------------------------------- LLM with a budget


class BudgetedLLM:
    """Wraps the LLM client with a daily request budget shared by every world on this server."""

    def __init__(self, inner, cap: int) -> None:
        self.inner, self.cap = inner, cap

    def complete(self, *args, **kwargs):
        usage = TELEMETRY["llm"]
        today = dt.date.today().isoformat()
        with _lock:
            if usage["day"] != today:
                usage.update(day=today, calls=0, refused=0)
            if usage["calls"] >= self.cap:
                usage["refused"] += 1
                raise LLMError("daily LLM budget for the game is spent; agents use their rules")
            usage["calls"] += 1
        return self.inner.complete(*args, **kwargs)


def _llm():
    """The LLM client for agents, if a key is configured; agents work without one."""
    if _shared["llm"] is None and os.environ.get("LLM_API_KEY"):
        from ..llm import Cache, OpenAICompatibleLLM

        inner = OpenAICompatibleLLM(
            os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            os.environ["LLM_API_KEY"],
            tokens_per_minute=int(os.environ.get("LLM_TOKENS_PER_MINUTE", "7500")),
            cache=Cache(os.environ.get("RLIFE_CACHE", ".cache/llm.sqlite")),
            timeout=8,
            max_quota_wait_s=0,  # a live game never waits for a provider quota to reset
        )
        _shared["llm"] = BudgetedLLM(inner, LLM_DAILY_CAP)
    return _shared["llm"]


# ----------------------------------------------------------------------------- telemetry


def _track(name: str, started: float) -> None:
    samples = TELEMETRY["latency_ms"].setdefault(name, [])
    samples.append(round((time.perf_counter() - started) * 1000, 2))
    del samples[:-500]


def _latency_summary() -> dict:
    out = {}
    for name, samples in TELEMETRY["latency_ms"].items():
        ordered = sorted(samples)
        out[name] = {
            "n": len(ordered),
            "p50": ordered[len(ordered) // 2],
            "p95": ordered[int(0.95 * (len(ordered) - 1))],
        }
    return out


def admin_token_hint() -> str:
    return "set by RLIFE_ADMIN_TOKEN" if os.environ.get("RLIFE_ADMIN_TOKEN") else ADMIN_TOKEN


# ----------------------------------------------------------------------------- sessions


def _sid(request: Request) -> str | None:
    sid = request.cookies.get(COOKIE, "")
    return sid if SID.match(sid) else None


def _path(sid: str) -> Path:
    return SAVE_DIR / f"{sid}.pkl"


def _load(sid: str) -> dict | None:
    if sid in SESSIONS:
        SESSIONS.move_to_end(sid)
        return SESSIONS[sid]
    path = _path(sid)
    if not path.exists():
        return None
    try:
        saved = pickle.loads(path.read_bytes())
    except Exception:  # an old or broken save should not stop the server
        return None
    if not isinstance(saved, dict) or not hasattr(saved.get("world"), "director"):
        return None  # a save from an older version of the game
    return _remember(sid, saved["world"], saved.get("navigator") or Navigator())


def _remember(sid: str, world: GameWorld, navigator: Navigator) -> dict:
    session = {"world": world, "navigator": navigator, "touched": time.time()}
    SESSIONS[sid] = session
    SESSIONS.move_to_end(sid)
    while len(SESSIONS) > MAX_WORLDS:
        SESSIONS.popitem(last=False)  # still on disk if its player returns
    return session


def _session(request: Request) -> dict:
    sid = _sid(request)
    with _lock:
        session = _load(sid) if sid else None
    if session is None:
        raise HTTPException(404, "No world yet: create one first.")
    session["touched"] = time.time()
    session["world"].director.llm = _llm()
    session["navigator"].llm = _llm()
    return session


def _write(sid: str, session: dict) -> None:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    _path(sid).write_bytes(pickle.dumps({"world": session["world"], "navigator": session["navigator"]}))


def _save(request: Request, session: dict) -> None:
    sid = _sid(request)
    if sid:
        _write(sid, session)


def _require_admin(request: Request, token: str | None) -> None:
    supplied = token or request.cookies.get("rlife_admin", "")
    if not hmac.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(403, "Admin token required.")


# ----------------------------------------------------------------------------- pages


@router.get("/game", response_class=HTMLResponse)
def game_page():
    return FileResponse(STATIC / "index.html")


@router.get("/game/admin", response_class=HTMLResponse)
def admin_page():
    return FileResponse(STATIC / "admin.html")


@router.get("/game/static/{name}")
def static_file(name: str):
    path = (STATIC / name).resolve()
    if path.parent != STATIC.resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)


@router.get("/healthz")
def healthz():
    return {"ok": True, "worlds": len(SESSIONS)}


# ----------------------------------------------------------------------------- game


@router.get("/game/api/presets")
def presets():
    return describe()


@router.post("/game/api/new")
async def new_world(request: Request, response: Response):
    body = await request.json()
    preset = body.get("preset", "indus")
    if preset not in PRESETS:
        raise HTTPException(400, "unknown region")
    lo, hi = PRESETS[preset]["years"]
    age = body.get("age", "founding")
    if age not in T.AGES:
        raise HTTPException(400, "unknown age")
    difficulty = body.get("difficulty", "balanced")
    if difficulty not in T.DIFFICULTY:
        raise HTTPException(400, "unknown difficulty")
    # The age places the start inside the region's era and sets the population; explicit values still win.
    default_year = round(lo + (hi - lo) * T.AGES[age]["where"])
    year = int(min(max(int(body.get("year", default_year)), lo), hi))
    population = int(min(max(int(body.get("population", T.AGES[age]["population"])), 300), 6000))
    kingdoms = int(body["rivals"]) + 1 if "rivals" in body else int(body.get("kingdoms", 7))
    kingdoms = int(min(max(kingdoms, 3), 10))
    seed = int(body.get("seed", 7)) % 100000
    started = time.perf_counter()
    sid = _sid(request) or secrets.token_urlsafe(18)
    world = GameWorld(
        preset,
        population,
        year,
        seed=seed,
        kingdoms=kingdoms,
        player=0,
        llm=_llm(),
        age=age,
        difficulty=difficulty,
    )
    with _lock:
        session = _remember(sid, world, Navigator(llm=_llm()))
        TELEMETRY["sessions"] += 1
        _write(sid, session)
    response.set_cookie(COOKIE, sid, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    _track("new", started)
    return {"ok": True, "year": world.year}


@router.get("/game/api/terrain")
def terrain(request: Request):
    return JSONResponse(_session(request)["world"].terrain.to_client())


@router.get("/game/api/state")
def state(request: Request):
    return _session(request)["world"].state(admin=False)


@router.post("/game/api/step")
async def step(request: Request):
    body = await request.json()
    years = int(min(max(int(body.get("years", 1)), 1), 25))
    started = time.perf_counter()
    session = _session(request)
    with _lock:
        world = session["world"]
        events = []
        for _ in range(years):
            events += world.step()
        _save(request, session)
    _track("step", started)
    _nav_event(session, "step")
    return {"events": events, "state": world.state(admin=False), "navigator": _nav_view(session)}


@router.post("/game/api/player")
async def choose_player(request: Request):
    body = await request.json()
    session = _session(request)
    with _lock:
        world = session["world"]
        kid = int(body.get("id", 0))
        if not 0 <= kid < len(world.kingdoms):
            raise HTTPException(400, "unknown kingdom")
        world.player = kid
        world.found_town(kid)
        world.clock = time.time()
        _save(request, session)
    return {"ok": True, "player": kid}


@router.post("/game/api/action")
async def action(request: Request):
    body = await request.json()
    started = time.perf_counter()
    session = _session(request)
    with _lock:
        world = session["world"]
        me = world.kingdoms[world.player]
        if not me.alive:
            raise HTTPException(400, "Your dynasty has fallen.")
        kind = body.get("action")
        n = int(min(max(int(body.get("n", 20)), 1), 2000))
        if kind == "train":
            result = {"message": world.train(me, n)}
        elif kind == "forge":
            result = {"message": world.forge(me, n)}
        elif kind == "walls":
            result = {"message": world.build_walls(me)}
        elif kind in (
            "harvest_festival",
            "trade_fair",
            "grain_reserve_release",
            "adjust_tax",
            "adjust_subsidy",
        ):
            args = {"delta": float(body.get("delta", 0))} if kind.startswith("adjust_") else {}
            decision = me.ops.apply(kind, args, actor="player")
            result = {
                "message": decision.reason if not decision.accepted else f"{kind.replace('_', ' ')}: done",
                "accepted": decision.accepted,
            }
        elif kind in ("attack", "check_attack"):
            tid = int(body.get("target", -1))
            if not 0 <= tid < len(world.kingdoms) or tid == world.player:
                raise HTTPException(400, "unknown target")
            target = world.kingdoms[tid]
            share = float(min(max(float(body.get("share", 0.6)), 0.1), 1.0))
            if kind == "attack":
                result = world.attack(me, target, share)
            else:
                result = world.attack_requirements(me, target, share)
        else:
            raise HTTPException(400, "unknown action")
        _save(request, session)
    TELEMETRY["actions"][kind] = TELEMETRY["actions"].get(kind, 0) + 1
    _track("action", started)
    _nav_event(session, {"train": "train", "harvest_festival": "festival", "attack": "attack"}.get(kind))
    return {"result": result, "state": world.state(admin=False), "navigator": _nav_view(session)}


# ----------------------------------------------------------------------------- navigator


def _nav_event(session: dict, event: str | None) -> None:
    if event:
        nav = session["navigator"]
        before = nav.step
        current = nav.advance(event)
        if current["index"] != before:
            TELEMETRY["funnel"][current["id"]] = TELEMETRY["funnel"].get(current["id"], 0) + 1


def _nav_view(session: dict) -> dict:
    nav, world = session["navigator"], session["world"]
    me = world.kingdom_summary(world.kingdoms[world.player])
    return {**nav.current(), "tip": nav.tip(me)}


@router.get("/game/api/navigator")
def navigator(request: Request):
    return _nav_view(_session(request))


@router.post("/game/api/navigator")
async def navigator_event(request: Request):
    body = await request.json()
    session = _session(request)
    _nav_event(session, str(body.get("event", "next")))
    return _nav_view(session)


@router.post("/game/api/navigator/ask")
async def navigator_ask(request: Request):
    body = await request.json()
    started = time.perf_counter()
    answer = _session(request)["navigator"].ask(str(body.get("question", "")))
    TELEMETRY["questions"] += 1
    _track("navigator_ask", started)
    return answer


@router.get("/game/api/kingdom/{kid}")
def kingdom(kid: int, request: Request):
    started = time.perf_counter()
    session = _session(request)
    world = session["world"]
    if not 0 <= kid < len(world.kingdoms):
        raise HTTPException(404)
    k = world.kingdoms[kid]
    _nav_event(session, "inspect")
    _track("kingdom", started)
    return {
        **world.kingdom_summary(k),
        "top_citizens": world.top_citizens(k),
        "feed": [p for p in world.feed if p["kingdom"] == kid][-25:],
        "neighbours": [o.id for o in world.neighbours(k)],
    }


# ----------------------------------------------------------------------------- admin


@router.post("/game/api/admin/login")
async def admin_login(request: Request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("token", "")), ADMIN_TOKEN):
        raise HTTPException(403, "Wrong token.")
    response = JSONResponse({"ok": True})
    response.set_cookie("rlife_admin", ADMIN_TOKEN, httponly=True, samesite="strict")
    return response


def _fleet() -> dict:
    """Agent metrics across every live world on this server, not just one player's."""
    worlds = [s["world"] for s in list(SESSIONS.values())]
    logs = [e for w in worlds for e in w.director.log]
    taken = [e for e in logs if e["accepted"] and e["action"] != "none"]
    return {
        "worlds_live": len(worlds),
        "moderation": moderation_metrics([warden for w in worlds for warden in w.wardens]),
        "director_actions": len(taken),
        "director_blocked": sum(not e["accepted"] for e in logs),
        "director_llm_share": round(sum(e["source"] == "llm" for e in logs) / max(len(logs), 1), 2),
    }


@router.get("/game/api/admin/state")
def admin_state(request: Request, x_admin_token: str | None = Header(default=None)):
    _require_admin(request, x_admin_token)
    sid = _sid(request)
    with _lock:
        session = (_load(sid) if sid else None) or (
            max(SESSIONS.values(), key=lambda s: s["touched"]) if SESSIONS else None
        )
    if session is None:
        raise HTTPException(404, "No world yet: start one in the game.")
    world, nav = session["world"], session["navigator"]
    return world.state(admin=True) | {
        "chronicle": world.chronicle[-300:],
        "agents": world.agent_metrics(),
        "fleet": _fleet(),
        "telemetry": {
            "latency_ms": _latency_summary(),
            "actions": TELEMETRY["actions"],
            "funnel": TELEMETRY["funnel"],
            "sessions": TELEMETRY["sessions"],
            "tutorial_step": nav.current()["id"],
            "questions": nav.questions[-20:],
            "llm_attached": _llm() is not None,
            "llm_budget": {**TELEMETRY["llm"], "cap": LLM_DAILY_CAP},
            "town_actions": TELEMETRY["town"],
            "battles": {
                **{k: v for k, v in TELEMETRY["battles"].items() if k != "destruction"},
                "mean_destruction": round(
                    sum(TELEMETRY["battles"]["destruction"]) / len(TELEMETRY["battles"]["destruction"]), 1
                )
                if TELEMETRY["battles"]["destruction"]
                else None,
            },
        },
    }


# ----------------------------------------------------------------------------- town and raids


def _player_town(world: GameWorld) -> T.Town:
    if world.player not in getattr(world, "towns", {}):
        world.found_town(world.player)
        world.clock = time.time()
    return world.towns[world.player]


def _tick_world(world: GameWorld, now: float) -> list[dict]:
    """The world moves on in real time: one year every YEAR_SECONDS (at most 3 at once)."""
    clock = getattr(world, "clock", None) or now
    due = int((now - clock) // YEAR_SECONDS)
    events: list[dict] = []
    if due > 0:
        for _ in range(min(due, 3)):
            events += world.step()
        clock += due * YEAR_SECONDS
    world.clock = clock
    me = world.player
    return [
        {"label": e["label"], "kind": e["kind"], "text": e["text"]}
        for e in events
        if e.get("kingdom") == me
        or e.get("defender") == me
        or e.get("attacker") == me
        or e["kind"] == "liveops"
    ]


def _town_view(session: dict, now: float, news: list | None = None) -> dict:
    world = session["world"]
    town = _player_town(world)
    me = world.kingdoms[world.player]
    summary = world.kingdom_summary(me)
    return {
        **town.to_client(world.wallet(me), now),
        "year": world.year,
        "label": year_label(world.year),
        "kingdom": {
            key: summary[key]
            for key in ("name", "color", "laws", "karma", "happiness", "population", "people")
        },
        "quest": world.director.quest,
        "news": news or [],
        "navigator": _nav_view(session),
        "next_year_in": round(max(0.0, getattr(world, "clock", now) + YEAR_SECONDS - now), 1),
    }


@router.get("/game/api/catalog")
def catalog():
    return T.catalog()


@router.get("/game/api/town")
def town_state(request: Request):
    started = time.perf_counter()
    session = _session(request)
    now = time.time()
    with _lock:
        world = session["world"]
        town = _player_town(world)
        news = [{"label": "", "kind": "build", "text": t} for t in town.advance(now)]
        news += _tick_world(world, now)
        if news:
            _save(request, session)
        view = _town_view(session, now, news)
    _track("town", started)
    return view


@router.post("/game/api/town/{op}")
async def town_action(op: str, request: Request):
    body = await request.json()
    started = time.perf_counter()
    session = _session(request)
    now = time.time()
    result: dict = {}
    with _lock:
        world = session["world"]
        town = _player_town(world)
        me = world.kingdoms[world.player]
        town.advance(now)
        wallet = world.wallet(me)
        try:
            if op == "build":
                b = town.build(
                    str(body.get("type")), int(body.get("x", -1)), int(body.get("y", -1)), wallet, now
                )
                result = {"id": b.id}
            elif op == "upgrade":
                b = town.upgrade(int(body.get("id", -1)), wallet, now)
                result = {"id": b.id}
            elif op == "move":
                town.move(int(body.get("id", -1)), int(body.get("x", -1)), int(body.get("y", -1)))
            elif op == "collect":
                result = {"amount": town.collect(int(body.get("id", -1)), wallet, now)}
            elif op == "train":
                result = {"trained": town.train(str(body.get("type")), int(body.get("n", 1)), wallet, now)}
            else:
                raise HTTPException(404, "unknown town action")
        except T.TownError as exc:
            raise HTTPException(400, str(exc)) from exc
        world.settle(me, wallet)
        _save(request, session)
    TELEMETRY["town"][op] = TELEMETRY["town"].get(op, 0) + 1
    _track("town_" + op, started)
    _nav_event(
        session, {"build": "build", "upgrade": "build", "collect": "collect", "train": "train"}.get(op)
    )
    return {"result": result, "town": _town_view(session, now)}


@router.get("/game/api/rivals")
def rivals(request: Request):
    world = _session(request)["world"]
    _player_town(world)
    return world.rivals()


@router.post("/game/api/battle/start")
async def battle_start(request: Request):
    body = await request.json()
    session = _session(request)
    with _lock:
        world = session["world"]
        town = _player_town(world)
        town.advance(time.time())
        tid = int(body.get("target", -1))
        if not 0 <= tid < len(world.kingdoms) or tid == world.player or not world.kingdoms[tid].alive:
            raise HTTPException(400, "unknown target")
        if not any(town.army.values()):
            raise HTTPException(400, "You have no troops. Train some in the Army panel first.")
        k = world.kingdoms[tid]
        rival = world.rival_town(k)
        layout = T.battle_layout(rival, world.loot_offer(k, rival.palace_level()))
        battle = {
            "id": secrets.token_urlsafe(8),
            "target": tid,
            "layout": layout,
            "army": dict(town.army),
            "started": time.time(),
        }
        session["battle"] = battle
    return {
        "battle_id": battle["id"],
        "target": {"id": tid, "name": k.name, "color": k.color, "laws": k.econ.laws.name},
        "army": battle["army"],
        "preset": world.preset,
        **layout,
    }


@router.post("/game/api/battle/end")
async def battle_end(request: Request):
    body = await request.json()
    session = _session(request)
    with _lock:
        battle = session.get("battle")
        if not battle or body.get("battle_id") != battle["id"]:
            raise HTTPException(400, "That battle is not running.")
        session["battle"] = None
        if time.time() - battle["started"] > 15 * 60:
            raise HTTPException(400, "That battle report is too old.")
        world = session["world"]
        result = T.check_report(battle["layout"], battle["army"], body)
        outcome = world.apply_battle(world.kingdoms[battle["target"]], result)
        _save(request, session)
    stats = TELEMETRY["battles"]
    stats["count"] += 1
    stats["stars"][result["stars"]] += 1
    stats["destruction"].append(result["destruction"])
    del stats["destruction"][:-500]
    if result["corrected"]:
        stats["corrected"] += 1
        for reason in result["corrected"]:
            stats["reasons"][reason] = stats["reasons"].get(reason, 0) + 1
    _nav_event(session, "attack")
    return {"outcome": outcome, "town": _town_view(session, time.time())}
