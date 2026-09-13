"""F-MEASCAP-1 — the measurement capability must follow the bound composition.

The launcher passed ``measurement_capability=resolve_tidmad_measurement_capability()``
twenty-one lines above ``task_composition=run_composition`` **in the same
``run_workflow(...)`` call**. One argument consulted the bound composition; its
neighbour was hardwired to TIDMAD and never looked at ``--task_composition``.

**Two defects wearing one symbol**, and the quiet one is why this is a blocker:

``anchor data ABSENT``
    the availability test (``torch`` + CUDA + ``os.path.isdir(root)``) fails and
    the launch is refused up front with ``LaunchGuardFailure``. **Loud and
    harmless** — and how the defect was found.

``anchor data PRESENT`` — every campaign host, and the qualification pods
    ``isdir`` succeeds, the capability reports itself AVAILABLE, and a composed
    non-TIDMAD run is admitted on the strength of a dataset it will never read.
    **Nothing refuses and nothing warns.**

So the load-bearing witness is
:meth:`TestComposedRunsCarryTheirOwnMeasurementIdentity.test_tidmad_data_present_does_not_make_a_composed_run_tidmads`:
TIDMAD data present AND a non-TIDMAD composition bound ⇒ the capability is
still the composed task's. That case had never been tested, in either
direction — no test in this repository had ever driven the launcher's
``main()`` with ``--task_composition`` at all, which is precisely how two
adjacent arguments in one call could disagree for as long as they did.

**Why the assertions are on IDENTITY and not on availability.** ``probe_available``
is a property of the MACHINE (CUDA present or not), and asserting it would pass
on a GPU box and fail on CI — the repository-portability defect the sibling
module ``test_measurement_capability_reachability`` already recorded against
itself. ``task_identity`` / ``dataset_adapter`` / ``dataset_root`` are populated
on EVERY return path of ``resolve_measurement_capability``, refusals included
(``Field(min_length=1)``), so identity is environment-independent and is the
thing the defect actually got wrong.
"""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch

import pytest

import workflows.run_one_iteration as runner
from tests.helpers.launcher_bindings import effective_workflow_kwargs

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: A SHIPPED non-TIDMAD manifest, driven through the launcher exactly as an
#: operator would drive it. Quickstart declares ``task_health: none`` and needs
#: no materialized data to compose, so these witnesses observe the capability
#: wiring rather than a Health roster or a dataset.
COMPOSED_MANIFEST = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"
COMPOSED_TASK_ID = "quickstart_tabular"

#: The adversarial fixture: a task SIDERIUS has never heard of — its id appears
#: in no framework source file, so a refusal that names it cannot have come
#: from a lookup that happened to know the answer.
FOURTH_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task" / "composition.yaml"
)
FOURTH_TASK_ID = "spectro_segmentation_v0"

#: What the hardwired call resolved to. Named here so the "not this" assertions
#: state the actual wrong answer rather than a paraphrase of it.
TIDMAD_TASK_IDENTITY = "tidmad_denoise"


@pytest.fixture(autouse=True)
def _leave_no_composition_residue():
    """Composing a manifest mutates TWO process-global structures. Undo both.

    These witnesses are about the LAUNCHER's wiring; registering a task data
    path and memoizing a task config are incidental side effects of composing
    a manifest in order to observe that wiring. A test that leaves them behind
    changes the result of whatever runs next, which is how an order-dependent
    failure gets born — so this module cleans up after itself rather than
    adding a new one.

    **The registry.** ``content_identity`` is
    ``module.qualname@sha256(source)``, and the module name of a
    ``file:``-declared plugin is derived from the LOGICAL REF that loaded it.
    So the same plugin file composed through a manifest at a different path is
    a different identity under the same id — ``register_task_data_path``'s
    "same id + DIFFERENT content" refusal, correctly fired. Restoring the
    snapshot means this module can never be the run that poisons another.

    This is NOT a reset that papers over a collision: the two-phase rule and
    its refusal are untouched, nothing is cleared mid-test, and no other
    module's reproducer is weakened. It removes only the residue this module
    itself created.

    **The task-config cache.** ``load_task_config`` memoizes per absolute
    path, process-wide — the same reason and the same remedy as the autouse
    fixture in ``tests/unit/workflows/test_step10_p1_c1_composition.py``.
    """
    from execute_tools import task_data_path as tdp
    from workflows.task_config import _clear_cache_for_tests

    registry_before = dict(tdp._REGISTRY)
    content_before = dict(tdp._CONTENT)
    _clear_cache_for_tests()
    try:
        yield
    finally:
        tdp._REGISTRY.clear()
        tdp._REGISTRY.update(registry_before)
        tdp._CONTENT.clear()
        tdp._CONTENT.update(content_before)
        _clear_cache_for_tests()
        assert tdp.registry_invariant_holds(), (
            "restoring the task-data-path registry left it inconsistent"
        )


class _StubResult:
    """Minimal ``HyperparamTuningOutput``-shaped object for ``write_manifest``."""

    def __init__(self, model_type: str) -> None:
        self.model_type = model_type
        self.best_denoising_score = 0.7
        self.completed_rounds = 1
        self.health_checks_config = None
        self.formal_reference_score = None
        self.resolved_skip_formal_threshold = None
        self.resolved_bypass_formal_threshold = None


def _capability_reaching_the_workflow(argv: list[str]) -> object:
    """Drive the launcher's REAL ``main()`` and return what the workflow got.

    Deliberately the production entry point rather than a direct call to the
    resolver: the defect was never in a resolver, it was in which resolver the
    call site chose. A test that called the new function directly would pass
    against the unfixed launcher.
    """
    argv = [
        "--run_name",
        "iter_001",
        "--healthgate_mode",
        "blocking",
        "--result_authority",
        "scientific",
        *argv,
    ]
    with patch("workflows.model_exploration.run_workflow") as mock_wf:
        mock_wf.return_value = [_StubResult("fmeascap1_arch")]
        with patch.object(
            runner,
            "write_manifest",
            return_value={
                "status": "completed",
                "model_name": "fmeascap1_arch",
                "best_score": 0.7,
                "output_path": "x",
            },
        ):
            with patch.object(sys, "argv", ["run_one_iteration.py", *argv]):
                try:
                    runner.main()
                except SystemExit as exc:  # pragma: no cover - diagnostic only
                    if exc.code not in (0, None):
                        raise AssertionError(
                            f"the launcher refused before reaching the workflow "
                            f"(exit {exc.code}); this witness cannot observe the "
                            f"capability unless main() gets that far"
                        ) from exc
        assert mock_wf.call_args is not None, "run_workflow was never called"
        return effective_workflow_kwargs(mock_wf.call_args)["measurement_capability"]


@pytest.fixture
def two_distinct_roots(tmp_path):
    """A TIDMAD root and a composed root that are BOTH real and NOT each other.

    Two directories, not one: with a single root every assertion about *which*
    dataset the capability describes would be satisfied by either answer, and
    the dangerous manifestation is exactly the case where TIDMAD's root is
    perfectly readable.
    """
    tidmad_root = tmp_path / "tidmad_anchor_data"
    composed_root = tmp_path / "spectro_task_data"
    tidmad_root.mkdir()
    composed_root.mkdir()
    return tidmad_root, composed_root


class TestComposedRunsCarryTheirOwnMeasurementIdentity:
    """Witnesses (a) and (b) — asserted at the workflow boundary."""

    def test_a_composed_non_tidmad_run_resolves_its_own_capability(
        self, tmp_path, two_distinct_roots
    ):
        """(a) MUTATION TARGET: restoring the hardwired call.

        The composed run declares ``quickstart_tabular``; the capability that
        reaches generic orchestration must say so. Before the fix it said
        ``tidmad_denoise`` and described TIDMAD's dataset.
        """
        _, composed_root = two_distinct_roots

        capability = _capability_reaching_the_workflow(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--start_iteration",
                "1",
                "--task_composition",
                str(COMPOSED_MANIFEST),
                "--data_dir",
                str(composed_root),
            ]
        )

        assert capability is not None, (
            "the launcher passed no capability at all; a real launch would "
            "abort with LaunchGuardFailure"
        )
        assert capability.task_identity == COMPOSED_TASK_ID, (
            f"the composed run's capability names {capability.task_identity!r}; "
            f"the run composed {COMPOSED_TASK_ID!r}"
        )
        assert capability.dataset_adapter == COMPOSED_TASK_ID
        assert capability.dataset_root == str(composed_root), (
            "availability was tested against a directory this run never binds"
        )

    def test_an_unrelated_dataset_does_not_change_the_composed_identity(
        self, tmp_path, two_distinct_roots
    ):
        """(b) THE DANGEROUS MANIFESTATION — the test that would have caught it.

        TIDMAD's dataset is present and readable, which on the unfixed code is
        precisely what makes the defect SILENT: ``isdir`` succeeds, the
        capability reports AVAILABLE, and the composed run is admitted against
        another task's geometry with nothing printed.

        ``resolve_tidmad_measurement_capability`` reads the module global at
        call time, so patching it here reproduces a campaign host exactly.
        """
        unrelated_root, composed_root = two_distinct_roots

        capability = _capability_reaching_the_workflow(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--start_iteration",
                "1",
                "--task_composition",
                str(COMPOSED_MANIFEST),
                "--data_dir",
                str(composed_root),
            ]
        )

        assert capability.task_identity != TIDMAD_TASK_IDENTITY, (
            "a composed non-TIDMAD run was given TIDMAD's measurement identity "
            "while TIDMAD's data happened to be present — the silent form of "
            "F-MEASCAP-1"
        )
        assert capability.task_identity == COMPOSED_TASK_ID
        assert capability.dataset_root != str(unrelated_root), (
            "the capability describes an unrelated dataset for a run that will never read it"
        )
        assert capability.dataset_root == str(composed_root)


class TestARefusalNamesTheComposedTask:
    """(d) When the composition cannot supply a root, say whose run failed."""

    def test_a_composed_run_without_a_root_refuses_by_name(self):
        """The refusal must name the COMPOSED task, never TIDMAD's dataset.

        The pre-fix launcher's refusal named TIDMAD's missing directory for a
        run that had composed something else entirely — an operator chasing a
        dataset their run never wanted. Identity is populated on every return
        path precisely so a refusal can say *which* task it could not measure.
        """
        from workflows.task_composition import (
            compose_run_task_bindings,
            resolve_composed_measurement_capability,
        )

        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        capability = resolve_composed_measurement_capability(composition, dataset_root=None)

        assert capability.probe_available is False
        assert (capability.unavailability_reason or "").strip(), (
            "a capability that switches itself off without a reason is the "
            "defect ResolvedMeasurementCapability exists to prevent"
        )
        assert capability.task_identity == FOURTH_TASK_ID, (
            "the refusal does not name the task that could not be measured"
        )
        assert TIDMAD_TASK_IDENTITY not in capability.detail
