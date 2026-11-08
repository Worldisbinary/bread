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
    /game/api/kingdom/{id}      one kingdom: characters, top citizens by karma, its town square
    /game/api/admin/state       everything, including metric histories (admin only)

The admin token comes from RLIFE_ADMIN_TOKEN; if unset, one is generated at startup and
printed in the server log. The public game never receives admin-only metrics.
"""

import hmac
import os
import pickle
import secrets
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .agents import Navigator
from .presets import PRESETS, describe
from .world import GameWorld

STATIC = Path(__file__).parent / "static"
SAVE = Path(os.environ.get("RLIFE_GAME_SAVE", "runs/game.pkl"))
ADMIN_TOKEN = os.environ.get("RLIFE_ADMIN_TOKEN") or secrets.token_urlsafe(12)

router = APIRouter()
_lock = threading.Lock()
_game: dict = {"world": None, "navigator": None, "llm": None}
TELEMETRY: dict = {"latency_ms": {}, "actions": {}, "funnel": {}, "sessions": 0, "questions": 0}


def _llm():
    """The LLM client for agents, if a key is configured; agents work without one."""
    if _game["llm"] is None and os.environ.get("LLM_API_KEY"):
        from ..llm import Cache, OpenAICompatibleLLM

        _game["llm"] = OpenAICompatibleLLM(
            os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
            os.environ["LLM_API_KEY"],
            cache=Cache(os.environ.get("RLIFE_CACHE", ".cache/llm.sqlite")),
            timeout=8,
        )
    return _game["llm"]


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


def _navigator() -> Navigator:
    if _game["navigator"] is None:
        _game["navigator"] = Navigator()
    _game["navigator"].llm = _llm()
    return _game["navigator"]


def admin_token_hint() -> str:
    return "set by RLIFE_ADMIN_TOKEN" if os.environ.get("RLIFE_ADMIN_TOKEN") else ADMIN_TOKEN


def _world() -> GameWorld:
    if _game["world"] is None and SAVE.exists():
        try:
            _game["world"] = pickle.loads(SAVE.read_bytes())
        except Exception:  # an old or broken save should not stop the server
            _game["world"] = None
    if _game["world"] is not None and not hasattr(_game["world"], "director"):
        _game["world"] = None  # a save from an older version of the game
    if _game["world"] is None:
        raise HTTPException(404, "No world yet: create one first.")
    _game["world"].director.llm = _llm()
    return _game["world"]


def _save(world: GameWorld) -> None:
    SAVE.parent.mkdir(parents=True, exist_ok=True)
    SAVE.write_bytes(pickle.dumps(world))


def _require_admin(request: Request, token: str | None) -> None:
    supplied = token or request.cookies.get("rlife_admin", "")
    if not hmac.compare_digest(supplied, ADMIN_TOKEN):
        raise HTTPException(403, "Admin token required.")


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


@router.get("/game/api/presets")
def presets():
    return describe()


@router.post("/game/api/new")
async def new_world(request: Request):
    body = await request.json()
    preset = body.get("preset", "indus")
    if preset not in PRESETS:
        raise HTTPException(400, "unknown region")
    lo, hi = PRESETS[preset]["years"]
    year = int(min(max(int(body.get("year", PRESETS[preset]["default_year"])), lo), hi))
    population = int(min(max(int(body.get("population", 2000)), 300), 6000))
    kingdoms = int(min(max(int(body.get("kingdoms", 6)), 3), 10))
    seed = int(body.get("seed", 7)) % 100000
    started = time.perf_counter()
    with _lock:
        world = GameWorld(preset, population, year, seed=seed, kingdoms=kingdoms, player=0, llm=_llm())
        _game["world"] = world
        _game["navigator"] = Navigator(llm=_llm())
        TELEMETRY["sessions"] += 1
        _save(world)
    _track("new", started)
    return {"ok": True, "year": world.year}


@router.get("/game/api/terrain")
def terrain():
    return JSONResponse(_world().terrain.to_client())


@router.get("/game/api/state")
def state():
    return _world().state(admin=False)


@router.post("/game/api/step")
async def step(request: Request):
    body = await request.json()
    years = int(min(max(int(body.get("years", 1)), 1), 25))
    started = time.perf_counter()
    with _lock:
        world = _world()
        events = []
        for _ in range(years):
            events += world.step()
        _save(world)
    _track("step", started)
    _nav_event("step")
    return {"events": events, "state": world.state(admin=False), "navigator": _nav_view(world)}


@router.post("/game/api/player")
async def choose_player(request: Request):
    body = await request.json()
    world = _world()
    kid = int(body.get("id", 0))
    if not 0 <= kid < len(world.kingdoms):
        raise HTTPException(400, "unknown kingdom")
    world.player = kid
    _save(world)
    return {"ok": True, "player": kid}


@router.post("/game/api/action")
async def action(request: Request):
    body = await request.json()
    started = time.perf_counter()
    with _lock:
        world = _world()
        me = world.kingdoms[world.player]
        if not me.alive:
            raise HTTPException(400, "Your dynasty has fallen.")
        kind = body.get("action")
        n = int(body.get("n", 20))
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
        elif kind == "attack":
            target = world.kingdoms[int(body.get("target", -1))]
            result = world.attack(me, target, float(body.get("share", 0.6)))
        elif kind == "check_attack":
            target = world.kingdoms[int(body.get("target", -1))]
            result = world.attack_requirements(me, target, float(body.get("share", 0.6)))
        else:
            raise HTTPException(400, "unknown action")
        _save(world)
    TELEMETRY["actions"][kind] = TELEMETRY["actions"].get(kind, 0) + 1
    _track("action", started)
    _nav_event({"train": "train", "harvest_festival": "festival", "attack": "attack"}.get(kind))
    return {"result": result, "state": world.state(admin=False), "navigator": _nav_view(world)}


def _nav_event(event: str | None) -> None:
    if event:
        before = _navigator().step
        step = _navigator().advance(event)
        if step["index"] != before:
            TELEMETRY["funnel"][step["id"]] = TELEMETRY["funnel"].get(step["id"], 0) + 1


def _nav_view(world: GameWorld) -> dict:
    nav = _navigator()
    me = world.kingdom_summary(world.kingdoms[world.player])
    return {**nav.current(), "tip": nav.tip(me)}


@router.get("/game/api/navigator")
def navigator():
    return _nav_view(_world())


@router.post("/game/api/navigator")
async def navigator_event(request: Request):
    body = await request.json()
    _nav_event(str(body.get("event", "next")))
    return _nav_view(_world())


@router.post("/game/api/navigator/ask")
async def navigator_ask(request: Request):
    body = await request.json()
    started = time.perf_counter()
    answer = _navigator().ask(str(body.get("question", "")))
    TELEMETRY["questions"] += 1
    _track("navigator_ask", started)
    return answer


@router.get("/game/api/kingdom/{kid}")
def kingdom(kid: int):
    started = time.perf_counter()
    world = _world()
    if not 0 <= kid < len(world.kingdoms):
        raise HTTPException(404)
    k = world.kingdoms[kid]
    _nav_event("inspect")
    _track("kingdom", started)
    return {
        **world.kingdom_summary(k),
        "top_citizens": world.top_citizens(k),
        "feed": [p for p in world.feed if p["kingdom"] == kid][-25:],
        "neighbours": [o.id for o in world.neighbours(k)],
    }


@router.post("/game/api/admin/login")
async def admin_login(request: Request):
    body = await request.json()
    if not hmac.compare_digest(str(body.get("token", "")), ADMIN_TOKEN):
        raise HTTPException(403, "Wrong token.")
    response = JSONResponse({"ok": True})
    response.set_cookie("rlife_admin", ADMIN_TOKEN, httponly=True, samesite="strict")
    return response


@router.get("/game/api/admin/state")
def admin_state(request: Request, x_admin_token: str | None = Header(default=None)):
    _require_admin(request, x_admin_token)
    world = _world()
    nav = _navigator()
    return world.state(admin=True) | {
        "chronicle": world.chronicle[-300:],
        "agents": world.agent_metrics(),
        "telemetry": {
            "latency_ms": _latency_summary(),
            "actions": TELEMETRY["actions"],
            "funnel": TELEMETRY["funnel"],
            "sessions": TELEMETRY["sessions"],
            "tutorial_step": nav.current()["id"],
            "questions": nav.questions[-20:],
            "llm_attached": _llm() is not None,
        },
    }
