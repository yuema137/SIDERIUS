"""The composed literature-review configuration boundary.

Design:
``docs/design/generic_framework_upgrade/step_12_external_extensibility_graduation/
pr_12a_composed_path_closure.md`` §5 C7 / D-12a-7; parent §0.1-B item 8
(Q-12-3, RATIFIED 2026-08-22).

The node and proposer-channel handoff are generic, but the shipped default
YAML contains TIDMAD-owned papers and confidence criteria. A composed run may
enable the node only when it supplies a non-default task-owned YAML. Selecting
the shipped default still fails before any LLM or GPU spend.

WHY THE GUARD IS AT STARTUP AND NOT AT THE CALL SITE: the lit-review node runs
inside the iteration loop, after interpretation. Refusing there would burn a
real interpretation round — LLM spend — to discover a configuration error that
was knowable before the loop began. `run_workflow` startup is the first point
where composition presence and the resolved flag are both in hand.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks.registry import _PROVIDER_REGISTRY, _REGISTRY
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"


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


class TestAComposedRunRefusesTheShippedLitReviewConfig:
    def test_it_raises_a_NAMED_error(self, tmp_path):
        composition = compose_run_task_bindings(str(FIXTURES / "pets" / "composition.yaml"))

        with (
            bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT),
            pytest.raises(ValueError) as excinfo,
        ):
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    lit_review_enabled=True,
                ),
                workspace=str(tmp_path / "ws"),
                run_name="pr12a_c7_litreview",
                task_composition=composition,
            )

        message = str(excinfo.value)
        assert "literature review is enabled on a COMPOSED run" in message
        # A refusal must say what to do about it and what its status is —
        # otherwise the operator learns only that something is forbidden.
        assert "--ml_lit_review_enabled" in message
        assert "--ml_lit_review_config" in message

    def test_it_refuses_BEFORE_any_node_is_constructed(self, tmp_path, monkeypatch):
        """The whole point of guarding at startup. If any node were built —
        let alone run — the refusal would have cost real LLM spend to reach.

        Asserted by making every node constructor explode: the guard must
        raise its OWN error, not theirs.
        """
        composition = compose_run_task_bindings(str(FIXTURES / "pets" / "composition.yaml"))

        def _must_not_be_constructed(*args, **kwargs):
            raise AssertionError(
                "a node was constructed before the lit-review guard refused — "
                "the guard has moved past the point where it is free"
            )

        for name in (
            "ResultInterpretationAgent",
            "MLModelProposalAgent",
            "MLModelImplementor",
            "MLCodeValidatorAgent",
            "HyperparamTuningAgent",
            "MLLiteratureReviewAgent",
        ):
            monkeypatch.setattr(
                f"workflows.model_exploration.{name}", _must_not_be_constructed, raising=True
            )

        with (
            bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT),
            pytest.raises(ValueError, match="literature review is enabled on a COMPOSED run"),
        ):
            run_workflow(
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    lit_review_enabled=True,
                ),
                workspace=str(tmp_path / "ws"),
                run_name="pr12a_c7_litreview_early",
                task_composition=composition,
            )


class TestEveryOtherCombinationIsUNAFFECTED:
    """Three of the four cells in the truth table must not move. A guard that
    also refused a legacy run, or a composed run with the flag off, would be
    a behaviour change wearing a safety fix's clothes."""

    def test_a_composed_run_with_lit_review_OFF_is_not_refused(self, tmp_path):
        """The default composed posture — and the one the ratification rests
        on, since the flag is OFF at all three layers."""
        composition = compose_run_task_bindings(str(FIXTURES / "pets" / "composition.yaml"))

        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            with pytest.raises(Exception) as excinfo:
                run_workflow(
                    launch=WorkflowLaunchConfig(
                        data_dir=str(tmp_path / "data"),
                        model_types=["punet"],
                        source_run_name="v1",
                    ),
                    workspace=str(tmp_path / "ws"),
                    run_name="pr12a_c7_litreview_off",
                    task_composition=composition,
                )
        # It fails for the ORDINARY reason a workflow with no seed data fails.
        # What matters is that it is not THIS guard: asserting "no exception"
        # would need a full fixture set and would test the harness, not the
        # guard's scope.
        assert "literature review is enabled" not in str(excinfo.value)

    def test_the_flag_default_is_still_OFF(self):
        """The evidence Q-12-3's ratification rests on, pinned at the layer
        this PR can see. If the default flipped, the guard would start
        refusing composed runs nobody opted in for."""
        assert WorkflowLaunchConfig().lit_review_enabled is False

    def test_the_chain_and_shipped_config_still_default_OFF(self):
        """The other two layers, so 'OFF at all three' stays a fact rather
        than a claim carried from the ratification note."""
        chain = (REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh").read_text(
            encoding="utf-8"
        )
        assert "ML_LIT_REVIEW_ENABLED=0" in chain

        config = (REPO_ROOT / "configs" / "lit_review_config.yaml").read_text(encoding="utf-8")
        assert "enabled: false" in config


class TestTheGuardIsANamedAuthority:
    """The decision lives in `refuse_shipped_lit_review_config_on_composed_run`, not
    inline in `run_workflow`.

    Written inline it turned the §12.1 sibling-shape tripwire RED (+1 If,
    +1 BoolOp on a function already carrying 132 branch nodes). The rule says
    establish the boundary before adding the complexity, so the orchestrator
    gained a CALL and the tripwire is back at 132 — the same disposition C1
    reached for the Health hand-off.
    """

    @pytest.mark.parametrize(
        ("composed", "enabled", "config_path", "refuses"),
        [
            (object(), True, "configs/lit_review_config.yaml", True),
            (object(), True, "/task/owned/lit_review.yaml", False),
            (object(), False, "configs/lit_review_config.yaml", False),
            (None, True, "configs/lit_review_config.yaml", False),
            (None, False, "configs/lit_review_config.yaml", False),
        ],
    )
    def test_the_refusal_truth_table(self, composed, enabled, config_path, refuses):
        from workflows.model_exploration import refuse_shipped_lit_review_config_on_composed_run

        if refuses:
            with pytest.raises(ValueError, match="literature review is enabled"):
                refuse_shipped_lit_review_config_on_composed_run(
                    task_composition=composed,
                    lit_review_enabled=enabled,
                    lit_review_config_path=config_path,
                )
        else:
            assert (
                refuse_shipped_lit_review_config_on_composed_run(
                    task_composition=composed,
                    lit_review_enabled=enabled,
                    lit_review_config_path=config_path,
                )
                is None
            )

    def test_the_orchestrator_calls_it_rather_than_branching(self):
        import inspect

        from workflows import model_exploration

        source = inspect.getsource(model_exploration.run_workflow)
        assert "refuse_shipped_lit_review_config_on_composed_run(" in source

    def test_it_names_no_task(self):
        """C-P56-1: the discriminator is composition PRESENCE, never a task
        identity or a surrogate for one. Asserted on the EXECUTABLE body —
        the docstring names TIDMAD to explain what the path still contains,
        which is prose, not dispatch.
        """
        import ast
        import inspect
        import textwrap

        from workflows.model_exploration import refuse_shipped_lit_review_config_on_composed_run

        function = next(
            node
            for node in ast.walk(
                ast.parse(
                    textwrap.dedent(
                        inspect.getsource(refuse_shipped_lit_review_config_on_composed_run)
                    )
                )
            )
            if isinstance(node, ast.FunctionDef)
        )
        statements = function.body[1:] if ast.get_docstring(function) else function.body
        guard = next(node for node in statements if isinstance(node, ast.If))
        rendered = ast.dump(guard.test)
        assert "task_composition" in rendered
        assert "lit_review_enabled" in rendered
        assert "lit_review_config_path" not in rendered
        for forbidden in ("tidmad", "TIDMAD", "denoising", "pets", "davis"):
            assert forbidden not in rendered
