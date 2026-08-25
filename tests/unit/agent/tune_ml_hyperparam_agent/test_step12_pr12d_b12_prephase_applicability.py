"""Step 12 / PR-12d — B12 / F-12d-25: the pre-phase measurement's THIRD
applicability rule, and the four states the operator ruling requires it to
keep distinct.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-45 (the finding) and the
operator's B12 ruling of 2026-08-24 (option B, APPROVED, with boundaries).

**What was wrong.** The pre-phase GPU measurement worker builds a
deliberately-real batch through ``probe_batch.build_bounded_probe_batch``,
which is TIDMAD-physical: the ``abra_training_????.h5`` family,
``tidmad_topology(...).channels.input_channel``, h5py's group layout, and an
explicit refusal to fall back to synthetic data (F-1a). Pets and DAVIS have
no semantically valid input to that legacy probe, so a real composed Pets
launch died in the worker's ``setup`` phase and the tuner reported
``STOP_INFRASTRUCTURE_FAILURE`` — a claim that the ENVIRONMENT was broken
when the environment was healthy, the GPU present and the candidate
measurable.

**The ruling, and the line it draws.** This is NOT "the probe crashed so turn
the probe off". It is "this probe's INPUT CONTRACT is TIDMAD-only, so for a
task with no valid input, applicability must refuse to run it rather than
fabricate a TIDMAD input". The operator's boundaries are what these tests
enforce — in particular that **NOT_APPLICABLE and probe FAILURE stay two
different states**, so the rule can never become a way to make a Gate green
by measuring less.

Each test below names the defect only it can catch:

* ``TestTidmadRemainsApplicable`` — boundary 1. If this rule ever widened to
  swallow TIDMAD, the entire measurement subsystem would silently stop
  running on the one task it exists for, and every downstream admission
  decision would lose its evidence with nothing raising.
* ``TestContrastTasksAreNotApplicable`` — boundary 2. The regression itself.
* ``TestMalformedTidmadTopologyStillFailsClosed`` — boundaries 3 and 4, and
  the sharpest one. ``tidmad_topology()`` raises for TWO reasons; if the rule
  had been written as ``try: tidmad_topology(...) except ValueError: skip``,
  a profile whose sections are PRESENT but MALFORMED would be silently
  reclassified as "declares no topology" and its measurement skipped instead
  of failed. The membership test is what keeps those apart.
* ``TestIndependentEnforcementIsUntouched`` — boundary 5.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

import nodes.ml_hyperparameter_tune_agent as tuner
from core.runtime_control.gpu_accounting import DeviceIdentity

#: The node's package name is rebound to its main module, so the private
#: `runtime` module must be reached through importlib — the same hop
#: `test_prephase_measurement_reachability.py` makes for `records`.
_runtime = importlib.import_module("nodes.ml_hyperparameter_tune_agent.runtime")
from execute_tools.dataset_config import (
    DatasetProfile,
    declares_tidmad_topology,
    resolve_dataset_profile,
    tidmad_topology,
)
from nodes.ml_hyperparameter_tune_agent.runtime import PrephaseOutcome

DEVICE = DeviceIdentity(uuid="GPU-b12test", physical_index=0)

#: A composed CONTRAST profile: Q-12-4 generic identity, no TIDMAD sections.
#: Shaped like the ones `pets.yaml` / `davis.yaml` really resolve (the keys
#: are quoted from the real Pets failure artifact in D-12d-45).
CONTRAST_TOPOLOGY = {
    "class_cardinality": 37,
    "input_tensor": {"shape": [3, 144, 144], "dtype": "float32"},
    "modality": "image",
    "partition_unit": "image",
    "preprocessing": {"resize_shorter_side": 160, "center_crop": 144},
    "scope_authority": "manifest",
    "target": "breed_label",
}


def _contrast_profile() -> DatasetProfile:
    # `anchor_selection_files` / `health_peek_files` are non-empty because
    # `DatasetProfile` REFUSES an empty declaration ("an empty list does not
    # mean 'none' to any consumer — it falls through to a fallback"). That
    # validator is production doing its job; the fixture satisfies it rather
    # than working around it.
    return DatasetProfile(
        partition_count=4,
        topology=dict(CONTRAST_TOPOLOGY),
        anchor_selection_files=(0,),
        health_peek_files=(0,),
    )


def _malformed_tidmad_profile() -> DatasetProfile:
    """All three TIDMAD sections PRESENT, but the typed view rejects them.

    This is the profile the membership test must classify as *applicable*
    (so the worker runs and fails closed), and that a caught-exception
    implementation would have classified as *inapplicable*.
    """
    return DatasetProfile(
        partition_count=20,
        topology={
            "dataset": {"nonsense": True},
            "channels": {"nonsense": True},
            "encoding": {"nonsense": True},
        },
        anchor_selection_files=(0,),
        health_peek_files=(0,),
    )


class _Sandbox:
    def __init__(self, tmp_path) -> None:
        self.base_dir = str(tmp_path)
        self.device_identity = DEVICE


class _Input:
    data_dir = "/nonexistent"
    gpu_pair_ceiling_gib = 24.0
    candidate_id = None


def _call(tmp_path, **over):
    kwargs = dict(
        agent_input=_Input(),
        sandbox=_Sandbox(tmp_path),
        is_trial=False,
        active_params={
            "model_type": "punet",
            "model_config": {"segmentation_size": 40_000},
            "train_config": {"batch_size": 1, "optimizer_type": "adamw"},
            "loss_config": {"loss_type": "focal"},
            "run_name": "b12",
        },
        exp_id="exp-b12",
        model_type="punet",
        file_index=None,
        record_params={},
        expert_advice_str="",
        hypothesis="",
        round_index=0,
        attempt_in_round=0,
    )
    kwargs.update(over)
    return tuner._handle_prephase_gpu_measurement(**kwargs)


class _WorkerSpawned(BaseException):
    """Raised BY the stubbed worker to prove the spawn was reached.

    Deliberately a `BaseException` and deliberately not `pytest.raises`:
    an earlier draft wrapped the whole call in `pytest.raises(Exception)`,
    which silently swallowed a FIXTURE construction error and left the real
    assertion unreached. Recording the spawn and re-raising a private
    sentinel makes "did the worker get spawned" the only thing under test.
    """


def _spawn_recorder(spawned: list[str]):
    def _stub(*_a, **_k):
        spawned.append("spawned")
        raise _WorkerSpawned

    return _stub


def _call_expecting_spawn(tmp_path, **over) -> list[str]:
    """Call the boundary and report whether the worker was reached."""
    spawned: list[str] = []
    import core.runtime_control.gpu_measurement_runner as runner_mod

    original = runner_mod.run_prephase_measurement
    runner_mod.run_prephase_measurement = _spawn_recorder(spawned)
    try:
        _call(tmp_path, **over)
    except _WorkerSpawned:
        pass
    finally:
        runner_mod.run_prephase_measurement = original
    return spawned


# ======================================================================
# Boundary 1 — TIDMAD behaviour is unchanged
# ======================================================================


class TestTidmadRemainsApplicable:
    def test_the_shipped_tidmad_profile_declares_topology(self):
        assert declares_tidmad_topology(resolve_dataset_profile()) is True

    def test_regime_a_none_profile_stays_applicable(self, tmp_path):
        """`run_profile=None` is an UN-COMPOSED run, which IS TIDMAD. It must
        not take the inapplicable path — otherwise every legacy run silently
        stops being measured."""
        assert _call_expecting_spawn(tmp_path, run_profile=None) == ["spawned"], (
            "an un-composed (Regime-A) run must still reach the measurement worker"
        )

    def test_a_real_tidmad_profile_stays_applicable(self, tmp_path):
        assert _call_expecting_spawn(tmp_path, run_profile=resolve_dataset_profile()) == ["spawned"]


# ======================================================================
# Boundary 2 — the contrast tasks reach the NOT_APPLICABLE path explicitly
# ======================================================================


class TestContrastTasksAreNotApplicable:
    def test_a_contrast_profile_is_not_applicable_and_never_spawns(self, tmp_path):
        """The regression. Before B12 this raised inside the worker and was
        reported as STOP_INFRASTRUCTURE_FAILURE."""
        assert _call_expecting_spawn(tmp_path, run_profile=_contrast_profile()) == [], (
            "applicability must be decided BEFORE the worker is spawned — an "
            "inapplicable measurement opens no artifact (the Step 08a rule)"
        )
        assert _call(tmp_path, run_profile=_contrast_profile()) is PrephaseOutcome.PROCEED

    def test_it_says_so_out_loud(self, tmp_path, capsys):
        """An operator reading the log must be able to tell a skipped
        measurement from one that silently never happened."""
        _call(tmp_path, run_profile=_contrast_profile())
        out = capsys.readouterr().out
        assert "NOT APPLICABLE" in out
        assert "not a probe failure" in out


# ======================================================================
# Boundaries 3 + 4 — NOT_APPLICABLE is not FAILURE, and the difference is
# a membership test rather than a caught exception
# ======================================================================


class TestMalformedTidmadTopologyStillFailsClosed:
    def test_malformed_tidmad_sections_are_present_so_still_applicable(self):
        """The membership test says PRESENT..."""
        assert declares_tidmad_topology(_malformed_tidmad_profile()) is True

    def test_but_the_typed_view_rejects_them(self):
        """...while the typed decode RAISES. Two different reasons, and only
        the membership one may route to inapplicable."""
        with pytest.raises(ValueError):
            tidmad_topology(_malformed_tidmad_profile())

    def test_a_malformed_tidmad_profile_still_reaches_the_worker(self, tmp_path):
        """The load-bearing case. A `try/except ValueError -> skip`
        implementation would classify this as "declares no topology" and skip
        a measurement that must instead fail closed."""
        assert _call_expecting_spawn(tmp_path, run_profile=_malformed_tidmad_profile()) == [
            "spawned"
        ], (
            "a MALFORMED TIDMAD topology is an applicable task whose probe must "
            "run and fail — never an inapplicable one"
        )

    def test_the_rule_is_not_implemented_by_catching_the_decoder(self):
        """Structural. The production rule must ask the membership predicate;
        a caught `tidmad_topology` ValueError is exactly the conflation
        `declares_tidmad_topology`'s own docstring forbids."""
        src = inspect.getsource(_runtime._handle_prephase_gpu_measurement)
        assert "declares_tidmad_topology" in src
        assert "except ValueError" not in src


# ======================================================================
# Boundary 5 — independent enforcement is untouched
# ======================================================================


class TestIndependentEnforcementIsUntouched:
    def test_a_missing_measurement_is_an_already_supported_downstream_state(self):
        """Not a new state invented for B12: the requirement lookup already
        returns `(None, None)` when nothing was attached, so skipping the
        measurement cannot fail an unrelated gate closed."""
        from core.sandbox_executor import _phase_requirement

        class _Bare:
            pass

        assert _phase_requirement(_Bare(), "training") == (None, None)

    def test_the_vram_capacity_gate_is_not_referenced_by_this_rule(self):
        """Boundary 5 structurally: the applicability rule must not reach into
        the independent capacity gate to disable it."""
        src = inspect.getsource(_runtime._handle_prephase_gpu_measurement)
        head = src.split("import uuid as _uuid")[0]
        assert "run_production_preflight" not in head
        assert "vram_budget" not in head
