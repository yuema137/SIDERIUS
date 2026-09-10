"""RT1 — trainer-mirroring step-count resolver and static-prior demotion.

Design: docs/design/runtime_estimation_and_watchdog.md §1 (rev 4).
The exact scientific incident oracle lives in ``siderius-exp``. This module
keeps the generic Rev-4 contract: the static formula is a preliminary risk screen
(``formal_execution_eligible: False``); the runtime prediction that
admits a formal execution must come from a warm-up measurement.
"""

from __future__ import annotations

from typing import ClassVar

from agent.skills.training_skill.estimator import (
    _total_train_steps,
    estimate_wall_time_seconds,
)
from tests.helpers.two_family_profile import make_two_family_profile

PHYSICAL_SEGMENT_LENGTH = 1_600_000
PROFILE = make_two_family_profile(
    num_files=20,
    psd_segment_length=PHYSICAL_SEGMENT_LENGTH,
    segments_per_file=20,
)

SAMPLE_SET: dict[str, list[int]] = {str(i): list(range(20)) for i in range(4, 10)}


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
        ml = PHYSICAL_SEGMENT_LENGTH // seg
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
                        est = _total_train_steps(ss, seg, bs, portion, epochs, PROFILE)
                        actual = self._loader_steps(ss, seg, bs, portion, epochs)
                        assert est == actual, (seg, bs, portion, epochs, est, actual)

    def test_many_small_files_max1_floor(self):
        """The old global-product formula undercounted many-small-file
        scopes ~10x: 20 files x 1 PSD at portion 0.1 keeps
        max(1, round(0.1)) = 1 PSD per file = 20 PSDs, not 2."""
        ss = {str(i): [0] for i in range(20)}
        est = _total_train_steps(ss, 10_000, 8, 0.1, 1, PROFILE)
        assert est == (20 * (PHYSICAL_SEGMENT_LENGTH // 10_000)) // 8


class TestFormalEligibilityContract:
    """Rev 4: only a measured step time may back the runtime prediction
    that admits a formal execution. RT2/RT3 enforce; RT1 provides the
    interface field."""

    WORKLOAD_KW: ClassVar[dict] = dict(
        model_type="x",
        model_config={"segmentation_size": 1250},
        train_config={"batch_size": 2, "epochs": 1},
        sample_set=SAMPLE_SET,
        train_portion=1.0,
        num_params=141_280,
    )

    def test_static_prior_is_not_formal_eligible(self):
        r = estimate_wall_time_seconds(
            **self.WORKLOAD_KW, ms_per_step=None, dataset_profile=PROFILE
        )
        bd = r["breakdown"]
        assert bd["ms_source"] == "static_uncalibrated"
        assert bd["formal_execution_eligible"] is False
        assert r["seconds"] > 0

    def test_warmup_measurement_is_formal_eligible(self):
        r = estimate_wall_time_seconds(**self.WORKLOAD_KW, ms_per_step=3.5, dataset_profile=PROFILE)
        bd = r["breakdown"]
        assert bd["ms_source"] == "real_dataset_warmup"
        assert bd["formal_execution_eligible"] is True

    def test_measured_step_time_changes_the_prediction(self):
        static = estimate_wall_time_seconds(
            **self.WORKLOAD_KW, ms_per_step=None, dataset_profile=PROFILE
        )
        measured = estimate_wall_time_seconds(
            **self.WORKLOAD_KW, ms_per_step=44.3, dataset_profile=PROFILE
        )
        assert measured["seconds"] > static["seconds"]
