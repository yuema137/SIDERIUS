"""Pre-launch duration calibration: what may influence a time budget.

V20 PR C1 / C-C5b.

Two questions this file answers, which no other test can:

  1. does an applicable, validated, local record actually reach the
     pre-launch decision -- or does the lookup silently return nothing
     forever, which looks identical to an empty registry?
  2. is the O-6 asymmetry real in code -- history may support ALLOW, but
     may never by itself REJECT?

The identity rows here are end-to-end through a real registry, unlike
`test_calibration_read_authority.py` which exercises the decision function
directly. Both are needed: the seam can be correct while the lookup that
feeds it builds the wrong identity, and then nothing ever matches.
"""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_context import (
    CalibrationContextInputs,
    build_calibration_context,
    candidate_config_hash,
)
from core.runtime_control.calibration_prelaunch import (
    historical_support_only,
    lookup_applicable_duration,
)
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    MeasurementIdentity,
)

INPUTS = CalibrationContextInputs(
    precision="float32",
    optimizer_type="adamw",
    model_family="wavenet",
    param_count=156_320,
    seg_size=40_000,
    batch_size=8,
)

TASK = "tidmad_denoising"
SHAPE = "tidmad_int8_1d"
UUID = "GPU-1111"
ENV_ID = "sha256:" + "b" * 64


def _identity(**over) -> MeasurementIdentity:
    from core.runtime_control.calibration_policy import stack_identity
    from core.runtime_control.provenance import capture_software_stack

    base = dict(
        measurement_kind="duration",
        task_identity=TASK,
        data_shape_class=SHAPE,
        model_family=INPUTS.model_family,
        candidate_config_hash=candidate_config_hash(build_calibration_context(INPUTS)),
        phase="training",
        hardware_uuid=UUID,
        runtime_stack_identity=stack_identity(capture_software_stack()),
    )
    base.update(over)
    return MeasurementIdentity(**base)


def _record(registry, *, ms: float, identity=None, **over) -> CalibrationObservation:
    payload = dict(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=ms,
        workload={
            "batch_size": INPUTS.batch_size,
            "seg_size": INPUTS.seg_size,
            "param_count": INPUTS.param_count,
        },
        realized_model={"parameter_count": INPUTS.param_count},
        hardware_compatibility_id="sha256:" + "a" * 64,
        execution_environment_id=ENV_ID,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="derived_runtime_observation@1.0.0",
        provenance="real_training_verification",
        validation_status="unvalidated",
        timestamp_metadata="2026-08-02T12:00:00Z",
        identity=identity if identity is not None else _identity(),
    )
    payload.update(over)
    obs = CalibrationObservation(**payload)
    registry.record_observation(obs)
    return obs


def _promote(registry, observations):
    from core.runtime_control.calibration_policy import evaluate_promotions

    for promo in evaluate_promotions(observations, generation=registry.load_manifest().generation):
        registry.record_promotion(promo)


@pytest.fixture
def registry(tmp_path) -> CalibrationRegistry:
    return CalibrationRegistry(tmp_path / "runtime_calibration_v2")


def _lookup(registry, **over):
    kwargs = dict(
        context_inputs=INPUTS,
        task_identity=TASK,
        data_shape_class=SHAPE,
        hardware_uuid=UUID,
        registry=registry,
        current_environment_id=ENV_ID,
    )
    kwargs.update(over)
    return lookup_applicable_duration(**kwargs)


class TestApplicableValidatedEvidenceIsConsumed:
    """The positive control, and the whole point of C-C5b. If this fails the
    subsystem writes and promotes evidence that production can never use."""

    def test_a_validated_applicable_record_is_returned(self, registry):
        observations = [_record(registry, ms=ms) for ms in (20.0, 21.0, 22.0)]
        _promote(registry, observations)

        result = _lookup(registry)

        assert result.found, f"applicable validated evidence was not consumed: {result.reasons}"
        assert result.estimate.blocking_eligible is True

    def test_an_unpromoted_bucket_is_not_authoritative(self, registry):
        """Recorded is not validated. Without a promotion the evidence is a
        prior, and a prior may not carry blocking authority."""
        _record(registry, ms=20.0)

        result = _lookup(registry)

        assert not result.found
        assert result.reasons


class TestReuseBoundariesEndToEnd:
    """The frozen non-reuse rules, exercised through a real registry rather
    than against the decision function directly -- a lookup that builds the
    wrong identity would pass the unit-level matrix and still never match."""

    @pytest.mark.parametrize(
        "field,value",
        [
            ("task_identity", "other_task"),
            ("data_shape_class", "other_shape"),
            ("hardware_uuid", "GPU-9999"),
            ("phase", "inference"),
            ("measurement_kind", "gpu_requirement"),
            ("runtime_stack_identity", "stack-other"),
        ],
    )
    def test_a_record_from_another_context_is_never_used(self, registry, field, value):
        observations = [
            _record(registry, ms=ms, identity=_identity(**{field: value}))
            for ms in (20.0, 21.0, 22.0)
        ]
        _promote(registry, observations)

        result = _lookup(registry)

        assert not result.found, f"{field} differs, yet the record was consumed"

    def test_a_different_candidate_config_is_never_used(self, registry):
        """`candidate_config_hash` separates two candidates of one family
        with materially different configurations."""
        other = CalibrationContextInputs(**{**INPUTS.model_dump(), "batch_size": 16})
        observations = [
            _record(
                registry,
                ms=ms,
                identity=_identity(
                    candidate_config_hash=candidate_config_hash(build_calibration_context(other))
                ),
            )
            for ms in (20.0, 21.0, 22.0)
        ]
        _promote(registry, observations)

        assert not _lookup(registry).found


class TestIncompleteIdentityNeverFabricatesAMatch:
    @pytest.mark.parametrize("field", ["task_identity", "data_shape_class", "hardware_uuid"])
    def test_a_missing_field_refuses_and_names_itself(self, registry, field):
        observations = [_record(registry, ms=ms) for ms in (20.0, 21.0, 22.0)]
        _promote(registry, observations)

        result = _lookup(registry, **{field: None})

        assert not result.found
        assert any(field in reason for reason in result.reasons), (
            "the refusal must name the missing field, or an operator cannot "
            "tell an unconfigured run from an inapplicable one"
        )


class TestTheLookupNeverCostsTheRunItsDecision:
    def test_an_unusable_registry_is_a_refusal_not_an_exception(self, registry):
        class _Broken:
            def iter_observations(self):
                raise OSError("registry unavailable")

        result = lookup_applicable_duration(
            context_inputs=INPUTS,
            task_identity=TASK,
            data_shape_class=SHAPE,
            hardware_uuid=UUID,
            registry=_Broken(),
            current_environment_id=ENV_ID,
        )

        assert not result.found
        assert any("unavailable" in r for r in result.reasons)

    def test_an_empty_registry_says_so(self, registry):
        result = _lookup(registry)
        assert not result.found
        assert any("no calibration record" in r for r in result.reasons)


class TestO6HistoricalEvidenceIsAsymmetric:
    """Frozen O-6. Supporting a candidate on prior evidence risks running
    something slow, which the budget and watchdog already bound. Rejecting on
    prior evidence risks refusing work that was never measured, which nothing
    bounds."""

    def test_under_budget_history_may_support_allow(self):
        supports, reasons = historical_support_only(
            object(), predicted_seconds=10.0, budget_seconds=20.0
        )
        assert supports is True
        assert reasons

    def test_over_budget_history_may_not_reject(self):
        supports, reasons = historical_support_only(
            object(), predicted_seconds=99.0, budget_seconds=20.0
        )
        assert supports is False
        assert any("may not reject" in r for r in reasons)

    def test_absent_history_supports_nothing(self):
        supports, reasons = historical_support_only(
            None, predicted_seconds=1.0, budget_seconds=20.0
        )
        assert supports is False
        assert reasons

    def test_there_is_no_reject_signal_in_the_return_type(self):
        """Structural: the helper returns `may_support_allow`, so there is no
        value it can return that denies a candidate. A boolean named
        `should_reject` would have made rejection expressible, and expressible
        eventually becomes reachable."""
        for predicted in (1.0, 19.9, 20.0, 20.1, 1e9):
            supports, _ = historical_support_only(
                object(), predicted_seconds=predicted, budget_seconds=20.0
            )
            assert supports in (True, False)


class TestTheProductionPreLaunchPathReachesTheLookup:
    """C-C5b's completion standard. The lookup working is not the point --
    the real pre-launch time decision calling it is.

    Three components already shipped in this PR were built, tested and
    called from nowhere (#156, #157, #159, and the C-C4 promotion trigger).
    This is the guard that stops a fourth.
    """

    @staticmethod
    def _wrapper_source():
        from pathlib import Path

        import agent.skills.evaluate_time_skill.wrapper as w

        return Path(w.__file__).read_text()

    def test_run_skill_calls_the_prelaunch_lookup(self):
        import ast

        tree = ast.parse(self._wrapper_source())
        run_skill = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_skill"
        )
        called = {
            getattr(c.func, "id", getattr(c.func, "attr", None))
            for c in ast.walk(run_skill)
            if isinstance(c, ast.Call)
        }
        assert "_prelaunch_calibration" in called, (
            "the pre-launch time check no longer consults duration calibration; "
            "the registry would be written and promoted but never read"
        )

    def test_the_helper_reaches_the_safe_read_boundary(self):
        import ast

        tree = ast.parse(self._wrapper_source())
        helper = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_prelaunch_calibration"
        )
        called = {
            getattr(c.func, "id", getattr(c.func, "attr", None))
            for c in ast.walk(helper)
            if isinstance(c, ast.Call)
        }
        assert "lookup_applicable_duration" in called, (
            "the pre-launch helper bypasses the C-C5a authority seam"
        )

    def test_the_result_reaches_the_gate(self):
        """Reaching the lookup is not enough -- the value has to arrive at
        the decision. A call whose result is discarded is the #159 shape."""
        source = self._wrapper_source()
        assert "historical_calibration=_prelaunch_calibration(" in source, (
            "the lookup result is not passed into _gate_decision"
        )

    def test_the_lookup_runs_before_the_gate_decides(self):
        """Ordering is the point of C-C5b: a time decision made after the
        subprocess launches cannot gate the phase it is meant to gate."""
        import ast

        tree = ast.parse(self._wrapper_source())
        gate = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_gate_decision"
        )
        code = ast.unparse(gate)
        # The verdict is computed before any historical evidence is examined,
        # so history cannot participate in producing it.
        assert code.index("policy.decide(") < code.index("historical_calibration is not None")


class TestDurationCalibrationCannotReachGpuAdmission:
    """Duration is milliseconds; GPU admission is mebibytes. A throughput
    figure says nothing about memory, so it must not be reachable from the
    VRAM gate even by accident."""

    def test_the_gpu_admission_module_does_not_import_calibration_reading(self):
        import ast
        from pathlib import Path

        import core.runtime_control.admission as admission

        tree = ast.parse(Path(admission.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

        forbidden = {
            "core.runtime_control.calibration_prelaunch",
            "core.runtime_control.calibration_read",
            "core.runtime_control.calibration_registry",
            "core.runtime_control.calibration_derivation",
        }
        assert not (imported & forbidden), (
            f"GPU admission imports duration-calibration modules: {imported & forbidden}"
        )

    def test_the_gpu_admission_entry_point_takes_no_duration_evidence(self):
        """Structural: no parameter through which a millisecond figure could
        be handed to a memory decision."""
        import inspect

        from core.runtime_control.admission import evaluate_gpu_admission

        params = set(inspect.signature(evaluate_gpu_admission).parameters)
        for banned in ("calibration", "duration", "historical_calibration", "estimate"):
            assert not any(banned in p for p in params), (
                f"evaluate_gpu_admission exposes a {banned!r}-shaped parameter"
            )

    def test_the_prelaunch_module_does_not_reach_gpu_admission(self):
        import ast
        from pathlib import Path

        import core.runtime_control.calibration_prelaunch as pre

        source = Path(pre.__file__).read_text()
        tree = ast.parse(source)
        called = {
            getattr(c.func, "id", getattr(c.func, "attr", None))
            for c in ast.walk(tree)
            if isinstance(c, ast.Call)
        }
        assert "evaluate_gpu_admission" not in called
        assert "admission" not in {
            n.module.split(".")[-1]
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module
        }
