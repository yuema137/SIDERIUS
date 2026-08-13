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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execute_tools.dataset_config import resolve_dataset_profile

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
        description=(
            "Validation file index. The upper bound is the declared topology's "
            "file count, checked against the resolved Dataset Profile rather "
            "than a fixed literal."
        ),
    )
    raw_baseline: float | None = Field(
        ...,
        description="log_{5.27} per-file score on raw CH1 under global s_max. "
        "Always set from the committed on-disk reference; Optional "
        "only to tolerate a missing reference JSON at load time.",
    )
    ground_truth: float | None = Field(
        ...,
        description="log_{5.27} per-file score under the perfect-denoiser "
        "substitution (CH2 → CH1) at global s_max. Same caveat "
        "as raw_baseline.",
    )
    model: float | None = Field(
        ...,
        description="log_{5.27} per-file score from this run. None when the "
        "file was outside the sampled set (trial mode).",
    )
    gain_vs_raw: float | None = Field(
        ...,
        description="model - raw_baseline. None if either input is None.",
    )
    headroom_vs_gt: float | None = Field(
        ...,
        ge=0.0,
        description="Remaining room to grow toward the ceiling — clipped at "
        "zero. Computed as max(ground_truth - model, 0). The "
        "raw difference can come out negative on dead-zone "
        "files (gt at floor, model slightly above floor due to "
        "noise output) or in rare numerical-overshoot cases, "
        "but 'negative headroom' is not a meaningful target — "
        "the field communicates one thing only: improvement "
        "potential. Dead-zone vs active-search-space "
        "partitioning is conveyed separately by the "
        "interpretation prompt's gt-at-floor signal. None if "
        "model is None.",
    )
    linear_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fractional contribution of this file's linear mean to "
        "the scalar's denominator over the sampled subset. Sums "
        "to ~1 across sampled rows. Context only — *not* the "
        "primary opportunity metric (use impact_score). None "
        "when the file was outside the sampled set.",
    )
    impact_score: float | None = Field(
        default=None,
        ge=0.0,
        description="Marginal log-scalar gain (log_5.27 units, same ruler "
        "as model_scalar) the agent would obtain by lifting "
        "this file's model_linear up to its gt_linear, holding "
        "the other sampled files at their current values. "
        "Clipped at 0 (saturated files contribute no remaining "
        "lever). Primary opportunity metric — rank by this "
        "descending to identify the next-iter lever. None when "
        "the file was outside the sampled set.",
    )

    @model_validator(mode="after")
    def _file_index_within_declared_topology(self) -> PerFileRow:
        """Reject an index the declared topology does not contain.

        This bound used to be the static ``le=NUM_FILES - 1`` evaluated when
        the class body ran, which pinned every task to TIDMAD's 20 files and
        made a different file count unrepresentable. The rule is unchanged;
        only its source moved to the resolved Dataset Profile.
        """
        num_files = resolve_dataset_profile().dataset.num_files
        if self.file_index >= num_files:
            raise ValueError(
                f"file_index={self.file_index} is outside the declared topology "
                f"(num_files={num_files}, valid 0..{num_files - 1})."
            )
        return self


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
        "log_{5.27}(Σ raw_linear_sum / Σ raw_n); -inf when ≤ 0.",
    )
    ground_truth_scalar: float = Field(
        ...,
        description="Grand-mean log scalar over sampled indices, computed via "
        "log_{5.27}(Σ gt_linear_sum / Σ gt_n); -inf when ≤ 0.",
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
        description=(
            "|sampled_indices|. Equal to the declared file count for a formal "
            "run, fewer for a trial. The upper bound comes from the resolved "
            "Dataset Profile."
        ),
    )

    @model_validator(mode="after")
    def _sampled_count_within_declared_topology(self) -> AggregateScalars:
        """A run cannot sample more files than the dataset declares."""
        num_files = resolve_dataset_profile().dataset.num_files
        if self.num_sampled_files > num_files:
            raise ValueError(
                f"num_sampled_files={self.num_sampled_files} exceeds the declared "
                f"topology (num_files={num_files})."
            )
        return self


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

    rows: list[PerFileRow] = Field(
        ...,
        description=(
            "Exactly one row per validation file in the declared topology. "
            "Unsampled files carry model/gain/headroom as None. The row count "
            "is checked against the resolved Dataset Profile."
        ),
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
    linear_weight_total: float = Field(
        default=0.0,
        ge=0.0,
        description="Σ linear_weight over sampled rows. Stored on the "
        "table as an invariant probe — must round-trip to ~1.0 "
        "(within 1e-9) when any sampled row carries a "
        "linear_weight value. Defaults to 0.0 for tables built "
        "without per-file impact data (legacy / direct dict "
        "construction).",
    )

    @model_validator(mode="after")
    def _one_row_per_declared_file(self) -> ScoreComparisonTable:
        """Exactly one row per file in the declared topology.

        Previously ``min_length=max_length=NUM_FILES`` on the field, fixed at
        import. Same rule, resolved against the profile so a contrast
        topology produces a correctly shaped table instead of a length error.
        """
        num_files = resolve_dataset_profile().dataset.num_files
        if len(self.rows) != num_files:
            raise ValueError(
                f"ScoreComparisonTable needs exactly one row per validation file: "
                f"got {len(self.rows)} rows for a declared topology of "
                f"{num_files} files."
            )
        return self

    @model_validator(mode="after")
    def _validate_weight_total(self) -> ScoreComparisonTable:
        """Guard the Σ linear_weight ≈ 1 invariant over the sampled subset.

        Skipped when no sampled row carries a ``linear_weight`` (legacy
        tables / direct dict construction). When weights are present, both
        the row-level sum and the stored ``linear_weight_total`` must round-
        trip to 1.0 within 1e-9.
        """
        sampled_weights = [r.linear_weight for r in self.rows if r.linear_weight is not None]
        if not sampled_weights:
            return self
        row_sum = sum(sampled_weights)
        if abs(row_sum - 1.0) > 1e-9:
            raise ValueError(
                f"linear_weight values across sampled rows sum to {row_sum} "
                f"— expected 1.0 within 1e-9. linear_weight_total stored: "
                f"{self.linear_weight_total}."
            )
        if abs(self.linear_weight_total - 1.0) > 1e-9:
            raise ValueError(
                f"linear_weight_total={self.linear_weight_total} expected "
                f"1.0 within 1e-9 over sampled rows."
            )
        return self
