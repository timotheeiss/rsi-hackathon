from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from .engine import Experiment, StopResearch
from .settings import load_settings
from .storage import experiment_lock, read_json


def preflight(experiment: Experiment, *, optimizer: bool):
    key = os.environ.get("STBENCH_UPSTREAM_KEY") or os.environ.get(experiment.contract.upstream_key_env)
    if not key:
        raise ValueError(f"set {experiment.contract.upstream_key_env} in .env")
    if optimizer and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("set OPENAI_API_KEY in .env for GPT-6 Astra")
    if not shutil.which("harbor"):
        raise ValueError("harbor is not installed/on PATH; run with uv run stbench-research")
    try:
        check = subprocess.run(["docker", "info", "--format", "{{.OSType}}"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Docker is unavailable; install/start Docker Engine first") from None
    if check.returncode or check.stdout.strip() != "linux":
        raise ValueError("Docker must be running with Linux containers and accessible by this user")


async def execute(experiment: Experiment, command: str):
    # SIGINT is handled by asyncio.run; systemd's SIGTERM uses the same cancellation path.
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, current.cancel)
    try:
        if command == "run":
            await experiment.run()
        else:
            result = await experiment.finalize()
            if any(d["status"] != "complete" for d in result["domains"].values()):
                raise RuntimeError("holdout incomplete; inspect holdout_report.json and rerun finalize")
    finally:
        experiment.save()
        if not experiment.state["sealed"]:
            experiment.select()
        else:
            experiment.report()
        loop.remove_signal_handler(signal.SIGTERM)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="stbench-research", description="Optimize Health/HLE skills with Astra")
    parser.add_argument("command", choices=["plan", "run", "finalize", "status", "doctor"])
    parser.add_argument("--config", default="autoresearch.toml")
    parser.add_argument("--env-file", default=None, help="defaults to .env beside the research config")
    args = parser.parse_args(argv)
    try:
        cfg = load_settings(args.config)
        load_dotenv(Path(args.env_file) if args.env_file else cfg.root / ".env", override=False)
        if args.command == "status":
            state = read_json(cfg.output / "state.json")
            print(json.dumps({k: v for k, v in state.items() if k not in {"candidates", "controls"}}, indent=2))
            if (cfg.output / "leaderboard.json").exists():
                print(json.dumps(read_json(cfg.output / "leaderboard.json"), indent=2))
            return 0
        with experiment_lock(cfg.output):
            experiment = Experiment(cfg)
            manifest = experiment.initialize()
            if args.command == "plan":
                splits = {d: {s: len(n) for s, n in split.items()} for d, split in manifest["splits"].items()}
                suites = None if cfg.generations == 0 else len(cfg.domains) * cfg.repeats * (
                    2 + cfg.generations * cfg.candidates_per_domain + 2)
                task_attempts = None if cfg.generations == 0 else sum(
                    cfg.repeats * (len(split["dev"]) * (3 + cfg.generations * cfg.candidates_per_domain)
                                   + 4 * len(split["holdout"])) for split in manifest["splits"].values())
                print(json.dumps({"output": str(cfg.output), "splits": splits, "optimizer": cfg.optimizer_model,
                                  "independent_agents": list(cfg.domains),
                                  "max_inflight_candidates_per_agent": cfg.max_inflight_candidates_per_domain,
                                  "max_search_hours": cfg.max_hours,
                                  "parallel_suites": cfg.max_parallel_suites, "max_containers": cfg.max_task_containers,
                                  "planned_suites_upper_bound": suites, "planned_task_attempts_upper_bound": task_attempts,
                                  "max_evaluations": cfg.max_evaluations, "max_optimizer_calls": cfg.max_optimizer_calls,
                                  "note": "No API calls. Each task attempt includes learner and grader calls; infra retries add cost."}, indent=2))
                return 0
            preflight(experiment, optimizer=args.command != "finalize")
            if args.command == "doctor":
                print("Inputs, split, skill validation, API key presence and Docker checks passed. No paid API calls made.")
                return 0
            asyncio.run(execute(experiment, args.command))
        return 0
    except (StopResearch, TimeoutError) as error:
        print(f"Research stopped at its configured limit: {error}. Completed artifacts are saved.")
        return 0
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Interrupted; completed suites are saved. Repeat the same command to resume.")
        return 130
    except (OSError, ValueError, RuntimeError, TypeError, KeyError) as error:
        print(f"research error: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
