# agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py
"""
Edge protocols: ml-result-interp → ml-model-propose
(result_interpretation_agent → ml_model_proposal_agent)

Each function is a distinct protocol on this edge. Orchestrators choose
which protocol to apply at traversal time.

Protocol naming convention: {transport}_{data_scope}
  transport  : how data moves between nodes (local = in-memory, database = via DB)
  data_scope : what subset of the source output is transferred

Implemented
-----------
local_full_context      Direct in-memory transfer of the complete interpretation output.

Planned
-------
database_full_context   DB-backed transfer: interp agent writes the interpretation to
                        the database, propose agent reads it. Requires a Postgres
                        StorageConfig backend. Raises NotImplementedError until wired.
"""

from typing import List, Literal, Optional, Sequence

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import (
    AgentCard,
    ExpertContextItem,
    ProposalInput,
    ReasoningPipelineConfig,
    VocabEntry,
)
from agent.schemas.hyperparam_tuning import (
    ExpertAdviceInput,
    HyperparamTuningOutput,
    serialize_expert_advice,
)
from agent.schemas.storage import StorageConfig


def local_full_context(
    output: InterpretationOutput,
    storage: StorageConfig,
    expert_context: Optional[List[ExpertContextItem]] = None,
    vocab_seed: Optional[List[VocabEntry]] = None,
    reasoning_pipeline: Optional[ReasoningPipelineConfig] = None,
    human_advice: Optional[ExpertAdviceInput] = None,
    mindset: Optional[str] = None,
    agent_cards: Optional[List[AgentCard]] = None,
    # --- Run-level data + time-budget context (workflow-supplied) ---
    is_trial: Optional[bool] = None,
    trial_strategy: Optional[Literal["snapshot", "anchors", "target"]] = None,
    trial_portion: Optional[float] = None,
    target_files: Optional[List[int]] = None,
    train_portion: Optional[float] = None,
    sampling_seed: Optional[int] = None,
    trial_time_budget_minutes: Optional[float] = None,
    formal_time_budget_minutes: Optional[float] = None,
    data_dir: Optional[str] = None,
    # --- Cross-iteration feedback (Phase K.7 → Phase N — see §10.13, §14.N) ---
    recent_tune_outputs: Sequence[HyperparamTuningOutput] = (),
) -> ProposalInput:
    """
    Local in-memory protocol — transfers the complete interpretation directly.

    Consumes from ml-result-interp (InterpretationOutput):
      - model_types          : all architectures analysed
      - model_descriptions   : full markdown descriptions of each architecture
      - per_model_best/worst, best_denoising_score, best_config
      - key_findings, bottlenecks, take_home_message
      - per_model_score_tables : per-model ScoreComparisonTable (per-file denoising
                                  scores + raw_baseline + ground_truth + rendered markdown).
                                  Replaces per_model_file_vectors per §7.3 / Decision 6.
      - weak_frequency_files    : file indices where each model scores poorly
      - per_model_params        : parameter count per model (efficiency)
      - per_model_training_segments : training data volume per model

    Additional context (passed by the workflow, not by the interpretation agent):
      - expert_context       : polymorphic upstream findings (human, agents, strategy reports)
      - vocab_seed           : runtime vocabulary (canonical + promoted + candidates)
      - reasoning_pipeline   : 3-stage pipeline config (stages, model selection, policy)
      - human_advice         : legacy human advice — wrapped into ExpertContextItem if provided
      - mindset              : optional free-text injected into the causal reasoning stage prompt
      - agent_cards          : optional list of external agent self-descriptions (Contributors block)
      - is_trial / trial_strategy / trial_portion / target_files / train_portion /
        sampling_seed         : run-level data-sampling parameters that mirror
                                HyperparamTuningInput exactly. Forwarded so the proposer's
                                evaluate_time_skill gate constructs the same SampleSet the
                                tuner will use (docs/resource_estimator_implement.md §2.7.2/§2.7.5).
                                Each falls through to the ProposalInput schema default when
                                None — partial workflow plumbing must not silently reset a
                                field the caller didn't touch.
      - trial_time_budget_minutes / formal_time_budget_minutes :
                                wall-time gate budgets, one per mode (Phase I two-budget split).
                                The proposer's baseline gate picks the one matching inp.is_trial.
                                Each None independently disables the gate for that mode.
      - data_dir             : TIDMAD data directory; required for the skill's real-dataset warmup.
      - recent_tune_outputs  : the last up-to-K tuner outputs (oldest first), where K is
                                the workflow's bounded FIFO size (Phase N sets K=3, §14.N).
                                Each output's ``gate_exhaustion`` is extracted; None values
                                are skipped. The surviving entries populate
                                ``ProposalInput.recent_gate_exhaustions`` so the proposer
                                prompt can render the [RECENT GATE EXHAUSTIONS] block over
                                multiple recent iterations — Phase N (§14.N) fix for the
                                §13.9 single-step-memory gap. When the sequence is empty
                                or all elements' ``gate_exhaustion`` are None, the
                                ProposalInput field stays at its schema default (``[]``)
                                and the prompt block is suppressed.

    Populates in ml-model-propose (ProposalInput):
      - interpretation       : full serialised InterpretationOutput (all fields above)
      - existing_model_types : output.model_types (names the proposal must not reuse)
      - expert_context       : merged list of ExpertContextItems
      - vocab_seed           : runtime vocabulary entries
      - reasoning_pipeline   : pipeline configuration
      - mindset              : passed through when provided
      - agent_cards          : passed through when provided
      - is_trial / trial_strategy / trial_portion / target_files / train_portion /
        sampling_seed / trial_time_budget_minutes / formal_time_budget_minutes /
        data_dir : passed through when provided; otherwise the ProposalInput
        schema defaults apply.
      - storage              : passed through from the orchestrator
    """
    # Build expert_context — start with what's passed, wrap legacy human_advice
    merged_context = list(expert_context or [])
    if human_advice is not None:
        advice_text = serialize_expert_advice(human_advice)
        if advice_text:
            merged_context.append(ExpertContextItem(
                source="human",
                kind="human",
                content=advice_text,
                cite_id="human_advice",
            ))

    result = {
        "interpretation":       output.model_dump(),
        "existing_model_types": list(output.model_types),
        "expert_context":       [c.model_dump() for c in merged_context],
        "storage":              storage.model_dump(),
    }

    # Typed mirror of interpretation.per_model_score_tables. Populated only
    # when upstream has tables — None keeps the ProposalInput default for
    # back-compat with interpretation outputs from pre-score_table runs.
    if output.per_model_score_tables:
        result["per_model_score_tables"] = {
            mt: st.model_dump() for mt, st in output.per_model_score_tables.items()
        }

    # Prefer runtime_vocab from interpretation output (accumulated memory)
    # over the static seed. Falls back to static seed if interpretation
    # didn't produce runtime_vocab (first iteration or legacy mode).
    if hasattr(output, "runtime_vocab") and output.runtime_vocab:
        result["vocab_seed"] = [
            v.model_dump() if hasattr(v, "model_dump") else v
            for v in output.runtime_vocab
        ]
    elif vocab_seed:
        result["vocab_seed"] = [v.model_dump() for v in vocab_seed]

    if reasoning_pipeline:
        result["reasoning_pipeline"] = reasoning_pipeline.model_dump()

    if mindset is not None:
        result["mindset"] = mindset

    if agent_cards:
        result["agent_cards"] = [
            c.model_dump() if hasattr(c, "model_dump") else c
            for c in agent_cards
        ]

    # Run-level fields for the proposer's evaluate_time_skill gate. Each is
    # only included when the caller supplied it; otherwise ProposalInput's
    # schema default takes effect (mirrors HyperparamTuningInput defaults:
    # is_trial=False, trial_strategy="snapshot", trial_portion=0.1,
    # target_files=[], train_portion=0.1, sampling_seed=None,
    # trial_time_budget_minutes=None, formal_time_budget_minutes=None,
    # data_dir=None). Phase I splits the single budget into two so each mode
    # has its own ceiling; both are independently optional.
    if is_trial is not None:
        result["is_trial"] = is_trial
    if trial_strategy is not None:
        result["trial_strategy"] = trial_strategy
    if trial_portion is not None:
        result["trial_portion"] = trial_portion
    if target_files is not None:
        result["target_files"] = target_files
    if train_portion is not None:
        result["train_portion"] = train_portion
    if sampling_seed is not None:
        result["sampling_seed"] = sampling_seed
    if trial_time_budget_minutes is not None:
        result["trial_time_budget_minutes"] = trial_time_budget_minutes
    if formal_time_budget_minutes is not None:
        result["formal_time_budget_minutes"] = formal_time_budget_minutes
    if data_dir is not None:
        result["data_dir"] = data_dir

    # Phase N (§14.N) — aggregate gate-exhaustion reports across up to K
    # recent iterations. Oldest-first order is preserved from the caller;
    # iterations whose tuner returned ``gate_exhaustion=None`` are dropped
    # (so ``recent_gate_exhaustions`` is a sparse record of aborts only).
    # When every entry's ``gate_exhaustion`` is None the field stays at its
    # ProposalInput default ([]) and the proposer prompt's [RECENT GATE
    # EXHAUSTIONS] block is suppressed. Replaces K.7.4's singular pass-through
    # — see §10.13 for detection criteria, §14.N for the window semantics.
    collected_gate_exhaustions = [
        tune_out.gate_exhaustion.model_dump()
        for tune_out in recent_tune_outputs
        if tune_out is not None and tune_out.gate_exhaustion is not None
    ]
    if collected_gate_exhaustions:
        result["recent_gate_exhaustions"] = collected_gate_exhaustions

    return ProposalInput.model_validate(result)


def database_full_context(
    output: InterpretationOutput,
    storage: StorageConfig,
) -> ProposalInput:
    """
    Database-backed protocol — reads the full interpretation from the database
    and returns a fully populated ProposalInput. The receiving node sees the same
    complete schema as with local_full_context; it never touches storage directly.

    Consumes from ml-result-interp (InterpretationOutput):
      - model_types          : used to query the correct DB partition
      - run_name (via storage): used to query the correct interpretation record

    Populates in ml-model-propose (ProposalInput):
      - interpretation       : fully populated by fetching the interpretation from the DB
      - existing_model_types : output.model_types passed through
      - storage              : passed through from the orchestrator
    """
    raise NotImplementedError(
        "database_full_context is not yet implemented. "
        "Wire a Postgres StorageConfig backend first."
    )
