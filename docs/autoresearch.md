# Health and HLE skill autoresearch

`stbench-research` uses **GPT-6 Astra (`gpt-6-astra`)** as two independent **OpenAI Agents SDK** researchers using the Responses API to improve the two draft skills in `submissions/aditya-tim/`. It evaluates them through this repository's existing Harbor/Docker runtime. The learner remains **`zai-glm-5-3-flash`**, and the graders and task limits remain those in `hackathon.toml`.

The loop takes the useful pattern from [uditgoenka/autoresearch](https://github.com/uditgoenka/autoresearch): form a hypothesis, make a constrained change, measure it, retain improvements, and repeat. This implementation uses immutable candidate folders and JSON checkpoints instead of editing or reverting the working tree.

## Run it

Requirements: x86_64 Linux, Docker Engine with Compose v2 and Buildx, Python 3.12+, uv, downloaded benchmark data, and API access to the configured models. The bootstrap script installs Ubuntu's `docker-compose-v2` and `docker-buildx` packages. Verify them with `docker compose version` and `docker buildx version`; Harbor needs Buildx even when Docker itself is working.

```bash
uv sync --locked
# If you already have .env, add the missing entries instead of replacing it.
cp -n .env_example .env
chmod 600 .env
# Edit .env: RUNWARE_API_KEY=... and OPENAI_API_KEY=...
uv run stbench data pull

# Free: freeze inputs/splits and show workload; makes no API calls.
uv run stbench-research plan --config autoresearch.smoke.toml
uv run stbench-research doctor --config autoresearch.smoke.toml

# Paid: one generation on two dev tasks per domain; verifies real plumbing.
uv run stbench-research run --config autoresearch.smoke.toml

# After the smoke works, initialize and start the full configured experiment.
uv run stbench-research plan
uv run stbench-research run
```

The smoke optimizes on tiny samples and should not be used to choose a final submission. `finalize --config autoresearch.smoke.toml` can also test the holdout plumbing.

`OPENAI_API_KEY` pays for Astra; `RUNWARE_API_KEY` pays for the fixed learner and graders. `HF_TOKEN` is optional. Environment variables already set in the shell take precedence over `.env`. `--env-file /path/to/file` selects another env file. Optional `AUTORESEARCH_OPENAI_BASE_URL` selects the curator's Responses endpoint; it does not reroute the learner. Access to Astra in an app does not establish API access for your key. See [Astra's official model reference](https://developers.openai.com/api/docs/models/gpt-6-astra).

## Three-hour EC2 search

After transferring this version and running `uv sync --locked`, use:

```bash
# Build the shell image before starting the research clock (no paid API calls).
docker build -t stbench-researcher:py312-v1 \
  -f src/skilltrainbench/research/researcher.Dockerfile src/skilltrainbench/research
uv run stbench-research plan --config autoresearch.3h.toml
uv run stbench-research doctor --config autoresearch.3h.toml
uv run stbench-research run --config autoresearch.3h.toml
```

This preset permits **two candidate skills per domain in flight**, each evaluated on
**four disjoint development subsets**. There can be sixteen candidate suites queued
across both researchers; up to ten suites and sixteen benchmark task containers run
at once. Each subset contains three questions. Both researchers share limits of
128 suite starts and 120 Astra HTTP attempts. The search cancels unfinished
work at three hours and preserves completed winners. Actual throughput also depends on
provider latency and quotas; more suites cannot guarantee a specific improvement.

Every candidate sees **12 development questions per domain**. Each HLE subset contains
one Chemistry, one Computer Science/AI, and one Engineering question. Each Health
subset contains one context-seeking, one emergency-referral, and one health-data task.
The checked-in assignments were sampled deterministically with seed 42, using only
category/theme labels. Health draws from the existing 16-task development panel;
HLE draws from the available training tasks after excluding the local holdout.
The original **30 Health / 24 HLE holdout tasks** are unchanged.

Controls and the original skill also run on all four subsets (16 bootstrap suites
across both domains). A candidate is eligible for promotion only after all four
subsets and all repeats finish successfully. The score is the equally weighted mean
over all development questions, so unequal subset sizes cannot distort selection.
`candidate_evaluated`, `leaderboard.json`, `report.md`, and the researcher's workspace
include overall, per-subset, and per-subject/theme scores. All four suite slots in the
evaluation budget are reserved when a candidate is admitted; a candidate that cannot
fit is not launched. Suite concurrency is still bounded separately.

The same four subsets are used for every candidate throughout the experiment. They
are development data available to Astra, not four holdouts or cross-validation folds.
This broadens coverage but does not eliminate development overfitting. The balanced
HLE panel weights the three subjects equally; it is not an estimate weighted by their
different frequencies in the full training dataset. Finalization still uses the
unchanged holdout distribution. After the search, assess the frozen winners separately:

```bash
uv run stbench-research finalize --config autoresearch.3h.toml
```

Finalization runs outside the three-hour search window and does not feed its scores
back to Astra. Use the larger full preset for more reliable development selection.

**Upgrading an existing run:** stop it before replacing code or syncing files into its
checkout. The SDK presets use new output folders (`runs/autoresearch-sdk*`), preserving
old smoke/full artifacts. Runtime/config changes intentionally cannot resume an older
manifest. The four-subset preset uses `runs/autoresearch-sdk-3h-subsets` so the failed
four-question run remains intact and the new experiment gets a fresh three-hour clock.
This update does not modify or restart an already-running remote process.
For a custom config, choose a fresh output directory and increase `max_optimizer_calls`
to account for the SDK's multiple model steps per research round.

## Run on an Apple Silicon Mac

Use Docker Desktop and `autoresearch.local.toml`. This preset keeps the full
configuration's dev/holdout partitions, limits the whole harness to two task
containers, and tries two variants per domain for three generations. The local
plan includes up to 20 suites / 576 task attempts, including optional finalization,
before infrastructure retries. API charges still apply.

The task images are amd64. Enable Docker Desktop's **Use Rosetta for
x86_64/amd64 emulation on Apple Silicon** setting and apply/restart Docker if
needed (as described in the main README). The default emulator has caused agent
installation crashes in this benchmark. Docker Desktop also cannot reproduce the
organizers' Linux network allowlists; skills should continue to work offline.

Add `OPENAI_API_KEY` and `RUNWARE_API_KEY` to the repository's `.env`, then:

```bash
uv run stbench-research doctor --config autoresearch.local.toml
caffeinate -i uv run stbench-research run --config autoresearch.local.toml
```

Keep the Mac plugged in and the lid open; `caffeinate -i` prevents idle sleep
while the command is running. Start with `autoresearch.smoke.toml` instead to
check actual API access and emulation on a small sample. A running EC2 instance
continues billing independently of where this harness runs; stop it in AWS when
you are not using it.

## What it does

Health and HLE each have their own Astra `Agent`, persistent `SQLiteSession`, research workspace, candidate history, and champion. The SDK handles reasoning and tool calling. The only agent tools are **`ShellTool` and `WebSearchTool`**, following the [official SDK guide](https://developers.openai.com/api/docs/guides/agents/sdk), [shell guide](https://developers.openai.com/api/docs/guides/tools-shell), and [web search guide](https://developers.openai.com/api/docs/guides/tools-web-search).

1. Freeze the learner contract, inputs, disjoint splits, and seed skills.
2. Start each domain's controls and seed suite concurrently. Each researcher begins as soon as its own bootstrap finishes; it never waits for the other domain.
3. Astra investigates freely using bash, Python, `rg`, `jq`, and web search. It can read code, inspect development logs, write analysis scripts, keep notes, and choose what to test. There is no prepared evidence bundle or custom `read_failure`/`compare_candidates` tool API.
4. Submit a skill by writing `SKILL.md`, `request.json`, and finally `READY` into a new directory under `/workspace/outbox/`. A Python watcher validates, snapshots, and queues it, publishing a receipt with a job ID. Submission does not wait for evaluation, and Astra can continue investigating while the job runs.
5. The harness runs suites under shared suite/container limits. Completed candidates are ranked immediately. A free candidate slot can start a new research round while slower siblings are still running. When all slots are occupied, Python waits for results without paid model polling.
6. Keep the best development skill and up to `keep_top` parent options. `min_improvement` controls promotions. Final holdout evaluation remains a separate, explicit command.

`generations` now means **SDK research rounds per domain**, independently. Each round may submit up to `candidates_per_domain` skills, with a smaller allowance when fewer slots are free. `max_inflight_candidates_per_domain` caps queued/running candidate jobs for one researcher. `researcher_max_turns` caps SDK model steps within a research round. `generations = 0` continues until a budget, persistent deadline, interruption, or STOP file.

The research instructions explicitly encourage compression, deletion, section ablations, alternative strategies, and rewrites from scratch. An initial multi-candidate batch should explore a shorter skill and a different strategy alongside focused improvements; with one free slot, the researcher should vary approaches over successive submissions. It is also instructed to revisit assumptions and failure patterns when progress stalls. These are research instructions, not enforced experiment quotas. Selection remains based on measured development reward, with equal scores keeping the incumbent; there is no automatic reward for either longer or shorter files.

The researchers' Docker containers are separate from benchmark containers. `/workspace` is writable and persistent. `/research` is a read-only mirror of source code, current-domain development inputs, evaluated skills, scores, and logs. Holdout data, `.env`, SSH keys, the host project, and Docker's socket are not mounted. Shell commands run offline with a 120-second cap; online research uses the SDK's hosted web search. Each researcher container is limited to one CPU and 2 GiB of memory, in addition to the benchmark container cap. Notes and scripts persist across restarts. Source edits in the scratch workspace do not change the evaluator.

The agent is instructed to research general methods, not benchmark answer keys. Broad web access means contamination cannot be ruled out automatically; review final skills for copied examples and answer lookups. SDK conversations are persisted locally in `optimizer/<domain>/session.sqlite`; external SDK tracing is disabled. OpenAI still receives the model inputs, tool outputs, and search requests needed to run the agent.

HealthBench uses the **mean raw rubric reward**: satisfied positive and negative criteria contribute points divided by total positive points. Individual rewards can be negative. The official display additionally clips the aggregate to [0,1]. HLE uses the mean of binary correct/incorrect judgments. The leaderboard subtracts placebo performance; since the development placebo is cached and shared, maximizing raw reward ranks candidates identically to maximizing placebo lift. Local development lift is an estimate, not the private leaderboard score.

An infrastructure error, missing result, nonfinite score, or grader invalidation makes the entire candidate evaluation ineligible. It cannot improve its score by excluding difficult tasks. The original evaluator retries infrastructure failures; a wrong answer is never retried selectively. Candidate repeats average every task equally. `repeats = 2` or `3` can reduce sampling noise at corresponding cost; set this before starting a new experiment. The default one-repeat development ranking is exploratory and susceptible to selection noise.

The checked-in full configuration preserves your existing **16 Health dev / 30 Health validation** task IDs, now used as dev/holdout. HLE gets a deterministic shuffled **24 dev / 24 holdout** split from the downloaded training data. Remaining training tasks are unused. Explicit split files accept comma-separated or whitespace-separated names. These are local partitions of the public training data, not the organizers' private held-out tasks. If you have already tuned on a local holdout, choose a fresh untouched partition before a new experiment.

For multiple development subsets, set a domain's `dev_subset_files` to a list of task-ID
files instead of `dev_file`. The harness rejects empty subsets, unknown tasks, duplicate
IDs within or between subsets, and overlap with holdout. Optional `dev_groups_file`
is a JSON object mapping exactly those development task IDs to subject/theme labels;
only these labels are exposed to the researcher. Assignments and labels are frozen in
the manifest. `repeats = 4` alone repeats the same tasks four times; it does not create
different subsets. Single-subset configurations continue to work.

## Workload and limits

The full default allows up to five candidates per research round and five candidates in flight per domain, ten rounds per domain, five suites at once, two tasks per suite, and a **global cap of ten active benchmark task attempts**. To admit ten suites simultaneously, set `max_parallel_suites = 10`; keeping `max_task_containers = 10` still caps overall load.

The default plan is at most **108 suites / 2,336 task attempts** including controls, original skills, and final holdout comparisons, before infrastructure retries. A task can use many model calls; Health grading can issue several concurrent rubric calls. API request/token rate limits may bottleneck before CPU or RAM. Reduce concurrency if rate limits are frequent.

- `max_evaluations` counts suite starts, including interrupted/failed starts. It persists across resumes. Two suites per domain per repeat are reserved for finalization.
- `max_optimizer_calls` counts every SDK model step and HTTP retry, shared by both researchers. It is no longer a count of single-shot proposal batches. The full preset allows 240 calls; smoke allows 40. Hosted web search may incur additional tool charges. Transient HTTP failures retry with bounded backoff, and each attempt is counted before sending.
- `suite_timeout_seconds` bounds an individual suite; the existing task timeouts remain intact.
- `max_hours` is a persistent wall-clock deadline beginning with the first `run`. It does not reset on restart. Finalization has separate suite timeouts and can run after the search deadline.
- `hackathon.toml` already caps each suite's learner and grader token pools. They are unchanged.
- `usage.json` totals observed tokens and available benchmark cost estimates, including failed attempts. Astra usage is separate; no dollar conversion is assumed. Missing accounting after a crash is unknown spend.

These are workload bounds, **not a hard dollar budget**. Use provider-side spend limits for a monetary cap. Larger machines do not increase provider quotas. Nothing starts paying for API calls until `run` or `finalize`.

## Inspect, stop, resume, and finalize

Progress is printed immediately to the terminal with UTC timestamps and saved as
structured records in `<output>/events.jsonl`. Both researchers report their domain
on each event. Important events include:

- `candidate_submitted`: the hypothesis, parent, new skill path, character count,
  and size change. This means the skill is saved and admitted for evaluation.
- `suite_queued` / `suite_started`: candidate, split, arms, task count, queue wait,
  and the directory containing the benchmark logs.
- `suite_complete`: baseline/placebo/skill scores for the arms evaluated, duration,
  and result file. `suite_cached` identifies reused results.
- `candidate_evaluated`, `candidate_decision`, and `promoted`: aggregate score,
  selection outcome, current champion, and improvement when a skill takes the lead.
- `researcher_started` / `researcher_complete`: round, submission allowance,
  submitted candidates, and saved findings. Model requests/responses, API retries,
  shell starts/outcomes, and completed hosted web search actions are also logged.
- `candidate_rejected`, `suite_failed`, and interruption events identify problems
  and point to available details. A heartbeat every 30 seconds shows active and
  queued suites, pending candidates, API calls, and time remaining.

Long hypotheses are abbreviated in the terminal; the full text is retained in the
JSON event. Environment API keys/tokens are redacted from event fields. Raw shell
commands, command output, and model reasoning are not printed to the progress log.
These logging changes are part of the frozen runtime: use a fresh output directory
when updating an existing experiment to this code.

```bash
uv run stbench-research status
cat runs/autoresearch-sdk/report.md
cat runs/autoresearch-sdk/usage.json
tail -f runs/autoresearch-sdk/events.jsonl

# Graceful admission stop: already-running suites finish, then the process exits.
touch runs/autoresearch-sdk/STOP
# To resume after a STOP:
rm runs/autoresearch-sdk/STOP
uv run stbench-research run
```

Ctrl+C or SIGTERM cancels active tasks, closes the researcher containers, and checkpoints interrupted suites. Restarting the same command reuses completed suites, researcher sessions, notes, and submission receipts; incomplete suites rerun and may incur charges again. Exact submission retries return the existing job ID. Failed candidates are skipped for that round. Failure of an original skill or control suite stops that domain; the other researcher can continue. Each failure has an `error` field in its `suite.json` and retains any trial/ledger artifacts.

Keep the same config, seed skills, task files, and runtime code to resume. Changing any of them intentionally requires a **new output directory**. This prevents comparing different learners, datasets, or resource settings in one ranking. Relative artifact paths allow copying the experiment to a different host and continuing there. Do not copy an experiment while it is running; stop it first. `plan` also freezes the inputs, so choose settings before running it.

After development, explicitly evaluate the selected skills:

```bash
uv run stbench-research finalize
cat runs/autoresearch-sdk/holdout_report.json
uv run stbench check-skill runs/autoresearch-sdk/best/health
uv run stbench check-skill runs/autoresearch-sdk/best/hle
```

Finalization seals the experiment **before any holdout result is exposed**. It evaluates the selected skill against no-skill/placebo controls and the original draft on the local holdout. It reports lift over both placebo and the original draft; it does not change the selected skills. No more optimization is allowed in that experiment. Rerun `finalize` to recover incomplete suites; completed results are reused. A provider/infra error may consume the remaining evaluation allowance; if it does, the report stays incomplete rather than overspending the cap.

Outputs:

```text
runs/autoresearch-sdk/
  manifest.json                 fixed inputs, split IDs, hashes
  state.json                    resumable search state and admission counters
  events.jsonl                  timestamped research, candidate, suite, and selection events
  leaderboard.json / report.md  scores and hypotheses
  usage.json                    observed benchmark and optimizer usage
  best/health/SKILL.md           exported development champion
  best/hle/SKILL.md
  candidates/<domain>/<id>/skill/  immutable skill packages
  optimizer/<domain>/generation-*/  round prompts, summaries, API usage
  optimizer/<domain>/session.sqlite  persistent SDK conversation
  researchers/<domain>/work/         writable notes, scripts, outbox submissions
  researchers/<domain>/view/         read-only development evidence and job receipts
  evaluations/<domain>/<suite>/attempt-*/
    eval_result.json
    attempts.jsonl
    learner_ledger.jsonl / grader_ledger.jsonl
    harbor-jobs/                learner trajectories and verifier logs
  holdout_report.json           final assessment, after finalize
```

The original submission folders remain untouched. Copy the exported winners into your submission when ready. Static checks and the optimizer prompt discourage benchmark memorization and grader manipulation, but do not prove their absence; review the resulting skills under the hackathon rules before submission. Researcher-written analysis scripts run only in the researcher container. Only the submitted `SKILL.md` becomes a benchmark candidate, mounted for the existing learner as usual.

## EC2 choice and SSH deployment

Recommended starting instance: **m7i.4xlarge, 16 vCPUs, 64 GiB RAM**, Ubuntu Server **24.04 LTS x86_64**, **200 GB gp3 EBS**, On-Demand. [AWS lists the M7i sizes and specifications here](https://aws.amazon.com/ec2/instance-types/m7i/). This is a sizing recommendation for Docker orchestration, not a measured throughput guarantee.

- Smaller start: **m7i.2xlarge, 8 vCPUs / 32 GiB**, with five global task slots.
- More headroom: **m7i.8xlarge, 32 vCPUs / 128 GiB**, if running ten suites with two tasks each (20 global slots), image builds or memory become the bottleneck.
- No GPU is needed: model inference and grading use external APIs. Prefer x86_64 for this repo's amd64 containers. Confirm the chosen type is offered in your selected region/AZ; AWS prices depend on region and purchasing model.
- Keep inbound SSH (22) restricted to your IP, and allow outbound HTTPS. Gateways bind loopback and the Docker bridge, so no public HTTP port is needed. Keep the Docker socket private. Persistent EBS retains the experiment across a stop/start; back up artifacts before terminating the instance.

Transfer from your Mac (replace the host and key paths):

```bash
rsync -az --progress -e 'ssh -i ~/.ssh/hackathon.pem' \
  --exclude=.git --exclude=.venv --exclude=.env --exclude='runs/' \
  --exclude='__pycache__/' --exclude='.DS_Store' --exclude='*.pem' \
  ./ ubuntu@EC2_HOST:/home/ubuntu/rsi-hackathon/

ssh -i ~/.ssh/hackathon.pem ubuntu@EC2_HOST
cd ~/rsi-hackathon
bash deploy/bootstrap-ubuntu.sh
exit
# Reconnect to apply Docker group membership.
ssh -i ~/.ssh/hackathon.pem ubuntu@EC2_HOST
cd ~/rsi-hackathon
cp -n .env_example .env
chmod 600 .env
nano .env
docker info
uv run stbench-research doctor --config autoresearch.smoke.toml
```

That transfer includes downloaded data if it exists locally. Otherwise run `uv run stbench data pull` on EC2. It excludes `.env`; enter keys on EC2 or transfer them separately over SSH. To resume an existing experiment, stop it first and transfer its `runs/autoresearch-sdk/` directory as well as the exact original code/config/skills/data.

Run interactively in a persistent terminal:

```bash
tmux new -s research
uv run stbench-research run
# Detach: Ctrl+B, then D. Reattach: tmux attach -t research
```

Or install the supplied service after verifying its user and paths:

```bash
sudo cp deploy/autoresearch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now autoresearch
journalctl -u autoresearch -f
# Gracefully stop, then resume with another start:
sudo systemctl stop autoresearch
sudo systemctl start autoresearch
```

The service does not automatically restart failed paid runs. A host hard kill may leave task containers behind; inspect `docker ps` before resuming and clean up only the identified orphaned experiment containers. `docker system df` helps watch image/log disk usage. Avoid pruning while an experiment is active.

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

Tests exercise the real SDK runner with a scripted model, a mocked Responses HTTP transport, and synthetic evaluators. They exercise the multi-generation loop, shared concurrency, selection with negative rewards, invalidation handling, state recovery, shell continuation after background submission, persistent sessions, domain independence, job idempotency, task/config/skill hashes, holdout isolation, budgets, and API retries without Docker or paid API calls. The real smoke configuration is the next deployment check.
