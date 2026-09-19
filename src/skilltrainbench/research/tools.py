"""Narrow, domain-scoped development evidence exposed to the SDK researchers."""
from __future__ import annotations

import json
from pathlib import Path

from agents import function_tool

from .storage import read_json


def safe_path(path: Path, root: Path) -> Path:
    """Refuse all symlink traversal, even links to another suite within the experiment."""
    relative = path.relative_to(root)
    current = root
    for part in ("", *relative.parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinked evidence is unavailable")
    path.resolve().relative_to(root.resolve())
    return path


def read_page(path: Path, root: Path, offset: int = 0, limit: int = 12000) -> dict:
    if not 0 <= offset <= 2_000_000 or not 1 <= limit <= 20000:
        raise ValueError("offset must be 0–2000000 and limit must be 1–20000 characters")
    path = safe_path(path, root)
    if not path.is_file():
        return {"text": "", "next_offset": None, "available": False}
    with path.open(errors="replace") as stream:
        stream.read(offset)
        text = stream.read(limit)
        more = bool(stream.read(1))
    return {"text": text, "next_offset": offset + len(text) if more else None, "available": True}


class ResearchTools:
    def __init__(self, experiment, domain):
        self.exp = experiment
        self.domain = domain
        self.generation = 0
        self.allowance = 0

    @property
    def records(self):
        return self.exp.state["candidates"][self.domain]

    def candidate(self, candidate_id):
        if candidate_id not in self.records:
            raise ValueError("unknown candidate in this domain; use list_experiments")
        return self.records[candidate_id]

    def list_experiments(self, offset=0, limit=30):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be nonnegative and limit must be 1–100")
        records = sorted(self.records.values(), key=lambda c: (c["generation"], c["id"]), reverse=True)
        fields = ("id", "parent", "generation", "status", "hypothesis", "scores")
        return {"domain": self.domain, "champion": self.exp.state["champions"].get(self.domain),
                "controls": self.exp.state.get("controls", {}).get(self.domain),
                "candidate_slots_free": max(0, self.exp.cfg.max_inflight_candidates_per_domain
                                            - sum(c["status"] == "pending" for c in records)),
                "research_round": self.generation, "submission_allowance": self.allowance,
                "experiments": [{**{k: c.get(k) for k in fields}, "job_id": f"{self.domain}/{c['id']}"}
                                for c in records[offset:offset + limit]],
                "next_offset": offset + limit if offset + limit < len(records) else None}

    def read_skill(self, candidate_id):
        self.candidate(candidate_id)
        root = self.exp.skill_dir(self.domain, candidate_id)
        path = safe_path(root / "SKILL.md", self.exp.root)
        return {"candidate_id": candidate_id, "skill_md": path.read_text(),
                "supporting_files": [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()]}

    def suite(self, candidate_id, repeat):
        self.candidate(candidate_id)
        if not 0 <= repeat < self.exp.cfg.repeats:
            raise ValueError("unknown repeat")
        directory = self.exp.root / "evaluations" / self.domain / f"dev-{candidate_id}-r{repeat}"
        status_path = safe_path(directory / "suite.json", self.exp.root)
        if not status_path.exists():
            return directory, {"status": "queued"}, None
        suite = read_json(status_path)
        identity = suite["identity"]
        if (identity["domain"] != self.domain or identity["candidate"] != candidate_id
                or identity["split"] != "dev" or identity["tasks"] != self.exp.splits[self.domain]["dev"]):
            raise ValueError("evidence is not from this candidate's registered development suite")
        attempt = suite["attempt"]
        if Path(attempt).name != attempt or not attempt.startswith("attempt-"):
            raise ValueError("invalid attempt identifier")
        return directory, suite, safe_path(directory / attempt, directory)

    def task_evidence(self, candidate_id, task_name, repeat):
        if task_name not in self.exp.splits[self.domain]["dev"]:
            raise ValueError("only tasks in this domain's development split are accessible")
        directory, suite, out = self.suite(candidate_id, repeat)
        row = {}
        trial = None
        if out:
            attempts = safe_path(out / "attempts.jsonl", directory)
            if attempts.exists():
                for line in attempts.read_text().splitlines():
                    item = json.loads(line)
                    if item.get("task_name") == task_name and item.get("arm") == "skill":
                        row = item
            if row.get("trial_dir"):
                old = Path(row["trial_dir"])
                trial = safe_path(out / "harbor-jobs" / old.parent.name / old.name, out)
            else:
                # Failed/running trials may not yet have an attempts.jsonl row. Job
                # names are created by Harbor from the registered task identifier.
                benchmark = self.exp.contract.domain(self.domain).benchmark
                jobs = sorted((out / "harbor-jobs").glob(f"{benchmark}-train-{task_name}-*"))
                trials = [p for job in jobs for p in job.glob("*/trial.log")]
                if trials:
                    trial = safe_path(max(trials, key=lambda p: p.stat().st_mtime).parent, out)
        return directory, suite, row, trial

    def read_failure(self, candidate_id, task_name, repeat=0):
        directory, suite, row, trial = self.task_evidence(candidate_id, task_name, repeat)
        task = self.exp.contract.domain(self.domain).dataset_dir / task_name
        instruction = task / ("environment/workspace/instruction.md" if self.domain == "hle" else "instruction.md")
        verdict = "verdicts.json" if self.domain == "health" else "judgment.json"
        return {"candidate_id": candidate_id, "task_name": task_name, "suite_status": suite["status"],
                "infrastructure_error": suite.get("error"),
                "instruction": read_page(instruction, task)["text"],
                "attempt": {k: row.get(k) for k in ("score", "status", "answer")},
                "grader_feedback": read_page(trial / "verifier" / verdict, directory)["text"] if trial else "",
                "trial_log": read_page(trial / "trial.log", directory, limit=6000)["text"] if trial else ""}

    def read_trajectory(self, candidate_id, task_name, repeat=0, artifact="trajectory", offset=0, limit=12000):
        allowed = {"trajectory": "agent/trajectory.json", "trial_log": "trial.log",
                   "response": "agent/response.txt", "verifier_log": "verifier/test-stdout.txt"}
        if artifact not in allowed:
            raise ValueError("artifact must be trajectory, trial_log, response, or verifier_log")
        directory, suite, _, trial = self.task_evidence(candidate_id, task_name, repeat)
        if not trial:
            return {"available": False, "suite_status": suite["status"], "text": "", "next_offset": None}
        return read_page(trial / allowed[artifact], directory, offset, limit)

    def compare_candidates(self, left_id, right_id):
        left, right = self.candidate(left_id), self.candidate(right_id)
        if left["status"] != "complete" or right["status"] != "complete":
            raise ValueError("comparison requires two completely evaluated candidates")
        a, b = left["scores"], right["scores"]
        differences = [{"task_name": name, "left": a["per_task"][name], "right": b["per_task"][name],
                        "delta": b["per_task"][name] - a["per_task"][name]}
                       for name in self.exp.splits[self.domain]["dev"]]
        return {"left": left_id, "right": right_id, "mean_delta": b["mean"] - a["mean"],
                "per_task": sorted(differences, key=lambda r: r["delta"]),
                "note": "Paired development differences; this is not holdout evidence or a significance test."}

    def submit_candidate(self, submission_key, parent_id, hypothesis, skill_md):
        return self.exp.submit_candidate(self.domain, self.generation, self.allowance,
                                         submission_key, parent_id, hypothesis, skill_md)

    def invoke(self, name, **arguments):
        from .engine import redact
        try:
            result = getattr(self, name)(**arguments)
        except (ValueError, KeyError) as error:
            result = {"error": str(error)}
        # Credential values can appear in infrastructure logs. Never feed them back.
        clean = json.loads(redact(json.dumps(result, ensure_ascii=False)))
        directory = self.exp.root / "optimizer" / self.domain / f"generation-{self.generation:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "tools.jsonl").open("a") as stream:
            stream.write(json.dumps({"tool": name, "arguments": json.loads(redact(json.dumps(arguments))),
                                     "result": clean}, ensure_ascii=False) + "\n")
        self.exp.event("research_tool", domain=self.domain, tool=name)
        return clean

    def sdk_tools(self):
        @function_tool(failure_error_function=None)
        async def list_experiments(offset: int = 0, limit: int = 30) -> dict:
            """List this domain's experiments, job status, scores, controls and free candidate slots."""
            return self.invoke("list_experiments", offset=offset, limit=limit)

        @function_tool(failure_error_function=None)
        async def read_skill(candidate_id: str) -> dict:
            """Read a registered candidate's complete SKILL.md and supporting file names."""
            return self.invoke("read_skill", candidate_id=candidate_id)

        @function_tool(failure_error_function=None)
        async def read_failure(candidate_id: str, task_name: str, repeat: int = 0) -> dict:
            """Inspect one development task's instruction, response, grade and failure logs."""
            return self.invoke("read_failure", candidate_id=candidate_id, task_name=task_name, repeat=repeat)

        @function_tool(failure_error_function=None)
        async def read_trajectory(candidate_id: str, task_name: str, repeat: int = 0,
                                  artifact: str = "trajectory", offset: int = 0, limit: int = 12000) -> dict:
            """Read paginated trajectory, trial_log, response or verifier_log for a dev task only."""
            return self.invoke("read_trajectory", candidate_id=candidate_id, task_name=task_name,
                               repeat=repeat, artifact=artifact, offset=offset, limit=limit)

        @function_tool(failure_error_function=None)
        async def compare_candidates(left_id: str, right_id: str) -> dict:
            """Compare complete candidates using paired differences on the identical development tasks."""
            return self.invoke("compare_candidates", left_id=left_id, right_id=right_id)

        @function_tool(failure_error_function=None)
        async def submit_candidate(submission_key: str, parent_id: str, hypothesis: str, skill_md: str) -> dict:
            """Validate and queue a complete SKILL.md; immediately return a job ID, without waiting.

            Use a unique submission_key per hypothesis in this research round. Exact retries are idempotent.
            """
            return self.invoke("submit_candidate", submission_key=submission_key, parent_id=parent_id,
                               hypothesis=hypothesis, skill_md=skill_md)

        return [list_experiments, read_skill, read_failure, read_trajectory, compare_candidates, submit_candidate]
