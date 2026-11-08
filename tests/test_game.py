import json

import numpy as np
from fastapi.testclient import TestClient

from rlife.game import api
from rlife.game.presets import PRESETS, year_label
from rlife.game.world import GameWorld
from rlife.game.worldgen import B, generate


def test_every_preset_generates_land_sea_and_rivers_deterministically():
    for preset in PRESETS:
        a, b = generate(preset, 3), generate(preset, 3)
        assert np.array_equal(a.biome, b.biome)
        assert (a.biome == B["river"]).any() and (a.biome == B["sea"]).any() and a.land().any()
        assert all(len(path) > 10 for path in a.rivers)


def test_years_label_bce_and_ce():
    assert year_label(-2500) == "2500 BCE" and year_label(300) == "300 CE"


def test_a_world_lives_through_decades():
    world = GameWorld("indus", 1500, -2500, seed=4, kingdoms=4)
    for _ in range(25):
        world.step()
    state = world.state()
    assert world.year == -2475 and len(state["kingdoms"]) == 4
    assert any(e["kind"] == "climate" for e in world.chronicle)
    assert all(
        "history" not in k for k in state["kingdoms"]
    )  # admin-only metrics stay out of the public state
    assert (
        world.top_citizens(world.kingdoms[0])[0]["standing"]
        >= world.top_citizens(world.kingdoms[0])[-1]["standing"]
    )


def test_attacks_need_supplies_and_reach():
    world = GameWorld("mesopotamia", 2000, -2300, seed=2, kingdoms=5)
    me = world.kingdoms[0]
    far = max(world.kingdoms[1:], key=lambda k: world.distance(me, k))
    near = min(world.kingdoms[1:], key=lambda k: world.distance(me, k))
    if world.distance(me, far) > 46:
        assert not world.attack(me, far)["ok"]
    me.energy = 0
    assert not world.attack_requirements(me, near)["ok"]
    me.energy, me.food, me.armour = 100, 10_000, 10_000
    world.train(me, 60)
    result = world.attack(me, near)
    if world.attack_requirements(me, near)["in_reach"]:
        assert result["ok"] and result["troops"] > 0
        assert any(e["kind"] == "war" and e["attacker"] == me.id for e in world.chronicle)
    # every response the API sends after a battle must be plain JSON (numpy scalars once broke /state)
    json.dumps(result)
    json.dumps(world.state(admin=True) | {"agents": world.agent_metrics()})


def test_api_keeps_metrics_admin_only(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "SAVE_DIR", tmp_path)
    api.SESSIONS.clear()
    from rlife.web import create_app

    client = TestClient(create_app([]))
    assert (
        client.post("/game/api/new", json={"preset": "nile", "population": 800, "kingdoms": 3}).status_code
        == 200
    )
    assert client.post("/game/api/step", json={"years": 2}).status_code == 200
    assert client.get("/game/api/admin/state").status_code == 403
    assert client.post("/game/api/admin/login", json={"token": "wrong"}).status_code == 403
    client.post("/game/api/admin/login", json={"token": api.ADMIN_TOKEN})
    assert len(client.get("/game/api/admin/state").json()["kingdoms"][0]["history"]) == 2
    assert client.get("/game/static/..%2Fapi.py").status_code == 404
