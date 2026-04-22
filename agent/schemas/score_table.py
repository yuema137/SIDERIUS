# agent/schemas/score_table.py
"""
Pydantic data contract for the per-file score comparison table — the enriched
replacement for the bare `file_vector` surfaced to every agent in the graph.

Each ``ScoreComparisonTable`` carries both machine-consumable rows (for
interpreter-side analysis) and a pre-rendered markdown string (``rendered_
markdown``) that the tuner / interpreter / proposer prompts drop in verbatim.
This keeps rendering single-sourced — see Decision 3 in
``docs/aggregated_score_table_awareness.md``.

Aggregate scalars are always **subset-scoped**: when a trial-mode run scored
only a subset of the 20 validation files, the raw / ground-truth / model
log scalars are re-computed over that same subset using the per-file linear
sums in ``ReferenceScores``. See Decision 14 for the full contract.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Per-file row
# ---------------------------------------------------------------------------

class PerFileRow(BaseModel):
    """One row of the per-file comparison table.

    Reference columns (``raw_baseline``, ``ground_truth``) are always present
    because they come from the committed on-disk reference data. Model-side
    columns (``model``, ``gain_vs_raw``, ``headroom_vs_gt``) are ``None`` when
    the file was not in the sampled set for this run.
    """

    model_config = ConfigDict(extra="forbid")

    file_index: int = Field(
        ...,
        ge=0,
        le=19,
        description="Validation file index (0..19).",
    )
    raw_baseline: Optional[float] = Field(
        ...,
        description="log_{5.27} per-file score on raw CH1 under global s_max. "
                    "Always set from the committed on-disk reference; Optional "
                    "only to tolerate a missing reference JSON at load time.",
    )
    ground_truth: Optional[float] = Field(
        ...,
        description="log_{5.27} per-file score under the perfect-denoiser "
                    "substitution (CH2 → CH1) at global s_max. Same caveat "
                    "as raw_baseline.",
    )
    model: Optional[float] = Field(
        ...,
        description="log_{5.27} per-file score from this run. None when the "
                    "file was outside the sampled set (trial mode).",
    )
    gain_vs_raw: Optional[float] = Field(
        ...,
        description="model - raw_baseline. None if either input is None.",
    )
    headroom_vs_gt: Optional[float] = Field(
        ...,
        description="ground_truth - model. None if either input is None.",
    )


# ---------------------------------------------------------------------------
# Aggregate scalars — subset-scoped (Decision 14)
# ---------------------------------------------------------------------------

class AggregateScalars(BaseModel):
    """Grand-mean log scalars over the same subset of files the model scored.

    All three log scalars (raw_baseline_scalar, ground_truth_scalar,
    model_scalar) are computed over the SAME set of file indices — the ones
    where the model has a value. This keeps the three numbers on a fair
    ruler under trial-mode sampling; see Decision 14.
    """

    model_config = ConfigDict(extra="forbid")

    raw_baseline_scalar: float = Field(
        ...,
        description="Grand-mean log scalar over sampled indices, computed via "
                    "log_{5.27}(round(Σ raw_linear_sum / Σ raw_n, 2) + 1e-10).",
    )
    ground_truth_scalar: float = Field(
        ...,
        description="Grand-mean log scalar over sampled indices, computed via "
                    "log_{5.27}(round(Σ gt_linear_sum / Σ gt_n, 2) + 1e-10).",
    )
    model_scalar: float = Field(
        ...,
        description="final_scalar from score_vector() on denoised CH1. "
                    "Already subset-scoped by construction.",
    )
    percent_of_ceiling_log: float = Field(
        ...,
        description="model_scalar / ground_truth_scalar. Ratio of log "
                    "scalars — NOT a ratio of linear grand means.",
    )
    num_sampled_files: int = Field(
        ...,
        ge=1,
        le=20,
        description="|sampled_indices|. 20 for a formal run, <20 for trial.",
    )


# ---------------------------------------------------------------------------
# Comparison table
# ---------------------------------------------------------------------------

class ScoreComparisonTable(BaseModel):
    """Full per-file comparison table + aggregated scalars + rendered markdown.

    ``rendered_markdown`` is the exact string the LLM sees in prompts — a
    single source of truth built once at construction time and carried
    through the graph untouched.
    """

    model_config = ConfigDict(extra="forbid")

    rows: List[PerFileRow] = Field(
        ...,
        min_length=20,
        max_length=20,
        description="Always exactly 20 rows (one per validation file). "
                    "Unsampled files carry model/gain/headroom as None.",
    )
    aggregate: AggregateScalars = Field(
        ...,
        description="Subset-scoped grand-mean scalars. See Decision 14.",
    )
    s_max_global: float = Field(
        ...,
        description="Global s_max from segment_anchors.json — identifies the "
                    "ruler all three columns live on.",
    )
    reference_source: str = Field(
        ...,
        description="Human-readable pointer to the reference data used for "
                    "raw_baseline / ground_truth columns (e.g. "
                    "'reference_data/raw_and_ground_score.md').",
    )
    rendered_markdown: str = Field(
        ...,
        description="Pre-rendered prompt-ready markdown (per §6 of the "
                    "design doc). Substituted verbatim at the "
                    "{SCORE_COMPARISON_TABLE} token in agent prompts.",
    )
