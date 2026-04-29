"""Unit tests for execute_tools.squid_health_checks.check_amplitude_collapse."""

from execute_tools.squid_health_checks import check_amplitude_collapse


# ---------------------------------------------------------------------------
# 1. Happy paths — the v7 collapse pattern and normal output
# ---------------------------------------------------------------------------

def test_collapse_detected_at_explore_v7_magnitude():
    """The exact collapse magnitudes observed on 2026-04-26 in
    explore_novel_v7 — formal round mean|file_vector| ≈ 0.005, trial
    winner ≈ 8.6 (a 0.06% ratio, well below the 1% default)."""
    file_vec = [0.005] * 20
    ref_vec = [8.6] * 20
    is_degen, reason = check_amplitude_collapse(file_vec, ref_vec)
    assert is_degen is True
    assert reason is not None
    # Magnitudes must surface in the reason string for LLM reasoning.
    assert "0.005" in reason
    assert "8.6" in reason
    assert "amplitude_collapse" in reason


def test_normal_output_passes_through():
    """Healthy output (within an order of magnitude of the reference)
    must NOT trip the check."""
    file_vec = [7.2] * 20
    ref_vec = [8.6] * 20
    is_degen, reason = check_amplitude_collapse(file_vec, ref_vec)
    assert is_degen is False
    assert reason is None


# ---------------------------------------------------------------------------
# 2. Threshold semantics — strict <
# ---------------------------------------------------------------------------

def test_threshold_boundary_exactly_at_1pct_does_not_trip():
    """Strict ``<`` comparison: a ratio of exactly threshold_ratio is
    not a collapse. Operator-set thresholds get exact semantics."""
    # Reference of 100, current of 1 → ratio is exactly 1%
    is_degen, _ = check_amplitude_collapse([1.0], [100.0], threshold_ratio=0.01)
    assert is_degen is False


def test_threshold_just_below_trips():
    """Ratio strictly below threshold trips."""
    is_degen, reason = check_amplitude_collapse([0.99], [100.0], threshold_ratio=0.01)
    assert is_degen is True
    assert reason is not None


def test_custom_threshold_overrides_default():
    """A 5% threshold catches a 4%-of-reference output that the default
    (1%) would miss."""
    file_vec = [4.0]   # 4% of reference
    ref_vec = [100.0]
    # Default 1% — passes
    is_degen, _ = check_amplitude_collapse(file_vec, ref_vec)
    assert is_degen is False
    # Custom 5% — trips
    is_degen, reason = check_amplitude_collapse(
        file_vec, ref_vec, threshold_ratio=0.05,
    )
    assert is_degen is True
    assert "5%" in reason  # threshold echoed in the reason


# ---------------------------------------------------------------------------
# 3. Indeterminate inputs — fail safe to (False, None)
# ---------------------------------------------------------------------------

def test_no_reference_returns_false_safely():
    """Missing reference -> indeterminate -> safe pass-through."""
    is_degen, reason = check_amplitude_collapse([0.005], None)
    assert is_degen is False
    assert reason is None


def test_empty_reference_returns_false_safely():
    """Empty reference list -> indeterminate."""
    is_degen, reason = check_amplitude_collapse([0.005], [])
    assert is_degen is False
    assert reason is None


def test_no_file_vector_returns_false_safely():
    """Missing current file_vector -> indeterminate (different bug, not
    our concern)."""
    is_degen, reason = check_amplitude_collapse(None, [8.6])
    assert is_degen is False
    assert reason is None


def test_zero_reference_magnitude_returns_false_safely():
    """A zero-magnitude reference would be a divide-by-zero. The reference
    itself is degenerate — refuse to compare and return (False, None).
    The caller's reference selector should not have picked this winner."""
    is_degen, reason = check_amplitude_collapse([0.005], [0.0, 0.0])
    assert is_degen is False
    assert reason is None


def test_none_entries_in_vectors_are_skipped():
    """``score_vector`` returns ``None`` for files not in the sample set.
    These entries must be skipped before averaging — they are not
    'amplitude zero' values."""
    # Without skipping, mean would be artificially low and trip false
    # positive. With skipping, the active entries average to 7.2 (healthy).
    file_vec = [7.2, None, 7.2, None, 7.2]
    ref_vec = [8.6, 8.6, 8.6, 8.6, 8.6]
    is_degen, _ = check_amplitude_collapse(file_vec, ref_vec)
    assert is_degen is False


# ---------------------------------------------------------------------------
# 4. Failure-reason content — auditable by the operator + the LLM
# ---------------------------------------------------------------------------

def test_failure_reason_includes_actual_and_reference_magnitudes():
    """The failure_reason string must report both magnitudes so the
    operator can audit the call without re-deriving."""
    is_degen, reason = check_amplitude_collapse([0.123], [45.6])
    assert is_degen is True
    assert "0.123" in reason
    assert "45.6" in reason


def test_failure_reason_includes_ratio_and_threshold():
    """The ratio (in %) and the threshold (in %) must surface so the
    LLM understands how far off it was."""
    is_degen, reason = check_amplitude_collapse(
        [0.5], [100.0], threshold_ratio=0.01,
    )
    assert is_degen is True
    assert "0.500%" in reason or "0.5%" in reason  # ratio
    assert "1%" in reason                          # threshold
