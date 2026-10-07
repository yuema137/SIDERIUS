"""Step 10 / P5+P6 — C3: ``accumulated_key_findings`` normalizes onto ChainState.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §6, §13 C3 (Q-10-6 = A).

C3 is an **ownership move, not a semantic change**. The union rule, the
projection, the digest content and the consumer block's rendered BYTES are all
unchanged; what changes is that the last bare cross-iteration local becomes a
carried ChainState sibling that also grows in-process.

Two defect classes only this module catches:

**1. Union-rule DRIFT.** The loop closure applies
``core.resume.project_knowledge``'s rule (``resume.py:926-929``) rather than
re-implementing it. If the two ever disagreed — on empty strings, on non-``str``
members, on dedup, on order — an uninterrupted in-process run and a
per-iteration chain restore would silently diverge, and only a comparison
against the projection ITSELF on the same input can see it. ``TestTheUnionRule``
drives both and asserts equality.

**2. Rendered-byte drift.** The block is LLM-facing. Moving its input from a
bare local to a carrier must not move one byte of what the proposer reads, and
the design explicitly preserves the pre-existing F-P56-1 label defect (the
count is labelled "prior iter(s)" while it counts FINDINGS). ``TestTheRenderedBlock``
pins the exact string, F-P56-1 included, so the normalization is provably a
move rather than an edit.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.chain_state import ChainState
from core.committed_digests import DigestRead
from core.resume import RestoredState, project_knowledge
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tune_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import TunerLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import bind_run_task_composition, compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART = REPO_ROOT / "configs" / "task_composition" / "quickstart.yaml"


def _drive(tmp_path, per_iteration_findings, *, restored_state=None):
    """Drive the REAL ``run_workflow``; return each iteration's proposer
    expert-context findings block (or ``None`` when none rendered)."""
    composition = compose_run_task_bindings(str(QUICKSTART))
    _write_tuning_output(
        tmp_path,
        "punet",
        fingerprint=composition.semantic_fingerprint,
        metric_spec=composition.metric.spec,
    )
    iterations = len(per_iteration_findings)

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        call = {"n": 0}

        def _interp(_inp):
            call["n"] += 1
            out = _make_interpretation_output()
            out.key_findings = list(per_iteration_findings[call["n"] - 1])
            return out

        names = iter([f"cand_{i}" for i in range(iterations + 1)])
        MockInterp.return_value.run.side_effect = _interp
        MockPropose.return_value.run.side_effect = lambda inp: _make_proposal_output(next(names))
        MockImpl.return_value.run.return_value = _make_implementor_output()
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
            model_type=inp.model_type,
            score=1.6,
            fingerprint=composition.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        )

        with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
            run_workflow(
                llm_config=WorkflowLLMConfig(
                    tune=TunerLLMConfig(planner_strategy="native-timing-v1")
                ),
                launch=WorkflowLaunchConfig(
                    data_dir=str(tmp_path / "data"),
                    model_types=["punet"],
                    source_run_name="v1",
                    max_iterations=iterations,
                ),
                workspace=str(tmp_path / "workflow_output"),
                run_name="p56_c3",
                restored_state=restored_state,
                task_composition=composition,
            )

        blocks = []
        for c in MockPropose.return_value.run.call_args_list:
            items = [i for i in c[0][0].expert_context if i.kind == "findings"]
            blocks.append(items[0].content if items else None)
        return blocks


# ---------------------------------------------------------------------------
# 1. The union rule is APPLIED, not re-implemented
# ---------------------------------------------------------------------------


class TestTheUnionRule:
    """The closure and ``project_knowledge`` must agree on every input class.

    Driven as a DIFFERENTIAL: the same per-iteration findings fed through the
    loop closure and through the projection must produce the identical list.
    A hand-written expectation would pass even if BOTH drifted together.
    """

    @pytest.mark.parametrize(
        "per_iteration",
        [
            pytest.param([["a"], ["b"], ["c"]], id="distinct"),
            pytest.param([["a"], ["a"], ["a"]], id="all-duplicates"),
            pytest.param([["a", "b"], ["b", "c"], ["c", "a"]], id="overlapping"),
            pytest.param([["a"], [], ["b"]], id="a-quiet-iteration"),
            pytest.param([[], [], []], id="never-any-findings"),
            pytest.param([["a", "a"], ["a"], ["b"]], id="duplicate-within-one-iteration"),
            pytest.param([["", "a"], ["b"], [""]], id="empty-strings-filtered"),
        ],
    )
    def test_the_closure_matches_the_projection_exactly(self, tmp_path, per_iteration):
        blocks = _drive(tmp_path, per_iteration)

        # Iteration N's block is the union of iterations 1..N-1, so the
        # differential is taken against the projection over EVERY prefix — one
        # comparison per iteration, not just the last.
        reads = [
            DigestRead(
                iter_idx=i,
                path=f"/ws/iter_{i:03d}.json",
                status="ok",
                payload={"key_findings": findings},
            )
            for i, findings in enumerate(per_iteration, start=1)
        ]

        for n, block in enumerate(blocks):
            _vocab, projected_prior = project_knowledge(reads[:n])
            if not projected_prior:
                assert block is None, f"iteration {n + 1} rendered a block from an empty history"
                continue
            assert block is not None, (
                f"iteration {n + 1} rendered nothing, but the projection over "
                f"its prior digests yields {projected_prior}"
            )
            bullets = [line[2:] for line in block.splitlines() if line.startswith("- ")]
            # Exact list equality: covers membership, dedup AND order in one
            # assertion, against the projection rather than a hand-written
            # expectation that could drift with it.
            assert bullets == projected_prior

    def test_non_string_members_are_filtered_by_both(self):
        """The projection filters non-``str`` members silently; the closure's
        ``isinstance`` guard must do the same, or a malformed LLM response
        would crash the loop while resuming cleanly.
        """
        reads = [
            DigestRead(
                iter_idx=1,
                path="/ws/1.json",
                status="ok",
                payload={"key_findings": ["good", 7, None, "", "also good"]},
            )
        ]
        _vocab, projected = project_knowledge(reads)
        assert projected == ["good", "also good"]

        state = ChainState.cold_start()
        for finding in ["good", 7, None, "", "also good"]:
            if (
                isinstance(finding, str)
                and finding
                and finding not in state.accumulated_key_findings
            ):
                state.accumulated_key_findings.append(finding)
        assert state.accumulated_key_findings == projected


# ---------------------------------------------------------------------------
# 2. Three-iteration accumulation, through the real loop
# ---------------------------------------------------------------------------


class TestAccumulationAcrossIterations:
    def test_each_iteration_sees_every_prior_finding_exactly_once(self, tmp_path):
        blocks = _drive(tmp_path, [["f1"], ["f2"], ["f3"]])

        assert blocks[0] is None  # no prior history yet
        assert "- f1" in blocks[1] and "- f2" not in blocks[1]
        assert "- f1" in blocks[2] and "- f2" in blocks[2]
        assert blocks[2].count("- f1") == 1

    def test_a_restored_history_seeds_the_first_iteration(self, tmp_path):
        """Chain mode: the union arrives restored and the loop extends it,
        rather than restarting from it."""
        restored = RestoredState(accumulated_key_findings=["prior_a", "prior_b"])
        blocks = _drive(tmp_path, [["f1"], ["f2"]], restored_state=restored)

        assert "- prior_a" in blocks[0] and "- prior_b" in blocks[0]
        assert "- f1" not in blocks[0]
        assert "- f1" in blocks[1]

    def test_a_restored_finding_repeated_in_process_is_not_duplicated(self, tmp_path):
        """First-wins makes the union idempotent — which is exactly what lets
        a resume re-union digests it already merged."""
        restored = RestoredState(accumulated_key_findings=["shared"])
        blocks = _drive(tmp_path, [["shared"], ["new"]], restored_state=restored)

        assert blocks[1].count("- shared") == 1
        assert "- new" not in blocks[1]

    def test_a_quiet_iteration_is_a_no_op(self, tmp_path):
        blocks = _drive(tmp_path, [["f1"], [], ["f3"]])
        assert "- f1" in blocks[2]
        bullets = [line for line in blocks[2].splitlines() if line.startswith("- ")]
        assert bullets == ["- f1"]


# ---------------------------------------------------------------------------
# 3. The rendered block is byte-identical (an ownership move, not an edit)
# ---------------------------------------------------------------------------


class TestTheRenderedBlock:
    def test_the_exact_rendered_bytes_for_a_fixed_history(self, tmp_path):
        """Hardcoded expectation — not read back from the code under test.

        **F-P56-1 is deliberately preserved**: the sentence labels the FINDINGS
        count as an ITER count ("from 2 prior iter(s)" for two findings
        produced by two iterations happens to coincide, but the number is
        ``len(findings)``). Fixing that wording is an LLM-facing byte change
        outside this child's declared deltas, so it stays and is recorded as
        prompt-hygiene debt.
        """
        restored = RestoredState(accumulated_key_findings=["alpha", "beta"])
        blocks = _drive(tmp_path, [["gamma"]], restored_state=restored)

        assert blocks[0] == ("Accumulated key findings from 2 prior iter(s):\n- alpha\n- beta")

    def test_the_count_is_findings_not_iterations(self, tmp_path):
        """F-P56-1 made executable, so the debt is visible rather than folklore:
        THREE findings from ONE restored history still render "3 prior
        iter(s)"."""
        restored = RestoredState(accumulated_key_findings=["a", "b", "c"])
        blocks = _drive(tmp_path, [["d"]], restored_state=restored)
        assert blocks[0].startswith("Accumulated key findings from 3 prior iter(s):")

    def test_the_item_metadata_is_unchanged(self, tmp_path):
        composition = compose_run_task_bindings(str(QUICKSTART))
        _write_tuning_output(
            tmp_path,
            "punet",
            fingerprint=composition.semantic_fingerprint,
            metric_spec=composition.metric.spec,
        )
        restored = RestoredState(accumulated_key_findings=["alpha"])

        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        ):
            MockInterp.return_value.run.return_value = _make_interpretation_output()
            MockPropose.return_value.run.return_value = _make_proposal_output("cand_0")
            MockImpl.return_value.run.return_value = _make_implementor_output()
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.side_effect = lambda inp: _make_tune_output(
                model_type=inp.model_type,
                score=1.6,
                fingerprint=composition.semantic_fingerprint,
                metric_spec=composition.metric.spec,
            )
            with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
                run_workflow(
                    llm_config=WorkflowLLMConfig(
                        tune=TunerLLMConfig(planner_strategy="native-timing-v1")
                    ),
                    launch=WorkflowLaunchConfig(
                        data_dir=str(tmp_path / "data"),
                        model_types=["punet"],
                        source_run_name="v1",
                        max_iterations=1,
                    ),
                    workspace=str(tmp_path / "workflow_output"),
                    run_name="p56_c3_meta",
                    restored_state=restored,
                    task_composition=composition,
                )
            proposal_input = MockPropose.return_value.run.call_args_list[0][0][0]

        [item] = [i for i in proposal_input.expert_context if i.kind == "findings"]
        assert item.source == "prior_iters"
        assert item.source_ref == "prior_iters_key_findings"


# ---------------------------------------------------------------------------
# 4. Ownership: the bare local is gone
# ---------------------------------------------------------------------------


def test_the_retired_bare_local_has_no_remaining_reads():
    """The rename the C0 guard analysis predicted.

    ``ChainState`` declaring ``accumulated_key_findings`` makes any bare local
    of that name a duplicate-writer twin (Step 09.5a Amendment C). The unpack
    row is now ``restored_accumulated_key_findings``, matching its eight
    siblings; the generic census
    (``test_step09_5a_c4_single_writer.py``) enforces this, and this test names
    the specific rename so a revert is legible.
    """
    import ast
    from pathlib import Path

    workflow = Path(__file__).resolve().parents[3] / "src/workflows" / "model_exploration.py"
    tree = ast.parse(workflow.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "run_workflow"
    )
    bare_assignments = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == "accumulated_key_findings"
    ]
    assert bare_assignments == []
    assert "restored_accumulated_key_findings = (" in workflow.read_text(encoding="utf-8")


def test_the_union_rule_has_exactly_ONE_authority_and_both_consumers_call_it():
    """REACHABILITY for the consolidation, and the reason it was needed.

    ``test_the_closure_matches_the_projection_exactly`` above is a
    differential: it drove both paths and compared them. That test could
    only ever catch a divergence AFTER someone wrote a second body — and a
    second body existed, its comment claiming "Applied, not re-implemented"
    while `resume.py` deduped with a `seen` set and the workflow closure
    deduped with a linear membership test on the list. Same semantics, two
    implementations; if the rule ever normalises (strip, casefold), only the
    C4 equality test stands between that and a silently divergent chain
    history.

    So the rule now lives in ONE function and both consumers CALL it. That
    makes the differential green by construction, which is the point — and
    it is also why this test exists: a structural invariant needs a
    structural guard, or the next author simply re-inlines the loop and the
    differential goes on passing.

    Fails when: someone re-inlines the dedup in either consumer, or defines
    a second `union_key_findings`.
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    resume_src = (root / "src/core" / "resume.py").read_text(encoding="utf-8")
    workflow_src = (root / "src/workflows" / "model_exploration.py").read_text(encoding="utf-8")

    # 1. Exactly one definition, and it is in core.resume.
    defs = [
        n.lineno
        for n in ast.walk(ast.parse(resume_src))
        if isinstance(n, ast.FunctionDef) and n.name == "union_key_findings"
    ]
    assert len(defs) == 1, f"expected ONE union authority in core/resume.py, found {defs}"
    assert "def union_key_findings" not in workflow_src, (
        "the workflow must CALL the authority, never define its own"
    )

    # 2. Both consumers call it. `project_knowledge` is the projection half;
    #    `run_workflow`'s loop closure is the in-process half.
    for src, fn_name, path in (
        (resume_src, "project_knowledge", "src/core/resume.py"),
        (workflow_src, "run_workflow", "src/workflows/model_exploration.py"),
    ):
        fn = next(
            n
            for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.FunctionDef) and n.name == fn_name
        )
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "union_key_findings"
        ]
        assert len(calls) == 1, (
            f"{path}::{fn_name} must call the union authority exactly once, found {len(calls)}"
        )

    # 3. Neither consumer still carries a hand-rolled dedup append. The old
    #    shape appended inside a membership test; require that it is gone.
    for src, path in ((resume_src, "src/core/resume.py"), (workflow_src, "model_exploration.py")):
        assert "not in state.accumulated_key_findings" not in src, (
            f"{path} re-inlined the membership test the authority owns"
        )
