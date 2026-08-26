"""The GPU-C probe assembler must honour the failure contract it states.

F-Q5-1, found on testpod during the Q5 co-residency probe. All four quad
legs died. The orchestrator DETECTED that correctly and printed its
promise (`gpu_c_coresidency_probe.sh:179-180`):

    WARNING: at least one quad leg failed or timed out — the assembler
      will name the failed legs and exit non-zero (factor not usable).

The assembler then died with `FileNotFoundError` at `_load_leg`, which
opened each leg JSON with no existence handling. The failed legs were
never named. **The detection worked; the reporting did not.**

The invariant, in the form the ledger records it:

    A STATED CONTRACT MUST BE HONOURED ON THE PATH THAT STATES IT.

`assemble` already implemented the promise -- `failed_legs`, the
`FAILED LEGS:` line, `return 1 if failures else 0` -- but only for legs
that survived long enough to write a file. Its failure test was
`status != "success"`, which can only see legs that wrote one, so TOTAL
failure was the single outcome it could not report. That is why the
crash and the blind spot are one defect and not two: the reporter was
unreachable exactly when it was most needed.

Scope. This is the CONTRACT half only. Nothing here reproduces or
explains why four legs died in under a second (hardware, a separate
lane), and nothing here touches the probe's leg-launch behaviour -- there
is a standing order on testpod that the probe script must not be changed
to obtain a green, and these tests are written so that it could not help
if it were: they drive `assemble` over fixture JSONs on disk and never
launch a leg.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = REPO_ROOT / "sdsc_submission_scripts" / "gpu_c_probe_train_leg.py"
ORCHESTRATOR = REPO_ROOT / "sdsc_submission_scripts" / "gpu_c_coresidency_probe.sh"


def _load_probe():
    """Load the driver from THIS checkout (portability rule)."""
    spec = importlib.util.spec_from_file_location("_fq51_probe", PROBE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_fq51_probe"] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


def _leg(label: str, band: str, *, status: str = "success", wall: float = 100.0) -> dict:
    return {
        "leg_label": label,
        "band": band,
        "status": status,
        "wall_seconds": wall,
        "peak_tree_anon_rss_gib": 12.5,
        "peak_tree_vram_gib": 30.0,
    }


def _write_legs(work: Path, *, omit: tuple[str, ...] = (), status: str = "success") -> None:
    """Lay down a full probe run, minus whichever legs `omit` names."""
    work.mkdir(parents=True, exist_ok=True)
    if "solo" not in omit:
        (work / "leg_solo.json").write_text(
            json.dumps(_leg("solo", probe.REFERENCE_BAND, wall=100.0)), encoding="utf-8"
        )
    for band in probe.CAMPAIGN_BANDS:
        if f"quad{band}" in omit:
            continue
        (work / f"leg_quad_band{band}.json").write_text(
            json.dumps(_leg("quad", band, status=status, wall=200.0)), encoding="utf-8"
        )


def _assemble(work: Path, out: Path) -> int:
    return probe.assemble(argparse.Namespace(work_dir=str(work), out=str(out)))


class TestTheStatedContractIsHonoured:
    """THE witness: the exact testpod shape -- every quad leg wrote nothing."""

    def test_all_quad_legs_missing_does_not_crash(self, tmp_path):
        """Before the fix this raised FileNotFoundError and named nothing."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=tuple(f"quad{b}" for b in probe.CAMPAIGN_BANDS))
        rc = _assemble(work, out)  # must not raise
        assert rc != 0, "the assembler reported success with no quad leg at all"

    def test_the_missing_legs_are_named(self, tmp_path, capsys):
        """'name the failed legs' is the promise; naming is the deliverable."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=("quad4-9", "quad15-19"))
        _assemble(work, out)
        printed = capsys.readouterr().out
        for band in ("4-9", "15-19"):
            assert f"quad_band{band}" in printed, (
                f"the assembler did not name the failed leg for band {band}"
            )

    def test_the_result_json_records_them_machine_readably(self, tmp_path):
        """An operator gates on the artifact, not on the human summary."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=("quad4-9",))
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert "quad_band4-9" in result["failed_legs"]
        assert result["legs_with_no_record"] == ["quad_band4-9"]

    def test_a_missing_solo_leg_is_reported_too(self, tmp_path):
        """The reference leg is not exempt from the contract."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=("solo",))
        rc = _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert rc != 0
        assert f"solo_band{probe.REFERENCE_BAND}" in result["failed_legs"]

    def test_a_truncated_leg_is_reported_not_raised(self, tmp_path):
        """A leg killed mid-write leaves invalid JSON.

        Same fact as absence for reporting purposes -- no usable record --
        and it must not become a `JSONDecodeError` in the reporter.
        """
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        (work / "leg_quad_band10-14.json").write_text('{"leg_label": "quad", "ba', encoding="utf-8")
        rc = _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert rc != 0
        assert "quad_band10-14" in result["failed_legs"]


class TestNoFactorIsDerivedFromALegThatNeverRan:
    """The other half of 'factor not usable'."""

    def test_a_missing_reference_leg_yields_no_factor(self, tmp_path):
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=(f"quad{probe.REFERENCE_BAND}",))
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["coresidency_factor"] is None, (
            "a co-residency factor was published from a leg that never ran"
        )

    def test_a_missing_leg_reports_no_measurements_rather_than_zero(self, tmp_path):
        """`None` is honest; `0.0` would read as a real observation."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, omit=("quad4-9",))
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["per_chain_peak_vram_gib"]["4-9"] is None
        assert result["per_chain_peak_anon_rss_gib"]["4-9"] is None


class TestTheHealthyPathIsUnchanged:
    """The repair must not turn a good probe run into a failure."""

    def test_a_complete_successful_run_still_exits_zero(self, tmp_path):
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        assert _assemble(work, out) == 0

    def test_it_still_derives_the_matched_band_factor(self, tmp_path):
        """Parity: asserts only PRE-EXISTING keys, so it passes on both
        sides of the repair and a regression here is a real one."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        # 200.0 quad / 100.0 solo, both on the reference band.
        assert result["coresidency_factor"] == 2.0
        assert result["failed_legs"] == []

    def test_a_leg_that_ran_and_failed_is_still_named_by_its_own_record(self, tmp_path):
        """Parity: the pre-existing status path is untouched."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, status="failed")
        rc = _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert rc != 0
        assert result["failed_legs"] == [f"quad_band{b}" for b in probe.CAMPAIGN_BANDS]


class TestRanAndFailedIsNotTheSameAsLeftNoRecord:
    """Two different diagnoses, and only the second was unreportable."""

    def test_a_leg_that_wrote_a_failure_record_is_not_reported_as_absent(self, tmp_path):
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work, status="failed")
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["failed_legs"], "the status path stopped naming failures"
        assert result["legs_with_no_record"] == [], (
            "a leg that wrote a failure record must not be reported as absent"
        )

    def test_a_healthy_run_records_neither(self, tmp_path):
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["failed_legs"] == []
        assert result["legs_with_no_record"] == []


class TestThePromiseAndTheCodeAgree:
    """The orchestrator's printed promise is this contract's specification.

    If the wording is ever changed, the test that guards it should be
    read again rather than silently guarding nothing.
    """

    def test_the_orchestrator_still_makes_the_promise(self):
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        assert "name the failed legs and exit non-zero" in text

    def test_the_loader_does_not_raise_on_a_missing_leg(self, tmp_path):
        """The single line the defect lived on."""
        assert probe._load_leg(tmp_path / "absent.json") is None


class TestTheReporterCannotBeCrashedByItsOwnInput:
    """N5. Every one of these would have put the crash back one line down.

    The whole point of the repair is that the reporter stays alive to name
    what went wrong. A malformed record reaching `.get` or `["wall_seconds"]`
    reinstates exactly the failure mode, just later in the function.
    """

    @pytest.mark.parametrize("body", ["[]", '"x"', "null", "123"])
    def test_valid_json_that_is_not_a_leg_record(self, tmp_path, body):
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        (work / "leg_quad_band4-9.json").write_text(body, encoding="utf-8")
        rc = _assemble(work, out)  # must not raise
        result = json.loads(out.read_text(encoding="utf-8"))
        assert rc != 0
        assert "quad_band4-9" in result["failed_legs"]

    def test_a_record_that_cannot_name_itself_is_still_named(self, tmp_path):
        """Falls back to the position it was loaded from."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        (work / "leg_quad_band10-14.json").write_text(
            json.dumps({"status": "failed"}), encoding="utf-8"
        )
        _assemble(work, out)
        result = json.loads(out.read_text(encoding="utf-8"))
        assert "quad_band10-14" in result["failed_legs"]

    def test_a_record_with_no_wall_time_yields_no_factor(self, tmp_path):
        """`wall_seconds` missing is the same hazard as an absent file."""
        work, out = tmp_path / "work", tmp_path / "result.json"
        _write_legs(work)
        (work / "leg_solo.json").write_text(
            json.dumps({"leg_label": "solo", "band": probe.REFERENCE_BAND, "status": "success"}),
            encoding="utf-8",
        )
        rc = _assemble(work, out)  # must not raise
        result = json.loads(out.read_text(encoding="utf-8"))
        assert result["coresidency_factor"] is None
        assert rc != 0, (
            "the probe published a null factor and exited 0 -- an uncomputable "
            "factor is a failed probe, not a successful one"
        )
