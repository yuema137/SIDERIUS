"""V21 PR E — E4: the read-side funnel assembler's contract.

The most dangerous possible bug in this commit is the join inventing or
merging identity, so the fixtures here are adversarial about exactly
that: multiple ``None``-id artifacts that must never collapse, a
malformed file that must never read as "stage absent", and a missing
directory that must never read as "zero candidates".

The assembler is READ-ONLY; a test asserts nothing on disk changes.

Design doc: ``docs/design/v21_priorities/pr_e_proposal_scale_funnel.md``
Commit E4.
"""

from __future__ import annotations

import json
import os

import pytest

from execute_tools.funnel_assembly import (
    assemble_iteration_funnel,
    read_trained_parameter_counts,
)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _attempt(
    tmp_path,
    n,
    name,
    *,
    cid,
    stages=("proposal", "implementor", "validation"),
    validation_passed=True,
    run="r1",
):
    d = tmp_path / f"attempt_{n:03d}_{name}"
    if "proposal" in stages:
        _write(
            d / f"proposal_{run}.json",
            {
                "candidate_id": cid,
                "model_name": name,
                "parameter_count_estimate": 5_000_000,
                "preflight_factor": 0.4,
            },
        )
    if "implementor" in stages:
        _write(d / f"implementor_{run}.json", {"candidate_id": cid, "model_type": name})
    if "validation" in stages:
        _write(
            d / f"validation_{run}.json",
            {
                "candidate_id": cid,
                "model_type": name,
                "passed": validation_passed,
                "instantiation_passed": validation_passed,
                "realized_total_parameter_count": 4352,
                "realized_trainable_parameter_count": 2304,
            },
        )
    return d


def _tuner(tmp_path, name, *, cid, params=(1000, 2000), run="r1"):
    _write(
        tmp_path / name / f"run_output_{run}.json",
        {
            "candidate_id": cid,
            "model_type": name,
            "all_records": [
                {"exp_id": f"e{i}", "candidate_id": cid, "model_params": p}
                for i, p in enumerate(params)
            ],
        },
    )


class TestCompleteAndStoppedRows:
    def test_complete_candidate_reaches_every_stage_with_fan_in(self, tmp_path):
        _attempt(tmp_path, 1, "alpha", cid="cand_a")
        _tuner(tmp_path, "alpha", cid="cand_a", params=(1000, 2000, None))
        funnel = assemble_iteration_funnel(str(tmp_path))
        assert funnel.discoverable is True
        assert len(funnel.rows) == 1 and not funnel.unjoinable
        row = funnel.rows[0]
        assert row.candidate_id == "cand_a"
        assert row.stopped_at_stage is None
        assert row.incomplete_stages == []
        assert row.tuner_record_count == 3  # one candidate, MANY records
        assert row.trained_trainable_parameter_counts == [1000, 2000, None]
        # O-E-6 convention-explicit columns from their native owners:
        assert row.proposed_trainable_parameter_count_estimate == 5_000_000
        assert row.preflight_factor == 0.4  # a MEASUREMENT, never a disposition
        assert row.implemented_total_parameter_count == 4352
        assert row.implemented_trainable_parameter_count == 2304

    def test_stopped_at_validation_carries_the_native_verdict(self, tmp_path):
        _attempt(tmp_path, 1, "beta", cid="cand_b", validation_passed=False)
        funnel = assemble_iteration_funnel(str(tmp_path))
        row = funnel.rows[0]
        assert row.stopped_at_stage == "validation"
        # The native verdict IS the reason — no new vocabulary (O-E-2).
        assert row.stop_reason_native is not None
        assert row.stop_reason_native["passed"] is False
        # Its measurements still surface: the candidate had a size.
        assert row.implemented_total_parameter_count == 4352

    def test_stopped_at_implementation_has_reason_ABSENT(self, tmp_path):
        """§0.E: implementation is the one stage with no typed native
        reason. Absence is preserved, never manufactured."""
        _attempt(tmp_path, 1, "gamma", cid="cand_c", stages=("proposal",))
        row = assemble_iteration_funnel(str(tmp_path)).rows[0]
        assert row.stopped_at_stage == "implementation"
        assert row.stop_reason_native is None
        assert row.stages["implementation"].reason_absent is True

    def test_implemented_but_never_validated_stops_at_validation(self, tmp_path):
        """The implementor emitted, validation never ran: the candidate
        stopped AT validation (the first stage without evidence), not at
        implementation — M-E4-7's killer. Reason absent: validation that
        never ran left no verdict."""
        _attempt(tmp_path, 1, "epsilon", cid="cand_e", stages=("proposal", "implementor"))
        row = assemble_iteration_funnel(str(tmp_path)).rows[0]
        assert row.stopped_at_stage == "validation"
        assert row.stop_reason_native is None
        assert row.stages["validation"].reason_absent is True

    def test_validation_passed_but_no_tuner_records_stops_at_tuner(self, tmp_path):
        _attempt(tmp_path, 1, "delta", cid="cand_d")
        row = assemble_iteration_funnel(str(tmp_path)).rows[0]
        assert row.stopped_at_stage == "tuner"
        assert row.incomplete_stages == ["tuner"]


class TestUnjoinableNeverMerges:
    def test_two_none_id_artifact_sets_stay_separate(self, tmp_path):
        """Two legacy attempt dirs, six None-id artifacts — six separate
        unjoinable evidence items. Same-directory co-location is a
        directory fact, not an identity (§10)."""
        _attempt(tmp_path, 1, "old_a", cid=None)
        _attempt(tmp_path, 2, "old_b", cid=None)
        funnel = assemble_iteration_funnel(str(tmp_path))
        assert funnel.rows == []
        assert len(funnel.unjoinable) == 6
        assert all(r.candidate_id is None for r in funnel.unjoinable)

    def test_a_none_id_tuner_output_is_unjoinable_not_absorbed(self, tmp_path):
        _attempt(tmp_path, 1, "alpha", cid="cand_a")
        _tuner(tmp_path, "alpha", cid=None)
        funnel = assemble_iteration_funnel(str(tmp_path))
        # The joinable candidate exists but its tuner leg is NOT joined via
        # the model_name coincidence — that would be the P6.2 regression.
        row = funnel.rows[0]
        assert row.tuner_record_count == 0
        assert row.stopped_at_stage == "tuner"
        assert len(funnel.unjoinable) == 1
        assert funnel.unjoinable[0].tuner_record_count == 2

    def test_mixed_dir_one_id_one_none(self, tmp_path):
        d = _attempt(tmp_path, 1, "mixed", cid="cand_m", stages=("proposal", "implementor"))
        _write(d / "validation_r1.json", {"candidate_id": None, "passed": True})
        funnel = assemble_iteration_funnel(str(tmp_path))
        assert len(funnel.rows) == 1
        assert set(funnel.rows[0].stages) >= {"proposal", "implementation"}
        assert len(funnel.unjoinable) == 1


class TestFailureModes:
    def test_malformed_artifact_is_unreadable_not_stage_absent(self, tmp_path):
        d = _attempt(tmp_path, 1, "alpha", cid="cand_a", stages=("proposal", "implementor"))
        (d / "validation_r1.json").write_text('{"truncated": ')
        funnel = assemble_iteration_funnel(str(tmp_path))
        row = funnel.rows[0]
        assert len(row.unreadable) == 1
        assert "validation_r1.json" in row.unreadable[0].path

    def test_missing_directory_is_not_discoverable_not_empty(self, tmp_path):
        funnel = assemble_iteration_funnel(str(tmp_path / "nope"))
        assert funnel.discoverable is False
        assert funnel.rows == []

    def test_empty_directory_is_discoverable_with_zero_candidates(self, tmp_path):
        funnel = assemble_iteration_funnel(str(tmp_path))
        assert funnel.discoverable is True
        assert funnel.rows == [] and funnel.unjoinable == []

    def test_attempt_dir_without_a_proposal_is_reported_not_rowed(self, tmp_path):
        (tmp_path / "attempt_001").mkdir()
        funnel = assemble_iteration_funnel(str(tmp_path))
        assert funnel.rows == []
        assert funnel.no_candidate_dirs == [str(tmp_path / "attempt_001")]

    def test_the_assembler_writes_nothing(self, tmp_path):
        _attempt(tmp_path, 1, "alpha", cid="cand_a")
        _tuner(tmp_path, "alpha", cid="cand_a")
        before = {
            os.path.join(dp, f): os.path.getmtime(os.path.join(dp, f))
            for dp, _, fs in os.walk(tmp_path)
            for f in fs
        }
        assemble_iteration_funnel(str(tmp_path))
        after = {
            os.path.join(dp, f): os.path.getmtime(os.path.join(dp, f))
            for dp, _, fs in os.walk(tmp_path)
            for f in fs
        }
        assert before == after, "the read-only assembler changed the workspace"


class TestLegacyStageLocalSanityCheck:
    """§11: NOT a funnel backfill. One stage's native numbers, no identity."""

    def test_reader_returns_flat_stage_local_counts(self, tmp_path):
        _tuner(tmp_path, "m1", cid=None, params=(7_280_256, 8_409_280))
        counts = read_trained_parameter_counts([str(tmp_path)])
        assert sorted(counts) == [7_280_256, 8_409_280]

    def test_v20_attempt3_range_reproduced_stage_locally(self):
        """LEGACY STAGE-LOCAL SANITY CHECK against the real V20 attempt-3
        arch-chain workspace — reproduces the ledger's already-recorded
        trained counts (P6.3: 7,280,256 ×3 · 8,409,280 ×4). No join, no
        identity, no new distribution claim (§E.3d.6).

        Machine-specific data: the path comes from an env var, is
        validated, and the test SKIPS with a reason when absent — it
        never falls back to a developer-specific location silently
        (CLAUDE.md portability rules).
        """
        root = os.environ.get("SIDERIUS_V20_ATTEMPT3_DIR")
        if not root:
            pytest.skip(
                "SIDERIUS_V20_ATTEMPT3_DIR not set — the legacy stage-local "
                "sanity check needs the preserved V20 attempt-3 campaign "
                "root holding BOTH chains (the ledger's ×3/×4 values span "
                "arch AND loss; lilab: /home/klz/Data/SIDEREIS_DATA/"
                "v20_attempt3_20260806_233242)"
            )
        if not os.path.isdir(root):
            pytest.fail(f"SIDERIUS_V20_ATTEMPT3_DIR={root!r} is not a directory")
        chains = sorted(
            os.path.join(root, c)
            for c in os.listdir(root)
            if os.path.isdir(os.path.join(root, c)) and c.startswith("v20_")
        )
        iter_dirs = sorted(
            os.path.join(chain, d, sub)
            for chain in chains
            for d in os.listdir(chain)
            # iter_NNN dirs sit beside iter_NNN_hardware.json files.
            if d.startswith("iter_") and os.path.isdir(os.path.join(chain, d))
            for sub in os.listdir(os.path.join(chain, d))
            if sub.startswith("iteration_")
        )
        counts = read_trained_parameter_counts(iter_dirs)
        # The ledger's recorded attempt-3 values must be PRESENT; asserting
        # the multiset exactly would be a new claim, which §E.3d.6 forbids.
        assert 7_280_256 in counts
        assert 8_409_280 in counts
        assert min(counts) >= 0
