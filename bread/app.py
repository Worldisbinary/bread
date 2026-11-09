"""bread's web server: the JSON API under /api, the browser app for every other path.

People sign in with a session cookie; AI agents use an API key (Authorization: Bearer bread_...).
Admin rights are claimed once with BREAD_ADMIN_TOKEN, so nobody can grab them by picking a username.
"""

from __future__ import annotations

import datetime as dt
import hmac
import os
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from . import db as D
from .agents import BotRunner
from .llm import LLMError
from .seed import seed
from .service import Bread, BreadError

WEB = Path(__file__).parent / "web"
COOKIE = "bread_session"
ADMIN_TOKEN = os.environ.get("BREAD_ADMIN_TOKEN") or secrets.token_urlsafe(16)
LLM_DAILY_CAP = int(os.environ.get("BREAD_LLM_DAILY_CAP", "800"))


class Budget:
    """One daily LLM budget shared by AutoMod and the agents, below the provider's free tier."""

    def __init__(self, cap: int) -> None:
        self.cap, self.day, self.used, self.lock = cap, "", 0, threading.Lock()

    def __call__(self) -> bool:
        with self.lock:
            today = dt.date.today().isoformat()
            if today != self.day:
                self.day, self.used = today, 0
            if self.used >= self.cap:
                return False
            self.used += 1
            return True


def make_llm():
    if not os.environ.get("LLM_API_KEY"):
        return None
    from .llm import Cache, OpenAICompatibleLLM

    return OpenAICompatibleLLM(
        os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        os.environ["LLM_API_KEY"],
        tokens_per_minute=int(os.environ.get("LLM_TOKENS_PER_MINUTE", "7000")),
        cache=Cache(os.environ.get("BREAD_CACHE", ".cache/llm.sqlite")),
        timeout=15,
        max_quota_wait_s=0,
    )


def create_app(database_url: str | None = None, llm="auto", agents: bool | None = None) -> FastAPI:
    engine = D.make_engine(database_url)
    seed(engine)
    llm = make_llm() if llm == "auto" else llm
    budget = Budget(LLM_DAILY_CAP)
    bread = Bread(engine, llm=llm, llm_budget=budget)
    app = FastAPI(title="bread", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.bread, app.state.budget = bread, budget
    app.state.runner = None

    if llm is not None:

        def automod_worker():
            while True:
                job = bread.reviews.get()
                try:
                    bread.run_ai_reviews([job])
                except (LLMError, Exception):  # noqa: BLE001 - one bad review must not stop the worker
                    pass

        threading.Thread(target=automod_worker, daemon=True, name="bread-automod").start()
        if agents if agents is not None else os.environ.get("BREAD_AGENTS", "on") != "off":
            app.state.runner = BotRunner(
                bread, llm, interval=float(os.environ.get("BREAD_AGENT_INTERVAL", "150")), budget=budget
            )
            app.state.runner.start()

    # ------------------------------------------------------------------ plumbing
    @app.exception_handler(BreadError)
    async def bread_error(request: Request, exc: BreadError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Cross-site request protection for cookie sessions: writes must come from this site.
        if (
            request.method in ("POST", "PATCH", "DELETE")
            and request.url.path.startswith("/api/")
            and request.cookies.get(COOKIE)
        ):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def viewer(request: Request):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return bread.by_api_key(auth[7:].strip())
        return bread.by_session(request.cookies.get(COOKIE))

    def need(request: Request):
        u = viewer(request)
        if not u:
            raise BreadError("Log in first.", 401)
        return u

    def admin(request: Request):
        u = need(request)
        if not u["is_admin"]:
            raise BreadError("Admins only.", 403)
        return u

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def ip(request: Request) -> str:
        return (
            (request.headers.get("x-forwarded-for") or (request.client.host if request.client else ""))
            .split(",")[0]
            .strip()
        )

    def with_ads(result: dict, community_id: int | None) -> dict:
        n = len(result["posts"]) // 7 + (1 if result["posts"] else 0)
        result["ads"] = bread.serve_ads(community_id, min(n, 3))
        return result

    # ------------------------------------------------------------------ accounts
    @app.post("/api/signup")
    async def signup(request: Request):
        b = await body(request)
        bread.signup(b.get("username", ""), b.get("password", ""), ip(request))
        return await login_response(request, b)

    async def login_response(request: Request, b: dict):
        token, _ = bread.login(b.get("username", ""), b.get("password", ""), ip(request))
        resp = JSONResponse({"ok": True})
        secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=secure, max_age=30 * 86400)
        return resp

    @app.post("/api/login")
    async def login(request: Request):
        return await login_response(request, await body(request))

    @app.post("/api/logout")
    async def logout(request: Request):
        token = request.cookies.get(COOKIE)
        if token:
            bread.logout(token)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/api/me")
    def me(request: Request):
        u = viewer(request)
        return (
            bread.me(u)
            if u
            else {"anonymous": True, "thresholds": {"post": D.POST_KARMA, "community": D.COMMUNITY_KARMA}}
        )

    @app.patch("/api/me")
    async def edit_me(request: Request):
        u = need(request)
        bread.set_bio(u, (await body(request)).get("bio", ""))
        return bread.me(bread.user(u["id"]))

    # ------------------------------------------------------------------ reading
    @app.get("/api/feed")
    def feed(request: Request, scope: str = "home", sort: str = "hot", t: str = "day", page: int = 0):
        u = viewer(request)
        if scope == "home" and not u:
            scope = "all"
        return with_ads(bread.feed(u, scope=scope, sort=sort, t=t, page=max(page, 0)), None)

    @app.get("/api/b/{name}")
    def community(name: str, request: Request):
        return bread.community_view(name, viewer(request))

    @app.get("/api/b/{name}/posts")
    def community_posts(name: str, request: Request, sort: str = "hot", t: str = "day", page: int = 0):
        com = bread.community(name)
        return with_ads(
            bread.feed(viewer(request), community=name, sort=sort, t=t, page=max(page, 0)), com["id"]
        )

    @app.get("/api/communities")
    def communities(sort: str = "members"):
        return bread.directory(sort)

    @app.get("/api/posts/{pid}")
    def post(pid: int, request: Request, sort: str = "best"):
        u = viewer(request)
        p = bread.post_view(pid, u)
        return {
            "post": p,
            "comments": bread.thread(pid, u, sort=sort),
            "community": bread.community_view(p["community"], u),
            "ads": bread.serve_ads(p["community_id"], 1),
        }

    @app.get("/api/users/{name}")
    def profile(name: str, request: Request):
        return bread.profile(name, viewer(request))

    @app.get("/api/saved")
    def saved(request: Request):
        return bread.feed(need(request), saved=True, sort="new")

    @app.get("/api/search")
    def search(request: Request, q: str = ""):
        return bread.search(q, viewer(request))

    @app.get("/api/notifications")
    def notifications(request: Request):
        return bread.notifications(need(request))

    # ------------------------------------------------------------------ writing
    @app.post("/api/communities")
    async def create_community(request: Request):
        b = await body(request)
        return bread.create_community(
            need(request),
            b.get("name", ""),
            b.get("title", ""),
            b.get("description", ""),
            b.get("rules") or [],
            b.get("color"),
        )

    @app.patch("/api/b/{name}")
    async def edit_community(name: str, request: Request):
        return bread.update_community(need(request), name, await body(request))

    @app.post("/api/b/{name}/join")
    async def join(name: str, request: Request):
        return bread.join(need(request), name, bool((await body(request)).get("join", True)))

    @app.post("/api/posts")
    async def create_post(request: Request):
        b = await body(request)
        return bread.create_post(
            need(request), b.get("community", ""), b.get("title", ""), b.get("body", ""), b.get("url")
        )

    @app.patch("/api/posts/{pid}")
    async def edit_post(pid: int, request: Request):
        bread.edit(need(request), "p", pid, (await body(request)).get("body", ""))
        return bread.post_view(pid, viewer(request))

    @app.delete("/api/posts/{pid}")
    def delete_post(pid: int, request: Request):
        bread.delete_own(need(request), "p", pid)
        return {"ok": True}

    @app.post("/api/posts/{pid}/comments")
    async def comment(pid: int, request: Request):
        b = await body(request)
        return bread.create_comment(need(request), pid, b.get("body", ""), b.get("parent_id"))

    @app.patch("/api/comments/{cid}")
    async def edit_comment(cid: int, request: Request):
        bread.edit(need(request), "c", cid, (await body(request)).get("body", ""))
        return bread.comment_view(cid, viewer(request))

    @app.delete("/api/comments/{cid}")
    def delete_comment(cid: int, request: Request):
        bread.delete_own(need(request), "c", cid)
        return {"ok": True}

    @app.post("/api/vote")
    async def vote(request: Request):
        b = await body(request)
        return bread.vote(need(request), b.get("kind", ""), int(b.get("id", 0)), int(b.get("value", 0)))

    @app.post("/api/save")
    async def save(request: Request):
        b = await body(request)
        bread.save(need(request), int(b.get("post_id", 0)), bool(b.get("save", True)))
        return {"ok": True}

    # ------------------------------------------------------------------ moderation
    @app.post("/api/report")
    async def report(request: Request):
        b = await body(request)
        bread.report(need(request), b.get("kind", ""), int(b.get("id", 0)), b.get("reason", ""))
        return {"ok": True}

    @app.get("/api/b/{name}/mod")
    def mod_queue(name: str, request: Request):
        return bread.mod_queue(need(request), name)

    @app.post("/api/moderate")
    async def moderate(request: Request):
        b = await body(request)
        bread.moderate(
            need(request), b.get("kind", ""), int(b.get("id", 0)), b.get("action", ""), b.get("reason", "")
        )
        return {"ok": True}

    @app.post("/api/reports/{rid}/dismiss")
    def dismiss(rid: int, request: Request):
        bread.dismiss_report(need(request), rid)
        return {"ok": True}

    @app.post("/api/b/{name}/ban")
    async def ban(name: str, request: Request):
        b = await body(request)
        bread.ban(need(request), name, b.get("username", ""), b.get("reason", ""), bool(b.get("ban", True)))
        return {"ok": True}

    @app.post("/api/b/{name}/mods")
    async def mods(name: str, request: Request):
        b = await body(request)
        bread.set_mod(need(request), name, b.get("username", ""), bool(b.get("mod", True)))
        return bread.community_view(name, viewer(request))

    # ------------------------------------------------------------------ bots and ads
    @app.post("/api/bots")
    async def create_bot(request: Request):
        b = await body(request)
        bot, key = bread.create_bot(need(request), b.get("username", ""), b.get("about", ""))
        return {
            "bot": bread.public_user(bot),
            "api_key": key,
            "note": "Store this key now: it is shown only once.",
        }

    @app.get("/api/bots")
    def bots(request: Request):
        return bread.my_bots(need(request))

    @app.post("/api/ads")
    async def create_ad(request: Request):
        b = await body(request)
        return bread.create_ad(
            need(request),
            b.get("title", ""),
            b.get("body", ""),
            b.get("url", ""),
            b.get("community") or None,
            int(b.get("max_impressions") or 1000),
        )

    @app.get("/api/ads/mine")
    def my_ads(request: Request):
        return bread.my_ads(need(request))

    @app.post("/api/ads/{aid}/pause")
    async def pause_ad(aid: int, request: Request):
        return bread.pause_ad(need(request), aid, bool((await body(request)).get("paused", True)))

    @app.get("/go/ad/{aid}")
    def ad_click(aid: int):
        return RedirectResponse(bread.click_ad(aid), status_code=302)

    # ------------------------------------------------------------------ site admin
    @app.post("/api/admin/claim")
    async def claim(request: Request):
        u = need(request)
        if not hmac.compare_digest(str((await body(request)).get("token", "")), ADMIN_TOKEN):
            raise BreadError("Wrong admin token.", 403)
        bread.make_admin(u)
        return {"ok": True}

    @app.get("/api/admin/stats")
    def stats(request: Request):
        admin(request)
        runner = app.state.runner
        return {
            **bread.stats(),
            "llm": {"attached": llm is not None, "used_today": budget.used, "cap": budget.cap},
            "agents": runner.log[-30:] if runner else [],
            "review_backlog": bread.reviews.qsize(),
        }

    @app.post("/api/admin/ads/{aid}")
    async def review_ad(aid: int, request: Request):
        b = await body(request)
        return bread.review_ad(admin(request), aid, bool(b.get("approve")), b.get("note", ""))

    @app.post("/api/admin/suspend")
    async def suspend(request: Request):
        b = await body(request)
        bread.suspend(admin(request), b.get("username", ""), bool(b.get("suspended", True)))
        return {"ok": True}

    # ------------------------------------------------------------------ the browser app
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "time": time.time()}

    @app.get("/static/{name}")
    def static(name: str):
        path = (WEB / name).resolve()
        if path.parent != WEB.resolve() or not path.is_file():
            return Response(status_code=404)
        return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})

    @app.get("/api/{rest:path}")
    def api_404(rest: str):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    @app.get("/{rest:path}")
    def spa(rest: str):
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def admin_token_hint() -> str:
    return "set by BREAD_ADMIN_TOKEN" if os.environ.get("BREAD_ADMIN_TOKEN") else ADMIN_TOKEN
