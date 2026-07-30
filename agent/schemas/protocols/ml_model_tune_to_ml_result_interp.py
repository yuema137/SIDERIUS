# agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py
"""
Edge protocols: ml-model-tune → ml-result-interp
(tune_ml_hyperparam_agent → result_interpretation_agent)

Each function is a distinct protocol on this edge. Orchestrators choose
which protocol to apply at traversal time.

Protocol naming convention: {transport}_{data_scope}
  transport  : how data moves between nodes (local = in-memory, database = via DB)
  data_scope : what subset of the source output is transferred

Implemented
-----------
local_all_records       Converts HyperparamTuningOutput to a condensed ModelRunSummary
                        (scores, trajectory, conclusions) and wraps it in InterpretationInput.

Planned
-------
database_all_records    DB-backed transfer. Raises NotImplementedError until wired.
"""

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput
from agent.schemas.storage import StorageConfig
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary


def local_all_records(
    output: HyperparamTuningOutput,
    storage: StorageConfig,
) -> InterpretationInput:
    """
    Local in-memory protocol — converts tuning output to a condensed summary.

    Consumes from ml-model-tune (HyperparamTuningOutput):
      - model_type, run_name, status, completed_rounds
      - best_denoising_score, best_config
      - best_score_table, formal_score_table (enriched per-file view of
        best_file_vector / formal_file_vector; populated by the tuner per
        Phase 3-B. Threaded into the ModelRunSummary so downstream agents
        can read the pre-rendered markdown directly.)
      - all_records (used to extract round_scores, round_conclusions,
        round_ordering, and round_health — the per-round condensed
        HealthGate evidence incl. collapse fingerprints, V19 PR 3 —
        then discarded; raw records are NOT passed to the
        interpretation agent)

    Populates in ml-result-interp (InterpretationInput):
      - summaries    : [ModelRunSummary] — condensed run summary
      - storage      : passed through from the workflow
    """
    summary = tuning_output_to_model_run_summary(output)

    return InterpretationInput(
        summaries=[summary],
        storage=storage,
    )


def database_all_records(
    output: HyperparamTuningOutput,
    storage: StorageConfig,
) -> InterpretationInput:
    """
    Database-backed protocol — reads run summary from the database and returns
    a fully populated InterpretationInput. Raises NotImplementedError until wired.
    """
    raise NotImplementedError(
        "database_all_records is not yet implemented. Wire a Postgres StorageConfig backend first."
    )
