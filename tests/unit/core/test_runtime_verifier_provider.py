"""Selected timing providers stay pinned across launch, phase work and priors."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)
from core.runtime_control import verifier_provider as providers
from core.runtime_control.adaptive import AdaptiveUnitVerification
from core.runtime_control.observation_store import observation_calibration_key
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload


@pytest.fixture
def installed_provider(tmp_path, monkeypatch):
    source = tmp_path / "provider.py"
    source.write_text("# fixture implementation v1\n")
    calls = []

    def create(*, unit, config, prior_expected_unit_ms, completion_policy):
        calls.append((unit, completion_policy, prior_expected_unit_ms))
        return AdaptiveUnitVerification(
            unit=unit, config=config, prior_expected_unit_ms=prior_expected_unit_ms
        )

    profile = providers.RuntimeVerifierProfile(
        name="fixture-verifier-v1",
        version="1",
        create=create,
        sources={"provider.py": source},
        qualified_assemblies=frozenset({providers.verifier_assembly_digest()}),
    )
    entry = SimpleNamespace(name=profile.name, load=lambda: lambda: profile)
    monkeypatch.setattr(providers, "entry_points", lambda **kwargs: [entry])
    return profile, source, calls


def test_native_default_has_no_external_identity_or_discovery(tmp_path, monkeypatch):
    def forbidden(**kwargs):
        raise AssertionError("native path must not discover external providers")

    monkeypatch.setattr(providers, "entry_points", forbidden)
    policy = RuntimeControlPolicy()
    assert "runtime_verifier" not in policy.model_dump()
    assert "runtime_verifier_identity" not in policy.model_dump()
    verifier = RuntimeVerificationSession(
        str(tmp_path / "rv.json"), policy
    ).start_phase_verification("training", "optimizer_step")
    assert type(verifier) is AdaptiveUnitVerification


def test_policy_roundtrip_and_production_phase_use_selected_factory(installed_provider, tmp_path):
    profile, _, calls = installed_provider
    parent = RuntimeControlPolicy(
        runtime_verifier=profile.name, runtime_completion_policy="verified-prediction-v1"
    )
    child = RuntimeControlPolicy.model_validate_json(parent.model_dump_json())
    assert child.runtime_verifier_identity == profile.identity()
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"), child)
    session.complete_setup(
        storage_provenance={},
        training_workload=ResolvedPhaseWorkload(
            phase="training",
            unit="optimizer_step",
            unit_count=2,
        ),
    )
    verifier = session.start_phase_verification(
        "training", "optimizer_step", prior_expected_unit_ms=3
    )
    verifier.feed(1)
    verifier.feed(1)
    session.complete_phase_verification("training", verifier, source="real_training_verification")
    assert calls == [("optimizer_step", "verified-prediction-v1", 3)]
    assert session.observation.components["training"].prediction is None
    assert (
        session.observation.runtime_policy["runtime_verifier_identity"]
        == profile.identity().model_dump()
    )


@pytest.mark.parametrize("boundary", ["child_policy", "session", "phase"])
def test_provider_change_refuses_before_next_work(installed_provider, tmp_path, boundary):
    profile, source, calls = installed_provider
    policy = RuntimeControlPolicy(runtime_verifier=profile.name)
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy)
    source.write_text("# different source in child environment\n")
    with pytest.raises(ValueError, match="changed"):
        if boundary == "child_policy":
            RuntimeControlPolicy.model_validate_json(policy.model_dump_json())
        elif boundary == "session":
            RuntimeVerificationSession(str(tmp_path / "other.json"), policy)
        else:
            session.start_phase_verification("training", "optimizer_step")
    assert not calls


def test_missing_duplicate_and_wrong_provider_never_fall_back(installed_provider, monkeypatch):
    profile, _, _ = installed_provider
    for entries in ([], [SimpleNamespace(name=profile.name)] * 2):
        monkeypatch.setattr(providers, "entry_points", lambda entries=entries, **kwargs: entries)
        with pytest.raises(ValueError, match="Expected one installed"):
            RuntimeControlPolicy(runtime_verifier=profile.name)
    monkeypatch.setattr(
        providers,
        "entry_points",
        lambda **kwargs: [SimpleNamespace(name=profile.name, load=lambda: lambda: object())],
    )
    with pytest.raises(TypeError, match="selected profile"):
        RuntimeControlPolicy(runtime_verifier=profile.name)


def test_unqualified_assembly_and_invalid_factory_result_refuse(
    installed_provider, tmp_path, monkeypatch
):
    profile, _, _ = installed_provider
    from dataclasses import replace

    unqualified = replace(profile, qualified_assemblies=frozenset())
    monkeypatch.setattr(
        providers,
        "entry_points",
        lambda **kwargs: [SimpleNamespace(name=profile.name, load=lambda: lambda: unqualified)],
    )
    with pytest.raises(ValueError, match="not qualified"):
        RuntimeControlPolicy(runtime_verifier=profile.name)
    invalid = replace(profile, create=lambda **kwargs: object())
    monkeypatch.setattr(
        providers,
        "entry_points",
        lambda **kwargs: [SimpleNamespace(name=profile.name, load=lambda: lambda: invalid)],
    )
    policy = RuntimeControlPolicy(runtime_verifier=profile.name)
    with pytest.raises(TypeError, match="evidence interface"):
        RuntimeVerificationSession(str(tmp_path / "rv.json"), policy).start_phase_verification(
            "training", "optimizer_step"
        )


def test_provider_identity_is_a_run_invariant(installed_provider, tmp_path):
    profile, _, _ = installed_provider
    old = RunInvariants(
        resolved_data_scope=[0], health_gate_enabled=False, health_config_sha256=None
    )
    path = write_run_invariants(str(tmp_path), old)
    before = open(path, "rb").read()
    selected = old.model_copy(update={"runtime_verifier_identity": profile.identity()})
    with pytest.raises(RunInvariantsViolation, match="runtime_verifier_identity"):
        validate_run_invariants(str(tmp_path), selected)
    assert open(path, "rb").read() == before


def test_resumed_observation_cannot_silently_change_verifier(installed_provider, tmp_path):
    profile, _, _ = installed_provider
    path = tmp_path / "rv.json"
    policy = RuntimeControlPolicy(runtime_verifier=profile.name)
    RuntimeVerificationSession(str(path), policy).complete_setup(storage_provenance={})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="resuming"):
        RuntimeVerificationSession.resume_or_start(str(path))
    assert path.read_bytes() == before
    assert RuntimeVerificationSession.resume_or_start(str(path), policy).policy == policy


def test_calibration_separates_native_and_every_selected_identity(installed_provider, tmp_path):
    profile, source, _ = installed_provider
    context = dict(
        precision="float32",
        optimizer_type="adam",
        model_family="fixture",
        param_count=4,
        seg_size=1,
    )
    keys = []
    for label, policy in (
        ("native", RuntimeControlPolicy()),
        ("external", RuntimeControlPolicy(runtime_verifier=profile.name)),
    ):
        session = RuntimeVerificationSession(str(tmp_path / f"{label}.json"), policy)
        session.set_calibration_context(context)
        keys.append(observation_calibration_key(session.observation, "training"))
    source.write_text("# revised implementation\n")
    changed = RuntimeVerificationSession(
        str(tmp_path / "changed.json"), RuntimeControlPolicy(runtime_verifier=profile.name)
    )
    changed.set_calibration_context(context)
    keys.append(observation_calibration_key(changed.observation, "training"))
    assert len(set(keys)) == 3
    assert "verifier=" not in keys[0]


def test_explicit_selection_is_pinned_before_direct_workflow_and_standard_launch(
    installed_provider, tmp_path, monkeypatch
):
    from workflows.launch_identity import resolve_launch_identity
    from workflows.run_config import WorkflowLaunchConfig, bind_runtime_verifier_launch
    from workflows.standard_cli import build_parser, normalize_args

    profile, source, _ = installed_provider
    launch = bind_runtime_verifier_launch(WorkflowLaunchConfig(runtime_verifier=profile.name))
    assert launch.runtime_verifier_identity == profile.identity()
    args = normalize_args(
        build_parser().parse_args(
            [
                "--workspace",
                str(tmp_path),
                "--run_name",
                "identity",
                "--start_iteration",
                "1",
                "--task_composition",
                str(
                    Path(__file__).resolve().parents[3] / "configs/task_composition/quickstart.yaml"
                ),
                "--data_dir",
                str(tmp_path),
                "--runtime_verifier",
                profile.name,
            ]
        )
    )
    assert (
        resolve_launch_identity(args).runtime_verifier_identity == launch.runtime_verifier_identity
    )
    source.write_text("# changed after standard resolution")
    with pytest.raises(ValueError, match="changed"):
        bind_runtime_verifier_launch(launch)


def test_provider_change_before_measurement_consumption_refuses(installed_provider, tmp_path):
    profile, source, _ = installed_provider
    policy = RuntimeControlPolicy(runtime_verifier=profile.name)
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy)
    session.record_phase_workload(
        "training", ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=1)
    )
    verifier = session.start_phase_verification("training", "optimizer_step")
    verifier.feed(1)
    source.write_text("# changed after phase creation")
    with pytest.raises(ValueError, match="changed"):
        session.complete_phase_verification(
            "training", verifier, source="real_training_verification"
        )
    assert session.observation.components["training"].measurement is None


@pytest.mark.parametrize("unit_count, unit_ms", [(2, 0.1), (200, 10.0), (5000, 0.01)])
def test_unselected_provider_preserves_native_timing_across_workload_scales(
    unit_count, unit_ms, monkeypatch
):
    """Dispatch must not change native stopping, evidence or predictions at any size."""
    from core.runtime_control.adaptive import AdaptiveVerificationConfig

    clock = [0.0]
    monkeypatch.setattr("core.runtime_control.adaptive.time.monotonic", lambda: clock[0])
    config = AdaptiveVerificationConfig()
    direct = AdaptiveUnitVerification(unit="optimizer_step", config=config)
    selected = providers.create_runtime_verifier(
        selection=None,
        expected=None,
        unit="optimizer_step",
        config=config,
        prior_expected_unit_ms=None,
        completion_policy="completed-workload-v1",
    )
    for _ in range(unit_count):
        clock[0] += unit_ms / 1000.0
        assert selected.feed(unit_ms, elapsed_ms=unit_ms) == direct.feed(
            unit_ms, elapsed_ms=unit_ms
        )
        if direct.is_terminal:
            break
    assert selected.finalize() == direct.finalize()
    assert selected.measurement() == direct.measurement()
    workload = ResolvedPhaseWorkload(phase="training", unit="optimizer_step", unit_count=unit_count)
    assert selected.prediction(workload, "real_training_verification") == direct.prediction(
        workload, "real_training_verification"
    )
