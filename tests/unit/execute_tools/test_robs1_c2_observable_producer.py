"""`R-OBS-1` C2 — the REAL runtime producer, and what it persists.

Levels 3 and 4 of the row's five-level required contract:

  level 3  real runtime producer — production code populates it during a run
  level 4  persistence — it survives into the record

**These tests drive the production trainer.** They call
``run_experiment_streaming`` on the in-process two-family fixture (CPU,
seconds) — the same vehicle Step 07a's own validation-pass suite uses — so
the observations asserted here were produced by the real epoch loop, the real
transactional validation pass and the real ``_build_training_history``. The
row's ``evidence_rule_binding`` excludes hand-authored fixtures by name, and
that exclusion is why no test in this file constructs a ``TrainingHistory``:
a hand-built one certifies a world production cannot reach.

Families, each naming the defect only it catches:

  (a) a declared DYNAMIC observable yields one value per completed epoch, in
      the real payload, keyed by its declared name;
  (b) a declared STATIC observable yields exactly one value, read off the
      TRAINED model — not the initial one;
  (c) the pass stays transactional: R2, R3 and the trained weights are
      bit-identical with and without observables;
  (d) a failing or non-finite observable is an ABSENCE, never a sentinel and
      never a failed training attempt;
  (e) a run that declares NONE emits a byte-identical summary;
  (f) the payload survives `interpret_training_results` into `TrainingResults`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import sys

import numpy as np
import pytest
import torch

import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.observables import (
    DeclaredDynamicObservable,
    DeclaredStaticObservable,
    RunObservables,
    StaticObservable,
    bind_run_observables,
    resolve_bound_run_observables,
)
from execute_tools.task_data_path import bind_task_data_path
from execute_tools.training_history import (
    STATIC_OBSERVATIONS_KEY,
    TRAINING_HISTORY_KEY,
    interpret_training_results,
)
from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig
from tests.helpers.synthetic_training_data_path import TwoFamilyDataPath
from tests.helpers.two_family_profile import TwoFamilyFixture, write_two_family_fixture

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PLUGIN_FIXTURE = os.path.join(REPO_ROOT, "tests", "fixtures", "robs1", "_observable_plugins.py")
EPOCHS = 3

#: "the caller said nothing", distinct from an explicit `None` (no pass).
_DEFAULT_EVAL = object()


def _plugins():
    spec = importlib.util.spec_from_file_location("_robs1_producer_plugins", PLUGIN_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def two_family(tmp_path) -> TwoFamilyFixture:
    return write_two_family_fixture(tmp_path)


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


def _sandbox(tmp_path, name: str) -> dict:
    dirs = {"models": str(tmp_path / name / "m"), "results": str(tmp_path / name / "r")}
    for path in dirs.values():
        os.makedirs(path, exist_ok=True)
    return dirs


def _run(
    fx: TwoFamilyFixture,
    tmp_path,
    *,
    name: str,
    observables: RunObservables | None = None,
    eval_sample_set: dict | None | object = _DEFAULT_EVAL,
    epochs: int = EPOCHS,
) -> dict:
    """One in-process streaming run through the PRODUCTION entry point."""
    random.seed(7)
    np.random.seed(7)
    torch.manual_seed(0)
    # `run_experiment_streaming` resolves observables from the RUN-SCOPED
    # BINDING, not a parameter — its argument list is frozen by a structural
    # guard. Binding here is what `main()` does through
    # `child_observables_binding`, so these tests drive the production wiring
    # rather than a shape production does not have.
    data_path = TwoFamilyDataPath(fx)
    with (
        bind_dataset_profile(fx.profile),
        bind_task_data_path(data_path),
        bind_run_observables(observables or RunObservables()),
    ):
        summary = tes.run_experiment_streaming(
            _tiny_model_cfg(fx.seg_size),
            TrainConfig(lr=1e-3, epochs=epochs, batch_size=2, optimizer_type="adam", device="cpu"),
            LossConfig(),
            sample_set=fx.full_sample_set(),
            data_dir=fx.data_dir,
            sandbox_dirs=_sandbox(tmp_path, name),
            exp_id=name,
            train_base_seed=123,
            profile=fx.profile,
            **data_path.scope_kwargs(
                fx.full_sample_set(),
                {"1": [0, 1]} if eval_sample_set is _DEFAULT_EVAL else eval_sample_set,
            ),
        )
    assert summary is not None
    return summary


def _dynamic(*entries) -> RunObservables:
    return RunObservables(
        dynamic=tuple(DeclaredDynamicObservable(name=n, implementation=i) for n, i in entries)
    )


def _static(*entries) -> RunObservables:
    return RunObservables(
        static=tuple(DeclaredStaticObservable(name=n, implementation=i) for n, i in entries)
    )


# ---------------------------------------------------------------------------
# (a) Level 3 — a real training run produces a per-epoch series
# ---------------------------------------------------------------------------


class TestDynamicProducer:
    def test_a_declared_dynamic_observable_yields_ONE_VALUE_PER_EPOCH(self, two_family, tmp_path):
        """The sentence the field's own docstring says has never been true.

        "NO REAL TRAINING RUN HAS EVER PRODUCED AN OBSERVATION." This is that
        run: the values below came out of the epoch loop, not out of a
        fixture.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="dyn",
            observables=_dynamic(
                ("mean_target", plugins.MeanTargetObservable()),
                ("output_mean", plugins.OutputMeanObservable()),
            ),
        )
        observations = summary[TRAINING_HISTORY_KEY]["observations"]
        assert sorted(observations) == ["mean_target", "output_mean"]
        for name, series in observations.items():
            assert len(series) == EPOCHS, name
            assert all(isinstance(v, float) for v in series), name

    def test_the_series_is_as_long_as_the_epochs_the_run_COMPLETED(self, two_family, tmp_path):
        """Alignment to the epoch axis, at a second epoch count.

        A producer that appended once per BATCH, or once per run, passes the
        length check above only by coincidence at one epoch count.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="dyn1",
            observables=_dynamic(("mean_target", plugins.MeanTargetObservable())),
            epochs=1,
        )
        history = summary[TRAINING_HISTORY_KEY]
        assert history["epochs_completed"] == 1
        assert len(history["observations"]["mean_target"]) == 1

    def test_the_observable_actually_RECEIVES_the_validation_batches(self, two_family, tmp_path):
        """The feed, against an expectation derived from the FIXTURE.

        Every shape assertion above survives an observable that is reset and
        read but never fed: it still returns a finite value of the right
        length. Only a number whose answer is known outside the engine can
        tell "wired up" from "wired up and receiving data" — so this asserts
        the exact row count implied by the eval scope `{"1": [0, 1]}`, which
        is two PSD segments' worth of ML rows.
        """
        plugins = _plugins()
        expected_rows = float(2 * two_family.ml_segs_per_psd)
        summary = _run(
            two_family,
            tmp_path,
            name="fed",
            observables=_dynamic(("rows_seen", plugins.BatchCountObservable())),
        )
        assert (
            summary[TRAINING_HISTORY_KEY]["observations"]["rows_seen"] == [expected_rows] * EPOCHS
        )

    def test_an_observation_is_a_DIFFERENT_quantity_from_the_objective(self, two_family, tmp_path):
        """The whole point of the family, per the field's own description.

        An observable that merely echoed R2 or R3 would satisfy every shape
        assertion above while carrying no new information.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="dyn2",
            observables=_dynamic(("output_mean", plugins.OutputMeanObservable())),
        )
        history = summary[TRAINING_HISTORY_KEY]
        series = history["observations"]["output_mean"]
        assert series != history["train_objective"]
        assert series != history["validation_objective"]

    def test_no_declaration_leaves_observations_EMPTY(self, two_family, tmp_path):
        summary = _run(two_family, tmp_path, name="none")
        assert summary[TRAINING_HISTORY_KEY]["observations"] == {}

    def test_a_dynamic_observable_produces_NOTHING_without_a_validation_pass(
        self, two_family, tmp_path
    ):
        """Honest absence rather than a fabricated series.

        A dynamic observable rides the per-epoch validation pass. A run with
        no eval scope has no per-epoch observation point at all — the same
        state in which R3 is honestly absent — and must produce no series
        rather than one invented from training batches.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="noeval",
            observables=_dynamic(("mean_target", plugins.MeanTargetObservable())),
            eval_sample_set=None,
        )
        assert summary[TRAINING_HISTORY_KEY]["observations"] == {}
        assert summary[TRAINING_HISTORY_KEY]["validation_objective"] is None


# ---------------------------------------------------------------------------
# (b) Level 3 — the static family reads the TRAINED model
# ---------------------------------------------------------------------------


class TestStaticProducer:
    def test_a_declared_static_observable_yields_exactly_one_value(self, two_family, tmp_path):
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="stat",
            observables=_static(("trainable_parameters", plugins.ParameterCountObservable())),
        )
        assert summary[STATIC_OBSERVATIONS_KEY] == {
            "trainable_parameters": float(summary["model_params"])
        }

    def test_the_static_observable_sees_the_TRAINED_model_not_the_initial_one(
        self, two_family, tmp_path
    ):
        """The defect a parameter count cannot catch.

        Counting parameters is invariant to training, so it proves the call
        happened but not WHEN. This observable reads a weight statistic that
        only training moves: a call sited before the epoch loop returns the
        initialisation value instead.
        """

        class FirstWeightSum(StaticObservable):
            def compute(self, model):
                return float(next(iter(model.parameters())).sum().item())

        summary = _run(
            two_family,
            tmp_path,
            name="stat_trained",
            observables=_static(("first_weight_sum", FirstWeightSum())),
        )
        observed = summary[STATIC_OBSERVATIONS_KEY]["first_weight_sum"]

        # The value the SAVED (trained) model carries, read independently of
        # the production path that produced `observed`.
        saved = torch.load(
            os.path.join(
                str(tmp_path / "stat_trained" / "m"), "model_wavenet_stat_trained_agent.pth"
            )
        )
        trained_first = float(next(iter(saved.values())).sum().item())
        assert observed == pytest.approx(trained_first, abs=1e-5)

    def test_no_static_declaration_writes_NO_KEY_AT_ALL(self, two_family, tmp_path):
        """Not an empty mapping — no key. This is the byte-identity rule."""
        summary = _run(two_family, tmp_path, name="nostat")
        assert STATIC_OBSERVATIONS_KEY not in summary


# ---------------------------------------------------------------------------
# (c) The validation pass stays transactional
# ---------------------------------------------------------------------------


class TestObservationDoesNotPerturbTraining:
    def test_R2_R3_and_the_trained_weights_are_BIT_IDENTICAL_with_and_without(
        self, two_family, tmp_path
    ):
        """The guarantee `_validation_pass` exists to make.

        An observable that consumed an RNG draw, mutated a tensor in place or
        left the model in ``eval()`` would move one of these three.
        """
        plugins = _plugins()
        without = _run(two_family, tmp_path, name="plain")
        with_obs = _run(
            two_family,
            tmp_path,
            name="observed",
            observables=RunObservables(
                dynamic=(
                    DeclaredDynamicObservable(
                        name="mean_target", implementation=plugins.MeanTargetObservable()
                    ),
                ),
                static=(
                    DeclaredStaticObservable(
                        name="params", implementation=plugins.ParameterCountObservable()
                    ),
                ),
            ),
        )
        assert without["loss_history"] == with_obs["loss_history"]
        assert (
            without[TRAINING_HISTORY_KEY]["validation_objective"]
            == with_obs[TRAINING_HISTORY_KEY]["validation_objective"]
        )
        a = torch.load(os.path.join(str(tmp_path / "plain" / "m"), "model_wavenet_plain_agent.pth"))
        b = torch.load(
            os.path.join(str(tmp_path / "observed" / "m"), "model_wavenet_observed_agent.pth")
        )
        assert a.keys() == b.keys()
        assert all(torch.equal(a[k], b[k]) for k in a)


# ---------------------------------------------------------------------------
# (d) A failed observation is an absence
# ---------------------------------------------------------------------------


class TestFailureIsAbsence:
    def test_a_raising_observable_does_not_fail_the_training_attempt(self, two_family, tmp_path):
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="raise",
            observables=_dynamic(
                ("broken", plugins.RaisingDynamicObservable()),
                ("healthy", plugins.MeanTargetObservable()),
            ),
        )
        observations = summary[TRAINING_HISTORY_KEY]["observations"]
        assert "broken" not in observations
        # The healthy sibling is unaffected — one bad observable does not
        # suppress the family.
        assert len(observations["healthy"]) == EPOCHS

    def test_a_NON_FINITE_observation_is_dropped_rather_than_recorded(self, two_family, tmp_path):
        """A NaN is the absence of an observation, not an observation of NaN.

        Recording it would put a non-finite point on a plotted series and into
        any future consumer's arithmetic.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="nan",
            observables=_dynamic(("nanny", plugins.NonFiniteDynamicObservable())),
        )
        assert summary[TRAINING_HISTORY_KEY]["observations"] == {}

    def test_a_PARTIAL_series_is_dropped_WHOLE_rather_than_padded(self, two_family, tmp_path):
        """An observable that worked in some epochs and not others.

        Its series is shorter than the epoch axis and the missing point is not
        at a known index, so it cannot be aligned. Padding it would fabricate
        an observation; keeping it unpadded would violate the schema's own
        length invariant and cost the run its ENTIRE history — so the series
        is dropped and the healthy sibling survives.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="partial",
            observables=_dynamic(
                ("flaky", plugins.FirstEpochOnlyObservable()),
                ("healthy", plugins.MeanTargetObservable()),
            ),
        )
        history = summary[TRAINING_HISTORY_KEY]
        assert "flaky" not in history["observations"]
        assert len(history["observations"]["healthy"]) == EPOCHS
        # The run kept its history rather than losing it to a schema refusal.
        assert history["epochs_completed"] == EPOCHS

    def test_a_raising_STATIC_observable_does_not_fail_the_attempt(self, two_family, tmp_path):
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="staticraise",
            observables=_static(
                ("broken", plugins.RaisingStaticObservable()),
                ("params", plugins.ParameterCountObservable()),
            ),
        )
        assert summary[STATIC_OBSERVATIONS_KEY] == {"params": float(summary["model_params"])}


# ---------------------------------------------------------------------------
# (e) Byte identity for a run that declares nothing
# ---------------------------------------------------------------------------


class TestUndeclaredRunIsByteIdentical:
    def test_the_summary_of_an_undeclared_run_has_the_pre_ROBS1_shape(self, two_family, tmp_path):
        """Key set AND serialized bytes, not just semantics.

        The trainer writes this dict to the results JSON the parent reads, so
        an extra key here is a byte change in every persisted artifact of
        every run — including every run that declared no observable.
        """
        summary = _run(two_family, tmp_path, name="identical")
        assert list(summary) == [
            "final_loss",
            "loss_history",
            "model_params",
            TRAINING_HISTORY_KEY,
        ]
        assert '"observations": {}' in json.dumps(summary, indent=4)
        assert STATIC_OBSERVATIONS_KEY not in json.dumps(summary)


# ---------------------------------------------------------------------------
# Reachability: the child actually composes from the transported manifest
# ---------------------------------------------------------------------------


class TestTheChildComposesTheTransportedManifest:
    def test_main_composes_observables_from_task_manifest_and_FORWARDS_them(
        self, tmp_path, monkeypatch, two_family
    ):
        """The production path this whole family depends on.

        Every test above hands `run_experiment_streaming` its observables
        directly. That proves the ENGINE produces observations; it says
        nothing about whether a real subprocess ever receives any. A `main()`
        that parsed `--task_manifest` and never composed would leave every one
        of those tests green and the feature dead at the child.
        """
        seen: dict = {}

        def fake_stream(*args, **kwargs):
            # Read at the instant the engine would: a binding established and
            # torn down around the call would be invisible to a check made
            # after `main()` returns.
            seen["observables"] = resolve_bound_run_observables()
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
        (cfg_dir / "ess.json").write_text(json.dumps({"1": [0, 1]}))
        manifest = _manifest_declaring_observables(tmp_path)

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
            "--eval_sample_set_json",
            str(cfg_dir / "ess.json"),
            "--task_manifest",
            manifest,
            "--task_data_path_id",
            "quickstart_tabular",
        ]
        monkeypatch.setattr(sys, "argv", argv)
        with bind_dataset_profile(two_family.profile):
            tes.main()

        observables = seen["observables"]
        assert [d.name for d in observables.dynamic] == ["mean_target"]
        assert [s.name for s in observables.static] == ["trainable_parameters"]

    def test_without_a_manifest_the_child_forwards_NO_observables(
        self, tmp_path, monkeypatch, two_family
    ):
        """A child with a registered data path but no manifest has no observables.

        No task-less training default is restored by testing absence of the
        optional observation declaration.
        """
        import workflows.task_composition as composition

        monkeypatch.setattr(
            composition,
            "resolve_child_task_data_path",
            lambda *a, **k: TwoFamilyDataPath(two_family),
        )
        seen: dict = {}

        def fake_stream(*args, **kwargs):
            seen["observables"] = resolve_bound_run_observables()
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
        monkeypatch.setattr(
            sys,
            "argv",
            [
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
                str(tmp_path / "sb2"),
                "--exp_id",
                "legacy",
                "--sample_set_json",
                str(cfg_dir / "ss.json"),
                "--task_data_path_id",
                TwoFamilyDataPath.task_data_path_id,
            ],
        )
        with bind_dataset_profile(two_family.profile):
            tes.main()
        bound = seen["observables"]
        assert bound.dynamic == ()
        assert bound.static == ()


def _manifest_declaring_observables(tmp_path) -> str:
    """A real, composable manifest declaring one observable of each kind."""
    import shutil

    import yaml

    dst_dir = tmp_path / "composed" / "configs" / "task_composition"
    dst_dir.mkdir(parents=True)
    shutil.copy(
        os.path.join(REPO_ROOT, "configs", "task_composition", "quickstart.yaml"),
        dst_dir / "quickstart.yaml",
    )
    os.symlink(
        os.path.join(REPO_ROOT, "examples"),
        tmp_path / "composed" / "examples",
        target_is_directory=True,
    )
    path = dst_dir / "quickstart.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["dynamic_observables"] = [
        {
            "name": "mean_target",
            "implementation": {"file": PLUGIN_FIXTURE, "symbol": "MeanTargetObservable"},
        }
    ]
    raw["static_observables"] = [
        {
            "name": "trainable_parameters",
            "implementation": {"file": PLUGIN_FIXTURE, "symbol": "ParameterCountObservable"},
        }
    ]
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return str(path)


# ---------------------------------------------------------------------------
# (f) Level 4 — it survives the trainer→tuner contract boundary
# ---------------------------------------------------------------------------


class TestItSurvivesInterpretation:
    def test_both_families_reach_TrainingResults_through_the_real_summary(
        self, two_family, tmp_path
    ):
        """The ONE validation boundary, fed the trainer's own output.

        Not a hand-built dict: this is the summary the run above produced,
        round-tripped through JSON exactly as the subprocess boundary does.
        """
        plugins = _plugins()
        summary = _run(
            two_family,
            tmp_path,
            name="interp",
            observables=RunObservables(
                dynamic=(
                    DeclaredDynamicObservable(
                        name="mean_target", implementation=plugins.MeanTargetObservable()
                    ),
                ),
                static=(
                    DeclaredStaticObservable(
                        name="params", implementation=plugins.ParameterCountObservable()
                    ),
                ),
            ),
        )
        results = interpret_training_results(
            json.loads(json.dumps(summary)), expected_validation=True
        )
        assert results.history is not None
        assert len(results.history.observations["mean_target"]) == EPOCHS
        assert results.static_observations == {"params": float(summary["model_params"])}

    def test_an_undeclared_run_interprets_to_the_empty_state(self, two_family, tmp_path):
        summary = _run(two_family, tmp_path, name="interp_none")
        results = interpret_training_results(
            json.loads(json.dumps(summary)), expected_validation=True
        )
        assert results.history is not None
        assert results.history.observations == {}
        assert results.static_observations == {}

    @pytest.mark.parametrize(
        "payload", [None, "not a mapping", 7, {"ok": "not a number"}, {"bad": float("nan")}]
    )
    def test_a_MALFORMED_static_payload_is_an_absence_not_a_contract_failure(
        self, two_family, tmp_path, payload
    ):
        """A broken diagnostic must not fail a successful training attempt.

        The two SCIENTIFIC payloads keep their fail-closed treatment; this one
        does not, because declaring an observable must never be riskier than
        not declaring one.
        """
        summary = _run(two_family, tmp_path, name=f"malformed{abs(hash(str(payload))) % 97}")
        summary[STATIC_OBSERVATIONS_KEY] = payload
        results = interpret_training_results(summary, expected_validation=True)
        assert results.static_observations == {}
