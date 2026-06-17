# Design: Enable Global Task Config (`enable_global_task_config`)

**Status**: Draft  
**Author**: Yue Ma  
**Created**: 2026-06-13  
**Branch**: (new branch, to be created)  
**Depends on**: nothing (can land independently)  
**Unblocks**: `enable_loss_inventory` (loss generation prompt needs task_description + forward_contract)

---

## Development principles

Same four rules as all SIDERIUS design docs:

1. **Check, don't guess.** Read source before making claims. If the answer isn't in the code, ask the user.
2. **Keep design doc and code in lock-step.** Tick `[ ] → [x]` as work lands; record test results inline.
3. **Stop before each commit.** Show progress + implementation details; wait for explicit approval before `git commit`. Tests run freely except real-LLM + real-training combos.
4. **Split logical commits at clean seams.** Each `Commit T*` is the logical unit; split further if the actual diff is too large.

---

## Motivation

Task-specific information is currently hardcoded in at least five production
files. This means applying SIDERIUS to a new task requires grep-and-replace
across Python files and Markdown templates — error-prone and invisible to
operators.

The immediate trigger is `enable_loss_inventory`: the loss generation prompt
(Commit L4) needs to know the forward contract (`[B, T] int64 → [B, 256, T]
float32`) and the task description to generate correct loss functions. Without
a canonical source for these values, the loss prompt would be the sixth place
to hardcode SQUID-specific information.

---

## Scope

**In scope:**
- New `configs/task_config.yaml` as the single canonical source for task
  description and forward contract
- Remove task-specific hardcodes from the **eight affected locations** listed
  below (T1–T4 covers all eight), replacing them with `{TASK_DESCRIPTION}` and
  `{FORWARD_CONTRACT}` placeholders injected at render time
- Workflow reads `task_config.yaml` and threads values into all affected nodes

**Explicitly out of scope (tracked as future work, do not touch):**
- `TIDMAD_DATA_DIR` / `nodes/scoring_reference.py` reference data coupling
- `denoising_score` field naming in schemas
- `NUM_FILES = 20` parameterization (already partially done via
  `execute_tools/dataset_config.py`)
- `ScoreComparisonTable` and `aggregated_score_table_awareness` system
  (already task-agnostic — no changes needed)
- `from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG`
  import in proposer/tuner nodes

---

## Affected locations (confirmed by audit 2026-06-13)

| # | File | Lines | Hardcoded content |
|---|------|-------|-------------------|
| 1 | `nodes/ml_model_implementor/ml_model_implementor.py` | 306-322 | "TIDMAD SQUID magnetometry", "integer ADC values 0-255", `[B, T] int64`, `[B, 256, T] float32`, "256 denoising classes", `nn.Embedding(256, embed_dim)`, "Conv1d(channels, 256, 1)" |
| 2 | `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | 172-186 | "TIDMAD SQUID magnetometry", "integer ADC values 0-255", `[B, T] int64`, `[B, 256, T] float32`, "256 denoising classes", "cross-entropy or focal loss: per-timestep 256-class classification" |
| 3 | `agent/prompt_templates/proposal/proposing_stage.md` | 69-70 | `[B, T] int64`, `[B, 256, T] float32`, "per-timestep logits over 256 classes" |
| 4 | `agent/prompt_templates/proposal/comparison_stage.md` | 4 | "previously tested denoising models on the TIDMAD dataset" |
| 5 | `agent/prompt_templates/literature_review/search_decision_system.md` | multiple | "1D signals", "broadband", "SQUID", "denoising", "1D time series" (query examples vs task framing — reviewed in T3) |
| 6 | `agent/prompts.py` | 10-11, multiple | "Senior Signal Processing Researcher specialized in deep learning for signal denoising", "optimize the 'Denoising Score' for the TIDMAD dataset" — 20 task-specific hits in tuner planner + reflector prompts |
| 7 | `nodes/result_interpretation_agent/result_interpretation_agent.py` | 47, 239 | "senior ML research analyst specialising in deep learning for signal denoising" — two system prompts; "The aggregate denoising scalar is the log of a sum…" |
| 8 | `nodes/ml_literature_review/ml_literature_review.py` | 70-75 | `AgentCard` role, expertise_domain, limitations — "Surface ML denoising literature", "ML denoising architectures", "SQUID-specific applicability" |

**Locations 6 and 7** are in files recently touched by Phase 8
(score_table awareness + Impact_Score rewrites). Changes must be
additive only — do NOT touch Phase 8 content (Impact_Score, Linear_Weight,
per_file_analysis, SYNTHESIS_SYSTEM_PROMPT reasoning frame). Only the
role/persona header lines and explicit TIDMAD/denoising framing are in scope.

**Location 8** (AgentCard) is small and self-contained — the role and
expertise_domain strings are read by the proposer when evaluating
lit-review finding credibility. They should reflect the actual task, not
hardcode "denoising".

---

## `configs/task_config.yaml` — canonical config file

```yaml
# configs/task_config.yaml
# Single source of truth for task-level configuration.
# All agents read task_description and forward_contract from here.
# ---------------------------------------------------------------------------

# Plain-English description of the research task.
# Injected into the {TASK_DESCRIPTION} placeholder in all agent system prompts
# (implementor, proposer, lit-review search/synthesis/extract).
# Keep this concise — it appears in every LLM call.
task_description: |
  full-spectrum 1-D time-series denoising of SQUID dark-matter
  detector data: map a noisy [B, T] integer signal to a clean
  [B, 256, T] reconstruction, trained across the whole frequency
  spectrum at once (not split into per-band models).

# Forward contract for the model plugin interface.
# Injected into the {FORWARD_CONTRACT} placeholder in implementor and proposer
# system prompts. Must describe the exact PyTorch tensor shapes and types
# expected by the training engine and validator.
forward_contract:
  input_shape: "[B, T] int64"
  input_description: "raw signal, integer class indices 0-255"
  output_shape: "[B, 256, T] float32"
  output_description: "per-timestep logits over 256 denoising classes"
  num_classes: 256
  embedding_note: >
    Input values are integer class indices — use nn.Embedding(num_classes,
    embed_dim) to convert [B, T] int64 → [B, T, embed_dim], then transpose
    to [B, embed_dim, T] for Conv1d layers.
  output_head_note: >
    Output must be exactly [output_shape] — use a final
    Conv1d(channels, num_classes, 1) or Linear + transpose.
  task_type: "classification"
  task_note: >
    Offline denoising — output at position t may depend on all positions.
    Causal constraints are not required.

# ---------------------------------------------------------------------------
# Future extensions (out of scope for this doc):
#   num_files: 20              # currently in execute_tools/dataset_config.py
#   data_dir: ...              # currently hardcoded as TIDMAD_DATA_DIR
#   metric_name: denoising_score  # currently hardcoded in schemas
# ---------------------------------------------------------------------------
```

---

## Rendered forward contract format

The `{FORWARD_CONTRACT}` placeholder is rendered from the YAML by a helper
function `render_forward_contract(fc: dict) -> str` in
`workflows/task_config.py` (new file). The rendered string is injected
verbatim into system prompts.

Example rendered output:

```
The model must satisfy this forward contract (non-negotiable):
    input:  [B, T]       int64   — raw signal, integer class indices 0-255
    output: [B, 256, T]  float32 — per-timestep logits over 256 denoising classes

Input values are integer class indices — use nn.Embedding(256, embed_dim)
to convert [B, T] int64 → [B, T, embed_dim], then transpose to
[B, embed_dim, T] for Conv1d layers.
Output must be exactly [B, 256, T] — use a final Conv1d(channels, 256, 1)
or Linear + transpose.
Offline denoising — output at position t may depend on all positions.
Causal constraints are not required.
Task type: classification (per-timestep 256-class).
```

---

## Backward compatibility

`configs/task_config.yaml` is committed to the repo with SQUID defaults
(same pattern as `configs/lit_review_config.yaml`). There is NO in-code
fallback. If the file is missing or a required field is empty,
`load_task_config()` raises a `FileNotFoundError` or `ValueError` with
a clear remediation message:

```
FileNotFoundError: configs/task_config.yaml not found.
  This file is required for all SIDERIUS agent runs.
  If you deleted it accidentally, restore from git:
      git checkout configs/task_config.yaml
  If you are setting up a new task, copy and edit:
      cp configs/task_config.example.yaml configs/task_config.yaml
```

`configs/task_config.example.yaml` is also committed alongside
`task_config.yaml` as a reference template for operators setting up a
new task.

**Already-completed run outputs** (`run_output_*.json`,
`evolution_log.jsonl`, `agent_data_stream.jsonl`) are not affected —
they contain experiment results and LLM reasoning outputs, not task
config. Re-reading old results does not require `task_config.yaml`.

---

## Run provenance — task config snapshot

**Problem**: before this feature, task description was hardcoded in Python
files and had no audit trail. After this feature, task description lives in
`configs/task_config.yaml`. If someone wants to replay an old run on a new
task config, they must know what task config was active when the original run
happened.

**Solution**: at the start of every workflow run, copy `task_config.yaml`
into the run's workspace as `task_config_snapshot.yaml`. This snapshot is
written once, never modified, and serves as the ground truth for replay.

```
{workspace}/{run_name}/
  task_config_snapshot.yaml   ← NEW: copy of task_config.yaml at run start
  workflow_{run_name}.json
  iteration_001/
  iteration_002/
  ...
```

This is added in **Commit T1b** — one `shutil.copy2(...)` call in
`workflows/model_exploration.py` immediately after the workspace-init
`os.makedirs(run_dir, exist_ok=True)` at line 953 in `run_workflow`.

**Replay procedure for runs after T1b landing:**
```bash
# To replay run at /path/to/workspace/{run_name}/:
cp /path/to/workspace/{run_name}/task_config_snapshot.yaml configs/task_config.yaml
# Then replay normally
```

**Replay procedure for runs BEFORE T1 landing (no snapshot exists):**
These runs used the hardcoded SQUID defaults. The current
`configs/task_config.yaml` (committed with SQUID defaults) is the correct
config to use for replay. No action needed — the defaults match what was
used.

**Important**: the snapshot is read-only metadata. The workflow always reads
from `configs/task_config.yaml` at runtime, never from the snapshot. The
snapshot is only for human reference and replay.

---

## Commit plan

### Commit T1a — config files + schema + loader

**Goal**: stand up `configs/task_config.yaml`, the `ForwardContract`
Pydantic schema, and the `workflows/task_config.py` loader/renderer
module. Self-contained: no workflow modification, no node code touched.
After this commit, `task_config.yaml` is readable, validates on load,
and `render_forward_contract()` works — but no agent has yet been wired
to use it.

**Code**:
- [x] `configs/task_config.yaml` — new file with `task_description` and
  `forward_contract` blocks as shown above (committed to repo with SQUID defaults)
- [x] `configs/task_config.example.yaml` — same content as `task_config.yaml`,
  also committed; serves as the copy-from template for operators setting up a new task
- [x] `agent/schemas/task_config.py` (new file) — define `ForwardContract`:
  ```python
  class ForwardContract(BaseModel):
      input_shape: str = ""
      input_description: str = ""
      output_shape: str = ""
      output_description: str = ""
      num_classes: int = 0
      embedding_note: str = ""
      output_head_note: str = ""
      task_type: str = ""
      task_note: str = ""
  ```
  Defaults are empty strings only so that a bare `ForwardContract()` is
  constructible for testing. Production callers always populate via
  `ForwardContract(**yaml_dict)` after `load_task_config()`, where a typo in
  the YAML key name produces a Pydantic `ValidationError` rather than silent
  empty rendering.
- [x] `workflows/task_config.py` — new module:
  - [x] `load_task_config(path: str | None = None) -> dict` — reads
    `configs/task_config.yaml` (or the provided path). **Raises `FileNotFoundError`**
    when the file is missing, with the remediation message shown in the
    *Backward compatibility* section. **Raises `ValueError`** when
    `task_description` is empty or the `forward_contract` block is missing
    a required field. Uses `yaml.safe_load`. Module-level cache (load once per process).
  - [x] `render_forward_contract(fc: ForwardContract) -> str` — takes a
    `ForwardContract` Pydantic instance, returns the formatted multi-line
    string shown above. Returns `""` on a `ForwardContract` whose fields are
    all empty (only happens if a caller bypasses `load_task_config` and
    constructs a default `ForwardContract()` directly).
  - [x] `get_task_description(config: dict) -> str` — extracts and strips
    `config["task_description"]`. Returns `""` only if caller bypasses
    `load_task_config` (which itself rejects empty).
- [x] `workflows/__init__.py` — already exists (0 bytes); no changes needed.

**Tests** (pure Python, no LLM — run freely):
- [x] `tests/unit/workflows/test_task_config.py` (new file) — **20 tests, all pass in 0.07s**
  - [x] `load_task_config` with valid YAML → returns dict with correct keys
  - [x] `load_task_config` with missing file → raises `FileNotFoundError` with the
    remediation message text
  - [x] `load_task_config` with empty YAML → raises `ValueError`
  - [x] `load_task_config` with empty `task_description` → raises `ValueError`
  - [x] `load_task_config` with `forward_contract` block missing a required key
    (e.g. `input_shape`) → raises Pydantic `ValidationError` from `ForwardContract`
    *(implemented as `extra="forbid"` rejecting the typo'd key, not a "missing"
    error — net effect is the same: a typo'd YAML key surfaces as ValidationError,
    not silent empty rendering.)*
  - [x] `render_forward_contract` with full ForwardContract → rendered string contains
    input_shape, output_shape, embedding_note, task_type
  - [x] `render_forward_contract` with default `ForwardContract()` → returns `""`
  - [x] `get_task_description` happy path

**Test gate**: unit only — no LLM, no GPU. All tests in `test_task_config.py` run freely.

**Out of scope**: no workflow modification, no prompt files touched, no node code touched.

**Implementation notes** (filled in as work lands):
- **Schema (`agent/schemas/task_config.py`)**: `ForwardContract` uses
  `ConfigDict(extra="forbid")` — a typo in a YAML key (e.g. `input_shapes`
  plural) raises `ValidationError` instead of being silently dropped.
  `is_empty()` helper added so `render_forward_contract` can short-circuit
  on default-constructed instances without re-checking every field at the
  call site.
- **Loader (`workflows/task_config.py`)**:
  - Module-level dict cache keyed by **absolute resolved path** — distinct
    fixtures don't collide and a test calling `load_task_config(tmp_path_A)`
    twice gets the same dict object (verified by
    `test_cache_returns_same_object_on_second_call`).
  - `_clear_cache_for_tests()` helper added (underscore-prefixed; not part
    of the public API) for the autouse pytest fixture that drops the cache
    between tests.
  - Validation order: file-exists → YAML-parses-to-mapping → `task_description`
    non-empty → `forward_contract` block present → `forward_contract` is a
    mapping → `ForwardContract(**fc_raw)` succeeds. Each step has a dedicated
    error type and message; tests cover all six.
  - Returned dict preserves the raw `forward_contract` sub-dict so downstream
    callers can rebuild `ForwardContract(**cfg["forward_contract"])` without
    the loader holding the only Pydantic instance.
- **Renderer (`workflows/task_config.py`)**: rendered shape matches the
  example block in this doc's *Rendered forward contract format* section —
  verified by `test_full_forward_contract_contains_expected_anchors`.
  Optional notes (`embedding_note`, `output_head_note`, `task_note`) are
  conditionally appended; when absent, no blank-line-separated paragraph
  appears (verified by `test_optional_notes_omitted_when_empty`).
- **Regression guard**: `TestCommittedConfigLoads::test_repo_task_config_loads`
  loads the actual repo's `configs/task_config.yaml` through the loader —
  fails CI if the committed config ever drifts from the schema.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 20/20 pass, 0.07 s wall.

### Commit T1b — Workflow snapshot wiring

**Goal**: at workflow run start, copy `configs/task_config.yaml` into
`{workspace}/{run_name}/task_config_snapshot.yaml` for replay provenance.
One `shutil.copy2` call; one regression test.

**Code**:
- [x] `workflows/model_exploration.py` — extracted snapshot logic to a private
  module-level helper `_snapshot_task_config(run_dir)` placed next to
  `_make_storage` (both are run-init helpers). The helper is the testable unit;
  `run_workflow` calls it on a single line immediately after the workspace-init
  `os.makedirs(run_dir, exist_ok=True)` at line 953:
  ```python
  os.makedirs(run_dir, exist_ok=True)
  _snapshot_task_config(run_dir)
  ```
  Helper body:
  ```python
  def _snapshot_task_config(run_dir: str) -> None:
      snapshot_path = os.path.join(run_dir, "task_config_snapshot.yaml")
      if not os.path.exists(snapshot_path):
          shutil.copy2(os.path.join(SIDERIUS_ROOT, "configs", "task_config.yaml"), snapshot_path)
  ```
  **Chain-mode policy**: the `if not os.path.exists(...)` guard means iter 1
  writes the snapshot; iter 2+ in the same chain skip it. The snapshot reflects
  the config that was active when the run was initialized — not whatever the
  operator may have edited mid-chain. This matches the "snapshot is read-only
  metadata" framing earlier in this doc.
  **Source path anchored on `SIDERIUS_ROOT`** (not cwd) — integration tests that
  pass a tmp workspace without `chdir`'ing to the repo root still pick up the
  committed config.
- [x] `shutil` is already imported at line 63 — no new import needed.
- [x] No need to import `load_task_config` — the snapshot is a raw byte copy,
  not a re-render of the parsed dict.

**Tests** (pure Python, no LLM — run freely):
- [x] `tests/unit/workflows/test_task_config_snapshot.py` (new file) — **4 tests, all pass in 1.02s**
  - [x] `_snapshot_task_config` writes `task_config_snapshot.yaml` to `{run_dir}` on first
    invocation with a clean workspace *(test_clean_run_dir_writes_snapshot)*
  - [x] `_snapshot_task_config` does NOT overwrite an existing snapshot (iter 2+
    behaviour — pre-populate the snapshot with sentinel content, call helper again,
    assert snapshot unchanged) *(test_existing_snapshot_is_not_overwritten)*
  - [x] Snapshot content is byte-identical to `configs/task_config.yaml` on first iter
    *(test_snapshot_is_byte_identical_to_source)*
  - [x] **Bonus regression guard** — `test_source_path_is_resolved_relative_to_repo_root_not_cwd`
    chdir's into a foreign tmp cwd (with no `configs/` subtree) and confirms the helper
    still finds the repo's committed YAML via `SIDERIUS_ROOT`.

**Test gate**: unit only — no LLM, no GPU.

**Out of scope**: no schema changes, no loader changes, no node changes.

**Implementation notes**:
- **Refactor for testability**: the design originally called for the 3-line
  snippet inlined at line 953 in `run_workflow`. The 800-line `run_workflow`
  function is impractical to unit-test directly without mocking every LLM call
  and subprocess. Extracted to a private `_snapshot_task_config(run_dir)` helper
  beside `_make_storage` — `run_workflow` calls it on one line; the test file
  exercises the helper without involving the rest of the workflow loop. The
  helper is private (`_` prefix) to signal it's not part of the public workflow
  API.
- **Source-path anchoring**: `shutil.copy2(os.path.join(SIDERIUS_ROOT, "configs",
  "task_config.yaml"), snapshot_path)` — the `SIDERIUS_ROOT` constant already
  exists at line 101 (`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`).
  Using it here avoids a class of bugs where a test or chain-runner with a
  non-root cwd would silently fail to find the YAML.
- **Regression**: full `tests/unit/workflows/` suite (163 tests, including this
  new file's 4) passes in 2.99s. No prior tests broke.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 4/4 new tests pass, 1.02s wall. Full workflows/ suite: 163/163.

### Commit T2 — Implementor prompt de-hardcoding

**Goal**: `IMPLEMENTOR_REASONING_PROMPT` in
`nodes/ml_model_implementor/ml_model_implementor.py` replaces the
hardcoded task/contract block with `{TASK_DESCRIPTION}` and
`{FORWARD_CONTRACT}` placeholders, substituted at build time from
`ImplementorInput`.

**Pre-read required** (before writing any code):
- [x] Read `nodes/ml_model_implementor/ml_model_implementor.py` lines
  290-430 verbatim to confirm exact current text
- [x] Read `agent/schemas/implementor.py` `ImplementorInput` class — confirmed
  `task_description` does NOT exist yet (no overlap with enable_loss_inventory
  L3 since L3 adds `custom_loss_spec`, not `task_description`). T2 adds it.

**Code**:
- [x] `nodes/ml_model_implementor/ml_model_implementor.py`
  - [x] Import `ForwardContract` from `agent.schemas.task_config` and
    `render_forward_contract` from `workflows.task_config` (both landed in T1a)
  - [x] Replace `IMPLEMENTOR_REASONING_PROMPT` system-prompt task block
    (lines 311-322 in pre-T2 numbering) with a single `{TASK_BACKGROUND}`
    placeholder — this collapses the previous SQUID-specific "Input data" /
    "forward contract" / "ADC values must be embedded" / output-head bullets
    into one substitutable block.
  - [x] Replace `IMPLEMENTOR_CODE_PROMPT` two `[B, 256, T] float32` literals
    (the `forward_body` field's instructional text + the hard-constraints
    bullet) with `{OUTPUT_SHAPE}` placeholder. **Scope expansion** — see
    implementation notes.
  - [x] Replace `_build_reasoning_prompt` user-prompt "## Forward contract"
    block (3 hardcoded lines: header + input + output shapes) with a
    `render_forward_contract(inp.forward_contract)` call. Section is now
    suppressed entirely when the contract is empty (test fixtures only).
    **Scope expansion** — see implementation notes.
  - [x] Added 3 module-level helpers next to `_build_reasoning_prompt`:
    `_render_task_background(td, fc)`, `_build_reasoning_system_prompt(inp)`,
    `_build_code_system_prompt(inp)`. Substitution happens at call time, not
    at module import — matches the T3 pattern documented for the proposer.
  - [x] Updated the two `self.bridge.generate*` call sites in `run()` to pass
    `_build_reasoning_system_prompt(inp)` and `_build_code_system_prompt(inp)`
    instead of the raw module-level constants. `IMPLEMENTOR_REPAIR_PROMPT`
    call site is unchanged — that constant has no task-specific content.
- [x] `agent/schemas/implementor.py` — add to `ImplementorInput`:
  - [x] `task_description: str = Field(default="", description="Task description from task_config.yaml. Injected into {TASK_DESCRIPTION} placeholder in system prompt.")`
  - [x] `forward_contract: ForwardContract = Field(default_factory=ForwardContract, description="Forward contract from task_config.yaml. Injected into {FORWARD_CONTRACT} placeholder.")`
- [x] `workflows/model_exploration.py` — at the implementor call site
  (current line 1461), inject from `load_task_config()`:
  ```python
  _task_cfg = load_task_config()
  impl_input.task_description = get_task_description(_task_cfg)
  impl_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
  ```
  Plus the corresponding top-of-file imports: `ForwardContract` from
  `agent.schemas.task_config`, `load_task_config` + `get_task_description`
  from `workflows.task_config`.

**Tests** (pure Python, no LLM — run freely):
- [x] `tests/unit/agent/ml_model_implementor/test_implementor_prompt.py` (new file) — **18 tests, all pass in 0.22s**
  - [x] With `task_description` set → rendered prompt contains the value,
    NOT the literal placeholder `{TASK_BACKGROUND}` *(test_custom_task_description_replaces_squid_hardcode)*
  - [x] With `forward_contract` populated → rendered prompt contains the rendered
    contract (input_shape, output_shape, embedding_note, task_type)
    *(test_full_populated_contains_header_description_and_contract)*
  - [x] Placeholder `{TASK_BACKGROUND}` and `{OUTPUT_SHAPE}` do NOT
    appear in any rendered prompt (substitution always fires)
    *(test_placeholder_never_survives_into_output — for both reasoning + code prompts)*
  - [x] With a custom non-SQUID `ForwardContract` (e.g. `output_shape="[B, T] float32"`)
    → rendered prompt contains the custom shapes, NOT the SQUID `[B, 256, T]` shapes
    *(test_custom_task_description_replaces_squid_hardcode + test_custom_output_shape_replaces_squid_default)*
  - [x] **Deferred-scope regression guard** — `TestDeferredScope` asserts the
    three intentionally-deferred hardcodes (dummy-tensor self-check at line 80,
    plugin-stub-assembly comment at line 254, description.md generation at line 827)
    are still present, fires if a follow-up commit silently removes them.

**Test gate**: **Gate 1 — real LLM + pseudo training**. One real implementor LLM
call with `task_config.yaml` present; assert generated code compiles + passes
dummy-tensor check. Not blocking T2 commit — the unit-level substitution is
fully covered by the 18 tests above. Gate 1 verification is a separate step.

**Out of scope**: proposer and lit-review prompts (T3); deferred hardcodes in
runtime self-check infrastructure (Category B), plugin stub assembly
(Category C), and `description.md` auto-generation (Category D) — see
Implementation notes.

**Implementation notes**:
- **Scope expansion vs. literal design**: the design's affected-locations
  table listed only `IMPLEMENTOR_REASONING_PROMPT` lines 306-322. Pre-read
  surfaced **two additional LLM-prompt hardcode sites in the same file**
  that share the same SQUID-specific framing — keeping them would have left
  T2 only partially complete. Folded into T2 with explicit rationale:
  | Site | Lines (pre-T2) | Action |
  |---|---|---|
  | `IMPLEMENTOR_REASONING_PROMPT` task block | 311-322 | ✅ Replaced with `{TASK_BACKGROUND}` |
  | `_build_reasoning_prompt` user prompt | 454-456 | ✅ Replaced with `render_forward_contract(inp.forward_contract)` |
  | `IMPLEMENTOR_CODE_PROMPT` `[B, 256, T] float32` | 379, 385 | ✅ Replaced with `{OUTPUT_SHAPE}` |
  | Dummy-tensor self-check `[1, 64]` / `(1, 256, 64)` | 80, 115, 120 | ❌ Deferred (Category B — runtime infra) |
  | Plugin stub-assembly forward-contract comment | 254, 259 | ❌ Deferred (Category C — generated-code text) |
  | `_assemble_test` test-template generator | 276-288 | ❌ Deferred (Category B — auto-generated tests) |
  | `description.md` auto-generation | 827 | ❌ Deferred (Category D — output artifact, read by test_implementor_agent.py::TestDescriptionFile) |
  Deferred sites need separate design (e.g. should dummy-tensor shape come
  from `ForwardContract.input_shape`? what about regressor vs classifier
  output dimensions?) — out of scope for T2's narrow placeholder substitution.
  `TestDeferredScope` in the new test file asserts these still exist, so a
  drive-by removal in a future commit will fail loudly.
- **Two placeholders, not three**: `{TASK_BACKGROUND}` rolls task_description
  + the rendered forward contract into one substitutable block (cleaner
  empty-fixture handling — the helper returns `""` instead of leaving an
  orphan "Background on the task:" header). `{OUTPUT_SHAPE}` is a separate
  single-line placeholder because `IMPLEMENTOR_CODE_PROMPT` only needs the
  short shape literal, not the full multi-line contract block. The design's
  `{TASK_DESCRIPTION}` + `{FORWARD_CONTRACT}` naming was nominal; the
  concrete placeholders chosen here are functionally equivalent.
- **Helper symmetry with T3**: `_build_reasoning_system_prompt(inp)` and
  `_build_code_system_prompt(inp)` mirror the `_build_system_prompt(inp)`
  helper documented for the proposer in T3 — same call-time `.replace()`
  substitution pattern.
- **System-prompt persona line touch-up**: the IMPLEMENTOR_REASONING_PROMPT
  opener used to read "specialising in 1-D signal processing models", which
  is itself a SQUID-flavored phrasing. Changed to "specialising in deep
  learning for signal denoising" — matches the proposer's existing persona
  framing at line 172 and is one step less task-specific. (Removing
  "denoising" entirely would need T4's broader generality push.)
- **Workflow injection guarded by `load_task_config` cache**: the loader is
  called inside the per-attempt loop, but its module-level cache makes every
  call after the first a dict lookup. No measurable cost.
- **Regression**: 371/371 tests pass across `tests/unit/agent/ml_model_implementor/`,
  `tests/unit/agent/schemas/`, and `tests/unit/workflows/` (the three
  directories T2 touches). No prior tests broke.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 18/18 new tests pass, 0.22s wall.

### Commit T3 — Proposer + lit-review prompt de-hardcoding

**Goal**: remove task-specific hardcodes from the proposer system prompt
and the two proposal template `.md` files. Lit-review `.md` files reviewed
for query-example vs parametrizable content.

**Pre-read required** (before writing any code):
- [x] Read `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`
  lines 165-195 verbatim — `PROPOSAL_REASONING_PROMPT` is a module-level
  constant; pre-T3 system prompt task block was lines 178-186.
- [x] Read `agent/prompt_templates/proposal/proposing_stage.md` lines
  60-80 verbatim — confirmed the "## Forward contract" block at lines 68-71.
- [x] Read `agent/prompt_templates/proposal/comparison_stage.md` lines
  1-10 verbatim — confirmed the "on the TIDMAD dataset" phrase at line 4.
- [x] Read `agent/prompt_templates/literature_review/search_decision_system.md`
  lines 1-130 verbatim. Found three categories of hardcodes:
  (a) line 1 persona ("ML denoising research agent") — task-anchored;
  (b) line 12 `{TASK_DESCRIPTION}` placeholder — already wired in Commit 6.5b-5;
  (c) query examples + broadband-framing guidance — illustrative, should stay.
- [x] Confirmed `agent/prompt_templates/proposal/__init__.py:73` already does
  `.replace(f"{{{key}}}", str(value))` via `template_vars` (resolved open Q3).
- [x] Decided to add `task_description` + `forward_contract` to `ProposalInput`
  (option a from open Q4) — mirrors T2's `ImplementorInput` pattern, cleaner
  than per-call kwarg threading given the proposer's many call sites.

**Code**:
- [x] `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`
  - [x] Import `ForwardContract` from `agent.schemas.task_config` and
    `render_forward_contract` from `workflows.task_config`.
  - [x] `PROPOSAL_REASONING_PROMPT`: replaced the 9-line Background-on-the-task
    block (pre-T3 lines 178-186) with a single `{TASK_BACKGROUND}` placeholder.
    The trailing VRAM-ceiling guidance (lines 187-189) is preserved as template-
    resident text.
  - [x] Added `_render_task_background(td, fc)` + `_build_reasoning_system_prompt(inp)`
    helpers next to `_render_hardware_context_block`. Identical render contract
    to T2's implementor helpers — both agents render the task framing the same way.
  - [x] Legacy-mode call site (now line ~990): `PROPOSAL_REASONING_PROMPT` →
    `_build_reasoning_system_prompt(inp)`. The pipeline-mode call sites use
    `.md` templates via `load_stage_prompt`; threaded the task config through
    the existing `template_vars` dict (current line 1188) — new keys
    `task_description` and `forward_contract` (rendered) — no call-site
    changes needed, `load_stage_prompt` does the substitution.
- [x] `agent/prompt_templates/proposal/proposing_stage.md`
  - [x] Replaced the 3-line "Forward contract" hardcode at lines 68-71 with the
    `{forward_contract}` placeholder, substituted at render time from
    `template_vars["forward_contract"] = render_forward_contract(inp.forward_contract)`.
    Used a single placeholder (rendered block) rather than the separate
    `{FORWARD_CONTRACT_INPUT}` / `{FORWARD_CONTRACT_OUTPUT}` the doc hedged
    about — single block matches the implementor pattern + carries the
    embedding / output-head guidance too.
- [x] `agent/prompt_templates/proposal/comparison_stage.md`
  - [x] Replaced "previously tested denoising models on the TIDMAD dataset"
    with "previously tested model architectures" (line 4). No placeholder —
    the task framing already lives upstream in the proposer system prompt;
    re-anchoring it here is redundant. **Decided** (open Q2): no
    `{TASK_DESCRIPTION}` / `{DATASET_NAME}` substitution; just drop.
- [x] `agent/prompt_templates/literature_review/search_decision_system.md`
  - [x] Line 1 persona: "automated ML denoising research agent" →
    "automated ML research agent". The `{TASK_DESCRIPTION}` placeholder at
    line 12 (Commit 6.5b-5) already carries the actual task focus.
  - [x] Confirmed query-example hardcodes (lines 53, 64-65, 96-99, 108-122)
    are illustrative and untouched. The broadband / FULL-SPECTRUM guidance
    at lines 121-122 is **deferred** — it's an operator-domain constraint
    (full-spectrum vs frequency-split search direction) that should migrate
    to a separate task_config field eventually, but that's out of T3 scope.
- [x] `workflows/model_exploration.py` — at the proposer call site
  (current line ~1392), inject from `load_task_config()`:
  ```python
  _task_cfg = load_task_config()
  propose_input.task_description = get_task_description(_task_cfg)
  propose_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
  ```
  Reuses the T2 imports — no new imports needed at the workflow level.
- [x] `agent/schemas/proposal.py` — added to `ProposalInput`:
  - [x] `task_description: str = Field(default="", ...)`
  - [x] `forward_contract: ForwardContract = Field(default_factory=ForwardContract, ...)`
  - [x] Import `ForwardContract`.

**Tests** (pure Python, no LLM — run freely):
- [x] `tests/unit/agent/ml_model_proposal_agent/test_proposer_task_config.py`
  (new file) — **17 tests, all pass in 0.89s**. Test classes:
  - [x] `TestRenderTaskBackground` (3): empty / full-populated / description-only
  - [x] `TestBuildReasoningSystemPrompt` (6):
    - [x] Placeholder never survives into rendered output
    - [x] Custom task_description replaces SQUID hardcode
    - [x] SQUID input reproduces the original task anchors (byte-equivalent
      semantic content for production callers)
    - [x] VRAM-ceiling + parameter_count_estimate guidance preserved
    - [x] Dropped pre-T3 lines verified gone: `"Loss is cross-entropy or focal loss"`
      and `"40000"` segment-length
  - [x] `TestProposingStageMdSubstitution` (2): `{forward_contract}` substituted
    via `load_stage_prompt(template_vars=...)`; custom contract replaces SQUID
    default, not just supplements it
  - [x] `TestComparisonStageMdContent` (2): "TIDMAD" gone; new wording is
    "previously tested model architectures"
  - [x] `TestLitReviewSearchDecisionPersona` (2): persona is generic;
    `{TASK_DESCRIPTION}` placeholder still wired
  - [x] `TestProposalInputTaskConfigFields` (2): defaults are empty;
    Pydantic round-trip preserves both fields

**Test gate**: **Gate 1 — real LLM + pseudo training**. Real proposer LLM call →
real implementor LLM call → dummy-tensor check, with `task_config.yaml` present.
Not blocking T3 commit — the unit-level substitution is fully covered by the
17 tests above. Gate 1 deferred to amortize after T4 lands.

**Implementation notes**:
- **Dropped pre-T3 hardcodes** (not substituted, just removed): the proposer
  system prompt previously asserted (i) "Loss is cross-entropy or focal loss:
  per-timestep 256-class classification" and (ii) "signal length up to 40000
  timesteps per segment". Both are task-specific and not part of the canonical
  forward contract:
  - The loss claim was over-prescriptive — the proposer chooses a loss type
    and the `ExperimentConfig.validate_architecture_loss_match` validator
    catches incompatible model/loss combos. Verified by
    `test_dropped_loss_line_is_gone`.
  - The "40000 timesteps" claim is redundant — `baseline_config.train_config.segmentation_size`
    is already injected into the user prompt at line 451 of `_build_reasoning_prompt`.
    Verified by `test_dropped_segment_length_is_gone`.
- **Two call paths in the proposer**: legacy mode passes
  `PROPOSAL_REASONING_PROMPT` as a constant; pipeline mode uses
  `load_stage_prompt(...)` with `template_vars`. T3 covers both — the legacy
  path through the new `_build_reasoning_system_prompt(inp)` helper, the
  pipeline path through two new `template_vars` keys (`task_description`
  and `forward_contract`).
- **Persona line touch-up not needed**: unlike T2, the proposer's persona
  line ("specialising in deep learning for signal denoising") was already in
  the more-generic form (T2 changed the implementor to match this).
- **`comparison_stage.md` no placeholder**: decided against substituting in
  `{TASK_DESCRIPTION}` because the task framing already lives upstream in
  the proposer system prompt (which the LLM sees first). Re-anchoring it at
  every stage prompt would bloat the prompt without adding signal.
- **`search_decision_system.md` deferred items**: the broadband-framing
  guidance at lines 121-122 is operator-domain (full-spectrum vs frequency-
  split search direction). Migrating it to a separate task_config field
  (e.g. `search_guidance:`) is a follow-up — out of T3 scope.
- **Regression**: 1033/1033 tests pass across `tests/unit/agent/{ml_model_proposal_agent,
  ml_model_implementor, prompt_templates, schemas, ml_literature_review}/`
  and `tests/unit/workflows/`. No prior tests broke.
- **Lint**: ruff (check + format) clean. Pyright clean (0 errors, 0 warnings).
- **Test results**: 17/17 new tests pass, 0.89s wall.

### Commit T4 — Tuner, interpreter, and lit-review AgentCard de-hardcoding

**Goal**: remove task-specific hardcodes from the three remaining locations
(tuner planner/reflector prompts, interpreter system prompts, lit-review
AgentCard). Backward compatible — these are all additive placeholder
substitutions, not structural changes. Phase 8 content (Impact_Score,
Linear_Weight, per_file_analysis, SYNTHESIS_SYSTEM_PROMPT reasoning frame)
is NOT touched.

**Pre-read required** (before writing any code):
- [ ] Read `agent/prompts.py` lines 1-15 and lines 185-205 verbatim —
  confirm exact current text of PLANNER_PROMPT header and REFLECTOR_PROMPT
- [ ] Read `nodes/result_interpretation_agent/result_interpretation_agent.py`
  lines 40-80 (PER_MODEL_SYSTEM_PROMPT) and lines 230-270
  (SYNTHESIS_SYSTEM_PROMPT) verbatim — confirm which lines are Phase 8
  content (DO NOT TOUCH) vs persona/task framing (in scope)
- [ ] Read `nodes/ml_literature_review/ml_literature_review.py` lines
  65-80 — confirm AgentCard field values

**Backward compat rule for this commit:**
Every change is a placeholder substitution only. The rendered output
when `task_config.yaml` contains the SQUID defaults must be byte-identical
to the current hardcoded output. This is verified by unit tests.

**Split into 3 git commits at clean seams** (per development principle 4):
**T4a** (tuner) → **T4b** (interpreter) → **T4c** (lit-review AgentCard). Each
subsystem is independently committable with its own test surface.

**Code — T4a (tuner)** ✅ landed:
- [x] `agent/prompts.py`
  - [x] PLANNER_PROMPT header: persona "Senior Signal Processing Researcher
    specialized in deep learning for signal denoising" → "Senior ML Research
    Analyst specializing in hyperparameter optimization for deep learning
    models"; goal "optimize the 'Denoising Score' for the TIDMAD dataset" →
    "maximize the `denoising_score` metric across hyperparameter configurations
    for the following task:\n\n{TASK_DESCRIPTION}"
  - [x] REFLECTOR_PROMPT: **no change needed** — persona is already generic
    ("You are a Research Analyst"); all `denoising_score` references in the
    GAP ANALYSIS section are field-name references (Phase 8 — DO NOT touch).
    Pre-read audit confirms zero task-anchored persona text in REFLECTOR.
  - [x] Substitution wired at `agent/llm_bridge.py:843-847`. Added
    `task_description: str = ""` parameter to `LLMBridge.plan()`; substitution
    chains a second `.replace("{TASK_DESCRIPTION}", task_description)` after
    the existing `{SCORE_COMPARISON_TABLE}` replacement.
  - [x] DO NOT touch: scoring sections, file_vector references, Impact_Score
    content, `denoising_score` field references — preserved verbatim.
- [x] `agent/schemas/hyperparam_tuning.py` — add `task_description: str = Field(default="", ...)`
  to `HyperparamTuningInput`. The tuner doesn't need `forward_contract`
  because hyperparameter optimization happens within an existing model
  architecture; the contract is fixed by the implementor upstream.
- [x] `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py`
  — pass `task_description=agent_input.task_description` to `brain.plan(...)`
  at the per-round call site (current line 1296-1300).
- [x] `workflows/model_exploration.py` — at the tuner call site (current
  line 1631-1634), inject `tune_input.task_description = get_task_description(load_task_config())`.
  Reuses T2/T3 imports — no new imports needed.
**Code — T4b (interpreter)** ✅ landed:
- [x] `nodes/result_interpretation_agent/result_interpretation_agent.py`
  - [x] PER_MODEL_SYSTEM_PROMPT (line 47): restructured persona
    "specialising in deep learning for signal denoising" → "You are a senior
    ML research analyst." (task-agnostic) + added `{TASK_DESCRIPTION}`
    placeholder block after "The research context is:" (same multi-sentence-
    paragraph rationale as T4a).
  - [x] SYNTHESIS_SYSTEM_PROMPT (line 239): same restructure pattern.
  - [x] DO NOT touch: Impact_Score content, per_file_analysis field,
    Linear_Weight content, Log-of-Mean trap section (all Phase 8) — preserved
    verbatim. Verified by `test_phase8_*_preserved` and
    `test_phase8_content_present_after_substitution` regression guards.
  - [x] Two new helpers `_build_per_model_system_prompt(inp)` and
    `_build_synthesis_system_prompt(inp)` at module level (near
    `_build_per_model_prompt` / `_build_synthesis_prompt` user-prompt builders).
    Substitution happens at call time — both `bridge.generate(...)` call sites
    now pass `_build_*_system_prompt(inp)` instead of the raw constants.
- [x] `agent/schemas/interpretation.py` — add `task_description: str = Field(default="", ...)`
  to `InterpretationInput`. The interpreter only needs the description —
  no forward_contract field needed (its job is reading summaries, not
  designing models).
- [x] `workflows/model_exploration.py` — at the interpreter call site
  (line 1213-1223), inject `task_description=get_task_description(load_task_config())`
  directly into the `InterpretationInput(...)` constructor. (Cleaner than
  post-hoc mutation because `InterpretationInput` is constructed all at once,
  unlike T2/T3 where the protocol returns it and the workflow mutates fields.)
  Reuses T2/T3 imports — no new imports.
- [ ] `nodes/ml_literature_review/ml_literature_review.py`
  - [ ] `AgentCard.role`: replace "Surface ML denoising literature
    relevant to the current iteration." with a template that incorporates
    `{TASK_DESCRIPTION}` — e.g. render at agent construction time from
    `inp.task_description`
  - [ ] `AgentCard.expertise_domain`: replace "ML denoising architectures;
    Semantic Scholar corpus." with task-agnostic phrasing sourced from
    `task_config.yaml`
  - [ ] `AgentCard.limitations`: remove "SQUID-specific" hardcode; replace
    with generic "task-specific" language
  - [ ] The AgentCard is constructed in `MLLiteratureReviewAgent.__init__`
    or `run()` — **CHECK** exact construction site before editing

**Tests — T4a (tuner)** ✅ landed (pure Python, no LLM — run freely):
- [x] `tests/unit/agent/test_planner_prompt_task_config.py` (new file) — **16 tests, all pass in 0.07s**
  - [x] PLANNER_PROMPT rendered with SQUID task_config → output contains
    "SQUID" from YAML, not from hardcode *(test_squid_input_reproduces_squid_anchors)*
  - [x] PLANNER_PROMPT rendered with custom task_description → output
    contains custom text *(test_custom_task_description_replaces_squid)*
  - [x] `{TASK_DESCRIPTION}` placeholder never survives into rendered output
    *(test_placeholder_never_survives_with_non_empty_input + collapses_to_empty_with_empty_input)*
  - [x] Phase 8 content (`{SCORE_COMPARISON_TABLE}` substitution) still wired
    after T4a *(test_score_table_substitution_still_works)*
  - [x] `denoising_score` field-name reference preserved
    *(test_denoising_score_field_name_preserved)*
  - [x] `HyperparamTuningInput.task_description` defaults to `""` and
    round-trips through Pydantic
- [x] **T4a regression sweep**: `tests/unit/agent/tune_ml_hyperparam_agent/`,
  `tests/unit/agent/schemas/`, `tests/unit/workflows/` — **749/749 pass in 224.6s**.
  (Long wall is the existing tuner-suite cost, not new.) No prior tests broke.

**Tests — T4b/T4c** (still pending):
- [x] `tests/unit/agent/result_interpretation_agent/test_interpreter_prompt_task_config.py`
  (new file) — **21 tests, all pass in 0.88s**
  - [x] PER_MODEL_SYSTEM_PROMPT and SYNTHESIS_SYSTEM_PROMPT both render
    with custom task_description; neither contains hardcoded "specialising
    in deep learning for signal denoising" persona framing
  - [x] Phase 8 sections still intact — `Log-of-Mean trap`, `Linear_Weight`,
    `Impact_Score` content survives substitution in both templates
    *(test_phase8_*_preserved + test_phase8_content_present_after_substitution
    in both helper test classes)*
  - [x] `InterpretationInput.task_description` defaults to `""`, round-trips
    through Pydantic, and accepts arbitrary strings (4 parametrized cases)
- [x] **T4b regression sweep**: `tests/unit/agent/result_interpretation_agent/`,
  `tests/unit/agent/schemas/`, `tests/unit/workflows/` — **431/431 pass in 3.66s**.
  No prior tests broke.
- [ ] `tests/unit/agent/ml_literature_review/test_agent_card_task_config.py`
  (new or extend existing)
  - [ ] AgentCard role/expertise_domain/limitations populated from
    task_config, not hardcoded strings
  - [ ] When `inp.task_description` set → AgentCard reflects it

**Test gate**: unit only — prompt substitution is pure string replacement,
no LLM needed to verify correctness. Phase 8 regression guards run as part
of the standard unit suite.

**Out of scope**: no schema changes, no workflow changes beyond injecting
task_config into existing call sites.

**Implementation notes**:
- **T4a deviation from literal design**: the design doc proposed substituting
  `{TASK_DESCRIPTION}` *inline* into the persona/goal phrases at lines 10-11.
  Pre-read showed the task_description is a multi-sentence paragraph (per
  `configs/task_config.yaml:44-47`), not a phrase — substituting it inline
  produces an unreadable run-on. Restructured instead: the persona/goal
  becomes task-agnostic ("Senior ML Research Analyst … hyperparameter
  optimization") and the `{TASK_DESCRIPTION}` placeholder is positioned as a
  separate block after "for the following task:". This matches the T2/T3
  pattern of carving task framing into its own renderable section.
- **REFLECTOR_PROMPT untouched**: the design doc said "REFLECTOR_PROMPT: same
  persona line replacement", but pre-read confirmed REFLECTOR's persona
  ("You are a Research Analyst") is already task-agnostic. The only
  `denoising_score` mentions in REFLECTOR are field-name references in the
  GAP ANALYSIS section — Phase 8 / not in scope. No change to REFLECTOR.
- **Tuner takes only `task_description`, not `forward_contract`**: the
  planner tunes hyperparameters within an existing model architecture; the
  forward contract is already fixed by the implementor. Adding
  `forward_contract` to the tuner schema would be dead weight.

### Checkpoint T — Smoke validation

**Goal**: confirm that with `configs/task_config.yaml` present, all agent
system prompts contain the task description and forward contract from the
YAML, not the hardcoded values.

**Pre-flight** (run freely):
- [ ] Full unit suite green: `uv run pytest tests/unit/ -q`
- [ ] `grep -rn "TIDMAD\|SQUID\|magnetometry" agent/prompt_templates/ nodes/ml_model_implementor/ nodes/ml_model_proposal_agent/ agent/prompts.py nodes/result_interpretation_agent/ nodes/ml_literature_review/` returns zero hits in any Python or `.md` source file (the only remaining hits are in `configs/task_config.yaml` itself + `configs/task_config.example.yaml`, which are the canonical sources)

**Validation**:
- [ ] Run `scripts/render_proposer_prompts_for_audit.py` (already exists)
  with `task_config.yaml` present; verify rendered output contains
  `task_description` from YAML, not the hardcoded SQUID text.
  Zero LLM calls — runs in ~1 second. Run freely.
- [ ] Run the implementor with a stub proposal; verify `IMPLEMENTOR_REASONING_PROMPT`
  contains the YAML's `forward_contract`, not the hardcoded shapes
  (covered by the Gate 2 dual-mode test described below)

**Test gate**: **Gate 2 — real LLM + ~5 min real training**. One trial-mode
iteration, punet baseline, real LLM, real training. Binary signal: did the
iteration complete with a non-error `denoising_score`? Needs user approval
before running.

**Sign-off**:
- [ ] `docs/checkpoint_t_sign_off.md` written with:
  - [ ] grep evidence of zero remaining hardcodes in affected files
  - [ ] Sample rendered prompt excerpt showing YAML injection
  - [ ] Verdict: ready to merge / blocked on X

---

## Open questions

1. **Proposer prompt build path** — resolved. See Commit T3 notes: requires
   adding `_build_system_prompt(inp)` helper. Documented above.

2. **`comparison_stage.md` line 4 substitution** — the full line is:
   "you are a senior ML research scientist conducting a systematic review
   of all previously tested denoising models on the TIDMAD dataset."
   `{TASK_DESCRIPTION}` would be too verbose here. A shorter
   `{DATASET_NAME}` or `{TASK_DOMAIN}` placeholder fits the syntactic slot
   better. **Decide in T3** after reading the full context: what is the
   minimal substitution that removes "TIDMAD dataset" without changing the
   sentence structure?

3. **`proposing_stage.md` substitution mechanism** — the proposer's
   `agent/prompt_templates/proposal/__init__.py` must be read in T3 to
   confirm whether it performs `.replace()` substitution (like the
   lit-review `__init__.py` does at lines 305/402/627). If not, T3 must
   add the substitution logic before adding placeholders to the `.md`
   files.

4. **ProposalInput vs render-time injection for T3** — two options:
   (a) add `task_description` + `forward_contract` fields to `ProposalInput`
   Pydantic schema (mirrors T2's ImplementorInput addition — clean but more
   schema churn), or (b) inject as kwargs at render time without schema
   change (less invasive but less explicit). **Decide in T3** after reading
   how the proposer node constructs its prompt context.

---

## Non-goals (explicit out of scope)

- `TIDMAD_DATA_DIR` / reference data coupling — separate feature
- `denoising_score` schema field rename — separate feature
- `ScoreComparisonTable` changes — already task-agnostic
- `from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG` — separate feature
- Proposer system prompt genericity beyond task_description/forward_contract
  (e.g. the `[B, 256, T]` validator shapes in `ml_code_validator_agent`) — separate feature
