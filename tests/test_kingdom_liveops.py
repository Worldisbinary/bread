import numpy as np
import pytest

from rlife.kingdom.economy import Economy
from rlife.kingdom.events import LiveOps
from rlife.kingdom.experiment import bootstrap_metric_diff, run_kingdom_ab_experiment
from rlife.kingdom.laws import LAW_SETS
from rlife.kingdom.steward import RoyalSteward
from rlife.kingdom.voices import TownSquare


def test_town_square_samples_and_generates_voices():
    econ = Economy(n=300, laws=LAW_SETS["liberal"], seed=10)
    econ.step()
    town_square = TownSquare(econ, sample_size=6)
    voices = town_square.step(recent_events_str="Harvest Fair underway")
    assert len(voices) == 6
    assert len(town_square.history) == 6
    for v in voices:
        assert v.name
        assert v.province
        assert v.profession
        assert v.statement
        assert v.thought


def test_royal_steward_intervenes_on_drought():
    econ = Economy(n=400, laws=LAW_SETS["liberal"], seed=12)
    ops = LiveOps(econ)
    steward = RoyalSteward(econ, ops)
    
    # Introduce severe drought shock
    ops.shock("drought")
    econ.step()
    
    # Deliberation should identify price/hunger risk and intervene
    entry = steward.deliberate()
    assert entry.decision.accepted
    assert entry.proposed_action in ("grain_reserve_release", "adjust_subsidy", "harvest_festival", "do_nothing")
    assert len(steward.audit_log) == 1


def test_bootstrap_metric_diff():
    a = np.array([0.5, 0.52, 0.48, 0.51, 0.49])
    b = np.array([0.7, 0.72, 0.68, 0.71, 0.69])
    res = bootstrap_metric_diff(a, b, n_boot=200)
    assert res["mean_diff"] > 0.15
    assert res["ci_low"] > 0.10
    assert res["ci_high"] > res["ci_low"]


def test_kingdom_ab_experiment_runs():
    res = run_kingdom_ab_experiment(n_citizens=200, ticks=6, difficulty="drought_season")
    assert len(res.control_snapshots) == 6
    assert len(res.treatment_snapshots) == 6
    assert "retention_relative_lift" in res.stats
    assert "retention_bootstrap_ci" in res.stats
    assert res.stats["final_retention_treatment"] >= 0.0
