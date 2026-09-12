# MLModelProposalAgent

> Reads the structured interpretation from `result_interpretation_agent` and proposes a new neural architecture that addresses the identified bottlenecks. Supports two modes: a 2-call legacy chain-of-thought (reasoning → commit) and a 3-stage configurable pipeline (comparison → causal reasoning → proposing) for production runs.

## Position in the pipeline

- **CLI entry**: **present** — `main()` reads an interpretation record and builds a minimal legacy-mode `ProposalInput`. Its advisory estimates and prompt constraints do not create deterministic hardware locks; richer pipeline context is supplied by the workflow route.
- **Upstream**: `result_interpretation_agent` (its `InterpretationOutput` is projected into the `interpretation_evidence` field by `build_proposer_evidence`). When external agents are active in the workflow, `ml_literature_review` also contributes via the proposer's `expert_context` / `agent_cards` / `mindset` / `vocab_seed` channels (mapped by `local_full_context`).
- **Downstream**: two downstream consumers via separate protocols:
  - `ml_model_implementor` — consumes `model_name`, `output_type`, `model_description`, `mathematical_definition`, `baseline_config`, `custom_loss_spec` via `ml_model_propose_to_ml_model_impl.py::local_full_spec` (`agent/schemas/protocols/`).
  - `ml_hyperparameter_tune_agent` — consumes `expert_advice` and `baseline_config` via the fan-in `ml_model_valid_to_ml_model_tune.py::local_validated_model`, which takes this node's `ProposalOutput` beside the validator's `ValidatorOutput`; there is no separate proposal→tuner protocol module.
- **Protocol (upstream)**: `local_full_context` in `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` — maps the prior `InterpretationOutput` + external-agent contributions + chain state into this node's `ProposalInput`.

## Input

**Schema**: `ProposalInput` in `agent/schemas/proposal.py`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `interpretation_evidence` | `ProposerInterpretationEvidence` | Yes | — | **The node's ONE interpretation contract** (Step 10 / P3). A typed CONSUMER VIEW of the upstream interpretation — 30 declared fields, the measured union of what this node actually reads: `key_findings`, `bottlenecks`, `take_home_message`, `model_types`, `model_descriptions`, per-model best/valid/worst scores, score tables, params, training segments, the prediction track record, vocabulary health, the deterministic HealthGate evidence, and `metric_identity` (the run's metric id + direction). Built by the ONE projection authority `build_proposer_evidence(mapping)` (`agent/schemas/proposer_evidence.py`) at BOTH entrypoints — the protocol `local_full_context` from `InterpretationOutput.model_dump()`, and the standalone CLI from the persisted `interpretation_{run_name}.json`, which is the same shape. Absent keys take documented per-field absence semantics (a legacy artifact still renders); a present-but-malformed value fails closed at the boundary; a malformed `metric_identity` becomes `None`, a NAMED absence, never a guessed direction. It REPLACED `interpretation: dict[str, Any]`, the raw upstream dump that two independent readers mined with `.get()` — see Key behavioral notes. |
| `existing_model_types` | `list[str]` | No | `[]` | Model type keys already registered in `MODEL_REGISTRY`. The proposer MUST NOT reuse any of these names; the run aborts if the LLM proposes a duplicate. |
| `constraints` | `list[str]` | No | `[]` | Advisory guidance for proposal synthesis (e.g. `"VRAM < 10 GB"`, `"params < 50M"`, `"no external dependencies"`); deterministic runtime policy remains the authority for admission and enforcement. |
| `enable_structured_health_feedback` | `bool` | No | `False` | V19 PR 3 prompt flag. **OFF (default): the reasoning prompt is byte-identical to pre-PR3** (golden-parity tested) even when the interpretation dump carries the structured fields. ON: one `[HEALTHGATE EVIDENCE]` block renders (see Key behavioral notes). Informational only — never routes or rejects proposals. Threaded by `local_full_context`; part of the run-invariants lock. |
| `baseline_isolation` | `bool` | No | `False` | **arXiv U3 (#260, ruling R6)** — the WITHOUT arm's explicit isolation flag, set by the workflow. When `True`, the prompt surface names no bundled baseline: `render_available_models` uses the isolated fallback/header (no built-in branch offered) and `load_stage_prompt` substitutes neutral example literals (`exemplar` / `1.23`) for the shipped `wavenet` / `5.57` tokens in `comparison_stage.md` / `causal_reasoning_stage.md`. **Every non-isolated render is byte-identical to pre-U3** — pinned against the base template sha256. The workflow additionally REFUSES a proposal naming a bundled built-in (`BaselineIsolationViolation`, fed back as `previous_failures`) before the implementor. |
| `reasoning_pipeline` | `ReasoningPipelineConfig` | No | `ReasoningPipelineConfig()` | Configurable reasoning pipeline (comparison → reasoning → proposing). When any stage is enabled, pipeline mode runs; otherwise legacy mode runs. Set at the workflow level. |
| `expert_context` | `list[ExpertContextItem]` | No | `[]` | Polymorphic upstream context — human advice, agent findings, etc. Each item carries a `source`, `kind`, `content`, and `source_ref` for attribution. The channel external agents (literature review, future physics) populate. |
| `agent_cards` | `list[AgentCard]` | No | `[]` | Self-descriptions of all external agents contributing context this round. Rendered as a "Contributors" section above the Expert Context block. Carries `trust_level` (`hard_limit` / `strong_prior` / `soft_prior`) for synthesis-rule routing. |
| `mindset` | `str \| None` | No | `None` | Mindset block injected at `{# EXPLORATION_MODE_BLOCK #}` in the causal-reasoning stage prompt. Overrides the default `_explore.md` / `_exploit.md` fallback. |
| `vocab_seed` | `list[VocabEntry]` | No | `[]` | The runtime vocabulary available to the reasoning pipeline (canonical seed + promoted candidates + active candidates). Populated by the upstream interpretation node via the protocol. |
| `is_trial` | `bool` | No | `False` | Whether the run uses trial (sparse) sampling; this selects inputs to the static `estimate_proposal_time` advisory. |
| `trial_strategy` | `Literal["snapshot", "anchors", "target"]` | No | `"snapshot"` | Sampling strategy for the training scope: `snapshot` (all 20 files), `anchors` (files 0/10/19), `target` (caller-specified files). Mirrors `HyperparamTuningInput.trial_strategy`. |
| `trial_portion` | `float` | No | `0.1` | Fraction of segments per file for the training scope. Mirrors `HyperparamTuningInput.trial_portion`. |
| `target_files` | `list[int]` | No | `[]` | File indices to sample from. Required when `trial_strategy="target"`. |
| `train_portion` | `float` | No | `0.1` | Per-epoch fraction supplied to the static proposal-time estimate; it does not trigger data sampling in the proposer. |
| `sampling_seed` | `int \| None` | No | `None` | Optional seed recorded as proposal context; the static estimate performs no `build_sample_set()` data access. |
| `trial_time_budget_minutes` | `float \| None` | No | `None` | Active trial budget supplied to the static `estimate_proposal_time` advisory; it never rejects or revises a proposal. |
| `formal_time_budget_minutes` | `float \| None` | No | `None` | Active formal budget supplied to the static `estimate_proposal_time` advisory; it never rejects or revises a proposal. |
| `vram_budget_gb` | `float \| None` | No | `None` | Active operator-defined VRAM ceiling (GB) for the upcoming tuning iteration. Workflow picks trial vs formal budget based on `is_trial`. |
| `data_dir` | `str \| None` | No | `None` | Caller-selected physical data root forwarded to the workflow/runtime when supplied. The proposer preflight is a static estimate: it performs no HDF5/data access and does not switch to a synthetic fallback when this value is absent. |
| `debug_dump_proposing_prompt_path` | `str \| None` | No | `None` | Debug instrumentation: when set, pipeline mode writes the rendered proposing-stage system prompt to this path before calling the LLM. Useful for offline prompt audits (Checkpoint P). |
| `human_advice` | `str \| ExpertAdvice \| None` | No | `None` | **DEPRECATED** — use `expert_context` instead. Legacy human-provided guidance. When present, the upstream `local_full_context` protocol wraps it into an `ExpertContextItem` with `source="human"`. |

### Workflow-populated fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `storage` | `StorageConfig` | Yes | — | Where the node reads its inputs and writes `proposal_{run_name}.json`. In standalone CLI use, constructed by `main()` from `--workspace` + `--run_name`; in workflow use, populated by `workflows/model_exploration.py`. |
| `hardware_context` | `HardwareContext \| None` | No | `None` | Live hardware manifest from `core.hardware_context.get_or_create()`. Populated by the workflow on GPU-enabled hosts; `None` for CPU-only / test stubs and uses deterministic priors in the static proposal-time estimate. |
| `task_description` | `str` | No | `""` | Plain-English task description, authored in `configs/task_config.yaml`. Populated by the workflow via `get_task_description(load_task_config())` and by the standalone CLI in `main()`. Rendered into the `{TASK_BACKGROUND}` block of the legacy reasoning prompt AND — since PR 01b — into the `{task_background_block}` placeholder of all three pipeline stage system prompts. The `""` default is for test fixtures only; empty or whitespace-only collapses the block. |
| `forward_contract` | `ForwardContract` | No | `ForwardContract()` | Typed forward-pass contract from the same YAML. Rendered into the legacy `{TASK_BACKGROUND}` block and into `proposing_stage.md`'s `{forward_contract}` placeholder. Deliberately NOT expanded into the comparison or causal stages. All-empty default is for test fixtures only. |
| `previous_failures` | `list[str]` | No | `[]` | Validation error messages from previous failed attempts in this iteration. The workflow populates this when retrying after a downstream validation failure, so the proposer can self-correct. |
| `recent_gate_exhaustions` | `list[GateExhaustionInfo]` | No | `[]` | Gate-exhaustion summaries from the most recent up-to-3 tuner iterations, oldest first. Iterations whose tuner produced no gate exhaustions are skipped. Lets the proposer learn from prior tuner-side gate failures. |
| `recent_trial_validity` | `list[TrialValidityFeedback]` | No | `[]` | **V20 PR D (D-C6)** — up to the last K iterations that produced NO HealthGate-valid trial winner, oldest first. Sparse: iterations with a valid winner contribute nothing, so a healthy chain leaves this empty and the prompt block is suppressed. Distinct from `recent_gate_exhaustions` (budget exhaustion) — these trials RAN and then failed their scientific gates. |

## Output

**Schema**: `ProposalOutput` in `agent/schemas/proposal.py`

| Field | Type | Description |
|---|---|---|
| `model_name` | `str` | Short, unique, snake_case identifier for the proposed model (e.g. `attn_unet`, `dilated_rnn`). MUST NOT clash with `existing_model_types`. |
| `output_type` | `Literal["classifier", "regressor"]` | The output representation this proposal commits to — an **independent design dimension** from the backbone and the loss family (V21 PR A). `classifier` → `[B, 256, T]`, legal losses `ce`/`focal`/`focal_cw`. `regressor` → `[B, T]`, legal loss `smooth_l1`. **Never inferred from `loss_type`** — the pair is checked by `validate_output_loss_compatibility` in `ml_models/models_format_sandbox.py`, which is the single production authority and is consumed by both the built-in path (`ExperimentConfig`) and the generated-plugin path (`TidmadSandbox._validate_configs`). Transported verbatim to `ImplementorInput.output_type`, which decides the emitted `PLUGIN_OUTPUT_TYPE`. Defaults to `classifier` for legacy reads only. |
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
| `preflight_factor` | `float \| None` | `preflight_estimated_minutes / active_budget_minutes`, rounded to 3 decimal places. `≤ 1.0` = predicted to fit; `> 1.0` = a labeled `PREFLIGHT_ADVISORY` note is appended to `memo_consistency_notes` (C1, 2026-07-30: the estimate is `static_uncalibrated` provenance and ADVISORY ONLY — it never triggers rejection or revision). C8b (2026-07-30): the note is emitted on the SHARED `RuntimeDecisionPolicy` decision (`phase="proposal"`), not on a private `factor > 1.0` comparison; the deciding policy identity is appended to the note, and a REJECT/ABORT at this stage raises `AssertionError` rather than silently rejecting a proposal. |

## CLI usage

```bash
.venv/bin/python src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py \
    --workspace ./siderius_workspace \
    --run_name v1 \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir ./siderius_workspace/quickstart_data \
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
| `--task_composition` | path | required | Task-composition manifest supplying the scientific contract. |
| `--data_dir` | path | required | Physical data root bound for the selected task composition. |

## Python API usage

```python
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import MLModelProposalAgent
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.storage import StorageConfig, LocalStorageConfig

inp = ProposalInput(
    # The ONE projection authority. Production callers get this from the
    # protocol; a direct caller builds it the same way, from the same shape.
    interpretation_evidence=build_proposer_evidence(interp_output.model_dump()),
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

- **One interpretation reader, and it is typed (Step 10 / P3).** The node used
  to receive `ProposalInput.interpretation: dict[str, Any]` — the upstream
  node's ENTIRE `model_dump()` — and mine it with `.get()` in two independent
  readers: the production pipeline and the legacy/standalone renderer. Nothing
  declared what the proposer consumed, so the two drifted onto fields the other
  never saw, and every new evidence field had to be wired into both. Now a
  single `build_proposer_evidence(mapping)` projection produces
  `ProposerInterpretationEvidence`, and the pipeline, the legacy adapter and the
  helpers all read that one value. The raw dict field and the dead
  `per_model_score_tables` typed mirror (which had zero readers) are REMOVED, so
  a bypass has no input to read. An executable census keeps the count of raw
  interpretation reads in the proposer's modules at **zero**.
- **The node is decomposed.** `ml_model_proposal_agent.py` + `.md` are the
  PUBLIC surface; `evidence_rendering.py` is PRIVATE and owns proposer
  prompt-evidence rendering — the 18-key `interpretation_summary` serializer,
  the HealthGate block, the legacy interpretation section, and the D1/D2
  grammar renderers. Production code outside the node must not import it;
  `_COMPATIBILITY_REEXPORTS` in the main module is scaffolding for existing
  importers and `mock.patch` targets, not contract.
- **The prompts state the run's metric direction (Step 10 / P3, D1/D2/D3).**
  The comparison and causal stage templates carry a `{metric_context_block}`
  that names the run's golden metric and which direction is better, rendered
  from the DECLARED `metric_identity` through the one direction authority
  (`MetricOrder.direction_words`) — never inferred from a metric name, a sign or
  a task. The causal stage's `falsifiable_prediction` example is rendered on
  that direction: under `higher` it reproduces the historical literal exactly
  (`1.5 → 2.5`, threshold `1.2`); under `lower` it inverts (`1.5 → 0.5`,
  threshold `1.8` — ABOVE current, the refuted side). The block also states what
  `threshold_for_refutation` MEANS in this run's direction, which Gate 1 showed
  is not inferable from the numbers alone. `comparison_stage.md` rule 7 defines
  SOTA as BEST under the stated direction, not the largest number. When the run
  declares NO usable identity, all three surfaces render the canonical
  `metric direction unavailable / metric_spec absent` absence: no direction
  words, no numeric example, and an explicit instruction to make no ranking
  claim. The proposing stage declares neither placeholder — it neither ranks nor
  authors a prediction. **The legacy path carries none of this**: it authors no
  prediction at all, and its prompt bytes are preserved.
- **Secondary metrics are NOT proposer evidence.** A task's observational
  secondary metrics (Step 10 / P2b) are deliberately absent from the typed
  evidence and from every proposer prompt — no raw values, no refusals, no
  runtime diagnostics. A second, differently-directed number beside the one
  being optimised invites a trade-off that observational metrics must never get.
  Secondary science reaches the proposer only through the interpreter's
  synthesized `key_findings` / `take_home_message`.

- **`[HEALTHGATE EVIDENCE]` block (V19 PR 3, flag-gated).** When `enable_structured_health_feedback=True`, `evidence_rendering.render_healthgate_evidence_block()` renders ONE bounded block — delivered on BOTH execution modes: in legacy 2-call mode it is spliced into `_build_reasoning_prompt`; in the production 3-stage pipeline it renders through the `healthgate_evidence_block` template variable into `proposing_stage.md` (the JSON-emitting final stage — the same mechanism and placement as the §14.N `recent_gate_exhaustions_block` variable; the earlier stages deliberately do not receive it, avoiding duplicated context). The block is built from the deterministic interpretation fields (`per_model_round_health_counts`, `per_model_collapse_fingerprints`, `collapse_fingerprint_history`) — never from `key_findings` or any LLM prose. Per model (grouped exactly as the interpreter grouped them, nothing unlabelled): this-iteration validity counts and fingerprints, then retained history with retained-window occurrence counts (stored history is post-retention, so bucket sums ARE window counts — lifetime totals never render), absolute iteration tags, a "Representative observation:" line for the entry-level raw metrics, and bounded source experiment ids. Ends with six behavioral rules (no fingerprinted repeat without a named mechanism; the mechanism must change actual configuration; invalid high score = failure; no inappropriate avoidance; no cross-model transfer; no unsupported use-claims). Legacy interpretations (fields absent) and empty evidence render NOTHING — no empty heading. A malformed history entry now fails EARLIER, at the typed projection boundary rather than at render time (Step 10 / P3); `ValidationError` subclasses `ValueError`, so the caller-visible failure class is unchanged. The block renders AFTER and visibly separate from `[RECENT GATE EXHAUSTIONS]` — a different failure family (abort-class resource failures), whose rendering is byte-identical pre/post PR 3.

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
- **Pre-flight ADVISORY (C1, 2026-07-30 — the former revision loop is REMOVED).** After the commit/proposing call, the proposer runs the static-formula wall-time estimate (`estimate_proposal_time`) against the active time budget. The result is `static_uncalibrated` provenance and advisory only: when the shared runtime policy returns anything other than `ALLOW` (i.e. the projection exceeds the active budget), a labeled `PREFLIGHT_ADVISORY` note (confidence=low, blocking_eligible=no, "do not infer a parameter-count ceiling", plus the deciding policy identity) is recorded on the output — no revision is requested and no rejection text enters any prompt. A task without the TIDMAD topology priced by this legacy formula returns `applicable=False`; the proposer records `PREFLIGHT_SKIPPED`, leaves the estimate fields as `None`, and continues normally. Rationale: the V19 wave-1 incident (`docs/design/runtime_estimation_and_calibration.md` §4); blocking runtime authority belongs to measured evidence via the shared decision policy (C4/C8). Structural validation retries (`_MAX_PROPOSING_RETRIES=2`) are unchanged.
- **Causal-reasoning minimum-boldness retry** (`_MAX_REASONING_RETRIES=1`). In pipeline mode, the causal-reasoning stage emits a `FalsifiablePrediction` with a `boldness` score. If the score falls below the configured minimum, the stage retries ONCE with a "be bolder" nudge. This is independent of the pre-flight loop.
- **Citation discipline** (`_check_citation_discipline`). The reasoning stage's output is checked for valid `source_ref` values: each ref must correspond to an entry in `expert_context` or `agent_cards`. Invalid refs (hallucinated citations) trigger an error message appended to the next attempt's prompt.
- **Task-background block in all three pipeline SYSTEM prompts** (PR 01b / S1-C). Each stage's base template (`comparison_stage.md`, `causal_reasoning_stage.md`, `proposing_stage.md`) carries `{task_background_block}` exactly once, immediately before its `## Your task` heading, in BOTH `explore` and `exploit` modes. It is filled from `inp.task_description` by `_render_pipeline_task_background()`, which delegates to `_render_task_background()` with an EMPTY `ForwardContract` — so the `Background on the task:` label has exactly one authority in the codebase and the forward contract is NOT duplicated into stages 1-2 (the proposing stage renders it separately through its own `{forward_contract}` placeholder). An absent or whitespace-only description collapses the block to `""`, leaving the rendered prompt byte-identical to the pre-JOIN template. The description authority is `configs/task_config.yaml` via `load_task_config()`; the workflow injects it at the proposer call site, and the standalone CLI loads it in `main()`. Before this PR the value was transported into `template_vars` and consumed by no template — the comparison and causal stages, which choose the architecture family, received no task framing at all.
- **Pipeline mode prompt assembly order** (locked by Commit P-d). Each pipeline stage's user prompt assembles blocks in this top-to-bottom order: (1) `[HARDWARE CONTEXT]`, (2) `## Constraints`, (3) `## External Contributors` (rendered `agent_cards`), (4) `## Expert Context` (rendered `expert_context`), (5) candidate markdown + accumulated JSON, (6) vocab block (reasoning stages only). This order is what Checkpoint P signed off on; reordering would be a structural regression.
- **Mindset overrides `_explore.md` / `_exploit.md` fallback.** When `mindset` is set, it replaces the default exploration/exploitation hint block at `{# EXPLORATION_MODE_BLOCK #}` in the causal-reasoning prompt. This is how the workflow signals "explore more / exploit more" without editing prompt files.
- **Auditing helper for tests.** `_audit_proposer_components(...)` (used by `tests/unit/agent/ml_model_proposal_agent/`) returns a 10-key components dict mirroring `bridge.generate(...)` inputs — for verifying prompt assembly in isolation without firing an LLM call.
- **Duplicate-name guard.** If the LLM proposes a `model_name` already in `existing_model_types`, `run()` raises `ValueError` immediately — no retry, no fallback. The workflow is expected to vary constraints or seed prompt on the next attempt.

## Dependencies

- **LLM**: up to two distinct call signatures, all via `LLMBridge`:
  - **Legacy mode** — `bridge.generate_text(...)` for reasoning (free-form) + `bridge.generate(...)` for commit (strict JSON via `ProposalOutput.model_validate`). Exactly one reasoning call + one commit call per run (C1: the pre-flight revision loop is removed; a schema-violating commit still raises immediately, unchanged).
  - **Pipeline mode** — `bridge.generate_text(...)` for the comparison stage, `bridge.generate(...)` for causal reasoning + proposing stages (each as JSON). Per-stage configuration controlled by `reasoning_pipeline.stages` (each stage can be disabled or have its own model overrides via the kwargs absorbed in the constructor).
- **GPU**: not required for the proposer itself. LLM calls are remote and the
  pre-flight wall-time result is a static advisory estimate by default; it is
  not a measured GPU admission check. A caller may supply hardware context for
  reporting, but this documentation does not claim a real-task warmup or
  scientific qualification.
- **External services**: none directly. Depends on the upstream interpretation file (in CLI mode) or on the upstream protocol (in workflow mode). The pre-flight time-gate uses `execute_tools.dataset_config.TIDMAD` for shape priors and optionally `core.hardware_context` for live GPU manifest.

- **`[RECENT TRIAL VALIDITY]` block (V20 PR D, D-C6).** Rendered by `_format_recent_trial_validity_block()` when `recent_trial_validity` is non-empty, and delivered on **BOTH** execution modes — spliced into `_build_reasoning_prompt` in legacy 2-call mode, and through the `recent_trial_validity_block` template variable into `proposing_stage.md` in the 3-stage pipeline. Both are required: Gate 1 caught a wiring that reached only the pipeline while the real call took the legacy branch, so the evidence never reached the model — the mirror image of the P3-V1 defect above. The block transports FACTS the gate system already recorded (record identities, which blocking gates failed, reasons, measured metrics, and what could not be established) and prescribes NO remedy: what a metric implies is the planner's judgement, and task-specific advice here would be wrong for the next task. It keeps distinct what a generic 'trial failed' string would collapse — execution failure (evidence ABSENT), gate invalidity (evidence NEGATIVE), validity unknown (the gates could not judge), and a formal round skipped for no valid winner versus skipped on the ordinary budget. Empty list renders NOTHING, so a healthy chain's prompt is byte-identical to pre-PR-D.
