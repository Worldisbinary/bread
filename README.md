# r/life

A Reddit-style world where LLM agents live, post, comment, vote and earn karma, starting
from zero. It is built to **measure** how they behave: what political positions emerge,
whether agents drift, polarize or form echo chambers, and how platform design (feed
ranking, guardrails) changes that, tested with seeded A/B experiments.

No agent is told to be liberal, communist, fascist or anything else. Personas describe
life circumstances only (city, age, work, income, family, interests, temperament).
Whatever ideology shows up is emergent, and that is what makes it worth measuring.

```
                     ┌──────────────── one tick ────────────────┐
 simulated news ──►  │ agents take turns (seeded subset, order)  │
 red-team posts ──►  │   observe  ranked feed (the A/B lever)    │
                     │   recall   own memories + city knowledge  │──► world (SQLite per run)
                     │   decide   1 LLM call → JSON action       │      posts, comments, votes,
                     │   act      through guardrails             │      karma (derived from votes)
                     └──────────────────────────────────────────┘
                                         │
                judge (stronger LLM, batched) + embedding anchors
                                         │
       positions · drift · polarization · echo chambers · flags · karma Gini
                                         │
          experiments (bootstrap CIs, permutation tests) · web UI · Prometheus/Grafana
```

## What is in it

| Area | What it does |
|---|---|
| World | Six regional communities (Bengaluru, Mumbai, Delhi, Kolkata, Chennai, Hyderabad) and five topic communities. Karma starts at 0 and is computed from votes, never stored, so it cannot drift from them. |
| Agents | Seeded personas; one LLM call per turn returns a JSON action (comment, post, votes). Memory and city knowledge are retrieved by embedding similarity (bge-small, local and free). |
| Guardrails | Feed text arrives in a delimited block under a data-not-instructions rule; injection-like posts are quarantined; actions are validated (visible ids, length caps, karma-based posting limits); the judge's hateful or violent flags trigger moderation removal. Every intervention is logged and counted. |
| Measurement | A stronger judge model scores each item on an economic axis (state and redistribution vs markets) and a social axis (liberty vs order and authority), with extremism flags. Embedding anchors give an independent cross-check. Labels such as "communist-leaning" or "fascist-leaning" are written down as operational definitions in `rlife/ideology.py`. |
| Metrics | Agent positions over time, drift, polarization (mean pairwise distance), reply homophily against a shuffled baseline, upvote vs downvote ideological distance, karma Gini, flag rates. |
| Experiments | `ranking`: new vs hot vs engagement feeds on the same society, news and seed. `redteam`: no defence vs prompt rule vs full guardrails against prompt-injection posts. Reports give 95% bootstrap intervals and permutation p-values. |
| Evals | Export items for hand labelling; agreement of judge and anchors with human labels (correlation, MAE, Cohen's kappa). 19 offline tests run in CI with a fake model. |
| Reliability | Per-model token-per-minute limiter, retry-after on 429s, response cache (seeded runs replay at zero cost), request budgets, and model errors cost one turn, never the run. Each run records the git commit it came from. |
| Observability | Prometheus metrics (turns, actions, rejections, guardrail events, latency, live polarization and karma Gini), a provisioned Grafana dashboard, and a web UI with feeds, threads with per-item scores, agent pages and an animated ideology compass. |

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[embeddings,dev]"
pytest -q                                              # offline, no keys

# Offline end to end (fake model, hash embeddings)
python -m rlife experiment ranking --offline --agents 8 --ticks 4 --out runs/offline

# Real run: put LLM_API_KEY (Groq or any OpenAI-compatible endpoint) in .env
python -m rlife simulate --agents 12 --ticks 6 --out runs/try.db
python -m rlife experiment ranking --agents 24 --ticks 12 --budget 200 --metrics-port 9101
python -m rlife serve runs/ranking/*.db                # http://localhost:8000

# Evaluate the judge against your own labels
python -m rlife label runs/ranking/*.db --n 150        # fill evals/labels.csv
python -m rlife judge-eval evals/labels.csv
```

With Docker: `docker compose up -d web prometheus grafana` (UI on 8000, Grafana on 3000), and
`docker compose --profile sim run --rm sim experiment ranking` for a run.

## Ages of Kingdoms: the game

A browser strategy game built on the same engine. Pick a real river valley (Indus, Nile,
Mesopotamia, Ganges, Yellow River, Mediterranean), a start year and 5 to 10 kingdoms, then rule
one dynasty. Every kingdom is a simulated society of farmers, labourers, artisans, merchants,
clerks, soldiers, civil servants and teachers living under liberal, authoritarian or socialist
laws. Citizens earn karma from how their town square votes on what they say; kings, generals,
sages and priests have abilities, knowledge and ideologies. Kingdoms trade blows over food,
energy and armour, and droughts and floods move the harvest.

Three kinds of agents run alongside the player, each with rules that always work, an optional
LLM layer, guardrails, and metrics:

| Agent | Job | Measured by |
|---|---|---|
| Navigator (Vira) | Spoken tutorial that advances on what the player does; answers questions | tutorial funnel, answer latency (hard 6 s deadline, then a canned answer) |
| Town Wardens | Moderate every town-square post: hate, threats, spam, prompt injection | precision and recall against labelled posts, including held-out paraphrases and harmless look-alikes |
| LiveOps Director | Festivals, relief, trade fairs, quests and difficulty, proposed by the LLM in the background | guardrail rejections, LLM share, happiness change a few years after each action |

The admin console (`/game/admin`, token required) shows all of it, plus endpoint latency.

```bash
python -m rlife serve --port 8010        # http://localhost:8010/game ; admin token printed here
```

**Deploy.** `Dockerfile.game` is a slim image of the game alone; `render.yaml` deploys it on
Render's free plan (New > Blueprint > this repo; paste your LLM key when asked). Each visitor
gets their own world through a session cookie, LLM calls are capped per day
(`RLIFE_LLM_DAILY_CAP`) after which agents use their rules, and the server honours `PORT`, so
the same image runs on Railway, Fly.io or Hugging Face Spaces. Free hosts sleep when idle and
have no persistent disk: the first visit after a pause takes about a minute, and saved worlds
reset when the service restarts.

## Results

The first live experiment (24 agents, 12 ticks, three feed rankings, Groq `gpt-oss-20b` agents
and `gpt-oss-120b` judge) is in progress. Results, with intervals and the judge's agreement with
hand labels, will be added here with the run files they came from. Nothing is reported before
it is measured.

## Limits worth knowing

- Free-tier limits (1,000 requests a day per model, 8,000 tokens a minute) keep runs small:
  dozens of agents, hundreds of turns. Intervals are reported because samples are small.
- The judge is an LLM; its scores are a measurement with error, which is why agreement with
  hand labels and with an independent embedding method is part of the report.
- One run per arm means arm differences mix the treatment with run-to-run variation; repeating
  arms over several seeds is the next step.
- Simulated news is fictional, labelled as simulated, and balanced across both axes.

## Layout

```
rlife/world.py       communities, agents, items, votes, karma (SQLite)
rlife/feed.py        new, hot and engagement ranking
rlife/personas.py    seeded personas and communities
rlife/agent.py       observe, recall, decide, act
rlife/guardrails.py  injection detection, validation, rate limits, moderation flags
rlife/llm.py         OpenAI-compatible client: rate limits, retries, cache, usage
rlife/embed.py       bge-small embeddings and vector search
rlife/ideology.py    judge, embedding anchors, operational labels
rlife/metrics.py     positions, drift, polarization, homophily, vote alignment, Gini
rlife/stats.py       bootstrap intervals and permutation tests
rlife/experiment.py  A/B arms and reports
rlife/evals.py       human-label export and agreement
rlife/obs.py         Prometheus metrics
rlife/web.py         web UI
docs/WALKTHROUGH.md  design decisions, explained
```
