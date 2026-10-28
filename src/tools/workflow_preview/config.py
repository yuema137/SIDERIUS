"""Preview entry point for captured ``llm_config`` bytes.

The strict unknown-key and duplicate-alias check is owned by
``workflows.llm_config.parse_llm_config_bytes``; this module only forwards to it.
"""

from workflows.llm_config import WorkflowLLMConfig, parse_llm_config_bytes


def parse_config(content: bytes) -> WorkflowLLMConfig:
    """Validate captured JSON, preserving missing blocks and explicit retry intent."""
    return parse_llm_config_bytes(content)
