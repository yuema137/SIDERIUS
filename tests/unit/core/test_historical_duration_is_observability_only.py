"""Historical duration calibration must not influence the time verdict.

V20 PR C1 — operator decision, 2026-08-02.

THE DECISION AND ITS REASON. Runtime and GPU conditions are live. The
production time decision must come from the current measured speed of the
concrete candidate on the current machine under current conditions. A stored
duration describes a different moment, and a subsystem that lets it decide is
pricing today's work with yesterday's clock.

So historical duration remains fully COLLECTED, identity-checked,
quarantined, promoted and reported -- and is barred from execution decisions.
Observability, not authority.

WHAT THIS FILE DOES AND DOES NOT COVER. These guards are about the **v2
`CalibrationObservation` registry**, the system PR C builds. They do not claim
that no historical number anywhere can reach a time estimate, because that is
not true today: a pre-existing legacy v1 mechanism writes an asymmetric-EMA
per-GPU correction (`evaluate_time_skill/calibration.py::update_k`) and
`training_skill/estimator.py:282-283` multiplies the estimate by it. That
mechanism predates PR C and is out of C1's scope -- filed as FU-C-10. Asserting
the broader claim here would make this file lie about its own reach.

WHY THESE ARE NEGATIVE TESTS. This file asserts an ABSENCE, which is the
hardest thing to keep true: nothing fails when someone adds the input back,
unless a test is watching for it. C-C5b wiring was implemented and committed
before this decision (95c4539) and then removed; these guards are what stop
it returning by accident.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import agent.skills.evaluate_time_skill.wrapper as time_wrapper

WRAPPER_SOURCE = Path(time_wrapper.__file__).read_text()
WRAPPER_TREE = ast.parse(WRAPPER_SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(WRAPPER_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in the time wrapper")


def _calls_within(node: ast.AST) -> set[str]:
    return {
        getattr(c.func, "id", getattr(c.func, "attr", None))
        for c in ast.walk(node)
        if isinstance(c, ast.Call)
    }


# ── historical evidence fixtures ───────────────────────────────────────
# Real promoted calibration, so the invariance assertion below is made
# against a registry that genuinely holds authority rather than an empty one.


def _calibration_record(registry, *, ms: float):
    from core.runtime_control.calibration_context import (
        CalibrationContextInputs,
        build_calibration_context,
        candidate_config_hash,
    )
    from core.runtime_control.calibration_policy import stack_identity
    from core.runtime_control.provenance import capture_software_stack
    from core.runtime_control.registry_schemas import (
        CalibrationObservation,
        MeasurementIdentity,
    )

    inputs = CalibrationContextInputs(
        precision="float32",
        optimizer_type="adamw",
        model_family="wavenet",
        param_count=156_320,
        seg_size=40_000,
        batch_size=8,
    )
    observation = CalibrationObservation(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=ms,
        workload={"batch_size": 8, "seg_size": 40_000, "param_count": 156_320},
        realized_model={"parameter_count": 156_320},
        hardware_compatibility_id="sha256:" + "a" * 64,
        execution_environment_id="sha256:" + "b" * 64,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="derived_runtime_observation@1.0.0",
        provenance="real_training_verification",
        validation_status="unvalidated",
        timestamp_metadata="2026-08-02T12:00:00Z",
        identity=MeasurementIdentity(
            measurement_kind="duration",
            task_identity="tidmad_denoising",
            data_shape_class="tidmad_int8_1d",
            model_family="wavenet",
            candidate_config_hash=candidate_config_hash(build_calibration_context(inputs)),
            phase="training",
            hardware_uuid="GPU-1111",
            runtime_stack_identity=stack_identity(capture_software_stack()),
        ),
    )
    registry.record_observation(observation)
    return observation


def _bucket_key(observation) -> str:
    from core.runtime_control.calibration_policy import bucket_key

    return bucket_key(observation)


def _promote(registry, observations) -> None:
    from core.runtime_control.calibration_policy import evaluate_promotions

    for promotion in evaluate_promotions(
        observations, generation=registry.load_manifest().generation
    ):
        registry.record_promotion(promotion)


class TestTheTimeGateTakesNoHistoricalInput:
    def test_gate_decision_has_no_historical_parameter(self):
        params = set(inspect.signature(time_wrapper._gate_decision).parameters)
        forbidden = {p for p in params if "historical" in p or "calibration" in p}
        assert not forbidden, (
            f"_gate_decision accepts {forbidden}; historical duration must not "
            "reach the production time verdict"
        )

    def test_the_gate_body_never_mentions_historical_calibration(self):
        code = ast.unparse(_function("_gate_decision"))
        assert "historical" not in code.lower(), (
            "the time gate references historical calibration; the verdict must "
            "come from the current live measurement alone"
        )


class TestTheProductionWrapperDoesNotLookUpHistory:
    def test_run_skill_calls_no_historical_lookup(self):
        called = _calls_within(_function("run_skill"))
        forbidden = {
            "lookup_applicable_duration",
            "_prelaunch_calibration",
            "as_estimate",
            "collect_calibration_state",
        }
        assert not (called & forbidden), (
            f"run_skill consults historical calibration via {called & forbidden}"
        )

    def test_the_wrapper_imports_no_calibration_read_path(self):
        imported = set()
        for node in ast.walk(WRAPPER_TREE):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        forbidden = {
            "core.runtime_control.calibration_prelaunch",
            "core.runtime_control.calibration_read",
            "core.runtime_control.calibration_registry",
        }
        assert not (imported & forbidden), (
            f"the time wrapper imports {imported & forbidden}; historical "
            "duration must stay out of the production time decision"
        )

    def test_the_removed_lookup_module_is_gone(self):
        """C-C5b's lookup boundary existed only to feed the production
        verdict. Leaving it importable would invite exactly the wiring the
        operator cancelled."""
        import importlib.util

        assert importlib.util.find_spec("core.runtime_control.calibration_prelaunch") is None


class TestRegistryContentsCannotChangeTheVerdict:
    """The behavioural counterpart to the structural guards above: for the
    same live measurement, the verdict is identical no matter what the
    historical registry contains -- including containing nothing at all."""

    @staticmethod
    def _verdict(budget_minutes: float, estimated_minutes: float) -> dict:
        """A MEASURED live projection -- the only input the verdict may use."""
        return time_wrapper._gate_decision(
            result_shape={
                "status": "success",
                "estimated_minutes": estimated_minutes,
                "breakdown": {"source": "real_dataset_warmup"},
                "phase_breakdown": {
                    "training": {"seconds": estimated_minutes * 60.0 * 0.8},
                    "inference": {"seconds": estimated_minutes * 60.0 * 0.2},
                },
                "inference_batch_uncalibrated": False,
            },
            effective_budget_minutes=budget_minutes,
            runtime_phase="trial",
            probe_record_available=True,
        )

    def test_the_verdict_is_a_function_of_the_live_measurement_only(self):
        """Populate the registry PRODUCTION WOULD READ -- the default root,
        pinned to a temporary tree by the session isolation fixture -- with
        promoted, validated evidence whose stored duration contradicts the
        live projection. The verdict must not move.

        Writing to an unrelated `tmp_path` would prove nothing: production
        never resolves there, so the assertion would hold even if the gate
        did consult history.
        """
        from core.runtime_control.calibration_registry import CalibrationRegistry

        before = self._verdict(20.0, 5.0)

        registry = CalibrationRegistry()
        observations = [_calibration_record(registry, ms=ms) for ms in (900.0, 910.0, 920.0)]
        _promote(registry, observations)
        assert any(
            registry.bucket_status(k)[0] == "validated"
            for k in {_bucket_key(o) for o in observations}
        ), "the fixture failed to create validated evidence; the test would prove nothing"

        after = self._verdict(20.0, 5.0)

        assert before["kind"] == after["kind"]
        assert before["evidence_provenance"] == after["evidence_provenance"]
        assert before["reasons"] == after["reasons"]

    def test_the_verdict_still_responds_to_the_live_measurement(self):
        """The positive control: the guards above would also pass if the gate
        ignored everything. A slower live measurement must still change the
        outcome, or the time gate is not deciding anything."""
        fast = self._verdict(20.0, 1.0)
        slow = self._verdict(20.0, 10_000.0)
        assert fast["kind"] != slow["kind"], (
            "the time gate returned the same verdict for a 1-minute and a "
            "10000-minute projection; it is not reading the live measurement"
        )


class TestHistoricalDurationCannotReachGpuAdmission:
    def test_gpu_admission_imports_no_calibration_module(self):
        import core.runtime_control.admission as admission

        tree = ast.parse(Path(admission.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        assert not {m for m in imported if "calibration" in m}, (
            "GPU admission imports a calibration module; duration is "
            "milliseconds and says nothing about memory"
        )

    def test_gpu_admission_exposes_no_duration_parameter(self):
        from core.runtime_control.admission import evaluate_gpu_admission

        params = set(inspect.signature(evaluate_gpu_admission).parameters)
        for banned in ("calibration", "duration", "historical"):
            assert not any(banned in p for p in params), (
                f"evaluate_gpu_admission exposes a {banned!r}-shaped parameter"
            )
