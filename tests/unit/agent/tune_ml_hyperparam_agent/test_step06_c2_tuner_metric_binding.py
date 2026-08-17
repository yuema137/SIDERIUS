"""Step 06 — C2: the tuner binds ONE metric at run scope and scores THROUGH it.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§9, §12, §19 C2 (acceptance: "asserted by reachability — a renamed/contrast
handle changes the observed behaviour — not by inspection alone").

Two properties, each with the defect only it catches:

1. **Reachability through the PRODUCTION loop.** One bounded pseudo iteration
   of the real ``HyperparamTuningAgent.run`` (Step-00 harness: canned bridge,
   ``RecordingSandbox``, real ``_emit_record``) records WHICH handle the
   scoring seam received. Under Regime A it is the TIDMAD instance; with the
   run-scope derivation swapped for a contrast handle it is the contrast — so
   a tuner that quietly re-derived or hardcoded the metric at the call site
   would be caught, which reading the source cannot prove.

2. **The scoring-failure record helper.** ``_build_scoring_failure_record``
   was extracted from ``run()``'s scoring ``except`` so the ONE new outcome
   (``NotScoreableError``) has an honest description without adding a branch
   to a function at pyright's complexity ceiling. Parity for every other
   exception is pinned against the pre-extraction dict, key for key.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import pytest

from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    MetricSpec,
    NotScoreableError,
    NotScoreableResult,
    PresenceScoreabilityContract,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from tests.helpers.tuner_source import tuner_node_source

_TUNER = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"


def _preflight():
    return json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]


def _scoring_calls(sandbox):
    return [c for c in sandbox.calls if c and c[0] == "evaluate_metric"]


# ---------------------------------------------------------------------------
# 1. Reachability — the live route receives the run-scope handle
# ---------------------------------------------------------------------------


def test_the_production_loop_scores_through_the_tidmad_handle(tmp_path, monkeypatch):
    """Regime A: every scoring call the real loop makes goes to
    ``sandbox.evaluate_metric`` carrying the TIDMAD identity/direction; the
    legacy ``score_vector`` seam is not called by the live route."""
    _, _, sandbox, _ = run_bounded_pseudo_iteration(
        tmp_path, monkeypatch, preflight_results=_preflight()
    )
    calls = _scoring_calls(sandbox)
    assert calls, "the bounded iteration reached scoring at least once"
    assert all(c[1:] == (TIDMAD_METRIC_ID, "higher") for c in calls), calls
    assert not [c for c in sandbox.calls if c and c[0] == "score_vector"]


def test_a_contrast_handle_bound_at_run_scope_reaches_the_scoring_seam(tmp_path, monkeypatch):
    """Swap the run-scope derivation for a scalar-only lower-is-better handle
    and the LIVE route carries THAT identity — proving the call site reads
    ``run_metric`` and does not re-derive TIDMAD on its own authority.
    (Roadmap §10.5's contrast, at the seam; the record payload is C4/C6.)"""

    class _ContrastHandle:
        spec = MetricSpec(
            id="step06_contrast_lower",
            direction="lower",
            aggregation="single_value",
            scoreability=PresenceScoreabilityContract(),
        )

    # The contrast is returned ONLY by the first derivation — the run-scope
    # binding. A call site that re-derived the metric on its own authority
    # (a second `derive_tidmad_metric(...)` per scoring call) would obtain the
    # SHIPPED instance and the seam would see TIDMAD, not the contrast. (C7
    # mutation "live route bypasses the handle" survived the always-contrast
    # stub — equivalent under that oracle — and is killed by this one.)
    shipped = _TUNER.derive_tidmad_metric
    derivations: list[int] = []

    def _bind_once(*args, **kwargs):
        derivations.append(1)
        return _ContrastHandle() if len(derivations) == 1 else shipped(*args, **kwargs)

    monkeypatch.setattr(_TUNER, "derive_tidmad_metric", _bind_once)
    _, _, sandbox, _ = run_bounded_pseudo_iteration(
        tmp_path, monkeypatch, preflight_results=_preflight()
    )
    calls = _scoring_calls(sandbox)
    assert calls
    assert all(c[1:] == ("step06_contrast_lower", "lower") for c in calls), calls
    assert len(derivations) == 1, "the metric is bound exactly once per run, at run scope"


# ---------------------------------------------------------------------------
# 2. The extracted scoring-failure record — parity + the one new outcome
# ---------------------------------------------------------------------------

_COMMON = dict(
    exp_id="e1",
    model_type="wavenet",
    file_index=6,
    record_params={"lr": 1e-3},
    timing={"train_time_s": 1.0, "inference_time_s": 2.0, "scoring_time_s": 0.5},
    expert_advice_str="advice",
    hypothesis="hyp",
    round_index=3,
    attempt_in_round=1,
)


def test_a_generic_scoring_exception_produces_the_pre_extraction_record(monkeypatch):
    """Byte-for-byte parity with the dict ``run()`` used to build inline
    (``ml_hyperparameter_tune_agent.py`` @530f574c :5448-5478): same keys,
    same prose, ``failure_stage``/``failure_type`` ABSENT."""
    monkeypatch.setattr(_TUNER.time, "strftime", lambda *_a, **_k: "2026-08-15 00:00:00")
    record = _TUNER._build_scoring_failure_record(KeyError("timeseries"), **_COMMON)
    assert record == {
        "exp_id": "e1",
        "status": "error_scoring",
        "model_type": "wavenet",
        "timestamp": "2026-08-15 00:00:00",
        "file_index": 6,
        "params": {"lr": 1e-3},
        "denoising_score": None,
        "timing": {"train_time_s": 1.0, "inference_time_s": 2.0, "scoring_time_s": 0.5},
        "memory": {
            "expert_advice_followed": "advice",
            "hypothesis": "hyp",
            "conclusion": "Scoring crashed: KeyError: 'timeseries'",
            # The pre-extraction prose doubles the type name (``{type}: {type}: msg``)
            # — preserved verbatim; parity is with what production wrote, warts included.
            "discovery": (
                "Training and inference completed but scoring raised KeyError: "
                "KeyError: 'timeseries'"
            ),
            "memory_update": (
                "Scoring crash — training succeeded so the "
                "checkpoint may be reusable. Investigate the "
                "scoring path (anchor map, sample_set, file "
                "vector shape) before retrying this config."
            ),
            "round_index": 3,
            "attempt_in_round": 1,
        },
    }


def test_a_not_scoreable_refusal_is_described_as_such_not_as_a_crash(monkeypatch):
    """The ONE new outcome: ``status`` stays ``error_scoring`` (no score, no
    gate evidence — its documented meaning) but the record says WHICH
    requirement the deliverable violated, marks ``failure_stage="scoring"`` /
    ``failure_type="not_scoreable"``, and never says "crashed"."""
    monkeypatch.setattr(_TUNER.time, "strftime", lambda *_a, **_k: "2026-08-15 00:00:00")
    refusal = NotScoreableResult(
        metric_id=TIDMAD_METRIC_ID,
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="tidmad_denoised_h5",
            failures=(
                ScoreabilityFailure(
                    requirement="required_attrs",
                    input_identity=4,
                    detail="attr 'voltage_range_mV' missing on group timeseries/channel0001",
                ),
            ),
        ),
    )
    record = _TUNER._build_scoring_failure_record(NotScoreableError(refusal), **_COMMON)
    assert record["status"] == "error_scoring"
    assert record["denoising_score"] is None
    assert (record["failure_stage"], record["failure_type"]) == ("scoring", "not_scoreable")
    memory = record["memory"]
    assert "not scoreable" in memory["conclusion"]
    assert "required_attrs[file 4]" in memory["conclusion"]
    assert "voltage_range_mV" in memory["conclusion"]
    assert "tidmad_denoised_h5" in memory["conclusion"]
    assert "crash" not in memory["conclusion"].lower()
    assert "No scorer arithmetic was reached" in memory["discovery"]
    assert (memory["round_index"], memory["attempt_in_round"]) == (3, 1)


def test_the_helper_is_what_the_live_except_path_calls():
    """Reachability of the boundary: the scoring ``except`` in ``run()`` calls
    the helper and no longer inlines the record (a re-inlined dict would
    silently drop the not-scoreable description)."""
    source = tuner_node_source()
    # Indentation-insensitive: the scoring `except` kept its body but changed
    # indent level when the attempt loop was decomposed into phase functions
    # (Step 07 PR 07b, C7d). The anchor is the handler and the statement that
    # opens it, not the column they happen to sit at.
    m = re.search(r"except Exception as e:\n\s*scoring_time", source)
    assert m, "the scoring except path is no longer recognisable"
    start = m.start()
    block = source[start : source.index("_emit_record(", start)]
    assert "_build_scoring_failure_record(" in block
    assert '"status": "error_scoring"' not in block


@pytest.mark.parametrize("exc", [ValueError("x"), RuntimeError("y")])
def test_non_refusal_exceptions_never_gain_failure_type(exc):
    record = _TUNER._build_scoring_failure_record(exc, **_COMMON)
    assert "failure_stage" not in record and "failure_type" not in record
