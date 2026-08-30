"""Step 10 / P1 C3 — the binding stops stopping at the process boundary.

``transport_argv`` and the three children's ``--task_data_path_id`` parsers
were built together and then joined by nothing: the flag was parsed by every
child and emitted by nobody, so every child took its regime-A branch and the
transport was architecture that never ran. This module owns the join.

Distinct failure class, distinct evidence. C2's ContextVar tests prove the
PARENT holds the right implementation; none of them can see that the child
process never hears about it. Two things must therefore be proven separately:

* **emission** — a composed run's child argv carries the bound
  implementation's own declared id, at all three sites (training, inference,
  scoring). Captured from the REAL argv the executor builds, not from source
  text: a source-level guard would pass for a builder that assembles the flag
  and then drops it;

* **non-emission** — an un-composed run's argv is byte-identical to the C0
  capture. This is the half that a naive implementation gets wrong, and it
  gets it wrong invisibly: ``resolve_bound_task_data_path()`` returns the
  compatibility implementation when nothing is bound, so an emitter written
  against it would silently add ``--task_data_path_id tidmad`` to every legacy
  child's command line.

Then the round trip: the emitted id, parsed as a child parses it, must resolve
to the SAME implementation object the parent bound — which is the whole point
of the hop, and what fails if the parent stops emitting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from tests.unit.workflows.test_step10_p1_c0_census import capture_uncomposed_child_argv
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FOURTH_MANIFEST = (
    REPO_ROOT / "tests" / "fixtures" / "step10_p1" / "fourth_task" / "composition.yaml"
)

EXP_ID = "c0exp"
RUN_NAME = "c0run"


@pytest.fixture
def sandbox(tmp_path):
    from core.sandbox_executor import TidmadSandbox

    return TidmadSandbox(run_name=RUN_NAME, workspace=str(tmp_path), progress_bar=False)


@pytest.fixture
def composition():
    return compose_run_task_bindings(str(FOURTH_MANIFEST))


class TestEmissionWhenBound:
    def test_all_three_children_receive_the_bound_implementation_s_own_id(
        self, sandbox, tmp_path, composition
    ):
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            vectors = capture_uncomposed_child_argv(sandbox, tmp_path)

        assert set(vectors) == {"training", "inference", "scoring"}
        for phase, cmd in vectors.items():
            assert TASK_DATA_PATH_ARGV_FLAG in cmd, f"the {phase} child got no binding"
            value = cmd[cmd.index(TASK_DATA_PATH_ARGV_FLAG) + 1]
            assert value == composition.task_data_path_id, (
                f"the {phase} child received {value!r}, not the bound implementation's "
                f"declared id {composition.task_data_path_id!r}"
            )
            assert value == "spectro_segmentation_v0"

    def test_the_flag_appears_exactly_once_per_child(self, sandbox, tmp_path, composition):
        """A duplicate would make the child's parser silently take the last
        one — fine today, and a trap the moment two emitters disagree."""
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            vectors = capture_uncomposed_child_argv(sandbox, tmp_path)
        for phase, cmd in vectors.items():
            assert cmd.count(TASK_DATA_PATH_ARGV_FLAG) == 1, f"{phase} argv: {cmd}"


class TestNonEmissionWhenUnComposed:
    def test_the_un_composed_argv_is_unchanged(self, sandbox, tmp_path):
        """The half a naive emitter gets wrong invisibly.

        Written against ``resolve_bound_task_data_path()`` — which falls back
        — this would put the compatibility id into every legacy child's
        command line, and nothing in the suite except this test would notice.
        """
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        vectors = capture_uncomposed_child_argv(sandbox, tmp_path)
        for phase, cmd in vectors.items():
            assert TASK_DATA_PATH_ARGV_FLAG not in cmd, f"{phase} argv gained the flag: {cmd}"

    def test_emission_stops_the_moment_the_binding_ends(self, sandbox, tmp_path, composition):
        """The run scope really is the emission scope."""
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            bound = capture_uncomposed_child_argv(sandbox, tmp_path)
        after = capture_uncomposed_child_argv(sandbox, tmp_path)

        assert TASK_DATA_PATH_ARGV_FLAG in bound["training"]
        assert TASK_DATA_PATH_ARGV_FLAG not in after["training"]


class TestRoundTripReachability:
    def test_the_emitted_id_resolves_to_the_SAME_implementation_in_the_child(
        self, sandbox, tmp_path, composition
    ):
        """The hop, end to end, as a child performs it.

        The parent emits; a child parses its argv and calls
        ``resolve_transported_task_data_path``. That must land on the object
        the parent bound — not merely on something with a matching id.

        This is the test that fails when the parent stops emitting: with no
        flag in the argv there is no id to transport, and the child would fall
        to its regime-A branch while every parent-side assertion stayed green.
        """
        import argparse
        import contextlib
        import io

        from execute_tools.task_data_path import (
            TASK_DATA_PATH_ARGV_FLAG,
            resolve_transported_task_data_path,
        )

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            vectors = capture_uncomposed_child_argv(sandbox, tmp_path)

        for phase, cmd in vectors.items():
            parser = argparse.ArgumentParser()
            parser.add_argument(TASK_DATA_PATH_ARGV_FLAG, type=str, default=None)
            with contextlib.redirect_stderr(io.StringIO()):
                known, _ = parser.parse_known_args(cmd)
            assert known.task_data_path_id is not None, f"{phase} carried no id"

            resolved = resolve_transported_task_data_path(known.task_data_path_id)
            assert resolved is composition.task_data_path, (
                f"the {phase} child resolved a DIFFERENT object than the parent bound"
            )

    def test_an_unknown_transported_id_still_fails_closed(self):
        """The child-side refusal this hop rides on, pinned so the new
        emitter cannot be read as having softened it."""
        from execute_tools.task_data_path import (
            TaskDataPathResolutionError,
            resolve_transported_task_data_path,
        )

        with pytest.raises(TaskDataPathResolutionError, match="Unknown task data path id"):
            resolve_transported_task_data_path("a_task_nobody_registered")


class TestTheEmitterUsesTheNonFallingBackAccessor:
    def test_active_task_data_path_returns_None_when_unbound(self):
        """The distinction the emitter depends on, asserted directly.

        ``resolve_bound_task_data_path`` falls back by design and is right for
        consumers; ``active_task_data_path`` must not, and is right for the
        question "is this run explicitly bound?".
        """
        from execute_tools.task_data_path import (
            TIDMAD_COMPATIBILITY_ID,
            active_task_data_path,
            bootstrap_legacy_tidmad_data_path,
            resolve_bound_task_data_path,
        )

        bootstrap_legacy_tidmad_data_path()
        assert active_task_data_path() is None
        assert resolve_bound_task_data_path().task_data_path_id == TIDMAD_COMPATIBILITY_ID

    def test_the_emitter_helper_is_empty_when_unbound_and_populated_when_bound(self, composition):
        from core.sandbox_executor import _task_data_path_argv
        from execute_tools.task_data_path import (
            active_task_data_path,
            content_identity,
        )

        assert _task_data_path_argv() == []
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            bound = active_task_data_path()
            assert bound is not None
            assert _task_data_path_argv() == [
                "--task_data_path_id",
                "spectro_segmentation_v0",
                # PR-12bc C2: the parent pins WHICH implementation it resolved,
                # because an id alone re-resolves to whatever the child happens
                # to have registered under that name.
                "--task_data_path_identity",
                content_identity(bound),
            ]
