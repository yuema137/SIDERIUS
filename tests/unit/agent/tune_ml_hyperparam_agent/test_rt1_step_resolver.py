"""RT1 — trainer-mirroring step-count resolver + static-prior demotion.

Design: docs/design/runtime_estimation_and_watchdog.md §1 (rev 4).
Motivated by the 2026-07-23 V18 incident: a 480,000-step formal attempt
priced at 2.00 ms/step (static) vs 44.3 ms/step measured — a 22x
underestimate that passed a 120-minute budget for a 5.9-hour training
run. Rev 4 contract: the static formula is a preliminary risk screen
(``formal_execution_eligible: False``); the runtime prediction that
admits a formal execution must come from a warm-up measurement.
"""

from __future__ import annotations

from typing import ClassVar

from agent.skills.training_skill.estimator import (
    _total_train_steps,
    estimate_wall_time_seconds,
)

PSD_LEN = 10_000_000

# The V18 incident scope: files 4-9 x 20 PSDs, seg 1250, bs 2, 1 epoch.
INCIDENT_SAMPLE_SET: dict[str, list[int]] = {str(i): list(range(20)) for i in range(4, 10)}


class TestStepResolverContract:
    """_total_train_steps vs the trainer's realized step count:
    the RT1 resolver mirrors the trainer's per-file max(1, round(...))
    subsample (train_engine_sandbox.py:300-304) + DataLoader
    drop_last=True floor exactly, so predicted steps == realized steps
    for every (seg, bs, portion, epochs) combination."""

    def _loader_steps(self, sample_set, seg, bs, portion, epochs):
        """Independent re-derivation of train_engine_sandbox.py:300-304 +
        DataLoader(drop_last=True): per-file max(1, round(portion*len)),
        then floor(total_samples / bs) per epoch."""
        ml = PSD_LEN // seg
        n_psd = sum(
            max(1, round(portion * len(v))) if (portion is not None and portion < 1.0) else len(v)
            for v in sample_set.values()
        )
        return (n_psd * ml // bs) * epochs

    def test_grid_exact_match(self):
        """RT1 resolver mirrors the trainer exactly — zero step error."""
        for seg in (1250, 2500, 10_000, 40_000):
            for bs in (2, 3, 8, 64):
                for portion in (1.0, 0.5, 0.1, None):
                    for epochs in (1, 3):
                        ss = {"4": list(range(20)), "5": list(range(7)), "9": [0]}
                        est = _total_train_steps(ss, seg, bs, portion, epochs)
                        actual = self._loader_steps(ss, seg, bs, portion, epochs)
                        assert est == actual, (seg, bs, portion, epochs, est, actual)

    def test_many_small_files_max1_floor(self):
        """The old global-product formula undercounted many-small-file
        scopes ~10x: 20 files x 1 PSD at portion 0.1 keeps
        max(1, round(0.1)) = 1 PSD per file = 20 PSDs, not 2."""
        ss = {str(i): [0] for i in range(20)}
        est = _total_train_steps(ss, 10_000, 8, 0.1, 1)
        assert est == (20 * (PSD_LEN // 10_000)) // 8  # all 20 PSDs kept

    def test_incident_step_count_exact(self):
        steps = _total_train_steps(
            INCIDENT_SAMPLE_SET, seg_size=1250, batch_size=2, train_portion=1.0, epochs=1
        )
        assert steps == 480_000


class TestFormalEligibilityContract:
    """Rev 4: only a measured step time may back the runtime prediction
    that admits a formal execution. RT2/RT3 enforce; RT1 provides the
    interface field."""

    INCIDENT_KW: ClassVar[dict] = dict(
        model_type="x",
        model_config={"segmentation_size": 1250},
        train_config={"batch_size": 2, "epochs": 1},
        sample_set=INCIDENT_SAMPLE_SET,
        train_portion=1.0,
        num_params=141_280,
    )

    def test_static_prior_is_not_formal_eligible(self):
        r = estimate_wall_time_seconds(**self.INCIDENT_KW, ms_per_step=None)
        bd = r["breakdown"]
        assert bd["ms_source"] == "static_uncalibrated"
        assert bd["formal_execution_eligible"] is False
        # The static prior still prices the incident config optimistically
        # (2.0 ms floor) — which is exactly why it may not admit formal
        # execution on its own.
        assert r["seconds"] / 60 < 120

    def test_warmup_measurement_is_formal_eligible(self):
        r = estimate_wall_time_seconds(**self.INCIDENT_KW, ms_per_step=3.5)
        bd = r["breakdown"]
        assert bd["ms_source"] == "real_dataset_warmup"
        assert bd["formal_execution_eligible"] is True

    def test_incident_measured_step_time_exceeds_budget(self):
        """With the measured 44.3 ms/step the warm-up path would have
        supplied, the incident config is over the 120-min formal budget —
        the mandatory-warm-up contract catches what the static prior
        cannot."""
        r = estimate_wall_time_seconds(**self.INCIDENT_KW, ms_per_step=44.3)
        assert r["seconds"] / 60 > 120  # 480k x 44.3ms x 1.3 = 461 min
