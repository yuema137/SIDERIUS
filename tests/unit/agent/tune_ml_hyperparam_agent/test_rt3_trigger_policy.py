"""
RT3 — §3 non-formal trigger-policy matrix + wrapper store-reuse wiring.

Pins: every row of the §3 table (store hit + bounds → reuse; each
violation forces warm-up with an accumulated reason), and the
evaluate_time_skill wiring (valid store hit skips the warm-up, stamps
``source="store"`` with ``formal_execution_eligible=False`` and the
planner-visible provenance keys; a §3 violation falls through to the
warm-up path).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import torch

from agent.skills.evaluate_time_skill.trigger_policy import (
    decide_nonformal_estimation,
)
from core.runtime_control.adaptive import AdaptiveVerificationConfig
from core.runtime_control.observation_store import ObservationStore
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from core.runtime_control.steady_state import SteadyStateConfig
from core.runtime_control.workload import ResolvedPhaseWorkload
from tests.helpers.two_family_profile import make_two_family_profile

_OK = dict(
    is_trial_round=True,
    n_steps=10_000,
    batch_size=8,
    seg_size=10_000,
    store_prior_unit_ms=5.0,
    static_ms_per_step=4.0,
)


class TestPolicyMatrix:
    def test_all_conditions_met_reuses_store(self):
        decision = decide_nonformal_estimation(**_OK)
        assert decision.action == "reuse_store"
        assert decision.store_unit_ms == pytest.approx(5.0)
        assert decision.reasons == []

    @pytest.mark.parametrize(
        ("override", "reason_fragment"),
        [
            ({"is_trial_round": False}, "not a trial round"),
            ({"store_prior_unit_ms": None}, "no valid store hit"),
            ({"n_steps": 50_001}, "store-reuse ceiling"),
            ({"batch_size": 3}, "batch_size"),
            ({"batch_size": 513}, "batch_size"),
            ({"seg_size": 2499}, "seg_size"),
            ({"seg_size": 40_001}, "seg_size"),
            ({"store_prior_unit_ms": 15.0}, "disagree"),  # 15 vs 4 → 3.75x
            ({"static_ms_per_step": 20.0}, "disagree"),  # 5 vs 20 → 4x (both directions)
        ],
    )
    def test_each_violation_forces_warmup(self, override, reason_fragment):
        decision = decide_nonformal_estimation(**{**_OK, **override})
        assert decision.action == "warmup_required"
        assert any(reason_fragment in r for r in decision.reasons), decision.reasons

    def test_reasons_accumulate(self):
        decision = decide_nonformal_estimation(
            **{**_OK, "n_steps": 60_000, "batch_size": 2, "store_prior_unit_ms": None}
        )
        assert len(decision.reasons) == 3

    def test_boundary_values_allowed(self):
        for override in (
            {"n_steps": 50_000},
            {"batch_size": 4},
            {"batch_size": 512},
            {"seg_size": 2500},
            {"seg_size": 40_000},
            {"store_prior_unit_ms": 12.0, "static_ms_per_step": 4.0},  # exactly 3.0x
        ):
            assert decide_nonformal_estimation(**{**_OK, **override}).action == "reuse_store"


_PARAMS = 100_000
_SEG = 10_000
_BATCH = 8
PROFILE = make_two_family_profile(
    num_files=1,
    psd_segment_length=40_000,
    segments_per_file=4,
)
_CONTEXT = {
    "precision": "float32",
    "optimizer_type": "adamw",
    "model_family": "wavenet",
    "param_count": _PARAMS,
    "seg_size": _SEG,
    "batch_size": _BATCH,
}


def _seed_store(store_root: str, sidecar_dir: str, unit_ms: float, gpu: str) -> None:
    """One clean, verified observation with the wrapper's exact §6a key."""
    import os

    donor = RuntimeVerificationSession(
        os.path.join(sidecar_dir, "donor.json"),
        policy=RuntimeControlPolicy(
            verification=AdaptiveVerificationConfig(
                steady=SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10),
                min_timed_steps=5,
                min_timed_ms=0.0,
                max_steps=50,
            )
        ),
    )
    donor.complete_setup(
        storage_provenance={"expected_raw_bytes": 10},
        training_workload=ResolvedPhaseWorkload(
            phase="training", unit="optimizer_step", unit_count=1000
        ),
    )
    donor.set_calibration_context(_CONTEXT)
    verifier = donor.start_phase_verification("training", unit="optimizer_step")
    for t in [unit_ms] * 30:
        verifier.feed(t)
        if verifier.is_terminal:
            break
    donor.complete_phase_verification("training", verifier, source="real_training_verification")
    donor.record_phase_actual("training", unit_ms * 1000 / 1000.0)  # realized == unit_ms
    donor._environment = {
        **donor._environment,
        "gpu_name": gpu,
        "torch_version": torch.__version__,
    }
    obs = donor.finalize("completed")
    ObservationStore(store_root).append(obs, writer_id="seed")


class TestWrapperStoreReuse:
    def _run(self, tmp_path, *, seed_unit_ms: float | None, warmup_ms: float = 7.0) -> dict:
        import os

        from agent.skills.evaluate_time_skill import wrapper

        store_root = str(tmp_path / "runtime_observations")
        gpu = "STUB-GPU"
        if seed_unit_ms is not None:
            _seed_store(store_root, str(tmp_path), seed_unit_ms, gpu)

        warmup_calls: list[int] = []

        def fake_warmup(**kw):
            warmup_calls.append(1)
            return warmup_ms, {
                "n_warmup_batches": 3,
                "n_timed_batches": 7,
                "timings_ms": [warmup_ms] * 7,
                "aggregator": "median",
            }

        data_dir = str(tmp_path)  # exists → warmup path reachable
        with (
            patch.object(wrapper, "_measure_ms_per_step", side_effect=fake_warmup),
            patch.object(wrapper, "_detect_gpu_name", return_value=gpu),
            patch.object(wrapper, "_count_params", return_value=_PARAMS),
        ):
            result = wrapper.run_skill(
                None,
                model_type="wavenet",
                model_config={"segmentation_size": _SEG, "batch_size": 1},
                train_config={"batch_size": _BATCH, "epochs": 1, "optimizer_type": "adamw"},
                loss_config={"loss_type": "focal"},
                sample_set={"0": [0, 1]},
                time_budget_minutes=120.0,
                data_dir=data_dir,
                allow_store_reuse=True,
                observation_store_root=store_root,
                dataset_profile=PROFILE,
            )
        result["_warmup_calls"] = len(warmup_calls)
        assert os.path.isdir(store_root) or seed_unit_ms is None
        return result

    def test_valid_store_hit_skips_warmup_with_store_provenance(self, tmp_path):
        # Static prior for this config is 24.0 ms; a 10 ms store prior is
        # within the 3x §3 disagreement bound (2.4x) → reuse.
        result = self._run(tmp_path, seed_unit_ms=10.0)
        assert result["status"] == "success"
        assert result["_warmup_calls"] == 0  # §3 reuse — no warm-up ran
        breakdown = result["breakdown"]
        assert breakdown["store_reuse"] is True
        assert breakdown["source"] == "store"
        assert breakdown["formal_execution_eligible"] is False  # never live-verified
        assert breakdown["store_lookup_status"] == "valid"
        assert breakdown["ms_per_step_warmup"] == pytest.approx(10.0)

    def test_no_store_hit_falls_through_to_warmup(self, tmp_path):
        result = self._run(tmp_path, seed_unit_ms=None)
        assert result["_warmup_calls"] == 1
        breakdown = result["breakdown"]
        assert breakdown["store_reuse"] is False
        assert breakdown["source"] == "real_dataset_warmup"
        assert breakdown["store_policy_reasons"] is not None
        assert any("no valid store hit" in r for r in breakdown["store_policy_reasons"])

    def test_disagreeing_store_falls_through_to_warmup(self, tmp_path):
        # Static for these params is ~max(0.24, 2.0) ms-scale; a 5000 ms
        # store prior disagrees ≫ 3x → §3 forces warm-up.
        result = self._run(tmp_path, seed_unit_ms=5000.0)
        assert result["_warmup_calls"] == 1
        assert result["breakdown"]["store_reuse"] is False
        assert any("disagree" in r for r in result["breakdown"]["store_policy_reasons"])
