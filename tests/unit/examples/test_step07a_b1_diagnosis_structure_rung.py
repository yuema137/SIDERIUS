"""Rung B-07a-1 — diagnosis-structure axis (L1, atomic).

Design: ``pr_07a_training_history_diagnosis.md`` §6 / §3.11; parent §8.2
Checkpoint B; roadmap §22.9a (frozen track semantics), §22.23.7 (an
``expected/`` fixture is legitimate ONLY if the tests consume it — this test
is that consumer).

The SAME ``derive_training_diagnosis`` boundary over three ``TrainingHistory``
fixtures carrying the EXACT frozen semantics:

* TIDMAD — the run-resolved training objective (representative atomic
  fixture ``objective_kind="focal"``); production-backed from 07a, so the
  fixture lives with the test, not in the pack;
* Oxford-IIIT Pet — ``ce`` train/validation + ``observations
  ={"validation_accuracy": …}`` (pack ``expected/``);
* DAVIS future prediction — ``mae`` train/validation + ``observations
  ={"validation_psnr": …}`` (pack ``expected/``);

→ the expected verdict shapes (best epoch, degradation, gap, trends) pinned
as LITERALS (hand-computed in the pack fixtures / below — never read back
from the boundary). Only the history / objective identity varies; atomicity
is machine-checked by diffing the fixtures' non-value fields. No image, no
video, no loader. Honestly an L1 rung: Pets / DAVIS have no executable path
until D14 (the fixtures say so in their ``_fixture`` label).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.schemas.training_diagnosis import TrainingDiagnosis, derive_training_diagnosis
from execute_tools.training_history import EPOCH_STATISTIC, TrainingHistory
from tests.unit.examples import maturity_vocabulary as mv

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "examples"

# TIDMAD — production-backed; the representative ATOMIC fixture (focal, mean).
_TIDMAD_HISTORY = {
    "cadence": "per_epoch",
    "objective_kind": "focal",
    "objective_config_fingerprint": "f90b6486db93809357e3edd4cc7022a2a31542a3e74b2945bd1dc944e411fc05",
    "objective_reduction": "mean",
    "epoch_statistic": EPOCH_STATISTIC,
    "comparability": "established",
    "comparability_reason": None,
    "epochs_planned": 5,
    "epochs_completed": 5,
    "train_objective": [2.90, 2.60, 2.45, 2.38, 2.35],
    "validation_objective": [2.95, 2.70, 2.58, 2.55, 2.62],
    "validation_requested_samples": 2000,
    "validation_samples": 2000,
    "validation_seconds": [1.2, 1.2, 1.1, 1.2, 1.2],
    "observations": {},
}
# Hand-computed from the §3.6 rules (NOT read back from the boundary).
_TIDMAD_EXPECTED = {
    "state": "ok",
    "validation_state": "present",
    "comparability": "established",
    "epochs_planned": 5,
    "epochs_completed": 5,
    "truncated": False,
    "train_first": 2.90,
    "train_last": 2.35,
    "train_min": 2.35,
    "train_min_epoch": 4,
    "validation_first": 2.95,
    "validation_last": 2.62,
    "validation_min": 2.55,
    "best_validation_epoch": 3,
    "final_vs_best_validation_degradation": 0.07,
    "final_vs_best_validation_degradation_rel": 0.07 / 2.62,
    "validation_degraded_after_best": True,
    "train_validation_gap_final": 0.27,
    "train_validation_gap_final_rel": 0.27 / 2.62,
    "train_trend": "decreasing",
    "validation_trend": "decreasing",
    "flat_rel_tol": 0.01,
}


def _pack_fixture(pack: str, kind: str) -> tuple[dict, dict]:
    path = EXAMPLES / pack / "expected" / f"{kind}_l1_fixture.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["_fixture"]["label"] == "l1_fixture", f"{path} must be labelled l1_fixture"
    assert payload["_fixture"]["kind"] == kind
    return payload["_fixture"], payload[kind]


TRACKS = {
    "tidmad": ("focal", _TIDMAD_HISTORY, _TIDMAD_EXPECTED, None),
    "oxford_iiit_pet": ("ce", None, None, "validation_accuracy"),
    "davis_future_prediction": ("mae", None, None, "validation_psnr"),
}


def _load(track: str) -> tuple[TrainingHistory, dict, str | None]:
    kind, hist, expected, observation = TRACKS[track]
    if hist is None:
        _meta, hist = _pack_fixture(track, "training_history")
        _meta, expected = _pack_fixture(track, "training_diagnosis")
    history = TrainingHistory.model_validate(hist)
    assert history.objective_kind == kind
    return history, expected, observation


_FLOAT_FIELDS = {
    "train_first",
    "train_last",
    "train_min",
    "validation_first",
    "validation_last",
    "validation_min",
    "final_vs_best_validation_degradation",
    "final_vs_best_validation_degradation_rel",
    "train_validation_gap_final",
    "train_validation_gap_final_rel",
    "flat_rel_tol",
}


@pytest.mark.parametrize("track", sorted(TRACKS))
def test_the_same_boundary_yields_the_expected_verdict_shape(track):
    """Defect: a task-specific assumption inside the boundary (e.g. TIDMAD's
    objective family, a fixed epoch count, the absence of observations) would
    change the verdict for one track and not the others."""
    history, expected, observation = _load(track)
    diagnosis = derive_training_diagnosis(history)
    got = diagnosis.model_dump()
    assert set(got) == set(expected), set(got) ^ set(expected)
    for key, exp in expected.items():
        if key in _FLOAT_FIELDS:
            assert got[key] == pytest.approx(exp, rel=1e-12, abs=1e-12), key
        else:
            assert got[key] == exp, key
    # The optional checkpointed observation travels on the history and is
    # ignored by the v1 diagnosis (no observation-derived field exists).
    if observation is not None:
        assert observation in history.observations
        assert len(history.observations[observation]) == history.epochs_completed
    assert not any("accuracy" in f or "psnr" in f for f in TrainingDiagnosis.model_fields)


def test_atomicity_only_the_history_and_objective_identity_vary():
    """Machine-checked atomicity: every NON-value field of the three fixtures is
    identical (cadence, statistic, reduction, comparability, epoch counts,
    validation identity, list lengths); only objective_kind / fingerprint, the
    observed values and the observation NAME differ."""
    histories = {t: _load(t)[0] for t in TRACKS}
    shapes = {
        t: {
            "cadence": h.cadence,
            "epoch_statistic": h.epoch_statistic,
            "objective_reduction": h.objective_reduction,
            "comparability": h.comparability,
            "comparability_reason": h.comparability_reason,
            "epochs_planned": h.epochs_planned,
            "epochs_completed": h.epochs_completed,
            "validation_identity_ok": h.validation_requested_samples == h.validation_samples,
            "len_train": len(h.train_objective),
            "len_val": len(h.validation_objective or []),
            "len_secs": len(h.validation_seconds or []),
            "n_observations": len(h.observations),
        }
        for t, h in histories.items()
    }
    ref = shapes["tidmad"]
    for t, shape in shapes.items():
        differ = {k for k in ref if ref[k] != shape[k]}
        assert differ <= {"n_observations"}, f"{t} varies non-value fields {differ}"
    kinds = {h.objective_kind for h in histories.values()}
    fps = {h.objective_config_fingerprint for h in histories.values()}
    assert kinds == {"focal", "ce", "mae"} and len(fps) == 3


def test_the_pack_fixtures_are_consumed_from_the_packs_and_labelled_l1():
    """§22.23.7: an `expected/` fixture without a consumer is a consumer-less
    file. This test IS the consumer; the fixture files must exist under the
    packs and carry the honest label."""
    for pack in ("oxford_iiit_pet", "davis_future_prediction"):
        for kind in ("training_history", "training_diagnosis"):
            meta, _payload = _pack_fixture(pack, kind)
            assert "NOT a real" in meta["note"]


def test_pack_docs_state_the_07a_maturity_honestly():
    """STATUS / README pins for 07a, against the shared maturity vocabulary.

    Every literal lives in `tests/unit/examples/maturity_vocabulary.py` so D14
    edits ONE place rather than the seven prose pins Step 07 accumulated across
    two modules. The expectations are still hardcoded, and deliberately: a
    version that read the row and asserted it matched itself would be the
    self-referential shape this PR has now found four times.
    """
    assert mv.MATURITY_PRODUCTION_07A in mv.status_text("tidmad")

    for pack in mv.L1_PACKS:
        status = mv.status_text(pack)
        for token in (
            mv.MATURITY_L1_FIXTURE,
            mv.RUNG_07A,
            mv.DEFERRAL_TOKEN,
            mv.L1_FIXTURE_BASENAME,
        ):
            assert token in status, f"{pack}/STATUS.md must state {token!r}"

    for pack in mv.TRACKS:
        readme = mv.readme_text(pack)
        missing = [t for t in mv.HISTORY_RUNGS if t not in readme]
        assert not missing, f"{pack}/README.md must state {missing}"
