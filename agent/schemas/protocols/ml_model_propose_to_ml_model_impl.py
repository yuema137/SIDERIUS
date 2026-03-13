# agent/schemas/protocols/ml_model_propose_to_ml_model_impl.py
"""
Protocol: ml-model-propose -> ml-model-impl

Functions:
  local_full_spec   — passes the full ProposalOutput in-memory to ImplementorInput
  database_full_spec — reads proposal from DB, returns fully populated ImplementorInput
                       (NotImplementedError placeholder — not yet implemented)

Naming convention:
  transport: local | database
  data_scope: full_spec — all fields needed by the implementor
"""

from agent.schemas.proposal import ProposalOutput
from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import StorageConfig


def local_full_spec(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput:
    """
    Map ProposalOutput -> ImplementorInput in-memory.

    Passes model_name, model_description, mathematical_definition, and
    baseline_config directly from the proposal. plugin_dir and test_dir
    use their ImplementorInput defaults (agent_generated/models and
    agent_generated/tests).
    """
    return ImplementorInput(
        model_name=output.model_name,
        model_description=output.model_description,
        mathematical_definition=output.mathematical_definition,
        baseline_config=output.baseline_config,
        storage=storage,
    )


def database_full_spec(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput:
    """
    Read proposal from database and return a fully populated ImplementorInput.

    When implemented, this function will read the proposal record from the
    database identified by storage and return a fully populated ImplementorInput —
    the calling node never needs to know which transport was used.
    """
    raise NotImplementedError("database_full_spec is not yet implemented")
