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
from agents import Model, ModelResponse, ShellCallOutcome, ShellCommandOutput, ShellResult
from agents.usage import Usage
from openai import AsyncOpenAI
from openai.types.responses import ResponseFunctionShellToolCall, ResponseOutputMessage

from skilltrainbench.research.engine import Experiment, StopResearch
from skilltrainbench.research.optimizer import AstraResearcher, MeteredResponsesModel
from skilltrainbench.research.storage import read_json
from skilltrainbench.research.workspace import ResearchWorkspace, read_submission
from test_research import FakeEvaluator, FakeResearchers, fixture, skill


def message(text):
    return ResponseOutputMessage(id="msg_test", type="message", role="assistant", status="completed",
                                 content=[{"type": "output_text", "text": text, "annotations": []}])


class ScriptedModel(Model):
    def __init__(self, steps):
        self.steps, self.inputs = steps, []

    async def get_response(self, *args, **kwargs):
        self.inputs.append(kwargs["input"])
        index = len(self.inputs) - 1
        output = self.steps[index]
        if callable(output):
            output = output()
        return ModelResponse(output=[output], usage=Usage(requests=1, input_tokens=10, output_tokens=10,
                                                          total_tokens=20), response_id=f"resp_{index}")

    async def stream_response(self, *args, **kwargs):
        raise AssertionError("streaming is not used")
        yield


def shell_call(index, command):
    return ResponseFunctionShellToolCall(id=f"shell_{index}", call_id=f"call_{index}", type="shell_call",
        status="completed", action={"commands": [command], "timeout_ms": 1000, "max_output_length": 4000})


class SDKResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = fixture(self.root)
        self.evaluator, self.researchers = FakeEvaluator(), FakeResearchers()
        self.exp = Experiment(self.cfg, self.evaluator, self.researchers)
        self.exp.initialize()

    async def test_health_advances_while_hle_bootstrap_is_blocked(self):
        release, health_researched = asyncio.Event(), asyncio.Event()
        async def evaluate(contract, domain, **kw):
            if domain == "hle":
                await release.wait()
            if domain == "health" and "dev-g0002" in str(kw["out"]):
                health_researched.set()
            return await self.evaluator(contract, domain, **kw)
        self.exp.evaluator = evaluate
        task = asyncio.create_task(self.exp.run())
        try:
            await asyncio.wait_for(health_researched.wait(), 3)
            self.assertNotIn("hle", self.exp.state.get("controls", {}))
            self.assertIn("health", self.exp.state["champions"])
        finally:
            release.set()
            await task

    async def test_refills_without_waiting_for_slow_sibling(self):
        self.exp.cfg = replace(self.cfg, max_inflight_candidates_per_domain=2)
        release, next_round = asyncio.Event(), asyncio.Event()
        active = {"health": 0, "hle": 0}
        peaks = active.copy()
        async def evaluate(contract, domain, **kw):
            candidate = kw["skill_dir"].parent.name if kw["skill_dir"] else "controls"
            active[domain] += 1
            peaks[domain] = max(peaks[domain], active[domain])
            try:
                if domain == "health" and candidate == "g0001-c02":
                    await release.wait()
                if domain == "health" and candidate == "g0002-c01":
                    next_round.set()
                return await self.evaluator(contract, domain, **kw)
            finally:
                active[domain] -= 1
        self.exp.evaluator = evaluate
        task = asyncio.create_task(self.exp.run())
        try:
            await asyncio.wait_for(next_round.wait(), 3)
            self.assertEqual(self.exp.state["candidates"]["health"]["g0001-c02"]["status"], "pending")
        finally:
            release.set()
            await task
        self.assertLessEqual(max(peaks.values()), 2)

    async def test_domain_failure_does_not_stop_other_researcher(self):
        async def evaluate(contract, domain, **kw):
            if domain == "hle" and kw["skill_dir"] is None:
                raise RuntimeError("provider failed")
            return await self.evaluator(contract, domain, **kw)
        self.exp.evaluator = evaluate
        with self.assertRaisesRegex(RuntimeError, "hle: control"):
            await self.exp.run()
        self.assertEqual(self.exp.state["agents"]["hle"]["status"], "failed")
        self.assertEqual(self.exp.state["agents"]["health"]["status"], "complete")
        self.assertEqual(self.exp.state["champions"]["health"], "g0002-c01")

    async def test_submission_is_immediate_idempotent_and_capacity_limited(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select()
        self.exp.cfg = replace(self.cfg, max_inflight_candidates_per_domain=1)
        receipt = self.exp.submit_candidate("health", 1, 2, "first", "seed", "hypothesis", skill(.8))
        self.assertEqual(receipt["status"], "pending")
        self.assertEqual(len(self.evaluator.calls), 1)
        again = self.exp.submit_candidate("health", 1, 2, "first", "seed", "hypothesis", skill(.8))
        self.assertEqual(receipt, again)
        with self.assertRaisesRegex(ValueError, "different content"):
            self.exp.submit_candidate("health", 1, 2, "first", "seed", "changed", skill(.8))
        with self.assertRaisesRegex(ValueError, "pool is full"):
            self.exp.submit_candidate("health", 1, 2, "second", "seed", "hypothesis", skill(.9))
        await asyncio.gather(*self.exp.jobs["health"].values())
        self.assertEqual(len(self.evaluator.calls), 2)

    async def test_workspace_contains_only_dev_data_and_outbox_is_nonblocking(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select()
        (self.root / ".env").write_text("OPENAI_API_KEY=secret")
        (self.root / "rsi-hack.pem").write_text("private")
        holdout = self.exp.root / "evaluations/health/holdout-winner-r0"
        holdout.mkdir(parents=True)
        (holdout / "eval_result.json").write_text("holdout secret")
        workspace = ResearchWorkspace(self.exp, "health")
        workspace.prepare()
        workspace.generation, workspace.allowance = 1, 1
        self.assertEqual({p.name for p in (workspace.view / "tasks").iterdir()}, set(self.exp.splits["health"]["dev"]))
        self.assertFalse(list(workspace.view.rglob("*.pem")))
        self.assertFalse(list(workspace.view.rglob(".env")))
        self.assertFalse(list(workspace.view.rglob("holdout*")))
        outbox = workspace.work / "outbox" / "test"
        outbox.mkdir()
        (outbox / "request.json").write_text(json.dumps({"parent_id": "seed", "hypothesis": "test"}))
        (outbox / "SKILL.md").write_text(skill(.8))
        workspace.collect_submissions()
        self.assertFalse(self.exp.jobs["health"])
        (outbox / "READY").touch()
        workspace.collect_submissions()
        receipt = read_json(workspace.view / "receipts/test.json")
        self.assertEqual(receipt["status"], "pending")
        workspace.collect_submissions()
        self.assertEqual(len(self.exp.jobs["health"]), 1)
        await asyncio.gather(*self.exp.jobs["health"].values())

    def test_submission_cannot_read_symlinks_or_non_regular_files(self):
        root = self.root / "work"
        root.mkdir()
        (self.root / "secret").write_text("secret")
        (root / "link").symlink_to(self.root / "secret")
        with self.assertRaises(OSError):
            read_submission(root, Path("link"), 100)
        (root / "outside").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            read_submission(root, Path("outside/secret"), 100)
        os.mkfifo(root / "fifo")
        with self.assertRaises(ValueError):
            read_submission(root, Path("fifo"), 100)
        with self.assertRaises(ValueError):
            read_submission(root, Path("../secret"), 100)

    async def test_actual_sdk_shell_loop_submits_then_continues_and_preserves_session(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select()
        release = asyncio.Event()
        async def blocked(contract, domain, **kw):
            await release.wait()
            return await self.evaluator(contract, domain, **kw)
        self.exp.evaluator = blocked
        owner = self
        class TestWorkspace(ResearchWorkspace):
            async def start(self):
                self.prepare()
            async def shell(self, request):
                command = request.data.action.commands[0]
                if command == "submit":
                    outbox = self.work / "outbox/hypothesis"
                    outbox.mkdir(exist_ok=True)
                    (outbox / "SKILL.md").write_text(skill(.8))
                    (outbox / "request.json").write_text(json.dumps({"parent_id": "seed", "hypothesis": "test"}))
                    (outbox / "READY").touch()
                    self.collect_submissions()
                elif command == "analyse while running":
                    owner.assertEqual(owner.exp.state["candidates"]["health"]["g0001-c01"]["status"], "pending")
                return ShellResult(output=[ShellCommandOutput(stdout="analysis output", outcome=ShellCallOutcome(type="exit", exit_code=0))])
            async def close(self):
                pass
        workspace = TestWorkspace(self.exp, "health")
        model = ScriptedModel([shell_call(1, "submit"), shell_call(2, "analyse while running"), message("Round findings")])
        researcher = AstraResearcher(self.exp, "health", model=model, workspace=workspace)
        try:
            self.assertEqual([type(t).__name__ for t in researcher.agent.tools], ["ShellTool", "WebSearchTool"])
            await researcher.investigate(1, 1)
            items = await researcher.session.get_items()
            self.assertIn("analysis output", json.dumps(items))
            self.assertEqual(len(model.inputs), 3)
            self.assertEqual(self.exp.state["candidates"]["health"]["g0001-c01"]["status"], "pending")
        finally:
            release.set()
            await asyncio.gather(*self.exp.jobs["health"].values())
            await researcher.close()
        resumed_model = ScriptedModel([message("Remembered findings")])
        resumed = AstraResearcher(self.exp, "health", model=resumed_model, workspace=workspace)
        try:
            await resumed.investigate(2, 1)
            self.assertIn("Round findings", json.dumps(resumed_model.inputs[0]))
        finally:
            await resumed.close()

    async def test_metered_sdk_responses_transport_counts_retries_and_hard_budget(self):
        requests = []
        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            self.assertEqual(body["model"], "gpt-6-astra")
            self.assertFalse(body["store"])
            self.assertEqual({t["type"] for t in body["tools"]}, {"shell", "web_search"})
            if len(requests) == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "rate limit"}})
            return httpx.Response(200, json={"id": "resp_1", "object": "response", "created_at": 1,
                "model": "gpt-6-astra", "status": "completed", "output": [message("analysis").model_dump()],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})
        class TestWorkspace(ResearchWorkspace):
            async def start(self):
                self.prepare()
            async def close(self):
                pass
        client = AsyncOpenAI(api_key="test-key", max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        model = MeteredResponsesModel(self.exp, "health", client)
        researcher = AstraResearcher(self.exp, "health", model=model, workspace=TestWorkspace(self.exp, "health"))
        try:
            await researcher.investigate(1, 1)
            events = [json.loads(line) for line in (self.exp.root / "events.jsonl").read_text().splitlines()]
            self.assertTrue(any(e["event"] == "optimizer_retry" and e["http_status"] == 429 for e in events))
            response = next(e for e in events if e["event"] == "optimizer_response")
            self.assertEqual(response["total_tokens"], 15)
            self.assertGreaterEqual(response["elapsed_seconds"], 0)
            self.assertEqual(self.exp.state["optimizer_calls"], 2)
            self.assertEqual(len(requests), 2)
            self.exp.cfg = replace(self.cfg, max_optimizer_calls=2)
            with self.assertRaises(StopResearch):
                await researcher.investigate(2, 1)
            self.assertEqual(len(requests), 2)
        finally:
            await researcher.close()
            await client.close()

    async def test_shell_logs_before_execution_and_reports_outcomes(self):
        workspace = ResearchWorkspace(self.exp, "health")
        workspace.prepare()
        async def execute(*args, **kwargs):
            event = json.loads((self.exp.root / "events.jsonl").read_text().splitlines()[-1])
            self.assertEqual(event["event"], "research_shell_started")
            return 0, "analysis output", ""
        from types import SimpleNamespace
        request = SimpleNamespace(data=shell_call(1, "echo analysis"))
        with patch("skilltrainbench.research.workspace.command_output", new=AsyncMock(side_effect=execute)):
            result = await workspace.shell(request)
        self.assertEqual(result.output[0].stdout, "analysis output")
        event = json.loads((self.exp.root / "events.jsonl").read_text().splitlines()[-1])
        self.assertEqual(event["event"], "research_shell")
        self.assertEqual(event["outcomes"], [{"type": "exit", "exit_code": 0}])

    async def test_interrupted_job_resumes_without_duplicate_submission(self):
        await self.exp.evaluate_candidate("health", "seed")
        self.exp.select()
        self.exp.state["agents"]["health"].update(active_generation=1, active_allowance=1)
        self.exp.save()
        receipt = self.exp.submit_candidate("health", 1, 1, "key", "seed", "test", skill(.8))
        task = self.exp.jobs["health"][receipt["candidate_id"]]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        resumed = Experiment(self.cfg, self.evaluator, self.researchers)
        resumed.initialize()
        same = resumed.submit_candidate("health", 1, 1, "key", "seed", "test", skill(.8))
        self.assertEqual(receipt, same)
        self.assertEqual(len(resumed.state["candidates"]["health"]), 2)
        await resumed.evaluate_and_select("health", receipt["candidate_id"])
        self.assertEqual(resumed.state["champions"]["health"], receipt["candidate_id"])


if __name__ == "__main__":
    unittest.main()
