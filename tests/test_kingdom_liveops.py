"""Kingdom sim end to end (offline fakes): voices, judge, censorship, karma, steward, queue."""

import json

from rlife.embed import HashEmbedder
from rlife.kingdom.experiment import laws_experiment, render, steward_experiment
from rlife.kingdom.sim import KingdomConfig, KingdomSim
from rlife.kingdom.voices import is_criticism
from rlife.world import World

from .fakes import fake_llm


def make(**overrides):
    cfg = KingdomConfig(**{"citizens": 120, "ticks": 4, "voices_per_tick": 4, "seed": 5, **overrides})
    world = World()
    return world, KingdomSim(world, fake_llm(), HashEmbedder(), cfg, log=lambda *_: None)


def test_a_kingdom_runs_and_records_everything():
    world, sim = make()
    result = sim.run()
    assert result["seasons"] == 4 and result["agent_requests"] == 16
    assert len(world.snapshots()) == 4
    assert world.db.execute("SELECT COUNT(*) FROM citizens").fetchone()[0] == 120
    assert any(i.kind == "comment" for i in world.all_items())
    assert world.posts(["r/royalcourt"])  # the herald announced the laws and the drought
    assert world.snapshots()[-1]["population"] > 0


def test_censorship_applies_only_without_free_speech():
    assert is_criticism("The crown is corrupt and the taxes are robbing us")
    assert not is_criticism("Lovely harvest this year in Rivermead")

    world, sim = make(laws="authoritarian")
    sim.run()
    author = next(a["id"] for a in world.agents())
    pid = world.post(author, "r/townsquare", "Enough", "The crown is corrupt and taxes are unfair", 3)
    before = sim.econ.standing[sim.citizen_of[author]]
    sim._judge_and_censor(3)
    assert world.item(pid).removed.startswith("censored")
    assert sim.econ.standing[sim.citizen_of[author]] == before - 3.0


def test_votes_feed_standing():
    world, sim = make(ticks=1)
    sim.run()
    a, b = world.agents()[:2]
    pid = world.post(a["id"], "r/townsquare", "Hello", "Fine weather", 1)
    world.vote(b["id"], pid, 1, 1)
    before = sim.econ.standing[sim.citizen_of[a["id"]]]
    sim._karma_to_standing(1)
    assert sim.econ.standing[sim.citizen_of[a["id"]]] == before + 0.5


def test_steward_in_propose_mode_waits_for_approval():
    world, sim = make(steward="propose", ticks=4)
    sim.run()
    rows = world.db.execute("SELECT action, status FROM liveops_queue").fetchall()
    assert rows and all(r["status"] == "proposed" for r in rows)
    assert not [e for e in sim.ops.log if e["actor"] == "steward"]  # nothing applied without approval


def test_steward_in_auto_mode_is_still_bound_by_guardrails():
    world, sim = make(steward="auto", ticks=10)
    sim.queue(0, "steward", "adjust_tax", {"delta": 0.2}, "fill the treasury")  # an over-the-limit proposal
    sim.run()
    steward_log = [e for e in sim.ops.log if e["actor"] == "steward"]
    assert len(steward_log) >= 2  # the queued proposal plus the steward's own auto-applied turns
    assert any("exceeds the limit" in e["reason"] for e in steward_log if not e["accepted"])
    assert sim.econ.laws.income_tax <= 0.12 + 1e-9  # the illegal 0.2 tax hike never applied


def test_admin_queue_applies_approved_actions():
    world, sim = make(ticks=2)
    sim.queue(0, "admin", "harvest_festival", {}, "test")
    sim.run()
    assert world.db.execute("SELECT status FROM liveops_queue").fetchone()["status"] == "applied"
    assert any("harvest festival" in (p.title or "") for p in world.posts(["r/royalcourt"]))


def test_experiments_produce_paired_reports():
    laws = laws_experiment(seeds=4, ticks=6, citizens=150)
    assert set(laws["arms"]) == {"liberal", "authoritarian", "socialist"}
    assert "vs_baseline" in laws["arms"]["authoritarian"]["outcomes"]["retention"]
    steward = steward_experiment(fake_llm(), "m", seeds=3, ticks=6, citizens=150, log=lambda *_: None)
    assert steward["steward_actions"]
    assert "What the steward did" in render("steward", steward)
    json.dumps(steward, default=str)
