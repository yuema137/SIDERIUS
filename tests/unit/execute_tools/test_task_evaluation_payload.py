"""A multi-artifact task can name every deliverable checked before scoring."""

from execute_tools.denoising_score_single import _scoreable_payload
from execute_tools.task_data_path import TaskEvaluationPayload


def test_explicit_multi_artifact_payload_replaces_the_single_file_fallback() -> None:
    """Catches scoreability inspecting only one file of a multi-file result."""
    carrier = TaskEvaluationPayload(
        value={"decoded": "task value"},
        deliverables={2: "/predictions/two.h5", 7: "/predictions/seven.h5"},
    )

    value, deliverables = _scoreable_payload(carrier, {0: "/fallback/result.bin"})

    assert value == {"decoded": "task value"}
    assert deliverables == {
        2: "/predictions/two.h5",
        7: "/predictions/seven.h5",
    }


def test_plain_payload_preserves_the_single_declared_deliverable() -> None:
    """Catches changing the existing one-artifact task contract."""
    value, deliverables = _scoreable_payload({"class": 4}, {0: "/result.csv"})

    assert value == {"class": 4}
    assert deliverables == {0: "/result.csv"}
