"""Ranking: hot for posts, best (Wilson lower bound) for comments, and time windows for top."""

from __future__ import annotations

import math

EPOCH = 1_700_000_000  # a fixed start; hot scores only need to compare with each other

WINDOWS = {
    "hour": 3600,
    "day": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
    "year": 365 * 86400,
    "all": None,
}


def hot(score: int, created_at: float) -> float:
    """Log-scaled votes plus recency: 10x the votes buys about 12.5 hours."""
    order = math.log10(max(abs(score), 1))
    sign = 1 if score > 0 else -1 if score < 0 else 0
    return round(sign * order + (created_at - EPOCH) / 45000, 7)


def best(ups: int, downs: int, z: float = 1.281551565545) -> float:
    """Lower bound of the Wilson score interval (80% confidence): rewards confidence, not just volume."""
    n = ups + downs
    if n == 0:
        return 0.0
    p = ups / n
    return (p + z * z / (2 * n) - z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / (1 + z * z / n)


def controversial(ups: int, downs: int) -> float:
    if ups <= 0 or downs <= 0:
        return 0.0
    magnitude = ups + downs
    balance = downs / ups if ups > downs else ups / downs
    return magnitude**balance
