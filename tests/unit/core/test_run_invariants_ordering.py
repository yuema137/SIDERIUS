"""Chain-lock semantics for the data-ordering override (V19 PR 2).

The lock pins the operator's ordering OVERRIDE — the chain's control
policy — and deliberately does NOT pin each round's resolved ordering.
Changing the override mid-chain would invalidate the comparison the chain
exists to make; varying the resolved value round to round is the intended
behavior when the agent is exploring and no override is set.

Resume matrix from ``docs/design/v19_priorities/pr2_data_ordering.md`` §3.8.
"""

import json
import os

import pytest

from core.run_invariants import (
    RUN_INVARIANTS_BASENAME,
    RunInvariants,
    RunInvariantsViolation,
    build_run_invariants,
    ensure_run_invariants,
    load_run_invariants,
    validate_run_invariants,
)

SCOPE = [4, 5, 6, 7, 8, 9]
PERMUTATION = [4, 6, 5, 9, 7, 8]


def _invariants(**overrides) -> RunInvariants:
    base = {
        "resolved_data_scope": SCOPE,
        "health_gate_enabled": False,
        "health_config_sha256": None,
    }
    return RunInvariants(**{**base, **overrides})


# ---- the override participates in lock identity ----


def test_same_override_on_resume_is_accepted(tmp_path):
    ws = str(tmp_path)
    locked = _invariants(
        ordering_override_strategy="sequential",
        ordering_override_file_order=PERMUTATION,
    )
    assert ensure_run_invariants(ws, locked) == "created"
    assert ensure_run_invariants(ws, locked) == "validated"


def test_changed_override_strategy_is_rejected(tmp_path):
    ws = str(tmp_path)
    ensure_run_invariants(ws, _invariants(ordering_override_strategy="sequential"))
    with pytest.raises(RunInvariantsViolation) as exc:
        validate_run_invariants(ws, _invariants(ordering_override_strategy="shuffle"))
    message = str(exc.value)
    assert "ordering_override_strategy" in message
    assert "'sequential'" in message and "'shuffle'" in message


def test_changed_override_file_order_is_rejected(tmp_path):
    ws = str(tmp_path)
    ensure_run_invariants(
        ws,
        _invariants(
            ordering_override_strategy="sequential",
            ordering_override_file_order=PERMUTATION,
        ),
    )
    with pytest.raises(RunInvariantsViolation) as exc:
        validate_run_invariants(
            ws,
            _invariants(
                ordering_override_strategy="sequential",
                ordering_override_file_order=[9, 8, 7, 6, 5, 4],
            ),
        )
    assert "ordering_override_file_order" in str(exc.value)


def test_dropping_an_override_mid_chain_is_rejected(tmp_path):
    """Removing the override is as much a policy change as swapping it."""
    ws = str(tmp_path)
    ensure_run_invariants(ws, _invariants(ordering_override_strategy="sequential"))
    with pytest.raises(RunInvariantsViolation):
        validate_run_invariants(ws, _invariants())


def test_adding_an_override_mid_chain_is_rejected(tmp_path):
    ws = str(tmp_path)
    ensure_run_invariants(ws, _invariants())
    with pytest.raises(RunInvariantsViolation):
        validate_run_invariants(ws, _invariants(ordering_override_strategy="shuffle"))


# ---- the RESOLVED ordering is deliberately NOT locked ----


def test_no_override_chain_accepts_any_number_of_resumes(tmp_path):
    """Agent-exploration mode: no override, so the resolved ordering may
    differ every round. The lock has nothing to say about that — it must not
    block the resume."""
    ws = str(tmp_path)
    invariants = _invariants()
    assert ensure_run_invariants(ws, invariants) == "created"
    for _ in range(3):
        assert ensure_run_invariants(ws, invariants) == "validated"


def test_lock_stores_no_resolved_ordering_field():
    """Guard against a future change quietly locking the outcome."""
    assert "ordering_override_strategy" in RunInvariants._CANONICAL
    assert "ordering_override_file_order" in RunInvariants._CANONICAL
    assert not any("resolved_order" in name for name in RunInvariants._CANONICAL)


# ---- legacy workspaces ----


def test_legacy_lock_without_ordering_keys_loads_as_no_override(tmp_path):
    """A pre-PR2 lock file has no ordering keys at all. It must read as
    'no override' — not trip the corruption guard, and not be rewritten."""
    ws = str(tmp_path)
    legacy = {
        "resolved_data_scope": SCOPE,
        "health_gate_enabled": False,
        "health_config_sha256": None,
        "created_at": "2026-07-01T00:00:00Z",
    }
    path = os.path.join(ws, RUN_INVARIANTS_BASENAME)
    with open(path, "w") as f:
        json.dump(legacy, f)

    loaded = load_run_invariants(ws)
    assert loaded is not None
    assert loaded.ordering_override_strategy is None
    assert loaded.ordering_override_file_order is None


def test_legacy_workspace_resumes_when_no_override_is_requested(tmp_path):
    ws = str(tmp_path)
    with open(os.path.join(ws, RUN_INVARIANTS_BASENAME), "w") as f:
        json.dump(
            {
                "resolved_data_scope": SCOPE,
                "health_gate_enabled": False,
                "health_config_sha256": None,
            },
            f,
        )
    validate_run_invariants(ws, _invariants())


def test_legacy_workspace_rejects_a_newly_added_override(tmp_path):
    """Starting to force an ordering is a control-policy change, so it needs
    a new workspace — same rule as a scope change or a gate flip."""
    ws = str(tmp_path)
    with open(os.path.join(ws, RUN_INVARIANTS_BASENAME), "w") as f:
        json.dump(
            {
                "resolved_data_scope": SCOPE,
                "health_gate_enabled": False,
                "health_config_sha256": None,
            },
            f,
        )
    with pytest.raises(RunInvariantsViolation) as exc:
        validate_run_invariants(ws, _invariants(ordering_override_strategy="sequential"))
    assert "ordering_override_strategy" in str(exc.value)


# ---- build_run_invariants plumbing ----


def test_build_defaults_to_no_override(tmp_path):
    invariants, effective = build_run_invariants(
        resolved_data_scope=SCOPE,
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(tmp_path),
    )
    assert invariants.ordering_override_strategy is None
    assert invariants.ordering_override_file_order is None
    assert effective is None


def test_build_carries_the_override_through(tmp_path):
    invariants, _ = build_run_invariants(
        resolved_data_scope=SCOPE,
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(tmp_path),
        ordering_override_strategy="sequential",
        ordering_override_file_order=PERMUTATION,
    )
    assert invariants.ordering_override_strategy == "sequential"
    assert invariants.ordering_override_file_order == PERMUTATION


def test_build_copies_the_file_order(tmp_path):
    """The lock must not alias a caller's mutable list."""
    caller_list = list(PERMUTATION)
    invariants, _ = build_run_invariants(
        resolved_data_scope=SCOPE,
        health_gate_enabled=False,
        health_gate_files=None,
        health_checks_config=None,
        workspace=str(tmp_path),
        ordering_override_strategy="sequential",
        ordering_override_file_order=caller_list,
    )
    caller_list.append(99)
    assert invariants.ordering_override_file_order == PERMUTATION


def test_override_survives_a_lock_write_read_round_trip(tmp_path):
    ws = str(tmp_path)
    ensure_run_invariants(
        ws,
        _invariants(
            ordering_override_strategy="sequential",
            ordering_override_file_order=PERMUTATION,
        ),
    )
    reloaded = load_run_invariants(ws)
    assert reloaded is not None
    assert reloaded.ordering_override_strategy == "sequential"
    assert reloaded.ordering_override_file_order == PERMUTATION
