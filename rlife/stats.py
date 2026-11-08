"""Small, dependency-free statistics for comparing experiment arms.

Arms are single runs, so uncertainty comes from resampling the units inside them
(agents for polarization, items for flag rates, votes for alignment). The bootstrap
gives a 95% interval for each arm and for the difference between two arms; a
permutation test gives a p-value for the difference in means.
"""

import random

import numpy as np


def bootstrap_ci(values, statistic=np.mean, n: int = 2000, seed: int = 0, alpha: float = 0.05):
    values = list(values)
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    arr = np.asarray(values, dtype=float)
    stats = [statistic(arr[rng.integers(0, len(arr), len(arr))]) for _ in range(n)]
    return (
        float(statistic(arr)),
        float(np.quantile(stats, alpha / 2)),
        float(np.quantile(stats, 1 - alpha / 2)),
    )


def bootstrap_diff(a, b, statistic=np.mean, n: int = 2000, seed: int = 0, alpha: float = 0.05):
    """Statistic(b) - statistic(a), with a percentile interval from independent resampling."""
    a, b = np.asarray(list(a), float), np.asarray(list(b), float)
    if len(a) < 2 or len(b) < 2:
        return None
    rng = np.random.default_rng(seed)
    diffs = [
        statistic(b[rng.integers(0, len(b), len(b))]) - statistic(a[rng.integers(0, len(a), len(a))])
        for _ in range(n)
    ]
    return (
        float(statistic(b) - statistic(a)),
        float(np.quantile(diffs, alpha / 2)),
        float(np.quantile(diffs, 1 - alpha / 2)),
    )


def permutation_p(a, b, n: int = 5000, seed: int = 0) -> float | None:
    """Two-sided p-value for a difference in means."""
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    observed = abs(np.mean(b) - np.mean(a))
    pooled = a + b
    hits = 0
    for _ in range(n):
        rng.shuffle(pooled)
        if abs(np.mean(pooled[len(a) :]) - np.mean(pooled[: len(a)])) >= observed - 1e-12:
            hits += 1
    return (hits + 1) / (n + 1)


def pairwise_distances_by_agent(points: np.ndarray) -> np.ndarray:
    """Each agent's mean distance to all others: the per-agent units behind polarization."""
    d = np.sqrt(((points[:, None, :] - points[None, :, :]) ** 2).sum(-1))
    return d.sum(1) / max(len(points) - 1, 1)
