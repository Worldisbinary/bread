"""Towns: the base-building and raiding layer of the game.

Every kingdom has a town on a GRID x GRID map: a palace, farms and mines that produce in real time,
granaries and treasuries that store, barracks and an army camp, towers and catapults that defend,
walls, houses and a temple. The player builds and upgrades theirs; rival towns are laid out by a
rule-based architect from each kingdom's strength and age.

Battles are animated and simulated in the browser, so they feel immediate. The server stays
authoritative for everything that matters: it owns the economy and the army, and it checks every
battle report against what the deployed army could possibly have done (a guardrail, with the number
of reports it had to correct counted for the admin console).

Resources are the kingdom's own: gold is the treasury of the simulated economy, grain is the royal
granary. Spending gold on walls is gold not spent on the economy, and raids take from the
kingdom that is raided.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

GRID = 44
BUILDERS = 2
BATTLE_SECONDS = 150

AGES = {
    "founding": {
        "name": "Founding age",
        "summary": "A young town. Spearmen and archers; one archer tower.",
        "palace": 1,
        "where": 0.15,
        "population": 2000,
        "gold": 2500,
        "food": 2500,
        "army": {"spearman": 14, "archer": 8},
    },
    "expansion": {
        "name": "Age of expansion",
        "summary": "Walled towns. Horse raiders, bolt throwers, more of everything.",
        "palace": 2,
        "where": 0.5,
        "population": 3000,
        "gold": 5000,
        "food": 5000,
        "army": {"spearman": 14, "archer": 10, "raider": 4},
    },
    "empire": {
        "name": "Age of empire",
        "summary": "Great cities. Battering rams, war elephants and catapults.",
        "palace": 3,
        "where": 0.85,
        "population": 4000,
        "gold": 9000,
        "food": 9000,
        "army": {"spearman": 12, "archer": 12, "raider": 6, "ram": 4, "elephant": 1},
    },
}

DIFFICULTY = {"peaceful": 0.6, "balanced": 1.0, "warlike": 1.4}

# Per level, index 0 = level 1. "limit" is how many may stand at each palace level.
BUILDINGS: dict[str, dict] = {
    "palace": {
        "name": "Palace",
        "role": "core",
        "size": 4,
        "cost": ("gold", [0, 1500, 4000, 9000, 16000]),
        "time": [0, 40, 80, 120, 180],
        "hp": [1500, 2100, 2800, 3600, 4500],
        "limit": [1, 1, 1, 1, 1],
        "capacity": [1500, 3000, 5000, 7000, 9000],
        "about": "The seat of your dynasty. Its level decides what else you may build.",
    },
    "farm": {
        "name": "Farm",
        "role": "resource",
        "size": 3,
        "cost": ("gold", [150, 400, 900, 1800, 3500]),
        "time": [5, 15, 30, 60, 90],
        "hp": [350, 420, 500, 600, 720],
        "limit": [2, 3, 4, 5, 6],
        "produces": "food",
        "rate": [30, 50, 75, 105, 140],
        "capacity": [300, 600, 1000, 1500, 2100],
        "about": "Farmers grow grain all the time. Tap it to bring the harvest in.",
    },
    "mine": {
        "name": "Gold mine",
        "role": "resource",
        "size": 3,
        "cost": ("food", [150, 400, 900, 1800, 3500]),
        "time": [5, 15, 30, 60, 90],
        "hp": [350, 420, 500, 600, 720],
        "limit": [2, 3, 4, 5, 6],
        "produces": "gold",
        "rate": [30, 50, 75, 105, 140],
        "capacity": [300, 600, 1000, 1500, 2100],
        "about": "Miners dig gold all the time. Tap it to fill the treasury.",
    },
    "granary": {
        "name": "Granary",
        "role": "resource",
        "size": 3,
        "cost": ("gold", [300, 900, 2000, 4500, 9000]),
        "time": [10, 25, 50, 90, 120],
        "hp": [600, 800, 1000, 1250, 1500],
        "limit": [1, 1, 2, 2, 3],
        "stores": "food",
        "capacity": [3000, 6000, 12000, 22000, 40000],
        "about": "Stores grain. Raiders love a full granary.",
    },
    "treasury": {
        "name": "Treasury",
        "role": "resource",
        "size": 3,
        "cost": ("food", [300, 900, 2000, 4500, 9000]),
        "time": [10, 25, 50, 90, 120],
        "hp": [600, 800, 1000, 1250, 1500],
        "limit": [1, 1, 2, 2, 3],
        "stores": "gold",
        "capacity": [3000, 6000, 12000, 22000, 40000],
        "about": "Stores gold. Keep it behind walls.",
    },
    "barracks": {
        "name": "Barracks",
        "role": "army",
        "size": 3,
        "cost": ("food", [200, 700, 1600, 3500, 7000]),
        "time": [10, 30, 60, 90, 120],
        "hp": [400, 500, 620, 760, 900],
        "limit": [1, 1, 1, 1, 1],
        "about": "Trains troops. Each level unlocks a new kind of soldier.",
    },
    "camp": {
        "name": "Army camp",
        "role": "army",
        "size": 4,
        "cost": ("food", [300, 1000, 2500, 5000, 9000]),
        "time": [10, 30, 60, 90, 120],
        "hp": [300, 380, 460, 550, 650],
        "limit": [1, 1, 2, 2, 3],
        "housing": [30, 40, 50, 60, 75],
        "about": "Where your army waits. More camps, bigger army.",
    },
    "archer_tower": {
        "name": "Archer tower",
        "role": "defense",
        "size": 3,
        "cost": ("gold", [500, 1200, 2500, 5000, 9000]),
        "time": [15, 40, 70, 100, 140],
        "hp": [450, 600, 760, 950, 1150],
        "limit": [1, 2, 3, 4, 5],
        "defense": {
            "range": 7.0,
            "min_range": 0.0,
            "damage": [11, 15, 20, 26, 33],
            "interval": 1.0,
            "splash": 0.0,
        },
        "about": "Archers shoot anything in range, quickly.",
    },
    "bolt_thrower": {
        "name": "Bolt thrower",
        "role": "defense",
        "size": 3,
        "cost": ("gold", [900, 2000, 4000, 7500, 12000]),
        "time": [20, 50, 90, 130, 170],
        "hp": [520, 700, 880, 1080, 1300],
        "limit": [0, 1, 2, 2, 3],
        "defense": {
            "range": 8.0,
            "min_range": 0.0,
            "damage": [45, 60, 78, 98, 120],
            "interval": 1.6,
            "splash": 0.0,
        },
        "about": "A giant crossbow: slow, heavy bolts that stop big troops.",
    },
    "catapult": {
        "name": "Catapult",
        "role": "defense",
        "size": 3,
        "cost": ("gold", [2000, 4000, 7500, 12000, 18000]),
        "time": [30, 70, 110, 150, 200],
        "hp": [600, 780, 960, 1150, 1400],
        "limit": [0, 0, 1, 1, 2],
        "defense": {
            "range": 10.0,
            "min_range": 3.5,
            "damage": [38, 50, 64, 80, 98],
            "interval": 4.0,
            "splash": 1.6,
        },
        "about": "Hurls stones over walls. Crushes groups, but cannot hit troops right next to it.",
    },
    "wall": {
        "name": "Wall",
        "role": "wall",
        "size": 1,
        "cost": ("gold", [50, 200, 600, 1500, 3500]),
        "time": [0, 0, 0, 0, 0],
        "hp": [300, 700, 1300, 2000, 3000],
        "limit": [70, 100, 130, 160, 190],
        "about": "Slows attackers down. Rams break them.",
    },
    "house": {
        "name": "House",
        "role": "civic",
        "size": 2,
        "cost": ("gold", [100, 250, 600, 1200, 2500]),
        "time": [5, 10, 20, 40, 60],
        "hp": [200, 260, 320, 390, 460],
        "limit": [3, 4, 5, 6, 8],
        "about": "Homes for your people. Every house adds villagers to the streets.",
    },
    "temple": {
        "name": "Temple",
        "role": "civic",
        "size": 3,
        "cost": ("gold", [800, 2000, 4500, 9000, 15000]),
        "time": [20, 50, 90, 130, 170],
        "hp": [600, 780, 960, 1150, 1400],
        "limit": [0, 1, 1, 1, 1],
        "about": "Priests and scholars. Raises your dynasty's karma every year.",
    },
}

TROOPS: dict[str, dict] = {
    "spearman": {
        "name": "Spearman",
        "about": "Sturdy and cheap. Attacks the nearest building.",
        "housing": 1,
        "cost": 25,
        "time": 2.0,
        "hp": 70,
        "dps": 11,
        "range": 0.8,
        "speed": 1.6,
        "prefers": "any",
        "barracks": 1,
    },
    "archer": {
        "name": "Archer",
        "about": "Shoots over walls from a distance. Fragile.",
        "housing": 1,
        "cost": 50,
        "time": 3.0,
        "hp": 30,
        "dps": 9,
        "range": 3.5,
        "speed": 1.8,
        "prefers": "any",
        "barracks": 2,
    },
    "raider": {
        "name": "Horse raider",
        "about": "Fast. Goes for farms, mines and storehouses; double damage to them.",
        "housing": 2,
        "cost": 70,
        "time": 4.0,
        "hp": 90,
        "dps": 14,
        "bonus": 2.0,
        "range": 0.8,
        "speed": 2.8,
        "prefers": "resource",
        "barracks": 3,
    },
    "ram": {
        "name": "Battering ram",
        "about": "Runs at the nearest wall and smashes it. Single use.",
        "housing": 2,
        "cost": 150,
        "time": 6.0,
        "hp": 100,
        "dps": 0,
        "blast": 450,
        "blast_radius": 1.5,
        "range": 0.6,
        "speed": 2.0,
        "prefers": "wall",
        "barracks": 4,
    },
    "elephant": {
        "name": "War elephant",
        "about": "A walking fortress. Targets defenses only.",
        "housing": 6,
        "cost": 400,
        "time": 10.0,
        "hp": 1000,
        "dps": 30,
        "range": 1.0,
        "speed": 1.0,
        "prefers": "defense",
        "barracks": 5,
    },
}


def catalog() -> dict:
    return {
        "grid": GRID,
        "builders": BUILDERS,
        "battle_seconds": BATTLE_SECONDS,
        "buildings": BUILDINGS,
        "troops": TROOPS,
        "ages": {k: {key: v[key] for key in ("name", "summary", "palace")} for k, v in AGES.items()},
    }


def stats(btype: str, level: int) -> dict:
    """Resolved numbers for one building at one level (level 0 = still under construction)."""
    spec = BUILDINGS[btype]
    i = max(level, 1) - 1
    out = {"hp": spec["hp"][i], "size": spec["size"], "role": spec["role"]}
    for key in ("rate", "capacity", "housing"):
        if key in spec:
            out[key] = spec[key][i]
    if "defense" in spec:
        d = spec["defense"]
        out["defense"] = {**d, "damage": d["damage"][i]}
    return out


@dataclass
class Building:
    id: int
    type: str
    level: int
    x: int
    y: int
    target: int = 0  # level being built or upgraded to; 0 = idle
    ready_at: float = 0.0
    stored: float = 0.0  # collectors: produced but not yet collected
    last: float = 0.0  # collectors: when production was last accounted

    @property
    def size(self) -> int:
        return BUILDINGS[self.type]["size"]

    def busy(self, now: float) -> bool:
        return self.target > 0 and self.ready_at > now

    def to_client(self, now: float) -> dict:
        level = max(self.level, 1)
        return {
            "id": self.id,
            "type": self.type,
            "level": self.level,
            "x": self.x,
            "y": self.y,
            "size": self.size,
            "target": self.target,
            "ready_in": round(max(self.ready_at - now, 0.0), 1) if self.target else 0,
            "stored": int(self.stored),
            **{k: v for k, v in stats(self.type, level).items() if k != "size"},
        }


@dataclass
class Town:
    kingdom: int
    buildings: list = field(default_factory=list)
    army: dict = field(default_factory=dict)
    queue: list = field(default_factory=list)  # [{"type", "done_at"}], trained in order
    glory: int = 0
    next_id: int = 1
    battles: list = field(default_factory=list)

    # --- queries -------------------------------------------------------------

    def palace_level(self) -> int:
        return max((b.level for b in self.buildings if b.type == "palace"), default=1) or 1

    def count(self, btype: str) -> int:
        return sum(b.type == btype for b in self.buildings)

    def limit(self, btype: str) -> int:
        return BUILDINGS[btype]["limit"][self.palace_level() - 1]

    def max_level(self, btype: str) -> int:
        if btype == "palace":
            return 5
        return min(5, self.palace_level() + 1)

    def capacity(self, resource: str) -> int:
        total = 0
        for b in self.buildings:
            if b.level and (b.type == "palace" or BUILDINGS[b.type].get("stores") == resource):
                total += stats(b.type, b.level)["capacity"]
        return total

    def housing(self) -> int:
        return sum(stats("camp", b.level)["housing"] for b in self.buildings if b.type == "camp" and b.level)

    def army_size(self) -> int:
        return sum(TROOPS[t]["housing"] * n for t, n in self.army.items())

    def queued_size(self) -> int:
        return sum(TROOPS[q["type"]]["housing"] for q in self.queue)

    def barracks_level(self) -> int:
        return max((b.level for b in self.buildings if b.type == "barracks"), default=0)

    def builders_busy(self, now: float) -> int:
        return sum(b.busy(now) for b in self.buildings)

    def get(self, bid: int) -> Building:
        for b in self.buildings:
            if b.id == bid:
                return b
        raise TownError("No such building.")

    def fits(self, btype: str, x: int, y: int, ignore: int | None = None) -> bool:
        size = BUILDINGS[btype]["size"]
        if x < 1 or y < 1 or x + size > GRID - 1 or y + size > GRID - 1:
            return False
        for b in self.buildings:
            if b.id == ignore:
                continue
            if x < b.x + b.size and b.x < x + size and y < b.y + b.size and b.y < y + size:
                return False
        return True

    # --- time ------------------------------------------------------------------

    def advance(self, now: float) -> list[str]:
        """Bring the town up to the present: finish builds, produce, train. Returns news."""
        news = []
        for b in self.buildings:
            if b.target and b.ready_at <= now:
                if b.level == 0:  # a new collector starts producing when it is finished, not when ordered
                    b.last = b.ready_at
                b.level, b.target, b.ready_at = b.target, 0, 0.0
                news.append(f"{BUILDINGS[b.type]['name']} reached level {b.level}.")
            spec = BUILDINGS[b.type]
            if "produces" in spec and b.level:
                since = max(0.0, now - (b.last or now))
                b.stored = min(
                    stats(b.type, b.level)["capacity"], b.stored + stats(b.type, b.level)["rate"] * since / 60
                )
                b.last = now
        while self.queue and self.queue[0]["done_at"] <= now:
            done = self.queue.pop(0)
            self.army[done["type"]] = self.army.get(done["type"], 0) + 1
        return news

    def _new(self, btype: str, level: int, x: int, y: int, now: float) -> Building:
        b = Building(self.next_id, btype, level, x, y, last=now)
        self.next_id += 1
        self.buildings.append(b)
        return b

    # --- player actions (resources are the kingdom's, passed in as a wallet) ---------------

    def build(self, btype: str, x: int, y: int, wallet: dict, now: float) -> Building:
        if btype not in BUILDINGS or btype == "palace":
            raise TownError("You cannot build that.")
        if self.count(btype) >= self.limit(btype):
            raise TownError(f"Upgrade your palace to build more {BUILDINGS[btype]['name'].lower()}s.")
        if not self.fits(btype, x, y):
            raise TownError("There is no room there.")
        instant = BUILDINGS[btype]["time"][0] == 0
        if not instant and self.builders_busy(now) >= BUILDERS:
            raise TownError("Both builders are busy. Wait for one to finish.")
        _pay(wallet, *_price(btype, 1))
        if instant:
            return self._new(btype, 1, x, y, now)
        b = self._new(btype, 0, x, y, now)
        b.target, b.ready_at = 1, now + BUILDINGS[btype]["time"][0]
        return b

    def upgrade(self, bid: int, wallet: dict, now: float) -> Building:
        b = self.get(bid)
        if b.target:
            raise TownError("Already being built.")
        if b.level >= self.max_level(b.type):
            raise TownError("Upgrade your palace first." if b.level < 5 else "Already at the highest level.")
        seconds = BUILDINGS[b.type]["time"][b.level]
        if seconds and self.builders_busy(now) >= BUILDERS:
            raise TownError("Both builders are busy. Wait for one to finish.")
        _pay(wallet, *_price(b.type, b.level + 1))
        if seconds == 0:
            b.level += 1
        else:
            b.target, b.ready_at = b.level + 1, now + seconds
        return b

    def move(self, bid: int, x: int, y: int) -> Building:
        b = self.get(bid)
        if not self.fits(b.type, x, y, ignore=b.id):
            raise TownError("There is no room there.")
        b.x, b.y = x, y
        return b

    def collect(self, bid: int, wallet: dict, now: float) -> int:
        self.advance(now)
        b = self.get(bid)
        resource = BUILDINGS[b.type].get("produces")
        if not resource:
            raise TownError("Nothing to collect here.")
        room = max(0, self.capacity(resource) - wallet[resource])
        amount = int(min(b.stored, room))
        if amount <= 0 and b.stored >= 1:
            raise TownError(
                "Your storehouses are full. Build or upgrade a "
                + ("granary." if resource == "food" else "treasury.")
            )
        b.stored -= amount
        wallet[resource] += amount
        return amount

    def train(self, ttype: str, n: int, wallet: dict, now: float) -> int:
        if ttype not in TROOPS:
            raise TownError("Unknown troop.")
        spec = TROOPS[ttype]
        if self.barracks_level() < spec["barracks"]:
            raise TownError(f"{spec['name']}s need a level {spec['barracks']} barracks.")
        room = self.housing() - self.army_size() - self.queued_size()
        n = max(0, min(int(n), room // spec["housing"]))
        if n == 0:
            raise TownError("Your army camps are full.")
        affordable = int(wallet["food"] // spec["cost"])
        n = min(n, affordable)
        if n == 0:
            raise TownError(f"Not enough grain: a {spec['name'].lower()} costs {spec['cost']}.")
        _pay(wallet, "food", spec["cost"] * n)
        start = max([q["done_at"] for q in self.queue] + [now])
        for i in range(n):
            self.queue.append({"type": ttype, "done_at": start + spec["time"] * (i + 1)})
        return n

    # --- read-out --------------------------------------------------------------

    def to_client(self, wallet: dict, now: float) -> dict:
        return {
            "kingdom": self.kingdom,
            "palace": self.palace_level(),
            "buildings": [b.to_client(now) for b in self.buildings],
            "army": dict(self.army),
            "queue": [
                {"type": q["type"], "ready_in": round(max(q["done_at"] - now, 0), 1)} for q in self.queue
            ],
            "housing": self.housing(),
            "army_size": self.army_size(),
            "queued_size": self.queued_size(),
            "barracks": self.barracks_level(),
            "builders": {"busy": self.builders_busy(now), "total": BUILDERS},
            "gold": int(wallet["gold"]),
            "food": int(wallet["food"]),
            "capacity": {"gold": self.capacity("gold"), "food": self.capacity("food")},
            "limits": {
                t: {"built": self.count(t), "limit": self.limit(t), "max_level": self.max_level(t)}
                for t in BUILDINGS
            },
            "glory": self.glory,
        }


class TownError(ValueError):
    pass


def _price(btype: str, level: int) -> tuple[str, int]:
    resource, costs = BUILDINGS[btype]["cost"]
    return resource, costs[level - 1]


def _pay(wallet: dict, resource: str, amount: float) -> None:
    if wallet[resource] < amount:
        raise TownError(f"Not enough {'gold' if resource == 'gold' else 'grain'}: you need {int(amount):,}.")
    wallet[resource] -= amount


# ----------------------------------------------------------------------------- the architect


def architect(kingdom: int, palace: int, seed: int, starter: bool = False) -> Town:
    """Lay out a town: palace in the middle, storehouses and defenses inside a ring of walls,
    farms, mines, the army and houses outside. Deterministic for a given seed."""
    rng = random.Random(seed)
    town = Town(kingdom)
    c = GRID // 2
    town._new("palace", palace, c - 2, c - 2, 0.0)

    def counts(btype: str) -> int:
        n = BUILDINGS[btype]["limit"][palace - 1]
        if starter:
            # leave room to grow: the first things a new ruler builds are another farm, mine and house
            n = {"farm": n - 1, "mine": n - 1, "house": n - 1, "archer_tower": min(n, palace)}.get(
                btype, min(n, 1)
            )
        return n

    def level(btype: str) -> int:
        top = 5 if btype == "palace" else min(5, palace + 1)
        if starter:
            return max(1, palace - (0 if btype in ("barracks", "camp") else 1))
        return max(1, min(top, palace + rng.choice([-1, 0, 0, 1])))

    def place(btype: str, lo: float, hi: float, outside: tuple | None = None) -> bool:
        size = BUILDINGS[btype]["size"]
        for _ in range(600):
            angle = rng.random() * math.tau
            radius = rng.uniform(lo, hi)
            x = int(round(c + math.cos(angle) * radius - size / 2))
            y = int(round(c + math.sin(angle) * radius - size / 2))
            if outside is not None:
                ox0, oy0, ox1, oy1 = outside  # keep clear of the walled core, with a lane around it
                if not (x + size <= ox0 - 1 or x >= ox1 + 2 or y + size <= oy0 - 1 or y >= oy1 + 2):
                    continue
            if town.fits(btype, x, y) and all(_gap(b, x, y, size) for b in town.buildings):
                town._new(btype, level(btype), x, y, 0.0)
                return True
        return False

    inner = ["treasury", "granary", "archer_tower", "bolt_thrower", "catapult", "temple"]
    for btype in inner:
        for _ in range(counts(btype)):
            place(btype, 4.0, 5.5 + palace)
    # a ring of walls around everything placed so far
    xs = [b.x for b in town.buildings] + [b.x + b.size for b in town.buildings]
    ys = [b.y for b in town.buildings] + [b.y + b.size for b in town.buildings]
    x0, x1, y0, y1 = min(xs) - 2, max(xs) + 1, min(ys) - 2, max(ys) + 1
    ring = [(x, y0) for x in range(x0, x1 + 1)] + [(x, y1) for x in range(x0, x1 + 1)]
    ring += [(x0, y) for y in range(y0 + 1, y1)] + [(x1, y) for y in range(y0 + 1, y1)]
    walls = counts("wall") if not starter else len(ring)
    wall_level = max(1, min(5, palace + (0 if not starter else -1)))
    for x, y in ring[: max(walls, 0)]:
        if town.fits("wall", x, y):
            town._new("wall", wall_level, x, y, 0.0)
    outer_lo = max(x1 - c, y1 - c, c - x0, c - y0) + 2.0
    for btype in ["barracks", "camp", "farm", "mine", "house"]:
        for _ in range(counts(btype)):
            place(btype, outer_lo - 3, outer_lo + 8, outside=(x0, y0, x1, y1))
    return town


def _gap(b: Building, x: int, y: int, size: int) -> bool:
    """Keep one free tile between buildings (walls excepted) so troops and villagers can pass."""
    if b.type == "wall":
        return True
    return x >= b.x + b.size + 1 or b.x >= x + size + 1 or y >= b.y + b.size + 1 or b.y >= y + size + 1


# ----------------------------------------------------------------------------- battles


def battle_layout(town: Town, loot: dict) -> dict:
    """What the attacker sees: every building with its stats, and the loot each holds."""
    holders = {"gold": [], "food": []}
    for b in town.buildings:
        spec = BUILDINGS[b.type]
        for res in ("gold", "food"):
            if b.type == "palace" or spec.get("stores") == res or spec.get("produces") == res:
                weight = 0.15 if b.type == "palace" else 0.2 if spec.get("produces") else 1.0
                holders[res].append((b.id, weight))
    share: dict[int, dict] = {}
    for res, items in holders.items():
        total = sum(w for _, w in items) or 1
        for bid, w in items:
            share.setdefault(bid, {"gold": 0, "food": 0})[res] = int(loot[res] * w / total)
    return {
        "grid": GRID,
        "seconds": BATTLE_SECONDS,
        "palace": town.palace_level(),
        "buildings": [
            {**b.to_client(0.0), "loot": share.get(b.id, {"gold": 0, "food": 0})} for b in town.buildings
        ],
        "loot": {res: sum(s[res] for s in share.values()) for res in ("gold", "food")},
    }


def army_potential(deployed: dict) -> float:
    """The most damage an army could do in one battle, if nothing ever shot back."""
    total = 0.0
    for t, n in deployed.items():
        spec = TROOPS[t]
        total += n * (spec["dps"] * spec.get("bonus", 1.0) * BATTLE_SECONDS + spec.get("blast", 0))
    return total


def check_report(layout: dict, army: dict, report: dict) -> dict:
    """Validate a battle report from the browser. Returns the result the server will apply."""
    deployed = {t: int(n) for t, n in (report.get("deployed") or {}).items() if t in TROOPS and int(n) > 0}
    corrected = []
    for t, n in list(deployed.items()):
        if n > army.get(t, 0):
            deployed[t] = army.get(t, 0)
            corrected.append(f"deployed more {t}s than the army had")
    deployed = {t: n for t, n in deployed.items() if n > 0}
    destruction = float(min(max(float(report.get("destruction", 0)), 0), 100))
    palace_down = bool(report.get("palace_destroyed", False))
    targets = [b for b in layout["buildings"] if b["type"] != "wall"]
    total_hp = sum(b["hp"] for b in targets) or 1
    potential = army_potential(deployed)
    plausible = min(100.0, 100.0 * potential / total_hp)
    if destruction > plausible + 1e-6:
        corrected.append("claimed more destruction than the army could deal")
        destruction = plausible
    if not deployed:
        destruction, palace_down = 0.0, False
    palace = next(b for b in layout["buildings"] if b["type"] == "palace")
    if palace_down and potential < palace["hp"]:
        corrected.append("claimed the palace with too small an army")
        palace_down = False
    loot = {}
    for res in ("gold", "food"):
        claimed = max(0, int((report.get("loot") or {}).get(res, 0)))
        cap = int(layout["loot"][res] * min(1.0, destruction / 100 + 0.35))
        if claimed > cap:
            corrected.append(f"claimed more {res} than was reachable")
        loot[res] = min(claimed, cap)
    stars = int(destruction >= 50) + int(palace_down) + int(destruction >= 99.5)
    return {
        "deployed": deployed,
        "destruction": round(destruction, 1),
        "palace_destroyed": palace_down,
        "stars": stars,
        "loot": loot,
        "corrected": corrected,
    }


def glory_change(stars: int) -> int:
    return {0: -8, 1: 10, 2: 18, 3: 28}[stars]


def defense_power(town: Town) -> float:
    """How much a town's towers and walls add when an AI army raids it."""
    power = 0.0
    for b in town.buildings:
        if not b.level:
            continue
        s = stats(b.type, b.level)
        if "defense" in s:
            power += s["defense"]["damage"] / s["defense"]["interval"]
        elif b.type == "wall":
            power += s["hp"] / 400
    return power


def now() -> float:
    return time.time()
