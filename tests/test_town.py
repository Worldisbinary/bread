import pytest

from rlife.game import town as T
from rlife.game.world import GameWorld


def wallet(gold=10_000, food=10_000):
    return {"gold": float(gold), "food": float(food)}


def test_architect_lays_out_every_age_without_overlaps():
    for palace in range(1, 6):
        t = T.architect(0, palace, seed=palace * 7)
        cells = set()
        for b in t.buildings:
            for dx in range(b.size):
                for dy in range(b.size):
                    assert (b.x + dx, b.y + dy) not in cells, "buildings overlap"
                    cells.add((b.x + dx, b.y + dy))
            assert b.x >= 1 and b.x + b.size <= T.GRID - 1
        assert t.palace_level() == palace
        assert t.count("wall") > 20
        assert t.count("archer_tower") == T.BUILDINGS["archer_tower"]["limit"][palace - 1]


def test_building_costs_time_builders_and_palace_limits():
    t = T.architect(0, 1, seed=3, starter=True)
    w, now = wallet(), 1000.0
    assert t.count("house") == t.limit("house") - 1  # room to grow
    t.build("house", 2, 2, w, now - 100)  # finished long ago, so both builders are free
    with pytest.raises(T.TownError, match="palace"):
        t.build("house", 5, 2, w, now)
    farm = next(b for b in t.buildings if b.type == "farm")
    gold = w["gold"]
    t.upgrade(farm.id, w, now)
    assert farm.target == 2 and farm.level == 1 and w["gold"] == gold - T.BUILDINGS["farm"]["cost"][1][1]
    mine = next(b for b in t.buildings if b.type == "mine")
    t.upgrade(mine.id, w, now)
    granary = next(b for b in t.buildings if b.type == "granary")
    with pytest.raises(T.TownError, match="builders"):
        t.upgrade(granary.id, w, now)
    t.advance(now + 60)
    assert farm.level == 2 and not farm.target
    with pytest.raises(T.TownError, match="palace"):
        t.upgrade(farm.id, w, now + 61)  # level 2 is the most a level 1 palace allows
    with pytest.raises(T.TownError, match="Not enough"):
        t.upgrade(granary.id, wallet(0, 0), now + 61)


def test_collectors_fill_in_real_time_and_storage_caps_collection():
    t = T.architect(0, 1, seed=3, starter=True)
    farm = next(b for b in t.buildings if b.type == "farm")
    farm.last, farm.stored = 1.0, 0.0
    t.advance(61.0)  # one minute
    assert farm.stored == pytest.approx(T.BUILDINGS["farm"]["rate"][0])
    t.advance(10_000.0)
    assert farm.stored == T.BUILDINGS["farm"]["capacity"][0]
    w = {"gold": 0.0, "food": float(t.capacity("food") - 50)}
    assert t.collect(farm.id, w, 10_000.0) == 50
    with pytest.raises(T.TownError, match="full"):
        t.collect(farm.id, w, 10_000.0)


def test_training_needs_barracks_level_space_and_grain():
    t = T.architect(0, 1, seed=3, starter=True)
    w = wallet()
    with pytest.raises(T.TownError, match="barracks"):
        t.train("elephant", 1, w, 0.0)
    trained = t.train("spearman", 500, w, 0.0)
    assert trained == t.housing()  # limited by the army camp
    with pytest.raises(T.TownError, match="full"):
        t.train("spearman", 1, w, 0.0)
    t.advance(10_000.0)
    assert t.army["spearman"] == trained and not t.queue


def test_battle_reports_are_checked_against_what_the_army_could_do():
    rival = T.architect(1, 3, seed=11)
    layout = T.battle_layout(rival, {"gold": 1000, "food": 800})
    army = {"spearman": 2}
    cheat = T.check_report(
        layout,
        army,
        {
            "deployed": {"spearman": 50, "elephant": 3},
            "destruction": 100,
            "palace_destroyed": True,
            "loot": {"gold": 10**6, "food": 0},
        },
    )
    assert cheat["deployed"] == {"spearman": 2}
    assert cheat["destruction"] < 100 and cheat["stars"] < 3 and cheat["loot"]["gold"] <= 1000
    assert cheat["corrected"]
    honest = T.check_report(
        layout,
        {"spearman": 30, "archer": 20},
        {
            "deployed": {"spearman": 30, "archer": 20},
            "destruction": 55,
            "palace_destroyed": False,
            "loot": {"gold": 400, "food": 300},
        },
    )
    assert honest["stars"] == 1 and not honest["corrected"] and honest["loot"] == {"gold": 400, "food": 300}


def test_a_raid_moves_loot_glory_and_karma_between_kingdoms():
    world = GameWorld("nile", 2000, -2400, seed=4, kingdoms=5, player=0, age="expansion")
    world.found_town(0)
    me, target = world.kingdoms[0], world.kingdoms[2]
    target.econ.treasury, before = 5000.0, me.econ.treasury
    result = {
        "deployed": {"spearman": 5},
        "destruction": 70.0,
        "palace_destroyed": True,
        "stars": 2,
        "loot": {"gold": 600, "food": 0},
        "corrected": [],
    }
    out = world.apply_battle(target, result)
    assert out["glory"] == T.glory_change(2) and world.towns[0].glory == T.glory_change(2)
    assert target.econ.treasury == 4400.0
    assert me.econ.treasury == before + out["gained"]["gold"]
    assert world.towns[0].army["spearman"] == T.AGES["expansion"]["army"]["spearman"] - 5
    assert me.karma < 0  # an unprovoked raid
    assert any(e["kind"] == "war" and e["attacker"] == 0 for e in world.chronicle)
