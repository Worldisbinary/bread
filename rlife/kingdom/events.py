"""LiveOps actions: the only levers a LiveOps operator (human or agent) can pull.

Each action is validated against guardrails before it touches the kingdom:
  - it must be on this list (no free-form changes),
  - it must fit the treasury budget (an action may spend at most 30% of the treasury),
  - policy changes move at most CHANGE_LIMITS per action and stay inside BOUNDS,
  - the same action cannot repeat within its cooldown.
Accepted and rejected actions are both logged, with the reason, for the audit trail.
"""

from dataclasses import dataclass

from .economy import Economy
from .laws import BOUNDS, CHANGE_LIMITS

MAX_BUDGET_SHARE = 0.30

ACTIONS = {
    "harvest_festival": {
        "cost_per_citizen": 0.6,
        "cooldown": 4,
        "description": "Feast in every province: happiness up for one season.",
    },
    "trade_fair": {
        "cost_per_citizen": 0.4,
        "cooldown": 4,
        "description": "Royal trade fair: demand for goods up 30% for two seasons.",
    },
    "grain_reserve_release": {
        "cost_per_citizen": 0.8,
        "cooldown": 3,
        "description": "Crown buys grain into the granary to lower prices.",
    },
    "adjust_tax": {
        "cost_per_citizen": 0.0,
        "cooldown": 2,
        "description": "Change income tax by up to 5 points (argument: delta).",
    },
    "adjust_subsidy": {
        "cost_per_citizen": 0.0,
        "cooldown": 2,
        "description": "Change the grain subsidy for the poor by up to 10 points (argument: delta).",
    },
    "adjust_policing": {
        "cost_per_citizen": 0.0,
        "cooldown": 2,
        "description": "Change policing by up to 15 points (argument: delta).",
    },
}

# Exogenous shocks: not LiveOps levers, used by scenarios ("difficulty").
SHOCKS = {
    "drought": {"weather": 0.55, "ticks": 2},
    "bumper_harvest": {"weather": 1.35, "ticks": 1},
}


@dataclass
class Decision:
    action: str
    accepted: bool
    reason: str
    cost: float = 0.0
    args: dict | None = None


class LiveOps:
    def __init__(self, econ: Economy) -> None:
        self.econ = econ
        self.last_used: dict[str, int] = {}
        self.log: list[dict] = []

    def apply(
        self, action: str, args: dict | None = None, actor: str = "operator", rationale: str = ""
    ) -> Decision:
        args = args or {}
        decision = self._apply(action, args)
        self.log.append(
            {
                "tick": self.econ.tick_no,
                "actor": actor,
                "action": action,
                "args": args,
                "accepted": decision.accepted,
                "reason": decision.reason,
                "cost": decision.cost,
                "rationale": rationale[:300],
            }
        )
        return decision

    def _apply(self, action: str, args: dict) -> Decision:
        econ = self.econ
        if action == "none":
            return Decision(action, True, "no action")
        spec = ACTIONS.get(action)
        if spec is None:
            return Decision(action, False, "not an allowed action")
        last = self.last_used.get(action)
        if last is not None and econ.tick_no - last < spec["cooldown"]:
            return Decision(action, False, f"cooldown: used {econ.tick_no - last} seasons ago")
        cost = spec["cost_per_citizen"] * int(econ.present.sum())
        if cost > MAX_BUDGET_SHARE * max(econ.treasury, 0.0):
            return Decision(
                action, False, f"over budget: costs {cost:.0f}, limit {MAX_BUDGET_SHARE * econ.treasury:.0f}"
            )

        if action.startswith("adjust_"):
            field = {
                "adjust_tax": "income_tax",
                "adjust_subsidy": "grain_subsidy",
                "adjust_policing": "policing",
            }[action]
            try:
                delta = float(args.get("delta", 0))
            except (TypeError, ValueError):
                return Decision(action, False, "delta must be a number")
            limit = CHANGE_LIMITS[field]
            if abs(delta) > limit + 1e-9:
                return Decision(action, False, f"change {delta:+.2f} exceeds the limit of {limit:.2f}")
            lo, hi = BOUNDS[field]
            new = min(hi, max(lo, getattr(econ.laws, field) + delta))
            econ.laws = econ.laws.with_changes(**{field: round(new, 3)})
        elif action == "harvest_festival":
            econ.shocks.festival = 0.08
            econ.shocks.remaining["festival"] = 1
        elif action == "trade_fair":
            econ.shocks.goods_demand = 1.3
            econ.shocks.remaining["goods_demand"] = 2
        elif action == "grain_reserve_release":
            econ.granary += 0.25 * int(econ.present.sum())

        econ.treasury -= cost
        self.last_used[action] = econ.tick_no
        return Decision(action, True, "applied", cost, args)

    def shock(self, name: str) -> None:
        spec = SHOCKS[name]
        self.econ.shocks.weather = spec["weather"]
        self.econ.shocks.remaining["weather"] = spec["ticks"]
        self.log.append(
            {
                "tick": self.econ.tick_no,
                "actor": "world",
                "action": name,
                "args": {},
                "accepted": True,
                "reason": "external shock",
                "cost": 0.0,
                "rationale": "",
            }
        )
