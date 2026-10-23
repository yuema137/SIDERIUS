"""Compare reviewed intent against durable admission without observing current files."""

from tools.candidate_prepare.reusable_models import ReusablePreparationObservations

from .models import OperationFailure, OperationRecord, ReusablePreparationExpectation


def compare_reusable_expectation(
    record: OperationRecord, expected: ReusablePreparationExpectation | None
) -> None:
    if expected is None:
        return
    if (
        record.submission.kind != "prepare_reusable"
        or record.request_digest != expected.request_digest
        or ReusablePreparationObservations.from_inputs(record.inputs) != expected.observations
    ):
        raise OperationFailure(
            "conflict", "reusable request or observations differ from reviewed intent"
        )
