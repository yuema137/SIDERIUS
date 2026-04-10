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
The workflow is responsible for checking passed before traversing this edge.

Fan-in protocol: consumes ValidatorOutput (adjacent node) and ProposalOutput
(non-adjacent, held by the workflow). The validator confirms the model is valid;
the proposal provides expert_advice and baseline_config for the tuning agent.
"""

from typing import List, Literal, Optional

from agent.schemas.validator import ValidatorOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import StorageConfig


def local_validated_model(
    output: ValidatorOutput,
    proposal: ProposalOutput,
    storage: StorageConfig,
    max_rounds: int = 50,
    file_index: int = 6,
    llm_provider: str = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
    reflect_provider: Optional[Literal["gemini", "openai"]] = None,
    reflect_model_id: Optional[str] = None,
    # --- Trial mode (optional — all defaults preserve normal single-file behavior) ---
    is_trial: bool = False,
    trial_strategy: Literal["snapshot", "anchors", "target"] = "snapshot",
    trial_portion: float = 0.1,
    target_files: Optional[List[int]] = None,
    train_portion: float = 0.1,
    eval_strategy: Literal["snapshot", "anchors", "target"] = "snapshot",
    eval_portion: float = 0.1,
    train_validation_align: bool = True,
    sampling_seed: Optional[int] = None,
    train_base_seed: Optional[int] = None,
    cleanup_denoised: bool = False,
    max_epochs: Optional[int] = None,
    max_retries: Optional[int] = None,
) -> HyperparamTuningInput:
    """
    Map ValidatorOutput + ProposalOutput -> HyperparamTuningInput in-memory.

    Consumes from ml-model-valid (ValidatorOutput):
      - model_type: the validated plugin key

    Consumes from ml-model-propose (ProposalOutput, held by workflow):
      - expert_advice  : structured guidance for the tuning agent
      - baseline_config: safe starting configuration for the new model

    Populates in ml-model-tune (HyperparamTuningInput):
      - model_type    : from ValidatorOutput
      - expert_advice : from ProposalOutput
      - storage       : passed through from the workflow
      - max_rounds    : tuning budget (caller-supplied, default 50)
      - file_index    : data split index (caller-supplied, default 6; ignored when is_trial=True)
      - llm_provider  : planner-call provider (caller-supplied, default gemini)
      - llm_model_id  : planner-call model ID (caller-supplied)
      - reflect_provider : optional separate provider for the tuner's
        reflect() call. None means the reflector uses llm_provider.
      - reflect_model_id : optional separate model for the tuner's
        reflect() call. None means the reflector uses llm_model_id.
      - is_trial + trial_*: trial mode configuration (caller-supplied, defaults to single-file)
    """
    return HyperparamTuningInput(
        model_type=output.model_type,
        file_index=file_index,
        max_rounds=max_rounds,
        expert_advice=proposal.expert_advice,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        storage=storage,
        is_trial=is_trial,
        trial_strategy=trial_strategy,
        trial_portion=trial_portion,
        target_files=target_files or [],
        train_portion=train_portion,
        eval_strategy=eval_strategy,
        eval_portion=eval_portion,
        train_validation_align=train_validation_align,
        sampling_seed=sampling_seed,
        train_base_seed=train_base_seed,
        cleanup_denoised=cleanup_denoised,
        max_epochs=max_epochs,
        max_retries=max_retries,
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
