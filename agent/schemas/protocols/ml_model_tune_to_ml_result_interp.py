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
local_all_records       Direct in-memory transfer of the full experiment history.

Planned
-------
database_all_records    DB-backed transfer: tune agent writes records to the database,
                        interp agent reads them from the database. Requires a Postgres
                        StorageConfig backend. Raises NotImplementedError until wired.
"""

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput
from agent.schemas.storage import StorageConfig


def local_all_records(
    output: HyperparamTuningOutput,
    storage: StorageConfig,
) -> InterpretationInput:
    """
    Local in-memory protocol — transfers the full experiment history directly.

    Consumes from ml-model-tune (HyperparamTuningOutput):
      - all_records  : full experiment history (success, error, OOM-skipped)
      - model_type   : architecture key
      - run_name     : run identifier

    Populates in ml-result-interp (InterpretationInput):
      - summaries    : [SummaryGroup(model_type, run_name, records)]
      - storage      : passed through from the orchestrator
    """
    records = [r.model_dump() for r in output.all_records]

    return InterpretationInput.model_validate({
        "summaries": [
            {
                "model_type": output.model_type,
                "run_name":   output.run_name,
                "records":    records,
            }
        ],
        "storage": storage.model_dump(),
    })


def database_all_records(
    output: HyperparamTuningOutput,
    storage: StorageConfig,
) -> InterpretationInput:
    """
    Database-backed protocol — reads all experiment records from the database
    and returns a fully populated InterpretationInput. The receiving node sees
    the same complete schema as with local_all_records; it never touches storage
    directly.

    Consumes from ml-model-tune (HyperparamTuningOutput):
      - model_type   : used to query the correct DB partition
      - run_name     : used to query the correct run in the DB

    Populates in ml-result-interp (InterpretationInput):
      - summaries    : [SummaryGroup(model_type, run_name, records)] — fully populated
                       by fetching all records from the database
      - storage      : passed through from the orchestrator
    """
    raise NotImplementedError(
        "database_all_records is not yet implemented. "
        "Wire a Postgres StorageConfig backend first."
    )
