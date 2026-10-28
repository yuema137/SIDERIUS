# CI Parity — the execution contract

**Lane**: CI Parity & Hermetic Test Harness.
**Status**: Phase 1 parity contract and manifest schema, plus the current
selective-PR usage added after the harness was connected.
**Base**: `84d74280` (landed master).

A test result is meaningful only if you can say what environment produced it.
This document says what that environment is — including, deliberately, what it
must **not** contain.

---

## 1. Responsibility split — three authorities, never merged

| authority | question it answers | owner |
|---|---|---|
| `tools/ci_selection/` | **WHAT** should run? | selector authority |
| hermetic execution (this lane) | **HOW** does it run reproducibly? | `tools/ci/` |
| failure attribution (this lane) | **WHY** did local / base / remote outcomes differ? | `tools/ci/` |

`tools/ci_selection/` is the sole changed-files→pytest mapping. It is
fail-closed by construction: the workflow's selection step deliberately omits
`set -e` so that an unmapped path, a declared hub, a change to the selector
itself, or any exception all resolve to the full suite. Selection runs on
`pull_request` only. The harness **composes** it. A second selector is an
architecture violation, not an optimisation.

---

## 2. The execution-root contract

An **execution root** is a directory a parity run may execute in: the canonical
checkout, or a disposable worktree, or a shard's tree.

### 2.1 Interpreter — DECIDED: per-root `uv sync`

Every execution root MUST contain its own `.venv`, created by the **same
command CI uses**:

```bash
uv sync --group dev --frozen
```

Tests may then rely on `<repo>/.venv/bin/python` resolving inside their own
root — which two of them genuinely do, executing it as a subprocess
(`tests/unit/scripts/test_sdsc_argument_forwarding.py:262`,
`tests/integration/runner/test_token_log_iter_rollup.py:149`).

**Measured, at base `84d74280`:**

| property | value |
|---|---|
| `uv sync --group dev --frozen` in a fresh worktree | **1 s** |
| real incremental disk | **21 MB** |
| apparent size (`du -sh .venv`) | 7.6 G |
| resulting `.venv/bin/python` | `cpython-3.12.13-linux-x86_64-gnu` |
| `test_sdsc_argument_forwarding.py` in that root | **29 passed** |

The 7.6 G / 21 MB gap is uv hardlinking from `~/.cache/uv`. Bootstrapping a
shard is therefore cheap enough that no other option needs to win on cost.

**Why not the alternatives:**

- *Symlink `.venv` to the developer's environment.* This is what PR-12d's
  tactical clean room did, and its own manifest records the gap honestly:
  *"installed-package identity is assumed, not proven."* It also shares mutable
  state across concurrent shards. Rejected on identity, not on cost.
- *Refactor the tests to `sys.executable`.* That changes test semantics so an
  unprepared root happens to pass. The operator ruled this out, and correctly:
  the contract should be satisfied, not weakened.

`uv sync --frozen` resolves against the committed `uv.lock`, so dependency
identity is **proven by the lock** rather than assumed — and it is byte-for-byte
the CI bootstrap, which is the strongest parity available.

### 2.2 An unbootstrapped root is INVALID_HARNESS_EVIDENCE

A root without a satisfied `.venv` contract does not produce product failures.
It produces *fake* ones — PR-12d's parity worktree is the worked example.

The harness MUST detect this in preflight (§5) and refuse, rather than
launching ~13,000 tests and reporting dozens of misleading failures.

---

## 3. Positive environment state

| dimension | contract |
|---|---|
| source tree | a git checkout at a **known exact SHA**, immutable for the run's duration |
| Python | 3.12, via `uv python install 3.12` |
| dependencies | `uv sync --group dev --frozen` against the committed `uv.lock` |
| interpreter path | `<root>/.venv/bin/python` resolves within that root (§2.1) |
| working directory | the execution root |
| test command | `pytest tests/unit/ -m "not real_run" -q`, or the selector's `pytest_args` |
| markers | `real_run` deselected; real task data and training qualification live in external task packages |
| `TMPDIR` | per-shard, isolated |
| `HOME` | isolated unless a test's contract is explicitly about the user home |
| thread pools | pinned per shard — see §3.1 |

### 3.1 One pytest process is not one CPU — measured

During the CP-8 diagnostic run, a single `pytest tests/unit/` process consumed
**29 m 50 s of CPU in 6 m 52 s of wall time** — roughly **4.3 cores**, at 1.6 GB
RSS. The suite imports torch/numpy, whose thread pools default to the host core
count.

**Consequence for shard sizing**: shard count is *not* free up to `nproc`. On
this 24-core host, ~6 unconstrained shards already saturate it, and beyond that
the shards slow each other down while the wall-clock stops improving.

So a parity run MUST pin the thread environment per shard —
`OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS`,
`TORCH_NUM_THREADS` — and record the chosen values in the manifest
(`environment.thread_vars`). Two runs with different thread counts are not
comparable, and an unpinned run is not reproducible.

This also interacts with the sensitive lane: the timing tests assert that a
preemption mechanism fired within a bound, so they must run with the bulk lane
**quiesced**, not merely in a separate process.

### 3.2 The harness does not own the host — observed, not assumed

Midway through the CP-8 diagnostic, a **second SIDERIUS pytest process** was
running concurrently in `/home/yuema137/siderius-c12p-landed` (the C12-P lane),
consuming ~4 further cores on the same 24-core box. Nobody coordinated the two.

That is the normal condition on a shared lab machine, not an anomaly, and it has
three consequences the design must absorb:

1. **Skip and outcome identities remain valid.** Skip predicates are functions of
   configuration and environment, not of load, and the two lanes used different
   worktrees and different virtualenvs with no shared mutable state. CP-8's
   attribution is unaffected.
2. **Durations from a contended run are not costs.** JUnit `time` attributes
   collected under an unknown competing load cannot serve as shard weights.
   Weighting requires a measurement taken under a *declared* load condition —
   otherwise the harness balances against noise.
3. **A quiet sensitive lane cannot be assumed into existence.** Quiescing this
   harness's own bulk lane does not quiesce the host. The sensitive lane must
   therefore either acquire an exclusive host, or **detect contention and mark
   its results provisional** — and a timing failure under detected contention is
   `INVALID_HARNESS_EVIDENCE`, never a product regression.

The manifest records load at start and end for exactly this reason: a timing
result whose host conditions were not captured cannot be re-interpreted later.

## 4. Negative state — parity is defined partly by ABSENCE

A parity root MUST NOT contain, unless the test under study declares otherwise:

| must be absent | why it matters |
|---|---|
| `tidmad_data_config.yaml` | **proven live cost.** Its presence suppresses a `UserWarning` from `execute_tools/data_paths.py:30`. In CI run `32794899427`, a golden stderr comparison saw 24 lines where the fixture had 22 — solely this warning — and the test had passed on every developer machine |
| `dashboard_config.yaml` | same class |
| `.env` | same class; also risks activating real-provider paths |
| generated plugins (`agent_generated/`) | stale plugin state changes registry contents |
| prior workspaces / run artifacts | resume and lock logic reads them |
| stale caches, `__pycache__`, `.pytest_cache` | bytecode has faked mutation proofs in this repository before |
| arbitrary developer `HOME` state | unowned, unversioned, invisible |

**The tracked template is not machine config.** `tidmad_data_config.example.yaml`
is committed, and `data_paths` falls back to it *with a warning* rather than
failing (`data_paths.py:27-43`). A clean checkout therefore resolves
`TIDMAD_DATA_DIR = '/path/to/TIDMAD/'`, which does not exist — so real-data
tests skip with a named reason. That is correct behaviour and must be preserved.

### 4.1 Machine-local DATA is a parity dimension — CP-8

Config files were the suspected axis; **data is the real one**. Reproduced by
hiding these and unsetting the override variables: the suite goes from 5 skips
to 48 — exactly CI's count.

| resource | default location | override | skips it gates |
|---|---|---|---:|
| legacy TIDMAD reference repo | `/home/tidmad/TIDMAD` | `SIDERIUS_LEGACY_TIDMAD_ROOT` | 18 |
| real Pets images | `/home/klz/Data/OXFORD_IIIT_PET/images` | `SIDERIUS_PETS_DATA_DIR` (2 files hardcode it — CP-11) | 17 |
| real DAVIS frames | `/home/klz/Data/DAVIS_2017` | `SIDERIUS_DAVIS_DATA_DIR` | 5 |
| preserved DAVIS Gate-2 `.npz` | `/home/klz/Data/SIDEREIS_DATA/d14_davis_gate2_20260818c/` | — | 3 |
| generated-plugin corpus | `<root>/agent_generated/models` | — | 3 |
| V20 attempt-3 campaign root | — | `SIDERIUS_V20_ATTEMPT3_DIR` | 1 |

Every one of these skips **intentionally**, declaring its requirement with an
informative reason. The defect was never the skipping — it was that the
difference was **undeclared**, so two environments both called themselves
"parity" while 43 tests silently differed.

A parity run therefore MUST record resource presence in the manifest
(`resource_presence`), and a run that claims CI parity MUST have them **absent**.
An *invalid* override (set, but not a directory) is a hard failure by design and
must not be confused with absence.

**Absence must stay observable.** Untracked pollution is not to be hidden behind
a broad `.gitignore` rule: an ignore rule makes future pollution invisible,
which is the opposite of what this lane is for.

---

## 5. Preflight — refuse early, never mislead late

Before executing any test, a parity run MUST verify and record:

1. exact SHA resolved, and the tree matches it
2. source tree immutable for the run (no concurrent checkout/reset/edit)
3. `.venv` contract satisfied in **this** root (§2.1)
4. `HOME` strategy established
5. `TMPDIR` established and isolated
6. clean/dirty state appropriate to the lane being run
7. config presence/absence contract known and recorded

A violation yields **`HARNESS PREFLIGHT FAILURE`** with the specific unmet
condition — never a test run. The failure mode being designed out is:

```
launch 13k tests  ->  52 misleading failures  ->  hours of misattribution
```

---

## 6. Provenance manifest

Emitted by every formal parity run. **Designed to be diffed, not merely
emitted** — §24.10 requires field-level comparison between two runs
(candidate vs base, local vs remote), so the schema is flat and typed from the
start rather than retrofitted.

```jsonc
{
  "schema_version": 1,
  "run": {
    "id": "...",              // opaque, unique per run
    "mode": "targeted|affected|bulk|sensitive|github-parity|env-report",
    "started_at": "...", "finished_at": "..."
  },
  "source": {
    "sha": "84d74280...",     // exact, resolved
    "dirty": false,
    "branch": "...",
    "root": "/abs/path"
  },
  "interpreter": {
    "python_version": "3.12.13",
    "venv_path": "<root>/.venv",
    "venv_bootstrap": "uv-sync-frozen|preexisting",
    "lock_hash": "sha256:..."  // of uv.lock
  },
  "platform": {
    "os": "...", "kernel": "...", "arch": "...", "cpu_count": 0
  },
  "environment": {
    "home_strategy": "isolated|inherited",
    "tmpdir_strategy": "per-shard|inherited",
    "cwd": "/abs/path",
    "thread_vars": { "OMP_NUM_THREADS": "..." },
    "host_load": { "at_start": 0.0, "at_end": 0.0, "cpu_count": 0 },
    "var_names_present": ["..."]   // NAMES ONLY — never values
  },
  "config_presence": {
    "tidmad_data_config.yaml": false,
    "dashboard_config.yaml": false,
    ".env": false
  },
  "resource_presence": {                 // CP-8: the real skip axis
    "legacy_tidmad_root": false,
    "pets_images": false,
    "davis_frames": false,
    "davis_gate2_npz": false,
    "generated_plugin_corpus": false
  },
  "selection": {
    "authority": "tools.ci_selection|explicit",
    "pytest_args": "...",
    "full_suite": true
  },
  "shards": [ { "index": 0, "files": 86, "root": "...", "result": "..." } ],
  "result": {
    "passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "deselected": 0,
    "duration_s": 0.0
  }
}
```

**Secrets**: environment variables are recorded by **name only**. No value is
ever written, and the redaction is a tested property (§30), not a convention.

**Skip census** is first-class: `skipped` is compared against the banked
baseline on every run, because a hermetic harness that converts failures into
skips is worse than no harness (§28).

---

## 7. Banked baselines — do not re-measure for ceremony

| measurement | value | source |
|---|---|---|
| collected unit tests | 12,992 across 688 files | `--collect-only`, 3.89 s, base `84d74280` |
| largest directory | `tests/unit/agent` = 4,654 (36 %) | same |
| largest file | `test_health_core_census.py` = 129 (1.0 %) | same |
| CI install / ruff / pyright / pytest | 47 s / 1 s / 2 m 17 s / 10 m 28 s | `ci.yml:30` |
| CI full-suite green | 12,941 passed · 48 skipped · 0 failed, 21 m 24 s | run `32799116501` @ `a1d5c101` |
| local clean-room full suite | 12,986 passed · 5 skipped · 1 failed (CP-2), 19 m 46 s | PR-12d archived manifest @ `a1d5c101` |
| **sharded bulk, by-count, 8×2** | 654 s · RED (CP-12) | measured `84d74280` |
| **sharded bulk, WEIGHTED, 8×2** | **489.7 s · GREEN** | measured `84d74280` |
| sensitive lane (sequential) | 41 s · 5/5 PASS | measured `84d74280` |
| **aggregate local parity** | **530.7 s (8:51) — 2.67× vs serial** | weighted bulk + sensitive (8 shards) |

> **Every row above is LOCAL, on a 24-core host with the TIDMAD data mounted.
> Do not read them as CI improvements.** Measured on CI (run `32835810411`,
> fully green): bulk 524.3 s + sensitive 57.3 s = **581.6 s against a banked
> historical pytest step of 628 s — a ratio of 1.08×.**
>
> At the time this row was written a runner was assumed to have 4 vCPUs; the
> manifest of run `40616894222` later measured `cpu_count` 2 (§9). Within one
> runner scheduling cannot beat the CPU budget; and the weight table is
> calibrated to this host, so shard 0 carried the locally-dominant file and finished in **31.3 s** while its
> siblings ran 450–524 s. Correctly weighted for CI it would reach ≈ 1.69×.
>
> **On a runner this harness buys attribution, hermeticity and the sensitive
> lane — not speed.** Speed is the local benefit. See the audit's CP-15.

### Post-CP-12, on the merged candidate `a6223b33`

| configuration | wall-clock | result |
|---|---:|---|
| **weighted 4-shard (shipping default)** | **449.2 s** | 1 failure, since fixed |
| by-count 8-shard (the plan that exposed CP-12) | 478.2 s | 1 failure, same test |
| sensitive lane | 40.3 s | **5/5 PASS** |

**4 weighted shards beat 8** — 449.2 s against 489.7 s — on half the threads and
half the memory, confirming the shard-count analysis end to end rather than by
projection. The 460.3 s single-file floor plus fixed overhead is the whole
budget; shard 0 carries that file alone at 449.2 s and the other three finish at
285-319 s.

**CP-12 did not reappear in either run**, including the by-count plan where no
enabler is co-located ahead of the failing test. That is the discriminating
evidence: the earlier weighted green was assignment luck, this one is not.

The single failure in both runs was
`test_selection_model.py::…test_the_pytest_step_uses_the_selector_output` — an
existing guard catching a real flaw in this lane's own workflow change (the
changed-file list was derived twice). Fixed at the source; the guard was
strengthened rather than relaxed.

**Shard-count optimum is 4, not 8.** With weights the floor is one 460.3 s file,
so 4 shards reach it using 8 threads / ~6.4 GB where 8 shards spend 16 threads /
~12.8 GB for identical wall-clock. Anything beyond 4 is pure waste.

**A green weighted run is NOT evidence that CP-12 is fixed.** The weighted
assignment happens to co-locate a known enabler ahead of the failing test, so the
defect is masked by scheduling luck. Any change to the weights, the shard count
or the file list can re-expose it. It stays open until repaired at its source.

Re-measure only when test topology materially changes, the sharding
architecture needs new numbers, or a final benchmark needs comparable
before/after evidence.

**Open discrepancy (CP-8)**: the CI run reports **48 skipped** where the local
clean room at the same SHA reports **5**. A 43-skip divergence between two
environments both claiming parity is exactly what §28 exists to catch, and it
is not yet explained. Owned by this lane; see the audit's findings register.

---

## 8. Typecheck parity — CP-9 (CLOSED)

CI runs `.venv/bin/pyright` against the version `uv.lock` pins:
**1.1.409**. `pyproject.toml:51`'s `pyright>=1.1.409` is a floor, so the lock is
the authority.

The pyright wheel resolves its Node through `PYRIGHT_PYTHON_GLOBAL_NODE`
(`pyright/node.py:25`), which **defaults to the system Node**. On a host whose
system Node is too old — this one is v10.19.0, from 2019 — pyright is unusable
and local typecheck results are **NOT VALID EVIDENCE**.

**The contract**, measured in a fresh worktree with `env -i` and an isolated
HOME:

```bash
PYRIGHT_PYTHON_GLOBAL_NODE=false \
PYRIGHT_PYTHON_ENV_DIR=<stable harness-owned path> \
    <root>/.venv/bin/python -m pyright
```

| property | measured |
|---|---|
| resulting pyright | **1.1.409** — the locked version, unchanged |
| provisioned Node | **v26.7.0**, via nodeenv |
| HOME dependence | **none**, once `PYRIGHT_PYTHON_ENV_DIR` is pinned |
| default cache (no ENV_DIR) | `$HOME/.cache/pyright-python/nodeenv/` |
| first provision | **requires network** |
| subsequent runs | cache only, no network |

Two failure modes found while establishing this, both mine: pre-creating the
`ENV_DIR` makes nodeenv refuse it ("Environment already exists"), and a `tail -3`
on the output hid the version line and nearly produced a false "it doesn't work"
report.

**Bootstrap contract — declare, never hide.** A parity run that claims typecheck
parity MUST record, in the manifest's `typecheck` block:

```jsonc
"typecheck": {
  "pyright_version": "1.1.409",        // must equal the uv.lock pin
  "node_strategy": "managed-nodeenv",  // or "system"
  "node_version": "v26.7.0",
  "env_dir": "<pinned PYRIGHT_PYTHON_ENV_DIR>",
  "provisioned_this_run": false,       // true => network was used
  "network_required_on_first_provision": true
}
```

First provisioning **may require network**. That is a **bootstrap** dependency,
not a test dependency, and it is declared rather than discovered. Subsequent runs
reuse the managed runtime from the pinned `env_dir`; nothing may silently depend
on arbitrary user HOME cache state, which is why `PYRIGHT_PYTHON_ENV_DIR` is
pinned rather than left to default under `$HOME`.

**Residual — a stronger option not taken (DEFERRED, operator ruling).** `node.py:26` also supports
`PYRIGHT_PYTHON_NODEJS_WHEEL`: with `pyright[nodejs]` installed, Node arrives as
a Python wheel through the lock, giving **zero network dependency and no cache**.
That is strictly more hermetic, but it changes `pyproject.toml`/`uv.lock` and so
alters CI's own resolution. **Operator ruling 2026-08-24: keep the locked
pyright dependency; do NOT adopt `pyright[nodejs]` now.** It would change
repository dependency resolution, modify the lock and alter CI bootstrap
authority without being required to solve current parity. Revisit only in a
dedicated dependency/bootstrap change, and only if offline-first execution
becomes an explicit requirement.

**Preflight** recognises the managed strategy: when
`PYRIGHT_PYTHON_GLOBAL_NODE` is false the system Node is never consulted, so
checking its version would refuse a root that works. Without the strategy, an
old system Node remains a violation — a run must not claim typecheck evidence it
cannot produce.

---

## 9. The declared CI profile — 8 shards over a 4-job matrix, 1 thread each

The bulk lane plans **8 shards × 1 thread** and executes them across **4
parallel matrix jobs**, each running **2 shards** — one per runner CPU. The
sensitive lane runs alone in its own job.

**Why the split (issue #990).** The runner manifest of full-suite run
`40616894222` records `cpu_count` 2, `affinity_count` 2. The previous profile
ran 4 shards × 1 thread on that one runner — 2× oversubscription. Its bulk step
took 18 m 38 s (shards 1073 / 1116 / 867 / 1071 s) inside a ~22 min job, and
three later full-suite runs (`40619940595`, `40620503887`, `40621567296`) were
cancelled at the 25-minute ceiling with no verdict. Adding shards to one 2-CPU
runner cannot shorten it, so the work moves to more runners instead; the
timeout stays a resource ceiling.

### Job graph and status

| job | status name | runs | needs |
|---|---|---|---|
| `prepare` | `Lint + Type + Select` | docs classification, docs fast path, install, ruff, pyright, selector; uploads the ONE changed-file list as artifact `ci-changed-files` when the selection is narrowed | — |
| `unit` (matrix `job: [0, 1, 2, 3]`) | `Unit tests (bulk <i>)` | `python -m tools.ci bulk --shards 8 --job-index <i> --job-count 4 --threads 1` | `prepare` |
| `sensitive` | `Unit tests (sensitive lane)` | `python -m tools.ci sensitive` on a quiesced runner | `prepare` only — a RED bulk lane never skips it |
| `quality` | **`Lint + Type + Unit Tests`** | aggregate verdict (below) | all three, `if: always()` |

`quality` keeps the historical status name. It is GREEN only when `prepare`
succeeded and either the run took the documentation fast path (unit lanes
skipped by design) or `unit` and `sensitive` both succeeded **and**
`src/tools/ci/matrix.py verify` accepts the matrix reports. Because it runs on
`always()`, a failed or cancelled upstream job makes it RED rather than
skipped. `unit` uses `fail-fast: false` so one RED job never cancels the
evidence of its siblings.

Branch protection: as of this change `master` has no classic protection and
its only ruleset (`Master-Protection`) has no required status checks, so no
required-check name is affected. If a required check is added, require
`Lint + Type + Unit Tests` only; the matrix job names carry the index and are
not stable gate names.

### Assignment and the whole-run proof — `tools/ci/matrix.py`

* Every matrix job computes the **same** full plan:
  `plan_shards(selection, count=8, …)` is deterministic (§ `shards.py`) and every
  job consumes the same commit and the same `ci-changed-files` list. A narrowed
  verdict whose list is missing makes the job fail rather than plan the full
  suite alone.
* Job `i` executes the strided subset `job_shard_indices(8, 4, i)` =
  `{i, i + 4}`. LPT packing already balances the shards, so a job's wall time
  is its slower shard. `job_count > shard_count` is refused: a job with no shard
  would report green having executed nothing.
* Each job writes `matrix_report.json` (schema version 1: `job_index`,
  `job_count`, `shard_count`, `plan_digest`, `shards_run`, `ok`, `full_suite`,
  `files`) beside `bulk_result.json` and `run_manifest.json`, inside its
  `ci-parity-evidence-bulk-<i>` artifact. `plan_digest` is the SHA-256 of the
  WHOLE plan (every shard's index and files plus the sensitive set).
* `quality` downloads those artifacts and runs `verify`, which fails unless
  one report exists per job `0..job_count-1`, all agree on `job_count`
  (equal to `--expect-jobs`), `shard_count` (equal to `--expect-shards`)
  and `plan_digest`, each job ran exactly its assigned indices,
  the union is every shard index exactly once, every job reported `ok`, and no
  full-suite report has `files == 0`.
  The verifier is standard-library only, so the aggregate job runs it with
  `uv run --no-project python -I` and does not install the project.
* An empty shard (a narrowed selection with fewer files than 8) is recorded as
  trivially passed and **never launched**: `pytest` with no path arguments
  would fall back to `testpaths` and run the whole tree.

`matrix.job` in the workflow must list exactly `0..CI_BULK_JOBS-1`, and
`CI_BULK_SHARDS / CI_BULK_JOBS` must equal the runner CPU count. A matrix
entry `>= CI_BULK_JOBS` fails in that job's own `--job-index` argument check;
a MISSING entry leaves no report for its index and fails `verify`. `verify`
also receives `--expect-jobs "$CI_BULK_JOBS"` and `--expect-shards
"$CI_BULK_SHARDS"` from the workflow, so reports from a profile other than the
declared one are refused even when internally consistent. A full-suite report
with `files == 0` is refused in the harness (exit 2) and again by `verify`: an
empty test universe is a broken checkout, never a green run. The CPU ratio is a
declaration (see below).

Local reproduction: `python -m tools.ci plan --shards 8 --job-index <i>
--job-count 4` prints the plan plus the job's `shards`; the defaults
(`--job-index 0 --job-count 1`) reproduce the single-process harness exactly.

### Expected duration

Estimated from the per-test JUnit times of run `40616894222` (3,964 test-seconds
measured under 2× contention) applied to the 8-shard plan at `fc7e3cf8`: the
heaviest shard holds ~765 contended test-seconds and the median ~450. With one
shard per CPU the heaviest shard should take roughly 400–770 s (the bound is
the contention factor of the measured times), plus ~1.5 min install and ~40 s
collection per job, after `prepare` (~3 min). Expected critical path is about
10–17 min against per-job ceilings of 25 min (`unit`) and 15 min (`prepare`,
`sensitive`). The first matrix run's manifests replace this estimate.

The residual imbalance comes from `weights.json`, which is calibrated to the
24-core lab host (§7) and still names a split file that no longer exists (the
harness drops that split and says so). CI-calibrated weights would bring the
heaviest of 8 shards to ~495 contended test-seconds; regenerating them is a
separate change (#1004).

### Why declared rather than detected

A source audit found no trustworthy way to read the effective CPU budget:
Python 3.12 has no `os.process_cpu_count()`, `os.sched_getaffinity` does not
observe cgroup quotas, `/sys/fs/cgroup/cpu.max` is not readable here, and no
repository helper exists. A detector would carry false precision, so the
profile is explicit. Every run emits `run_manifest.json` recording the declared
profile *and* the observed facts — `cpu_count`, `affinity_count`,
`cgroup_cpu_max`, `runner_name`, `runner_os` — side by side, so a mismatch is
visible in the first remote artifact and any adjustment is made from fact.

### What the manifest carries

`schema_version` · `mode` · start/finish · source (sha, branch, dirty, untracked
count, root) · interpreter (python version, venv path, `uv.lock` sha256) ·
platform facts · declared profile including `thread_vars` and the
`unpinned_residual` · `config_presence` · `resource_presence` · selection
provenance (authority, full_suite, reason, file count) · per-shard results ·
totals with the heaviest shard · `env_var_names`.

Environment variables are recorded **by name only**, and any name matching
`KEY`, `TOKEN`, `SECRET`, `PASSWORD`, `CREDENTIAL` or `AUTH` is omitted
entirely — recording that a credential variable *exists* still advertises which
secrets a runner holds. That is a tested property, not a convention.

---

## 10. Current selective pull-request usage

The required CI workflow always starts. It installs the frozen environment and
runs repository-wide Ruff and Pyright before choosing the unit-test file set.
Only pull requests may narrow unit tests. Pushes to `master`, scheduled runs and
manual workflow dispatches continue to run the full unit suite.

For a pull request, the workflow computes one NUL-delimited
`git diff --name-status -z` against the base. Rename and copy records contribute
both their old and new paths. The selector writes the normalized list as JSON;
the harness consumes that same file instead of computing another diff.

Selection is conservative:

- tracked Markdown selects the always-on repository guards and document
  readers, plus any test with a literal contract-file edge;
- Python changes select direct tests, tests of explicit transitive callers,
  declared dynamic readers and the changed area's owning suite;
- shared hubs, CI/selector infrastructure, dependencies, missing/deleted paths,
  unmapped importable files, inventory/parse errors and malformed transport run
  the full suite with a reason;
- finding one cheap document or direct-test edge never suppresses a FULL trigger
  or the additive area owner from another changed path.

The selector reports its causal reasons. The harness preserves them in stderr
and its provenance manifest, then expands only to test files tracked by Git. An
empty expansion fails closed to the full suite.

After running `uv sync --group dev --frozen`, inspect a branch selection locally
without executing tests:

```bash
git diff --name-status -z origin/master...HEAD \
  | .venv/bin/python -m tools.ci_selection \
      --name-status-z \
      --write-paths-json /tmp/siderius-ci-changed.json

.venv/bin/python -m tools.ci plan \
  --root . \
  --changed-from /tmp/siderius-ci-changed.json
```

`plan` prints selection and shard metadata only. Use `bulk` in place of `plan`
only when the selected tests should actually execute. An absent or invalid
changed-path file deliberately produces a full plan.

## Ordinary documentation fast path

PR CI classifies the shared NUL-delimited Git diff before installing application
dependencies. `src/tools/ci_selection/docs_preflight.py` owns the ordinary-document
boundary: the root README and Markdown under `docs/getting-started`, `guides`,
`concepts`, `reference`, `releases` and `audit`. Only modifications to existing regular
files qualify. Empty, malformed, mixed, added, removed, renamed, copied, type-changed or
unrecognized paths retain the normal CI route. Classification failure or a missing
output also retains it.

The existing quality job/status stays present. A qualifying PR installs only the frozen
development dependency group and runs the existing Markdown link, user-contract,
split-evidence and documentation-directory checks with application conftests disabled.
It skips application installation, Ruff, Pyright, unit-test execution lanes and their
evidence upload. Documentation-check failures still fail the job.

This exception does not treat all Markdown as inert: orchestration payloads, skills and
prompts can be runtime inputs. Source Markdown (even README files), agent-reference
payloads, examples, gates, CI contracts and design documents retain normal checks.
Extending the ordinary document directories requires auditing consumers. Python
comments, docstrings and schema descriptions use normal CI; no semantic equivalence is
inferred from a small textual diff. Normal PRs keep the affected-test selector, and
master pushes, scheduled/manual runs and unknown impact keep their existing full-suite
policy. Production and paper experiment configuration are unchanged.
