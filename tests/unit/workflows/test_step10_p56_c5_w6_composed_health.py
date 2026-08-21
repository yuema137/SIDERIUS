"""Step 10 / P5+P6 — C5 / **W6**: composed Health classification follows the run.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §22.4 (F-P56-2), §22.5
(IR-P56-2, operator-approved).

W6 completes C5's family of legacy-fallback removals:

    W4  no implicit legacy TIDMAD REFERENCE SCIENCE in composed mode
    W6  no implicit legacy TIDMAD HEALTH REQUIREMENTS in composed mode

**The defect.** Every downstream classifier reached
``resolve_scientific_gate_ids(None)``, which composes with ``LEGACY_OMITTED``
— the legacy TIDMAD task-health config. Merely READING gate roles therefore
bound TIDMAD's Health family process-globally, and the Step-08b run-scope
guard then correctly refused the composed run's OWN family. A composed Pets or
DAVIS run could not start at all.

**The fix, per the operator's ruling.** The run's Health declaration is
resolved **ONCE, at the composition edge**
(``resolve_run_scientific_gate_ids``) and consumed downstream as a RESOLVED
VALUE — never a config path a classifier re-loads, never an ambient binding,
never a task-identity branch, never an ordering workaround.

    composition edge  ->  resolves the declaration ONCE
    downstream        ->  consumes resolved required_gate_ids

The hard part of testing this is that "Pets can start now" is a SYMPTOM. A
classifier that simply stopped checking requirements would produce the same
green. So the load-bearing test here is
``TestTheClassifierActuallyConsumesTheResolvedSet``: feeding a Pets record the
TIDMAD gate set must change the verdict. If it does not, the value is being
threaded and ignored.
"""

from __future__ import annotations

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.candidate_eligibility import (
    classify_candidate_health,
    resolve_run_scientific_gate_ids,
    resolve_scientific_gate_ids,
)
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from execute_tools.health_checks.schemas import CandidateHealthValidity
from tests.unit.workflows.test_step10_p56_c0_three_task_baseline import FIXTURES
from workflows.task_composition import compose_run_task_bindings

#: Hand-written from the shipped declarations, NOT read back from the resolver.
EXPECTED_BLOCKING = {
    "tidmad": {
        "amplitude_collapse_blocking",
        "output_diversity_blocking",
        "output_std_blocking",
    },
    "pets": {"pets_distinct_symbols_blocking", "pets_dominant_fraction_blocking"},
    "davis": {"davis_dispersion_blocking"},
}


@pytest.fixture(autouse=True)
def _isolated_run_scope():
    """One process binds ONE Health plugin set; these tests bind several."""
    registry = dict(_REGISTRY)
    providers = dict(_PROVIDER_REGISTRY)
    _plugin_binding.reset_run_scope()
    try:
        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(registry)
        _PROVIDER_REGISTRY.clear()
        _PROVIDER_REGISTRY.update(providers)
        _plugin_binding.reset_run_scope()


def _binding(task: str):
    return compose_run_task_bindings(str(FIXTURES / task / "composition.yaml")).task_health_binding


def _record(gate_ids, *, passed=True):
    """A successful record carrying one gate result per id.

    The keys are the ones ``classify_candidate_health`` actually reads
    (``execution_status`` == ``"passed"`` AND ``check_passed`` is ``True``) —
    established from source, not guessed: a first draft used
    ``execution_status="completed"`` with a ``passed`` key and every record
    classified INVALID.
    """
    return {
        "status": "success",
        "denoising_score": -1.5,
        "health_gate_results": [
            {
                "gate_name": gid,
                "execution_status": "passed" if passed else "failed",
                "check_passed": passed,
                "action": "continue",
            }
            for gid in gate_ids
        ],
    }


# ---------------------------------------------------------------------------
# 1. Legacy parity — the half W6 must NOT change
# ---------------------------------------------------------------------------


class TestLegacyParity:
    def test_the_default_binding_is_byte_for_byte_the_legacy_resolution(self):
        """``LEGACY_OMITTED`` delegates to the untouched legacy resolver, so an
        un-composed run cannot have changed."""
        assert resolve_run_scientific_gate_ids() == resolve_scientific_gate_ids(None)
        assert resolve_run_scientific_gate_ids(
            HealthBindingState.LEGACY_OMITTED
        ) == resolve_scientific_gate_ids(None)

    def test_the_legacy_set_is_tidmads(self):
        assert resolve_scientific_gate_ids(None) == EXPECTED_BLOCKING["tidmad"]

    def test_a_none_requirement_still_means_resolve_the_legacy_default(self):
        """The classifier's own default is unchanged: ``required_gate_ids=None``
        is exactly the pre-W6 path, which is what keeps every un-composed
        caller — including the tuner's — working untouched."""
        record = _record(EXPECTED_BLOCKING["tidmad"])
        assert classify_candidate_health(record) is CandidateHealthValidity.VALID


# ---------------------------------------------------------------------------
# 2. Each composed task resolves ITS OWN declaration
# ---------------------------------------------------------------------------


class TestEachCompositionResolvesItsOwnHealthFamily:
    @pytest.mark.parametrize("task", ["tidmad", "pets", "davis"])
    def test_the_resolved_set_is_the_tasks_own(self, task):
        assert resolve_run_scientific_gate_ids(_binding(task)) == EXPECTED_BLOCKING[task]

    @pytest.mark.parametrize("task", ["pets", "davis"])
    def test_a_contrast_task_does_NOT_get_the_tidmad_default(self, task):
        """The C-P56-1 rule, for Health: no implicit legacy science."""
        resolved = resolve_run_scientific_gate_ids(_binding(task))
        assert resolved != EXPECTED_BLOCKING["tidmad"]
        assert not (resolved & EXPECTED_BLOCKING["tidmad"])

    def test_composed_tidmad_equals_legacy(self):
        """TIDMAD's composition names the SAME shipped declaration the legacy
        path resolves, so composing it changes nothing — which is why this
        defect stayed invisible until a contrast task was composed."""
        assert resolve_run_scientific_gate_ids(_binding("tidmad")) == resolve_scientific_gate_ids(
            None
        )


# ---------------------------------------------------------------------------
# 3. ANTI-VACUITY — the resolved set is actually consumed
# ---------------------------------------------------------------------------


class TestTheClassifierActuallyConsumesTheResolvedSet:
    """The operator's requirement, and the load-bearing test of W6.

    "Pets can start" would also be true of a classifier that stopped checking
    requirements altogether. These prove the threaded value CHANGES the verdict.
    """

    def test_a_pets_record_judged_against_pets_requirements_is_valid(self):
        record = _record(EXPECTED_BLOCKING["pets"])
        assert (
            classify_candidate_health(record, required_gate_ids=EXPECTED_BLOCKING["pets"])
            is CandidateHealthValidity.VALID
        )

    def test_the_SAME_pets_record_judged_against_TIDMAD_requirements_is_unknown(self):
        """Feeding the wrong family must change the answer.

        The Pets record carries Pets gate results; TIDMAD's required ids are
        not a subset of them, so the verdict is UNKNOWN — missing evidence,
        never a silent pass. If this returned VALID, the requirement set would
        be decorative.
        """
        record = _record(EXPECTED_BLOCKING["pets"])
        assert (
            classify_candidate_health(record, required_gate_ids=EXPECTED_BLOCKING["tidmad"])
            is CandidateHealthValidity.UNKNOWN
        )

    def test_the_mirror_case_davis(self):
        record = _record(EXPECTED_BLOCKING["davis"])
        assert (
            classify_candidate_health(record, required_gate_ids=EXPECTED_BLOCKING["davis"])
            is CandidateHealthValidity.VALID
        )
        assert (
            classify_candidate_health(record, required_gate_ids=EXPECTED_BLOCKING["tidmad"])
            is CandidateHealthValidity.UNKNOWN
        )

    def test_a_failed_required_gate_is_invalid_under_the_tasks_own_set(self):
        """The requirement set is not merely a presence check — the task's own
        gates still decide validity."""
        record = _record(EXPECTED_BLOCKING["pets"], passed=False)
        assert (
            classify_candidate_health(record, required_gate_ids=EXPECTED_BLOCKING["pets"])
            is CandidateHealthValidity.INVALID
        )


# ---------------------------------------------------------------------------
# 4. Sequential runs in one process do not contaminate each other
# ---------------------------------------------------------------------------


class TestSequentialRunsDoNotContaminate:
    """The failure class this finding was discovered in.

    The binding is PROCESS-GLOBAL, so "run A's Health family leaks into run B"
    is a real shape. Each ordering is driven explicitly rather than assumed
    symmetric.
    """

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("pets", "davis"),
            ("davis", "pets"),
            ("pets", "tidmad"),
            ("tidmad", "pets"),
            ("davis", "tidmad"),
        ],
    )
    def test_the_second_run_resolves_its_own_family(self, first, second):
        assert resolve_run_scientific_gate_ids(_binding(first)) == EXPECTED_BLOCKING[first]

        # The run boundary: a new process would start with a clean scope, and
        # `reset_run_scope` is the repository's test-only stand-in for it.
        _plugin_binding.reset_run_scope()

        assert resolve_run_scientific_gate_ids(_binding(second)) == EXPECTED_BLOCKING[second]

    def test_without_the_run_boundary_the_guard_still_refuses(self):
        """Anti-vacuity for the test above: the isolation is doing real work.

        Resolving a SECOND, different family without crossing a run boundary
        must still be refused — W6 removed an incorrect legacy default, it did
        NOT weaken the process-global invariant that one run evaluates one
        run's checks.
        """
        from execute_tools.health_checks._plugin_binding import HealthPluginRunScopeError

        resolve_run_scientific_gate_ids(_binding("pets"))
        with pytest.raises(HealthPluginRunScopeError):
            resolve_run_scientific_gate_ids(_binding("davis"))
