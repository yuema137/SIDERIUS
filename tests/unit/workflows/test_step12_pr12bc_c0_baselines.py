"""Step 12 / PR-12bc — C0: Phase-C loading/lifecycle baselines and guards.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §E, §M / C0; ledger §Q.C0.

C0 changes **no production file**. It pins Phase C's starting behaviour and
makes its four defects executably visible first, so each later commit flips a
NAMED guard rather than asserting progress against nothing.

**Re-audited against the ACTUAL Phase-B implementation**, not pre-B source —
§F item 10, recorded at §Q.F. That audit found real drift: `_REGISTRY` moved
from `:219` to `:570` and the duplicate refusal from `:246-252` to `:599` as
Phase B added to `task_data_path.py`. **Every mechanism is unchanged**, so
every Phase-C finding stands; only the anchors moved. Nothing here asserts a
line number, for exactly that reason.

===========  ==================================================  ==========
guard        defect asserted PRESENT                             flips in
===========  ==================================================  ==========
(f12-3)      RETIRED at C1 — see the note below; the positive    RETIRED
(f12bc-2)    contracts live in
             ``test_step12_pr12bc_c1_lifecycle.py``
(oot)        an out-of-tree id fails closed in every child        C3
(f12bc-4)    the child-bootstrap census pins the import set       C3
             to exactly the three built-ins
===========  ==================================================  ==========

`TestPhaseCStructuralBaseline` is NOT inverted — it records the §J pre-values
for the functions Phase C touches, so C4/BC-FINAL can compare.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

from execute_tools.task_data_path import (
    TaskBindingContext,
    TaskDataPathRegistrationError,
    TaskDataPathResolutionError,
    register_task_data_path,
    registered_task_data_path_ids,
    resolve_task_data_path,
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))
from tests.unit.guardrails.test_step12_pr12a_c0_defect_baselines import (
    _qualified_functions,
    measure,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
COMPOSITION = REPO_ROOT / "workflows" / "task_composition.py"
DATA_PATH = REPO_ROOT / "execute_tools" / "task_data_path.py"


# ======================================================================
# (f12-3) the stale-instance early return
# ======================================================================


# Guards (f12-3) and (f12bc-2) were RETIRED at C1 (R-11-10).
#
# Both were shaped around the code as it looked at C0 — one around the early
# return's CONDITION, the other around the except handler's BODY — and C1
# fixed both defects with a different shape: the content comparison sits
# INSIDE the early-return block, and the rollback is a context manager around
# `exec_module` rather than a statement in the handler. So neither guard would
# have flipped, even though both defects are closed.
#
# That is the guards being too narrow, not the fixes being wrong, and the
# honest response is to replace them with the positive contracts rather than
# to reshape an inverted assertion until it fires. Those contracts live in
#
#     tests/unit/workflows/test_step12_pr12bc_c1_lifecycle.py
#
# which asserts what the code must DO, not what it must look like.

# ======================================================================
# (oot) an out-of-tree id fails closed
# ======================================================================


class TestTheRegistryResolverStillFailsClosed:
    """An id nobody registered is refused, naming what IS registered.

    Was `TestInvertedGuardOutOfTreeIdFailsClosed`, and it was never really
    inverted — C3 UPGRADED it rather than flipping it. The registry resolver
    keeps this exact behaviour; what C3 added is a row ABOVE it, in which a
    child may first compose the implementation from the transported manifest.
    This is the last row of that truth table and it must survive, or "not
    registered" would quietly become "compose anything you are handed".

    The second member was RETIRED — see the note below.
    """

    def test_an_unknown_id_is_refused_and_names_the_registered_set(self):
        with pytest.raises(TaskDataPathResolutionError) as exc:
            resolve_task_data_path(TaskBindingContext(task_data_path_id="c0_not_registered"))
        message = str(exc.value)
        assert "c0_not_registered" in message
        assert "Currently registered:" in message
        assert "never fall back" in message


# ======================================================================
# (f12bc-4) the child-bootstrap census
# ======================================================================
#
# **F-12bc-6 — the flip detector that never fired.**
#
# Two members were RETIRED at C4, and one of them is a finding rather than a
# tidy-up:
#
# `test_no_child_composes_a_data_path_from_a_manifest_today` searched each
# child for the string `_compose_task_data_path` — the PRIVATE composer — and
# carried the message "C3 has landed; retire this guard." C3 landed. It
# reached composition through the PUBLIC sibling `resolve_child_task_data_path`
# (D-BC-12), so the detector never fired, and its green result said the
# opposite of the truth.
#
# The lesson, recorded because it generalizes: a flip detector must assert the
# PROPERTY, not the symbol an unwritten implementation was expected to use.
# The corrected form asks *"can a child resolve an id it never imported?"* in a
# real fresh interpreter, which no choice of symbol can dodge:
#
#     tests/unit/guardrails/test_step12_pr12bc_c4_permanent_guards.py
#     ::TestAChildCanResolveWhatItNeverImported
#
# `test_a_child_today_can_ONLY_resolve_what_it_imported` was retired with it —
# its assertion is still true of the REGISTRY resolver and is kept above under
# an accurate name, but its own name asserts the defect C3 removed.
#
# `test_the_census_exists_and_pins_an_exact_set` is retired as pure
# indirection: the census it pointed at is executable and owns itself
# (`test_task_data_path_census.py`), and D-BC-9 records that it needed no
# extension — the composing route imports no task module at all.


# ======================================================================
# Registration lifecycle, as it behaves TODAY
# ======================================================================


class TestTheRegistrationLifecycleToday:
    """The two-phase contract's starting point, so C1's change is measurable."""

    def test_the_two_phase_registration_rule(self):
        """UPGRADED at C1 — C0 recorded the pre-C1 behaviour (ANY second
        registration refused) and C1 replaced it with the frozen §8 rule.
        Both halves asserted, because the second half is what makes the
        first one safe.
        """

        class _Impl:
            task_data_path_id = "c0_duplicate_probe"

            def training_dataset(self, scope, params): ...
            def validation_dataset(self, scope, params): ...
            def write_deliverable(self, outputs, request): ...
            def read_evaluation_payload(self, request): ...

        register_task_data_path(_Impl())
        register_task_data_path(_Impl())  # same content -> idempotent

        class _Other(_Impl):
            """Different implementation, same id."""

        with pytest.raises(TaskDataPathRegistrationError, match="DIFFERENT content"):
            register_task_data_path(_Other())

    def test_registration_is_process_global_and_monotonic(self):
        """The hazard in one sentence: what a run registers is still there
        after that run ends, because there is nowhere for it to go.
        """
        before = set(registered_task_data_path_ids())

        class _Impl:
            task_data_path_id = "c0_monotonic_probe"

            def training_dataset(self, scope, params): ...
            def validation_dataset(self, scope, params): ...
            def write_deliverable(self, outputs, request): ...
            def read_evaluation_payload(self, request): ...

        register_task_data_path(_Impl())
        assert set(registered_task_data_path_ids()) - before == {"c0_monotonic_probe"}
        # and it is STILL there — no scope ended, because none was ever opened
        assert "c0_monotonic_probe" in registered_task_data_path_ids()


# ======================================================================
# §J pre-values for the Phase-C surface
# ======================================================================

PHASE_C_STRUCTURAL_BASELINE: dict[str, tuple[int, int, int, int]] = {
    "workflows/task_composition.py::_compose_task_data_path": (19, 9, 63, 2),
    "workflows/task_composition.py::_load_symbol": (33, 13, 85, 3),
    "workflows/task_composition.py::bind_run_task_composition": (25, 4, 80, 2),
    "execute_tools/task_data_path.py::register_task_data_path": (11, 5, 26, 1),
    "execute_tools/task_data_path.py::resolve_task_data_path": (13, 4, 27, 1),
}

#: §J: "per-family composers stay <= the current largest; the overlay is its
#: own module, not a growth of the composer."
COMPOSITION_LOC_AT_C0 = 1475
MAX_BRANCH_GROWTH = 3
MAX_LOC_GROWTH = 80
MAX_PARAM_GROWTH = 1


def phase_c_current_structure() -> dict[str, tuple[int, int, int, int]]:
    out: dict[str, tuple[int, int, int, int]] = {}
    by_file: dict[str, list[str]] = {}
    for key in PHASE_C_STRUCTURAL_BASELINE:
        rel, name = key.split("::")
        by_file.setdefault(rel, []).append(name)
    for rel, names in by_file.items():
        fns = _qualified_functions(REPO_ROOT / rel)
        for name in names:
            if name in fns:
                out[f"{rel}::{name}"] = measure(fns[name])
    return out


class TestPhaseCStructuralBaseline:
    def test_every_baselined_function_still_exists(self):
        assert set(phase_c_current_structure()) == set(PHASE_C_STRUCTURAL_BASELINE)

    @pytest.mark.parametrize("key", sorted(PHASE_C_STRUCTURAL_BASELINE))
    def test_no_function_grew_past_its_budget(self, key):
        _, branch, loc, params = phase_c_current_structure()[key]
        _, base_branch, base_loc, base_params = PHASE_C_STRUCTURAL_BASELINE[key]
        assert branch - base_branch <= MAX_BRANCH_GROWTH, (
            f"{key} gained {branch - base_branch} branch nodes — that is a new "
            f"branch family. The overlay is its OWN module (§J), not a growth "
            f"of the composer."
        )
        assert loc - base_loc <= MAX_LOC_GROWTH
        assert params - base_params <= MAX_PARAM_GROWTH
