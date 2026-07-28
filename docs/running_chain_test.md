# Running the Chain Test (lilab vs SDSC)

Operational runbook for the SIDERIUS multi-iteration model exploration chain.
The chain runs the 5-agent loop (interpret → propose → implement → validate →
tune) once per iteration, and feeds each iteration's output back as a seed for
the next iteration.

## The entry points

| # | Entry point | Environment | Mechanism | Use when |
|---|---|---|---|---|
| 1 | `tests/integration/workflows/test_full_exploration_loop.py::test_chained_iterations` | lilab | pytest, `tmp_path` workspace, in-process two `run_workflow()` calls | Quick smoke test / regression. Throwaway artifacts. |
| 2 | **`sdsc_submission_scripts/run_chain.sh --mode {lilab,sdsc}`** | lilab or SDSC Expanse | Unified Bash orchestrator. `--mode lilab` runs `run_one_iteration.py` as foreground subprocess; `--mode sdsc` submits via `sbatch` with `--dependency=afterany`. | **Canonical chain entry point** for any real durable run on either environment (since Phase 6.8 Commit 13.A). |
| 3 | ~~`sdsc_submission_scripts/run_iteration_chain_lilab.sh`~~ | lilab | **Deprecated** — delegating stub that calls `run_chain.sh --mode lilab "$@"` and prints a `WARNING:` banner. Removal tracked under Commit 15. | Legacy operator muscle memory only. New work should use entry 2. |
| 4 | ~~`sdsc_submission_scripts/run_iteration_chain.sh`~~ | SDSC Expanse | **Deprecated** — delegating stub that calls `run_chain.sh --mode sdsc "$@"` and prints a `WARNING:` banner. Removal tracked under Commit 15. | Legacy operator muscle memory only. New work should use entry 2. |

**Entry 2 is the single source of truth.** It sources
`sdsc_submission_scripts/_chain_common.sh` for all shared logic (defaults,
arg parsing, advice file loading, source-path building, APP_ARGS construction,
per-iteration loop) and dispatches to `submit_iteration_lilab` /
`submit_iteration_sdsc` based on `--mode`. The two stubs (entries 3 and 4)
exist solely to keep prior runbooks and shell history working during the
transition; they `exec` into entry 2 unchanged and add nothing of their own.

**Iterations always hand off via `manifest.json` files**, regardless of
whether the previous iteration was a Python subprocess or a Slurm job. This
keeps the two `--mode`s identical for debugging.

The shared advice file `advice/workflow/human_advice_chain_test.json` is the
single source of truth for human guidance to the 5 agents. **Both lilab and
SDSC tests load from it** — edit one file to retune both environments.

### Two levels of human-advice files

Human-advice files come in two distinct shapes, one per level of the run hierarchy.
Do not confuse them:

| Level | File shape | Used by | Example |
|---|---|---|---|
| **Aggregated** (workflow / chain) | Keyed by agent name — has all 5 keys, one per agent in the loop | `run_iteration_chain.sh`, `run_iteration_chain_lilab.sh`, `run_one_iteration.py` (chain test) | `{"interpret":"...", "propose":"...", "implement":"...", "validate":"...", "tune":"..."}` |
| **Per-agent** (single-agent run) | One key matching the single agent the script invokes | `run_comparison.py` (single-model hyperparameter tuning) | `{"tune":"..."}` |

The per-agent file is a strict subset of the aggregated file — pulling the
relevant key out of the aggregated file gives you a valid per-agent file.
Both formats are JSON; the chain runbook in this doc only uses the aggregated
format.

---

## Pre-flight (both environments)

1. **Pull latest code** on whichever box you're running on:
   ```bash
   cd ~/SIDERIUS
   git pull
   git log --oneline -3
   ```

2. **Inspect / edit shared advice** if needed:
   ```bash
   cat advice/workflow/human_advice_chain_test.json
   ```
   Five keys, one per agent: `interpret`, `propose`, `implement`, `validate`,
   `tune`. Any key may be empty (`""`) — empty strings are not forwarded.

---

## Unified entry point — `run_chain.sh` (canonical, since 13.A)

`sdsc_submission_scripts/run_chain.sh` is the single user-facing orchestrator
for chain runs on both lilab and SDSC. The legacy `run_iteration_chain*.sh`
stubs print a deprecation warning and delegate here unchanged.

### Required flags
| Flag | Purpose |
|---|---|
| `--mode {lilab,sdsc}` | Backend selector. **No default — must be set.** `lilab` runs each iteration as a foreground subprocess; `sdsc` submits each iter as a `sbatch` job with `--dependency=afterany` on the previous iter's job ID. |
| `--workspace DIR` | Chain workspace root. Iter NNN's artifacts land under `${WORKSPACE}/iter_NNN/`. |
| `--seed_paths P [P …]` | One or more seed `run_output_*.json` files. Greedy slurp until the next `--flag`. Seeds must match the run's DataScope (unstamped legacy seeds = full scope); partial-scope runs are normally seedless. |
| `--data_scope S` | Restrict the chain to a file subset (`4-9`, `4,5,6,7,8,9`, or mixed). Omitted = complete dataset. Pinned per workspace by `run_invariants_lock.json`. |
| `--health_gate_files L` | Run-level shared monitored-file list for ALL HealthGate checks (same spec format). Mandatory under a partial scope when gates are enabled. |
| `--health_gate_enabled` / `--no-health_gate_enabled` | HealthGate subsystem switch (default enabled). |

### Resume / safety flags (Commit 13.B)
| Flag | Default | Purpose |
|---|---|---|
| `--auto_resume` | **ON** | Query `scripts/inspect_run_state.py --layout chain --next-iter` to pick `START_ITER`. The inspector exits non-zero on legacy-layout detection or non-contiguous chains, and `run_chain.sh` propagates that exit code. |
| `--no_auto_resume` | — | Force `START_ITER=1` regardless of workspace state. |
| `--start_iter N` | — | Manual pin; wins over auto-resume when both are present. |
| `--force_fresh` | OFF | Override the stale-fresh safety guard (which otherwise refuses to start fresh on a non-empty workspace with a clear error). |

If auto-resume returns `START_ITER > NUM_ITERATIONS`, the orchestrator exits 0
cleanly with `"All N iterations are already complete. Nothing to do."` —
idempotent rerun is the expected behaviour for cron-driven chains.

### Inspection / safety flags
| Flag | Default | Purpose |
|---|---|---|
| `--dry-run` | OFF | Walk the full chain loop printing the exact command per iter (with `DRYRUN_iter_NNN` placeholders for sdsc dependency wiring) **without touching the workspace, calling python, or submitting jobs**. Side-effect-free; `${WORKSPACE}` is never created. Use for sanity-checking arg parsing + dependency chain before committing to a real run. |
| `--num_iterations N` | 2 | Total iters to walk. |

### §3.2 flags (full input contract)
The full set of `--max_rounds`, `--max_proposal_attempts`,
`--data_dir`, etc. is the §3.2 contract (`--trial_strategy` and
`--target_files` are DEPRECATED no-ops since DS7 — parsed, warned,
ignored; use `--data_scope`); defaults match
both Python entries (`run_one_iteration.py` and `run_exploration_adaptive.py`)
and are enforced by `tests/unit/scripts/test_chain_consistency.py` (Gate A
three-way parity test). See the design doc
`docs/phase68_orchestrator_memory_and_resume.md` §3.2 for the canonical table.

### Cold-start real-training runs (operator rule, 2026-07-27)

Every new real-training gate/smoke run must be cold-start — do NOT
pass `--seed_paths`. The chain's own iter 1 produces a fresh
DS-stamped output; iter 2+ chain off that. Rationale (DS8 correctness
+ uniformity + provenance) and the twin partial-scope rule (paired
`--data_scope` + `--health_gate_files`) are in
`docs/gates/gate_testing_standard.md` "Partial-scope rules" section.
The pre-DS8 canonical seeds referenced there are historical only.
Exception: reproducing a specific historical seeded run —
operator-approved case-by-case only.

### Chain formal-incumbent coupling (V19 PR 1)

Two related tuner inputs, forwarded from the chain layer:

- The chain reconstructs the best HealthGate-VALID FORMAL score from
  prior committed iterations and delivers it to every subsequent
  iteration's tuner (unconditional; visible in the `[resume]
  incumbent carry-over` log line, the tuner's `[chain_incumbent]`
  startup line, and every manifest under `chain_incumbent_source`).
- Whether the tuner's formal delta gates ACT on that reference is
  controlled by `--enable_chain_incumbent_formal_gates` (default
  OFF). ON: gates use `chain_incumbent + fixed_delta` as thresholds.
  OFF: reconstruction still runs but the gates ignore the reference
  (they never fire on it). **OFF is not a fixed-`0.0` mode** — the
  pre-V19 default is unrepresentable.

See `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
under "Chain formal-incumbent reference" for full semantics.

### Virtualenv auto-detection (`--mode lilab` orchestrator + SDSC submission node)
The orchestrator resolves the Python interpreter in this priority order
(set in `resolve_py_cmd` and verified by the version + passthrough guards):

1. `$VIRTUAL_ENV/bin/python` — operator-activated venv. Highest priority so
   that an explicit `source .venv/bin/activate` always wins.
2. `${PROJECT_DIR}/.venv/bin/python` — project-local venv (the standard
   SIDERIUS dev-machine layout per `CLAUDE.md`).
3. `uv run --project ${PROJECT_DIR} python` — used when neither venv is
   present and `uv` is on `$PATH`.
4. `python3` — last-resort fallback. Prints a multi-line warning banner
   with the exact remediation command (`python3.10 -m venv .venv && .venv/bin/pip install -e .`)
   because system `python3` on lilab is 3.8 and will fail SIDERIUS's modern
   syntax.

After resolution, two unconditional guards run:

- **Version guard** (`enforce_py_version_guard`): refuses any interpreter
  reporting `sys.version_info < (3, 10)` with the exact error
  `ERROR: SIDERIUS requires Python 3.10+. Current: <version>` plus a
  diagnostic line naming the resolved interpreter and source label.
- **Env passthrough** (`setup_py_env_passthrough`): exports
  `VIRTUAL_ENV=$PY_VENV_ROOT` and idempotently prepends `$PY_VENV_ROOT/bin`
  to `$PATH` so subprocesses (training workers, plugin sandbox) inherit the
  same venv as the orchestrator. No-op for the `uv run` and system `python3`
  paths.

The chain header surfaces the resolved interpreter on lilab:
`Python: /path/to/python (source: $VIRTUAL_ENV / project venv / uv / python3)`.

For `--mode sdsc`, the iteration jobs themselves use whatever python
`submit_one_iteration.slurm` configures (it activates `.venv/bin/activate`
inside the Slurm job). The submission-node interpreter resolved here is
used only to call the inspector for `--auto_resume`.

### Examples

**Lilab fresh run, 3 iterations:**
```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --num_iterations 3 \
    --seed_paths /home/klz/Data/SIDEREIS_DATA/punet/.../run_output_*.json \
                 /home/klz/Data/SIDEREIS_DATA/wavenet/.../run_output_*.json \
    --max_rounds 2 --max_epochs 1 \
    --human_advice_file advice/workflow/human_advice_chain_test.json
```

**Lilab dry-run (verify before committing — produces no side effects):**
```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab --dry-run \
    --workspace /tmp/chain_v1_preview \
    --num_iterations 3 \
    --seed_paths /home/klz/Data/SIDEREIS_DATA/punet/.../run_output_*.json
```

**SDSC submission with explicit Slurm budget:**
```bash
bash sdsc_submission_scripts/run_chain.sh --mode sdsc \
    --workspace /expanse/.../exploration_v1 \
    --num_iterations 5 \
    --seed_paths /expanse/.../seed.json \
    --partition gpu-shared --time 06:00:00 --mem 48G --cpus 8
```

**Resume after iter 2 crashed (auto-resume picks 3 from on-disk state):**
```bash
# Same command as the original launch — auto_resume is ON by default.
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --num_iterations 5 \
    --seed_paths ...
# Header prints: "Start: auto-resume — inspector computed START_ITER=3"
```

**Manual override (force a specific start iter, e.g. for debugging):**
```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --start_iter 2 --num_iterations 5 \
    --seed_paths ...
```

---

## Lilab — Tier 3 pytest

Two tests live in `tests/integration/workflows/test_full_exploration_loop.py`:

| Test | What it does | Runtime |
|---|---|---|
| `test_full_loop` | One iteration of the full 5-agent loop. Validates the loop end-to-end. | ~5–10 min |
| `test_chained_iterations` | Two sequential `run_workflow()` calls. Iteration 2 sees seeds + iteration 1's output. Mirrors the SDSC chain in-process. | ~20–30 min in practice |

Both tests use the same pinned `max_rounds=2`, `max_epochs=1`, `trial_portion=0.02`, `eval_portion=0.02` smoke-test budget defined in the pytest source — they're not configurable from the command line.

### Run the chain test (the one that mirrors SDSC)
```bash
cd ~/SIDERIUS
tmux new -s lilab_chain
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::test_chained_iterations \
    2>&1 | tee /tmp/lilab_chain.log
```
Detach with `Ctrl-b d`. Reattach with `tmux attach -t lilab_chain`.

### Watch progress
```bash
tail -f /tmp/lilab_chain.log
nvidia-smi -l 5    # in another pane — watch GPU usage
```

### What "success" looks like
- Final pytest line: `PASSED` (exit code 0)
- Two model plugins were created and cleaned up under `agent_generated/models/`
- `pytest`'s `tmp_path` workspace contains:
  - `iter_001/iteration_001/{model1}/run_output_iter_001.json`
  - `iter_002/iteration_001/{model2}/run_output_iter_002.json`

### If it fails
The test prints a `[CLEANUP]` line for each registered plugin. Verify no
orphan plugins remain in `agent_generated/models/` before rerunning:
```bash
ls agent_generated/models/
```

### Optional: quick smoke test first
```bash
uv run pytest -m real_run -v -s \
    tests/integration/workflows/test_full_exploration_loop.py::test_full_loop
```

---

## Lilab — real durable chain run (legacy entry point 3)

> **DEPRECATED — use `run_chain.sh --mode lilab` instead.** The script
> referenced below (`run_iteration_chain_lilab.sh`) is now a thin
> delegating stub that prints a `WARNING:` banner and `exec`s into
> `run_chain.sh --mode lilab "$@"`. Same flags, same behaviour, same
> workspace artifacts. Removal of the stub is tracked under Phase 6.8
> Commit 15. New work — and new operator muscle memory — should target
> the [Unified entry point](#unified-entry-point--run_chainsh-canonical-since-13a)
> directly. The section below is preserved for historical context and
> because existing tmux sessions / shell history may still reference the
> stub by name.

When you want a *real* lilab run with a fixed, persistent workspace
(not a pytest throwaway), the canonical command is:

```bash
bash sdsc_submission_scripts/run_chain.sh --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --num_iterations 2 \
    --seed_paths <one or more seed JSONs> \
    --human_advice_file advice/workflow/human_advice_chain_test.json
```

The legacy invocation below — using `run_iteration_chain_lilab.sh` —
still works because the stub `exec`s into the unified entry point
unchanged. It is the non-Slurm sibling of `run_iteration_chain.sh`
(same flags, same behavior, same shared logic via `_chain_common.sh`)
and the **only** legitimate difference is that iterations run as
foreground Python subprocesses instead of Slurm jobs.

### Submit (validated smoke-test config matching the pytest budget)
```bash
cd ~/SIDERIUS
tmux new -s lilab_real_chain
bash sdsc_submission_scripts/run_iteration_chain_lilab.sh \
    --workspace /home/klz/Data/SIDEREIS_DATA/lilab_chain_v1 \
    --num_iterations 2 \
    --seed_paths \
        /home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
        /home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json \
    --max_rounds 2 \
    --max_epochs 1 \
    --trial_portion 0.02 \
    --eval_portion 0.02 \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    2>&1 | tee /tmp/lilab_real_chain.log
```
Detach with `Ctrl-b d`. Reattach with `tmux attach -t lilab_real_chain`.

This is the exact config of the run that completed successfully end-to-end on
2026-04-07 (~25 min for both iterations on RTX 5090). Bumping `--max_rounds`
or `--max_epochs` is fine for longer runs but expect proportionally longer
runtime, especially because **the formal (last) round always evaluates on
full data** regardless of `--eval_portion` (eval_portion is forced to 1.0
in formal mode — see "Notes on trial vs formal mode" below).

The lilab orchestrator auto-detects `uv` and uses `uv run python` to invoke
`run_one_iteration.py` (so deps from `.venv` are picked up correctly).
Falls back to plain `python3` when `uv` is absent.

### Monitor (other pane)
```bash
tail -f /tmp/lilab_real_chain.log
nvidia-smi -l 5
```

### Success criteria (same as SDSC)
- Script exits 0
- Both `iter_001/manifest.json` and `iter_002/manifest.json` exist with
  `"status": "completed"`
- Round outputs present under `iter_NNN/iteration_001/{model}/`
- Iter 2's interpretation step references iter 1's model name (proves the
  manifest handoff carried real data)

### If iter 1 fails
The script aborts via `set -e`. Inspect `iter_001/` (the partial manifest
will not exist; runner only writes it on clean exit). Fix the bug, and
**always rerun with a fresh `--workspace`** — partial state from a killed
run can confuse manifest resolution on the next attempt.

### Differences vs the pytest test
| Aspect | pytest `test_chained_iterations` | `run_iteration_chain_lilab.sh` |
|---|---|---|
| Workspace | `tmp_path` (pytest, throwaway) | Fixed durable path you choose |
| Verification | strict assertions in test code | inspect manifests + outputs manually |
| Plugin cleanup | auto-removes registered plugins | leaves everything in place |
| Code path | calls `run_workflow()` directly in-process | calls `run_one_iteration.py` as a subprocess (same as SDSC) |
| Use when | CI / quick smoke / regression | real exploration, want artifacts to keep |

### Differences vs the SDSC mode (entry 2 with `--mode sdsc`, or legacy entry 4)
| Aspect | SDSC mode (`run_chain.sh --mode sdsc` / legacy `run_iteration_chain.sh`) | lilab mode (`run_chain.sh --mode lilab` / legacy `run_iteration_chain_lilab.sh`) |
|---|---|---|
| Execution | Each iteration = separate Slurm job | Each iteration = foreground Python subprocess |
| Concurrency model | Async; orchestrator returns after submission | Sync; orchestrator blocks until chain finishes |
| Failure handling | `afterany` lets next iter run; iter N+1's runner errors at source-path resolution if iter N's manifest is missing | `set -e` aborts the script |
| Walltime cap | Slurm `--time` enforced by scheduler | None (runs until done or you Ctrl-C) |
| Slurm-only flags | `--partition`, `--time`, `--mem`, `--gpus`, `--cpus` | accepted but ignored |
| Shared code | `_chain_common.sh` | `_chain_common.sh` (same file) |

---

## SDSC Expanse — Slurm chain submission (legacy entry point 4)

> **DEPRECATED — use `run_chain.sh --mode sdsc` instead.** The script
> referenced below (`run_iteration_chain.sh`) is now a thin delegating
> stub that prints a `WARNING:` banner and `exec`s into
> `run_chain.sh --mode sdsc "$@"`. Same flags, same `sbatch` dependency
> wiring (`afterany`, not `afterok` — preserves OOM-tolerant chain
> survival), same `submit_one_iteration.slurm` per-iter job. Removal of
> the stub is tracked under Phase 6.8 Commit 15. New work should target
> the [Unified entry point](#unified-entry-point--run_chainsh-canonical-since-13a)
> directly. The section below remains as the most complete operator
> walkthrough for the SDSC submission workflow because it covers SSH
> sync, Slurm flags, monitoring, and post-mortem mechanics that are
> identical under either invocation.

The real distributed test. Each iteration is its own Slurm job; iteration N+1
starts only after iteration N's `manifest.json` is written. Shares all
non-execution logic with the lilab orchestrator via `_chain_common.sh`.

### 1. Sync code on SDSC
```bash
ssh ym137@login.expanse.sdsc.edu
cd ~/SIDERIUS
git checkout small_sample_trial_fixed_config
git pull
git log --oneline -3
```

### 2. Submit the chain (use a fresh workspace each time)
```bash
bash sdsc_submission_scripts/run_iteration_chain.sh \
    --workspace /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v1 \
    --num_iterations 2 \
    --seed_paths /expanse/lustre/projects/ddp433/ym137/siderius_workspace/punet/hpt_full_v1/agent/run_output_hpt_full_v1_agent.json \
    --max_rounds 2 \
    --max_epochs 1 \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    --time 06:00:00 \
    --mem 48G \
    --cpus 8
```

Key flags (same shape as the lilab orchestrator — `_chain_common.sh` enforces this):
- `--max_epochs 1` — hard cap on epochs per round (LLM cannot override)
- `--max_rounds 2` — total rounds per iteration (last round = formal mode, see notes below)
- `--human_advice_file ...` — loads all 5 advice keys from JSON (the same file lilab uses)
- `--time 06:00:00` — Slurm walltime per iteration. **6 h is the empirically validated budget for `max_rounds=2, max_epochs=1` on `gpu-shared`**, and it leaves comfortable headroom for the formal round's full-data eval. Lower values (3 h, 4 h) start the job sooner but risk hitting the wall on a slow V100; bump to 8 h+ if you increase `max_rounds`.
- `--mem 48G` — host RAM cap. **24G is too low**: the formal-round scoring step uses 8 parallel `concurrent.futures` workers, each loading HDF5 files independently, and combined peak host RAM hits ~25–30 GB. The orchestrator's default is now 48G; only override downward if you understand what you're doing. (Note: this is **host CPU memory**, not GPU VRAM; the V100/A100 has its own 32–80 GB of VRAM that is not affected.)
- **Always use a fresh workspace** (`_v1`, `_v2`, … bump on every resubmit) — partial state from a killed run will confuse the manifest resolution. After any failure, `rm -rf` the old workspace dir (or pick a new name) before resubmitting.

### Tuner planner / reflector model split (optional)

The tuner agent makes two distinct LLM calls per round: a reasoning-heavy
**planner** (`brain.plan()`) at the start of each round, and a templated
**reflector** (`brain.reflect()`) at the end. They have very different
cognitive demands, and as of commit `2dc688a` they can use different
models — and even different providers — independently.

The chain orchestrator exposes two new optional flags:

| Flag | Default | Purpose |
|---|---|---|
| `--reflect_provider {gemini,openai}` | unset → falls back to gemini | Provider for the tuner's reflector sub-call. Set to `openai` to route reflect calls to a different vendor entirely (the bridge holds two clients in this case). |
| `--reflect_model_id MODEL` | `gemini-2.5-flash` (auto-applied for gemini provider) | Model for the tuner's reflector sub-call. Defaults to `gemini-2.5-flash` (GA, **unlimited daily quota**, well-suited for templated JSON extraction). The planner stays on `--llm_model`. |

**Example: same provider, two different models** (the recommended config —
keeps the planner on the strong reasoning model, drops the reflector to
flash for quota relief):

```bash
bash sdsc_submission_scripts/run_iteration_chain.sh \
    --workspace ... \
    --num_iterations 2 \
    --seed_paths ... \
    --max_rounds 2 \
    --max_epochs 1 \
    --llm_model gemini-3.1-pro-preview \
    --reflect_model_id gemini-2.5-flash \
    --human_advice_file advice/workflow/human_advice_chain_test.json \
    --time 06:00:00 --cpus 8
```

This is also the **default** when you don't pass `--reflect_*` flags at
all — the chain runner auto-applies `gemini-2.5-flash` for the gemini
provider. So in practice, the explicit flag is only needed when you want
something different from the default (e.g., forcing the legacy
single-model behavior for an apples-to-apples comparison, or routing
the reflector to openai).

**Example: cross-provider** (planner on gemini, reflector on openai —
useful when gemini is rate-limited globally):

```bash
bash sdsc_submission_scripts/run_iteration_chain.sh \
    --workspace ... \
    --num_iterations 2 \
    --seed_paths ... \
    --reflect_provider openai \
    --reflect_model_id gpt-4o-mini \
    ...
```

The bridge instantiates a second `OpenAI()` client internally and routes
the reflect call to it, while the planner keeps using the gemini client.

**Why this matters for chain runs**: every iteration's tuner makes
`max_rounds × 2` LLM calls. With `max_rounds=10` and 10 chain
iterations, that's 200 calls per chain — enough to exhaust the daily
gemini-3.1-pro quota of 250 requests. Splitting reflector to flash cuts
the pro usage by ~50%, doubling your daily runway.

**Quota math** (gemini provider, default split):

| `max_rounds` × iterations | Pro calls before split | Pro calls after split | Reduction |
|---|---|---|---|
| 2 × 2 | 8 | 4 | 50% |
| 5 × 5 | 50 | 25 | 50% |
| 10 × 10 | 200 | 100 | 50% |
| 20 × 20 | 800 | 400 | 50% |

**Configuring per-agent in JSON config files**: If you maintain a
declarative `WorkflowLLMConfig` JSON file (loaded via
`WorkflowLLMConfig.from_json(...)`), the `tune` slot now uses a nested
`TunerLLMConfig` structure with per-sub-call `NodeLLMConfig` slots:

```json
{
  "tune": {
    "planner": {
      "provider": "gemini",
      "model_id": "gemini-3.1-pro-preview"
    },
    "reflector": {
      "provider": "gemini",
      "model_id": "gemini-2.5-flash"
    }
  }
}
```

This is the user-facing structural format. Each sub-call is a first-class
`NodeLLMConfig` with its own provider and model. Future agents (interpret,
validator) will follow the same nested-NodeLLMConfig pattern when their
internal sub-calls grow distinct cognitive demands. See
`docs/break_tuner_agent.md` §3.6 for the full design rationale.

For richer multi-round runs (smoke test passes, you want real signal), bump `--max_rounds`/`--max_epochs` and the walltime accordingly. Rough scaling: each additional trial round adds ~5–15 min on V100 with `max_epochs=1`; the formal round is always the long pole regardless.

### 3. Capture the two job IDs
The script prints something like:
```
  iter 1 → job XXXXXXXX
  iter 2 → job YYYYYYYY  (depends on XXXXXXXX via --dependency=afterany)
```
Save them — you need them for monitoring.

### 4. Monitor

While queued/running:
```bash
squeue -u ym137
squeue -j XXXXXXXX,YYYYYYYY -o "%.10i %.8T %.10M %.20R"
scontrol show job XXXXXXXX | grep -E "JobState|Reason|RunTime|TimeLimit"
```

Once iter 1 starts running, tail its log:
```bash
tail -f sdsc_submission_scripts/logs/iter_XXXXXXXX.out
tail -f sdsc_submission_scripts/logs/iter_XXXXXXXX.err
```

After iter 1 finishes, **verify the manifest** (this is the critical handoff
between iterations):
```bash
ls /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_001/
cat /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_001/manifest.json
```
Expected: `"status": "completed"` and an `output_path` that exists on disk.

When iter 2 starts, the **first lines of its log should show**:
```
  Resolved @manifest:.../iter_001/manifest.json → .../{model}/run_output_iter_001.json
```
That confirms the manifest indirection worked end-to-end. Tail it:
```bash
tail -f sdsc_submission_scripts/logs/iter_YYYYYYYY.out
```

### 5. Post-mortem after completion
```bash
sacct -j XXXXXXXX,YYYYYYYY --format=JobID,JobName,State,Elapsed,ExitCode,MaxRSS,Start,End
ls /expanse/lustre/projects/ddp433/ym137/siderius_workspace/exploration_chain_test_v3/iter_*/manifest.json
```

### Success criteria
- Both jobs `State=COMPLETED`, `ExitCode=0:0`
- Both `iter_001/manifest.json` and `iter_002/manifest.json` exist with
  `"status": "completed"`
- Iter 2's log shows it resolved iter 1's manifest
- Iter 2's interpretation step references iter 1's model name (proves the
  chain handoff carried real data, not just a path)

### If iter 1 fails
With `--dependency=afterany`, iter 2 will start regardless of iter 1's
slurm-level exit state. The runner inside iter 2 then tries to resolve
the `@manifest:` source path and:
- If iter 1's `manifest.json` exists with `status=completed`, iter 2 proceeds normally.
- If iter 1's `manifest.json` is missing or has `status=failed`, the runner errors immediately at source-path resolution and writes a `failed` manifest of its own.

This is intentional: it lets the chain survive transient OOM events that
the OOM-tolerant tuner can recover from on its own. **Downstream iterations
are NOT auto-cancelled** — if you decide a chain is unrecoverable, you
must `scancel <iter_N+1_id> <iter_N+2_id> ...` manually.

Diagnosing iter 1's failure:
1. Read `sdsc_submission_scripts/logs/iter_XXXXXXXX.err` first.
2. If it ends with `slurmstepd: ... CANCELLED ... DUE TO TIME LIMIT`, the
   walltime was too short — bump `--time` or reduce `--max_rounds` /
   `--max_epochs`, and check the runtime breakdown in `.out` (look for the
   gap between `[Step 1/3] Training...` and `[Step 2/3] Inference...`).
3. If `sacct -j <jobid>` shows `State=OUT_OF_MEMORY`, **iter 1's host RAM
   exceeded `--mem`**. The python tuner may still have written a valid
   manifest (see "Validated end-to-end on SDSC" — this is exactly what
   happened in `exploration_chain_test_v1`). With `afterany` the chain
   survives; with `--mem 48G` it shouldn't recur.
4. Fix, choose a new workspace dir, resubmit.

---

## Recommended order of operations

1. **Lilab `test_chained_iterations` first** (entry point 1, ~25 min). The
   pytest exercises exactly the same code path as the bash orchestrator;
   it's the cheapest signal that the schema, advice loading, and manifest
   round-trip all work on the latest code.
2. **(Optional) `run_chain.sh --mode lilab` next** (entry point 2,
   ~25 min). Same scope as the pytest but produces durable artifacts under
   `/home/klz/Data/SIDEREIS_DATA/lilab_chain_v*` so you can inspect manifests
   and per-round outputs after the run. Useful when debugging or when you
   want to keep results. Add `--dry-run` first to walk the loop and
   eyeball the §3.2 plan-flag header without touching the workspace.
3. **Once lilab is green, submit SDSC** (entry point 2 with `--mode sdsc`).
   Watch iter 1 closely until you've confirmed `iter_001/manifest.json` is
   written *and* iter 2 (47913515 in the most recent run) has actually
   started — that's the moment of truth for the chain plumbing on SDSC.
4. **Don't run lilab and other GPU work simultaneously.** The test will
   conflict with anything else using the lilab GPU and may hit CUDA launch
   timeouts (display GPU watchdog kills kernels >2s when GPU is shared).
   `nvidia-smi` before launching.

---

## Notes on trial vs formal mode (read this if walltime matters)

Each iteration runs `max_rounds` rounds. The **last round of each iteration
is forced into "formal" mode** by the tuner (`nodes/ml_hyperparameter_tune_agent.py`):

- `is_trial = False` is forced on the last round.
- `eval_portion` is forced to **`1.0`** (full evaluation data) regardless of
  what the LLM picked or what `--eval_portion` was passed to the orchestrator.
- `trial_portion` and `train_portion` (training data scope) remain
  LLM-controlled — they are *not* overridden in formal mode, so the LLM is
  free to pick a small training fraction even in the formal round.
- `target_files` is forced empty, so any LLM that picked
  `trial_strategy="target"` for the trial rounds must switch to `"snapshot"`
  for the formal round.

**Practical implication: the formal round is always the dominant cost** of an
iteration, because eval has to inference + score every segment of all 20 files.
Trimming `--trial_portion` / `--eval_portion` only speeds up the trial rounds,
not the formal round. If you want a faster chain run, reduce `--max_rounds` or
`--max_epochs`, not the data portions.

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| Iter 1 hits walltime, iter 2 still runs but errors at source-path resolution | Single round took too long (LLM picked too many epochs, or formal-round eval ran on full data); iter 1 never wrote a manifest | Confirm `--max_epochs` is set; tighten `tune` advice in JSON; bump `--time` |
| Iter 1 sacct shows `OUT_OF_MEMORY` but logs say "COMPLETED SUCCESSFULLY" | Cgroup OOM killer hit a child process during the run; the OOM-tolerant tuner caught it, recorded `error_training_oom`, and continued. Slurm permanently records the in-job OOM event in accounting state, even though the python workflow eventually succeeded. | **Historical (mitigated in `_chain_common.sh` defaulting to `--mem 48G`).** The chain now uses `afterany` (not `afterok`), so iter 2 still runs and reads iter 1's valid manifest. If you actually run out of host RAM at 48G too, bump higher. |
| `manifest.json` missing after iter 1 "finished" | Workflow raised an exception before manifest write | Check `iter_XXXXX.err` — runner writes `manifest.json` only on clean exit |
| Iter 2 fails with `Manifest not found` at source-path resolution | Iter 1 truly failed at the python level (no manifest, or manifest with `status=failed`) | Diagnose iter 1's failure; with `afterany`, iter 2 was supposed to start anyway and surface the error. Don't use `--kill-on-invalid-dep=yes` to mask it. |
| Iter 2 fails with `pydantic ValidationError: Input should be a valid number ... input_value=None` on `file_vector` | **Historical (fixed in `313c45c`)** — old-schema `Optional[List[float]]` rejected JSON `null` elements that pydantic produced from `NaN` floats. The schema is now `Optional[List[Optional[float]]]` and the writer uses Python `None`. | Should not recur. If it does, you're running pre-`313c45c` code somewhere — `git pull` and resubmit. |
| `Resolved @manifest:... → ...` shows wrong model name in iter 2 | Stale workspace from previous run | Always use a fresh `--workspace` directory |
| CUDA launch timeout on lilab only | Display GPU watchdog kills kernels >2s when GPU is shared with other processes (e.g. another user's tensor job, or the X server) | Don't run lilab chain when GPU is contended; check `nvidia-smi` first |
| `bank_limit plugin` rejection on SDSC | Missing `--ntasks=1` or wrong GPU spec | Already handled by `run_iteration_chain.sh`; don't edit the sbatch args block |
| `Nodes required for job are DOWN, DRAINED or reserved` on SDSC | Specific GPU type is unavailable on `gpu-shared` at submission time (transient) | Wait a few minutes; if persistent, paste `scontrol show job <id>` output for diagnosis. Often resolves itself within an hour. |
| Lilab orchestrator fails immediately with `ModuleNotFoundError: No module named 'dotenv'` | Old version of `run_iteration_chain_lilab.sh` invoked system `python3` instead of `uv run python` | **Historical (fixed in `86cee48`)**. Should not recur — script auto-detects `uv`. |
| SDSC slurm `.out` file empty for hours despite job running | Old slurm scripts didn't set `PYTHONUNBUFFERED=1`, so python's block-buffered stdout never flushed to disk until the process exited | **Historical (fixed in `331d7c1`)**. `submit_one_iteration.slurm` and `submit_hpt_agent.slurm` both export `PYTHONUNBUFFERED=1` now. |

---

## Files referenced

- **`sdsc_submission_scripts/run_chain.sh`** — **canonical** unified orchestrator (since Phase 6.8 Commit 13.A). Sources `_chain_common.sh`, dispatches `submit_iteration_lilab` / `submit_iteration_sdsc` based on `--mode`. The single user-facing entry point for all real chain runs.
- `sdsc_submission_scripts/_chain_common.sh` — shared logic across modes and the legacy stubs (defaults, arg parsing, advice loading, source-path building, APP_ARGS construction, chain loop, `parse_chain_args`, `build_app_args`, `run_chain`)
- `sdsc_submission_scripts/run_iteration_chain.sh` — **deprecated** legacy SDSC stub. `exec`s into `run_chain.sh --mode sdsc`. Removal tracked under Commit 15.
- `sdsc_submission_scripts/run_iteration_chain_lilab.sh` — **deprecated** legacy lilab stub. `exec`s into `run_chain.sh --mode lilab`. Removal tracked under Commit 15.
- `sdsc_submission_scripts/submit_one_iteration.slurm` — Slurm wrapper for one iteration (SDSC only)
- `sdsc_submission_scripts/run_one_iteration.py` — Python runner: `run_workflow(max_iterations=1)` + manifest write (used by both lilab and SDSC)
- `advice/workflow/human_advice_chain_test.json` — shared advice file (5 keys: interpret/propose/implement/validate/tune)
- `tests/integration/workflows/test_full_exploration_loop.py` — lilab Tier 3 pytest tests
- `workflows/model_exploration.py` — `run_workflow()` implementation
- `agent/schemas/run_metadata.py` — typed `BaseRunMetadata` hierarchy. Today only `TunerRunMetadata` is implemented (written by `run_comparison.py` to `{agent_workspace}/tuner_run_metadata.json`); workflow-level and chain-level subclasses will land later and reference lower-level metadata files via `child_metadata_paths`.
- `docs/full_loop_5_agents.md` — design doc (companion to this runbook)
