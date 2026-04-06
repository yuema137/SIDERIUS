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

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import StorageConfig


def local_full_context(
    output: InterpretationOutput,
    storage: StorageConfig,
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

    Populates in ml-model-propose (ProposalInput):
      - interpretation       : full serialised InterpretationOutput (all fields above)
      - existing_model_types : output.model_types (names the proposal must not reuse)
      - storage              : passed through from the orchestrator
    """
    return ProposalInput.model_validate({
        "interpretation":       output.model_dump(),
        "existing_model_types": list(output.model_types),
        "storage":              storage.model_dump(),
    })


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
