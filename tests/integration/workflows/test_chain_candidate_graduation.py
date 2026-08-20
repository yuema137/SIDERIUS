"""
Dual-mode integration test: G1 Bridge — proposed_vocab_candidates survives
the chain subprocess boundary (Phase 1 Commit 1.4).

Background
----------
In chain mode each iteration is its own ``run_workflow`` subprocess with
``max_iterations=1``. Without the G1 bridge, the workflow's local
``previous_proposal_data`` always started as ``None`` on every chain iter
(workflows/model_exploration.py:799 pre-Phase-1) — so candidates proposed
in iter N never accumulated ``seen_in_runs`` evidence at iter N+1, and
``promote_candidates`` could not fire across the chain.

The bridge has three pieces (see docs/Consistent_growing_vocab_list.md §10):

    1. ``core/resume.py::load_latest_proposal`` — globs the latest committed
       iter's ``proposal_iter_NNN.json`` and returns the dict.
    2. ``RestoredState.previous_proposal_data`` — passes the dict through
       the chain runner.
    3. ``workflows/model_exploration.py::run_workflow`` — accepts a new
       ``restored_previous_proposal`` kwarg that seeds local
       ``previous_proposal_data`` on the very first round of the iter,
       replacing the unconditional ``None`` initialisation.

This test exercises all three pieces with a real disk roundtrip.

Test design
-----------
Two tests covering both code paths.

Test 1 (chain mode, 4 iters):
    Cold start. Each iter is its own ``run_workflow`` call with
    ``max_iterations=1``. Between iters the test writes the manifest +
    run_output files that ``restore_prior_state`` expects, then calls
    ``restore_prior_state`` for real and forwards
    ``RestoredState.previous_proposal_data`` to the next ``run_workflow``
    via ``restored_previous_proposal``.

    The mock proposer physically writes ``proposal_iter_NNN.json`` to its
    storage workspace (mirrors nodes/ml_model_proposal_agent.py:754-761),
    so ``load_latest_proposal`` exercises its real glob+open code path —
    not just an in-memory dict shuttle.

    Why 4 iters and not 3?
        Iter N's proposer emits ``foo`` with ``model_name=model_iter_N``.
        Iter N+1's interp reads N's proposal and adds ``model_iter_N``
        to ``foo.seen_in_runs``. Reaching ``seen_in_runs`` len 3 therefore
        requires FOUR proposers' contributions. Promotion fires at the
        end of iter 4 when iter 4's interp ingests iter 3's proposal.
        (3 iters from cold yields ``seen_in_runs`` len 2 — not enough
        to trip ``promote_candidates``.)

Test 2 (in-process regression, 4 iters via single ``run_workflow``):
    Single ``run_workflow(max_iterations=4)``. The local in-process update
    at workflows/model_exploration.py:1232
    (``previous_proposal_data = proposal.model_dump()``) carries state
    between iterations within the same loop, replacing the chain-mode
    kwarg. Asserts the same final vocab as Test 1 — proves the bridge
    is path-symmetric (chain ≡ in-process).

Pseudo-only — no real-mode opt-in. The assertion is structural ("foo
graduates to canonical with seen_in_runs len 3"), not LLM-quality, so
real-mode would add no signal.
"""

from __future__ import annotations

import glob as _glob
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import VocabEntry
from core.resume import restore_prior_state
from nodes.interpretation_helpers import build_runtime_vocab, promote_candidates
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
    _write_tuning_output,
)
from workflows.llm_config import (
    NodeLLMConfig,
    ProposalLLMConfig,
    TunerLLMConfig,
    WorkflowLLMConfig,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig

pytestmark = pytest.mark.dual_mode


# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

_FOO_CANDIDATE = {
    "name": "foo",
    "kind": "feature",
    "description": (
        "G1-bridge sentinel — a feature candidate proposed in every iter "
        "so seen_in_runs accumulates one model_name per cross-iter "
        "boundary crossed."
    ),
}


def _llm_config_pseudo() -> WorkflowLLMConfig:
    """Minimal LLM config that satisfies workflow plumbing without making
    any real API call (every agent is mocked at the workflow boundary)."""
    return WorkflowLLMConfig(
        interpret=NodeLLMConfig(provider="openai", model_id="test"),
        propose=ProposalLLMConfig(),
        implement=NodeLLMConfig(provider="openai", model_id="test"),
        validate_model=NodeLLMConfig(provider="openai", model_id="test"),
        tune=TunerLLMConfig(
            planner=NodeLLMConfig(provider="openai", model_id="test"),
            reflector=NodeLLMConfig(provider="openai", model_id="test"),
        ),
    )


def _make_proposal_persist_side_effect(model_name: str):
    """Mock proposer side_effect that:

      1. Returns a ``ProposalOutput`` with ``proposed_vocab_candidates=[foo]``
         and the given ``model_name``.
      2. Physically writes ``proposal_{run_name}.json`` to
         ``inp.storage.local.workspace`` — mirrors
         ``nodes/ml_model_proposal_agent.py:754-761``.

    The persistence step is critical: without it, ``load_latest_proposal``
    has nothing to find on disk and the bridge never gets exercised."""

    def _side_effect(inp):
        output = _make_proposal_output(model_name=model_name).model_copy(
            update={"proposed_vocab_candidates": [dict(_FOO_CANDIDATE)]}
        )
        if inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            out_path = os.path.join(workspace, f"proposal_{run_name}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=4))
        return output

    return _side_effect


def _make_proposal_persist_counter_side_effect(call_counter: list):
    """Same as above but the model_name advances per call. Used by Test 2's
    single in-process ``run_workflow`` (which fires the proposer 4 times
    in a row, each needing a unique model_name)."""

    def _side_effect(inp):
        call_counter[0] += 1
        return _make_proposal_persist_side_effect(
            model_name=f"model_iter_{call_counter[0]:03d}",
        )(inp)

    return _side_effect


def _make_interp_with_real_vocab_logic_side_effect(
    captured_inputs: list,
    captured_outputs: list,
):
    """Mock interp side_effect that simulates the real interpretation node's
    ``proposed_by_run`` injection + ``build_runtime_vocab`` accumulation.

    Mirrors nodes/result_interpretation_agent.py:894-911:
      - read previous_proposal.proposed_vocab_candidates
      - inject ``proposed_by_run = previous_proposal.model_name``
      - call ``build_runtime_vocab(incoming, [], proposed_candidates)``
      - call ``promote_candidates`` (seen_in_runs >= 3 → canonical)

    Also persists the digest to
    ``{interp_storage.workspace}/interpretation_{run_name}.json`` so the
    chain runner's ``load_latest_knowledge`` finds something on the next
    iter (otherwise restored_runtime_vocab arrives empty and seen_in_runs
    cannot accumulate across the boundary)."""

    def _side_effect(inp):
        captured_inputs.append(inp)

        proposed_candidates = []
        if inp.previous_proposal:
            model_name = inp.previous_proposal.get("model_name", "")
            raw = inp.previous_proposal.get("proposed_vocab_candidates", []) or []
            proposed_candidates = [
                {**c, "proposed_by_run": model_name} if not c.get("proposed_by_run") else c
                for c in raw
            ]

        runtime_vocab = build_runtime_vocab(
            incoming_vocab=list(inp.runtime_vocab or []),
            new_discoveries=[],
            proposed_candidates=proposed_candidates,
        )
        runtime_vocab, _promoted = promote_candidates(runtime_vocab)

        output = InterpretationOutput(
            model_types=["punet"],
            model_descriptions={"punet": "punet seed"},
            total_experiments=1,
            per_model_best={"punet": 1.0},
            per_model_worst={"punet": 0.5},
            best_denoising_score=1.0,
            worst_denoising_score=0.5,
            best_config={"model_config": {}},
            key_findings=[],
            bottlenecks=[],
            take_home_message="proceed",
            model_knowledge_cache={},
            runtime_vocab=runtime_vocab,
        )
        captured_outputs.append(output)

        if inp.storage and inp.storage.backend == "local" and inp.storage.local:
            workspace = inp.storage.local.workspace
            run_name = inp.storage.local.run_name
            os.makedirs(workspace, exist_ok=True)
            digest_path = os.path.join(
                workspace,
                f"interpretation_{run_name}.json",
            )
            with open(digest_path, "w", encoding="utf-8") as f:
                f.write(output.model_dump_json(indent=2))
        return output

    return _side_effect


def _write_chain_iter_artifacts(
    chain_root: str,
    iteration: int,
    tune_output,
):
    """Write the manifest + run_output JSON that the chain runner produces
    after ``run_workflow`` returns. Real chain runner code:
    ``sdsc_submission_scripts/run_one_iteration.py::write_manifest``.

    Layout produced::

        {chain_root}/iter_NNN/manifest.json
        {chain_root}/iter_NNN/run_output_iter_NNN.json
    """
    run_name = f"iter_{iteration:03d}"
    iter_dir = os.path.join(chain_root, run_name)
    os.makedirs(iter_dir, exist_ok=True)

    output_path = os.path.join(iter_dir, f"run_output_{run_name}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(tune_output.model_dump_json(indent=2))

    manifest = {
        "iteration": iteration,
        "status": "completed",
        "output_path": output_path,
    }
    with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)


# ---------------------------------------------------------------------------
# Test 1 — chain mode: G1 bridge proves seen_in_runs survives subprocess
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_chain_bridge_promotes_foo_after_four_iters(tmp_path):
    """Cold-start chain: 4 iters, each its own run_workflow call. Between
    iters, ``restore_prior_state`` walks the workspace from disk and
    forwards ``previous_proposal_data`` via the new
    ``restored_previous_proposal`` kwarg. After 4 iters the candidate
    ``foo`` accumulates ``seen_in_runs`` len 3 and graduates to canonical.

    This test is the contract that proves the G1 bridge: the same
    ``foo`` must survive 3 chain-subprocess boundary crossings to reach
    promotion.
    """
    chain_root = str(tmp_path / "chain_workspace")
    os.makedirs(chain_root, exist_ok=True)

    # Seed run_output JSON to bootstrap iter 1's source_paths
    seed_root = tmp_path / "seed"
    seed_root.mkdir(parents=True, exist_ok=True)
    _write_tuning_output(seed_root, "punet", run="v1", score=1.5)
    seed_path = str(seed_root / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")

    captured_interp_inputs: list = []
    captured_interp_outputs: list = []
    state_per_iter: list = []  # RestoredState per iter, for assertions

    for iteration in range(1, 5):  # iters 1..4
        run_name = f"iter_{iteration:03d}"

        state = restore_prior_state(
            workspace=chain_root,
            current_iter=iteration,
            seed_paths=[seed_path],
        )
        state_per_iter.append(state)

        model_name = f"model_iter_{iteration:03d}"
        tune_output = _make_tuning_output(
            model_type=model_name,
            run_name=run_name,
            score=1.5,
        )

        with (
            patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
            patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
            patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
            patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
            patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        ):
            MockInterp.return_value.run.side_effect = (
                _make_interp_with_real_vocab_logic_side_effect(
                    captured_interp_inputs,
                    captured_interp_outputs,
                )
            )
            MockImpl.return_value.run.return_value = _make_implementor_output(model_type=model_name)
            MockValid.return_value.run.return_value = _make_validator_output(passed=True)
            MockTune.return_value.run.return_value = tune_output
            MockPropose.return_value.run.side_effect = _make_proposal_persist_side_effect(
                model_name
            )

            run_workflow(
                launch=WorkflowLaunchConfig(
                    source_paths=state.resolved_source_paths,
                    max_iterations=1,
                    start_iteration=iteration,
                ),
                workspace=chain_root,
                run_name=run_name,
                llm_config=_llm_config_pseudo(),
                restored_runtime_vocab=state.runtime_vocab,
                accumulated_key_findings=state.accumulated_key_findings,
                accumulated_physical_rejections=state.accumulated_physical_rejections,
                accumulated_gate_exhaustions=state.accumulated_gate_exhaustions,
                restored_previous_proposal=state.previous_proposal_data,
            )

        _write_chain_iter_artifacts(chain_root, iteration, tune_output)

    # ---------------------------------------------------------------
    # Assertion 1: bridge wired correctly through restore_prior_state
    # ---------------------------------------------------------------

    # Iter 1's restore returns previous_proposal_data=None (no prior iters).
    assert state_per_iter[0].previous_proposal_data is None, (
        f"Iter 1 should restore previous_proposal_data=None (no prior "
        f"committed iters); got {state_per_iter[0].previous_proposal_data!r}"
    )

    # Iter 2-4 restored the previous iter's proposal dict (latest-wins).
    for i in range(1, 4):
        restored = state_per_iter[i].previous_proposal_data
        assert restored is not None, (
            f"G1 BRIDGE FAILED at iter {i + 1}: restore_prior_state "
            f"returned previous_proposal_data=None — disk roundtrip broken."
        )
        expected_model = f"model_iter_{i:03d}"
        assert restored.get("model_name") == expected_model, (
            f"G1 BRIDGE: iter {i + 1} restored proposal.model_name="
            f"{restored.get('model_name')!r}, expected {expected_model!r} "
            f"(should be the LATEST committed iter's proposal)."
        )
        foo_in_restored = [
            c for c in restored.get("proposed_vocab_candidates", []) or [] if c.get("name") == "foo"
        ]
        assert len(foo_in_restored) == 1, (
            f"G1 BRIDGE: iter {i + 1} restored proposal lost the foo "
            f"candidate. proposed_vocab_candidates="
            f"{restored.get('proposed_vocab_candidates')!r}"
        )

    # ---------------------------------------------------------------
    # Assertion 2: 4 disk-persisted proposal files exist
    # ---------------------------------------------------------------
    for i in range(1, 5):
        run_name = f"iter_{i:03d}"
        # Post-cc198ad workflow loop encodes the chain-wide iter index in
        # the iteration sub-dir name as well. Pre-fix this was always
        # ``iteration_001``; that legacy assumption is what the original
        # _proposal_path bug rode on.
        proposal_glob = os.path.join(
            chain_root,
            run_name,
            f"iteration_{i:03d}",
            f"attempt_*_model_iter_{i:03d}",
            f"proposal_{run_name}.json",
        )
        matches = _glob.glob(proposal_glob)
        assert len(matches) == 1, (
            f"Iter {i}: proposal_{run_name}.json not persisted to disk. "
            f"Glob {proposal_glob} matched: {matches}"
        )
        with open(matches[0]) as f:
            data = json.load(f)
        assert data["model_name"] == f"model_iter_{i:03d}"
        foo_match = [c for c in data.get("proposed_vocab_candidates", []) if c.get("name") == "foo"]
        assert len(foo_match) == 1, f"Iter {i}: foo missing from persisted proposal."

    # ---------------------------------------------------------------
    # Assertion 3: foo graduates to canonical with seen_in_runs len 3
    # by the end of iter 4 (the headline G1 bridge contract)
    # ---------------------------------------------------------------
    assert len(captured_interp_outputs) == 4, (
        f"Expected 4 interp calls (one per iter); got {len(captured_interp_outputs)}."
    )
    final_vocab = captured_interp_outputs[-1].runtime_vocab
    foo_entries = [v for v in final_vocab if v.name == "foo"]
    assert len(foo_entries) == 1, (
        f"G1 BRIDGE FAILED: foo missing from iter-4 runtime_vocab. "
        f"vocab names: {[v.name for v in final_vocab]}"
    )
    foo = foo_entries[0]
    assert foo.tier == "canonical", (
        f"G1 BRIDGE FAILED: foo not promoted after 3 cross-iter boundary "
        f"crossings. tier={foo.tier!r}, seen_in_runs={foo.seen_in_runs!r}"
    )
    assert len(foo.seen_in_runs) == 3, (
        f"G1 BRIDGE FAILED: foo.seen_in_runs should have exactly 3 entries "
        f"(model_iter_001, model_iter_002, model_iter_003); "
        f"got {foo.seen_in_runs!r}"
    )
    expected_runs = {"model_iter_001", "model_iter_002", "model_iter_003"}
    assert set(foo.seen_in_runs) == expected_runs, (
        f"G1 BRIDGE: foo.seen_in_runs has the wrong runs. "
        f"expected={expected_runs}, got={set(foo.seen_in_runs)}"
    )

    print(
        "\n  [G1 chain] 4 disk roundtrips verified: "
        f"foo.seen_in_runs={foo.seen_in_runs} → tier={foo.tier!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — In-process regression: same outcome via single run_workflow
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_in_process_run_workflow_promotes_foo_after_four_iters(tmp_path):
    """Single ``run_workflow(max_iterations=4)`` reaches the same final
    vocabulary state as the chain test above. This proves the bridge is
    path-symmetric: the in-process update at
    workflows/model_exploration.py:1232 carries
    ``previous_proposal_data`` between iterations within the same loop,
    and the chain bridge restores the same value across subprocess
    boundaries — both produce identical end state.
    """
    workspace = str(tmp_path / "in_process_workspace")
    os.makedirs(workspace, exist_ok=True)

    seed_root = tmp_path / "seed"
    seed_root.mkdir(parents=True, exist_ok=True)
    _write_tuning_output(seed_root, "punet", run="v1", score=1.5)
    seed_path = str(seed_root / "data" / "punet" / "v1" / "agent" / "run_output_v1_agent.json")

    captured_interp_inputs: list = []
    captured_interp_outputs: list = []
    propose_call_counter = [0]
    tune_call_counter = [0]

    def _tune_side_effect(inp):
        tune_call_counter[0] += 1
        n = tune_call_counter[0]
        return _make_tuning_output(
            model_type=f"model_iter_{n:03d}",
            run_name=f"in_process_v{n}",
            score=1.5,
        )

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
    ):
        MockInterp.return_value.run.side_effect = _make_interp_with_real_vocab_logic_side_effect(
            captured_interp_inputs,
            captured_interp_outputs,
        )
        MockImpl.return_value.run.side_effect = lambda inp: _make_implementor_output(
            model_type=f"model_iter_{propose_call_counter[0]:03d}",
        )
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = _tune_side_effect
        MockPropose.return_value.run.side_effect = _make_proposal_persist_counter_side_effect(
            propose_call_counter
        )

        run_workflow(
            launch=WorkflowLaunchConfig(
                source_paths=[seed_path],
                max_iterations=4,
            ),
            workspace=workspace,
            run_name="in_process",
            llm_config=_llm_config_pseudo(),
        )

    # Same headline contract as Test 1
    assert len(captured_interp_outputs) == 4, (
        f"Expected 4 interp calls; got {len(captured_interp_outputs)}."
    )
    final_vocab = captured_interp_outputs[-1].runtime_vocab
    foo_entries = [v for v in final_vocab if v.name == "foo"]
    assert len(foo_entries) == 1, (
        f"In-process: foo missing from iter-4 runtime_vocab. "
        f"vocab names: {[v.name for v in final_vocab]}"
    )
    foo = foo_entries[0]
    assert foo.tier == "canonical", (
        f"In-process: foo not promoted after 4 in-process iters. "
        f"tier={foo.tier!r}, seen_in_runs={foo.seen_in_runs!r}"
    )
    assert len(foo.seen_in_runs) == 3, (
        f"In-process: foo.seen_in_runs should have exactly 3 entries; got {foo.seen_in_runs!r}"
    )
    expected_runs = {"model_iter_001", "model_iter_002", "model_iter_003"}
    assert set(foo.seen_in_runs) == expected_runs, (
        f"In-process: foo.seen_in_runs has the wrong runs. "
        f"expected={expected_runs}, got={set(foo.seen_in_runs)}"
    )

    print(
        "\n  [G1 in-process] foo.seen_in_runs="
        f"{foo.seen_in_runs} → tier={foo.tier!r} ✓ "
        "(path-symmetric with chain bridge)"
    )
