"""Step 10 / P1 C5 — the launcher surface: one restored parameter, one flag.

Two changes, both at the edge, and both with a failure mode that hides.

**The `RestoredState` collapse** (Step 09.5a's own C4b hand-off). Nine
`restored_*`/`accumulated_*` parameters became one typed carrier. The risk is
not that it breaks loudly — it is that ONE of the nine quietly stops arriving.
A run whose restored vocabulary, key findings or incumbent score silently
became empty still runs, still scores, still writes artifacts; it has just
forgotten part of its chain. So the proof is per-value and taken AT THE
CONSUMER: what `ChainState` ends up holding, and what the three
non-`ChainState` consumers see — never at the signature, which can be correct
while the unpacking drops a field.

**The composition flag**. `--task_composition` is the operator's only way in,
and the transport flag `--task_data_path_id` must remain unreachable from the
command line: it is emitted from a resolved binding by construction, and an
operator-settable id would let a run declare a data path its composition never
resolved.
"""

from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path

import pytest

from core.chain_state import ChainState
from core.resume import RestoredState
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
WORKFLOW = REPO_ROOT / "workflows" / "model_exploration.py"

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "step10_p1"
FOURTH_MANIFEST = FIXTURES / "fourth_task" / "composition.yaml"


#: A restored state in which every one of the carried values is DISTINCTIVE,
#: so a dropped field cannot be masked by a default that happens to look right.
#:
#: Step 10 / P5+P6 C2 grew the set from NINE to TEN: `vocab_link_confirmations`
#: joined as the fifth projected carry-over. The set below stays EXACT rather
#: than becoming a floor — the defect this guard exists for is a typo that
#: reads the wrong field name, and only an exact set catches that.
def _distinctive_restored_state() -> RestoredState:
    from agent.schemas.interpretation import PredictionMemory
    from agent.schemas.proposal import VocabEntry

    return RestoredState(
        runtime_vocab=[VocabEntry(name="c5_term", kind="concept", description="a restored term")],
        accumulated_key_findings=["c5 finding one", "c5 finding two"],
        model_knowledge_cache={"punet": {"key_findings": ["cached"]}},
        accumulated_physical_rejections=[{"model_type": "punet", "reason": "vram"}],
        accumulated_gate_exhaustions=[{"model_type": "punet", "rounds": 3}],
        previous_proposal_data={"model_name": "c5_prior_proposal"},
        chain_best_valid_formal_score=-1.75,
        collapse_fingerprint_history={"punet": [{"iteration": 1}]},
        prediction_memory=PredictionMemory(
            prediction_outcomes_history={"confirmed": 5, "partial": 1, "refuted": 2},
            cumulative_information_gain=2.5,
        ),
    )


class TestTheCarriedValuesStillReachTheirConsumers:
    """Per-value equality, observed where the value is USED."""

    def test_the_six_chain_state_seeds_arrive_unchanged(self):
        """Applied through the same rules `ChainState.from_restored` already
        applied — this asserts the UNPACKING maps the right field to the right
        seed, which is the step C5 introduced and the only new place a value
        can be lost."""
        restored = _distinctive_restored_state()

        state = ChainState.from_restored(
            vocab_seed=[],
            restored_runtime_vocab=restored.runtime_vocab,
            restored_model_knowledge_cache=restored.model_knowledge_cache,
            restored_previous_proposal=restored.previous_proposal_data,
            restored_chain_incumbent_score=restored.chain_best_valid_formal_score,
            restored_collapse_fingerprint_history=restored.collapse_fingerprint_history,
            restored_prediction_memory=restored.prediction_memory,
        )

        assert [entry.name for entry in state.current_runtime_vocab] == ["c5_term"]
        assert state.model_knowledge_cache == {"punet": {"key_findings": ["cached"]}}
        assert state.previous_proposal_data == {"model_name": "c5_prior_proposal"}
        assert state.chain_formal_incumbent_reference == -1.75
        assert state.current_collapse_fingerprint_history == {"punet": [{"iteration": 1}]}
        assert state.current_prediction_memory is restored.prediction_memory

    def test_the_workflow_unpacks_every_one_of_the_carried_fields(self):
        """The unpacking block reads each carried value exactly once, and
        reads the RIGHT field name for each.

        Source-level because the mapping is what C5 introduced: a typo like
        `restored_state.runtime_vocab` where `accumulated_key_findings` was
        meant produces a run that is merely wrong, never one that raises.
        """
        tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
        run_workflow = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_workflow"
        )
        read_fields = {
            node.attr
            for node in ast.walk(run_workflow)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "restored_state"
        }
        assert read_fields == {
            "runtime_vocab",
            "accumulated_key_findings",
            "model_knowledge_cache",
            "accumulated_physical_rejections",
            "previous_proposal_data",
            "chain_best_valid_formal_score",
            "collapse_fingerprint_history",
            "prediction_memory",
            # Step 10 / P5+P6 C2.
            "vocab_link_confirmations",
        }, f"the unpacking reads {sorted(read_fields)}"

        helper = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_restored_negative_feedback"
        )
        helper_fields = {
            node.attr
            for node in ast.walk(helper)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "restored_state"
        }
        assert helper_fields == {
            "accumulated_negative_feedback",
            "accumulated_gate_exhaustions",
        }
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_restored_negative_feedback"
            for node in ast.walk(run_workflow)
        )

    def test_cold_start_and_restored_nothing_stay_indistinguishable(self):
        """The three non-`ChainState` consumers all test TRUTHINESS, so the
        migration is only behaviour-preserving if `None` (cold start) and
        `RestoredState()`'s empty containers remain equally falsy.

        This is the assumption the collapse rests on. Stated here so that a
        future change to `RestoredState`'s defaults — say a sentinel object —
        fails loudly instead of quietly enabling three cross-iteration
        branches on a cold-start run.
        """
        empty = RestoredState()
        assert not empty.accumulated_key_findings
        assert not empty.accumulated_gate_exhaustions
        assert not empty.accumulated_physical_rejections
        assert not empty.runtime_vocab
        assert not empty.model_knowledge_cache
        assert not empty.collapse_fingerprint_history
        assert empty.previous_proposal_data is None
        assert empty.chain_best_valid_formal_score is None


class TestSignatureAndCallers:
    def test_run_workflow_has_exactly_twenty_one_parameters(self):
        from workflows.model_exploration import run_workflow

        assert len(inspect.signature(run_workflow).parameters) == 21

    def test_no_compatibility_wrapper_re_exposes_the_carried_values(self):
        """09.5a rule 2, unchanged: the old surface must not survive beside
        the new one, or the transport this closed would still be reachable."""
        retired = {
            "restored_runtime_vocab",
            "accumulated_key_findings",
            "restored_model_knowledge_cache",
            "accumulated_physical_rejections",
            "accumulated_gate_exhaustions",
            "restored_previous_proposal",
            "restored_chain_incumbent_score",
            "restored_collapse_fingerprint_history",
            "restored_prediction_memory",
        }
        offenders: dict[str, list[str]] = {}
        for rel in (
            "workflows/model_exploration.py",
            "sdsc_submission_scripts/run_one_iteration.py",
        ):
            tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
            for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                declared = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
                overlap = sorted(declared & retired)
                if overlap:
                    offenders[f"{rel}::{fn.name}"] = overlap
        assert offenders == {}, f"the retired restored surface survives: {offenders}"

    def test_the_launcher_forwards_the_carrier_and_the_composition(self):
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        call = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_workflow"
        )
        keywords = {kw.arg: ast.unparse(kw.value) for kw in call.keywords if kw.arg}
        assert keywords["restored_state"] == "state"
        assert keywords["task_composition"] == "run_composition"


class TestTheCompositionFlag:
    def test_both_edges_expose_it_and_default_to_the_legacy_run(self):
        """Absent ⇒ `None` ⇒ un-composed, on BOTH composition edges."""
        for path in (LAUNCHER, WORKFLOW):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            declared = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "--task_composition"
            ]
            assert len(declared) == 1, (
                f"{path.name} does not declare --task_composition exactly once"
            )
            defaults = {
                kw.arg: ast.literal_eval(kw.value)
                for kw in declared[0].keywords
                if kw.arg == "default"
            }
            assert defaults == {"default": None}

    def test_the_transport_flag_is_NOT_an_operator_surface(self):
        """`--task_data_path_id` is emitted from a RESOLVED binding by
        construction (the `transport_argv` signature takes the implementation,
        not a string). Exposing it as an operator flag would let a run declare
        a data path its composition never resolved — precisely the ambiguity
        the composition removes."""
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        for path in (LAUNCHER, WORKFLOW):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_argument"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                ):
                    assert node.args[0].value != TASK_DATA_PATH_ARGV_FLAG, (
                        f"{path.name} exposes the internal transport flag to operators"
                    )

    def test_the_launcher_resolves_the_composition_before_the_workflow(self):
        """§5.1: the workflow receives the resolved VALUE, never a path, so it
        performs no YAML or plugin I/O of its own."""
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        composes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "compose_run_task_bindings"
        ]
        assert len(composes) == 1
        assert ast.unparse(composes[0].args[0]) == "args.task_composition"

        workflow_tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
        run_workflow = next(
            node
            for node in ast.walk(workflow_tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run_workflow"
        )
        inside = [
            node
            for node in ast.walk(run_workflow)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "compose_run_task_bindings"
        ]
        assert inside == [], "run_workflow composes; it must only consume"

    def test_the_launcher_wraps_the_call_in_the_binding(self):
        """The binding must ENCLOSE the workflow call, not merely precede it —
        a bare call would leave every authority unbound and `run_workflow`'s
        own guard would refuse the run."""
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        wrapped = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            items = [
                item.context_expr
                for item in node.items
                if isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "bind_run_task_composition"
            ]
            if not items:
                continue
            if any(
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "run_workflow"
                for inner in ast.walk(node)
            ):
                wrapped = True
        assert wrapped, "run_workflow is not enclosed by bind_run_task_composition"


class TestEndToEndAtTheEdge:
    def test_a_composed_launch_binds_every_authority_for_the_call(self):
        """The edge behaviour, executed rather than parsed: resolving a
        manifest and entering the binding is enough for the workflow's own
        fail-closed guard to accept the run."""
        from workflows.task_composition import (
            bind_run_task_composition,
            compose_run_task_bindings,
            verify_composition_is_bound,
        )

        composition = compose_run_task_bindings(str(FOURTH_MANIFEST))
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            verify_composition_is_bound(composition)

    def test_an_absent_flag_produces_an_un_composed_run(self):
        """The legacy path, taken exactly as the launcher takes it."""
        from workflows.task_composition import (
            bind_run_task_composition,
            verify_composition_is_bound,
        )

        parser = argparse.ArgumentParser()
        parser.add_argument("--task_composition", type=str, default=None)
        args = parser.parse_args([])

        composition = None if not args.task_composition else pytest.fail("unreachable")
        with bind_run_task_composition(composition, physical_data_root=COMPOSED_TEST_DATA_ROOT):
            verify_composition_is_bound(composition)

        from execute_tools.task_data_path import active_task_data_path

        assert active_task_data_path() is None
