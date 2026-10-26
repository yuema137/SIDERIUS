"""A Gate flag must survive every hop, or it bounds nothing.

THE DEFECT THIS EXISTS FOR, 2026-08-14 — twice in one afternoon.
`--validation_max_train_samples` and `--validation_max_phase_seconds`
were wired from the shell into `_build_runtime_policy`, with focused
tests at both ends. Every one passed. Two real Gate launches died:

    TypeError: run_workflow() got an unexpected keyword argument
               'validation_max_train_samples'
    TypeError: local_validated_model() got an unexpected keyword
               argument 'validation_max_train_samples'

Both take explicit keywords. Testing the ends and trusting the middle
found neither; a signature comparison finds both in milliseconds, and
the second was discovered only after fixing the first — which is what
happens when a test is written for the hop that just broke instead of
for the chain.

So this module asserts the WHOLE path:

    _chain_common.sh  ->  run_one_iteration.py   (test_chain_consistency)
                      ->  run_workflow()          } this module
                      ->  local_validated_model() } every hop, every flag
                      ->  HyperparamTuningInput

These flags exist solely to bound a Gate, which makes their silent loss
the most expensive kind: a dropped bound does not fail — it runs for an
hour and reports success.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from tests.helpers.launcher_bindings import workflow_call_bindings
from workflows.run_config import WorkflowLaunchConfig
from workflows.run_one_iteration import build_parser

#: Every hop between the CLI and the tuner input that declares its parameters
#: EXPLICITLY, so an unknown keyword is a TypeError at launch. Both entries
#: were added by a real Gate failure, in this order.
#:
#: Step 09.5a C3: the workflow hop is now the typed carrier rather than
#: ``run_workflow``'s own signature — the validation flags are transit
#: configuration and live on ``WorkflowLaunchConfig``. The invariant is
#: unchanged and still the one the Gate failure taught: every hop must DECLARE
#: the flag, so a dropped one is a launch-time error rather than a silently
#: ignored bound.
FORWARDING_HOPS = (WorkflowLaunchConfig, local_validated_model)

#: Every CLI flag whose job is to bound validation work. Derived from the
#: parser rather than listed, so a NEW validation flag is covered the
#: moment it is added — a hand-maintained list would have to be updated
#: by the same person who forgot the middle hop.
VALIDATION_FLAGS: tuple[str, ...] = tuple(
    sorted(
        option.removeprefix("--")
        for action in build_parser()._actions
        for option in action.option_strings
        if option.startswith("--validation_")
    )
)


def test_there_are_validation_flags_to_check():
    """A parametrize over an empty list is a green test that checks
    nothing — the failure mode of every derived-list test.
    """
    assert VALIDATION_FLAGS, "no --validation_* flags found; the derivation is broken"


def _call_keywords(owner, callee):
    """Read the real named call, excluding comments and neighboring calls."""
    calls = [
        n
        for n in ast.walk(ast.parse(inspect.getsource(owner)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
    ]
    assert len(calls) == 1, f"expected one {callee} call"
    return {kw.arg: ast.unparse(kw.value) for kw in calls[0].keywords}


@pytest.mark.parametrize("flag", VALIDATION_FLAGS)
def test_each_hop_accepts_what_the_previous_hop_forwards(flag):
    """Unknown keywords must fail here, not during a real Gate launch.

    Follow the reachable standard projection rather than main's former flat
    call; otherwise extraction makes every case return without checking anything.
    The fixed candidate plan is consumed by the workflow, not the tuner.
    """
    from workflows import tuner_preparation

    source = Path(__file__).resolve().parents[3] / "src/workflows/run_one_iteration.py"
    forwarded = workflow_call_bindings(source)
    assert flag in forwarded, f"standard launch dropped {flag}"
    expected = (
        "fixed_candidate_plan" if flag == "validation_fixed_candidate_plan" else f"args.{flag}"
    )
    assert forwarded[flag] == expected
    assert flag in inspect.signature(WorkflowLaunchConfig).parameters
    protocol = _call_keywords(tuner_preparation.prepare_native_tuner_input, "local_validated_model")
    if flag in protocol:
        assert flag in inspect.signature(local_validated_model).parameters
        assert flag in HyperparamTuningInput.model_fields
    else:
        assert flag == "validation_fixed_candidate_plan", f"protocol dropped bound {flag}"


@pytest.mark.parametrize("flag", VALIDATION_FLAGS)
def test_no_validation_flag_is_accepted_and_then_dropped(flag):
    """A declared ceiling must retain its value through builder and protocol.

    Exact call arguments catch dropped, swapped and constant values; occurrence
    counts could pass on a comment or an unrelated neighboring call.
    """
    from workflows import model_exploration, tuner_preparation

    if flag == "validation_fixed_candidate_plan":
        tree = ast.parse(inspect.getsource(model_exploration.run_workflow))
        plans = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and ast.unparse(n.func) == "ProposalOutput.model_validate"
        ]
        assert any(
            [ast.unparse(arg) for arg in call.args] == [f"launch.{flag}"] for call in plans
        ), "workflow dropped the fixed validation plan"
        return
    workflow = _call_keywords(model_exploration.run_workflow, "prepare_native_tuner_input")
    assert workflow.get("launch") == "launch", "workflow bypassed the launch carrier"
    protocol = _call_keywords(tuner_preparation.prepare_native_tuner_input, "local_validated_model")
    assert protocol.get(flag) == f"launch.{flag}", f"builder dropped/swapped {flag}"
    tuner_input = _call_keywords(local_validated_model, "HyperparamTuningInput")
    assert tuner_input.get(flag) == flag, f"protocol dropped/swapped {flag}"


@pytest.mark.parametrize("flag", VALIDATION_FLAGS)
def test_every_validation_bound_defaults_to_off(flag):
    """Validation posture must be invisible to production.

    Fails when: any of these acquires a non-None default, which would
    apply a Gate's workload ceiling or kill deadline to a real
    scientific campaign.
    """
    for hop in FORWARDING_HOPS:
        parameter = inspect.signature(hop).parameters.get(flag)
        if parameter is None:
            continue
        assert parameter.default is None, (
            f"{flag} defaults to {parameter.default!r} at {hop.__name__}; "
            f"every ordinary campaign would inherit it"
        )
    if flag in HyperparamTuningInput.model_fields:
        assert HyperparamTuningInput.model_fields[flag].default is None, (
            f"{flag} has a non-None default on the tuner input"
        )
