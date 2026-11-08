"""The kingdom economy: every citizen, every season, in vectorised numpy.

One tick is one season. In order:
  1. production   farmers grow grain (weather matters), artisans make goods
  2. prices       grain price follows demand over supply; goods price follows prosperity
  3. incomes      private and farm incomes come from markets, public wages from the treasury
  4. taxes        the crown collects income tax; it pays public wages, subsidies and events
  5. food         everyone needs one unit of grain; the poor get the subsidy; the rest go hungry
  6. crime        hungry, poor citizens may steal; policing decides who is caught
  7. mood         happiness follows food, income, taxes, freedom and events
  8. careers      some citizens move to better-paying work, within guild and public-job rules
  9. migration    the unhappy emigrate (churn); a prosperous, happy kingdom attracts newcomers
 10. standing     lawful work raises standing (karma); crime lowers it

Every rule is a few lines with named constants, so a reviewer can trace any metric to
the behaviour that produced it. Randomness flows from one seeded generator.
"""

from dataclasses import dataclass, field

import numpy as np

from .laws import Laws

PROFESSIONS = ["farmer", "labourer", "artisan", "merchant", "clerk", "soldier", "civil_servant", "teacher"]
SECTOR = {
    "farmer": "agriculture",
    "labourer": "agriculture",
    "artisan": "private",
    "merchant": "private",
    "clerk": "private",
    "soldier": "public",
    "civil_servant": "public",
    "teacher": "public",
}
P = {name: i for i, name in enumerate(PROFESSIONS)}
PUBLIC = np.array([SECTOR[p] == "public" for p in PROFESSIONS])
GUILD_TRADES = np.array([p in ("artisan", "merchant") for p in PROFESSIONS])
INITIAL_MIX = [0.38, 0.14, 0.12, 0.07, 0.09, 0.07, 0.07, 0.06]

PROVINCES = ["Northmarch", "Rivermead", "Highvale", "Saltcoast", "Emberfell", "Greenhollow"]

BASE_YIELD = 3.2  # grain units per farmer season at skill 1
LABOURER_YIELD = 1.4
GOODS_PER_ARTISAN = 2.0
BASE_GRAIN_PRICE = 1.0
BASE_GOODS_PRICE = 1.6
PUBLIC_WAGE = 2.2
MERCHANT_MARGIN = 0.12  # share of market turnover captured by merchants
TRAVEL_COST = 0.5  # wealth an emigrant needs to leave


@dataclass
class Shocks:
    """Temporary modifiers set by events; each decays back to neutral."""

    weather: float = 1.0
    goods_demand: float = 1.0
    festival: float = 0.0
    remaining: dict = field(default_factory=dict)  # name -> ticks left

    def tick(self) -> None:
        for name in list(self.remaining):
            self.remaining[name] -= 1
            if self.remaining[name] <= 0:
                del self.remaining[name]
                setattr(self, name, 0.0 if name == "festival" else 1.0)


class Economy:
    def __init__(self, n: int, laws: Laws, seed: int = 0, treasury_per_citizen: float = 3.0) -> None:
        self.rng = np.random.default_rng(seed)
        self.laws = laws
        self.shocks = Shocks()
        self.tick_no = 0
        self.n_initial = n
        self.profession = self.rng.choice(len(PROFESSIONS), size=n, p=INITIAL_MIX)
        self.province = self.rng.integers(0, len(PROVINCES), size=n)
        self.skill = np.clip(self.rng.beta(4, 3, size=n), 0.15, 1.0)
        self.age = self.rng.integers(18, 70, size=n)
        self.wealth = self.rng.lognormal(mean=1.2, sigma=0.7, size=n)
        self.happiness = np.clip(self.rng.normal(0.6, 0.08, size=n), 0.0, 1.0)
        self.order_pref = self.rng.beta(2, 2, size=n)  # how much a citizen values order over liberty
        self.standing = np.zeros(n)
        self.hunger = np.zeros(n, dtype=int)
        self.present = np.ones(n, dtype=bool)
        self.original = np.ones(n, dtype=bool)  # cohort for retention
        self.last_income = np.zeros(n)
        self.treasury = treasury_per_citizen * n
        self.granary = 0.2 * n
        self.grain_price = BASE_GRAIN_PRICE
        self.goods_price = BASE_GOODS_PRICE
        self.last = {}

    # --- helpers -------------------------------------------------------------

    @property
    def alive(self) -> np.ndarray:
        return self.present

    def _is(self, *names: str) -> np.ndarray:
        mask = np.zeros(len(self.profession), dtype=bool)
        for name in names:
            mask |= self.profession == P[name]
        return mask & self.present

    def _grow(self, k: int) -> None:
        """Add k newcomers (immigrants), mostly into farm and labour work."""
        if k <= 0:
            return
        mix = np.array([0.35, 0.3, 0.1, 0.05, 0.1, 0.0, 0.05, 0.05])
        self.profession = np.concatenate(
            [self.profession, self.rng.choice(len(PROFESSIONS), size=k, p=mix / mix.sum())]
        )
        self.province = np.concatenate([self.province, self.rng.integers(0, len(PROVINCES), size=k)])
        self.skill = np.concatenate([self.skill, np.clip(self.rng.beta(3, 3, size=k), 0.15, 1.0)])
        self.age = np.concatenate([self.age, self.rng.integers(18, 45, size=k)])
        self.wealth = np.concatenate([self.wealth, self.rng.lognormal(0.6, 0.6, size=k)])
        self.happiness = np.concatenate([self.happiness, np.full(k, 0.6)])
        self.order_pref = np.concatenate([self.order_pref, self.rng.beta(2, 2, size=k)])
        self.standing = np.concatenate([self.standing, np.zeros(k)])
        self.hunger = np.concatenate([self.hunger, np.zeros(k, dtype=int)])
        self.present = np.concatenate([self.present, np.ones(k, dtype=bool)])
        self.original = np.concatenate([self.original, np.zeros(k, dtype=bool)])
        self.last_income = np.concatenate([self.last_income, np.zeros(k)])

    # --- one season ----------------------------------------------------------

    def step(self) -> dict:
        laws, rng, here = self.laws, self.rng, self.present
        pop = int(here.sum())
        farmers, labourers = self._is("farmer"), self._is("labourer")
        artisans, merchants, clerks = self._is("artisan"), self._is("merchant"), self._is("clerk")
        public = here & PUBLIC[self.profession]

        # 1-2. production and prices
        grain = (BASE_YIELD * self.skill * farmers).sum() + (LABOURER_YIELD * self.skill * labourers).sum()
        grain *= self.shocks.weather
        supply = grain + self.granary
        self.grain_price = float(np.clip(BASE_GRAIN_PRICE * (pop / max(supply, 1.0)) ** 1.5, 0.3, 6.0))
        prosperity = float(np.mean(self.wealth[here])) / 4.0
        self.goods_price = float(
            np.clip(BASE_GOODS_PRICE * prosperity**0.5 * self.shocks.goods_demand, 0.5, 6.0)
        )
        goods = (GOODS_PER_ARTISAN * self.skill * artisans).sum()

        # 3. incomes
        income = np.zeros(len(self.profession))
        income[farmers] = BASE_YIELD * self.skill[farmers] * self.shocks.weather * self.grain_price * 0.75
        income[labourers] = (
            LABOURER_YIELD * self.skill[labourers] * self.shocks.weather * self.grain_price * 0.9
        )
        income[artisans] = GOODS_PER_ARTISAN * self.skill[artisans] * self.goods_price
        turnover = grain * self.grain_price + goods * self.goods_price
        if merchants.any():
            share = self.skill[merchants] / self.skill[merchants].sum()
            income[merchants] = MERCHANT_MARGIN * turnover * share
        private_mean = float(np.mean(income[artisans | merchants])) if (artisans | merchants).any() else 2.0
        income[clerks] = 0.8 * private_mean * (0.6 + 0.6 * self.skill[clerks])
        wage_bill = PUBLIC_WAGE * public.sum()
        pay_ratio = min(1.0, self.treasury / wage_bill) if wage_bill else 1.0
        income[public] = PUBLIC_WAGE * pay_ratio * (0.8 + 0.4 * self.skill[public])
        self.treasury -= wage_bill * pay_ratio

        # 4. taxes
        tax = laws.income_tax * income
        self.treasury += float(tax.sum())
        net = income - tax
        self.wealth += net

        # 5. food
        cost = np.full(len(self.profession), self.grain_price)
        poor = here & (self.wealth < 2 * self.grain_price)
        subsidy = np.where(poor, laws.grain_subsidy * self.grain_price, 0.0)
        subsidy_bill = float(subsidy.sum())
        if subsidy_bill > self.treasury:  # the crown can only pay what it has
            subsidy *= max(self.treasury, 0.0) / subsidy_bill
            subsidy_bill = float(subsidy.sum())
        self.treasury -= subsidy_bill
        cost -= subsidy
        can_eat = here & (self.wealth >= cost)
        hungry = here & ~can_eat
        self.wealth[can_eat] -= cost[can_eat]
        self.wealth[hungry] = 0.0
        self.hunger[can_eat] = 0
        self.hunger[hungry] += 1
        self.granary = max(0.0, supply - can_eat.sum()) * 0.5  # half of any surplus spoils

        # 6. crime
        median_wealth = float(np.median(self.wealth[here]))
        desperation = 1.2 * np.minimum(self.hunger, 3) + 1.5 * (self.wealth < 0.25 * median_wealth) - 3.0
        steal = here & (rng.random(len(self.profession)) < 1 / (1 + np.exp(-desperation))) & (self.hunger > 0)
        stolen = 0.0
        if steal.any():
            victims = rng.choice(
                np.flatnonzero(here & (self.wealth > median_wealth))
                if (here & (self.wealth > median_wealth)).any()
                else np.flatnonzero(here),
                size=steal.sum(),
            )
            take = np.minimum(self.wealth[victims] * 0.1, 2.0)
            np.subtract.at(self.wealth, victims, take)
            self.wealth[steal] += take
            stolen = float(take.sum())
        caught = steal & (rng.random(len(self.profession)) < laws.policing)
        self.standing[caught] -= laws.punishment
        self.wealth[caught] *= 0.5

        # 7. happiness
        growth = np.tanh((net - self.last_income) / 2.0)
        liberty_cost = 0.0 if laws.free_speech else 0.12
        target = (
            0.55
            + 0.15 * growth
            - 0.35 * hungry
            - 0.25 * laws.income_tax
            - liberty_cost * (1 - self.order_pref)
            + 0.05 * self.order_pref * (laws.policing - 0.4)
            - 0.08 * (self.wealth < 0.3 * median_wealth)
            + self.shocks.festival
            - 0.1 * (self.profession == P["soldier"]) * (laws.conscription > 0)
        )
        self.happiness = np.where(here, np.clip(0.75 * self.happiness + 0.25 * target, 0, 1), self.happiness)
        self.last_income = net

        # 8. careers
        mean_by_prof = np.array(
            [
                income[here & (self.profession == i)].mean() if (here & (self.profession == i)).any() else 0.0
                for i in range(len(PROFESSIONS))
            ]
        )
        considering = here & (rng.random(len(self.profession)) < 0.08) & (self.profession != P["soldier"])
        switches = 0
        if considering.any():
            target_job = rng.choice(len(PROFESSIONS), size=considering.sum())
            idx = np.flatnonzero(considering)
            gain = mean_by_prof[target_job] - income[idx]
            ok = gain > 0.25 * np.maximum(income[idx], 0.5)
            blocked = GUILD_TRADES[target_job] & (rng.random(len(idx)) < laws.guild_restrictions)
            public_full = PUBLIC[target_job] & (public.sum() >= laws.public_jobs_share * pop)
            move = ok & ~blocked & ~public_full & (target_job != P["soldier"])
            self.profession[idx[move]] = target_job[move]
            switches = int(move.sum())
        if laws.conscription > 0:  # the crown drafts young citizens until the soldier quota is met
            soldiers_needed = int(laws.conscription * pop) - int(self._is("soldier").sum())
            young = np.flatnonzero(here & (self.age < 30) & (self.profession != P["soldier"]))
            if soldiers_needed > 0 and len(young):
                drafted = rng.choice(young, size=min(soldiers_needed, len(young)), replace=False)
                self.profession[drafted] = P["soldier"]

        # 9. migration
        leaving = (
            here
            & (self.happiness < 0.3)
            & (self.wealth > TRAVEL_COST)
            & (rng.random(len(self.profession)) < 0.35)
        )
        self.wealth[leaving] -= TRAVEL_COST
        self.present[leaving] = False
        mean_h = float(self.happiness[self.present].mean())
        arrivals = int(rng.poisson(max(0.0, mean_h - 0.5) * 0.08 * pop))
        self._grow(arrivals)

        # 10. standing (karma) for lawful work
        n0 = len(caught)  # arrivals were appended after this season's work
        lawful = self.present[:n0] & ~caught
        self.standing[:n0][lawful] += 0.2

        # skills improve where there are teachers
        teacher_ratio = self._is("teacher").sum() / max(self.present.sum(), 1)
        self.skill = np.clip(self.skill + 0.02 * min(teacher_ratio / 0.06, 1.5) * self.present, 0, 1)
        self.age += self.tick_no % 4 == 3

        self.shocks.tick()
        self.tick_no += 1
        self.last = {
            "income": income,
            "hungry": hungry,
            "caught": caught,
            "steal": steal,
            "leaving": leaving,
            "arrivals": arrivals,
            "switches": switches,
            "stolen": stolen,
            "subsidy_bill": subsidy_bill,
            "tax": float(tax.sum()),
            "grain": float(grain),
            "wage_bill": wage_bill * pay_ratio,
            "pay_ratio": pay_ratio,
        }
        return self.last

    # --- read-outs -----------------------------------------------------------

    def citizen(self, i: int) -> dict:
        return {
            "id": i,
            "profession": PROFESSIONS[self.profession[i]],
            "sector": SECTOR[PROFESSIONS[self.profession[i]]],
            "province": PROVINCES[self.province[i]],
            "age": int(self.age[i]),
            "wealth": round(float(self.wealth[i]), 2),
            "happiness": round(float(self.happiness[i]), 3),
            "standing": round(float(self.standing[i]), 1),
            "hungry_seasons": int(self.hunger[i]),
            "present": bool(self.present[i]),
            "last_income": round(float(self.last_income[i]), 2),
        }
