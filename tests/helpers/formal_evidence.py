"""Explicit Health-disabled record evidence for authority-filter fixtures."""

from execute_tools.formal_evidence import FormalResultEvidence


def disabled_formal_evidence(model_type: str, score: float | None) -> FormalResultEvidence:
    """Declare the fixture's waiver independently from any stored verdict."""
    return FormalResultEvidence(
        model_type=model_type,
        run_name="v1",
        exp_id=f"{model_type}_formal",
        status="success",
        denoising_score=score,
        is_trial=False,
        health_gate_enabled=False,
        required_gate_ids=None,
        healthgate_mode="blocking",
        result_authority="scientific",
    )
