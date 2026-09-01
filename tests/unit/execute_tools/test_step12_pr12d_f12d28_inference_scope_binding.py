"""Step 12 / PR-12d — F-12d-28: the inference child RESOLVED its task data
path but never BOUND it, so it deserialized the scope with the wrong task.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-53.

**The defect, first observed in a real composed external-task run:**

```text
File "execute_tools/inference_single.py", line 743, in main
File "execute_tools/scope_artifact.py", line 249, in load_transported_scope
File "execute_tools/tidmad_data_path.py", line 467, in deserialize_scope
ValueError: scope payload declares a kind owned by another task
  — the binding and the scope object must come from the same task.
```

That message is **PR-12bc's pairing-gap guard firing correctly, one child
over**. 12bc closed the case where the BINDING crossed and the SCOPE did not;
this is the mirror — the scope crossed, and the binding did not.

**Resolving is not binding.** `inference_single.main` computed
`data_path = resolve_child_task_data_path(...)` and held it in a local, then
called `load_transported_scope`, which delegates to whichever implementation
is **ACTIVE**. With nothing bound, that is the registered TIDMAD one, which
refused the composed payload by name. The training child had this right all
along — its `main` deserializes the scope inside that binding — so
the asymmetry — not the concept — was the defect.

Each test names a defect only it can catch.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
QUICKSTART_MANIFEST = str(REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml")


@pytest.fixture
def task_scope_artifact(tmp_path):
    """A transported synthetic scope, serialized by production's own codec.

    An earlier draft hand-wrote an assumed external scope payload and the
    task validator rejected it — correctly. Guessing the payload shape would
    have tested a fiction; building it through
    `build_training_scope` + `serialize_scope` means these bytes are exactly
    what the parent writes and the child must read.
    """
    from execute_tools.task_data_path import ScopeBuildRequest, active_task_data_path
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    composition = compose_run_task_bindings(QUICKSTART_MANIFEST)
    with bind_run_task_composition(composition, physical_data_root=str(tmp_path)):
        tdp = active_task_data_path()
        scope = tdp.build_training_scope(
            ScopeBuildRequest(
                round_kind="formal", selection_strategy="snapshot", portion=1.0, seed=0
            )
        )
        raw = tdp.serialize_scope(scope).encode("utf-8")

    path = tmp_path / "task_scope.json"
    path.write_bytes(raw)
    return str(path), hashlib.sha256(raw).hexdigest()


def _task_data_path():
    from workflows.task_composition import resolve_child_task_data_path

    return resolve_child_task_data_path(
        "quickstart_tabular", identity=None, manifest_path=QUICKSTART_MANIFEST
    )


class TestTheScopeDeserializesUnderTheTaskThatWroteIt:
    def test_binding_makes_the_task_scope_load(self, task_scope_artifact):
        """THE regression: with the task bound, the composed payload is
        decoded by the implementation that wrote it."""
        from execute_tools.scope_artifact import load_transported_scope
        from execute_tools.task_data_path import bind_task_data_path

        ref, digest = task_scope_artifact
        with bind_task_data_path(_task_data_path()):
            scope = load_transported_scope(ref, digest, leg="training")
        assert type(scope).__name__ == "QuickstartScope"

    def test_without_a_binding_it_does_NOT_silently_succeed(self, task_scope_artifact):
        """The other half of the contract: an unbound load must REFUSE, never
        decode a composed payload under a foreign task. If this ever passes
        silently, the pairing guard has been removed and an external run could
        execute under another task's scope semantics."""
        from execute_tools.scope_artifact import load_transported_scope
        from execute_tools.task_data_path import TaskDataPathResolutionError

        ref, digest = task_scope_artifact
        # BOTH named refusals are correct, and which one fires depends on
        # whether a legacy compatibility implementation happens to be registered
        # in this process: registered -> its `deserialize_scope` rejects the
        # foreign `kind` (ValueError); not registered
        # -> regime-A resolution refuses first. Naming both is precise;
        # `Exception` would also pass on an ImportError or a typo.
        with pytest.raises((ValueError, TaskDataPathResolutionError)):
            load_transported_scope(ref, digest, leg="training")


class TestTheInferenceChildBindsBeforeDeserializing:
    """Reachability: the behaviour above must be what `main` actually does."""

    def test_main_binds_around_the_scope_load(self):
        import inspect

        from execute_tools import inference_single

        source = inspect.getsource(inference_single.main)
        bind_at = source.find("bind_task_data_path(data_path)")
        load_at = source.find("load_transported_scope(")
        assert bind_at != -1, "the inference child must BIND its resolved task data path"
        assert load_at != -1
        assert bind_at < load_at, (
            "the binding must be entered BEFORE the scope is deserialized — "
            "resolving a data path into a local does not make it the ACTIVE "
            "implementation, which is what load_transported_scope delegates to"
        )

    def test_an_uncomposed_run_takes_the_nullcontext(self):
        """Boundary: an uncomposed run has task_data_path_id None and must not
        acquire a binding it never had."""
        import inspect

        from execute_tools import inference_single

        source = inspect.getsource(inference_single.main)
        assert "contextlib.nullcontext()" in source
        assert "args.task_data_path_id is not None" in source


class TestTheTrainingChildAlreadyHadThisRight:
    """Pins the asymmetry that WAS the defect, so a future edit cannot
    'simplify' training back to the broken shape."""

    def test_training_loads_its_scope_inside_the_binding(self):
        """The scope is deserialized INSIDE the binding — asserted structurally.

        This located its subject by the literal text ``"with binding_cm:"``
        and then compared character offsets. Both halves were wrong, and the
        first one broke the moment a second context manager joined that
        statement (`R-OBS-1`'s observables binding), which does not touch the
        property at all:

        * the ANCHOR could vanish while the property held, and a locator that
          returns ``-1`` reports "cannot see my subject" as "property
          violated" — the two are different failures and only one is a bug;
        * ``bind_at < load_at`` is TEXT ORDER, which is strictly weaker than
          enclosure. A ``load_transported_scope`` call placed AFTER the
          with-block closed would satisfy it — and that is exactly the defect
          this file exists to prevent, one child over.

        Walking the tree fixes both: it finds the ``with`` whose items include
        ``binding_cm`` however many siblings it has, and asserts the call is
        in its BODY.
        """
        import ast
        import inspect
        import textwrap

        from execute_tools import train_engine_sandbox

        tree = ast.parse(textwrap.dedent(inspect.getsource(train_engine_sandbox.main)))
        enclosing = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.With)
            and any(ast.unparse(item.context_expr) == "binding_cm" for item in node.items)
        ]
        assert len(enclosing) == 1, (
            f"expected exactly one `with binding_cm ...` in the training child's "
            f"main(), found {len(enclosing)}"
        )
        inside = [
            call
            for stmt in enclosing[0].body
            for call in ast.walk(stmt)
            if isinstance(call, ast.Call)
            and getattr(call.func, "id", None) == "load_transported_scope"
        ]
        assert inside, (
            "the training child must deserialize its transported scope INSIDE "
            "the task-data-path binding — resolving a data path into a local "
            "does not make it the ACTIVE implementation, which is what "
            "load_transported_scope delegates to"
        )
        # Nothing loads a scope outside it either, which text order could not say.
        all_loads = [
            call
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and getattr(call.func, "id", None) == "load_transported_scope"
        ]
        assert len(all_loads) == len(inside)
