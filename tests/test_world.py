from rlife.feed import controversy, rank
from rlife.personas import make_personas, populate
from rlife.world import World


def small_world():
    w = World()
    populate(w, n_agents=6, seed=1)
    return w


def test_populate_is_deterministic_and_regionally_balanced():
    assert make_personas(12, seed=3) == make_personas(12, seed=3)
    cities = [p["city"] for p in make_personas(12, seed=3)]
    assert len(set(cities)) == 6 and all(cities.count(c) == 2 for c in set(cities))


def test_personas_never_carry_ideology_labels():
    text = str(make_personas(30, seed=9)).lower()
    for word in ("liberal", "communis", "fascis", "conservative", "left-wing", "right-wing", "socialis"):
        assert word not in text


def test_karma_starts_at_zero_and_follows_votes():
    w = small_world()
    a, b, c = (x["id"] for x in w.agents()[:3])
    assert w.karma_table() == {x["id"]: 0 for x in w.agents()}
    p = w.post(a, "r/life", "Hello", "First post", tick=0)
    assert w.vote(b, p, 1, tick=0)
    assert w.vote(c, p, 1, tick=0)
    assert not w.vote(a, p, 1, tick=0)  # no self-votes
    assert w.karma(a) == 2
    assert w.vote(c, p, -1, tick=1)  # changing a vote replaces it
    assert w.karma(a) == 0


def test_comments_must_belong_to_their_post():
    w = small_world()
    a = w.agents()[0]["id"]
    p1 = w.post(a, "r/life", "One", "x", 0)
    p2 = w.post(a, "r/life", "Two", "y", 0)
    c1 = w.comment(a, p1, "reply", 0)
    try:
        w.comment(a, p2, "wrong thread", 0, parent_id=c1)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert w.item(p1).comments == 1


def test_rankings_differ_in_what_they_reward():
    w = small_world()
    ids = [x["id"] for x in w.agents()]
    old_popular = w.post(ids[0], "r/life", "Old popular", "x", tick=0)
    for voter in ids[1:5]:
        w.vote(voter, old_popular, 1, 0)
    fresh = w.post(ids[1], "r/life", "Fresh", "y", tick=6)
    fight = w.post(ids[2], "r/life", "Divisive", "z", tick=4)
    for voter, value in zip(ids[3:], [1, -1, 1], strict=False):
        w.vote(voter, fight, value, 4)
    w.comment(ids[3], fight, "no", 4)
    w.comment(ids[4], fight, "yes", 4)

    posts = w.posts()
    assert rank(posts, "new", 6)[0].id == fresh
    assert rank(posts, "engagement", 6)[0].id == fight
    assert controversy(w.item(fight)) > 0 == controversy(w.item(old_popular))
