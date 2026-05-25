# agent/schemas/protocols/__init__.py
"""
Protocol registry for the SIDERIUS node graph.

One module per directed edge, named {source_code}_to_{target_code}.
Each module contains protocol functions named {transport}_{data_scope}.

  transport  : how data moves (local = in-memory, database = via Postgres)
  data_scope : what subset of the source output is transferred

Workflows and orchestrators import from this module and choose which protocol to apply.

Implemented edges
-----------------
ml_model_tune_to_ml_result_interp      tune_ml_hyperparam_agent -> result_interpretation_agent
ml_result_interp_to_ml_model_propose   result_interpretation_agent -> ml_model_proposal_agent
ml_model_propose_to_ml_model_impl      ml_model_proposal_agent -> ml_model_implementor
ml_model_impl_to_ml_model_valid        ml_model_implementor -> ml_code_validator_agent
ml_model_valid_to_ml_model_tune        ml_code_validator_agent -> tune_ml_hyperparam_agent (fan-in: also consumes ProposalOutput)
"""

from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import (
    database_all_fields as impl_to_valid__database_all_fields,
)
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import (
    local_all_fields as impl_to_valid__local_all_fields,
)
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import (
    database_full_spec as propose_to_impl__database_full_spec,
)
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import (
    local_full_spec as propose_to_impl__local_full_spec,
)
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import (
    database_all_records as tune_to_interp__database_all_records,
)
from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import (
    local_all_records as tune_to_interp__local_all_records,
)
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    database_validated_model as valid_to_tune__database_validated_model,
)
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    local_validated_model as valid_to_tune__local_validated_model,
)
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    database_full_context as interp_to_propose__database_full_context,
)
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
    local_full_context as interp_to_propose__local_full_context,
)

__all__ = [
    "impl_to_valid__database_all_fields",
    "impl_to_valid__local_all_fields",
    "interp_to_propose__database_full_context",
    "interp_to_propose__local_full_context",
    "propose_to_impl__database_full_spec",
    "propose_to_impl__local_full_spec",
    "tune_to_interp__database_all_records",
    "tune_to_interp__local_all_records",
    "valid_to_tune__database_validated_model",
    "valid_to_tune__local_validated_model",
]
