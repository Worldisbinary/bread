"""Seeded persona generation and the community layout.

Personas describe life circumstances (city, age, work, income, family, interests,
temperament), never political ideology. Nobody is told to be liberal, communist
or fascist; whatever positions appear are emergent, which is what makes measuring
them meaningful. The same seed always produces the same society.
"""

import json
import random
from importlib import resources

REGIONS = json.loads(resources.files("rlife").joinpath("data/regions.json").read_text())
REGIONS.pop("_note")

TOPIC_COMMUNITIES = {
    "r/life": "Everyday life, work, relationships and whatever is on your mind.",
    "r/economy": "Jobs, prices, taxes, markets and the economy.",
    "r/policy": "Laws, government decisions and public policy.",
    "r/technology": "Tech, AI, startups and the internet.",
    "r/worldnews": "News from outside India.",
}

BASE_RULES = [
    "Be civil: attack ideas, not people.",
    "No hate speech or slurs against any group.",
    "No calls for violence.",
    "No spam or vote manipulation.",
]

FIRST_NAMES = [
    "Aarav",
    "Ishita",
    "Kabir",
    "Meera",
    "Rohan",
    "Ananya",
    "Vikram",
    "Priya",
    "Arjun",
    "Sneha",
    "Farhan",
    "Lakshmi",
    "Siddharth",
    "Nandini",
    "Rahul",
    "Divya",
    "Imran",
    "Kavya",
    "Aditya",
    "Pooja",
    "Joseph",
    "Swati",
    "Manish",
    "Deepa",
    "Gaurav",
    "Ritu",
    "Harpreet",
    "Anjali",
    "Suresh",
    "Neha",
    "Tenzin",
    "Zoya",
]
PROFESSIONS = [
    "software engineer",
    "schoolteacher",
    "auto-rickshaw driver",
    "small shop owner",
    "nurse",
    "civil servant",
    "college student",
    "delivery rider",
    "bank clerk",
    "startup founder",
    "retired army officer",
    "journalist",
    "factory supervisor",
    "doctor",
    "farmer who moved to the city",
    "chartered accountant",
    "homemaker",
    "graphic designer",
    "lawyer",
    "real estate broker",
    "call centre agent",
    "university professor",
]
INCOME = ["struggling to make ends meet", "lower middle class", "comfortably middle class", "well off"]
FAMILY = [
    "single and living alone",
    "living with parents",
    "married with young children",
    "married, children grown up",
    "sharing a flat with friends",
    "single parent",
]
INTERESTS = [
    "cricket",
    "cooking",
    "films",
    "personal finance",
    "gaming",
    "history",
    "music",
    "fitness",
    "travel",
    "books",
    "local food",
    "startups",
    "photography",
    "spirituality",
    "football",
    "gardening",
]
TEMPERAMENT = [
    "calm and thoughtful",
    "sarcastic",
    "earnest and idealistic",
    "practical and blunt",
    "curious, asks lots of questions",
    "easily irritated",
    "funny, likes to joke",
    "cautious",
]


def setup_communities(world) -> None:
    for city, info in REGIONS.items():
        world.add_community(info["community"], "regional", f"Life in {city}.", BASE_RULES, region=city)
    for name, description in TOPIC_COMMUNITIES.items():
        world.add_community(name, "topic", description, BASE_RULES)


def make_personas(n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    cities = list(REGIONS)
    names = rng.sample(FIRST_NAMES, k=min(n, len(FIRST_NAMES)))
    while len(names) < n:
        names.append(f"{rng.choice(FIRST_NAMES)}{len(names)}")
    personas = []
    for i in range(n):
        city = cities[i % len(cities)]  # balanced regions
        personas.append(
            {
                "name": names[i],
                "handle": f"{names[i].lower()}_{rng.randint(10, 99)}",
                "city": city,
                "age": rng.randint(19, 68),
                "profession": rng.choice(PROFESSIONS),
                "income": rng.choice(INCOME),
                "family": rng.choice(FAMILY),
                "interests": rng.sample(INTERESTS, k=3),
                "temperament": rng.choice(TEMPERAMENT),
            }
        )
    return personas


def populate(world, n_agents: int, seed: int) -> None:
    rng = random.Random(seed + 1)
    setup_communities(world)
    for persona in make_personas(n_agents, seed):
        home = REGIONS[persona["city"]]["community"]
        topics = ["r/life"] + rng.sample([t for t in TOPIC_COMMUNITIES if t != "r/life"], k=3)
        world.add_agent(persona["handle"], persona, home, [home, *topics])
    world.add_agent("simulated_news", {"name": "Simulated News"}, None, [], kind="news")
