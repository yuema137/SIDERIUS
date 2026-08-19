"""Step 08a C6 — roadmap §8.4 rungs B and C, as one executable pair.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.6,
§4.6; roadmap §8.4.

The two rungs are deliberately in ONE module and, for the decisive test,
in ONE gate evaluation, because separately they each prove half a claim
and the halves are what mislead:

* **8.4-B alone** — "the int8 family reports inapplicable on a
  declared-float output, and opens no file" — is equally satisfied by a
  framework that has quietly stopped checking anything.
* **8.4-C alone** — "a continuous check fires and can fail" — says
  nothing about whether inapplicability was honest.

Together they state the actual property: *inapplicability is a statement
about ONE family, never an exemption from health evaluation.*

The arithmetic vectors are hand-computed and asserted directly, so the
dispersion check has a numerical oracle independent of its own
implementation.
"""

from __future__ import annotations

import math

import pytest

from execute_tools.health_checks import runner
from execute_tools.health_checks._regime_a_facts import resolve_health_facts
from execute_tools.health_checks.amplitude_collapse import AmplitudeCollapseCheck
from execute_tools.health_checks.config import (
    ActionConfig,
    CheckRef,
    GateConfig,
    HealthChecksConfig,
)
from execute_tools.health_checks.output_diversity import OutputDiversityCheck
from execute_tools.health_checks.output_std import OutputStdCheck
from execute_tools.health_checks.pearson_dispersion import PearsonDispersionCheck
from execute_tools.health_checks.per_file_output_std import PerFileOutputStdCheck
from execute_tools.health_checks.registry import register
from execute_tools.health_checks.runner import evaluate_gate
from execute_tools.health_checks.sample_dispersion_floor import SampleDispersionFloorCheck
from execute_tools.health_checks.schemas import (
    CheckVerdict,
    GateAction,
    HealthCheckContext,
    TaskHealthFacts,
    applicability,
)
from execute_tools.health_checks.spectral_peak_ratio import SpectralPeakRatioCheck

INT8_FAMILY = (
    OutputDiversityCheck,
    OutputStdCheck,
    AmplitudeCollapseCheck,
    PerFileOutputStdCheck,
    SpectralPeakRatioCheck,
    PearsonDispersionCheck,
)

# A task that declares continuous float outputs — the 8.4-B fixture. No
# task-binding machinery is involved: 08a takes facts as an argument, and
# the binding that would supply them is 08b.
DECLARED_FLOAT_TASK = TaskHealthFacts(
    encoding_family="continuous_float",
    value_scale_unit="mV",
    file_group_size=3,
    sampling_frequency_hz=250.0,
)

# Hand-computed vectors. Constant series: mean 2.0, every deviation 0, so
# population std is exactly 0.0. Varied series: mean 3.0, deviations
# -3/-1/+1/+3, squares 9/1/1/9 summing to 20, /4 = 5, so std = sqrt(5).
CONSTANT_SERIES = [2.0, 2.0, 2.0, 2.0]
VARIED_SERIES = [0.0, 2.0, 4.0, 6.0]
VARIED_STD = math.sqrt(5.0)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


def _full_ctx() -> HealthCheckContext:
    return _ctx(
        denoised_filename_fn=lambda fi: f"/tmp/denoised_{fi:04d}.h5",
        target_path_fn=lambda fi: f"/tmp/target_{fi:04d}.h5",
    )


class TestDispersionArithmetic:
    """A numerical oracle for the new check, computed by hand, not by it."""

    def test_constant_series_has_zero_dispersion_and_fails_the_floor(self):
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"samples": CONSTANT_SERIES, "min_dispersion": 0.5}
        )
        assert result.metrics["dispersion"] == 0.0
        assert result.metrics["mean"] == 2.0
        assert result.passed is False
        assert result.verdict is CheckVerdict.FAILED

    def test_varied_series_dispersion_is_sqrt_five_and_passes(self):
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"samples": VARIED_SERIES, "min_dispersion": 0.5}
        )
        assert result.metrics["dispersion"] == pytest.approx(VARIED_STD)
        assert result.metrics["mean"] == 3.0
        assert result.passed is True
        assert result.verdict is CheckVerdict.PASSED

    def test_the_floor_is_what_decides(self):
        """Same data, two floors — so the threshold is load-bearing."""
        check = SampleDispersionFloorCheck()
        below = check.run(_ctx(), {"samples": VARIED_SERIES, "min_dispersion": VARIED_STD + 1})
        at = check.run(_ctx(), {"samples": VARIED_SERIES, "min_dispersion": VARIED_STD})
        assert below.passed is False
        assert at.passed is True  # the floor is inclusive

    @pytest.mark.parametrize("samples", [[], None], ids=["empty", "absent"])
    def test_no_samples_is_an_error_not_a_pass(self, samples):
        """A floor over nothing is the absence of evidence — fail closed."""
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"samples": samples, "min_dispersion": 0.5}
        )
        assert result.verdict is CheckVerdict.ERROR
        assert result.passed is False


class TestTheAxisCutsBothWays:
    def test_the_new_check_is_inapplicable_under_tidmad(self):
        """Otherwise it is not a contrast family, just another TIDMAD check."""
        verdict = applicability(
            SampleDispersionFloorCheck.declaration, resolve_health_facts(), _full_ctx()
        )
        assert verdict.applicable is False
        assert verdict.axis == "encoding_family"

    def test_the_new_check_applies_under_the_declared_float_task(self):
        verdict = applicability(
            SampleDispersionFloorCheck.declaration, DECLARED_FLOAT_TASK, _full_ctx()
        )
        assert verdict.applicable is True

    def test_it_is_registered_but_configured_nowhere_in_production(self):
        """Being registered is not being configured.

        The check must be reachable by name — that is what makes it a real
        registration rather than a test-only object — while never firing in
        a production run.
        """
        from execute_tools.health_checks.config import load_health_gates_config
        from execute_tools.health_checks.registry import get

        assert get("sample_dispersion_floor") is not None
        for config_path in (None, "configs/health_checks_baseline_observe_mode.yaml"):
            config = load_health_gates_config(config_path)
            configured = {ref.name for gate in config.health_gates for ref in gate.checks}
            assert "sample_dispersion_floor" not in configured, config_path


class TestRungsBAndCInOneGateEvaluation:
    """The decisive test: both rungs, one gate, one declared-float task."""

    @pytest.fixture
    def declared_float_gate(self, monkeypatch, clean_registry):
        import h5py

        def _boom(*args, **kwargs):
            raise AssertionError(
                "an inapplicable check opened an HDF5 file — applicability "
                "must be decided BEFORE artifact I/O (roadmap §8.4-B)"
            )

        monkeypatch.setattr(h5py, "File", _boom)
        monkeypatch.setattr(runner, "_resolve_task_facts", lambda: DECLARED_FLOAT_TASK)
        for cls in INT8_FAMILY:
            register(cls())
        register(SampleDispersionFloorCheck())
        gate = GateConfig(
            id="rung_gate",
            after_round=1,
            short_circuit=False,
            checks=[
                *(CheckRef(name=cls.name) for cls in INT8_FAMILY),
                CheckRef(
                    name="sample_dispersion_floor",
                    config={"samples": CONSTANT_SERIES, "min_dispersion": 0.5},
                ),
            ],
            on_pass=ActionConfig(action=GateAction.CONTINUE),
            # Blocking-capable: the fixture check CAN stop a round.
            on_fail=ActionConfig(action=GateAction.INVALIDATE_ROUND),
        )
        monkeypatch.setattr(
            runner,
            "load_health_gates_config",
            lambda *a, **k: HealthChecksConfig(health_gates=[gate]),
        )
        return evaluate_gate("rung_gate", _full_ctx())

    def test_rung_b_the_int8_family_is_inapplicable_and_opens_no_file(self, declared_float_gate):
        """§8.4-B: declared-float ⇒ int8 family `inapplicable`, no file opened."""
        by_name = {r.check_name: r for r in declared_float_gate.check_results}
        for cls in INT8_FAMILY:
            assert by_name[cls.name].verdict is CheckVerdict.INAPPLICABLE, cls.name
        # The no-file-opened half is enforced by the patched h5py.File: any
        # read would have raised out of evaluate_gate's exception guard and
        # produced an ERROR verdict instead.
        assert not any(r.verdict is CheckVerdict.ERROR for r in declared_float_gate.check_results)

    def test_rung_c_a_generic_check_fires_and_fails_on_that_same_output(self, declared_float_gate):
        """§8.4-C: a generic check FIRES and can FAIL on that same output.

        This is the negative control: inapplicability of one family is not
        an exemption from health evaluation.
        """
        by_name = {r.check_name: r for r in declared_float_gate.check_results}
        dispersion = by_name["sample_dispersion_floor"]
        assert dispersion.verdict is CheckVerdict.FAILED
        assert dispersion.passed is False
        assert dispersion.metrics["dispersion"] == 0.0

    def test_the_gate_blocks_on_the_contrast_family_failure(self, declared_float_gate):
        """The failure is not merely recorded — it routes.

        A framework that reported the failure but took ``on_pass`` would
        satisfy every assertion above while still exempting the task.
        """
        assert declared_float_gate.passed is False
        assert declared_float_gate.action is GateAction.INVALIDATE_ROUND
        assert "sample_dispersion_floor" in declared_float_gate.failure_reason

    def test_no_check_in_this_gate_reports_a_pass(self, declared_float_gate):
        """Inapplicable is not pass — asserted on the verdicts, not the count."""
        assert not any(r.verdict is CheckVerdict.PASSED for r in declared_float_gate.check_results)
