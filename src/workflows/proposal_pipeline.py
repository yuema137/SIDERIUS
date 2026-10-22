"""Shared native proposal reasoning-stage selection."""

from workflows.llm_config import ProposalLLMConfig, WorkflowLLMConfig
from workflows.strategy_modes import ExplorationMode


def get_reasoning_pipeline(
    llm_config: WorkflowLLMConfig,
    exploration_mode: ExplorationMode = "auto",
    minimum_boldness: float = 0.05,
    n_candidates: int | None = None,
):
    """Build a ReasoningPipelineConfig from the workflow's ProposalLLMConfig.

    Returns None if propose is not a ProposalLLMConfig (legacy mode).

    Args:
        llm_config: Workflow LLM config; must have a ProposalLLMConfig in the
            propose slot for the pipeline to be active.
        exploration_mode: One of "auto", "explore", "exploit".
            "auto" lets the pipeline resolver choose based on n_agent_proposed
            and vocab_diversity_ratio. "explore" and "exploit" force the mode
            regardless of those signals.
        minimum_boldness: Minimum required boldness for a FalsifiablePrediction
            (|predicted - current| / |current|). Predictions below this threshold
            trigger a causal_reasoning retry. Default 0.05.
        n_candidates: Optional override for the top-N candidate cut used by the
            comparison stage. When None, falls through to the schema default
            (ModelSelectionStrategy → {"n": 5}). Set to a larger value for
            large-scale experiments that want more past models in the prompt.
    """
    if llm_config.propose and isinstance(llm_config.propose, ProposalLLMConfig):
        from agent.schemas.proposal import (
            ModelSelectionStrategy,
            ReasoningPipelineConfig,
            ReasoningStage,
            ResearchPolicy,
        )

        selection = (
            ModelSelectionStrategy(params={"n": n_candidates})
            if n_candidates is not None
            else ModelSelectionStrategy()
        )
        pipeline = ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
            model_selection=selection,
            exploration_mode=exploration_mode,
            policy=ResearchPolicy(minimum_boldness=minimum_boldness),
        )
        return pipeline
    return None
