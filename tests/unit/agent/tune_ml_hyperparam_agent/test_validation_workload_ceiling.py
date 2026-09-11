"""FU-D-12 — the harness owns the maximum workload, not the planner.

Gate 2 Case A attempt 2 requested `--trial_portion 0.02` and measured **0.1**.
The audit found why: the tuner resolves trial-mode portions from
`plan.trial_portion` — the LLM's plan — while formal-mode portions come from
`agent_input.formal_*`. So the operator value was a suggestion, not a ceiling.

Time budgets bound wall TIME. They do not bound WORKLOAD: a planner can pick
an oversized data fraction and simply consume the budget doing less useful
work. The frozen minimum-bounded-validation rule requires the harness to own
the maximum, so this clamp exists.

It is a **maximum, never a replacement**: `min(planned, ceiling)` can only
reduce a portion, so it can never make a run larger, and `None` — the default
— leaves ordinary campaigns untouched.
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from tests.helpers.tuner_source import tuner_node_source

BASE = {"model_type": "m", "run_name": "r", "workspace": "/tmp/ws"}


class TestTheCeilingIsOptionalAndFailsClosed:
    def test_absent_by_default_so_campaigns_are_unchanged(self):
        assert HyperparamTuningInput.model_validate(BASE).validation_max_portion is None

    @pytest.mark.parametrize(
        "bad",
        [0.0, -0.1, 1.5, float("inf"), float("-inf"), float("nan")],
        ids=["zero", "negative", "over-one", "inf", "-inf", "nan"],
    )
    def test_a_malformed_ceiling_is_refused(self, bad):
        """MUTATION TARGET: relaxing the bounds.

        A non-finite or out-of-range ceiling would either disable the clamp
        silently (`inf`) or make every portion zero (`0.0`). Both are worse
        than refusing.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HyperparamTuningInput.model_validate({**BASE, "validation_max_portion": bad})

    def test_a_valid_ceiling_is_accepted(self):
        got = HyperparamTuningInput.model_validate({**BASE, "validation_max_portion": 0.02})
        assert got.validation_max_portion == 0.02


class TestTheClampReachesTheResolvedValues:
    """The property that matters: the clamp must act on the RESOLVED config,
    after `_resolve_sample_set_cfg` has chosen between plan and operator
    sources — otherwise it would bind only one branch."""

    @staticmethod
    def _tuner_source() -> str:
        # The node, not one file of it: C7 split the tuner into a main module plus
        # node-local submodules, and these scans are claims about the NODE.
        return tuner_node_source()

    def test_the_clamp_is_applied_after_resolution(self):
        """MUTATION TARGET: clamping `plan.*` instead of the resolved cfg.

        Clamping the plan alone would miss any value the resolver takes from
        another source, and would silently stop binding if the resolver
        changed.
        """
        src = self._tuner_source()
        resolve_at = src.index("_cfg = _resolve_sample_set_cfg(")
        clamp_at = src.index("if agent_input.validation_max_portion is not None:")
        assert clamp_at > resolve_at, (
            "the ceiling is applied before the config is resolved, so it "
            "cannot bind the values production actually uses"
        )

    def test_all_three_trial_portions_are_bounded(self):
        """MUTATION TARGET: clamping only `trial_portion`.

        `train_portion` and `eval_portion` are equally planner-controlled;
        bounding one and not the others leaves the workload unbounded.
        """
        src = self._tuner_source()
        block = src[src.index("if agent_input.validation_max_portion is not None:") :][:1600]
        for name in ("cfg_trial_portion", "cfg_train_portion", "cfg_eval_portion"):
            assert f"{name} = min({name}, _ceiling)" in block, f"{name} is not bounded"

    def test_it_is_a_maximum_and_never_raises_a_portion(self):
        """The safety property: a ceiling must not be able to ENLARGE a run.

        `min` is the whole guarantee, so it is asserted directly rather than
        inferred from the variable name.
        """
        src = self._tuner_source()
        block = src[src.index("if agent_input.validation_max_portion is not None:") :][:1600]
        assert "max(" not in block, "a workload ceiling must never use max()"
        assert block.count("min(") == 3


class TestTheClampArithmetic:
    """The rule itself, exercised directly."""

    @pytest.mark.parametrize(
        ("planned", "ceiling", "expected"),
        [
            (0.1, 0.02, 0.02),  # the measured Gate 2 case
            (0.02, 0.02, 0.02),  # at the ceiling
            (0.01, 0.02, 0.01),  # below — untouched, never raised
            (1.0, 0.05, 0.05),
        ],
    )
    def test_min_semantics(self, planned, ceiling, expected):
        assert min(planned, ceiling) == expected

    def test_formal_portions_are_deliberately_out_of_scope(self):
        """Formal-mode portions already come from operator input
        (`agent_input.formal_*`), so clamping them would add a second policy
        over a value the operator already controls."""
        import importlib
        import inspect

        mod = importlib.import_module(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
        )
        src = inspect.getsource(mod._resolve_sample_set_cfg)
        assert "agent_input.formal_portion" in src
        assert "plan.trial_portion" in src


class TestEndToEndPlumbing:
    """A ceiling the launcher accepts but never delivers is worthless — the
    defect class this PR family has hit four times."""

    def test_the_launcher_forwards_it_to_the_workflow(self):
        from pathlib import Path

        launcher = (
        Path(__file__).resolve().parents[4] / "src" / "workflows" / "run_one_iteration.py"
        )
        # Step 09.5a C3: the launcher binds transit configuration inside the
        # WorkflowLaunchConfig it constructs, one level below the run_workflow
        # call. The shared extractor flattens both levels; the forwarding
        # invariant is unchanged.
        from tests.helpers.launcher_bindings import workflow_call_bindings

        assert "validation_max_portion" in workflow_call_bindings(launcher), (
            "run_workflow is called without validation_max_portion"
        )

    def test_the_workflow_forwards_it_through_the_protocol(self):
        """MUTATION TARGET: the workflow accepting the ceiling and dropping it.

        Checked per CALL NODE, and the first version of this test was a
        SUBSTRING check that passed while the kwarg sat on the wrong call —
        `local_validated_model()` did not accept it, and only the launch-surface
        parity guard noticed. Field mapping belongs in the protocol (the node
        contract), so this asserts the protocol call carries it.
        """
        import ast
        import inspect

        from workflows import model_exploration

        tree = ast.parse(inspect.getsource(model_exploration))
        carried = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
            == "local_validated_model"
            and "validation_max_portion" in {kw.arg for kw in n.keywords}
        ]
        assert carried, (
            "local_validated_model is called without validation_max_portion, so "
            "the ceiling never reaches the tuner input"
        )

    def test_the_protocol_maps_it_onto_the_tuner_input(self):
        """The other half: a protocol that accepts a field and never maps it
        would satisfy the call-site test while dropping the value."""
        import ast
        import inspect

        from agent.schemas.protocols import ml_model_valid_to_ml_model_tune as proto

        src = inspect.getsource(proto.local_validated_model)
        assert "validation_max_portion: float | None" in src, "not accepted"
        tree = ast.parse(inspect.getsource(proto))
        mapped = any(
            isinstance(n, ast.Call)
            and "validation_max_portion" in {kw.arg for kw in n.keywords}
            and any(
                isinstance(kw.value, ast.Name) and kw.value.id == "validation_max_portion"
                for kw in n.keywords
                if kw.arg == "validation_max_portion"
            )
            for n in ast.walk(tree)
        )
        assert mapped, "the protocol accepts the ceiling but never maps it onto the input"


class TestCeilingProvenanceIsPersisted:
    """A Gate must be able to PROVE the workload was bounded — not merely
    that a CLI flag was accepted.

    The clamp previously only printed. That is the same defect class this PR
    family has now hit five times, so the before/after pair is persisted and
    the field is DECLARED on the record schema (undeclared, Pydantic's default
    `extra="ignore"` would drop it silently).
    """

    def test_the_record_schema_declares_the_field(self):
        """MUTATION TARGET: removing the declaration.

        Undeclared, the tuner would still write it and the artifact would
        simply lack the key — indistinguishable from a run that never clamped.
        """
        from agent.schemas.hyperparam_tuning import ExperimentRecord

        assert "validation_workload_ceiling" in ExperimentRecord.model_fields

    def test_it_survives_serialisation_to_the_artifact(self):
        import json

        from agent.schemas.hyperparam_tuning import ExperimentRecord

        payload = {
            "enabled": True,
            "configured_ceiling": 0.02,
            "planned": {"trial_portion": 0.1, "train_portion": 0.1, "eval_portion": 0.1},
            "resolved": {"trial_portion": 0.02, "train_portion": 0.02, "eval_portion": 0.02},
        }
        rec = ExperimentRecord.model_validate(
            {
                "exp_id": "e",
                "status": "success",
                "model_type": "m",
                "timestamp": "t",
                "params": {},
                "validation_workload_ceiling": payload,
            }
        )
        assert json.loads(rec.model_dump_json())["validation_workload_ceiling"] == payload

    def test_the_tuner_records_planned_and_resolved(self):
        """MUTATION TARGET: recording only the resolved values.

        Without the PLANNED half, a clamp that silently stopped firing is
        indistinguishable from a planner that happened to choose small
        values — the Gate would prove nothing.
        """
        src = TestTheClampReachesTheResolvedValues._tuner_source()
        block = src[src.index('final_record["validation_workload_ceiling"]') :][:900]
        assert '"planned": _planned_portions' in block
        assert '"resolved"' in block
        assert '"configured_ceiling": agent_input.validation_max_portion' in block
        assert '"enabled": agent_input.validation_max_portion is not None' in block

    def test_planned_values_are_captured_before_the_clamp(self):
        """Order matters: capturing them after `min` would record the clamped
        values twice and the provenance would be a tautology."""
        src = TestTheClampReachesTheResolvedValues._tuner_source()
        capture = src.index("_planned_portions = {")
        clamp = src.index("if agent_input.validation_max_portion is not None:")
        assert capture < clamp, "planned portions are captured after clamping"


class TestOrdinaryCampaignsAreUnchanged:
    """`None` must leave the normal path byte-identical in behaviour."""

    def test_no_ceiling_means_no_clamp_branch_is_entered(self):
        src = TestTheClampReachesTheResolvedValues._tuner_source()
        assert "if agent_input.validation_max_portion is not None:" in src, (
            "the clamp must be guarded, so an ordinary campaign never enters it"
        )

    def test_provenance_still_records_the_disabled_state(self):
        """Recorded as `enabled: False` rather than omitted, so a reader can
        tell 'no ceiling configured' from 'nobody wrote the field'."""
        import ast

        src = TestTheClampReachesTheResolvedValues._tuner_source()
        block = src[src.index('final_record["validation_workload_ceiling"]') :][:900]
        assert '"enabled": agent_input.validation_max_portion is not None' in block

        # The stamp sits OUTSIDE the `is not None` guard. Stated as
        # CONTAINMENT rather than as a byte offset: since Step 07 PR 07b C7d
        # the clamp lives in the node's `planning` module and the stamp in its
        # `records` module, so "appears later in the text" no longer means
        # "runs after" — and would pass or fail on file order alone.
        tree = ast.parse(src)
        guards = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "validation_max_portion is not None" in (ast.get_source_segment(src, n.test) or "")
        ]
        assert guards, "the clamp guard is gone"
        stamped_inside = [
            g
            for g in guards
            if 'final_record["validation_workload_ceiling"]'
            in (ast.get_source_segment(src, g) or "")
        ]
        assert stamped_inside == [], (
            "the provenance stamp moved inside the ceiling guard, so an "
            "ordinary campaign would record nothing instead of enabled: False"
        )
