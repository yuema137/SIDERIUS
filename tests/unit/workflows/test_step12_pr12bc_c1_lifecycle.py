"""Step 12 / PR-12bc — C1: the run-scoped registration lifecycle.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §E.3, §M / C1; ledger §Q.C1.

The permanent owner of what C0's inverted guards (f12-3) and (f12bc-2) were
pointing at. Both were retired here rather than reshaped: each was written
around the code's SHAPE at C0 — one around the early return's condition, the
other around an except handler's body — and C1 fixed both defects with a
different shape. Asserting what the code must DO is the durable form.

The frozen §8 two-phase contract, in full::

    WITHIN an active run   same identity + same content  -> idempotent   (C1.1)
                           same id + DIFFERENT content   -> refuse       (C1.1)
                           a different roster mid-run    -> refuse       (C1.1)
    AFTER the run unwinds  a DIFFERENT roster is legal — no permanent
                           poisoning                                     (here)

**D-BC-3's scope, stated so the claim is not overread.** The overlay owns
run-scoped semantics *wherever multiple run scopes share an interpreter*.
Production today gets equivalent post-run isolation STRUCTURALLY — one process
per iteration — so it is neither "what production does" nor "test-only": it is
the same guarantee with a different owner. Concurrent in-process runs are OUT
OF SCOPE and fail closed.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest

# The built-ins' bootstrap, performed at COLLECTION time — deliberately, and
# not for tidiness. These modules register their implementations as an import
# side effect. A FIRST import that happens inside a test whose fixture has
# replaced `_REGISTRY` registers into the temporary dict, which is discarded on
# teardown — and the module is now in `sys.modules`, so it never registers
# again. Every later test in the process then sees a registry missing `tidmad`,
# and the failure surfaces in an unrelated module.
#
# Found exactly that way: C1 imported `tidmad_data_path` inside a test body,
# and `test_step10_p1_c3_transport.py` failed three modules later. Collection
# is the one moment guaranteed to precede every test.
import execute_tools.davis_data_path
import execute_tools.pets_data_path
import execute_tools.task_data_path as tdp
import execute_tools.tidmad_data_path
from execute_tools.task_data_path import (
    TaskDataPathRegistrationError,
    content_identity,
    register_task_data_path,
    registered_content_identity,
    registered_task_data_path_ids,
    registry_invariant_holds,
)
from execute_tools.task_registration_scope import (
    RegistrationScopeError,
    active_registration_scope,
    registration_rollback,
    run_registration_scope,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Both maps, always in lockstep — the C1.1 fragility, guarded here too."""
    monkeypatch.setattr(tdp, "_REGISTRY", {})
    monkeypatch.setattr(tdp, "_CONTENT", {})


def _impl(id_: str, *, cls_name: str = "Impl"):
    ns = {"task_data_path_id": id_}
    for method in (
        "training_dataset",
        "validation_dataset",
        "write_deliverable",
        "read_evaluation_payload",
    ):
        ns[method] = lambda self, *a, **k: None
    return type(cls_name, (), ns)()


# ======================================================================
# Content identity
# ======================================================================


class TestContentIdentity:
    def test_the_same_class_has_the_same_identity(self):
        cls = type(_impl("x"))
        assert content_identity(cls()) == content_identity(cls())

    def test_two_different_classes_do_not(self):
        assert content_identity(_impl("x", cls_name="A")) != content_identity(
            _impl("x", cls_name="B")
        )

    def test_a_file_backed_implementation_carries_its_SOURCE_digest(self):
        """The half that notices an EDIT. A qualname-only identity would call
        an edited plugin the same implementation.
        """
        from execute_tools.tidmad_data_path import TidmadTaskDataPath

        identity = content_identity(TidmadTaskDataPath())
        assert identity.startswith("execute_tools.tidmad_data_path.TidmadTaskDataPath@")
        assert len(identity.rsplit("@", 1)[1]) == 64

    def test_it_excludes_host_paths(self):
        """The health precedent's rule, one family over: two checkouts of the
        same package at different absolute paths are ONE identity, because
        they are the same scientific run.
        """
        from execute_tools.tidmad_data_path import TidmadTaskDataPath

        assert "/" not in content_identity(TidmadTaskDataPath()).rsplit("@", 1)[0]


# ======================================================================
# F-12bc-2 — rollback on a raising plugin
# ======================================================================


class TestRegistrationRollback:
    def test_a_block_that_raises_leaves_the_registry_UNCHANGED(self):
        before = set(registered_task_data_path_ids())
        with pytest.raises(RuntimeError, match="boom"), registration_rollback():
            register_task_data_path(_impl("c1_rollback_probe"))
            assert "c1_rollback_probe" in registered_task_data_path_ids()
            raise RuntimeError("boom")
        assert set(registered_task_data_path_ids()) == before
        assert registry_invariant_holds()

    def test_a_block_that_SUCCEEDS_keeps_what_it_registered(self):
        """Deliberately narrower than the run scope: a plugin that loads
        successfully registered something the run is meant to keep.
        """
        with registration_rollback():
            register_task_data_path(_impl("c1_kept_probe"))
        assert "c1_kept_probe" in registered_task_data_path_ids()

    def test_the_composition_loader_USES_it(self):
        """F-12bc-2 at its actual site. Asserted on the call, not on an except
        handler's body — C1's fix is a context manager around `exec_module`,
        which is why C0's shape-based guard could not see it.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        loader = src[src.index("def _load_symbol") : src.index("def _compose_task_data_path")]
        assert "with registration_rollback():" in loader
        assert "spec.loader.exec_module(module)" in loader

    def test_a_real_plugin_that_registers_then_raises_leaves_nothing_behind(self, tmp_path):
        """End to end through the production loader, not a simulation."""
        from workflows.task_composition import TaskCompositionError, _load_symbol

        plugin = tmp_path / "dirty_plugin.py"
        plugin.write_text(
            textwrap.dedent(
                """
                from execute_tools.task_data_path import register_task_data_path

                class _Impl:
                    task_data_path_id = "c1_dirty_plugin"
                    def training_dataset(self, scope, params): ...
                    def validation_dataset(self, scope, params): ...
                    def write_deliverable(self, outputs, request): ...
                    def read_evaluation_payload(self, request): ...

                register_task_data_path(_Impl())
                raise RuntimeError("this plugin fails AFTER registering")
                """
            ),
            encoding="utf-8",
        )
        before = set(registered_task_data_path_ids())
        with pytest.raises(TaskCompositionError, match="raised while importing"):
            _load_symbol({"file": str(plugin), "symbol": "_Impl"}, str(tmp_path), "task_data_path")
        assert set(registered_task_data_path_ids()) == before, (
            "the failed plugin's id is still registered — its id is now "
            "permanently taken by an implementation whose module never "
            "finished running"
        )
        assert registry_invariant_holds()


# ======================================================================
# The run-scoped overlay
# ======================================================================


class TestTheRunScopedOverlay:
    def test_registrations_made_inside_are_retired_on_unwind(self):
        before = set(registered_task_data_path_ids())
        with run_registration_scope():
            register_task_data_path(_impl("c1_scoped"))
            assert "c1_scoped" in registered_task_data_path_ids()
        assert set(registered_task_data_path_ids()) == before
        assert registry_invariant_holds()

    def test_it_retires_on_an_EXCEPTION_too(self):
        """Mirrors the ContextVar binding discipline: a run that crashed must
        not leave its roster behind for the next one.
        """
        before = set(registered_task_data_path_ids())
        with pytest.raises(RuntimeError), run_registration_scope():
            register_task_data_path(_impl("c1_crashed"))
            raise RuntimeError("boom")
        assert set(registered_task_data_path_ids()) == before

    def test_the_INHERITED_roster_survives(self):
        """Retiring is scoped to what the run ADDED. A run must not tear down
        registrations it did not make.
        """
        register_task_data_path(_impl("c1_inherited"))
        with run_registration_scope() as baseline:
            assert "c1_inherited" in baseline
            register_task_data_path(_impl("c1_added"))
        assert "c1_inherited" in registered_task_data_path_ids()
        assert "c1_added" not in registered_task_data_path_ids()

    def test_after_unwind_a_DIFFERENT_roster_is_legal(self):
        """The frozen contract's second phase, and the whole point: no
        permanent poisoning. The same id may be re-registered by a DIFFERENT
        implementation once the first run has ended — which within a run
        would refuse.
        """
        with run_registration_scope():
            register_task_data_path(_impl("c1_reused_id", cls_name="First"))
        with run_registration_scope():
            register_task_data_path(_impl("c1_reused_id", cls_name="Second"))
            assert "c1_reused_id" in registered_task_data_path_ids()

    def test_WITHIN_a_run_the_same_id_with_different_content_still_refuses(self):
        """The half that makes the half above safe."""
        with run_registration_scope():
            register_task_data_path(_impl("c1_conflict", cls_name="First"))
            with pytest.raises(TaskDataPathRegistrationError, match="DIFFERENT content"):
                register_task_data_path(_impl("c1_conflict", cls_name="Second"))

    def test_concurrent_in_process_scopes_FAIL_CLOSED(self):
        """Out of scope by ruling (D-BC-3). Two scopes sharing one registry
        would interleave each other's roster, and refusing is the honest
        answer rather than inventing a nested semantics.
        """
        with run_registration_scope():
            with pytest.raises(RegistrationScopeError, match="already open"):
                with run_registration_scope():
                    pass

    def test_no_scope_is_open_in_the_ordinary_production_state(self):
        """D-BC-3's honesty clause: production today gets its isolation from
        the process boundary, so no scope is open unless something opened one.
        """
        assert active_registration_scope() is None

    def test_the_two_maps_stay_in_lockstep_through_every_operation(self):
        assert registry_invariant_holds()
        with run_registration_scope():
            register_task_data_path(_impl("c1_lockstep"))
            assert registry_invariant_holds()
        assert registry_invariant_holds()


# ======================================================================
# F-12-3 — an edited plugin cannot run under a fresh identity
# ======================================================================


class TestF12_3EditedPluginRefuses:
    def test_the_registry_itself_refuses_the_edited_content(self):
        """The first line of defence, and the one a self-registering plugin
        meets: `register_task_data_path` compares content, so the edited
        module raises during `exec_module` and never reaches composition.
        """
        register_task_data_path(_impl("c1_edited", cls_name="Original"))
        with pytest.raises(TaskDataPathRegistrationError, match="DIFFERENT content"):
            register_task_data_path(_impl("c1_edited", cls_name="Edited"))

    def test_the_composer_states_the_check_at_its_own_early_return(self):
        """The second line, for a FACTORY plugin that does not self-register:
        the id matches, so the early return fires — and it now compares
        content before handing back the registered object.

        Stated at the composer too, deliberately: "the other function already
        checked" is exactly the kind of reasoning that decays.
        """
        src = (REPO_ROOT / "workflows" / "task_composition.py").read_text(encoding="utf-8")
        fn = src[src.index("def _compose_task_data_path") : src.index("def _compose_metric")]
        assert "registered_content_identity(declared)" in fn
        assert "content_identity(resolved)" in fn
        assert "would run the OLD code under" in fn

    def test_the_registered_identity_is_readable_for_the_comparison(self):
        register_task_data_path(_impl("c1_readable", cls_name="Readable"))
        assert registered_content_identity("c1_readable") is not None
        assert registered_content_identity("c1_absent") is None
