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
from importlib import import_module
from pathlib import Path

import pytest

from core.chain_state import ChainState
from core.resume import RestoredState
from tests.helpers.composition_data_root import COMPOSED_TEST_DATA_ROOT

REPO_ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = REPO_ROOT / "src" / "workflows" / "run_one_iteration.py"

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


@pytest.fixture(params=["run_one_iteration", "model_exploration"])
def entrypoint_parser(request, monkeypatch):
    """Observe the parser used by main, stopping before launch effects."""
    module = import_module(f"workflows.{request.param}")
    captured = []

    class ParserReached(Exception):
        pass

    def capture(parser, *args, **kwargs):
        captured.append(parser)
        raise ParserReached

    with monkeypatch.context() as patch:
        patch.setattr(argparse.ArgumentParser, "parse_args", capture)
        with pytest.raises(ParserReached):
            module.main()
    assert len(captured) == 1
    argv = ["--workspace", "runs", "--run_name", "probe", "--data_dir", "data"]
    if request.param == "model_exploration":
        argv += ["--models", "synthetic", "--source_run_name", "previous"]
    return captured[0], argv


class TestTheCompositionFlag:
    def test_both_edges_require_an_explicit_task_composition(self, entrypoint_parser, capsys):
        """Both supported CLI edges refuse an undeclared task."""
        parser, argv = entrypoint_parser
        with pytest.raises(SystemExit) as refusal:
            parser.parse_args(argv)
        assert refusal.value.code == 2
        assert "required: --task_composition" in capsys.readouterr().err
        parsed = parser.parse_args([*argv, "--task_composition", "external/task.yaml"])
        assert parsed.task_composition == "external/task.yaml"

    def test_the_transport_flag_is_NOT_an_operator_surface(self, entrypoint_parser, capsys):
        """Only a resolved binding can emit the internal transport flag."""
        from execute_tools.task_data_path import TASK_DATA_PATH_ARGV_FLAG

        parser, argv = entrypoint_parser
        with pytest.raises(SystemExit) as refusal:
            parser.parse_args(
                [*argv, "--task_composition", "external/task.yaml", TASK_DATA_PATH_ARGV_FLAG, "x"]
            )
        assert refusal.value.code == 2
        assert f"unrecognized arguments: {TASK_DATA_PATH_ARGV_FLAG}" in capsys.readouterr().err

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

    def test_an_absent_flag_is_refused(self):
        """A supported launcher requires a declared task instead of selecting one."""
        from workflows.task_composition import TaskCompositionError, bind_run_task_composition

        with pytest.raises(TaskCompositionError, match="task composition is required"):
            with bind_run_task_composition(None, physical_data_root=COMPOSED_TEST_DATA_ROOT):
                pass
