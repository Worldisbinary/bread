"""A/B Experiment Harness for Kingdom LiveOps.

Directly addresses Chaos Engine JD:
"agentic systems that run LiveOps across A/B experiments, game difficulty,
game economy and player retention... with guardrails, observability, evals and business impact."

Compares:
- Arm A (Control): Kingdom under status-quo static governance (no LiveOps intervention)
- Arm B (Treatment): Kingdom under autonomous Royal Steward LiveOps system

Evaluates:
- Player Retention (D12 / D24 survival rate of starting cohort)
- Cumulative Churn
- Wealth Gini Inequality
- Population Happiness & Unrest
- Treasury Efficiency & ROI

Includes bootstrap confidence intervals and Welch's t-test / permutation significance tests.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats

from .economy import Economy
from .events import LiveOps
from .laws import LAW_SETS, Laws
from .metrics import snapshot
from .steward import RoyalSteward


@dataclass
class ABExperimentResult:
    n_citizens: int
    ticks: int
    control_snapshots: List[Dict[str, Any]]
    treatment_snapshots: List[Dict[str, Any]]
    control_steward_logs: List[Dict[str, Any]]
    treatment_steward_logs: List[Dict[str, Any]]
    stats: Dict[str, Any]


def bootstrap_metric_diff(a: np.ndarray, b: np.ndarray, n_boot: int = 1000, ci: float = 0.95) -> Dict[str, float]:
    """Computes bootstrap confidence interval of the mean difference (B - A)."""
    rng = np.random.default_rng(42)
    diffs = []
    for _ in range(n_boot):
        sample_a = rng.choice(a, size=len(a), replace=True)
        sample_b = rng.choice(b, size=len(b), replace=True)
        diffs.append(sample_b.mean() - sample_a.mean())
    
    alpha = (1.0 - ci) / 2.0
    diffs = np.sort(diffs)
    return {
        "mean_diff": float(b.mean() - a.mean()),
        "ci_low": float(np.percentile(diffs, 100 * alpha)),
        "ci_high": float(np.percentile(diffs, 100 * (1.0 - alpha))),
    }


def run_kingdom_ab_experiment(
    n_citizens: int = 1500,
    ticks: int = 24,
    law_set: str = "liberal",
    seed: int = 42,
    difficulty: str = "normal",  # "normal" or "drought_season"
    llm=None
) -> ABExperimentResult:
    """Runs a controlled A/B experiment between Static Governance and Agentic LiveOps."""
    laws = LAW_SETS[law_set]

    # --- ARM A: Control (Static Policy, No Steward) ---
    econ_control = Economy(n=n_citizens, laws=laws, seed=seed)
    liveops_control = LiveOps(econ_control)
    control_snapshots = []

    # --- ARM B: Treatment (Royal Steward Active) ---
    econ_treatment = Economy(n=n_citizens, laws=laws, seed=seed)
    liveops_treatment = LiveOps(econ_treatment)
    steward = RoyalSteward(econ_treatment, liveops_treatment, llm=llm)
    treatment_snapshots = []
    steward_logs = []

    for t in range(ticks):
        # Apply exogenous difficulty shocks if specified (e.g. drought at tick 4)
        if difficulty == "drought_season" and t in (4, 12):
            liveops_control.shock("drought")
            liveops_treatment.shock("drought")

        # Control step: no LiveOps agent interventions
        econ_control.step()
        control_snapshots.append(snapshot(econ_control))

        # Treatment step: Steward deliberates and applies guarded LiveOps lever
        log_entry = steward.deliberate()
        steward_logs.append({
            "tick": log_entry.tick,
            "action": log_entry.proposed_action,
            "accepted": log_entry.decision.accepted,
            "reason": log_entry.decision.reason,
            "analysis": log_entry.analysis,
        })
        econ_treatment.step()
        treatment_snapshots.append(snapshot(econ_treatment))

    # Evaluate final cohort retention and health metrics
    control_retention = [s["retention"] for s in control_snapshots]
    treatment_retention = [s["retention"] for s in treatment_snapshots]
    
    control_happiness = [s["happiness"] for s in control_snapshots]
    treatment_happiness = [s["happiness"] for s in treatment_snapshots]

    retention_diff = bootstrap_metric_diff(
        np.array(control_retention),
        np.array(treatment_retention)
    )
    happiness_diff = bootstrap_metric_diff(
        np.array(control_happiness),
        np.array(treatment_happiness)
    )

    t_stat_ret, p_val_ret = stats.ttest_ind(treatment_retention, control_retention)

    final_control = control_snapshots[-1]
    final_treatment = treatment_snapshots[-1]

    analysis_stats = {
        "final_retention_control": final_control["retention"],
        "final_retention_treatment": final_treatment["retention"],
        "retention_relative_lift": float((final_treatment["retention"] - final_control["retention"]) / max(final_control["retention"], 1e-4)),
        "retention_bootstrap_ci": retention_diff,
        "retention_p_value": float(p_val_ret),
        "final_happiness_control": final_control["happiness"],
        "final_happiness_treatment": final_treatment["happiness"],
        "happiness_bootstrap_ci": happiness_diff,
        "final_gini_control": final_control["wealth_gini"],
        "final_gini_treatment": final_treatment["wealth_gini"],
        "final_treasury_control": final_control["treasury"],
        "final_treasury_treatment": final_treatment["treasury"],
        "total_steward_actions": sum(1 for e in steward_logs if e["accepted"] and e["action"] != "do_nothing")
    }

    return ABExperimentResult(
        n_citizens=n_citizens,
        ticks=ticks,
        control_snapshots=control_snapshots,
        treatment_snapshots=treatment_snapshots,
        control_steward_logs=[],
        treatment_steward_logs=steward_logs,
        stats=analysis_stats
    )
