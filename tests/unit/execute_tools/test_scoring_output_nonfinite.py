"""Scoring child -> parent ``--output_json`` transport of non-finite metrics (#1316).

The child's real result emitter (``denoising_score_single._emit_outcome``) runs
in place of the subprocess; the parent is the real ``TidmadSandbox.execute_scoring``
and the tuner's adoption helpers. Only process creation is replaced.
"""

import importlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools import denoising_score_single as child
from execute_tools.data_paths import bind_physical_data_root
from execute_tools.evaluation_metric import MetricResult
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

# The package __init__ rebinds `execution`; import the submodules by name.
execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")
scoring_transport = importlib.import_module("nodes.ml_hyperparameter_tune_agent.scoring_transport")

QUICKSTART = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"
RUN_NAME = "run"
EXP_ID = "exp"
INF, NAN = float("inf"), float("nan")

# Bytes the pre-change child wrote for this finite outcome (captured at master
# fb52df064 before #1316): finite payloads must not acquire encoding metadata.
FINITE_BYTES = (
    b'{\n    "denoising_score": 0.5,\n    "file_vector": [\n        0.25,\n'
    b'        null,\n        0.75\n    ],\n    "metric_result": {\n'
    b'        "metric_id": "mse",\n        "direction": "lower",\n'
    b'        "scalar": 0.5,\n        "references_used": []\n    }\n}'
)


@pytest.fixture
def sandbox(tmp_path):
    composition = compose_run_task_bindings(str(QUICKSTART))
    with (
        bind_physical_data_root(str(tmp_path), purpose="scoring transport test"),
        bind_run_task_composition(composition, physical_data_root=str(tmp_path)),
    ):
        box = TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)
        os.makedirs(os.path.join(box.dirs["records"], RUN_NAME), exist_ok=True)
        yield box


def _score(sandbox, outcome, secondaries=None):
    """Run the parent with the child's real emitter as its subprocess."""
    written: list[bytes] = []

    def scoring_child(argv, **kwargs):
        path = argv[argv.index("--output_json") + 1]
        child._emit_outcome(SimpleNamespace(output_json=path), outcome, secondaries=secondaries)
        written.append(Path(path).read_bytes())
        result = MagicMock()
        result.returncode, result.stdout, result.stderr = 0, "", ""
        return result

    with patch("core.sandbox_executor.subprocess.run", side_effect=scoring_child):
        score = sandbox.execute_scoring(EXP_ID, RUN_NAME, "fcnet", {}, {}, {})
    assert score["status"] == "success", score
    return score, written[0]


def _same(actual, expected):
    if isinstance(expected, float) and math.isnan(expected):
        return isinstance(actual, float) and math.isnan(actual)
    return type(actual) is type(expected) and actual == expected


@pytest.mark.parametrize("number", [INF, -INF, NAN, 0.5], ids=["inf", "-inf", "nan", "finite"])
def test_child_metric_reaches_the_tuner_with_value_sign_and_missingness(sandbox, number):
    """Defect: the child null-projects non-finite metrics before the parent reads them.

    With ``coerce_nonfinite_to_none`` back at the child's write site every
    non-finite assertion below sees ``None`` (the primary scalar, its record
    identity and the secondary), and the not-measured ``None`` element becomes
    indistinguishable from a diverged one. Without the parent's decode the
    raw ``denoising_score`` is the string ``"Infinity"`` and the encoding
    member leaks into the tuner's results. The written file must be strict JSON.
    """
    outcome = MetricResult(
        metric_id="mse", direction="lower", scalar=number, per_sample=[number, None, 0.25]
    )
    secondary = MetricResult(metric_id="mae", direction="lower", scalar=number)
    score, written = _score(
        sandbox,
        outcome,
        {"secondary_metric_results": [secondary.model_dump(mode="json")]},
    )

    def refuse(token):
        raise AssertionError(f"bare JSON constant {token}")

    json.loads(written, parse_constant=refuse)
    results = score["results"]
    assert "$siderius_encoding" not in results

    facts = scoring_transport.adopt_child_score(
        SimpleNamespace(agent_input=SimpleNamespace()),
        score,
        execution._require_successful_scoring_result,
    )
    assert _same(facts.scalar, number)
    assert [_same(a, e) for a, e in zip(facts.file_vector, [number, None, 0.25], strict=True)] == [
        True
    ] * 3
    adopted = execution._adopt_child_metric_result(results, current=None)
    assert adopted is not None and _same(adopted["scalar"], number)
    (adopted_secondary,), _, _ = execution._adopt_child_secondaries(
        results, results=[], refusals=[], errors={}
    )
    assert _same(adopted_secondary.scalar, number)


def test_finite_child_output_keeps_its_historical_bytes(sandbox):
    """Defect: the transport migration rewrites finite scoring output.

    Writing with ``always=True`` (or any new layout) adds the encoding member or
    changes indentation, and the byte equality with the pre-change literal fails.
    """
    outcome = MetricResult(
        metric_id="mse", direction="lower", scalar=0.5, per_sample=[0.25, None, 0.75]
    )
    score, written = _score(sandbox, outcome)
    assert written == FINITE_BYTES
    assert score["results"]["file_vector"] == [0.25, None, 0.75]
