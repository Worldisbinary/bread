"""Law sets: the rules a kingdom is run under.

Each law set is a small, explicit parameter bundle. The names (liberal, authoritarian,
socialist) are shorthand for the bundle, not claims about any real country. LiveOps
can change individual parameters at runtime within guardrail limits (see events.py).
"""

from dataclasses import asdict, dataclass, replace


@dataclass(frozen=True)
class Laws:
    name: str
    income_tax: float  # share of income taken by the crown
    free_speech: bool  # if False, critical town-square posts can be punished
    guild_restrictions: float  # 0..1, how hard it is to enter private trades
    policing: float  # 0..1, chance a theft is caught
    conscription: float  # share of young citizens drafted as soldiers
    grain_subsidy: float  # crown pays this share of the grain price for the poor
    public_jobs_share: float  # target share of citizens employed by the crown
    punishment: float  # standing lost when caught stealing

    def to_dict(self) -> dict:
        return asdict(self)

    def with_changes(self, **changes) -> "Laws":
        return replace(self, **changes)


LAW_SETS = {
    "liberal": Laws(
        "liberal",
        income_tax=0.12,
        free_speech=True,
        guild_restrictions=0.05,
        policing=0.35,
        conscription=0.0,
        grain_subsidy=0.05,
        public_jobs_share=0.12,
        punishment=4.0,
    ),
    "authoritarian": Laws(
        "authoritarian",
        income_tax=0.30,
        free_speech=False,
        guild_restrictions=0.6,
        policing=0.75,
        conscription=0.08,
        grain_subsidy=0.1,
        public_jobs_share=0.25,
        punishment=12.0,
    ),
    "socialist": Laws(
        "socialist",
        income_tax=0.38,
        free_speech=True,
        guild_restrictions=0.3,
        policing=0.5,
        conscription=0.0,
        grain_subsidy=0.45,
        public_jobs_share=0.40,
        punishment=6.0,
    ),
}

# Guardrails for runtime changes by LiveOps (human or agent): max change per action.
CHANGE_LIMITS = {"income_tax": 0.05, "grain_subsidy": 0.10, "policing": 0.15, "guild_restrictions": 0.15}
BOUNDS = {
    "income_tax": (0.0, 0.6),
    "grain_subsidy": (0.0, 0.8),
    "policing": (0.0, 1.0),
    "guild_restrictions": (0.0, 1.0),
}
