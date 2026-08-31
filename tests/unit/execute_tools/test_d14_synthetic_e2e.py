"""D14-1 C5 — full-surface synthetic end-to-end through the REAL engine.

The claim (child §5 C5): a task with in-memory
samples, list-of-string-ids scope, scalar-int target vs vector-float output —
trains through the PRODUCTION `run_experiment_streaming` body via the
run-scoped TaskDataPath binding, and completes the four-method surface
(train → outputs → deliverable → payload) through the declared data path.
The deterministic negative proves that the same synthetic scope with a missed
binding fails loudly before training rather than selecting an implicit task.

In-process and deterministic: unit-owned per the #221 layer doctrine — this
is structural genericity evidence, not a hardware qualification.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch
from torch import nn
from torch.utils.data import Dataset

import execute_tools.train_engine_sandbox as tes
from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from execute_tools.task_data_path import (
    DeliverableWriteRequest,
    EpochSamplingParams,
    EvalMaterializationParams,
    EvaluationReadRequest,
    TaskDataPathResolutionError,
    bind_task_data_path,
)
from ml_models.models_format_sandbox import LossConfig, TrainConfig

# ---------------------------------------------------------------------------
# The synthetic task exercises independent input, target, and output axes.
# ---------------------------------------------------------------------------


class _SyntheticPairs(Dataset):
    """float32 [4] model input; scalar int class target (Amendment 1: the
    target shares neither shape, rank nor dtype with the [2]-logit output)."""

    def __init__(self, ids: list[str], seed: int):
        gen = torch.Generator().manual_seed(seed)
        self._inputs = torch.rand((len(ids), 4), generator=gen, dtype=torch.float32)
        self._targets = torch.arange(len(ids)) % 2
        self.ids = list(ids)

    def __len__(self) -> int:
        return len(self.ids)

    def __getitem__(self, idx: int):
        return self._inputs[idx], int(self._targets[idx])


class SyntheticE2ETaskDataPath:
    task_data_path_id = "synthetic_e2e_pairs"

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset:
        assert isinstance(scope, list), "synthetic scope is a plain list of string ids"
        return _SyntheticPairs(scope, seed=params.epoch_seed or 0)

    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset:
        assert isinstance(scope, list)
        return _SyntheticPairs(scope, seed=0)

    def write_deliverable(self, outputs, request: DeliverableWriteRequest) -> None:
        path = Path(request.output_dir) / f"synthetic_{request.run_name}_{request.exp_id}.jsonl"
        with path.open("w", encoding="utf-8") as fh:
            for sample_id, vector in outputs:
                fh.write(json.dumps({"id": sample_id, "output": [float(v) for v in vector]}) + "\n")

    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object:
        path = (
            Path(request.deliverable_dir) / f"synthetic_{request.run_name}_{request.exp_id}.jsonl"
        )
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _TinyClassifier(nn.Module):
    """[B, 4] float -> [B, 2] logits. Registered under the synthetic type."""

    def __init__(self, cfg):
        super().__init__()
        self.net = nn.Linear(4, 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


_MODEL_TYPE = "synthetic_tiny_classifier"


def _synthetic_contract() -> ModelIOContract:
    """The task's declared boundary: float32 [B, 4] in, float32 [B, 2] out.

    The contract is the engine's dtype authority (Step 03); no implicit task
    preference may reinterpret these float inputs.
    """

    def axis(role, **dim) -> TensorAxis:
        return TensorAxis(dimension=Dimension(**dim), role=role)

    return ModelIOContract(
        input=TensorContract(
            axes=(axis(AxisRole.BATCH, symbolic="B"), axis(None, fixed=4)),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
        output=TensorContract(
            axes=(axis(AxisRole.BATCH, symbolic="B"), axis(AxisRole.CLASS, fixed=2)),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        ),
    )


@pytest.fixture()
def synthetic_engine_setup(tmp_path, monkeypatch):
    monkeypatch.setitem(tes.MODEL_REGISTRY, _MODEL_TYPE, _TinyClassifier)
    model_cfg = SimpleNamespace(model_type=_MODEL_TYPE, segmentation_size=4)
    train_cfg = TrainConfig(lr=1e-3, epochs=1, batch_size=2, optimizer_type="adam", device="cpu")
    loss_cfg = LossConfig(loss_type="ce")
    sandbox_dirs = {"models": str(tmp_path / "models"), "results": str(tmp_path / "results")}
    for d in sandbox_dirs.values():
        Path(d).mkdir()
    return model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path


SCOPE_IDS = ["a", "b", "c", "d", "e", "f"]


class TestSyntheticEndToEnd:
    def test_full_surface_through_run_experiment_streaming(self, synthetic_engine_setup):
        """Train through the PRODUCTION engine body under the synthetic
        binding, then complete the surface: trained model → outputs →
        deliverable → evaluation payload."""
        model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path = synthetic_engine_setup
        impl = SyntheticE2ETaskDataPath()

        with bind_task_data_path(impl):
            results = tes.run_experiment_streaming(
                model_cfg,
                train_cfg,
                loss_cfg,
                sample_set={},  # compatibility argument, unused by the seam path
                data_dir=str(tmp_path),
                sandbox_dirs=sandbox_dirs,
                exp_id="synth_e2e_1",
                train_base_seed=7,
                model_io=_synthetic_contract(),
                task_scope=list(SCOPE_IDS),
            )

        assert results is not None
        assert results["final_loss"] == pytest.approx(results["loss_history"][-1])
        assert len(results["loss_history"]) == 1  # one epoch
        th = results["training_history"]
        assert th["objective_kind"] == "ce"
        assert len(th["train_objective"]) == 1
        # No eval scope was declared: R3 honestly absent (None), not faked.
        assert th["validation_objective"] is None

        # The trained model is the engine's persisted artifact.
        model_files = list(Path(sandbox_dirs["models"]).glob("*.pth"))
        assert len(model_files) == 1

        # Complete the four-method surface with the trained model's outputs.
        model = _TinyClassifier(model_cfg)
        model.load_state_dict(torch.load(model_files[0], weights_only=True))
        eval_ds = impl.validation_dataset(
            list(SCOPE_IDS), EvalMaterializationParams(data_dir="/unused")
        )
        with torch.no_grad():
            outputs = [
                (sid, model(eval_ds[i][0].unsqueeze(0))[0].tolist())
                for i, sid in enumerate(SCOPE_IDS)
            ]
        impl.write_deliverable(
            outputs,
            DeliverableWriteRequest(
                output_dir=str(tmp_path),
                exp_id="synth_e2e_1",
                run_name="r1",
                model_type=_MODEL_TYPE,
            ),
        )
        payload = impl.read_evaluation_payload(
            EvaluationReadRequest(
                deliverable_dir=str(tmp_path),
                exp_id="synth_e2e_1",
                run_name="r1",
                model_type=_MODEL_TYPE,
            )
        )
        assert [row["id"] for row in payload] == SCOPE_IDS
        assert all(len(row["output"]) == 2 for row in payload)

    def test_explicit_eval_scope_produces_real_r3_through_the_engine(self, synthetic_engine_setup):
        """D14-2 C5b: an explicit task-owned evaluation scope
        triggers the REAL per-epoch R3 pass — validation_objective rows land
        in training_history with requested == materialized pinned by the
        caller's declaration."""
        model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path = synthetic_engine_setup
        impl = SyntheticE2ETaskDataPath()
        eval_ids = ["va", "vb", "vc"]
        with bind_task_data_path(impl):
            results = tes.run_experiment_streaming(
                model_cfg,
                train_cfg,
                loss_cfg,
                sample_set={},
                data_dir=str(tmp_path),
                sandbox_dirs=sandbox_dirs,
                exp_id="synth_r3_1",
                train_base_seed=7,
                model_io=_synthetic_contract(),
                task_scope=list(SCOPE_IDS),
                task_eval_scope=list(eval_ids),
                validation_requested_rows=len(eval_ids),
            )
        assert results is not None
        th = results["training_history"]
        assert len(th["validation_objective"]) == 1  # one epoch, one R3 row
        assert th["validation_requested_samples"] == 3
        assert th["validation_samples"] == 3
        assert th["comparability"] == "established"

    def test_explicit_eval_scope_without_declared_rows_fails_loudly(self, synthetic_engine_setup):
        model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path = synthetic_engine_setup
        with bind_task_data_path(SyntheticE2ETaskDataPath()):
            with pytest.raises(ValueError, match="validation_requested_rows"):
                tes.run_experiment_streaming(
                    model_cfg,
                    train_cfg,
                    loss_cfg,
                    sample_set={},
                    data_dir=str(tmp_path),
                    sandbox_dirs=sandbox_dirs,
                    exp_id="synth_r3_neg",
                    train_base_seed=7,
                    model_io=_synthetic_contract(),
                    task_scope=list(SCOPE_IDS),
                    task_eval_scope=["va"],
                )

    def test_determinism_two_runs_same_seed_same_history(self, synthetic_engine_setup):
        model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path = synthetic_engine_setup
        impl = SyntheticE2ETaskDataPath()
        histories = []
        for exp in ("det_a", "det_b"):
            torch.manual_seed(123)  # model init determinism
            with bind_task_data_path(impl):
                results = tes.run_experiment_streaming(
                    model_cfg,
                    train_cfg,
                    loss_cfg,
                    sample_set={},
                    data_dir=str(tmp_path),
                    sandbox_dirs=sandbox_dirs,
                    exp_id=exp,
                    train_base_seed=7,
                    model_io=_synthetic_contract(),
                    task_scope=list(SCOPE_IDS),
                )
            assert results is not None
            histories.append(results["loss_history"])
        assert histories[0] == histories[1]

    def test_missed_binding_fails_closed_before_training(self, synthetic_engine_setup):
        """A synthetic scope cannot execute without a declared task data path."""
        model_cfg, train_cfg, loss_cfg, sandbox_dirs, tmp_path = synthetic_engine_setup
        with pytest.raises(TaskDataPathResolutionError, match="No task data path is bound"):
            tes.run_experiment_streaming(
                model_cfg,
                train_cfg,
                loss_cfg,
                sample_set={},
                data_dir=str(tmp_path),
                sandbox_dirs=sandbox_dirs,
                exp_id="neg_1",
                train_base_seed=7,
                task_scope=list(SCOPE_IDS),
            )
        assert list(Path(sandbox_dirs["models"]).glob("*.pth")) == []
