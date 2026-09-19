"""Persistent researcher workspaces, generic Docker shell, and file-based submissions."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

from agents import ShellCallOutcome, ShellCommandOutput, ShellResult

from .storage import write_json


WORKSPACE_README = '''# Research workspace

Use bash, Python, rg, jq and git freely to investigate, write scripts, take notes,
and develop skills. Online research is available through the SDK web_search tool.
The shell container has no network; it cannot access host services or credentials.

/research/code/              source code, documentation and frozen benchmark contract
/research/tasks/             this domain's development instructions and environment assets
/research/brief.json         scoring contract and generic grader source
/research/status.json        live candidates, scores, champion, round and capacity
/research/candidates/        immutable evaluated skills (copy to /workspace to edit)
/research/evaluations/       development suite results and logs, refreshed as they change
/research/receipts/          acknowledgments for submitted jobs
/workspace/                 persistent writable notes, scripts and drafts
/workspace/outbox/           candidate submission directories

To submit a hypothesis, create /workspace/outbox/<unique-name>/ containing:
1. SKILL.md: a complete skill with YAML name and description frontmatter.
2. request.json: {"parent_id": "seed", "hypothesis": "What this tests and why"}
3. READY: an empty file, created LAST, after both files have been fully written.

The harness watches READY files while you continue working. It validates and queues
each request, then writes /research/receipts/<unique-name>.json with a job_id (or an
error). Jobs run asynchronously; use status.json and evaluations to inspect results.
Do not modify a submitted directory. Use a new name for a revised hypothesis.
Submissions inherit the parent's supporting files; only SKILL.md is changed.
Do not busy-poll. Once your current allowance is used or all slots are full, finish
this research turn with findings and next steps. The harness wakes you on new results.
The research workspace persists across turns and restarts. Holdout files, API keys,
the host filesystem and the Docker socket are not mounted here.
'''


async def command_output(*args, timeout=120, limit=20000):
    """Drain pipes without retaining unbounded command output."""
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
    async def read(stream):
        parts, remaining = [], limit
        while chunk := await stream.read(65536):
            if remaining:
                parts.append(chunk[:remaining])
                remaining = max(0, remaining - len(chunk))
        return b"".join(parts).decode(errors="replace")
    readers = [asyncio.create_task(read(proc.stdout)), asyncio.create_task(read(proc.stderr))]
    try:
        async with asyncio.timeout(timeout):
            await proc.wait()
            stdout, stderr = await asyncio.gather(*readers)
        return proc.returncode, stdout, stderr
    except BaseException:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        await asyncio.gather(*readers, return_exceptions=True)
        raise


def read_submission(root: Path, relative: Path, limit: int) -> str:
    """Read untrusted container-written files using no-follow directory descriptors."""
    if relative.is_absolute() or any(p in {".", ".."} for p in relative.parts):
        raise ValueError("invalid submission path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        file_fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("submission must be a regular file within the size limit")
            raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("submission exceeds the size limit")
            return raw.decode("utf-8")
    finally:
        os.close(fd)


class ResearchWorkspace:
    def __init__(self, experiment, domain):
        self.exp, self.domain = experiment, domain
        self.root = experiment.root / "researchers" / domain
        self.work, self.view = self.root / "work", self.root / "view"
        self.container = f"stbench-research-{domain}-{uuid.uuid4().hex[:12]}"
        self.started = False
        self.generation = self.allowance = 0
        self.copied = {}

    def copy_tree(self, source, target, *, allowed=None, redact_text=False):
        from .engine import redact
        if source.is_symlink() or not source.exists():
            return
        for directory, dirs, files in os.walk(source, followlinks=False):
            base = Path(directory)
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", ".venv"}
                       and not (base / d).is_symlink()]
            for name in files:
                path = base / name
                if path.is_symlink() or (allowed is not None and name not in allowed):
                    continue
                rel = path.relative_to(source)
                if path.suffix in {".pyc", ".pem"} or name.startswith(".env"):
                    continue
                info = path.stat()
                signature = (info.st_mtime_ns, info.st_size)
                dest = target / rel
                if self.copied.get(str(dest)) == signature and dest.exists():
                    continue
                if info.st_size > 32_000_000:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                if redact_text:
                    dest.write_text(redact(path.read_text(errors="replace")))
                else:
                    shutil.copyfile(path, dest)
                self.copied[str(dest)] = signature

    def prepare(self):
        (self.work / "outbox").mkdir(parents=True, exist_ok=True)
        (self.view / "receipts").mkdir(parents=True, exist_ok=True)
        (self.view / "README.md").write_text(WORKSPACE_README)
        code = self.view / "code"
        code.mkdir(exist_ok=True)
        for name in ("src", "docs", "tests"):
            self.copy_tree(self.exp.cfg.root / name, code / name)
        for name in ("README.md", "pyproject.toml", "uv.lock"):
            source = self.exp.cfg.root / name
            if source.is_file() and not source.is_symlink():
                shutil.copyfile(source, code / name)
        shutil.copyfile(self.exp.cfg.contract, code / "hackathon.toml")
        write_json(self.view / "brief.json", self.exp.research_brief(self.domain))
        task_root = self.exp.contract.domain(self.domain).dataset_dir
        for name in self.exp.splits[self.domain]["dev"]:
            source, target = task_root / name, self.view / "tasks" / name
            target.mkdir(parents=True, exist_ok=True)
            for filename in ("instruction.md", "task.toml"):
                if (source / filename).is_file():
                    shutil.copyfile(source / filename, target / filename)
            self.copy_tree(source / "environment", target / "environment")
        self.refresh()

    def refresh(self):
        records = self.exp.state["candidates"][self.domain]
        write_json(self.view / "status.json", {
            "domain": self.domain, "generation": self.generation, "submission_allowance": self.allowance,
            "champion": self.exp.state["champions"].get(self.domain),
            "controls": self.exp.state.get("controls", {}).get(self.domain),
            "slots_free": max(0, self.exp.cfg.max_inflight_candidates_per_domain
                              - sum(c["status"] == "pending" for c in records.values())),
            "candidates": list(records.values())})
        for cid, record in list(records.items()):
            if record["status"] != "rejected":
                self.copy_tree(self.exp.skill_dir(self.domain, cid), self.view / "candidates" / cid)
        allowed = {"suite.json", "eval_result.json", "attempts.jsonl", "learner_ledger.jsonl", "grader_ledger.jsonl",
                   "trajectory.json", "response.txt", "trial.log", "verdicts.json", "judgment.json", "test-stdout.txt"}
        for suite in (self.exp.root / "evaluations" / self.domain).glob("dev-*"):
            self.copy_tree(suite, self.view / "evaluations" / suite.name, allowed=allowed, redact_text=True)

    def collect_submissions(self):
        from .engine import redact
        for ready in sorted((self.work / "outbox").glob("*/READY")):
            name = ready.parent.name
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name):
                continue
            receipt = self.view / "receipts" / f"{name}.json"
            if receipt.exists():
                continue
            try:
                base = Path("outbox") / name
                read_submission(self.work, base / "READY", 1024)
                request = json.loads(read_submission(self.work, base / "request.json", 20000))
                text = read_submission(self.work, base / "SKILL.md", self.exp.cfg.max_skill_chars * 4)
                if not isinstance(request, dict) or not all(isinstance(request.get(k), str)
                                                          for k in ("parent_id", "hypothesis")):
                    raise ValueError("request.json needs string parent_id and hypothesis fields")
                result = self.exp.submit_candidate(self.domain, self.generation, self.allowance, name,
                                                    request["parent_id"], request["hypothesis"], text)
            except (ValueError, OSError, KeyError) as error:
                result = {"accepted": False, "error": redact(str(error))[:2000]}
            write_json(receipt, result)

    async def watch(self):
        while True:
            self.collect_submissions()
            self.refresh()
            await asyncio.sleep(1)

    async def start(self):
        if self.started:
            return
        self.prepare()
        async with self.exp.research_image_lock:
            code, _, _ = await command_output("docker", "image", "inspect", self.exp.cfg.researcher_image)
            if code:
                dockerfile = Path(__file__).with_name("researcher.Dockerfile")
                code, _, stderr = await command_output("docker", "build", "-t", self.exp.cfg.researcher_image,
                                                       "-f", str(dockerfile), str(dockerfile.parent), timeout=600)
                if code:
                    raise RuntimeError(f"researcher image build failed: {stderr[-2000:]}")
        args = ["docker", "run", "-d", "--init", "--name", self.container, "--network", "none",
                "--cpus", "1", "--memory", "2g", "--pids-limit", "128", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
                "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/workspace", "-w", "/workspace",
                "--mount", f"type=bind,src={self.work.resolve()},dst=/workspace",
                "--mount", f"type=bind,src={self.view.resolve()},dst=/research,readonly",
                self.exp.cfg.researcher_image, "sleep", "infinity"]
        try:
            code, _, stderr = await command_output(*args)
            if code:
                raise RuntimeError(f"researcher container failed to start: {stderr[-2000:]}")
            self.started = True
        except BaseException:
            await command_output("docker", "rm", "-f", self.container)
            raise

    async def shell(self, request):
        from .engine import redact
        action = request.data.action
        timeout = min(120, max(1, (action.timeout_ms or 60000) / 1000))
        limit = min(20000, max(1000, action.max_output_length or 12000))
        outputs = []
        for cmd in action.commands[:20]:
            try:
                code, stdout, stderr = await command_output(
                    "docker", "exec", self.container, "timeout", "--signal=KILL", f"{timeout}s",
                    "bash", "-lc", cmd, timeout=timeout + 10, limit=limit)
                outcome = ShellCallOutcome(type="timeout" if code in {124, 137} else "exit", exit_code=code)
            except TimeoutError:
                stdout, stderr = "", "Shell command timed out"
                outcome = ShellCallOutcome(type="timeout")
            outputs.append(ShellCommandOutput(stdout=redact(stdout), stderr=redact(stderr), outcome=outcome, command=cmd))
        self.collect_submissions()
        self.refresh()
        self.exp.event("research_shell", domain=self.domain, commands=len(outputs))
        return ShellResult(output=outputs, max_output_length=limit)

    async def close(self):
        if self.started:
            await command_output("docker", "rm", "-f", self.container)
            self.started = False
