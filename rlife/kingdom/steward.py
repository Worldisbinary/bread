"""Autonomous Agentic LiveOps Steward.

The Royal Steward acts as the automated LiveOps team:
- Observes the kingdom's telemetry every tick (retention, happiness, Gini, treasury, hunger, crime)
- Reasoned chain-of-thought analysis of economic imbalances
- Selects an optimal intervention from an approved constrained action space
- Enforces strict guardrails (budget caps, cooldowns, delta boundaries)
- Provides full observability: logs every rationale, predicted vs actual outcome, and rejected attempts
"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .economy import Economy
from .events import ACTIONS, MAX_BUDGET_SHARE, Decision, LiveOps
from .metrics import snapshot


STEWARD_SYSTEM_PROMPT = """You are the Royal Steward of the Realm, an autonomous LiveOps agent managing a game economy of 1,500 citizens.
Your mandate is to maximize player retention, minimize churn and unrest, keep wealth inequality (Gini) within healthy limits, and preserve the royal treasury.

Current Kingdom Telemetry:
- Tick (Season): {tick}
- Population: {population} (Retention: {retention:.1%}, Churn this season: {churned})
- Happiness: {happiness:.2f} (Unrest: {unrest:.1%})
- Economy: Treasury: {treasury:.1f} coins | Grain Price: {grain_price:.2f} | Goods Price: {goods_price:.2f}
- Social: Wealth Gini: {wealth_gini:.3f} | Hunger Rate: {hunger_rate:.1%} | Crime Rate: {crime_rate:.1%}
- Current Laws: Income Tax: {tax:.1%}, Policing: {policing:.1%}, Grain Subsidy: {subsidy:.1%}

Available LiveOps Actions:
{actions_doc}

Recent Actions Cooldown Status:
{cooldown_status}

Analyze the kingdom's telemetry and choose EXACTLY ONE action. If no intervention is required or risks treasury depletion, choose "do_nothing".
Respond strictly in valid JSON:
{{
  "analysis": "<detailed rationale diagnosing the primary bottleneck: e.g. hunger spike, rising inequality, or impending churn>",
  "action": "<action_name from available list or 'do_nothing'>",
  "args": {{"delta": <float if adjusting tax/subsidy/policing>}},
  "expected_impact": "<expected directional change in retention/happiness/treasury>"
}}
"""


@dataclass
class StewardLogEntry:
    tick: int
    telemetry: Dict[str, Any]
    analysis: str
    proposed_action: str
    args: Dict[str, Any]
    decision: Decision
    expected_impact: str


class RoyalSteward:
    """Agentic LiveOps Steward with reasoning and strict guardrail enforcement."""

    def __init__(self, econ: Economy, liveops: LiveOps, llm=None, human_in_the_loop: bool = False) -> None:
        self.econ = econ
        self.liveops = liveops
        self.llm = llm
        self.human_in_the_loop = human_in_the_loop
        self.audit_log: List[StewardLogEntry] = []

    def _get_active_cooldowns(self) -> Dict[str, int]:
        active = {}
        for action, spec in ACTIONS.items():
            last = self.liveops.last_used.get(action)
            if last is not None:
                elapsed = self.econ.tick_no - last
                needed = spec.get("cooldown", 0)
                if elapsed < needed:
                    active[action] = needed - elapsed
        return active

    def _can_afford(self, action: str) -> bool:
        spec = ACTIONS.get(action)
        if not spec:
            return False
        cost = spec.get("cost_per_citizen", 0.0) * int(self.econ.present.sum())
        return cost <= MAX_BUDGET_SHARE * max(self.econ.treasury, 0.0)

    def _format_actions_doc(self) -> str:
        lines = []
        for name, spec in ACTIONS.items():
            cost = spec.get("cost_per_citizen", 0.0) * self.econ.present.sum()
            lines.append(f"- {name}: {spec['description']} (Cost: ~{cost:.1f} coins, Cooldown: {spec['cooldown']} ticks)")
        lines.append("- do_nothing: Observe without intervening.")
        return "\n".join(lines)

    def _format_cooldowns(self) -> str:
        cooldowns = self._get_active_cooldowns()
        if not cooldowns:
            return "All levers are currently ready."
        return ", ".join(f"{k}: {v} ticks remaining" for k, v in cooldowns.items())

    def deliberate(self) -> StewardLogEntry:
        """Runs the steward's agentic loop: observe -> deliberate -> propose -> guardrail check -> act."""
        tele = snapshot(self.econ)
        
        prompt = STEWARD_SYSTEM_PROMPT.format(
            tick=tele["tick"],
            population=tele["population"],
            retention=tele["retention"],
            churned=tele["churned"],
            happiness=tele["happiness"],
            unrest=tele["unrest"],
            treasury=tele["treasury"],
            grain_price=tele["grain_price"],
            goods_price=tele["goods_price"],
            wealth_gini=tele["wealth_gini"],
            hunger_rate=tele["hunger_rate"],
            crime_rate=tele["crime_rate"],
            tax=self.econ.laws.income_tax,
            policing=self.econ.laws.policing,
            subsidy=self.econ.laws.grain_subsidy,
            actions_doc=self._format_actions_doc(),
            cooldown_status=self._format_cooldowns()
        )

        analysis = ""
        action = "do_nothing"
        args: Dict[str, Any] = {}
        expected_impact = ""

        if self.llm is not None:
            try:
                response = self.llm.chat([
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Review current metrics and issue your LiveOps decree."}
                ])
                parsed = json.loads(response.strip("` \n").removeprefix("json"))
                analysis = parsed.get("analysis", "Autonomous monitoring.")
                action = parsed.get("action", "do_nothing")
                args = parsed.get("args", {})
                expected_impact = parsed.get("expected_impact", "")
            except Exception as e:
                analysis, action, args, expected_impact = self._rule_based_fallback(tele)
        else:
            analysis, action, args, expected_impact = self._rule_based_fallback(tele)

        # Apply through LiveOps Guardrails
        if action == "do_nothing":
            decision = Decision(action="do_nothing", accepted=True, reason="Steward observed no critical intervention needed.")
        else:
            decision = self.liveops.apply(action, args, actor="RoyalSteward", rationale=analysis)

        entry = StewardLogEntry(
            tick=self.econ.tick_no,
            telemetry=tele,
            analysis=analysis,
            proposed_action=action,
            args=args,
            decision=decision,
            expected_impact=expected_impact
        )
        self.audit_log.append(entry)
        return entry

    def _rule_based_fallback(self, tele: Dict[str, Any]):
        """Intelligent heuristic controller mirroring optimal LiveOps decision tree."""
        cooldowns = self._get_active_cooldowns()

        # 1. Hunger / Price crisis
        if tele["hunger_rate"] > 0.15 or tele["grain_price"] > 1.35:
            if "grain_reserve_release" not in cooldowns and self._can_afford("grain_reserve_release"):
                return (
                    "Grain prices are creating unacceptable hunger and driving emigration churn.",
                    "grain_reserve_release",
                    {},
                    "Lower market grain price, alleviating lower-class hunger."
                )
            elif "adjust_subsidy" not in cooldowns and self.econ.laws.grain_subsidy < 0.4:
                return (
                    "Grain subsidies need immediate boost to protect impoverished citizens from starvation.",
                    "adjust_subsidy",
                    {"delta": 0.10},
                    "Direct grain price relief for lowest wealth quintile."
                )

        # 2. Dangerous unrest / Low happiness
        if tele["unrest"] > 0.20 or tele["happiness"] < 0.50:
            if "harvest_festival" not in cooldowns and self._can_afford("harvest_festival"):
                return (
                    "Unrest is climbing above safety thresholds; festival will prevent churn.",
                    "harvest_festival",
                    {},
                    "Immediate kingdom-wide happiness boost (+0.10)."
                )

        # 3. High crime rate
        if tele["crime_rate"] > 0.12 and "adjust_policing" not in cooldowns:
            return (
                "Crime rates rising; expanding royal watch to deter theft and stabilize standing.",
                "adjust_policing",
                {"delta": 0.10},
                "Increase apprehension rate of unlawful activity."
            )

        # 4. Economic stagnation
        if tele["goods_price"] < 1.3 and "trade_fair" not in cooldowns and self._can_afford("trade_fair"):
            return (
                "Private sector trade is sluggish; royal fair will stimulate artisan goods turnover.",
                "trade_fair",
                {},
                "30% boost in goods demand for two seasons."
            )

        return (
            "Kingdom telemetry remains within stable operating boundaries. Preserving treasury.",
            "do_nothing",
            {},
            "Maintain status quo and reserve capital."
        )
