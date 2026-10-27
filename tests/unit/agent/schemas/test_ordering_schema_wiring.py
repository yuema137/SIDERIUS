"""Ordering fields on the tuner schemas: proposal, override, resolved.

Three intake levels, three schemas:

- ``ExperimentPlan``          — the agent's PROPOSAL (intent)
- ``HyperparamTuningInput``   — the operator's OVERRIDE (control)
- ``TrialConfig``             — the RESOLVED value (execution truth)

with ``ExperimentRecord`` carrying all three plus the resolution source.

These tests cover the wiring and the schema/runtime validation split; the
precedence logic itself is tested in ``test_ordering.py``.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    ExperimentPlan,
    HyperparamTuningInput,
    TrialConfig,
    validate_runtime_config,
)
from execute_tools.dataset_config import DataScope

SCOPE_SPEC = "4-9"
SCOPE = [4, 5, 6, 7, 8, 9]
PERMUTATION = [4, 6, 5, 9, 7, 8]


def _input(**overrides) -> HyperparamTuningInput:
    base = {"model_type": "wavenet", "run_name": "ordering_wiring_test"}
    return HyperparamTuningInput(**{**base, **overrides})


def _trial_config(**overrides) -> TrialConfig:
    base = {
        "is_trial": True,
        "mode": "trial",
        "train_sampling_seed": 1,
        "eval_sampling_seed": 1,
        "train_base_seed": 2,
    }
    return TrialConfig(**{**base, **overrides})


# ---- ExperimentPlan: the agent's proposal ----


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_strategy": "shuffle", "file_order": [4, 5]},  # file order + shuffle
        {"file_order": [4, 5]},  # file order, no strategy
        {"order_strategy": "sequential", "file_order": []},  # empty
        {"order_strategy": "sequential", "file_order": [4, 4, 5]},  # duplicate
        {"order_strategy": "sequential", "file_order": [-1, 4]},  # negative
    ],
)
def test_plan_rejects_structurally_invalid_proposals(kwargs):
    with pytest.raises(ValidationError) as exc:
        ExperimentPlan(**kwargs)
    assert "agent proposal" in str(exc.value)


def test_with_defaults_drops_a_malformed_ordering_proposal_instead_of_raising():
    """Established LLM-robustness contract: a bad trial field falls back to
    defaults rather than killing the round. The proposal is simply absent,
    which is what the record will then honestly report."""
    plan = ExperimentPlan.with_defaults(
        {
            "model_type": "wavenet",
            "hypothesis": "kept",
            "order_strategy": "sequential",
            "file_order": [4, 4, 4],  # duplicates — structurally invalid
        }
    )
    assert plan.order_strategy is None
    assert plan.file_order is None
    assert plan.model_type == "wavenet"
    assert plan.hypothesis == "kept"


def test_with_defaults_keeps_a_valid_ordering_proposal():
    plan = ExperimentPlan.with_defaults(
        {"model_type": "wavenet", "order_strategy": "sequential", "file_order": PERMUTATION}
    )
    assert plan.order_strategy == "sequential"
    assert plan.file_order == PERMUTATION


# ---- HyperparamTuningInput: the operator's override ----


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_strategy_override": "shuffle", "file_order_override": [4, 5]},
        {"file_order_override": [4, 5]},
        {"order_strategy_override": "sequential", "file_order_override": []},
        {"order_strategy_override": "sequential", "file_order_override": [4, 4]},
    ],
)
def test_input_rejects_structurally_invalid_overrides(kwargs):
    with pytest.raises(ValidationError) as exc:
        _input(**kwargs)
    assert "operator override" in str(exc.value)


# ---- the schema / runtime validation split ----


def test_validate_runtime_config_rejects_a_subset_override():
    agent_input = _input(
        data_scope=DataScope.from_cli(SCOPE_SPEC),
        order_strategy_override="sequential",
        file_order_override=[4, 6, 5],
        health_gate_files=SCOPE,
    )
    with pytest.raises(ValueError) as exc:
        validate_runtime_config(agent_input)
    assert "not a full permutation" in str(exc.value)


def test_validate_runtime_config_accepts_a_full_permutation():
    agent_input = _input(
        data_scope=DataScope.from_cli(SCOPE_SPEC),
        order_strategy_override="sequential",
        file_order_override=PERMUTATION,
        health_gate_files=SCOPE,
    )
    assert validate_runtime_config(agent_input) == SCOPE


def test_override_is_validated_under_a_FULL_scope_too():
    """Regression guard: validate_runtime_config early-returns for full
    scopes, so the ordering check must precede that return."""
    agent_input = _input(
        order_strategy_override="sequential",
        file_order_override=[0, 1, 2],  # nowhere near the full 20-file scope
    )
    with pytest.raises(ValueError) as exc:
        validate_runtime_config(agent_input)
    assert "not a full permutation" in str(exc.value)


def test_no_override_passes_runtime_validation_unchanged():
    assert validate_runtime_config(_input()) == list(range(20))


# ---- TrialConfig: the resolved value ----


def test_trial_config_rejects_a_file_order_under_shuffle():
    """A stale file order alongside shuffle would misreport what ran."""
    with pytest.raises(ValidationError) as exc:
        _trial_config(resolved_order_strategy="shuffle", resolved_file_order=PERMUTATION)
    assert "must be None when resolved_order_strategy" in str(exc.value)


# ---- ExperimentRecord: the provenance septet ----
