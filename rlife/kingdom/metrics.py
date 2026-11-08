"""Kingdom health metrics, the LiveOps team's dashboard.

The game analogies are deliberate: population is DAU, emigration is churn, the original
cohort still present is retention, the treasury is the economy's sink/source balance,
and unrest is the early-warning signal LiveOps should act on before churn spikes.
"""

import numpy as np

from .economy import PROFESSIONS, SECTOR, Economy


def gini(values: np.ndarray) -> float:
    x = np.sort(np.maximum(values, 0))
    if len(x) == 0 or x.sum() == 0:
        return 0.0
    n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1) @ x / (n * x.sum()))


def snapshot(econ: Economy) -> dict:
    here = econ.present
    pop = int(here.sum())
    last = econ.last or {}
    jobs = {p: int(((econ.profession == i) & here).sum()) for i, p in enumerate(PROFESSIONS)}
    sectors: dict[str, int] = {}
    for p, n in jobs.items():
        sectors[SECTOR[p]] = sectors.get(SECTOR[p], 0) + n
    happiness = econ.happiness[here]
    return {
        "tick": econ.tick_no,
        "population": pop,
        "retention": float((econ.original & here).sum() / econ.n_initial),
        "churned": int(last.get("leaving", np.zeros(0)).sum()),
        "arrivals": int(last.get("arrivals", 0)),
        "happiness": float(happiness.mean()) if pop else 0.0,
        "unrest": float((happiness < 0.3).mean()) if pop else 0.0,
        "wealth_gini": gini(econ.wealth[here]),
        "median_wealth": float(np.median(econ.wealth[here])) if pop else 0.0,
        "hunger_rate": float(last.get("hungry", np.zeros(1)).sum() / max(pop, 1)),
        "crime_rate": float(last.get("steal", np.zeros(1)).sum() / max(pop, 1)),
        "caught": int(last.get("caught", np.zeros(0)).sum()),
        "job_switches": int(last.get("switches", 0)),
        "treasury": float(econ.treasury),
        "tax_revenue": float(last.get("tax", 0.0)),
        "public_pay_ratio": float(last.get("pay_ratio", 1.0)),
        "grain_price": econ.grain_price,
        "goods_price": econ.goods_price,
        "mean_standing": float(econ.standing[here].mean()) if pop else 0.0,
        "jobs": jobs,
        "sectors": sectors,
        "laws": econ.laws.to_dict(),
    }
