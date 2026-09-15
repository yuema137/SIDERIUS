# SIDERIUS Project Rules

README files are human-facing landing pages: lead with purpose, the shortest
safe route, effects, and links to deeper documentation. Detailed coding-agent
contracts belong in non-README documents (such as `docs/agent-reference/` or
node contract pages), so do not describe a README itself as an agent
instruction surface.

## Context
- SIDERIUS is a task-generic closed-loop research framework for supervised
  scientific machine learning. Its agent loop surrounds a deterministic core
  that owns execution, scoring, validity checks, and provenance.
- Real scientific tasks and campaigns are external consumers. A task declares
  its data, metric, objective, Health checks, prompt guidance, and plugins in
  its own composition manifest and workspace. Framework source must not select
  TIDMAD or any other scientific task implicitly.
- The shipped Quickstart and synthetic examples are framework specifications,
  not scientific defaults, benchmarks, or campaign templates.
- During the active repository-separation work, after any conversation
  compaction, reread
  `docs/design/framework_experiment_repository_separation.md` for separation
  history before taking another task action. Current P0 decisions, ownership,
  validation and unresolved findings belong in the P0 work plan linked below;
  do not maintain a second active P0 ledger in that historical document.

## Planning documents

- New planning efforts follow structured-coding v0.1.2's default:
  `.structured-coding/plans/<effort>/`. Keep the overall plan, step/PR design
  and any handoff together, with one authority per plan; do not put new plans
  at the repository root or in `docs/plan/`.
- **Local only (operator ruling, 2026-09-10):** `.structured-coding/` must
  remain ignored and untracked. Never commit, push or force-add its contents.
  This overrides upstream guidance suggesting plans be committed. Keep local
  plans intact when removing them from the Git index. A fresh clone will not
  contain them: obtain the applicable plan from the operator before resuming
  its work, rather than inventing its scope or approval. Public user-facing
  documentation still belongs in the tracked README/docs tree.
- Current P0 scope and progress start at
  the local `.structured-coding/plans/infra-exp-p0/overall.md` (not shipped).
  Existing `docs/design/` records remain historical evidence, not the active
  P0 ledger. After compaction during P0, reread the overview and its linked
  work plan before continuing.
- Markdown is authoritative; update any corresponding HTML rendering only
  after the Markdown. This convention does not install hooks or authorize
  later development or scientific experiments.
- Every new or updated active step document (including a combined step/PR
  design) has a same-directory Chinese reading mirror: `step-name_zh.md`
  beside `step-name.md`. The English document remains the sole implementation
  ground truth; the mirror is for operator review, not a second plan or ledger.
  Update English first, then synchronize Chinese in the same change. Preserve
  scope, decisions, checkboxes, acceptance, evidence, limitations and commands;
  never introduce approval, requirements or completion claims in translation.
- Use the [DongbeiGPT explanation approach](https://github.com/yuema137/DongbeiGPT)
  for these explicitly requested mirrors: concrete actions, causal explanations
  and restrained Dongbei rhythm, with exact technical identifiers retained.
  Each mirror links its English source and records its source SHA-256 and sync
  date. A mismatch means stale: consult English and resync before presenting it
  as current. Existing archived plans need not be bulk-translated.

## Environment
- **Every checkout owns one frozen virtualenv.** From the exact SIDERIUS
  checkout that will be tested or executed, run
  `uv sync --group dev --frozen`, then use that checkout's
  `.venv/bin/python` for every Python command. This is the shared environment
  rule for local tests, hardware qualification, and formal campaigns.
- **Never borrow another checkout's environment.** Do not copy or reuse a
  different checkout's `.venv`, editable install, `site-packages`, or source
  path through `PYTHONPATH`. Those shortcuts can import code from a different
  revision while reporting the current checkout's Git SHA. The system
  `python` / `python3` is also unsupported.
- A container image may be used by a deployment, but it must be built from
  the same committed `uv.lock` and execute the selected checkout/package
  revisions. A container is an isolation mechanism, not a second dependency
  authority. Datasets, workspaces, and machine-owned secrets remain external
  mounts or runtime inputs.
- **Scientific baseline comparison is external.** The former
  `scripts/run_comparison.py` now belongs to siderius-exp at
  `tasks/tidmad/tools/run_comparison.py`. Do not invoke the retired path from
  this checkout or restore a scientific default to make it work.
- **Generic chain dry-run**:
  ```bash
  bash scripts/launch/run_chain.sh \
      --mode lilab \
      --workspace /path/to/workspace \
      --run_name quickstart_v1 \
      --task_composition configs/task_composition/quickstart.yaml \
      --data_dir /path/to/workspace/quickstart_data \
      --num_iterations 1 \
      --max_rounds 1 \
      --dry-run
  ```
  Real task manifests, data, workflow settings, and campaign launchers belong
  in the consumer repository. They call the same framework entrypoint without
  modifying this checkout.

- **Credentials at every real launch**: Offline installation, tests and
  `--dry-run` need no API key. Before each effectful experiment, use a trusted
  machine-owned external credential file (mode `600`) or managed secret
  injection, and perform the name-only presence check in the same shell/process
  that launches the run. Require only keys for enabled providers; the current
  bridge names `OPENAI_API_KEY`, `GEMINI_API_KEY` and `DEEPSEEK_API_KEY`.
  Never commit, upload, log or shell-trace values. Follow the complete
  [installation procedure](docs/getting-started/installation.md#api-keys).
  Existing dotenv loading is compatibility behavior, not a per-launch
  binding guarantee; no runtime helper or hook is implied.

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

- **Maintainability without critical-path drift (binding, operator decision
  2026-08-31)**: clarity, local testability, and explicit data flow are part
  of correctness. Prefer the simplest implementation that preserves the
  required boundary: simple, then explicit, modular, testable, and extensible.
  Do not introduce abstraction, inheritance, dispatch machinery, or special
  cases for hypothetical consumers. Use composition and small typed
  interfaces where behavior genuinely varies by task, backend, or provider.

  Size is a review signal, not a mechanical splitting rule. A cohesive
  function below roughly 100 lines is normally unremarkable; 100--200 lines
  warrants a responsibility check; above 300 lines creates a strong
  presumption for decomposition; and ordinary handwritten functions above
  500 lines require a compelling documented reason. Cohesive modules below
  roughly 1,000 lines are normally acceptable; 1,000--2,000 lines warrant
  review; above 2,000 lines is a strong modularization candidate; and ordinary
  handwritten modules above 3,000 lines require a compelling architectural
  reason. Generated, vendored, schema-generated, and static-data files are
  exceptions. Extract real responsibilities, never meaningless numbered
  helpers.

  Keep control flow shallow through guard clauses, focused policy functions,
  and typed adapters. Nesting beyond three levels, long conditional chains,
  or cyclomatic complexity above 10 should trigger review; complexity above
  15 is a strong refactoring candidate unless the domain logic is inherently
  branch-heavy. Comments explain scientific invariants, policy reasons, and
  compatibility constraints; they do not compensate for tangled code.

  Preserve public APIs, CLIs, configuration contracts, serialization formats,
  and task/plugin interfaces during internal refactoring. Tests follow the
  real boundary: pure policy tests, contract tests, bounded component tests,
  and only the end-to-end tests that require the complete chain. Before a
  non-trivial commit, ask whether the same behavior can be expressed more
  simply, whether a special case or speculative abstraction was added, and
  whether another implementation could be added without editing unrelated
  branches.

  These rules are preventive, not authorization for a repository-wide cleanup.
  The active priority is clean campaign readiness and completion of the
  framework/experiment separation. Refactor only when the current change would
  worsen an unhealthy boundary, the existing structure makes the repair
  unsafe, or nearby duplication and special cases are accumulating. Keep such
  refactors bounded, behavior-preserving, and separately validated.

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
  training) must be **cold-start** — do NOT pass `--seed_paths`. Rationale,
  the twin DS8 partial-scope rule (paired `--data_scope` +
  `--health_gate_files`), and the **cold-start checklist** (which state is
  cleared vs retained, in order: workspace, seeds, `agent_generated`
  models + capability index, workspace plugins, root-papers cache,
  calibration store, advice file) live in
  `docs/gates/gate_testing_standard.md` "Partial-scope rules" section. The
  pre-DS8 canonical seed paths still listed there are historical reference
  only. Exception: reproducing a specific historical seeded run —
  operator-approved case-by-case only.
- **Node/skill doc sync before merge (operator rule, 2026-07-28)**:
  every PR that updates a node or a skill must update the relevant
  `.md` (the node's `src/nodes/{node}/{node}.md`, the skill's doc, and any
  operator-surface doc such as `docs/reference/entrypoints.md` or
  `docs/guides/operating-a-run.md`) so CLI
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
  (`scripts/pr3_l2_calibration/preflight.py`, the `subprocess.run(["git",
  "diff", "--name-only"], …)` call feeding the
  `checks["no_production_file_modified"]` assignment) and fails when **any**
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

- **Validation economy: ONE expensive full CI per final head (binding,
  operator decision 2026-08-18)**. The same failure class must not be
  validated three times — a local chunked suite, a manual
  `workflow_dispatch`, and then the formal PR's automatic run is waste,
  not rigour.

  | validation | default |
  |---|---|
  | local full unit suite | **DO NOT RUN** |
  | manual `workflow_dispatch` full CI | **DO NOT RUN** |
  | formal PR automatic CI | **the CANONICAL exact-head evidence** |

  **Splitting the suite into several local "chunks" is still running the
  full suite** and is not a workaround. During implementation run only:
  the targeted tests for the changed authority, targeted static checks,
  the relevant structural guards, and a bounded Gate when its failure
  class is affected — then ledger, commit, continue.

  **At the intended final head**: finalize code + docs → open (or
  retarget) the formal master-targeting PR → its automatic CI runs on the
  merge-candidate SHA → **operator review happens in parallel with that
  run** → green + no review changes ⇒ merge; a review change moves the
  head and CI re-runs itself.

  **Stacked milestones**: child PRs are the REVIEW decomposition, not the
  CI decomposition — targeted validation + Gate evidence per child, and
  **one** full CI on the final integrated stack head. Review granularity
  and CI granularity are different concepts.

  **Manual dispatch is exceptional**, allowed only when automatic PR CI
  cannot be triggered, the evidence is genuinely needed before a formal PR
  can exist, AND no identical run will immediately follow. Ask first:
  *"will the normal PR workflow run substantially the same suite on this
  SHA shortly anyway?"* — if yes, do not dispatch.

  **Gates are NOT duplicate CI.** Gate 2 owns real data / GPU / training /
  validation / inference / scoring; unit+CI own deterministic repository
  correctness. They are complementary — never drop a real Gate because CI
  exists.

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
| 1 | Node implementation | `src/nodes/{node_name}/{node_name}.py` (one directory per node) |
| 2 | Protocol(s) for each edge this node participates in | `src/agent/schemas/protocols/{source}_to_{target}.py` |
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
| `data_` | Data processing / analysis | `data_analysis_agent` (built: caller-independent typed input/report, authorized materialization, pluggable reference skills, and caller-injected historical-model inference) |

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
default. See `tests/pseudo_data/README.md` for the fixtures and
`docs/architecture.md` ("Pseudo-full-loop tests") for the design — the
original `docs/pseudo_test_infra.md` note was removed in the 2026-08-10 docs
sweep (`6bc1f536`).

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

**Current naming convention**: `src/agent/skills/` holds atomic tools (training,
inference, etc.) used internally by agents. The earlier `agent/tools/` rename
was a proposal, not a landed path or a current instruction. P0 preserves
`src/agent/skills/`; see `docs/architecture.md` for the conceptual design.

## HealthGate System (Pluggable Health Checks)

SIDERIUS uses a rev-6 **HealthGate** system to catch model failures during
tuning without polluting the scoring pipeline. Migration landed in PR #101
(commits 1-6).

- **Config (Step 08b, 2026-08-18 — split by OWNER)**:
  `src/execute_tools/health_checks/resources/health_checks.yaml` carries
  the packaged generic default, FRAMEWORK POLICY ONLY — a
  `health_policy` block mapping each disposition (`blocking` / `recording`)
  to gate role, cadence, short-circuit, `on_pass`/`on_fail` and per-check
  policy keys such as `aggregation`. It must NEVER carry a task identity,
  roster, threshold, peek set or science prose. An external task supplies its
  own Health declaration and plugins from its task package and needs no
  SIDERIUS edit. The two inputs compose
  deterministically into the same pinned
  `{workspace}/health_checks_effective.yaml`, and
  `load_health_gates_config()` returns that COMPOSED result. To change a
  THRESHOLD edit the task config; to change what a failure DOES edit the
  framework policy. Two things are run-level INPUTS, not YAML
  (DataScope feature, DS4-DS6): `health_gate_enabled` (subsystem switch)
  and `health_gate_files` (shared monitored-file list overriding every
  check's `peek_file_indices`). At startup the run materializes the
  EFFECTIVE config to `{workspace}/health_checks_effective.yaml` (sha256
  pinned by the run-invariants lock) and every path-based loader reads
  that file — never override the config in memory.
- **Skills**: `src/execute_tools/health_checks/` — each check is a
  `HealthCheckSkill` conforming to
  `run(ctx, config, *, view=None) -> HealthCheckResult`. A check that does
  not require a view is invoked as `run(ctx, config)` exactly as before;
  only a view-consuming check receives `view=`. **The `__init__` import list
  is the built-ins' bootstrap, NOT the extension path** (Step 08b): an
  external task names plugin files in its own task health config, and they
  register through the same public `register` / `register_view_provider`.
- **Gate actions**: `CONTINUE`, `INVALIDATE_ROUND`. Severity resolution
  when multiple gates fire in one round:
  `INVALIDATE_ROUND > CONTINUE`. (`SKIP_TO_FORMAL` / `SKIP_ITER` were
  RETIRED from the vocabulary — F-SCANC-1, operator decision packet v1,
  2026-08-26: the C7 decomposition had severed the tuner-side carrier,
  so they were declared-but-unreachable loop control; a config declaring
  either now refuses at validation. Gate actions classify the round;
  they carry no loop control.)
- **Firing point**: gates fire at **tuner round boundaries** in
  `src/nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`, NOT
  inside `score_vector`.
- **Design doc**: `docs/design/pluggable_health_checks.md`.

## Subsystem Invariants (Read Before Touching)

- **`score_vector` is pure scoring** (2-tuple return: `(file_vector, scalar)`)
  after the commit-5a refactor. It does NOT return `is_degenerate` or
  `failure_reason`. Never call `score_vector` expecting health-check results —
  use HealthGates in the tuner instead. Any downstream consumer that reads
  `is_degenerate` / `failure_reason` from a merged score record should use
  `.get(default)` (these keys are no longer produced by score_vector, though
  `StubSandbox` still injects them for pseudo-mode compatibility).
- **Production scoring goes THROUGH the evaluation-metric handle (Step 06,
  2026-08)** — `src/execute_tools/evaluation_metric.py`. The tuner binds
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
  the id. Losses are NOT metrics — but that boundary is TYPED, not lexical: since Step 12 / PR-12a C5 closed D16, **`MetricSpec.id` is an OPAQUE identity** and `log_loss` is as declarable as `accuracy`. What enforces the boundary is the contract (a deliverable, an aggregation, an executable `ScoreabilityContract`), `_compose_metric`'s `EvaluationMetric` type check, and `extra="forbid"` plus zero loss-named fields on the record-facing types.
  Records carry the additive `metric_result` / `metric_refusal`; the frozen
  `denoising_score` / `file_vector` / `score_table` names are unchanged (D1).
- **RLIMIT_AS for inference subprocess = 60 GiB**
  (`src/core/sandbox_executor.py:_ROLE_DEFAULT_RSS_GB["inference"] = 60`).
  Training uses 40 GiB, scoring uses 24 GiB. The inference bump (commit
  `4acb5b5`) is required for full-scope baseline inference on RTX 5090 — CUDA
  static VA is ~18-20 GiB, plus ~7.4 GiB numpy peak per-file (four ~1.86 GiB
  int8 arrays — the `np.zeros((dim1, input_size), dtype=_storage_dtype)`
  `denoised`/`injected` pairs in `src/execute_tools/inference_single.py`), plus
  the transient `.flatten().astype(int8)` copies `create_abra_file` emits,
  plus caching-allocator
  overhead. Do not lower this back to 40 without re-verifying full-scope
  baseline inference passes.
- **Focal loss implementation** (`src/ml_models/loss_models_sandbox.py`, class
  `FocalLoss1D`)
  is line-for-line identical to TIDMAD's `network.py:FocalLoss1D`. If you
  change the loss math, verify against the paper implementation first.
- **DataScope (partial-file runs) is enforced in layers — never by prompts.**
  `DataScope` (`src/execute_tools/dataset_config.py`) restricts a run to a file
  subset (`--data_scope 4-9` or `4,5,6,7,8,9`). Enforcement: constructive
  (`build_sample_set(scope=)`), boundary (`validate_sample_set` at the
  sandbox before ALL file I/O — train/inference/`score_vector`; violations
  terminate the run, non-retryable), and direct-access
  (`health_gate_files` ⊆ scope validated at startup). Under a partial
  scope only `snapshot` sampling is legal: operator config errors at
  startup; LLM plans are normalized with recorded provenance. **Aggregate
  scalars are only comparable within one scope** — the resolved scope +
  `health_gate_enabled` + effective-config sha256 are pinned per workspace
  by `{workspace}/run_invariants_lock.json` (`src/core/run_invariants.py`);
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

## Historical state records (original heading: Current State, 2026-07-23)

The dated entries below preserve incident evidence and decisions at their named
revisions. Their `NEXT`, active-branch, pending-work, shipped-path and capability
statements are historical, not current execution instructions. Preserve the
recorded invariants and incident evidence; verify present capability from source
and Git before acting on an old status. This bounded correction does not claim
that every historical passage or subsystem description has been re-audited.

Current P0 scope and progress: local `.structured-coding/plans/infra-exp-p0/overall.md`
and its linked work plan. Current source/navigation audit:
[repository map](docs/repository-map.md). In particular, real task packages now
live in exp, and the current tuner reaches the composed Health phase; the old
PR-12d zero-Health statement below records that earlier revision.

- **STEP 12 / PR-12d — COMPLETE / MERGED (2026-08-24)**: PR #274, squash
  **`84d74280`**; exact-head CI SUCCESS (12,941 passed / 48 skipped / 0
  failed). **Pets and DAVIS reach L4** — the composed production chain ran
  both end to end (`G-12d`, persisted PASS records in the design ledger
  D-12d-62: Pets `accuracy` 0.0946 higher + `macro_f1`/`log_loss`; DAVIS
  `mse` 0.01607 LOWER + `psnr`/`mae`, objective `custom/davis_exact_l1`
  overriding the planner's `smooth_l1` — the task's declaration is
  authoritative, F-12d-31). Both packs' `STATUS.md` promoted to **L4** at
  D-FINAL. Manifest vocabulary grew: `model_plugins:` / `loss_plugins:` /
  `objective` + task-instance `config:` with `{ref:}` envelopes; unknown
  SECTION-level keys are now refused (`_refuse_unknown_section_keys` — at
  the old base they were silently dropped); seam P unions pack plugin dirs
  into every child; scope transport reaches all three children; seam E
  narrowed `DeliverableNaming` to an indexed capability. **TIDMAD §J
  witness: row 3 PROVEN; rows 4/5 `DEFERRED_TO_C12P`** (operator acceptance
  exception — a pre-existing `run_comparison.py --data_dir` transport gap,
  not PR-12d's). **Declared debt future work must not re-break or forget**:
  composed runs fire ZERO HealthGates (ledger A1 — 08c's D14-runner
  evidence stands, never restate it as composed-path); false
  `tidmad_denoise` calibration provenance from composed runs (A4);
  the tuner planner's prompt still names built-ins unconditionally (A2/A3
  debt). Design + evidence:
  `generic_framework_upgrade/step_12_external_extensibility_graduation/pr_12d_contrast_subprocess_closure.md`
  §A / §Q (D-12d-62 the PASS records, D-12d-63 the closeout). **NEXT =
  PR-12e** (out-of-tree graduation) per the frozen T5 topology, plus the
  landed arXiv-readiness integration (issues #253–#268) tracked in its own
  lane.
- **STEP 12 / PR-12bc — COMPLETE / MERGED (2026-08-23)**: PR #249, squash
  `42d79b9d`; final executable head `486ea47f`, final PR head `06103e9a`
  (delta **docs-only**), authoritative exact-head CI **32657760919 SUCCESS**
  with **no commit after it**; landed master **byte-identical** to the
  validated head. **`G-12bc-B` PASS** (`8fd80cdc`, re-run PASS at `486ea47f`)
  and **`G-12bc-C` PASS** (`2ad868e3`, re-run PASS at `486ea47f`).
  **CAP-SCOPE IS CLOSED.** A task now declares an **OPTIONAL SIBLING**
  `TaskScopeCapability` — the frozen four-method `TaskDataPath` is
  **unchanged** — and builds its own training/eval scopes; they cross the
  process boundary as an **artifact + sha256 verified BEFORE deserialization**
  (raw scope JSON never goes on argv), written atomically by the parent.
  `DatasetProfile` splits into **generic identity** (`partition_count`,
  `anchor_selection_files`, `health_peek_files`) plus an **opaque `topology`**
  the framework carries and never interprets (Q-12-4); the legacy wire form is
  still accepted and emitted. The **pairing gap** is closed — the binding used
  to cross while the scope did not, so a composed child fell into its regime-A
  `TidmadScope` branch that a non-TIDMAD implementation then refused.
  Registration-order **CASE A is CLOSED** through production lifecycle
  semantics only (a two-phase rule: same id + same content ⇒ idempotent, same
  id + different content ⇒ refuse; plus a run-scoped registration overlay) —
  no pytest-order hack, no test-specific reset, no weakened reproducer. The
  parent **pins a per-family content identity** the child verifies **before
  consuming** (a registry HIT is never identity proof), and **a child can
  resolve a task the framework has never heard of** by composing the
  transported manifest through the SAME authority the parent used — the
  manifest now reaches all three children, not only scoring.
  **Things future work must not re-break**: the transported identity is the
  value **CAPTURED at registration**, never a fresh read of the plugin file
  (**F-12bc-7**) · row 2 (divergent identity) is not row 4 (miss), so the
  child's MISS must stay a **membership test** and never an exception to catch,
  or C2's refusal silently becomes a fallback · the §F item-9 census scopes now
  include `execute_tools/`, where the scope ABI lives (**F-12bc-9**) ·
  `_task_manifest_argv()` is emitted at all three spawn sites but still **only
  when bound**, so legacy argv is unchanged.
  **Why the two lightweight real Gates were worth keeping.** `G-12bc-C`
  **FAILED on its first launch** and found **F-12bc-7**: `content_identity()`
  hashes the source FILE, so `transport_argv` re-derived the "parent-pinned"
  identity at SPAWN time from whatever was on disk — the pin followed the very
  edit it exists to catch, and a tampered plugin was loaded AND consumed.
  Every deterministic identity test was green because each held
  `content_identity(impl)` as a **string** across the edit: *the test pinned a
  value where production pinned a function call.* **A test that captures what
  production recomputes cannot see a recomputation defect.** CI's pyright found
  **F-12bc-10** — three sites reaching for optional-sibling methods off the base
  `TaskDataPath`, i.e. the type system enforcing this PR's own architecture on
  paths no test could reach. Two **census** defects: **F-12bc-6** (a flip
  detector that named a SYMBOL and stayed green through the landing it was
  written to announce) and **F-12bc-9** (a census whose FILE SET omitted the
  scope ABI's directory — self-evidencing, since its own exemption list could
  never fire). **F-12bc-8 is NOT a census defect** — it is a **test-isolation /
  import-registration lifetime** defect (a built-in imported under a blanked
  registry never registers again), surfaced by the regression suite AFTER CASE
  A had already been closed independently, and never a means of closing it.
  **§G plant matrix 9/9 RED** against named owners; **§J** max **+2** branch
  nodes against a +3 budget with **zero parameter growth**. Design + evidence:
  `generic_framework_upgrade/step_12_external_extensibility_graduation/pr_12bc_generic_task_boundary_closure.md`
  §A (terminal facts) and §Q (per-checkpoint). **NEXT = PR-12d** (Pets + DAVIS
  real contrast execution closure) — CAP-SCOPE was its frozen prerequisite and
  is now discharged — to be planned in a FRESH session from merged state, never
  from the conversation that produced PR-12bc.
- **STEP 12 / PR-12a — COMPLETE / MERGED (2026-08-23)**: PR #248, squash
  `15554174`; final executable head `ec30bd65` (where G-12a-2 ran), final PR
  head `d4bf899d`, exact-head CI **32615196536 SUCCESS**; local master
  byte-identical to `origin/master`. **A composed run resolves ZERO implicit
  TIDMAD semantics in the surfaces 12a owns** — pre-flight scope topology,
  per-model lock identity, health materialization and deliverable naming as
  VALUES; planner / reflector / proposer / implementor as PROMPT SCIENCE.
  Legacy un-composed bytes are proved identical against RECORDED pre-C7
  digests, not against themselves. **Gate 1 PASS** (with no declared blocks a
  real model answered *"No domain was stated."* rather than inventing TIDMAD's
  science) and **Gate 2 PASS** (A1/A2/A3; three per-model locks carrying
  `task_composition_fingerprint 9125bf58…` and the chain's own
  `health_config_sha256` — **F-P56-3 closed with a live witness**).
  **Things future work must not re-break**: the shipped TIDMAD manifest now
  DECLARES `proposal_blocks:` and `implementor_blocks:`, so its composition
  fingerprint moved `d6628a93…` → `9125bf58…` and **a composed workspace
  started before this PR fails its resume CLOSED — intended, and no
  compatibility bypass may be added**; `MetricSpec.id` is OPAQUE (D16/C5, the
  lexical `_is_loss_shaped` rule is gone); and **F-12a-G2** — a COMPLETED
  resource probe may never be discarded for elapsed wall time, because
  `memory feasibility != calibration completeness != host wall time !=
  watchdog timeout` (the check ran AFTER the probe returned, so it guarded
  nothing and made capacity depend on host load). **Gate-2 honesty**: attempt
  4 is canonical, and the chain was NOT uninterrupted — a provider hang forced
  a kill and a resume at iteration 2 in the same workspace; no provider-hang
  robustness may be inferred. A **BOUNDED TERMINAL-EQUIVALENCE EXCEPTION** was
  granted for the final delta (not literally docs-only; accepted on proven
  execution-inertness) and is **explicitly not a generic relaxation** of the
  Step-12 terminal rule. **Carried debt, none solved**: Q-07c-6 ·
  registration-order CASE A · F-12a-G2b (usable VRAM cap derives from TOTAL,
  not free) · partial-calibration acceptance + a true probe watchdog ·
  CAP-SCOPE · external child loading · Pets/DAVIS L4 · fourth-task
  graduation. Parent gained **§14a** (Gate count by failure class, Gate cost
  by earliest sufficient witness). **NEXT = PR-12bc, owned by the isolated
  Step-12 planning session**, which must re-anchor against LANDED source per
  §11.1 before freezing — never from an implementation session.

- **STEP 11 — COMPLETE / MERGED (2026-08-22)**: PR #247, squash `da2aa705`;
  final executable head `88f190a1` with exact-head CI **32562135614 SUCCESS**
  and **Gate 2 PASS on that same SHA**; final PR head `fd6bfccb`, CI
  **32563043661 SUCCESS**, delta docs-only; landed master byte-identical to
  the validated head. **The execution infrastructure is task-neutral wherever
  a resolved framework binding already has a transport authority.** Three
  values that made the spawn surface TIDMAD-only now cross it: the physical
  data root reached **no** child (all three fell back to the import-time
  `TIDMAD_DATA_DIR`) and is transported when composed — **`--data_dir` for
  training/inference, `--raw_data_dir` for scoring**, whose `--data_dir` is
  the DELIVERABLE dir and must never be conflated; the scoring child composes
  the run's DECLARED metric through the same Step-10 authority with **no
  fallback** (a failed composition terminates the subprocess — silently
  scoring with TIDMAD's metric is C-P56-1 one layer down); and deliverable
  naming is declared by the task, validated by `DeliverableNaming`, which
  stays the sole owner. Transport is emitted **only when bound**, so legacy
  argv is unchanged. Ceilings became declared calibration with provenance in
  `core/execution_calibration.py` — two layers only, `0` still disables, a
  malformed override REFUSES loudly, and the lock RECORDS them without ever
  comparing them (`RunInvariants._PROVENANCE` partitions with `_CANONICAL`).
  **Things future work must not re-break**: the `active_*` vs `resolve_*`
  split on every run-scoped binding — the transport must ask the one WITHOUT
  the legacy fallback, or every un-composed child's argv changes; the record
  AND output composition stamps must read ONE run-scoped authority (a real
  Gate caught them disagreeing — see below); `DeliverableNaming` needs
  `extra="forbid"` because a misspelled declaration key otherwise yields the
  shipped TIDMAD template and a cleanup glob that deletes files the run never
  wrote; and `_ROLE_DEFAULT_RSS_GB` resolves 40/60/24 with the inference value
  marked `empirical_unverified` — **lowering it without re-verifying
  full-scope baseline inference is a regression**. **Operator rulings**:
  **R-11-13** (R-11-1's "argv byte-identical" was literally false after C7's
  frozen absolute script anchoring; wording corrected, code NOT reverted) and
  **R-11-14** (C8's additive `task_composition_fingerprint` stamp RATIFIED —
  R-11-9 was unsatisfiable as written because nothing carried a fingerprint;
  implementation PASS, and the process deviation is recorded: a schema
  expansion is not ordinary implementation discretion). **Gate 2 earned its
  keep** — run 1 INCONCLUSIVE (RT4 watchdog at deadline + ~1 s; cause is
  **Q-07c-6 = B**, admission prices `phase="training"` only, still OPEN and
  NOT Step 11's; shrinking capacity shrinks the deadline so it cannot
  converge), run 2 caught **F-11-C10-a** (the OUTPUT stamp read the tuner's
  own sub-workspace lock and resolved to `None`, so a composed **2-iteration**
  chain would have refused its own iteration-1 output — invisible to every
  unit test), run 3 PASS. **Structural: zero branch growth and zero parameter
  growth** in all four baselined `sandbox_executor.py` functions.
  **NOT claimed**: task-scope construction/rehydration or any scope registry
  (**R-11-12 → CAP-SCOPE**), real contrast-task subprocess L4, out-of-tree
  plugin availability in children, removal of the import-time `data_paths`
  fallback. **Carried debt for the Step-12 audit**: CAP-SCOPE · out-of-tree
  child bootstrap · F-P56-3 (tuner sub-lock, now consumer-less) · the 60-GiB
  recalibration · the legacy scoring path that never reads `score_res`
  status · Q-07c-6 · two timing-sensitive real-training "unit" tests.
  Design + evidence:
  `generic_framework_upgrade/step_11_execution_infrastructure.md` §11a–§11e.
  **NEXT = Step 12**, to be planned in a FRESH session from merged state,
  never from the conversation that produced Step 11.

- **STEP 10 — COMPLETE (2026-08-21). ALL 7 semantic children MERGED: P1
  `bcb17e45` · P4 `79833db8` · P2a `e094fa26` · P2b `5a2ecfd1` ·
  P3 `254cbaa1` · **P5+P6 `b54623b2`** (PR #246, squash; exact-head CI
  **32532482260 SUCCESS** on `8450fd27`; merged master byte-identical to
  the validated head apart from three node/operator `.md` files).**

  **P5+P6 — Lifecycle Closure + Three-Task Orchestration Closure.** Two
  values the chain produced and then threw away now survive a REAL process
  restart, and the composed production path executed for the first time.
  `vocab_link_confirmations` (latest-wins on the WHOLE dict; a key-less
  digest is SKIPPED, not a reset; malformed RAISES per Q-P5-1) and
  `accumulated_key_findings` (chronological union) became `ChainState`
  fields carried through `run_workflow`'s closures. Before this both
  fields existed on the schemas while NOTHING transported them, so
  promotion (`min_runs=3`) was unreachable in any real chain.
  `run_chain.sh` gained `--task_composition` (the operator's chain could
  not launch a composed run at all) and `configs/task_composition/tidmad.yaml`
  ships as the first real manifest. **C-P56-1 held**: no implicit legacy
  TIDMAD reference science reaches a composed run, the guard keying on
  composition PRESENCE — observed live in production prompts.
  **Things future work must not re-break**: the findings-union rule has
  ONE authority (`core.resume.union_key_findings`) that BOTH the digest
  projection and the loop closure CALL — a mutation-proven structural
  guard enforces it, because the differential test that used to guard it
  PASSES when the rule is re-inlined; and the sidecar
  `accumulated_findings_*.json` is a LOG, never the transport channel.
  **Gate-2 governance corrections promoted to the canonical standard**: a
  Gate tests the CHANGED failure class and never acquires acceptance
  criteria by proximity (model quality, HealthGate PASS and convergence
  are NOT implicit criteria); and **semantic latency sets the minimum
  depth** — the frozen "2 iterations" was UNSATISFIABLE under cold start,
  because a seeded unit test proves nothing about a cold-start chain.
  **Carried debt, none blocking**: F-P56-3 (composition kwargs reach only
  the chain-level invariants lock) · **CAP-SCOPE** still gates composed
  CONTRAST runs and the five un-threaded tuner eligibility sites ·
  the tuner's ambient `active_task_data_path()` read → Step 12 ·
  auto-resume's `START_ITER` capture is corrupted by plugin-loader stdout
  (`--start_iter N` is the workaround).
  **NEXT = Step 11**, to be re-confirmed from the merged roadmap in a
  fresh session, never from the conversation that produced P5+P6.

  Historical (pre-merge) context for the consolidated child:
  Authoritative design:
  `docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/pr_10_p5_6_lifecycle_and_three_task_closure.md`
  (the old P5 draft and P6 skeleton are REMOVED, reconciled in its §18;
  open operator questions 0). **Frozen rulings**: **Q-P56-1 = B** —
  contrast-task loop TRAINING is a missing declared capability
  (task-owned scope construction: the frozen D14 seam takes CALLER-built
  scopes; the tuner builds TIDMAD `SampleSet`s unconditionally; no scope
  argv; `DatasetProfile` cannot describe Pets/DAVIS), so Step 10 closes
  at the roadmap ladder's depth, parent §16.1/§17.1/§26.O are AMENDED,
  and **CAP-SCOPE is the REQUIRED prerequisite for contrast-track L4 —
  Step 12 may not claim L4 past it** (recorded on the roadmap Step-12
  row). **Q-P5-1 = RAISE** (malformed confirmations fail closed).
  **C-P56-1** (operator catch): NO implicit legacy TIDMAD reference
  science in ANY composed run — the W4 guard keys on composition
  PRESENCE, never `TIDMAD_METRIC_ID` or any task-identity surrogate;
  legacy path byte-for-byte; composed-mode parity = the composition
  invariants only. The frozen shape: C0–C4 carried-state lifecycle
  (confirmations activation + DD-2 cold-start carry-through; findings
  onto `ChainState`; ≥ 3-iteration deterministic reachability + per-link
  severing; resume deep-equality) → C5 composed-chain operator surface +
  wiring W1–W5 → C6 three-task ORCHESTRATION closure through ONE
  `run_workflow` path (frozen orthogonal roles; DAVIS ≥ 2-iteration
  lower-is-better falsifier; C6 honesty rule: orchestration semantics
  only, never contrast L4; Pets deliberately NOT ≥ 2 iterations) → C7
  runner claims per Q-10-5 = B + the §10.6 L3-evidence freshness contract
  (provenance + dependency diff; bounded rerun only if semantics changed)
  → C8 **Gate 1 NOT REQUIRED (flip = template/schema bytes) · Gate 2
  REQUIRED = the FIRST real COMPOSED chain, exactly 2 iterations ×
  1 round, AUTONOMOUS inside the pre-authorized ≤ ~1 h envelope, with the
  non-vacuous two-layer restore evidence (findings = mandatory witness,
  no-usable-finding ⇒ MUST NOT PASS; confirmations = exact-restore
  provenance, no reachability claim when `{}`)**. The §12.1
  `run_workflow` tripwire binds implementation (sibling-shaped delta
  only; pre/post LOC + branch counts recorded).
  **P3 — Proposer Typed Evidence + Prediction Authoring — COMPLETE / MERGED
  2026-08-21**: PR #245, squash `254cbaa1`; final head `31cdabaa`,
  exact-head CI **32457848717 SUCCESS**. **The proposer has ONE declared
  interpretation contract and is told which direction is better.**
  `ProposerInterpretationEvidence` (30 carried / 12 refused-with-reasons / 2
  dead reads dropped) is built by the ONE `build_proposer_evidence(Mapping)`
  projection and consumed by BOTH entrypoints; `ProposalInput.interpretation`
  and the zero-reader `per_model_score_tables` mirror are REMOVED and the
  evidence is REQUIRED, so raw interpretation reads went **40 + 12 → 0** and a
  bypass has no input to read. Things future work must not re-break: the
  proposer must never regain a second semantic reader (a standing census with
  five plant shapes, plus the structural fact that the raw carrier is gone);
  **F-P3-1** — `clamp_comparative_analysis`'s retention draw is direction-aware
  now, and its missing-score sentinel is `order.worst_sentinel`, because `-inf`
  is "worst" only under `higher`; the P2a scanner was deliberately NOT widened
  to see that site, so its hand-computed fixtures ARE its guard; raw secondary
  metrics stay out of proposer evidence and prompts (Q-P3-3), with a DAVIS
  negative fixture proving suppression rather than absence; and D1/D2/D3 are
  the only LLM-facing deltas — the legacy path carries none of them and its
  bytes are pinned. **Gate 1 PASS after a genuine FAIL** (a real model put the
  refutation threshold on the wrong side; the persisted prompt showed the
  design's aligning sentence had never been implemented — three numbers in a
  JSON example do not teach a semantic). Gate 2 NOT REQUIRED; no training,
  inference or GPU. **Carried debt**: the typed migration stops at the
  DECLARATION boundary — `accumulated` and `candidates` are still string-keyed
  dicts, so a future evidence field travels its last hop as a dict key
  (Step 12). A second lesson worth keeping: the two dead reads survived for
  years because they HAD A TEST that fed undeclared names into a
  `dict[str, Any]` — a raw-mapping boundary lets tests certify behaviour
  production cannot reach.
  Parent `docs/design/generic_framework_upgrade/step_10_orchestration_task_binding.md`
  (REVISION 2 FROZEN) is the status authority; the roadmap's Step-10 row
  carries the per-child evidence. Step 09.5a merged first (PR #240, squash
  `2393aacc`), which is why the STEP-09 entry below still saying "NEXT =
  STEP 09.5" is history, not an instruction.
  **P2b — Secondary Metric Production Transport — COMPLETE / MERGED
  2026-08-21**: PR #244, squash `5a2ecfd1`; executable head `f6a73afd`
  (exact-head CI **32439134908 SUCCESS**), final PR head `41eeff60` (CI
  **32444963507 SUCCESS**, 11,318 passed / 33 skipped); merged master
  byte-identical to the validated head. **A task now declares OBSERVATIONAL
  secondary metrics and the whole lifecycle carries them** — an OPTIONAL
  manifest `secondary_metrics:` section resolved by the SAME `_compose_metric`
  authority (no duplicated fail-closed branch), bound on
  `bind_run_task_composition`'s existing ExitStack, evaluated by
  `_evaluate_secondary_metrics` **wherever the PRIMARY evaluates** (no
  round-type branch exists), transported on
  `ExperimentRecord.secondary_metric_{results,refusals,errors}` +
  `HyperparamTuningOutput.secondary_metric_specs` (stamped on BOTH the healthy
  and degraded output branches), projected against that declared stamp,
  carried across a quiet iteration via `_stats` (closing audit B-6
  symmetrically with `failure_counts`), and rendered by the Step-09b renderer
  **reused unchanged**. Things future work must not re-break: the per-secondary
  catch ORDER is load-bearing — `ScopeViolationError` subclasses `ValueError`,
  so it is caught FIRST and **re-raised** to the existing outer handler, and an
  ordinary crash is diagnostic provenance that projects `unavailable`, never a
  fourth scientific state; secondaries are OBSERVATIONAL and an AST census over
  the whole lifecycle keeps them out of every ordering expression; a run that
  declares none writes NO secondary record key, NO `_stats` key, renders ZERO
  bytes and keeps its composition fingerprint byte-identical (§4.7 freezes
  SEMANTIC emptiness, NOT persisted-JSON byte identity — do not build omission
  machinery for cosmetic parity). Gate 1 / Gate 2 NOT REQUIRED, neither run.
  **F-P2b-4 — carried debt**: the Step-09a evaluator census used ANCHORED
  symbol regexes and was blind to a leading underscore, so it would have
  reported "no production module evaluates a secondary metric" while one did —
  a guard green for the wrong reason. Fixed there; **the same anchored-census
  pattern may exist elsewhere and must be audited per-census when its area is
  next touched, never as a repo-wide sweep.**

- **STEP 09 — COMPLETE (2026-08-20).**
  09b merged: PR #239, squash `e9a1f9fbb1c2e882be5b017756e2552a6b9f8d7c`,
  exact-head CI **32324124087 SUCCESS** on `ce3b971d`; merged master
  byte-identical to the validated head. **The interpreter's prompts no longer
  own task science.** `InterpretationTaskBlocks` — four framework keys
  (`evidence_reading` / `per_model_guidance` / `synthesis_guidance` /
  `prediction_guidance`), task-owned prose, absent ⇒ nothing rendered — arrives
  as a CALLER-SUPPLIED value on `InterpretationInput.task_blocks`; TIDMAD's
  science moved VERBATIM into `configs/task_interpretation/tidmad.yaml` behind
  ONE bounded Regime-A adapter (`agent/prompt_templates/interpretation/task_blocks.py`)
  whose single task-identity occurrence is a default-path CONSTANT, not a
  branch — AST-guarded, and a second task constant or an `if "tidmad" in …`
  turns it RED. The whole prompt surface moved byte-exactly to
  `agent/prompt_templates/interpretation/rendering.py` (node main file 2,005 →
  1,252 lines) and now also owns explicit renderers — ONE authority per
  evidence family: metric identity, per-role `TrainingDiagnosis`, secondaries
  in their scored/refused/**named-absent** states, and `RecordFailureCounts`
  keyed only by existing authority vocabularies — reusing 07b's direction-word
  and diagnosis-line authorities rather than re-implementing them. The
  prediction track record became version-aware in BOTH consumer nodes, closing
  the declared Q-09a-3 consequence in which v2 fractions rendered over the
  frozen v1 denominator; both N's count comparable outcomes by construction.
  **Gate 1 PASS** — ONE launch, exactly 5 calls, 13/13 checks: the real model
  designated the better model in TIDMAD's negative-valued higher-is-better
  regime AND in DAVIS's lower-is-better regime, and reported the ABSENCE of
  per-file evidence instead of inventing a lever; Gate 2 not required. Three
  findings were defects in the Gate's own EVALUATION function (decimal-breaking
  sentence splitter; a fabrication probe contradicting the frozen A/B split; a
  name-only matcher mis-reading a winner referenced by score) — the verdict was
  read from the persisted artifacts re-evaluated with corrected probes, zero
  extra LLM calls. Design + ledger:
  `generic_framework_upgrade/step_09_interpretation_task_blocks/pr_09b_interpretation_prompts_task_blocks.md`
  §22 (72 `[x]` / 0 `[ ]`). **Things future work must not re-break**: the
  framework templates are census-proven task-free in BOTH directions (banned in
  the template, required in the TIDMAD-assembled prompt) — a new task-science
  sentence in `rendering.py` is RED; absent task blocks must render no header
  and no bytes; and secondaries stay observational (Q-09-7 = B) with no
  evaluator, record field or transport. **NEXT = Step 09.5** — the repository
  structural-debt + test-topology AUDIT (roadmap §15.1b), whose disposition
  gates Step-10 entry. Debt carried forward unchanged: proposer
  prediction-authoring grammar · proposer task-science prompts ·
  `evaluation.py` per-check-NAME tables · resume/dashboard direction literals ·
  secondary transport · `vocab_link_confirmations` → **Step 10**; the TIDMAD
  interpretation adapter · tuner Regime-A binding · composition root →
  **Step 12**.
- **STEP 09a — COMPLETE / MERGED (2026-08-19)**: PR #238, squash
  `4cf38dec0934cf22c59c80cc69711d7c2bd0401b`; final PR head `9d85f67b`,
  exact-head CI **32313798097 SUCCESS**; merged master byte-identical to the
  validated head. **The interpreter no longer assumes which direction is
  better, and it refuses to guess.** The run's `MetricSpec` is stamped on
  `HyperparamTuningOutput` by the tuner's ONE existing derivation
  (Step 09a adds ZERO new `derive_tidmad_metric*` production sites — pinned by
  an executable census over every production module), reconciled across
  outputs by `reconcile_metric_spec`, and `InterpretationInput` FAILS CLOSED
  when a score-bearing input carries no spec — a legacy/pre-09a output is a
  NAMED refusal, never a re-derivation (adding the validator turned 79 tests
  red at once; every one had been silently relying on the assumed direction,
  and all were UPGRADED, never weakened). All **21** interpreter direction
  consumers now read `MetricOrder`, and the C1a differential oracle is
  **BYTE-IDENTICAL** across that migration — 21 ordering sites changed shape
  and nothing observable moved. Prediction semantics v2
  (`metric_order_signsafe_v2`) fixes three defects that all looked like
  working code: direction-blindness, a sign-degenerate band (scaling a
  NEGATIVE reference made `partial` UNREACHABLE for every TIDMAD score), and
  uncomputable results counted as evidence (now `unevaluated`, in NO pool).
  v1 and v2 statistics are NEVER mixed: the legacy pool is frozen and carried,
  accuracy is v2-only and labelled, and both pool sizes are stated. The
  interpreter's prediction memory now actually rides the EXISTING canonical
  lifecycle (digest → loop carry → `RestoredState` latest-wins → next input);
  pre-09a it was carried by NOTHING (parent erratum E2), so every production
  digest's pool held exactly ONE outcome and the proposer always rendered
  `N=1`. Evidence projection adds per-role training diagnosis, failure counts
  derived only from authorities that already own them, and the typed secondary
  contract with **Q-09-7 = B held** — the builder NEVER populates
  `secondary_metrics` and no evaluator/record field/tuner persistence/
  transport/loader exists. Three-task L1 rung (TIDMAD higher · Pets accuracy ·
  **DAVIS `mse` LOWER**, hand-computed literals). **Gate 1 = 0, Gate 2 = 0,
  real LLM/training/inference = 0** — exactly the frozen §7 disposition.
  Pre-merge closeout: the semantics ids were centralized to ONE schema-layer
  authority (F-09a-17 — five literal sites, replaced by a single-authority
  census that is mutation-proven RED), and the ledger audit found **F-09a-25**,
  a planned §5 integration-test UPGRADE never executed which had left
  `tests/integration/workflows/test_vocab_accumulation.py` broken *outside CI*
  — a reminder that a test excluded from CI is only as green as the last
  person who ran it. Design + evidence:
  `docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks/pr_09a_interpreter_evidence_ordering.md`
  §10 (104 `[x]` / 0 `[ ]`). **Debt carried forward, none blocking**: Q-09-7
  production secondary transport → Step 10; `evaluation.py`'s per-check-NAME
  threshold tables → Step 10; the bounded TIDMAD interpretation-block
  compatibility adapter → Step 12; the unchanged tuner Regime-A metric binding
  → Step 12; resume/dashboard direction literals → Step 10; scale-naive
  boldness → Step 10+; the `vocab_link_confirmations` carry → Step 10; and the
  proposer's "Prediction Track Record" rendering, which pairs v2 FRACTIONS
  with the v1 DENOMINATOR — the consequence Q-09a-3 explicitly declares and
  freezes, owned by 09b's rendering surface. **NEXT = Step 09b** (interpreter-
  local decomposition owned by its prompt/rendering semantics), and after 09b
  merges but BEFORE Step 10 implementation, the dedicated repo-wide production
  structural-debt + test-topology audit (operator sequencing, 2026-08-19) — all
  to be re-confirmed from the merged roadmap in a fresh session, never from the
  conversation that produced 09a.
- **STEP 08c — COMPLETE / MERGED (2026-08-19) ⇒ STEP 08 COMPLETE**: PR
  #237, squash `3f4effb5`; exact-head CI **32226620524 SUCCESS** on
  `532035e6` (final EXECUTABLE head `ede11fd5` — C6 is verified
  docs/tests only, so the Gate evidence covers the final executable
  state). **The first REAL contrast content runs through the 08b
  extension architecture.** Two framework-standard view capabilities
  (`categorical_predictions` / `continuous_samples`,
  `execute_tools/health_checks/standard_views.py`) with a frozen
  NumPy ABI: 1-D typed streams, strict dtype kinds, NO coercion,
  read-only no-copy views (`np.shares_memory`, never `.base`), NATIVE
  dtype preserved, runtime-only, ENGINE-OPAQUE (censused). Three generic
  collapse checks consume them: `categorical_distinct_symbols` (records
  occupancy = distinct/cardinality), `categorical_dominant_fraction`
  (thresholds a FRACTION — the real collapse is 369/370 NEAR-constant),
  and `sample_dispersion_floor` UPGRADED in place (view-consuming,
  `required_facts=()`, `np.std(dtype=float64, ddof=0)`, config-borne
  samples retired). `symbol_cardinality` reaches checks ONLY by
  declaration-driven composition injection from the frozen
  `INJECTABLE_AXIS_PARAMETERS` table (`_composition.py`); a roster
  hand-authoring ANY injected key is a deterministic
  `HealthCompositionError` (the silent-overwrite hazard is gone). §3.2a
  verdict boundary: unreadable/empty ⇒ ERROR; read-but-invalid
  (out-of-range symbol, non-finite sample) ⇒ FAILED — the categorical
  family shares ONE mechanism (`_categorical_validity.py`). Pets and
  DAVIS bind task-owned Health families through the EXTERNAL state-C
  interface (pack `declared/task_health.yaml` + underscore-prefixed pack
  plugins loaded ONLY by explicit `kind: file` refs — both directory
  scanners skip `_` members; frozen thresholds 5 / 0.95 / 0.04; committed
  real Pets collapse fixture sha `cc847026…f752c`; codec parity both
  packs). Both D14 runners gained ONE shared Health evidence stage
  (`scripts/_gate2_health_stage.py`: explicit binding keyword-only with
  no default, EVERY selected gate persisted, additive `health:` block);
  the 08b cross-task guardrail is INVERTED, never deleted. **Gate 2:
  Pets PASS + DAVIS PASS at `ede11fd5`** — Pets deterministically
  REPRODUCED the D14 collapse byte-identically and both blocking gates
  caught it with independently-recomputed-consistent evidence; DAVIS's
  fresh npz reproduced the preserved artifact and the FULL
  5,160,960-sample view passed at the frozen floor with dispersion
  `0.2156402715035823` bit-equal. TIDMAD parity owners byte-identical at
  every commit (NO new TIDMAD Gate); Gate 1 NOT REQUIRED; the 08b
  out-of-tree fourth-task proof stays green; health-core census (124
  tests) + three-task rung landed; parent §14 A–H ALL CLOSED (mapping:
  child §10.8). **Debt carried to Step 9/10 (parent §15 R5)**:
  `evaluation.py`'s per-check-NAME threshold tables must become
  declaration-driven — census-excluded by listed name today. Design +
  evidence:
  `generic_framework_upgrade/step_08_health_check_task_profile/pr_08c_contrast_families.md`
  §10. **NEXT = Step 09** — to be re-confirmed from the merged roadmap in
  a fresh session, never from the conversation that produced 08c.
- **STEP 08a — COMPLETE / MERGED (2026-08-19)**: PR #235, squash
  `7da1e45e`; exact-head CI **32207685908 SUCCESS** on `3055af66`. Health
  checks no longer say "not applicable" by returning `passed=True` with prose:
  **`CheckVerdict` (`passed|failed|inapplicable|error`) is a typed fact**, and
  applicability is decided in `runner.evaluate_gate` BEFORE the skill is
  invoked, so an inapplicable check opens no artifact. `passed` keeps its
  exact meaning (it selects `on_pass`/`on_fail` and drives `short_circuit`),
  so gate ACTIONS are unchanged; honesty moved to counting, persistence
  (`PersistedHealthGateResult.check_verdicts`, additive) and eligibility (an
  all-inapplicable gate is excluded from the required set; an errored one
  never is). The six checks declare their inputs as data
  (`CheckInputDeclaration`); the peek reads channel identity from the
  Deliverable Contract (zero `channel0001`/`channel0002` literals left in the
  peek path, one whitelisted persisted label). **Gate 2 PASS** — six gates
  fired, all six persisted `check_verdicts`, verdict union exactly
  `{passed, failed}` with no `inapplicable`, and a real mode collapse drove
  `invalidate_round` on two blocking gates while four passed. **Gate 1 NOT
  REQUIRED** (LLM-facing rendering byte-identical to a worktree at
  `a37fd15d`). Three things future work must not re-break: `value_scale_unit`
  is owned by NOTHING today (the mV constant is a check-local literal), so
  08b must move it TOGETHER with its declaration or parity breaks in between;
  `spectral_peak_ratio` reads ONLY the denoised channel; and
  `threshold_parameter_names` means THRESHOLDS, not parameters read —
  recording-only checks declare `()`. Design + evidence:
  `generic_framework_upgrade/step_08_health_check_task_profile/pr_08a_check_input_contract.md`
  §4/§10.
- **STEP 08b — COMPLETE / MERGED (2026-08-18)**: PR #236, squash `13e28796`;
  exact-head CI **32217121228 SUCCESS** on `65a3c7d9` (final executable head
  `bf6e9e19` — C7 is test/docs only). **The task owns its Health science and
  an external task extends the system with no SIDERIUS edit.**
  `configs/health_checks.yaml` is now a policy-only `health_policy` block
  (disposition → role, cadence, short-circuit, actions, `aggregation`);
  TIDMAD's roster, thresholds, `peek_samples`, health-peek files, mV value
  scale and `reason` prose live in **`configs/task_health/tidmad.yaml`**. The
  two compose deterministically into the same pinned
  `health_checks_effective.yaml`, and **`load_health_gates_config()` returns
  that COMPOSED result** — a file already carrying `health_gates` (an
  effective config, or a pre-08b custom YAML) is returned untouched. To
  change a THRESHOLD edit the task config; to change what a failure DOES edit
  the framework policy. External plugins register checks AND view providers
  through the public `register` / `register_view_provider`; their content
  digests join the pinned `health_config_sha256`, so an edited plugin fails a
  resume closed, while host paths are excluded so the same package at two
  absolute paths pins one identity. Three binding states are frozen —
  `LEGACY_OMITTED` (resolves to the TIDMAD config; the bounded legacy path),
  `EXPLICIT_NONE` (a NAMED absence that must never fall back to another
  task's family), and an explicit path. **D18 landed**: a scalar-only metric
  reaches Health as a typed `PerSampleEvidence` instead of an empty list.
  **Gate 2 PASS**; **Gate 1 NOT REQUIRED**. Parity is measured on EXECUTED
  SEMANTICS, not bytes (the composed sha moved `c933bcee`→`7a4debd6`, and
  08a's 27-case verdict manifest is byte-identical after the millivolt factor
  changed owner). Four things future work must not re-break: `TASK_HEALTH_PEEK`
  is a **bounded legacy adapter** kept ONLY so pre-08b configs stay readable
  (removal was implemented and falsified — their recorded sha is computed over
  the RESOLVED document); a check must declare an input only if it CONSUMES it
  (the `value_scale_unit` and `per_sample_evidence` biconditionals); the
  Pets/DAVIS D14 runners are direct-execution harnesses that never enter
  Health composition, so `EXPLICIT_NONE` is what will protect them when 08c
  routes them through it; and **DAVIS is scalar-only too** (`GlobalMseMetric`
  returns `per_sample=None`), so 2 of the 3 executable tracks depend on D18.
  Design + evidence:
  `generic_framework_upgrade/step_08_health_check_task_profile/pr_08b_extension_architecture.md`
  §4/§10/§11. **NEXT = 08c** (standard `categorical_predictions` /
  `continuous_samples` capabilities, the reusable generic checks, and the
  Pets/DAVIS Health families) — to be re-confirmed from the merged roadmap in
  a fresh session, never from the conversation that produced 08b.
- **D14 EXECUTABLE DATA PATH — COMPLETE / MERGED (2026-08-18)**: PR #232, the
  integrated stack #230 → #231 → #232, squash
  `4db414b599bb1a41357ad694f78bceec4f4577e1`; canonical exact-head CI
  **32191416252 SUCCESS** (lint · ruff-format · pyright · unit), landed master
  verified byte-identical to the validated head `322064b2`. #230/#231 closed
  as superseded review units (they remain the per-child review records).
  **THREE materially different tasks now run through ONE execution
  architecture**: TIDMAD 1-D denoising (relocated behind the seam at byte
  parity — Gate-2 PAIR PASS), Oxford-IIIT Pet 37-way RGB classification
  (Gate-2 PASS; accuracy 0.027 = chance, a REAL constant-prediction collapse
  kept as Step-08 health evidence, deliberately not tuned), DAVIS 8→4
  future-frame regression (Gate-2 PASS; global MSE 0.017290, better than the
  last-frame-copy baseline 0.017392). Seam:
  `execute_tools/task_data_path.py` (four methods, fail-closed registry keyed
  on binding PRESENCE never task name, run-scoped binding, internal transport)
  with `tidmad_data_path.py` / `pets_data_path.py` / `davis_data_path.py`.
  Enforced invariants: zero task-name branches in generic core, zero
  production dependency on `examples/` (plugin SOURCE only, loaded
  dynamically), one registry / three implementations, Step-06 metric
  ownership (three instances behind one handle) and Step-07 training
  semantics preserved. Design + full evidence:
  `docs/design/generic_framework_upgrade/d14_executable_data_path.md` §7a
  (per-child ledgers in its subdirectory). Deferred, none blocking: #225,
  #226, #227, #228, #229, #233 (stacked PRs get no CI — fix before any future
  stacked milestone). **NEXT = Step 08 (HealthGate), whose premature draft on
  master must be re-compared against these three tracks' actual executable
  behaviour before any Step-08 design is written.**
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
  **PR0 COMPLETE — MERGED (PR #214, squash `79403b44`, 2026-08-15)**:
  `examples/{tidmad,oxford_iiit_pet,davis_future_prediction}/` at honest
  maturity (TIDMAD read-only resolved snapshots; Pets 2 946 / 734 / 3 669
  and DAVIS 60 / 15 / 15 identity manifests; L0/L1 `ModelIOContract` /
  `MetricSpec` declarations), `tools/example_packs/` (tooling only, never
  imported by production), `tests/unit/examples/` (61 tests incl. the
  maturity-pinned governance guards — no `.py` under `examples/` until D14;
  no top-level `task_description`/`forward_contract` YAML under `examples/`
  until Step 12). **07a IMPLEMENTED (2026-08-15, branch
  `step07-pr07a-training-history-diagnosis`, C1–C4; design
  `pr_07a_training_history_diagnosis.md` FROZEN rev 2, §14 = ledger)**: the
  production trainer runs a transactional R3 validation pass on the tuner's
  EXISTING eval SampleSet (`--eval_sample_set_json`; exact-scope
  materialization; R2 unchanged; `comparability` stamped) and emits the typed
  `training_history` beside the three legacy keys; the tuner interprets
  results through `interpret_training_results` (expected validation + missing
  R3 → `error_training`), derives `TrainingDiagnosis` once, persists both on
  `ExperimentRecord` and HIDES them from planner + reflector (PB/WF exact);
  Seam 5 written; TIDMAD production-backed, Pets/DAVIS L1 fixture-backed
  (rung B-07a-1). Gate 2 PASS 2026-08-16 — the RT4 watchdog killed 3/4 attempts
  INSIDE the un-priced validation pass (validation is a missing deadline term:
  `T_deadline = T̂_train + T̂_val + overhead + margin` is ADDED 07c scope, parent
  §8.4; until 07c lands, `--runtime_watchdog`-enabled real campaigns are NOT a
  reliable configuration). **MERGED — PR #215, squash `65804b3d83d67eac5e8821f012bfb2f9f1fbffec` (`65804b3d`), 2026-08-16; final PR head `752f8f0e`, exact-head CI 31927638592 SUCCESS; parity `git diff 752f8f0e 65804b3d` empty — 07a COMPLETE.** Next = 07b design (fresh
  Implementation Working Rules contract; Gate 1 required). **07b detailed
  design FROZEN — operator approved 2026-08-15 (rev 2;
  `pr_07b_tuner_policy.md`: one order authority `MetricOrder`, per-rule
  scale classification, P2 authority-rendered blocks byte-exact, P3 declared
  PB deltas via owned renderers, Gate 1 ≥ 2 tuner rounds pseudo-training)**.
  **07b IMPLEMENTED 2026-08-16 (branch `step07-pr07b-tuner-policy`, C1–C6;
  design `pr_07b_tuner_policy.md` §14 = ledger)**: `execute_tools/metric_order.py`
  is the ONE authority interpreting `MetricSpec.direction` — all 21 golden-metric
  ordering sites in the tuner ask it (the same-loss `final_loss` rank
  deliberately does NOT, and is pinned not to move); every scale-sensitive rule
  is classified rather than sign-flipped, with `degenerate_penalty_score` FAILING
  CLOSED at startup under a minimised metric; `AttemptTransition` /
  `AttemptDecision` REMOVED with the `resolved_action` hazard recorded at its
  declaration (a dedicated round-semantics correction, operator decision
  required — NOT 07b/07c); the planner/reflector prompts render task content
  (P2, TIDMAD bytes EXACT — PB sha256 unchanged), direction wording, metric
  identity and compact calibration-free `TrainingDiagnosis` lines (P3, the only
  authorised PB deltas) from landed authorities; `plan(task_render, metric_spec)`
  and `reflect(metric_spec, training_diagnosis)` FAIL CLOSED (WF-1 22→23→24;
  WF-2 `actual_results` 9 / `reflection_context` 23 EXACT); OD-1 closed by
  record-own key order. `run()` AST branch count 244 → 198.
  **C7 — tuner node structural decomposition (operator scope amendment,
  2026-08-16; C7d follow-up = decision A′)**: the node is now
  `<node>.py` + `<node>.md` PUBLIC and eight PRIVATE modules
  (`contracts` carriers · `planning` · `execution` 3 coarse phases ·
  `records` BUILDS · `runtime` EMITS · `policy` · `feedback` · `cli`) on a
  one-way acyclic private graph. Main file 7,430 → 1,473; `run()` 2,714 →
  1,011 (branch nodes 198 → 64) and now reads as a lifecycle — plan →
  admission → train → infer/score/health → `brain.reflect` → build record →
  emit → finalize. `RunBindings` carries run-scoped authorities ONLY, enforced
  at construction by `FORBIDDEN_BINDING_FIELDS`; `AttemptStage` is the single
  deliberate mutable carrier (the raising path has no return value). All 15
  loop-control exits translated 1:1 to `AttemptSignal` (`raise` untouched), so
  retry/round semantics are unchanged — proven by a 13-surface differential
  PRE/POST oracle, deep-equal on all 12 behavioural surfaces. **The node's
  public boundary is an executable rule**
  (`tests/unit/nodes/test_node_public_boundary.py`): never import a node's
  private modules from outside it, and stub internals on the module that CALLS
  them (`_run_skill` → `runtime`, `_emit_record` → `records`).
  **07b MERGED — PR #216, squash `9ea3755fb36b916bdca5113471fb5cd74d856335` (`9ea3755f`), 2026-08-16. COMPLETE.**
  NEXT = the Step-07 round-state semantics correction (decouple trial/formal
  identity from the time-budget machinery; regression-first; NOT `resolved_action`,
  NOT 07c) — DONE, see the correction entry below. Gate 1 PASS twice (pre-/post-refactor); Gate 2 PASS — the latter was
  NOT required by the frozen 07b disposition and was ADDED by the C7 operator scope
  amendment as structural-refactor regression evidence. Final executable head
  `cb1a885a`; final PR head `307fa0ce917c0afbd6ee5425fae7ef902b267019` (documentation
  and gate-advice JSON only in between); PR #216; exact-head CI 31989125173 SUCCESS;
  clean tree. Deferred and UNCHANGED by 07b: the `memory.time_mode` /
  disabled-time-budget coupling, the `resolved_action` hazard (recorded then
  as "stale-attempt"; the mechanism was a SEVERED carrier, CLOSED by the
  F-SCANC-1 retirement, 2026-08-26), and the
  validation-time/watchdog accounting debt (07c).
- **Step 07 trial/formal-identity correction — MERGED (PR #217, squash
  `a15d1366e5a86b1d3297cda65b0d3a5dfdb84a2e` / `a15d1366`, 2026-08-17; base
  `48e9fb90`; C1 `b661a964` executable + C2 `f804d3e6` docs; final PR head
  `f804d3e6`; exact-head CI 31995712890 SUCCESS; parity `git diff f804d3e6
  a15d1366` empty; full unit suite 9,824 passed / 3 skipped / 0 failed from a
  clean tree; Gate 1 and Gate 2 both NOT REQUIRED, decided separately with the
  assignment row quoted — no live Gate run, and no time budget added anywhere
  to make anything pass)**: a SMALL semantic
  correction PR with **no separate design document** — the source audit, decision,
  regression evidence and disposition live in the PR body, in the tuner node's
  public `ml_hyperparameter_tune_agent.md` ("Candidate role identity") and in the
  PR handoff. **`record.is_trial` is the ONE authority for trial/formal candidate
  role**; `memory.time_mode` is time-gate metadata ("which budget was active",
  stamped only when the gate ran) and is removed from role eligibility in
  `policy._best_trial_winner` and `feedback._build_trial_validity_feedback`. Its
  POPULATION is deliberately unchanged, so the timing subsystem, the planner
  resource block and the trial→formal inference-measurement reuse are untouched.
  Fixes the 07b-Gate-1-exposed chain: incumbent formal gates ON + both time
  budgets unset → valid trial invisible → `[SkipFormal] reason=no_valid_trial_winner`
  → the forced formal round never ran. Unchanged: candidate validity, MetricOrder,
  skip/bypass threshold mathematics, retry/round semantics, record schema, prompts,
  the node's public interface. Still OPEN at the time: the `resolved_action`
  hazard ("stale-attempt" was wrong in kind — the C7 decomposition had
  SEVERED the carrier, so the variable was never written at all; CLOSED by
  the F-SCANC-1 retirement, operator decision packet v1, 2026-08-26) and
  07c's validation-time/watchdog accounting debt.
  **Runtime-control debt opened by the 07c design review (operator decision,
  2026-08-17, Q-07c-6 = B)**: *pre-run ADMISSION pricing of the validation
  workload*. 07c prices validation for runtime PREDICTION and the WATCHDOG
  only — `admission.py:148-150` says the prephase measurement covers
  `phase="training"` only, and 07a's validation pass runs inside the training
  subprocess, so no measurement-backed validation estimate exists when
  admission executes. Owner: admission / runtime-control (§7e); **OPEN after
  07c; NOT bound to D14**; and it must never be approximated from the training
  measurement by a fixed ratio (the `× 2.7` pattern that the historical
  `docs/refine_inference_time_estimator.md` removed — that note itself was
  deleted in the 2026-08-10 docs sweep, `6bc1f536`; the surviving design is
  `docs/design/runtime_estimation_and_calibration.md`).
  **`resolved_action` is NOT scheduled ahead of 07c (operator decision,
  2026-08-17)**: it is conceptually adjacent to the coupling just corrected but
  is a different defect, and adjacency is not a schedule. [Superseded: the
  operator decision its note named arrived 2026-08-26 — F-SCANC-1, decision
  packet v1, RETIRE for v1. The severed machinery, the `gate_aborted` carrier
  and the `SKIP_ITER` / `SKIP_TO_FORMAL` vocabulary members are removed;
  re-opening gate-driven loop control is ICLR-track work needing its own
  decision and witness cycle.] **07c detailed design is FROZEN — Revision 3, operator approved 2026-08-17** (`docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/pr_07c_tuner_measurement.md`, source audit at `ad176036`; seven commits C1–C7; Q-07c-1..9 all closed; three-track matrix = TIDMAD executable / Pets + DAVIS at current maturity only; Gate 1 NOT REQUIRED, Gate 2 REQUIRED bounded once at the final executable head, watchdog ON and counterfactual-discriminative). **NEXT = 07c IMPLEMENTATION**, to be
  re-confirmed from the merged roadmap / current-state documents at the start of
  a fresh session — never from the conversation that produced this correction.
  See the Step-07 parent §17.1.

- **Active line of work (2026-08-30)**: separate reusable framework ownership
  from real tasks and campaigns. The live ledger is
  `docs/design/framework_experiment_repository_separation.md`. Real task and
  campaign assets move to `siderius-exp`; SIDERIUS retains only generic
  mechanisms and lightweight synthetic examples. Historical entries below
  remain provenance, not current ownership instructions.

- **HISTORICAL — superseded, retained for provenance, NOT actionable.** The
  four entries below were accurate around 2026-08-17 and are kept because this
  project does not erase a superseded statement, it marks it. Since then both
  branches they name have **merged and been deleted**:
  `feat/rt1-fixed-step-overhead` and `feat/enable-partial-file-list` no longer
  exist (`git rev-parse --verify` fails for both), and `d0aa0b6` was a commit
  on the former — it is reachable from **zero** refs today
  (`git for-each-ref --contains d0aa0b6` returns nothing), so a fresh clone
  does not contain it. Treat no branch, SHA, "Pending" or "still pending" item
  in these entries as work to be done.

  - **Active branch** *(historical)*: `feat/rt1-fixed-step-overhead` —
  runtime-control system, RT1 → RT6 COMPLETE per
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
  - **Previous feature** *(historical)*: `feat/enable-partial-file-list` —
  DataScope DS1-DS8 complete; DS Gates 1 & 2 + PR still pending.
  - **Master CI** *(historical)*: red at `9e503ea` (PR #127 merged over a
  stale shell-parity expectation); fixed by `a84203a` on this branch — lands
  with the PR.
  - **Open issues** *(historical)*: carry-forward #91, #93, #94, #95, #97, #100, plus the
  PR #101 follow-ups still open (#103, #105, #107, #110, #111, #113) and
  the DS8-filed issues (FU-1 peek-vs-eval-coverage latent bug, FU-7
  vocab-accumulation NoneType test defect — see the design doc's
  follow-up tracker).
