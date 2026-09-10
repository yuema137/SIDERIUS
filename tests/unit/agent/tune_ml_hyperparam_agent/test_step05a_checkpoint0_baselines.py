"""PR-05a CHECKPOINT 0 — pre-edit compatibility baselines.

Captured against **byte-unchanged production code**, before any 05a edit, so
Checkpoint A can prove the run-bound-`DatasetProfile` migration moved nothing.

Design: `docs/design/generic_framework_upgrade/step_05a_tuner_data_selection.md`
§6 originally named two compatibility surfaces with **no existing oracle**:

1. ``_validate_data_config`` accept/reject **and its exact diagnostic text**;
2. the **live** legacy ``single_file`` train/eval segment counts.

The second oracle was retired during repository separation. Its harness had no
task composition, task configuration, or declared metric and therefore could
not construct a supported run after scientific defaults moved outside the
framework. External composed-task qualification owns live runtime accounting;
this module retains only the pure, explicitly supplied legality parity below.

Everything else in §6 (TrialConfig serialization, SampleSet identities,
run-invariant stamping) already has a Step-00/Step-02 baseline, and §17
CHECKPOINT 0 forbids duplicating those.

Scope of the legality baseline — one failure class, not four
------------------------------------------------------------
``_validate_data_config`` has three raising branches. Only ONE of them can
change verdict or text when the supplied dataset object changes:

* **branch 1** — ``psd % segmentation_size != 0``. Profile-dependent
  (``psd_segment_length``) and reachable. **Baselined here.**
* **branch 2** — ``eval_segs < 1`` after ``eval_segs = max(1, round(...))``.
  ``max(1, ...)`` is never below 1, so the guard is unreachable for every
  input. It reads ``segments_per_file``, but no profile can make it fire.
* **branch 3** — ``train_segs < 1`` after ``train_segs = max(1, round(...))``.
  Same shape, same unreachability.

Baselining an unreachable guard would pin nothing (CLAUDE.md test economy:
"every test must name a defect only it can catch"), so branches 2 and 3 are
recorded as a source finding in the ledger and deliberately NOT baselined.
05a does not change them — closing a dead guard is a behavioural change to a
legality rule Step 02 owns.

Why the legality baseline passes the dataset explicitly
-------------------------------------------------------
The property this file pins is *"under TIDMAD's topology, this input is
rejected with this text"* — an invariant that must hold identically before
and after the migration. Whether **production actually supplies** the object
is a different claim, and a stronger one; it belongs to the run-binding guard
and Checkpoint C, exactly as Step 02b split it. Pinning the default-argument
call here would make the baseline itself un-runnable the moment M3 removes
that default, which would defeat the purpose of a baseline.
"""

import pytest

from agent.schemas.hyperparam_tuning import TrialConfig
from execute_tools.dataset_config import TIDMAD
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _validate_data_config,
)

# ---------------------------------------------------------------------------
# Baseline 1 — legality verdict + exact diagnostic text
# ---------------------------------------------------------------------------

# Hardcoded, never re-derived from `TIDMAD.valid_segmentation_sizes()`:
# computing the expectation from the thing under test compares the code to
# itself and would pass for any list (CLAUDE.md).
_TIDMAD_VALID_SEGMENTATION_SIZES = (
    "[100, 125, 128, 160, 200, 250, 320, 400, 500, 625, 640, 800, 1000, 1250, "
    "1600, 2000, 2500, 3125, 3200, 4000, 5000, 6250, 8000, 10000, 12500, "
    "15625, 16000, 20000, 25000, 31250, 40000, 50000, 62500, 78125, 80000, "
    "100000]"
)

REJECTING_SEGMENTATION_SIZE = 30_000  # 10,000,000 % 30,000 == 10,000
ACCEPTING_SEGMENTATION_SIZE = 40_000  # a divisor of 10,000,000

EXPECTED_REJECTION_TEXT = (
    "psd_segment_length (10000000) must be divisible by "
    "segmentation_size (30000). "
    "Remainder: 10000. "
    f"Valid segmentation_size values: {_TIDMAD_VALID_SEGMENTATION_SIZES}."
)


def _trial_config() -> TrialConfig:
    return TrialConfig.model_validate(
        {
            "is_trial": True,
            "mode": "trial",
            "trial_portion": 0.1,
            "train_sampling_seed": 1,
            "eval_sampling_seed": 1,
            "train_base_seed": 1,
        }
    )


class TestLegalityBaselineUnderTidmad:
    """The single profile-dependent failure class, pinned exactly."""

    def test_an_illegal_segmentation_size_is_rejected_with_this_exact_text(self):
        """Exact text, not a substring.

        A migration that supplied a *different* dataset object would keep the
        exception type and the phrasing while changing the numbers — the
        remainder and the legal-value list are the only parts that move, so
        asserting the whole string is what makes this a parity oracle.
        """
        with pytest.raises(ValueError) as exc:
            _validate_data_config(
                _trial_config(),
                REJECTING_SEGMENTATION_SIZE,
                dataset_config=TIDMAD,
            )
        assert str(exc.value) == EXPECTED_REJECTION_TEXT

    def test_a_legal_segmentation_size_is_accepted(self):
        """The negative half alone cannot detect a migration that starts
        rejecting everything."""
        _validate_data_config(
            _trial_config(),
            ACCEPTING_SEGMENTATION_SIZE,
            dataset_config=TIDMAD,
        )
