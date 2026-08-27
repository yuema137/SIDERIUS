"""V19 PR 1 P1-C5 — per-file best table tests
(design: docs/design/v19_priorities/pr1_chain_incumbents.md §3.7).

Fixtures build real chain workspaces on disk: ``iter_NNN/manifest.json``
+ ``run_output_iter_NNN.json`` + optional ``run_config_iter_NNN.json``.
No LLM, no training. Every test exercises the shared :func:`build_table`
computation; the byte-equality assertion pairs it with the rebuild CLI's
:func:`canonical_bytes` output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.resume import ReplayIntegrityError
from execute_tools.evaluation_metric import TIDMAD_METRIC_ID
from execute_tools.per_file_best import (
    LOG_BASE,
    SCHEMA_VERSION,
    TABLE_BASENAME,
    build_table,
    canonical_bytes,
    write_table,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Workspace fixture helpers
# ---------------------------------------------------------------------------

_BLOCKING_IDS = (
    "output_diversity_blocking",
    "output_std_blocking",
    "amplitude_collapse_blocking",
)


def _passing_verdicts() -> list[dict]:
    return [
        {
            "gate_name": gate_id,
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
        }
        for gate_id in _BLOCKING_IDS
    ]


def _failing_verdicts() -> list[dict]:
    """One blocking failure => production-policy invalidation."""
    return [
        {
            "gate_name": "output_diversity_blocking",
            "execution_status": "failed",
            "check_passed": False,
            "would_invalidate_under_production_policy": True,
            "resolved_action": "continue",
        }
    ] + [
        {
            "gate_name": gate_id,
            "execution_status": "passed",
            "check_passed": True,
            "would_invalidate_under_production_policy": False,
            "resolved_action": "continue",
        }
        for gate_id in _BLOCKING_IDS[1:]
    ]


def _record(
    exp_id: str,
    *,
    file_vector: list[float | None],
    is_trial: bool = False,
    status: str = "success",
    logical_round: int | None = None,
    waiver: bool | None = False,
    verdicts: list[dict] | None = None,
    eval_strategy: str | None = None,
    eval_portion: float | None = None,
    train_portion: float | None = None,
    model_params: int | None = 100,
    timestamp: str = "2026-07-27 00:00:00",
    metric_identity: tuple[str, str] = (TIDMAD_METRIC_ID, "higher"),
) -> dict:
    """Schema-valid ExperimentRecord dict.

    ``waiver=False`` stamps DS5 disabled-mode waiver (commit-time VALID
    without policy artifacts). Trial fields written only under
    ``is_trial=True``, mirroring production.

    ``metric_identity`` is the ``(metric_id, direction)`` pair the record
    declares it was scored under. It defaults to TIDMAD's, so every existing
    caller is unchanged; a non-TIDMAD value builds the composed-run shape that
    exposed the header's hardcoded identity.
    """
    rec: dict = {
        "exp_id": exp_id,
        "status": status,
        "model_type": "punet",
        "timestamp": timestamp,
        "params": {},
        "logical_round": logical_round,
        "denoising_score": max((v for v in file_vector if v is not None), default=None),
        "file_vector": file_vector,
        "health_gate_results": verdicts or [],
        "model_params": model_params,
    }
    # Step 10 P2a C2 — a SCORED record carries the identity it was scored
    # under (Step 06's additive `metric_result`), and the table now reads it
    # to decide which direction "best" means. These fixtures predate the
    # field; stamping it restores what a real post-Step-06 record looks like,
    # so these tests keep asserting row selection and provenance rather than
    # accidentally asserting the no-identity refusal. That refusal has its own
    # coverage in tests/unit/execute_tools/test_step10_p2a_c2_resume_and_per_file.py.
    if status == "success" and rec["denoising_score"] is not None:
        rec["metric_result"] = {
            "metric_id": metric_identity[0],
            "direction": metric_identity[1],
            "scalar": rec["denoising_score"],
            "per_sample": file_vector,
        }
    if waiver is False:
        rec["health_gate_enabled"] = False
    if is_trial:
        rec["is_trial"] = True
        rec["memory"] = {
            "expert_advice_followed": "n/a (test fixture)",
            "hypothesis": "n/a (test fixture)",
            "time_mode": "trial",
        }
        rec["trial_strategy"] = "snapshot"
        rec["eval_strategy"] = eval_strategy or "snapshot"
        rec["eval_portion"] = eval_portion if eval_portion is not None else 0.1
        rec["train_portion"] = train_portion if train_portion is not None else 0.1
        rec["trial_portion"] = 0.1
    return rec


def _write_iter(
    workspace: str,
    iter_idx: int,
    records: list[dict],
    *,
    best_valid_formal_score: float | None = None,
    best_valid_formal_exp_id: str | None = None,
    manifest_extra: dict | None = None,
    with_hash: bool = True,
    health_config_sha256: str | None = None,
    manifest_status: str = "completed",
    formal_eval_portion: float | None = None,
    formal_strategy: str | None = None,
    include_run_config: bool = True,
) -> str:
    run_name = f"iter_{iter_idx:03d}"
    iter_dir = os.path.join(workspace, run_name)
    model_dir = os.path.join(iter_dir, f"iteration_{iter_idx:03d}", "punet")
    os.makedirs(model_dir, exist_ok=True)

    if manifest_status == "no_records":
        manifest = {"status": "no_records", "iteration_dir": iter_dir, "output_path": None}
        with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        return ""

    output = HyperparamTuningOutput(
        run_name=run_name,
        model_type="punet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        all_records=records,
        started_at="2026-07-27 00:00:00",
        finished_at="2026-07-27 00:00:01",
        best_valid_formal_denoising_score=best_valid_formal_score,
        best_valid_formal_exp_id=best_valid_formal_exp_id,
        health_config_sha256=health_config_sha256,
    )
    output_path = os.path.join(model_dir, f"run_output_{run_name}.json")
    with open(output_path, "w") as f:
        f.write(output.model_dump_json())

    if include_run_config:
        cfg = {
            "run_name": run_name,
            "started_at": "2026-07-27 00:00:00",
        }
        if formal_eval_portion is not None:
            cfg["formal_eval_portion"] = formal_eval_portion
        if formal_strategy is not None:
            cfg["formal_strategy"] = formal_strategy
        with open(os.path.join(model_dir, f"run_config_{run_name}.json"), "w") as f:
            json.dump(cfg, f)

    manifest = {
        "status": "completed",
        "iteration_dir": iter_dir,
        "output_path": output_path,
        "model_name": "punet",
    }
    if with_hash:
        with open(output_path, "rb") as f:
            manifest["run_output_sha256"] = hashlib.sha256(f.read()).hexdigest()
    if manifest_extra:
        manifest.update(manifest_extra)
    with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f)
    return output_path


# ---------------------------------------------------------------------------
# Test bullet 1 — rebuild == incremental (byte-identical) [A5 primary]
# ---------------------------------------------------------------------------


def test_rebuild_equals_incremental_byte_identical(tmp_path):
    """The single build_table call reproduces byte-identical output on
    consecutive invocations over the same inputs; write_table's atomic
    canonical serialization means incremental writes and rebuild-CLI
    writes are bit-for-bit equal.
    """
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record("f1", file_vector=[0.5, 2.0, None] + [None] * 17, logical_round=1),
            _record(
                "t1", file_vector=[0.4, 0.9, None] + [None] * 17, is_trial=True, logical_round=1
            ),
        ],
        best_valid_formal_score=math.log(2.0) / math.log(LOG_BASE),
        best_valid_formal_exp_id="f1",
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    _write_iter(
        ws,
        2,
        [_record("f2", file_vector=[1.0, 1.5, None] + [None] * 17, logical_round=2)],
        best_valid_formal_score=math.log(1.5) / math.log(LOG_BASE),
        best_valid_formal_exp_id="f2",
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )

    # Incremental — the chain-runner path.
    path = write_table(ws)
    on_disk = Path(path).read_bytes()

    # Rebuild — the CLI path calls the SAME build_table.
    rebuilt = canonical_bytes(build_table(ws))
    assert on_disk == rebuilt


# ---------------------------------------------------------------------------
# Test bullet 2 — canonical ordering stable under permuted input order
# ---------------------------------------------------------------------------


def test_canonical_ordering_stable_under_permuted_iteration_order(tmp_path):
    """iter_NNN discovery is deterministic (ascending walk); rows within
    a build are sorted by (file_index, phase, validity); repeated builds
    yield identical bytes even when the underlying dict insertion order
    could differ (we assert against a build performed after touching the
    manifests in reverse order).
    """
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    _write_iter(
        ws,
        2,
        [_record("b", file_vector=[None, 1.5] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    first = canonical_bytes(build_table(ws))
    # Touch manifests in reverse order — must not change the output.
    for iter_idx in (2, 1):
        path = os.path.join(ws, f"iter_{iter_idx:03d}", "manifest.json")
        os.utime(path, (time.time(), time.time()))
    second = canonical_bytes(build_table(ws))
    assert first == second


# ---------------------------------------------------------------------------
# Test bullet 3 — atomicity: interrupted write preserves the previous
# ---------------------------------------------------------------------------


def test_atomic_write_preserves_previous_on_failure(tmp_path, monkeypatch):
    """A failure inside write_table after the temp file was created but
    before os.replace ran must NOT corrupt an already-existing table.
    """
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    good = write_table(ws)
    original = Path(good).read_bytes()

    # Now simulate a mid-write failure. os.replace is the last step;
    # patching it to raise leaves the temp file behind, but the real
    # per_file_best.json must be unchanged.
    _write_iter(
        ws,
        2,
        [_record("b", file_vector=[None, 1.5] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    import execute_tools.per_file_best as mod

    def _boom(_src, _dst):
        raise OSError("simulated write failure")

    monkeypatch.setattr(mod.os, "replace", _boom)
    with pytest.raises(OSError, match="simulated write failure"):
        write_table(ws)

    # Original table untouched.
    assert Path(good).read_bytes() == original


# ---------------------------------------------------------------------------
# Test bullet 4 — timestamps derive from committed provenance
# ---------------------------------------------------------------------------


def test_timestamps_derive_from_record_provenance_not_wallclock(tmp_path):
    """Building the table now and later (with different wall-clock
    times) yields byte-identical output. Every row's timestamp comes
    from the source record's persisted ``timestamp``, never from
    ``time.time()``.
    """
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "a",
                file_vector=[0.5, None] + [None] * 18,
                logical_round=1,
                timestamp="2026-07-27 12:34:56",
            )
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    a = canonical_bytes(build_table(ws))
    time.sleep(0.01)  # small delta; no wall-clock component should leak
    b = canonical_bytes(build_table(ws))
    assert a == b
    table = build_table(ws)
    assert table["rows"][0]["timestamp"] == "2026-07-27 12:34:56"


# ---------------------------------------------------------------------------
# Test bullet 5 — linear→log conversion + non-positive skip counting
# ---------------------------------------------------------------------------


def test_linear_to_log_conversion_and_nonpositive_skip(tmp_path):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "a",
                file_vector=[
                    5.27,  # log_5.27 == 1.0 exactly
                    0.0,  # skipped (non-positive)
                    -1.5,  # skipped (non-positive)
                    None,  # not counted (no value)
                ]
                + [None] * 16,
                logical_round=1,
            )
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    file0_rows = [r for r in table["rows"] if r["file_index"] == 0]
    assert file0_rows and file0_rows[0]["best_log_score"] == pytest.approx(1.0)
    # 0.0 and -1.5 counted; None values don't participate. inf is not
    # tested here because real scoring never emits non-finite floats
    # in file_vector; the production guard (`not math.isfinite(linear)
    # or linear <= 0.0`) is exercised by the 0.0/-1.5 branch.
    assert table["skipped_nonpositive_count"] == 2
    assert table["files_covered"] == [0]  # only file 0 had a usable value


# ---------------------------------------------------------------------------
# Test bullet 6 — validity semantics (record-level; raw vs valid)
# ---------------------------------------------------------------------------


def test_valid_rows_use_record_level_commit_time_validity(tmp_path):
    """A record with a failing blocking gate under commit-time policy
    appears in RAW rows only; VALID rows require validity=VALID."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "a",
                file_vector=[3.0, None] + [None] * 18,
                logical_round=1,
                waiver=False,  # DS5 disabled-mode waiver => VALID under P1-C2 rules
            ),
            _record(
                "b",
                file_vector=[5.0, None] + [None] * 18,
                logical_round=2,
                waiver=None,  # NOT waived: falls to persisted-verdict path
                verdicts=_failing_verdicts(),  # -> INVALID
            ),
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    file0 = {(r["phase"], r["validity"]): r for r in table["rows"] if r["file_index"] == 0}
    # RAW row: 5.0 wins (linear) — sourced from record 'b'.
    assert file0[("formal", "raw")]["exp_id"] == "b"
    assert file0[("formal", "raw")]["best_linear"] == 5.0
    # RAW row's gate_summary reports the source record's actual
    # commit-time classification. Without a materialized effective
    # policy artifact matching a health_config_sha256 stamp,
    # commit-time gate-set completeness is UNKNOWN (design §3.3 rule 3;
    # never a fallback to repo-current policy). The failing gate id is
    # still visible in blocking_failed_gate_ids — the row records what
    # the source record actually says.
    assert file0[("formal", "raw")]["gate_summary"]["candidate_validity"] == "unknown"
    assert file0[("formal", "raw")]["gate_summary"]["validity_basis"] == "unknown"
    assert file0[("formal", "raw")]["gate_summary"]["blocking_failed_gate_ids"] == [
        "output_diversity_blocking"
    ]
    # VALID row: only 'a' qualifies (linear 3.0).
    assert file0[("formal", "valid")]["exp_id"] == "a"
    assert file0[("formal", "valid")]["best_linear"] == 3.0
    assert file0[("formal", "valid")]["gate_summary"]["candidate_validity"] == "valid"
    assert file0[("formal", "valid")]["gate_summary"]["validity_basis"] == "waiver"
    assert file0[("formal", "valid")]["gate_summary"]["waiver_ids"] == ["health_gate_enabled=false"]


def test_phantom_score_only_in_raw_rows(tmp_path):
    """A collapsed-record's score appears in RAW rows only (never
    VALID) — the phantom-family guardrail from §3.7 A2/§2.5 trap 6."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "phantom",
                file_vector=[5.5762667, None] + [None] * 18,
                logical_round=1,
                status="failed_mode_collapse",  # never valid regardless of policy
            ),
            _record(
                "healthy",
                file_vector=[0.5, None] + [None] * 18,
                logical_round=2,
                waiver=False,
            ),
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    file0 = {(r["phase"], r["validity"]): r for r in table["rows"] if r["file_index"] == 0}
    # RAW row only includes SUCCESSFUL records — phantom is
    # failed_mode_collapse, so it never enters even the raw pool.
    assert file0[("formal", "raw")]["exp_id"] == "healthy"
    assert file0[("formal", "raw")]["best_linear"] == 0.5
    # VALID row: same 'healthy' record.
    assert file0[("formal", "valid")]["exp_id"] == "healthy"


# ---------------------------------------------------------------------------
# Test bullet 7 — tampered artifact => fail-closed on rebuild
# ---------------------------------------------------------------------------


def test_hash_mismatch_raises_replay_integrity(tmp_path):
    ws = str(tmp_path)
    output_path = _write_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    with open(output_path, "a") as f:
        f.write("\n")
    with pytest.raises(ReplayIntegrityError) as exc:
        build_table(ws)
    assert "REPLAY-INTEGRITY" in str(exc.value)
    assert output_path in str(exc.value)


# ---------------------------------------------------------------------------
# Test bullet 8 — offline legacy backfill smoke
# ---------------------------------------------------------------------------


def test_legacy_no_hash_manifest_counted_as_unverified(tmp_path):
    """A no-hash (V17-era) manifest still contributes rows but the
    header ``unverified_sources`` counter reflects it."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[1.0, None] + [None] * 18, logical_round=1, waiver=False)],
        formal_eval_portion=None,  # legacy source has neither key persisted
        formal_strategy=None,
        with_hash=False,
    )
    table = build_table(ws)
    assert table["unverified_sources"] == 1
    file0_valid = next(
        r for r in table["rows"] if r["file_index"] == 0 and r["validity"] == "valid"
    )
    # A4 legacy contract: null, never inferred.
    assert file0_valid["eval_portion"] is None
    assert file0_valid["eval_strategy"] is None


def test_modern_run_config_populates_formal_provenance(tmp_path):
    """A4 modern path: formal rows read the committed
    formal_eval_portion + formal_strategy from run_config."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[1.0, None] + [None] * 18, logical_round=1, waiver=False)],
        formal_eval_portion=0.25,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    file0_valid = next(
        r for r in table["rows"] if r["file_index"] == 0 and r["validity"] == "valid"
    )
    assert file0_valid["eval_portion"] == 0.25
    assert file0_valid["eval_strategy"] == "snapshot"


def test_formal_row_naming_mismatch_guard(tmp_path):
    """Operator-required (2026-07-27): explicitly guard against a
    silent naming mismatch between the tuner's write-side keys
    (``formal_strategy``, ``formal_eval_portion`` in
    ``run_config_iter_NNN.json``) and the per-file-best reader's
    row-side keys (``eval_strategy``, ``eval_portion``). Uses
    NON-default values on both fields — a hardcoded default anywhere
    in the read path would silently pass a default-values-only test.

    Additionally seeds the run_config via a dict constructed with the
    EXACT literal keys the tuner writes (mirroring the tuner block at
    ``ml_hyperparameter_tune_agent.py`` around line 1969, checked
    2026-07-27), so a rename on either side breaks the test.
    """
    ws = str(tmp_path)

    # Manually write a run_config using the tuner's literal keys —
    # bypasses `_write_iter`'s parameter names so a rename can't hide.
    _write_iter(
        ws,
        1,
        [_record("f1", file_vector=[3.0, None] + [None] * 18, logical_round=1, waiver=False)],
        include_run_config=False,  # we write the config manually below
    )
    model_dir = os.path.join(ws, "iter_001", "iteration_001", "punet")
    tuner_run_config = {
        "run_name": "iter_001",
        # These two keys are the write-side contract under audit.
        "formal_strategy": "anchors",  # non-default (production default is "snapshot")
        "formal_eval_portion": 0.42,  # non-default (production default is 1.0)
    }
    with open(os.path.join(model_dir, "run_config_iter_001.json"), "w") as f:
        json.dump(tuner_run_config, f)

    table = build_table(ws)
    formal_rows = [r for r in table["rows"] if r["phase"] == "formal"]
    assert formal_rows, "expected at least one formal row"
    for row in formal_rows:
        assert row["eval_strategy"] == "anchors", (
            f'read-side naming mismatch: tuner wrote formal_strategy="anchors" '
            f"but reader produced eval_strategy={row['eval_strategy']!r}"
        )
        assert row["eval_portion"] == 0.42, (
            f"read-side naming mismatch: tuner wrote formal_eval_portion=0.42 "
            f"but reader produced eval_portion={row['eval_portion']!r}"
        )


# ---------------------------------------------------------------------------
# Additional coverage — A6 (incremental trigger), A7 (untouched files),
# operator-required recovery test
# ---------------------------------------------------------------------------


def test_no_records_and_missing_iters_skipped(tmp_path):
    """A6: only completed iterations contribute; no_records skipped."""
    ws = str(tmp_path)
    _write_iter(ws, 1, [], manifest_status="no_records")
    _write_iter(
        ws,
        2,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    assert table["iterations_included"] == [2]


def test_untouched_files_have_no_rows(tmp_path):
    """A7: file_index that never received a usable score gets no row;
    files_covered reflects the actual sorted set."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "a",
                file_vector=[None] * 5 + [3.5] + [None] * 14,  # only file 5 has a score
                logical_round=1,
            )
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    assert table["files_covered"] == [5]
    assert all(r["file_index"] == 5 for r in table["rows"])


def test_trial_row_uses_record_sampling_provenance(tmp_path):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [
            _record(
                "t1",
                file_vector=[2.0, None] + [None] * 18,
                is_trial=True,
                logical_round=1,
                eval_strategy="anchors",
                eval_portion=0.05,
            )
        ],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    trial_row = next(r for r in table["rows"] if r["phase"] == "trial")
    assert trial_row["eval_strategy"] == "anchors"
    assert trial_row["eval_portion"] == 0.05


def test_failed_incremental_recoverable_by_rebuild(tmp_path, monkeypatch):
    """OPERATOR REQUIREMENT: a failed or missing incremental update
    must be fully recoverable via the rebuild path from committed
    artifacts alone — no dependence on prior table state."""
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    _write_iter(
        ws,
        2,
        [_record("b", file_vector=[None, 1.5] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )

    # Simulate a completely missing incremental table (chain-runner's
    # best-effort WARN'd out on iter 2 — no per_file_best.json exists).
    table_path = Path(ws) / TABLE_BASENAME
    assert not table_path.exists()

    # Rebuild from committed artifacts recovers the FULL state without
    # any prior table.
    rebuilt_path = write_table(ws)
    assert rebuilt_path.exists()
    rebuilt = build_table(ws)
    assert set(rebuilt["iterations_included"]) == {1, 2}
    assert set(rebuilt["files_covered"]) == {0, 1}


# ---------------------------------------------------------------------------
# Header stability + schema fingerprint
# ---------------------------------------------------------------------------


def test_header_shape_and_schema_version(tmp_path):
    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[1.0, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    table = build_table(ws)
    required = {
        "schema_version",
        "metric_id",
        "score_transform",
        "log_base",
        "iterations_included",
        "files_covered",
        "skipped_nonpositive_count",
        "unverified_sources",
        "validity_semantics",
        "rows",
    }
    assert required.issubset(table.keys())
    # Fields explicitly EXCLUDED from the canonical domain (A8).
    assert "generated_by" not in table
    assert "generated_at" not in table
    assert table["schema_version"] == SCHEMA_VERSION
    assert table["log_base"] == LOG_BASE


class TestTheHeaderNamesTheRunsOwnMetric:
    """The header's ``metric_id`` is RESOLVED, never a literal.

    The defect this class exists to catch, observed in a live composed
    California-housing run (metric ``mae``, direction ``lower``, no log
    transform): ``_assemble`` emitted ``"metric_id": TIDMAD_METRIC_ID`` as a
    hardcoded literal, so every task's table claimed TIDMAD's metric identity.
    The module already resolved the real identity a few lines earlier — to
    order the rows — and discarded it. Two authorities, one file.

    If this class were deleted, nothing would catch a regression to the
    literal: every other assertion in this suite builds a TIDMAD workspace,
    where the literal and the resolved value coincide. That coincidence is
    exactly why the defect survived to production.

    The distinction is drawn from the DECLARED binding the artifacts carry,
    never from a task name.
    """

    _MAE = ("mae", "lower")

    def _mae_workspace(self, tmp_path) -> str:
        ws = str(tmp_path / "composed_ws")
        _write_iter(
            ws,
            1,
            [
                _record(
                    "h1",
                    file_vector=[0.5, 1.5] + [None] * 18,
                    logical_round=1,
                    metric_identity=self._MAE,
                )
            ],
            formal_eval_portion=1.0,
            formal_strategy="snapshot",
        )
        return ws

    def test_production_writer_stamps_the_declared_metric_not_tidmads(self, tmp_path):
        """Drives ``write_table`` — the function
        ``sdsc_submission_scripts/run_one_iteration.py`` calls after every
        committed iteration — and reads the bytes back off disk, so the
        assertion covers the artifact an operator actually finds in the
        workspace, not an in-memory dict.

        Fails with ``metric_id == 'tidmad_denoising_score'`` if the header
        reverts to the literal.
        """
        ws = self._mae_workspace(tmp_path)
        path = write_table(ws)
        written = json.loads(Path(path).read_text(encoding="utf-8"))
        assert written["metric_id"] == "mae"
        assert written["metric_id"] != TIDMAD_METRIC_ID

    def test_the_declared_direction_also_orders_the_rows(self, tmp_path):
        """The header and the ranking come from ONE resolution, so a
        ``lower``-is-better run must both SAY ``mae`` and RANK by ``mae``.
        Hardcoded expectation: of 0.5 and 1.5 the better MAE is 0.5."""
        ws = self._mae_workspace(tmp_path)
        table = build_table(ws)
        assert table["metric_id"] == "mae"
        raw = [r for r in table["rows"] if r["validity"] == "raw"]
        assert {r["file_index"]: r["best_linear"] for r in raw} == {0: 0.5, 1: 1.5}

    def test_an_undeclared_workspace_reports_a_named_absence(self, tmp_path):
        """No record declares an identity => ``null``. A metric name here
        would be invented, and inventing TIDMAD's is the original defect."""
        ws = str(tmp_path / "silent_ws")
        _write_iter(
            ws,
            1,
            [
                _record(
                    "s1",
                    file_vector=[1.0, 2.0] + [None] * 18,
                    logical_round=1,
                    status="skipped_time_risk",
                )
            ],
            formal_eval_portion=1.0,
            formal_strategy="snapshot",
        )
        table = build_table(ws)
        assert table["metric_id"] is None
        assert table["rows"] == []

    def test_a_tidmad_workspace_header_is_unchanged(self, tmp_path):
        """The byte-identity guarantee, at header granularity: resolution must
        reproduce TIDMAD's frozen header values exactly. Hardcoded, not read
        back from the module."""
        ws = str(tmp_path / "tidmad_ws")
        _write_iter(
            ws,
            1,
            [_record("t1", file_vector=[1.0, 2.0] + [None] * 18, logical_round=1)],
            formal_eval_portion=1.0,
            formal_strategy="snapshot",
        )
        table = build_table(ws)
        assert table["metric_id"] == "tidmad_denoising_score"
        assert table["score_transform"] == "log"
        assert table["log_base"] == 5.27

    def test_the_row_transform_is_the_modules_own_and_does_not_track_the_metric(self, tmp_path):
        """``score_transform``/``log_base`` document ``_log``, the transform
        this module applies to every row's ``best_log_score`` — NOT the run
        metric's declared transform (``mae`` declares none).

        Pinned deliberately: making these fields follow the metric's
        declaration would need a second, spec-granularity reconciliation over
        a different pool of sources, and would make the header contradict the
        column it documents — the rows below really are log_5.27 values.
        Hardcoded expectation: log_5.27(0.5) = -0.4171...
        """
        ws = self._mae_workspace(tmp_path)
        table = build_table(ws)
        assert table["score_transform"] == "log"
        assert table["log_base"] == 5.27
        row = next(r for r in table["rows"] if r["file_index"] == 0 and r["validity"] == "raw")
        assert row["best_log_score"] == pytest.approx(math.log(0.5) / math.log(5.27))


class TestTheProducerSerializationBoundary:
    """The bytes production writes, read by the consumer that must read them.

    The fixture above writes `output.model_dump_json()`. Production
    (`nodes/ml_hyperparameter_tune_agent/records.py`, `finalize_run_output`)
    writes `publish_json_atomically(output_path,
    coerce_nonfinite_to_none(output.model_dump()), indent=4)` — the
    `json.dump(..., indent=4)` bytes, published atomically since S2 / U5 —
    and its own comment says why it coerces: `model_dump_json` emits
    non-standard `-Infinity` tokens that break the dashboard's `JSON.parse`.

    So the whole `-inf` no-signal path through `build_table` and the
    `run_output_sha256` byte check has only ever been exercised against a
    shape production never produces. Field drift was already caught -- the
    fixture routes through `HyperparamTuningOutput`, and
    `test_producer_to_artifact_transport.py` covers field reachability. The
    SERIALIZATION FORM was not.

    Scope, stated because it bounds the claim: driving `finalize_run_output`
    end to end needs a full `RunBindings` and `RunExitSnapshot`, which is out
    of proportion for a serialization contract. Instead the behavioural half
    calls the REAL `coerce_nonfinite_to_none` and writes with the same
    `json.dump` call production uses, and `test_production_writes_through_the_coercion`
    binds that to production so the two cannot drift apart silently. Without
    that second test this file would be asserting its own conventions again,
    which is the defect it exists to fix.
    """

    @staticmethod
    def _write_as_production_does(path: str, output: HyperparamTuningOutput) -> None:
        from core.durable_io import publish_json_atomically
        from execute_tools.scoring_utils import coerce_nonfinite_to_none

        publish_json_atomically(path, coerce_nonfinite_to_none(output.model_dump()), indent=4)

    def test_production_writes_through_the_coercion(self):
        """Reachability. If `records.py` stops coercing, coerces AFTER
        serialising, or goes back to a truncating `open(path, "w")` write,
        the round-trip below stops describing production."""
        src = (REPO_ROOT / "nodes" / "ml_hyperparameter_tune_agent" / "records.py").read_text(
            encoding="utf-8"
        )
        assert "coerce_nonfinite_to_none(agent_output.model_dump())" in src
        assert "publish_json_atomically(output_path, safe_output, indent=4)" in src
        assert "json.dump(safe_output" not in src
        assert "f.write(agent_output.model_dump_json())" not in src

    def test_a_no_signal_score_survives_as_null_not_as_a_nonstandard_token(self, tmp_path):
        """`-inf` is the no-signal sentinel. It must reach disk as JSON `null`:
        `-Infinity` is not RFC 8259 and the dashboard's `JSON.parse` rejects
        it, which is a broken dashboard rather than a failed test."""
        output = HyperparamTuningOutput(
            run_name="ser",
            model_type="punet",
            file_index=6,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-08-17 00:00:00",
            finished_at="2026-08-17 00:00:01",
            best_valid_formal_denoising_score=float("-inf"),
        )
        path = str(tmp_path / "run_output_ser.json")
        self._write_as_production_does(path, output)

        text = Path(path).read_text(encoding="utf-8")
        for token in ("-Infinity", "Infinity", "NaN"):
            assert token not in text, f"{token!r} reached disk; JSON.parse will reject it"

        # A strict RFC parser, not Python's permissive default -- which
        # accepts `-Infinity` and would hide the whole defect.
        def _refuse(value):
            raise AssertionError(f"non-standard JSON constant on disk: {value}")

        reloaded = json.loads(text, parse_constant=_refuse)
        assert reloaded["best_valid_formal_denoising_score"] is None

    def test_the_consumer_reads_the_producers_bytes(self, tmp_path):
        """The join. `build_table` must treat the coerced `null` as no signal,
        not as a score."""
        workspace = str(tmp_path / "ws")
        iter_dir = os.path.join(workspace, "iter_001")
        model_dir = os.path.join(iter_dir, "iteration_001", "punet")
        os.makedirs(model_dir, exist_ok=True)
        output = HyperparamTuningOutput(
            run_name="iter_001",
            model_type="punet",
            file_index=6,
            status="completed",
            completed_rounds=0,
            total_attempts=0,
            all_records=[],
            started_at="2026-08-17 00:00:00",
            finished_at="2026-08-17 00:00:01",
            best_valid_formal_denoising_score=float("-inf"),
        )
        output_path = os.path.join(model_dir, "run_output_iter_001.json")
        self._write_as_production_does(output_path, output)
        with open(os.path.join(iter_dir, "manifest.json"), "w") as f:
            json.dump(
                {
                    "status": "completed",
                    "iteration_dir": iter_dir,
                    "output_path": output_path,
                    "model_name": "punet",
                },
                f,
            )

        table = build_table(workspace)
        assert table is not None


# ---------------------------------------------------------------------------
# S2 / U5 (#258) — the rebuild applies the SAME manifest predicate as resume
# ---------------------------------------------------------------------------


def test_an_edited_manifest_field_fails_the_rebuild_closed(tmp_path):
    """Undetected before S2: only the artifact bytes were hashed, so a
    hand-edited manifest still fed rows into the table. Fails if the
    table is built (or the iteration silently skipped) instead of raising."""
    from core.iteration_manifest import publish_iteration_manifest

    ws = str(tmp_path)
    _write_iter(
        ws,
        1,
        [_record("a", file_vector=[0.5, None] + [None] * 18, logical_round=1)],
        formal_eval_portion=1.0,
        formal_strategy="snapshot",
    )
    iter_dir = os.path.join(ws, "iter_001")
    manifest_path = os.path.join(iter_dir, "manifest.json")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    os.remove(manifest_path)
    publish_iteration_manifest(iter_dir, manifest)  # now carries manifest_sha256
    assert build_table(ws)["rows"], "anti-vacuity: the untampered fixture must yield rows"

    with open(manifest_path, encoding="utf-8") as f:
        published = json.load(f)
    published["model_name"] = "tampered"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(published, f)

    with pytest.raises(ReplayIntegrityError) as exc:
        build_table(ws)
    assert "REPLAY-INTEGRITY" in str(exc.value)
    assert "manifest changed after publication" in str(exc.value)
    assert manifest_path in str(exc.value)
