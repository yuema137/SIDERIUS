"""V19 PR 1 P1-V1 — pseudo integration for chain-incumbent threading.

Design (docs/design/v19_priorities/pr1_chain_incumbents.md §7 P1-V1):
BOTH incumbent branches are exercised DETERMINISTICALLY so that the
downstream P1-V2 Gate 2 smoke does not need to force a particular
stochastic real-training outcome.

Three scenarios, one per test:

  A. Numeric incumbent — iter 1's committed run_output has a
     ``best_valid_formal_denoising_score``; iter 2's tuner input
     receives it as ``current_run_best_formal_score``; iter 2's
     manifest carries ``chain_incumbent_used`` + full
     ``chain_incumbent_source`` provenance; iter 2's own
     ``best_valid_formal_score`` stays untouched (Invariant II).
  B. No incumbent — iter 1's committed run_output has null
     ``best_valid_formal_denoising_score``; iter 2's tuner input
     receives ``None``; iter 2's manifest has ``chain_incumbent_used``
     null; gates short-circuit.
  C. Flag OFF (rollback) — reconstruction, provenance stamps, and
     manifest ``chain_incumbent_source`` all still run; only
     ``chain_incumbent_used`` is null because gate consumption is off.

Every test drives the FULL production commit path:

  * ``restore_prior_state`` (real; from ``core.resume``);
  * ``run_workflow`` (real; from ``workflows.model_exploration``) with
    all agent classes mocked at the workflow boundary so no LLM call
    happens and no training runs;
  * ``write_manifest`` (real; from
    ``sdsc_submission_scripts.run_one_iteration``) — the same code the
    chain runner uses.

No real LLM, no real training. Test gate: pseudo only.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.validator import ValidatorOutput
from core.resume import restore_prior_state
from sdsc_submission_scripts.run_one_iteration import write_manifest
from workflows.model_exploration import run_workflow

# ---------------------------------------------------------------------------
# Fixture helpers — mocked node outputs + a chain-runner-shaped disk seed
# ---------------------------------------------------------------------------

_BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _passing_verdicts() -> list[dict]:
    return [
        {
            "gate_name": gate_id,
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
        }
        for gate_id in _BLOCKING_IDS
    ]


def _formal_record(
    exp_id: str,
    score: float,
    *,
    logical_round: int = 3,
) -> dict:
    """Formal record (DS5 disabled-mode waiver so it's commit-time VALID
    without needing a policy artifact)."""
    return {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "punet",
        "timestamp": "2026-07-27 00:00:00",
        "params": {},
        "logical_round": logical_round,
        "denoising_score": score,
        "file_vector": [score] + [None] * 19,
        "health_gate_results": _passing_verdicts(),
        "health_gate_enabled": False,  # DS5 waiver: commit-time VALID
    }


def _make_tune_output(
    run_name: str,
    *,
    valid_formal: float | None,
    exp_id: str | None,
    records: list[dict] | None = None,
) -> HyperparamTuningOutput:
    """A minimal but schema-valid HyperparamTuningOutput. When
    ``valid_formal`` is set the record is included so iter 2's
    reconstruction has a real source to point at."""
    if records is None:
        records = [_formal_record(exp_id or "f", valid_formal)] if valid_formal is not None else []
    return HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        best_denoising_score=(valid_formal if valid_formal is not None else None),
        best_formal_denoising_score=(valid_formal if valid_formal is not None else None),
        best_valid_formal_denoising_score=valid_formal,
        best_valid_formal_exp_id=exp_id,
        all_records=records,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
    )


def _write_iter_disk(
    workspace: str,
    iter_idx: int,
    tune_output: HyperparamTuningOutput,
    *,
    chain_incumbent_used: float | None = None,
    chain_incumbent_source: dict | None = None,
) -> str:
    """Write iter N's on-disk artifacts EXACTLY the way the chain runner
    does — same layout, same manifest keys, same write_manifest helper.

    Returns the manifest path (for post-facto assertions on the same
    dict `write_manifest` returns)."""
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, "iteration_001", tune_output.model_type)
    os.makedirs(model_dir, exist_ok=True)
    output_path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(output_path, "w") as f:
        f.write(tune_output.model_dump_json())
    # Modern write side (P1-C5 A4): persist formal sampling provenance
    # so per_file_best rows populate correctly. The value here is not
    # asserted in P1-V1 (that's P1-C5's job) — set to production defaults.
    with open(os.path.join(model_dir, f"run_config_{run_name}.json"), "w") as f:
        json.dump({"formal_strategy": "snapshot", "formal_eval_portion": 1.0}, f)
    manifest = write_manifest(
        iter_dir,
        run_name,
        [tune_output],
        chain_incumbent_used=chain_incumbent_used,
        chain_incumbent_source=chain_incumbent_source,
    )
    return manifest


_INTERP_OUT = InterpretationOutput(
    model_types=["punet"],
    model_descriptions={"punet": "punet"},
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
    runtime_vocab=[],
)
_PROPOSAL_OUT = ProposalOutput(
    model_name="punet",
    model_description="punet",
    mathematical_definition="—",
    motivation="—",
    expert_advice=ExpertAdvice(
        focus_areas=["—"],
        constraints=["—"],
        known_failures=["—"],
        suggested_directions=["—"],
        rationale="pseudo test — no real advice",
    ),
    baseline_config={
        "model_config": {},
        "train_config": {},
        "loss_config": {"loss_type": "focal"},
    },
)
_IMPL_OUT = ImplementorOutput(
    model_type="punet",
    description_file_path="/tmp/punet.md",
    model_file_path="/tmp/punet.py",
    test_file_path="/tmp/test_punet.py",
    config_fields={"n_layers": 4},
    model_description="punet stub for pseudo test",
    mathematical_definition="—",
)
_VALID_OUT = ValidatorOutput(
    passed=True,
    model_type="punet",
    plugin_registered=True,
    tests_passed=True,
    description_valid=True,
    config_fields_valid=True,
    instantiation_passed=True,
    gradient_check_passed=True,
    llm_review_passed=True,
)


def _run_iter_2(workspace: str, iter2_tune_output, *, enable_gates: bool):
    """Reproduce what run_one_iteration.main does at iter 2 boundary:
    real restore_prior_state → real run_workflow (mocked agents) → real
    write_manifest with the reconstructed incumbent."""
    state = restore_prior_state(workspace, current_iter=2, seed_paths=[])
    captured_tune_inputs: list[HyperparamTuningInput] = []

    def _capture(inp):
        captured_tune_inputs.append(inp)
        return iter2_tune_output

    with contextlib.ExitStack() as stack:
        MockInterp = stack.enter_context(
            patch("workflows.model_exploration.ResultInterpretationAgent")
        )
        MockPropose = stack.enter_context(patch("workflows.model_exploration.MLModelProposalAgent"))
        MockImpl = stack.enter_context(patch("workflows.model_exploration.MLModelImplementor"))
        MockValid = stack.enter_context(patch("workflows.model_exploration.MLCodeValidatorAgent"))
        MockTune = stack.enter_context(patch("workflows.model_exploration.HyperparamTuningAgent"))
        # Avoid touching real plugin registries in this pseudo test.
        stack.enter_context(
            patch("workflows.model_exploration._register_plugin", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_model_to_global", return_value=None)
        )
        stack.enter_context(
            patch("workflows.model_exploration._promote_loss_to_global", return_value=None)
        )
        MockInterp.return_value.run.return_value = _INTERP_OUT
        MockPropose.return_value.run.return_value = _PROPOSAL_OUT
        MockImpl.return_value.run.return_value = _IMPL_OUT
        MockValid.return_value.run.return_value = _VALID_OUT
        MockTune.return_value.run.side_effect = _capture

        run_workflow(
            data_dir="/tmp/data",
            model_types=["punet"],
            source_run_name="v1",
            workspace=workspace,
            run_name="iter_002",
            start_iteration=2,
            max_iterations=1,
            source_paths=state.resolved_source_paths,
            restored_runtime_vocab=state.runtime_vocab,
            accumulated_key_findings=state.accumulated_key_findings,
            restored_model_knowledge_cache=state.model_knowledge_cache,
            accumulated_physical_rejections=state.accumulated_physical_rejections,
            accumulated_gate_exhaustions=state.accumulated_gate_exhaustions,
            restored_previous_proposal=state.previous_proposal_data,
            restored_chain_incumbent_score=state.chain_best_valid_formal_score,
            enable_chain_incumbent_formal_gates=enable_gates,
        )
    tune_input = captured_tune_inputs[0]
    # Mirror production: the tuner writes its run_output to disk before
    # write_manifest reads its sha256. Under the mocked HyperparamTuningAgent
    # the file wouldn't exist otherwise, and write_manifest would silently
    # skip the hash (P1-C2 write side).
    iter2_model_dir = os.path.join(
        workspace, "iter_002", "iteration_001", iter2_tune_output.model_type
    )
    os.makedirs(iter2_model_dir, exist_ok=True)
    with open(os.path.join(iter2_model_dir, "run_output_iter_002.json"), "w") as f:
        f.write(iter2_tune_output.model_dump_json())
    manifest = write_manifest(
        os.path.join(workspace, "iter_002"),
        "iter_002",
        [iter2_tune_output],
        chain_incumbent_used=(state.chain_best_valid_formal_score if enable_gates else None),
        chain_incumbent_source=state.chain_best_valid_formal_provenance,
    )
    return tune_input, manifest, state


# ---------------------------------------------------------------------------
# Branch A — numeric incumbent (flag ON)
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_branch_a_numeric_incumbent_threads_through_full_chain(tmp_path):
    """iter 1 commits valid_formal=1.25; iter 2's tuner input carries
    that value; iter 2's manifest stamps chain_incumbent_used=1.25 with
    source.iter_idx=1; iter 2's local best_valid_formal_score is
    ITER 2's own value (Invariant II)."""
    ws = str(tmp_path / "branch_a")
    os.makedirs(ws)

    # iter 1 → committed with a valid formal.
    iter1_out = _make_tune_output("iter_001", valid_formal=1.25, exp_id="f1")
    _write_iter_disk(ws, 1, iter1_out)

    # iter 2 → mocked tune returns an output with its OWN valid formal
    # (different value) so Invariant II can be asserted concretely.
    iter2_out = _make_tune_output("iter_002", valid_formal=0.60, exp_id="f2_local")
    tune_input, manifest, state = _run_iter_2(ws, iter2_out, enable_gates=True)

    # Reconstruction delivered iter 1's value.
    assert state.chain_best_valid_formal_score == 1.25
    assert state.chain_best_valid_formal_provenance["iter_idx"] == 1
    assert state.chain_best_valid_formal_provenance["exp_id"] == "f1"

    # The tuner input carried it as its formal reference.
    assert tune_input.current_run_best_formal_score == 1.25
    assert tune_input.enable_chain_incumbent_formal_gates is True

    # Iter 2's manifest stamps the chain-incumbent stuff under its own
    # keys (Invariant II).
    assert manifest["chain_incumbent_used"] == 1.25
    assert manifest["chain_incumbent_source"]["iter_idx"] == 1
    assert manifest["chain_incumbent_source"]["exp_id"] == "f1"
    assert manifest["chain_incumbent_source"]["artifact_verified"] is True

    # Iter 2's OWN local best is iter 2's value — NEVER contaminated by
    # the restored chain state.
    assert manifest["best_valid_formal_score"] == 0.60

    # Iter 2's own run_output_sha256 present (P1-C2 write side).
    assert "run_output_sha256" in manifest


# ---------------------------------------------------------------------------
# Branch B — no incumbent (flag ON, but iter 1 had no valid formal)
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_branch_b_no_incumbent_short_circuits(tmp_path):
    """iter 1 commits with no valid formal → iter 2's tuner input has
    ``current_run_best_formal_score = None`` (gates short-circuit) and
    manifest ``chain_incumbent_used = None``."""
    ws = str(tmp_path / "branch_b")
    os.makedirs(ws)

    iter1_out = _make_tune_output("iter_001", valid_formal=None, exp_id=None)
    _write_iter_disk(ws, 1, iter1_out)

    iter2_out = _make_tune_output("iter_002", valid_formal=0.75, exp_id="f2_local")
    tune_input, manifest, state = _run_iter_2(ws, iter2_out, enable_gates=True)

    # Reconstruction found no incumbent.
    assert state.chain_best_valid_formal_score is None
    assert state.chain_best_valid_formal_provenance is None

    # Tuner input receives None (short-circuit).
    assert tune_input.current_run_best_formal_score is None
    # Flag is ON, but with no reference there's nothing to consume.
    assert tune_input.enable_chain_incumbent_formal_gates is True

    # Manifest stamps reflect the no-incumbent state.
    assert manifest["chain_incumbent_used"] is None
    assert manifest["chain_incumbent_source"] is None

    # Iter 2's own best_valid_formal_score is iter 2's own value.
    assert manifest["best_valid_formal_score"] == 0.75


# ---------------------------------------------------------------------------
# Branch C — flag OFF (rollback path)
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_branch_c_flag_off_reconstruction_still_stamps_source(tmp_path):
    """Flag OFF: reconstruction, provenance dict, and
    ``chain_incumbent_source`` manifest key STILL run unconditionally
    (design §3.2: OFF never reinstates 0.0; it only disables gate
    consumption). ``chain_incumbent_used`` is None because gates are
    off. Tuner's ``current_run_best_formal_score`` sees None."""
    ws = str(tmp_path / "branch_c")
    os.makedirs(ws)

    iter1_out = _make_tune_output("iter_001", valid_formal=1.25, exp_id="f1")
    _write_iter_disk(ws, 1, iter1_out)

    iter2_out = _make_tune_output("iter_002", valid_formal=0.60, exp_id="f2_local")
    tune_input, manifest, state = _run_iter_2(ws, iter2_out, enable_gates=False)

    # Reconstruction still recovers the incumbent (unconditional).
    assert state.chain_best_valid_formal_score == 1.25
    assert state.chain_best_valid_formal_provenance["iter_idx"] == 1

    # Design §3.4 clarification: the numeric value IS carried through
    # the protocol/input (reconstruction + delivery are unconditional);
    # only CONSUMPTION is gated. Flag=False on the input tells the
    # tuner's internal resolver to short-circuit the gates. The
    # tuner-side flag-OFF short-circuit is covered by the P1-C1 unit
    # test `test_incumbent_provided_but_flag_off_not_consumed`.
    assert tune_input.current_run_best_formal_score == 1.25
    assert tune_input.enable_chain_incumbent_formal_gates is False

    # Manifest: chain_incumbent_used = None; source STILL stamped (so
    # a post-hoc auditor can see "the incumbent existed but was not
    # consumed" — the design's audit-grade provenance requirement).
    assert manifest["chain_incumbent_used"] is None
    assert manifest["chain_incumbent_source"] is not None
    assert manifest["chain_incumbent_source"]["iter_idx"] == 1
    assert manifest["chain_incumbent_source"]["exp_id"] == "f1"

    # Iter 2's own local best untouched.
    assert manifest["best_valid_formal_score"] == 0.60

    # Direct gate-consumption proof (operator requirement 2026-07-27):
    # replicate exactly what the tuner does — `_consumed_reference`
    # gates the incumbent on the flag, then the same resolver as
    # production runs — and assert (a) the reference actually consumed
    # is None, so both resolved thresholds are None, and (b) neither
    # incumbent-based gate can fire on ANY winning trial score. Uses
    # only production helpers; no re-implementation.
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _resolve_formal_comparison_thresholds,
        _should_bypass_formal_time_budget,
        _should_skip_formal,
    )

    consumed_reference = (
        tune_input.current_run_best_formal_score
        if tune_input.enable_chain_incumbent_formal_gates
        else None
    )
    ref, skip_t, bypass_t = _resolve_formal_comparison_thresholds(
        reference_score=consumed_reference,
        skip_min_delta=tune_input.skip_formal_min_delta,
        bypass_min_delta=tune_input.bypass_formal_time_budget_min_delta,
    )
    # Reference actually consumed is None (NOT the pre-V19 fixed 0.0,
    # and NOT the numeric 1.25 that was delivered on the input).
    assert consumed_reference is None
    assert ref is None and skip_t is None and bypass_t is None, (
        "flag OFF must resolve to None reference AND None thresholds — "
        "OFF is not a fixed-0.0 mode and gates must not consume the "
        "reconstructed incumbent"
    )
    # Neither incumbent-based gate can fire even against a trial winner
    # that would have easily crossed a numeric threshold.
    trial_winner_record = {
        "exp_id": "hypothetical_high_trial",
        "status": "success",
        "is_trial": True,
        "denoising_score": 99.0,
        "health_gate_results": _passing_verdicts(),
        "memory": {"time_mode": "trial"},
    }
    assert not _should_skip_formal([trial_winner_record], threshold=skip_t)
    assert not _should_bypass_formal_time_budget([trial_winner_record], threshold=bypass_t)


# ---------------------------------------------------------------------------
# Additional deterministic check — replay integrity is enforced end to
# end (fail-closed if a committed artifact changes between iterations).
# ---------------------------------------------------------------------------


@pytest.mark.dual_mode
def test_tampered_iter1_artifact_stops_the_chain(tmp_path):
    """A committed run_output whose bytes change after write_manifest
    recorded its sha256 raises ReplayIntegrityError at the next iter's
    restore_prior_state — same fail-closed behavior as the per-file
    best rebuild."""
    from core.resume import ReplayIntegrityError

    ws = str(tmp_path / "tamper")
    os.makedirs(ws)

    iter1_out = _make_tune_output("iter_001", valid_formal=1.25, exp_id="f1")
    manifest1 = _write_iter_disk(ws, 1, iter1_out)
    output_path = manifest1["output_path"]

    # Tamper: append a byte after the manifest hash was recorded.
    expected_sha = manifest1["run_output_sha256"]
    with open(output_path, "a") as f:
        f.write("\n")
    with open(output_path, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha != expected_sha  # sanity: the tamper actually changed the file

    with pytest.raises(ReplayIntegrityError) as exc:
        restore_prior_state(ws, current_iter=2, seed_paths=[])
    msg = str(exc.value)
    assert "REPLAY-INTEGRITY" in msg
    assert expected_sha[:16] in msg
    assert actual_sha[:16] in msg
