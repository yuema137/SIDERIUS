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

### Stopping a chain or the queue (C13, operator surface)

Killing the iteration Python used to end only that child — `run_chain.sh`
then started the next iteration anyway (the V19 wave-1 respawn). Stopping
now ends the LOOP, and every stop leaves an explicit record.

**Stop one chain.** Either is sufficient:

```bash
touch "$WORKSPACE/STOP"          # graceful: finishes the current iteration
kill -TERM <run_chain.sh pid>    # same effect; the trap stops the loop
```

The chain finishes the iteration it is in, starts no further iteration,
writes `$WORKSPACE/chain_stopped.json`, and exits **99**. Killing the
iteration Python directly also works: a child that exits `128+N` is
treated as an external stop, and the loop does not continue.

| Env | Default | Purpose |
|---|---|---|
| `CHAIN_STOP_FILE` | `$WORKSPACE/STOP` | Where the chain looks for a stop request. |

`chain_stopped.json` records `reason`, `signal`,
`stopped_before_iteration`, `iterations_planned`, `run_name`,
`workspace`, `chain_pid`, `stopped_at` and `respawn: false`.

**Stop the queue.** Same two channels, at the runner:

```bash
touch "$WS_ROOT/$CAMPAIGN_ID/control/STOP"   # or: kill -TERM <v19_queue_runner.sh pid>
```

> **This path changed (V20 PR E).** It used to be `$WS_ROOT/STOP`, one
> file shared by every campaign under the root — so on 2026-07-31 an
> operator stopped one campaign and stopped an unrelated one with it.
> The stop file now lives inside the campaign it stops. **A file at
> `$WS_ROOT/STOP` no longer stops anything**: the launcher logs it,
> appends a `legacy_global_stop_observed` record, and continues. It is
> never deleted — removing it is an operator act, and its mtime is
> evidence for reconstructing that incident.

The queue lets the running wave finish, launches no further wave, appends
a `queue_stopped` record to
`$WS_ROOT/$CAMPAIGN_ID/queue_state/wave_state.jsonl`, and exits 99. A
chain that exited 99 is logged as stopped-on-request and does **not**
produce a targeted-restart suggestion.

The **chain**-level stop above is unchanged: `$WORKSPACE/STOP`,
`chain_stopped.json`, exit 99, and the traps all behave exactly as
before.

| Env | Default | Purpose |
|---|---|---|
| `QUEUE_STOP_FILE` | `$WS_ROOT/$CAMPAIGN_ID/control/STOP` | Where the queue looks for a stop request. Only the DEFAULT moved; an explicit value still wins, for compatibility with existing habits and scripts. It is not a general-purpose relocation knob — use `CAMPAIGN_HOME` to move a campaign. |
| `WAVE_WALL_SECONDS` | `259200` (72 h) | Bound on how long one wave may be waited on. On breach the QUEUE stops and records `wave_wall_cap_exceeded`; running chains are left alone — killing them stays an operator act. |

Reasons: `operator_stop_requested`, `iteration_terminated_by_signal`,
`wave_wall_cap_exceeded`. A wave summary is written on every exit path,
including a failed launch (`disposition: launch_failed`).

An ordinary non-zero iteration is **not** a stop: the frozen continuation
policy is unchanged, because the no-respawn rule is scoped to an
operator-directed stop.

### Campaign control state (V20 PR E, operator surface)

Campaign identity used to be a filename **prefix** under a shared root,
and a prefix is easy to forget — `QUEUE_STOP_FILE` omitted it entirely.
It is now a **directory**, which cannot be forgotten the same way.

```text
$WS_ROOT/                                campaign COLLECTION root
├── <campaign_id>/                        one campaign's control state
│   ├── control/
│   │   ├── campaign.json                 identity stamp
│   │   └── STOP                          operator-created; read ONLY here
│   ├── queue_state/
│   │   ├── wave_state.jsonl              canonical history
│   │   └── queue_runner.log
│   └── pair_summaries/
│       └── wave_<n>_<band_tag>.json      derived per-wave view
├── <run_name>/                           chain workspace (UNCHANGED, flat)
├── <campaign_id>_wave_state.jsonl        LEGACY — read only under adoption
├── <campaign_id>_queue_runner.log        LEGACY — never read, never written
└── STOP                                  LEGACY GLOBAL — observed, no authority
```

`$WS_ROOT`'s default is `/home/klz/Data/SIDEREIS_DATA/v19`. The name
looks like a campaign but is not one: it is a **collection root**, and
two campaigns living under it is the normal case — the case that broke.

Chain workspaces stay flat at `$WS_ROOT/<run_name>`. Run names already
carry the campaign id, and moving them would break `campaign_spend.py`
and every historical report path.

| Env | Default | Purpose |
|---|---|---|
| `WS_ROOT` | `/home/klz/Data/SIDEREIS_DATA/v19` | The campaign collection root. |
| `CAMPAIGN_ID` | `v19` **when unset** | Names the campaign home and every run. See the unset/empty rule below. |
| `CAMPAIGN_HOME` | `$WS_ROOT/$CAMPAIGN_ID` | The one knob that moves a campaign, coherently. |

`control/`, `queue_state/` and `pair_summaries/` are **derived from
`CAMPAIGN_HOME` and are not independently overridable**. Separate
overrides would let two campaigns be aimed at one state directory, which
is the defect this layout removes; a configuration surface that can
reconstruct the defect is not a configuration surface.

#### Unset is not the same as empty

```text
CAMPAIGN_ID unset             -> `v19`, the compatibility default
CAMPAIGN_ID explicitly empty  -> REFUSED before anything is created
```

`GATE_RUN_PREFIX` behaves identically (`v19_c14` when unset). Clearing
one of these on the command line is how an operator says "not that
identity" — so it must refuse, not silently hand back the default and
write into that campaign's control state.

#### Valid campaign ids and Gate prefixes

Both go through one rule, because both become path components:

```text
1-128 characters from [A-Za-z0-9._-]
and not exactly `.` or `..`
```

Refused: empty, `.`, `..`, anything containing `/` or `\`, absolute
paths, control characters, and values over 128 characters. An invalid id
is refused **before any directory is created**.

`alpha..beta` is **valid**. The rule rejects an id that *is* `.` or
`..`, never one that merely *contains* two dots — separators are already
excluded, so the id is always a single path segment and cannot traverse.

#### Resuming a campaign that predates this layout

Adoption is a **campaign-level decision made once**, at the moment the
campaign's stamp is created:

```text
first start (no campaign.json yet)
  AND $WS_ROOT/$CAMPAIGN_ID/queue_state/wave_state.jsonl does not exist
  AND $WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl does exist
    -> campaign.json records `legacy_adopted_from: <that path>`
    -> this campaign may read that file for completion evidence, read-only
```

Once the campaign has its own `wave_state.jsonl`, the legacy file is
**never consulted again**. In particular: if a run is recorded complete
*only* in the legacy file and the campaign did not adopt it, **that run
is launched**. There is no per-record fallback — a file the campaign
never adopted does not get to decide that work is finished.

Adoption is scoped to one campaign's own legacy file: `alpha` cannot
adopt `beta_wave_state.jsonl`. Legacy files are read-only; nothing on
disk is moved, rewritten or deleted, and their bytes and mtimes are
unchanged by any run.

#### Wave records: canonical history, derived view

```text
queue_state/wave_state.jsonl          canonical, append-only
pair_summaries/wave_<n>_<tag>.json    derived, overwritten
```

The canonical line is appended and `fsync`ed **first**; only then is the
per-wave file atomically replaced. A failure between the two loses the
convenience, never the evidence — and a per-wave file with no matching
canonical line is a detectable inconsistency, not a normal state. If the
derived write fails the queue stops and says so; the canonical record is
kept and the per-wave file can be rebuilt from the JSONL.

Both carry the same `record_id`:

```text
<campaign_id>:<wave>:<band_tag>:<attempt>
```

`attempt` is counted from the canonical file, so a queue restart cannot
reset it. A retried wave leaves two canonical records with different ids
and one per-wave file holding the later one. **Per-wave files for
historical waves are not rebuilt automatically.**

The wave record is chain-list-shaped, so a campaign with one chain, or
five, or other role names needs no schema change:

```json
{"wave_summary": 1, "record_id": "v19:1:15_19:1", "campaign_id": "v19",
 "band": "15-19", "band_tag": "15_19",
 "chains": [{"run_name": "v19_arch_15_19", "role": "arch",
             "pid": "1111", "exit": 0}],
 "start": "…", "end": "…", "disposition": "complete"}
```

The field inside `chains` is **`run_name`**, not `run`, and that is
load-bearing: the completion check greps the whole line for
`"run": "<name>"` followed by `"exit": 0`, so a bare `run` key would let
one chain's success mark every chain in the wave complete — including one
that failed.

`exit: -1` means the chain left no exit marker. When a role cannot be
resolved from the ROSTER it is recorded as `null` and the record also
carries `role_resolution_failed: true` and `unresolved_roles: [...]`,
rather than being guessed.

The six `arch_*` / `loss_*` keys are a **compatibility mirror**, emitted
only when a wave has exactly two chains whose roles are exactly `arch`
and `loss`. Any other shape gets `chains` and no mirror — an invented
`arch_exit` would show up in a report as though it were measured.

#### Gate artifacts

```text
$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json
$GATE_ROOT/${GATE_RUN_PREFIX}_runner.log
```

A prefix, not a directory: the Gate has no directory model. The summary's
`"gate"` field is the resolved prefix, so two Gate runs under one
`GATE_ROOT` no longer overwrite each other and are distinguishable by
their own contents. Pre-existing `gate0_pair_summary.json` and
`gate0_runner.log` keep their names and contents as historical
artifacts; nothing reads, moves or deletes them.

**The Gate has no STOP file and gains none here.** Its summary is written
on every exit path by an `EXIT` trap, and its wall cap is unchanged.

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

### Watchdog safety factors — ALWAYS pass them (empirical, lilab)

`_chain_common.sh` defaults `RUNTIME_SAFETY_FACTOR=1.0` to mirror the
Python schema default. That is correct as a schema default and
**dangerous as a launch value**: the watchdog deadline is
`predicted × safety_factor`, so 1.0 means **zero margin** — a run that
exceeds its own RT2 prediction by a fraction of a percent is killed.

Any run passing `--runtime_watchdog` should also pass the V18r posture
(from `sdsc_submission_scripts/launch_v18_wave1.sh:125-127`):

```bash
--runtime_watchdog \
--runtime_safety_factor 1.5 \
--runtime_trial_safety_factor 3.0 \
--runtime_formal_safety_factor 2.0
```

Trial gets the largest factor (3.0) because trial rounds run
LLM-invented architectures with no historical prior, where the
prediction is least reliable. Formal 2.0 is the operator decision in
`a780186`.

**Failure signature when you forget** (observed 2026-07-28, V19 PR 2
Gate 2 attempt 1 — three consecutive kills):

```
watchdog killed training after 118.112s (deadline 117.866s, source=verified_components)
```

Overshoot under 1%, killed at 96-98% of the epoch,
`source=verified_components`. That combination means the prediction was
ACCURATE and the margin was ABSENT — it is not evidence that the model
is too large or that the feature under test slowed training down. Do
not let the planner chase it by shrinking the architecture.

Copying an older Gate command verbatim is how this gets missed: the
V19 PR 1 Gate 2 command omits these flags and happened to pass. Check
new launch plans against `launch_v18_wave1.sh`, not against the
previous PR's command. Full note:
`docs/memories/project_watchdog_safety_factor_lilab.md`.

### Selective launching and runtime provenance (V19 O1a/O2)

**Selective launching (`--only`)** — `launch_v18_wave1.sh` accepts an
optional chain filter within the phase roster:

```bash
bash sdsc_submission_scripts/launch_v18_wave1.sh 1a --only v18r_loss_04_09
bash sdsc_submission_scripts/launch_v18_wave1.sh 1b --only v18r_arch_10_14 --dry-run
```

Omitting `--only` launches the full phase roster exactly as before.
Names come from the phase's roster; unknown names, duplicates, and
blank selections fail BEFORE preflight (listing the valid names), with
no fallback to the full set. Multiple names are comma-separated and
always launch in canonical roster order regardless of the order given;
the resolved selection is echoed as `[selection]`. Launch selection is
operational only — it does not touch any chain's workspace,
run-invariants lock, or resume semantics.

**Runtime hardware provenance (recording-only)** — every run's
canonical hardware manifest `{workspace}/{run_name}_hardware.json`
(written at run start, reused by subprocesses) now also records:
platform, Python version, `CUDA_VISIBLE_DEVICES`, ALL visible GPUs in
logical-index order (name/memory/compute capability), the NVIDIA
driver version (bounded best-effort `nvidia-smi` probe), the repo
commit, and `collection_errors`. All new fields are best-effort: a
failed probe records an explicit error entry and leaves the field
null — collection can never abort a run, values are never fabricated,
CPU-only hosts record an explicit unavailable state, and no
environment variable other than `CUDA_VISIBLE_DEVICES` is captured.
Old manifests remain loadable; behavior (training, admission,
watchdog, scoring) is unchanged.

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

### Data-ordering override (V19 PR 2)

Ordering — the sequence in which selected training samples are visited —
is **agent-proposable** and **operator-overridable**. The execution
system resolves the value that runs:

```text
operator override  >  agent proposal  >  default ("shuffle")
```

Two chain flags, both forwarded only when set (an unset override
reproduces pre-V19 argv exactly):

| Flag | Default | Meaning |
|---|---|---|
| `--order_strategy_override` | unset | Force `shuffle` or `sequential` for **every round of the chain**, overriding any agent proposal. |
| `--file_order_override` | unset | File visitation **order** for `sequential`, e.g. `4,6,5,9,7,8`. Order is preserved as written and must be a full permutation of the resolved `DataScope`. Range syntax (`4-9`) is rejected — a range cannot express an order. Omit for ascending file index. |

Two supported chain modes:

- **Forced comparison** — set the override. Every round resolves to it;
  agent proposals are still recorded but not executed. Use this for a
  controlled ordering experiment, where a varying ordering would
  confound the comparison.
- **Agent exploration** — leave the override unset. Ordering may vary
  round to round as the agent proposes; each round records its own.

**Resume rule:** the OVERRIDE is pinned in `run_invariants_lock.json`,
so changing it mid-chain is a violation — the chain's control policy
cannot silently shift underneath a comparison. Adding an override to a
chain that started without one (or removing one) requires a new
workspace, the same rule as a scope change or a HealthGate flip. The
per-round RESOLVED ordering is deliberately **not** locked, since it may
legitimately vary in exploration mode.

Where to look afterwards: the tuner prints a `[data_order]` line per
round naming all three levels; the training engine prints one per epoch
with the resolved values and epoch seed; each iteration's `manifest.json`
carries `ordering_by_experiment`, keyed per experiment.

See `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
under "Data-ordering resolution" for full semantics.

### Structured HealthGate feedback (V19 PR 3)

Three chain flags (all forwarded by `run_chain.sh` only when set — an
unset policy reproduces pre-PR3 argv exactly):

| Flag | Default | Meaning |
|---|---|---|
| `--enable_structured_health_feedback` | off (`False`) | Render structured HealthGate evidence in the interpreter and proposer prompts: per-round `[GATE ...]` trajectory labels + a `### HealthGate summary` section for the interpreter; one `[HEALTHGATE EVIDENCE]` block for the proposer. **OFF: every agent-facing prompt is byte-identical to pre-PR3** (golden-parity tested); the deterministic evidence — per-round `RoundHealth`, collapse fingerprints, and the bounded cross-iteration history — is still recorded in the experiment records, the interpretation digest, and the manifest regardless (recording-only provenance). Informational only — never routes, rejects, or scores anything. |
| `--health_feedback_history_window_iterations` | `3` | Fingerprint-history retention window: the TOTAL number of iterations retained INCLUDING the current one (window 3 at iteration 5 retains 3, 4, 5). Must be `>= 1` — an invalid value fails at startup, before any resume mutation or LLM work. |
| `--health_feedback_history_max_entries_per_model` | `8` | Deterministic per-model trim bound on retained history entries. Must be `>= 1`; same startup validation. |

**Resume rule:** all three values are pinned in
`run_invariants_lock.json` at every lock site (tuner, workflow, chain
runner). Changing any of them on the same workspace fails startup with a
`RunInvariantsViolation` naming the field and both values. A legacy
(pre-PR3) workspace resolves to `False` / `3` / `8` and resumes cleanly
with the defaults — but turning the flag ON over such a workspace is a
canonical mismatch and requires a NEW workspace, exactly like a scope
change or a HealthGate flip.

> **Experimental status (V19 PR 3, final).** This optional feature is
> fully implemented and operationally validated, but no universal
> performance-improvement claim is made. A controlled 40-sample
> descriptive evaluation (Control vs Treatment, 4 scenario families)
> found more precise evidence grounding in some scenarios (exact gate
> and fingerprint naming, supported feedback-use claims), no primary
> behavioral improvement under the tested fixtures, and no observed
> safety regressions in either arm. Its effect is context-dependent —
> do not assume improvement without task-specific evaluation. The
> default remains OFF; enabling it on an existing default-OFF
> workspace is rejected by the run-invariants lock — use a new
> workspace.

Where to look afterwards: each iteration's `manifest.json` carries the
`health_feedback_policy` control stamp (flag + the two retention
values — policy only; per-round gate evidence stays in the records and
the interpretation digest); the tuner's `run_config_{run}.json` stamps
the same three values; the interpretation digest carries
`per_model_round_health_counts`, `per_model_collapse_fingerprints`, and
the merged `collapse_fingerprint_history` whether the flag is on or off.

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

## New GPU host — bring-up and revalidation runbook (V20 PR B)

**Why this exists.** The code is hardware-generic: devices are keyed by
UUID, ceilings come from configuration, and a measurement from one card
is never silently reused on another. That makes a new host *possible*.
It does not make it *reproducible* — this runbook is what makes it
reproducible, and it must be followed in order on every new GPU host.

**The one-sentence rule:** measurements are bound to a GPU UUID, so
moving hardware invalidates every stored figure for admission purposes,
even for a byte-identical candidate.

### 0. What is per-host, per-candidate, and neither

| Scope | Items | Repeat when |
|---|---|---|
| **Per host** (once) | GPU UUID, ceilings, host quota, concurrency, telemetry policy | new machine, new GPU, driver change that alters UUID |
| **Per candidate + phase** | driver-visible peak for that config on that UUID | any change to config, batch, segment, portions, task, data shape |
| **Neither** (generic) | the commands below, the admission logic, the attribution vocabulary | never — no production edit should be needed |

### 1. Resolve the new hardware identity

```bash
nvidia-smi --query-gpu=index,uuid,name,memory.total --format=csv
```

Record the **UUID**, not the index. `CUDA_VISIBLE_DEVICES` changes
indices; it does not change UUIDs. The run's own hardware manifest
(`core/hardware_context.py::write_manifest`) stamps the UUID it actually
used — check it agrees.

### 2. Confirm no existing measurement applies

Any figure recorded on another UUID is **not** applicable, however
similar the hardware. There is no "close enough": a measurement either
matches the applicability tuple or it does not.

```text
normalized candidate config · phase · task · dataset/data-shape class
· runtime settings · measurement type · GPU UUID
```

Expected consequence on a fresh host: `formal` mode refuses every
candidate with `reason_code=measurement_unavailable`. **That is the
system working, not a defect.**

### 3. Configure the host's limits — do not edit code

These are **hardware-owned configuration**, not framework constants:

| Value | Source | Default |
|---|---|---|
| aggregate pair ceiling | `SIDERIUS_PAIR_VRAM_CEILING_GIB` | `28.0` GiB (`pair_admission.py:45`) |
| host per-user quota | `SIDERIUS_GPU_VRAM_QUOTA_MIB` | **undeclared = unknown, not unlimited** |

> **Concrete hazard on a larger card.** The `28.0` GiB default was chosen
> for a 31.34 GiB RTX 5090. On an 80 GB H100 it would silently cap the
> device at 28 GiB and refuse legitimate work as
> `insufficient_headroom` — which reads as "the device is busy" rather
> than "the ceiling is misconfigured". **Set the ceiling explicitly on
> any host whose card is not ~32 GiB.**

The effective ceiling is `min(configured, measured device capacity)`:
policy may be stricter than the hardware, never looser. Both figures are
recorded on every admission decision, so a later reader can tell which
one bound.

### 4. Collect a bounded measurement on the new device

Run one candidate, one round, one attempt, one epoch, small portion, on
an otherwise idle card. What you need from it is the **driver-visible
peak** for that candidate and phase — not the pre-flight estimate, which
is a different quantity (see
`agent/skills/evaluate_vram_skill/evaluate_vram_skill.md`).

Precondition, checked before starting:

```bash
nvidia-smi --query-compute-apps=pid,used_gpu_memory,gpu_uuid --format=csv
# expect: header only — no compute apps
nvidia-smi --query-gpu=memory.used --format=csv
# expect: the host's idle baseline
```

### 5. Validate applicability and promote — PR C, not PR B

PR B **consumes** an applicable authoritative measurement. It does not
decide applicability and does not promote. Until PR C supplies that
path, a new host has no authoritative measurement and `formal` mode
stays refused. Do not work around this by hand-writing a registry entry
or by pointing admission at a predicted estimate — that reintroduces the
defect PR B exists to remove, behind a guard that then looks like it is
working.

### 6. Permit test — the equivalent of B-G1

With an applicable measurement and an idle card, a GPU phase must
**start** and produce artifacts identical to the pre-admission path.

### 7. Refusal test — the equivalent of B-G2

Two distinct refusals, both required:

| Scenario | Setup | Expected |
|---|---|---|
| cold start | `formal`, no applicable measurement | `measurement_unavailable`, no subprocess |
| contention | applicable measurement + a controlled holder so occupancy + requirement > ceiling | `insufficient_headroom`, no subprocess |

Use a **deliberate, bounded memory holder** pinned to the same UUID
rather than incidental load: its PID and occupancy are then known, so a
refusal is attributable rather than merely observed. Record the holder's
**measured driver-visible** MiB — never the requested tensor size; they
differ.

### 8. Verify cleanup

```bash
pgrep -af "train_engine_sandbox.py|inference_single.py|preflight_worker_main"
nvidia-smi --query-compute-apps=pid,used_gpu_memory,gpu_uuid --format=csv
nvidia-smi --query-gpu=memory.used --format=csv
```

All three must show the host back at its idle baseline with no
survivors. A GPU child that never started leaves no artifacts — absence
of a checkpoint is part of the evidence that a refusal really refused.

### 9. Interpreting the result

| Outcome | Meaning |
|---|---|
| **PASS** | permit started and produced artifacts; both refusals occurred before any subprocess launched; GPU returned to baseline |
| **FAIL** | a phase started despite a refusal, or a refusal blamed the candidate, or a measured-headroom shortfall was admitted |
| **INCONCLUSIVE** | card not idle at start, telemetry unavailable, holder occupancy materially off target, or any orphan process |

**INCONCLUSIVE is not FAIL.** It means the conditions for a verdict were
not met — rerun; it does not mean the guard is broken.

### 10. Refusals never blame the candidate

None of `measurement_unavailable`, `policy_unavailable` or
`insufficient_headroom` is evidence about model size, and none carries
authority to shrink anything. A record with
`status="skipped_resource_admission"` is a statement about the machine.
Only a **measured** capacity failure — attribution
`candidate_gpu_capacity` — may say the candidate was too large.

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
| Records with `status="skipped_resource_admission"` and no score | **Expected since V20 PR B.** Driver-visible GPU occupancy is measured before each training/inference phase; when the device cannot currently hold it, the phase is refused and never starts. The record consumes the attempt slot but is **not** a candidate failure — no score, no shrink advice, no incumbent update. Check `memory.reason_code`: `insufficient_headroom` (something else held the card), `measurement_unavailable` (formal mode with no applicable authoritative measurement — expected until PR C lands), `policy_unavailable` (misconfigured `admission_mode`; the accepted values are `trial` and `formal`). | Nothing to fix if it is `insufficient_headroom` on a shared GPU — check `nvidia-smi` for the other holder. Default posture is `trial`, which proceeds and only records what it could not prove. |
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
