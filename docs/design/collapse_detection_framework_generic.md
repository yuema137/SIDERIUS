# Collapse Detection Framework — Generic

- **Status**: active
- **Scope**: **generic** (applies to any ML task using SIDERIUS)
- **Owner**: TBD
- **Created**: 2026-07-15
- **Last Updated**: 2026-07-16

## 1. Purpose and scope

This document specifies how SIDERIUS detects **degenerate model outputs** —
outputs that produce a nominal "score" but carry no real learning signal.
The framework is task-agnostic: every mechanism described here is a
plug-in point that any ML task can compose without touching framework
code.

**In scope**:

- The abstract definition of degeneracy that all detection mechanisms
  share
- The `HealthCheckSkill` plugin interface (already implemented in
  `execute_tools/health_checks/protocol.py`)
- Generic detection building blocks: unique-value diversity,
  distribution mode-fraction, subnormal-noise guard, file-vector
  byte-identity, phantom fingerprint table, correlation guard
- Acceptance criteria the framework must satisfy to remain task-agnostic

**Out of scope**:

- Specific phantom scalar values (e.g. `5.5762667` for TIDMAD) — those
  live in per-task advice under `advice/` and in
  `reference_data/collapse_phantoms.json`
- Task-specific detection thresholds (e.g. "TIDMAD wavenet outputs
  should have `> 50` unique int8 values") — same
- Task-specific loss-collapse tendencies (e.g. "focal loss on TIDMAD
  favours class-127") — advice content, not framework code

## 2. Definition of degeneracy

**Generic definition**: model output is *degenerate* when its
distribution is statistically independent of the target — the score
computed on it reflects the scoring pipeline's response to the output's
own statistical structure rather than any input-target relationship the
model learned.

Four canonical categories that a task-agnostic framework must cover:

| Category | Signature | Example mechanism |
|---|---|---|
| **Constant-output collapse** | All output values are identical (single-mode delta distribution) | Classifier collapses to a fixed class; regressor outputs a fixed value |
| **Low-entropy collapse** | Output distribution is dominated by 1-few modes; effective vocabulary is a small fraction of the possible output alphabet | Classifier outputs 3 of 256 possible classes for 99% of samples |
| **Byte-identity across independent runs** | Two runs with different (model, loss, seed) tuples produce byte-identical output vectors | Multiple runs collapse to the same constant; scoring is fully determined by the constant, not the training |
| **Correlation collapse** | Output has finite variation but is uncorrelated with target | Model output tracks a fixed reference (e.g. one input channel passed through) instead of any function of the target |

The framework provides one or more detectors per category; a task adds
its own detectors via the `HealthCheckSkill` plugin surface without
modifying core code.

## 3. HealthCheckSkill plugin architecture

### 3.1 Protocol interface (existing)

Every check conforms to the Protocol defined in
`execute_tools/health_checks/protocol.py`:

```python
class HealthCheckSkill(Protocol):
    name: str
    description: str
    def run(self, ctx: HealthCheckContext,
                  config: dict | None = None) -> HealthCheckResult: ...
```

`HealthCheckContext` (schema in `execute_tools/health_checks/schemas.py`)
provides everything a check needs to inspect a round's output —
`model_name`, `run_name`, `round_index`, `denoised_output_path`,
`denoising_score`, etc. — with **no task-specific fields**.

`HealthCheckResult` carries `passed: bool` and `reason: str`; the
`GateAction` StrEnum (see §3.3 for the full member / value table) is
attached at the gate-runner level via YAML config.

### 3.2 Registration

New checks self-register at import time via the registry in
`execute_tools/health_checks/registry.py`. A task adds a check by
creating one file under `execute_tools/health_checks/` and importing it
from `__init__.py`. **No modifications to `runner.py`, `protocol.py`, or
`schemas.py` are required.**

### 3.3 Gate action semantics

The action a check *triggers* is decided by `configs/health_checks.yaml`,
not by the check itself. This decouples "how to detect" from "what to do
about it":

| Member name (Python) | Serialised value (JSON / YAML) | Meaning |
|---|---|---|
| `GateAction.CONTINUE` | `"continue"` | Detected but not blocking — logged and passed through |
| `GateAction.INVALIDATE_ROUND` | `"invalidate_round"` | Round's score is discarded; chain continues |
| `GateAction.SKIP_TO_FORMAL` | `"skip_to_formal"` | Skip remaining trial rounds; go straight to formal |
| `GateAction.SKIP_ITER` | `"skip_iter"` | Abort the iteration entirely |

**Nuance to watch**: `GateAction` is a `StrEnum`. Python code references
members by their uppercase name (`GateAction.CONTINUE`); serialised
records (`ExperimentRecord.gate_action`, YAML `on_pass.action` /
`on_fail.action`) store the **lowercase string value** (`"continue"`).
Consumers reading JSON records must compare against the string values,
not the member names. See
`execute_tools/health_checks/schemas.py::GateAction` for the
authoritative definition.

Severity resolution when multiple gates fire on one round:
`SKIP_ITER > SKIP_TO_FORMAL > INVALIDATE_ROUND > CONTINUE`.

See `docs/design/pluggable_health_checks.md` §4 for the full runner
contract.

## 4. Detection mechanisms (generic building blocks)

Each is a Protocol-conforming skill; specific parameters (thresholds,
window sizes) come from YAML config, not from code.

### 4.1 Output diversity check

**Category**: constant / low-entropy collapse.
**Signal**: `unique(output).size / total_output.size` below a
configurable threshold, OR mode-fraction above a threshold.
**Implementation**: `execute_tools/health_checks/output_diversity.py`
(already exists).

Task-agnostic because "unique values" is well-defined for any
finite-alphabet output (classifier logits' argmax, quantized regressor
output).

### 4.2 Amplitude / distribution mode-fraction check

**Category**: low-entropy collapse.
**Signal**: single most-common value accounts for a
task-configurable-threshold fraction of the output.
**Implementation**: `execute_tools/health_checks/amplitude_collapse.py`
(already exists).

Different from 4.1 in that it targets the *dominant-mode* case
specifically (e.g. 99% of outputs are one value with a few outliers) —
which 4.1 might miss if the outlier count is above the
unique-value threshold.

### 4.3 Noise-floor subnormal guard

**Category**: constant-output collapse (mathematical mechanism).
**Signal**: within a scoring pipeline that uses FFT/PSD on a
constant-valued time series, the noise-window sum drops into
floating-point subnormal territory (`< 1e-10`), and any `signal/noise`
ratio computed on it becomes a deterministic FP artifact rather than a
real SNR.
**Implementation**: `execute_tools/scoring_utils.py::get_snr` returns
`NaN` when `noise < 1e-10`; downstream `_collect_raw_pairs` filters NaN
segments.

**Generic principle**: any scoring pipeline that computes ratios of
small quantities derived from FFT of an input signal is vulnerable to
subnormal-noise ratios producing spurious deterministic outputs. The
guard is a general defence against this class of numerical artifact —
not a TIDMAD-specific mechanism, even though the class-127 phantom is
what first surfaced it.

### 4.4 File-vector byte-identity dedup (Layer 1)

**Category**: byte-identity across independent runs.
**Signal**: two runs with different `(model, loss, seed)` tuples produce
`hash(file_vector) == hash(file_vector_other)`.
**Implementation**: **not yet built** — tracked as MUST-fix **M1** (see
[v17_priorities.md](./v17_priorities.md) MUST-fix M1), issue #108.

**Generic mechanism**: a chain-scoped set of `sha256(file_vector)`
hashes; every new score's file_vector is hashed and compared. Collision
across runs of different provenance is impossible for real training —
it can only happen when both runs produce the same output (i.e. output
is signal-independent). Catches all collapse constants including ones
we haven't catalogued.

**Scope clarifications**:

- **Chain-scoped**: dedup state is maintained per chain (one iteration =
  one chain). Cross-chain dedup is not part of M1 — it belongs to the
  future Run Monitor (issue #100) with a persistent store.
- **Seed handling**: file_vectors injected via `--seed_paths` from prior
  runs are excluded from dedup comparison. Seeds may legitimately
  contain historical phantoms (documented artifacts) without triggering
  dedup on new-round outputs that happen to match. Only file_vectors
  produced by rounds within the current chain participate in the hash
  set.
- **Hash format**: `sha256(numpy_array.tobytes())` where
  `numpy_array = np.array(file_vector, dtype=np.float64)`. This is
  what makes byte-identity truly byte-level, not just "close in value."

### 4.5 Phantom fingerprint table (Layer 2)

**Category**: constant-output collapse to a known constant.
**Signal**: a run's file_vector or scalar score matches a value in a
precomputed table of `constant K → resulting score` fingerprints for the
task's scoring formula.
**Implementation**: **not yet built** — tracked as MUST-fix **M4** (see
[v17_priorities.md](./v17_priorities.md) MUST-fix M4), issue #109.

**Framework contract**: the table itself lives at
`reference_data/collapse_phantoms.json` (data, not code) with the
schema:

```json
[
  {
    "task": "<task_name>",
    "output_type": "<classifier|regressor|...>",
    "constant_k": <value | null>,
    "resulting_score": <float>,
    "resulting_grand_mean": <float | null>,
    "resulting_file_vector_hash": "<sha256>",
    "notes": "<free-text mechanism description>"
  }
]
```

Both `resulting_grand_mean` and `resulting_file_vector_hash` carry
diagnostic value — grand_mean lets an operator sanity-check the score
via the inverse formula (`log_base(grand_mean)`), while the file_vector
hash enables exact matching before scoring is even computed. Keeping
both makes the table more useful for triage.

This is the **authoritative schema**;
`docs/design/tidmad_collapse_advice_and_forensics.md` §2.3 references
it and populates TIDMAD-specific entries.

The checker reads this table and rejects any score that matches within a
task-configurable tolerance. **Zero fingerprint values are hardcoded in
Python.**

### 4.6 Correlation-based scoring guard (Layer 4, future)

**Category**: correlation collapse.
**Signal**: `pearson_correlation(denoised, target)` below a
task-configurable epsilon on a per-file basis.
**Implementation**: **not yet built** — tracked as SHOULD-fix **S3** (see
[v17_priorities.md](./v17_priorities.md) SHOULD-fix S3).

Provides post-hoc detection of the "output has variation but isn't
learned" case (which byte-identity dedup misses because the vector
varies per file). Generic because pearson correlation is well-defined
between any two continuous sequences.

### 4.7 Multi-file peek pattern (generic framework capability)

**Category**: aggregation-across-files strategy for any check whose
per-file measurement can be computed independently.
**Implementation**: `execute_tools/health_checks/_multi_file_peek.py` —
`peek_and_aggregate(ctx, peek_file_indices, metric_fn, predicate,
aggregation, peek_samples, channel)`. Adopted M9 (2026-07-16).

The pattern refactors the pre-M9 single-file peek shape into a
per-file `metric_fn` + `predicate` pair plus a batch-level
`aggregation`. Each blocking check declares its own metric and
threshold-direction predicate; the helper handles file resolution,
I/O errors, and aggregation uniformly. Task-agnostic — nothing in
the helper knows about TIDMAD.

**Threshold direction as a predicate concern.** The helper does not
own a `threshold_direction: min | max` YAML knob. Instead, each
check's `predicate` callback expresses the pass condition directly:

  * `output_diversity`: `predicate = lambda m: m > threshold`
    (min-threshold direction — pass when the metric exceeds a floor).
  * `output_std`: `predicate = lambda m: m >= threshold` (min-threshold,
    inclusive at the boundary).
  * `amplitude_collapse`: `predicate = lambda m: m <= threshold`
    (max-threshold direction — pass when the metric stays under a
    ceiling; dominant_fraction < 0.95 is healthy).

This keeps the helper generic — the check author picks the direction
by writing the predicate. A YAML `threshold_direction` field would
only encode information the check already has to declare in code
anyway.

**Supported aggregation modes** (see `AggregationMode` in
`_multi_file_peek.py`):

| Mode | Verdict rule | I/O failure handling |
|------|-------------|----------------------|
| `any_pass` | at least one per-file `passed=True` | dropped from population |
| `all_pass` | every per-file `passed=True` | counts as fail (strictest) |
| `max` | apply predicate to `max(metric_values)` | dropped from aggregate |
| `min` | apply predicate to `min(metric_values)` | dropped from aggregate |
| `mean` | apply predicate to `mean(metric_values)` | dropped from aggregate |
| `median` | apply predicate to `median(metric_values)` | dropped from aggregate |

**Backward compat**: an empty `peek_file_indices` list falls back to
`[min(ctx.denoised_paths.keys())]` (or `[0]` when the dict is empty).
Existing YAML entries that don't specify `peek_file_indices` continue
to behave as pre-M9 single-file peek.

**Empirical basis** for the concrete `peek_file_indices` choice used
in the shipped TIDMAD YAML: [`paper_and_collapse_reference_baselines.md`
§6.4](./paper_and_collapse_reference_baselines.md). The framework
itself is agnostic — future tasks pick their own triplet (or single, or
per-check custom set).

## 5. Acceptance criteria for this framework

The framework is task-agnostic iff **all** of the following hold:

1. A new task can add a `HealthCheckSkill` by creating one file under
   `execute_tools/health_checks/` and one entry in
   `configs/health_checks.yaml` — **no modifications** to
   `runner.py`, `protocol.py`, `schemas.py`, or the registry.
2. The framework catches at least the four canonical degeneracy
   categories: constant output, low-entropy output, byte-identity
   across runs, known-phantom fingerprint match.
3. **Zero task-specific values are hardcoded** in
   `execute_tools/health_checks/*.py` or `agent/schemas/`. All
   thresholds, phantom values, tolerance parameters come from YAML
   config or JSON data files.
4. The `HealthCheckContext` schema contains no task-specific fields.
   Adding a task never requires extending the context schema.
5. Removing a task from the config removes its detectors from the
   runtime chain without touching any Python file.
6. **Observability**: every fired check must record `check_name`,
   `failure_reason`, and resolved `gate_action` in a structured field
   of `ExperimentRecord` that is machine-readable without parsing
   Python source. External tools (JSON queries, log grep) must be able
   to answer "which check fired on which round?" from the on-disk
   record alone.

## 6. What lives in advice, not here

The following are **task-specific** and belong in
`advice/workflow/<task>_*.json` or `reference_data/`, never in
`execute_tools/health_checks/` code:

- Specific phantom scalar values (e.g. `5.5762667` for TIDMAD)
- Task-specific thresholds (e.g. "wavenet outputs need `>= 50` unique
  int8 values")
- Task-specific loss / architecture collapse tendencies (e.g. "focal
  loss on TIDMAD data drives collapse to class-127")
- Task-specific advice for the proposer on how to recover from
  collapse (e.g. "if class-127 collapse, try `alpha=0.5`, `lr=5e-4`")
- Task-specific reference scores (e.g. "official wavenet weights score
  -2.47 under SIDERIUS scoring")

See `docs/design/tidmad_collapse_advice_and_forensics.md` for how
TIDMAD-specific content is factored out of the framework.

## 7. Bad-vs-good example

### Anti-pattern: hardcoded task-specific constants in framework code

```python
# execute_tools/health_checks/phantom_score_check.py  — BAD
KNOWN_PHANTOMS = {5.5762667: "class-127", 6.3556: "second_cluster"}  # ← TIDMAD-only

class PhantomScoreCheck:
    name = "phantom_score"
    def run(self, ctx, config=None):
        if any(abs(ctx.denoising_score - p) < 0.001 for p in KNOWN_PHANTOMS):
            return HealthCheckResult(passed=False, reason="known phantom")
        return HealthCheckResult(passed=True, reason="clean")
```

**Why it's bad**: framework file now knows about TIDMAD. Adding a
second task requires editing this file. Framework is no longer
task-agnostic.

### Correct pattern: config-injected generic version

```python
# execute_tools/health_checks/phantom_score_check.py  — GOOD
class PhantomScoreCheck:
    name = "phantom_score"
    def run(self, ctx, config=None):
        cfg = config or {}
        table_path = cfg.get("phantom_table_path",
                             "reference_data/collapse_phantoms.json")
        tolerance = cfg.get("tolerance", 0.001)
        with open(table_path) as f:
            phantoms = json.load(f)
        # Optionally filter by task
        task = cfg.get("task")
        if task:
            phantoms = [p for p in phantoms if p.get("task") == task]
        for p in phantoms:
            if abs(ctx.denoising_score - p["resulting_score"]) < tolerance:
                return HealthCheckResult(passed=False,
                                         reason=f"phantom: {p.get('notes', '')}")
        return HealthCheckResult(passed=True, reason="clean")
```

```yaml
# configs/health_checks.yaml  — task binding, not code
- name: phantom_score_tidmad
  check: phantom_score
  config:
    task: tidmad
    phantom_table_path: reference_data/collapse_phantoms.json
    tolerance: 0.001
  after_round: every
  on_fail: INVALIDATE_ROUND
```

**Why it's good**: framework file knows nothing about any specific
task. A new task adds a YAML block; framework code is untouched.

## 8. Related docs

- `docs/design/pluggable_health_checks.md` — the parent design doc for
  the HealthGate runner and protocol; this doc extends it with the
  generic-detection perspective and specifies the acceptance criteria
  for task-agnosticism.
- `docs/design/structured_feedback_loop_experiment_to_proposer.md` —
  once detection fires, the resulting `gate_action` and
  `failure_reason` fields need to flow to the interpreter and
  proposer. That signal-flow contract is defined there.
- `docs/design/tidmad_collapse_advice_and_forensics.md` — the concrete
  TIDMAD-specific instantiation of what this framework promises to
  keep out of code. Read that for what NOT to add here.
- [`docs/design/v17_priorities.md`](./v17_priorities.md) — tracks
  **M1** (file-vector dedup), **M2** (MRS collapse-signal wiring),
  **M4** (phantom table), **M5** (iter 4 R4 forensic), **M7**
  (loss-implementor bug), and **S3** (correlation guard) as v17
  MUST/SHOULD-fix items relevant to this doc.
- Related open issues: #108 (M1), #109 (M4), #110 (6.3556 phantom
  coverage), #93 (M3 adaptive training regime), #95 / #107 (M2),
  #112 (M7).
