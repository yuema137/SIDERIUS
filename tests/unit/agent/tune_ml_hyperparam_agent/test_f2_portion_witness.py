"""Lane F2 — the DISCRIMINATIVE witness: frozen portions reach the runtime
consumer through the REAL production planning route (SRI-2, both directions).

The operator's evidence rule: "Do not accept a config/argv fingerprint alone
as evidence. Prove consumption at the runtime consumer." So both legs drive
``HyperparamTuningAgent.run`` itself (the real ``prepare_attempt`` →
``_apply_plan_overrides`` → ``_resolve_sample_set_cfg`` → records path, with
the LLM and heavy subsystems stubbed — the pseudo-full-loop shape), with a
predefined LLM plan that CARRIES CONFLICTING portions, and read the verdict
from the TRIAL RECORD's top-level ``trial_portion`` — written ONLY on trial
rounds (#316 B2's truth: ``records.py``, inside ``if trial_config.is_trial:``;
absence == formal), so the assertion never depends on a formal round.

Sentinels 0.07/0.11/0.13 collide with NO default anywhere in the chain:
ExperimentPlan 0.02/0.1/0.02 · formal_* 0.1/1.0/1.0 · the frozen campaign
sets {0.1, 0.01, 1.0} · the preflight authority 0.02/0.1 — a sentinel equal
to any of those would prove nothing.
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    _mock_run_skill,
    _synth_reference,
)
from workflows.run_config import WorkflowLaunchConfig, frozen_portion_overrides

#: The plan the "LLM" proposes every round — portions CONFLICT with the
#: sentinels on every field, so whichever value reaches the record names the
#: winning authority unambiguously.
CONFLICTING_PLAN = {
    **FAKE_PLAN_WITH_TRIAL,
    "trial_portion": 0.02,
    "train_portion": 0.5,
    "eval_portion": 0.02,
}

SENTINELS = {"trial_portion": 0.07, "train_portion": 0.11, "eval_portion": 0.13}


def _run_real_route(tmp_path, plan_overrides):
    """Drive the agent's real run() with the conflicting plan; return the
    saved records. max_rounds=2 so round 1 is a genuine TRIAL round (with
    max_rounds=1 the F14 satisfiability refusal correctly fires for the
    frozen leg — that interplay is pinned in test_plan_overrides_failfast)."""
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch("os.path.exists", return_value=True),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = CONFLICTING_PLAN
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        saved_records: list[dict] = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = saved_records.append
        mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        stub_scoring(mock_sandbox, [1.0] * 20, 1.5)

        inp = HyperparamTuningInput(
            model_type="punet",
            file_index=6,
            max_rounds=2,
            is_trial=True,
            expert_advice="",
            llm_provider="gemini",
            llm_model_id="test-model",
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="f2_witness"),
            ),
            progress_bar=False,
            plan_overrides=plan_overrides or {},
        )
        HyperparamTuningAgent().run(inp)
        return saved_records


def _trial_records(records):
    return [r for r in records if r.get("is_trial") is True and "trial_portion" in r]


def test_frozen_sentinels_beat_the_conflicting_plan_at_the_runtime_consumer(tmp_path):
    """THE witness, direction 1 — the defect only this catches: the frozen
    campaign portions failing to govern the EXECUTED trial workload (the
    original P0-1: the LLM plan silently winning). The launch types the
    sentinels; the merge produces the lock; the REAL planning route runs
    against a plan proposing 0.02/0.5/0.02; the trial record — the runtime
    consumer's own stamp — must carry the SENTINELS. Fails by: any plan
    value surviving to the record."""
    launch = WorkflowLaunchConfig(**SENTINELS)
    merged = frozen_portion_overrides(launch)
    assert merged == SENTINELS, "precondition: the merge carries exactly the sentinels"

    records = _trial_records(_run_real_route(tmp_path, merged))
    assert records, "the route must produce at least one trial record"
    for rec in records:
        assert rec["trial_portion"] == 0.07
        assert rec["train_portion"] == 0.11
        assert rec["eval_portion"] == 0.13


def test_unfrozen_launch_lets_the_plan_execute_the_inverse_leg(tmp_path):
    """THE witness, direction 2 (the half most people skip) — the defect
    only this catches: the repair over-reaching, i.e. AGENT_CONTROLLED
    portions no longer executing (some default sneaking into the lock on a
    bare launch — the supervisor-pinned unchanged-behavior property, at the
    runtime consumer rather than the helper). Fails by: the record carrying
    anything but the PLAN's values."""
    launch = WorkflowLaunchConfig()
    assert frozen_portion_overrides(launch) is None, "precondition: bare launch merges nothing"

    records = _trial_records(_run_real_route(tmp_path, frozen_portion_overrides(launch)))
    assert records, "the route must produce at least one trial record"
    for rec in records:
        assert rec["trial_portion"] == 0.02
        assert rec["train_portion"] == 0.5
        assert rec["eval_portion"] == 0.02
