"""The watchdog deadline prices the validation pass (Step 07 / PR 07c C5).

07a's Gate 2 killed 3 of 4 real training attempts INSIDE the per-epoch R3
pass, and the survivor spent 9 s training against 26.45 s validating under a
deadline built from the 9 s alone. That is not estimator noise — a TERM was
missing:

    T_deadline = T̂_train + T̂_val + overhead + margin

Left unfixed it is a BIAS rather than lost attempts: validation cost grows with
model size, so large candidates die in validation while small ones survive and
the tuner learns a false regularity from an accounting gap.

The fix is a `RuntimePhase = "validation"` component carrying a
measurement-backed prediction, which the existing provider then sums with no
arithmetic change. So the tests that matter are about the SEQUENCE and the
CLOCK, not about a bigger number: a term that arrives late, or is expressed
against the wrong clock origin, leaves the process dead and the suite green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runtime_control.phases import RUNTIME_PHASES, RuntimePhase
from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES
from core.sandbox_executor import _watchdog_deadline_provider

#: The 07a Gate-2 regime, from the parent design's §8.4 ADDED-SCOPE clause.
TRAIN_ACTUAL_S = 9.0
VALIDATION_ACTUAL_S = 26.45
OBSERVED_WALL_S = TRAIN_ACTUAL_S + VALIDATION_ACTUAL_S  # 35.45

#: `_run`'s default eval set, as a sentinel so `None` stays meaningful:
#: `None` is the no-validation control, not "use the default".
_DEFAULT_EVAL = object()


def _component(predicted_seconds: float, *, source: str, eligible: bool = True) -> dict:
    """One phase component carrying a complete, valid prediction.

    Every field is populated because the sidecar is VALIDATED on read; a
    partial prediction makes the whole document malformed and the reader
    returns `None`, which would turn every deadline assertion below into a
    comparison against nothing.
    """
    return {
        "prediction": {
            "predicted_seconds": predicted_seconds,
            "source": source,
            "formal_execution_eligible": eligible,
            "steady_state": True,
            "verification": "passed",
            "confidence": "high",
            "safety_factor": 1.0,
            # The schema refuses `formal_execution_eligible=True` without
            # measurement provenance, which is the admission invariant doing
            # its job — so the fixture carries a real rate and unit count
            # rather than being weakened to dodge it.
            "ms_per_unit": predicted_seconds * 1000.0 / 100,
            "n_steady_units": 100,
            "unit_count": 100,
        }
    }


def _write_sidecar(path: Path, components: dict[str, dict]) -> str:
    """A sidecar exactly as the subprocess writes it.

    Routed through `RuntimeObservation` on purpose: the provider reads via
    `_read_runtime_observation_sidecar`, which VALIDATES the document and
    treats anything malformed as absent. A hand-rolled JSON blob would be
    silently discarded and every deadline assertion here would compare
    `None` — the test would be measuring the reader's fail-open path, not the
    deadline.
    """
    from core.runtime_control.records import RuntimeObservation

    payload = {"timestamp": "2026-08-17T00:00:00+0000", "components": components}
    path.write_text(RuntimeObservation.model_validate(payload).model_dump_json(), encoding="utf-8")
    return str(path)


class _Watchdog:
    def __init__(self, *, max_phase_seconds=None, floor_seconds=0.0, safety_factor=None):
        self.max_phase_seconds = max_phase_seconds
        self.floor_seconds = floor_seconds
        self.safety_factor = safety_factor


class _Policy:
    def __init__(self, *, operator_budget_seconds=None, safety_factor=1.0, **watchdog):
        self.operator_budget_seconds = operator_budget_seconds
        self.safety_factor = safety_factor
        self.watchdog = _Watchdog(**watchdog)


class TestTheVocabularyExtendsWithoutMovingAnything:
    def test_validation_is_a_phase(self):
        assert "validation" in RUNTIME_PHASES

    def test_no_existing_phase_moved_or_was_dropped(self):
        """A NEW namespace, not a redefinition. `calibration_key` embeds
        `f"phase={phase}"`, so an existing member changing name or meaning
        would silently rewrite the values under keys already in the store."""
        assert set(RUNTIME_PHASES) - {"validation"} == {
            "setup",
            "training",
            "inference",
            "scoring",
            "orchestration",
        }

    def test_the_validation_key_is_a_new_namespace_and_the_others_are_untouched(self):
        """Asserted against hardcoded key strings, not against a recomputation
        of the implementation."""
        from core.runtime_control.observation_store import calibration_key

        factors = dict(
            gpu_name="NVIDIA X",
            torch_version="2.10.0",
            precision="float32",
            optimizer_type="adamw",
            model_family="wavenet",
            param_count=1024,
            seg_size=40_000,
            batch_size=1,
        )
        captured = {
            phase: calibration_key(phase, **factors)
            for phase in ("setup", "training", "inference", "scoring", "orchestration")
        }
        for phase, key in captured.items():
            assert key.startswith(f"phase={phase}|")
        validation_key = calibration_key("validation", **factors)
        assert validation_key.startswith("phase=validation|")
        assert validation_key not in captured.values()
        # Everything AFTER the phase segment is byte-identical, so the new
        # phase differs from the others in exactly one factor.
        assert {k.split("|", 1)[1] for k in [*captured.values(), validation_key]} == {
            validation_key.split("|", 1)[1]
        }

    def test_the_validation_source_is_measurement_backed(self):
        """C8d forbids a non-measurement-backed prediction from setting a kill
        deadline, so a validation prediction that is not in this set is INERT
        and the whole commit would be cosmetic."""
        assert "real_validation_verification" in MEASUREMENT_BACKED_SOURCES

    def test_the_phase_literal_and_the_tuple_agree(self):
        """Two declarations of one vocabulary; a member added to only one is a
        latent type/runtime disagreement."""
        import typing

        assert set(typing.get_args(RuntimePhase)) == set(RUNTIME_PHASES)


class TestTheProviderReadsAProductionSHAPEDSidecar:
    """The Unit half of the producer→provider join.

    Under the frozen ownership model this pair is split:

        Unit    given a valid production-SHAPED sidecar, the provider parses
                and uses it correctly                          <- a contract
        Gate 2  the real runtime actually produces that sidecar at the
                required lifecycle moment                      <- timing

    Only the first is here. The second is Gate 2's and must not be pushed
    back into Unit — that is the 07c defect.

    The gap this closes: every other test in this file builds its sidecar with
    `_write_sidecar`, whose payload carries **two** top-level keys. A real
    subprocess writes **sixteen** (`admission`, `calibration_context`,
    `hardware`, `historical_prior`, `runtime_policy`, `software`, `storage`,
    `total`, `watchdog_status`, …). So the provider has only ever been proven
    against a strict subset of the document it actually reads in production,
    and a reader that tripped over a populated sibling key would pass every
    existing case.
    """

    def test_a_full_document_still_yields_the_deadline(self, tmp_path):
        """Every top-level field production can emit is present and populated
        with a schema-valid value; the provider must still find `components`
        and compute from them, not fail open to `None`."""
        from core.runtime_control.records import RuntimeObservation

        payload = {
            "timestamp": "2026-08-17T00:00:00+0000",
            "components": {
                "training": _component(9.0, source="real_training_verification"),
                "validation": _component(26.45, source="real_validation_verification"),
            },
            "attempt_id": "attempt-0001",
            "chain_id": "chain-0001",
            "schema_version": 1,
            "final_status": "success",
            "calibration_eligible": True,
        }
        # Anti-vacuity: the point is the FULL document, so fail loudly if the
        # schema grows a field this fixture does not exercise.
        unexercised = set(RuntimeObservation.model_fields) - set(payload)
        assert unexercised == {
            "admission",
            "calibration_context",
            "hardware",
            "historical_prior",
            "prior_agreement",
            "runtime_policy",
            "software",
            "storage",
            "total",
            "watchdog_status",
        }, (
            "RuntimeObservation's top-level shape changed; extend this fixture "
            f"rather than letting the provider go unproven against it: {unexercised}"
        )

        path = tmp_path / "rv.json"
        path.write_text(
            RuntimeObservation.model_validate(payload).model_dump_json(), encoding="utf-8"
        )
        deadline, source = _watchdog_deadline_provider(_Policy(safety_factor=2.0), str(path))()
        assert source == "verified_components", (
            "the provider fell open on a full production document — it has only "
            "ever been proven against the two-key subset this file writes"
        )
        assert deadline == pytest.approx((9.0 + 26.45) * 2.0)


class TestDeadlineParityWhenNoValidationEvidenceExists:
    """The regression half. Every run that produces no validation component —
    validation disabled, R3 absent, an older subprocess — must see the deadline
    it saw before 07c, for every candidate combination."""

    @pytest.mark.parametrize(
        "policy_kwargs,expected",
        [
            # verified_components alone: sum x factor, floored.
            ({"safety_factor": 2.0}, 18.0),
            # operator_budget tightens.
            ({"safety_factor": 2.0, "operator_budget_seconds": 12.0}, 12.0),
            # validation_max_phase tightens.
            ({"safety_factor": 2.0, "max_phase_seconds": 7.5}, 7.5),
            # the floor raises whatever min() chose.
            ({"safety_factor": 2.0, "operator_budget_seconds": 1.0, "floor_seconds": 5.0}, 5.0),
            # the watchdog factor overrides the shared one.
            ({"safety_factor": 2.0, "safety_factor_override": None}, 18.0),
        ],
    )
    def test_the_deadline_is_the_recorded_baseline(self, tmp_path, policy_kwargs, expected):
        policy_kwargs = dict(policy_kwargs)
        policy_kwargs.pop("safety_factor_override", None)
        sidecar = _write_sidecar(
            tmp_path / "rv.json",
            {"training": _component(TRAIN_ACTUAL_S, source="real_training_verification")},
        )
        deadline, _source = _watchdog_deadline_provider(_Policy(**policy_kwargs), sidecar)()
        assert deadline == pytest.approx(expected)

    def test_min_precedence_is_unchanged(self, tmp_path):
        sidecar = _write_sidecar(
            tmp_path / "rv.json",
            {"training": _component(TRAIN_ACTUAL_S, source="real_training_verification")},
        )
        _d, source = _watchdog_deadline_provider(
            _Policy(safety_factor=2.0, operator_budget_seconds=1.0), sidecar
        )()
        assert source == "operator_budget"

    def test_a_non_measurement_backed_validation_prediction_is_ignored(self, tmp_path):
        """C8d. A static prior must never set a kill deadline — which is
        exactly why Q-07c-5 measures the first real batch instead."""
        sidecar = _write_sidecar(
            tmp_path / "rv.json",
            {
                "training": _component(TRAIN_ACTUAL_S, source="real_training_verification"),
                "validation": _component(
                    VALIDATION_ACTUAL_S,
                    source="historical_observation_prior",
                    # The schema itself refuses an eligible prior — the same
                    # admission invariant C8d enforces at the deadline.
                    eligible=False,
                ),
            },
        )
        deadline, source = _watchdog_deadline_provider(_Policy(safety_factor=1.0), sidecar)()
        assert deadline == pytest.approx(TRAIN_ACTUAL_S)
        assert source == "verified_components"


class TestIncompleteEvidenceCannotTightenAnOperatorBudget:
    """Regression for #388's external composed-task failure."""

    def test_setup_only_evidence_retains_the_formal_operator_budget(self, tmp_path):
        sidecar = _write_sidecar(
            tmp_path / "setup_only.json",
            {
                "setup": _component(1.264, source="real_dataset_setup"),
                "training": {"prediction": None},
                "validation": {"prediction": None},
            },
        )
        deadline, source = _watchdog_deadline_provider(
            _Policy(
                operator_budget_seconds=1200.0,
                safety_factor=3.5,
                floor_seconds=120.0,
            ),
            sidecar,
        )()
        assert deadline == pytest.approx(1200.0)
        assert source == "operator_budget"

    def test_training_only_evidence_waits_for_declared_validation(self, tmp_path):
        sidecar = _write_sidecar(
            tmp_path / "validation_pending.json",
            {
                "setup": _component(1.264, source="real_dataset_setup"),
                "training": _component(92.0, source="real_training_verification"),
                "validation": {
                    "workload": {
                        "phase": "validation",
                        "unit": "validation_batch",
                        "unit_count": 2,
                    },
                    "prediction": None,
                },
            },
        )
        deadline, source = _watchdog_deadline_provider(
            _Policy(operator_budget_seconds=1200.0, safety_factor=3.5), sidecar
        )()
        assert deadline == pytest.approx(1200.0)
        assert source == "operator_budget"

    def test_static_training_prediction_cannot_complete_setup_evidence(self, tmp_path):
        sidecar = _write_sidecar(
            tmp_path / "static_training.json",
            {
                "setup": _component(1.0, source="real_dataset_setup"),
                "training": _component(
                    10.0,
                    source="historical_observation_prior",
                    eligible=False,
                ),
            },
        )
        deadline, source = _watchdog_deadline_provider(
            _Policy(operator_budget_seconds=600.0, safety_factor=3.5), sidecar
        )()
        assert deadline == pytest.approx(600.0)
        assert source == "operator_budget"

    def test_inference_ignores_other_complete_phase_evidence(self, tmp_path):
        sidecar = _write_sidecar(
            tmp_path / "inference_pending.json",
            {
                "setup": _component(1.0, source="real_dataset_setup"),
                "training": _component(10.0, source="real_training_verification"),
                "inference": {"prediction": None},
            },
        )
        deadline, source = _watchdog_deadline_provider(
            _Policy(operator_budget_seconds=600.0, safety_factor=3.5),
            sidecar,
            phase="inference",
        )()
        assert deadline == pytest.approx(600.0)
        assert source == "operator_budget"


class TestTheDeadlineGrowsByTheValidationTermAndNothingElse:
    def test_the_number_is_exact(self, tmp_path):
        """Hardcoded, not recomputed from the implementation — a test that
        recomputes agrees with any arithmetic the code happens to do."""
        sidecar = _write_sidecar(
            tmp_path / "rv.json",
            {
                "training": _component(10.0, source="real_training_verification"),
                "validation": _component(30.0, source="real_validation_verification"),
            },
        )
        deadline, source = _watchdog_deadline_provider(_Policy(safety_factor=1.5), sidecar)()
        assert deadline == pytest.approx(60.0)  # (10 + 30) x 1.5
        assert source == "verified_components"

    def test_the_07a_regime_survives_the_fix_and_would_not_have_before(self, tmp_path):
        """THE HEADLINE ASSERTION.

        Replays the measured 07a Gate-2 numbers. The pre-07c provider — the
        same real function, over a sidecar with no validation component —
        yields a deadline BELOW the observed 35.45 s wall time, so it would
        have killed the attempt. With the validation component it does not.
        """
        factor = 1.2
        without = _write_sidecar(
            tmp_path / "old.json",
            {"training": _component(TRAIN_ACTUAL_S, source="real_training_verification")},
        )
        with_validation = _write_sidecar(
            tmp_path / "new.json",
            {
                "training": _component(TRAIN_ACTUAL_S, source="real_training_verification"),
                "validation": _component(
                    VALIDATION_ACTUAL_S, source="real_validation_verification"
                ),
            },
        )
        d_old, _ = _watchdog_deadline_provider(_Policy(safety_factor=factor), without)()
        d_new, source = _watchdog_deadline_provider(
            _Policy(safety_factor=factor), with_validation
        )()

        assert d_old is not None and d_new is not None
        assert d_old < OBSERVED_WALL_S, (
            f"the pre-07c deadline {d_old:.2f}s would NOT have killed the 07a "
            "attempt, so this replay proves nothing"
        )
        assert OBSERVED_WALL_S <= d_new
        assert source == "verified_components"

    def test_zero_validation_samples_produce_no_term_rather_than_a_nan(self, tmp_path):
        """`0/0` in a rate would poison the deadline with `nan`, and
        `nan <= deadline` is False — the watchdog would kill every attempt
        instantly."""
        sidecar = _write_sidecar(
            tmp_path / "rv.json",
            {
                "training": _component(TRAIN_ACTUAL_S, source="real_training_verification"),
                "validation": {
                    "workload": {
                        "phase": "validation",
                        "unit": "validation_batch",
                        "unit_count": 0,
                    },
                    "prediction": None,
                },
            },
        )
        deadline, _ = _watchdog_deadline_provider(_Policy(safety_factor=1.0), sidecar)()
        assert deadline == pytest.approx(TRAIN_ACTUAL_S)


class TestColdStartTemporalUpdate:
    """rev-2 blocker 2 — the invariant a "the term eventually appears" test
    misses entirely.

    If the validation term arrives after the stale training-only deadline
    fires, the process is already dead and the suite is still green. So the
    provider is driven across the REAL sequence, against a sidecar that changes
    underneath it exactly as the subprocess rewrites it.
    """

    @staticmethod
    def _sequence(tmp_path):
        """Returns (provider, sidecar_path, factor)."""
        factor = 1.2
        path = tmp_path / "rv.json"
        _write_sidecar(
            path, {"training": _component(TRAIN_ACTUAL_S, source="real_training_verification")}
        )
        return _watchdog_deadline_provider(_Policy(safety_factor=factor), str(path)), path, factor

    def test_at_t0_the_provider_sees_the_old_training_only_deadline(self, tmp_path):
        provider, _path, factor = self._sequence(tmp_path)
        deadline, source = provider()
        assert deadline == pytest.approx(TRAIN_ACTUAL_S * factor)
        assert source == "verified_components"

    def test_the_refreshed_deadline_arrives_strictly_before_the_old_one_fires(self, tmp_path):
        """DEFECT 3 — "correct but too late".

        The watchdog compares total elapsed against the deadline, so the
        question is whether the refreshed value is in the sidecar at an elapsed
        time below the OLD deadline. The first validation batch lands at
        `T_train + one batch`; with the 07a regime's 15 000 rows that batch is
        a small fraction of the 26.45 s pass, and the old deadline is
        9 x 1.2 = 10.8 s.
        """
        provider, path, factor = self._sequence(tmp_path)
        old_deadline, _ = provider()

        # WHEN the prediction lands is NOT asserted here, and deliberately so.
        # This test used to model it — `VALIDATION_ACTUAL_S * (500 / 15_000)`
        # added to `TRAIN_ACTUAL_S`, compared against the stale deadline. That
        # is arithmetic over three constants the test itself chose; production
        # could defer the write arbitrarily and it would not move. It was the
        # original 07c defect one level up, inside the test written to catch it.
        #
        # Arrival time is owned, at the production boundary, by
        # `tests/unit/execute_tools/test_pr07c_validation_persistence_timing.py::
        # TestValidationPredictionArrivesDuringThePass` — a real streaming run
        # whose model reads the live sidecar from disk DURING validation and
        # asserts the measurement-backed prediction appeared before the pass
        # finished. Deadline-vs-real-elapsed is Gate 2's.
        #
        # What remains here is the arithmetic that is genuinely local: given
        # the refreshed component, the provider recomputes a TOTAL that clears
        # the observed wall.

        _write_sidecar(
            path,
            {
                "training": _component(TRAIN_ACTUAL_S, source="real_training_verification"),
                "validation": _component(
                    VALIDATION_ACTUAL_S, source="real_validation_verification"
                ),
            },
        )
        refreshed, source = provider()
        assert refreshed == pytest.approx((TRAIN_ACTUAL_S + VALIDATION_ACTUAL_S) * factor)
        assert source == "verified_components"
        assert refreshed > old_deadline
        # And the run it was killing now survives.
        assert OBSERVED_WALL_S <= refreshed

    def test_the_refreshed_deadline_is_a_total_not_a_remainder(self, tmp_path):
        """DEFECT 1 — an elapsed-vs-remaining mix-up.

        The enforcement site compares `time.perf_counter() - t_start` (the
        subprocess launch) against the deadline, so the value must be the WHOLE
        allowed wall time. Expressed as a remainder it would be
        `total - already_elapsed`, which for this regime is
        (9+26.45)x1.2 - 9 = 33.54s — close enough to look plausible and wrong
        enough to kill the attempt.
        """
        provider, path, factor = self._sequence(tmp_path)
        _write_sidecar(
            path,
            {
                "training": _component(TRAIN_ACTUAL_S, source="real_training_verification"),
                "validation": _component(
                    VALIDATION_ACTUAL_S, source="real_validation_verification"
                ),
            },
        )
        deadline, _ = provider()
        total = (TRAIN_ACTUAL_S + VALIDATION_ACTUAL_S) * factor
        assert deadline == pytest.approx(total)
        assert deadline != pytest.approx(total - TRAIN_ACTUAL_S)

    def test_the_source_convention_is_documented_at_the_provider(self):
        """The convention was implicit, and an implicit convention is how
        defect 1 happens. It is now stated in the provider's own docstring."""
        import inspect

        doc = inspect.getdoc(_watchdog_deadline_provider) or ""
        assert "TOTAL ELAPSED SINCE SUBPROCESS START" in doc


class TestAdmissionIsUnchangedByConstruction:
    """Q-07c-6 = B. A changed admission verdict is a DEFECT of this commit, not
    an improvement, so the parity is asserted rather than assumed."""

    def test_no_admission_decision_can_follow_a_validation_prediction(self):
        """The structural argument, checked against source.

        `decide_admission` is reachable from the trainer only through
        `_finish_training_verification`, which is guarded by
        `if verifier is not None` at BOTH call sites and sets `verifier = None`
        immediately afterwards. `verifier` is assigned exactly once, before the
        epoch loop. So at most one admission decision is taken per run, and it
        happens inside or at the end of epoch 0's batch loop — strictly before
        the first `_validation_pass`, which runs after that loop.

        Therefore no admission decision ever sees a validation prediction, and
        `known_cost` at every admission stage is what it was before 07c.
        """
        import ast

        source = (
            Path(__file__).resolve().parents[3] / "execute_tools" / "train_engine_sandbox.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)

        # 1. `decide_admission` is reachable from exactly two places, and
        #    neither statement mentions validation.
        admission_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "decide_admission"
        ]
        assert len(admission_calls) == 2, (
            f"the trainer now takes {len(admission_calls)} admission decisions; "
            "re-derive the ordering argument before trusting this test — a new "
            "call site could run after a validation prediction exists"
        )

        # 2. The training verifier is STARTED exactly once, which is what makes
        #    `_finish_training_verification` at-most-once and therefore places
        #    every admission decision inside epoch 0.
        training_starts = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "start_phase_verification"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "training"
        ]
        assert len(training_starts) == 1

        # 3. Every `_finish_training_verification` call is GUARDED by the
        #    verifier being live, and both call sites clear it — so the guard,
        #    not the loop structure, is what bounds it.
        finish_calls = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "_finish_training_verification"
        ]
        assert len(finish_calls) == 2, (
            "a new _finish_training_verification call site appeared; it may now "
            "run after a validation prediction exists, which would change the "
            "admission verdict"
        )
        guards = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "verifier" in ast.dump(n.test)
            and "_finish_training_verification" in ast.dump(n)
        ]
        assert len(guards) >= 1

    def test_the_validation_verification_never_decides_admission(self):
        """`complete_phase_verification` records evidence; only
        `decide_admission` judges. The validation completion must not be
        followed by an admission call in the same statement block."""
        import ast

        source = (
            Path(__file__).resolve().parents[3] / "execute_tools" / "train_engine_sandbox.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            body = ast.dump(node)
            if '"validation"' in body and "complete_phase_verification" in body:
                assert "decide_admission" not in body


def _wavenet_cfg(seg_size: int) -> dict:
    """The 07a rung's own config — reused rather than re-derived, so a
    validation-config difference can never be mistaken for a C5 defect."""
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
class TestTheRealTrainerEmitsAValidationComponent:
    """The reachability half, run for real (CPU, seconds).

    Every assertion above drives `_watchdog_deadline_provider` over a
    hand-written sidecar. That proves the deadline arithmetic and the clock
    convention, and proves nothing at all about whether the production trainer
    ever WRITES a validation component — the hop where 07a's evidence already
    existed and simply never reached `RuntimeSession`.

    So this runs the REAL `train_engine_sandbox.py` subprocess through the
    production `execute_training`, on a tiny CPU model over the committed
    two-family fixture, and reads the sidecar the executor itself reads.
    """

    @staticmethod
    def _run(
        tmp_path,
        monkeypatch,
        *,
        run_name: str,
        runtime_policy: dict,
        eval_sample_set: dict | None | object = _DEFAULT_EVAL,
    ):
        """One real `train_engine_sandbox.py` subprocess over the committed
        two-family fixture. Returns (result, fixture)."""
        import core.sandbox_executor as sandbox_module
        from core.sandbox_executor import TidmadSandbox
        from execute_tools.dataset_config import bind_dataset_profile
        from tests.helpers.two_family_profile import write_two_family_fixture

        (tmp_path / "data").mkdir(exist_ok=True)
        fx = write_two_family_fixture(tmp_path / "data")

        # The only test seam, inherited from the 07a rung: the child would
        # otherwise resolve the machine's TIDMAD directory.
        real_launch = sandbox_module._run_observed_subprocess

        def launch_with_data_dir(cmd, **kwargs):
            return real_launch([*cmd, "--data_dir", fx.data_dir], **kwargs)

        monkeypatch.setattr(sandbox_module, "_run_observed_subprocess", launch_with_data_dir)

        with bind_dataset_profile(fx.profile):
            sb = TidmadSandbox(
                run_name=run_name, workspace=str(tmp_path / "ws"), progress_bar=False
            )
            out = sb.execute_training(
                f"pr07c_{run_name}",
                run_name,
                "wavenet",
                _wavenet_cfg(fx.seg_size),
                {
                    "lr": 1e-3,
                    "epochs": 2,
                    "batch_size": 2,
                    "optimizer_type": "adam",
                    "device": "cpu",
                },
                {"loss_type": "focal"},
                sample_set={0: [0, 1, 2, 3], 1: [0, 1, 2, 3], 2: [0, 1, 2, 3]},
                eval_sample_set=(
                    {0: [0, 1], 2: [1, 3]} if eval_sample_set is _DEFAULT_EVAL else eval_sample_set
                ),
                train_base_seed=5,
                runtime_policy=runtime_policy,
            )
        assert out["status"] == "success", out.get("message")
        return out, fx

    def test_the_validation_evidence_reaches_the_runtime_session(self, tmp_path, monkeypatch):
        """The routing hop that did not exist. 07a already measured
        `validation_seconds` per epoch, but it landed in the trainer's results
        payload and nothing carried it into `RuntimeSession` — so the phase was
        invisible to the runtime model no matter how long it took.

        Run under the PRODUCTION verification policy, unmodified.
        """
        out, _fx = self._run(tmp_path, monkeypatch, run_name="c5", runtime_policy={})
        observation = out.get("runtime_verification")
        assert observation is not None, "no runtime sidecar was produced"
        components = observation.get("components") or {}

        assert "validation" in components, (
            "the trainer produced R3 but recorded no validation component — "
            "07a's evidence still never reaches RuntimeSession, and the "
            "watchdog cannot price a phase it cannot see"
        )
        validation = components["validation"]

        # The ACTUAL — the half that calibrates FUTURE runs.
        assert validation.get("actual_seconds") is not None
        assert validation["actual_seconds"] > 0

        # The WORKLOAD covers the whole phase — every row of every epoch — so
        # a prediction built from it covers the validation still to come, not
        # just the batch that was measured.
        workload = validation.get("workload")
        assert workload is not None
        assert workload["unit"] == "validation_sample"
        assert workload["unit_count"] == 8 * 2  # 8 rows per pass x 2 epochs

        # The MEASUREMENT is recorded regardless of outcome (§6.2 event log).
        measurement = validation.get("measurement")
        assert measurement is not None
        assert measurement["unit"] == "validation_sample"
        assert measurement["n_measured_units"] > 0

    def test_a_pass_too_short_to_stabilise_yields_no_prediction(self, tmp_path, monkeypatch):
        """FAIL-CLOSED, and an honest limitation rather than a hidden one.

        This fixture's validation scope is 8 rows, far below the production
        stopping policy's `min_timed_ms=500` / `window=8 x stable_windows=4`.
        The verifier therefore ends `failed_no_steady_state`, and §2.11 gives
        no prediction — so the watchdog gets no validation term and the
        deadline is exactly what it was before 07c.

        That is CORRECT: a prediction extrapolated from eight noisy sub-
        millisecond samples would be worse than none, and C8d exists to keep
        such a thing out of a kill deadline. Pinned so the behaviour is a
        recorded decision rather than an accident of fixture size.
        """
        out, _fx = self._run(tmp_path, monkeypatch, run_name="c5short", runtime_policy={})
        validation = ((out.get("runtime_verification") or {}).get("components") or {})["validation"]
        assert validation["prediction"] is None
        assert validation["measurement"]["steady_state_reached"] is False
        assert "no steady state" in validation["measurement"]["detail"]["failure_reason"]
