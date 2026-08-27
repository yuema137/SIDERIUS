"""PR-05a CHECKPOINT 0 — pre-edit compatibility baselines.

Captured against **byte-unchanged production code**, before any 05a edit, so
Checkpoint A can prove the run-bound-`DatasetProfile` migration moved nothing.

Design: `docs/design/generic_framework_upgrade/step_05a_tuner_data_selection.md`
§6 names exactly two compatibility surfaces with **no existing oracle**:

1. ``_validate_data_config`` accept/reject **and its exact diagnostic text**;
2. the **live** legacy ``single_file`` train/eval segment counts.

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

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import TrialConfig
from execute_tools.dataset_config import TIDMAD
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _validate_data_config,
)
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_RESPONSE,
    FAKE_REFLECT_RESPONSE,
    FAKE_SCORE_VECTOR_RESULT,
    _make_trial_input,
    _mock_run_skill,
    _synth_reference,
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


# ---------------------------------------------------------------------------
# Baseline 2 — LIVE legacy single_file segment accounting
# ---------------------------------------------------------------------------

# TIDMAD.segments_per_file. Hardcoded for the same reason as above: reading
# it from the dataset object would make the assertion true by construction
# both before and after the migration.
EXPECTED_SINGLE_FILE_SEGMENTS = 200


def _run_single_file_tuner(tmp_path):
    """Drive the REAL tuner down the legacy ``single_file`` route.

    Reachability (design §2): ``mode = "single_file"`` requires BOTH
    ``plan.is_trial`` false and ``trial_allowed`` false, and
    ``trial_allowed = agent_input.is_trial`` is an operator CLI flag. So
    ``FAKE_PLAN_RESPONSE`` (which carries no ``is_trial`` key) plus
    ``is_trial=False`` selects it — no patching of the branch itself, which
    is what makes this the *live* path rather than the arithmetic expression
    called directly (§17 CHECKPOINT 0).

    Returns ``(saved_records, persisted_trial_configs)``. The saved record
    carries no ``mode``, so the route is confirmed from the ``TrialConfig``
    JSON the tuner writes for the subprocess — an operator-visible artifact
    rather than an inference from the counts being asserted.
    """
    configs_dir = str(tmp_path / "configs")
    os.makedirs(configs_dir, exist_ok=True)
    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch(
            "nodes.ml_hyperparameter_tune_agent.round_health.get_gates_for_position",
            return_value=[],
        ),
    ):
        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN_RESPONSE
        mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

        saved_records: list = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
        mock_sandbox.save_record.side_effect = lambda r: saved_records.append(r)
        mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
        stub_scoring(mock_sandbox, *FAKE_SCORE_VECTOR_RESULT)

        agent = HyperparamTuningAgent()
        agent.run(_make_trial_input(tmp_path, max_rounds=1, is_trial=False))

    trial_configs = [
        json.loads((Path(configs_dir) / name).read_text())
        for name in sorted(os.listdir(configs_dir))
        if name.startswith("trial_config_")
    ]
    return saved_records, trial_configs


class TestLegacySingleFileAccountingBaseline:
    def test_the_live_single_file_path_reports_tidmad_segment_counts(self, tmp_path):
        """Both counts come from ``DATASET_CONFIG.segments_per_file`` today.

        Asserted on the persisted record, which is what the reflector and
        every downstream consumer actually read — not on a local variable.
        """
        records, trial_configs = _run_single_file_tuner(tmp_path)

        # Route first: if the run silently took the trial/formal branch the
        # counts would come from a SampleSet and this would be measuring the
        # wrong thing while still looking plausible.
        assert trial_configs, "the tuner persisted no TrialConfig — no attempt ran"
        assert trial_configs[0]["mode"] == "single_file", (
            f"expected the legacy route, got mode={trial_configs[0]['mode']!r}"
        )

        assert records, "the run saved no record — the accounting path never executed"
        record = records[0]
        assert record["training_psd_segments"] == EXPECTED_SINGLE_FILE_SEGMENTS
        assert record["eval_psd_segments"] == EXPECTED_SINGLE_FILE_SEGMENTS
