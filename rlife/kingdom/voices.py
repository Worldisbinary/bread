"""Citizen voices in the Town Square.

1,500 citizens live in the simulated economy, but to keep Groq/LLM quotas affordable,
only a representative sub-sample of citizens speak in the Town Square forum each season.

Every speaking citizen generates a post reacting to their exact real situation:
- current job, province, standing
- wealth, income, whether they went hungry or stole last season
- current grain and goods prices
- crown decrees, tax rate, and recent events (festivals, droughts)
"""

import json
from dataclasses import dataclass
from typing import Any, List, Optional

import numpy as np

from .economy import Economy, PROFESSIONS, PROVINCES


SYSTEM_TOWN_SQUARE = """You are a citizen in a historical-fantasy kingdom simulation.
Your name is {name}, living in the province of {province}.
You work as a {profession} (Skill: {skill:.2f}).
Personal economic state:
- Wealth: {wealth:.1f} coins | Last season income: {income:.1f} coins
- Hunger state: {hunger_desc}
- Social standing (karma): {standing:+.1f}
Kingdom context:
- Reign laws: {law_name} (Income tax: {tax:.0%}, Policing: {policing:.0%}, Grain subsidy: {subsidy:.0%})
- Grain price: {grain_price:.2f} coins | Goods price: {goods_price:.2f} coins
- Recent crown decrees or events: {recent_events}

Express yourself authentically in the Town Square forum regarding your real life, hunger, wages, local market prices, or the crown's decrees.
Keep it between 15 and 45 words. Be emotional, opinionated, grateful, or angry depending on how hard or easy your life currently is.
Never mention you are an AI. Respond with valid JSON:
{{"thought": "<one private sentence about your secret feelings>", "statement": "<what you announce in the town square>", "topic": "<economy|governance|crime|faith|daily_life>"}}
"""

VOICE_NAMES = [
    "Alden", "Bartholomew", "Cedric", "Doran", "Elric", "Faelan", "Godric", "Harlan",
    "Isolde", "Jocelyn", "Kaelen", "Leofric", "Marek", "Nesta", "Osric", "Perrin",
    "Quinn", "Rowan", "Silas", "Theron", "Ulric", "Vesper", "Wystan", "Yorick",
    "Althea", "Briony", "Cora", "Daphne", "Elysia", "Gisela", "Helena", "Linnea"
]


@dataclass
class CitizenVoice:
    citizen_id: int
    name: str
    province: str
    profession: str
    tick: int
    thought: str
    statement: str
    topic: str
    wealth: float
    income: float
    hunger: int
    standing: float


class TownSquare:
    """Manages citizen sampling and LLM-driven public discourse in the kingdom."""

    def __init__(self, econ: Economy, llm=None, sample_size: int = 5) -> None:
        self.econ = econ
        self.llm = llm
        self.sample_size = sample_size
        self.history: List[CitizenVoice] = []

    def sample_speakers(self) -> np.ndarray:
        """Select a representative sample of living, present citizens."""
        present_indices = np.where(self.econ.present)[0]
        if len(present_indices) == 0:
            return np.array([], dtype=int)
        
        # Mix stratified sample: some hungry/poor, some wealthy, some public servants
        size = min(self.sample_size, len(present_indices))
        return self.econ.rng.choice(present_indices, size=size, replace=False)

    def generate_statement_prompt(self, citizen_id: int, recent_events_str: str) -> str:
        prof = PROFESSIONS[self.econ.profession[citizen_id]]
        prov = PROVINCES[self.econ.province[citizen_id]]
        wealth = float(self.econ.wealth[citizen_id])
        income = float(self.econ.last_income[citizen_id])
        hunger = int(self.econ.hunger[citizen_id])
        standing = float(self.econ.standing[citizen_id])
        skill = float(self.econ.skill[citizen_id])

        if hunger == 0:
            hunger_desc = "Well-fed and healthy."
        elif hunger == 1:
            hunger_desc = "Hungry; could not afford enough grain."
        else:
            hunger_desc = f"Starving ({hunger} seasons without adequate grain)."

        name = VOICE_NAMES[citizen_id % len(VOICE_NAMES)] + f" of {prov}"

        return SYSTEM_TOWN_SQUARE.format(
            name=name,
            province=prov,
            profession=prof,
            skill=skill,
            wealth=wealth,
            income=income,
            hunger_desc=hunger_desc,
            standing=standing,
            law_name=self.econ.laws.name,
            tax=self.econ.laws.income_tax,
            policing=self.econ.laws.policing,
            subsidy=self.econ.laws.grain_subsidy,
            grain_price=self.econ.grain_price,
            goods_price=self.econ.goods_price,
            recent_events=recent_events_str or "No sudden decrees."
        )

    def step(self, recent_events_str: str = "") -> List[CitizenVoice]:
        """Runs the Town Square round for the current season."""
        speakers = self.sample_speakers()
        voices = []

        for cid in speakers:
            prof = PROFESSIONS[self.econ.profession[cid]]
            prov = PROVINCES[self.econ.province[cid]]
            name = f"{VOICE_NAMES[cid % len(VOICE_NAMES)]} of {prov}"
            wealth = float(self.econ.wealth[cid])
            income = float(self.econ.last_income[cid])
            hunger = int(self.econ.hunger[cid])
            standing = float(self.econ.standing[cid])

            prompt = self.generate_statement_prompt(cid, recent_events_str)

            if self.llm is not None:
                try:
                    res = self.llm.chat([
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": "Speak in the town square."}
                    ])
                    # Parse JSON or fallback
                    parsed = json.loads(res.strip("` \n").removeprefix("json"))
                    thought = parsed.get("thought", "...")
                    statement = parsed.get("statement", "Grain is dear this year.")
                    topic = parsed.get("topic", "economy")
                except Exception:
                    thought, statement, topic = self._heuristic_fallback(cid, hunger, income, wealth)
            else:
                thought, statement, topic = self._heuristic_fallback(cid, hunger, income, wealth)

            voice = CitizenVoice(
                citizen_id=int(cid),
                name=name,
                province=prov,
                profession=prof,
                tick=self.econ.tick_no,
                thought=thought,
                statement=statement,
                topic=topic,
                wealth=wealth,
                income=income,
                hunger=hunger,
                standing=standing,
            )
            voices.append(voice)
            self.history.append(voice)

        return voices

    def _heuristic_fallback(self, cid: int, hunger: int, income: float, wealth: float):
        prof = PROFESSIONS[self.econ.profession[cid]]
        if hunger > 0:
            return (
                "My belly aches and the granaries look bare.",
                f"Grain is at {self.econ.grain_price:.1f} coins! A working {prof} cannot feed their family while taxes stay at {self.econ.laws.income_tax:.0%}!",
                "economy"
            )
        elif self.econ.happiness[cid] > 0.75:
            return (
                "The season treats me well.",
                f"Praise the Realm! As a {prof}, business thrives and the peace holds across our province.",
                "daily_life"
            )
        elif self.econ.laws.policing > 0.7:
            return (
                "Guards watch every alleyway.",
                "The watch patrols every corner day and night. Lawful citizens rest easy, but whispers carry a price.",
                "governance"
            )
        else:
            return (
                "Another hard season.",
                f"Taxes take {self.econ.laws.income_tax:.0%} of our coin, yet the roads remain in disrepair.",
                "governance"
            )
