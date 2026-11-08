"""The game world: dynasties on a real-world-inspired map, living through the years.

Each kingdom is a full kingdom economy (rlife.kingdom.economy) for its share of the
population, plus what a strategy game needs on top:

  military   troops (the economy's soldiers), armour, energy (army stamina), walls
  climate    yearly rainfall per kingdom from its land and the region's volatility:
             droughts, floods and bumper harvests feed straight into the economy
  war        a kingdom may raid a nearby kingdom if it has the food, energy and armour;
             walls, terrain and armour decide the battle; loot, losses, vassalage follow
  people     named characters (ruler, general, sage, ...) with abilities, knowledge,
             an ideology position that drifts with what they live through, and karma
  karma      every citizen's standing (lawful work, crime, votes, war service);
             characters and dynasties earn or lose karma for what they do
  chronicle  every notable event, by year, for the timeline

Model assumptions (how ideology drifts, how battles resolve) are written down here and
are choices of this simulation, not claims about real history.
"""

import math
import random
from dataclasses import dataclass, field

import numpy as np

from ..ideology import classify
from ..kingdom.economy import Economy, P
from ..kingdom.events import LiveOps
from ..kingdom.laws import LAW_SETS
from ..kingdom.metrics import snapshot
from . import town as T
from .agents import BAD_POSTS, HARD_NEGATIVES, HELD_OUT_BAD, Director, Warden, moderation_metrics
from .presets import PRESETS, year_label
from .worldgen import BIOMES, B, H, W, generate

COLORS = [
    "#e4572e",
    "#4c9ee8",
    "#f2c14e",
    "#7bc96f",
    "#b07cd8",
    "#ef8bb4",
    "#4fd1c5",
    "#f08a24",
    "#8d99ae",
    "#c0392b",
]
ROLES = {
    "ruler": ["statecraft", "law", "diplomacy"],
    "general": ["tactics", "siegecraft", "horsemanship"],
    "sage": ["astronomy", "medicine", "mathematics", "philosophy"],
    "high_priest": ["rituals", "calendars", "oratory"],
    "merchant": ["trade routes", "coinage", "shipping"],
    "builder": ["irrigation", "masonry", "metallurgy"],
}
GIVEN = [
    "Aruna",
    "Bodhi",
    "Chandra",
    "Dara",
    "Esha",
    "Farid",
    "Gaia",
    "Hiran",
    "Ila",
    "Jaya",
    "Kavi",
    "Lena",
    "Mira",
    "Nala",
    "Omar",
    "Priya",
    "Ravi",
    "Sena",
    "Tara",
    "Uma",
    "Varun",
    "Yara",
    "Zubin",
    "Asha",
]
REACH = 46  # tiles: how far a kingdom can march to raid


@dataclass
class Character:
    name: str
    role: str
    age: int
    might: int
    wisdom: int
    charisma: int
    craft: int
    knowledge: list
    economic: float  # -1 redistribution .. +1 markets
    social: float  # -1 liberty .. +1 order
    karma: float = 0.0
    alive: bool = True

    def to_client(self) -> dict:
        return {
            **self.__dict__,
            "ideology": classify(self.economic, self.social, set()),
            "economic": round(self.economic, 2),
            "social": round(self.social, 2),
            "karma": round(self.karma, 1),
        }


@dataclass
class Kingdom:
    id: int
    name: str
    color: str
    capital: tuple
    traits: dict
    econ: Economy
    ops: LiveOps
    characters: list
    armour: float = 0.0
    food: float = 0.0  # royal granary: a tithe of each harvest, for armies and famine relief
    energy: float = 80.0
    walls: int = 1
    karma: float = 0.0
    vassal_of: int | None = None
    alive: bool = True
    tiles: int = 0
    attacked_by: dict = field(default_factory=dict)  # kingdom id -> last year attacked
    names: list = field(default_factory=list)
    history: list = field(default_factory=list)

    @property
    def soldiers(self) -> np.ndarray:
        return np.flatnonzero(self.econ.present & (self.econ.profession == P["soldier"]))

    @property
    def population(self) -> int:
        return int(self.econ.present.sum())


class GameWorld:
    def __init__(
        self,
        preset: str,
        population: int,
        start_year: int,
        seed: int = 7,
        kingdoms: int = 5,
        player: int = 0,
        llm=None,
        age: str = "founding",
        difficulty: str = "balanced",
    ) -> None:
        self.preset, self.seed, self.year = preset, seed, start_year
        self.age, self.difficulty = age, difficulty
        self.towns: dict[int, T.Town] = {}
        self.start_year = start_year
        self.rng = random.Random(seed)
        self.nrng = np.random.default_rng(seed)  # one generator for every numpy draw
        self.terrain = generate(preset, seed)
        self.chronicle: list[dict] = []
        self.feed: list[dict] = []
        self.player = player
        self.kingdoms = self._found(kingdoms, population)
        self._claim_territory()
        self.wardens = [Warden(k.id) for k in self.kingdoms]
        self.director = Director(llm=llm)
        self.director.difficulty = T.DIFFICULTY.get(difficulty, 1.0)
        self.removed: list[dict] = []
        self.say(
            f"The world begins in {year_label(start_year)}: {len(self.kingdoms)} dynasties settle "
            f"the {PRESETS[preset]['name']}.",
            "founding",
        )

    # --- founding ------------------------------------------------------------

    def _found(self, k: int, population: int) -> list[Kingdom]:
        t, rng = self.terrain, self.rng
        land = np.argwhere(t.land() & (t.biome != B["snow"]) & (t.biome != B["mountain"]))
        weights = np.array([t.fertility[y, x] for y, x in land]) + 1e-3
        capitals: list[tuple[int, int]] = []
        spacing = 20 if k <= 6 else 15 if k <= 8 else 13
        order = np.random.default_rng(self.seed).choice(
            len(land), size=len(land), replace=False, p=weights / weights.sum()
        )
        for i in order:
            y, x = land[i]
            if all((x - cx) ** 2 + (y - cy) ** 2 > spacing**2 for cx, cy in capitals):
                capitals.append((int(x), int(y)))
            if len(capitals) == k:
                break
        fert = np.array(
            [t.fertility[max(0, y - 5) : y + 6, max(0, x - 5) : x + 6].mean() for x, y in capitals]
        )
        shares = fert / fert.sum()
        dynasties = list(PRESETS[self.preset]["dynasties"])
        rng.shuffle(dynasties)
        kingdoms = []
        for i, (cap, share) in enumerate(zip(capitals, shares, strict=True)):
            traits = {
                "aggression": rng.random(),
                "trade": rng.random(),
                "piety": rng.random(),
                "learning": rng.random(),
            }
            laws = self._choose_laws(traits)
            econ = Economy(max(60, int(population * share)), LAW_SETS[laws], seed=self.seed * 31 + i)
            econ.shocks.weather = 1.0
            chars = [self._character(role) for role in ROLES]
            names = [
                f"{rng.choice(GIVEN)} of {dynasties[i % len(dynasties)]}" for _ in range(len(econ.present))
            ]
            kingdoms.append(
                Kingdom(
                    i,
                    f"{dynasties[i % len(dynasties)]}",
                    COLORS[i % len(COLORS)],
                    cap,
                    traits,
                    econ,
                    LiveOps(econ),
                    chars,
                    armour=20 + 40 * traits["aggression"],
                    walls=1 + int(2 * traits["aggression"]),
                    names=names,
                    food=0.5 * econ.n_initial,
                )
            )
        return kingdoms

    def _choose_laws(self, traits: dict) -> str:
        if traits["aggression"] > 0.6 and self.rng.random() < 0.7:
            return "authoritarian"
        if traits["trade"] > 0.55:
            return "liberal"
        return self.rng.choice(["socialist", "liberal", "authoritarian"])

    def _character(self, role: str) -> Character:
        rng = self.rng
        stat = lambda: rng.randint(2, 10)  # noqa: E731
        return Character(
            name=rng.choice(GIVEN),
            role=role,
            age=rng.randint(22, 58),
            might=stat(),
            wisdom=stat(),
            charisma=stat(),
            craft=stat(),
            knowledge=rng.sample(ROLES[role], k=min(2, len(ROLES[role]))),
            economic=rng.uniform(-0.6, 0.6),
            social=rng.uniform(-0.6, 0.6),
        )

    def _claim_territory(self) -> None:
        t = self.terrain
        owner = np.full((H, W), -1)
        ys, xs = np.mgrid[0:H, 0:W]
        best = np.full((H, W), 1e9)
        for k in self.kingdoms:
            cx, cy = k.capital
            # distance grows faster across mountains, so borders follow ridges
            d = np.hypot(xs - cx, ys - cy) * (1 + 1.5 * (t.elevation > 0.68))
            closer = d < best
            owner[closer] = k.id
            best = np.minimum(best, d)
        owner[~t.land() | (best > 27)] = -1
        self.owner = owner
        for k in self.kingdoms:
            k.tiles = int((owner == k.id).sum())

    # --- helpers -------------------------------------------------------------

    def say(self, text: str, kind: str, kingdom: int | None = None, **extra) -> None:
        self.chronicle.append(
            {
                "year": self.year,
                "label": year_label(self.year),
                "kind": kind,
                "text": text,
                "kingdom": kingdom,
                **extra,
            }
        )

    def distance(self, a: Kingdom, b: Kingdom) -> float:
        return math.dist(a.capital, b.capital)

    def neighbours(self, k: Kingdom) -> list[Kingdom]:
        return [o for o in self.kingdoms if o.id != k.id and o.alive and self.distance(k, o) <= REACH]

    def terrain_defence(self, k: Kingdom) -> float:
        x, y = k.capital
        biome = BIOMES[self.terrain.biome[y, x]]
        bonus = {"mountain": 1.45, "hills": 1.25, "forest": 1.1, "marsh": 1.15}.get(biome, 1.0)
        return bonus * (1.15 if self.terrain.river_dist[y, x] <= 2 else 1.0)  # rivers are moats

    # --- player and AI actions -------------------------------------------------

    def train(self, k: Kingdom, n: int) -> str:
        econ = k.econ
        pool = np.flatnonzero(econ.present & np.isin(econ.profession, [P["labourer"], P["farmer"]]))
        n = int(min(n, len(pool), econ.treasury // 2, k.food // 0.5))
        if n <= 0:
            return "Not enough gold, food or labourers to train troops."
        chosen = self.nrng.choice(pool, size=n, replace=False)
        econ.profession[chosen] = P["soldier"]
        econ.treasury -= 2 * n
        k.food -= 0.5 * n
        return f"Trained {n} troops."

    def forge(self, k: Kingdom, n: int) -> str:
        artisans = int((k.econ.present & (k.econ.profession == P["artisan"])).sum())
        n = int(min(n, artisans * 3, k.econ.treasury // 1.5))
        if n <= 0:
            return "Not enough gold or artisans to forge armour."
        k.armour += n
        k.econ.treasury -= 1.5 * n
        return f"Forged {n} sets of armour."

    def build_walls(self, k: Kingdom) -> str:
        cost = 250 * (k.walls + 1)
        if k.walls >= 5:
            return "Walls are already at their highest."
        if k.econ.treasury < cost:
            return f"Walls level {k.walls + 1} costs {cost} gold."
        k.econ.treasury -= cost
        k.walls += 1
        return f"Walls raised to level {k.walls}."

    def attack_requirements(self, att: Kingdom, dfn: Kingdom, share: float = 0.6) -> dict:
        troops = int(len(att.soldiers) * share)
        needs = {"troops": 10, "food": troops * 1.0, "energy": 40, "armour": troops * 0.3}
        have = {"troops": troops, "food": att.food, "energy": att.energy, "armour": att.armour}
        ok = all(have[key] >= needs[key] for key in needs) and dfn in self.neighbours(att)
        return {
            "troops": troops,
            "needs": needs,
            "have": have,
            "in_reach": dfn in self.neighbours(att),
            "ok": ok,
        }

    def attack(self, att: Kingdom, dfn: Kingdom, share: float = 0.6) -> dict:
        req = self.attack_requirements(att, dfn, share)
        if not req["ok"]:
            return {
                "ok": False,
                "reason": "Not enough troops, food, energy or armour, or the target is out of reach.",
                "requirements": req,
            }
        rng = self.nrng
        troops = req["troops"]
        general = next(c for c in att.characters if c.role == "general")
        attack_power = (
            troops
            * (1 + 0.6 * min(att.armour / max(troops, 1), 1))
            * (0.5 + att.energy / 200)
            * (1 + 0.3 * att.traits["aggression"])
            * (1 + general.might / 40)
            * rng.uniform(0.85, 1.15)
        )
        defenders = len(dfn.soldiers)
        militia = 0.05 * dfn.population * 0.3
        town = self.towns.get(dfn.id)
        defence_power = (
            (defenders + militia + (3.0 * T.defense_power(town) if town else 0.0))
            * (1 + 0.25 * dfn.walls)
            * self.terrain_defence(dfn)
            * (1 + 0.4 * min(dfn.armour / max(defenders, 1), 1))
            * rng.uniform(0.85, 1.15)
        )
        won = bool(attack_power > defence_power)
        att_loss = int(troops * (rng.uniform(0.15, 0.3) if won else rng.uniform(0.4, 0.6)))
        def_loss = int(defenders * (rng.uniform(0.4, 0.6) if won else rng.uniform(0.15, 0.3)))
        self._kill(att, att_loss)
        self._kill(dfn, def_loss)
        att.food = max(0.0, att.food - troops * 1.0)
        att.energy -= 35
        att.armour = max(0.0, att.armour - troops * 0.1)
        provoked = self.year - att.attacked_by.get(dfn.id, -(10**6)) <= 5
        dfn.attacked_by[att.id] = self.year
        loot = {"gold": 0.0, "food": 0.0}
        if won:
            share = (0.08, 0.1) if town else (0.25, 0.3)  # a player's town keeps most of its stores
            loot = {"gold": share[0] * max(dfn.econ.treasury, 0), "food": share[1] * dfn.food}
            dfn.econ.treasury -= loot["gold"]
            dfn.food -= loot["food"]
            att.econ.treasury += loot["gold"]
            att.food += loot["food"]
            dfn.econ.happiness[dfn.econ.present] = np.clip(dfn.econ.happiness[dfn.econ.present] - 0.1, 0, 1)
            if len(dfn.soldiers) < 5 and dfn.walls <= 1 and dfn.vassal_of is None:
                dfn.vassal_of = att.id
                self.say(f"{dfn.name} bows to {att.name} and becomes its vassal.", "vassal", dfn.id)
            general.karma += 2
        else:
            next(c for c in dfn.characters if c.role == "general").karma += 3
            dfn.karma += 2
        ruler = next(c for c in att.characters if c.role == "ruler")
        ruler.karma += 2 if provoked else -6  # unprovoked aggression costs a ruler's standing
        att.karma += 1 if provoked else -4
        survivors = att.soldiers
        att.econ.standing[survivors] += 1.0  # war service earns standing at home
        quest = self.director.quest
        if won and quest and att.id == self.player:
            att.econ.treasury += quest["reward"]
            self.say(f"Bounty quest complete: {quest['reward']} gold awarded.", "liveops", att.id)
            self.director.quest = None
        verb = "raided" if won else "was repelled by"
        self.say(
            f"{att.name} {verb} {dfn.name}: {troops} troops marched, {att_loss} fell; "
            f"defenders lost {def_loss}. Loot: {loot['gold']:.0f} gold, {loot['food']:.0f} grain.",
            "war",
            att.id,
            attacker=att.id,
            defender=dfn.id,
            won=won,
        )
        return {
            "ok": True,
            "won": won,
            "troops": troops,
            "attacker_losses": att_loss,
            "defender_losses": def_loss,
            "loot": {k: round(v) for k, v in loot.items()},
            "attack_power": round(attack_power),
            "defence_power": round(defence_power),
            "provoked": provoked,
        }

    def _kill(self, k: Kingdom, n: int) -> None:
        soldiers = k.soldiers
        if n <= 0 or not len(soldiers):
            return
        dead = self.nrng.choice(soldiers, size=min(n, len(soldiers)), replace=False)
        k.econ.present[dead] = False

    def _ai_turn(self, k: Kingdom) -> None:
        rng = self.rng
        econ = k.econ
        soldiers_share = len(k.soldiers) / max(k.population, 1)
        if soldiers_share < 0.05 + 0.08 * k.traits["aggression"] and econ.treasury > 200:
            self.train(k, int(0.02 * k.population) + 5)
        if k.armour < len(k.soldiers) * 0.5 and econ.treasury > 300:
            self.forge(k, int(len(k.soldiers) * 0.3) + 5)
        if econ.treasury > 900 and k.walls < 4 and rng.random() < 0.3:
            self.build_walls(k)
        hungry = (econ.last.get("hungry", np.zeros(1)).sum() / max(k.population, 1)) > 0.03
        aggression = min(1.0, k.traits["aggression"] * self.director.difficulty)
        if rng.random() < 0.25 * aggression + (0.2 if hungry else 0):
            targets = [o for o in self.neighbours(k) if o.vassal_of != k.id]
            if targets:
                weakest = min(targets, key=lambda o: len(o.soldiers) * (1 + 0.25 * o.walls))
                if self.attack_requirements(k, weakest)["ok"] and len(k.soldiers) > 1.2 * len(
                    weakest.soldiers
                ):
                    self.attack(k, weakest)

    # --- the year --------------------------------------------------------------

    def _climate(self, k: Kingdom) -> None:
        p = PRESETS[self.preset]
        x, y = k.capital
        t = self.terrain
        local = t.moisture[max(0, y - 8) : y + 9, max(0, x - 8) : x + 9].mean()
        swing = p["volatility"] * (1.4 - local)
        weather = float(np.clip(1 + self.rng.gauss(0, swing), 0.4, 1.4))
        k.econ.shocks.weather = weather
        k.econ.shocks.remaining["weather"] = 1
        if weather < 0.7:
            self.say(f"Drought in {k.name}: the harvest withers.", "climate", k.id, weather="drought")
        elif weather > 1.25:
            near_river = t.river_dist[y, x] <= 3
            self.say(
                f"{'The river floods' if near_river else 'Rains are generous'} in {k.name}: "
                f"{'silt enriches the fields' if near_river else 'a bumper harvest'}.",
                "climate",
                k.id,
                weather="rain",
            )

    def _drift(self, k: Kingdom, snap: dict) -> None:
        """Ideology and karma drift for characters (stated model assumptions).

        hunger pushes people toward redistribution; rising prosperity toward markets;
        crime and war toward order; censorship (no free speech) pushes the aggrieved toward liberty.
        """
        hunger, crime = snap["hunger_rate"], snap["crime_rate"]
        at_war = any(self.year - y <= 1 for y in k.attacked_by.values())
        for c in k.characters:
            if not c.alive:
                continue
            c.age += 1
            c.economic += -0.6 * hunger + 0.02 * (snap["happiness"] - 0.5) + self.rng.gauss(0, 0.02)
            c.social += 0.8 * crime + (0.03 if at_war else 0) - (0.02 if not k.econ.laws.free_speech else 0)
            c.economic, c.social = float(np.clip(c.economic, -1, 1)), float(np.clip(c.social, -1, 1))
            if c.role == "ruler":
                c.karma += 4 * (snap["happiness"] - 0.5) - 20 * hunger
            if c.age > 62 and self.rng.random() < 0.15:
                c.alive = False
                heir = self._character(c.role)
                heir.age = self.rng.randint(20, 35)
                k.characters[k.characters.index(c)] = heir
                self.say(
                    f"{c.name}, {c.role.replace('_', ' ')} of {k.name}, dies at {c.age}; "
                    f"{heir.name} succeeds.",
                    "succession",
                    k.id,
                )

    def _town_square(self, k: Kingdom, snap: dict) -> None:
        """A few citizens speak each year; neighbours' votes move their standing (karma)."""
        econ, rng = k.econ, self.rng
        present = np.flatnonzero(econ.present)
        if not len(present):
            return
        mood = snap["happiness"]
        for i in rng.sample(list(present), min(3, len(present))):
            prof = list(P)[econ.profession[i]]
            hungry = econ.hunger[i] > 0
            if hungry:
                text = rng.choice(
                    [
                        "Grain costs more than a week's work. How are families to eat?",
                        "Another season with an empty pot. The granaries must open.",
                    ]
                )
            elif prof == "soldier":
                text = rng.choice(
                    [
                        "We marched far this year. I hope the crown remembers the fallen.",
                        "Walls are only as strong as the people behind them.",
                    ]
                )
            elif prof in ("merchant", "artisan", "clerk"):
                text = rng.choice(
                    [
                        "Trade is good when roads are safe and taxes fair.",
                        "The market square was busy today; coin is moving again.",
                    ]
                )
            elif prof == "farmer":
                text = rng.choice(
                    ["The river was kind this year.", "We need better canals before the next drought."]
                )
            else:
                text = rng.choice(
                    ["Our children should learn letters and numbers.", "Order in the streets, at last."]
                )
            truth, roll = "ok", rng.random()
            if roll < 0.06:  # trolls, spammers and injection attempts: labelled, for the wardens' eval
                truth = rng.choice(list(BAD_POSTS))
                text = rng.choice(BAD_POSTS[truth])
            elif roll < 0.10:  # held-out paraphrases the rules never saw
                truth = rng.choice(list(HELD_OUT_BAD))
                text = rng.choice(HELD_OUT_BAD[truth])
            elif roll < 0.14:  # harmless posts that look risky
                text = rng.choice(HARD_NEGATIVES)
            post = {"year": self.year, "text": text, "truth": truth}
            decision = self.wardens[k.id].review(post)
            if decision["action"] == "remove":
                econ.standing[i] -= 2.0  # breaking the town's rules costs karma
                self.removed.append(
                    {
                        **post,
                        "kingdom": k.id,
                        "reason": decision["reason"],
                        "author": k.names[i] if i < len(k.names) else f"Newcomer {i}",
                    }
                )
                self.removed = self.removed[-300:]
                continue
            agree = mood if not hungry else 1 - mood  # the mood of the town decides how it lands
            votes = sum(1 if rng.random() < agree else -1 for _ in range(rng.randint(3, 12)))
            econ.standing[i] += 0.5 * votes
            self.feed.append(
                {
                    "year": self.year,
                    "label": year_label(self.year),
                    "kingdom": k.id,
                    "author": k.names[i] if i < len(k.names) else f"Newcomer {i}",
                    "profession": prof,
                    "text": text,
                    "score": votes,
                }
            )
        self.feed = self.feed[-400:]

    def step(self) -> list[dict]:
        before = len(self.chronicle)
        alive = [k for k in self.kingdoms if k.alive]
        for k in alive:
            self._climate(k)
            k.econ.step()
            town = self.towns.get(k.id)
            cap = max(5.0 * k.population, town.capacity("food")) if town else 5.0 * k.population
            k.food = min(k.food + 0.15 * k.econ.last.get("grain", 0.0), max(cap, k.food))
            if town:
                k.karma += 0.5 * max((b.level for b in town.buildings if b.type == "temple"), default=0)
            k.energy = min(100.0, k.energy + (15 if k.food > 0.1 * k.population else 5))
            k.armour += 0.05 * (k.econ.present & (k.econ.profession == P["artisan"])).sum()
            if k.vassal_of is not None:  # vassals pay a fifth of their tax take as tribute
                lord = self.kingdoms[k.vassal_of]
                tribute = 0.2 * k.econ.last.get("tax", 0.0)
                k.econ.treasury -= tribute
                lord.econ.treasury += tribute
        for k in alive:
            if k.id != self.player:
                self._ai_turn(k)
        for k in alive:
            snap = snapshot(k.econ)
            self._drift(k, snap)
            self._town_square(k, snap)
            k.history.append(
                {
                    "year": self.year,
                    **{
                        key: snap[key]
                        for key in (
                            "population",
                            "retention",
                            "happiness",
                            "unrest",
                            "wealth_gini",
                            "hunger_rate",
                            "crime_rate",
                            "treasury",
                            "grain_price",
                        )
                    },
                    "troops": len(k.soldiers),
                    "armour": round(k.armour),
                    "walls": k.walls,
                }
            )
            if k.population < 25:
                k.alive = False
                self.say(f"The {k.name} dynasty collapses; its last people scatter.", "collapse", k.id)
        self.director.tick(self)
        self.director.score(self)
        quest = self.director.quest
        if quest and self.year > quest["until"]:
            self.say("The bounty quest expired unclaimed.", "liveops", self.player)
            self.director.quest = None
        self.year += 1
        return self.chronicle[before:]

    # --- towns ------------------------------------------------------------------

    def wallet(self, k: Kingdom) -> dict:
        return {"gold": float(k.econ.treasury), "food": float(k.food)}

    def settle(self, k: Kingdom, wallet: dict) -> None:
        k.econ.treasury, k.food = float(wallet["gold"]), float(wallet["food"])

    def found_town(self, kid: int) -> T.Town:
        """The player's starting town, laid out for the chosen age."""
        age = T.AGES[self.age]
        town = T.architect(kid, age["palace"], self.seed * 31 + kid, starter=True)
        town.army = dict(age["army"])
        now = T.now()
        for b in town.buildings:
            b.last = now
            if "produces" in T.BUILDINGS[b.type]:
                b.stored = 0.6 * T.stats(b.type, b.level)["capacity"]  # a first harvest is waiting
        k = self.kingdoms[kid]
        k.econ.treasury = max(k.econ.treasury, age["gold"])
        k.food = max(k.food, age["food"])
        self.towns = {kid: town}
        return town

    def rival_palace(self, k: Kingdom) -> int:
        rivals = [o for o in self.kingdoms if o.alive and o.id != self.player]
        strength = {o.id: len(o.soldiers) * (1 + 0.25 * o.walls) + 0.02 * o.population for o in rivals}
        order = sorted(rivals, key=lambda o: strength[o.id])
        rank = order.index(k) / max(len(order) - 1, 1) if k in order else 0.5
        level = T.AGES[self.age]["palace"] + (1 if rank > 0.66 else -1 if rank < 0.25 else 0)
        level += (self.year - self.start_year) // 30
        return int(min(max(level, 1), 5))

    def rival_town(self, k: Kingdom) -> T.Town:
        palace = self.rival_palace(k)
        return T.architect(k.id, palace, self.seed * 1009 + k.id * 97 + palace * 13 + (self.year // 10))

    def loot_offer(self, k: Kingdom, palace: int) -> dict:
        return {
            "gold": int(0.2 * max(k.econ.treasury, 0) + 250 * palace),
            "food": int(0.25 * max(k.food, 0) + 250 * palace),
        }

    def rivals(self) -> list[dict]:
        me = self.kingdoms[self.player]
        out = []
        for k in self.kingdoms:
            if k.id == self.player or not k.alive:
                continue
            palace = self.rival_palace(k)
            out.append(
                {
                    "id": k.id,
                    "name": k.name,
                    "color": k.color,
                    "palace": palace,
                    "laws": k.econ.laws.name,
                    "troops": len(k.soldiers),
                    "loot": self.loot_offer(k, palace),
                    "in_reach": k in self.neighbours(me),
                    "raided_you": self.year - k.attacked_by.get(me.id, -(10**6)) <= 5
                    or self.year - me.attacked_by.get(k.id, -(10**6)) <= 5,
                }
            )
        return out

    def apply_battle(self, target: Kingdom, result: dict) -> dict:
        """Consequences of a raid the player fought in the browser (already checked by town.check_report)."""
        me = self.kingdoms[self.player]
        town = self.towns[self.player]
        for t, n in result["deployed"].items():
            town.army[t] = max(0, town.army.get(t, 0) - n)
        wallet = self.wallet(me)
        gained = {}
        for res in ("gold", "food"):
            room = max(0, town.capacity(res) - wallet[res])
            gained[res] = int(min(result["loot"][res], room))
            wallet[res] += gained[res]
        self.settle(me, wallet)
        target.econ.treasury = max(0.0, target.econ.treasury - result["loot"]["gold"])
        target.food = max(0.0, target.food - result["loot"]["food"])
        provoked = self.year - me.attacked_by.get(target.id, -(10**6)) <= 5
        target.attacked_by[me.id] = self.year
        glory = T.glory_change(result["stars"])
        town.glory = max(0, town.glory + glory)
        if result["stars"]:
            present = target.econ.present
            target.econ.happiness[present] = np.clip(
                target.econ.happiness[present] - 0.03 * result["stars"], 0, 1
            )
            me.karma += 1 if provoked else -2  # retaliation is understood; unprovoked raids are not
        ruler = next(c for c in me.characters if c.role == "ruler")
        ruler.karma += (1 if provoked else -2) if result["stars"] else 0
        stars = "★" * result["stars"] or "no stars"
        self.say(
            f"{me.name} raided {target.name}: {result['destruction']:.0f}% destroyed, {stars}. "
            f"Taken: {gained['gold']} gold, {gained['food']} grain.",
            "war",
            me.id,
            attacker=me.id,
            defender=target.id,
            won=result["stars"] > 0,
        )
        town.battles.append(
            {"year": self.year, "target": target.id, **result, "gained": gained, "glory": glory}
        )
        town.battles = town.battles[-50:]
        quest = self.director.quest
        bonus = 0
        if quest and result["stars"]:
            bonus = quest["reward"]
            me.econ.treasury += bonus
            self.say(f"Bounty quest complete: {bonus} gold awarded.", "liveops", me.id)
            self.director.quest = None
        return {
            **result,
            "gained": gained,
            "glory": glory,
            "glory_total": town.glory,
            "bonus": bonus,
            "provoked": provoked,
        }

    # --- read-outs -----------------------------------------------------------

    def kingdom_summary(self, k: Kingdom, admin: bool = False) -> dict:
        econ = k.econ
        jobs = {name: int((econ.present & (econ.profession == i)).sum()) for name, i in P.items()}
        out = {
            "id": k.id,
            "name": k.name,
            "color": k.color,
            "capital": k.capital,
            "alive": k.alive,
            "population": k.population,
            "laws": econ.laws.name,
            "free_speech": econ.laws.free_speech,
            "gold": round(econ.treasury),
            "food": round(k.food),
            "armour": round(k.armour),
            "energy": round(k.energy),
            "troops": len(k.soldiers),
            "walls": k.walls,
            "karma": round(k.karma, 1),
            "vassal_of": k.vassal_of,
            "tiles": k.tiles,
            "traits": {a: round(b, 2) for a, b in k.traits.items()},
            "buildings": {
                "houses": k.population // 25,
                "farms": jobs["farmer"] // 12,
                "barracks": max(1, jobs["soldier"] // 40),
                "markets": (jobs["merchant"] + jobs["artisan"]) // 20,
                "temples": 1 + int(k.traits["piety"] * 2),
                "academies": jobs["teacher"] // 15,
            },
            "jobs": jobs,
            "people": {
                "king": 1 if k.alive else 0,
                "soldiers": jobs["soldier"],
                "farmers": jobs["farmer"] + jobs["labourer"],
                "merchants": jobs["merchant"] + jobs["artisan"] + jobs["clerk"],
                "scholars": jobs["teacher"] + jobs["civil_servant"],
            },
            "characters": [c.to_client() for c in k.characters],
            "happiness": round(float(econ.happiness[econ.present].mean()), 3) if k.population else 0,
        }
        if admin:
            out["history"] = k.history[-200:]
            out["liveops_log"] = k.ops.log[-30:]
        return out

    def top_citizens(self, k: Kingdom, n: int = 10) -> list[dict]:
        econ = k.econ
        idx = np.flatnonzero(econ.present)
        order = idx[np.argsort(-econ.standing[idx])][:n]
        return [
            {"name": k.names[i] if i < len(k.names) else f"Newcomer {i}", **econ.citizen(int(i))}
            for i in order
        ]

    def state(self, admin: bool = False) -> dict:
        return {
            "preset": self.preset,
            "region": PRESETS[self.preset]["name"],
            "year": self.year,
            "label": year_label(self.year),
            "player": self.player,
            "kingdoms": [self.kingdom_summary(k, admin) for k in self.kingdoms],
            "owner": self.owner.flatten().tolist(),
            "chronicle": self.chronicle[-60:],
            "feed": self.feed[-60:],
            "quest": self.director.quest,
        }

    def agent_metrics(self) -> dict:
        return {
            "moderation": moderation_metrics(self.wardens),
            "director": self.director.metrics(),
            "director_log": self.director.log[-40:],
            "removed": self.removed[-40:],
        }
