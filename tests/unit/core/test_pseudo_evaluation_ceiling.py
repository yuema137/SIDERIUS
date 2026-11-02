"""Issue 1468: pseudo deliverable cost follows a declared row ceiling, not data size.

Removing the launch default leaves pseudo TIDMAD materializing its full formal
scope; removing the stub transport or the materialized-size check lets a task
that ignores ``ScopeBuildRequest.max_samples`` iterate an unbounded scope.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.pseudo_deliverables as pseudo_deliverables
from agent.skills.inference_skill.wrapper import run_skill as infer
from core.pseudo_admission import PSEUDO_VALIDATION_MAX_SAMPLES
from core.pseudo_deliverables import PseudoEvidenceUnsupported, write_pseudo_deliverable
from core.stub_sandbox import StubSandbox
from execute_tools.task_data_path import ScopeBuildRequest
from tests.helpers.step04a_fixtures import tidmad_model_io
from workflows.standard_cli import build_parser, normalize_args
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

MANIFEST = Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"
PARAMS = {
    "exp_id": "ceiling_attempt",
    "run_name": "ceiling_run",
    "model_type": "synthetic_model",
    "model_config": {},
    "train_config": {},
    "loss_config": {"loss_type": "ce"},
}
BASE_ARGV = [
    "--workspace", "runs", "--run_name", "r", "--start_iteration", "1",
    "--task_composition", "task.yaml", "--data_dir", "data",
]  # fmt: skip


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (["--is_pseudo_training"], PSEUDO_VALIDATION_MAX_SAMPLES),
        (["--is_pseudo_training", "--validation_max_samples", "7"], 7),
        (["--is_pseudo_llm"], None),
        ([], None),
    ],
)
def test_launch_records_a_pseudo_training_ceiling_only(extra, expected):
    """Real and pseudo-LLM-only launches keep their absent ceiling unchanged."""
    args = normalize_args(build_parser().parse_args([*BASE_ARGV, *extra]))
    assert args.validation_max_samples == expected


class _PaperSizedScope:
    """TIDMAD's full Formal scope: 20 files x 200 PSD segments x 250 rows."""

    def __len__(self):
        return 20 * 200 * 250

    def __getitem__(self, index):
        pytest.fail("a refused scope must not materialize any row")


class _UnboundedTask:
    task_data_path_id = "ignores_max_samples"

    def validation_dataset(self, scope, params):
        return _PaperSizedScope()

    def write_deliverable(self, outputs, request):
        pytest.fail("a refused scope must not reach the task writer")


def test_paper_sized_scope_above_the_ceiling_is_refused_before_any_row(monkeypatch, tmp_path):
    monkeypatch.setattr(pseudo_deliverables, "active_task_data_path", _UnboundedTask)
    monkeypatch.setattr(pseudo_deliverables, "run_bound_model_io_contract", tidmad_model_io)
    with pytest.raises(PseudoEvidenceUnsupported, match=r"1000000 evaluation samples.*=256"):
        write_pseudo_deliverable(
            output_dir=str(tmp_path),
            data_dir=str(tmp_path),
            exp_id="paper",
            run_name="paper_run",
            model_type="stub",
            task_scopes=SimpleNamespace(evaluation=object()),
            max_samples=PSEUDO_VALIDATION_MAX_SAMPLES,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.usefixtures("synthetic_dataset_profile", "synthetic_physical_data_root")
def test_inference_wrapper_transports_the_run_ceiling_to_the_stub(tmp_path):
    """The tuner's runtime policy is the only route from launch to the stub."""
    from examples.quickstart.plugins._quickstart_task import write_data_dir

    write_data_dir(tmp_path)
    composition = compose_run_task_bindings(str(MANIFEST))
    task = composition.task_data_path
    unbounded = ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0, seed=0
    )
    scopes = SimpleNamespace(
        training=task.build_training_scope(unbounded),
        evaluation=task.build_eval_scope(unbounded),
    )
    sandbox = StubSandbox(workspace=str(tmp_path / "run"), run_id="ceiling")
    write_data_dir(sandbox.dirs["data"])
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        with pytest.raises(PseudoEvidenceUnsupported, match="validation_max_samples=2"):
            infer(
                sandbox, **PARAMS, task_scopes=scopes, runtime_policy={"validation_max_samples": 2}
            )
        assert not list(Path(sandbox.base_dir).glob("predictions_*"))

        infer(
            sandbox, **PARAMS, task_scopes=scopes, runtime_policy={"validation_max_samples": 10**6}
        )
    sidecar = Path(sandbox.base_dir) / "pseudo_inference_ceiling_attempt_ceiling_run.json"
    assert json.loads(sidecar.read_text())["evaluation_max_samples"] == 10**6


@pytest.mark.usefixtures("synthetic_dataset_profile", "synthetic_physical_data_root")
def test_admitted_ceiling_adds_no_dataset_construction(monkeypatch, tmp_path):
    """An admitted ceiling costs no construction beyond the uncapped pass.

    The task writer may rematerialize its own scope, so the uncapped pass is
    the baseline; a separate size-check construction adds one.
    """
    from examples.quickstart.plugins._quickstart_task import write_data_dir

    write_data_dir(tmp_path)
    composition = compose_run_task_bindings(str(MANIFEST))
    task = composition.task_data_path
    request = ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0, seed=0, max_samples=2
    )
    scopes = SimpleNamespace(evaluation=task.build_eval_scope(request))
    built = type(task).validation_dataset
    calls = []

    def counting(self, scope, params):
        calls.append(scope)
        return built(self, scope, params)

    monkeypatch.setattr(type(task), "validation_dataset", counting)
    counts = {}
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        for ceiling in (None, 2):
            calls.clear()
            write_pseudo_deliverable(
                output_dir=str(tmp_path / f"out_{ceiling}"),
                data_dir=str(tmp_path),
                exp_id="once",
                run_name="once_run",
                model_type="stub",
                task_scopes=scopes,
                max_samples=ceiling,
            )
            counts[ceiling] = len(calls)
    assert counts[None] >= 1
    assert counts[2] == counts[None]
