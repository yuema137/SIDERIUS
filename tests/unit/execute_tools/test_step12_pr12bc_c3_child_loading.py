"""Step 12 / PR-12bc — C3: a child can resolve an OUT-OF-TREE task.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12bc_generic_task_boundary_closure.md`` §E.1, §E.4, §M / C3; ledger §Q.C3
(D-BC-12, D-BC-9).

**The defect this closes.** A child resolved a transported `task_data_path_id`
through the registry, and the registry holds exactly what that child's
bootstrap imported — the three built-ins. So an externally declared
implementation resolved in the parent and was unresolvable in every child the
parent spawned. Nothing in the suite noticed, because every test that
exercised the transport used a built-in id.

The four-row table (§E.1)::

    transported id -> registry lookup
                      |- HIT  -> verify identity == parent-pinned
                      |           match     -> use it              (row 1)
                      |           divergent -> REFUSE              (row 2)
                      |- MISS -> compose from the transported manifest
                      |           through the SAME authority       (row 3)
                      '- neither registered nor composable -> REFUSE
                                  naming BOTH facts                (row 4)

Row 2 is not row 4. A divergent identity must never be re-composed as though
the id had simply been missing — that would turn C2's refusal into a fallback,
which is the C-P56-1 shape one layer down.
"""

from __future__ import annotations

import ast
import os
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
    TaskDataPathResolutionError,
    content_identity,
    register_task_data_path,
    registered_task_data_path_ids,
)
from workflows.task_composition import (
    TaskCompositionError,
    compose_task_data_path_from_manifest,
    resolve_child_task_data_path,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CHILDREN = (
    "execute_tools/train_engine_sandbox.py",
    "execute_tools/inference_single.py",
    "execute_tools/denoising_score_single.py",
)

#: The adversarial fourth task from Step 10 / P1 — a task SIDERIUS has never
#: heard of, declared entirely outside the framework. Reused deliberately
#: rather than hand-rolled: it is a COMPLETE manifest, and a complete manifest
#: is what a child actually receives. A partial one would have tested a shape
#: production never transports.
OUT_OF_TREE_ID = "spectro_segmentation_v0"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task"


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(tdp, "_REGISTRY", {})
    monkeypatch.setattr(tdp, "_CONTENT", {})


@pytest.fixture
def out_of_tree(tmp_path_factory):
    """The fourth task, copied OUTSIDE the repository AND outside the run
    workspace.

    Copied rather than referenced in place so the tests may edit it; placed
    away from the test's own `tmp_path` so it is not inside the sandbox
    workspace either. Nothing here may work by virtue of sitting next to
    production code or inside the run directory.
    """
    import shutil

    def _make():
        root = tmp_path_factory.mktemp("out_of_tree") / "fourth_task"
        shutil.copytree(FIXTURE, root)
        return root / "composition.yaml", root / "plugins" / "spectro_data_path.py"

    return _make


def _builtin(id_: str = "c3_builtin", *, cls_name: str = "Builtin"):
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
# The four rows
# ======================================================================


class TestRow1RegisteredAndMatching:
    def test_a_built_in_id_resolves_from_the_registry(self, out_of_tree):
        impl = _builtin()
        register_task_data_path(impl)
        manifest, _ = out_of_tree()
        # The manifest is present and is deliberately NOT consulted: a hit is
        # a hit, and re-composing on every resolve would make an unrelated
        # manifest error break a run that never needed it.
        assert (
            resolve_child_task_data_path(
                "c3_builtin",
                identity=content_identity(impl),
                manifest_path=str(manifest),
            )
            is impl
        )

    def test_it_resolves_with_no_manifest_at_all(self):
        """The un-composed run. Legacy behaviour, untouched."""
        impl = _builtin()
        register_task_data_path(impl)
        assert resolve_child_task_data_path("c3_builtin") is impl


class TestRow2RegisteredButDivergent:
    def test_a_divergent_identity_REFUSES(self):
        from execute_tools.task_data_path import TaskDataPathIdentityError

        register_task_data_path(_builtin(cls_name="Registered"))
        with pytest.raises(TaskDataPathIdentityError):
            resolve_child_task_data_path(
                "c3_builtin", identity=content_identity(_builtin(cls_name="Other"))
            )

    def test_a_divergent_identity_is_NOT_treated_as_a_MISS(self, out_of_tree):
        """Row 2 is not row 4, and the difference is load-bearing.

        If a divergent registration fell through to the composing row, C2's
        refusal would become a silent re-composition — the run would proceed
        under an implementation the parent never pinned, which is exactly the
        failure C2 exists to prevent. Asserted by giving the resolver a
        manifest it COULD compose and requiring it to refuse anyway.
        """
        from execute_tools.task_data_path import TaskDataPathIdentityError

        manifest, _ = out_of_tree()
        register_task_data_path(_builtin(id_=OUT_OF_TREE_ID, cls_name="Stale"))
        with pytest.raises(TaskDataPathIdentityError):
            resolve_child_task_data_path(
                OUT_OF_TREE_ID,
                identity="a_totally_different_identity",
                manifest_path=str(manifest),
            )


class TestRow3MissButComposable:
    def test_an_OUT_OF_TREE_implementation_resolves_in_a_child(self, out_of_tree):
        """The headline. Before C3 this raised `TaskDataPathResolutionError`
        in every child while the parent held the implementation happily.
        """
        manifest, _ = out_of_tree()
        assert OUT_OF_TREE_ID not in registered_task_data_path_ids()

        impl = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert impl.task_data_path_id == OUT_OF_TREE_ID
        assert type(impl).__name__ == "SpectroTaskDataPath"

    def test_composing_REGISTERS_it_so_later_resolves_hit(self, out_of_tree):
        """The composer's side effect is what makes the id usable for the rest
        of the child's life — a second resolve must not re-execute the plugin.
        """
        manifest, _ = out_of_tree()
        first = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert OUT_OF_TREE_ID in registered_task_data_path_ids()
        second = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert second is first, "the second resolve produced a DIFFERENT object"

    def test_the_composed_implementation_is_VERIFIED_against_the_parent_pin(self, out_of_tree):
        """An id the child composes itself is exactly as unproven as one it
        looked up. This is the row a naive implementation forgets, because
        "I just loaded it" feels like evidence.
        """
        from execute_tools.task_data_path import TaskDataPathIdentityError

        manifest, _ = out_of_tree()
        with pytest.raises(TaskDataPathIdentityError):
            resolve_child_task_data_path(
                OUT_OF_TREE_ID,
                identity="what_the_parent_actually_pinned",
                manifest_path=str(manifest),
            )

    def test_a_MATCHING_pin_on_a_composed_implementation_passes(self, out_of_tree):
        """The half that makes the refusal above meaningful — a parent-pinned
        identity taken from the same plugin must resolve, or C3 would refuse
        every real composed run.
        """
        manifest, _ = out_of_tree()
        pinned = content_identity(compose_task_data_path_from_manifest(str(manifest)))
        impl = resolve_child_task_data_path(
            OUT_OF_TREE_ID, identity=pinned, manifest_path=str(manifest)
        )
        assert impl.task_data_path_id == OUT_OF_TREE_ID


class TestRow4NeitherRegisteredNorComposable:
    def test_no_manifest_refuses_naming_BOTH_facts(self):
        with pytest.raises(TaskDataPathResolutionError) as exc:
            resolve_child_task_data_path("c3_nobody_registered")
        message = str(exc.value)
        assert "not registered in this child" in message
        assert "no task manifest was transported" in message
        assert "registered here:" in message, (
            "the refusal does not say what the child DOES hold — an operator "
            "cannot tell a bootstrap failure from a typo without it"
        )

    def test_a_manifest_declaring_a_DIFFERENT_id_refuses(self, out_of_tree):
        """Parent and child reading different declarations. Composing anyway
        would run a task the parent never bound.
        """
        manifest, _ = out_of_tree()
        with pytest.raises(TaskDataPathResolutionError) as exc:
            resolve_child_task_data_path("c3_some_other_id", manifest_path=str(manifest))
        message = str(exc.value)
        assert "c3_some_other_id" in message
        assert OUT_OF_TREE_ID in message

    def test_a_manifest_with_no_task_data_path_section_refuses(self, out_of_tree):
        manifest, _ = out_of_tree()
        text = manifest.read_text(encoding="utf-8")
        head, _, tail = text.partition("task_data_path:")
        manifest.write_text(head + tail.split("\n\n", 1)[1], encoding="utf-8")
        with pytest.raises(TaskCompositionError):
            resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))

    def test_an_unreadable_manifest_refuses_naming_the_path(self, tmp_path):
        missing = tmp_path / "absent.yaml"
        with pytest.raises(TaskCompositionError) as exc:
            resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(missing))
        assert str(missing) in str(exc.value)


# ======================================================================
# Edge cases the design named
# ======================================================================


class TestTheDeclaredEdgeCases:
    def test_refs_resolve_against_the_MANIFEST_dir_not_the_cwd(self, out_of_tree, monkeypatch):
        """§M / C3 edge case 3. A child's cwd is whatever the parent left it
        at; the manifest's own directory is the only stable anchor. Asserted
        from a directory that is neither the repo nor the manifest's.
        """
        manifest, _ = out_of_tree()
        elsewhere = manifest.parent.parent
        monkeypatch.chdir(elsewhere)
        assert os.getcwd() != str(manifest.parent)
        assert os.getcwd() != str(REPO_ROOT)

        impl = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert impl.task_data_path_id == OUT_OF_TREE_ID

    def test_a_RELATIVE_ref_inside_the_manifest_resolves_the_same_way(
        self, out_of_tree, monkeypatch
    ):
        """The manifest's ref is `plugins/spectro_data_path.py` — relative.
        Resolved against the cwd it would be found only by accident, and the
        repo root is the most dangerous accident because a same-named path
        could exist there.
        """
        manifest, _ = out_of_tree()
        assert "plugins/spectro_data_path.py" in manifest.read_text(encoding="utf-8")
        monkeypatch.chdir(REPO_ROOT)
        impl = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert impl.task_data_path_id == OUT_OF_TREE_ID

    def test_a_plugin_that_registers_then_FAILS_leaves_the_registry_clean(self, out_of_tree):
        """C1's rollback, reached through C3's route. The composing row runs
        arbitrary external code, so it is the most likely place for a
        half-registered id to survive.
        """
        manifest, plugin = out_of_tree()
        plugin.write_text(
            plugin.read_text(encoding="utf-8")
            + textwrap.dedent(
                """

                from execute_tools.task_data_path import register_task_data_path

                register_task_data_path(SpectroTaskDataPath())
                raise RuntimeError("this plugin fails AFTER registering")
                """
            ),
            encoding="utf-8",
        )
        before = set(registered_task_data_path_ids())
        with pytest.raises(TaskCompositionError):
            resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert set(registered_task_data_path_ids()) == before


# ======================================================================
# The parent side, and what must NOT have changed
# ======================================================================


class TestTheManifestNowReachesAllThreeChildren:
    def test_every_child_parses_the_manifest_flag(self):
        for child in CHILDREN:
            src = (REPO_ROOT / child).read_text(encoding="utf-8")
            assert '"--task_manifest"' in src, f"{child} cannot receive a manifest"

    def test_the_emitter_is_used_at_all_three_spawn_sites(self):
        """Training and inference gained it here; scoring had it since
        Step 11 C5. Counted rather than grepped, because "the helper exists"
        was true before C3 and the training child still never saw it.
        """
        tree = ast.parse((REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8"))
        uses = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_task_manifest_argv"
        ]
        assert len(uses) == 3, (
            f"the manifest reaches {len(uses)} spawn sites, not 3 — a child "
            f"that cannot read the run's declaration cannot resolve an "
            f"out-of-tree task the parent bound"
        )

    def test_it_is_still_emitted_only_when_composed(self):
        """R-11-1, unchanged: an un-composed run's argv gains nothing. The
        emitter is keyed on the binding, so all three sites inherit that.
        """
        src = (REPO_ROOT / "core" / "sandbox_executor.py").read_text(encoding="utf-8")
        fn = src[src.index("def _task_manifest_argv") : src.index("def _run_observed_subprocess")]
        assert 'return ["--task_manifest", bound] if bound is not None else []' in fn

    def test_the_un_composed_child_argv_gains_no_manifest_flag(self, tmp_path):
        from core.sandbox_executor import TidmadSandbox
        from tests.unit.workflows.test_step10_p1_c0_census import (
            capture_uncomposed_child_argv,
        )

        sandbox = TidmadSandbox(run_name="c3run", workspace=str(tmp_path), progress_bar=False)
        for phase, cmd in capture_uncomposed_child_argv(sandbox, tmp_path).items():
            assert "--task_manifest" not in cmd, (
                f"{phase} argv is no longer legacy-identical: {cmd}"
            )


class TestTheBootstrapSetIsAFloorNotACeiling:
    """D-BC-9. The bootstrap census pins the three built-ins EXACTLY, and read
    alone it invites the conclusion that those three are the only resolvable
    implementations — which is the opposite of this PR's claim.

    The census is right and stays; this states the other half, so the pair
    reads correctly: the bootstrap is what a child starts with, not what it is
    limited to.
    """

    def test_a_child_resolves_an_id_that_is_in_NO_bootstrap(self, out_of_tree):
        manifest, _ = out_of_tree()
        assert OUT_OF_TREE_ID not in {
            "tidmad",
            "oxford_iiit_pet",
            "davis_future_prediction",
        }
        impl = resolve_child_task_data_path(OUT_OF_TREE_ID, manifest_path=str(manifest))
        assert impl.task_data_path_id == OUT_OF_TREE_ID

    def test_the_composing_route_imports_no_task_module(self):
        """And it must stay that way: the route composes by PATH, so a fourth
        task needs no framework edit. An `import *_data_path` appearing here
        would mean the opposite.
        """
        fn = next(
            n
            for n in ast.walk(
                ast.parse((REPO_ROOT / "workflows" / "task_composition.py").read_text())
            )
            if isinstance(n, ast.FunctionDef) and n.name == "resolve_child_task_data_path"
        )
        for node in ast.walk(fn):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").endswith("_data_path") or (
                    node.module == "execute_tools.task_data_path"
                ), f"the child resolver imports a task implementation: {node.module}"


class TestTheHopEndToEnd:
    """The parent's REAL argv, parsed and resolved exactly as a child does.

    Step 10's C3 round trip proved the id survives the hop. It could not prove
    this, because it resolved a BUILT-IN id — the one case that works with no
    manifest at all. The whole C3 defect lived in the gap between those two
    facts, and only an out-of-tree id can see it.
    """

    def test_an_out_of_tree_task_survives_the_whole_hop(self, tmp_path, out_of_tree):
        import argparse
        import contextlib
        import io

        from core.sandbox_executor import TidmadSandbox
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG
        from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
        from tests.unit.workflows.test_step10_p1_c0_census import (
            capture_uncomposed_child_argv,
        )
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
        )

        manifest, _ = out_of_tree()
        composition = compose_run_task_bindings(str(manifest))
        sandbox = TidmadSandbox(run_name="c3hop", workspace=str(tmp_path), progress_bar=False)
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            vectors = capture_uncomposed_child_argv(sandbox, tmp_path)

        # Composing bound the implementation; a real child starts with only
        # its bootstrap, so drop it and make the child earn the resolution.
        parent_held = composition.task_data_path
        tdp._REGISTRY.clear()
        tdp._CONTENT.clear()

        parser = argparse.ArgumentParser()
        parser.add_argument(TASK_DATA_PATH_ARGV_FLAG, type=str, default=None)
        parser.add_argument("--task_data_path_identity", type=str, default=None)
        parser.add_argument("--task_manifest", type=str, default=None)

        for phase, cmd in vectors.items():
            with contextlib.redirect_stderr(io.StringIO()):
                known, _ = parser.parse_known_args(cmd)
            assert known.task_data_path_id == OUT_OF_TREE_ID, f"{phase} carried no id"
            assert known.task_manifest is not None, (
                f"the {phase} child received no manifest — it cannot compose an "
                f"implementation it does not have, and would fail closed on an "
                f"id the parent resolved successfully"
            )
            resolved = resolve_child_task_data_path(
                known.task_data_path_id,
                identity=known.task_data_path_identity,
                manifest_path=known.task_manifest,
            )
            assert resolved.task_data_path_id == parent_held.task_data_path_id
            # NOT `type(resolved) is type(parent_held)`: the child re-executed
            # the module, so it holds a distinct class object built from the
            # same source. In a real child process that is not a simulation
            # artefact — it is the normal case, because object identity cannot
            # cross a process boundary. Which is exactly why the pin is
            # CONTENT and not the object.
            assert content_identity(resolved) == content_identity(parent_held), (
                f"the {phase} child composed a DIFFERENT implementation than the parent bound"
            )
            assert known.task_data_path_identity == content_identity(parent_held), (
                f"the {phase} child's pin is not the parent's own identity"
            )
            tdp._REGISTRY.clear()
            tdp._CONTENT.clear()
