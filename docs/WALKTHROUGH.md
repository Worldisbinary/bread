# Design walkthrough

Why each part of r/life is built the way it is. Each section is a question you should be
able to answer about this project without notes.

## 1. Why a simulation, and what is actually being measured?

The simulation is the instrument; the output is measurement. The questions:

1. What political positions emerge when agents with ordinary life circumstances talk to
   each other?
2. Do agents drift, polarize or cluster into echo chambers over time?
3. Does platform design change that? (Feed ranking is the lever; guardrails are another.)

Personas never contain ideology words (a test enforces this), so any position is emergent.

## 2. How is ideology measured, and why should anyone trust the number?

Two independent methods:

- **LLM judge** (a stronger model than the agents): economic axis, social axis, and
  extremism flags, in batches of ten at temperature 0.
- **Embedding anchors**: the mean embedding of reference statements for each pole; an item's
  score is its similarity to one pole minus the other.

Trust comes from evaluation, not assertion: `rlife label` exports a sample; you score it
yourself; `rlife judge-eval` reports correlation, MAE and Cohen's kappa for the judge and the
anchors. Known failure mode seen in the first runs: sarcasm ("Great, now the rich can pay
their way out") can be scored as pro-market.

**Labels are operational definitions.** "Fascist-leaning" means social score of at least 0.5
plus at least two markers among ultranationalism, scapegoating, anti-democratic and
endorsing violence. "Communist-leaning" means economic score of at most -0.6 with an
authoritarian lean, or calls for revolution or abolishing private property. They are written
down in `rlife/ideology.py` so they can be challenged and changed.

## 3. Why one LLM call per turn with a JSON action?

Budget and checkability. Free tiers allow about 1,000 requests a day per model, so a turn
cannot be a multi-step tool loop. A JSON action (comment, post, votes) is validated field by
field before it touches the world.

Found live: when the template showed `comment` as optional, the model voted silently on 11 of
12 turns. An active turn now asks for a comment or a post, with votes as extras. Lurkers
simply do not get a turn.

## 4. What do the guardrails do, and how do you know they work?

- **Input:** feed text sits inside `<feed>` under a standing rule that it is data, never
  instructions. Injection-like posts can be quarantined by a pattern detector.
- **Output:** ids must be visible to the agent, text is length-capped, and posting is
  rate-limited for accounts below -3 karma.
- **Moderation:** judge flags `hateful` or `incites_violence` lead to removal.

The `redteam` experiment measures them. A red-team account posts injections carrying a canary
word, and compliance is measured as the share of agents shown the post who upvoted it or used
the canary word. It is compared across three arms: no defence, the prompt rule only, and full
guardrails.

## 5. How is an A/B test run on a simulation?

- **What is held fixed:** the same personas, the same news schedule and the same seed. The
  only difference between arms is the feed ranking.
- **Units:** outcomes are per agent (polarization contribution), per item (flag rate,
  extremity) and per vote (alignment).
- **Statistics:** each arm gets a 95% bootstrap interval, the difference from baseline gets a
  bootstrap interval, and there is a permutation p-value.
- **Honest limit:** one run per arm mixes the treatment with run-to-run noise. The fix is
  several seeds per arm, which the code supports through `--seed`.

## 6. How do the rankings differ?

- **new:** chronological.
- **hot:** Reddit's published formula: `sign(s) * log10(max(|s|, 1)) + age_term`. Ten times
  the score is worth a fixed amount of recency.
- **engagement:** `(2 * comments + votes + 3 * controversy + 1) / (age + 2)^1.2`.
  Controversy is high when up and down votes are both many and balanced. This is the shape of
  engagement-maximising feeds, which is why it is the arm most likely to raise polarization.

## 7. What makes long runs reliable?

- **Rate limiting:** a sliding one-minute token window per model, and retry-after on 429s.
- **Strict JSON failures:** when Groq's strict JSON mode returns a 400, the client retries once
  in lenient mode.
- **Bounded failure:** a failed turn costs one turn, and a failed judge batch is retried next
  tick.
- **Caching:** the response cache is keyed by the full request, so replaying a seed costs
  nothing.
- **Budgets:** a request budget stops the run cleanly.
- **Traceability:** each run stores the git commit it came from.

## 8. Observability

Prometheus counters and gauges cover:
- turns and actions by kind
- rejections and guardrail interventions
- parse errors
- turn latency
- live polarization, karma Gini and flagged share

Grafana is provisioned from `ops/`. The web UI shows each item's judged position, and the
compass animates agent positions tick by tick.

## 9. Numbers to know (and where they come from)

Fill these from `runs/*/report.md` after the experiments. Use only measured values.

| Quantity | Value | Source |
|---|---|---|
| Agents, ticks, turns per arm | | report.json |
| Polarization by arm, with interval | | report.md |
| Flagged share by arm | | report.md |
| Reply homophily ratio | | report.md |
| Injection compliance by defence | | redteam/report.md |
| Judge vs human: correlation and kappa | | judge-eval output |
