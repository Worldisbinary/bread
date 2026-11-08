"""The Royal Steward: an LLM agent that runs LiveOps for the kingdom.

Every few seasons it reads the dashboard (recent metric trends, laws, treasury, what it
did before) and proposes exactly one action from the allowed list.

Guardrails, in layers:
  1. Output contract: one JSON action; anything else becomes "none".
  2. LiveOps.apply: allowed list, budget cap, change limits, bounds and cooldowns.
  3. Mode: "auto" applies accepted proposals; "propose" queues them for a human to approve
     in the admin console.
Every proposal is logged with its rationale and expected effect, so the steward's
judgement can be evaluated afterwards against what actually happened.
"""

import json

from ..llm import LLMError, parse_json
from .events import ACTIONS

SYSTEM = f"""You are the Royal Steward of a kingdom simulation, acting as its LiveOps operator.
Your goal: keep citizens in the kingdom (retention), keep them content (happiness) and keep \
unrest, hunger and crime low, while keeping the treasury solvent. Prefer small, targeted actions; \
doing nothing is often right.

Allowed actions (exactly one per decision):
{json.dumps({k: v["description"] for k, v in ACTIONS.items()}, indent=1)}
plus "none".
Guardrails the system enforces: an action may spend at most 30% of the treasury; tax moves at most \
0.05, subsidy 0.10, policing 0.15 per action; each action has a cooldown.

Reply with JSON only:
{{"action": "<name or none>", "args": {{"delta": <number, only for adjust_* actions>}},
  "rationale": "<one or two sentences citing the metrics>", "expected_effect": "<what should change>"}}"""

DASHBOARD_KEYS = [
    "population",
    "retention",
    "happiness",
    "unrest",
    "hunger_rate",
    "crime_rate",
    "wealth_gini",
    "treasury",
    "grain_price",
    "public_pay_ratio",
]


def dashboard(history: list[dict], log: list[dict]) -> str:
    rows = [
        {k: round(h[k], 3) if isinstance(h[k], float) else h[k] for k in DASHBOARD_KEYS}
        | {"season": h["tick"]}
        for h in history[-4:]
    ]
    laws = history[-1]["laws"] if history else {}
    mine = [e for e in log if e["actor"] == "steward"][-4:]
    return json.dumps({"recent_seasons": rows, "laws": laws, "your_recent_actions": mine}, default=str)


def _none(reason: str) -> dict:
    return {"action": "none", "args": {}, "rationale": reason[:200], "expected_effect": ""}


class Steward:
    def __init__(self, llm, model: str) -> None:
        self.llm = llm
        self.model = model

    def propose(self, history: list[dict], log: list[dict]) -> dict:
        try:
            completion = self.llm.complete(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": dashboard(history, log)}],
                model=self.model,
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
            )
            reply = parse_json(completion.text)
        except (LLMError, ValueError, json.JSONDecodeError) as exc:
            return _none(f"steward unavailable: {exc}")
        if not isinstance(reply, dict):
            return _none("unparseable proposal")
        args = reply.get("args") if isinstance(reply.get("args"), dict) else {}
        return {
            "action": str(reply.get("action", "none")),
            "args": args,
            "rationale": str(reply.get("rationale", ""))[:300],
            "expected_effect": str(reply.get("expected_effect", ""))[:200],
        }
