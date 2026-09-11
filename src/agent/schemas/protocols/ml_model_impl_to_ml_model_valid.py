# agent/schemas/protocols/ml_model_impl_to_ml_model_valid.py
"""
Protocol: ml-model-impl -> ml-model-valid
(ml_model_implementor -> ml_code_validator_agent)

Functions:
  local_all_fields   — passes all fields in-memory to ValidatorInput
  database_all_fields — DB-backed transfer (NotImplementedError placeholder)

Naming convention:
  transport: local | database
  data_scope: all_fields — every field ValidatorInput requires from ImplementorOutput

Per the inter-node communication principle: the validator never reads the implementor's
output file from storage. All required data is mapped explicitly by this protocol.
"""

from typing import Literal

from agent.schemas.implementor import ImplementorOutput
from agent.schemas.storage import StorageConfig
from agent.schemas.validator import ValidatorInput


def local_all_fields(
    output: ImplementorOutput,
    storage: StorageConfig,
    llm_provider: Literal["gemini", "openai", "deepseek"] = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
) -> ValidatorInput:
    """
    Map ImplementorOutput -> ValidatorInput in-memory.

    Consumes from ml-model-impl (ImplementorOutput):
      - model_type            : plugin model key
      - model_file_path       : absolute path to the written plugin file
      - test_file_path        : absolute path to the written test file
      - description_file_path : absolute path to description.md
      - config_fields         : dict of field names -> default values
      - model_description     : plain-English description from the proposal
      - mathematical_definition: spec from the proposal
      - model_io_contract      : the normalized Step-03 Model-I/O contract the
                                 candidate was generated against, or None on
                                 the legacy prose-only path (Step 04a)

    Populates in ml-model-valid (ValidatorInput):
      - all eight fields above
      - storage, llm_provider, llm_model_id: passed from the orchestrator
    """
    return ValidatorInput(
        # V21 PR E hop 3: carried from the IMMEDIATE upstream (the
        # implementor's echo), not re-read from the proposal — so severing
        # any earlier echo is visible end to end instead of papered over.
        candidate_id=output.candidate_id,
        model_type=output.model_type,
        model_file_path=output.model_file_path,
        test_file_path=output.test_file_path,
        description_file_path=output.description_file_path,
        config_fields=output.config_fields,
        model_description=output.model_description,
        mathematical_definition=output.mathematical_definition,
        # Step 04a: the semantic declaration travels the SAME hop as the
        # artifact it describes. Mapped verbatim — never re-resolved here and
        # never defaulted, so a contract that existed upstream cannot be
        # replaced by a plausible-looking substitute on the way down.
        model_io_contract=output.model_io_contract,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
        storage=storage,
    )


def database_all_fields(
    output: ImplementorOutput,
    storage: StorageConfig,
    **kwargs,
) -> ValidatorInput:
    """
    DB-backed protocol — reads implementor output from the database and returns
    a fully populated ValidatorInput.
    """
    raise NotImplementedError(
        "database_all_fields is not yet implemented. Wire a Postgres StorageConfig backend first."
    )
