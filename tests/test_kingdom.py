import numpy as np

from rlife.kingdom.economy import Economy, P
from rlife.kingdom.events import LiveOps
from rlife.kingdom.laws import LAW_SETS
from rlife.kingdom.metrics import gini, snapshot


def run(laws="liberal", n=600, ticks=12, seed=3):
    econ = Economy(n, LAW_SETS[laws], seed=seed)
    rows = []
    for _ in range(ticks):
        econ.step()
        rows.append(snapshot(econ))
    return econ, rows


def test_seeded_runs_are_identical():
    _, a = run()
    _, b = run()
    assert [r["population"] for r in a] == [r["population"] for r in b]
    assert a[-1]["treasury"] == b[-1]["treasury"]


def test_metrics_stay_in_range():
    _, rows = run(ticks=24)
    for r in rows:
        assert 0 <= r["happiness"] <= 1 and 0 <= r["unrest"] <= 1 and 0 <= r["wealth_gini"] <= 1
        assert 0 <= r["retention"] <= 1 and r["population"] > 0 and r["grain_price"] > 0
        assert sum(r["jobs"].values()) == r["population"]


def test_drought_raises_grain_prices_and_hunger():
    calm, rows_calm = run(ticks=3)
    econ = Economy(600, LAW_SETS["liberal"], seed=3)
    ops = LiveOps(econ)
    for t in range(3):
        if t == 1:
            ops.shock("drought")
        econ.step()
    assert econ.grain_price > calm.grain_price


def test_harsher_laws_lose_more_citizens():
    _, liberal = run("liberal", ticks=24)
    _, strict = run("authoritarian", ticks=24)
    assert strict[-1]["retention"] < liberal[-1]["retention"]


def test_conscription_fills_the_soldier_quota():
    econ, _ = run("authoritarian", ticks=4)
    soldiers = ((econ.profession == P["soldier"]) & econ.present).sum()
    assert soldiers >= int(econ.laws.conscription * econ.present.sum()) - 1


def test_liveops_guardrails():
    econ = Economy(400, LAW_SETS["liberal"], seed=1)
    ops = LiveOps(econ)
    assert not ops.apply("raise_army", {}).accepted  # not on the allowed list
    assert not ops.apply("adjust_tax", {"delta": 0.2}).accepted  # over the change limit
    assert ops.apply("adjust_tax", {"delta": 0.05}).accepted
    assert abs(econ.laws.income_tax - 0.17) < 1e-9
    assert not ops.apply("adjust_tax", {"delta": 0.05}).accepted  # cooldown
    econ.treasury = 10.0
    assert "over budget" in ops.apply("harvest_festival").reason
    assert len(ops.log) == 5 and sum(e["accepted"] for e in ops.log) == 1


def test_festival_lifts_happiness_for_one_season():
    base = Economy(500, LAW_SETS["liberal"], seed=9)
    fest = Economy(500, LAW_SETS["liberal"], seed=9)
    assert LiveOps(fest).apply("harvest_festival").accepted
    base.step()
    fest.step()
    assert fest.happiness[fest.present].mean() > base.happiness[base.present].mean()


def test_gini():
    assert gini(np.array([1.0, 1.0, 1.0])) == 0.0
    assert gini(np.array([0.0, 0.0, 9.0])) > 0.6
