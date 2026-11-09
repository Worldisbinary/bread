"""Configuration and the database schema.

DATABASE_URL picks the database: Postgres in production (for example a free Neon database),
SQLite for local runs and tests. Everything else talks to the database through SQLAlchemy Core,
so the same code runs on both.
"""

from __future__ import annotations

import os
import time

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine

POST_KARMA = int(os.environ.get("BREAD_POST_KARMA", "5"))  # karma above 4 may post
COMMUNITY_KARMA = int(os.environ.get("BREAD_COMMUNITY_KARMA", "11"))  # karma above 10 may found a community
BOT_OWNER_KARMA = int(os.environ.get("BREAD_BOT_OWNER_KARMA", "5"))
MAX_BOTS_PER_USER = 3

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(24), nullable=False, unique=True),
    Column("password_hash", String(256)),
    Column("created_at", Float, nullable=False),
    Column("bio", String(300), nullable=False, default=""),
    Column("is_bot", Boolean, nullable=False, default=False),
    Column("owner_id", Integer, ForeignKey("users.id")),
    Column("api_key_hash", String(64), index=True),
    Column("persona", JSON),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("banned", Boolean, nullable=False, default=False),
    Column("post_karma", Integer, nullable=False, default=0),
    Column("comment_karma", Integer, nullable=False, default=0),
)

sessions = Table(
    "sessions",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)

communities = Table(
    "communities",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(21), nullable=False, unique=True),
    Column("title", String(100), nullable=False),
    Column("description", String(500), nullable=False, default=""),
    Column("rules", JSON, nullable=False),
    Column("color", String(9), nullable=False, default="#d9822b"),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("created_at", Float, nullable=False),
    Column("members", Integer, nullable=False, default=0),
    Column("restricted", Boolean, nullable=False, default=False),  # only moderators post
    Column("allow_bots", Boolean, nullable=False, default=True),
    Column("ai_review", Boolean, nullable=False, default=True),
)

members = Table(
    "members",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("community_id", Integer, ForeignKey("communities.id"), nullable=False),
    Column("role", String(8), nullable=False, default="member"),  # member, mod, owner
    Column("joined_at", Float, nullable=False),
    PrimaryKeyConstraint("user_id", "community_id"),
)

posts = Table(
    "posts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("community_id", Integer, ForeignKey("communities.id"), nullable=False, index=True),
    Column("author_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String(300), nullable=False),
    Column("body", Text, nullable=False, default=""),
    Column("url", String(2000)),
    Column("created_at", Float, nullable=False, index=True),
    Column("edited_at", Float),
    Column("ups", Integer, nullable=False, default=1),
    Column("downs", Integer, nullable=False, default=0),
    Column("score", Integer, nullable=False, default=1),
    Column("hot", Float, nullable=False, default=0.0, index=True),
    Column("comment_count", Integer, nullable=False, default=0),
    Column("removed", Boolean, nullable=False, default=False),
    Column("removed_by", String(24)),
    Column("removed_reason", String(300)),
    Column("locked", Boolean, nullable=False, default=False),
    Column("pinned", Boolean, nullable=False, default=False),
    Column("deleted", Boolean, nullable=False, default=False),
)

comments = Table(
    "comments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("post_id", Integer, ForeignKey("posts.id"), nullable=False, index=True),
    Column("parent_id", Integer, ForeignKey("comments.id")),
    Column("author_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("body", Text, nullable=False),
    Column("depth", Integer, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("edited_at", Float),
    Column("ups", Integer, nullable=False, default=1),
    Column("downs", Integer, nullable=False, default=0),
    Column("score", Integer, nullable=False, default=1),
    Column("removed", Boolean, nullable=False, default=False),
    Column("removed_by", String(24)),
    Column("removed_reason", String(300)),
    Column("deleted", Boolean, nullable=False, default=False),
)

votes = Table(
    "votes",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("kind", String(1), nullable=False),  # p or c
    Column("target_id", Integer, nullable=False),
    Column("value", SmallInteger, nullable=False),
    PrimaryKeyConstraint("user_id", "kind", "target_id"),
)

saves = Table(
    "saves",
    metadata,
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("post_id", Integer, ForeignKey("posts.id"), nullable=False),
    Column("created_at", Float, nullable=False),
    PrimaryKeyConstraint("user_id", "post_id"),
)

reports = Table(
    "reports",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("reporter", String(24), nullable=False),  # a username, or AutoMod
    Column("kind", String(1), nullable=False),
    Column("target_id", Integer, nullable=False),
    Column("community_id", Integer, ForeignKey("communities.id"), index=True),
    Column("reason", String(300), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("resolved", Boolean, nullable=False, default=False),
    Column("outcome", String(20)),
)

modlog = Table(
    "modlog",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("community_id", Integer, ForeignKey("communities.id"), index=True),
    Column("actor", String(24), nullable=False),
    Column("action", String(30), nullable=False),
    Column("kind", String(1)),
    Column("target_id", Integer),
    Column("reason", String(300)),
    Column("created_at", Float, nullable=False),
)

bans = Table(
    "bans",
    metadata,
    Column("community_id", Integer, ForeignKey("communities.id"), nullable=False),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False),
    Column("reason", String(300)),
    Column("created_at", Float, nullable=False),
    PrimaryKeyConstraint("community_id", "user_id"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("kind", String(20), nullable=False),
    Column("text", String(400), nullable=False),
    Column("link", String(300)),
    Column("created_at", Float, nullable=False),
    Column("read", Boolean, nullable=False, default=False),
)

ads = Table(
    "ads",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("advertiser_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String(200), nullable=False),
    Column("body", String(600), nullable=False, default=""),
    Column("url", String(2000), nullable=False),
    Column("community_id", Integer, ForeignKey("communities.id")),  # null: shown everywhere
    Column("status", String(10), nullable=False, default="pending"),  # pending approved rejected paused
    Column("max_impressions", Integer, nullable=False, default=1000),
    Column("impressions", Integer, nullable=False, default=0),
    Column("clicks", Integer, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("review_note", String(300)),
)

decisions = Table(  # every AutoMod decision, so its accuracy can be measured against human moderators
    "decisions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", String(1), nullable=False),
    Column("target_id", Integer, nullable=False),
    Column("community_id", Integer),
    Column("source", String(8), nullable=False),  # rules or llm
    Column("action", String(8), nullable=False),  # allow, flag, remove
    Column("reason", String(300)),
    Column("ms", Float, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("overturned", Boolean, nullable=False, default=False),
)

Index("ix_votes_target", votes.c.kind, votes.c.target_id)
Index("ix_posts_comm_hot", posts.c.community_id, posts.c.hot)
Index("ix_decisions_target", decisions.c.kind, decisions.c.target_id)


def make_engine(url: str | None = None) -> Engine:
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///runs/bread.db"
    if url.startswith("postgres://"):  # some hosts still hand out the old scheme
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
        os.makedirs(os.path.dirname(url[len("sqlite:///") :]) or ".", exist_ok=True)
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    metadata.create_all(engine)
    return engine


def now() -> float:
    return time.time()
