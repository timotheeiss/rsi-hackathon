from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from ..config import HackathonCfg
from .storage import read_json


SCORING = {
    "health": "HealthBench: each satisfied positive rubric adds points; satisfied negative rubrics "
    "subtract points. Raw reward is achieved points / total positive points and CAN BE NEGATIVE. "
    "Optimize mean raw reward, not the fraction of tasks with reward=1. The official display clips "
    "the aggregate into [0,1]. A grader invalidation is unscored, never a successful zero. "
    "Write the final response to the output file required by the task within FOUR learner turns.",
    "hle": "HLE: the verifier extracts the final answer and checks equivalence against a reference "
    "using a model judge. Correct=1, incorrect=0; ambiguity/non-equivalence fails; small numeric "
    "tolerance is allowed. Explanation and confidence have no separate reward. Read /app/instruction.md "
    "and save Explanation / Answer / Confidence to /logs/agent/response.txt. There are 50 learner turns.",
}


def complete_scores(result: dict, names: list[str], arms: list[str]) -> dict[str, dict[str, float]]:
    """Reject missing/invalidated tasks so no candidate wins by shrinking its denominator."""
    if result.get("tasks") != names or set(result.get("arms", [])) != set(arms):
        raise ValueError("evaluation task list or arms differ from the registered suite")
    if result.get("summary", {}).get("n_invalidated_tasks", 0):
        raise ValueError("ungraded tasks: suite is ineligible for selection")
    rows = result.get("per_task", [])
    if len(rows) != len(names) or {r.get("task_name") for r in rows} != set(names):
        raise ValueError("incomplete or duplicate evaluation rows")
    scores = {a: {} for a in arms}
    for row in rows:
        for arm in arms:
            value = row.get(arm)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"missing/nonfinite {arm} score")
            scores[arm][row["task_name"]] = float(value)
    return scores


def aggregate(results: list[dict], names: list[str], arm: str) -> dict:
    by_repeat = [complete_scores(r, names, r["arms"])[arm] for r in results]
    per_task = {n: statistics.mean(r[n] for r in by_repeat) for n in names}
    means = [statistics.mean(r.values()) for r in by_repeat]
    return {"mean": statistics.mean(per_task.values()), "per_task": per_task,
            "repeat_means": means, "repeat_stddev": statistics.stdev(means) if len(means) > 1 else None}


def aggregate_subsets(results: list[dict], subsets: dict[str, list[str]], groups: dict[str, str],
                      arm: str, repeats: int) -> dict:
    """Join disjoint subsets per repeat; every task gets equal weight, never partial scores."""
    if len(results) != len(subsets) * repeats:
        raise ValueError("incomplete development subset results")
    names = [name for tasks in subsets.values() for name in tasks]
    if len(set(names)) != len(names):
        raise ValueError("overlapping development subsets")
    merged, subset_scores = [], {}
    for index, (subset, tasks) in enumerate(subsets.items()):
        subset_scores[subset] = aggregate([results[r * len(subsets) + index] for r in range(repeats)], tasks, arm)
    for repeat in range(repeats):
        parts = results[repeat * len(subsets):(repeat + 1) * len(subsets)]
        # aggregate above has validated each part's exact task identities and all arm scores.
        merged.append({"tasks": names, "arms": [arm],
                       "per_task": [{"task_name": row["task_name"], arm: row[arm]}
                                    for part in parts for row in part["per_task"]]})
    scores = aggregate(merged, names, arm)
    scores["subsets"] = subset_scores
    scores["groups"] = {
        group: {"mean": statistics.mean(scores["per_task"][n] for n in tasks), "tasks": len(tasks)}
        for group in sorted(set(groups.values()))
        if (tasks := [n for n in names if groups.get(n) == group])
    }
    return scores


def excerpt(path: Path, root: Path, limit=6000) -> str:
    try:
        path.resolve().relative_to(root.resolve())
        if path.is_symlink():
            return ""
        with path.open(errors="replace") as stream:
            return stream.read(limit)
    except (ValueError, OSError):
        return ""


def feedback(contract: HackathonCfg, domain: str, names: list[str], eval_dirs: list[Path],
             max_examples: int) -> list[dict]:
    """Only registered development attempts; never traverse the task's solution/answer keys."""
    examples = []
    for directory in eval_dirs:
        attempts = directory / "attempts.jsonl"
        if not attempts.exists():
            continue
        for line in attempts.read_text().splitlines():
            row = json.loads(line)
            if row.get("arm") != "skill" or row.get("task_name") not in names:
                continue
            examples.append((directory, row))
    # Show the worst cases and one success to preserve strengths.
    examples.sort(key=lambda pair: pair[1].get("score") if pair[1].get("score") is not None else -math.inf)
    if len(examples) <= max_examples:
        chosen = examples
    else:
        chosen = examples[:max_examples - 1] + examples[-1:] if max_examples > 1 else examples[:1]
    output = []
    for directory, row in chosen:
        task = contract.domain(domain).dataset_dir / row["task_name"]
        prompt = task / ("environment/workspace/instruction.md" if domain == "hle" else "instruction.md")
        item = {k: row.get(k) for k in ("task_name", "score", "status", "answer")}
        item["answer"] = str(item["answer"] or "")[:6000]
        item["instruction"] = excerpt(prompt, task, 6000)
        trial = Path(row["trial_dir"]) if row.get("trial_dir") else None
        if trial:
            # Harbor can store absolute paths; after moving an experiment, locate the
            # same job/trial underneath this suite, not the old host's filesystem.
            trial = directory / "harbor-jobs" / trial.parent.name / trial.name
            response = excerpt(trial / "agent/response.txt", directory)
            if response:
                item["answer"] = response
            verdict = trial / "verifier" / ("verdicts.json" if domain == "health" else "judgment.json")
            item["grader_feedback"] = excerpt(verdict, directory, 10000)
            item["trajectory_excerpt"] = excerpt(trial / "agent/trajectory.json", directory, 5000)
            item["trial_log"] = excerpt(trial / "trial.log", directory, 2000)
        output.append(item)
    return output
