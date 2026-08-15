# SIDERIUS Project Rules

## Context
- SIDERIUS is a project that utilizes LLM agents to explore advanced denoising
  algorithms (stage 0), propose new hypotheses, and conduct experiments to
  investigate them (stage 1).
- Primary application: SQUID / TIDMAD signal denoising (framed in
  `configs/task_config.yaml`). The framework is task-agnostic — porting to a new
  task starts with editing `configs/task_config.yaml`, not with grep-and-replace
  across Python sources.

## Environment
- **Always use the project virtualenv**: every Python command must use the
  repo's `.venv/bin/python` (e.g. `/workspace/REPO/SIDERIUS/.venv/bin/python`
  on the H100 box, `/home/yuema137/SIDERIUS/.venv/bin/python` on lilab) or
  activate `.venv/bin/activate` first. Never use the system `python` or `python3` — they are Python 3.8 and
  will fail on f-strings and other modern syntax.
- **`run_comparison.py` lives at `scripts/run_comparison.py`** (moved from repo
  root in commit `13c34fa`). If you see a `SIDERIUS_ROOT` bug where subprocess
  paths resolve to `scripts/nodes/...` instead of `nodes/...`, that's the
  double-dirname fix from commit `6789e29` — verify that fix is on disk before
  running.
- **Standard baseline / chain launch command** (as of 2026-07):
  ```bash
  python scripts/run_comparison.py \
      --model {wavenet|punet|...} \
      --provider openai --model_id gpt-5.5 \
      --reflect_provider openai --reflect_model_id gpt-5.5 \
      --max_rounds 10 \
      --max_epochs 1 \
      --trial_time_budget_minutes 20 \
      --formal_time_budget_minutes 120 \
      --formal_portion 0.1 \
      --formal_train_portion 1.0 \
      --run_name healthgate_baseline_v1 \
      --is_trial \
      --progress_bar \
      --cleanup_denoised
  ```
  - `--max_epochs 1` matches the TIDMAD paper spec (direct communication from
    the paper authors). The 10-epoch default was wrong.
  - `--trial_time_budget_minutes` / `--formal_time_budget_minutes` cap per-round
    wall time. Without them, a badly-chosen `trial_portion` from the LLM planner
    can produce multi-hour trial rounds.
  - `--max_epochs` is forwarded to the tuner subprocess (clamps LLM-planned
    epochs to `min(planned, max_epochs)`).

## Repository and Environment Portability

SIDERIUS is maintained as a large open-source codebase. All production
code, scripts, tests, and documentation examples must operate on the
**current checkout** and on **explicitly configured** resources. They must
not silently depend on a particular developer, server, username, home
directory, or separate repository clone.

Operator documentation may explicitly name known deployments and
machine-specific examples. The prohibition is against implicit or silent
dependencies in executable code and tests, not against clearly labelled
documentation of a specific environment.

**Motivating failure**: two test modules hardcoded one developer's
repository path. CI failed because that path did not exist on the runner —
and locally the same tests could pass falsely by reading a *different*
clone, so a local green result said nothing about the code under test.

### Required practices

- **Never hardcode an absolute repository path**, such as
  `/home/<user>/SIDERIUS` or `/Users/<user>/.../SIDERIUS`.
- **Derive the repository root from the current file location**, or use an
  existing repository helper:
  ```python
  REPO_ROOT = Path(__file__).resolve().parents[...]
  ```
  Prefer the established project helper or a nearby convention when one
  exists; do not duplicate root-discovery logic unnecessarily.
- **Tests must load code and artifacts from the checkout in which the test
  is being executed.** A test must never silently import or load files from
  another clone.
- **Machine-specific data paths, workspace paths, cache paths, and
  executable paths must come from** configuration, environment variables,
  fixtures, or explicit test parameters.
- **Tests that require external datasets or machine-specific resources
  must**: declare the requirement clearly; validate the configured path;
  skip or fail with an informative reason according to the intended test
  contract; and never fall back silently to a developer-specific location.
- **Temporary files must use pytest fixtures** (`tmp_path`) or standard
  temporary directories, rather than fixed shared locations.
- **Shell scripts must resolve paths relative to their own location** or to
  a supplied repository/workspace root — not to the caller's current
  working directory, unless that dependency is intentional and documented.
- **Local success is not sufficient evidence of portability** when a test
  touches filesystem paths, environment variables, executables, GPUs,
  datasets, or shell tools. Add a targeted portability check when the risk
  is meaningful.

### Portability validation

When adding or modifying path-sensitive tests, verify where practical that
they work from a checkout at a different absolute path. A useful check is:

```text
current checkout
  → copy or clone to a temporary unrelated path
  → run the targeted tests there
  → confirm they read that checkout, not another local clone
```

Simply running a test from another working directory is insufficient if an
old hardcoded path still exists on the machine: an absolute reference keeps
resolving to it, and the test passes while validating the wrong tree.

### Environment assumptions

Do not assume that local tools and CI tools are identical. Before claiming
a check was run locally, verify that the required tool can actually run in
the local environment, and record limitations explicitly — for example, an
unsupported Node version preventing local pyright execution. Do not claim
local validation when CI is the only environment capable of running the
check.

### Regression rule

When a portability defect is found:

1. Classify whether it is production code, test scaffolding, or
   environment configuration.
2. Search for the same hardcoded pattern in nearby files.
3. Fix the smallest confirmed scope.
4. Add a regression test that proves the current checkout is used.
5. Track broader similar findings separately, rather than silently
   widening the active PR.

**Governing principle**: a green test is meaningful only if it tests the
code and resources from the checkout and environment it claims to
validate.

## Coding Standards

- **Logic First**: Before every modification, review the current structure of
  the whole project. Think about whether the structure is appropriate, rather
  than just adding the desired feature. Keep the code clean and elegant.
- **Slow is Smooth, Smooth is Fast**: Never be greedy when adding features or
  refactoring. Fixing the bug is always the priority; elegance of structure
  comes after. Focus on the current problem at each step and don't
  over-optimize.
- **Clear docstrings and comments**: Write correct types for inputs and outputs.
  Pydantic validation and appropriate error messages are highly recommended for
  every function and class.
- **Never pass raw LLM output to execution without Pydantic validation**:
  LLM-generated content (hyperparameters, trial parameters, any config) must go
  through a Pydantic schema before it reaches any execution layer (training,
  inference, scoring). The validated schema object is the single source of
  truth — execution code reads from the schema, not from raw dicts. This
  applies to every config type: `ExperimentPlan` validates the LLM plan,
  `TrialConfig` validates trial/formal decisions, `TrainConfig`/`LossConfig`/
  model configs validate hyperparameters. If a new config category is
  introduced, define a Pydantic model for it before wiring it into execution.
- **Avoid deep dependency between modules**: each module should be testable
  individually, pluggable, and decoupled.
- **Every test must name a defect only it can catch (binding, operator
  decision 2026-08-02)**: before adding or keeping a test, answer:

  > If this test were deleted, which real defect would no longer be
  > caught by Pydantic, pyright, ruff, another existing test, or a Gate?

  If there is no answer, the test is decoration. Do not pytest what a
  declaration already enforces: an optional field defaulting to `None`,
  a `Literal` rejecting an unknown string, a declared type accepting
  its own type, a required field being required, or a scalar
  round-tripping through JSON with no custom serializer.

  **A new test must also state how it fails when the behaviour breaks.**
  Both defects found on 2026-08-02 — a `... or True` assertion and a
  guardrail blind to the most common `subprocess` calling form — passed
  review because nobody asked that question. 383 cases were guarding
  nothing.

  **Never assert a value read back from the thing under test.**
  `record.file_index == Model.model_fields["file_index"].default`
  compares the schema to itself and passes for any default. Hardcode the
  expectation.

  **Test the concept, not the field.** A rule that spans models needs one
  test naming the concept and asserting across every model that declares
  it — the per-field shape cannot express it, which is how ten
  cross-schema divergences and eleven unpinned production defaults
  survived a 6,900-test suite.

  **Consolidating a test family requires stating**: which non-equivalent
  input classes the originals covered, how the replacement preserves each,
  which assertion fails when each class breaks, and why a static checker
  or Gate cannot cover it. Ten tests calling one function are not
  thereby equivalent.

  Preserve without argument: regression tests naming a dated incident,
  SHA, campaign ID or a production value that failed; reachability tests
  proving a guard is actually called; and prompt text that IS a safety
  control.
- **Be humble and curious**: if you are not sure about something (the detail of
  a desired feature, the format of data), do not guess — ASK the user
  explicitly.
- **Be strict to the user and always double check**: what the user says is not
  always correct. If you feel a statement is wrong or an idea is impractical,
  ask for clarification and state your objection clearly.
- **Never directly continue on the previous work right after conversation
  compression**: stop after conversation compression. The user will remind you
  of the context, the docs, and the code to read. Never start blindly.
- **Gradual genericization (in-passing rule)**: SIDERIUS is being reshaped
  from TIDMAD-only into a generic dataset/task/metric framework (operator
  decision 2026-07-27). When a PR touches a module, refactor the touched
  module toward the generic seams as part of that PR — in its own commit,
  skippable for urgent fixes. Never a big-bang refactor PR. Seams are defined
  once in the genericity contract (`docs/design/v19_priorities.md` §1.3 until
  the dedicated contract doc exists; design direction in
  `docs/architecture.md`) — do not invent ad-hoc abstractions. Exception: the
  frozen TIDMAD score formula stays byte-identical; new metrics plug in
  beside it, never rewrite it.
- **Responsibility-oriented decomposition (binding, operator decision
  2026-08-01)**: SIDERIUS must not create or further enlarge giant
  orchestration functions. A function that coordinates multiple phases,
  constructs records, handles errors, mutates state, performs I/O **and**
  decides control flow is not a valid extension point — it is several
  components sharing one scope.

  **The rule**: do not add substantial new branching, record construction,
  persistence or task logic directly into an already oversized function.
  Instead:

  ```text
  identify the responsibility
  → extract a typed, independently testable boundary
  → prove behavioural parity
  → put the new feature inside that boundary
  → leave the top-level orchestrator doing sequencing
  ```

  Split by **responsibility, not line count** — phase execution, result
  interpretation, failure/skip record construction, retry and round
  transitions, evidence attachment, admission decisions, artifact
  persistence. A helper that still reads and mutates arbitrary outer
  state is not a completed decomposition; it is the same complexity in a
  different file. Each extracted unit needs explicit inputs, a typed
  result, a documented responsibility, bounded side effects, focused
  tests, and **reachability evidence** — a test that fails when the
  production path bypasses the boundary.

  Every decomposition must preserve behaviour and prove it: parity before
  and after, unchanged retry/round behaviour, unchanged phase ordering,
  unchanged timeout and signal semantics, unchanged persisted artifacts
  and statuses, and strict type checking over the extracted units. Never
  change retry, phase order, signal, timeout or scientific behaviour
  "while refactoring".

  Bounded in-passing decomposition, as with genericization — **never a
  repository-wide rewrite**, and never a full rewrite of one giant
  function in a single PR.

  **Review trigger, every PR**: *does this add a new responsibility or new
  branching to a function already coordinating unrelated concerns?* If
  yes, establish the boundary first. Adding detail to a focused function
  is fine; adding another responsibility to a giant orchestrator is not.

  **Why this is a rule and not a preference**: `HyperparamTuningAgent.run()`
  reached 2,487 lines and sat *exactly* on pyright's strict complexity
  ceiling — 258 branch nodes passed, 259 failed. Past that limit strict
  mode does not degrade, it abandons the whole function, so every
  annotation inside the tuner's main method was unverified. The defect was
  invisible until an unrelated PR added one `if`. Waiting for a type
  checker or a test suite to collapse is not a design process.

- **Cold-start real-training gate runs (operator rule, 2026-07-27)**:
  every new real-training gate run (Gate 1 with real training, Gate 2,
  any smoke that invokes `run_chain.sh` or `run_one_iteration.py` with real
  training) must be **cold-start** — do NOT pass `--seed_paths`. Rationale
  and the twin DS8 partial-scope rule (paired `--data_scope` +
  `--health_gate_files`) live in `docs/gates/gate_testing_standard.md`
  "Partial-scope rules" section. The pre-DS8 canonical seed paths still
  listed there are historical reference only. Exception: reproducing a
  specific historical seeded run — operator-approved case-by-case only.
- **Node/skill doc sync before merge (operator rule, 2026-07-28)**:
  every PR that updates a node or a skill must update the relevant
  `.md` (the node's `nodes/{node}/{node}.md`, the skill's doc, and any
  operator-surface doc such as `docs/running_chain_test.md`) so CLI
  arguments, default values, and behavior explanations stay current —
  this codebase is large and the docs are the operator's map. If a
  touched skill has no `.md`, create a minimal one. Done as the very
  last step before merging the PR (so docs describe the merged code),
  written into the PR's plan as its own checklist stage, and verified
  by quoting each documented flag/default against the merged source.
- **Final validation runs from a clean tree, and the verdict comes from
  the log (binding, operator decision 2026-08-08)**: two near-misses in
  one PR B session, both promoted from incident to standing rule.

  **1. Commit the semantic checkpoint BEFORE running the full suite.**
  `tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants`
  runs `git diff --name-only`
  (`scripts/pr3_l2_calibration/preflight.py:287`) and fails when **any**
  uncommitted file outside `scripts/pr3_l2_calibration/`, `tests/`,
  `docs/`, `reports/` or `*.md` is modified — the PR3-L2 calibration
  protocol requires production untouched at launch. Run the full suite
  on a work-in-progress tree and it reports a failure naming the files
  you are editing. That is the guard working.

  ```text
  full suite red, no_production_file_modified
    -> commit the checkpoint, re-run
    -> NEVER relax the guard to make an in-progress tree green
  ```

  Targeted and subsystem runs during development are fine; it is the
  **full** suite whose result is meaningless from a dirty tree.

  **2. Never take a pytest verdict from a wrapper's exit status.**
  `pytest ... | tail -5` reports **`tail`'s** exit code, so a run can be
  announced as exit 0 while the log says `1 failed`. Redirect, capture
  pytest's own status, then show the tail:

  ```bash
  pytest <args> > /tmp/pytest.log 2>&1
  rc=$?
  tail -n 20 /tmp/pytest.log
  exit $rc
  ```

  or set `-o pipefail` explicitly. A background-task notification's
  "exit code 0" is **not** evidence that pytest passed; read the log.

**Nodes communicate exclusively through three mechanisms — schema, storage, and
protocols. No other form of inter-node communication is permitted.**

- **Schema**: the input and output `BaseModel` of each node is the complete,
  explicit contract for what data flows in and out. Every field that a
  downstream node needs must be present in one or more upstream node output
  schemas and mapped by the protocol. The input schema is the completeness
  contract — it validates that all required fields are present, regardless of
  how many sources contributed. There are no hidden contracts.
- **Storage**: each node writes its own output record to
  `{storage.local.workspace}/{node}_{run_name}.json` for persistence and
  recovery. This is NOT the communication channel — it is a log. Downstream
  nodes never read the upstream node's output file from storage; they receive
  data through the protocol function in memory.
- **Protocols**: typed functions that assemble a target node's input from one
  or more upstream node outputs. The protocol is the only place where field
  mapping happens. It receives the required upstream `*Output` objects and must
  produce a fully populated downstream `*Input`. No field should be silently
  dropped. Simple protocols take one source; fan-in protocols aggregate
  multiple sources when the target needs data from non-adjacent nodes.

**Why this matters**: as the graph grows, any shortcut (reading files by
convention, sharing state through the filesystem, passing paths instead of
data) creates hidden dependencies between nodes that are invisible to the
protocol system. This makes the graph untestable in isolation and fragile when
nodes are reordered or replaced. The schema + storage + protocol triad keeps
every edge in the graph explicit, typed, and independently testable.

---

## Graph Architecture — Adding a New Node

SIDERIUS has a **directed graph structure** where nodes are agents or
processing modules and edges are typed protocols. When adding any new node,
work through all 8 steps below. Do not consider a node "done" until all 8 are
complete.

| Step | Artefact | Location |
|------|----------|----------|
| 0 | **Graph placement** — decide which existing nodes feed into this node (upstream) and which nodes consume its output (downstream). Draw or write out the directed edges explicitly: `A → new_node → B`. Confirm the input schema can be fully populated from the upstream node's output schema, and that the output schema covers everything the downstream node needs. No file is generated at this step. | (design only) |
| 1 | Node implementation | `nodes/{node_name}/{node_name}.py` (one directory per node) |
| 2 | Protocol(s) for each edge this node participates in | `agent/schemas/protocols/{source}_to_{target}.py` |
| 3 | Node unit tests (mocked LLM) | `tests/unit/agent/{node_name}/test_{node_name}.py` |
| 4 | Protocol unit tests | `tests/unit/agent/protocols/test_{source}_to_{target}.py` |
| 5 | Node integration test (real API, Tier 1) | `tests/integration/nodes/test_{node_name}.py` |
| 6 | Protocol integration test (real API, Tier 2) | `tests/integration/protocols/test_{source}_to_{target}.py` |
| 7 | **Connection audit** — verify end-to-end schema compatibility: every field required by the downstream node's input schema is present in this node's output schema, and every field required by this node's input schema is present in the upstream node's output schema. Check that each protocol function correctly maps all fields without silent defaults or missing keys. Run the full unit test suite to confirm nothing is broken. | (no new file — audit existing files) |

**Agent design principle**: each agent is scoped to one well-defined category
of task within its module, and should be flexible enough to handle that task
well. Cross-task and cross-module flexibility is the responsibility of the
infrastructure (orchestrators, protocols) — not the agent. An agent that tries
to be general-purpose becomes unpredictable and hard to test. Concretely:
`ml_code_validator_agent` validates ML model plugin code — it does not validate
arbitrary code, and it knows about the ML plugin interface contract
specifically.

**Agent naming convention**: agent names are prefixed by the module they belong
to, followed by a concise, specific descriptor of their task. The prefix is
not universal — it reflects which module the agent lives in. As new modules
are added (e.g. a data module, a reporting module), they will introduce their
own prefixes. Do not use a prefix from a different module just because it
sounds close.

| Prefix | Module | Example agents |
|--------|--------|----------------|
| `ml_` | Machine learning pipeline | `ml_hyperparameter_tune_agent`, `ml_model_proposal_agent`, `ml_model_implementor`, `ml_code_validator_agent` |
| `data_` | Data processing / analysis | `data_analysis_agent` |

When naming a new agent: identify which module it belongs to, use that
module's prefix, then add a short snake_case descriptor of the specific task.
Avoid generic suffixes like `_processor` or `_handler` — be specific. A name
like `code_validator_agent` (no prefix) is wrong because it implies generality
across modules; `ml_code_validator_agent` is correct because it is explicitly
scoped to the ML pipeline.

**Protocol naming convention**: one file per directed edge, named
`{source_code}_to_{target_code}.py`. Node codes: `ml_literature_review` (full name), `ml_model_tune`,
`ml_result_interp`, `ml_model_propose`, `ml_model_impl`, `ml_model_valid`.
Functions inside the file: `{transport}_{data_scope}` (e.g.
`local_all_records`, `database_full_context`). Always add a `database_*`
placeholder (raises `NotImplementedError`) alongside every `local_*` function.

**Integration test tiers** — tiers describe how many nodes are exercised in a
single test, not API load or cost. Real-API tiers skip automatically if the
required API key is not set.

| Tier | Scope | Location | What it tests |
|------|-------|----------|---------------|
| **Pseudo-full-loop** | Full node orchestration, predefined LLM + subprocess results | `tests/integration/` (`@dual_mode`) | The wiring between the agent's internal steps (plan → train → score → reflect → save) works correctly. Runs in milliseconds, no API key, no GPU. **Default mode for dual-mode tests.** |
| **Tier 1** | One node in isolation | `tests/integration/nodes/` (`@real_run`) | A hand-crafted synthetic input is passed directly to `node.run()`. Validates that the node itself works end-to-end with a real LLM call. No other node is involved. |
| **Tier 2** | One directed edge (two nodes) | `tests/integration/protocols/` (`@real_run`) | The upstream node runs with a real LLM call, the protocol function maps its output to the downstream node's input, and the downstream node runs. Validates that the wiring between two specific nodes is correct. |
| **Tier 3** | Multi-hop path (3+ nodes) | `tests/integration/workflows/` (`@real_run`) | A sequence of nodes traversed end-to-end. Validates that a complete sub-path of the graph works correctly. |

**Dual-mode tests** (`@pytest.mark.dual_mode`) run in pseudo mode by default
(predefined responses from `tests/pseudo_data/`) and switch to real mode only
when `--real-api-call` is passed. New integration tests should be dual-mode by
default. See `docs/pseudo_test_infra.md` for the full design.

Steps 5 and 6 in the node checklist correspond to Tier 1 and Tier 2
respectively.

## Skill Architecture (Universal Callable Contract)

**Every callable in the system is a skill.** Agents, atomic tools, and
orchestrators all conform to a single interface: `{name, description,
input_schema, output_schema}`. From the caller's perspective, there is no
structural difference between a deterministic function and an LLM-powered
agent — both are skills with typed inputs and outputs.

The hierarchy describes internal composition, not the external interface:

```
Orchestrator  (LLM-powered, goal-driven, selects skills autonomously)
  └── Workflows  (pre-designed paths through the graph, deterministic)
       └── Agents  (LLM-powered, run(input)->output, may use tools internally)
            └── Tools  (atomic operations: training, inference, scoring)
```

**Workflows vs. Orchestrators**:
- **Workflows**: execute a pre-designed, deterministic path through the graph.
  The sequence of nodes and protocols is hardcoded. Workflows are scripts, not
  agents. Used for the first demo and well-understood sequences.
- **Orchestrators**: LLM-powered agents that pursue a goal autonomously. They
  query a skill registry, select which skills to invoke (including workflows
  as sub-skills), apply protocols, and iterate until the goal is met. This is
  the long-term target.

**Current naming convention**: `agent/skills/` holds atomic tools (training,
inference, etc.) used internally by agents. This will be renamed to
`agent/tools/` after the first demo, to reserve "skill" for the universal
contract. See `docs/architecture.md` for the full plan.

## HealthGate System (Pluggable Health Checks)

SIDERIUS uses a rev-6 **HealthGate** system to catch model failures during
tuning without polluting the scoring pipeline. Migration landed in PR #101
(commits 1-6).

- **Config**: `configs/health_checks.yaml` — source of truth for gate
  POLICY (which check runs at which round, thresholds, `GateAction` on
  failure, and the DEFAULT monitored-file placement). Edit this file, not
  code, to change gate behavior. Two things are run-level INPUTS, not YAML
  (DataScope feature, DS4-DS6): `health_gate_enabled` (subsystem switch)
  and `health_gate_files` (shared monitored-file list overriding every
  check's `peek_file_indices`). At startup the run materializes the
  EFFECTIVE config to `{workspace}/health_checks_effective.yaml` (sha256
  pinned by the run-invariants lock) and every path-based loader reads
  that file — never override the config in memory.
- **Skills**: `execute_tools/health_checks/` — each check is a
  `HealthCheckSkill` conforming to `run(ctx, config) -> HealthCheckResult`.
  Built-in checks: `OutputDiversityCheck`, `AmplitudeCollapseCheck`. Add new
  checks by registering a subclass and referencing it from the YAML.
- **Gate actions**: `CONTINUE`, `INVALIDATE_ROUND`, `SKIP_TO_FORMAL`,
  `SKIP_ITER`. Severity resolution when multiple gates fire in one round:
  `SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`.
- **Firing point**: gates fire at **tuner round boundaries** in
  `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`, NOT
  inside `score_vector`.
- **Design doc**: `docs/design/pluggable_health_checks.md`.

## Baseline Configs — TIDMAD Paper Alignment

**`ml_models/legacy_baseline_configs.json` is the source of truth for
paper-spec baseline configurations.** Cross-referenced verbatim against
`/home/tidmad/TIDMAD/train.py` and `/home/tidmad/TIDMAD/network.py` (class
`FocalLoss1D`).

Aligned parameters (as of commit `3e119c6`):
- **Learning rate**: `lr = 5e-4` for every model (paper:
  `torch.optim.Adam(..., lr=0.0005)`). Was `1e-3` before the fix.
- **Wavenet focal alpha**: `alpha = 0.5` (paper: `FocalLoss1D()` default). Was
  `0.25` before the fix. Punet/transformer/rnn/gated_fno already matched at
  `alpha=0.5`.
- **Epochs (Phase 1 baseline)**: hardcoded to `--max_epochs 1` in
  `scripts/run_comparison.py::run_baseline_trial` (paper authors, direct
  communication).

Structural discrepancies known and NOT addressed by config alone:
- Paper trains 4 separate models per architecture (frequency-band split via
  `ifile_checkpoint = [0, 4, 10, 15, 20]` in `train.py`); SIDERIUS trains a
  single generalist model on all 20 files.
- Paper re-initializes the optimizer per-file (`optimizer = ...` inside the
  `for ifile` loop); SIDERIUS uses a single optimizer.

The `FocalLoss1D` implementation itself
(`ml_models/loss_models_sandbox.py:135-168`) is line-for-line identical to
TIDMAD's `network.py:FocalLoss1D`.

## Subsystem Invariants (Read Before Touching)

- **`score_vector` is pure scoring** (2-tuple return: `(file_vector, scalar)`)
  after the commit-5a refactor. It does NOT return `is_degenerate` or
  `failure_reason`. Never call `score_vector` expecting health-check results —
  use HealthGates in the tuner instead. Any downstream consumer that reads
  `is_degenerate` / `failure_reason` from a merged score record should use
  `.get(default)` (these keys are no longer produced by score_vector, though
  `StubSandbox` still injects them for pseudo-mode compatibility).
- **Production scoring goes THROUGH the evaluation-metric handle (Step 06,
  2026-08)** — `execute_tools/evaluation_metric.py`. The tuner binds
  `run_metric` once at run scope and calls
  `TidmadSandbox.evaluate_metric(run_metric, …)`; the scoring subprocess
  (`denoising_score_single.py`) reconstructs the same TIDMAD instance from
  `--dataset_profile_json`. Order inside both routes is load-bearing:
  DataScope validation → the metric's **executable scoreability contract**
  (`ScoreabilityContract.check`, structured `NotScoreableResult`) →
  `scoring_utils.score_vector` (arithmetic untouched, still the pure 2-tuple).
  A refused deliverable is `NotScoreableError` → an `error_scoring` record with
  `failure_type="not_scoreable"` and `metric_refusal`; never re-inline
  `score_vector` at a call site, never move the contract after the arithmetic.
  `TIDMAD_METRIC_ID = "tidmad_denoising_score"` and the direction vocabulary
  are declared ONCE in the metric module (guarded); `per_file_best` imports
  the id. Losses are NOT metrics (metric types refuse loss-shaped ids).
  Records carry the additive `metric_result` / `metric_refusal`; the frozen
  `denoising_score` / `file_vector` / `score_table` names are unchanged (D1).
- **`ml_models/legacy_baseline_configs.json` is the paper-spec source of
  truth.** Any edit here must cite the corresponding paper source (train.py
  line, network.py class, or paper section). Do not tune these values away
  from paper spec without a written justification in the commit message.
- **RLIMIT_AS for inference subprocess = 60 GiB**
  (`core/sandbox_executor.py:_ROLE_DEFAULT_RSS_GB["inference"] = 60`).
  Training uses 40 GiB, scoring uses 24 GiB. The inference bump (commit
  `4acb5b5`) is required for full-scope baseline inference on RTX 5090 — CUDA
  static VA is ~18-20 GiB, plus ~7.4 GiB numpy peak per-file (four ~1.86 GiB
  int8 arrays at `inference_single.py:325-331`), plus caching-allocator
  overhead. Do not lower this back to 40 without re-verifying full-scope
  baseline inference passes.
- **Focal loss implementation** (`ml_models/loss_models_sandbox.py:135-168`)
  is line-for-line identical to TIDMAD's `network.py:FocalLoss1D`. If you
  change the loss math, verify against the paper implementation first.
- **DataScope (partial-file runs) is enforced in layers — never by prompts.**
  `DataScope` (`execute_tools/dataset_config.py`) restricts a run to a file
  subset (`--data_scope 4-9` or `4,5,6,7,8,9`). Enforcement: constructive
  (`build_sample_set(scope=)`), boundary (`validate_sample_set` at the
  sandbox before ALL file I/O — train/inference/`score_vector`; violations
  terminate the run, non-retryable), and direct-access
  (`health_gate_files` ⊆ scope validated at startup). Under a partial
  scope only `snapshot` sampling is legal: operator config errors at
  startup; LLM plans are normalized with recorded provenance. **Aggregate
  scalars are only comparable within one scope** — the resolved scope +
  `health_gate_enabled` + effective-config sha256 are pinned per workspace
  by `{workspace}/run_invariants_lock.json` (`core/run_invariants.py`);
  mismatched resumes/seeds/reuse fail at startup. Default (no scope) is
  behaviorally identical to pre-feature runs. See
  `docs/design/enable_partial_file_list.md`.

## Reference Project Guidelines

- You have read access to `legacy_repo`: `/home/tidmad/TIDMAD`.
- **CRITICAL**: The legacy project is unoptimized and contains deprecated
  patterns.
- Do NOT replicate the legacy project's structure.
- Only reference it for specific physics formulas, paper-spec hyperparameters,
  or data-loading logic as requested. Don't go beyond the required file or
  module.
- Prioritize modern, PEP 8, and modular standards for SIDERIUS.

## Current State (as of 2026-07-23)

*Ephemeral section — update as work progresses.*

- **Generic Framework Upgrade (2026-08-15)**: Steps 00-06 COMPLETE and merged
  (Step 06 metric interface: PR #213, `02f382eb`). Roadmap
  `docs/design/siderius_generic_framework_upgrade.md` §15.1 is the status
  authority; its §22 (Rev 5.1, architecture accepted, NOT yet frozen) is the
  top-level guidance for Step 07 onward. Persistent tracks SELECTED:
  Track B = Oxford-IIIT Pet 37-way RGB classification, Track C = DAVIS 2017
  RGB 8→4 future-frame prediction (§22.9a); D14 = dedicated milestone after
  Step 07; Step 07 = PR0 (persistent example baseline: `examples/`
  roots + identity manifests) · 07a history/diagnosis · 07b policy (Gate 1)
  · 07c measurement. **Rev 5.3 FROZEN (Q4, operator 2026-08-15)**; Step-07
  parent (`step_07_tuner_policy_and_training_diagnostics.md`, rev 2)
  FROZEN and its PR0 detailed design FROZEN (operator, 2026-08-15);
  PR0 implementation not yet started (fresh Implementation Working Rules
  contract required).

- **Active branch**: `feat/rt1-fixed-step-overhead` — runtime-control
  system, RT1 → RT6 COMPLETE per
  `docs/design/runtime_estimation_and_watchdog.md` (§0 tracker; §12
  per-stage evidence): exact workload resolvers, P/M/A data model,
  in-subprocess setup measurement + adaptive training/inference
  verification (verification = the first production steps), append-only
  observation store + priors, contribution-based total eligibility
  (`historical_phase_share_limit`), tuner admission wiring
  (in-subprocess rejection consumes an attempt), §3 trigger policy,
  §4 watchdog (process-group deadline kill, disabled by default), §5
  guardrails, and the full chain/CLI operator surface
  (`--max_steps_per_attempt --min_formal_batch_size
  --allow_extreme_steps --runtime_watchdog`). Pending: pre-Gate full
  test sweep, then operator-approved Gate 1 (real LLM + pseudo) and
  Gate 2 (real training incl. the incident pathological case). A
  parallel session is committing scoring work on this branch
  (`d0aa0b6`, `cb8b857`, `82b40e9`).
- **Previous feature**: `feat/enable-partial-file-list` — DataScope
  DS1-DS8 complete; DS Gates 1 & 2 + PR still pending.
- **Master CI**: red at `9e503ea` (PR #127 merged over a stale shell-parity
  expectation); fixed by `a84203a` on this branch — lands with the PR.
- **Open issues**: carry-forward #91, #93, #94, #95, #97, #100, plus the
  PR #101 follow-ups still open (#103, #105, #107, #110, #111, #113) and
  the DS8-filed issues (FU-1 peek-vs-eval-coverage latent bug, FU-7
  vocab-accumulation NoneType test defect — see the design doc's
  follow-up tracker).
