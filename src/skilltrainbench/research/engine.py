from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from .. import evaluate
from ..config import check_skill, load_config
from .feedback import SCORING, aggregate, complete_scores
from .optimizer import AstraResearcher
from .settings import Settings
from .storage import digest, manifest, read_json, tree_digest, write_json
from .usage import summarize_usage


class StopResearch(RuntimeError):
    """An explicit admission/time limit; completed work remains resumable."""


class Experiment:
    def __init__(self, cfg: Settings, evaluator=None, researcher_factory=None):
        self.cfg = cfg
        self.contract = load_config(cfg.contract)
        self.root = cfg.output
        self.evaluator = evaluator or evaluate.run_eval
        self.state_path = self.root / "state.json"
        self.manifest_path = self.root / "manifest.json"
        self.state = read_json(self.state_path) if self.state_path.exists() else {
            "generation": 0, "evaluations_started": 0, "optimizer_calls": 0,
            "candidates": {d: {} for d in cfg.domains}, "champions": {}, "sealed": False,
        }
        self.suite_slots = asyncio.Semaphore(cfg.max_parallel_suites)
        self.task_slots = asyncio.Semaphore(cfg.max_task_containers)
        self.researcher_factory = researcher_factory or AstraResearcher
        self.jobs = {d: {} for d in cfg.domains}
        self.research_image_lock = asyncio.Lock()
        self.state.setdefault("agents", {d: {"generation": self.state["generation"],
                                            "proposed_generation": self.state["generation"], "status": "pending"}
                                          for d in cfg.domains})
        self.active_suites = set()
        self.finalizing = False

    def save(self):
        write_json(self.state_path, self.state)

    def event(self, kind, **fields):
        record = {"time": time.time(), "event": kind, **fields}
        with (self.root / "events.jsonl").open("a") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{kind}] " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for spec in self.cfg.domains.values():
            check = check_skill(self.cfg.path(spec.skill), self.contract)
            if not check["ok"]:
                raise ValueError(f"invalid seed skill: {check['errors']}")
        expected = manifest(self.cfg, self.contract)
        if self.manifest_path.exists():
            if read_json(self.manifest_path) != expected:
                raise ValueError("experiment inputs/config/code changed; restore them or use a new output directory")
        else:
            if self.state_path.exists():
                raise ValueError("state exists without an experiment manifest")
            write_json(self.manifest_path, expected)
            shutil.copyfile(self.cfg.contract, self.root / "hackathon.snapshot.toml")
        self.splits = expected["splits"]
        for domain, spec in self.cfg.domains.items():
            if "seed" not in self.state["candidates"][domain]:
                self.register(domain, "seed", self.cfg.path(spec.skill), None, "Original draft", 0)
        self.verify_candidates()
        for path in (self.root / "evaluations").glob("*/*/suite.json"):
            suite = read_json(path)
            if suite.get("status") == "complete":
                result = path.parent / suite["attempt"] / "eval_result.json"
                if digest(result.read_bytes()) != suite["result_sha256"]:
                    raise ValueError(f"immutable result modified: {result}")
        self.save()
        return expected

    def skill_dir(self, domain, candidate):
        return self.root / "candidates" / domain / candidate / "skill"

    def register(self, domain, candidate, parent_path, skill_md, hypothesis, generation, parent_id=None, **metadata):
        target = self.skill_dir(domain, candidate)
        # Only an unregistered staging directory can exist after an interrupted copy.
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(parent_path, target)
        if skill_md is not None:
            (target / "SKILL.md").write_text(skill_md, encoding="utf-8")
        check = check_skill(target, self.contract)
        if not check["ok"] or (skill_md is not None and check["warnings"]):
            raise ValueError(f"candidate failed skill validation: {check}")
        record = {"id": candidate, "parent": parent_id, "generation": generation,
                  "hypothesis": hypothesis, "sha256": tree_digest(target), "status": "pending", **metadata}
        self.state["candidates"][domain][candidate] = record
        self.save()
        return record

    def verify_candidates(self):
        for domain, candidates in self.state["candidates"].items():
            for candidate, record in candidates.items():
                if record["status"] != "rejected" and tree_digest(self.skill_dir(domain, candidate)) != record["sha256"]:
                    raise ValueError(f"immutable candidate modified: {domain}/{candidate}")

    def check_stop(self):
        if (self.root / "STOP").exists():
            raise StopResearch("STOP file detected; no further work admitted")
        if not self.finalizing and self.state.get("deadline") and time.time() >= self.state["deadline"]:
            raise StopResearch("experiment wall-clock limit reached")

    def reserve_call(self):
        self.check_stop()
        if self.state["optimizer_calls"] >= self.cfg.max_optimizer_calls:
            raise StopResearch("max_optimizer_calls reached")
        self.state["optimizer_calls"] += 1
        self.save()
        return self.state["optimizer_calls"]

    async def suite(self, domain, label, candidate, split, arms):
        directory = self.root / "evaluations" / domain / label
        status_path = directory / "suite.json"
        names = self.splits[domain][split]
        identity = {"domain": domain, "candidate": candidate, "split": split, "arms": arms, "tasks": names,
                    "skill_sha256": self.state["candidates"][domain][candidate]["sha256"] if candidate else None}
        previous = read_json(status_path) if status_path.exists() else {}
        if previous and previous["identity"] != identity:
            raise ValueError("cached suite identity mismatch")
        if previous.get("status") == "complete":
            result_path = directory / previous["attempt"] / "eval_result.json"
            if digest(result_path.read_bytes()) != previous["result_sha256"]:
                raise ValueError(f"cached result changed: {result_path}")
            result = read_json(result_path)
            complete_scores(result, names, arms)
            return {"result": result, "directory": str(result_path.parent.relative_to(self.root))}
        async with self.suite_slots:
            self.check_stop()
            reserve = 0 if self.finalizing else 2 * len(self.cfg.domains) * self.cfg.repeats
            if self.state["evaluations_started"] >= self.cfg.max_evaluations - reserve:
                raise StopResearch("evaluation limit reached (final holdout slots are reserved)")
            self.state["evaluations_started"] += 1
            self.save()
            attempt = f"attempt-{self.state['evaluations_started']:05d}"
            out = directory / attempt
            record = {"identity": identity, "attempt": attempt, "status": "running"}
            write_json(status_path, record)
            self.event("suite_started", domain=domain, suite=label, count=self.state["evaluations_started"])
            self.active_suites.add(f"{domain}/{label}")
            try:
                async with asyncio.timeout(self.cfg.suite_timeout_seconds):
                    result = await self.evaluator(
                        self.contract, domain, skill_dir=self.skill_dir(domain, candidate) if candidate else None,
                        out=out, arms=arms, task_ids=names,
                        upstream_base_url=os.environ.get("STBENCH_UPSTREAM_BASE_URL") or self.contract.upstream_base_url,
                        upstream_key=os.environ.get("STBENCH_UPSTREAM_KEY") or os.environ.get(self.contract.upstream_key_env),
                        concurrency=self.cfg.tasks_per_suite, task_semaphore=self.task_slots)
                complete_scores(result, names, arms)
                # Atomic publication even though the underlying evaluator also writes it.
                write_json(out / "eval_result.json", result)
                record.update(status="complete", result_sha256=digest((out / "eval_result.json").read_bytes()))
                write_json(status_path, record)
                self.event("suite_complete", domain=domain, suite=label,
                           **{arm: aggregate([result], names, arm)["mean"] for arm in arms})
                return {"result": result, "directory": str(out.relative_to(self.root))}
            except asyncio.CancelledError:
                write_json(status_path, {**record, "status": "interrupted"})
                raise
            except Exception as error:
                # Do not leak provider response bodies/credentials into console output.
                write_json(status_path, {**record, "status": "failed", "error_type": type(error).__name__,
                                         "error": redact(str(error))[:3000]})
                self.event("suite_failed", domain=domain, suite=label, error=type(error).__name__)
                return None
            finally:
                self.active_suites.discard(f"{domain}/{label}")

    async def batch(self, coroutines):
        """Admission stops allow already-running suites to finish and checkpoint."""
        tasks = [asyncio.create_task(c) for c in coroutines]
        try:
            values = await asyncio.gather(*tasks, return_exceptions=True)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for value in values:
            if isinstance(value, BaseException):
                raise value
        return values

    async def evaluate_candidate(self, domain, candidate):
        record = self.state["candidates"][domain][candidate]
        if record["status"] in {"rejected", "complete"}:
            return
        suites = await self.batch([
            self.suite(domain, f"dev-{candidate}-r{r}", candidate, "dev", ["skill"])
            for r in range(self.cfg.repeats)])
        if any(s is None for s in suites):
            record.update(status="failed")
        else:
            scores = aggregate([s["result"] for s in suites], self.splits[domain]["dev"], "skill")
            record.update(status="complete", scores=scores, suites=[s["directory"] for s in suites])
        self.save()

    def ranked(self, domain):
        candidates = [c for c in self.state["candidates"][domain].values() if c["status"] == "complete"]
        return sorted(candidates, key=lambda c: (-c["scores"]["mean"], c["generation"], c["id"]))

    def select(self, domain=None):
        for domain in ([domain] if domain else self.cfg.domains):
            ranked = self.ranked(domain)
            if not ranked:
                continue
            current = self.state["champions"].get(domain)
            best = ranked[0]
            incumbent = self.state["candidates"][domain].get(current)
            if incumbent is None or best["scores"]["mean"] > incumbent["scores"]["mean"] + self.cfg.min_improvement:
                self.state["champions"][domain] = best["id"]
                self.event("promoted", domain=domain, candidate=best["id"], score=best["scores"]["mean"])
            winner = self.state["champions"][domain]
            # best/<domain> is an exported copy; the immutable evaluated artifact is candidates/...
            target = self.root / "best" / domain
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(self.skill_dir(domain, winner), target)
        self.save()
        self.report()

    def report(self):
        rows = []
        lines = ["# Skill autoresearch", "", "Local development scores; not private leaderboard scores.", ""]
        for domain in self.cfg.domains:
            control = self.state.get("controls", {}).get(domain, {}).get("placebo", {}).get("mean")
            lines.extend([f"## {domain}", "", "| Candidate | Mean dev reward | Lift over placebo | State | Hypothesis |",
                          "|---|---:|---:|---|---|"])
            for c in self.ranked(domain):
                score = c["scores"]["mean"]
                lift = score - control if control is not None else None
                state = "champion" if self.state["champions"].get(domain) == c["id"] else "retained history"
                row = {"domain": domain, "id": c["id"], "score": score, "placebo_lift": lift,
                       "state": state, "hypothesis": c["hypothesis"]}
                rows.append(row)
                lift_text = f"{lift:.4f}" if lift is not None else "—"
                hypothesis = c["hypothesis"].replace("|", "/").replace("\n", " ")
                lines.append(f"| {c['id']} | {score:.4f} | {lift_text} | {state} | {hypothesis} |")
            lines.append("")
        write_json(self.root / "leaderboard.json", rows)
        write_json(self.root / "usage.json", summarize_usage(self.root))
        (self.root / "report.md").write_text("\n".join(lines))

    def research_brief(self, domain):
        return {"domain": domain, "scoring": SCORING[domain],
                "objective": "Maximize mean raw skill reward on the fixed development tasks. "
                "Controls are cached; holdout evaluation is separate and unavailable to researchers.",
                "contract": (self.root / "hackathon.snapshot.toml").read_text(),
                "grader_source": self.grader_source(domain),
                "development_tasks": self.splits[domain]["dev"],
                "max_skill_chars": self.cfg.max_skill_chars}

    def grader_source(self, domain):
        task = self.contract.domain(domain).dataset_dir / self.splits[domain]["dev"][0]
        if domain == "hle":
            path = task / "tests/test_judge.py"
            return path.read_text() if path.exists() else SCORING[domain]
        import ast
        path = task / "tests/simple_evals_shim/healthbench_eval.py"
        if not path.exists():
            return SCORING[domain]
        source = path.read_text()
        return "\n\n".join(ast.get_source_segment(source, node) for node in ast.parse(source).body
                           if isinstance(node, ast.FunctionDef) and node.name == "calculate_score")

    def submit_candidate(self, domain, generation, allowance, submission_key, parent_id, hypothesis, skill_md):
        """Durably register then queue a job, without waiting for any benchmark results."""
        self.check_stop()
        if self.state["sealed"]:
            raise ValueError("experiment is sealed")
        records = self.state["candidates"][domain]
        if not submission_key.strip() or len(submission_key) > 100:
            raise ValueError("submission_key must contain 1–100 characters")
        # Tool replay after an interrupted SDK run must not launch a second paid suite.
        request_hash = digest(json.dumps([parent_id, hypothesis, skill_md]).encode())
        previous = next((c for c in records.values() if c.get("submission_key") == submission_key
                         and c["generation"] == generation), None)
        if previous:
            if previous["request_sha256"] != request_hash:
                raise ValueError("submission_key already used with different content")
            return self.job_receipt(domain, previous["id"])
        members = [c for c in records.values() if c["generation"] == generation]
        if len(members) >= min(allowance, self.cfg.candidates_per_domain):
            raise ValueError("this research round has used its candidate allowance")
        if sum(c["status"] == "pending" for c in records.values()) >= self.cfg.max_inflight_candidates_per_domain:
            raise ValueError("candidate pool is full; inspect running jobs and finish this research turn")
        reserve = 2 * len(self.cfg.domains) * self.cfg.repeats
        if self.state["evaluations_started"] >= self.cfg.max_evaluations - reserve:
            raise StopResearch("evaluation limit reached (final holdout slots are reserved)")
        parents = {c["id"] for c in self.ranked(domain)[:self.cfg.keep_top]}
        parents.add(self.state["champions"].get(domain))
        if parent_id not in parents:
            raise ValueError("parent must be a retained, completely evaluated candidate in this domain")
        if not skill_md.strip() or len(skill_md) > self.cfg.max_skill_chars:
            raise ValueError("skill is empty or exceeds max_skill_chars")
        if not hypothesis.strip() or len(hypothesis) > 4000:
            raise ValueError("hypothesis must contain 1–4000 characters")
        if any(name in skill_md for names in self.splits[domain].values() for name in names):
            raise ValueError("skill contains a benchmark task identifier")
        if any((self.skill_dir(domain, cid) / "SKILL.md").read_text() == skill_md
               for cid, c in records.items() if c["status"] != "rejected"):
            raise ValueError("duplicate skill; inspect the existing experiment instead")
        cid = f"g{generation:04d}-c{len(members) + 1:02d}"
        try:
            record = self.register(domain, cid, self.skill_dir(domain, parent_id), skill_md,
                                   hypothesis, generation, parent_id,
                                   submission_key=submission_key, request_sha256=request_hash)
        except ValueError:
            shutil.rmtree(self.skill_dir(domain, cid), ignore_errors=True)
            raise
        self.start_candidate(domain, cid)
        self.event("candidate_submitted", domain=domain, candidate=cid, generation=generation)
        return self.job_receipt(domain, record["id"])

    def job_receipt(self, domain, candidate):
        return {"accepted": True, "job_id": f"{domain}/{candidate}", "candidate_id": candidate,
                "status": self.state["candidates"][domain][candidate]["status"]}

    def start_candidate(self, domain, candidate):
        if candidate not in self.jobs[domain]:
            self.jobs[domain][candidate] = asyncio.create_task(self.evaluate_and_select(domain, candidate))

    async def evaluate_controls(self, domain):
        # Cache each domain independently; a slow HLE suite never blocks Health.
        if domain in self.state.get("controls", {}):
            return
        results = await self.batch([
            self.suite(domain, f"dev-controls-r{r}", None, "dev", ["baseline", "placebo"])
            for r in range(self.cfg.repeats)])
        if any(result is None for result in results):
            raise RuntimeError(f"{domain}: control suite failed; inspect suite.json and rerun to retry")
        self.state.setdefault("controls", {})[domain] = {
            arm: aggregate([r["result"] for r in results], self.splits[domain]["dev"], arm)
            for arm in ("baseline", "placebo")}
        self.save()

    def checkpoint_agent(self, domain):
        agent = self.state["agents"][domain]
        records = self.state["candidates"][domain]
        previous = agent["generation"]
        # Rounds can finish out of order. Only advance the contiguous completed prefix.
        while agent["generation"] < agent["proposed_generation"]:
            generation = agent["generation"] + 1
            members = [c for c in records.values() if c["generation"] == generation]
            if any(c["status"] == "pending" for c in members):
                break
            agent["generation"] = generation
        self.state["generation"] = min(a["generation"] for a in self.state["agents"].values())
        self.save()
        if agent["generation"] != previous:
            self.event("generation_complete", domain=domain, generation=agent["generation"])

    async def evaluate_and_select(self, domain, candidate):
        await self.evaluate_candidate(domain, candidate)
        self.select(domain)
        self.checkpoint_agent(domain)

    async def search_domain(self, domain):
        """Run an SDK researcher alongside its bounded, independently completing jobs."""
        agent = self.state["agents"][domain]
        records = self.state["candidates"][domain]
        jobs = self.jobs[domain]
        researcher = self.researcher_factory(self, domain)
        pending = [cid for cid, c in records.items() if cid != "seed" and c["status"] == "pending"]
        research = None
        try:
            while True:
                for cid, task in list(jobs.items()):
                    if task.done():
                        del jobs[cid]
                        task.result()
                while pending and len(jobs) < self.cfg.max_inflight_candidates_per_domain:
                    self.start_candidate(domain, pending.pop(0))
                self.checkpoint_agent(domain)
                vacancies = self.cfg.max_inflight_candidates_per_domain - len(jobs)
                terminal_count = sum(c["status"] in {"complete", "failed", "rejected"} for c in records.values())
                more_rounds = not self.cfg.generations or agent["proposed_generation"] < self.cfg.generations
                fresh = terminal_count != agent.get("proposal_feedback_count", -1)
                resume_round = "active_generation" in agent
                if research is None and not pending and more_rounds and (
                        resume_round or (vacancies and (fresh or not jobs))):
                    self.check_stop()
                    agent.setdefault("active_generation", agent["proposed_generation"] + 1)
                    agent.setdefault("active_allowance", min(vacancies, self.cfg.candidates_per_domain))
                    agent["proposal_feedback_count"] = terminal_count
                    self.save()
                    research = asyncio.create_task(researcher.investigate(
                        agent["active_generation"], agent["active_allowance"]))
                waiting = set(jobs.values())
                if research is not None:
                    waiting.add(research)
                if not waiting:
                    return
                done, _ = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if research is not None and research in done:
                    research.result()
                    agent["proposed_generation"] = agent.pop("active_generation")
                    agent.pop("active_allowance")
                    self.save()
                    research = None
        except asyncio.CancelledError:
            tasks = [*jobs.values(), *([research] if research else [])]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except Exception:
            # Stop further submissions before draining jobs, including jobs the SDK
            # could otherwise submit while the error handler is awaiting cleanup.
            if research is not None and not research.done():
                research.cancel()
            if research is not None:
                await asyncio.gather(research, return_exceptions=True)
            await asyncio.gather(*jobs.values(), return_exceptions=True)
            self.checkpoint_agent(domain)
            raise
        finally:
            await researcher.close()

    async def run_domain(self, domain):
        agent = self.state["agents"][domain]
        agent.update(status="bootstrapping")
        agent.pop("error", None)
        self.save()
        self.event("agent_started", domain=domain)
        try:
            # Within each domain, controls and the original skill also run concurrently.
            await self.batch([self.evaluate_controls(domain), self.evaluate_candidate(domain, "seed")])
            if self.state["candidates"][domain]["seed"]["status"] != "complete":
                raise RuntimeError(f"{domain}: seed suite failed; inspect suite.json and rerun to retry")
            self.select(domain)
            agent["status"] = "searching"
            self.save()
            await self.search_domain(domain)
            agent["status"] = "complete"
            self.event("agent_complete", domain=domain, generation=agent["generation"])
        except asyncio.CancelledError:
            agent["status"] = "interrupted"
            raise
        except StopResearch as error:
            agent.update(status="limited", error=str(error))
            self.event("agent_stopped", domain=domain, reason=str(error))
            raise
        except Exception as error:
            agent.update(status="failed", error=redact(str(error))[:3000])
            self.event("agent_failed", domain=domain, error=type(error).__name__)
            raise
        finally:
            self.save()

    async def heartbeat(self):
        while True:
            await asyncio.sleep(30)
            self.event("progress", active_suites=len(self.active_suites),
                       suites=sorted(self.active_suites),
                       agents={d: a["status"] for d, a in self.state["agents"].items()},
                       minutes_left=round(max(0, self.state["deadline"] - time.time()) / 60, 1))

    async def run(self):
        if self.state["sealed"]:
            raise ValueError("holdout evaluation sealed this experiment; start a new experiment for further research")
        self.state.setdefault("deadline", time.time() + self.cfg.max_hours * 3600)
        self.save()
        self.check_stop()
        heartbeat = asyncio.create_task(self.heartbeat())
        try:
            async with asyncio.timeout(max(0, self.state["deadline"] - time.time())):
                # batch drains independent agents even if one fails; no stage barriers.
                await self.batch([self.run_domain(d) for d in self.cfg.domains])
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def finalize(self):
        if set(self.state["champions"]) != set(self.cfg.domains):
            raise ValueError("run development evaluation before finalizing")
        # Seal BEFORE exposing any holdout scores. Even interrupted finalization cannot feed them back.
        self.state["sealed"] = True
        self.finalizing = True
        self.state.setdefault("finalists", dict(self.state["champions"]))
        self.save()
        jobs = []
        for domain, winner in self.state["finalists"].items():
            for repeat in range(self.cfg.repeats):
                jobs.append((domain, "winner", self.suite(domain, f"holdout-winner-r{repeat}", winner,
                                                           "holdout", ["baseline", "placebo", "skill"])))
                if winner != "seed":
                    jobs.append((domain, "seed", self.suite(domain, f"holdout-seed-r{repeat}", "seed", "holdout", ["skill"])))
        results = await self.batch([j[2] for j in jobs])
        report = {"sealed": True, "finalists": self.state["finalists"], "domains": {}}
        for domain, winner in self.state["finalists"].items():
            groups = {role: [v["result"] for (d, r, _), v in zip(jobs, results) if d == domain and r == role and v]
                      for role in ("winner", "seed")}
            if len(groups["winner"]) != self.cfg.repeats or (winner != "seed" and len(groups["seed"]) != self.cfg.repeats):
                report["domains"][domain] = {"status": "incomplete", "note": "rerun finalize to retry failed suites"}
                continue
            names = self.splits[domain]["holdout"]
            arms = {a: aggregate(groups["winner"], names, a) for a in ("baseline", "placebo", "skill")}
            seed = aggregate(groups["seed"], names, "skill") if winner != "seed" else arms["skill"]
            report["domains"][domain] = {"status": "complete", "arms": arms, "original_seed": seed,
                                         "lift_over_placebo": arms["skill"]["mean"] - arms["placebo"]["mean"],
                                         "lift_over_seed": arms["skill"]["mean"] - seed["mean"]}
        write_json(self.root / "holdout_report.json", report)
        self.event("holdout_complete", report="holdout_report.json")
        return report


def redact(message: str) -> str:
    for key, value in os.environ.items():
        if value and (key.endswith("_KEY") or key.endswith("_TOKEN")):
            message = message.replace(value, "[REDACTED]")
    return message
