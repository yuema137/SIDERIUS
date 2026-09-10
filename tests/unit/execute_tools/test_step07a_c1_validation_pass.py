"""Step 07a C1 — the trainer's R3 validation pass (design §3.2, §3.3, §3.4,
§3.4b, §3.9) on the in-process synthetic two-family contrast profile
(CPU, seconds).

Families, each naming the defect only it catches:

  (a) two-arm TRAJECTORY oracle: `loss_history` and the trained model state
      are bit-identical with and without the pass;
  (b) RNG-isolation MUTATION: a stochastic forward — the oracle stays green
      WITH the fork and goes RED without it (the fork is the mechanism);
  (c) R2/R3 comparability on an UNEQUAL last batch: R3 == the per-sample
      reference, ≠ the unweighted mean of batch means;
  (d) legacy keys byte-identical, additive key last;
  (e) `--eval_sample_set_json` fail-closed / absent, and its reachability;
  (f) legacy single-file → history with R3 None;
  (g) runtime accounting: the training ACTUAL EXCLUDES validation seconds,
      `unit_count` unchanged;
  (h) memory order: the validation dataset is built only after the training
      dataset is released;
  (k) STATE census before/after each pass; objective-state mutation →
      `ObjectiveStateMutationError`; mode restore under exception;
  (l) task-owned exact-materialization refusal propagates on the first or a
      later validation pass, with no successful model/results persisted;
  (m) comparability stamping through the trainer for `reduction="sum"`.
"""

from __future__ import annotations

import contextlib
import gc
import hashlib
import json
import os
import random
import sys
import weakref

import numpy as np
import pytest
import torch
from torch.utils.data import DataLoader

import execute_tools.train_engine_sandbox as tes
from core.runtime_control.session import RuntimeVerificationSession
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.task_data_path import EvalMaterializationParams, bind_task_data_path
from execute_tools.training_history import (
    COMPARABILITY_REASON_SUM,
    LEGACY_TRAINING_RESULT_KEYS,
    TrainingHistory,
    interpret_training_results,
)
from ml_models.loss_models_sandbox import get_criterion
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig
from ml_models.models_sandbox import MODEL_REGISTRY
from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
from tests.helpers.two_family_profile import TwoFamilyFixture, write_two_family_fixture

_REAL_WAVENET = MODEL_REGISTRY["wavenet"]  # bound at import: the fixtures below re-register the key

# ---------------------------------------------------------------------------
# Fixture: the two-family contrast profile + a tiny wavenet on CPU
# ---------------------------------------------------------------------------


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


def _sandbox(tmp_path, name: str) -> dict:
    d = {"models": str(tmp_path / name / "m"), "results": str(tmp_path / name / "r")}
    for p in d.values():
        os.makedirs(p, exist_ok=True)
    return d


def _seed_everything() -> None:
    random.seed(7)
    np.random.seed(7)
    torch.manual_seed(0)


def _run(
    fx: TwoFamilyFixture,
    tmp_path,
    *,
    name: str,
    eval_sample_set: dict | None,
    epochs: int = 3,
    batch_size: int = 2,
    loss_cfg: LossConfig | None = None,
    sample_set: dict | None = None,
    runtime_session: RuntimeVerificationSession | None = None,
    seed: bool = True,
) -> dict:
    """One in-process streaming run on the fixture; fixed seeds by default."""
    if seed:
        _seed_everything()
    data_path = TwoFamilyDataPath(fx)
    with bind_dataset_profile(fx.profile), bind_task_data_path(data_path):
        summary = tes.run_experiment_streaming(
            _tiny_model_cfg(fx.seg_size),
            TrainConfig(
                lr=1e-3, epochs=epochs, batch_size=batch_size, optimizer_type="adam", device="cpu"
            ),
            loss_cfg or LossConfig(),
            sample_set=sample_set or fx.full_sample_set(),
            data_dir=fx.data_dir,
            sandbox_dirs=_sandbox(tmp_path, name),
            exp_id=name,
            train_base_seed=123,
            profile=fx.profile,
            runtime_session=runtime_session,
            **data_path.scope_kwargs(sample_set or fx.full_sample_set(), eval_sample_set),
        )
    assert summary is not None
    return summary


def _saved_state(tmp_path, name: str) -> dict[str, torch.Tensor]:
    return torch.load(os.path.join(str(tmp_path / name / "m"), f"model_wavenet_{name}_agent.pth"))


def _states_equal(a: dict[str, torch.Tensor], b: dict[str, torch.Tensor]) -> bool:
    return a.keys() == b.keys() and all(torch.equal(a[k], b[k]) for k in a)


# ---------------------------------------------------------------------------
# (a) two-arm trajectory oracle  +  (d) legacy keys byte-identical
# ---------------------------------------------------------------------------


class TestTwoArmTrajectoryOracle:
    def test_loss_history_and_model_state_are_bit_identical_with_and_without_the_pass(
        self, two_family, tmp_path
    ):
        """Defect: a validation pass that consumed torch's global RNG (the
        shuffle loader's permutation source), updated BatchNorm stats or
        touched the optimizer would move epoch ≥ 1 — the trajectory would
        differ, or the final weights would."""
        without = _run(two_family, tmp_path, name="arm_without", eval_sample_set=None)
        with_ = _run(
            two_family, tmp_path, name="arm_with", eval_sample_set=two_family.full_sample_set()
        )
        assert with_["loss_history"] == without["loss_history"]  # exact float equality
        assert with_["final_loss"] == without["final_loss"]
        assert _states_equal(
            _saved_state(tmp_path, "arm_with"), _saved_state(tmp_path, "arm_without")
        )

        # (d) legacy floor: the three keys, first, byte-identical; ONE additive key, last.
        legacy_with = json.dumps({k: with_[k] for k in LEGACY_TRAINING_RESULT_KEYS})
        legacy_without = json.dumps({k: without[k] for k in LEGACY_TRAINING_RESULT_KEYS})
        assert legacy_with == legacy_without
        assert list(with_.keys()) == [*LEGACY_TRAINING_RESULT_KEYS, "training_history"]
        assert list(without.keys()) == [*LEGACY_TRAINING_RESULT_KEYS, "training_history"]

        # The additive payload validates and carries R2 == loss_history and a 3-point R3
        # over the whole 24-row validation scope.
        h = TrainingHistory.model_validate(with_["training_history"])
        assert h.train_objective == with_["loss_history"]
        assert h.validation_objective is not None and len(h.validation_objective) == 3
        assert h.validation_requested_samples == h.validation_samples == 24
        assert h.comparability == "established" and h.objective_kind == "focal"
        assert h.validation_seconds is not None and all(s >= 0 for s in h.validation_seconds)
        # R3 is observed on the VALIDATION family (distinct payload) — it must not
        # coincide with R2 (would indicate the training family was read instead).
        assert h.validation_objective != h.train_objective

        # Flag absent → honest absence, never fabricated.
        h0 = TrainingHistory.model_validate(without["training_history"])
        assert h0.validation_objective is None and h0.validation_samples is None
        # And the typed boundary accepts each arm under its own expectation.
        interpret_training_results(with_, expected_validation=True)
        interpret_training_results(without, expected_validation=False)


# ---------------------------------------------------------------------------
# (b) RNG-isolation mutation — the fork is the mechanism
# ---------------------------------------------------------------------------


class _StochasticForward(torch.nn.Module):
    """Wraps the real wavenet; consumes ONE torch global-RNG draw per forward
    (a dropout-like model). The draw is discarded — only the RNG advance
    matters."""

    def __init__(self, cfg, *args, **kwargs):
        super().__init__()
        self.inner = _REAL_WAVENET(cfg, *args, **kwargs)

    def forward(self, x):
        torch.rand(1)
        return self.inner(x)


@pytest.fixture
def stochastic_wavenet(monkeypatch):
    monkeypatch.setitem(MODEL_REGISTRY, "wavenet", _StochasticForward)


class TestRngIsolationMutation:
    def test_with_the_fork_a_stochastic_forward_keeps_the_oracle_green(
        self, two_family, tmp_path, stochastic_wavenet
    ):
        without = _run(two_family, tmp_path, name="s_without", eval_sample_set=None)
        with_ = _run(
            two_family, tmp_path, name="s_with", eval_sample_set=two_family.full_sample_set()
        )
        assert with_["loss_history"] == without["loss_history"]

    def test_without_the_fork_the_same_model_moves_the_trajectory(
        self, two_family, tmp_path, stochastic_wavenet, monkeypatch
    ):
        """MUTATION: remove `torch.random.fork_rng` from the pass. The
        validation forwards then advance the global RNG, epoch-1's shuffle
        permutation changes, and the trajectory diverges → this proves the
        fork is what isolates, not luck."""

        @contextlib.contextmanager
        def _no_fork(*args, **kwargs):
            yield

        monkeypatch.setattr(tes.torch.random, "fork_rng", _no_fork)
        without = _run(two_family, tmp_path, name="m_without", eval_sample_set=None)
        with_ = _run(
            two_family, tmp_path, name="m_with", eval_sample_set=two_family.full_sample_set()
        )
        assert with_["loss_history"][0] == without["loss_history"][0]  # epoch 0 precedes any pass
        assert with_["loss_history"][1:] != without["loss_history"][1:]


# ---------------------------------------------------------------------------
# (c) R2/R3 comparability — unequal last batch, sample-weighted reference
# ---------------------------------------------------------------------------


class TestComparabilityUnequalLastBatch:
    def test_r3_equals_the_per_sample_reference_and_not_the_mean_of_batch_means(self, tmp_path):
        """5 validation ML segments, batch_size=2 → batches of 2, 2, 1. The
        MUTATION `np.mean(batch_losses)` on the validation loop would weight
        the last sample double; the sample-count-weighted estimator does not."""
        # 1 ML segment per PSD segment (psd_len == seg_size), 3 PSD segments/file.
        fx = write_two_family_fixture(
            tmp_path, num_files=2, psd_segment_length=1000, segments_per_file=3
        )
        eval_set = {"0": [0, 1, 2], "1": [0, 1]}  # 5 rows
        summary = _run(fx, tmp_path, name="cmp", eval_sample_set=eval_set, epochs=1, batch_size=2)
        h = TrainingHistory.model_validate(summary["training_history"])
        assert h.validation_samples == 5
        r3 = h.validation_objective[0]  # type: ignore[index]

        # Independent reference on the SAVED model (the state R3 was observed on).
        model = _REAL_WAVENET(_tiny_model_cfg(fx.seg_size))
        model.load_state_dict(_saved_state(tmp_path, "cmp"))
        model.eval()
        criterion = get_criterion(LossConfig(), None)
        data_path = TwoFamilyDataPath(fx)
        ds = data_path.validation_dataset(
            data_path.scope(eval_set, family="validation"),
            EvalMaterializationParams(data_dir=fx.data_dir),
        )
        per_sample = []
        with torch.no_grad():
            for x, y in DataLoader(ds, batch_size=1, shuffle=False):
                per_sample.append(criterion(model(x.to(torch.long)), y.to(torch.long)).item())
            batch_means = []
            for x, y in DataLoader(ds, batch_size=2, shuffle=False, drop_last=False):
                batch_means.append(criterion(model(x.to(torch.long)), y.to(torch.long)).item())
        reference = sum(per_sample) / len(per_sample)
        mutation = float(np.mean(batch_means))  # unweighted mean of batch means (2, 2, 1)
        assert r3 == pytest.approx(reference, abs=1e-12)
        assert abs(r3 - mutation) > 1e-9, "the fixture must separate the two estimators"


# ---------------------------------------------------------------------------
# (e) --eval_sample_set_json: fail-closed child side + reachability into the engine
# ---------------------------------------------------------------------------


class TestEvalSampleSetArg:
    def test_absent_means_no_validation_pass(self):
        assert tes._load_eval_sample_set_arg(None) is None
        assert tes._load_eval_sample_set_arg("") is None

    def test_missing_file_fails_closed_naming_the_path(self, tmp_path):
        missing = str(tmp_path / "nope.json")
        with pytest.raises(ValueError, match=r"nope\.json"):
            tes._load_eval_sample_set_arg(missing)

    def test_non_mapping_payload_fails_closed_naming_the_path(self, tmp_path):
        p = tmp_path / "list.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match=r"list\.json"):
            tes._load_eval_sample_set_arg(str(p))
        p2 = tmp_path / "bad_values.json"
        p2.write_text('{"0": "not a list"}')
        with pytest.raises(ValueError, match=r"bad_values\.json"):
            tes._load_eval_sample_set_arg(str(p2))

    def test_a_valid_mapping_loads_verbatim(self, tmp_path):
        p = tmp_path / "ok.json"
        p.write_text('{"0": [0, 1], "2": [3]}')
        assert tes._load_eval_sample_set_arg(str(p)) == {"0": [0, 1], "2": [3]}

    def test_main_forwards_the_flag_to_the_streaming_engine(
        self, tmp_path, monkeypatch, two_family
    ):
        """The child must deserialize and forward the explicit evaluation scope.

        The obsolete sample-set-only path is intentionally no longer runnable;
        the same transport failure class now lives at the opaque scope boundary.
        """
        import workflows.task_composition as composition

        seen: dict = {}
        data_path = TwoFamilyDataPath(two_family)
        scope_args = data_path.scope_kwargs({"0": [0]}, {"1": [0, 1]})
        monkeypatch.setattr(composition, "resolve_child_task_data_path", lambda *a, **k: data_path)

        def fake_stream(*args, **kwargs):
            seen.update(kwargs)
            return {"final_loss": 1.0, "loss_history": [1.0], "model_params": 1}

        monkeypatch.setattr(tes, "run_experiment_streaming", fake_stream)
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        (cfg_dir / "m.json").write_text(json.dumps(_tiny_model_cfg(1000).model_dump()))
        (cfg_dir / "t.json").write_text(
            json.dumps(TrainConfig(epochs=1, device="cpu").model_dump())
        )
        (cfg_dir / "l.json").write_text(json.dumps(LossConfig().model_dump()))
        (cfg_dir / "ss.json").write_text(json.dumps({"0": [0]}))
        argv = [
            "prog",
            "--model_cfg",
            str(cfg_dir / "m.json"),
            "--train_cfg",
            str(cfg_dir / "t.json"),
            "--loss_cfg",
            str(cfg_dir / "l.json"),
            "--data_dir",
            two_family.data_dir,
            "--sandbox_dir",
            str(tmp_path / "sb"),
            "--exp_id",
            "reach",
            "--sample_set_json",
            str(cfg_dir / "ss.json"),
            "--task_data_path_id",
            data_path.task_data_path_id,
            "--validation_requested_rows",
            "4",
        ]
        for name in ("task_scope", "task_eval_scope"):
            payload = data_path.serialize_scope(scope_args[name])
            path = cfg_dir / f"{name}.json"
            path.write_text(payload)
            argv.extend(
                [
                    f"--{name}_ref",
                    str(path),
                    f"--{name}_digest",
                    hashlib.sha256(payload.encode()).hexdigest(),
                ]
            )
        monkeypatch.setattr(sys, "argv", argv)
        with bind_dataset_profile(two_family.profile):
            tes.main()
        assert seen["task_eval_scope"] == scope_args["task_eval_scope"]
        assert seen["task_scope"] == scope_args["task_scope"]
        assert seen["validation_requested_rows"] == 4
        assert seen["eval_sample_set"] is None
        assert seen["sample_set"] == {"0": [0]}


# ---------------------------------------------------------------------------
# (f) legacy single-file mode → history with R3 None
# ---------------------------------------------------------------------------


class TestLegacySingleFile:
    def test_run_experiment_emits_the_additive_history_with_validation_absent(
        self, two_family, tmp_path
    ):
        with bind_dataset_profile(two_family.profile):
            data_path = TwoFamilyDataPath(two_family)
            ds = data_path.validation_dataset(
                data_path.scope({"0": list(range(two_family.segments_per_file))}),
                EvalMaterializationParams(data_dir=two_family.data_dir),
            )
            loader = DataLoader(ds, batch_size=2, shuffle=True, drop_last=True)
            _seed_everything()
            summary = tes.run_experiment(
                _tiny_model_cfg(two_family.seg_size),
                TrainConfig(lr=1e-3, epochs=2, batch_size=2, optimizer_type="adam", device="cpu"),
                LossConfig(),
                loader,
                _sandbox(tmp_path, "legacy"),
                "legacy",
            )
        assert list(summary.keys()) == [*LEGACY_TRAINING_RESULT_KEYS, "training_history"]
        h = TrainingHistory.model_validate(summary["training_history"])
        assert h.validation_objective is None and h.train_objective == summary["loss_history"]
        assert h.epochs_planned == h.epochs_completed == 2
        # Legacy caller: validation NOT expected → the boundary accepts it.
        res = interpret_training_results(summary, expected_validation=False)
        assert res.history is not None and res.history.validation_objective is None


# ---------------------------------------------------------------------------
# (g) runtime accounting — ACTUAL excludes validation seconds; unit_count unchanged
# ---------------------------------------------------------------------------


class TestRuntimeAccounting:
    def test_training_actual_excludes_the_recorded_validation_seconds(
        self, two_family, tmp_path, monkeypatch
    ):
        """MUTATION `record_phase_actual("training", perf_counter() - t_start)`
        (the pre-07a line) would include the passes. We make each pass REPORT
        100 s (the real work is milliseconds) and read the RAW actual handed
        to the session: it must be ≈ (real elapsed − 300 s), i.e. deeply
        negative — impossible unless the subtraction happens.

        07c C5 UPGRADE. The spy now keys by PHASE. This previously asserted
        `len(raw_actuals) == 1`, which was an incidental fact of 07a's world
        rather than the property under test: C5 legitimately records a SECOND
        actual, for the new ``validation`` phase, so that
        ``realized_unit_ms = actual ÷ units`` can calibrate future runs. The
        original claim is unchanged and still asserted on the TRAINING actual;
        the validation actual is now pinned beside it, so the test proves both
        halves of the split — the training observation stays pure AND the
        validation cost is no longer discarded.
        """
        real_pass = tes._validation_pass

        def slow_reporting_pass(**kwargs):
            r3, n, _secs = real_pass(**kwargs)
            return r3, n, 100.0

        monkeypatch.setattr(tes, "_validation_pass", slow_reporting_pass)
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"), attempt_id="acct")
        raw_actuals: list[tuple[str, float]] = []
        orig = session.record_phase_actual

        def spy(phase, actual_seconds):
            raw_actuals.append((phase, actual_seconds))
            orig(phase, actual_seconds)

        monkeypatch.setattr(session, "record_phase_actual", spy)
        summary = _run(
            two_family,
            tmp_path,
            name="acct",
            eval_sample_set=two_family.full_sample_set(),
            runtime_session=session,
        )
        assert summary["training_history"]["validation_seconds"] == [100.0, 100.0, 100.0]

        by_phase = dict(raw_actuals)
        assert len(raw_actuals) == len(by_phase), f"a phase was recorded twice: {raw_actuals}"
        assert set(by_phase) == {"training", "validation"}, raw_actuals

        # The original 07a claim, unchanged: NEGATIVE is impossible unless the
        # 300 s of reported validation was subtracted out. Real elapsed time is
        # strictly positive, so `elapsed - 300` is the only way here.
        #
        # The bound was `-300.0 <= x < -290.0`, which silently also asserted
        # that the real CPU training finishes in under 10 s. It does, on an idle
        # machine; under full-suite load it took 12.66 s and the test failed
        # with `-287.34` — a machine-speed assumption masquerading as a
        # correctness bound. The mutation it exists to catch (dropping the
        # subtraction) makes the value POSITIVE, so `< 0` kills it just as
        # dead, without pinning the host's speed.
        assert -300.0 < by_phase["training"] < 0.0, raw_actuals
        # 07c: and those same 300 s are now RECORDED rather than discarded.
        assert by_phase["validation"] == pytest.approx(300.0)

    def test_verification_unit_count_is_unchanged_by_the_pass(self, two_family, tmp_path):
        """Validation batches are NOT optimizer steps: the training workload's
        `unit_count` (materialized epoch-0 loader × epochs) is identical with
        and without the pass."""
        counts = []
        for name, ess in (("uc_without", None), ("uc_with", two_family.full_sample_set())):
            session = RuntimeVerificationSession(str(tmp_path / f"{name}.json"), attempt_id=name)
            _run(two_family, tmp_path, name=name, eval_sample_set=ess, runtime_session=session)
            obs = json.load(open(tmp_path / f"{name}.json"))
            counts.append(obs["components"]["training"]["workload"]["unit_count"])
        assert counts[0] == counts[1] == 12 * 3  # 24 rows / batch 2 = 12 steps × 3 epochs


# ---------------------------------------------------------------------------
# (h) memory order — validation dataset only after the training dataset is released
# ---------------------------------------------------------------------------


class TestTransientValidationDataset:
    def test_the_validation_dataset_is_built_only_when_no_training_dataset_is_alive(
        self, two_family, tmp_path, monkeypatch
    ):
        alive_training: weakref.WeakSet = weakref.WeakSet()
        events: list[str] = []
        train = TwoFamilyDataPath.training_dataset
        validate = TwoFamilyDataPath.validation_dataset

        def training(self, *args):
            dataset = train(self, *args)
            alive_training.add(dataset)
            events.append("training")
            return dataset

        def validation(self, *args):
            gc.collect()
            assert len(alive_training) == 0, "validation dataset beside live training dataset"
            events.append("validation")
            return validate(self, *args)

        monkeypatch.setattr(TwoFamilyDataPath, "training_dataset", training)
        monkeypatch.setattr(TwoFamilyDataPath, "validation_dataset", validation)
        _run(two_family, tmp_path, name="mem", eval_sample_set=two_family.full_sample_set())
        assert events == ["training", "validation"] * 3


# ---------------------------------------------------------------------------
# (k) state census; objective-state mutation; mode restore under exception
# ---------------------------------------------------------------------------


def _census(model, optimizer, criterion) -> dict:
    return {
        "model": {k: v.detach().clone() for k, v in model.state_dict().items()},
        "optimizer": json.dumps(
            {
                "state": {
                    str(k): {
                        kk: (vv.tolist() if torch.is_tensor(vv) else vv) for kk, vv in st.items()
                    }
                    for k, st in optimizer.state_dict()["state"].items()
                },
                "param_groups": optimizer.state_dict()["param_groups"],
            },
            sort_keys=True,
            default=str,
        ),
        "criterion": {k: v.detach().clone() for k, v in criterion.state_dict().items()},
        "training_flag": model.training,
        "py": random.getstate(),
        "np": np.random.get_state()[1].tobytes(),  # type: ignore[index]
        "torch": torch.get_rng_state().clone(),
        "cuda": [s.clone() for s in torch.cuda.get_rng_state_all()]
        if torch.cuda.is_available()
        else [],
    }


def _census_equal(a: dict, b: dict) -> bool:
    return (
        _states_equal(a["model"], b["model"])
        and a["optimizer"] == b["optimizer"]
        and _states_equal(a["criterion"], b["criterion"])
        and a["training_flag"] == b["training_flag"]
        and a["py"] == b["py"]
        and a["np"] == b["np"]
        and torch.equal(a["torch"], b["torch"])
        and len(a["cuda"]) == len(b["cuda"])
        and all(torch.equal(x, y) for x, y in zip(a["cuda"], b["cuda"], strict=True))
    )


class TestStateCensus:
    def test_every_pass_leaves_model_optimizer_objective_mode_and_all_rngs_unchanged(
        self, two_family, tmp_path, monkeypatch
    ):
        """Snapshot the whole observable training state immediately before and
        after each `_validation_pass` call (the optimizer captured from the
        production constructor). Any drift is a violation of the frozen
        transactional rule (§3.2)."""
        captured: dict = {}
        orig_build = tes.build_training_optimizer

        def capture_opt(model, train_cfg):
            opt = orig_build(model, train_cfg)
            captured["optimizer"] = opt
            return opt

        monkeypatch.setattr(tes, "build_training_optimizer", capture_opt)
        real_pass = tes._validation_pass
        checks: list[bool] = []

        def censused_pass(**kwargs):
            before = _census(kwargs["model"], captured["optimizer"], kwargs["criterion"])
            out = real_pass(**kwargs)
            after = _census(kwargs["model"], captured["optimizer"], kwargs["criterion"])
            checks.append(_census_equal(before, after))
            # perturb nothing: the census clones are local
            return out

        monkeypatch.setattr(tes, "_validation_pass", censused_pass)
        _run(two_family, tmp_path, name="census", eval_sample_set=two_family.full_sample_set())
        assert checks == [True, True, True]

    def test_an_objective_that_mutates_its_state_under_validation_fails_closed(
        self, two_family, tmp_path, monkeypatch
    ):
        class _CountingFocal(torch.nn.Module):
            def __init__(self, cfg):
                super().__init__()
                self.inner = get_criterion(cfg, None)
                self.register_buffer("calls", torch.zeros(1))

            def forward(self, out, tgt):
                self.calls += 1  # a plugin violating the contract
                return self.inner(out, tgt)

        monkeypatch.setattr(
            tes, "get_criterion", lambda cfg, class_weights=None: _CountingFocal(cfg)
        )
        with pytest.raises(tes.ObjectiveStateMutationError, match="_CountingFocal"):
            _run(two_family, tmp_path, name="mut", eval_sample_set=two_family.full_sample_set())

    def test_mode_is_restored_even_when_the_pass_raises(self, two_family, tmp_path, monkeypatch):
        """The `finally` restores `training=True` immediately — a caller cannot
        rely on the next epoch's `model.train()` when there is no next epoch."""
        instances: list = []

        class _RaisesInEval(torch.nn.Module):
            def __init__(self, cfg, *a, **k):
                super().__init__()
                self.inner = _REAL_WAVENET(cfg, *a, **k)
                instances.append(self)

            def forward(self, x):
                if not self.training:
                    raise RuntimeError("boom in validation")
                return self.inner(x)

        monkeypatch.setitem(MODEL_REGISTRY, "wavenet", _RaisesInEval)
        with pytest.raises(RuntimeError, match="boom in validation"):
            _run(two_family, tmp_path, name="mode", eval_sample_set=two_family.full_sample_set())
        assert instances and instances[0].training is True


# ---------------------------------------------------------------------------
# (l) task-owned materialization failures cannot become successful training
# ---------------------------------------------------------------------------


class TestExactMaterialization:
    @pytest.mark.parametrize(
        "successful_passes,reason",
        [
            (0, "task cannot materialize the declared scope"),
            (1, "data changed between epochs"),
        ],
    )
    def test_task_refusal_propagates_without_success_artifacts(
        self, two_family, tmp_path, monkeypatch, successful_passes, reason
    ):
        """The task validates its own files; the engine must not swallow its refusal.

        Old filesystem/topology checks belonged to the removed scientific data
        adapter. At the generic boundary those causes are the same typed
        refusal; the distinct engine states are before any validation result
        and after a real successful pass. Both must fail without artifacts.
        """
        original = TwoFamilyDataPath.validation_dataset
        calls = []
        failure = tes.ValidationScopeError(reason)

        def refusing(self, scope, params):
            calls.append(scope)
            if len(calls) > successful_passes:
                raise failure
            return original(self, scope, params)

        monkeypatch.setattr(TwoFamilyDataPath, "validation_dataset", refusing)
        with pytest.raises(tes.ValidationScopeError) as caught:
            _run(two_family, tmp_path, name="refused", eval_sample_set=two_family.full_sample_set())
        assert caught.value is failure
        assert len(calls) == successful_passes + 1
        assert list((tmp_path / "refused" / "m").iterdir()) == []
        assert list((tmp_path / "refused" / "r").iterdir()) == []


# ---------------------------------------------------------------------------
# (m) comparability stamped through the trainer for reduction="sum"
# ---------------------------------------------------------------------------


class TestComparabilityStampedByTrainer:
    def test_sum_reduction_is_recorded_not_established_and_r3_still_computed(
        self, two_family, tmp_path
    ):
        summary = _run(
            two_family,
            tmp_path,
            name="sum",
            eval_sample_set=two_family.full_sample_set(),
            epochs=1,
            loss_cfg=LossConfig(reduction="sum"),
        )
        h = TrainingHistory.model_validate(summary["training_history"])
        assert (
            h.comparability == "not_established"
            and h.comparability_reason == COMPARABILITY_REASON_SUM
        )
        assert h.objective_reduction == "sum"
        assert h.validation_objective is not None and len(h.validation_objective) == 1
