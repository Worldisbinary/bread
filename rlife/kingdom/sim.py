"""KingdomSim: the economy, the town square, the judge and LiveOps in one seasonal loop.

Each season:
  1. LiveOps queue: actions approved in the admin console (or by the steward) are applied
  2. scenario shocks (e.g. a drought) hit, and the royal herald announces them
  3. the economy steps every citizen forward
  4. a seeded sample of citizens speaks in the town square (LLM)
  5. the judge scores new speech; censorship applies if the laws forbid criticism
  6. forum karma feeds each speaker's standing
  7. every few seasons the Royal Steward proposes a LiveOps action
  8. citizens, metrics and the LiveOps log are saved for the public site and the admin console
"""

import json
import random
from dataclasses import asdict, dataclass, field

from .. import metrics as forum_metrics
from ..ideology import Judge
from ..personas import BASE_RULES, FIRST_NAMES
from ..world import World
from .economy import PROFESSIONS, PROVINCES, SECTOR, Economy
from .events import ACTIONS, LiveOps
from .laws import LAW_SETS
from .metrics import snapshot
from .steward import Steward
from .voices import COMMUNITIES, Voices, board, is_criticism, laws_text

SURNAMES = [
    "Ashford",
    "Brightwater",
    "Coldbrook",
    "Dunmore",
    "Elmstead",
    "Fairholt",
    "Greywind",
    "Hollowell",
    "Ironwood",
    "Kestrel",
    "Larkspur",
    "Merrow",
    "Northcott",
    "Oakhurst",
    "Pennick",
    "Ravensworth",
    "Stonebridge",
    "Thornfield",
    "Underhill",
    "Westbrook",
]
CENSOR_PENALTY = 3.0
KARMA_TO_STANDING = 0.5

SCHEMA = """
CREATE TABLE IF NOT EXISTS citizens (
    agent_id INTEGER PRIMARY KEY, idx INTEGER NOT NULL, profession TEXT, sector TEXT, province TEXT,
    age INTEGER,
    wealth REAL, happiness REAL, standing REAL, hungry INTEGER, present INTEGER
);
CREATE TABLE IF NOT EXISTS liveops_queue (
    id INTEGER PRIMARY KEY, tick INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    args TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '', expected TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, result TEXT
);
"""


@dataclass
class KingdomConfig:
    arm: str = "kingdom"
    citizens: int = 1500
    ticks: int = 12
    laws: str = "liberal"
    seed: int = 7
    voices_per_tick: int = 10
    steward: str = "off"  # off | auto | propose
    steward_every: int = 2
    shocks: dict = field(default_factory=lambda: {"4": "drought"})
    agent_model: str = "openai/gpt-oss-20b"
    judge_model: str = "openai/gpt-oss-120b"
    steward_model: str = "openai/gpt-oss-120b"
    max_agent_requests: int | None = None


def make_names(n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return [f"{rng.choice(FIRST_NAMES)} {rng.choice(SURNAMES)}" for _ in range(n)]


class KingdomSim:
    def __init__(self, world: World, llm, embedder, config: KingdomConfig, log=print) -> None:
        self.world, self.llm, self.config, self.log = world, llm, config, log
        world.db.executescript(SCHEMA)
        self.econ = Economy(config.citizens, LAW_SETS[config.laws], seed=config.seed)
        self.ops = LiveOps(self.econ)
        self.rng = random.Random(config.seed)
        world.set_meta("mode", "kingdom")
        world.set_meta("config", asdict(config))
        if not world.agents(kind=None):
            self._setup()
        self.citizen_of = {}  # agent id -> economy index
        self.agent_of = {}  # economy index -> agent id
        for row in world.db.execute("SELECT id, persona FROM agents WHERE kind = 'member'"):
            idx = json.loads(row["persona"])["idx"]
            self.citizen_of[row["id"]] = idx
            self.agent_of[idx] = row["id"]
        self.herald = world.agents(kind="news")[0]["id"]
        self.voices = Voices(
            world,
            llm,
            embedder,
            model=config.agent_model,
            ranking="hot",
            seed=config.seed,
            econ=self.econ,
            citizen_of=self.citizen_of,
        )
        self.judge = Judge(llm, config.judge_model, embedder)
        self.steward = Steward(llm, config.steward_model) if config.steward != "off" else None
        self.history: list[dict] = []
        self.agent_requests = 0

    # --- setup ---------------------------------------------------------------

    def _setup(self) -> None:
        w = self.world
        for province in PROVINCES:
            w.add_community(board(province), "province", f"Life in {province}.", BASE_RULES, region=province)
        for name, description in COMMUNITIES.items():
            w.add_community(name, "kingdom", description, BASE_RULES)
        names = make_names(self.config.citizens, self.config.seed)
        rows = []
        for i, name in enumerate(names):
            handle = f"{name.split()[0].lower()}_{name.split()[1].lower()}_{i}"
            persona = {"name": name, "idx": i, "province": PROVINCES[self.econ.province[i]]}
            rows.append((handle, "member", json.dumps(persona), board(persona["province"]), "[]"))
        w.db.executemany(
            "INSERT INTO agents (handle, kind, persona, home, subscriptions) VALUES (?,?,?,?,?)", rows
        )
        w.db.commit()
        w.add_agent("royal_herald", {"name": "The Royal Herald"}, None, [], kind="news")
        w.post(
            w.agents(kind="news")[0]["id"],
            "r/royalcourt",
            "The crown proclaims the laws of the realm",
            f"By royal decree: {laws_text(self.econ)}.",
            0,
        )

    # --- LiveOps -------------------------------------------------------------

    def _announce(self, title: str, body: str, tick: int) -> None:
        self.world.post(self.herald, "r/royalcourt", title, body, tick)

    def _process_queue(self, tick: int) -> list[str]:
        applied = []
        rows = self.world.db.execute(
            "SELECT * FROM liveops_queue WHERE status = 'approved' ORDER BY id"
        ).fetchall()
        for row in rows:
            decision = self.ops.apply(
                row["action"], json.loads(row["args"]), actor=row["actor"], rationale=row["rationale"]
            )
            status = "applied" if decision.accepted else "rejected"
            self.world.db.execute(
                "UPDATE liveops_queue SET status = ?, result = ? WHERE id = ?",
                (status, decision.reason, row["id"]),
            )
            self.world.log(
                tick,
                "liveops",
                None,
                action=row["action"],
                actor=row["actor"],
                status=status,
                reason=decision.reason,
                args=json.loads(row["args"]),
            )
            if decision.accepted and row["action"] != "none":
                applied.append(row["action"])
                desc = ACTIONS[row["action"]]["description"]
                self._announce(
                    f"Royal decree: {row['action'].replace('_', ' ')}", f"{desc} {row['args']}", tick
                )
        self.world.db.commit()
        return applied

    def queue(
        self,
        tick: int,
        actor: str,
        action: str,
        args: dict,
        rationale: str = "",
        expected: str = "",
        status: str = "approved",
    ) -> None:
        self.world.db.execute(
            "INSERT INTO liveops_queue (tick, actor, action, args, rationale, expected, status) "
            "VALUES (?,?,?,?,?,?,?)",
            (tick, actor, action, json.dumps(args), rationale, expected, status),
        )
        self.world.db.commit()

    def _steward_turn(self, tick: int) -> None:
        proposal = self.steward.propose(self.history, self.ops.log)
        status = "approved" if self.config.steward == "auto" else "proposed"
        self.queue(
            tick,
            "steward",
            proposal["action"],
            proposal["args"],
            proposal["rationale"],
            proposal["expected_effect"],
            status,
        )
        self.world.log(tick, "steward_proposal", None, **proposal, status=status)

    # --- the season loop ------------------------------------------------------

    def run(self) -> dict:
        cfg = self.config
        start = self.world.meta("next_tick", 0)
        for tick in range(start, cfg.ticks):
            events = self._process_queue(tick)
            shock = cfg.shocks.get(str(tick))
            if shock:
                self.ops.shock(shock)
                events.append(shock)
                self._announce(
                    f"News from the provinces: {shock.replace('_', ' ')}",
                    "Reports reach the court that the season's harvest is affected.",
                    tick,
                )
            before_laws = self.econ.laws
            self.econ.step()
            snap = snapshot(self.econ)
            if self.econ.laws != before_laws:
                self._announce("The crown revises the laws", laws_text(self.econ), tick)
            self.voices.events_text = ", ".join(e.replace("_", " ") for e in events)
            self._speak(tick)
            self._judge_and_censor(tick)
            self._karma_to_standing(tick)
            snap["forum"] = forum_metrics.summary(self.world, upto_tick=tick)
            snap["events"] = events
            self.history.append(snap)
            if self.steward and tick >= 1 and tick % cfg.steward_every == 0:
                self._steward_turn(tick)
            self._save(tick, snap)
            self.log(
                f"[{cfg.arm}] season {tick}: pop {snap['population']} retention {snap['retention']:.2f} "
                f"happiness {snap['happiness']:.2f} unrest {snap['unrest']:.2f} "
                f"gini {snap['wealth_gini']:.2f} "
                f"treasury {snap['treasury']:.0f} events {events}"
            )
            if cfg.max_agent_requests is not None and self.agent_requests >= cfg.max_agent_requests:
                self.log(f"[{cfg.arm}] request budget reached; stopping cleanly")
                break
        result = {
            "arm": cfg.arm,
            "seasons": len(self.history),
            "final": {k: v for k, v in self.history[-1].items() if k not in ("forum", "laws", "jobs")},
            "agent_requests": self.agent_requests,
            "liveops_actions": len(self.ops.log),
        }
        self.world.set_meta("result", result)
        return result

    def _speak(self, tick: int) -> None:
        present = [i for i in range(len(self.econ.present)) if self.econ.present[i] and i in self.agent_of]
        k = min(self.config.voices_per_tick, len(present))
        for idx in self.rng.sample(present, k):
            if (
                self.config.max_agent_requests is not None
                and self.agent_requests >= self.config.max_agent_requests
            ):
                return
            self.voices.step(self.world.agent(self.agent_of[idx]), tick)
            self.agent_requests += 1

    def _judge_and_censor(self, tick: int) -> None:
        scored = self.judge.score(self.world.unscored())
        for item_id, score in scored.items():
            self.world.save_score(item_id, score, self.judge.model)
        if self.econ.laws.free_speech:
            return
        for item in self.world.items_since(tick):
            if item.removed or item.author_id not in self.citizen_of:
                continue
            if is_criticism(f"{item.title or ''} {item.body}"):
                self.world.remove(item.id, "censored: criticism of the crown")
                self.econ.standing[self.citizen_of[item.author_id]] -= CENSOR_PENALTY
                self.world.log(tick, "censored", item.author_id, item=item.id)

    def _karma_to_standing(self, tick: int) -> None:
        rows = self.world.db.execute(
            "SELECT i.author_id AS author, SUM(v.value) AS k FROM votes v JOIN items i ON i.id = v.item_id "
            "WHERE v.tick = ? GROUP BY i.author_id",
            (tick,),
        )
        for row in rows:
            idx = self.citizen_of.get(row["author"])
            if idx is not None:
                self.econ.standing[idx] += KARMA_TO_STANDING * row["k"]

    def _save(self, tick: int, snap: dict) -> None:
        econ = self.econ
        rows = []
        for idx, agent_id in self.agent_of.items():
            prof = PROFESSIONS[econ.profession[idx]]
            rows.append(
                (
                    agent_id,
                    idx,
                    prof,
                    SECTOR[prof],
                    PROVINCES[econ.province[idx]],
                    int(econ.age[idx]),
                    float(econ.wealth[idx]),
                    float(econ.happiness[idx]),
                    float(econ.standing[idx]),
                    int(econ.hunger[idx]),
                    int(econ.present[idx]),
                )
            )
        self.world.db.executemany("INSERT OR REPLACE INTO citizens VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.world.db.commit()
        self.world.save_snapshot(tick, json.loads(json.dumps(snap, default=float)))
        self.world.set_meta("liveops_log", self.ops.log[-50:])
        self.world.set_meta("next_tick", tick + 1)
