"""Census every reachable persisted model field, not only known score examples.

Probe field types only to select witnesses. Assertions exercise our encoder and
native field serialization; this does not retest Pydantic's rejection policy.
"""

import json
import math
from typing import get_args

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ProposalOutput
from agent.schemas.validator import ValidatorOutput
from core.record_encoding import decode_record, record_json
from tools.candidate_worker.models import CandidateRunReceipt

ROOTS = (
    CandidateRunReceipt,
    ExperimentRecord,
    HyperparamTuningOutput,
    ImplementorOutput,
    InterpretationOutput,
    LiteratureReviewOutput,
    ProposalOutput,
    ValidatorOutput,
)


def models():
    pending = list(ROOTS)
    seen = set()
    while pending:
        annotation = pending.pop()
        pending.extend(get_args(annotation))
        if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
            continue
        if annotation in seen:
            continue
        seen.add(annotation)
        yield annotation
        pending.extend(field.annotation for field in annotation.model_fields.values())


def witnesses(annotation):
    adapter = TypeAdapter(annotation)
    for number in (float("inf"), float("-inf"), float("nan")):
        for candidate in (number, [number], {"witness": number}):
            try:
                accepted = adapter.validate_python(candidate)
            except (ValidationError, TypeError, KeyError):
                continue
            if contains_nonfinite(accepted):
                yield candidate, accepted


def cases():
    for model in models():
        for name, field in model.model_fields.items():
            for candidate, accepted in witnesses(field.rebuild_annotation()):
                yield pytest.param(model, name, accepted, id=f"{model.__name__}.{name}:{candidate}")


def contains_nonfinite(value):
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, dict):
        return any(contains_nonfinite(v) for v in value.values())
    if isinstance(value, (tuple, list)):
        return any(contains_nonfinite(v) for v in value)
    return False


@pytest.mark.parametrize("model,name,value", list(cases()))
def test_all_admitted_nonfinite_field_witnesses_survive_record_serialization(model, name, value):
    # Construct only the selected field: sibling required fields and cross-field
    # scientific checks are irrelevant to a serializer census. Full-model/native
    # round trips are covered separately by the worker regressions.
    instance = model.model_construct(**{name: value})
    payload = record_json(instance, include={name})
    raw = json.loads(payload, parse_constant=lambda token: pytest.fail(f"bare constant: {token}"))
    restored = decode_record(raw)
    assert contains_nonfinite(restored[name]), f"{model.__name__}.{name} lost its float"
    assert record_json(model.model_construct(**restored), include={name}) == payload


def test_census_includes_required_prediction_and_score_models():
    names = {model.__name__ for model in models()}
    assert {"AggregateScalars", "FalsifiablePrediction", "ExperimentRecord"} <= names
