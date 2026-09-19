"""Bind prediction comparisons to the proposer's measured input evidence."""

from agent.schemas.prediction_reference import ObservedPredictionReference
from agent.schemas.proposal import FalsifiablePrediction, ProposalInput


def observed_prediction_reference(
    inp: ProposalInput, metric: str
) -> ObservedPredictionReference | None:
    """Only the declared primary metric has a scalar observation here.

    Do not guess free-text metrics or assign a primary score to a per-file
    prediction. Those require their own explicit evidence projection.
    """
    evidence = inp.interpretation_evidence
    identity = evidence.metric_identity
    value = evidence.best_valid_denoising_score
    if inp.cold_start or identity is None or value is None or metric != identity.id:
        return None
    return ObservedPredictionReference(
        metric_id=identity.id, direction=identity.direction, value=value
    )


def ground_prediction(
    prediction: FalsifiablePrediction, reference: ObservedPredictionReference | None
) -> FalsifiablePrediction:
    """Revalidate after replacing an authored baseline with observed evidence.

    Grounding can turn an apparently different prediction into a no-change
    prediction. Do not persist an object that its own schema would reject on
    resume.
    """
    payload = prediction.model_dump()
    payload["current_value"] = reference.value if reference else None
    return FalsifiablePrediction.model_validate(payload)
