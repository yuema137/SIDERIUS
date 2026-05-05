"""Unit tests for ``tools/build_token_baseline_report.py``.

Covers the §8 Commit 5 (Rev 6) pre-commit checklist:

- USD precision (4 decimals)
- Happy-Path-Cost vs Recovery-Cost segmentation
- Linear-regression growth slope robust to missing iterations
- ``[BLOAT_ALERT]`` and ``[CONTEXT_EXPLOSION]`` alert thresholds
- Pre-flight lint refuses to publish from a corrupted JSONL
- Verdict line written at the top of the top-3 bloat report
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from agent.schemas.telemetry import TokenUsageRow  # noqa: E402
from tools.build_token_baseline_report import (  # noqa: E402
    DEFAULT_RATE_COMPLETION,
    DEFAULT_RATE_PROMPT,
    BloatAlert,
    CallStats,
    aggregate_by_iter,
    aggregate_component_growth,
    detect_alerts,
    is_happy_path,
    linear_slope,
    main,
    per_label_slopes,
    render_baseline_report,
    render_top3_bloat_report,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic row factory
# ---------------------------------------------------------------------------

_RUN_ID = "test-run-20260505-1"


def _make_row(
    *,
    iter_: int,
    label: str = "proposer.proposing",
    prompt: int = 100,
    completion: int = 10,
    chars_total: int = 200,
    attempt: int = 0,
    status: str = "ok",
    components: Dict[str, int] | None = None,
    run_id: str = _RUN_ID,
) -> TokenUsageRow:
    return TokenUsageRow.model_validate({
        "ts": f"2026-05-05T00:00:{iter_:02d}Z",
        "run_id": run_id,
        "run_name": "test",
        "iter": iter_,
        "label": label,
        "model": "gpt-4o-mini",
        "provider": "openai",
        "tokens": {"prompt": prompt, "completion": completion, "total": prompt + completion},
        "chars": {"system": 0, "user": chars_total, "total": chars_total},
        "components": components or {},
        "extra": {"attempt": attempt, "status": status},
    })


def _write_jsonl(path: Path, rows: List[TokenUsageRow]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r.model_dump()) + "\n")


# ---------------------------------------------------------------------------
# 1. USD precision
# ---------------------------------------------------------------------------

def test_usd_precision_to_four_decimals():
    """Spec: 100K prompt + 10K completion at default rates = $1.30 exactly."""
    cs = CallStats()
    cs.add_row(_make_row(iter_=1, prompt=100_000, completion=10_000))
    usd = cs.usd(DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION)
    # 100_000 * 10/1e6 + 10_000 * 30/1e6 = 1.0 + 0.3 = 1.3
    assert round(usd, 4) == 1.3000


def test_usd_zero_when_no_tokens():
    cs = CallStats()
    assert cs.usd(DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION) == 0.0


def test_usd_overrides_propagate():
    """Custom rates flow into per-row USD."""
    cs = CallStats()
    cs.add_row(_make_row(iter_=1, prompt=1_000_000, completion=0))
    assert round(cs.usd(rate_prompt=5.0, rate_completion=15.0), 4) == 5.0


# ---------------------------------------------------------------------------
# 2. Happy / Recovery segmentation
# ---------------------------------------------------------------------------

def test_happy_path_classifier():
    happy = _make_row(iter_=1, attempt=0, status="ok")
    retry = _make_row(iter_=1, attempt=1, status="ok")
    error = _make_row(iter_=1, attempt=0, status="error")
    assert is_happy_path(happy) is True
    assert is_happy_path(retry) is False
    assert is_happy_path(error) is False


def test_segmentation_3_row_jsonl():
    """Spec: hand-craft 3-row JSONL with 1 happy + 2 retry. Assert
    Happy-Path-Cost = first row's tokens; Recovery-Cost = sum of others."""
    rows = [
        _make_row(iter_=1, prompt=1000, completion=100, attempt=0, status="ok"),
        _make_row(iter_=1, prompt=2000, completion=200, attempt=1, status="error"),
        _make_row(iter_=1, prompt=3000, completion=300, attempt=2, status="ok"),
    ]
    aggs = aggregate_by_iter(rows)
    a = aggs[1]
    assert a.happy.prompt_tok == 1000
    assert a.happy.completion_tok == 100
    assert a.recovery.prompt_tok == 5000  # 2000 + 3000
    assert a.recovery.completion_tok == 500  # 200 + 300
    # USD math
    happy_usd = a.happy.usd(DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION)
    recov_usd = a.recovery.usd(DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION)
    assert round(happy_usd, 6) == round(1000 * 10 / 1e6 + 100 * 30 / 1e6, 6)
    assert round(recov_usd, 6) == round(5000 * 10 / 1e6 + 500 * 30 / 1e6, 6)


# ---------------------------------------------------------------------------
# 3. Growth slope — linear regression robust to missing iters
# ---------------------------------------------------------------------------

def test_linear_slope_perfect_line():
    """y = 2x + 1 fit to integer x — slope=2, R²=1."""
    pts = [(1, 3.0), (2, 5.0), (3, 7.0), (4, 9.0), (5, 11.0)]
    slope, r2 = linear_slope(pts)
    assert round(slope, 6) == 2.0
    assert round(r2, 6) == 1.0


def test_linear_slope_handles_missing_iters():
    """Crashed iter 2 and iter 4 → fit on (1,3),(3,7),(5,11). Slope=2, R²=1."""
    pts = [(1, 3.0), (3, 7.0), (5, 11.0)]
    slope, r2 = linear_slope(pts)
    assert round(slope, 6) == 2.0
    assert round(r2, 6) == 1.0


def test_linear_slope_flat_returns_zero():
    """Constant y → slope=0, R²=0 (undefined → 0 by convention)."""
    pts = [(1, 5.0), (2, 5.0), (3, 5.0)]
    slope, r2 = linear_slope(pts)
    assert slope == 0.0
    assert r2 == 0.0


def test_linear_slope_single_point_safe():
    """<2 points → (0, 0) — no exception."""
    assert linear_slope([(1, 5.0)]) == (0.0, 0.0)
    assert linear_slope([]) == (0.0, 0.0)


def test_per_label_slopes_skips_missing_iters():
    """Label observed only on iter 1, 3, 5 must still produce a valid slope."""
    rows = [
        _make_row(iter_=1, label="proposer.proposing", prompt=1000, completion=100),
        _make_row(iter_=3, label="proposer.proposing", prompt=3000, completion=300),
        _make_row(iter_=5, label="proposer.proposing", prompt=5000, completion=500),
        _make_row(iter_=2, label="other.label", prompt=100, completion=10),
        _make_row(iter_=4, label="other.label", prompt=100, completion=10),
    ]
    aggs = aggregate_by_iter(rows)
    slopes = per_label_slopes(aggs, DEFAULT_RATE_PROMPT, DEFAULT_RATE_COMPLETION)
    s = slopes["proposer.proposing"]
    # tokens go 1100, 3300, 5500 over iters 1,3,5 → slope = 1100 tok/iter
    assert s["n_points"] == 3
    assert round(s["tok_slope"], 2) == 1100.0
    assert round(s["tok_r2"], 4) == 1.0


# ---------------------------------------------------------------------------
# 4. Alerts
# ---------------------------------------------------------------------------

def test_bloat_alert_fires_above_threshold():
    """1 iter whose total cost computes to ~$2.00 → [BLOAT_ALERT] fires."""
    # 200_000 prompt + 0 completion = 200_000 * 10 / 1e6 = $2.00
    rows = [_make_row(iter_=1, prompt=200_000, completion=0)]
    aggs = aggregate_by_iter(rows)
    bloats, _ = detect_alerts(
        rows, aggs,
        rate_prompt=DEFAULT_RATE_PROMPT,
        rate_completion=DEFAULT_RATE_COMPLETION,
        bloat_usd_threshold=1.50,
        context_prompt_threshold=50_000,
    )
    assert len(bloats) == 1
    assert bloats[0].iter == 1
    assert round(bloats[0].usd, 4) == 2.0000


def test_bloat_alert_silent_below_threshold():
    """1 iter at $1.20 → no [BLOAT_ALERT]."""
    # 120_000 * 10/1e6 = $1.20
    rows = [_make_row(iter_=1, prompt=120_000, completion=0)]
    aggs = aggregate_by_iter(rows)
    bloats, _ = detect_alerts(
        rows, aggs,
        rate_prompt=DEFAULT_RATE_PROMPT,
        rate_completion=DEFAULT_RATE_COMPLETION,
        bloat_usd_threshold=1.50,
        context_prompt_threshold=50_000,
    )
    assert bloats == []


def test_context_explosion_alert_fires_above_threshold():
    """Single call with prompt=60_000 → [CONTEXT_EXPLOSION] for that row."""
    rows = [_make_row(iter_=1, prompt=60_000, completion=100, label="proposer.proposing")]
    aggs = aggregate_by_iter(rows)
    _, explosions = detect_alerts(
        rows, aggs,
        rate_prompt=DEFAULT_RATE_PROMPT,
        rate_completion=DEFAULT_RATE_COMPLETION,
        bloat_usd_threshold=1.50,
        context_prompt_threshold=50_000,
    )
    assert len(explosions) == 1
    assert explosions[0].prompt_tok == 60_000
    assert explosions[0].label == "proposer.proposing"
    assert explosions[0].iter == 1


def test_context_explosion_silent_at_threshold():
    """Strict-> threshold: prompt=50_000 (= threshold) does not fire."""
    rows = [_make_row(iter_=1, prompt=50_000, completion=100)]
    aggs = aggregate_by_iter(rows)
    _, explosions = detect_alerts(
        rows, aggs,
        rate_prompt=DEFAULT_RATE_PROMPT,
        rate_completion=DEFAULT_RATE_COMPLETION,
        bloat_usd_threshold=1.50,
        context_prompt_threshold=50_000,
    )
    assert explosions == []


# ---------------------------------------------------------------------------
# 5. Verdict + top-3 rendering
# ---------------------------------------------------------------------------

def test_verdict_written_at_top_of_top3_report():
    """Spec: §1.9.2 verdict is written explicitly at the top of top3 report."""
    rows = [
        _make_row(
            iter_=1, label="proposer.proposing",
            components={"candidates_markdown": 1000, "vocab_block": 500},
        ),
        _make_row(
            iter_=2, label="proposer.proposing",
            components={"candidates_markdown": 5000, "vocab_block": 600},
        ),
    ]
    aggs = aggregate_by_iter(rows)
    growth = aggregate_component_growth(aggs)
    from tools.build_token_baseline_report import compute_verdict
    verdict = compute_verdict(growth)
    body = render_top3_bloat_report(
        aggs, growth, verdict,
        workspace=Path("/tmp/fake"), run_id=_RUN_ID,
    )
    # Verdict line must appear in the first ~5 lines
    head = "\n".join(body.splitlines()[:8])
    assert "Verdict" in head
    assert verdict in head


# ---------------------------------------------------------------------------
# 6. End-to-end positive (synthetic happy + recovery + components)
# ---------------------------------------------------------------------------

def test_end_to_end_positive_run(tmp_path: Path):
    """Tool runs cleanly on a small synthetic workspace and writes both
    reports. Validates the full pipeline including pre-flight lint."""
    ws = tmp_path / "ws"
    ws.mkdir()
    rows: List[TokenUsageRow] = []
    for it in (1, 2, 3):
        rows.append(_make_row(
            iter_=it, label="proposer.proposing",
            prompt=10_000 * it, completion=1_000 * it,
            components={"candidates_markdown": 800 * it, "vocab_block": 200},
        ))
        rows.append(_make_row(
            iter_=it, label="interpretation.synthesis",
            prompt=5_000 * it, completion=500 * it,
        ))
    _write_jsonl(ws / "token_usage.jsonl", rows)
    out_dir = tmp_path / "reports"
    rc = main([
        "--workspace", str(ws),
        "--output-dir", str(out_dir),
    ])
    assert rc == 0
    baseline = (out_dir / "v12_token_baseline.md").read_text()
    top3 = (out_dir / "v12_top3_bloat.md").read_text()
    assert "## 1. Per-iteration totals" in baseline
    assert "Verdict" in top3
    # All 3 iters present in baseline
    for it in (1, 2, 3):
        assert f"| {it} |" in baseline


# ---------------------------------------------------------------------------
# 7. Negative — corrupted JSONL is rejected
# ---------------------------------------------------------------------------

def test_corrupted_jsonl_blocks_publication(tmp_path: Path):
    """Spec: corrupted log → 'AUDIT LOG CORRUPTION DETECTED' on stderr,
    exit nonzero. We never publish numbers from a corrupted log."""
    ws = tmp_path / "ws"
    ws.mkdir()
    jsonl = ws / "token_usage.jsonl"
    # Mix of valid row + a malformed JSON line — the linter must flag it
    valid = _make_row(iter_=1).model_dump()
    with jsonl.open("w") as f:
        f.write(json.dumps(valid) + "\n")
        f.write("{this is not json\n")
    out_dir = tmp_path / "reports"
    proc = subprocess.run(
        [sys.executable,
         str(REPO_ROOT / "tools" / "build_token_baseline_report.py"),
         "--workspace", str(ws),
         "--output-dir", str(out_dir)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert proc.returncode != 0
    assert "AUDIT LOG CORRUPTION DETECTED" in proc.stderr
    # Reports must NOT have been written
    assert not (out_dir / "v12_token_baseline.md").exists()


def test_skip_lint_bypasses_corruption_block(tmp_path: Path):
    """``--skip-lint`` is a documented test-only escape hatch; verify it works."""
    ws = tmp_path / "ws"
    ws.mkdir()
    valid = _make_row(iter_=1).model_dump()
    with (ws / "token_usage.jsonl").open("w") as f:
        f.write(json.dumps(valid) + "\n")
    out_dir = tmp_path / "reports"
    rc = main([
        "--workspace", str(ws),
        "--output-dir", str(out_dir),
        "--skip-lint",
    ])
    assert rc == 0
    assert (out_dir / "v12_token_baseline.md").exists()
