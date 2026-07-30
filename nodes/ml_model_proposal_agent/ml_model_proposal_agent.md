# MLModelProposalAgent

> Reads the structured interpretation from `result_interpretation_agent` and proposes a new neural architecture that addresses the identified bottlenecks. Supports two modes: a 2-call legacy chain-of-thought (reasoning → commit) and a 3-stage configurable pipeline (comparison → causal reasoning → proposing) for production runs.

## Position in the pipeline

- **Node type**: **standalone-capable** — `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` exposes a CLI `main()` that reads `interpretation_{run_name}.json` from the workspace, builds a minimal `ProposalInput` (legacy-mode only — no `reasoning_pipeline`), runs the agent, and writes `proposal_{run_name}.json` back to the same workspace. For pipeline mode + external-agent contributions (`expert_context`, `agent_cards`, `mindset`), drive the node via `workflows/model_exploration.py`.
- **Upstream**: `result_interpretation_agent` (provides the serialized `InterpretationOutput` as the `interpretation` field). When external agents are active in the workflow, `ml_literature_review` also contributes via the proposer's `expert_context` / `agent_cards` / `mindset` / `vocab_seed` channels (mapped by `local_full_context`).
- **Downstream**: two downstream consumers via separate protocols:
  - `ml_model_implementor` — consumes `model_description`, `mathematical_definition`, `motivation`, `baseline_config` via `proposal_to_implementor_v1`.
  - `ml_hyperparameter_tune_agent` — consumes `expert_advice`, `baseline_config`, `parameter_count_estimate` via `proposal_to_hyperparam_seeded_v1`.
- **Protocol (upstream)**: `local_full_context` in `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — maps the prior `InterpretationOutput` + external-agent contributions + chain state into this node's `ProposalInput`.

## Input

**Schema**: `ProposalInput` in `agent/schemas/proposal.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `interpretation` | `dict[str, Any]` | Yes | — | Serialized `InterpretationOutput` from the upstream interpretation node. Carries `key_findings`, `bottlenecks`, `take_home_message`, `model_types`, `model_descriptions`, per-model best/worst scores. |
| `existing_model_types` | `list[str]` | No | `[]` | Model type keys already registered in `MODEL_REGISTRY`. The proposer MUST NOT reuse any of these names; the run aborts if the LLM proposes a duplicate. |
| `constraints` | `list[str]` | No | `[]` | Hard limits the proposed architecture must respect (e.g. `"VRAM < 10 GB"`, `"params < 50M"`, `"no external dependencies"`). |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 prompt flag. **OFF (default): the reasoning prompt is byte-identical to pre-PR3** (golden-parity tested) even when the interpretation dump carries the structured fields. ON: one `[HEALTHGATE EVIDENCE]` block renders (see Key behavioral notes). Informational only — never routes or rejects proposals. Threaded by `local_full_context`; part of the run-invariants lock. |
| `reasoning_pipeline` | `ReasoningPipelineConfig` | No | `ReasoningPipelineConfig()` | Configurable reasoning pipeline (comparison → reasoning → proposing). When any stage is enabled, pipeline mode runs; otherwise legacy mode runs. Set at the workflow level. |
| `expert_context` | `list[ExpertContextItem]` | No | `[]` | Polymorphic upstream context — human advice, agent findings, etc. Each item carries a `source`, `kind`, `content`, and `source_ref` for attribution. The channel external agents (literature review, future physics) populate. |
| `agent_cards` | `list[AgentCard]` | No | `[]` | Self-descriptions of all external agents contributing context this round. Rendered as a "Contributors" section above the Expert Context block. Carries `trust_level` (`hard_limit` / `strong_prior` / `soft_prior`) for synthesis-rule routing. |
| `mindset` | `str \| None` | No | `None` | Mindset block injected at `{# EXPLORATION_MODE_BLOCK #}` in the causal-reasoning stage prompt. Overrides the default `_explore.md` / `_exploit.md` fallback. |
| `vocab_seed` | `list[VocabEntry]` | No | `[]` | The runtime vocabulary available to the reasoning pipeline (canonical seed + promoted candidates + active candidates). Populated by the upstream interpretation node via the protocol. |
| `is_trial` | `bool` | No | `False` | Whether the run uses trial (sparse) sampling. Forwarded to `build_sample_set` inside the proposer's `evaluate_time_skill` pre-flight gate so the wall-time estimate matches what the tuner will see. |
| `trial_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy for the training scope: `snapshot` (all 20 files), `anchors` (files 0/10/19), `target` (caller-specified files). Mirrors `HyperparamTuningInput.trial_strategy`. |
| `trial_portion` | `float` | No | `0.1` | Fraction of segments per file for the training scope. Mirrors `HyperparamTuningInput.trial_portion`. |
| `target_files` | `list[int]` | No | `[]` | File indices to sample from. Required when `trial_strategy="target"`. |
| `train_portion` | `float` | No | `0.1` | Per-epoch subsample fraction from the training scope. Forwarded to `evaluate_time_skill` so the proposer's wall-time estimate matches the tuner's. |
| `sampling_seed` | `int \| None` | No | `None` | Seed for `build_sample_set()`. When `None` the proposer auto-generates one for its estimate; the tuner uses its own auto-generation policy. |
| `trial_time_budget_minutes` | `float \| None` | No | `None` | Wall-time budget (minutes) against which `evaluate_time_skill` gates the baseline config when `is_trial=True`. `None` = trial gate disabled. |
| `formal_time_budget_minutes` | `float \| None` | No | `None` | Wall-time budget (minutes) against which `evaluate_time_skill` gates the baseline config when `is_trial=False`. `None` = formal gate disabled. |
| `vram_budget_gb` | `float \| None` | No | `None` | Active operator-defined VRAM ceiling (GB) for the upcoming tuning iteration. Workflow picks trial vs formal budget based on `is_trial`. |
| `data_dir` | `str \| None` | No | `None` | Filesystem path to the TIDMAD data directory. Required by the real-dataset warmup inside `evaluate_time_skill`; when `None` the skill falls back to its synthetic stub. |
| `debug_dump_proposing_prompt_path` | `str \| None` | No | `None` | Debug instrumentation: when set, pipeline mode writes the rendered proposing-stage system prompt to this path before calling the LLM. Useful for offline prompt audits (Checkpoint P). |
| `human_advice` | `str \| ExpertAdvice \| None` | No | `None` | **DEPRECATED** — use `expert_context` instead. Legacy human-provided guidance. When present, the upstream `local_full_context` protocol wraps it into an `ExpertContextItem` with `source="human"`. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where the node reads its inputs and writes `proposal_{run_name}.json`. In standalone CLI use, constructed by `main()` from `--workspace` + `--run_name`; in workflow use, populated by `workflows/model_exploration.py`. |
| `hardware_context` | `HardwareContext \| None` | No | `None` | Live hardware manifest from `core.hardware_context.get_or_create()`. Populated by the workflow on GPU-enabled hosts; `None` for CPU-only / test stubs and falls back to deterministic priors in `evaluate_time_skill`. |
| `per_model_score_tables` | `dict[str, ScoreComparisonTable] \| None` | No | `None` | `model_type` → best `ScoreComparisonTable`, carried forward from `InterpretationOutput.per_model_score_tables`. Typed mirror of the `interpretation["per_model_score_tables"]` dict for tables the proposer renders. |
| `previous_failures` | `list[str]` | No | `[]` | Validation error messages from previous failed attempts in this iteration. The workflow populates this when retrying after a downstream validation failure, so the proposer can self-correct. |
| `recent_gate_exhaustions` | `list[GateExhaustionInfo]` | No | `[]` | Gate-exhaustion summaries from the most recent up-to-3 tuner iterations, oldest first. Iterations whose tuner produced no gate exhaustions are skipped. Lets the proposer learn from prior tuner-side gate failures. |

## Output

**Schema**: `ProposalOutput` in `agent/schemas/proposal.py`

| Field | Type | Description |
|---|---|---|
| `model_name` | `str` | Short, unique, snake_case identifier for the proposed model (e.g. `attn_unet`, `dilated_rnn`). MUST NOT clash with `existing_model_types`. |
| `model_description` | `str` | One paragraph plain-English description of the architecture and why it is expected to improve on the current best. Read by `ml_model_implementor`. |
| `mathematical_definition` | `str` | Precise layer-by-layer specification: layer types, dimensions, activation functions, skip connections, etc. Must be concrete enough for an LLM to implement directly. Read by `ml_model_implementor`. |
| `motivation` | `str` | Why this specific architecture addresses the bottlenecks. References `take_home_message` directly. |
| `expert_advice` | `ExpertAdvice` | Structured guidance for `ml_hyperparameter_tune_agent`: safe starting hyperparameter ranges, known failure modes, exploration focus areas. Read by the downstream tuner. |
| `baseline_config` | `dict[str, Any]` | A safe, moderate starting configuration for this architecture. Conservative param count + GPU memory footprint suitable for initial trial-mode training. |
| `inherited_components` | `list[InheritedComponent]` | Architectural primitives carried over from past winning runs (copied from the `DiscoveryMemo`). The validator checks each claimed component actually appears in the generated source. Carries `source_type` (`experiment` / `external_agent` / `human`) + `source_id`. |
| `falsifiable_prediction` | `FalsifiablePrediction \| None` | The numerical prediction from the `DiscoveryMemo`. Evaluated by the next iteration's interpretation agent (SOTA-based) to determine if the hypothesis was confirmed, partial, or refuted. |
| `proposed_vocab_links` | `list[ProposedVocabLink]` | Feature→capability link hypotheses from the `DiscoveryMemo`. Evaluated across iterations; confirmed links get promoted to `VocabEntry.related_to`. |
| `proposed_vocab_candidates` | `list[dict[str, str]]` | New feature/capability candidates from the comparison or reasoning stage. Each entry is `{"name", "kind" (feature\|capability), ...}`. |
| `proposed_discoveries` | `list[VocabEntry]` | New `kind="discovery"` vocabulary entries the proposer suggests. Empirical findings expressed as sentences. Added to `runtime_vocab` after the next interpretation pass. |
| `memo_consistency_notes` | `list[str]` | Inconsistencies the proposing stage noticed between the `DiscoveryMemo` and what's physically implementable. Empty = no issues. |
| `parameter_count_estimate` | `int \| None` | LLM-emitted estimate of the total trainable parameter count for `baseline_config`. Consumed by the proposer's own pre-flight static-cost gate. |
| `preflight_estimated_minutes` | `float \| None` | Pre-flight static-formula wall-time estimate (minutes) for `baseline_config`, evaluated against the active time budget. |
| `preflight_factor` | `float \| None` | `preflight_estimated_minutes / active_budget_minutes`, rounded to 3 decimal places. `≤ 1.0` = predicted to fit; `> 1.0` = a labeled `PREFLIGHT_ADVISORY` note is appended to `memo_consistency_notes` (C1, 2026-07-30: the estimate is `static_uncalibrated` provenance and ADVISORY ONLY — it never triggers rejection or revision). |

## CLI usage

```bash
.venv/bin/python nodes/ml_model_proposal_agent/ml_model_proposal_agent.py \
    --workspace ./siderius_workspace \
    --run_name v1 \
    --provider gemini \
    --model_id gemini-3.1-flash-lite-preview
```

The CLI reads `{workspace}/interpretation_{run_name}.json` (the upstream interpretation agent's output), builds a **legacy-mode-only** `ProposalInput`, runs the agent, and writes `{workspace}/proposal_{run_name}.json`.

**Limitations of standalone CLI use** (compared to workflow-driven use):

- **Legacy mode only** — the CLI does not construct a `reasoning_pipeline`, so pipeline mode never engages. To exercise pipeline mode, drive the node from `workflows/model_exploration.py`.
- **No external-agent contributions** — `expert_context`, `agent_cards`, `mindset`, `vocab_seed` all default to empty. The CLI cannot pipe in literature-review findings.
- **No hardware context / VRAM budget / time budgets** — the pre-flight time-gate falls back to deterministic priors.
- **No `previous_failures` / `recent_gate_exhaustions` retry signal** — each CLI invocation is a fresh attempt.

### CLI arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `--workspace` | `str` | `./siderius_workspace` | Root directory for reading `interpretation_{run_name}.json` and writing `proposal_{run_name}.json`. |
| `--run_name` | `str` | `v1` | Filename suffix shared across the chain (interpretation, proposal). |
| `--provider` | `str` (`gemini` \| `openai`) | `gemini` | LLM provider for both calls (reasoning + commit in legacy; all stages in pipeline). |
| `--model_id` | `str` | `gemini-3.1-flash-lite-preview` | Specific model id passed to the provider. |

## Python API usage

```python
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import StorageConfig, LocalStorageConfig

inp = ProposalInput(
    interpretation=interp_output.model_dump(),  # from upstream
    existing_model_types=["punet", "wavenet", "fcnet"],
    constraints=["VRAM < 10 GB", "params < 50M"],
    storage=StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace="./workspace", run_name="iter_001"),
    ),
    # Optional — pipeline mode + external-agent channels:
    reasoning_pipeline=reasoning_pipeline_config,
    expert_context=external_findings,      # from ml_literature_review et al.
    agent_cards=external_agent_cards,
    mindset="exploit",
    vocab_seed=runtime_vocab,
    # Pre-flight time + VRAM gate:
    is_trial=True,
    trial_time_budget_minutes=20.0,
    vram_budget_gb=8.0,
    hardware_context=hw_ctx,
    data_dir="/home/klz/Data/TIDMAD",
)

agent = MLModelProposalAgent(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
output = agent.run(inp)  # -> ProposalOutput
```

The constructor accepts `bridge_factory` (test injection — defaults to `LLMBridge`) and `max_retries` (defaults to `None`, infinite quota retry per project policy). Extra kwargs are absorbed for future per-stage bridge routing (`comparison_provider`, `reasoning_model_id`, etc.) — currently unused.

## Storage outputs

- **Proposal JSON**: `{storage.local.workspace}/proposal_{run_name}.json` — the validated `ProposalOutput` dumped at the end of `run()`. The workflow does NOT read this back — downstream nodes receive data through the protocol functions in memory. This is the audit log for the iteration.
- **Debug proposing-prompt dump** (optional): when `debug_dump_proposing_prompt_path` is set, pipeline mode writes the rendered proposing-stage system prompt to that path before calling the LLM. Used by Checkpoint P offline prompt audits.

## Key behavioral notes

- **`[HEALTHGATE EVIDENCE]` block (V19 PR 3, flag-gated).** When `enable_structured_health_feedback=True`, `_format_healthgate_evidence_block()` renders ONE bounded block — delivered on BOTH execution modes: in legacy 2-call mode it is spliced into `_build_reasoning_prompt`; in the production 3-stage pipeline it renders through the `healthgate_evidence_block` template variable into `proposing_stage.md` (the JSON-emitting final stage — the same mechanism and placement as the §14.N `recent_gate_exhaustions_block` variable; the earlier stages deliberately do not receive it, avoiding duplicated context). The block is built from the deterministic interpretation fields (`per_model_round_health_counts`, `per_model_collapse_fingerprints`, `collapse_fingerprint_history`) — never from `key_findings` or any LLM prose. Per model (grouped exactly as the interpreter grouped them, nothing unlabelled): this-iteration validity counts and fingerprints, then retained history with retained-window occurrence counts (stored history is post-retention, so bucket sums ARE window counts — lifetime totals never render), absolute iteration tags, a "Representative observation:" line for the entry-level raw metrics, and bounded source experiment ids. Ends with six behavioral rules (no fingerprinted repeat without a named mechanism; the mechanism must change actual configuration; invalid high score = failure; no inappropriate avoidance; no cross-model transfer; no unsupported use-claims). Legacy interpretation dicts (fields absent) and empty evidence render NOTHING — no empty heading; a malformed hand-built history entry raises a diagnostic `ValueError` naming the model. The block renders AFTER and visibly separate from `[RECENT GATE EXHAUSTIONS]` — a different failure family (abort-class resource failures), whose rendering is byte-identical pre/post PR 3.

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
- **Two execution modes auto-selected by `reasoning_pipeline.stages`.** Legacy mode (2 calls: `generate_text` reasoning → `generate` commit JSON) is the historical default and what the CLI exercises. Pipeline mode (3 stages: comparison → causal reasoning → proposing) engages when `reasoning_pipeline` has any enabled stage and is what the workflow uses in production. Both modes converge on the same `ProposalOutput` schema.
- **Pre-flight ADVISORY (C1, 2026-07-30 — the former revision loop is REMOVED).** After the commit/proposing call, the proposer runs the static-formula wall-time estimate (`estimate_proposal_time`) against the active time budget. The result is `static_uncalibrated` provenance and advisory only: if `preflight_factor > 1.0`, a labeled `PREFLIGHT_ADVISORY` note (confidence=low, blocking_eligible=no, "do not infer a parameter-count ceiling") is recorded on the output — no revision is requested and no rejection text enters any prompt. Rationale: the V19 wave-1 incident (`docs/design/runtime_estimation_and_calibration.md` §4); blocking runtime authority belongs to measured evidence via the shared decision policy (C4/C8). Structural validation retries (`_MAX_PROPOSING_RETRIES=2`) are unchanged.
- **Causal-reasoning minimum-boldness retry** (`_MAX_REASONING_RETRIES=1`). In pipeline mode, the causal-reasoning stage emits a `FalsifiablePrediction` with a `boldness` score. If the score falls below the configured minimum, the stage retries ONCE with a "be bolder" nudge. This is independent of the pre-flight loop.
- **Citation discipline** (`_check_citation_discipline`). The reasoning stage's output is checked for valid `source_ref` values: each ref must correspond to an entry in `expert_context` or `agent_cards`. Invalid refs (hallucinated citations) trigger an error message appended to the next attempt's prompt.
- **Pipeline mode prompt assembly order** (locked by Commit P-d). Each pipeline stage's user prompt assembles blocks in this top-to-bottom order: (1) `[HARDWARE CONTEXT]`, (2) `## Constraints`, (3) `## External Contributors` (rendered `agent_cards`), (4) `## Expert Context` (rendered `expert_context`), (5) candidate markdown + accumulated JSON, (6) vocab block (reasoning stages only). This order is what Checkpoint P signed off on; reordering would be a structural regression.
- **Mindset overrides `_explore.md` / `_exploit.md` fallback.** When `mindset` is set, it replaces the default exploration/exploitation hint block at `{# EXPLORATION_MODE_BLOCK #}` in the causal-reasoning prompt. This is how the workflow signals "explore more / exploit more" without editing prompt files.
- **Auditing helper for tests.** `_audit_proposer_components(...)` (used by `tests/unit/agent/ml_model_proposal_agent/`) returns a 10-key components dict mirroring `bridge.generate(...)` inputs — for verifying prompt assembly in isolation without firing an LLM call.
- **Duplicate-name guard.** If the LLM proposes a `model_name` already in `existing_model_types`, `run()` raises `ValueError` immediately — no retry, no fallback. The workflow is expected to vary constraints or seed prompt on the next attempt.

## Dependencies

- **LLM**: up to two distinct call signatures, all via `LLMBridge`:
  - **Legacy mode** — `bridge.generate_text(...)` for reasoning (free-form) + `bridge.generate(...)` for commit (strict JSON via `ProposalOutput.model_validate`). Exactly one reasoning call + one commit call per run (C1: the pre-flight revision loop is removed; a schema-violating commit still raises immediately, unchanged).
  - **Pipeline mode** — `bridge.generate_text(...)` for the comparison stage, `bridge.generate(...)` for causal reasoning + proposing stages (each as JSON). Per-stage configuration controlled by `reasoning_pipeline.stages` (each stage can be disabled or have its own model overrides via the kwargs absorbed in the constructor).
- **GPU**: not required for the proposer itself (the LLM calls are remote and the pre-flight wall-time estimate uses a static formula by default). However, if `hardware_context` is supplied AND `data_dir` points at the real TIDMAD data, the pre-flight gate runs a brief real-dataset warmup inside `evaluate_time_skill` — that warmup uses the host GPU when available.
- **External services**: none directly. Depends on the upstream interpretation file (in CLI mode) or on the upstream protocol (in workflow mode). The pre-flight time-gate uses `execute_tools.dataset_config.TIDMAD` for shape priors and optionally `core.hardware_context` for live GPU manifest.
