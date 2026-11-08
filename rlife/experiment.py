"""A/B experiments: the same society, news and seed, with one platform setting changed.

Feed-ranking experiment: arms differ only in ranking (new, hot, engagement).
Red-team experiment: arms differ only in defences (none, prompt rule only, full filters).

Each arm is one run file under runs/<experiment>/<arm>.db. The report compares arms
on per-unit outcomes with bootstrap intervals and permutation p-values.
"""

import json
from pathlib import Path

import numpy as np

from . import metrics
from .sim import RunConfig, Simulation
from .stats import bootstrap_ci, bootstrap_diff, pairwise_distances_by_agent, permutation_p
from .world import World

EXPERIMENTS = {
    "ranking": [
        {"arm": "new", "ranking": "new"},
        {"arm": "hot", "ranking": "hot"},
        {"arm": "engagement", "ranking": "engagement"},
    ],
    "redteam": [
        {"arm": "no_defence", "ranking": "new", "red_team": True, "filters": False, "prompt_defense": False},
        {"arm": "prompt_rule", "ranking": "new", "red_team": True, "filters": False, "prompt_defense": True},
        {
            "arm": "full_guardrails",
            "ranking": "new",
            "red_team": True,
            "filters": True,
            "prompt_defense": True,
        },
    ],
}


def run_experiment(name: str, llm, embedder, out_dir: str | Path, base: dict, log=print) -> dict:
    out = Path(out_dir) / name
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for arm in EXPERIMENTS[name]:
        config = RunConfig(**{**base, **arm})
        world = World(out / f"{arm['arm']}.db")
        log(f"=== {name}: arm {arm['arm']} ===")
        results[arm["arm"]] = Simulation(world, llm, embedder, config, log=log).run()
    report = analyse(out, [a["arm"] for a in EXPERIMENTS[name]])
    (out / "report.json").write_text(json.dumps({"runs": results, "analysis": report}, indent=2))
    (out / "report.md").write_text(render(name, report))
    return report


def arm_units(world: World) -> dict:
    """Per-unit outcome samples for one arm."""
    pos = metrics.positions(metrics.political_scores(world))
    pts = np.array([[p["economic"], p["social"]] for p in pos.values() if p["n"] >= 2])
    scores = world.scores()
    member_items = [i for i in world.all_items() if i.author != "simulated_news" and i.id in scores]
    flagged = [1.0 if scores[i.id]["flags"] else 0.0 for i in member_items]
    political = [1.0 if scores[i.id]["political"] else 0.0 for i in member_items]
    extremity = [
        float(np.hypot(scores[i.id]["economic"], scores[i.id]["social"]))
        for i in member_items
        if scores[i.id]["political"] and scores[i.id]["economic"] is not None
    ]
    karma = list(world.karma_table().values())
    return {
        "agent_spread": pairwise_distances_by_agent(pts).tolist() if len(pts) > 1 else [],
        "flagged": flagged,
        "political": political,
        "extremity": extremity,
        "karma": karma,
        "homophily": metrics.reply_homophily(world, pos),
        "vote_alignment": metrics.vote_alignment(world, pos),
        "labels": metrics.summary(world)["agent_labels"],
        "items": len(member_items),
        "result": world.meta("result"),
    }


OUTCOMES = {
    "agent_spread": "Polarization: each agent's mean ideological distance to others",
    "extremity": "Extremity: distance of political items from the centre",
    "flagged": "Share of items with an extremism flag",
    "political": "Share of items that are political",
}


def analyse(out_dir: Path, arms: list[str]) -> dict:
    units = {arm: arm_units(World(out_dir / f"{arm}.db")) for arm in arms if (out_dir / f"{arm}.db").exists()}
    baseline = arms[0]
    analysis = {"baseline": baseline, "arms": {}}
    for arm, u in units.items():
        row = {
            "items": u["items"],
            "labels": u["labels"],
            "homophily": u["homophily"],
            "vote_alignment": u["vote_alignment"],
            "karma_gini": metrics.gini(u["karma"]),
            "injection_compliance": (u["result"] or {}).get("injection_compliance"),
            "outcomes": {},
        }
        for key in OUTCOMES:
            row["outcomes"][key] = {"estimate": bootstrap_ci(u[key])}
            if arm != baseline and baseline in units:
                row["outcomes"][key]["vs_baseline"] = {
                    "difference": bootstrap_diff(units[baseline][key], u[key]),
                    "p_value": permutation_p(units[baseline][key], u[key]),
                }
        analysis["arms"][arm] = row
    return analysis


def _fmt(ci) -> str:
    return "n/a" if ci is None else f"{ci[0]:.3f} [{ci[1]:.3f}, {ci[2]:.3f}]"


def render(name: str, analysis: dict) -> str:
    lines = [
        f"# Experiment: {name}",
        "",
        f"Baseline arm: `{analysis['baseline']}`. Intervals are 95% bootstrap.",
        "",
    ]
    for key, title in OUTCOMES.items():
        lines += [f"## {title}", "", "| Arm | Estimate | Difference vs baseline | p |", "|---|---|---|---|"]
        for arm, row in analysis["arms"].items():
            o = row["outcomes"][key]
            vs = o.get("vs_baseline", {})
            p = vs.get("p_value")
            lines.append(
                f"| {arm} | {_fmt(o['estimate'])} | {_fmt(vs.get('difference'))} | "
                f"{'' if p is None else f'{p:.3f}'} |"
            )
        lines.append("")
    lines += ["## Echo chambers, votes, karma, labels", ""]
    for arm, row in analysis["arms"].items():
        h, v = row["homophily"], row["vote_alignment"]
        homophily = (
            "n/a" if not h else "{:.2f} (p={:.3f}, {} pairs)".format(h["ratio"], h["p_value"], h["pairs"])
        )
        gap = "n/a" if not v else "{:.3f}".format(v["gap"])
        gini = "n/a" if row["karma_gini"] is None else "{:.3f}".format(row["karma_gini"])
        lines.append(
            f"- **{arm}**: reply-distance ratio {homophily}; upvote vs downvote distance gap {gap}; "
            f"karma Gini {gini}; agent labels {row['labels']}"
        )
        if row["injection_compliance"]:
            c = row["injection_compliance"]
            rate = "n/a (never shown)" if c["rate"] is None else f"{c['rate']:.0%}"
            lines.append(f"  - injection compliance: {rate} of {c['exposed_agents']} exposed agents obeyed")
    return "\n".join(lines) + "\n"
