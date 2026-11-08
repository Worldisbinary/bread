"""Command line: rlife simulate | experiment | report | serve | label | judge-eval"""

import argparse
import json
import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    if not Path(path).exists():
        return
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def build_llm(offline: bool):
    from .llm import Cache, OpenAICompatibleLLM

    if offline:
        from tests.fakes import fake_llm  # noqa: PLC0415  (dev-only offline mode)

        return fake_llm()
    key = os.environ.get("LLM_API_KEY", "")
    if not key:
        raise SystemExit("Set LLM_API_KEY (and optionally LLM_BASE_URL) in .env, or pass --offline.")
    return OpenAICompatibleLLM(
        os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1"),
        key,
        tokens_per_minute=int(os.environ.get("LLM_TOKENS_PER_MINUTE", "7500")),
        cache=Cache(os.environ.get("RLIFE_CACHE", ".cache/llm.sqlite")),
    )


def build_embedder(offline: bool):
    from .embed import HashEmbedder, default_embedder

    return HashEmbedder() if offline else default_embedder()


def base_config(args) -> dict:
    return {
        "agents": args.agents,
        "ticks": args.ticks,
        "seed": args.seed,
        "active_share": args.active_share,
        "agent_model": os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b"),
        "judge_model": os.environ.get("JUDGE_MODEL", "openai/gpt-oss-120b"),
        "max_agent_requests": args.budget,
    }


def main(argv=None) -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="rlife", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--agents", type=int, default=24)
        p.add_argument("--ticks", type=int, default=12)
        p.add_argument("--seed", type=int, default=7)
        p.add_argument("--active-share", type=float, default=0.6)
        p.add_argument("--budget", type=int, default=None, help="max agent requests per run")
        p.add_argument("--offline", action="store_true", help="fake LLM and hash embeddings (no keys)")
        p.add_argument("--metrics-port", type=int, default=None)

    s = sub.add_parser("simulate", help="run one world")
    common(s)
    s.add_argument("--ranking", default="hot", choices=["new", "hot", "engagement"])
    s.add_argument("--red-team", action="store_true")
    s.add_argument("--no-filters", action="store_true")
    s.add_argument("--out", default="runs/single.db")

    e = sub.add_parser("experiment", help="run all arms of an experiment")
    common(e)
    e.add_argument("name", choices=["ranking", "redteam"])
    e.add_argument("--out", default="runs")

    r = sub.add_parser("report", help="re-analyse an experiment directory")
    r.add_argument("directory")

    v = sub.add_parser("serve", help="browse a run in the web UI")
    v.add_argument("runs", nargs="*", default=[], help="run .db files")
    v.add_argument("--port", type=int, default=8000)

    lab = sub.add_parser("label", help="export items for hand-labelling")
    lab.add_argument("runs", nargs="+")
    lab.add_argument("--n", type=int, default=150)
    lab.add_argument("--out", default="evals/labels.csv")

    je = sub.add_parser("judge-eval", help="agreement between the judge, anchors and your hand labels")
    je.add_argument("labels", default="evals/labels.csv", nargs="?")

    k = sub.add_parser("kingdom", help="run a kingdom: economy, town square, judge and LiveOps")
    k.add_argument("--citizens", type=int, default=1500)
    k.add_argument("--seasons", type=int, default=12)
    k.add_argument("--laws", default="liberal", choices=["liberal", "authoritarian", "socialist"])
    k.add_argument("--voices", type=int, default=10, help="citizens who speak each season (LLM calls)")
    k.add_argument("--steward", default="off", choices=["off", "auto", "propose"])
    k.add_argument("--seed", type=int, default=7)
    k.add_argument("--budget", type=int, default=None, help="max citizen LLM turns")
    k.add_argument("--offline", action="store_true")
    k.add_argument("--metrics-port", type=int, default=None)
    k.add_argument("--out", default="runs/kingdom.db")

    ke = sub.add_parser("kingdom-experiment", help="replicated A/B tests on the kingdom economy")
    ke.add_argument("name", choices=["laws", "steward"])
    ke.add_argument("--seeds", type=int, default=None)
    ke.add_argument("--seasons", type=int, default=None)
    ke.add_argument("--citizens", type=int, default=1500)
    ke.add_argument("--offline", action="store_true")
    ke.add_argument("--out", default="runs")

    args = parser.parse_args(argv)

    if getattr(args, "metrics_port", None):
        from .obs import serve_metrics

        serve_metrics(args.metrics_port)

    if args.cmd == "simulate":
        from .sim import RunConfig, Simulation
        from .world import World

        cfg = RunConfig(
            **base_config(args),
            arm=args.ranking,
            ranking=args.ranking,
            red_team=args.red_team,
            filters=not args.no_filters,
        )
        result = Simulation(World(args.out), build_llm(args.offline), build_embedder(args.offline), cfg).run()
        print(json.dumps(result, indent=2))
    elif args.cmd == "experiment":
        from .experiment import run_experiment

        report = run_experiment(
            args.name, build_llm(args.offline), build_embedder(args.offline), args.out, base_config(args)
        )
        print((Path(args.out) / args.name / "report.md").read_text())
        del report
    elif args.cmd == "report":
        from .experiment import EXPERIMENTS, analyse, render

        directory = Path(args.directory)
        name = directory.name
        analysis = analyse(directory, [a["arm"] for a in EXPERIMENTS[name]])
        (directory / "report.md").write_text(render(name, analysis))
        print((directory / "report.md").read_text())
    elif args.cmd == "serve":
        import uvicorn

        from .game.api import admin_token_hint
        from .web import create_app

        print(
            f"Game: http://localhost:{args.port}/game   Admin: http://localhost:{args.port}/game/admin "
            f"(token: {admin_token_hint()})"
        )
        uvicorn.run(create_app(args.runs), host="0.0.0.0", port=args.port)
    elif args.cmd == "label":
        from .evals import export_for_labelling

        print(export_for_labelling(args.runs, args.n, args.out))
    elif args.cmd == "judge-eval":
        from .evals import judge_agreement

        print(json.dumps(judge_agreement(args.labels), indent=2))
    elif args.cmd == "kingdom":
        from .kingdom.sim import KingdomConfig, KingdomSim
        from .world import World

        cfg = KingdomConfig(
            citizens=args.citizens,
            ticks=args.seasons,
            laws=args.laws,
            seed=args.seed,
            voices_per_tick=args.voices,
            steward=args.steward,
            max_agent_requests=args.budget,
            agent_model=os.environ.get("AGENT_MODEL", "openai/gpt-oss-20b"),
            judge_model=os.environ.get("JUDGE_MODEL", "openai/gpt-oss-120b"),
            steward_model=os.environ.get(
                "STEWARD_MODEL", os.environ.get("JUDGE_MODEL", "openai/gpt-oss-120b")
            ),
        )
        sim = KingdomSim(World(args.out), build_llm(args.offline), build_embedder(args.offline), cfg)
        print(json.dumps(sim.run(), indent=2, default=str))
    elif args.cmd == "kingdom-experiment":
        from .kingdom import experiment as kx

        if args.name == "laws":
            result = kx.laws_experiment(
                seeds=args.seeds or 30, ticks=args.seasons or 24, citizens=args.citizens
            )
        else:
            model = os.environ.get("STEWARD_MODEL", os.environ.get("JUDGE_MODEL", "openai/gpt-oss-120b"))
            result = kx.steward_experiment(
                build_llm(args.offline),
                model,
                seeds=args.seeds or 8,
                ticks=args.seasons or 16,
                citizens=args.citizens,
            )
        print(kx.save(args.name, result, args.out).read_text())


if __name__ == "__main__":
    main()
