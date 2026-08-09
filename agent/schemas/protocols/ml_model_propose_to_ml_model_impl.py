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

from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import StorageConfig


def local_full_spec(output: ProposalOutput, storage: StorageConfig) -> ImplementorInput:
    """
    Map ProposalOutput -> ImplementorInput in-memory.

    Passes model_name, model_description, mathematical_definition,
    baseline_config, and custom_loss_spec directly from the proposal.
    plugin_dir, test_dir, and loss_dir use their ImplementorInput defaults
    (agent_generated/models, agent_generated/tests, agent_generated/losses);
    the workflow overrides loss_dir to a per-run path before invoking the
    implementor so concurrent iterations do not clobber each other's losses.

    custom_loss_spec is forwarded unchanged — it is None when the proposer
    used a built-in loss type, and a CustomLossSpec instance when L4 should
    generate (or reuse) a custom loss plugin. See
    docs/design/enable_loss_inventory.md § Commit L3.
    """
    return ImplementorInput(
        # V21 PR E hop 2: the system-minted identity travels inside the
        # objects, so this protocol maps it field->field like every other
        # field. None propagates for pre-PR-E / non-proposer candidates.
        candidate_id=output.candidate_id,
        model_name=output.model_name,
        # V21 PR A3: the output contract must survive this hop. If it is dropped
        # here, a proposal declaring `regressor` silently produces a classifier
        # plugin — "produced but not delivered", the exact failure class V20
        # kept hitting. tests/unit/agent/protocols/ asserts this hop explicitly.
        output_type=output.output_type,
        model_description=output.model_description,
        mathematical_definition=output.mathematical_definition,
        baseline_config=output.baseline_config,
        custom_loss_spec=output.custom_loss_spec,
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
