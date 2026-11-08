"""Kingdom experiments: LiveOps-style A/B tests with real confidence intervals.

The economy is cheap, so each arm is replicated over many seeds (seed = unit of analysis),
which gives proper uncertainty instead of one run per arm. Arms share seeds, so
differences are paired by seed.

laws     liberal vs authoritarian vs socialist, same shock schedule (a drought in season 6)
steward  no LiveOps vs the LLM Royal Steward on the same seeds, under two droughts:
         does an agentic LiveOps operator improve retention and happiness, and at what cost?

Results describe this model's behaviour under its stated rules, not real societies.
"""

import json
from pathlib import Path

import numpy as np

from ..stats import bootstrap_ci
from .economy import Economy
from .events import LiveOps
from .laws import LAW_SETS
from .metrics import snapshot
from .steward import Steward

OUTCOMES = {
    "retention": "Share of the original citizens still in the kingdom at the end",
    "mean_happiness": "Average happiness over all seasons",
    "peak_unrest": "Highest share of unhappy citizens in any season",
    "final_gini": "Wealth inequality (Gini) at the end",
    "hunger_seasons": "Average share of citizens hungry per season",
    "final_treasury_per_citizen": "Treasury per citizen at the end",
}


def run_economy(
    laws: str,
    seed: int,
    ticks: int,
    citizens: int,
    shocks: dict,
    steward: Steward | None = None,
    every: int = 2,
) -> dict:
    econ = Economy(citizens, LAW_SETS[laws], seed=seed)
    ops = LiveOps(econ)
    history = []
    for tick in range(ticks):
        if tick in shocks:
            ops.shock(shocks[tick])
        econ.step()
        history.append(snapshot(econ))
        if steward and tick >= 1 and tick % every == 0:
            p = steward.propose(history, ops.log)
            ops.apply(p["action"], p["args"], actor="steward", rationale=p["rationale"])
    return {
        "retention": history[-1]["retention"],
        "mean_happiness": float(np.mean([h["happiness"] for h in history])),
        "peak_unrest": float(max(h["unrest"] for h in history)),
        "final_gini": history[-1]["wealth_gini"],
        "hunger_seasons": float(np.mean([h["hunger_rate"] for h in history])),
        "final_treasury_per_citizen": history[-1]["treasury"] / max(history[-1]["population"], 1),
        "actions": [e for e in ops.log if e["actor"] == "steward"],
    }


def paired_test(diffs: list[float], shuffles: int = 5000, seed: int = 0) -> float:
    """Two-sided sign-flip permutation p-value for a mean paired difference."""
    d = np.asarray(diffs, dtype=float)
    rng = np.random.default_rng(seed)
    observed = abs(d.mean())
    flips = np.abs((d * rng.choice([-1.0, 1.0], size=(shuffles, len(d)))).mean(axis=1))
    return float((np.sum(flips >= observed - 1e-12) + 1) / (shuffles + 1))


def compare(rows_by_arm: dict, baseline: str) -> dict:
    out = {"baseline": baseline, "arms": {}}
    for arm, rows in rows_by_arm.items():
        entry = {"n": len(rows), "outcomes": {}}
        for key in OUTCOMES:
            values = [r[key] for r in rows]
            entry["outcomes"][key] = {"estimate": bootstrap_ci(values)}
            if arm != baseline:
                base = [r[key] for r in rows_by_arm[baseline]]
                diffs = [a - b for a, b in zip(values, base, strict=True)]
                entry["outcomes"][key]["vs_baseline"] = {
                    "difference": bootstrap_ci(diffs),
                    "p_value": paired_test(diffs),
                }
        out["arms"][arm] = entry
    return out


def laws_experiment(seeds: int = 30, ticks: int = 24, citizens: int = 1500) -> dict:
    shocks = {6: "drought"}
    rows = {name: [run_economy(name, s, ticks, citizens, shocks) for s in range(seeds)] for name in LAW_SETS}
    return compare(rows, "liberal")


def steward_experiment(
    llm, model: str, seeds: int = 8, ticks: int = 16, citizens: int = 1500, laws: str = "liberal", log=print
) -> dict:
    shocks = {4: "drought", 10: "drought"}
    rows = {"no_liveops": [], "steward": []}
    for s in range(seeds):
        base = run_economy(laws, s, ticks, citizens, shocks)
        with_s = run_economy(laws, s, ticks, citizens, shocks, steward=Steward(llm, model))
        rows["no_liveops"].append(base)
        rows["steward"].append(with_s)
        log(
            "seed {}: retention {:.3f} -> {:.3f}, happiness {:.3f} -> {:.3f}".format(
                s, base["retention"], with_s["retention"], base["mean_happiness"], with_s["mean_happiness"]
            )
        )
    result = compare(rows, "no_liveops")
    result["steward_actions"] = [a for r in rows["steward"] for a in r["actions"]]
    return result


def _fmt(ci) -> str:
    return "n/a" if ci is None else f"{ci[0]:.3f} [{ci[1]:.3f}, {ci[2]:.3f}]"


def render(name: str, result: dict) -> str:
    lines = [
        f"# Kingdom experiment: {name}",
        "",
        f"Baseline: `{result['baseline']}`. Seeds are the unit; differences are paired by seed. "
        "Intervals are 95% bootstrap; p-values from sign-flip permutation. These results describe "
        "the model's behaviour under its stated rules.",
        "",
    ]
    for key, title in OUTCOMES.items():
        lines += [
            f"## {title}",
            "",
            "| Arm | n | Estimate | Difference vs baseline | p |",
            "|---|---|---|---|---|",
        ]
        for arm, entry in result["arms"].items():
            o = entry["outcomes"][key]
            vs = o.get("vs_baseline", {})
            p = vs.get("p_value")
            p_text = "" if p is None else f"{p:.4f}"
            lines.append(
                f"| {arm} | {entry['n']} | {_fmt(o['estimate'])} | {_fmt(vs.get('difference'))} | {p_text} |"
            )
        lines.append("")
    if result.get("steward_actions"):
        counts: dict[str, int] = {}
        for a in result["steward_actions"]:
            key = f"{a['action']} ({'accepted' if a['accepted'] else 'rejected: ' + a['reason']})"
            counts[key] = counts.get(key, 0) + 1
        lines += ["## What the steward did", ""]
        lines += [f"- {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])]
    return "\n".join(lines) + "\n"


def save(name: str, result: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir) / f"kingdom-{name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(result, indent=2, default=str))
    (out / "report.md").write_text(render(name, result))
    return out / "report.md"
