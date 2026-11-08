"""The kingdom: an economy of citizens under laws, run by a LiveOps team.

economy.py    citizens, professions, prices, wages, taxes, hunger, crime, migration (numpy, fast)
laws.py       law sets (liberal, authoritarian, socialist) and their parameters
events.py     LiveOps events: harvest festival, drought, trade fair, grain subsidy, ...
metrics.py    population, retention, happiness, Gini, unrest, treasury, job mix
voices.py     Town square citizen sampling and LLM-driven public discourse
steward.py    Agentic Royal Steward proposing LiveOps interventions with guardrails
experiment.py Seeded A/B experiments comparing Static Governance vs Agentic LiveOps
"""

from .economy import Economy, PROFESSIONS, PROVINCES
from .events import ACTIONS, LiveOps
from .laws import LAW_SETS, Laws
from .metrics import gini, snapshot
from .voices import TownSquare, CitizenVoice
from .steward import RoyalSteward
from .experiment import run_kingdom_ab_experiment

__all__ = [
    "Economy",
    "Laws",
    "LAW_SETS",
    "LiveOps",
    "ACTIONS",
    "gini",
    "snapshot",
    "PROFESSIONS",
    "PROVINCES",
    "TownSquare",
    "CitizenVoice",
    "RoyalSteward",
    "run_kingdom_ab_experiment",
]
