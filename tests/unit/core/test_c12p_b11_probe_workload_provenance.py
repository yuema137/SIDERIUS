"""C12-P / B11 — a probe observation's ``workload`` must describe the probe.

FALSIFIER for the two paired provenance sites::

    core/runtime_control/bootstrap.py                      (records the probe)
    nodes/ml_hyperparameter_tune_agent/runtime.py          (requests the probe)

Both wrote ``segment_length`` from ``.get("segmentation_size", 0)``. Both feed
``production_probe_executors``, which builds the candidate with
``config_cls(**model_config)`` — so an OMITTED key made the probe run at the
config class's DECLARED default while the record said ``0``. ``bootstrap.py``'s
own comment claimed "the workload the probe ACTUALLY ran"; C12-P made that
sentence true again.

Why ``0`` is not a harmless sentinel
------------------------------------
``ApplicabilityEnvelope.from_observations`` derives ``segment_length``'s
observed span from these very records, and ``applicability_for_request`` then
labels a candidate ``"interpolation"`` when it falls inside that span. One
record carrying ``0`` drags ``observed_min`` to zero, and every far-smaller
request in that bucket is then labelled as sitting inside measured evidence
that does not exist. It cannot be read back as "unset" either: the request side
declares ``segment_length: int = Field(gt=0)``
(``core/runtime_control/estimate_types.py:222``), so ``0`` is not a value any
reader is prepared to reject.

The discriminating property
---------------------------
Asserting that the recorded integer changed is NOT enough — the recorded number
moving from ``0`` to ``20000`` could be satisfied by any edit that writes a
bigger literal. :class:`TestTheEnvelopeStopsClaimingUnmeasuredGround` asserts
the CONSEQUENCE across two observations, where the two verdicts genuinely
differ: with the defect the envelope says ``interpolation`` for a request 200x
smaller than anything measured, and after the fix it says
``unsupported_extrapolation``.

``transformer`` is the witness because its config class DECLARES 20000
(``ml_models/models_format_sandbox.py:122``), which is neither the old sentinel
nor the ``40_000`` literal other sites used — so no test here can pass by two
halves agreeing on a value neither would really produce.
"""

from __future__ import annotations

from typing import Any

from core.runtime_control.bootstrap import BootstrapDependencies, run_bootstrap
from core.runtime_control.calibration_policy import ApplicabilityEnvelope
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeResult,
    RealizedModelProperties,
    probe_observations,
)
from core.runtime_control.registry_schemas import (
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
)

#: The model whose DECLARED default differs from BOTH literals this family has
#: used. Hardcoded, never read back from the config class: asserting against
#: the class would compare the schema to itself and pass for any value.
_DIVERGENT_MODEL = "transformer"
_ITS_DECLARED_DEFAULT = 20_000

#: What the two sites recorded for an omitted key before C12-P / B11.
_THE_OLD_SENTINEL = 0

_HARDWARE = HardwareCompatibilityProfile(
    accelerator_vendor="NVIDIA",
    accelerator_model="c12p-b11-gpu",
    gpu_count=1,
    vram_gb=32.0,
    torch_version="2.7.0",
)


class _Window:
    classification = "single_candidate_idle"
    reasons = ("test",)
    occupancy = None

    def __init__(self) -> None:
        self.samples = (ContentionSnapshot(telemetry_available=True),) * 5

    def raw_telemetry(self) -> dict[str, Any]:
        return {"samples": [], "classification": self.classification}


class _Guard:
    checks = ("a",)
    policy_identity = "runtime_decision_policy@1.0.0+c12p"


def _capability(root: str):
    from core.runtime_control.measurement_capability import ResolvedMeasurementCapability

    return ResolvedMeasurementCapability(
        task_identity="c12p_b11_task",
        dataset_adapter="c12p_b11_adapter",
        data_shape_class="c12p_b11_shape",
        probe_available=True,
        unavailability_reason=None,
        dataset_root=root,
        target_device="cuda:test",
        supported_phases=("training", "inference"),
    )


def _probe_result() -> ProbeResult:
    return ProbeResult(
        status="ok",
        model_identity=_DIVERGENT_MODEL,
        realized=RealizedModelProperties(
            parameter_count=45_408,
            trainable_parameter_count=45_408,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=1.5,
        train_ms_per_step=17.6,
        train_ms_spread=(17.0, 18.2),
        inference_ms_per_batch=8.1,
        inference_ms_spread=(7.9, 8.4),
        peak_vram_gb=1.2,
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0),
        caps=ProbeCaps(),
        wall_seconds=20.0,
    )


def _run_bootstrap_recording(tmp_path, model_config: dict[str, Any]) -> list:
    """Drive the REAL ``run_bootstrap`` and return the observations it built.

    ``build_executors`` is a stub, which is exactly the point: the production
    wiring hands it this same ``model_config`` and it resolves the absent key
    through Pydantic, so the recorded workload is the only place the two can
    disagree. The observations come from the real ``probe_observations``
    producer, because a hand-built ``CalibrationObservation`` cannot see a
    call-site defect.
    """
    recorded: list = []

    def _observations(result, *, hardware_compatibility_id, execution_environment_id, workload):
        records = probe_observations(
            result,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            workload=workload,
            software_stack={"torch": "2.7.0"},
            source_run={"run_name": "c12p_b11"},
        )
        recorded.extend(records)
        return records

    deps = BootstrapDependencies(
        collect_hardware=lambda: _HARDWARE,
        collect_environment=lambda **kw: ExecutionEnvironmentProfile(**kw),
        build_registry=lambda: CalibrationRegistry(tmp_path / "runtime_calibration"),
        measurement_capability=lambda: _capability(str(tmp_path / "data")),
        sample_contention=lambda **kw: _Window(),
        build_executors=lambda **kw: object(),
        run_probe=lambda **kw: _probe_result(),
        build_observations=_observations,
        launch_self_test=lambda **kw: _Guard(),
        device_vram_gb=lambda: 32.0,
    )
    report = run_bootstrap(
        model_type=_DIVERGENT_MODEL,
        model_config=model_config,
        train_config={"batch_size": 8, "epochs": 1},
        loss_config={"loss_type": "ce"},
        deps=deps,
    )
    assert report.ready is True, f"the fixture must reach step 9: {report.failures}"
    assert recorded, "the bootstrap never built an observation"
    return recorded


def _tuner_request_workload(monkeypatch, model_config: dict[str, Any]) -> dict[str, Any]:
    """Drive the REAL ``_resolve_time_check_probe_request`` far enough to
    build its ``ProbeRequest``, and return the workload it declared."""
    import nodes.ml_hyperparameter_tune_agent as tuner
    from core.runtime_control import probe_wiring

    captured: dict[str, Any] = {}

    class _Capability:
        available = True
        unavailability_reason = None

    monkeypatch.setattr(probe_wiring, "probe_runner_availability", lambda _c: (True, "forced"))
    monkeypatch.setattr(probe_wiring, "build_production_probe_runner", lambda **kw: lambda r: None)
    monkeypatch.setattr(probe_wiring, "build_registry_persist", lambda **kw: lambda *a: ())
    monkeypatch.setattr(probe_wiring, "probe_capability", lambda **kw: _Capability(), raising=False)

    def _capture(*, request, budget, mode, run_probe, persist, **kw):
        captured["workload"] = dict(request.workload)

        class _Res:
            class decision:
                kind = "ALLOW"
                reasons = ()
                evidence_provenance = "bounded_live_probe"

            probe_ran = True
            probe_status = "ok"
            observation_ids = ()
            estimate = None

        return _Res()

    monkeypatch.setattr(probe_wiring, "resolve_request_probe", _capture)

    tuner._resolve_time_check_probe_request(
        {"breakdown": {"runtime_decision": "REQUEST_PROBE"}},
        model_type=_DIVERGENT_MODEL,
        active_params={
            "model_config": model_config,
            "train_config": {"batch_size": 8, "epochs": 1},
            "loss_config": {"loss_type": "ce"},
        },
        time_budget_minutes=60.0,
        is_trial=False,
        data_dir=None,
        run_name="c12p_b11",
        exp_id="e1",
    )
    assert "workload" in captured, "the production helper never built a ProbeRequest"
    return captured["workload"]


class TestTheRecordedWorkloadIsWhatTheProbeRan:
    def test_bootstrap_records_the_size_the_model_is_built_at(self, tmp_path):
        """DEFECT THIS TEST ALONE CATCHES
            ``bootstrap.py`` recording a workload the probe did not run —
            ``segment_length: 0`` for a candidate ``production_probe_executors``
            constructs at its config class's declared 20000.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            The literal comes back and the recorded value is ``0`` again,
            which this names against the declared 20000.
        """
        records = _run_bootstrap_recording(tmp_path, {})

        sizes = {int(r.workload["segment_length"]) for r in records}
        assert sizes == {_ITS_DECLARED_DEFAULT}, (
            f"the bootstrap recorded segment_length={sizes} for a probe that "
            f"ran at the transformer's declared {_ITS_DECLARED_DEFAULT}. Its "
            f"own comment claims this is 'the workload the probe ACTUALLY ran'."
        )

    def test_the_tuner_requests_the_size_the_model_is_built_at(self, monkeypatch):
        """DEFECT THIS TEST ALONE CATCHES
            The tuner's ``ProbeRequest`` declaring a workload its own
            ``build_production_probe_runner`` will not run. The bootstrap case
            above cannot see it: the two sites are separate call sites that
            merely happen to describe the same probe.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            ``request.workload['segment_length']`` is ``0`` again.
        """
        workload = _tuner_request_workload(monkeypatch, {})

        assert int(workload["segment_length"]) == _ITS_DECLARED_DEFAULT, (
            f"the tuner requested segment_length="
            f"{workload['segment_length']!r} for a probe that will be built at "
            f"the transformer's declared {_ITS_DECLARED_DEFAULT}"
        )
        assert workload["segment_length"] != _THE_OLD_SENTINEL

    def test_a_declared_size_still_travels_unchanged_on_both_sites(self, tmp_path, monkeypatch):
        """CONTROL — guards the fix, not the defect.

        Every production plan states this field, so this is where
        "behaviour-preserving" is actually measured: an over-correction that
        started preferring the class default over the caller's explicit value
        would turn 6250 into 20000 on both sides.

        6250 rather than a round number on purpose: it divides TIDMAD's
        ``psd_segment_length`` evenly, so it is a legal value that is
        nevertheless equal to neither literal nor to the declared default.
        """
        declared = {"segmentation_size": 6_250}

        records = _run_bootstrap_recording(tmp_path, declared)
        assert {int(r.workload["segment_length"]) for r in records} == {6_250}

        workload = _tuner_request_workload(monkeypatch, declared)
        assert int(workload["segment_length"]) == 6_250


class TestTheEnvelopeStopsClaimingUnmeasuredGround:
    def test_a_recorded_zero_makes_a_tiny_request_look_interpolated(self, tmp_path):
        """THE DISCRIMINATING CASE. The defect this alone catches: applicability
        authority granted by a sentinel rather than by evidence.

        Two observations enter one bucket — one from a plan that DECLARED
        40000, one from a plan that omitted the key. With the defect the second
        contributes ``0``, the span becomes ``[0, 40000]`` and a request at 100
        — 400x below anything ever measured — is labelled ``interpolation``.
        With the fix the span is ``[20000, 40000]`` and the same request is
        correctly ``unsupported_extrapolation``.

        This is asserted instead of "the number got bigger" because the number
        getting bigger is satisfied by writing any other literal; only the
        verdict flip proves the recorded value came from what was measured.

        HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
            ``label`` is ``interpolation``, and the message reports the span
            the envelope derived, naming the ``0`` that widened it.
        """
        observations = [
            *_run_bootstrap_recording(tmp_path / "declared", {"segmentation_size": 40_000}),
            *_run_bootstrap_recording(tmp_path / "omitted", {}),
        ]

        envelope = ApplicabilityEnvelope.from_observations(observations)
        span = envelope.ranges["segment_length"]
        label, _reasons = envelope.classify({"segment_length": 100.0})

        assert label == "unsupported_extrapolation", (
            f"the envelope's segment_length span is {span} and it called a "
            f"request of 100 {label!r}. A span reaching down to "
            f"{_THE_OLD_SENTINEL} is a recorded sentinel, not measured "
            f"evidence, and every far-smaller candidate in this bucket "
            f"inherits authority no probe ever earned."
        )
        assert span[0] == _ITS_DECLARED_DEFAULT, (
            f"the observed minimum is {span[0]}, but the smallest size any of "
            f"these probes was built at is the transformer's declared "
            f"{_ITS_DECLARED_DEFAULT}"
        )
