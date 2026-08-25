"""Step 12 / PR-12a — C3: the tuner's deliverable acquisition, PINNED.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C3 and §2.1 A-12a-1.

**No production logic changes in C3.** The parent's §4.1-R2 called the tuner's
deliverable-spec acquisition "unconditional TIDMAD" and assigned it to this PR;
this child's source audit found its NAMING half already closed by Step 11 C6.
So C3's job is to make that a pinned fact instead of a claim, and to correct
source prose that still describes the pre-C5/C6 world.

WHAT IS AND IS NOT CLOSED
-------------------------
* **NAMING — closed.** ``bind_run_task_composition`` enters
  ``bind_deliverable_naming`` when the task declared one, and
  ``derive_tidmad_deliverable_spec`` resolves the BOUND naming internally. The
  tuner's single acquisition site therefore already yields the declared naming
  on a composed run without a call-site change.
* **STORAGE — open, and NOT this PR's.** The spec's storage half (dtype,
  layout, channel-group identity) is still profile-derived. That is Q-12-4 /
  the ``DatasetProfile`` topology contract, owned by PR-12b.

The pin is deliberately paired: a differential on the RESOLUTION plus an AST
assertion that the tuner's acquisition site is still the expression this
differential evaluates. Either alone would rot — a resolution test that the
tuner had stopped calling, or a source assertion with no behavioural meaning.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composed_manifest import write_complete_manifest
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNER = REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"

#: A naming NO TIDMAD run could produce, so a fallback cannot masquerade as a
#: pass.
DECLARED_PREFIX = "pr12a_c3_declared_pred"


@pytest.fixture(autouse=True)
def _isolated_run_scope():
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


def _acquire_as_the_tuner_does():
    """Evaluate the tuner's acquisition expression, in the caller's binding.

    This is the exact pair of lines the tuner runs at its single acquisition
    site; `test_the_tuner_still_acquires_it_this_way` is what keeps that true.
    """
    from execute_tools.dataset_config import resolve_dataset_profile
    from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec

    return derive_tidmad_deliverable_spec(resolve_dataset_profile())


class TestComposedDeliverableNaming:
    def test_a_declared_naming_reaches_the_tuners_acquisition(self, tmp_path):
        """A-12a-1: already true via Step-11 C6's bound authority. Pinned here
        because 'already closed' is the reason this PR does NOT implement it,
        and an unpinned reason is how a closure silently reopens."""
        manifest = write_complete_manifest(tmp_path, deliverable={"prefix": DECLARED_PREFIX})
        composition = compose_run_task_bindings(str(manifest))
        assert composition.deliverable_naming is not None

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            spec = _acquire_as_the_tuner_does()

        assert spec.naming.prefix == DECLARED_PREFIX

    def test_an_un_declared_composition_keeps_the_shipped_naming(self, tmp_path):
        """LEGACY PARITY inside composed mode: declaring no `deliverable:`
        section must resolve the shipped TIDMAD naming byte-identically, or
        every existing composed run's cleanup glob would move."""
        manifest = write_complete_manifest(tmp_path)
        composition = compose_run_task_bindings(str(manifest))
        assert composition.deliverable_naming is None

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            spec = _acquire_as_the_tuner_does()

        assert spec.naming.prefix == "abra_validation_denoised"

    def test_an_un_composed_run_keeps_the_shipped_naming(self):
        assert _acquire_as_the_tuner_does().naming.prefix == "abra_validation_denoised"

    def test_the_tuner_still_acquires_it_this_way(self):
        """Reachability. The differential above evaluates an expression; this
        asserts the tuner still evaluates the SAME one, so the pin cannot
        quietly become a test of an unused code path."""
        tree = ast.parse(TUNER.read_text(encoding="utf-8"))
        acquisitions = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("derive_run_deliverable_spec", "derive_tidmad_deliverable_spec")
        ]
        assert len(acquisitions) == 1, (
            "the tuner must have exactly ONE deliverable acquisition site; a "
            "second one is how a rename moves some artifacts and not others."
        )
        # Step 12 / PR-12d seam B (B11): the tuner now calls
        # `derive_run_deliverable_spec`, which answers `None` for a task that
        # declares no TIDMAD storage geometry and is otherwise the SAME
        # derivation (pinned by D2's differential oracle). The ARGUMENT is
        # still asserted -- a spec derived from anything other than the run's
        # own profile is the defect this reachability test exists for -- but
        # the exact `ast.unparse` STRING is not, because renaming a local
        # would turn it RED with no semantic change.
        assert acquisitions[0].func.id == "derive_run_deliverable_spec"
        assert [ast.unparse(arg) for arg in acquisitions[0].args] == ["run_profile"]
        assert acquisitions[0].keywords == []


class TestTheStorageHalfIsStillProfileDerived:
    """The other half of A-12a-1, asserted so the PR's honesty is executable:
    C3 pins the naming closure and claims NOTHING about storage, which is
    Q-12-4 / PR-12b's.
    """

    def test_storage_comes_from_the_profile_not_a_declaration(self, tmp_path):
        manifest = write_complete_manifest(tmp_path, deliverable={"prefix": DECLARED_PREFIX})
        composition = compose_run_task_bindings(str(manifest))

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            spec = _acquire_as_the_tuner_does()

        # The declaration moved the NAME; the storage representation is still
        # whatever the dataset profile says.
        assert spec.naming.prefix == DECLARED_PREFIX
        assert spec.storage is not None
