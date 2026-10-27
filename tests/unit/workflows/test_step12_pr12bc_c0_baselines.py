"""Registry resolution and registration reject unknown identities and conflicting content."""

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
