"""
SQUID-specific health checks for denoising score outputs.

These checks live in ``execute_tools`` (the task-specific layer) and are
called from :func:`execute_tools.scoring_utils.score_vector` when a
reference vector is available. The agent does not import or depend on
this module — it only consumes the ``(is_degenerate, failure_reason)``
tuple returned through the scoring contract.

Why this exists
---------------
On 2026-04-26, V7 chain runs produced formal-round outputs whose mean
PSD magnitude was ~0.005 while their trial-round winners' was ~10,000 —
a 2,000,000× collapse. The model had been trained on an untested
``focal_cw`` loss for 10× more steps and degenerated to near-zero PSD
output. The denoising score is computed in log space, so this collapse
produced large negative numbers (~-3.16) that pushed the LLM planner
toward genuinely worse configurations in subsequent rounds.

What this module does
---------------------
Compares the magnitude of the current ``file_vector`` against a reference
``file_vector`` (typically the highest-scoring trial-mode success) and
flags degenerate collapse when the ratio falls below a configurable
threshold (default 1%).

What this module does NOT do
----------------------------
* It does not know about ``denoising_score`` semantics, formal vs trial
  mode, the agent's ``status`` taxonomy, or the planner's memory format.
* It does not decide what penalty to apply on collapse.
* It does not pick which reference to use — the caller is responsible
  for selecting an appropriate reference (e.g. via the agent's generic
  ``_best_trial_winner`` predicate).

Returning ``(False, None)`` for indeterminate inputs is intentional: a
missing reference or a malformed file_vector means we have no grounds
to flag degeneracy, and silently passing through is the only safe
behavior at the task-specific layer. The agent's generic handling layer
decides what to do with the bool.
"""

from __future__ import annotations


def check_amplitude_collapse(
    file_vector: list[float | None] | None,
    reference_file_vector: list[float | None] | None,
    threshold_ratio: float = 0.01,
) -> tuple[bool, str | None]:
    """Detect mode collapse via PSD output magnitude ratio.

    Compares ``mean(|file_vector|)`` against
    ``mean(|reference_file_vector|)``. If the ratio is strictly less than
    ``threshold_ratio``, the current output is declared degenerate.

    Args:
        file_vector: Per-file denoised PSD output magnitudes for the
            current scoring run. ``None`` entries (files not in the
            sample set) are skipped before averaging.
        reference_file_vector: Per-file PSD output magnitudes from a
            reference run — typically the highest-scoring trial-mode
            success in the same iteration. ``None`` entries are skipped.
        threshold_ratio: Collapse boundary as a fraction of the
            reference magnitude. Default 0.01 (1%) catches the
            explore_novel_v7 collapse pattern (10000 → 0.005). Strict
            ``<`` comparison — exactly 1% does NOT trip the check.

    Returns:
        ``(is_degenerate, failure_reason)``. The reason string includes
        the actual vs reference magnitudes plus the ratio so the LLM
        planner has concrete numbers to reason about. ``(False, None)``
        when the check is indeterminate (missing reference, empty
        vectors, non-positive reference magnitude).

    Examples:
        >>> # Collapse detected (V7 magnitudes: 0.005 vs 8.6)
        >>> check_amplitude_collapse([0.005], [8.6])
        (True, "...")
        >>> # Healthy output passes through
        >>> check_amplitude_collapse([7.2], [8.6])
        (False, None)
        >>> # No reference -> indeterminate -> safe pass
        >>> check_amplitude_collapse([0.005], None)
        (False, None)
    """
    if not file_vector:
        return (False, None)
    if not reference_file_vector:
        return (False, None)

    current_vals = [abs(x) for x in file_vector if x is not None]
    reference_vals = [abs(x) for x in reference_file_vector if x is not None]
    if not current_vals or not reference_vals:
        return (False, None)

    current_mag = sum(current_vals) / len(current_vals)
    reference_mag = sum(reference_vals) / len(reference_vals)
    if reference_mag <= 0:
        return (False, None)

    ratio = current_mag / reference_mag
    if ratio < threshold_ratio:
        reason = (
            f"amplitude_collapse: mean|file_vector|={current_mag:.4g} vs "
            f"reference={reference_mag:.4g} (ratio={ratio * 100:.3f}%, "
            f"threshold={threshold_ratio * 100:.0f}%)"
        )
        return (True, reason)
    return (False, None)
