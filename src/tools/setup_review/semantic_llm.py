"""The explicitly selected provider boundary; never imported for a skip."""

from pathlib import Path

from core.execution_deadline import remaining_seconds
from nodes.llm_settings import node_bridge_kwargs
from tools.setup_review.semantic_models import ReviewSnapshotRequest, SetupJudgement


def request_judgement(
    operation: ReviewSnapshotRequest, system: str, user: str, run_id: str
) -> SetupJudgement:
    from agent.llm_bridge import LLMBridge

    remaining_seconds("setup_review.gateway_import")
    config = operation.llm
    bridge = LLMBridge(
        **node_bridge_kwargs(
            provider=config.provider,
            model_id=config.model_id,
            max_retries=config.max_retries,
            reasoning_effort=config.reasoning_effort,
        ),
        request_timeout=operation.request_timeout_seconds,
    )
    remaining_seconds("setup_review.gateway_constructed")
    bridge.set_run_context(
        workspace=Path(operation.output), iter=0, run_name="setup-review", run_id=run_id
    )
    remaining_seconds("setup_review.before_request")
    result = bridge.generate(system, user, label="setup_review.judge")
    remaining_seconds("setup_review.response")
    judgement = SetupJudgement.model_validate(result)
    remaining_seconds("setup_review.validated")
    return judgement
