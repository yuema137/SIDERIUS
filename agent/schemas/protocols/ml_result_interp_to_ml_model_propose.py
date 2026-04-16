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

from typing import List, Optional

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import (
    AgentCard,
    ExpertContextItem,
    ProposalInput,
    ReasoningPipelineConfig,
    VocabEntry,
)
from agent.schemas.hyperparam_tuning import ExpertAdviceInput, serialize_expert_advice
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
) -> ProposalInput:
    """
    Local in-memory protocol — transfers the complete interpretation directly.

    Consumes from ml-result-interp (InterpretationOutput):
      - model_types          : all architectures analysed
      - model_descriptions   : full markdown descriptions of each architecture
      - per_model_best/worst, best_denoising_score, best_config
      - key_findings, bottlenecks, take_home_message
      - per_model_file_vectors  : per-file denoising scores per model (frequency analysis)
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

    Populates in ml-model-propose (ProposalInput):
      - interpretation       : full serialised InterpretationOutput (all fields above)
      - existing_model_types : output.model_types (names the proposal must not reuse)
      - expert_context       : merged list of ExpertContextItems
      - vocab_seed           : runtime vocabulary entries
      - reasoning_pipeline   : pipeline configuration
      - mindset              : passed through when provided
      - agent_cards          : passed through when provided
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
