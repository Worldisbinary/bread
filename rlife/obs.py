"""Observability: Prometheus metrics for live runs, plus a JSON-lines event log.

Metrics are exposed by `rlife serve` (or `rlife simulate --metrics-port`) and scraped
by the Prometheus service in docker-compose; Grafana reads them for the run dashboard.
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

TURNS = Counter("rlife_agent_turns_total", "Agent turns", ["arm"])
ACTIONS = Counter("rlife_actions_total", "Applied agent actions", ["arm", "kind"])
REJECTED = Counter("rlife_rejected_actions_total", "Actions rejected by guardrails or validation", ["arm"])
PARSE_ERRORS = Counter("rlife_parse_errors_total", "Unparseable agent replies", ["arm"])
GUARDRAIL = Counter("rlife_guardrail_events_total", "Guardrail interventions", ["arm", "rule"])
LLM_TOKENS = Counter("rlife_llm_tokens_total", "LLM tokens used", ["model", "direction"])
LLM_CACHE_HITS = Counter("rlife_llm_cache_hits_total", "LLM responses served from cache", ["model"])
LLM_LATENCY = Histogram(
    "rlife_llm_turn_seconds", "Wall time of one agent turn", ["arm"], buckets=(0.5, 1, 2, 4, 8, 16, 32, 64)
)
TICK = Gauge("rlife_tick", "Current simulation tick", ["arm"])
POLARIZATION = Gauge("rlife_polarization", "Mean pairwise ideological distance between agents", ["arm"])
KARMA_GINI = Gauge("rlife_karma_gini", "Inequality of karma across agents", ["arm"])
FLAGGED_SHARE = Gauge("rlife_flagged_share", "Share of judged items with an extremism flag", ["arm"])


def serve_metrics(port: int) -> None:
    start_http_server(port)
