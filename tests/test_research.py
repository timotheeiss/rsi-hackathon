from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from skilltrainbench import evaluate
from skilltrainbench.research.engine import Experiment, StopResearch
from skilltrainbench.research.feedback import aggregate, complete_scores, feedback
from skilltrainbench.research.optimizer import AstraResearcher, MeteredResponsesModel
from skilltrainbench.research.tools import ResearchTools
from skilltrainbench.research.settings import Domain, Settings, load_settings
from skilltrainbench.research.storage import experiment_lock, read_json, split_tasks, write_json
from skilltrainbench.tasks import REQUIRED_FILES, Task


def skill(score):
    return f"---\nname: test-skill\ndescription: A reusable procedure\n---\nScore marker: {score}\n"


def fixture(root: Path) -> Settings:
    contract = root / "hackathon.toml"
    contract.write_text('''schema_version = 1
[learner]
model = "frozen"
harbor_agent = "openhands-sdk"
[upstream]
base_url = "https://invalid.example"
key_env = "RUNWARE_API_KEY"
[domains.health]
benchmark = "healthbench"
dataset_dir = "data/health"
[domains.hle]
benchmark = "hlebench"
dataset_dir = "data/hle"
''')
    for domain in ("health", "hle"):
        seed = root / "seeds" / domain
        seed.mkdir(parents=True)
        (seed / "SKILL.md").write_text(skill(0.2))
        (seed / "helper.txt").write_text("Unchanged supporting content")
        for n in range(8):
            task = root / "data" / domain / f"task-{n}"
            task.mkdir(parents=True)
            (task / "task.toml").write_text('[task]\nname = "test"\n')
            (task / "instruction.md").write_text(f"Training instruction {n}")
    return Settings(root, contract, root / "output",
                    {d: Domain(f"seeds/{d}", dev_size=3, holdout_size=2) for d in ("health", "hle")},
                    generations=2, candidates_per_domain=2, max_evaluations=50,
                    max_parallel_suites=3, tasks_per_suite=2, max_task_containers=2,
                    min_improvement=0.001)


class FakeEvaluator:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.peak = 0
        self.fail = False
        self.invalid = False

    async def __call__(self, contract, domain, **kw):
        self.calls.append((domain, kw))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(0.003)
            if self.fail:
                raise RuntimeError("synthetic infrastructure failure")
            out = kw["out"]
            out.mkdir(parents=True, exist_ok=True)
            score = 0.0
            if kw["skill_dir"]:
                score = float((kw["skill_dir"] / "SKILL.md").read_text().split("Score marker: ")[1].strip())
            rows = [{"task_name": n, "task_id": n,
                     **{a: (score if a == "skill" else 0.1) for a in kw["arms"]}} for n in kw["task_ids"]]
            if self.invalid:
                rows[0][kw["arms"][0]] = None
            result = {"tasks": kw["task_ids"], "arms": kw["arms"], "per_task": rows,
                      "summary": {"skill_rate": score, "n_invalidated_tasks": int(self.invalid)}}
            write_json(out / "eval_result.json", result)
            (out / "attempts.jsonl").write_text("".join(json.dumps({
                "task_name": n, "arm": "skill", "score": score, "answer": "answer", "status": "ok"
            }) + "\n" for n in kw["task_ids"]))
            (out / "learner_ledger.jsonl").write_text(json.dumps({"charged_tokens": 10, "cost_usd": 0.1}) + "\n")
            return result
        finally:
            self.active -= 1


class FakeResearchers:
    def __init__(self):
        self.prompts = []

    def __call__(self, experiment, domain):
        owner = self
        class Researcher:
            async def investigate(self, generation, allowance):
                owner.prompts.append(experiment.research_brief(domain))
                parent = experiment.state["champions"][domain]
                bridge = ResearchTools(experiment, domain)
                bridge.generation, bridge.allowance = generation, allowance
                for index, value in enumerate((0.7 + generation / 10, -0.1 * generation)[:allowance]):
                    bridge.submit_candidate(f"hypothesis-{index}", parent, f"Test score {value}", skill(value))

            async def close(self):
                pass
        return Researcher()


class ResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = fixture(self.root)
        self.evaluator = FakeEvaluator()
        self.proposer = FakeResearchers()
        self.exp = Experiment(self.cfg, self.evaluator, self.proposer)
        self.exp.initialize()

    async def test_end_to_end_selection_resume_and_sealed_holdout(self):
        await self.exp.run()
        self.assertEqual(self.exp.state["generation"], 2)
        self.assertLessEqual(self.evaluator.peak, 3)
        self.assertGreater(self.evaluator.peak, 1)
        for domain in self.cfg.domains:
            self.assertEqual(self.exp.state["champions"][domain], "g0002-c01")
            self.assertAlmostEqual(self.exp.ranked(domain)[0]["scores"]["mean"], .9)
            self.assertEqual((self.root / "seeds" / domain / "SKILL.md").read_text(), skill(.2))
            self.assertEqual((self.root / "output/best" / domain / "helper.txt").read_text(), "Unchanged supporting content")
        for prompt in self.proposer.prompts:
            domain = prompt["domain"]
            for name in self.exp.splits[domain]["holdout"]:
                self.assertNotIn(name, json.dumps(prompt))
        calls = len(self.evaluator.calls)
        resumed = Experiment(self.cfg, self.evaluator, self.proposer)
        resumed.initialize()
        await resumed.run()
        self.assertEqual(calls, len(self.evaluator.calls))
        report = await resumed.finalize()
        for domain in self.cfg.domains:
            self.assertAlmostEqual(report["domains"][domain]["lift_over_seed"], .7)
        calls = len(self.evaluator.calls)
        await resumed.finalize()
        self.assertEqual(calls, len(self.evaluator.calls))
        with self.assertRaisesRegex(ValueError, "sealed"):
            await resumed.run()

    async def test_negative_health_scores_are_not_clipped(self):
        await self.exp.run()
        record = self.exp.state["candidates"]["health"]["g0001-c02"]
        self.assertAlmostEqual(record["scores"]["mean"], -.1)

    async def test_failure_does_not_become_zero_or_promote(self):
        self.evaluator.fail = True
        await self.exp.evaluate_candidate("health", "seed")
        self.assertEqual(self.exp.state["candidates"]["health"]["seed"]["status"], "failed")
        self.assertEqual(self.exp.ranked("health"), [])
        self.evaluator.fail = False
        await self.exp.evaluate_candidate("health", "seed")
        self.assertEqual(self.exp.ranked("health")[0]["id"], "seed")
        self.assertEqual(self.exp.state["evaluations_started"], 2)

    async def test_invalidated_task_rejects_whole_candidate(self):
        self.evaluator.invalid = True
        await self.exp.evaluate_candidate("hle", "seed")
        self.assertEqual(self.exp.ranked("hle"), [])
        path = next((self.root / "output/evaluations").glob("*/*/suite.json"))
        self.assertEqual(read_json(path)["status"], "failed")

    async def test_budget_admission_is_global_and_reserves_finalization(self):
        exp = Experiment(replace(self.cfg, max_evaluations=6), self.evaluator, self.proposer)
        exp.splits = self.exp.splits
        with self.assertRaises(StopResearch):
            await exp.batch([exp.suite("health", f"test-{i}", "seed", "dev", ["skill"]) for i in range(10)])
        self.assertEqual(exp.state["evaluations_started"], 2)
        self.assertEqual(len(self.evaluator.calls), 2)

    async def test_completed_suite_is_reused_after_resume(self):
        await self.exp.suite("health", "cached", "seed", "dev", ["skill"])
        resumed = Experiment(self.cfg, self.evaluator, self.proposer)
        resumed.initialize()
        await resumed.suite("health", "cached", "seed", "dev", ["skill"])
        self.assertEqual(len(self.evaluator.calls), 1)

    async def test_cancelled_suite_is_marked_and_retryable(self):
        started = asyncio.Event()
        async def hanging(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
        self.exp.evaluator = hanging
        task = asyncio.create_task(self.exp.suite("health", "interrupted", "seed", "dev", ["skill"]))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.exp.evaluator = self.evaluator
        await self.exp.suite("health", "interrupted", "seed", "dev", ["skill"])
        self.assertEqual(self.exp.state["evaluations_started"], 2)

    async def test_immutable_skill_and_result_tampering_detected(self):
        path = self.exp.skill_dir("health", "seed") / "SKILL.md"
        path.write_text(skill(.99))
        with self.assertRaisesRegex(ValueError, "modified"):
            self.exp.verify_candidates()
        path.write_text(skill(.2))
        suite = await self.exp.suite("health", "cache", "seed", "dev", ["skill"])
        path = self.exp.root / suite["directory"] / "eval_result.json"
        path.write_text("{}")
        with self.assertRaisesRegex(ValueError, "modified"):
            Experiment(self.cfg).initialize()

    def test_split_is_deterministic_and_disjoint(self):
        first = split_tasks(self.cfg, self.exp.contract)
        second = split_tasks(self.cfg, self.exp.contract)
        self.assertEqual(first, second)
        for split in first.values():
            self.assertFalse(set(split["dev"]) & set(split["holdout"]))
        (self.root / "dev.txt").write_text("task-1,task-2")
        cfg = replace(self.cfg, domains={"health": Domain("seeds/health", dev_file="dev.txt", holdout_file="dev.txt")})
        with self.assertRaisesRegex(ValueError, "overlap"):
            split_tasks(cfg, self.exp.contract)

    def test_changed_config_and_dataset_block_resume(self):
        with self.assertRaisesRegex(ValueError, "changed"):
            Experiment(replace(self.cfg, repeats=2)).initialize()
        name = self.exp.splits["health"]["dev"][0]
        (self.root / "data/health" / name / "instruction.md").write_text("changed input")
        with self.assertRaisesRegex(ValueError, "changed"):
            Experiment(self.cfg).initialize()

    def test_lock_prevents_two_writers(self):
        with experiment_lock(self.root / "lock"):
            with self.assertRaisesRegex(ValueError, "another process"):
                with experiment_lock(self.root / "lock"):
                    pass

    async def test_stop_file_prevents_new_admissions(self):
        (self.exp.root / "STOP").touch()
        with self.assertRaises(StopResearch):
            await self.exp.suite("health", "stop", "seed", "dev", ["skill"])
        self.assertEqual(len(self.evaluator.calls), 0)

    async def test_finalize_still_works_after_search_deadline(self):
        for domain in self.cfg.domains:
            await self.exp.evaluate_candidate(domain, "seed")
        self.exp.select()
        self.exp.state["deadline"] = 1
        with self.assertRaises(StopResearch):
            self.exp.check_stop()
        report = await self.exp.finalize()
        self.assertTrue(all(d["status"] == "complete" for d in report["domains"].values()))

    async def test_repeats_average_each_task_equally(self):
        one = await self.exp.suite("health", "repeat1", "seed", "dev", ["skill"])
        two = json.loads(json.dumps(one["result"]))
        two["per_task"][0]["skill"] = .8
        result = aggregate([one["result"], two], self.exp.splits["health"]["dev"], "skill")
        self.assertAlmostEqual(result["mean"], .3)

    async def test_malformed_and_duplicate_submissions_are_rejected(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select()
        bridge = ResearchTools(self.exp, "health")
        bridge.generation, bridge.allowance = 1, 2
        for content in (skill(.2), "no frontmatter"):
            with self.assertRaises(ValueError):
                bridge.submit_candidate("bad", "seed", "invalid", content)
        self.assertEqual(list(bridge.records), ["seed"])
        self.assertFalse(self.exp.jobs["health"])

    def test_feedback_cannot_read_outside_suite_or_holdout(self):
        directory = self.exp.root / "feedback"
        directory.mkdir()
        dev = self.exp.splits["health"]["dev"][0]
        holdout = self.exp.splits["health"]["holdout"][0]
        rows = [{"task_name": n, "arm": "skill", "score": .1, "trial_dir": "/tmp/secret/trial"}
                for n in (dev, holdout)]
        (directory / "attempts.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        values = feedback(self.exp.contract, "health", [dev], [directory], 6)
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["task_name"], dev)
        self.assertEqual(values[0]["grader_feedback"], "")


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_evaluator_parallel_suites_share_cap_and_close_gateways(self):
        from skilltrainbench.config import load_config
        with tempfile.TemporaryDirectory() as directory:
            cfg = fixture(Path(directory))
            contract = load_config(cfg.contract)
            for domain in contract.domains.values():
                task = domain.dataset_dir / "task-0"
                for name in REQUIRED_FILES[domain.benchmark]:
                    path = task / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    if not path.exists():
                        path.write_text("")
            gateways = []
            class Gateway:
                container_url = "http://localhost:1"
                def __init__(self, app):
                    self.stopped = False
                    gateways.append(self)
                async def start(self):
                    return self
                async def stop(self):
                    self.stopped = True
            active = peak = 0
            async def attempt(task, *args, **kwargs):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(.002)
                active -= 1
                return {"task_id": task.id, "status": "ok", "verifier_status": "ok", "answer": "saved",
                        "artifacts": {"verifier": {"reward": .75, "success": True, "task_id": task.id}}}
            shared = asyncio.Semaphore(1)
            with patch("skilltrainbench.evaluate.LocalGatewayServer", Gateway), \
                 patch("skilltrainbench.evaluate.fetch_prices", AsyncMock(return_value={})), \
                 patch("skilltrainbench.evaluate.harbor.run_attempt", attempt):
                results = await asyncio.gather(*[evaluate.run_eval(
                    contract, domain, skill_dir=cfg.path(f"seeds/{domain}"),
                    out=Path(directory) / "results" / domain, arms=["baseline", "placebo", "skill"],
                    task_ids=["task-0"], upstream_base_url="https://invalid.example", upstream_key=None,
                    task_semaphore=shared) for domain in cfg.domains])
            self.assertEqual(peak, 1)
            self.assertEqual(len(gateways), 4)
            self.assertTrue(all(g.stopped for g in gateways))
            self.assertEqual(results[0]["summary"]["skill_rate"], .75)
            self.assertEqual(results[1]["summary"]["skill_rate"], 1)

    async def test_gateway_startup_failure_closes_started_resources(self):
        from skilltrainbench.config import load_config
        with tempfile.TemporaryDirectory() as directory:
            cfg = fixture(Path(directory))
            contract = load_config(cfg.contract)
            task = contract.domain("hle").dataset_dir / "task-0"
            for name in REQUIRED_FILES["hlebench"]:
                path = task / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    path.write_text("")
            gateways = []
            class Gateway:
                def __init__(self, app):
                    self.stopped = False
                    gateways.append(self)
                async def start(self):
                    if len(gateways) == 2:
                        raise RuntimeError("port failure")
                    return self
                async def stop(self):
                    self.stopped = True
            with patch("skilltrainbench.evaluate.LocalGatewayServer", Gateway), \
                 patch("skilltrainbench.evaluate.fetch_prices", AsyncMock(return_value={})):
                with self.assertRaisesRegex(RuntimeError, "port failure"):
                    await evaluate.run_eval(contract, "hle", skill_dir=None, out=Path(directory) / "eval",
                                            arms=["baseline"], task_ids=["task-0"],
                                            upstream_base_url="https://invalid.example", upstream_key=None)
            self.assertEqual(len(gateways), 2)
            self.assertTrue(all(g.stopped for g in gateways))

    async def test_global_container_cap_across_suites(self):
        active = peak = 0
        async def attempt(*args, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(.003)
            active -= 1
            return {"status": "ok"}
        sem = asyncio.Semaphore(2)
        task = Task("id", "name", "hlebench", Path("/tmp"), 1)
        with patch("skilltrainbench.evaluate.harbor.run_attempt", attempt):
            await asyncio.gather(*[evaluate._attempt_with_retries(
                task, None, asyncio.Semaphore(4), registry=None, tags={}, task_semaphore=sem) for _ in range(10)])
        self.assertEqual(peak, 2)

    async def test_failed_attempt_cancels_siblings_before_return(self):
        stopped = asyncio.Event()
        async def sibling():
            try:
                await asyncio.sleep(100)
            finally:
                stopped.set()
        async def failed():
            await asyncio.sleep(.003)
            raise RuntimeError("failure")
        with self.assertRaises(RuntimeError):
            await evaluate._gather_cancel_on_error(sibling(), failed())
        self.assertTrue(stopped.is_set())

    def test_default_config_loads(self):
        cfg = load_settings(Path(__file__).resolve().parents[1] / "autoresearch.toml")
        self.assertEqual(cfg.optimizer_model, "gpt-6-astra")

    def test_score_validation_rejects_missing_duplicate_and_nan(self):
        base = {"tasks": ["a", "b"], "arms": ["skill"], "summary": {},
                "per_task": [{"task_name": "a", "skill": .1}, {"task_name": "b", "skill": .2}]}
        for value in (None, float("nan"), True):
            base["per_task"][0]["skill"] = value
            with self.assertRaises(ValueError):
                complete_scores(base, ["a", "b"], ["skill"])
        base["per_task"] = [{"task_name": "a", "skill": 1}] * 2
        with self.assertRaises(ValueError):
            complete_scores(base, ["a", "b"], ["skill"])


if __name__ == "__main__":
    unittest.main()
