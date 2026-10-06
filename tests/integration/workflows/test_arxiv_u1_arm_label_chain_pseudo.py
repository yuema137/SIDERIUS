"""arXiv U1 (#253 / #254) — the arm label across a two-iteration chain.

Pseudo mode only: all five agents are mocked at the workflow boundary, no
LLM call, no training. Every other piece is the REAL production path —
``compute_expected_invariants`` + ``resolve_launch_identity`` (the chain
runner's pre-flight), ``restore_prior_state``, ``run_workflow`` (which
creates / validates the workspace lock and validates ingress evidence) and
``write_manifest``.

What only this file catches:

* the label survives the process boundary: iteration 2 restores iteration 1
  from disk and hands the tuner the SAME label it locked, with the lock
  bytes unchanged;
* a second launch under a different label — or no label — is refused by the
  EXISTING lock comparison, naming ``experiment_arm``;
* a labelled iteration refuses to restore an UNSTAMPED (pre-U1 / other-arm)
  output at the workflow pre-flight, before any node runs.
* agent-owned Formal training scope survives the real iteration-2 restore
  instead of being replaced by the operator default at the chain pre-flight.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.resume import restore_prior_state as _restore_prior_state_impl
from core.run_invariants import RUN_INVARIANTS_BASENAME, RunInvariantsViolation
from tests.integration.workflows.test_chain_candidate_graduation import _llm_config_pseudo
from tests.unit.workflows.test_model_exploration import (
    _make_implementor_output,
    _make_interpretation_output,
    _make_proposal_output,
    _make_tuning_output,
    _make_validator_output,
)
from workflows.model_exploration import run_workflow
from workflows.run_config import WorkflowLaunchConfig
from workflows.task_composition import (
    bind_run_task_composition,
    compose_run_task_bindings,
)

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_spec = importlib.util.spec_from_file_location(
    "run_one_iteration_for_arm_chain_test",
    _REPO / "src" / "workflows" / "run_one_iteration.py",
)
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)

COMPOSITION = compose_run_task_bindings(_REPO / "configs/task_composition/quickstart.yaml")

MODEL = "gated_tcn"
WITH = "with-prior-art"
WITHOUT = "without-prior-art"


def _restore_prior_state(*args, **kwargs):
    kwargs.setdefault("dataset_partition_count", COMPOSITION.dataset_profile.partition_count)
    return _restore_prior_state_impl(*args, **kwargs)


def _chain_args(
    workspace: str,
    iteration: int,
    arm: str | None,
    *,
    formal_training_scope_source: str = "operator",
):
    argv = [
        "--workspace",
        workspace,
        "--start_iteration",
        str(iteration),
        "--run_name",
        "arm",
        "--task_composition",
        str(_REPO / "configs/task_composition/quickstart.yaml"),
        "--data_dir",
        str(_REPO),
    ]
    if arm is not None:
        argv += ["--experiment_arm", arm]
    argv += ["--formal_training_scope_source", formal_training_scope_source]
    # Production posture (gates ON): the pre-flight materializes the effective
    # Health config into the workspace exactly as the chain runner does, and
    # the workflow's own pre-flight recomputes the identical sha (W7).
    return roi.build_parser().parse_args(argv)


def _run_iteration(
    workspace: str,
    iteration: int,
    *,
    arm: str | None,
    state,
    tune_output,
    probe=None,
    formal_training_scope_source: str = "operator",
):
    """One chain iteration exactly as the runner sequences it, agents mocked.

    ``probe`` (a dict) receives ``node_runs`` — how many times the first node
    ran — even when the workflow raises, so a refusal can be shown to have
    happened BEFORE any node executed.
    """
    captured = []

    def _capture(inp):
        captured.append(inp)
        return tune_output

    with (
        patch("workflows.model_exploration.ResultInterpretationAgent") as MockInterp,
        patch("workflows.model_exploration.MLModelProposalAgent") as MockPropose,
        patch("workflows.model_exploration.MLModelImplementor") as MockImpl,
        patch("workflows.model_exploration.MLCodeValidatorAgent") as MockValid,
        patch("workflows.model_exploration.HyperparamTuningAgent") as MockTune,
    ):
        MockInterp.return_value.run.return_value = _make_interpretation_output()
        MockPropose.return_value.run.return_value = _make_proposal_output(model_name=MODEL)
        MockImpl.return_value.run.return_value = _make_implementor_output(model_type=MODEL)
        MockValid.return_value.run.return_value = _make_validator_output(passed=True)
        MockTune.return_value.run.side_effect = _capture
        try:
            with bind_run_task_composition(COMPOSITION, physical_data_root=str(_REPO)):
                run_workflow(
                    launch=WorkflowLaunchConfig(
                        data_dir=str(_REPO),
                        source_paths=state.resolved_source_paths,
                        max_iterations=1,
                        start_iteration=iteration,
                        experiment_arm=arm,
                        formal_training_scope_source=formal_training_scope_source,
                    ),
                    workspace=workspace,
                    run_name=f"iter_{iteration:03d}",
                    llm_config=_llm_config_pseudo(),
                    restored_state=state,
                    task_composition=COMPOSITION,
                )
        finally:
            if probe is not None:
                probe["node_runs"] = MockInterp.return_value.run.call_count
    return captured


def _commit_iteration(workspace: str, iteration: int, tune_output, identity) -> None:
    """Persist iteration N's artifacts the way the chain runner does."""
    run_name = f"iter_{iteration:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, "iteration_001", tune_output.model_type)
    os.makedirs(model_dir, exist_ok=True)
    with open(os.path.join(model_dir, f"run_output_{run_name}.json"), "w") as f:
        f.write(tune_output.model_dump_json())
    roi.write_manifest(iter_dir, run_name, [tune_output], launch_identity=identity)


def _output(iteration: int, *, arm: str | None):
    """What the REAL tuner returns for a labelled run (its stamp is proven by
    the bounded pseudo iteration in the unit tier); here the tuner is mocked,
    so the fixture carries the label the tuner would have stamped."""
    return _make_tuning_output(
        model_type=MODEL,
        run_name=f"iter_{iteration:03d}",
        fingerprint=COMPOSITION.semantic_fingerprint,
        metric_spec=COMPOSITION.metric.spec,
    ).model_copy(update={"experiment_arm": arm})


def _expected_invariants(args, *, launch_identity=None):
    return roi.compute_expected_invariants(
        args,
        run_composition=COMPOSITION,
        launch_identity=launch_identity,
        llm_config=_llm_config_pseudo(),
    )


def _labelled_iteration_one(workspace: str, *, output_arm: str | None = WITH):
    """Iteration 1 under the WITH label; returns the lock bytes it created."""
    args1 = _chain_args(workspace, 1, WITH)
    identity = roi.resolve_launch_identity(args1)
    state1 = _restore_prior_state(
        workspace,
        current_iter=1,
        seed_paths=[],
        expected_invariants=_expected_invariants(args1, launch_identity=identity),
    )
    out1 = _output(1, arm=output_arm)
    captured = _run_iteration(workspace, 1, arm=WITH, state=state1, tune_output=out1)
    assert captured[0].experiment_arm == WITH
    _commit_iteration(workspace, 1, out1, identity)
    return (Path(workspace) / RUN_INVARIANTS_BASENAME).read_bytes()


@pytest.mark.dual_mode
def test_the_label_survives_restore_and_is_relocked_identically(tmp_path):
    ws = str(tmp_path / "chain")
    os.makedirs(ws)
    lock_after_iter_1 = _labelled_iteration_one(ws)
    lock = json.loads(lock_after_iter_1)
    assert lock["experiment_arm"] == WITH
    assert "lit_review_enabled" not in lock and "lit_review_config_sha256" not in lock
    manifest = json.loads((Path(ws) / "iter_001" / "manifest.json").read_text())
    assert manifest["experiment_arm"] == WITH

    args2 = _chain_args(ws, 2, WITH)
    identity2 = roi.resolve_launch_identity(args2)
    state2 = _restore_prior_state(
        ws,
        current_iter=2,
        seed_paths=[],
        expected_invariants=_expected_invariants(args2, launch_identity=identity2),
    )
    assert state2.committed_iters == [1]
    captured = _run_iteration(ws, 2, arm=WITH, state=state2, tune_output=_output(2, arm=WITH))
    tune_input = captured[0]
    assert tune_input.experiment_arm == WITH
    assert tune_input.lit_review_enabled is False
    assert tune_input.lit_review_config_sha256 is None
    # The workspace lock was VALIDATED, not rewritten: byte-identical.
    assert (Path(ws) / RUN_INVARIANTS_BASENAME).read_bytes() == lock_after_iter_1


@pytest.mark.dual_mode
def test_agent_owned_formal_training_scope_survives_iteration_two_restore(tmp_path):
    """Regression for #563: both lock construction sites must preserve `agent`."""
    ws = str(tmp_path / "chain")
    os.makedirs(ws)
    args1 = _chain_args(ws, 1, WITH, formal_training_scope_source="agent")
    identity1 = roi.resolve_launch_identity(args1)
    state1 = _restore_prior_state(
        ws,
        current_iter=1,
        seed_paths=[],
        expected_invariants=_expected_invariants(args1, launch_identity=identity1),
    )
    out1 = _output(1, arm=WITH)
    _run_iteration(
        ws,
        1,
        arm=WITH,
        state=state1,
        tune_output=out1,
        formal_training_scope_source="agent",
    )
    _commit_iteration(ws, 1, out1, identity1)
    lock_path = Path(ws) / RUN_INVARIANTS_BASENAME
    lock_after_iter_1 = lock_path.read_bytes()
    assert json.loads(lock_after_iter_1)["formal_training_scope_source"] == "agent"

    args2 = _chain_args(ws, 2, WITH, formal_training_scope_source="agent")
    state2 = _restore_prior_state(
        ws,
        current_iter=2,
        seed_paths=[],
        expected_invariants=_expected_invariants(args2),
    )
    assert state2.committed_iters == [1]
    assert _expected_invariants(args2).formal_training_scope_source == "agent"
    assert lock_path.read_bytes() == lock_after_iter_1


@pytest.mark.dual_mode
@pytest.mark.parametrize("second_arm", [WITHOUT, None], ids=["other-arm", "unlabelled"])
def test_a_different_or_missing_label_is_refused_by_the_lock(tmp_path, second_arm):
    ws = str(tmp_path / "chain")
    os.makedirs(ws)
    _labelled_iteration_one(ws)
    args2 = _chain_args(ws, 2, second_arm)
    with pytest.raises(RunInvariantsViolation) as exc:
        _restore_prior_state(
            ws,
            current_iter=2,
            seed_paths=[],
            expected_invariants=_expected_invariants(args2),
        )
    msg = str(exc.value)
    assert "experiment_arm" in msg
    assert f"locked={WITH!r}" in msg


@pytest.mark.dual_mode
def test_restore_refuses_an_unstamped_output_under_a_labelled_lock(tmp_path):
    """Case 3 of the ingress rule at the chain runner's restore: the
    iteration-1 artifact carries no arm (a pre-U1 or foreign artifact under a
    labelled lock). Refused before the plugin is registered.

    This is the refusal the two-iteration chain found MISSING: the restore
    site forwarded every other stamp but not the arm, so a labelled chain
    could not even read its own history."""
    ws = str(tmp_path / "chain")
    os.makedirs(ws)
    _labelled_iteration_one(ws, output_arm=None)
    args2 = _chain_args(ws, 2, WITH)
    with pytest.raises(RunInvariantsViolation, match="experiment_arm") as exc:
        _restore_prior_state(
            ws,
            current_iter=2,
            seed_paths=[],
            expected_invariants=_expected_invariants(args2),
        )
    assert "LABELLED" in str(exc.value)


@pytest.mark.dual_mode
def test_the_workflow_preflight_refuses_an_unstamped_output_before_any_node_runs(tmp_path):
    """The same case 3 at the workflow's OWN pre-flight, with the restore-time
    check bypassed (``expected_invariants=None`` — a caller that predates
    DS6c, or a seed path, which restore never parses). No interpreter ran,
    so no LLM was spent on evidence the run cannot certify."""
    ws = str(tmp_path / "chain")
    os.makedirs(ws)
    _labelled_iteration_one(ws, output_arm=None)
    state2 = _restore_prior_state(ws, current_iter=2, seed_paths=[])
    probe: dict = {}
    with pytest.raises(RunInvariantsViolation, match="experiment_arm") as exc:
        _run_iteration(ws, 2, arm=WITH, state=state2, tune_output=_output(2, arm=WITH), probe=probe)
    assert "LABELLED" in str(exc.value)
    assert probe["node_runs"] == 0
