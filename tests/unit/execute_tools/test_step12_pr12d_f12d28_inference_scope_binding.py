"""Step 12 / PR-12d — F-12d-28: the inference child RESOLVED its task data
path but never BOUND it, so it deserialized the scope with the wrong task.

Design: ``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12d_contrast_subprocess_closure.md`` §Q D-12d-53.

**The defect, from a REAL composed Pets run:**

```text
File "execute_tools/inference_single.py", line 743, in main
File "execute_tools/scope_artifact.py", line 249, in load_transported_scope
File "execute_tools/tidmad_data_path.py", line 467, in deserialize_scope
ValueError: scope payload declares kind 'pets_scope_v1', not 'tidmad_scope_v1'
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
along (`train_engine_sandbox.py:2138` loads inside `with binding_cm:`), so
the asymmetry — not the concept — was the defect.

Each test names a defect only it can catch.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
PETS_MANIFEST = str(REPO_ROOT / "configs" / "task_composition" / "pets.yaml")

PETS_DATA = "/home/klz/Data/OXFORD_IIIT_PET/images"


@pytest.fixture
def pets_scope_artifact(tmp_path):
    """A REAL transported Pets scope, serialized by production's own codec.

    An earlier draft hand-wrote `{"kind": "pets_scope_v1", "rows": [1,2,3]}`
    and the real `PetsItem` validator rejected it — correctly. Guessing the
    payload shape would have tested a fiction; building it through
    `build_training_scope` + `serialize_scope` means these bytes are exactly
    what the parent writes and the child must read.
    """
    import os

    if not os.path.isdir(PETS_DATA):
        pytest.skip(f"Pets data root not present on this machine: {PETS_DATA}")

    from execute_tools.task_data_path import ScopeBuildRequest, active_task_data_path
    from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

    composition = compose_run_task_bindings(PETS_MANIFEST)
    with bind_run_task_composition(composition, physical_data_root=PETS_DATA):
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


def _pets_data_path():
    from workflows.task_composition import resolve_child_task_data_path

    return resolve_child_task_data_path(
        "oxford_iiit_pet", identity=None, manifest_path=PETS_MANIFEST
    )


class TestTheScopeDeserializesUnderTheTaskThatWroteIt:
    def test_binding_makes_the_pets_scope_load(self, pets_scope_artifact):
        """THE regression: with the task bound, the composed payload is
        decoded by the implementation that wrote it."""
        from execute_tools.scope_artifact import load_transported_scope
        from execute_tools.task_data_path import bind_task_data_path

        ref, digest = pets_scope_artifact
        with bind_task_data_path(_pets_data_path()):
            scope = load_transported_scope(ref, digest, leg="training")
        assert type(scope).__name__ == "PetsScope"

    def test_without_a_binding_it_does_NOT_silently_succeed(self, pets_scope_artifact):
        """The other half of the contract: an unbound load must REFUSE, never
        decode a composed payload under a foreign task. If this ever passes
        silently, the pairing guard has been removed and a Pets run could be
        scored against TIDMAD's scope semantics."""
        from execute_tools.scope_artifact import load_transported_scope
        from execute_tools.task_data_path import TaskDataPathResolutionError

        ref, digest = pets_scope_artifact
        # BOTH named refusals are correct, and which one fires depends on
        # whether the legacy TIDMAD implementation happens to be registered in
        # this process: registered -> TIDMAD's `deserialize_scope` rejects the
        # foreign `kind` (ValueError, what the real child hit); not registered
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
        """Boundary: a TIDMAD run has task_data_path_id None and must not
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
        import inspect

        from execute_tools import train_engine_sandbox

        source = inspect.getsource(train_engine_sandbox.main)
        bind_at = source.find("with binding_cm:")
        load_at = source.find("load_transported_scope(")
        assert bind_at != -1 and load_at != -1
        assert bind_at < load_at
