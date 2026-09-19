from __future__ import annotations

import asyncio
import json
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from skilltrainbench.research.engine import Experiment, StopResearch
from skilltrainbench.research.settings import Domain, load_settings
from skilltrainbench.research.storage import development_layout, read_json, split_tasks
from test_research import FakeEvaluator, FakeResearchers, fixture, skill


class SubsetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cfg = fixture(self.root)
        files = []
        for index, names in enumerate(([0], [1], [2], [3, 4, 5])):
            filename = f"subset-{index}.txt"
            (self.root / filename).write_text("\n".join(f"task-{n}" for n in names))
            files.append(filename)
        (self.root / "holdout.txt").write_text("task-6\ntask-7\n")
        (self.root / "groups.json").write_text(json.dumps({f"task-{i}": f"group-{i % 3}" for i in range(6)}))
        self.cfg = replace(cfg, generations=1, candidates_per_domain=1, max_evaluations=80,
                           domains={d: Domain(f"seeds/{d}", dev_subset_files=files,
                                              holdout_file="holdout.txt", dev_groups_file="groups.json")
                                    for d in cfg.domains})
        self.evaluator = FakeEvaluator()
        self.exp = Experiment(self.cfg, self.evaluator, FakeResearchers())
        self.exp.initialize()

    async def test_all_subsets_controls_resume_and_holdout(self):
        await self.exp.run()
        self.assertEqual(self.exp.state["evaluations_started"], 24)  # 2 domains * (controls + seed + candidate) * 4
        self.assertLessEqual(self.evaluator.peak, self.cfg.max_parallel_suites)
        self.assertGreater(self.evaluator.peak, 1)
        for domain in self.cfg.domains:
            scores = self.exp.state["candidates"][domain]["g0001-c01"]["scores"]
            self.assertEqual(len(scores["per_task"]), 6)
            self.assertEqual(len(scores["subsets"]), 4)
            self.assertEqual(len(scores["groups"]), 3)
            self.assertEqual(len(self.exp.state["controls"][domain]["baseline"]["subsets"]), 4)
        self.assertFalse(self.exp.reserved_suites)
        resumed = Experiment(self.cfg, self.evaluator, FakeResearchers())
        resumed.initialize()
        await resumed.run()
        self.assertEqual(len(self.evaluator.calls), 24)
        report = await resumed.finalize()
        self.assertTrue(all(row["status"] == "complete" for row in report["domains"].values()))
        self.assertEqual(len(self.evaluator.calls), 28)  # Holdout remains one whole suite per role/domain.
        self.assertTrue(all(kw["task_ids"] == ["task-6", "task-7"] for _, kw in self.evaluator.calls[24:]))

    async def test_unequal_subsets_do_not_overweight_a_lucky_small_subset(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select("health")
        async def biased(contract, domain, **kwargs):
            result = await self.evaluator(contract, domain, **kwargs)
            for row in result["per_task"]:
                row["skill"] = 1 if row["task_name"] == "task-0" else 0
            return result
        self.exp.evaluator = biased
        self.exp.submit_candidate("health", 1, 1, "biased", "seed", "Test narrow gain", skill(.9))
        await asyncio.gather(*self.exp.jobs["health"].values())
        scores = self.exp.state["candidates"]["health"]["g0001-c01"]["scores"]
        self.assertAlmostEqual(scores["mean"], 1 / 6)
        self.assertEqual(scores["subsets"]["s01"]["mean"], 1)
        self.assertAlmostEqual(scores["groups"]["group-0"]["mean"], .5)
        self.assertEqual(self.exp.state["champions"]["health"], "seed")

    async def test_pending_and_failed_subset_never_promote_partial_candidate(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select("health")
        waiting, release = asyncio.Event(), asyncio.Event()
        async def delayed(contract, domain, **kwargs):
            if "task-3" in kwargs["task_ids"]:
                waiting.set()
                await release.wait()
                raise RuntimeError("fourth subset failed")
            return await self.evaluator(contract, domain, **kwargs)
        self.exp.evaluator = delayed
        self.exp.submit_candidate("health", 1, 1, "delayed", "seed", "Test broad gain", skill(.9))
        try:
            await asyncio.wait_for(waiting.wait(), 2)
            self.assertEqual(self.exp.state["candidates"]["health"]["g0001-c01"]["status"], "pending")
            self.assertEqual(self.exp.state["champions"]["health"], "seed")
        finally:
            release.set()
            await asyncio.gather(*self.exp.jobs["health"].values())
        record = self.exp.state["candidates"]["health"]["g0001-c01"]
        self.assertEqual(record["status"], "failed")
        self.assertNotIn("scores", record)
        self.assertEqual(self.exp.state["champions"]["health"], "seed")
        self.exp.evaluator = self.evaluator
        before = len(self.evaluator.calls)
        await self.exp.evaluate_and_select("health", "g0001-c01")
        self.assertEqual(len(self.evaluator.calls), before + 1)  # Three completed subsets are reused.
        self.assertEqual(self.exp.state["champions"]["health"], "g0001-c01")

    async def test_budget_reserves_whole_candidate_before_admission(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select("health")
        self.exp.cfg = replace(self.cfg, candidates_per_domain=2, max_evaluations=15)
        self.exp.submit_candidate("health", 1, 2, "first", "seed", "First hypothesis", skill(.8))
        with self.assertRaisesRegex(StopResearch, "all development subsets"):
            self.exp.submit_candidate("health", 1, 2, "second", "seed", "Second hypothesis", skill(.9))
        self.assertNotIn("g0001-c02", self.exp.state["candidates"]["health"])
        await asyncio.gather(*self.exp.jobs["health"].values())
        self.assertFalse(self.exp.reserved_suites)

    async def test_repeats_evaluate_the_same_subsets_and_average_per_task(self):
        cfg = replace(self.cfg, output=self.root / "repeats", repeats=2)
        exp = Experiment(cfg, self.evaluator, FakeResearchers())
        exp.initialize()
        await exp.evaluate_candidate("health", "seed")
        self.assertEqual(len(self.evaluator.calls), 8)
        scores = exp.state["candidates"]["health"]["seed"]["scores"]
        self.assertEqual(len(scores["repeat_means"]), 2)
        self.assertAlmostEqual(scores["mean"], .2)

    def test_overlap_holdout_leakage_and_changed_layout_are_rejected(self):
        (self.root / "subset-0.txt").write_text("task-6")
        with self.assertRaisesRegex(ValueError, "overlap"):
            split_tasks(self.cfg, self.exp.contract)
        (self.root / "subset-0.txt").write_text("task-1")
        with self.assertRaisesRegex(ValueError, "overlap"):
            split_tasks(self.cfg, self.exp.contract)
        (self.root / "subset-0.txt").write_text("task-0")
        groups = read_json(self.root / "groups.json")
        groups["task-6"] = "heldout"
        (self.root / "groups.json").write_text(json.dumps(groups))
        with self.assertRaisesRegex(ValueError, "exactly the development tasks"):
            Experiment(self.cfg).initialize()
        del groups["task-6"]
        groups["task-0"] = "changed group"
        (self.root / "groups.json").write_text(json.dumps(groups))
        with self.assertRaisesRegex(ValueError, "changed"):
            Experiment(self.cfg).initialize()

    def test_checked_in_preset_has_four_balanced_disjoint_subsets(self):
        cfg = load_settings(Path(__file__).resolve().parents[1] / "autoresearch.3h.toml")
        def names(path):
            return re.split(r"[,\s]+", cfg.path(path).read_text().strip())
        splits = {d: {"dev": [task for filename in spec.dev_subset_files for task in names(filename)],
                      "holdout": names(spec.holdout_file)} for d, spec in cfg.domains.items()}
        subsets, groups = development_layout(cfg, splits)
        self.assertEqual(cfg.candidates_per_domain, 2)
        self.assertEqual(cfg.max_inflight_candidates_per_domain, 2)
        for domain in cfg.domains:
            self.assertEqual(len(subsets[domain]), 4)
            self.assertEqual(len(splits[domain]["dev"]), 12)
            self.assertEqual(len(set(splits[domain]["dev"])), 12)
            self.assertFalse(set(splits[domain]["dev"]) & set(splits[domain]["holdout"]))
            for tasks in subsets[domain].values():
                self.assertEqual(len(tasks), 3)
                self.assertEqual(len({groups[domain][task] for task in tasks}), 3)
        self.assertEqual(set(groups["hle"].values()), {"Chemistry", "Engineering", "Computer Science/AI"})


if __name__ == "__main__":
    unittest.main()
