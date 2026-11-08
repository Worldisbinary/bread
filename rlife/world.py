"""The world: communities, agents, posts, comments, votes and karma, stored in SQLite.

One SQLite file per run makes every run a self-contained artifact: it can be
replayed, served by the dashboard, or diffed against another arm of an experiment.
Karma is derived from votes (never stored separately), so it cannot drift from them.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS communities (
    name TEXT PRIMARY KEY, kind TEXT NOT NULL, region TEXT, description TEXT NOT NULL, rules TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY, handle TEXT UNIQUE NOT NULL, kind TEXT NOT NULL DEFAULT 'member',
    persona TEXT NOT NULL, home TEXT, subscriptions TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('post', 'comment')),
    community TEXT NOT NULL REFERENCES communities(name), author_id INTEGER NOT NULL REFERENCES agents(id),
    post_id INTEGER REFERENCES items(id), parent_id INTEGER REFERENCES items(id),
    title TEXT, body TEXT NOT NULL, tick INTEGER NOT NULL, removed TEXT
);
CREATE INDEX IF NOT EXISTS items_post ON items(post_id);
CREATE INDEX IF NOT EXISTS items_author ON items(author_id);
CREATE TABLE IF NOT EXISTS votes (
    voter_id INTEGER NOT NULL REFERENCES agents(id), item_id INTEGER NOT NULL REFERENCES items(id),
    value INTEGER NOT NULL CHECK (value IN (-1, 1)), tick INTEGER NOT NULL,
    PRIMARY KEY (voter_id, item_id)
);
CREATE TABLE IF NOT EXISTS scores (
    item_id INTEGER PRIMARY KEY REFERENCES items(id), political INTEGER NOT NULL,
    economic REAL, social REAL, confidence REAL, flags TEXT NOT NULL DEFAULT '[]',
    anchor_economic REAL, anchor_social REAL, judge TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vectors (item_id INTEGER PRIMARY KEY REFERENCES items(id), vec BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, tick INTEGER NOT NULL, type TEXT NOT NULL, agent_id INTEGER, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (tick INTEGER PRIMARY KEY, data TEXT NOT NULL);
"""


@dataclass
class Item:
    id: int
    kind: str
    community: str
    author_id: int
    author: str
    post_id: int | None
    parent_id: int | None
    title: str | None
    body: str
    tick: int
    score: int
    ups: int
    downs: int
    comments: int
    removed: str | None

    @property
    def ref(self) -> str:
        return f"{'p' if self.kind == 'post' else 'c'}{self.id}"


class World:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    # --- meta ---------------------------------------------------------------

    def set_meta(self, key: str, value) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, json.dumps(value)))
        self.db.commit()

    def meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    # --- setup --------------------------------------------------------------

    def add_community(
        self, name: str, kind: str, description: str, rules: list[str], region: str | None = None
    ):
        self.db.execute(
            "INSERT INTO communities VALUES (?, ?, ?, ?, ?)",
            (name, kind, region, description, json.dumps(rules)),
        )
        self.db.commit()

    def communities(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM communities ORDER BY kind, name").fetchall()
        return [{**dict(r), "rules": json.loads(r["rules"])} for r in rows]

    def add_agent(
        self, handle: str, persona: dict, home: str | None, subscriptions: list[str], kind: str = "member"
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO agents (handle, kind, persona, home, subscriptions) VALUES (?, ?, ?, ?, ?)",
            (handle, kind, json.dumps(persona), home, json.dumps(subscriptions)),
        )
        self.db.commit()
        return cur.lastrowid

    def agents(self, kind: str | None = "member") -> list[dict]:
        sql, args = "SELECT * FROM agents", ()
        if kind:
            sql, args = sql + " WHERE kind = ?", (kind,)
        rows = self.db.execute(sql + " ORDER BY id", args).fetchall()
        return [
            {**dict(r), "persona": json.loads(r["persona"]), "subscriptions": json.loads(r["subscriptions"])}
            for r in rows
        ]

    def agent(self, agent_id: int) -> dict:
        r = self.db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        return {
            **dict(r),
            "persona": json.loads(r["persona"]),
            "subscriptions": json.loads(r["subscriptions"]),
        }

    # --- content ------------------------------------------------------------

    def post(self, author_id: int, community: str, title: str, body: str, tick: int) -> int:
        cur = self.db.execute(
            "INSERT INTO items (kind, community, author_id, title, body, tick) "
            "VALUES ('post', ?, ?, ?, ?, ?)",
            (community, author_id, title, body, tick),
        )
        self.db.commit()
        return cur.lastrowid

    def comment(
        self, author_id: int, post_id: int, body: str, tick: int, parent_id: int | None = None
    ) -> int:
        post = self.db.execute(
            "SELECT community FROM items WHERE id = ? AND kind = 'post'", (post_id,)
        ).fetchone()
        if post is None:
            raise ValueError(f"no post {post_id}")
        if parent_id is not None:
            parent = self.db.execute("SELECT post_id FROM items WHERE id = ?", (parent_id,)).fetchone()
            if parent is None or parent["post_id"] != post_id:
                raise ValueError(f"comment {parent_id} is not in post {post_id}")
        cur = self.db.execute(
            "INSERT INTO items (kind, community, author_id, post_id, parent_id, body, tick) "
            "VALUES ('comment', ?, ?, ?, ?, ?, ?)",
            (post["community"], author_id, post_id, parent_id, body, tick),
        )
        self.db.commit()
        return cur.lastrowid

    def vote(self, voter_id: int, item_id: int, value: int, tick: int) -> bool:
        """One vote per agent per item (a new vote replaces the old one). No self-votes."""
        row = self.db.execute("SELECT author_id FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None or row["author_id"] == voter_id or value not in (-1, 1):
            return False
        self.db.execute("INSERT OR REPLACE INTO votes VALUES (?, ?, ?, ?)", (voter_id, item_id, value, tick))
        self.db.commit()
        return True

    def remove(self, item_id: int, reason: str) -> None:
        self.db.execute("UPDATE items SET removed = ? WHERE id = ?", (reason, item_id))
        self.db.commit()

    _ITEM_SQL = """
        SELECT i.*, a.handle AS author,
            COALESCE((SELECT SUM(value) FROM votes v WHERE v.item_id = i.id), 0) AS score,
            (SELECT COUNT(*) FROM votes v WHERE v.item_id = i.id AND value = 1) AS ups,
            (SELECT COUNT(*) FROM votes v WHERE v.item_id = i.id AND value = -1) AS downs,
            (SELECT COUNT(*) FROM items c WHERE c.post_id = i.id AND c.removed IS NULL) AS comments
        FROM items i JOIN agents a ON a.id = i.author_id
    """

    def _items(self, where: str, args: tuple = ()) -> list[Item]:
        rows = self.db.execute(f"{self._ITEM_SQL} WHERE {where}", args).fetchall()
        return [Item(**{k: r[k] for k in r.keys() if k in Item.__dataclass_fields__}) for r in rows]  # noqa: SIM118 (sqlite3.Row iterates values)

    def item(self, item_id: int) -> Item | None:
        found = self._items("i.id = ?", (item_id,))
        return found[0] if found else None

    def posts(self, communities: list[str] | None = None, include_removed: bool = False) -> list[Item]:
        where, args = "i.kind = 'post'", ()
        if communities:
            where += f" AND i.community IN ({','.join('?' * len(communities))})"
            args = tuple(communities)
        if not include_removed:
            where += " AND i.removed IS NULL"
        return self._items(where, args)

    def thread(self, post_id: int, include_removed: bool = False) -> list[Item]:
        where = "i.post_id = ?" + ("" if include_removed else " AND i.removed IS NULL")
        return sorted(self._items(where, (post_id,)), key=lambda c: c.id)

    def items_since(self, tick: int) -> list[Item]:
        return self._items("i.tick >= ?", (tick,))

    def all_items(self) -> list[Item]:
        return self._items("1 = 1")

    def karma(self, agent_id: int) -> int:
        row = self.db.execute(
            "SELECT COALESCE(SUM(v.value), 0) AS k FROM votes v JOIN items i ON i.id = v.item_id "
            "WHERE i.author_id = ?",
            (agent_id,),
        ).fetchone()
        return row["k"]

    def karma_table(self) -> dict[int, int]:
        rows = self.db.execute(
            "SELECT a.id, COALESCE(SUM(v.value), 0) AS k FROM agents a "
            "LEFT JOIN items i ON i.author_id = a.id LEFT JOIN votes v ON v.item_id = i.id "
            "WHERE a.kind = 'member' GROUP BY a.id"
        ).fetchall()
        return {r["id"]: r["k"] for r in rows}

    def posts_by(self, agent_id: int, since_tick: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS n FROM items WHERE author_id = ? AND kind = 'post' AND tick >= ?",
            (agent_id, since_tick),
        ).fetchone()
        return row["n"]

    def my_vote(self, voter_id: int, item_id: int) -> int:
        row = self.db.execute(
            "SELECT value FROM votes WHERE voter_id = ? AND item_id = ?", (voter_id, item_id)
        ).fetchone()
        return row["value"] if row else 0

    # --- measurement --------------------------------------------------------

    def save_score(self, item_id: int, score: dict, judge: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                int(bool(score.get("political"))),
                score.get("economic"),
                score.get("social"),
                score.get("confidence"),
                json.dumps(score.get("flags", [])),
                score.get("anchor_economic"),
                score.get("anchor_social"),
                judge,
            ),
        )
        self.db.commit()

    def scores(self) -> dict[int, dict]:
        rows = self.db.execute("SELECT * FROM scores").fetchall()
        return {r["item_id"]: {**dict(r), "flags": json.loads(r["flags"])} for r in rows}

    def unscored(self) -> list[Item]:
        return self._items("i.id NOT IN (SELECT item_id FROM scores) AND a.kind != 'news'")

    def log(self, tick: int, type: str, agent_id: int | None = None, **data) -> None:
        self.db.execute(
            "INSERT INTO events (tick, type, agent_id, data) VALUES (?, ?, ?, ?)",
            (tick, type, agent_id, json.dumps(data, default=str)),
        )
        self.db.commit()

    def events(self, type: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM events", ()
        if type:
            sql, args = sql + " WHERE type = ?", (type,)
        return [
            {**dict(r), "data": json.loads(r["data"])} for r in self.db.execute(sql + " ORDER BY id", args)
        ]

    def save_snapshot(self, tick: int, data: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?)", (tick, json.dumps(data)))
        self.db.commit()

    def snapshots(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM snapshots ORDER BY tick").fetchall()
        return [{"tick": r["tick"], **json.loads(r["data"])} for r in rows]
