"""B-G3: the admission gate must be reachable from the real launcher.

Before this wiring the gate was correct and inert. Nothing in production
set `admission_mode` or `measured_requirements`, so the executor's
`getattr` defaults were the only values it ever saw — posture
permanently `trial`, requirement permanently `None` — and that
combination admits unconditionally. B-G1/B-G2 exercised the gate through
the validation harness's `sandbox_factory` seam, which is the only
channel that had ever set those attributes.

So these tests are about the *path*, not the decision. Each one fails if
a link in

    launcher flag -> CLI -> schema -> tuner -> sandbox -> gate

is removed, which is what "reachability" has to mean if it is to be
worth anything.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.runtime_control.admission import GpuAdmissionPolicy
from core.sandbox_executor import TidmadSandbox
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _build_admission_policy,
)
from tests.helpers.tuner_source import tuner_node_source

REPO_ROOT = Path(__file__).resolve().parents[3]
SDSC = REPO_ROOT / "sdsc_submission_scripts"
CHAIN_COMMON = SDSC / "_chain_common.sh"
SLURM = SDSC / "submit_one_iteration.slurm"
RUNNER = SDSC / "run_one_iteration.py"

ADMISSION_FLAGS = ("--gpu_admission_measurement_source", "--gpu_pair_ceiling_gib")

#: The parser's own required arguments, so a parse test exercises the
#: flag under test rather than tripping over an unrelated requirement.
REQUIRED_ARGS = ["--workspace", "/tmp/w", "--run_name", "r"]


def code_only(path: Path) -> str:
    """Source with comments and docstrings stripped.

    A plain substring search over the file also matches the comment that
    *explains* a defect, so a fixed defect can look unfixed. Unparsing
    the AST leaves only what executes.
    """
    return ast.unparse(ast.parse(path.read_text()))


def _runner_parser() -> argparse.ArgumentParser:
    """The real parser from `run_one_iteration.py`."""
    spec = importlib.util.spec_from_file_location("_roi", RUNNER)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:  # pragma: no cover - module guards its own __main__
        pass
    return module.build_parser()


class TestTheTypedPolicy:
    def test_it_accepts_only_trial_and_formal(self):
        assert GpuAdmissionPolicy(mode="trial").mode == "trial"
        assert GpuAdmissionPolicy(mode="formal").mode == "formal"

    def test_it_carries_no_requirement_figure(self):
        """The load-bearing absence. A field holding a raw MiB number an
        operator could type would impersonate a measurement in formal
        mode — the estimate-as-fact defect PR B exists to remove."""
        fields = set(GpuAdmissionPolicy.model_fields)
        assert not [f for f in fields if "mib" in f.lower()]
        assert "requirement" not in " ".join(fields)
        with pytest.raises(ValidationError):
            GpuAdmissionPolicy(mode="formal", requirement_mib=1476)


class TestPostureIsDerivedNotConfigured:
    """A second posture input could disagree with the round actually
    executing, and the disagreement would be silent."""

    @pytest.mark.parametrize("is_trial,expected", [(True, "trial"), (False, "formal")])
    def test_posture_follows_the_executing_round(self, is_trial, expected):
        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=is_trial,
            device_identity=None,
        )
        assert policy.mode == expected
        assert policy.provenance["mode_source"] == "plan.is_trial"

    def test_no_admission_mode_flag_exists(self):
        """If one were added, posture could be set twice."""
        options = {s for a in _runner_parser()._actions for s in a.option_strings}
        assert "--admission_mode" not in options
        assert not [o for o in options if "measured_requirement" in o]

    def test_the_device_uuid_is_carried_not_chosen(self):
        class _Id:
            uuid = "GPU-abc"

        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=False,
            device_identity=_Id(),
        )
        assert policy.device_uuid == "GPU-abc"
        assert policy.provenance["device_uuid_source"] == "hardware_discovery"

    def test_a_missing_device_identity_does_not_invent_one(self):
        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=False,
            device_identity=None,
        )
        assert policy.device_uuid is None


class TestTheSchemaAndCliCarryIt:
    def test_the_schema_has_a_source_reference_and_a_ceiling(self):
        fields = HyperparamTuningInput.model_fields
        assert "gpu_admission_measurement_source" in fields
        assert "gpu_pair_ceiling_gib" in fields

    def test_the_schema_has_no_raw_requirement_field(self):
        assert not [f for f in HyperparamTuningInput.model_fields if "requirement_mib" in f]

    def test_the_schema_defaults_preserve_pre_bg3_behaviour(self):
        cfg = HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w")
        assert cfg.gpu_admission_measurement_source is None
        assert cfg.gpu_pair_ceiling_gib is None

    @pytest.mark.parametrize("flag", ADMISSION_FLAGS)
    def test_the_runner_cli_declares_the_flag(self, flag):
        options = {s for a in _runner_parser()._actions for s in a.option_strings}
        assert flag in options

    def test_the_runner_forwards_them_into_the_schema(self):
        src = RUNNER.read_text()
        assert "gpu_admission_measurement_source=args.gpu_admission_measurement_source" in src
        assert "gpu_pair_ceiling_gib=args.gpu_pair_ceiling_gib" in src

    def test_parsing_a_ceiling_yields_a_float(self):
        args = _runner_parser().parse_args([*REQUIRED_ARGS, "--gpu_pair_ceiling_gib", "6.0"])
        assert args.gpu_pair_ceiling_gib == 6.0


class TestIsTrialCanExpressFalse:
    """`is_trial=args.is_trial or True` erased an explicit False, so the
    flag could never say anything. Default stays True, so omitting it is
    unchanged."""

    def test_omitting_it_still_means_trial(self):
        assert _runner_parser().parse_args(REQUIRED_ARGS).is_trial is True

    def test_it_can_now_be_turned_off(self):
        args = _runner_parser().parse_args([*REQUIRED_ARGS, "--no-is_trial"])
        assert args.is_trial is False

    def test_the_consumer_no_longer_erases_false(self):
        src = code_only(RUNNER)
        assert "args.is_trial or True" not in src
        assert "is_trial=args.is_trial" in src


class TestTheSandboxAndGateAcceptIt:
    def test_the_sandbox_takes_an_admission_policy(self):
        assert "admission_policy" in inspect.signature(TidmadSandbox.__init__).parameters

    def test_omitting_it_preserves_pre_bg3_behaviour(self, tmp_path):
        sandbox = TidmadSandbox(run_name="r", workspace=str(tmp_path))
        assert sandbox.admission_policy is None

    def test_the_gate_prefers_the_policy_over_the_legacy_attribute(self, tmp_path):
        """Two sources would otherwise be able to disagree. The typed one
        wins; the duck-typed reads remain only as the pre-B-G3 path and
        the validation harness's seam."""
        src = Path(REPO_ROOT / "core" / "sandbox_executor.py").read_text()
        gate = src[src.index("def _admission_refusal") : src.index("def _has_host_memory_evidence")]
        assert "policy.mode if policy is not None" in gate
        assert "admission_policy" in gate

    def test_the_gate_passes_the_configured_ceiling(self):
        """It accepted `ceiling_gib` but the call site omitted it, so the
        ceiling reached the gate only through os.environ."""
        src = Path(REPO_ROOT / "core" / "sandbox_executor.py").read_text()
        gate = src[src.index("def _admission_refusal") : src.index("def _has_host_memory_evidence")]
        assert "ceiling_gib=ceiling_gib" in gate

    def test_the_tuner_sets_it_per_round(self):
        """Posture follows the round, so it cannot be resolved once at
        construction and reused across a trial/formal transition."""
        src = tuner_node_source()
        assert "sandbox.admission_policy = _build_admission_policy(" in src
        assert "is_trial=plan.is_trial," in src


class TestLauncherForwarding:
    @pytest.mark.parametrize("flag", ADMISSION_FLAGS)
    def test_chain_common_parses_and_forwards_it(self, flag):
        src = CHAIN_COMMON.read_text()
        assert f"{flag})" in src, f"{flag} has no case arm"
        assert f"APP_ARGS+=({flag} " in src, f"{flag} is parsed but never forwarded"

    @pytest.mark.parametrize("flag", ADMISSION_FLAGS)
    def test_the_sdsc_launcher_forwards_it(self, flag):
        """Superseded design note: these flags used to need explicit case
        arms in the slurm wrapper, because anything unnamed was dropped.
        The wrapper no longer owns the application CLI at all — it
        forwards what it does not own — so the property to assert is that
        the flag *arrives*, not that the wrapper recognises it.

        Full argv-level coverage lives in
        `tests/unit/scripts/test_sdsc_argument_forwarding.py`; this is the
        admission-specific case.
        """
        from tests.unit.scripts.test_sdsc_argument_forwarding import BASE, forward

        out = forward([*BASE, flag, "X"])
        assert flag in out
        assert out[out.index(flag) + 1] == "X"

    def test_the_sdsc_launcher_drops_nothing(self):
        """Neither silently nor with a warning. warn-and-drop was
        withdrawn: making the loss visible does not make the requested
        configuration arrive."""
        src = SLURM.read_text()
        assert "# ignore unknown flags" not in src
        assert "dropping unrecognised flag" not in src

    def test_an_unknown_flag_reaches_the_single_validator(self):
        """The wrapper must not adjudicate. Python owns the CLI, so an
        unknown token is forwarded and rejected there."""
        from tests.unit.scripts.test_sdsc_argument_forwarding import BASE, forward

        out = forward([*BASE, "--totally_unknown_flag", "x"])
        assert "--totally_unknown_flag" in out


class TestReachabilityGuardrails:
    """Each of these fails if a link is removed, which is the only way a
    reachability claim can be worth anything."""

    def test_the_validation_sandbox_is_not_the_production_mechanism(self):
        """`_ValidationSandbox` may never become the configuration
        channel (§4d.3d)."""
        prod = Path(REPO_ROOT / "core" / "sandbox_executor.py").read_text()
        tuner = tuner_node_source()
        assert "_ValidationSandbox" not in prod
        assert "_ValidationSandbox" not in tuner
        assert "bg_admission_validation" not in prod
        assert "bg_admission_validation" not in tuner

    def test_the_full_chain_is_intact(self):
        """One assertion per hop, so a break names the hop."""
        chain = [
            (CHAIN_COMMON.read_text(), "--gpu_pair_ceiling_gib", "run_chain -> app args"),
            (RUNNER.read_text(), "--gpu_pair_ceiling_gib", "app args -> CLI"),
            (RUNNER.read_text(), "gpu_pair_ceiling_gib=args", "CLI -> schema"),
            (
                tuner_node_source(),
                "sandbox.admission_policy",
                "tuner -> sandbox",
            ),
            (
                Path(REPO_ROOT / "core" / "sandbox_executor.py").read_text(),
                "admission_policy",
                "sandbox -> gate",
            ),
        ]
        for src, needle, hop in chain:
            assert needle in src, f"broken hop: {hop}"

    def test_no_new_environment_reads_were_scattered(self):
        """The ceiling is resolved once, at a boundary. Re-reading the
        environment deeper in the runtime path is how policy stops being
        auditable."""
        tuner = tuner_node_source()
        assert "SIDERIUS_PAIR_VRAM_CEILING_GIB" not in tuner

    def test_the_compatibility_ceiling_default_is_unchanged(self):
        """B-G3 wires the ceiling; it does not move it."""
        src = Path(REPO_ROOT / "core" / "runtime_control" / "pair_admission.py").read_text()
        assert re.search(r"DEFAULT_PAIR_CEILING_GIB\s*=\s*28\.0", src)


class TestProvenanceCannotAbortAnAttempt:
    """`device_uuid` is recorded so a refusal can be checked against the
    card it ran on. It never selects a device. So an identity object that
    cannot supply a usable string must degrade to unknown rather than
    raise — otherwise building provenance aborts an attempt the gate
    itself would have allowed."""

    @pytest.mark.parametrize("bad", [object(), 123, b"GPU-x", ["GPU-x"]])
    def test_a_non_string_uuid_degrades_to_none(self, bad):
        class _Id:
            uuid = bad

        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=False,
            device_identity=_Id(),
        )
        assert policy.device_uuid is None
        assert policy.mode == "formal"

    def test_a_real_uuid_still_survives(self):
        class _Id:
            uuid = "GPU-c30b6678"

        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=False,
            device_identity=_Id(),
        )
        assert policy.device_uuid == "GPU-c30b6678"

    def test_a_bad_ceiling_still_fails_loudly(self):
        """Degrading provenance must not turn into degrading policy: a
        ceiling that cannot be honoured is a misconfiguration, and the
        CLI types it as a float, so it must not be silently dropped."""
        cfg = HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w")
        object.__setattr__(cfg, "gpu_pair_ceiling_gib", -5.0)
        with pytest.raises(ValidationError):
            _build_admission_policy(cfg, is_trial=False, device_identity=None)


class TestTheProtocolHopIsNotSkipped:
    """The hop my first reachability suite missed -- twice.

    `run_workflow` does not build `HyperparamTuningInput` itself; it goes
    through the `ml_model_valid -> ml_model_tune` protocol, which is the
    only place field mapping is allowed to happen. A field added to the
    schema and the launcher but not to the protocol reaches nothing, and
    every launcher-side test still passes.
    """

    PROTOCOL = REPO_ROOT / "agent" / "schemas" / "protocols" / "ml_model_valid_to_ml_model_tune.py"

    @pytest.mark.parametrize("field", ["gpu_admission_measurement_source", "gpu_pair_ceiling_gib"])
    def test_the_protocol_accepts_and_maps_the_field(self, field):
        from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
            local_validated_model,
        )

        assert field in inspect.signature(local_validated_model).parameters
        src = code_only(self.PROTOCOL)
        assert f"{field}={field}" in src, f"{field} is accepted but never mapped"

    @pytest.mark.parametrize("field", ["gpu_admission_measurement_source", "gpu_pair_ceiling_gib"])
    def test_run_workflow_accepts_and_forwards_the_field(self, field):
        # Step 09.5a C3: these are transit configuration, so the workflow
        # forwards them as `field=launch.field`. Same forwarding invariant.
        src = code_only(REPO_ROOT / "workflows" / "model_exploration.py")
        assert f"{field}=launch.{field}" in src or f"{field}={field}" in src

    def test_no_field_is_declared_on_the_schema_without_reaching_the_protocol(self):
        """Generalised: any admission field the schema gains must be
        mappable, or it is decoration."""
        from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
            local_validated_model,
        )

        accepted = set(inspect.signature(local_validated_model).parameters)
        admission_fields = {f for f in HyperparamTuningInput.model_fields if f.startswith("gpu_")}
        assert admission_fields, "guard would be vacuous with no gpu_* fields"
        assert admission_fields <= accepted


def _crowded_or_empty(used_mib):
    from core.runtime_control.gpu_accounting import DeviceIdentity, GpuAccountingSnapshot

    return GpuAccountingSnapshot(
        device=DeviceIdentity(uuid="GPU-e-0", physical_index=0),
        telemetry_available=True,
        device_total_mib=32_000,
        device_used_mib=used_mib,
        own_tree_mib=0,
        other_mib=used_mib,
        other_process_count=1 if used_mib else 0,
        per_pid_total_mib=used_mib,
        unattributed_mib=0,
        accounting_skew_mib=0,
    )


class _EnforcementSandbox:
    def __init__(self, policy):
        from core.runtime_control.gpu_accounting import DeviceIdentity

        self.device_identity = DeviceIdentity(uuid="GPU-e-0", physical_index=0)
        self.run_name = "enf"
        self.admission_policy = policy
        self.admission_observations: list[dict] = []


class TestEnforcementIsSeparateFromPosture:
    """B-G3 made the consequence concrete: once the gate is reachable,
    formal + no authoritative measurement refuses -- correctly -- and PR C
    does not exist yet. `observe_only` keeps formal rounds running while
    recording exactly what would have been refused. The phase is never
    relabelled: a formal round called `trial` would make every record
    claim a posture the round did not have."""

    @staticmethod
    def _decide(enforcement, mode="formal", used_mib=0, requirements=None):
        import subprocess as sp

        from core.runtime_control.admission import GpuAdmissionPolicy
        from core.sandbox_executor import _admission_refusal

        sandbox = _EnforcementSandbox(
            GpuAdmissionPolicy(mode=mode, enforcement=enforcement, ceiling_gib=6.0)
        )
        sandbox.measured_requirements = requirements or {}
        with (
            patch(
                "core.runtime_control.gpu_accounting.sample",
                return_value=_crowded_or_empty(used_mib),
            ),
            patch.object(sp, "Popen") as popen,
        ):
            status = _admission_refusal(sandbox, phase="training")
        return status, sandbox, popen

    def test_the_two_are_separate_fields(self):
        from core.runtime_control.admission import GpuAdmissionPolicy

        fields = GpuAdmissionPolicy.model_fields
        assert "mode" in fields and "enforcement" in fields
        p = GpuAdmissionPolicy(mode="formal", enforcement="observe_only")
        assert p.mode == "formal"
        assert p.enforcement == "observe_only"

    def test_observe_only_lets_a_formal_phase_proceed(self):
        status, _, _ = self._decide("observe_only")
        assert status is None, "observe_only must not stop the phase"

    def test_observe_only_still_evaluates_and_records_the_refusal(self):
        _, sandbox, _ = self._decide("observe_only")
        assert len(sandbox.admission_observations) == 1
        obs = sandbox.admission_observations[0]
        assert obs["would_refuse"] is True
        assert obs["admission"]["reason_code"] == "policy_unavailable"
        assert obs["enforcement"] == "observe_only"

    def test_observe_only_does_not_relabel_the_phase(self):
        """The whole reason a separate field exists."""
        _, sandbox, _ = self._decide("observe_only")
        obs = sandbox.admission_observations[0]
        assert obs["mode"] == "formal"
        assert obs["admission"]["evidence"]["mode"] == "formal"
        assert "trial" not in (obs["mode"], obs["admission"]["evidence"]["mode"])

    def test_enforce_stops_the_phase(self):
        status, _, popen = self._decide("enforce")
        assert status is not None
        assert status["admission"]["reason_code"] == "policy_unavailable"
        assert popen.call_count == 0

    def test_enforce_records_no_observation_because_it_refused(self):
        _, sandbox, _ = self._decide("enforce")
        assert sandbox.admission_observations == []

    def test_observe_only_does_not_suppress_evidence(self):
        """An observe-only interval must be auditable, or "we observed
        it" is unfalsifiable."""
        _, sandbox, _ = self._decide("observe_only")
        ev = sandbox.admission_observations[0]["admission"]["evidence"]
        for key in ("mode", "device_uuid", "requirement_mib", "effective_ceiling_gib"):
            assert key in ev

    def test_observe_only_emits_no_shrink_advice(self):
        _, sandbox, _ = self._decide("observe_only")
        blob = json.dumps(sandbox.admission_observations[0])
        assert "reduce model" not in blob
        assert "reduce batch_size" not in blob

    def test_an_admitted_phase_records_nothing(self):
        """Empty must mean "nothing would have been refused", not
        "nothing was checked"."""
        _, sandbox, _ = self._decide(
            "observe_only",
            requirements={"training": {"requirement_mib": 100, "provenance": "measured"}},
        )
        assert sandbox.admission_observations == []

    def test_enforce_does_not_fall_open_on_a_sampling_error(self):
        import subprocess as sp

        from core.runtime_control.admission import GpuAdmissionPolicy
        from core.sandbox_executor import _admission_refusal

        sandbox = _EnforcementSandbox(GpuAdmissionPolicy(mode="formal", enforcement="enforce"))
        sandbox.measured_requirements = {}
        with (
            patch(
                "core.runtime_control.gpu_accounting.sample",
                side_effect=RuntimeError("nvml exploded"),
            ),
            patch.object(sp, "Popen"),
        ):
            status = _admission_refusal(sandbox, phase="training")
        assert status is not None, "formal+enforce must not fall open"

    @pytest.mark.parametrize("bad", ["", "observe", "ENFORCE", "yes", "trial"])
    def test_an_invalid_enforcement_value_is_rejected(self, bad):
        from core.runtime_control.admission import GpuAdmissionPolicy

        with pytest.raises(ValidationError):
            GpuAdmissionPolicy(mode="formal", enforcement=bad)

    def test_the_compatibility_default_is_provenance_stamped(self):
        policy = _build_admission_policy(
            HyperparamTuningInput(model_type="punet", run_name="r", workspace="/tmp/w"),
            is_trial=False,
            device_identity=None,
        )
        assert policy.enforcement == "observe_only"
        assert "enforcement_source" in policy.provenance

    def test_the_legacy_duck_typed_path_still_enforces(self):
        """The B-G harness injects posture via a bare `admission_mode`
        attribute and B-G1/B-G2 are evidence about that path. Defaulting
        it to observe_only would disarm every harness scenario while the
        tests still looked green."""
        import subprocess as sp

        from core.runtime_control.gpu_accounting import DeviceIdentity
        from core.sandbox_executor import _admission_refusal

        class _Legacy:
            device_identity = DeviceIdentity(uuid="GPU-e-0", physical_index=0)
            run_name = "legacy"
            admission_mode = "formal"
            measured_requirements: ClassVar[dict] = {}

        with (
            patch(
                "core.runtime_control.gpu_accounting.sample",
                return_value=_crowded_or_empty(0),
            ),
            patch.object(sp, "Popen"),
        ):
            status = _admission_refusal(_Legacy(), phase="training")
        assert status is not None


class TestCeilingIsAuditable:
    """FU-B-17. A `policy_unavailable` refusal returns before the
    headroom block, so without this the record could not say which
    ceiling applied -- and for `insufficient_headroom` the ceiling IS the
    decision."""

    @pytest.mark.parametrize("mode", ["formal", "trial"])
    def test_the_ceiling_triple_is_recorded_even_without_a_requirement(self, mode):
        from core.runtime_control.admission import evaluate_gpu_admission

        decision = evaluate_gpu_admission(
            snapshot=_crowded_or_empty(0),
            requirement_mib=None,
            requirement_provenance=None,
            mode=mode,
            ceiling_gib=6.0,
        )
        ev = decision.evidence
        assert ev["configured_ceiling_gib"] == 6.0
        assert ev["measured_device_capacity_gib"] > 0
        assert ev["effective_ceiling_gib"] == 6.0

    def test_policy_and_hardware_stay_separate_facts(self):
        """ "the operator asked for 6 GiB" and "the card holds 31.8 GiB"
        are different facts; the effective value is derived from both."""
        from core.runtime_control.admission import evaluate_gpu_admission

        ev = evaluate_gpu_admission(
            snapshot=_crowded_or_empty(0),
            requirement_mib=None,
            requirement_provenance=None,
            mode="formal",
            ceiling_gib=99_999.0,
        ).evidence
        assert ev["configured_ceiling_gib"] == 99_999.0
        assert ev["effective_ceiling_gib"] == ev["measured_device_capacity_gib"]
        assert ev["effective_ceiling_gib"] < ev["configured_ceiling_gib"]

    def test_an_insufficient_headroom_refusal_can_be_audited(self):
        from core.runtime_control.admission import evaluate_gpu_admission

        decision = evaluate_gpu_admission(
            snapshot=_crowded_or_empty(31_500),
            requirement_mib=1476,
            requirement_provenance="measured",
            mode="formal",
            ceiling_gib=6.0,
        )
        assert decision.reason_code == "insufficient_headroom"
        assert decision.evidence["effective_ceiling_gib"] == 6.0
