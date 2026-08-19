"""Step 08a C6 — roadmap §8.4 rungs B and C — UPGRADED at 08c C2.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.6,
§4.6; roadmap §8.4; Step-08c child design §2.11/§4.2/§5 for the upgrade.

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

**The 08c upgrade.** The dispersion check's samples no longer arrive
through its own config (the 08a scaffold, retired): they arrive through a
REAL registered provider materializing the standard ``continuous_samples``
view over the real 08b binding path (``resolve_task_health_bindings`` sets
the bound facts and the view binding; no runner monkeypatching). Every
hand-computed arithmetic anchor is preserved verbatim. Reverting the check
to its config-borne form turns rung C red: the gate supplies no config
samples, so a reverted check ERRORs instead of FAILING.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

import numpy as np
import pytest

from execute_tools.health_checks import _plugin_binding, runner
from execute_tools.health_checks._plugin_binding import (
    HealthBindingError,
    resolve_task_health_bindings,
)
from execute_tools.health_checks._regime_a_facts import resolve_health_facts
from execute_tools.health_checks._task_health_config import TaskHealthConfig
from execute_tools.health_checks._view_provider import HealthView
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
from execute_tools.health_checks.registry import register, register_view_provider
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
from execute_tools.health_checks.standard_views import (
    CONTINUOUS_SAMPLES,
    ContinuousSamplesPayload,
)

INT8_FAMILY = (
    OutputDiversityCheck,
    OutputStdCheck,
    AmplitudeCollapseCheck,
    PerFileOutputStdCheck,
    SpectralPeakRatioCheck,
    PearsonDispersionCheck,
)

# The declared-continuous task the 8.4-B fixture uses. Since the 08c
# upgrade the decisive gate derives these SAME facts through the real
# binding path (``_declared_float_config().resolved_facts()``); the
# equality is asserted below so the two spellings cannot drift.
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

GENERIC_CHECKS = (
    "sample_dispersion_floor",
    "categorical_distinct_symbols",
    "categorical_dominant_fraction",
)


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _plugin_binding.reset_run_scope()


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


def _full_ctx() -> HealthCheckContext:
    return _ctx(
        denoised_filename_fn=lambda fi: f"/tmp/denoised_{fi:04d}.h5",
        target_path_fn=lambda fi: f"/tmp/target_{fi:04d}.h5",
    )


def _view(samples: list[float]) -> HealthView:
    return HealthView(
        capability_key=CONTINUOUS_SAMPLES,
        provider_id="rung.fixture_views",
        payload=ContinuousSamplesPayload(samples=np.array(samples, dtype=np.float64)),
    )


class _RungFixtureViews:
    """A real registered provider serving the constant series."""

    provider_id: ClassVar[str] = "rung.fixture_views"
    capabilities: ClassVar[frozenset[str]] = frozenset({CONTINUOUS_SAMPLES})

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        return _view(CONSTANT_SERIES)


def _declared_float_config(**overrides) -> TaskHealthConfig:
    body: dict[str, Any] = {
        "facts": {
            "encoding_family": "continuous_float",
            "file_group_size": 3,
            "sampling_frequency_hz": 250.0,
        },
        "value_scale": {"unit": "mV", "units_per_sample": 0.3125},
        "providers": [{"provider_id": "rung.fixture_views"}],
        "roster": [
            {
                "gate_id": "rung_gate",
                "check": "sample_dispersion_floor",
                "disposition": "blocking",
            }
        ],
    }
    body.update(overrides)
    return TaskHealthConfig.model_validate(body)


class TestDispersionArithmetic:
    """A numerical oracle for the check, computed by hand, not by it.

    Samples arrive through the standard view — the 08c transport — with
    every pre-upgrade expectation preserved verbatim.
    """

    def test_constant_series_has_zero_dispersion_and_fails_the_floor(self):
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"min_dispersion": 0.5}, view=_view(CONSTANT_SERIES)
        )
        assert result.metrics["dispersion"] == 0.0
        assert result.metrics["mean"] == 2.0
        assert result.passed is False
        assert result.verdict is CheckVerdict.FAILED

    def test_varied_series_dispersion_is_sqrt_five_and_passes(self):
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"min_dispersion": 0.5}, view=_view(VARIED_SERIES)
        )
        assert result.metrics["dispersion"] == pytest.approx(VARIED_STD)
        assert result.metrics["mean"] == 3.0
        assert result.passed is True
        assert result.verdict is CheckVerdict.PASSED

    def test_the_floor_is_what_decides(self):
        """Same data, two floors — so the threshold is load-bearing."""
        check = SampleDispersionFloorCheck()
        below = check.run(_ctx(), {"min_dispersion": VARIED_STD + 1}, view=_view(VARIED_SERIES))
        at = check.run(_ctx(), {"min_dispersion": VARIED_STD}, view=_view(VARIED_SERIES))
        assert below.passed is False
        assert at.passed is True  # the floor is inclusive

    def test_an_empty_stream_is_an_error_not_a_pass(self):
        """A floor over nothing is the absence of evidence — fail closed."""
        result = SampleDispersionFloorCheck().run(_ctx(), {"min_dispersion": 0.5}, view=_view([]))
        assert result.verdict is CheckVerdict.ERROR
        assert result.passed is False

    def test_an_absent_view_is_an_error(self):
        result = SampleDispersionFloorCheck().run(_ctx(), {"min_dispersion": 0.5})
        assert result.verdict is CheckVerdict.ERROR
        assert CONTINUOUS_SAMPLES in result.reason

    def test_the_config_borne_samples_path_is_retired(self):
        """08a's scaffold is GONE: config samples are ignored, not read.

        A reverted (pre-08c) check would compute dispersion 0.0 from these
        config samples and report FAILED; the upgraded check ERRORs because
        no view was supplied. This is the §5 disposition's mutation
        anchor — reverting the upgrade turns this red.
        """
        result = SampleDispersionFloorCheck().run(
            _ctx(), {"samples": CONSTANT_SERIES, "min_dispersion": 0.5}
        )
        assert result.verdict is CheckVerdict.ERROR
        assert "samples" not in result.metrics


class TestTheAxisCutsBothWays:
    def test_the_upgraded_check_declares_only_what_it_consumes(self):
        """§2.11 biconditional: the arithmetic never reads encoding_family.

        The 08a scaffold declared ``encoding_family=continuous_float`` only
        because applicability needed an axis before views existed. The
        upgraded declaration is the view itself plus the threshold —
        nothing else.
        """
        declaration = SampleDispersionFloorCheck.declaration
        assert declaration.consumes_view == "continuous_samples"
        assert declaration.requires_view is True
        assert declaration.required_facts == ()
        assert declaration.threshold_parameter_names == ("min_dispersion",)

    def test_declaration_applies_anywhere_binding_is_the_gate(self):
        """The check applies by declaration even under TIDMAD facts.

        That is not a hole: TIDMAD binds no continuous provider and its
        roster never names this check, and ``requires_view=True`` makes an
        unwired roster fail closed at BINDING time (below) — the §2.11
        statement that binding the capability IS the applicability
        statement.
        """
        verdict = applicability(
            SampleDispersionFloorCheck.declaration, resolve_health_facts(), _full_ctx()
        )
        assert verdict.applicable is True

    def test_a_roster_naming_it_without_a_provider_fails_closed(self, clean_registry):
        register(SampleDispersionFloorCheck())
        with pytest.raises(HealthBindingError, match="continuous_samples"):
            resolve_task_health_bindings(_declared_float_config(providers=[]))

    @pytest.mark.parametrize("check_name", GENERIC_CHECKS)
    def test_it_is_registered_but_configured_nowhere_in_production(self, check_name):
        """Being registered is not being configured.

        Each generic check must be reachable by name — that is what makes
        it a real registration rather than a test-only object — while never
        firing in a production run. The consuming tasks bind them through
        their own pack configs (Pets/DAVIS, 08c C3/C4), never through the
        shipped framework YAMLs.
        """
        from execute_tools.health_checks.config import load_health_gates_config
        from execute_tools.health_checks.registry import get

        assert get(check_name) is not None
        for config_path in (None, "configs/health_checks_baseline_observe_mode.yaml"):
            config = load_health_gates_config(config_path)
            configured = {ref.name for gate in config.health_gates for ref in gate.checks}
            assert check_name not in configured, config_path


class TestRungsBAndCInOneGateEvaluation:
    """The decisive test: both rungs, one gate, one declared-float task.

    Since the 08c upgrade the gate runs the REAL transport end to end:
    registered provider → binding resolution → runner materialization →
    standard payload → check arithmetic. No runner internals are patched;
    the bound facts come from the same binding.
    """

    @pytest.fixture
    def declared_float_gate(self, monkeypatch, clean_registry):
        import h5py

        def _boom(*args, **kwargs):
            raise AssertionError(
                "an inapplicable check opened an HDF5 file — applicability "
                "must be decided BEFORE artifact I/O (roadmap §8.4-B)"
            )

        monkeypatch.setattr(h5py, "File", _boom)
        for cls in INT8_FAMILY:
            register(cls())
        register(SampleDispersionFloorCheck())
        register_view_provider(_RungFixtureViews())
        config = _declared_float_config()
        assert config.resolved_facts() == DECLARED_FLOAT_TASK
        resolve_task_health_bindings(config)
        gate = GateConfig(
            id="rung_gate",
            after_round=1,
            short_circuit=False,
            checks=[
                *(CheckRef(name=cls.name) for cls in INT8_FAMILY),
                CheckRef(
                    name="sample_dispersion_floor",
                    config={"min_dispersion": 0.5},
                ),
            ],
            on_pass=ActionConfig(action=GateAction.CONTINUE),
            # Blocking-capable: the generic check CAN stop a round.
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
        an exemption from health evaluation. The samples came through the
        REAL provider, not through check config.
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
