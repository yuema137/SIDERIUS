"""Issue #983 S2: the trainer seeds every RNG from one ``TrainingSeedPlan``.

Contract: ``docs/agent-reference/mechanisms/seeding.md`` (trainer seeding).
Each test names the defect it catches in its docstring.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

import execute_tools.train_engine_sandbox as tes
from core.seeding import MissingRunSeed, SeedCoordinates, derive_seed
from core.subprocess_env import subprocess_env
from core.training_seeds import SeedContext, TrainingSeedPlan
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.task_data_path import bind_task_data_path
from execute_tools.training_history import interpret_training_results
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig
from ml_models.models_sandbox import MODEL_REGISTRY
from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
from tests.helpers.two_family_profile import TwoFamilyFixture, write_two_family_fixture

_REAL_WAVENET = MODEL_REGISTRY["wavenet"]


def _tiny_model_cfg(seg_size: int) -> WaveNetConfig:
    return WaveNetConfig(
        segmentation_size=seg_size,
        input_channels=4,
        residual_channels=8,
        gate_channels=8,
        skip_channels=8,
        kernel_size=2,
        num_blocks=1,
    )


@pytest.fixture
def two_family(tmp_path) -> TwoFamilyFixture:
    return write_two_family_fixture(tmp_path)


@pytest.fixture
def initial_weights(monkeypatch) -> list[dict[str, torch.Tensor]]:
    """Record the weights of every model the engine constructs, at construction."""
    recorded: list[dict[str, torch.Tensor]] = []

    class RecordingWaveNet(_REAL_WAVENET):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            recorded.append({k: v.detach().clone() for k, v in self.state_dict().items()})

    monkeypatch.setitem(MODEL_REGISTRY, "wavenet", RecordingWaveNet)
    return recorded


def _train(fx: TwoFamilyFixture, tmp_path, name: str, plan: TrainingSeedPlan | None) -> dict:
    sandbox = {"models": str(tmp_path / name / "m"), "results": str(tmp_path / name / "r")}
    for path in sandbox.values():
        Path(path).mkdir(parents=True)
    data_path = TwoFamilyDataPath(fx)
    with bind_dataset_profile(fx.profile), bind_task_data_path(data_path):
        summary = tes.run_experiment_streaming(
            _tiny_model_cfg(fx.seg_size),
            TrainConfig(lr=1e-3, epochs=2, batch_size=2, optimizer_type="adam", device="cpu"),
            LossConfig(),
            sample_set=fx.full_sample_set(),
            data_dir=fx.data_dir,
            sandbox_dirs=sandbox,
            exp_id=name,
            train_portion=0.5,
            seed_plan=plan,
            profile=fx.profile,
            **data_path.scope_kwargs(fx.full_sample_set()),
        )
    assert summary is not None
    return summary


def _disturb_process_rngs(value: int) -> None:
    random.seed(value)
    np.random.seed(value)
    torch.manual_seed(value)


def _same_state(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor]) -> bool:
    return a.keys() == b.keys() and all(torch.equal(a[k], b[k]) for k in a)


class TestEngineSeeding:
    def test_same_context_reproduces_initial_weights_and_losses(
        self, two_family, tmp_path, initial_weights
    ):
        """T3. Defect: the trainer leaves model init, dropout, subsample or shuffle
        on the process-default RNG, or seeds after model construction. The two
        runs start from deliberately different process RNG states, so either
        defect changes the initial weights or the loss trajectory."""
        plan = TrainingSeedPlan(SeedContext(run_seed=11, at=SeedCoordinates(iteration=1)))
        _disturb_process_rngs(1)
        first = _train(two_family, tmp_path, "a", plan)
        _disturb_process_rngs(2)
        second = _train(two_family, tmp_path, "b", plan)

        assert _same_state(initial_weights[0], initial_weights[1])
        assert first["loss_history"] == second["loss_history"]

    def test_different_run_seed_changes_initial_weights(
        self, two_family, tmp_path, initial_weights
    ):
        """T3. Defect: the init seed ignores the run seed (e.g. a constant)."""
        _disturb_process_rngs(1)
        _train(two_family, tmp_path, "a", TrainingSeedPlan(SeedContext(run_seed=11)))
        _disturb_process_rngs(1)
        _train(two_family, tmp_path, "b", TrainingSeedPlan(SeedContext(run_seed=12)))

        assert not _same_state(initial_weights[0], initial_weights[1])

    def test_missing_plan_is_refused_before_model_construction(
        self, two_family, tmp_path, initial_weights
    ):
        """Defect: a missing seed falls back to a hidden value (formerly
        ``hash(exp_id)``) instead of raising ``MissingRunSeed``."""
        with pytest.raises(MissingRunSeed):
            _train(two_family, tmp_path, "a", None)
        assert initial_weights == []


class TestTrainerEntryBoundary:
    """T4: ``main()`` is the trainer CLI entry boundary for a run seed."""

    def _main(
        self, tmp_path, monkeypatch, fx, *extra: str, capsys=None
    ) -> tuple[TrainingSeedPlan, dict]:
        import workflows.task_composition as composition

        data_path = TwoFamilyDataPath(fx)
        monkeypatch.setattr(composition, "resolve_child_task_data_path", lambda *a, **k: data_path)
        seen: dict = {}

        def fake_stream(*args, **kwargs):
            seen.update(kwargs)
            if capsys is not None:
                seen["stdout_before_training"] = capsys.readouterr().out
            return {"final_loss": 1.0, "loss_history": [1.0], "model_params": 1}

        monkeypatch.setattr(tes, "run_experiment_streaming", fake_stream)
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / "m.json").write_text(json.dumps(_tiny_model_cfg(fx.seg_size).model_dump()))
        (cfg / "t.json").write_text(json.dumps(TrainConfig(epochs=1, device="cpu").model_dump()))
        (cfg / "l.json").write_text(json.dumps(LossConfig().model_dump()))
        (cfg / "ss.json").write_text(json.dumps({"0": [0]}))
        payload = data_path.serialize_scope(data_path.scope({"0": [0]}))
        (cfg / "scope.json").write_text(payload)
        argv = [
            "prog",
            *("--model_cfg", str(cfg / "m.json"), "--train_cfg", str(cfg / "t.json")),
            *("--loss_cfg", str(cfg / "l.json"), "--data_dir", fx.data_dir),
            *("--sandbox_dir", str(tmp_path / "sb"), "--exp_id", "seeded"),
            *("--sample_set_json", str(cfg / "ss.json")),
            *("--task_data_path_id", data_path.task_data_path_id),
            *("--task_scope_ref", str(cfg / "scope.json")),
            *("--task_scope_digest", hashlib.sha256(payload.encode()).hexdigest()),
            *extra,
        ]
        monkeypatch.setattr(sys, "argv", argv)
        with bind_dataset_profile(fx.profile):
            tes.main()
        (result_path,) = (tmp_path / "sb").rglob("experiment_results_*.json")
        self.seen = seen
        return seen["seed_plan"], json.loads(result_path.read_text())

    def test_generated_seed_is_printed_before_training_starts(
        self, two_family, tmp_path, monkeypatch, capsys
    ):
        """Defect: a generated seed is recorded only in the results JSON written
        after training, so a crash, OOM or timeout loses it."""
        plan, _ = self._main(tmp_path, monkeypatch, two_family, capsys=capsys)
        stdout = self.seen["stdout_before_training"]
        assert f"[seed] run_seed={plan.context.run_seed} source=generated" in stdout

    def test_absent_context_generates_and_records_the_run_seed(
        self, two_family, tmp_path, monkeypatch
    ):
        """Defect: the trainer CLI without a context falls back to a label hash
        or leaves the seed unrecorded. Every seed must derive from the recorded
        generated run seed, independent of ``exp_id``. The seed keys must not
        enter the payload the tuner forwards toward LLM-visible records."""
        plan, results = self._main(tmp_path, monkeypatch, two_family)

        assert results["seed_source"] == "generated"
        assert results["seed_derivation"] == "siderius-seed/v1"
        assert results["seed_context"] == plan.context.model_dump(mode="json")
        assert results["process_seeds"] == plan.process_seeds().model_dump()
        run_seed = results["seed_context"]["run_seed"]
        assert [plan.epoch(k).subsample for k in (0, 1)] == [
            derive_seed(run_seed, "trainer.epoch_subsample", SeedCoordinates(epoch=k))
            for k in (0, 1)
        ]
        forwarded = interpret_training_results(results, expected_validation=False)
        assert not any("seed" in key for key in forwarded.legacy_payload)

    def test_supplied_context_is_used_verbatim(self, two_family, tmp_path, monkeypatch):
        """Defect: the trainer ignores the parent's ``SeedContext`` and generates."""
        context = SeedContext(run_seed=5, at=SeedCoordinates(iteration=2, round=1, attempt=3))
        path = tmp_path / "seed_context.json"
        path.write_text(context.model_dump_json())
        plan, results = self._main(
            tmp_path, monkeypatch, two_family, "--seed_context_json", str(path)
        )

        assert plan == TrainingSeedPlan(context)
        assert results["seed_source"] == "supplied"
        assert results["seed_context"] == context.model_dump(mode="json")

    def test_retired_train_base_seed_flag_is_refused(self, two_family, tmp_path, monkeypatch):
        """Defect: the retired S2 interim transport is still accepted, so a
        caller could pin the subsample stream outside the run seed (#983 S3b)."""
        with pytest.raises(SystemExit):
            self._main(tmp_path, monkeypatch, two_family, "--train_base_seed", "41")


class TestSeedPlan:
    def test_freeze_pins_only_the_subsample_stream(self):
        """Defect: ``freeze_subsample`` also freezes order and shuffle, or the
        streams collapse into one value (the old ``order:{epoch_seed}`` coupling)."""
        plan = TrainingSeedPlan(SeedContext(run_seed=3))
        frozen = [plan.epoch(k, freeze_subsample=True) for k in (0, 1)]

        assert frozen[0].subsample == frozen[1].subsample == plan.epoch(0).subsample
        assert frozen[0].order != frozen[1].order
        assert frozen[0].shuffle != frozen[1].shuffle
        assert len({plan.epoch(1).subsample, plan.epoch(1).order, plan.epoch(1).shuffle}) == 3

    def test_context_refuses_a_preset_epoch(self):
        """Defect: a parent-set epoch coordinate would give every epoch one seed."""
        with pytest.raises(ValueError, match="trainer owns the epoch"):
            SeedContext(run_seed=3, at=SeedCoordinates(epoch=0))


def test_child_environment_pins_the_hash_seed_unless_the_operator_set_one(monkeypatch):
    """Defect: children inherit a randomized ``PYTHONHASHSEED``, so set
    iteration in task code differs between trainer and probe; or the builder
    silently overrides a value the operator set deliberately."""
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    assert subprocess_env()["PYTHONHASHSEED"] == "0"
    monkeypatch.setenv("PYTHONHASHSEED", "123")
    assert subprocess_env()["PYTHONHASHSEED"] == "123"
