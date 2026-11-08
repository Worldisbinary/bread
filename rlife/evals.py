"""Evaluating the measurement itself.

The ideology numbers are only as good as the judge. `export_for_labelling` samples
items from runs into a CSV; you fill in your own economic and social scores (-1..1)
and a political yes/no. `judge_agreement` then reports how well the LLM judge and the
embedding anchors agree with you: correlation, mean absolute error, and Cohen's kappa
on three-way buckets (left / centre / right; liberty / centre / order).
"""

import csv
import random
from pathlib import Path

import numpy as np

from .ideology import item_text
from .world import World

FIELDS = ["run", "item_id", "text", "political", "economic", "social", "notes"]


def export_for_labelling(runs: list[str], n: int, out: str, seed: int = 0) -> str:
    rows = []
    for run in runs:
        world = World(run)
        scores = world.scores()
        for item in world.all_items():
            if item.author != "simulated_news" and item.id in scores:
                rows.append({"run": run, "item_id": item.id, "text": item_text(item)})
    random.Random(seed).shuffle(rows)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows[:n]:
            writer.writerow({**row, "political": "", "economic": "", "social": "", "notes": ""})
    return f"wrote {min(n, len(rows))} items to {out}; fill political (y/n), economic and social (-1..1)"


def bucket(x: float, cut: float = 0.25) -> int:
    return -1 if x <= -cut else 1 if x >= cut else 0


def cohen_kappa(a: list[int], b: list[int]) -> float | None:
    if not a:
        return None
    cats = sorted(set(a) | set(b))
    observed = np.mean([x == y for x, y in zip(a, b, strict=True)])
    expected = sum((a.count(c) / len(a)) * (b.count(c) / len(b)) for c in cats)
    return float((observed - expected) / (1 - expected)) if expected < 1 else 1.0


def _compare(human: list[float], machine: list[float]) -> dict:
    h, m = np.array(human), np.array(machine)
    if len(h) < 3:
        return {"n": len(h)}
    return {
        "n": len(h),
        "pearson_r": float(np.corrcoef(h, m)[0, 1]) if h.std() and m.std() else None,
        "mae": float(np.abs(h - m).mean()),
        "kappa_3_buckets": cohen_kappa([bucket(x) for x in h], [bucket(x) for x in m]),
    }


def judge_agreement(labels_csv: str) -> dict:
    with open(labels_csv, encoding="utf-8") as fh:
        labelled = [r for r in csv.DictReader(fh) if r["political"].strip()]
    worlds: dict[str, World] = {}
    pol_h, pol_j = [], []
    axes = {axis: {"human": [], "judge": [], "anchor": []} for axis in ("economic", "social")}
    for row in labelled:
        world = worlds.setdefault(row["run"], World(row["run"]))
        s = world.scores().get(int(row["item_id"]))
        if not s:
            continue
        human_political = row["political"].strip().lower() in ("y", "yes", "1", "true")
        pol_h.append(int(human_political))
        pol_j.append(int(bool(s["political"])))
        if human_political and s["political"] and s["economic"] is not None:
            for axis in axes:
                if row[axis].strip():
                    axes[axis]["human"].append(float(row[axis]))
                    axes[axis]["judge"].append(s[axis])
                    axes[axis]["anchor"].append(s[f"anchor_{axis}"])
    out = {
        "labelled_items": len(pol_h),
        "political_agreement": float(np.mean([a == b for a, b in zip(pol_h, pol_j, strict=True)]))
        if pol_h
        else None,
        "political_kappa": cohen_kappa(pol_h, pol_j),
    }
    for axis, v in axes.items():
        out[axis] = {
            "judge_vs_human": _compare(v["human"], v["judge"]),
            "anchor_vs_human": _compare(v["human"], v["anchor"]),
        }
    return out
