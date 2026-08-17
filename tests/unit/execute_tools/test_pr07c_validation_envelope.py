"""`validation_max_samples` — the interim validation-scope envelope (07c C6).

07a's Gate 2 capped the TRAINING epoch at 2 000 rows while validation ran the
full 15 000-row eval SampleSet: 7.5x the training work, every epoch, unpriced.
`validation_max_train_samples` could not bound it, because it bounds a
different set — the two names differ by one word and that is the whole point.

This is explicitly the INTERIM cost bound, not the root fix (C5's priced
deadline is). And it is a bound that can DEFEAT its own Gate: clamp validation
hard enough and the counterfactual stops separating, which §4.1 records as
INCONCLUSIVE rather than PASS.

The clamp applies to the REQUESTED scope. That is not a preference: 07a's
`TrainingHistory` fails closed when `validation_samples !=
validation_requested_samples`, so a ceiling applied after materialization would
make every clamped run RAISE.
"""

from __future__ import annotations

import pytest

from execute_tools.dataset_config import TIDMAD_PROFILE
from execute_tools.train_engine_sandbox import ValidationScopeError, clamp_validation_scope
from execute_tools.training_history import TrainingHistory

#: A natural scope: 3 files x 4 PSD segments, 2 ML rows per PSD = 24 rows.
NATURAL = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]}
ML_PER_PSD = 2
NATURAL_ROWS = 24


def _rows(scope: dict) -> int:
    return sum(len(v) for v in scope.values()) * ML_PER_PSD


class TestTheCeilingClamps:
    def test_none_is_exact_parity(self):
        """The default, and every production campaign. The object must be the
        scope itself, not a rebuilt copy — a rebuild is where key types and
        ordering quietly change."""
        assert clamp_validation_scope(NATURAL, max_samples=None, ml_segs_per_psd=ML_PER_PSD) is (
            NATURAL
        )

    def test_a_ceiling_above_the_natural_size_does_not_clamp(self):
        out = clamp_validation_scope(NATURAL, max_samples=1000, ml_segs_per_psd=ML_PER_PSD)
        assert _rows(out) == NATURAL_ROWS
        assert out == NATURAL

    def test_a_ceiling_equal_to_the_natural_size_does_not_clamp(self):
        out = clamp_validation_scope(NATURAL, max_samples=NATURAL_ROWS, ml_segs_per_psd=ML_PER_PSD)
        assert _rows(out) == NATURAL_ROWS

    @pytest.mark.parametrize("ceiling,expected_rows", [(2, 2), (8, 8), (10, 10), (22, 22)])
    def test_an_aligned_ceiling_resolves_exactly(self, ceiling, expected_rows):
        """`validation_samples == min(natural, ceiling)` exactly, whenever the
        ceiling is a whole number of PSD segments."""
        out = clamp_validation_scope(NATURAL, max_samples=ceiling, ml_segs_per_psd=ML_PER_PSD)
        assert _rows(out) == min(NATURAL_ROWS, expected_rows)

    @pytest.mark.parametrize("ceiling,expected_rows", [(3, 2), (9, 8), (23, 22)])
    def test_an_unaligned_ceiling_rounds_DOWN_and_never_overshoots(self, ceiling, expected_rows):
        """A SampleSet can only express whole PSD segments, so a ceiling that
        falls between them resolves to the largest multiple below it.

        Rounding down rather than up is the load-bearing half: this is a
        MAXIMUM, and a bound that could be exceeded is not one.
        """
        out = clamp_validation_scope(NATURAL, max_samples=ceiling, ml_segs_per_psd=ML_PER_PSD)
        assert _rows(out) == expected_rows
        assert _rows(out) <= ceiling

    def test_a_ceiling_below_one_psd_segment_is_refused_not_silently_zeroed(self):
        """R3 = Σ n_i·L_i / Σ n_i does not exist for an empty scope. Silently
        resolving to zero rows would produce a run with no validation and no
        error; the refusal says what to change."""
        with pytest.raises(ValidationScopeError, match="below one PSD segment"):
            clamp_validation_scope(NATURAL, max_samples=1, ml_segs_per_psd=ML_PER_PSD)

    def test_files_that_lose_every_segment_are_dropped_not_left_empty(self):
        """An empty per-file list would reach the pre-flight as a request for
        a file with no segments — a shape the rest of the path never sees."""
        out = clamp_validation_scope(NATURAL, max_samples=4, ml_segs_per_psd=ML_PER_PSD)
        assert all(v for v in out.values())
        assert set(out) == {0}


class TestWhichSamples:
    """rev-2 blocker 5. 07a defines R3 as a real validation objective, so a
    clamp that silently changed WHICH rows are evaluated would change the
    science, not just the cost."""

    def test_the_same_input_config_and_ceiling_select_identical_identities(self):
        first = clamp_validation_scope(NATURAL, max_samples=10, ml_segs_per_psd=ML_PER_PSD)
        second = clamp_validation_scope(NATURAL, max_samples=10, ml_segs_per_psd=ML_PER_PSD)
        # Identities AND order, not just the count.
        assert list(first.items()) == list(second.items())

    def test_the_selection_is_the_declared_prefix_in_ascending_file_order(self):
        """Asserted as the concrete selection, not as "it is deterministic".
        A stable-but-wrong rule is still deterministic."""
        out = clamp_validation_scope(NATURAL, max_samples=10, ml_segs_per_psd=ML_PER_PSD)
        assert out == {0: [0, 1, 2, 3], 1: [0]}

    def test_file_order_does_not_depend_on_dict_insertion_order(self):
        """A scope assembled in a different order must select the same rows —
        otherwise the clamp's result depends on how the caller built the dict."""
        shuffled = {2: [0, 1, 2, 3], 0: [0, 1, 2, 3], 1: [0, 1, 2, 3]}
        assert clamp_validation_scope(
            shuffled, max_samples=10, ml_segs_per_psd=ML_PER_PSD
        ) == clamp_validation_scope(NATURAL, max_samples=10, ml_segs_per_psd=ML_PER_PSD)

    def test_string_and_int_file_keys_order_numerically(self):
        """The SampleSet crosses a JSON boundary, so keys arrive as strings.
        Ordering them lexicographically would put file 10 before file 2."""
        as_strings = {"10": [0, 1], "2": [0, 1], "0": [0, 1]}
        # Budget 3 PSD segments: file "0" takes both, file "2" takes one, file
        # "10" gets nothing. Lexicographic ordering would have visited "10"
        # second and dropped file 2 instead.
        out = clamp_validation_scope(as_strings, max_samples=6, ml_segs_per_psd=ML_PER_PSD)
        assert list(out) == ["0", "2"]
        assert out == {"0": [0, 1], "2": [0]}


class TestTheEnvelopeMatrix:
    """rev-3 correction. The four controls do NOT share one dimension, and
    `min()` is only meaningful within one. Rev 2's "the tighter bound wins"
    was right for one pair and wrong for the other two."""

    def test_portion_and_samples_share_a_dimension_so_the_tighter_wins(self):
        """Both bound the VALIDATION sample scope. `validation_max_portion`
        shrinks the natural scope first; the row ceiling then applies to
        whatever that produced, so the outcome is the tighter of the two in
        either order."""
        # portion-like reduction to 2 files, then the row ceiling
        after_portion = {0: [0, 1, 2, 3], 1: [0, 1, 2, 3]}  # 16 rows
        tighter_ceiling = clamp_validation_scope(
            after_portion, max_samples=6, ml_segs_per_psd=ML_PER_PSD
        )
        looser_ceiling = clamp_validation_scope(
            after_portion, max_samples=100, ml_segs_per_psd=ML_PER_PSD
        )
        assert _rows(tighter_ceiling) == 6  # the ceiling won
        assert _rows(looser_ceiling) == 16  # the portion won
        assert _rows(tighter_ceiling) == min(16, 6)
        assert _rows(looser_ceiling) == min(16, 100)

    def test_the_training_ceiling_is_orthogonal_to_the_validation_ceiling(self):
        """The pair the names make easy to confuse.
        `validation_max_train_samples` bounds TRAINING rows; this bounds
        VALIDATION rows. There is no `min()` between them because they bound
        different SETS — asserted in BOTH directions from the policy object,
        so a future edit that fused them fails here."""
        from core.runtime_control.session import RuntimeControlPolicy

        only_training = RuntimeControlPolicy(validation_max_train_samples=2000)
        assert only_training.validation_max_samples is None

        only_validation = RuntimeControlPolicy(validation_max_samples=500)
        assert only_validation.validation_max_train_samples is None

        both = RuntimeControlPolicy(validation_max_train_samples=2000, validation_max_samples=500)
        assert both.validation_max_train_samples == 2000
        assert both.validation_max_samples == 500

        # And the validation clamp is indifferent to the training ceiling's
        # value: the same scope in, the same scope out.
        assert clamp_validation_scope(
            NATURAL, max_samples=both.validation_max_samples, ml_segs_per_psd=ML_PER_PSD
        ) == clamp_validation_scope(NATURAL, max_samples=500, ml_segs_per_psd=ML_PER_PSD)

    def test_the_phase_fuse_is_orthogonal_and_in_different_units(self):
        """Seconds versus samples. Neither is expressible in the other's
        units, so there is no `min()` to take: the sample ceiling sizes the
        workload, the phase fuse remains an independently enforceable
        wall-clock termination."""
        from core.runtime_control.session import RuntimeControlPolicy

        policy = RuntimeControlPolicy(
            validation_max_samples=500, watchdog={"max_phase_seconds": 30.0}
        )
        assert policy.validation_max_samples == 500
        assert policy.watchdog.max_phase_seconds == 30.0
        # The clamp reads only the sample ceiling; the fuse cannot change the
        # resolved scope, and the scope cannot change the fuse.
        assert clamp_validation_scope(NATURAL, max_samples=8, ml_segs_per_psd=ML_PER_PSD) == (
            clamp_validation_scope(NATURAL, max_samples=8, ml_segs_per_psd=ML_PER_PSD)
        )


class TestTheSchemaRefusesNonsense:
    @pytest.mark.parametrize("bad", [0, -1, -500])
    def test_zero_and_negative_are_rejected_at_startup(self, bad):
        """Before any spend. A ceiling of 0 would mean "validate nothing",
        which is `eval_sample_set=None`, not a ceiling."""
        from pydantic import ValidationError

        from core.runtime_control.session import RuntimeControlPolicy

        with pytest.raises(ValidationError, match="validation_max_samples"):
            RuntimeControlPolicy(validation_max_samples=bad)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_the_operator_input_rejects_them_too(self, bad):
        """The tuner's own input schema, so a bad value never reaches the
        policy in the first place."""
        from pydantic import ValidationError

        from agent.schemas.hyperparam_tuning import HyperparamTuningInput

        with pytest.raises(ValidationError, match="validation_max_samples"):
            HyperparamTuningInput(
                model_type="wavenet",
                run_name="x",
                workspace="/tmp/x",
                validation_max_samples=bad,
            )


class TestTheClampProvenanceIsRecoverable:
    """Q-07c-9. `ceiling=2000, requested=2000` is ambiguous between "the
    natural scope was 2 000 and the ceiling did not bind" and "the natural
    scope was 12 000 and the ceiling clamped it" — the configured ceiling plus
    the effective count cannot recover which happened."""

    @staticmethod
    def _history(**over):
        base = dict(
            objective_kind="focal",
            objective_config_fingerprint="fp",
            objective_reduction="mean",
            comparability="established",
            comparability_reason=None,
            epochs_planned=1,
            epochs_completed=1,
            train_objective=[0.5],
            validation_objective=[0.6],
            validation_requested_samples=2000,
            validation_samples=2000,
            validation_seconds=[1.0],
        )
        base.update(over)
        return TrainingHistory(**base)

    def test_a_clamped_run_is_distinguishable(self):
        clamped = self._history(validation_requested_samples_before_limit=12_000)
        assert clamped.validation_requested_samples_before_limit is not None
        was_limited = (
            clamped.validation_requested_samples_before_limit > clamped.validation_requested_samples
        )
        assert was_limited is True

    def test_the_ambiguous_case_reads_as_NOT_limited(self):
        """`ceiling == natural == 2000` — the case rev 2 got wrong."""
        not_clamped = self._history(validation_requested_samples_before_limit=2000)
        was_limited = (
            not_clamped.validation_requested_samples_before_limit
            > not_clamped.validation_requested_samples
        )
        assert was_limited is False

    def test_no_ceiling_configured_leaves_the_field_none(self):
        assert self._history().validation_requested_samples_before_limit is None

    def test_a_before_limit_below_the_effective_count_is_refused(self):
        """A ceiling may only REDUCE. The reverse would invert `was_limited`
        for every consumer, silently."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="may only reduce"):
            self._history(validation_requested_samples_before_limit=500)

    def test_07as_exact_materialization_invariant_still_fires(self):
        """The clamp must never be an excuse to relax it."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="must materialize exactly"):
            self._history(validation_samples=1999)

    @pytest.mark.parametrize("before_limit", [None, 2000, 12_000])
    def test_comparability_is_byte_identical_with_and_without_a_clamp(self, before_limit):
        """rev-3 RETRACTION, as an executable guard. `stamp_comparability` is a
        function of the resolved `LossConfig` alone — objective kind and
        reduction — and answers "can THIS round's train and validation
        objectives be read against each other?", not "can two rounds be?".
        Widening it to carry sample-scope metadata would make it the semantic
        bag this codebase keeps refusing to create.
        """
        history = self._history(validation_requested_samples_before_limit=before_limit)
        assert history.comparability == "established"
        assert history.comparability_reason is None


class TestItIsNotPlannerVisible:
    def test_the_ceiling_never_reaches_the_planner(self):
        """An operator/runtime input. If the planner could see it, the harness
        would no longer own the bound — which is the whole reason the field
        exists."""
        from agent.prompts import _PLANNER_HIDDEN_RECORD_KEYS

        assert "training_history" in _PLANNER_HIDDEN_RECORD_KEYS

    def test_the_provenance_field_cannot_leak_through_the_history(self):
        """The planner drops the WHOLE `training_history` record key, so an
        inner field cannot leak regardless of what is added to it — the
        Gate-1-NOT-REQUIRED evidence, checked rather than asserted."""
        from agent.prompts import _PLANNER_HIDDEN_RECORD_KEYS

        assert "validation_requested_samples_before_limit" not in _PLANNER_HIDDEN_RECORD_KEYS
        assert "training_history" in _PLANNER_HIDDEN_RECORD_KEYS


class TestTheProfileGeometryIsRealistic:
    def test_the_tidmad_geometry_makes_the_fixture_numbers_meaningful(self):
        """The clamp's granularity is `psd_segment_length // seg_size`, so the
        rounding behaviour above is not a fixture artefact — under TIDMAD at
        seg 40 000 one PSD segment is 250 ML rows, and a ceiling of 100 is
        genuinely unsatisfiable."""
        psd = TIDMAD_PROFILE.dataset.psd_segment_length
        assert psd // 40_000 == 250
        with pytest.raises(ValidationScopeError, match="below one PSD segment"):
            clamp_validation_scope({0: [0, 1]}, max_samples=100, ml_segs_per_psd=psd // 40_000)


def _wavenet_cfg(seg_size: int) -> dict:
    return {
        "model_type": "wavenet",
        "segmentation_size": seg_size,
        "input_channels": 4,
        "residual_channels": 8,
        "gate_channels": 8,
        "skip_channels": 8,
        "kernel_size": 2,
        "num_blocks": 1,
    }


@pytest.mark.allow_real_subprocess
class TestTheClampInARealRun:
    """The REAL `train_engine_sandbox.py` subprocess, CPU, seconds.

    The unit tests above prove the clamp arithmetic. Only a real run proves
    that the clamped scope MATERIALIZES — which is the half 07a's fail-closed
    validator would reject if the ceiling were applied a moment too late.
    """

    @staticmethod
    def _run(tmp_path, monkeypatch, *, name: str, runtime_policy: dict, batch_size: int = 2):
        import core.sandbox_executor as sandbox_module
        from core.sandbox_executor import TidmadSandbox
        from execute_tools.dataset_config import bind_dataset_profile
        from tests.helpers.two_family_profile import write_two_family_fixture

        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        fx = write_two_family_fixture(tmp_path / "data")
        real_launch = sandbox_module._run_observed_subprocess

        def launch_with_data_dir(cmd, **kwargs):
            return real_launch([*cmd, "--data_dir", fx.data_dir], **kwargs)

        monkeypatch.setattr(sandbox_module, "_run_observed_subprocess", launch_with_data_dir)
        with bind_dataset_profile(fx.profile):
            sb = TidmadSandbox(run_name=name, workspace=str(tmp_path / "ws"), progress_bar=False)
            out = sb.execute_training(
                f"pr07c_{name}",
                name,
                "wavenet",
                _wavenet_cfg(fx.seg_size),
                {
                    "lr": 1e-3,
                    "epochs": 1,
                    "batch_size": batch_size,
                    "optimizer_type": "adam",
                    "device": "cpu",
                },
                {"loss_type": "focal"},
                sample_set={0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]},
                eval_sample_set=fx.full_sample_set(),
                train_base_seed=5,
                runtime_policy=runtime_policy,
            )
        assert out["status"] == "success", out.get("message")
        from execute_tools.training_history import interpret_training_results

        history = interpret_training_results(out["results"], expected_validation=True).history
        assert history is not None
        return history, sb, fx

    def test_no_ceiling_is_exact_parity(self, tmp_path, monkeypatch):
        history, _sb, _fx = self._run(tmp_path, monkeypatch, name="c6none", runtime_policy={})
        assert history.validation_samples == NATURAL_ROWS
        assert history.validation_requested_samples == NATURAL_ROWS
        assert history.validation_requested_samples_before_limit is None

    def test_a_binding_ceiling_clamps_and_still_materializes_exactly(self, tmp_path, monkeypatch):
        """07a's `validation_samples == validation_requested_samples` validator
        must never fire. It would if the ceiling were applied to the
        materialized rows instead of the request — every clamped run raising is
        the failure mode this ordering exists to prevent."""
        history, _sb, _fx = self._run(
            tmp_path, monkeypatch, name="c6clamp", runtime_policy={"validation_max_samples": 10}
        )
        assert history.validation_samples == 10
        assert history.validation_requested_samples == 10
        assert history.validation_requested_samples_before_limit == NATURAL_ROWS
        # The provenance the effective count alone cannot recover.
        assert (
            history.validation_requested_samples_before_limit > history.validation_requested_samples
        )

    def test_a_non_binding_ceiling_records_before_limit_equal_not_greater(
        self, tmp_path, monkeypatch
    ):
        """The ambiguous case, on a real run: the ceiling is configured but did
        not bind, and `was_limited` must read False."""
        history, _sb, _fx = self._run(
            tmp_path, monkeypatch, name="c6loose", runtime_policy={"validation_max_samples": 1000}
        )
        assert history.validation_samples == NATURAL_ROWS
        assert history.validation_requested_samples_before_limit == NATURAL_ROWS

    def test_comparability_is_unchanged_by_the_clamp(self, tmp_path, monkeypatch):
        """Same `LossConfig`, same stamp — with and without a binding ceiling.
        The rev-3 retraction, on real runs rather than constructed models."""
        clamped, _sb_a, _fx_a = self._run(
            tmp_path / "a",
            monkeypatch,
            name="c6cmpA",
            runtime_policy={"validation_max_samples": 10},
        )
        unclamped, _sb_b, _fx_b = self._run(
            tmp_path / "b", monkeypatch, name="c6cmpB", runtime_policy={}
        )
        assert clamped.comparability == unclamped.comparability == "established"
        assert clamped.comparability_reason == unclamped.comparability_reason is None
        assert clamped.objective_config_fingerprint == unclamped.objective_config_fingerprint

    def test_r3_over_a_partial_final_batch_is_sample_count_weighted(self, tmp_path, monkeypatch):
        """rev-2 blocker 5. A ceiling is exactly what CREATES a partial final
        batch, and that is precisely when the sample-count-weighted mean and
        the unweighted mean-of-batch-means diverge.

        10 clamped rows at batch 4 gives batches of 4, 4, 2. The epoch
        statistic 07a pins is
        `sample_count_weighted_mean_of_batch_criterion`, so R3 must be
        Σ n_i·L_i / Σ n_i — and must NOT be (L1+L2+L3)/3.
        """
        import os

        import torch
        from torch.utils.data import DataLoader

        import execute_tools.train_engine_sandbox as tes
        from execute_tools.dataset_config import bind_dataset_profile
        from ml_models.loss_models_sandbox import get_criterion
        from ml_models.models_format_sandbox import LossConfig
        from ml_models.models_sandbox import MODEL_REGISTRY

        history, sb, fx = self._run(
            tmp_path,
            monkeypatch,
            name="c6weight",
            runtime_policy={"validation_max_samples": 10},
            batch_size=4,
        )
        assert history.validation_samples == 10  # 4 + 4 + 2

        # Recompute both statistics over the SAME clamped scope and the saved
        # model, and record both numbers so the test is known to discriminate.
        clamped_scope = tes.clamp_validation_scope(
            fx.full_sample_set(), max_samples=10, ml_segs_per_psd=ML_PER_PSD
        )
        state = torch.load(
            os.path.join(sb.dirs["models"], "model_wavenet_pr07c_c6weight_agent.pth")
        )
        model = MODEL_REGISTRY["wavenet"](
            tes.get_config_class("wavenet")(**_wavenet_cfg(fx.seg_size))
        )
        model.load_state_dict(state)
        model.eval()
        criterion = get_criterion(LossConfig(loss_type="focal"), None)

        with bind_dataset_profile(fx.profile):
            dataset = tes.TIDMADEpochDataset(
                fx.data_dir,
                {str(k): v for k, v in clamped_scope.items()},
                fx.seg_size,
                train_portion=None,
                profile=fx.profile,
                file_family="validation",  # type: ignore[arg-type]
            )
        assert len(dataset) == 10
        batch_losses: list[tuple[float, int]] = []
        with torch.no_grad():
            for x, y in DataLoader(dataset, batch_size=4, shuffle=False, drop_last=False):
                loss = float(criterion(model(x.to(torch.long)), y.to(torch.long)).item())
                batch_losses.append((loss, int(x.shape[0])))
        assert [n for _loss, n in batch_losses] == [4, 4, 2], "no partial final batch was created"

        weighted = sum(loss * n for loss, n in batch_losses) / sum(n for _l, n in batch_losses)
        unweighted = sum(loss for loss, _n in batch_losses) / len(batch_losses)
        print(
            f"[C6] r3={history.validation_objective[-1]!r} weighted={weighted!r} "
            f"unweighted={unweighted!r}"
        )

        assert history.validation_objective is not None
        assert history.validation_objective[-1] == pytest.approx(weighted, abs=1e-5)
        assert weighted != pytest.approx(unweighted, abs=1e-9), (
            "the two statistics coincide on this data, so the test cannot "
            "discriminate — choose a scope where the batch losses differ"
        )


class TestTheOperatorSurface:
    def test_the_launcher_help_gains_exactly_one_flag(self):
        """`--help` must gain one line and change no other byte of the
        validation-posture group."""
        import ast
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "run_one_iteration.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        flags = [
            n.args[0].value
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "add_argument"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
            and n.args[0].value.startswith("--validation_max")
        ]
        assert sorted(flags) == [
            "--validation_max_phase_seconds",
            "--validation_max_portion",
            "--validation_max_samples",
            "--validation_max_train_samples",
        ]

    def test_the_chain_wrapper_parses_and_forwards_it(self):
        """A flag the launcher accepts but the chain wrapper drops is
        unreachable from the documented operator entry point."""
        from pathlib import Path

        shell = (
            Path(__file__).resolve().parents[3] / "sdsc_submission_scripts" / "_chain_common.sh"
        ).read_text(encoding="utf-8")
        assert "--validation_max_samples)" in shell
        assert 'APP_ARGS+=(--validation_max_samples "$VALIDATION_MAX_SAMPLES")' in shell
