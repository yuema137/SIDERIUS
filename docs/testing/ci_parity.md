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
> A runner has 4 vCPUs, so four shards saturate it and scheduling cannot beat
> the CPU budget; and the weight table is calibrated to this host, so shard 0
> carried the locally-dominant file and finished in **31.3 s** while its
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

## 9. The initial declared CI profile — 4 × 1

The workflow declares **4 bulk shards × 1 thread per shard**, capped at 4.

**This is a declaration, not a remote measurement.** Nothing has yet been timed
on a GitHub runner, and the number must not be quoted as the remote optimum
until a run measures it.

**Why declared rather than detected.** A source audit found no trustworthy way
to read the effective CPU budget: Python 3.12 has no `os.process_cpu_count()`,
`os.sched_getaffinity` does not observe cgroup quotas, `/sys/fs/cgroup/cpu.max`
is not readable here, and no repository helper exists. A detector would carry
false precision, so the profile is explicit.

**Why 4 and why capped at 4.** `ubuntu-latest` is documented as 4 vCPU, so
4 × 1 fills it without oversubscription. The cap is 4 because the measured floor
is a single 460.3 s file: no file-level shard can finish before its heaviest
file, so a fifth shard cannot make the run shorter.

**How it gets corrected.** Every run emits `run_manifest.json` recording the
declared profile *and* the observed facts — `cpu_count`, `affinity_count`,
`cgroup_cpu_max`, `runner_name`, `runner_os` — side by side. A mismatch is
therefore visible in the first remote artifact, and any adjustment afterwards is
made from fact rather than assumption. One adjustment, not a sweep: the remote
budget is for correctness, not benchmarking.

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
