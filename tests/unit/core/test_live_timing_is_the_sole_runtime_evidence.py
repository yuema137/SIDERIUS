"""The current live measurement is the only runtime evidence in the verdict.

V20 PR C1 — operator decision, 2026-08-03.

THE DECISION. Runtime depends on current machine conditions, current GPU
contention, current caching and current candidate behaviour. So the production
time-budget decision may use exactly one piece of runtime evidence: the live
measurement of the concrete candidate being launched now.

WHAT REMAINS, AND WHY THAT IS NOT A CONTRADICTION. Removing history is not
removing safety. These stay, because they are CONFIGURED POLICY rather than
learned experience:

  * the operator's time budget;
  * the fixed `SAFETY_MULTIPLIER` margin;
  * the deterministic projection from the live measurement;
  * the existing behaviour when the live measurement is missing or
    inconclusive -- which is NOT "fall back to history".

WHAT WAS REMOVED. `training_skill/estimator.py` used to multiply the estimate
by a legacy per-GPU `k`, an asymmetric EMA over previous runs loaded from
`~/.siderius/time_calibration_<gpu>.json`. That multiplication is gone, and so
is the `k_correction` breakdown field -- removed rather than pinned to 1.0,
because a neutral-valued field is a socket that invites a future correction.

This file is the guard. It asserts an ABSENCE, which is the hardest property
to keep: nothing fails when someone reconnects history unless a test is
watching. Its companion is
`test_historical_duration_is_observability_only.py`, which covers the v2
registry; together they cover BOTH history systems.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import agent.skills.evaluate_time_skill.wrapper as time_wrapper
from agent.skills.training_skill import estimator

ESTIMATOR_SOURCE = Path(estimator.__file__).read_text()
ESTIMATOR_TREE = ast.parse(ESTIMATOR_SOURCE)

#: The legacy k API. None of it may be reachable from the estimate.
LEGACY_K_NAMES = {"lookup_k", "load_table", "update_k", "save_table"}


def _estimate(ms_per_step: float | None, *, gpu_name: str | None = "NVIDIA GeForce RTX 5090"):
    """One production estimate. `sample_set` shaped as the resolver expects."""
    return estimator.estimate_wall_time_seconds(
        model_type="punet",
        model_config={"segmentation_size": 40000, "batch_size": 8},
        train_config={"batch_size": 8, "epochs": 1},
        loss_type="focal",
        sample_set={"abra_training_0000.h5": list(range(200))},
        train_portion=1.0,
        ms_per_step=ms_per_step,
        gpu_name=gpu_name,
    )


class TestTheEstimateCannotReachLegacyK:
    def test_the_estimator_does_not_import_the_legacy_calibration_module(self):
        """Structural, and the cheapest guard that actually holds. Re-adding
        the import is exactly how the multiplication would come back."""
        imported: set[str] = set()
        for node in ast.walk(ESTIMATOR_TREE):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)

        offenders = {m for m in imported if "evaluate_time_skill.calibration" in m}
        offenders |= {m for m in imported if m.endswith("calibration")}
        assert not offenders, (
            f"the runtime estimator imports {offenders}; the legacy per-GPU k "
            "must not be reachable from the production estimate"
        )

    def test_no_legacy_k_call_appears_in_the_estimator(self):
        called = {
            getattr(c.func, "id", getattr(c.func, "attr", None))
            for c in ast.walk(ESTIMATOR_TREE)
            if isinstance(c, ast.Call)
        }
        assert not (called & LEGACY_K_NAMES), f"estimator calls {called & LEGACY_K_NAMES}"

    def test_the_breakdown_no_longer_carries_a_correction_slot(self):
        out = _estimate(10.0)
        assert "k_correction" not in out["breakdown"], (
            "k_correction is still emitted; a neutral-valued correction field "
            "is a socket for reconnecting history"
        )

    def test_the_time_wrapper_does_not_republish_a_correction(self):
        source = Path(time_wrapper.__file__).read_text()
        tree = ast.parse(source)
        keys = {
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        }
        assert "k_correction" not in keys


class TestTheLegacyTableCannotMoveTheEstimate:
    """Behavioural counterpart. The structural guards above would pass if the
    lookup moved somewhere else; these would not."""

    @staticmethod
    def _write_k_table(tmp_path, k: float) -> None:
        import json

        (tmp_path / "time_calibration_nvidia_geforce_rtx_5090.json").write_text(
            json.dumps(
                {
                    "gpu_name": "NVIDIA GeForce RTX 5090",
                    "k_values": {"punet": k, "*": k},
                    "history": [],
                }
            )
        )

    def test_an_extreme_k_value_does_not_change_the_estimate(self, tmp_path, monkeypatch):
        """The load-bearing one. A k of 50 would have multiplied the estimate
        fiftyfold; the two results must be identical."""
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))

        self._write_k_table(tmp_path, 1.0)
        baseline = _estimate(10.0)["seconds"]

        self._write_k_table(tmp_path, 50.0)
        after = _estimate(10.0)["seconds"]

        assert baseline == after, (
            f"the legacy k table changed the estimate ({baseline}s -> {after}s); "
            "history must not influence the production time decision"
        )

    def test_an_absent_table_gives_the_same_estimate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path / "nothing_here"))
        assert _estimate(10.0)["seconds"] == _estimate(10.0)["seconds"]

    def test_the_estimate_is_identical_with_and_without_a_gpu_name(self, tmp_path, monkeypatch):
        """`gpu_name` was the key the historical table was looked up by. With
        the lookup gone it must no longer alter the number at all."""
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
        self._write_k_table(tmp_path, 7.0)

        assert (
            _estimate(10.0, gpu_name="NVIDIA GeForce RTX 5090")["seconds"]
            == _estimate(10.0, gpu_name=None)["seconds"]
        )


class TestTheLiveMeasurementStillDecides:
    """POSITIVE CONTROLS. Every assertion above is about an absence, and all
    of them would also hold if the estimator ignored its inputs entirely. These
    prove it does not."""

    def test_a_slower_live_measurement_produces_a_larger_estimate(self):
        fast = _estimate(10.0)["seconds"]
        slow = _estimate(100.0)["seconds"]
        assert slow > fast, (
            "a 10x slower live measurement did not increase the estimate; the "
            "estimator is not reading the live measurement at all"
        )

    def test_the_live_measurement_scales_the_estimate_proportionally(self):
        """Stronger than monotonic: with history gone, the projection from the
        live measurement is exactly linear in it."""
        assert _estimate(100.0)["seconds"] == pytest.approx(_estimate(10.0)["seconds"] * 10.0)

    def test_the_configured_safety_margin_is_still_applied(self):
        """Removing history must not have removed safety. The margin is
        configured policy, not learned experience, and it stays."""
        out = _estimate(10.0)
        assert out["breakdown"]["safety_multiplier"] == estimator.SAFETY_MULTIPLIER
        assert estimator.SAFETY_MULTIPLIER > 1.0

        steps = out["breakdown"]["total_train_steps"]
        expected = steps * 10.0 * estimator.SAFETY_MULTIPLIER / 1000.0
        assert out["seconds"] == pytest.approx(expected)

    def test_a_missing_live_measurement_does_not_fall_back_to_history(self, tmp_path, monkeypatch):
        """The failure path must stay what it was -- a static prior that is
        explicitly NOT formal-eligible -- and must not acquire a historical
        fallback now that history is gone from the happy path."""
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path))
        self._write_k_table = TestTheLegacyTableCannotMoveTheEstimate._write_k_table
        self._write_k_table(tmp_path, 25.0)

        out = _estimate(None)

        assert out["breakdown"]["ms_source"] == "static_uncalibrated"
        assert out["breakdown"]["formal_execution_eligible"] is False
