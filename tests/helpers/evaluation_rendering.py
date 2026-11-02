"""Fixed scientific declarations for offline renderer and consumer witnesses."""

from contextlib import contextmanager
from pathlib import Path

from agent.evaluation_context import bind_evaluation_prompt_context
from tests.helpers.metric_fixtures import shipped_spec
from workflows.evaluation_composition import compose_evaluation


def evaluation_fixture(root: Path, *, formula: bool = False):
    primary = shipped_spec().model_copy(update={"id": "validation_accuracy", "direction": "higher"})
    error = primary.model_copy(update={"id": "validation_error", "direction": "lower"})
    declaration = {
        "components": [
            {
                "id": "quality",
                "kind": "metric",
                "metric": primary.id,
                "meaning": "Fraction of correct predictions on the evaluation split.",
                "units": "fraction",
                "range": {"lower": 0.0, "upper": 1.0},
            },
            {
                "id": "error",
                "kind": "metric",
                "metric": error.id,
                "meaning": "Mean absolute voltage error on the evaluation split.",
                "units": "mV",
                "range": {"lower": 0.0, "upper": 100.0},
            },
        ],
        "selection": {"kind": "primary"},
    }
    if formula:
        declaration["selection"] = {
            "kind": "formula",
            "formula": {
                "family": "weighted_sum",
                "params": {
                    "terms": [
                        {
                            "component": "quality",
                            "weight": 3.0,
                            "lower": 0.0,
                            "upper": 1.0,
                            "out_of_range": "refuse",
                        },
                        {
                            "component": "error",
                            "weight": 1.0,
                            "lower": 0.0,
                            "upper": 10.0,
                            "out_of_range": "clip",
                        },
                    ]
                },
            },
        }
    resolved = compose_evaluation(
        {"evaluation": declaration}, str(root), {primary.id: primary, error.id: error}, None
    )
    assert resolved is not None
    return resolved, primary


@contextmanager
def evaluation_scope(root: Path):
    resolved, primary = evaluation_fixture(root)
    with bind_evaluation_prompt_context(resolved, primary, None):
        yield
