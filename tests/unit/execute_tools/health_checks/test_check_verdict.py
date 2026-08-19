"""Step 08a C1 — the typed four-way check verdict and its compatibility bridge.

Design authority: ``docs/design/generic_framework_upgrade/
step_08_health_check_task_profile/pr_08a_check_input_contract.md`` §3.1, §4.1.

Defect classes these tests own, none of which any other layer catches:

* a silently mis-derived verdict — a legacy-shaped result classified as
  ``passed`` when it was inapplicable, or as ``failed`` when every file
  failed I/O (the difference between "the model is bad" and "we could not
  look at the model");
* a result whose typed verdict contradicts the ``passed`` field that
  actually routes the gate;
* verdict drift under the additive schema change: the six checks must emit
  byte-identical ``passed`` / ``reason`` / ``metrics`` after it.

Static tooling cannot own these: Pydantic enforces that ``verdict`` is a
member of the enum, but not WHICH member a given legacy result maps to.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from execute_tools.health_checks.schemas import CheckVerdict, HealthCheckResult
from tests.unit.execute_tools.health_checks._verdict_corpus import (
    CASE_IDS,
    normalise,
    run_case,
)

MANIFEST_PATH = Path(__file__).resolve().parent / "goldens" / "verdict_parity_manifest_pre08a.json"


# ---------------------------------------------------------------------------
# §3.1 derivation table — one test per row
# ---------------------------------------------------------------------------


class TestVerdictDerivation:
    """Each row of the design's compatibility mapping, from the legacy shape."""

    def test_clean_pass_derives_passed(self):
        r = HealthCheckResult(check_name="x", passed=True)
        assert r.verdict is CheckVerdict.PASSED

    def test_pass_with_non_na_reason_derives_passed(self):
        """A passing result may still carry prose; that is not inapplicability."""
        r = HealthCheckResult(check_name="x", passed=True, reason="x: measured 3 files")
        assert r.verdict is CheckVerdict.PASSED

    def test_pass_with_na_marker_derives_inapplicable(self):
        r = HealthCheckResult(
            check_name="x",
            passed=True,
            reason="x: not applicable — no target_path_fn in context",
        )
        assert r.verdict is CheckVerdict.INAPPLICABLE

    def test_exception_metric_derives_error(self):
        """The runner's Bug-B guard shape (``runner.py`` exception handler)."""
        r = HealthCheckResult(
            check_name="x",
            passed=False,
            reason="x: check raised unexpected ValueError: boom",
            metrics={"exception_type": "ValueError"},
        )
        assert r.verdict is CheckVerdict.ERROR

    def test_all_files_io_failed_derives_error(self):
        """Nothing was measurable — an error, not a scientific failure."""
        r = HealthCheckResult(
            check_name="x",
            passed=False,
            reason="x: all 3 files failed I/O",
            metrics={"n_files_attempted": 3, "n_files_io_failed": 3},
        )
        assert r.verdict is CheckVerdict.ERROR

    def test_partial_io_failure_derives_failed(self):
        """A computed failing metric survives alongside some I/O loss."""
        r = HealthCheckResult(
            check_name="x",
            passed=False,
            reason="x: aggregation=any_pass failed — per-file: file_0=1, file_1=io_err",
            metrics={"n_files_attempted": 2, "n_files_io_failed": 1},
        )
        assert r.verdict is CheckVerdict.FAILED

    def test_plain_failure_derives_failed(self):
        r = HealthCheckResult(check_name="x", passed=False, reason="x: unique_int8=1")
        assert r.verdict is CheckVerdict.FAILED

    def test_zero_files_attempted_is_not_error(self):
        """``0 == 0`` must not be read as "every file failed"."""
        r = HealthCheckResult(
            check_name="x",
            passed=False,
            reason="x: flagged",
            metrics={"n_files_attempted": 0, "n_files_io_failed": 0},
        )
        assert r.verdict is CheckVerdict.FAILED

    @pytest.mark.parametrize(
        "reason",
        [
            "x: NOT APPLICABLE — no files",
            "x: Not Applicable — no files",
            "x: this check is notapplicable here",
        ],
    )
    def test_only_the_exact_lowercase_marker_maps_to_inapplicable(self, reason: str):
        """Prose drift must surface as a test failure, never as a silent reclass.

        Casing variants ARE matched (the derivation lowercases the reason);
        a differently-worded phrase is not. This pins which is which so a
        future edit to a check's wording cannot quietly change its verdict.
        """
        r = HealthCheckResult(check_name="x", passed=True, reason=reason)
        expected = (
            CheckVerdict.INAPPLICABLE if "not applicable" in reason.lower() else CheckVerdict.PASSED
        )
        assert r.verdict is expected


class TestExplicitVerdictWins:
    def test_explicit_verdict_overrides_derivation(self):
        """An explicit ``verdict=`` is authority; the bridge does not second-guess it."""
        r = HealthCheckResult(
            check_name="x",
            passed=True,
            reason="x: measured cleanly",  # would derive PASSED
            verdict=CheckVerdict.INAPPLICABLE,
        )
        assert r.verdict is CheckVerdict.INAPPLICABLE

    def test_explicit_error_on_failing_result_is_kept(self):
        r = HealthCheckResult(
            check_name="x",
            passed=False,
            reason="x: could not read",
            verdict=CheckVerdict.ERROR,
        )
        assert r.verdict is CheckVerdict.ERROR


class TestContradictionRejected:
    """A result may never route one way and report another."""

    @pytest.mark.parametrize(
        ("verdict", "passed"),
        [
            (CheckVerdict.PASSED, False),
            (CheckVerdict.INAPPLICABLE, False),
            (CheckVerdict.FAILED, True),
            (CheckVerdict.ERROR, True),
        ],
    )
    def test_contradictory_pair_raises(self, verdict: CheckVerdict, passed: bool):
        with pytest.raises(ValidationError, match="contradiction"):
            HealthCheckResult(check_name="x", passed=passed, verdict=verdict)

    def test_unknown_verdict_string_rejected(self):
        with pytest.raises(ValidationError):
            HealthCheckResult(check_name="x", passed=True, verdict="probably_fine")  # type: ignore[arg-type]


class TestSerialisation:
    def test_json_round_trip_preserves_verdict(self):
        original = HealthCheckResult(
            check_name="x",
            passed=True,
            reason="x: not applicable — no files in context",
            metrics={"peek_samples_requested": 10},
        )
        restored = HealthCheckResult.model_validate_json(original.model_dump_json())
        assert restored.verdict is CheckVerdict.INAPPLICABLE
        assert restored == original

    def test_serialised_verdict_is_the_plain_string(self):
        """Records are read by external tooling — the wire value is the vocabulary."""
        r = HealthCheckResult(check_name="x", passed=False, reason="x: flagged")
        assert json.loads(r.model_dump_json())["verdict"] == "failed"

    def test_round_trip_of_an_explicitly_contradictory_payload_is_rejected(self):
        """Validation is not bypassed by coming in through JSON."""
        payload = json.dumps({"check_name": "x", "passed": True, "verdict": "failed"})
        with pytest.raises(ValidationError, match="contradiction"):
            HealthCheckResult.model_validate_json(payload)


# ---------------------------------------------------------------------------
# Capture-first parity — the six checks are unchanged by the additive field
# ---------------------------------------------------------------------------


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


class TestVerdictParityManifest:
    """Replay the frozen pre-08a corpus through the CURRENT code.

    The manifest was captured before any 08a change existed and its expected
    verdicts were transcribed independently in ``_verdict_corpus``. This test
    is therefore comparing production against evidence production did not
    author.
    """

    def test_manifest_covers_every_case_and_verdict_class(self):
        manifest = _manifest()
        assert [case["case_id"] for case in manifest["cases"]] == list(CASE_IDS)
        assert {case["expected_verdict"] for case in manifest["cases"]} == {
            "passed",
            "failed",
            "inapplicable",
            "error",
        }

    def test_every_case_replays_byte_identically_with_the_expected_verdict(self, tmp_path):
        manifest = _manifest()
        drift: list[str] = []
        for case in manifest["cases"]:
            case_id = case["case_id"]
            workdir = tmp_path / case_id
            workdir.mkdir(parents=True, exist_ok=True)
            result = run_case(case_id, workdir)
            token = str(workdir)

            if result.passed != case["passed"]:
                drift.append(f"{case_id}: passed {case['passed']} -> {result.passed}")
            reason = normalise(result.reason, token)
            if reason != case["reason"]:
                drift.append(f"{case_id}: reason {case['reason']!r} -> {reason!r}")
            metrics = normalise(result.metrics, token)
            if metrics != case["metrics"]:
                changed = sorted(
                    key
                    for key in set(metrics) | set(case["metrics"])
                    if metrics.get(key) != case["metrics"].get(key)
                )
                drift.append(f"{case_id}: metrics differ on {changed}")
            if result.verdict.value != case["expected_verdict"]:
                drift.append(
                    f"{case_id}: verdict {case['expected_verdict']} -> {result.verdict.value}"
                )
        assert not drift, "pre-08a parity broken:\n  " + "\n  ".join(drift)
