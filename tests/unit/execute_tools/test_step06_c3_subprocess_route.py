"""Step 06 — C3: the SUBPROCESS route reconstructs the metric and agrees.

Design: ``docs/design/generic_framework_upgrade/step_06_metric_interface.md``
§9, §12, §19 C3.

The second existing entry point — ``TidmadSandbox.execute_scoring`` →
``execute_tools/denoising_score_single.py`` — now derives the SAME TIDMAD
instance from what already crosses (``--dataset_profile_json``, 05c §3.2a
Option A), evaluates the SAME scoreability, and only then calls the frozen
``score_vector``. Positive parity (route (ii) == route (i) == the C0 literal,
through a REAL child) is asserted by the C0 oracle module itself, which now
runs against this code; this module adds what C3 owns:

* the child's structure — ONE metric derivation, ONE deliverable-spec
  derivation, ONE ``resolve_dataset_profile()`` (the pre-existing Regime-A
  fallback), NO executed copy of the deliverable-name template (the two
  literals 05c left for Step 06 are gone), no ambient second resolution;
* the NEGATIVE through a real child: an unscoreable deliverable yields a
  STRUCTURED refusal — named on stderr, persisted into ``--output_json`` —
  with exit 1 (so the parent's existing classifier says ``"error"``, exactly
  as the retired "File not found" pre-check did) and NO scorer traceback;
* the parent's argv is byte-identical (the C0 golden runs against this code).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from core.sandbox_executor import TidmadSandbox
from execute_tools.array2h5 import create_abra_file
from execute_tools.dataset_config import bind_dataset_profile
from execute_tools.deliverable_spec import derive_tidmad_deliverable_spec
from tests.unit.core.test_step06_c0_two_route_oracle import (
    EXP_ID,
    FILE_INDEX,
    MODEL_TYPE,
    RUN_NAME,
    _bound_profile,
)
from tests.unit.scripts.test_step05c_c6_launcher_reconstruction import (
    _executed_string_constants,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CHILD = REPO_ROOT / "execute_tools" / "denoising_score_single.py"


# ---------------------------------------------------------------------------
# 1. Structure of the child — one derivation, no second authority
# ---------------------------------------------------------------------------


def _calls_named(source: str, name: str) -> int:
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_the_child_derives_the_metric_and_the_spec_exactly_once():
    source = CHILD.read_text()
    assert _calls_named(source, "derive_tidmad_metric") == 1
    # Step 12 / PR-12d D4b: the SPEC derivation became the geometry-aware
    # `derive_run_deliverable_spec`, which answers a DECLARED ABSENCE instead
    # of raising for a task that declares no TIDMAD storage geometry. The
    # claim this test makes — EXACTLY ONE derivation, no ambient second one —
    # is unchanged; only which function performs it moved.
    assert _calls_named(source, "derive_tidmad_deliverable_spec") == 0
    assert _calls_named(source, "derive_run_deliverable_spec") == 1
    # The pre-existing Regime-A fallback (absent --dataset_profile_json) and
    # nothing else: no ambient second resolution when a profile was given.
    assert _calls_named(source, "resolve_dataset_profile") == 1
    assert "load_dataset_profile(args.dataset_profile_json)" in source


def test_the_child_names_the_deliverable_through_the_contract_not_a_literal():
    """The two literals 05c left at the scorer (its census :178/:200 — "Step 06
    — NOT touched") are gone: no executed copy of the template survives, and
    both name shapes resolve through ``deliverable_spec.naming``."""
    source = CHILD.read_text()
    inlined = [s for s in _executed_string_constants(source) if "abra_validation_denoised" in s]
    assert inlined == [], inlined
    assert "deliverable_spec.naming.name(" in source
    assert "deliverable_spec.naming.unqualified_name(" in source


def test_scoreability_precedes_the_arithmetic_in_the_child():
    """Order in source: the handle's ``evaluate`` is the only route to the
    scorer; ``score_vector`` is not called directly by the child anymore."""
    source = CHILD.read_text()
    assert _calls_named(source, "score_vector") == 0
    assert "metric.evaluate(" in source
    assert source.index("metric.evaluate(") < source.index("Final Denoising Score")


# ---------------------------------------------------------------------------
# 2. The NEGATIVE through a REAL child
# ---------------------------------------------------------------------------


@pytest.fixture
def unscoreable_workspace(tmp_path):
    """A workspace whose ONE deliverable is refused by the contract: stored as
    int16 (the scorer would not crash on it — it would silently score on the
    wrong scale — so only the contract catches it), small (scoreability is
    file-level; no arithmetic is reached, so no full-length segment is
    needed). The raw side is irrelevant: the child must refuse before opening
    it."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    profile = _bound_profile(str(tmp_path / "raw_{file_index:04d}.h5"))
    spec = derive_tidmad_deliverable_spec(profile)
    name = spec.naming.name(
        model_type=MODEL_TYPE, run_name=RUN_NAME, exp_id=EXP_ID, input_identity=FILE_INDEX
    )
    wide = np.arange(64, dtype=np.int16)
    create_abra_file(str(workspace / name), wide, wide, indexed=False, storage=spec.storage)
    return {"profile": profile, "workspace": workspace}


@pytest.mark.allow_real_subprocess  # the REAL scoring child is the point (design §19 C3 §4)
def test_an_unscoreable_deliverable_is_a_structured_refusal_through_the_real_child(
    unscoreable_workspace, monkeypatch
):
    monkeypatch.chdir(REPO_ROOT)
    fx = unscoreable_workspace
    with bind_dataset_profile(fx["profile"]):
        sandbox = TidmadSandbox(
            run_name=RUN_NAME, workspace=str(fx["workspace"]), file_index=FILE_INDEX
        )
        result = sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})

    # The parent's EXISTING classifier: exit 1 → "error" (design C3 §6 — no
    # new status invented). The message names the structured refusal.
    assert result["status"] == "error", result
    assert "Deliverable not scoreable [tidmad_denoised_h5] required_dtype" in result["message"]
    assert "int16" in result["message"] and "int8" in result["message"]
    assert "Traceback" not in result["message"], result["message"]

    # The child persisted the structured payload into --output_json (which
    # the parent leaves in place on the error path).
    score_json = (
        fx["workspace"] / "records" / RUN_NAME / f"score_results_{MODEL_TYPE}_{EXP_ID}.json"
    )
    payload = json.loads(score_json.read_text())
    assert payload["denoising_score"] is None
    assert payload["not_scoreable"]["metric_id"] == "tidmad_denoising_score"
    assert payload["not_scoreable"]["direction"] == "higher"
    failures = payload["not_scoreable"]["verdict"]["failures"]
    assert [f["requirement"] for f in failures] == ["required_dtype"]
    assert failures[0]["input_identity"] == FILE_INDEX


@pytest.mark.allow_real_subprocess
def test_a_missing_deliverable_is_a_completeness_refusal_through_the_real_child(
    tmp_path, monkeypatch
):
    """The retired ``File not found`` pre-check is now the contract's
    completeness requirement — same exit, same parent classification, but a
    named, structured refusal."""
    monkeypatch.chdir(REPO_ROOT)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    with bind_dataset_profile(_bound_profile(str(tmp_path / "raw_{file_index:04d}.h5"))):
        sandbox = TidmadSandbox(run_name=RUN_NAME, workspace=str(workspace), file_index=FILE_INDEX)
        result = sandbox.execute_scoring(EXP_ID, RUN_NAME, MODEL_TYPE, {}, {}, {})
    assert result["status"] == "error"
    assert "completeness: deliverable not found at" in result["message"]
    assert "Traceback" not in result["message"]
