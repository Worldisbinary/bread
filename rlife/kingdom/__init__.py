"""The kingdom: an economy of citizens under laws, run by a LiveOps team.

economy.py     citizens, professions, prices, wages, taxes, hunger, crime, migration (numpy, fast)
laws.py        law sets (liberal, authoritarian, socialist) and their parameters
events.py      LiveOps levers with guardrails (budget, change limits, cooldowns), and world shocks
metrics.py     population, retention, happiness, Gini, unrest, treasury, job mix
voices.py      citizens speaking in the town square, prompted from their actual state
steward.py     the Royal Steward: an LLM LiveOps operator behind the same guardrails
sim.py         the seasonal loop tying economy, voices, judge, censorship and LiveOps together
experiment.py  replicated, seed-paired A/B experiments (laws; steward vs no LiveOps)
"""
