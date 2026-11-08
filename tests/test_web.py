from fastapi.testclient import TestClient

from rlife.embed import HashEmbedder
from rlife.sim import RunConfig, Simulation
from rlife.web import create_app
from rlife.world import World

from .fakes import fake_llm


def make_run(tmp_path):
    path = tmp_path / "runs" / "demo.db"
    world = World(path)
    cfg = RunConfig(agents=6, ticks=3, active_share=1.0, seed=2)
    Simulation(world, fake_llm(), HashEmbedder(), cfg, log=lambda *_: None).run()
    return str(path), world


def test_pages_render_and_escape_agent_text(tmp_path):
    path, world = make_run(tmp_path)
    agent = world.agents()[0]
    evil = world.post(agent["id"], "r/life", "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", 3)
    client = TestClient(create_app([path]))

    assert client.get("/").status_code == 200
    assert "Karma" in client.get("/run/demo/").text
    feed = client.get("/run/demo/r/r/life").text
    assert "&lt;script&gt;" in feed and "<script>alert(1)" not in feed
    thread = client.get(f"/run/demo/p/{evil}").text
    assert "<img src=x" not in thread
    assert client.get(f"/run/demo/u/{agent['handle']}").status_code == 200
    data = client.get("/api/run/demo/snapshots").json()
    assert len(data["snapshots"]) == 3 and data["agents"]
    assert "Ideology compass" in client.get("/run/demo/compass").text
    assert client.get("/run/nope/").status_code == 404
    assert "rlife_" in client.get("/metrics").text or client.get("/metrics").status_code == 200
