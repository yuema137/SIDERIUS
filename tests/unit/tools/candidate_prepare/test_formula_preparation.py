"""Issue #1294: prepared interpretation payloads stamp the effective selection metric."""

import importlib
import json
import subprocess
from pathlib import Path

from tests.helpers.composed_manifest import write_complete_manifest
from tests.helpers.formula_selection import FORMULA_EVALUATION
from tools.candidate_prepare import prepare_candidate
from tools.workspace_sandbox.runner import ExecutionResult

launch = importlib.import_module("tools.candidate_prepare.launch")


def test_prepared_interpretation_input_stamps_the_effective_metric(
    selection, tmp_path, monkeypatch
):
    """Defect: preparation stamps the source metric on the cold-start interpretation
    input, so the worker refuses the bundle under formula selection (or, if it were
    accepted, interpretation would rank in source units instead of utility).

    The real preparation child runs in a plain subprocess (no sandbox namespace).
    """
    from workflows.task_composition import compose_run_task_bindings

    manifest = write_complete_manifest(tmp_path / "task", evaluation=FORMULA_EVALUATION)
    composition = compose_run_task_bindings(str(manifest))
    effective = composition.selection_metric_spec
    assert effective.id != composition.metric.spec.id

    def child(profile, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(launch, "run", child)
    receipt = prepare_candidate(selection.model_copy(update={"task_manifest": str(manifest)}))
    assert receipt.status == "prepared"
    stamped = json.loads(
        (Path(selection.output_dir) / "preparation/interpretation_input.json").read_text()
    )["metric_spec"]
    assert (stamped["id"], stamped["aggregation"]) == (effective.id, effective.aggregation)
