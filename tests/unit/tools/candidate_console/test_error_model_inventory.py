"""Bind whole ReviewView serialization coverage to every typed native failure path."""

from collections.abc import Iterator
from typing import get_args, get_origin

from pydantic import BaseModel

from tests.unit.tools.candidate_console.test_editor import editor_config
from tests.unit.tools.candidate_console.test_editor_errors import SECRET, failed_review
from tools.candidate_console.error_messages import safe_review
from tools.setup_review.composition_models import CheckFailure
from tools.workflow_authoring.models import ReviewRequest, ReviewView
from tools.workflow_authoring.service import WorkflowAuthoring

# These are projection coverage obligations, not assertions about schema validity.
# Each must be populated by the fixture and sanitized by both existing HTTP surfaces
# (test_editor_errors: ordinary review and AuthoringError.proposal).
FAILURE_PATHS = {
    ("task_reference_update", "observation", "result", "failure"),
    ("task_reference_update", "current_observation", "result", "failure"),
}


def _failure_paths(
    annotation: object, prefix: tuple[str, ...] = (), seen: tuple[type, ...] = ()
) -> Iterator[tuple[str, ...]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if issubclass(annotation, CheckFailure):
            yield prefix
        elif annotation not in seen:
            for name, field in annotation.model_fields.items():
                yield from _failure_paths(field.annotation, (*prefix, name), (*seen, annotation))
        return
    child_prefix = (*prefix, "*") if get_origin(annotation) in (list, tuple, dict) else prefix
    for child in get_args(annotation):
        yield from _failure_paths(child, child_prefix, seen)


def _at(payload: dict, path: tuple[str, ...]) -> dict:
    for field in path:
        payload = payload[field]
    return payload


def test_every_whole_review_failure_path_has_a_live_projection_witness(editor_config):
    """A new nested carrier requires coverage even if no adapter reads .failure.message."""
    assert set(_failure_paths(ReviewView)) == FAILURE_PATHS, (
        "ReviewView gained an unreviewed failure carrier; extend the safe projection and HTTP witness."
    )
    service = WorkflowAuthoring(editor_config.editor_projects[0])
    base = service.read()
    native = failed_review(
        service.review(
            ReviewRequest.model_validate(
                {
                    "expected_sha256": base.sha256,
                    "proposal": {"kind": "source", "source": base.source},
                }
            )
        ),
        service.project.project_root,
        SECRET,
    )
    before = native.model_dump(mode="json")
    projected = safe_review(native)
    after = projected.model_dump(mode="json")
    for path in FAILURE_PATHS:
        assert SECRET in _at(before, path)["message"], (
            "Fixture must populate every inventoried path"
        )
        assert SECRET not in str(_at(after, path))
        assert _at(after, path)["exception_type"] in {"invalid", "unexpected"}
    assert SECRET not in projected.model_dump_json()
    assert native.model_dump(mode="json") == before
