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

import inspect

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from sdsc_submission_scripts.run_one_iteration import build_parser, main
from workflows.model_exploration import run_workflow

#: Every callable between the CLI and the tuner input that declares its
#: parameters EXPLICITLY, so an unknown keyword is a TypeError at launch.
#: Both entries were added by a real Gate failure, in this order.
FORWARDING_HOPS = (run_workflow, local_validated_model)

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


@pytest.mark.parametrize("flag", VALIDATION_FLAGS)
def test_each_hop_accepts_what_the_previous_hop_forwards(flag):
    """Walk the chain: forwarded by hop N -> must be declared by hop N+1.

    Not "every hop takes every flag" — that is false and would be the
    same mistake in reverse. ``validation_fixed_candidate_plan``
    legitimately stops at the workflow, which consumes it to bypass the
    proposer; it never reaches the tuner protocol and must not be
    required to.

    The real invariant is narrower and is exactly what broke twice: a
    keyword one function hands to the next must be one the next function
    declares. Forwarding is read from source as ``name=`` in the caller,
    which is the form every hop here uses.
    """
    forwarded_from = "run_one_iteration.main"
    forwarded = f"{flag}=args.{flag}" in inspect.getsource(main)

    for hop in FORWARDING_HOPS:
        if not forwarded:
            return  # the flag's journey ended at the previous hop
        assert flag in inspect.signature(hop).parameters, (
            f"{forwarded_from} forwards {flag} to {hop.__name__}(), which does "
            f"not declare it; the chain raises TypeError at launch"
        )
        forwarded_from = hop.__name__
        forwarded = f"{flag}={flag}" in inspect.getsource(hop)

    if forwarded:
        assert flag in HyperparamTuningInput.model_fields, (
            f"{forwarded_from} forwards {flag} to HyperparamTuningInput, which does not declare it"
        )


@pytest.mark.parametrize("flag", VALIDATION_FLAGS)
def test_no_validation_flag_is_accepted_and_then_dropped(flag):
    """Accepted-but-unused is the SILENT version of the same defect.

    A TypeError at least stops the run. A parameter a hop declares and
    never passes on produces a Gate that starts, runs unbounded, and
    reports success — the bound existing only in the command line.

    Occurrence counting, not a call graph: a used parameter appears at
    least twice in the function source (its declaration and its use),
    a dropped one exactly once.
    """
    for hop in FORWARDING_HOPS:
        if flag not in inspect.signature(hop).parameters:
            continue  # a flag whose path stops before this hop
        source = inspect.getsource(hop)
        assert source.count(flag) >= 2, (
            f"{hop.__name__}() declares {flag} but never uses it; the bound "
            f"would be silently discarded rather than failing loudly"
        )


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
