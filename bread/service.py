"""Everything bread does, in one place: the API layer only translates HTTP to these calls.

Karma is the sum of votes others give your posts and comments (your own upvote does not count).
New accounts can comment and vote; karma above 4 lets you post; above 10 lets you found a community.
"""

from __future__ import annotations

import datetime as dt
import queue
import random
import re
from urllib.parse import urlparse

from sqlalchemy import and_, case, delete, func, insert, or_, select, update

from . import db as D
from .moderation import AIModerator, check_rules
from .ranking import WINDOWS, best, controversial, hot
from .security import (
    COMMUNITY,
    RESERVED,
    USERNAME,
    allowed,
    check_password,
    hash_password,
    new_token,
    token_hash,
)

SESSION_DAYS = 30
COLORS = [
    "#d9822b",
    "#c0392b",
    "#2e86de",
    "#16a085",
    "#8e44ad",
    "#27ae60",
    "#e67e22",
    "#2c3e50",
    "#d35400",
    "#7f8c8d",
]


class BreadError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def karma(u) -> int:
    return int(u["post_karma"]) + int(u["comment_karma"])


def _clean(text: str | None, limit: int) -> str:
    return re.sub(r"\r\n?", "\n", (text or "").strip())[:limit]


def _url(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise BreadError("Links must start with http:// or https://")
    return url[:2000]


class Bread:
    def __init__(self, engine, llm=None, llm_budget=None) -> None:
        self.engine = engine
        self.llm = llm
        self.ai = AIModerator(llm) if llm else None
        self.llm_budget = llm_budget  # callable returning True while the daily LLM budget lasts
        self.reviews: queue.Queue = queue.Queue(maxsize=2000)  # drained by the AutoMod worker thread

    # ------------------------------------------------------------------ accounts
    def signup(self, username: str, password: str, ip: str = "") -> dict:
        username = (username or "").strip()
        if not USERNAME.match(username):
            raise BreadError("Usernames are 3 to 20 letters, numbers, - or _.")
        if username.lower() in RESERVED:
            raise BreadError("That username is reserved.")
        if len(password or "") < 8:
            raise BreadError("Passwords need at least 8 characters.")
        if not allowed("signup", ip):
            raise BreadError("Too many sign-ups from here. Try again later.", 429)
        with self.engine.begin() as c:
            if c.execute(
                select(D.users.c.id).where(func.lower(D.users.c.username) == username.lower())
            ).first():
                raise BreadError("That username is taken.", 409)
            uid = c.execute(
                insert(D.users).values(
                    username=username, password_hash=hash_password(password), created_at=D.now(), bio=""
                )
            ).inserted_primary_key[0]
            general = c.execute(
                select(D.communities.c.id).where(
                    D.communities.c.name.in_(["general", "askbread", "announcements"])
                )
            ).all()
            for (cid,) in general:  # start new people somewhere lively
                self._join(c, uid, cid)
        return self.user(uid)

    def login(self, username: str, password: str, ip: str = "") -> tuple[str, dict]:
        if not allowed("login", ip):
            raise BreadError("Too many attempts. Wait a few minutes.", 429)
        with self.engine.begin() as c:
            u = (
                c.execute(
                    select(D.users).where(func.lower(D.users.c.username) == (username or "").strip().lower())
                )
                .mappings()
                .first()
            )
            if not u or u["is_bot"] or not check_password(password or "", u["password_hash"]):
                raise BreadError("Wrong username or password.", 401)
            if u["banned"]:
                raise BreadError("This account is suspended.", 403)
            token = new_token()
            c.execute(
                insert(D.sessions).values(
                    token_hash=token_hash(token),
                    user_id=u["id"],
                    created_at=D.now(),
                    expires_at=D.now() + SESSION_DAYS * 86400,
                )
            )
        return token, dict(u)

    def logout(self, token: str) -> None:
        with self.engine.begin() as c:
            c.execute(delete(D.sessions).where(D.sessions.c.token_hash == token_hash(token)))

    def by_session(self, token: str | None):
        if not token:
            return None
        with self.engine.connect() as c:
            row = (
                c.execute(
                    select(D.users)
                    .join(D.sessions, D.sessions.c.user_id == D.users.c.id)
                    .where(D.sessions.c.token_hash == token_hash(token), D.sessions.c.expires_at > D.now())
                )
                .mappings()
                .first()
            )
        return dict(row) if row and not row["banned"] else None

    def by_api_key(self, key: str | None):
        if not key:
            return None
        with self.engine.connect() as c:
            row = (
                c.execute(select(D.users).where(D.users.c.api_key_hash == token_hash(key), D.users.c.is_bot))
                .mappings()
                .first()
            )
        return dict(row) if row and not row["banned"] else None

    def user(self, uid: int) -> dict:
        with self.engine.connect() as c:
            return dict(c.execute(select(D.users).where(D.users.c.id == uid)).mappings().one())

    def me(self, u) -> dict:
        with self.engine.connect() as c:
            joined = (
                c.execute(
                    select(D.communities.c.name, D.communities.c.color, D.members.c.role)
                    .join(D.members, D.members.c.community_id == D.communities.c.id)
                    .where(D.members.c.user_id == u["id"])
                    .order_by(D.communities.c.name)
                )
                .mappings()
                .all()
            )
            unread = c.execute(
                select(func.count())
                .select_from(D.notifications)
                .where(D.notifications.c.user_id == u["id"], D.notifications.c.read.is_(False))
            ).scalar()
        return {
            **self.public_user(u),
            "joined": [dict(j) for j in joined],
            "unread": unread,
            "can_post": karma(u) >= D.POST_KARMA or u["is_admin"],
            "can_found": karma(u) >= D.COMMUNITY_KARMA or u["is_admin"],
            "thresholds": {"post": D.POST_KARMA, "community": D.COMMUNITY_KARMA},
        }

    @staticmethod
    def public_user(u) -> dict:
        return {
            "id": u["id"],
            "username": u["username"],
            "karma": karma(u),
            "post_karma": u["post_karma"],
            "comment_karma": u["comment_karma"],
            "created_at": u["created_at"],
            "bio": u["bio"],
            "is_bot": u["is_bot"],
            "is_admin": u["is_admin"],
        }

    def set_bio(self, u, bio: str) -> None:
        with self.engine.begin() as c:
            c.execute(update(D.users).where(D.users.c.id == u["id"]).values(bio=_clean(bio, 300)))

    # ------------------------------------------------------------------ bots
    def create_bot(self, owner, username: str, about: str) -> tuple[dict, str]:
        if karma(owner) < D.BOT_OWNER_KARMA and not owner["is_admin"]:
            raise BreadError(f"You need {D.BOT_OWNER_KARMA} karma to register a bot.", 403)
        username = (username or "").strip()
        if not USERNAME.match(username) or username.lower() in RESERVED:
            raise BreadError("Bot usernames are 3 to 20 letters, numbers, - or _.")
        key = "bread_" + new_token()
        with self.engine.begin() as c:
            n = c.execute(
                select(func.count()).select_from(D.users).where(D.users.c.owner_id == owner["id"])
            ).scalar()
            if n >= D.MAX_BOTS_PER_USER and not owner["is_admin"]:
                raise BreadError(f"You can register up to {D.MAX_BOTS_PER_USER} bots.", 403)
            if c.execute(
                select(D.users.c.id).where(func.lower(D.users.c.username) == username.lower())
            ).first():
                raise BreadError("That username is taken.", 409)
            uid = c.execute(
                insert(D.users).values(
                    username=username,
                    created_at=D.now(),
                    bio=_clean(about, 300),
                    is_bot=True,
                    owner_id=owner["id"],
                    api_key_hash=token_hash(key),
                )
            ).inserted_primary_key[0]
        return self.user(uid), key

    def my_bots(self, owner) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(D.users).where(D.users.c.owner_id == owner["id"])).mappings().all()
        return [self.public_user(r) for r in rows]

    # ------------------------------------------------------------------ communities
    def community(self, name: str, conn=None) -> dict:
        def get(c):
            row = (
                c.execute(
                    select(D.communities).where(func.lower(D.communities.c.name) == (name or "").lower())
                )
                .mappings()
                .first()
            )
            if not row:
                raise BreadError("No community with that name.", 404)
            return dict(row)

        if conn is not None:
            return get(conn)
        with self.engine.connect() as c:
            return get(c)

    def role(self, c, uid: int | None, cid: int) -> str | None:
        if uid is None:
            return None
        return c.execute(
            select(D.members.c.role).where(D.members.c.user_id == uid, D.members.c.community_id == cid)
        ).scalar()

    def is_mod(self, c, u, cid: int) -> bool:
        return bool(u) and (u["is_admin"] or self.role(c, u["id"], cid) in ("mod", "owner"))

    def create_community(
        self, u, name: str, title: str, description: str, rules: list[str], color: str | None = None
    ) -> dict:
        if karma(u) < D.COMMUNITY_KARMA and not u["is_admin"]:
            raise BreadError(
                f"You need more than {D.COMMUNITY_KARMA - 1} karma to create a community (you have {karma(u)}).",
                403,
            )
        name = (name or "").strip()
        if not COMMUNITY.match(name) or name.lower() in RESERVED:
            raise BreadError("Community names are 3 to 21 letters, numbers or _.")
        if not allowed("community", u["id"]):
            raise BreadError("You have created enough communities for today.", 429)
        rules = [_clean(r, 200) for r in (rules or []) if _clean(r, 200)][:15]
        action, reason = check_rules(f"{name} {title} {description} " + " ".join(rules))
        if action == "remove":
            raise BreadError(f"That breaks the site policy ({reason}).")
        with self.engine.begin() as c:
            if c.execute(
                select(D.communities.c.id).where(func.lower(D.communities.c.name) == name.lower())
            ).first():
                raise BreadError("That community already exists.", 409)
            cid = c.execute(
                insert(D.communities).values(
                    name=name,
                    title=_clean(title, 100) or name,
                    description=_clean(description, 500),
                    rules=rules,
                    color=color if re.match(r"^#[0-9a-fA-F]{6}$", color or "") else random.choice(COLORS),
                    created_by=u["id"],
                    created_at=D.now(),
                    members=0,
                )
            ).inserted_primary_key[0]
            self._join(c, u["id"], cid, role="owner")
            self._log(c, cid, u["username"], "create_community", None, None, "")
        return self.community(name)

    def _join(self, c, uid: int, cid: int, role: str = "member") -> None:
        if self.role(c, uid, cid):
            if role != "member":
                c.execute(
                    update(D.members)
                    .where(D.members.c.user_id == uid, D.members.c.community_id == cid)
                    .values(role=role)
                )
            return
        c.execute(insert(D.members).values(user_id=uid, community_id=cid, role=role, joined_at=D.now()))
        c.execute(
            update(D.communities).where(D.communities.c.id == cid).values(members=D.communities.c.members + 1)
        )

    def join(self, u, name: str, joining: bool = True) -> dict:
        with self.engine.begin() as c:
            com = self.community(name, c)
            if joining:
                self._join(c, u["id"], com["id"])
            else:
                role = self.role(c, u["id"], com["id"])
                if role == "owner":
                    raise BreadError(
                        "Owners cannot leave their community. Hand it to another moderator first."
                    )
                if role:
                    c.execute(
                        delete(D.members).where(
                            D.members.c.user_id == u["id"], D.members.c.community_id == com["id"]
                        )
                    )
                    c.execute(
                        update(D.communities)
                        .where(D.communities.c.id == com["id"])
                        .values(members=D.communities.c.members - 1)
                    )
        return self.community_view(name, u)

    def community_view(self, name: str, viewer=None) -> dict:
        with self.engine.connect() as c:
            com = self.community(name, c)
            mods = (
                c.execute(
                    select(D.users.c.username, D.members.c.role)
                    .join(D.members, D.members.c.user_id == D.users.c.id)
                    .where(D.members.c.community_id == com["id"], D.members.c.role.in_(["mod", "owner"]))
                )
                .mappings()
                .all()
            )
            role = self.role(c, viewer["id"] if viewer else None, com["id"])
            banned = (
                bool(viewer)
                and c.execute(
                    select(D.bans.c.user_id).where(
                        D.bans.c.community_id == com["id"], D.bans.c.user_id == viewer["id"]
                    )
                ).first()
            )
            week = D.now() - 7 * 86400
            posts_week = c.execute(
                select(func.count())
                .select_from(D.posts)
                .where(D.posts.c.community_id == com["id"], D.posts.c.created_at >= week)
            ).scalar()
            comments_week = c.execute(
                select(func.count())
                .select_from(D.comments)
                .join(D.posts, D.posts.c.id == D.comments.c.post_id)
                .where(D.posts.c.community_id == com["id"], D.comments.c.created_at >= week)
            ).scalar()
        return {
            **com,
            "posts_week": posts_week,
            "comments_week": comments_week,
            "mods": [dict(m) for m in mods],
            "role": role,
            "is_mod": bool(viewer) and (viewer["is_admin"] or role in ("mod", "owner")),
            "banned": bool(banned),
        }

    def update_community(self, u, name: str, fields: dict) -> dict:
        with self.engine.begin() as c:
            com = self.community(name, c)
            if not self.is_mod(c, u, com["id"]):
                raise BreadError("Only moderators can change this community.", 403)
            values = {}
            if "title" in fields:
                values["title"] = _clean(fields["title"], 100) or com["name"]
            if "description" in fields:
                values["description"] = _clean(fields["description"], 500)
            if "rules" in fields:
                values["rules"] = [_clean(r, 200) for r in fields["rules"] if _clean(r, 200)][:15]
            if "color" in fields and re.match(r"^#[0-9a-fA-F]{6}$", fields["color"] or ""):
                values["color"] = fields["color"]
            for flag in ("restricted", "allow_bots", "ai_review"):
                if flag in fields:
                    values[flag] = bool(fields[flag])
            if values:
                c.execute(update(D.communities).where(D.communities.c.id == com["id"]).values(**values))
                self._log(c, com["id"], u["username"], "edit_settings", None, None, ", ".join(values))
        return self.community_view(name, u)

    def directory(self, sort: str = "members", limit: int = 50) -> list[dict]:
        order = D.communities.c.members.desc() if sort != "new" else D.communities.c.created_at.desc()
        with self.engine.connect() as c:
            return [
                dict(r)
                for r in c.execute(select(D.communities).order_by(order).limit(limit)).mappings().all()
            ]

    # ------------------------------------------------------------------ posts and comments
    def _can_participate(self, c, u, com, posting: bool) -> None:
        if u["banned"]:
            raise BreadError("This account is suspended.", 403)
        if c.execute(
            select(D.bans.c.user_id).where(D.bans.c.community_id == com["id"], D.bans.c.user_id == u["id"])
        ).first():
            raise BreadError(f"You are banned from b/{com['name']}.", 403)
        if u["is_bot"] and not com["allow_bots"]:
            raise BreadError(f"b/{com['name']} does not allow bots.", 403)
        mod = self.is_mod(c, u, com["id"])
        if posting and com["restricted"] and not mod:
            raise BreadError(f"Only moderators can post in b/{com['name']}.", 403)
        if posting and not mod and karma(u) < D.POST_KARMA:
            raise BreadError(
                f"You need more than {D.POST_KARMA - 1} karma to post (you have {karma(u)}). "
                "Comment and help others to earn karma first.",
                403,
            )

    def create_post(self, u, community: str, title: str, body: str = "", url: str | None = None) -> dict:
        title, body, url = _clean(title, 300), _clean(body, 20000), _url(url)
        if len(title) < 3:
            raise BreadError("Give your post a title.")
        if not allowed("post", u["id"]):
            raise BreadError("You are posting very fast. Take a short break.", 429)
        with self.engine.begin() as c:
            com = self.community(community, c)
            self._can_participate(c, u, com, posting=True)
            now = D.now()
            pid = c.execute(
                insert(D.posts).values(
                    community_id=com["id"],
                    author_id=u["id"],
                    title=title,
                    body=body,
                    url=url,
                    created_at=now,
                    hot=hot(1, now),
                )
            ).inserted_primary_key[0]
            c.execute(insert(D.votes).values(user_id=u["id"], kind="p", target_id=pid, value=1))
            self._automod(c, "p", pid, com, f"{title}\n{body}\n{url or ''}")
        self._ai_review_later("p", pid, com)
        return self.post_view(pid, u)

    def create_comment(self, u, post_id: int, body: str, parent_id: int | None = None) -> dict:
        body = _clean(body, 10000)
        if not body:
            raise BreadError("Write something first.")
        if not allowed("comment", u["id"]):
            raise BreadError("You are commenting very fast. Take a short break.", 429)
        with self.engine.begin() as c:
            post = c.execute(select(D.posts).where(D.posts.c.id == post_id)).mappings().first()
            if not post or post["deleted"]:
                raise BreadError("That post is gone.", 404)
            com = dict(
                c.execute(select(D.communities).where(D.communities.c.id == post["community_id"]))
                .mappings()
                .one()
            )
            if (post["locked"] or post["removed"]) and not self.is_mod(c, u, com["id"]):
                raise BreadError("Comments are locked on this post.", 403)
            self._can_participate(c, u, com, posting=False)
            depth, parent = 0, None
            if parent_id:
                parent = (
                    c.execute(
                        select(D.comments).where(
                            D.comments.c.id == parent_id, D.comments.c.post_id == post_id
                        )
                    )
                    .mappings()
                    .first()
                )
                if not parent:
                    raise BreadError("That comment is gone.", 404)
                depth = min(parent["depth"] + 1, 12)
            cid = c.execute(
                insert(D.comments).values(
                    post_id=post_id,
                    parent_id=parent_id,
                    author_id=u["id"],
                    body=body,
                    depth=depth,
                    created_at=D.now(),
                )
            ).inserted_primary_key[0]
            c.execute(insert(D.votes).values(user_id=u["id"], kind="c", target_id=cid, value=1))
            c.execute(
                update(D.posts)
                .where(D.posts.c.id == post_id)
                .values(comment_count=D.posts.c.comment_count + 1)
            )
            to = parent["author_id"] if parent else post["author_id"]
            if to != u["id"]:
                what = "comment" if parent else f'post "{post["title"][:60]}"'
                self._notify(
                    c,
                    to,
                    "reply",
                    f"u/{u['username']} replied to your {what}: {body[:120]}",
                    f"/b/{com['name']}/comments/{post_id}#c{cid}",
                )
            self._automod(c, "c", cid, com, body)
        self._ai_review_later("c", cid, com)
        return self.comment_view(cid, u)

    def edit(self, u, kind: str, target_id: int, body: str) -> None:
        table = D.posts if kind == "p" else D.comments
        with self.engine.begin() as c:
            row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
            if not row or row["author_id"] != u["id"] or row["deleted"]:
                raise BreadError("You can only edit your own posts and comments.", 403)
            body = _clean(body, 20000 if kind == "p" else 10000)
            c.execute(update(table).where(table.c.id == target_id).values(body=body, edited_at=D.now()))
            com_id = (
                row["community_id"]
                if kind == "p"
                else c.execute(select(D.posts.c.community_id).where(D.posts.c.id == row["post_id"])).scalar()
            )
            com = dict(c.execute(select(D.communities).where(D.communities.c.id == com_id)).mappings().one())
            self._automod(c, kind, target_id, com, body)

    def delete_own(self, u, kind: str, target_id: int) -> None:
        table = D.posts if kind == "p" else D.comments
        with self.engine.begin() as c:
            row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
            if not row or (row["author_id"] != u["id"] and not u["is_admin"]):
                raise BreadError("You can only delete your own posts and comments.", 403)
            c.execute(update(table).where(table.c.id == target_id).values(deleted=True, body=""))

    # ------------------------------------------------------------------ votes and saves
    def vote(self, u, kind: str, target_id: int, value: int) -> dict:
        if kind not in ("p", "c") or value not in (-1, 0, 1):
            raise BreadError("Bad vote.")
        if not allowed("vote", u["id"]):
            raise BreadError("Slow down a little.", 429)
        table = D.posts if kind == "p" else D.comments
        with self.engine.begin() as c:
            row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
            if not row or row["deleted"] or row["removed"]:
                raise BreadError("That is no longer available.", 404)
            old = (
                c.execute(
                    select(D.votes.c.value).where(
                        D.votes.c.user_id == u["id"], D.votes.c.kind == kind, D.votes.c.target_id == target_id
                    )
                ).scalar()
                or 0
            )
            if old == value:
                return {"score": row["score"], "vote": value}
            if old:
                c.execute(
                    delete(D.votes).where(
                        D.votes.c.user_id == u["id"], D.votes.c.kind == kind, D.votes.c.target_id == target_id
                    )
                )
            if value:
                c.execute(
                    insert(D.votes).values(user_id=u["id"], kind=kind, target_id=target_id, value=value)
                )
            ups = row["ups"] - (old == 1) + (value == 1)
            downs = row["downs"] - (old == -1) + (value == -1)
            score = ups - downs
            values = {"ups": ups, "downs": downs, "score": score}
            if kind == "p":
                values["hot"] = hot(score, row["created_at"])
            c.execute(update(table).where(table.c.id == target_id).values(**values))
            if row["author_id"] != u["id"]:  # your own votes never earn you karma
                col = "post_karma" if kind == "p" else "comment_karma"
                c.execute(
                    update(D.users)
                    .where(D.users.c.id == row["author_id"])
                    .values({col: getattr(D.users.c, col) + (value - old)})
                )
        return {"score": score, "vote": value}

    def save(self, u, post_id: int, saving: bool = True) -> None:
        with self.engine.begin() as c:
            c.execute(delete(D.saves).where(D.saves.c.user_id == u["id"], D.saves.c.post_id == post_id))
            if saving:
                c.execute(insert(D.saves).values(user_id=u["id"], post_id=post_id, created_at=D.now()))

    # ------------------------------------------------------------------ reading
    def _post_query(self, viewer):
        q = select(
            D.posts,
            D.users.c.username.label("author"),
            D.users.c.is_bot.label("author_is_bot"),
            D.communities.c.name.label("community"),
            D.communities.c.color.label("community_color"),
        )
        q = q.join(D.users, D.users.c.id == D.posts.c.author_id).join(
            D.communities, D.communities.c.id == D.posts.c.community_id
        )
        if viewer:
            myvote = (
                select(D.votes.c.value)
                .where(
                    D.votes.c.user_id == viewer["id"],
                    D.votes.c.kind == "p",
                    D.votes.c.target_id == D.posts.c.id,
                )
                .correlate(D.posts)
                .scalar_subquery()
            )
            saved = (
                select(func.count())
                .select_from(D.saves)
                .where(D.saves.c.user_id == viewer["id"], D.saves.c.post_id == D.posts.c.id)
                .correlate(D.posts)
                .scalar_subquery()
            )
            q = q.add_columns(myvote.label("my_vote"), saved.label("saved"))
        return q

    def _post_out(self, r) -> dict:
        p = dict(r)
        if p["deleted"]:
            p.update(body="", author="[deleted]", title=p["title"] if not p["removed"] else "[removed]")
        if p["removed"]:
            p["body"] = ""
        p["my_vote"] = p.get("my_vote") or 0
        p["saved"] = bool(p.get("saved"))
        return p

    def feed(
        self,
        viewer=None,
        scope: str = "all",
        community: str | None = None,
        sort: str = "hot",
        t: str = "day",
        page: int = 0,
        limit: int = 25,
        author: str | None = None,
        saved: bool = False,
    ) -> dict:
        q = self._post_query(viewer).where(D.posts.c.removed.is_(False), D.posts.c.deleted.is_(False))
        com = None
        with self.engine.connect() as c:
            if community:
                com = self.community(community, c)
                q = q.where(D.posts.c.community_id == com["id"])
            elif author:
                q = q.where(func.lower(D.users.c.username) == author.lower())
            elif saved and viewer:
                q = q.join(
                    D.saves, and_(D.saves.c.post_id == D.posts.c.id, D.saves.c.user_id == viewer["id"])
                )
            elif scope == "home" and viewer:
                joined = select(D.members.c.community_id).where(D.members.c.user_id == viewer["id"])
                q = q.where(D.posts.c.community_id.in_(joined))
            elif scope == "popular":
                q = q.where(D.posts.c.score >= 2)
            window = WINDOWS.get(t)
            if sort == "top" and window:
                q = q.where(D.posts.c.created_at >= D.now() - window)
            if sort == "new":
                q = q.order_by(D.posts.c.created_at.desc())
            elif sort == "top":
                q = q.order_by(D.posts.c.score.desc(), D.posts.c.created_at.desc())
            elif sort == "rising":
                q = q.where(D.posts.c.created_at >= D.now() - 86400).order_by(
                    (D.posts.c.score + D.posts.c.comment_count).desc()
                )
            elif sort == "controversial":
                q = q.where(D.posts.c.ups > 1, D.posts.c.downs > 0).order_by(
                    (D.posts.c.ups + D.posts.c.downs).desc()
                )
            else:
                q = q.order_by(*([D.posts.c.pinned.desc()] if community else []), D.posts.c.hot.desc())
            rows = c.execute(q.offset(page * limit).limit(limit + 1)).mappings().all()
        items = [self._post_out(r) for r in rows[:limit]]
        if sort == "controversial":
            items.sort(key=lambda p: -controversial(p["ups"], p["downs"]))
        return {"posts": items, "more": len(rows) > limit, "page": page}

    def post_view(self, post_id: int, viewer=None) -> dict:
        with self.engine.connect() as c:
            r = c.execute(self._post_query(viewer).where(D.posts.c.id == post_id)).mappings().first()
            if not r:
                raise BreadError("That post does not exist.", 404)
            p = self._post_out(r)
            if p["removed"] and not (
                viewer and (viewer["id"] == p["author_id"] or self.is_mod(c, viewer, p["community_id"]))
            ):
                p.update(title="[removed by moderators]", body="", url=None)
        return p

    def comment_view(self, cid: int, viewer=None) -> dict:
        return next(x for x in self.thread(self.post_id_of(cid), viewer, flat=True) if x["id"] == cid)

    def post_id_of(self, cid: int) -> int:
        with self.engine.connect() as c:
            return c.execute(select(D.comments.c.post_id).where(D.comments.c.id == cid)).scalar_one()

    def thread(self, post_id: int, viewer=None, sort: str = "best", flat: bool = False) -> list[dict]:
        q = (
            select(D.comments, D.users.c.username.label("author"), D.users.c.is_bot.label("author_is_bot"))
            .join(D.users, D.users.c.id == D.comments.c.author_id)
            .where(D.comments.c.post_id == post_id)
        )
        if viewer:
            q = q.add_columns(
                select(D.votes.c.value)
                .where(
                    D.votes.c.user_id == viewer["id"],
                    D.votes.c.kind == "c",
                    D.votes.c.target_id == D.comments.c.id,
                )
                .correlate(D.comments)
                .scalar_subquery()
                .label("my_vote")
            )
        with self.engine.connect() as c:
            rows = [dict(r) for r in c.execute(q).mappings().all()]
            com_id = c.execute(select(D.posts.c.community_id).where(D.posts.c.id == post_id)).scalar()
            mod = bool(viewer) and com_id is not None and self.is_mod(c, viewer, com_id)
        for r in rows:
            r["my_vote"] = r.get("my_vote") or 0
            if r["deleted"]:
                r.update(body="", author="[deleted]")
            elif r["removed"] and not (mod or (viewer and viewer["id"] == r["author_id"])):
                r["body"] = ""
        if flat:
            return rows
        key = {
            "new": lambda r: -r["created_at"],
            "top": lambda r: -r["score"],
            "old": lambda r: r["created_at"],
            "controversial": lambda r: -controversial(r["ups"], r["downs"]),
        }.get(sort, lambda r: -best(r["ups"], r["downs"]))
        children: dict = {}
        for r in sorted(rows, key=key):
            children.setdefault(r["parent_id"], []).append(r)

        def build(parent):
            out = []
            for r in children.get(parent, []):
                r["replies"] = build(r["id"])
                if (r["removed"] or r["deleted"]) and not r["body"] and not r["replies"]:
                    continue  # nothing worth showing
                out.append(r)
            return out

        return build(None)

    def profile(self, username: str, viewer=None) -> dict:
        with self.engine.connect() as c:
            u = (
                c.execute(select(D.users).where(func.lower(D.users.c.username) == (username or "").lower()))
                .mappings()
                .first()
            )
            if not u:
                raise BreadError("No such user.", 404)
            owner = (
                c.execute(select(D.users.c.username).where(D.users.c.id == u["owner_id"])).scalar()
                if u["owner_id"]
                else None
            )
            recent = (
                c.execute(
                    select(
                        D.comments.c.id,
                        D.comments.c.body,
                        D.comments.c.score,
                        D.comments.c.created_at,
                        D.comments.c.post_id,
                        D.posts.c.title,
                        D.communities.c.name.label("community"),
                    )
                    .join(D.posts, D.posts.c.id == D.comments.c.post_id)
                    .join(D.communities, D.communities.c.id == D.posts.c.community_id)
                    .where(
                        D.comments.c.author_id == u["id"],
                        D.comments.c.deleted.is_(False),
                        D.comments.c.removed.is_(False),
                    )
                    .order_by(D.comments.c.created_at.desc())
                    .limit(30)
                )
                .mappings()
                .all()
            )
            moderates = (
                c.execute(
                    select(D.communities.c.name)
                    .join(D.members, D.members.c.community_id == D.communities.c.id)
                    .where(D.members.c.user_id == u["id"], D.members.c.role.in_(["mod", "owner"]))
                )
                .scalars()
                .all()
            )
        return {
            **self.public_user(u),
            "owner": owner,
            "comments": [dict(r) for r in recent],
            "moderates": list(moderates),
            "posts": self.feed(viewer, author=u["username"], sort="new")["posts"],
        }

    def search(self, q: str, viewer=None, community: str | None = None) -> dict:
        q = (q or "").strip()[:80]
        if len(q) < 2:
            return {"communities": [], "posts": [], "users": []}
        like = f"%{q.lower()}%"
        with self.engine.connect() as c:
            coms = (
                c.execute(
                    select(D.communities)
                    .where(
                        or_(
                            func.lower(D.communities.c.name).like(like),
                            func.lower(D.communities.c.title).like(like),
                        )
                    )
                    .order_by(D.communities.c.members.desc())
                    .limit(8)
                )
                .mappings()
                .all()
            )
            people = (
                c.execute(select(D.users).where(func.lower(D.users.c.username).like(like)).limit(8))
                .mappings()
                .all()
            )
            found = (
                c.execute(
                    self._post_query(viewer)
                    .where(
                        D.posts.c.removed.is_(False),
                        D.posts.c.deleted.is_(False),
                        or_(func.lower(D.posts.c.title).like(like), func.lower(D.posts.c.body).like(like)),
                        *([func.lower(D.communities.c.name) == community.lower()] if community else []),
                    )
                    .order_by(D.posts.c.score.desc())
                    .limit(25)
                )
                .mappings()
                .all()
            )
        return {
            "communities": [dict(r) for r in coms],
            "users": [self.public_user(r) for r in people],
            "posts": [self._post_out(r) for r in found],
        }

    # ------------------------------------------------------------------ notifications
    def _notify(self, c, uid: int, kind: str, text: str, link: str | None = None) -> None:
        c.execute(
            insert(D.notifications).values(
                user_id=uid, kind=kind, text=text[:400], link=link, created_at=D.now()
            )
        )

    def notifications(self, u, mark_read: bool = True) -> list[dict]:
        with self.engine.begin() as c:
            rows = (
                c.execute(
                    select(D.notifications)
                    .where(D.notifications.c.user_id == u["id"])
                    .order_by(D.notifications.c.created_at.desc())
                    .limit(50)
                )
                .mappings()
                .all()
            )
            if mark_read:
                c.execute(
                    update(D.notifications).where(D.notifications.c.user_id == u["id"]).values(read=True)
                )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ moderation
    def _log(self, c, cid, actor: str, action: str, kind, target_id, reason: str) -> None:
        c.execute(
            insert(D.modlog).values(
                community_id=cid,
                actor=actor,
                action=action,
                kind=kind,
                target_id=target_id,
                reason=(reason or "")[:300],
                created_at=D.now(),
            )
        )

    def _automod(
        self, c, kind: str, target_id: int, com: dict, text: str, source: str = "rules", verdict=None
    ) -> str:
        if verdict is None:
            started = D.now()
            action, reason = check_rules(text)
            ms = (D.now() - started) * 1000
        else:
            action, reason, ms = verdict["verdict"], verdict["reason"] or verdict["rule"], verdict["ms"]
        c.execute(
            insert(D.decisions).values(
                kind=kind,
                target_id=target_id,
                community_id=com["id"],
                source=source,
                action=action,
                reason=reason,
                ms=ms,
                created_at=D.now(),
            )
        )
        table = D.posts if kind == "p" else D.comments
        if action == "remove":
            c.execute(
                update(table)
                .where(table.c.id == target_id)
                .values(removed=True, removed_by="AutoMod", removed_reason=f"AutoMod ({source}): {reason}")
            )
            self._log(
                c,
                com["id"],
                "AutoMod",
                "remove_" + ("post" if kind == "p" else "comment"),
                kind,
                target_id,
                f"{source}: {reason}",
            )
            author = c.execute(select(table.c.author_id).where(table.c.id == target_id)).scalar()
            self._notify(
                c,
                author,
                "removed",
                f"AutoMod removed your {'post' if kind == 'p' else 'comment'} in b/{com['name']}: {reason}. "
                "A moderator can restore it if this was a mistake.",
            )
        elif action == "flag":
            c.execute(
                insert(D.reports).values(
                    reporter="AutoMod",
                    kind=kind,
                    target_id=target_id,
                    community_id=com["id"],
                    reason=f"{source}: {reason}",
                    created_at=D.now(),
                )
            )
        return action

    def _ai_review_later(self, kind: str, target_id: int, com: dict) -> None:
        """Queue the AI moderator; a worker thread reviews in the background so posting stays instant."""
        if self.ai and com.get("ai_review", True):
            try:
                self.reviews.put_nowait((kind, target_id, com["id"]))
            except queue.Full:
                pass  # under a flood, rules still apply; the AI layer catches up later

    def run_ai_reviews(self, jobs) -> None:
        for kind, target_id, cid in jobs:
            if self.llm_budget and not self.llm_budget():
                return
            table = D.posts if kind == "p" else D.comments
            with self.engine.connect() as c:
                row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
                com = dict(c.execute(select(D.communities).where(D.communities.c.id == cid)).mappings().one())
            if not row or row["removed"] or row["deleted"]:
                continue
            text = (
                (row["title"] + "\n" if kind == "p" else "")
                + row["body"]
                + ("\n" + row["url"] if kind == "p" and row["url"] else "")
            )
            verdict = self.ai.review(text, com["rules"])
            if not verdict.get("ok"):
                continue
            with self.engine.begin() as c:
                self._automod(c, kind, target_id, com, text, source="llm", verdict=verdict)

    def report(self, u, kind: str, target_id: int, reason: str) -> None:
        if not allowed("report", u["id"]):
            raise BreadError("You have sent a lot of reports. Thank you; try again later.", 429)
        table = D.posts if kind == "p" else D.comments
        with self.engine.begin() as c:
            row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
            if not row:
                raise BreadError("Nothing to report.", 404)
            cid = (
                row["community_id"]
                if kind == "p"
                else c.execute(select(D.posts.c.community_id).where(D.posts.c.id == row["post_id"])).scalar()
            )
            c.execute(
                insert(D.reports).values(
                    reporter=u["username"],
                    kind=kind,
                    target_id=target_id,
                    community_id=cid,
                    reason=_clean(reason, 300) or "Breaks the rules",
                    created_at=D.now(),
                )
            )

    def mod_queue(self, u, name: str) -> dict:
        with self.engine.connect() as c:
            com = self.community(name, c)
            if not self.is_mod(c, u, com["id"]):
                raise BreadError("Only moderators can see the queue.", 403)
            reps = (
                c.execute(
                    select(D.reports)
                    .where(D.reports.c.community_id == com["id"], D.reports.c.resolved.is_(False))
                    .order_by(D.reports.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            removed_posts = (
                c.execute(
                    select(D.posts.c.id)
                    .where(D.posts.c.community_id == com["id"], D.posts.c.removed_by == "AutoMod")
                    .order_by(D.posts.c.created_at.desc())
                    .limit(30)
                )
                .scalars()
                .all()
            )
            removed_comments = (
                c.execute(
                    select(D.comments.c.id)
                    .join(D.posts, D.posts.c.id == D.comments.c.post_id)
                    .where(D.posts.c.community_id == com["id"], D.comments.c.removed_by == "AutoMod")
                    .order_by(D.comments.c.created_at.desc())
                    .limit(30)
                )
                .scalars()
                .all()
            )
            log = (
                c.execute(
                    select(D.modlog)
                    .where(D.modlog.c.community_id == com["id"])
                    .order_by(D.modlog.c.created_at.desc())
                    .limit(60)
                )
                .mappings()
                .all()
            )
            banned = (
                c.execute(
                    select(D.users.c.username, D.bans.c.reason)
                    .join(D.bans, D.bans.c.user_id == D.users.c.id)
                    .where(D.bans.c.community_id == com["id"])
                )
                .mappings()
                .all()
            )
        items = {}
        for kind, ids in (
            ("p", [r["target_id"] for r in reps if r["kind"] == "p"] + list(removed_posts)),
            ("c", [r["target_id"] for r in reps if r["kind"] == "c"] + list(removed_comments)),
        ):
            for i in set(ids):
                items[f"{kind}{i}"] = self._item(kind, i)
        return {
            "reports": [dict(r) for r in reps],
            "removed": [f"p{i}" for i in removed_posts] + [f"c{i}" for i in removed_comments],
            "items": items,
            "log": [dict(r) for r in log],
            "banned": [dict(b) for b in banned],
        }

    def _item(self, kind: str, target_id: int) -> dict | None:
        table = D.posts if kind == "p" else D.comments
        with self.engine.connect() as c:
            r = (
                c.execute(
                    select(table, D.users.c.username.label("author"))
                    .join(D.users, D.users.c.id == table.c.author_id)
                    .where(table.c.id == target_id)
                )
                .mappings()
                .first()
            )
        return dict(r) if r else None

    def moderate(self, u, kind: str, target_id: int, action: str, reason: str = "") -> None:
        table = D.posts if kind == "p" else D.comments
        with self.engine.begin() as c:
            row = c.execute(select(table).where(table.c.id == target_id)).mappings().first()
            if not row:
                raise BreadError("Nothing to moderate.", 404)
            cid = (
                row["community_id"]
                if kind == "p"
                else c.execute(select(D.posts.c.community_id).where(D.posts.c.id == row["post_id"])).scalar()
            )
            if not self.is_mod(c, u, cid):
                raise BreadError("Only moderators can do that.", 403)
            com_name = c.execute(select(D.communities.c.name).where(D.communities.c.id == cid)).scalar()
            if action == "remove":
                c.execute(
                    update(table)
                    .where(table.c.id == target_id)
                    .values(removed=True, removed_by=u["username"], removed_reason=_clean(reason, 300))
                )
                self._notify(
                    c,
                    row["author_id"],
                    "removed",
                    f"A moderator of b/{com_name} removed your {'post' if kind == 'p' else 'comment'}"
                    + (f": {reason}" if reason else "."),
                )
            elif action == "approve":
                if row["removed_by"] == "AutoMod":  # a human disagreed with AutoMod: count it
                    c.execute(
                        update(D.decisions)
                        .where(
                            D.decisions.c.kind == kind,
                            D.decisions.c.target_id == target_id,
                            D.decisions.c.action == "remove",
                        )
                        .values(overturned=True)
                    )
                c.execute(
                    update(table)
                    .where(table.c.id == target_id)
                    .values(removed=False, removed_by=None, removed_reason=None)
                )
            elif action in ("lock", "unlock", "pin", "unpin") and kind == "p":
                if (
                    action == "pin"
                    and c.execute(
                        select(func.count())
                        .select_from(D.posts)
                        .where(D.posts.c.community_id == cid, D.posts.c.pinned)
                    ).scalar()
                    >= 2
                ):
                    raise BreadError("Two posts are already pinned.")
                field = "locked" if action in ("lock", "unlock") else "pinned"
                c.execute(
                    update(D.posts)
                    .where(D.posts.c.id == target_id)
                    .values({field: action in ("lock", "pin")})
                )
            else:
                raise BreadError("Unknown moderator action.")
            c.execute(
                update(D.reports)
                .where(
                    D.reports.c.kind == kind,
                    D.reports.c.target_id == target_id,
                    D.reports.c.resolved.is_(False),
                )
                .values(resolved=True, outcome=action)
            )
            if action == "approve":  # flags AutoMod raised on approved content were not needed
                c.execute(
                    update(D.decisions)
                    .where(
                        D.decisions.c.kind == kind,
                        D.decisions.c.target_id == target_id,
                        D.decisions.c.action == "flag",
                    )
                    .values(overturned=True)
                )
            self._log(
                c,
                cid,
                u["username"],
                f"{action}_{'post' if kind == 'p' else 'comment'}",
                kind,
                target_id,
                reason,
            )

    def dismiss_report(self, u, report_id: int) -> None:
        with self.engine.begin() as c:
            rep = c.execute(select(D.reports).where(D.reports.c.id == report_id)).mappings().first()
            if not rep or not self.is_mod(c, u, rep["community_id"]):
                raise BreadError("Only moderators can do that.", 403)
            c.execute(
                update(D.reports)
                .where(D.reports.c.id == report_id)
                .values(resolved=True, outcome="dismissed")
            )
            if rep["reporter"] == "AutoMod":
                c.execute(
                    update(D.decisions)
                    .where(
                        D.decisions.c.kind == rep["kind"],
                        D.decisions.c.target_id == rep["target_id"],
                        D.decisions.c.action == "flag",
                    )
                    .values(overturned=True)
                )

    def ban(self, u, name: str, username: str, reason: str, banning: bool = True) -> None:
        with self.engine.begin() as c:
            com = self.community(name, c)
            if not self.is_mod(c, u, com["id"]):
                raise BreadError("Only moderators can ban.", 403)
            target = (
                c.execute(select(D.users).where(func.lower(D.users.c.username) == (username or "").lower()))
                .mappings()
                .first()
            )
            if not target:
                raise BreadError("No such user.", 404)
            if self.role(c, target["id"], com["id"]) in ("mod", "owner"):
                raise BreadError("Moderators cannot be banned.")
            c.execute(
                delete(D.bans).where(D.bans.c.community_id == com["id"], D.bans.c.user_id == target["id"])
            )
            if banning:
                c.execute(
                    insert(D.bans).values(
                        community_id=com["id"],
                        user_id=target["id"],
                        reason=_clean(reason, 300),
                        created_at=D.now(),
                    )
                )
                self._notify(
                    c,
                    target["id"],
                    "ban",
                    f"You were banned from b/{com['name']}" + (f": {reason}" if reason else "."),
                )
            self._log(
                c,
                com["id"],
                u["username"],
                "ban" if banning else "unban",
                None,
                target["id"],
                f"u/{target['username']} {reason}",
            )

    def set_mod(self, u, name: str, username: str, making: bool = True) -> None:
        with self.engine.begin() as c:
            com = self.community(name, c)
            if not (u["is_admin"] or self.role(c, u["id"], com["id"]) == "owner"):
                raise BreadError("Only the community owner can change moderators.", 403)
            target = (
                c.execute(select(D.users).where(func.lower(D.users.c.username) == (username or "").lower()))
                .mappings()
                .first()
            )
            if not target:
                raise BreadError("No such user.", 404)
            if self.role(c, target["id"], com["id"]) == "owner":
                raise BreadError("The owner is always a moderator.")
            if making:
                self._join(c, target["id"], com["id"], role="mod")
                self._notify(
                    c,
                    target["id"],
                    "mod",
                    f"You are now a moderator of b/{com['name']}.",
                    f"/b/{com['name']}/mod",
                )
            else:
                c.execute(
                    update(D.members)
                    .where(D.members.c.user_id == target["id"], D.members.c.community_id == com["id"])
                    .values(role="member")
                )
            self._log(
                c,
                com["id"],
                u["username"],
                "add_mod" if making else "remove_mod",
                None,
                target["id"],
                f"u/{target['username']}",
            )

    # ------------------------------------------------------------------ ads
    def create_ad(
        self, u, title: str, body: str, url: str, community: str | None, max_impressions: int
    ) -> dict:
        if not allowed("ad", u["id"]):
            raise BreadError("You have submitted enough ads for today.", 429)
        title, body, url = _clean(title, 200), _clean(body, 600), _url(url)
        if len(title) < 3 or not url:
            raise BreadError("Ads need a headline and a link.")
        action, reason = check_rules(f"{title}\n{body}")
        if action == "remove":
            raise BreadError(f"That ad breaks the site policy ({reason}).")
        with self.engine.begin() as c:
            cid = self.community(community, c)["id"] if community else None
            aid = c.execute(
                insert(D.ads).values(
                    advertiser_id=u["id"],
                    title=title,
                    body=body,
                    url=url,
                    community_id=cid,
                    max_impressions=int(min(max(max_impressions or 1000, 100), 100000)),
                    created_at=D.now(),
                    status="pending",
                )
            ).inserted_primary_key[0]
        return self.ad(aid)

    def ad(self, aid: int) -> dict:
        with self.engine.connect() as c:
            r = (
                c.execute(
                    select(
                        D.ads, D.communities.c.name.label("community"), D.users.c.username.label("advertiser")
                    )
                    .outerjoin(D.communities, D.communities.c.id == D.ads.c.community_id)
                    .join(D.users, D.users.c.id == D.ads.c.advertiser_id)
                    .where(D.ads.c.id == aid)
                )
                .mappings()
                .first()
            )
        if not r:
            raise BreadError("No such ad.", 404)
        return dict(r)

    def my_ads(self, u) -> list[dict]:
        with self.engine.connect() as c:
            ids = (
                c.execute(
                    select(D.ads.c.id)
                    .where(D.ads.c.advertiser_id == u["id"])
                    .order_by(D.ads.c.created_at.desc())
                )
                .scalars()
                .all()
            )
        return [self.ad(i) for i in ids]

    def pause_ad(self, u, aid: int, paused: bool) -> dict:
        ad = self.ad(aid)
        if ad["advertiser_id"] != u["id"] and not u["is_admin"]:
            raise BreadError("Not your ad.", 403)
        if ad["status"] not in ("approved", "paused"):
            raise BreadError("Only approved ads can be paused.")
        with self.engine.begin() as c:
            c.execute(
                update(D.ads).where(D.ads.c.id == aid).values(status="paused" if paused else "approved")
            )
        return self.ad(aid)

    def serve_ads(self, community_id: int | None, n: int) -> list[dict]:
        """Approved, unexhausted ads for this place, least-shown first; each one served counts an impression."""
        if n <= 0:
            return []
        with self.engine.begin() as c:
            where = [D.ads.c.status == "approved", D.ads.c.impressions < D.ads.c.max_impressions]
            where.append(
                or_(D.ads.c.community_id.is_(None), D.ads.c.community_id == community_id)
                if community_id
                else D.ads.c.community_id.is_(None)
            )
            rows = (
                c.execute(
                    select(
                        D.ads.c.id,
                        D.ads.c.title,
                        D.ads.c.body,
                        D.ads.c.url,
                        D.users.c.username.label("advertiser"),
                    )
                    .join(D.users, D.users.c.id == D.ads.c.advertiser_id)
                    .where(*where)
                    .order_by((D.ads.c.impressions * 1.0 / D.ads.c.max_impressions).asc())
                    .limit(n)
                )
                .mappings()
                .all()
            )
            for r in rows:
                c.execute(
                    update(D.ads).where(D.ads.c.id == r["id"]).values(impressions=D.ads.c.impressions + 1)
                )
        return [dict(r) for r in rows]

    def click_ad(self, aid: int) -> str:
        with self.engine.begin() as c:
            url = c.execute(
                select(D.ads.c.url).where(D.ads.c.id == aid, D.ads.c.status.in_(["approved", "paused"]))
            ).scalar()
            if not url:
                raise BreadError("No such ad.", 404)
            c.execute(update(D.ads).where(D.ads.c.id == aid).values(clicks=D.ads.c.clicks + 1))
        return url

    # ------------------------------------------------------------------ site admin
    def make_admin(self, u) -> None:
        with self.engine.begin() as c:
            c.execute(update(D.users).where(D.users.c.id == u["id"]).values(is_admin=True))

    def review_ad(self, admin, aid: int, approve: bool, note: str = "") -> dict:
        ad = self.ad(aid)
        with self.engine.begin() as c:
            c.execute(
                update(D.ads)
                .where(D.ads.c.id == aid)
                .values(status="approved" if approve else "rejected", review_note=_clean(note, 300))
            )
            self._notify(
                c,
                ad["advertiser_id"],
                "ad",
                f'Your ad "{ad["title"][:60]}" was {"approved" if approve else "rejected"}'
                + (f": {note}" if note else "."),
                "/ads",
            )
        return self.ad(aid)

    def suspend(self, admin, username: str, suspended: bool = True) -> None:
        with self.engine.begin() as c:
            target = (
                c.execute(select(D.users).where(func.lower(D.users.c.username) == (username or "").lower()))
                .mappings()
                .first()
            )
            if not target or target["is_admin"]:
                raise BreadError("Cannot suspend that account.")
            c.execute(update(D.users).where(D.users.c.id == target["id"]).values(banned=suspended))
            if suspended:
                c.execute(delete(D.sessions).where(D.sessions.c.user_id == target["id"]))

    def stats(self) -> dict:
        day = D.now() - 86400
        with self.engine.connect() as c:
            count = lambda t, *w: c.execute(select(func.count()).select_from(t).where(*w)).scalar()  # noqa: E731
            dec = c.execute(
                select(
                    D.decisions.c.source,
                    D.decisions.c.action,
                    func.count(),
                    func.sum(case((D.decisions.c.overturned, 1), else_=0)),
                    func.avg(D.decisions.c.ms),
                ).group_by(D.decisions.c.source, D.decisions.c.action)
            ).all()
            ads = c.execute(
                select(
                    D.ads.c.status, func.count(), func.sum(D.ads.c.impressions), func.sum(D.ads.c.clicks)
                ).group_by(D.ads.c.status)
            ).all()
            pending = (
                c.execute(select(D.ads.c.id).where(D.ads.c.status == "pending").order_by(D.ads.c.created_at))
                .scalars()
                .all()
            )
            return {
                "users": count(D.users, D.users.c.is_bot.is_(False)),
                "bots": count(D.users, D.users.c.is_bot),
                "new_users_24h": count(D.users, D.users.c.created_at >= day, D.users.c.is_bot.is_(False)),
                "communities": count(D.communities),
                "posts": count(D.posts),
                "posts_24h": count(D.posts, D.posts.c.created_at >= day),
                "comments": count(D.comments),
                "comments_24h": count(D.comments, D.comments.c.created_at >= day),
                "votes": count(D.votes),
                "open_reports": count(D.reports, D.reports.c.resolved.is_(False)),
                "automod": [
                    {
                        "source": s,
                        "action": a,
                        "count": n,
                        "overturned": int(o or 0),
                        "avg_ms": round(float(ms or 0), 1),
                    }
                    for s, a, n, o, ms in dec
                ],
                "ads": [
                    {"status": s, "count": n, "impressions": int(i or 0), "clicks": int(k or 0)}
                    for s, n, i, k in ads
                ],
                "pending_ads": [self.ad(i) for i in pending],
                "date": dt.date.today().isoformat(),
            }
