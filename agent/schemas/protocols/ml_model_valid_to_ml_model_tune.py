# agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py
"""
Protocol: ml-model-valid -> ml-model-tune
(ml_code_validator_agent -> tune_ml_hyperparam_agent)

Functions:
  local_validated_model  — passes the validated model_type in-memory to HyperparamTuningInput
  database_validated_model — DB-backed transfer (NotImplementedError placeholder)

Naming convention:
  transport: local | database
  data_scope: validated_model — the confirmed model type, ready for tuning

Note: this protocol should only be called when ValidatorOutput.passed is True.
The orchestrator is responsible for checking passed before traversing this edge.
"""

from agent.schemas.validator import ValidatorOutput
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import StorageConfig


def local_validated_model(
    output: ValidatorOutput,
    storage: StorageConfig,
    max_rounds: int = 50,
    file_index: int = 6,
    llm_provider: str = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
) -> HyperparamTuningInput:
    """
    Map ValidatorOutput -> HyperparamTuningInput in-memory.

    Consumes from ml-model-valid (ValidatorOutput):
      - model_type: the validated plugin key

    Populates in ml-model-tune (HyperparamTuningInput):
      - model_type    : from ValidatorOutput
      - storage       : passed through from the orchestrator
      - max_rounds    : tuning budget (caller-supplied, default 50)
      - file_index    : data split index (caller-supplied, default 6)
      - llm_provider  : LLM backend (caller-supplied, default gemini)
      - llm_model_id  : specific model ID (caller-supplied, default gemini-3.1-flash-lite-preview)
      - expert_advice : empty string (no prior guidance at first tuning run)
      - seed_records  : empty list (no prior experiments)
    """
    return HyperparamTuningInput(
        model_type=output.model_type,
        file_index=file_index,
        max_rounds=max_rounds,
        expert_advice="",
        seed_records=[],
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
        storage=storage,
    )


def database_validated_model(
    output: ValidatorOutput,
    storage: StorageConfig,
    **kwargs,
) -> HyperparamTuningInput:
    """
    DB-backed protocol — reads the validated model record from the database and
    returns a fully populated HyperparamTuningInput. Raises NotImplementedError
    until a Postgres StorageConfig backend is wired.
    """
    raise NotImplementedError(
        "database_validated_model is not yet implemented. "
        "Wire a Postgres StorageConfig backend first."
    )
