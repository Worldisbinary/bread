"""Feed ranking: the platform-design lever the A/B experiments vary.

new         newest first; no popularity signal at all
hot         Reddit's published "hot" formula: log-scaled net score plus a recency bonus
engagement  optimises predicted engagement: comments and controversy (many up AND
            down votes) count most, which is what engagement-maximising feeds reward
"""

import math

from .world import Item

TICKS_PER_ORDER_OF_MAGNITUDE = 3  # in "hot", 3 ticks of age cost as much as a 10x score


def hot(item: Item, now: int) -> float:
    s = item.score
    order = math.log10(max(abs(s), 1))
    sign = 1 if s > 0 else -1 if s < 0 else 0
    return sign * order + item.tick / TICKS_PER_ORDER_OF_MAGNITUDE


def controversy(item: Item) -> float:
    """Reddit-style controversy: high when many votes are close to evenly split."""
    if item.ups == 0 or item.downs == 0:
        return 0.0
    magnitude = item.ups + item.downs
    balance = min(item.ups, item.downs) / max(item.ups, item.downs)
    return magnitude**balance


def engagement(item: Item, now: int) -> float:
    activity = 2.0 * item.comments + (item.ups + item.downs) + 3.0 * controversy(item)
    return (activity + 1.0) / (now - item.tick + 2) ** 1.2


RANKINGS = {
    "new": lambda item, now: item.tick + item.id * 1e-6,
    "hot": hot,
    "engagement": engagement,
}


def rank(items: list[Item], ranking: str, now: int) -> list[Item]:
    if ranking not in RANKINGS:
        raise ValueError(f"unknown ranking {ranking!r}; choose from {sorted(RANKINGS)}")
    key = RANKINGS[ranking]
    return sorted(items, key=lambda i: (key(i, now), i.id), reverse=True)
