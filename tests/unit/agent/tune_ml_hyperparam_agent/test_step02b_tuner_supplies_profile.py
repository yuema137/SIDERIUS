"""PR-02b B2 — the REAL tuner path supplies the profile explicitly.

`test_step02b_b2_explicit_profile_selection.py` proves the builder honours an
explicit profile. That is not the same claim as *production supplies one*: a
parameter with a `None` default is invisible to every caller that never
passes it. This module drives the actual `HyperparamTuningAgent.run()` and
asserts the production call sites pass it.

Failure class guarded (design §8): **ambient-fallback reachability**.

Method: `build_sample_set` stays REAL — only wrapped in a recording spy —
while ambient resolution inside the builder is made to RAISE. A tuner site
that stopped passing `profile=` would fall through to the ambient resolver,
so the spy records the omission AND the resolver records the consultation.
Both are asserted, so the test cannot pass because the tuner swallowed an
exception somewhere up the stack.

Both modes are exercised. Per the §13.0 audit the tuner has ONE pair of
`build_sample_set` calls (train + eval) inside a single
`trial_config.mode in ("trial", "formal")` branch, so "the trial and formal
construction sites" means that pair running in both modes — which
`max_rounds=2` produces (round 1 trial, final round forced formal).
"""

from unittest.mock import patch

import pytest

from execute_tools import sample_set_builder
from execute_tools.dataset_config import TIDMAD_PROFILE
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    FAKE_SCORE_VECTOR_RESULT,
    _make_trial_input,
    _mock_run_skill,
    _synth_reference,
)


class _AmbientConsulted(RuntimeError):
    """Raised if build_sample_set falls back to ambient resolution."""


@pytest.fixture(autouse=True)
def _disable_health_gates():
    with patch(
        "nodes.ml_hyperparameter_tune_agent.round_health.get_gates_for_position",
        return_value=[],
    ):
        yield


def _run_tuner(tmp_path, max_rounds):
    """Drive the real agent, recording every build_sample_set call.

    Returns the recorded kwargs list and the ambient-resolver mock.
    """
    import tempfile

    real_build = sample_set_builder.build_sample_set
    calls: list[dict] = []

    def spy(**kwargs):
        calls.append(kwargs)
        return real_build(**kwargs)

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch("nodes.ml_hyperparameter_tune_agent.planning.build_sample_set", side_effect=spy),
        patch.object(
            sample_set_builder,
            "resolve_dataset_profile",
            side_effect=_AmbientConsulted("build_sample_set fell back to ambient resolution"),
        ) as ambient,
        patch("os.path.exists", return_value=True),
        tempfile.TemporaryDirectory() as configs_dir,
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE
        mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

        saved_records: list = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        stub_scoring(mock_sandbox, *FAKE_SCORE_VECTOR_RESULT)

        agent = HyperparamTuningAgent()
        output = agent.run(_make_trial_input(tmp_path, max_rounds=max_rounds, is_trial=True))

    return calls, ambient, output


class TestTunerSuppliesResolvedProfile:
    def test_both_sites_supply_a_profile_in_both_modes(self, tmp_path):
        calls, ambient, output = _run_tuner(tmp_path, max_rounds=2)

        # Ordered most-diagnostic first. A dropped `profile=` also degrades the
        # run's status, so asserting status first would report "partial !=
        # completed" and say nothing about the actual defect.
        assert len(calls) >= 2, f"expected at least the train/eval pair, got {len(calls)}"

        missing = [i for i, kw in enumerate(calls) if kw.get("profile") is None]
        assert not missing, (
            f"build_sample_set call(s) {missing} reached the builder with no explicit "
            "profile — that site still relies on ambient resolution"
        )

        # No ambient fallback is reachable on the migrated path. Asserted
        # independently of the run's status so a swallowed exception upstream
        # cannot make this look green.
        ambient.assert_not_called()

        assert output.status == "completed"

    def test_the_supplied_profile_is_the_resolved_run_profile(self, tmp_path):
        """It must be the run's profile, not a freshly invented one.

        Equality rather than identity: 02b consumes 02a's authority, and a
        value-equal profile is the contract. What would fail here is a site
        passing some *other* topology.
        """
        calls, _, _ = _run_tuner(tmp_path, max_rounds=2)
        for index, kwargs in enumerate(calls):
            assert kwargs["profile"] == TIDMAD_PROFILE, (
                f"call {index} supplied a profile that is not the run's resolved one"
            )

    def test_train_and_eval_share_one_profile_object(self, tmp_path):
        """Train and eval must select against the SAME topology.

        The tuner resolves once and reuses the value; resolving separately
        per site would let a rebind between them split one round's SampleSets
        across two topologies.
        """
        calls, _, _ = _run_tuner(tmp_path, max_rounds=2)
        pair = calls[:2]
        assert len(pair) == 2
        assert pair[0]["profile"] is pair[1]["profile"], (
            "train and eval received distinct profile objects — they were resolved "
            "separately rather than once per round"
        )
