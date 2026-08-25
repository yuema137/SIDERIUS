"""Step 10 / P5+P6 — C0: what a COMPOSED run does today, per task.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §13 C0, §2.5, §10.5 (W4).

Two baselines C5/C6 flip.

**A. The composed loop drive.** §2.5 measures that **no real composed chain run
has ever executed**: `configs/task_composition/` does not exist, the chain
launcher cannot forward `--task_composition`, and P2b's "three-task closure"
drove the tuner, not `run_workflow`. These drives are the first time all three
compositions traverse `run_workflow` itself, and they record TODAY's behaviour
— per C0's rule, *"if a drive cannot complete today, record the exact failure
point as the baseline instead (an honest baseline is whatever today does)"*.

**B. The W4 reference-score leak (§2.5 W4, §10.5).**
`load_reference_scores()` is called unconditionally by the tuner
(`ml_hyperparameter_tune_agent.py:795`) with no composition guard. Its
`_fine_indices()` derives the file count from the RESOLVED Dataset Profile, and
both contrast fixtures declare fewer files than TIDMAD ships references for
(Pets 4, DAVIS 3, TIDMAD 20). So the call **silently succeeds** under a Pets or
DAVIS composition and injects TIDMAD's `s_max`, raw-baseline and ground-truth
numbers into that run's prompt tables — *silent wrong science, not a crash*,
exactly as §2.5 W4 states. This is the before-picture for **C-P56-1**: after
C5, ANY composed run carries a named absence instead.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"

#: Declared file counts, hardcoded from the fixture profiles — NOT read back
#: from the code under test. TIDMAD ships 20 per-file reference artifacts.
#: Step 12 / PR-12d D5 MOVED the Pets entry 4 -> 370, with this reason: the
#: fabricated fixture profile that declared 4 HDF5 shards is deleted, and the
#: shipped Pets profile declares its real index domain — the 370 rows of the
#: Gate manifest its scope capability samples. DAVIS' 3 is still the
#: fabricated fixture value and moves at D6.
DECLARED_NUM_FILES = {"tidmad": 20, "pets": 370, "davis": 3}
TIDMAD_REFERENCE_FILES = 20


@pytest.fixture(autouse=True)
def _isolated_registries_and_run_scope():
    """One process may bind exactly ONE Health plugin set (Step 08b).

    **Diagnosed, not worked around.** Binding a second composition's Health
    family in the same process raises ``HealthPluginRunScopeError`` — a CORRECT
    production guard ("Health check registration is process-global, so
    continuing would let this run evaluate checks registered by the previous
    one"). In production one process is one run is one composition; only a test
    driving three tasks in one pytest process meets it. The repository ships
    ``_plugin_binding.reset_run_scope()`` for exactly this, documented
    *"Test-only — never call from production"*, and the established fixture
    shape is copied verbatim from ``tests/unit/examples/test_pets_health_family.py``
    :76-89 (see also ``tests/unit/guardrails/test_health_core_census.py``:30,
    which drives several task families in one module the same way).

    **This is a binding constraint on C6**: the ONE parametrized three-task
    driver must reset the run scope between tasks, or it will pass only for
    whichever task happens to run first.
    """
    registry_snapshot = dict(_REGISTRY)
    provider_snapshot = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry_snapshot)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(provider_snapshot)
        _plugin_binding.reset_run_scope()


def _composition(task: str):
    return compose_run_task_bindings(str(FIXTURES / task / "composition.yaml"))


def _drive_composed_loop(task: str, tmp_path):
    """Drive ONE `run_workflow` iteration under `task`'s composition.

    Returns ``(results, interp_inputs)`` on success. Any exception propagates —
    C0 records the failure point rather than hiding it.
    """
    composition = _composition(task)
    # Step 11 C8 / R-11-9 — a COMPOSED drive must seed evidence it can
    # certify as its own; an unstamped seed is refused by design.
    _write_tuning_output(tmp_path, "punet", fingerprint=composition.semantic_fingerprint)

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockPropose.return_value.run.return_value = _make_proposal_output("model_a")
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type, score=1.6
        )

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            results = run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=1,
                ),
                workspace=str(tmp_path / "workflow_output"),
                run_name=f"p56_c0_{task}",
                task_composition=composition,
            )
        return results, [c[0][0] for c in MockInterp.return_value.run.call_args_list]


# ---------------------------------------------------------------------------
# A. The composed loop drive — today's behaviour, recorded
# ---------------------------------------------------------------------------


class TestComposedLoopDriveBaseline:
    """BASELINE. C6 turns these into the three-task ORCHESTRATION closure
    (§10.3) — one parametrized driver, direction/secondaries/Health/carried
    state asserted per task. Here we only record what the composed loop does
    TODAY, including where it stops."""

    def test_composed_tidmad_completes_one_iteration_today(self, tmp_path):
        """TIDMAD composes and traverses the loop already."""
        results, interp_inputs = _drive_composed_loop("tidmad", tmp_path)
        assert len(results) == 1
        assert len(interp_inputs) == 1

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_a_composed_contrast_run_no_longer_dies_on_the_legacy_health_binding(
        self, task, tmp_path
    ):
        """**FLIPPED BY C5 / W6** (finding F-P56-2, ruling IR-P56-2).

        WAS: a composed Pets/DAVIS run could not start AT ALL — this test
        asserted ``pytest.raises(HealthPluginRunScopeError)``. The ordering
        that caused it, preserved because it is the whole reason W6 exists:

            run_workflow:1729   Step 0 loads existing tuning outputs
              -> tuning_output_to_model_run_summary
              -> classify_candidate_health
              -> resolve_scientific_gate_ids(config_path=None)
              -> load_health_gates_config(None)
              -> load_composed_health_config(None)      # NO task binding
              -> _load_task_binding(LEGACY_OMITTED)
              => binds TIDMAD's configs/task_health/tidmad.yaml, plugins ()

            run_workflow:1786   build_run_invariants FINALLY passes the
                                composition's task_health_binding
              => the task's OWN plugin set is requested
              => HealthPluginRunScopeError: refused

        The run-scope guard is CORRECT — it is the Step-08b invariant that one
        process evaluates one run's checks. The defect is that generic core
        resolves the LEGACY (TIDMAD) task-health binding at Step 0, before the
        composition is ever consulted. It is latent for an un-composed run
        (both resolutions are TIDMAD's, plugins `()` both times, so the
        idempotent branch is taken) and for composed TIDMAD (same file, same
        canonical identity) — which is why nothing caught it until a contrast
        task was composed through the real loop.

        This is the **same family as W4**: generic core implicitly resolving
        TIDMAD science in a composed run.

        NOW: W6 resolves the run's Health declaration ONCE at the composition
        edge, so the run's own family is the first (and only) one bound and the
        later materialisation is idempotent. The Health barrier is gone.

        This test owns exactly that — the ABSENCE of the legacy-binding
        failure. It deliberately does NOT assert the drive completes: these
        C0 fixtures seed a TIDMAD-scored tuning output, which a composition
        declaring `accuracy`/`mse` correctly refuses to reconcile (P2a). C6
        owns the full drives, with composition-consistent inputs.
        """
        from execute_tools.health_checks._plugin_binding import HealthPluginRunScopeError

        try:
            _drive_composed_loop(task, tmp_path)
        except HealthPluginRunScopeError as exc:  # pragma: no cover - the flip
            pytest.fail(
                f"W6 regressed: the composed {task} run still dies on the legacy "
                f"Health binding — {exc}"
            )
        except Exception:
            # Any OTHER failure is out of this test's scope; the run got past
            # the Health barrier, which is the property W6 owns.
            pass

    @pytest.mark.parametrize("task", ["tidmad", "pets", "davis"])
    def test_the_composition_actually_bound_its_own_metric(self, task, tmp_path):
        """Anti-vacuity for the drives above: prove each composition really
        resolves — so the Pets/DAVIS failure above is a LOOP-wiring defect,
        not an unresolvable manifest."""
        from execute_tools.evaluation_metric import resolve_bound_run_metric

        composition = _composition(task)
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            bound = resolve_bound_run_metric()
            assert bound is not None
            assert bound.spec.id == composition.metric.spec.id


# ---------------------------------------------------------------------------
# B. The W4 reference-score leak
# ---------------------------------------------------------------------------


class TestTidmadReferenceScoresLeakIntoComposedRuns:
    """BASELINE — the C-P56-1 before-picture. **FLIPPED BY C5.**

    Note the guard C5 must implement keys on composition PRESENCE, never on
    `TIDMAD_METRIC_ID` or any other task-identity surrogate (§10.5, §19.3).
    """

    def test_a_composed_davis_run_silently_loads_tidmad_reference_science(self):
        """THE DEFECT: no crash, no warning — TIDMAD's numbers, in a DAVIS
        run's prompt tables."""
        from nodes.scoring_reference import load_reference_scores

        with bind_run_task_composition(
            _composition("davis"), physical_data_root=COMPOSED_TEST_DATA_ROOT
        ):
            refs = load_reference_scores(use_cache=False)

        # It succeeded, and every number it returned is TIDMAD's.
        assert refs.s_max > 0
        assert len(refs.raw_per_file_log) == DECLARED_NUM_FILES["davis"]
        assert len(refs.gt_per_file_log) == DECLARED_NUM_FILES["davis"]

    def test_a_composed_pets_run_now_loads_them_LOUDLY_instead(self):
        """The SAME defect, wearing the other of its two faces.

        This case used to be parametrized alongside DAVIS and asserted the
        SILENT outcome. Step 12 / PR-12d D5 gave Pets its honest 370-partition
        index domain, and the sibling test below already named what that would
        do: *"a task declaring MORE than 20 would have crashed instead"*. It
        does — `_fine_indices()` walks past `raw_baseline_score_file_0019` and
        `FileNotFoundError` names the TIDMAD artifact a Pets run has no
        business reading.

        Kept, rather than deleted with the silent case, because the two faces
        of this leak are exactly why the C5 guard may not key on file counts:
        loud and silent are both wrong, and only removing the call from
        composed runs fixes either. Fails if someone "repairs" this by making
        `load_reference_scores` tolerate a missing reference file — which
        would restore the silent leak for every task at once.
        """
        from nodes.scoring_reference import load_reference_scores

        with bind_run_task_composition(
            _composition("pets"), physical_data_root=COMPOSED_TEST_DATA_ROOT
        ):
            with pytest.raises(FileNotFoundError, match="raw_baseline_score_file_0020"):
                load_reference_scores(use_cache=False)

    def test_the_leak_takes_ITS_SHAPE_from_the_declared_partition_count(self):
        """WHY it is silent for one task and loud for the other — the fact the
        C5 guard must not depend on.

        `_fine_indices()` derives the count from the resolved profile. DAVIS
        declares FEWER partitions than TIDMAD ships references for, so every
        lookup hits an existing TIDMAD artifact; Pets now declares MORE, so
        the walk runs off the end. Neither outcome is acceptable; C5 removes
        the call from composed runs entirely, and does it by keying on
        composition PRESENCE rather than on any count.
        """
        assert DECLARED_NUM_FILES["davis"] < TIDMAD_REFERENCE_FILES
        assert DECLARED_NUM_FILES["pets"] > TIDMAD_REFERENCE_FILES
        assert DECLARED_NUM_FILES["tidmad"] == TIDMAD_REFERENCE_FILES

    def test_an_uncomposed_run_loads_them_too_and_must_keep_doing_so(self):
        """The OTHER half of C-P56-1: the legacy/un-composed path is preserved
        byte-for-byte. Recorded here so C5's change is provably one-sided."""
        from nodes.scoring_reference import load_reference_scores

        refs = load_reference_scores(use_cache=False)
        assert len(refs.raw_per_file_log) == TIDMAD_REFERENCE_FILES
        assert len(refs.gt_per_file_log) == TIDMAD_REFERENCE_FILES
