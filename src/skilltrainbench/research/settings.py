from __future__ import annotations

import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Domain:
    skill: str
    dev_size: int = 24
    holdout_size: int = 24
    dev_file: str = ""
    holdout_file: str = ""


@dataclass(frozen=True)
class Settings:
    root: Path
    contract: Path
    output: Path
    domains: dict[str, Domain]
    generations: int = 10
    candidates_per_domain: int = 5
    max_inflight_candidates_per_domain: int = 5
    keep_top: int = 3
    max_parallel_suites: int = 5
    tasks_per_suite: int = 2
    max_task_containers: int = 10
    repeats: int = 1
    seed: int = 42
    max_evaluations: int = 120
    max_optimizer_calls: int = 40
    suite_timeout_seconds: int = 14400
    max_hours: float = 12
    min_improvement: float = 0.001
    feedback_examples: int = 6
    max_skill_chars: int = 24000
    optimizer_model: str = "gpt-6-astra"
    reasoning_effort: str = "high"
    max_output_tokens: int = 40000

    def path(self, value: str) -> Path:
        return (self.root / value).resolve()

    def identity(self) -> dict:
        """Portable experiment identity; output location can change after SSH transfer."""
        data = asdict(self)
        for name in ("root", "output", "contract"):
            data.pop(name)
        return data


def load_settings(path: str | Path) -> Settings:
    path = Path(path).resolve()
    raw = tomllib.loads(path.read_text())
    root = path.parent
    run = dict(raw.get("research", {}))
    contract = (root / run.pop("contract", "hackathon.toml")).resolve()
    output = (root / run.pop("output", "runs/autoresearch")).resolve()
    domains = {name: Domain(**value) for name, value in raw.get("domains", {}).items()}
    if not domains or not set(domains) <= {"health", "hle"}:
        raise ValueError("research domains must include health and/or hle")
    cfg = Settings(root, contract, output, domains, **run)
    positive = ("candidates_per_domain", "max_inflight_candidates_per_domain", "keep_top", "max_parallel_suites", "tasks_per_suite",
                "max_task_containers", "repeats", "max_evaluations", "max_optimizer_calls",
                "suite_timeout_seconds", "feedback_examples", "max_skill_chars", "max_output_tokens")
    if any(type(getattr(cfg, k)) is not int or getattr(cfg, k) < 1 for k in positive):
        raise ValueError("counts, concurrency, timeouts and token limits must be positive integers")
    if type(cfg.generations) is not int or cfg.generations < 0:
        raise ValueError("generations must be nonnegative (0 means until a budget/STOP)")
    if not math.isfinite(cfg.max_hours) or cfg.max_hours <= 0:
        raise ValueError("max_hours must be finite and positive")
    if not math.isfinite(cfg.min_improvement) or cfg.min_improvement < 0:
        raise ValueError("min_improvement must be finite and nonnegative")
    if cfg.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError("unsupported Astra reasoning effort")
    for name, domain in domains.items():
        if domain.dev_size < 1 or domain.holdout_size < 1:
            raise ValueError(f"{name}: dev_size and holdout_size must be positive")
    return cfg
