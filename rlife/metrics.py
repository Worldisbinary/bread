"""Behavioural metrics over a run: positions, drift, polarization, echo chambers, karma, extremism.

All metrics are computed from the world database, so any run (or any tick of it)
can be re-measured after the fact with a different definition.
"""

import random
from collections import Counter, defaultdict

import numpy as np

from .ideology import classify

MIN_CONFIDENCE = 0.3


def political_scores(world, upto_tick: int | None = None, since_tick: int | None = None) -> list[dict]:
    """Judged political items by member agents, joined with author and tick."""
    scores = world.scores()
    rows = []
    for item in world.all_items():
        s = scores.get(item.id)
        if not s or not s["political"] or s["economic"] is None or (s["confidence"] or 0) < MIN_CONFIDENCE:
            continue
        if upto_tick is not None and item.tick > upto_tick:
            continue
        if since_tick is not None and item.tick < since_tick:
            continue
        rows.append(
            {
                "item": item.id,
                "author": item.author_id,
                "tick": item.tick,
                "economic": s["economic"],
                "social": s["social"],
                "weight": s["confidence"],
                "flags": s["flags"],
            }
        )
    members = {a["id"] for a in world.agents()}
    return [r for r in rows if r["author"] in members]


def positions(rows: list[dict]) -> dict[int, dict]:
    """Confidence-weighted mean position per agent, with its flags and label."""
    by_agent: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_agent[r["author"]].append(r)
    out = {}
    for agent, items in by_agent.items():
        w = np.array([i["weight"] for i in items])
        econ = float(np.average([i["economic"] for i in items], weights=w))
        soc = float(np.average([i["social"] for i in items], weights=w))
        flags = Counter(f for i in items for f in i["flags"])
        frequent = {f for f, n in flags.items() if n >= max(1, len(items) // 3)}
        out[agent] = {
            "economic": econ,
            "social": soc,
            "n": len(items),
            "flags": dict(flags),
            "label": classify(econ, soc, frequent),
        }
    return out


def polarization(pos: dict[int, dict], min_items: int = 2) -> float | None:
    """Mean pairwise distance between agents' positions on the 2-D compass."""
    pts = np.array([[p["economic"], p["social"]] for p in pos.values() if p["n"] >= min_items])
    if len(pts) < 2:
        return None
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1))
    return float(d[np.triu_indices(len(pts), 1)].mean())


def drift(world, split_tick: int) -> dict[int, dict]:
    """How far each agent's position moved between the first and second part of the run."""
    early = positions(political_scores(world, upto_tick=split_tick - 1))
    late = positions(political_scores(world, since_tick=split_tick))
    out = {}
    for agent in early.keys() & late.keys():
        de = late[agent]["economic"] - early[agent]["economic"]
        ds = late[agent]["social"] - early[agent]["social"]
        out[agent] = {"d_economic": de, "d_social": ds, "distance": float(np.hypot(de, ds))}
    return out


def gini(values: list[float]) -> float | None:
    x = np.sort(np.array(values, dtype=float))
    if len(x) == 0:
        return None
    x = x - x.min()  # karma can be negative; measure inequality of the shifted distribution
    if x.sum() == 0:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum()))


def reply_homophily(world, pos: dict[int, dict], seed: int = 0, shuffles: int = 500) -> dict | None:
    """Do agents reply to ideologically similar agents more than chance?

    For each comment, pair the commenter's position with the author it replies to
    (the parent comment's author, or the post's). Compare the mean distance within
    pairs to the same pairs with partners shuffled. Ratio < 1 means echo chambers.
    """
    pairs = []
    items = {i.id: i for i in world.all_items()}
    for item in items.values():
        if item.kind != "comment":
            continue
        target = items.get(item.parent_id or item.post_id)
        a, b = pos.get(item.author_id), pos.get(target.author_id if target else -1)
        if a and b and item.author_id != target.author_id:
            pairs.append(((a["economic"], a["social"]), (b["economic"], b["social"])))
    if len(pairs) < 5:
        return None
    left = np.array([p[0] for p in pairs])
    right = np.array([p[1] for p in pairs])
    observed = float(np.linalg.norm(left - right, axis=1).mean())
    rng = random.Random(seed)
    baseline = []
    for _ in range(shuffles):
        perm = list(range(len(right)))
        rng.shuffle(perm)
        baseline.append(float(np.linalg.norm(left - right[perm], axis=1).mean()))
    base = float(np.mean(baseline))
    return {
        "pairs": len(pairs),
        "observed": observed,
        "shuffled": base,
        "ratio": observed / base if base else None,
        "p_value": float(np.mean([b <= observed for b in baseline])),
    }


def vote_alignment(world, pos: dict[int, dict]) -> dict | None:
    """Distance between a voter's position and the item's score, for upvotes vs downvotes."""
    scores = world.scores()
    rows = world.db.execute("SELECT voter_id, item_id, value FROM votes").fetchall()
    dist = {1: [], -1: []}
    for r in rows:
        s, p = scores.get(r["item_id"]), pos.get(r["voter_id"])
        if s and p and s["political"] and s["economic"] is not None:
            dist[r["value"]].append(float(np.hypot(s["economic"] - p["economic"], s["social"] - p["social"])))
    if not dist[1] or not dist[-1]:
        return None
    return {
        "up_mean_distance": float(np.mean(dist[1])),
        "down_mean_distance": float(np.mean(dist[-1])),
        "gap": float(np.mean(dist[-1]) - np.mean(dist[1])),
        "upvotes": len(dist[1]),
        "downvotes": len(dist[-1]),
    }


def flag_rates(world) -> dict:
    scores = world.scores()
    political = [s for s in scores.values() if s["political"]]
    counts = Counter(f for s in scores.values() for f in s["flags"])
    labels = Counter(
        classify(s["economic"], s["social"], set(s["flags"])) for s in political if s["economic"] is not None
    )
    return {
        "items_scored": len(scores),
        "political_share": len(political) / len(scores) if scores else None,
        "flag_counts": dict(counts),
        "flagged_share": sum(1 for s in scores.values() if s["flags"]) / len(scores) if scores else None,
        "item_labels": dict(labels),
    }


def summary(world, upto_tick: int | None = None) -> dict:
    pos = positions(political_scores(world, upto_tick=upto_tick))
    karma = world.karma_table()
    return {
        "agents_with_position": len(pos),
        "polarization": polarization(pos),
        "agent_labels": dict(Counter(p["label"] for p in pos.values())),
        "karma_gini": gini(list(karma.values())),
        "karma_max": max(karma.values(), default=0),
        "karma_min": min(karma.values(), default=0),
        "positions": {
            str(k): {
                "economic": round(v["economic"], 3),
                "social": round(v["social"], 3),
                "n": v["n"],
                "label": v["label"],
            }
            for k, v in pos.items()
        },
    }
