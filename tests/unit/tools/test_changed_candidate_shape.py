"""Changed-reference support is limited to the native fixed managed candidate shape."""

import pytest

from tests.unit.workflows.reusable_fixture import reusable
from tools.workflow_authoring.candidate_compatibility import _check_source
from workflows.definition import ReusableWorkflowDocument


def managed():
    raw = reusable().model_dump()
    raw["definition"]["externals"] = tuple(
        value for value in raw["definition"]["externals"] if value["id"] != "context"
    )
    raw["definition"]["nodes"][1]["request"]["arguments"] = tuple(
        value
        for value in raw["definition"]["nodes"][1]["request"]["arguments"]
        if value["name"] != "constraint_context"
    )
    return ReusableWorkflowDocument.model_validate(raw)


def test_fixed_managed_shape_does_not_change_graph_or_options():
    document = managed()
    _check_source(document, document)
    changed = document.model_copy(update={"positions": ()})
    with pytest.raises(ValueError, match="Save graph"):
        _check_source(document, changed)


def test_literal_context_cannot_inherit_changed_task():
    document = reusable()
    with pytest.raises(ValueError, match="managed proposal/storage"):
        _check_source(document, document)


@pytest.mark.parametrize("profile", ("native-proposal-fanout/v1",))
def test_profile_is_outside_fixed_candidate_update(profile):
    document = managed().model_copy(update={"execution_profile": profile})
    with pytest.raises(ValueError, match="without training or execution profiles"):
        _check_source(document, document)
