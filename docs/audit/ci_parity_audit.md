# CI Parity Audit — local-vs-CI divergence taxonomy

**Lane**: CI Parity & Hermetic Test Harness (independent top-level workstream).
**Kickoff authority**: Rev 3, operator-approved 2026-08-24.
**Base**: `84d74280fdda6637afb6dad353f882501196ea98` (landed master; the PR-12d
squash, PR #274).
**Branch**: `infra/ci-parity-hermetic-harness`.
**Phase**: 0 — forensic audit. This document is the §3 artifact.

Every claim below carries a `file:line` verified at the base SHA. Findings are
labelled **CONFIRMED** (reproduced, or read directly off source), **LIKELY**
(source supports it, not yet reproduced), **NOT OBSERVED** (searched, nothing
found) or **OUT OF SCOPE**.

---

## 0. The current CI contract, as it actually is

One workflow file, `.github/workflows/ci.yml`, 116 lines, `runs-on:
ubuntu-latest`.

| step | command | line |
|---|---|---|
| Python | `uv python install 3.12` | `:58` |
| deps | `uv sync --group dev --frozen` | `:61` |
| lint | `uv run ruff check .` | `:64` |
| format | `uv run ruff format --check .` | `:67` |
| types | `uv run pyright` | `:78` |
| selection | `printf '%s\n' "$CHANGED" \| uv run python -m tools.ci_selection` | `:108` |
| tests | `uv run pytest ${{ steps.selection.outputs.pytest_args }}` | `:116` |

Recorded step timings (`ci.yml:30`): install ~47 s · ruff ~1 s · pyright strict
~2 m 17 s · pytest ~10 m 28 s. Banked per Rev 3 §26 — not re-measured.

### 0.1 The selector is already fail-closed. Do not rebuild it.

`tools/ci_selection/` (`__main__.py`, `manifest.py` ~8.8 KB, `resolver.py`
~13.6 KB) is the existing impact-selection authority (Rev 3 §5, P7).

Its fail-closed design is explicit in the workflow, and the comment at
`ci.yml:80-86` states the intent: *"an unmapped path, a declared hub, a change
to the selector itself, or ANY exception all resolve to the full suite."* The
shell block deliberately omits `set -e` (`ci.yml:89-91`) so that **every**
failure falls back to the full suite rather than skipping tests — *"a selector
that can break CI is a selector people switch off."*

Selection is also **pull-request-only**: `ci.yml:97-99` sends every other event
straight to `full()`.

**Consequence for this lane**: the harness composes this authority. It does not
shadow it, and any second changed-files→pytest mapping is a P7 violation.

### 0.2 The green baseline run

Run `32799116501` on `a1d5c101` (PR-12d's final head): lint / format / pyright
GREEN, pytest **12,941 passed · 48 skipped · 0 failed** in 21 m 24 s. The
selector resolved to the **full** `tests/unit/ -m "not real_run" -q` fallback,
so that figure is whole-suite, not impact-narrowed.

---

## 1. Test-suite shape (measured at base SHA)

`pytest tests/unit/ -m "not real_run" -q --collect-only` → **12,992 tests
across 688 files**, collected in 3.89 s.

| top-level directory | tests | share |
|---|---:|---:|
| `tests/unit/agent` | 4,654 | 36 % |
| `tests/unit/core` | 2,681 | 21 % |
| `tests/unit/execute_tools` | 2,231 | 17 % |
| `tests/unit/workflows` | 926 | 7 % |
| `tests/unit/sdsc_submission_scripts` | 529 | 4 % |
| `tests/unit/scripts` | 497 | 4 % |
| `tests/unit/guardrails` | 431 | 3 % |
| `tests/unit/ml_models` | 337 | 3 % |
| `tests/unit/examples` | 309 | 2 % |
| `tests/unit/tools` | 161 | 1 % |
| `tests/unit/nodes` | 115 | < 1 % |
| `tests/unit/agent_generated` | 56 | < 1 % |
| `tests/unit/dashboard` | 44 | < 1 % |
| `tests/unit/*.py` (root) | ~20 | < 1 % |

Largest single file: `tests/unit/guardrails/test_health_core_census.py`, 129
tests (1.0 % of the suite).

**Design conclusion (§8/§9), source-grounded**: directory-level sharding is
**not viable** — `tests/unit/agent` alone is 36 % of the suite and would be the
long pole Rev 3 §8 forbids. **File-level sharding is viable**: 688 units, with
the largest at 1 % of total tests, so no single file can dominate. Test count is
a proxy for runtime, not runtime itself; weighted sharding (§9) still needs
measured per-file timings, which Phase 8 will collect.

### 1.1 `pytest-xdist` is NOT installed — CONFIRMED

`import xdist` fails in `.venv`, and `pyproject.toml` declares no xdist
dependency. Rev 3 §8 already preferred process-level isolation where
global-state safety is uncertain; this removes the choice for now. Adopting
xdist would be a new dev dependency and a deliberate decision, not a default.

### 1.2 conftest topology — 5 files only

`tests/conftest.py` · `tests/unit/conftest.py` ·
`tests/unit/tools/claude_hooks/conftest.py` ·
`tests/unit/agent/tune_ml_hyperparam_agent/conftest.py` ·
`tests/unit/execute_tools/health_checks/conftest.py`.

`tests/unit/conftest.py` (110 lines) installs an **autouse** fixture
`forbid_real_heavy_subprocess` (`:64-65`) that monkeypatches `subprocess.run`
and `Popen` to refuse real training/inference/scoring launches, with
`@pytest.mark.allow_real_subprocess` as the documented opt-out (`:72`). This is
global interpreter state mutated per-test and is relevant to §18 (leakage) and
§10 (shard isolation).

---

## 2. Divergence classes

### A. Hidden machine-local files — **CONFIRMED, with two live reproductions**

`tests/conftest.py:32-38` imports `TIDMAD_DATA_DIR` from
`execute_tools.data_paths`; when the machine config is absent, that import emits
a `UserWarning` naming `tidmad_data_config.yaml` and falling back to
`tidmad_data_config.example.yaml`.

Reproduced twice at this base, in two independent clean checkouts:

1. The PR-12d parity probe (recovered evidence, kickoff §1a): 29 passed, 1
   warning, 12.07 s — the warning fires, tests still pass.
2. This lane's own probe worktree (§5 below): same warning, same text.

**Live production impact, already paid.** In CI run `32794899427` (`d5f1e11a`),
`tests/unit/execute_tools/test_step12_pr12d_d4a_scoring_restructure.py::TestBehaviouralParity`
failed because a golden stderr comparison saw 24 lines where the fixture had 22
— the two extra lines being exactly this warning. It passed on every developer
machine that carries the gitignored config. Fixed in `a1d5c101` by scrubbing the
warning as host noise; deliberately **not** baked into the golden, which would
have inverted the test into one that passes only where the config is absent.

Files referencing the machine-config names (search over `tests/`, `tools/`,
`execute_tools/`, `core/`, `scripts/`): 20+, the majority under
`tests/integration/` (not in CI). Unit-side references to triage further in
Phase 5: `tests/unit/workflows/test_step00_task_config_baselines.py`,
`tests/unit/sdsc_submission_scripts/test_chain_data_dir_portability.py`,
`tests/unit/sdsc_submission_scripts/test_gate_data_dir_resolution.py`,
`tests/unit/execute_tools/test_step12_pr12d_d4a_scoring_restructure.py`.

### A.1 Developer-path fallback in the root conftest — **CONFIRMED**

`tests/conftest.py:32-38`:

```python
try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR
    REAL_DATA_DIR = TIDMAD_DATA_DIR
except (FileNotFoundError, ImportError):
    REAL_DATA_DIR = "/home/klz/Data/TIDMAD/"
```

A bare `except` converting a missing machine config into an absolute path that
exists on exactly one machine. CLAUDE.md's portability section prohibits this by
name: tests "must never fall back silently to a developer-specific location".

Owned by this lane (`tests/` infrastructure, unowned by the in-flight lanes).
**Not yet fixed** — per the operator ruling, the intended meaning of
`REAL_DATA_DIR` must be established from source first, and a fix that merely
raises the skip count is a failed fix (§28).

### B. `.venv` / interpreter path contract — **CONFIRMED, and better-defined than expected**

Two tests hard-code `<repo>/.venv/bin/python`:

- `tests/unit/scripts/test_sdsc_argument_forwarding.py:262` — **a unit test that
  CI runs**, and it genuinely *executes* the interpreter via `subprocess.run`
  (`:261-275`).
- `tests/integration/runner/test_token_log_iter_rollup.py:149` — integration,
  not in CI.

Other `.venv` mentions are exclusion filters over `Path.parts`
(`test_step11_c7_spawn_hygiene.py:241`,
`test_step12_pr12a_c6_registration_layering.py:122`,
`test_model_io_resolution.py:113`) and are not path assumptions.

**Why CI is green today**: `uv sync` creates `.venv/` in the project root, so
`<repo>/.venv/bin/python` exists on the runner (`ci.yml:61`) and on any
developer box that has run `uv sync`. The contract is therefore *real and
satisfied* in both environments.

**Where it breaks**: a `git worktree` that has never had `uv sync` run in it.
That is exactly the PR-12d parity-worktree failure, and it is a property of the
*harness*, not of the product. Under Rev 3 §24.4 this is class **I —
INVALID_HARNESS_EVIDENCE**, not a product regression.

**Decision owed (Rev 3 §11)**: every execution root gets a valid `.venv`; or a
deterministic link to the immutable environment; or the tests move to
`sys.executable` if that is the real contract. Whichever is chosen, local
parity, shards and GitHub must obey the same rule.

### C. HOME / user-state dependence — **LIKELY, one site**

`tests/unit/agent/tune_ml_hyperparam_agent/test_time_calibration.py:31`
computes `os.path.join(os.path.expanduser("~"), cal._DEFAULT_SUBDIR)`. Whether
this reads real HOME content or only asserts a derived string is Phase 5 work.

Notably **NOT OBSERVED**: no unit test reads `~/.claude`, `~/.siderius` or
`~/.cache` directly. The continuity-hook tests operate on `tmp_path` repos via
`tests/unit/tools/claude_hooks/conftest.py`.

### C.1 `.claude` ancestor defeats a path assertion — **CONFIRMED, reproduced**

`tests/unit/tools/claude_hooks/test_context_state.py:85`:

```python
assert ".claude" not in path.parts
```

`cs.template_path()` (`tools/claude_hooks/context_state.py:340`) returns
`Path(__file__).resolve().parent / TEMPLATE_DIRNAME / TEMPLATE_BASENAME` — an
**absolute** path. `path.parts` therefore contains every filesystem ancestor,
not just the repository-relative ones.

Reproduced at this base in a checkout placed below a directory named `.claude`:

```
E  AssertionError: the canonical template resolved into .claude/, which is gitignored …
E  assert '.claude' not in ('/', 'tmp', …, 'scratchpad', '.claude', 'probe_wt',
   'tools', 'claude_hooks', 'templates', 'before_end_memory.template.md')
```

The template resolved **correctly** — beside the module, at
`…/probe_wt/tools/claude_hooks/templates/…` — and the test failed anyway. The
same file's `:90-91` already pin the true structural invariant
(`parent.name == TEMPLATE_DIRNAME`, `parent.parent.name == "claude_hooks"`).

The intended invariant, per the docstring at `context_state.py:337` and the
assertion's own message, concerns the **repository-local gitignored `.claude/`
directory**, not any ancestor anywhere on the filesystem. Class **H —
test-assumption defect** (Rev 3 §24.4). Owned by this lane.

### D. Interpreter / dependency environment — **NOT OBSERVED as a divergence**

Both sides pin Python 3.12 via `uv` with `--frozen` against the committed lock.
No evidence yet of a version-dependent test. Re-examine if a numeric finding
implicates a library version.

### E. Numeric / runtime environment — **CONFIRMED, one live instance**

`tests/unit/core/test_step07a_c2_transport.py::TestRungB07a2ValidationScopeAxis::test_real_trainer_emits_r2_and_r3_over_the_validation_family`
failed in run `32794899427` on `assert abs(r3 - train_ref) > 1e-4`, observing
`8.046627e-06`. It was **not reproducible locally or in a parity worktree**, and
passed on master and PR head alike — CI-runner numerics only.

The semantics were intact: r3 sat `1.5e-07` from `val_ref` and `8.0e-06` from
`train_ref`, i.e. R3 *was* computed over the validation family as claimed. The
assertion encoded a claim about how different two **datasets** happen to be,
which no production code controls. Retargeted in `a1d5c101` to
`abs(r3 - val_ref) < abs(r3 - train_ref)` — better aimed, not weaker: were R3
computed over the training family, it fails.

This is the model case for Rev 3 §16: the fix protected the semantic invariant
instead of widening a tolerance.

This test is also one of the two timing-sensitive real-training "unit" tests
carried as debt since Step 11 (CLAUDE.md).

### F. Process concurrency — **LIKELY, not yet quantified**

107 files under `tests/unit/` match timing-related patterns; 10+ call
`time.sleep(` directly, including `test_probe_hard_timeout.py`,
`test_gpu_measurement_runner.py`, `test_observed_subprocess_seam.py`,
`test_formal_stability_controller.py`, `test_isolated_preflight.py`. Phase 3
must classify these into the sensitive lane by reading them, not by pattern
match (`feedback_no_heuristic_test_classification`).

### G. Repository state / dirty-tree — **CONFIRMED**

`scripts/pr3_l2_calibration/preflight.py:297` runs
`["git", "diff", "--name-only"]` with `cwd=REPO`. Its unit test
`tests/unit/scripts/test_pr3_l2p_preflight.py` therefore reads the **live
working tree** and fails when tracked files outside its allowlist are modified
(CLAUDE.md documents this as intended).

Other tests touching git state: `tests/unit/core/test_manifest_io.py`,
`tests/unit/tools/claude_hooks/conftest.py`,
`tests/unit/workflows/test_step10_p1_c4_extension_proof.py`,
`tests/unit/execute_tools/health_checks/test_step10_p4_c3_fourth_task_evidence.py`.

**Scheduling requirement (§19)**: these need an exclusive, un-mutated checkout.
A dirty-tree guard firing because a sibling shard wrote into the same tree is
class **I**, not a product failure.

### H. Module / global state — **LIKELY**

The autouse `forbid_real_heavy_subprocess` fixture (§1.2) mutates interpreter
globals for every unit test. Registry-lifetime defects are a live failure class
in this repository: F-12bc-8 (CLAUDE.md) was an import-registration lifetime
defect where a built-in imported under a blanked registry never registered
again. Phase 3 owes deterministic leakage checks.

### I. Path semantics — **partially CONFIRMED** (see B and C.1)

### J. Warning / stderr behaviour — **CONFIRMED** (see A)

The green run reports **650 warnings**. Golden-text comparisons over child
stderr are demonstrably fragile to an unrelated import-time warning. Rev 3 §17
governs: classify before hardening, and never scrub a warning that indicates a
real user-facing problem — the `tidmad_data_config.yaml` warning must keep
firing.

---

## 3. Root-cause reference case — PR-12d, N = 4 / M = 3

Retained as the lane's real fixture material (operator instruction). Four
consecutive red CI runs on four different SHAs (`36447b56`, `9e55b672`,
`3038d041`, `d5f1e11a`) preceded one attributed fix.

The final red, run `32794899427` @ `d5f1e11a` — **4 failed / 12,937 passed / 48
skipped**:

| # | node | root cause | class |
|---|---|---|---|
| 1–2 | `test_step12_pr12bc_b6_scope_transport::TestTheTrainingArgv` (×2) | `validation_rows_argv` hoisted to the training spawn made the **parent** materialize real TIDMAD `.h5` files. Base control on the same clean worktree: master 3 passed / PR head 2 FAILED | A — PR regression |
| 3 | `test_step12_pr12d_d4a_scoring_restructure::TestBehaviouralParity` | golden stderr + machine-config warning (§2.A) | B — PR-exposed portability |
| 4 | `test_step07a_c2_transport::…validation_family` | dataset-difference assertion vs CI numerics (§2.E) | F — numerical |

**N = 4 observed failures, M = 3 distinct root causes.** All fixed in one
commit (`a1d5c101`). Attribution came from a CI-parity worktree carrying
**tracked files only**, with `origin/master` as base control under identical
conditions — the method Rev 3 §24 makes routine.

---

## 4. Findings register

| id | class | location | status | owner |
|---|---|---|---|---|
| CP-1 | A — machine config | `tests/conftest.py:32-38` developer-path fallback | **CLOSED** `fa9040bc` — dead code; skip census unchanged (399/0 both sides) | this lane |
| CP-2 | H — test assumption | `tests/unit/tools/claude_hooks/test_context_state.py:85` `.claude` ancestor | **CLOSED** `dd443466` — RED→GREEN + both M-C8 shapes still RED | this lane |
| CP-3 | I — harness/`.venv` | `tests/unit/scripts/test_sdsc_argument_forwarding.py:262` executes `<repo>/.venv/bin/python` | **CLOSED by contract** — per-root `uv sync --group dev --frozen`, 1 s / 21 MB measured; enforced by preflight `f42f579e`. No product change | this lane |
| CP-4 | G — dirty tree | `tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants` | **CONFIRMED, refined** — see below | this lane (scheduling only) |
| CP-5 | C — HOME | `test_time_calibration.py:29-32` | **CLOSED** — HOME-robust, not sensitive; weak-assertion finding recorded, deferred | deferred |
| CP-6 | F — concurrency | 4 timing files + 1 deadline loop | **RESOLVED, provisional** — sensitive lane = 5 of 688 | this lane |
| CP-7 | H — global state | autouse subprocess guard, `tests/unit/conftest.py:64` | **CLOSED** — monkeypatch-scoped, no leak; constrains shards to process-level | this lane |
| CP-8 | parity signal | CI 48 skipped vs local 5 | **SOLVED** — N=43 → M=4; machine-local DATA presence, not config. See §CP-8 below | this lane |
| CP-10 | parity signal | 12,992 collected locally vs 12,989 outcomes on CI | **OPEN, bounded** — every local hypothesis eliminated; needs CI-side node data | this lane |
| CP-12 | C+D order/global-state | composition authority vs `_CACHED_GATES` | **RESOLVED EXTERNALLY** by `6f8f5da4`; consumed and verified | C12-P family |
| CP-11 | portability | hardcoded `/home/klz/Data/...` paths in 3 unit tests | CONFIRMED; recorded, deferred | deferred |
| CP-9 | tooling parity | local pyright unusable: node **v10.19.0** vs pyright 1.1.409 pinned in `uv.lock` | **CLOSED** — managed nodeenv (`PYRIGHT_PYTHON_GLOBAL_NODE=false` + pinned `ENV_DIR`) yields the locked 1.1.409 on node v26.7.0, HOME-independent; `pyright[nodejs]` deferred by ruling | this lane |

### CP-4, corrected by reading

Phase 0's grep listed four git-state files. **Three were false positives**: in
`test_manifest_io.py:65`, `test_step10_p1_c4_extension_proof.py:17` and
`test_step10_p4_c3_fourth_task_evidence.py:251` the word `git` appears only in
comments and docstrings — two of which explain why the test deliberately uses
an AST census *instead of* `git diff`.

Exactly one test genuinely reads the live working tree:
`test_preflight_all_invariants` calls `preflight_main()` with no monkeypatching
(`tests/unit/scripts/test_pr3_l2p_preflight.py:11-12`), and that function runs
`git diff --name-only` with `cwd=REPO`
(`scripts/pr3_l2_calibration/preflight.py:297`).

**Sensitive-lane membership**: this test requires an exclusive, un-mutated
checkout. A sibling shard writing into the same tree makes it fail *invalidly*
— class I, not a product regression.

This is why `feedback_no_heuristic_test_classification` exists, and it applies
to the CP-6 timing candidates too: they must be read individually, not
pattern-matched into the sensitive lane.

### CP-6, resolved by reading: the sensitive lane is SMALL

Phase 0 reported "107 files match timing-related patterns" and 10+ calling
`time.sleep(`. Read individually, almost none are load-sensitive, because the
presence of a sleep says nothing — **the direction of the assertion does**.

| shape | load behaviour | verdict |
|---|---|---|
| "the event must occur within T" (upper bound on measured wall time) | saturation can exceed T | **load-fragile → sensitive lane** |
| "the event must NOT occur within T" | saturation makes it *more* true | load-robust → bulk |
| sleep used only to sequence or to let a thread start | outcome independent of load | bulk |

`tests/unit/core/test_gpu_observer.py:233` is the instructive counter-example:
it sleeps 0.05 s and then asserts a counter did **not** advance
(`"observer kept sampling after stop()"`). CPU contention only makes that
assertion easier to satisfy. A `time.sleep` grep would have quarantined it for
no reason.

**Confirmed load-fragile — upper-bound assertions on measured wall time:**

| test | assertion |
|---|---|
| `tests/unit/core/test_probe_hard_timeout.py:122` | `assert elapsed < 10.0, "the hard cap must actually bound the wall time"` |
| `tests/unit/core/test_probe_hard_timeout.py:144` | `assert elapsed < cap + grace + 5.0` |
| `tests/unit/scripts/test_inspection_cost_study.py:152` | `assert elapsed < 3.5, "the native alarm did not preempt — a relaxation snuck in"` |
| `tests/unit/agent/evaluate_vram_skill/test_isolated_preflight.py:120` | `assert elapsed < 45.0, "the memory bound must fire well before the deadline"` |

**One further candidate, a deadline-poll loop rather than an assertion on
elapsed** — the only such shape in the suite:
`tests/unit/core/test_formal_stability_controller.py:412-416` polls for 5.0 s
and then asserts `"the watcher thread never polled"`. Under saturation that
message would be a false accusation, so it belongs in the sensitive lane on the
same reasoning.

Each of these asserts *"the preemption mechanism fired in time"*. When CPU
saturation defeats them the failure is **class I — INVALID_HARNESS_EVIDENCE**,
never a product regression. They must not be "fixed" by inflating the bound:
the bound is the thing under test.

**Census consequence**: the sensitive lane is **4 timing files + 1 git-state
file = 5 of 688**. The bulk lane keeps ~683 files, so isolation costs almost no
parallelism. This is provisional until CP-8 closes — §9 forbids freezing the
bulk/sensitive contract while an unexplained parity delta stands, because the
skip delta may expose further environment-sensitive classes.

### CP-7, resolved: not a leakage hazard, but it constrains the shard model

`tests/unit/conftest.py:64` installs an autouse `forbid_real_heavy_subprocess`
fixture that replaces `subprocess.run` and `subprocess.Popen`.

**Not a cross-test leak.** Both replacements go through `monkeypatch.setattr`,
which pytest reverts at teardown, and the fixture is per-test. Nothing survives
into the next test. It is also carefully built — `_GuardedPopen` is a *subclass*
rather than a wrapper function, with a comment explaining that replacing the
class with a function changes its type and breaks tests that legitimately
subclass `Popen`. No defect here.

**But it does constrain sharding.** The patch is process-wide *for the duration
of a test*. Tests executing concurrently **inside one interpreter** — pytest-xdist
in threaded mode, or any in-process parallelism — would see each other's guard
state. With **process-level shards** (one pytest process per shard, tests
sequential within it) the fixture is entirely safe.

This is an independent argument for the process-level shard model already
chosen for other reasons (§1.1: xdist is not even installed).

### CP-5, resolved: HOME-robust, but a weak assertion

`tests/unit/agent/tune_ml_hyperparam_agent/test_time_calibration.py:29-32`:

```python
expected = os.path.join(os.path.expanduser("~"), cal._DEFAULT_SUBDIR)
assert cal.calibration_dir() == expected
```

Production is `agent/skills/evaluate_time_skill/calibration.py:62`:
`os.path.join(os.path.expanduser("~"), _DEFAULT_SUBDIR)`.

**Not HOME-fragile.** Under an isolated HOME both sides move together, so the
test passes either way. It does **not** belong in the sensitive lane, and it is
not a parity defect.

**It is, however, a weak assertion** of the shape CLAUDE.md bans: it rebuilds
the production expression from production's own constant (`cal._DEFAULT_SUBDIR`)
and compares the result to production's output, so it cannot notice the subdir
changing. Hardcoding `".siderius"` would make it catch that.

Recorded, **not fixed**: it is a test-quality finding rather than a CI-parity
one, and §35 says this lane records findings outside its clear ownership rather
than opportunistically repairing them. Owner: whoever next touches
`evaluate_time_skill`.

### CP-9, and why the obvious fix is wrong

`pyproject.toml:51` declares `pyright>=1.1.409` (a floor); `uv.lock` pins
**1.1.409**, and CI runs `uv run pyright` (`ci.yml:78`) — so the lock is the
authority. This machine has **node v10.19.0** (2019), too old to run pyright's
bundled Node program, so `uv run pyright --version` emits only an update warning
and produces no version.

The available-version notice (1.1.409 → 1.1.411) is a red herring. Upgrading
would move the repository's typecheck authority away from the lock to repair one
developer box. The remedy is a newer Node **in the parity environment**.

Until then, local pyright is reported as **NOT VALID EVIDENCE** — never
GREEN/RED. `ruff check` and `ruff format` evidence is banked independently and
is unaffected. CLAUDE.md anticipates exactly this case.

**Not owned by this lane**: no numeric or warning assertion outside the files
above has yet been shown defective. Per Rev 3 §16/§17 and §35, further findings
are recorded and assigned, not opportunistically fixed.

---

## 5. Reproduction assets

- **Probe worktree**: created at a path containing a `.claude` ancestor to
  reproduce CP-2, detached at `84d74280`. Volatile scratch — recreate on demand
  with `git worktree add --detach <path-with-.claude-ancestor> 84d74280`; do not
  depend on it persisting.
- **Collected inventory**: `pytest --collect-only` output, 12,992 node ids, used
  for the §1 distribution. Regenerate in seconds; not committed.

Both are evidence, not architecture (Rev 3 §1a).

---

## 6. Open questions for later phases

1. **§11 `.venv` contract** — which of the three options? Affects every shard.
2. **`REAL_DATA_DIR` semantics** — optional override, tracked default, or
   genuinely required input? Gates CP-1's fix shape.
3. **Sensitive-lane membership** — needs per-test reading of the ~10 timing
   tests and the 4 git-state tests, not pattern matching.
4. **Weighted sharding** — needs measured per-file runtimes (Phase 8).
5. **Structured CI failure output** — the workflow currently emits `-q` pytest
   text and no JUnit XML or JSON, so §24.7 likely needs the smallest possible
   structured artifact.

---

## CP-8 — SOLVED. The skip delta is machine-local DATA, not config

**N = 43 observed skip differences → M = 4 root causes.**

### Method

A single-variable experiment, then a namespace reproduction. Both ran in the
same pristine worktree at `84d74280`, with the same `uv sync --frozen` venv and
the same corpus, so nothing but the named variable moved.

| run | variable | result |
|---|---|---|
| A | machine configs **absent** (CI-equivalent) | 12,987 passed · **5 skipped** |
| B | machine configs **present** | 12,987 passed · **5 skipped** |

Node sets identical (12,992 each), **zero** outcome differences between A and B.
So the leading hypothesis — that machine config drives the delta — is
**refuted**, and the CI-equivalent bootstrap does *not* by itself reproduce CI's
48.

The five local skips are corpus/env absence: two for a missing
`agent_generated/models` plugin corpus, one for an unset
`SIDERIUS_V20_ATTEMPT3_DIR`, one for an empty parameter set, one for absent
on-disk plugins. All five also hold on CI.

The remaining 43 had to come from something present on this lab host and absent
on a GitHub runner. Reproduced by hiding exactly that, in a user mount namespace
(`unshare -r -m`, bind-mounting empty directories over `/home/klz/Data` and
`/home/tidmad`) with the three override env vars unset:

```
baseline, data present :  142 passed,  0 skipped
data hidden            :   99 passed, 43 skipped
```

**5 + 43 = 48 — exactly CI's count.**

### The four root causes

| RC | cause | skips | files |
|---|---|---:|---|
| **RC-A** | legacy TIDMAD reference repo `/home/tidmad/TIDMAD` absent | **18** | `test_c12b_legacy_fidelity.py` |
| **RC-B** | real Pets images absent | **17** | `test_pets_data_path.py`, `test_pets_execution_manifest.py`, `test_step12_pr12d_d3_child_transport.py`, `test_step12_pr12d_f12d27_training_scope_transport.py`, `test_step12_pr12d_f12d28_inference_scope_binding.py` |
| **RC-C** | real DAVIS frames absent | **5** | `test_davis_data_path.py`, `test_davis_execution_manifest.py`, `test_step12_pr12d_d3_child_transport.py` |
| **RC-D** | preserved DAVIS Gate-2 `.npz` absent | **3** | `test_davis_health_family.py` |

### Disposition — intentional, and now declared

Per kickoff §6, a skip difference is not automatically a defect. All four are
**intentional**: each test declares an external-resource requirement and skips
with an informative reason naming the path and the override variable. That is
precisely the contract CLAUDE.md requires of tests needing external datasets.

The defect was never the skipping — it was that the difference was
**undeclared**, so two environments both called themselves "parity" while 43
tests silently differed. It is now a declared dimension of the contract
(`docs/testing/ci_parity.md` §4.1) and a recorded manifest field.

**Consequence for the bulk/sensitive split: none.** These skips are
deterministic functions of resource presence, not of load or ordering, so no new
sensitive class appears and the CP-6 classification can be frozen.

### A correction made during the experiment

An earlier attempt set the override variables to non-existent paths and produced
**4 errors**. Those were not defects: the tests correctly refuse a *set but
invalid* path (`"SIDERIUS_PETS_DATA_DIR=… is set but is not a directory"`)
rather than skipping silently. Misconfiguration and absence are different
states, and CI has these variables **unset**. The namespace reproduction models
absence, which is why it lands exactly on 43.

---

## CP-10 — the 3-node gap, separated and bounded

CI reports **12,989** terminal outcomes (12,941 passed + 48 skipped, with zero
deselected/xfailed/xpassed/errors — verified directly in the run log). Local
collection is **12,992**.

**This is not the skip delta.** It survives independently of it, and every local
hypothesis has been eliminated by measurement:

| hypothesis | test | result |
|---|---|---|
| the SHAs differ | collected at `a1d5c101` and `84d74280` | **12,992 both** — refuted |
| `tests/unit/` differs between the SHAs | `git diff a1d5c101 84d74280 -- tests/unit/` | empty — refuted |
| machine configs change collection | runs A vs B | identical node sets — refuted |
| machine data changes collection | collect inside the hiding namespace | **12,992** — refuted |
| CI had deselects/xfails/errors | full CI log scan | zero — refuted |

What remains requires **CI-side per-node data**, which the current workflow
cannot supply: it runs pytest with `-q` and emits no JUnit XML, so skipped and
collected node identities never leave the runner.

**Closure mechanism, at zero extra remote cost.** Kickoff §24.7 already calls for
the smallest structured artifact needed for attribution. Adding `--junitxml` to
the workflow is that artifact, and CP-10 will be answered by the **first**
workflow-integration run that carries it — no dedicated run, no additional
budget. Until then CP-10 stays OPEN and is not classified.

---

## CP-11 — hardcoded developer paths in three unit tests

`tests/unit/execute_tools/test_step12_pr12d_d3_child_transport.py:77-78`,
`test_step12_pr12d_f12d27_training_scope_transport.py:42` and
`test_step12_pr12d_f12d28_inference_scope_binding.py:42` hardcode
`/home/klz/Data/OXFORD_IIIT_PET/images` and `/home/klz/Data/DAVIS_2017` with no
environment override, unlike their siblings which read `SIDERIUS_PETS_DATA_DIR`
/ `SIDERIUS_DAVIS_DATA_DIR`.

They skip rather than falsely pass, so this is mild — but on any machine holding
the data elsewhere they skip **silently and permanently**, and the coverage loss
is invisible. CLAUDE.md requires machine-specific data paths to come from
configuration or environment.

Recorded, **not fixed**: these files belong to the PR-12d/C12-P surface, and §35
directs this lane to record across ownership boundaries rather than repair.

---

## CP-12 — a test that cannot run in isolation (pre-existing, found by sharding)

`tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py::TestW4ReadsTheInputNotTheAmbientEnvironment::test_a_composed_run_loads_no_legacy_reference_science`

```
HealthPluginRunScopeError: A different Health plugin set was already loaded in
this process. Health check registration is process-global, so continuing would
let this run evaluate checks registered by the previous one.
  already loaded: []
  now requested:  [{'configured_ref': '../plugins/_pets_health_views.py', ...}]
```

### Measured behaviour

| context | result |
|---|---|
| the single test, alone | **FAILS** |
| its whole file, alone | **FAILS** |
| the file + `test_step10_p56_c5_w6_composed_health.py` | 31 passed |
| the file + `test_step12_pr12a_c1_composed_invariants.py` | 31 passed |
| whole `tests/unit/workflows/` | 926 passed |
| full serial suite (twice) | passes |
| bulk shard 02 (different neighbour mix) | **FAILS** |

Identical on the canonical checkout (machine configs present) and the probe
worktree (absent), so it is not config-dependent.

### What it actually is

The test **requires a predecessor**: it passes if and only if some earlier test
in the same process has already bound a Health plugin set. It cannot establish
that itself, so in a fresh process it fails. Several files satisfy the
requirement, which is why any reasonably large slice of
`tests/unit/workflows/` — and the full suite — hides it.

**Classification: C (pre-existing / base defect) + D (order coupling).** It is
**not** a PR regression, **not** caused by this harness, and **not**
`INVALID_HARNESS_EVIDENCE`: the harness ran a legitimate subset in a clean
process and reported truthfully. The serial suite conceals it by accident of
ordering.

It also means a completely ordinary developer action — running just that
file — shows a red test on landed master today.

### An earlier diagnosis of mine, corrected

I first called this "sharding separated it from `test_plugin_binding.py`". That
was wrong: it fails with **no neighbours at all**. The dependency is on *any*
prior Health binding, not on one specific file. The correction came from
running the test alone, which is the check that should have come first.

### Disposition — reported, NOT worked around

The obvious harness "fix" is a co-location rule pinning this file to its
enablers. **Deliberately not done.** That would hide a real defect behind
scheduling, and the operator ruling is explicit: the harness must *expose and
classify* such a failure, not repair every historical test.

Owner: the PR-12a surface (`test_step12_pr12a_c2_composition_projection.py`) and
the production binding lifetime in `execute_tools/health_checks/_plugin_binding.py`.
Both are outside this lane's write set (§35), so this is recorded and assigned,
not edited.

Until it is fixed, the bulk lane carries exactly one known RED with a recorded
attribution. No quarantine mechanism is being built for it: a quarantine that
can hide a regression is worse than a red line with a name.

---

## CP-12 handoff packet

Prepared per the §6 template. Source-grounded; no fix applied by this lane.

### A. What predecessor state makes it pass

Not a specific file. The test passes whenever **some earlier test in the same
process has already imported the pets Health plugin module**. Two unrelated
files independently satisfy it:

```
file + test_step10_p56_c5_w6_composed_health.py   -> 31 passed
file + test_step12_pr12a_c1_composed_invariants.py -> 31 passed
whole tests/unit/workflows/                        -> 926 passed
the file alone / the test alone                    -> FAILS
```

### B. Which global value is missing

> **CORRECTED 2026-08-24 by tracing, after this packet was first written.** The
> section below said the discriminator was `sys.modules` import state. **It is
> not.** Tracing every `load_task_health_plugins` call shows the real
> mechanism, recorded in "B-corrected" following this section. The original
> reasoning is left visible because it was plausible, cited the right prior
> incident (F-12bc-8), and was still wrong — the trace is what settled it.

`_RUN_SCOPE` in `execute_tools/health_checks/_plugin_binding.py`. `bind`
(`:381-399`) refuses when a **different** set is already loaded, comparing
`canonical_identity()` tuples, and returns idempotently when they match.

The observed conflict is *inside a single test*:

```
already loaded: []                    <- an EMPTY set bound first
now requested:  [pets health views]
```

`test_a_composed_run_loads_no_legacy_reference_science` (`:146-158`) calls
`compose_run_task_bindings` (`:148`) and then `bind_run_task_composition`
(`:149`). In a fresh process the first resolves to an **empty** plugin set; once
the pets plugin module has been imported by any predecessor, the same call
resolves to the pets set and the second bind is idempotent.

So the discriminator is **module import state**, not test ordering as such. This
is the `F-12bc-8` family CLAUDE.md already records: *a built-in imported under a
blanked registry never registers again*.

### C. Who is contractually responsible

**Undetermined, deliberately.** The file already does everything a test is
normally asked to do: an autouse `_isolated_run_scope` fixture (`:49-61`) saves
and restores both registries and calls `reset_run_scope()` before and after
every test. The defect is therefore *not* a missing fixture.

The open question is whether resolution should depend on `sys.modules` at all —
i.e. whether `_resolve` returning an empty set for an unimported plugin is
correct behaviour that the test must accommodate, or a lifetime defect in the
binding authority. That is a call for the owning authority, not this lane.

### D. Is the state reset between tests

Yes for `_RUN_SCOPE` (`reset_run_scope()`, autouse, both directions) and yes for
the two registries (saved/restored by the same fixture). **No** for
`sys.modules` — and nothing in the repository claims to reset that. Note
`reset_run_scope`'s own docstring: it *deliberately* does not unregister
anything, because "having two mechanisms undo each other's work is how a test
starts passing for the wrong reason."

### E. Minimum valid repair surface

```
execute_tools/health_checks/_plugin_binding.py                      (authority)
tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py (consumer)
```

### Collision classification: **NO OVERLAP**

Exact-path check across every active worktree — 12e A/B/C/D1/D2/D3/R, C12-P
w1/w2/w3, C12-P-P, arXiv — found neither path modified, committed or
uncommitted. Last touched by already-merged PRs: `13e28796` (#236, Step 08b) for
the authority and `15554174` (#248, PR-12a) for the test.

An earlier pass of this check reported seven overlaps. All seven were **false
positives**: the pattern `_plugin_binding` also matches
`tests/unit/ml_models/test_step12_pr12d_dp_plugin_binding.py`, an unrelated
file. Exact paths, not substrings — the same lesson as the CP-4 `git` grep.

### Proposed disposition

A small corrective branch off master touching only the two files above, owned by
whoever owns the Health binding lifetime. It is **disjoint** from every active
lane, so it can proceed in parallel without coordination.

**Does not block Phase 5.** It **does** block the sharded harness becoming
authoritative CI, because until it is fixed the bulk lane carries a known RED.

---

## CP-9 — SOLVED without moving the pin

The pyright wheel resolves its Node through
`PYRIGHT_PYTHON_GLOBAL_NODE` (`.venv/.../pyright/node.py:25`), which **defaults
to true** — i.e. use the system Node, which here is v10.19.0 (2019) and too old
to run it. When false, the wheel provisions its own Node via nodeenv
(`node.py:44-54`).

```
$ PYRIGHT_PYTHON_GLOBAL_NODE=false .venv/bin/python -m pyright --version
pyright 1.1.409
```

That is the **exact version pinned by `uv.lock`**, the one CI runs via
`uv run pyright`. The repository's typecheck authority is unchanged, no host
package was installed, and the "1.1.411 available" notice remains correctly
ignored.

**Contract addition**: a parity run that intends to claim typecheck parity sets
`PYRIGHT_PYTHON_GLOBAL_NODE=false` and records the resolved pyright version in
the manifest. Without it, local pyright remains NOT VALID EVIDENCE — the
distinction is now mechanical rather than a note.

---

## CP-12 — B-corrected, and why the repair is NOT small

Tracing every `load_task_health_plugins` call during the failing test shows
**two** binds inside one tuner run, with **different configs**:

```
BIND #1  declared plugins=0  config_dir=<repo>/configs/task_health
         ml_hyperparameter_tune_agent.py:814 run
         -> config.py:400 load_health_gates_config
         -> config.py:567 load_composed_health_config
         -> config.py:528 _load_task_binding

BIND #2  declared plugins=1  config_dir=<repo>/examples/oxford_iiit_pet/declared
         ml_hyperparameter_tune_agent.py:495 _resolve_run_gate_ids
         -> candidate_eligibility.py:140 resolve_run_scientific_gate_ids
         -> config.py:567 load_composed_health_config
         -> config.py:528 _load_task_binding
```

The tuner binds the **framework default** task-health config first and the
**composed task's** config second. They are different plugin sets, so the
run-scope guard refuses — correctly. The guard is not the defect; it is the
detector.

### What actually hides it

`_CACHED_GATES` (`execute_tools/health_checks/config.py:355`) is a module-global
returned whenever `path is None` (`:398-399`). With a warm cache **BIND #1 never
executes** — it short-circuits before binding — so only the composed set is ever
bound and no conflict arises.

The failing file's autouse fixture resets `_RUN_SCOPE` and both registries but
**does not** clear `_CACHED_GATES`, and no test under `tests/unit/workflows/`
clears it. So:

| process state | BIND #1 | outcome |
|---|---|---|
| fresh (cold cache) | executes, binds 0 plugins | **conflict → RED** |
| warm cache from any predecessor | short-circuits | GREEN |

This also means the obvious test-side "fix" — clearing the cache in the
fixture — would make the failure **deterministic rather than fixing it**, which
is a strong signal the inconsistency is in the production path.

### Contract classification: **B**, with a material caveat

Under the §7 taxonomy this is **B — the production composition authority should
resolve the run's declared task independently**, not A (the caller is already
doing everything correctly) and not C (nothing is leaking across a lifecycle
boundary; the cache is legitimately scoped, it merely masks the disagreement).

But the repair surface is **not** the two files this packet originally named:

```
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:814   production tuner
execute_tools/health_checks/config.py:355-410, 528, 567                  caching + composed binding
execute_tools/health_checks/_plugin_binding.py                           the guard (likely unchanged)
tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py      the consumer
```

`ml_hyperparameter_tune_agent.py` is the giant orchestrator CLAUDE.md's
responsibility-decomposition rule specifically protects, and the semantic
question — *should a composed run's first health-config load resolve the
composed task rather than the framework default?* — is exactly the property
C-P56-1 asserts and that this very test exists to defend.

### STOP, per the §7 bounded stop rule

Two of the four stop conditions are met:

* **the repair expands materially beyond the expected small surface** — it
  reaches the production tuner and the composed-config authority, not two files;
* **public API semantics would change** — what a composed run resolves on its
  first health-config load is a composition-authority contract, not a test
  detail.

CLAUDE.md's standing rule points the same way: production semantics must not be
changed for CI convenience, and this would be a scientific-path change made from
a test-infrastructure lane.

**No corrective branch has been opened.** The diagnosis above is complete enough
for the owning authority to act, and the harness continues to report CP-12
honestly in the meantime.

---

# CP-12 — HANDOFF PACKET FOR THE C12-P PARENT

**From**: CI Parity & Hermetic Test Harness lane (`infra/ci-parity-hermetic-harness`).
**To**: the C12-P family / Health-composition authority.
**Status**: Test Infra is **NOT proposing a repair**. This packet is exposure,
reproduction, classification and evidence. The contract decision is the owning
authority's.

**Filing note**: this packet is deliberately **not** appended to
`pr_12e_out_of_tree_graduation.md` (§U.10–U.12), where C12-P's scope is defined.
Twelve active worktrees — 12e A/B/C/D1/D2/D3/R, C12-I candidate/demo, C12-P
12dref, 12e planning and speculative-impl — carry committed changes to that
file, so writing into it from this lane would create a merge conflict in every
one of them. It lives here, in Test-Infra-owned documentation, for the operator
to route.

## 1. Exact failing node

```
tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py::TestW4ReadsTheInputNotTheAmbientEnvironment::test_a_composed_run_loads_no_legacy_reference_science
```

Base: `84d74280` (landed master). Present on the canonical checkout **and** on a
tracked-only worktree, with and without machine configs.

## 2. Cold-process command — RED

```bash
.venv/bin/python -m pytest \
  "tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py::TestW4ReadsTheInputNotTheAmbientEnvironment::test_a_composed_run_loads_no_legacy_reference_science" \
  -q -p no:cacheprovider
# 1 failed
```

Its whole file alone also fails: `1 failed, 11 passed`.

## 3. Warm-process masking commands — GREEN

```bash
# any predecessor that warms the health-config cache
.venv/bin/python -m pytest \
  tests/unit/workflows/test_step10_p56_c5_w6_composed_health.py \
  tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py -q   # 31 passed

.venv/bin/python -m pytest \
  tests/unit/workflows/test_step12_pr12a_c1_composed_invariants.py \
  tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py -q   # 31 passed

.venv/bin/python -m pytest tests/unit/workflows/ -q                        # 926 passed
```

## 4. BIND #1 — config and resolved set

```
config_dir : <repo>/configs/task_health
plugins    : 0
call path  : nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:814  run
             -> execute_tools/health_checks/config.py:400  load_health_gates_config
             -> execute_tools/health_checks/config.py:567  load_composed_health_config
             -> execute_tools/health_checks/config.py:528  _load_task_binding
```

## 5. BIND #2 — config and resolved set

```
config_dir : <repo>/examples/oxford_iiit_pet/declared
plugins    : 1   (../plugins/_pets_health_views.py,
                  sha256 9203c0384f1a43ce2c00bec60e32c88e668bdec7630b6c88766238faba70d7d4)
call path  : nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:495  _resolve_run_gate_ids
             -> execute_tools/health_checks/candidate_eligibility.py:140  resolve_run_scientific_gate_ids
             -> execute_tools/health_checks/config.py:567  load_composed_health_config
             -> execute_tools/health_checks/config.py:528  _load_task_binding
```

Both traced by wrapping `load_task_health_plugins`, not inferred.

## 6. `_CACHED_GATES` masking behaviour

`execute_tools/health_checks/config.py:355` declares the module-global
`_CACHED_GATES`; `:397-402` returns it whenever `path is None`.

| process state | BIND #1 | result |
|---|---|---|
| cold cache | executes, binds **0** plugins | BIND #2 conflicts → **RED** |
| warm cache (any predecessor) | **short-circuits, never binds** | only the composed set exists → GREEN |

The failing file's autouse `_isolated_run_scope` fixture (`:49-61`) resets
`_RUN_SCOPE` and both registries but does **not** clear `_CACHED_GATES`; no test
under `tests/unit/workflows/` clears it.

**Consequence worth weighing**: clearing the cache in the fixture would make the
failure *deterministic*, not fix it.

## 7. Implicated files and lines

```
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:814   BIND #1 origin
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:495   BIND #2 origin
execute_tools/health_checks/config.py:355, 397-402                       the masking cache
execute_tools/health_checks/config.py:528, 567                           composed task binding
execute_tools/health_checks/_plugin_binding.py:381-399                   the guard (detector)
tests/unit/workflows/test_step12_pr12a_c2_composition_projection.py:146  the consumer
```

## 8. Why the run-scope guard is the detector, not the defect

`bind` compares `canonical_identity()` tuples and returns idempotently when they
match (`:385-390`); it refuses only a genuinely *different* set. Its own message
states the reason: registration is process-global, so continuing "would let this
run evaluate checks registered by the previous one." Two different plugin sets
were requested in one run; refusing is correct. Removing or relaxing the guard
would let a composed run silently evaluate the wrong gates.

## 9. Candidate interpretations of the composition contract

Offered as framing, not as a recommendation:

1. **The first load should already be task-aware** — in a composed run,
   `ml_hyperparameter_tune_agent.py:814`'s `load_health_gates_config` should
   resolve the run's declared task rather than the framework default, making
   both binds the same set.
2. **The framework-default load is legitimate** and the composed load should be
   additive or scoped, so the two are not competing bindings at all.
3. **The cache is doing load-bearing work it was not designed for** — if
   `_CACHED_GATES` is the only thing keeping the two loads consistent, the
   caching boundary and the binding boundary disagree by construction.

Which of these is the intended contract is a composition-authority question, and
it is precisely the C-P56-1 property this very test defends.

## 10. Isolation matrix

| context | result |
|---|---|
| the single test, fresh process | **RED** |
| its whole file, fresh process | **RED** (1 failed, 11 passed) |
| file + `test_step10_p56_c5_w6_composed_health.py` | GREEN (31 passed) |
| file + `test_step12_pr12a_c1_composed_invariants.py` | GREEN (31 passed) |
| whole `tests/unit/workflows/` | GREEN (926 passed) |
| full serial suite ×2 | GREEN (12,987 passed) |
| by-count 8-shard bulk | **RED** |
| weighted 8-shard bulk | GREEN — **by assignment luck only** |

The last row matters: the weighted plan happens to place
`test_step12_pr12a_c1_composed_invariants.py` in the same shard, sorting before
the failing test. A green sharded run is therefore **not** evidence of health.

## 11. Explicit non-proposal

Test Infra is **not** proposing a repair and has **not** opened a corrective
branch. The surface reaches the production tuner and the composed-config
authority — both inside active C12-P-family semantics — so this is a
same-semantic-authority handoff, not a disjoint CI cleanup.

Test Infra will **not** mask it: no shard co-location, predecessor ordering,
cache warming, retries, quarantine or harness pre-import. Until the owning
authority resolves it, the harness reports one known RED with this attribution,
and sharded CI is **not** treated as authoritative.

---

## CP-12 — RESOLVED EXTERNALLY, and verified by this lane before consuming

The C12-P family produced the repair as **`6f8f5da4`** on `c12p-cp12-followup`,
one commit on top of base `84d74280`. This lane detected it mechanically — by
content identity over refs descending from base, never by branch name or commit
message — and verified it before merging.

### What the repair does

`load_health_gates_config` no longer returns early on a warm default-path cache.
`_CACHED_GATES` now memoizes the composed **value** while composition itself runs
on **every** call, because composing is not only a computation: it *binds* the
task's plugin set into the process run scope and replaces regime-A fact
derivation with the task's declared facts. Those globals have their own
lifecycle, so an early return made composition **authority** depend on cache
warmth.

It also corrected the site that masking had hidden: the tuner's first health
resolution composed `LEGACY_OMITTED` — TIDMAD's family — for a run that
materialized no effective config, so a composed run bound TIDMAD there and had
its own family refused moments later.

That is exactly classification **B** as handed over: *the production composition
authority should resolve the run's declared task independently.*

### Verification performed by this lane, against the repair rather than its message

| check | result |
|---|---|
| COLD single test `…loads_no_legacy_reference_science` | **1 passed** (RED on master — the whole defect) |
| COLD its whole file | **12 passed** (1 failed / 11 passed on master) |
| WARM `tests/unit/workflows/` | 926 passed (unchanged) |
| the repair's own test file, cold | 4 passed, carrying **5** `HealthPluginRunScopeError` assertions |
| `_plugin_binding.py` blob, base → repair | `7fbf4a6d` → `7fbf4a6d`, **byte-identical** |

The last row is the one that mattered most to check. The cheapest way to make
this failure disappear is to weaken the run-scope guard, and that would have
converted a detector into a silence. The guard source is unchanged and the
repair's own tests prove it still refuses a different family.

### Consumption

Merged as `a6223b33` (`merge --no-ff`; rebase is blocked by a repository hook,
and a merge records when this lane consumed the repair). Write sets are
disjoint — CP-12 touches `config.py`, the tuner and its `.md`, plus a new
health-checks test; this lane owns `tools/ci`, `tests/unit/tools/ci`, docs and
the workflow — so there was no conflict.

CP-12 is expected to land on master separately; this lane then reconciles
against landed master and the merged copy disappears.

### Why the by-count plan is part of the revalidation

The weighted plan passed CP-12 **by assignment luck** — it happened to place an
enabling file ahead of the failing test in the same shard. The by-count 8-shard
plan did not, and is the configuration that originally caught the defect. Re-running
that specific plan is therefore the discriminating evidence: a green there cannot
be explained by scheduling.


---

## CP-10 — the adjudication method, and a portability finding it exposed

Per-node JUnit now exists locally, so the collected-vs-emitted question can be
asked directly instead of inferred from summary counts.

**The two lanes partition the suite exactly.** At matched SHAs, bulk ∪ sensitive
== collected, with **zero** overlap between the lanes:

```
collected            13,057
bulk emitted         12,871
sensitive emitted       184
overlap                   0
union                13,055   + the 2 tests below == 13,057
```

The residual 2 were `test_the_changed_file_list_is_computed_exactly_once` and
`test_the_execution_step_is_not_a_hardcoded_suite` — added in `3b3211f6`, so
present at the collection SHA and absent from the older worktree the bulk ran
in. Not a defect: a SHA mismatch in my own comparison.

### The finding that matters for the remote adjudication

Ten node ids differed between the two checkouts **for the same tests**, because
their parametrisation embeds an **absolute path**:

```
…::test_contrast_gates_are_blank_at_both_hops[/home/yuema137/SIDERIUS/examples/…/task_health.yaml]
…::test_contrast_gates_are_blank_at_both_hops[/tmp/…/candidate/examples/…/task_health.yaml]
```

Affected: `test_step10_p4_c0_evidence_baseline.py` (8 ids) and
`test_step12_pr12d_f12d31_objective_authority.py` (2 ids).

The tests are correct — they parametrise over discovered config files — but the
**identity** of a test now depends on where the repository is checked out. Any
cross-environment node comparison, CP-10's included, must normalise the
repository root out of parametrisation ids or it will report ~10 phantom
differences between a local run and a runner at `/home/runner/work/SIDERIUS`.

Recorded as **CP-13**, deferred: the fix belongs to whoever owns those two test
modules (`id=` on the parametrisation, or a repo-relative path), not to this
lane. It does not affect correctness of any run.

### How CP-10 gets adjudicated

`ci-parity-evidence` from the first remote run carries per-node XML. Compare its
`testcase` entries against that run's collected count, normalising absolute
paths first. A residual gap identifies nodes collected but emitting no outcome;
no gap closes CP-10 as a reporting artefact of the summary line rather than a
parity defect.

---

## CP-14 — the first remote RED, and what reproducing it actually cost

Remote run `32830892610` failed on shards 2 and 3 and reported **nothing else**.
Verified mechanically: the entire 75 KB CI log contains exactly two
failure-mentioning lines, both of them this harness's own summary. The evidence
artifact had uploaded zero files.

Two defects, both mine, had to coincide (fixed in `6c60814c`):

1. `upload-artifact@v4` **excludes dot-prefixed paths by default**, and the
   workdir is `.ci_parity`. The step showed a green check while collecting
   nothing, warning only.
2. Shard pytest output goes to files, invisible in a CI log — so with the
   artifact empty the detail existed nowhere reachable.

### Reproduction, and its own contamination

| attempt | environment | result |
|---|---|---|
| plain | this host, data present, 4×1 | **GREEN** (762.5 s) |
| faithful | data hidden via mount namespace + `taskset -c 0-3` | **RED**, 4 failures |

**N = 4 → M = 2**, and the larger cause was the reproduction itself:

| RC | failures | cause | class |
|---|---:|---|---|
| RC-1 | 3 | `test_calibration_state.py:195,211` and `test_campaign_identity.py:265` `chmod(0o500)` a directory and expect the write to fail. `unshare -r` maps the caller to **uid 0**, and root ignores permission bits | **INVALID_HARNESS_EVIDENCE** |
| RC-2 | 1 | `test_gpu_measurement_runner.py:265` asserts `samples[0].at <= phases[0].started_at` | **real load-sensitivity** |

RC-1 is worth keeping visible: the tool built to hide machine data also silently
granted root, and three product tests "failed" for a reason that has nothing to
do with the product. A reproduction environment is an execution root like any
other, and its own distortions have to be classified before its results are
believed.

### RC-2 extends the CP-6 discriminator

The frozen rule looked for an upper wall-clock **bound**. This assertion has no
timeout in it at all — it is an **ordering** claim between two independently
scheduled things (a sampler thread and a worker boot), and contention can invert
it. Added to the frozen manifest, which is now **6 files**, and the
discriminator gains a row:

```
"A happened before B", A and B on different schedulers  -> sensitive
```

A grep for timeouts would never have found it. Only running under a constrained
CPU budget did.

### What remains unknown, honestly

The faithful reproduction failed **shard 1**; CI failed **shards 2 and 3**. The
plan is deterministic over an identical file list, so those are *different*
tests. **This reproduction did not reproduce CI's actual failures**, and with
the evidence capture broken at the time, CI's failing node ids do not exist
anywhere.

Learning them requires one further remote run — not to debug ordinary failures
remotely, but because local reproduction has been genuinely attempted across two
environments and cannot produce them, and because the fix under test *is* the
evidence capture. That is the narrow case the remote-budget rule reserves.

### Weight portability — CP-15

| environment | shard 0 (`test_step02b_checkpoint_c_live_integration.py`) |
|---|---:|
| local, threads=2 | 449.2 s |
| local, threads=1 | 762.5 s |
| **CI runner** | **25.1 s** |

The file is expensive here because the machine data exists and its
live-integration work runs; on CI that work skips. **The weight table encodes a
property of this host.** On the runner it inverts the balance — shard 0 idle at
25 s while shards 2 and 3 carry ~500 s each.

So the weighted planner's measured advantage is **local only**, and no claim is
made that it improves a runner. CP-8's machine-data axis, which appeared first
as a skip-count divergence, is also a *runtime* divergence. Recorded; not acted
on, because acting would mean measuring weights in a CI-like environment and
that is a change worth making deliberately rather than in a failure-repair pass.

---

## CP-16 — the harness was contaminating the tree it tests

Remote run `32834492183` was RED with **two** failures, and this time the fixed
evidence capture named them. **N = 2 → M = 1.**

```
shard 1  tests.unit.tools.ci.test_preflight…test_a_non_git_directory_reports_unknown_sha_and_refuses
shard 3  tests.unit.workflows.test_step12_pr12d_checkpoint_a…test_zero_production_imports_from_examples
```

### The single cause

The workdir was `$GITHUB_WORKSPACE/.ci_parity` — **inside the checkout**. Every
shard's `TMPDIR` lives under the workdir, so every `tmp_path` in every test
landed inside the repository.

| failure | mechanism |
|---|---|
| shard 1 | the test needs a **non-git** directory; `tmp_path` was `…/SIDERIUS/.ci_parity/bulk/shard01_tmp/…`, so `git rev-parse HEAD` walked up and **succeeded**, returning `2abb6620…` where the test asserts `None` |
| shard 3 | `test_plugin_loader.py:110` plants `def (: pass` in its `tmp_path` — a legitimate syntax-error fixture. That file landed in the repo, and the census at `test_step12_pr12d_checkpoint_a.py:386` walks the tree skipping `tests/ examples/ tools/ .venv/ .claude/ agent_generated/` — **not `.ci_parity/`** — parsed it, and died on `SyntaxError` |

Shard 3 failed on a file **shard 1 or 2 wrote**. Cross-shard contamination of
the source tree, from a harness whose own documented rule is that no shard
mutates the checkout during execution. The census is correct and should not have
to know this scratch directory exists; the defect is entirely the harness's.

### Fix

* `run_bulk` raises `WorkdirInsideSourceTree` for a workdir equal to or beneath
  the root. Refuse, not warn: the contamination is silent, and it surfaces in a
  *different* shard from the one that caused it.
* The default workdir moved out of the repository to the system temp.
* CI uses `$RUNNER_TEMP/ci_parity`, and the artifact path follows it.

### Causality, proven both ways

```
TMPDIR outside the tree   2 passed
TMPDIR inside the tree    test_a_non_git_directory… FAILED   (CI's exact failure)
```

### Why this took two remote runs

Run 1 was RED and said nothing at all — the artifact silently uploaded zero
files (dot-prefixed path) and shard output went only to files. Run 2 carried the
fix for that and immediately named both nodes, and the artifact uploaded 18,674
files.

Neither run was spent debugging ordinary product failures. The first exposed
that the evidence pipeline did not work; the second proved it does, and paid for
itself by identifying a defect that two local environments had failed to
reproduce.

---

## CP-10 — SOLVED. The three nodes were GPU parametrisation

The original observation: CI reported 12,941 passed + 48 skipped = **12,989**
terminal outcomes where local collection said **12,992**. Three nodes
unaccounted for, every local hypothesis eliminated by measurement, and no way to
go further without CI-side per-node data.

Run 2's artifact supplied it. Diffing CI's emitted node ids against a local
collection of the same bulk file set — normalising the checkout root out of
parametrisation ids, which CP-13 showed is required — leaves exactly three:

```
tests…test_inference_checkpoint_loading.TestWhatIsLoadedIsUnchanged
    ::test_dtype_and_device_placement_survive_the_host_load[cuda:0]
    ::test_parameter_values_are_identical_either_way[cuda:0]
    ::test_predictions_are_identical_on_a_fixed_input[cuda:0]
```

`tests/unit/execute_tools/test_inference_checkpoint_loading.py:178`:

```python
DEVICES = ["cpu"] + (["cuda:0"] if torch.cuda.is_available() else [])
```

consumed by three `@pytest.mark.parametrize("device", DEVICES)` (`:184`, `:205`,
`:220`). This host has a GPU, so `cuda:0` is collected; a GitHub runner has
none, so those three parameters do not exist there.

**Verdict: not a defect, and not a reporting artefact — a real, correct,
capability-dependent collection difference.** The original comparison was
invalid: it measured a LOCAL collection against a REMOTE run. Collected counts
are only comparable within one capability profile.

### What this adds to the parity contract

Test **collection** is environment-dependent, not merely test **outcomes**. Three
mechanisms are now confirmed, all of them legitimate:

| mechanism | effect | example |
|---|---|---|
| machine-local DATA presence | changes **skips** (CP-8) | 43 skips |
| checkout path | changes **node ids** (CP-13) | 10 ids |
| device availability | changes **collection** (CP-10) | 3 nodes |

So a cross-environment node comparison must normalise the checkout root *and*
account for capability-dependent parametrisation. Counts alone cannot adjudicate
anything — which is exactly why the operator ruling that node identities, not
counts, are the durable contract was the right call.

### The harness itself is clean

CI's four bulk shards emitted **12,835 testcase entries with 12,835 distinct
node ids and zero duplicates**. No node was executed twice, and none went
missing. That is the property the sharding scheme has to hold, now measured on a
real runner rather than argued.

---

## CP-15 (continued) — MEASURED: the harness does not speed up CI

Run `32835810411` (`3a79c97a`) was fully GREEN — every step, both lanes, the
artifact. It is also the first honest measurement of what this harness does to
remote wall-clock, and the answer is: **almost nothing.**

| | |
|---|---:|
| bulk lane | 524.3 s |
| sensitive lane | 57.3 s |
| **harness test total** | **581.6 s** |
| banked historical single pytest step (`ci.yml:30`) | 628 s |
| **ratio** | **1.08×** |

Against **2.89×** measured locally. Two reasons, both structural:

1. **The runner has 4 vCPUs.** Four shards at one thread each saturate it, so
   scheduling cannot beat the CPU budget. The local 2.89× came from having 24
   cores, not from the planner being clever.
2. **The weights are mis-calibrated for CI** (CP-15). Shard 0 carried the
   locally-dominant file and finished in **31.3 s** while shards 1-3 ran
   450.7 / 483.1 / 524.2 s. Perfectly balanced CI weights would give
   ≈ 372 s — about **1.69×**, and still nowhere near the local figure.

### What this means for the claim this PR makes

**Speed is a local benefit and must not be presented as a CI benefit.** On a
runner the harness buys:

* **attribution** — per-node JUnit, failing node ids inline in the log, a
  provenance manifest. Run 1 was RED and said nothing at all; run 2 named both
  failures instantly. That difference is the entire point.
* **hermeticity** — preflight refuses an invalid execution root before ~13,000
  tests run, and the resource profile is recorded rather than assumed.
* **the sensitive lane** — six files that must not compete with a saturated
  bulk lane, now run serially and reported even when bulk fails.

Not speed. The PR says so explicitly rather than letting a local benchmark
imply otherwise.

### Residual, deliberately not fixed here

Re-measuring weights in a CI-like environment would recover perhaps 1.08× →
1.69×. That means measuring on a data-less, 4-CPU host and committing a second
weight table, or making weights environment-scoped. It is a real improvement and
a deliberate design change — not something to slip into a failure-repair pass at
the end of a PR. Recorded for a follow-up.

---

## Reconciliation against landed master `8f5e69ba` (TESTINFRA-RECONCILE-001)

Twelve PRs landed while this lane waited — #295 #298 #299 #304 #296 #305 #306
#294 #307 #308 #310 #311 — moving the base from `84d74280` to `8f5e69ba`:
308 files, +51,806 lines, and the unit suite from 689 to **761** test files.

The wait was deliberate. Reconciling earlier would have cost one reconciliation
per landing.

### CP-12 collapsed out, exactly as this ledger predicted

Four files conflicted, **all of them CP-12's**:

```
execute_tools/health_checks/config.py
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py
nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md
tests/unit/execute_tools/health_checks/test_c12p_cp12_composition_cache_authority.py
```

Master's version was taken for every one, and each now matches
`origin/master` **byte-identically**. The repair landed as **#298 (`1902a377`)**,
authored and owned by C12-P, carrying a later docstring correction that this
lane's copy predated (`66e5b9f3` → `ff688961`). The diff against master no longer
contains a single CP-12 file.

That is the outcome recorded when the repair was consumed: *"CP-12 is expected to
land on master separately; this branch then reconciles and the merged copy
disappears."*

**This lane's own bytes did not move.** Every file under `tools/ci/`,
`tests/unit/tools/ci/`, `docs/` and `.github/` is byte-identical to pre-merge
`e393e742`. `tests/conftest.py` auto-merged with both changes intact — the CP-1
helper present, the developer path still absent.

### Base-movement classification

| class | what |
|---|---|
| **STILL VALID** | the harness's own contracts. 94 harness + selector tests pass on the new base; all 6 sensitive files still exist; `verify_plan` clean over 761 files; ruff and pyright clean |
| **PROVENANCE-ONLY** | the banked baselines (12,992 collected, the 460.3 s dominant file, 2.89× local). They are labelled with the SHA they were measured at and describe `84d74280`, not this tree |
| **DETERMINISTIC INVALIDATED** | the canonical CI at `e393e742`. It exercised a different base, so the reconciled head needs its own run |
| **SEMANTICALLY INVALIDATED** | **nothing.** No finding is overturned, no contract changed, and CP-12 landed exactly as predicted |

### What was re-run, and why only that

* **harness + selector-composition tests** — master changed
  `tools/ci_selection/manifest.py` (+27 lines), which this harness *composes*.
  A dependency move demands re-verification: **94 passed**.
* **plan validity on the new file set** — 761 files → 755 bulk + 6 sensitive,
  imbalance 1.044, `verify_plan` clean.
* **static checks** — ruff and pyright (managed node) clean.

Deliberately **not** re-run: the full local bulk lane and the sensitive lane. The
harness's bytes are unchanged, its unit contracts pass, and the push triggers CI
which is the canonical evidence for the new head. Re-running locally first would
be the duplicate expensive validation the economy rule forbids.

**Weights are now partial by construction**: 262 files were measured at
`84d74280`; the 72 files added since resolve to `DEFAULT_WEIGHT`. That degrades
balance, never correctness — shard 0 still isolates the dominant file and
imbalance is 1.044. Re-measurement belongs with the CP-15 follow-up, not here.
