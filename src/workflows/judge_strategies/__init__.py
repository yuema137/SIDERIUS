"""LLM COMBINE strategies for B6 adaptors (B2): admit, run, replay.

Public API B6 calls: ``admit_llm_strategy`` (pure), ``strategy_items`` (projects
admissible items), ``run_llm_strategy`` (the only provider effect) and
``replay_llm_strategy`` (readback, never calls a provider).
Contract: ``judge-strategies-contract.md`` beside this file.
"""

from .admission import admit_llm_strategy
from .kinds import IMPLEMENTED_KINDS, strategy_call_bound
from .models import (
    CombinedItem,
    CombinedItems,
    ItemRanking,
    PromptBudgetExceeded,
    RubricScore,
    StrategyAdmission,
    StrategyError,
    StrategyEvidence,
    StrategyInvocation,
    StrategyItem,
    StrategyOutcome,
    StrategyRefusal,
    StrategyResult,
    invocation_sha256,
)
from .projection import ITEM_PROJECTORS, project_item, strategy_items
from .replay import replay_llm_strategy
from .run import run_llm_strategy

__all__ = [
    "IMPLEMENTED_KINDS",
    "ITEM_PROJECTORS",
    "CombinedItem",
    "CombinedItems",
    "ItemRanking",
    "PromptBudgetExceeded",
    "RubricScore",
    "StrategyAdmission",
    "StrategyError",
    "StrategyEvidence",
    "StrategyInvocation",
    "StrategyItem",
    "StrategyOutcome",
    "StrategyRefusal",
    "StrategyResult",
    "admit_llm_strategy",
    "invocation_sha256",
    "project_item",
    "replay_llm_strategy",
    "run_llm_strategy",
    "strategy_call_bound",
    "strategy_items",
]
