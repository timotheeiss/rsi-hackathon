# Health and HLE skill autoresearch

`stbench-research` uses **GPT-6 Astra (`gpt-6-astra`)** through the OpenAI Responses API to improve the two draft skills in `submissions/aditya-tim/`. It evaluates them through this repository's existing Harbor/Docker runtime. The learner remains **`zai-glm-5-3-flash`**, and the graders and task limits remain those in `hackathon.toml`.

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

1. Validate the seed skills; snapshot them and the learner contract. Hash the source runtime, selected task files, original skills, configuration, and split membership.
2. Evaluate no-skill and placebo controls once on each development split, followed by the original draft. All candidates use exactly the same development tasks.
3. Give Astra the scoring contract, actual generic grader source, retained parent skills, recent experiment history, and a bounded selection of development answers, grader verdicts, and trajectory/log excerpts. Include losing hypotheses as well as the champion.
4. Ask for five complete `SKILL.md` variants per domain with explicit hypotheses. Validate and store each separately. Supporting files are inherited unchanged. Invalid, duplicate, oversized, or identifier-containing candidates are rejected before evaluation.
5. Schedule suites across both domains. Separate semaphores cap simultaneous suites, tasks within a suite, and all task containers across the process. Every suite has its own gateways, ledgers, Docker trial directories, and timeout.
6. Rank complete results by mean development reward, keep the top three as parents, and promote an improvement greater than `min_improvement`. Ties keep the incumbent. Repeat for the configured number of generations, or use `generations = 0` to continue until a budget, deadline, interruption, or STOP file.

HealthBench uses the **mean raw rubric reward**: satisfied positive and negative criteria contribute points divided by total positive points. Individual rewards can be negative. The official display additionally clips the aggregate to [0,1]. HLE uses the mean of binary correct/incorrect judgments. The leaderboard subtracts placebo performance; since the development placebo is cached and shared, maximizing raw reward ranks candidates identically to maximizing placebo lift. Local development lift is an estimate, not the private leaderboard score.

An infrastructure error, missing result, nonfinite score, or grader invalidation makes the entire candidate evaluation ineligible. It cannot improve its score by excluding difficult tasks. The original evaluator retries infrastructure failures; a wrong answer is never retried selectively. Candidate repeats average every task equally. `repeats = 2` or `3` can reduce sampling noise at corresponding cost; set this before starting a new experiment. The default one-repeat development ranking is exploratory and susceptible to selection noise.

The checked-in full configuration preserves your existing **16 Health dev / 30 Health validation** task IDs, now used as dev/holdout. HLE gets a deterministic shuffled **24 dev / 24 holdout** split from the downloaded training data. Remaining training tasks are unused. Explicit split files accept comma-separated or whitespace-separated names. These are local partitions of the public training data, not the organizers' private held-out tasks. If you have already tuned on a local holdout, choose a fresh untouched partition before a new experiment.

## Workload and limits

The full default has five variants per domain, ten generations, five suites at once, two tasks per suite, and a **global cap of ten active task attempts**. To admit ten suites simultaneously, set `max_parallel_suites = 10`; keeping `max_task_containers = 10` still caps overall load.

The default plan is at most **108 suites / 2,336 task attempts** including controls, original skills, and final holdout comparisons, before infrastructure retries. A task can use many model calls; Health grading can issue several concurrent rubric calls. API request/token rate limits may bottleneck before CPU or RAM. Reduce concurrency if rate limits are frequent.

- `max_evaluations` counts suite starts, including interrupted/failed starts. It persists across resumes. Two suites per domain per repeat are reserved for finalization.
- `max_optimizer_calls` counts every Astra HTTP attempt, including retries. Astra retries transient failures with bounded backoff.
- `suite_timeout_seconds` bounds an individual suite; the existing task timeouts remain intact.
- `max_hours` is a persistent wall-clock deadline beginning with the first `run`. It does not reset on restart. Finalization has separate suite timeouts and can run after the search deadline.
- `hackathon.toml` already caps each suite's learner and grader token pools. They are unchanged.
- `usage.json` totals observed tokens and available benchmark cost estimates, including failed attempts. Astra usage is separate; no dollar conversion is assumed. Missing accounting after a crash is unknown spend.

These are workload bounds, **not a hard dollar budget**. Use provider-side spend limits for a monetary cap. Larger machines do not increase provider quotas. Nothing starts paying for API calls until `run` or `finalize`.

## Inspect, stop, resume, and finalize

```bash
uv run stbench-research status
cat runs/autoresearch/report.md
cat runs/autoresearch/usage.json
tail -f runs/autoresearch/events.jsonl

# Graceful admission stop: already-running suites finish, then the process exits.
touch runs/autoresearch/STOP
# To resume after a STOP:
rm runs/autoresearch/STOP
uv run stbench-research run
```

Ctrl+C or SIGTERM cancels active tasks and checkpoints interrupted suites. Restarting the same command reuses completed suites and proposals; it reruns incomplete work, which may incur charges again. Failed candidates are skipped for the current generation. Failure of the original skill or controls stops the run so you can correct infrastructure and retry. Each failure has an `error` field in its `suite.json` and retains any trial/ledger artifacts.

Keep the same config, seed skills, task files, and runtime code to resume. Changing any of them intentionally requires a **new output directory**. This prevents comparing different learners, datasets, or resource settings in one ranking. Relative artifact paths allow copying the experiment to a different host and continuing there. Do not copy an experiment while it is running; stop it first. `plan` also freezes the inputs, so choose settings before running it.

After development, explicitly evaluate the selected skills:

```bash
uv run stbench-research finalize
cat runs/autoresearch/holdout_report.json
uv run stbench check-skill runs/autoresearch/best/health
uv run stbench check-skill runs/autoresearch/best/hle
```

Finalization seals the experiment **before any holdout result is exposed**. It evaluates the selected skill against no-skill/placebo controls and the original draft on the local holdout. It reports lift over both placebo and the original draft; it does not change the selected skills. No more optimization is allowed in that experiment. Rerun `finalize` to recover incomplete suites; completed results are reused. A provider/infra error may consume the remaining evaluation allowance; if it does, the report stays incomplete rather than overspending the cap.

Outputs:

```text
runs/autoresearch/
  manifest.json                 fixed inputs, split IDs, hashes
  state.json                    resumable search state and admission counters
  events.jsonl                  suite starts/completions, promotions, failures
  leaderboard.json / report.md  scores and hypotheses
  usage.json                    observed benchmark and optimizer usage
  best/health/SKILL.md           exported development champion
  best/hle/SKILL.md
  candidates/<domain>/<id>/skill/  immutable skill packages
  optimizer/<domain>/generation-*/  prompts, analysis, proposals, API usage
  evaluations/<domain>/<suite>/attempt-*/
    eval_result.json
    attempts.jsonl
    learner_ledger.jsonl / grader_ledger.jsonl
    harbor-jobs/                learner trajectories and verifier logs
  holdout_report.json           final assessment, after finalize
```

The original submission folders remain untouched. Copy the exported winners into your submission when ready. Static checks and the optimizer prompt discourage benchmark memorization and grader manipulation, but do not prove their absence; review the resulting skills under the hackathon rules before submission. No candidate-generated code is executed on the host. Only `SKILL.md` is generated, and it is mounted for the existing learner as usual.

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
  --exclude='__pycache__/' --exclude='.DS_Store' \
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

That transfer includes downloaded data if it exists locally. Otherwise run `uv run stbench data pull` on EC2. It excludes `.env`; enter keys on EC2 or transfer them separately over SSH. To resume an existing experiment, stop it first and transfer its `runs/autoresearch/` directory as well as the exact original code/config/skills/data.

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

Tests use synthetic evaluators and a mocked Responses transport. They exercise the multi-generation loop, shared concurrency, selection with negative rewards, invalidation handling, state recovery, task/config/skill hashes, holdout sealing, budgets, and API retries without Docker or paid API calls. The real smoke configuration is the next deployment check.
