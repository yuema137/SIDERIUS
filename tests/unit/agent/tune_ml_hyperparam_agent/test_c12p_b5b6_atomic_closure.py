"""C12-P B5 + B6 — the atomic closure falsifiers (PREPARATION, uncommitted).

These are written to be **RED on the current candidate** and GREEN after the
combined B5+B6 landing. Each names the defect only it can catch.

WHY ONE FILE. B6 currently MASKS B5: the training/inference children are never
told where to write their runtime-observation sidecar, so `runtime_verification`
is `None`, so `_derive_calibration_from_observation` returns at its `if not
rv_block` guard and B5's mislabelled write never happens. Repairing B6 alone
arms B5. The two must land together, so their falsifiers live together.

REGISTRY ISOLATION. No test here deletes or inspects the operator's real
`~/.siderius` tree. `tests/conftest.py::_isolate_calibration_registry` is a
session-scoped autouse fixture that pins `SIDERIUS_CALIBRATION_DIR`; each test
below narrows that further to its own `tmp_path` so it can assert on exactly
what its own call wrote.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import core.sandbox_executor as se
import nodes.ml_hyperparameter_tune_agent as tuner
from core.runtime_control.calibration_registry import registry_dirname
from tests.helpers.hardware_profile_stub import stub_hardware_profile_collection

EXP_ID = "c12p_b5b6"
RUN_NAME = "c12p_b5b6_run"
MODEL_CFG = {"model_type": "fcnet", "segmentation_size": 10000, "latent_dims": [100, 10]}
TRAIN_CFG = {"lr": 1e-4, "epochs": 1, "batch_size": 1, "device": "cpu"}
LOSS_CFG = {"loss_type": "ce"}
WATCHDOG_POLICY = {"watchdog": {"enabled": True}}

TIDMAD_TASK_IDENTITY = "tidmad_denoise"


# ----------------------------------------------------------------------
# Shared fixtures
# ----------------------------------------------------------------------


@pytest.fixture
def registry_root(tmp_path, monkeypatch):
    """A private calibration root for this test only.

    Narrows the session-wide isolation fixture so an assertion about "what
    this call wrote" cannot read another test's records.

    `SIDERIUS_CALIBRATION_DIR` is a BASE directory, not a tree: the registry
    lands at `$DIR/runtime_calibration_v2` (`calibration_registry.py:83-90,
    114-116`). Returning the base would silently read an empty directory and
    make every "nothing was exported" assertion pass for the wrong reason.
    """
    base = tmp_path / "calib"
    monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(base))
    return base / registry_dirname()


def _eligible_observation() -> dict:
    """A CLEAN, calibration-eligible System-A observation.

    Shaped to pass `component_calibration_eligible`: eligible terminal
    status, no watchdog, no rejected admission, a steady-state measurement,
    and a `model_family` in `calibration_context` (without it the derivation
    quarantines for a reason unrelated to task identity, which would make
    these tests pass for the wrong reason).
    """
    return {
        "timestamp": "2026-08-24T00:00:00Z",
        # `observation_store._CALIBRATION_ELIGIBLE_STATUSES` == {"completed",
        # "inference_complete"}. Anything else is `NotDerivable` and writes
        # NOTHING AND PRINTS NOTHING (`runtime.py:1636-1637` is a silent
        # `continue`), which would make every assertion here pass vacuously.
        "final_status": "completed",
        "calibration_context": {"model_family": "fcnet"},
        "components": {
            "training": {
                "measurement": {
                    "unit": "optimizer_step",
                    "n_measured_units": 50,
                    "n_stabilization_units": 5,
                    "unit_time_ms_median": 12.5,
                    "steady_state_reached": True,
                    "total_measurement_seconds": 0.625,
                }
            }
        },
    }


def _device():
    d = MagicMock()
    d.uuid = "GPU-11111111-2222-3333-4444-555555555555"
    return d


def _foreign_profile():
    """A composed profile that declares NO TIDMAD topology (Pets-shaped)."""
    from execute_tools.dataset_config import DatasetProfile

    return DatasetProfile(
        partition_count=1,
        anchor_selection_files=[0],
        health_peek_files=[0],
        topology={"rows": {"count": 3669}},
    )


def _tidmad_profile():
    from execute_tools.dataset_config import resolve_dataset_profile

    return resolve_dataset_profile()


def _exported_task_identities(root) -> list[str]:
    """Every task identity this run exported as USABLE calibration evidence.

    Reads `observations/` only. A quarantined record lives in `quarantine/`
    and is structurally unable to reach a bucket or a promotion, so it is
    deliberately NOT counted as an export.
    """
    obs_dir = root / "observations"
    if not obs_dir.is_dir():
        return []
    out = []
    for p in sorted(obs_dir.glob("*.json")):
        payload = json.loads(p.read_text())
        identity = payload.get("identity") or {}
        out.append(identity.get("task_identity"))
    return out


class _Sandbox:
    base_dir = "/tmp"


# ======================================================================
# B5 — no foreign task may export TIDMAD-labelled calibration
# ======================================================================


class TestB5ForeignTaskMustNotExportTidmadIdentity:
    @pytest.fixture(autouse=True)
    def _stub_the_accelerator_probe(self, monkeypatch):
        """The derivation reads the live GPU; the unit layer must not.

        `_derive_calibration_from_observation` calls
        `collect_hardware_compatibility_profile()`, which raises
        `RuntimeError("hardware profile collection requires CUDA")` on a
        CPU-only host — which is every CI runner. The derivation's own broad
        `except` turns that into a non-fatal print, so on CI NOTHING below
        this line is ever written.

        That silently split this class in two: the three "TIDMAD still
        exports" cases went RED, and — the reason this fixture is autouse
        over the WHOLE class rather than applied to those three — the two
        "nothing was exported" cases went GREEN FOR THE WRONG REASON. Their
        registry was empty because the probe crashed, not because the guard
        under test refused. Verified by planting the B5 defect itself: with
        `_tidmad_calibration_identity_applicable` dropped from the guard,
        `test_a_composed_foreign_task_exports_no_tidmad_labelled_calibration`
        still PASSED on a CPU host. A skip would have made that permanent,
        disarming all five behavioural cases on exactly the machine CI runs.

        Only the accelerator read is stubbed. The registry, the identity
        construction, the eligibility policy and the on-disk write are the
        real production code — they are the subject.
        """
        stub_hardware_profile_collection(monkeypatch)

    def test_a_composed_foreign_task_exports_no_tidmad_labelled_calibration(
        self, registry_root, tmp_path
    ):
        """THE B5 DEFECT.

        `resolve_tidmad_measurement_capability` hardcodes
        `task_identity="tidmad_denoise"` and a TIDMAD-derived
        `data_shape_class`, and the wiring's guard
        (`if uuid and capability.task_identity and capability.data_shape_class`)
        is a TAUTOLOGY -- both fields are `Field(min_length=1)`, so neither can
        ever be falsy. A composed Pets/DAVIS run therefore writes a fully
        eligible calibration record claiming to be about TIDMAD.

        FAILS ON REGRESSION: a record with `task_identity == "tidmad_denoise"`
        appears in `observations/` for a run whose task declares no TIDMAD
        topology.
        """
        foreign_data_dir = str(tmp_path / "pets_root")
        os.makedirs(foreign_data_dir, exist_ok=True)

        tuner._derive_calibration_from_observation(
            _Sandbox(),
            rv_block=_eligible_observation(),
            device_identity=_device(),
            data_dir=foreign_data_dir,
            run_profile=_foreign_profile(),
        )

        exported = _exported_task_identities(registry_root)
        assert TIDMAD_TASK_IDENTITY not in exported, (
            f"a composed task that declares no TIDMAD topology exported "
            f"calibration labelled {TIDMAD_TASK_IDENTITY!r} into machine-global "
            f"state (identities written: {exported})"
        )

    def test_genuine_tidmad_calibration_still_exports(self, registry_root, tmp_path):
        """PRESERVATION. The bounded rule must not switch TIDMAD off.

        Regime A -- `run_profile=None` -- is an UN-COMPOSED run, which IS
        TIDMAD, so it stays applicable and its behaviour is bit-for-bit what
        it was.

        FAILS ON REGRESSION: a fail-closed rule written too broadly (e.g.
        gating on `probe_available`, or requiring a composed profile) silently
        stops TIDMAD exporting calibration at all.
        """
        data_dir = str(tmp_path / "tidmad_root")
        os.makedirs(data_dir, exist_ok=True)

        tuner._derive_calibration_from_observation(
            _Sandbox(),
            rv_block=_eligible_observation(),
            device_identity=_device(),
            data_dir=data_dir,
        )

        assert TIDMAD_TASK_IDENTITY in _exported_task_identities(registry_root), (
            "an un-composed (Regime A) run is TIDMAD and must still export its calibration evidence"
        )

    def test_a_composed_tidmad_task_still_exports(self, registry_root, tmp_path):
        """PRESERVATION, composed leg. A composed run whose profile DOES
        declare TIDMAD topology is genuinely applicable.

        FAILS ON REGRESSION: the applicability predicate keys on "is anything
        composed?" instead of "does this profile declare TIDMAD topology?".
        """
        data_dir = str(tmp_path / "tidmad_root2")
        os.makedirs(data_dir, exist_ok=True)

        tuner._derive_calibration_from_observation(
            _Sandbox(),
            rv_block=_eligible_observation(),
            device_identity=_device(),
            data_dir=data_dir,
            run_profile=_tidmad_profile(),
        )

        assert TIDMAD_TASK_IDENTITY in _exported_task_identities(registry_root)

    def test_absent_identity_still_fails_closed_to_quarantine(self, registry_root):
        """The EXISTING absence-is-first-class behaviour must survive.

        No device UUID => `identity=None` => `QuarantinedDerivation` => the
        separate `quarantine/` tree, never `observations/`.

        FAILS ON REGRESSION: someone "fixes" B5 by synthesizing an identity
        so the write can happen.
        """
        tuner._derive_calibration_from_observation(
            _Sandbox(),
            rv_block=_eligible_observation(),
            device_identity=None,
            data_dir=None,
        )
        assert _exported_task_identities(registry_root) == [], (
            "a measurement with no device identity must quarantine, never export"
        )

    def test_the_foreign_refusal_is_a_membership_test_not_a_caught_exception(self):
        """`tidmad_topology()` raises for ABSENT and for MALFORMED sections.

        Inferring "some other task" from catching its `ValueError` would
        silently reclassify a BROKEN TIDMAD declaration as inapplicable and
        skip an export that must instead be visible. Same rule the landed
        `wall_time_preflight_applicable` and `_has_scope_to_train_from` state.

        FAILS ON REGRESSION: the applicability decision is implemented as
        `try: tidmad_topology(...) except ValueError`.

        Scoped over the DEFINING MODULE, reached through the public re-export
        rather than by importing the node's private `runtime` module (the
        node public-boundary rule). Asserting only the deriver's own bytes
        would go green if the decision were delegated to a helper that
        catches the exception.
        """
        import inspect

        module_src = inspect.getsource(
            inspect.getmodule(tuner._derive_calibration_from_observation)
        )
        assert "declares_tidmad_topology" in module_src, (
            "the applicability decision must consume the landed membership "
            "predicate `execute_tools.dataset_config.declares_tidmad_topology`"
        )
        assert "except ValueError" not in inspect.getsource(
            tuner._derive_calibration_from_observation
        ), "a miss must be a membership test, never an exception to catch"

    def test_a_malformed_tidmad_profile_still_exports(self, registry_root, tmp_path):
        """Row 2 is not row 4. Sections PRESENT but payload broken is a BROKEN
        DECLARATION, not "some other task", so the run stays APPLICABLE and
        its calibration still carries TIDMAD's identity.

        Asserted behaviourally, through the production entry point, so it
        cannot pass by reading back a predicate's own return value.

        FAILS ON REGRESSION: the predicate is rewritten as a `try/except` over
        `tidmad_topology`, which conflates absent with malformed and would
        silently reclassify this profile as a foreign task.
        """
        from execute_tools.dataset_config import DatasetProfile

        malformed = DatasetProfile(
            partition_count=20,
            anchor_selection_files=[0],
            health_peek_files=[0],
            # All three sections PRESENT -- so `declares_tidmad_topology` is
            # True -- but the payload cannot satisfy the typed view.
            topology={"dataset": {}, "channels": {}, "encoding": {}},
        )
        data_dir = str(tmp_path / "tidmad_root3")
        os.makedirs(data_dir, exist_ok=True)

        tuner._derive_calibration_from_observation(
            _Sandbox(),
            rv_block=_eligible_observation(),
            device_identity=_device(),
            data_dir=data_dir,
            run_profile=malformed,
        )
        assert TIDMAD_TASK_IDENTITY in _exported_task_identities(registry_root)


class TestWhyTheGuardBelongsAtTheConsumer:
    """The bounded fix's BOUNDARY CONDITIONS — permanently true, by design.

    CORRECTION TO THE PREP ANALYSIS. These three were drafted as R-11-10
    "inverted guards" that would flip RED once B5 landed. **That prediction
    was wrong**, and the reason matters: they assert properties of
    `execute_tools/data_paths.py` and
    `core/runtime_control/measurement_capability.py`, and the bounded rule
    deliberately changes NEITHER. The producer stays unconditionally TIDMAD;
    the fix is at the CONSUMER, which is the only place that knows whose run
    this is.

    So they are not inverted guards and must not be retired. They are the
    standing explanation of why the guard could not have been placed in
    `resolve_tidmad_measurement_capability`, and they fail if someone
    "generalises" that producer to synthesize a foreign identity — which is
    exactly what the operator ruling forbids ("do NOT invent a generic
    measurement-identity capability family"; "never synthesize a foreign
    identity to make the write happen").
    """

    def test_the_capability_identity_is_hardcoded_tidmad_for_any_data_root(self, tmp_path):
        """`execute_tools/data_paths.py:265-271` stamps `tidmad_denoise` and
        TIDMAD's segment geometry regardless of which task's data root it is
        handed."""
        from execute_tools.data_paths import resolve_tidmad_measurement_capability

        foreign = tmp_path / "pets_root"
        foreign.mkdir()
        cap = resolve_tidmad_measurement_capability(dataset_root=str(foreign))
        assert cap.task_identity == TIDMAD_TASK_IDENTITY
        assert cap.data_shape_class.startswith("psd")

    def test_the_wiring_guard_is_a_tautology(self):
        """`if uuid and capability.task_identity and capability.data_shape_class`
        reduces to `if uuid:` — both fields are `Field(min_length=1)` on
        `ResolvedMeasurementCapability` and are populated on EVERY return
        path, refusals included (`measurement_capability.py:117-127`)."""
        from pydantic import ValidationError

        from core.runtime_control.measurement_capability import (
            ResolvedMeasurementCapability,
        )

        for blank in ("task_identity", "data_shape_class"):
            kwargs = {
                "task_identity": "t",
                "dataset_adapter": "a",
                "data_shape_class": "s",
                "probe_available": False,
                "unavailability_reason": "r",
            }
            kwargs[blank] = ""
            with pytest.raises(ValidationError):
                ResolvedMeasurementCapability(**kwargs)

    def test_probe_available_is_never_consulted_at_the_write_site(self):
        """The guard does not read `probe_available`, so a capability that
        REFUSED still yields a fully eligible (non-quarantined) identity."""
        import inspect

        src = inspect.getsource(tuner._derive_calibration_from_observation)
        assert "probe_available" not in src


# ======================================================================
# B6 — task/data-shape state must not gate task-neutral runtime safety
# ======================================================================


def _training_argv(sample_set, task_scopes, tmp_path):
    sb = se.TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)
    holder: dict = {}

    def _side(*args, **kwargs):
        holder["cmd"] = list(args[0])
        holder["kwargs"] = kwargs
        os.makedirs(sb.dirs["models"], exist_ok=True)
        open(os.path.join(sb.dirs["models"], f"_OK_{EXP_ID}"), "wb").close()
        r = MagicMock()
        r.returncode = 0
        r.stdout = "done"
        r.stderr = ""
        return r, None

    with (
        patch.object(se, "_run_observed_subprocess", side_effect=_side),
        patch.object(se, "task_scope_argv", return_value=[]),
        patch.object(se, "validation_rows_argv", return_value=[]),
    ):
        sb.execute_training(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            TRAIN_CFG,
            LOSS_CFG,
            sample_set=sample_set,
            runtime_policy=WATCHDOG_POLICY,
            task_scopes=task_scopes,
        )
    return holder


def _inference_argv(sample_set, task_scopes, tmp_path):
    sb = se.TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)
    cfg = sb.dirs["configs"]
    os.makedirs(cfg, exist_ok=True)
    os.makedirs(sb.dirs["models"], exist_ok=True)
    for name in (f"model_config_{EXP_ID}.json", f"loss_config_{EXP_ID}.json"):
        with open(os.path.join(cfg, name), "w") as fh:
            json.dump({}, fh)
    open(os.path.join(sb.dirs["models"], f"model_fcnet_{EXP_ID}_agent.pth"), "w").close()
    holder: dict = {}

    def _side(*args, **kwargs):
        holder["cmd"] = list(args[0])
        holder["kwargs"] = kwargs
        r = MagicMock()
        r.returncode = 0
        r.stdout = "done"
        r.stderr = ""
        return r, None

    with (
        patch.object(se, "_run_observed_subprocess", side_effect=_side),
        patch.object(se, "task_scope_argv", return_value=[]),
        patch.object(se, "validation_rows_argv", return_value=[]),
    ):
        sb.execute_inference(
            EXP_ID,
            RUN_NAME,
            "fcnet",
            MODEL_CFG,
            LOSS_CFG,
            sample_set=sample_set,
            runtime_policy=WATCHDOG_POLICY,
            task_scopes=task_scopes,
        )
    return holder


class _Scopes:
    """A composed run's acquired scopes. Only `.training` is read by the
    parent-side emitter, and only its PRESENCE decides transport."""

    training = object()
    evaluation = object()


class TestB6RuntimeMachineryIsArmedForAComposedRun:
    def test_the_composed_training_child_is_told_where_to_write_its_observation(self, tmp_path):
        """THE B6 DEFECT, training leg.

        `sample_set is not None` is used as an APPLICABILITY predicate at
        `core/sandbox_executor.py:1528`. A composed contrast run has
        `sample_set is None` BY CONSTRUCTION (`planning.py:511/551` builds one
        only when the profile `declares_physical_geometry`), so
        `--runtime_observation_out` is never emitted and no runtime session
        exists in either child.

        FAILS ON REGRESSION: the composed training argv carries no sidecar
        path, which silently disarms the whole runtime-control subsystem.
        """
        holder = _training_argv(None, _Scopes(), tmp_path)
        assert "--runtime_observation_out" in holder["cmd"]

    def test_the_composed_training_child_receives_its_runtime_policy(self, tmp_path):
        """FAILS ON REGRESSION: no in-subprocess admission decision is
        possible, so a composed attempt can never be rejected on time risk."""
        holder = _training_argv(None, _Scopes(), tmp_path)
        assert "--runtime_policy_json" in holder["cmd"]

    def test_the_watchdog_is_armed_for_a_composed_training_launch(self, tmp_path):
        """`--runtime_watchdog` is currently a COMPLETE no-op for a composed
        run: the deadline branch at `sandbox_executor.py:1611` also ANDs on
        `sample_set is not None`.

        FAILS ON REGRESSION: `_run_observed_subprocess` is called with no
        `deadline_provider`, so nothing can kill a runaway composed attempt.
        """
        holder = _training_argv(None, _Scopes(), tmp_path)
        assert holder["kwargs"].get("deadline_provider") is not None

    def test_the_composed_inference_child_is_told_where_to_write_its_observation(self, tmp_path):
        """Same defect, inference leg (`sandbox_executor.py:1919`)."""
        holder = _inference_argv(None, _Scopes(), tmp_path)
        assert "--runtime_observation_out" in holder["cmd"]

    def test_the_watchdog_is_armed_for_a_composed_inference_launch(self, tmp_path):
        """`sandbox_executor.py:1961`."""
        holder = _inference_argv(None, _Scopes(), tmp_path)
        assert holder["kwargs"].get("deadline_provider") is not None


class TestB6PreservedInvariants:
    """The predicate is `has a scope to launch from`, NOT `always`."""

    def test_a_legacy_single_file_launch_is_still_not_armed(self, tmp_path):
        """LEGACY single-file mode ALSO has `sample_set is None`, and the
        child's own `_has_scope_to_train_from` sends it to the legacy branch
        that supports no runtime session.

        FAILS ON REGRESSION: the fix is a blanket un-gating rather than the
        parent-side twin of `_has_scope_to_train_from`, so a legacy argv
        changes and every legacy-parity guard breaks.
        """
        holder = _training_argv(None, None, tmp_path)
        assert "--runtime_observation_out" not in holder["cmd"]
        assert holder["kwargs"].get("deadline_provider") is None

    def test_a_legacy_sample_set_launch_is_unchanged(self, tmp_path):
        """The un-composed TIDMAD argv must stay byte-identical in this
        family."""
        holder = _training_argv({0: [1, 2]}, None, tmp_path)
        assert "--runtime_observation_out" in holder["cmd"]
        assert holder["kwargs"].get("deadline_provider") is not None

    def test_train_portion_is_not_emitted_for_a_composed_contrast_run(self, tmp_path):
        """THE HOIST TRAP.

        `--train_portion` currently sits INSIDE the `sample_set is not None`
        block. `ExperimentPlan.train_portion` defaults to **0.1**
        (`agent/schemas/proposal.py:870`) and BOTH contrast packs refuse
        `< 1.0` by name (`pets_data_path.py:358`, `davis_data_path.py:429`).
        A naive hoist therefore converts a silent gap into a
        100%-reproducible crash on the FIRST attempt of every composed
        contrast run.

        FAILS ON REGRESSION: `--train_portion` is emitted on a composed argv,
        which is exactly the value the task's own scope authority refuses.
        """
        holder = _training_argv(None, _Scopes(), tmp_path)
        cmd = holder["cmd"]
        assert "--train_portion" not in cmd, (
            "the composed leg must not carry the legacy per-epoch subsample "
            "fraction: epoch sampling belongs to the task's own scope "
            "authority, which refuses a fraction it defines no rule for"
        )
