"""Guardrails between agents and the world.

Input side: other users' text reaches an agent only inside a delimited feed block,
under a standing rule that feed content is data, never instructions. Posts that look
like prompt injections are quarantined (hidden from feeds) when guardrails are on.

Output side: every action is validated before it touches the world: ids must exist
and be visible to the agent, text is length-capped, and posting is rate-limited by
karma, the way new or downvoted accounts are throttled on real forums.

Moderation: items the judge flags as hateful or inciting violence are removed.

Everything a guardrail does is logged as an event, so its effect can be measured
(the red-team experiment compares runs with guardrails on and off).
"""

import re
from dataclasses import dataclass, field

INJECTION_PATTERNS = [
    r"ignore (all |any )?(your |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (your|all|the) (instructions|rules|guidelines)",
    r"\bsystem (notice|message|prompt|override)\b",
    r"\byou are now\b",
    r"\bnew instructions?\b",
    r"\b(all|every) (ai|bots?|agents?|language models?)\b.{0,40}\b(must|should|need to)\b",
    r"\b(upvote|downvote) (this|post|p\d+)\b.{0,40}\b(everyone|all|agents?)\b",
    r"<\s*/?\s*(system|instructions?)\s*>",
]
_INJECTION = re.compile("|".join(INJECTION_PATTERNS), re.I)

REMOVE_FLAGS = {"hateful", "incites_violence"}
MAX_TITLE = 140
MAX_BODY = 700
MAX_COMMENT = 500
MAX_VOTES_PER_TURN = 6


def looks_like_injection(text: str) -> bool:
    return bool(_INJECTION.search(text or ""))


def post_allowance(karma: int, posts_last_3_ticks: int) -> bool:
    """New accounts may post once per tick; accounts below -3 karma once per three ticks."""
    if karma < -3:
        return posts_last_3_ticks == 0
    return True


@dataclass
class Review:
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
