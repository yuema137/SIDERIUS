#!/usr/bin/env python
"""Stage-3 Strict Best finalization — post-search selection over Stage-2 retrains.

Contract
--------
``docs/campaign/stage_artifact_contract.md`` (landed via PR #329; FROZEN):

* §2 — Stage-2 layout: one retrain unit per ``{workspace_root}/stage2/
  {design}_{target_band}/`` holding ``deliverables/`` (the unit's
  TARGET-BAND ABRA-format HDF5 files — Q-S3-2 ruling A, 2026-08-26; a
  design's four band dirs partition 0..19) and ``COMPLETE.json``, written
  LAST by atomic rename. The marker is
  the ONLY completion signal: absence == not done, partial dirs without it
  are never evidence of anything.
* §3 — consumption rule: ``strict_best`` reads Stage-2 ``deliverables/``
  dirs, only from units whose ``COMPLETE.json`` exists and has
  ``healthgate_valid: true``.
* §4 — the shared composer boundary ``compose_and_score(deliverable_dirs, *,
  files=range(20), sample_set=None) -> (file_vector, scalar)``, owned by the
  sibling lane's ``scripts/stage3/stage3_common.py``. It wraps the frozen
  ``score_vector`` arithmetic EXACTLY ONCE over all 20 files; missing or
  duplicated deliverables are its refusal, not ours — this module never
  re-checks file-level coverage and never re-inlines ``score_vector``.

Operator-frozen semantics (Strict Best lane)
--------------------------------------------
Stage-2 retrained each of the campaign's 4 frozen winner DESIGNS (complete
candidate identity — never Stage-1 weights) from scratch on each of the 4
bands = 16 units. Per design this module verifies its 4 units, pools the 4
band ``deliverables/`` dirs, and obtains StrictScore(design) from ONE
``compose_and_score`` call at full 0..19 scope. Across designs it selects
the best StrictScore under :class:`~execute_tools.metric_order.MetricOrder`
— direction always read from the metric declaration, never assumed from a
literal (this file contains no ``max``/``min``/``sorted`` and no comparison
against a direction string; an AST census in the tests pins that).

Per-band scalars are deliberately INEXPRESSIBLE here (campaign rule SRI-11,
the F-SCAND-1 lesson one stage up): there is exactly one composer call site,
no division, no ``sum``/``mean``-family arithmetic, and no numeric value in
any band-scoped output node. ``COMPLETE.json.denoising_score`` (a Stage-2
unit's own band-scoped score) is validated for marker well-formedness and
then never read again — it must not appear in any output, log line, refusal
message, or provenance field of this module (coordinator hazard flag,
2026-08-26). Per-band information leaves this module ONLY as per-FILE
entries of the full-scope ``file_vector``.

Fail-closed decision (flagged for the operator)
-----------------------------------------------
"A unit without the marker or without validity is a NAMED refusal, never a
skip." This module implements the STRICT reading: any refused unit among the
required 4 designs x 4 bands fails the WHOLE finalization closed — every
failing unit is named, the composer is never invoked, no selection artifact
is written, and the CLI exits 2. No degraded best-of-N selection is ever
emitted, mirroring the §4 composer precedent (a missing file refuses the
whole call). The alternative reading — select among the surviving designs
and name the refusals alongside — was deliberately NOT implemented; if the
operator wants it, it is a semantic change to this module, not a default.

Band vocabulary
---------------
The contract's Conventions line fixes ``{BAND}`` ∈ ``0-3 | 4-9 | 10-14 |
15-19`` and names the (not yet landed) F-LAUNCH-1 band launcher's map as the
authority, cross-checked by ``campaign_preflight.sh`` R6. Until that map is
importable, :data:`BAND_VOCABULARY` restates the contract vocabulary here,
verbatim and cited; converging on the launcher's map is a follow-up for the
launcher lane.

Sibling dependency
------------------
``scripts/stage3/stage3_common.py`` is owned by a parallel writer lane and
is bound lazily by module path (see :func:`_resolve_compose_and_score`), so
this module imports, type-checks, and unit-tests cleanly before the sibling
lands; tests stub the boundary with the frozen §4 signature.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    ValidationError,
    field_validator,
    model_validator,
)

from execute_tools.evaluation_metric import (
    MetricIdentityConflictError,
    MetricSpec,
    NotScoreableError,
    StampedMetricSpec,
    reconcile_metric_specs,
)
from execute_tools.metric_order import MetricOrder
from scripts.stage3.stage3_composed_best import (
    Stage3ComposedBestError,
    _iteration_dirs,
    _load_completed_iteration,
    _stamped_metric_spec,
    band_file_indices,
)

# ---------------------------------------------------------------------------
# Frozen layout constants (contract citations on each)
# ---------------------------------------------------------------------------

#: Contract "Conventions": ``{BAND}`` ∈ ``0-3 | 4-9 | 10-14 | 15-19`` (DS8
#: band vocabulary). Order here fixes the pooled-dir order handed to the
#: composer; coverage of files 0..19 is the composer's own frozen check.
BAND_VOCABULARY: Final[tuple[str, str, str, str]] = ("0-3", "4-9", "10-14", "15-19")

#: Operator-frozen Strict Best semantics: the campaign has exactly 4 frozen
#: winner designs. Fewer or more is refused — a "best of 3" finalization is
#: exactly the silent degradation this lane exists to make impossible.
EXPECTED_DESIGN_COUNT: Final[int] = 4

#: Contract §2 — the atomic completion marker, the ONLY thing Stage-3 polls.
COMPLETE_MARKER_NAME: Final[str] = "COMPLETE.json"

#: Contract §2 — the unit's copied deliverable set (its TARGET-BAND files,
#: Q-S3-2 ruling A; the four band dirs of a design partition 0..19).
DELIVERABLES_DIR_NAME: Final[str] = "deliverables"

#: Contract §2 — Stage-2 units live under ``{workspace_root}/stage2/``.
STAGE2_DIR_NAME: Final[str] = "stage2"

#: Contract §2 — each unit's chain workspace (Stage-1 rules apply inside).
WORKSPACE_DIR_NAME: Final[str] = "workspace"

#: Contract §3 — this lane's namespace under ``{workspace_root}/stage3/``.
DEFAULT_SELECTION_RELPATH: Final[str] = "stage3/strict_best/strict_best_selection.json"

#: Contract §4 — the full 0..19 file set, passed EXPLICITLY on the one call.
FULL_FILE_SET: Final[range] = range(20)

_FULL_FILE_COUNT: Final[int] = 20

#: The sibling lane's module holding the shared composer (contract §4).
_STAGE3_COMMON_MODULE: Final[str] = "scripts.stage3.stage3_common"

CONTRACT_DOC: Final[str] = "docs/campaign/stage_artifact_contract.md"

#: Versioned identity of this module's selection semantics, stamped into the
#: emitted artifact so a consumer can tell WHICH rule produced it.
SELECTION_RULE: Final[str] = "strict_best.fail_closed.one_composed_score_per_design.v1"


class ComposeAndScore(Protocol):
    """The frozen §4 composer boundary (owned by ``stage3_common``).

    ``deliverable_dirs`` are pooled dirs of ABRA-format ``.h5`` deliverables;
    exactly one deliverable must resolve per file across them (the composer's
    own refusal). Returns ``score_vector``'s 2-tuple ``(file_vector, scalar)``.
    """

    def __call__(
        self,
        deliverable_dirs: list[str],
        *,
        files: range = ...,
        sample_set: None = ...,
        reconciled_spec: MetricSpec,
    ) -> tuple[list[float], float]: ...


class StrictBestRefusal(RuntimeError):
    """Named fail-closed refusal: NO selection may be derived from this state.

    Carries every individual refusal line so the operator sees the complete
    list at once (all failing units are named in one pass, not one per rerun).
    Raising this guarantees no composer call was or will be made for the
    refused finalization and no selection artifact is written.
    """

    def __init__(self, refusals: Sequence[str]) -> None:
        self.refusals: tuple[str, ...] = tuple(refusals)
        super().__init__(
            "Strict Best refused (fail-closed, no selection emitted):\n  - "
            + "\n  - ".join(self.refusals)
        )


class CompleteMarker(BaseModel):
    """The frozen ``COMPLETE.json`` schema (contract §2), validated fail-closed.

    ``healthgate_valid`` is a :class:`~pydantic.StrictBool` on purpose: a
    marker carrying ``"true"`` (string) is a malformed artifact and refuses —
    lax coercion here would let a mis-serialized launcher silently pass the
    one gate field Stage-3 consumes. ``deliverable_count`` is the TARGET
    band's file count (Q-S3-2 ruling A, 2026-08-26: a band-scoped run
    produces the scope's files ONLY — DS8's enforced behaviour — so the four
    units of a design partition 0..19 and whole-dir pooling composes with
    zero duplicates; the pre-ruling literal 20 could never compose).
    ``denoising_score`` is validated as a number ONLY so a
    malformed marker refuses; it is a band-scoped scalar and is never copied
    into any output of this module (module docstring, hazard rule). Extra
    keys are tolerated: additive launcher provenance must not break Stage-3.
    """

    model_config = ConfigDict(extra="allow")

    design: str
    target_band: str
    exp_id: str
    model_type: str
    repo_sha: str
    denoising_score: float
    healthgate_valid: StrictBool
    deliverable_count: int
    completed_utc: str

    @model_validator(mode="after")
    def _deliverable_count_matches_target_band(self) -> CompleteMarker:
        """Q-S3-2 ruling A: the count is the TARGET band's file count."""
        try:
            expected = len(band_file_indices(self.target_band))
        except Exception as exc:  # malformed band label -> schema refusal
            raise ValueError(
                f"target_band {self.target_band!r} is not a parseable band label: {exc}"
            ) from exc
        if self.deliverable_count != expected:
            raise ValueError(
                f"deliverable_count={self.deliverable_count} does not match target band "
                f"{self.target_band!r} ({expected} files; Q-S3-2 ruling A — a unit "
                f"carries its target-band deliverables only)"
            )
        return self


class UnitProvenance(BaseModel):
    """Identity provenance for one verified Stage-2 unit.

    This is a band-scoped output node: it must NEVER gain a numeric field
    (coordinator hazard flag — no band-level scalar in outputs/logs/
    provenance; the no-band-scalar witness in the tests enforces it).
    ``extra="forbid"`` keeps an undeclared field from riding in via a dict.
    """

    model_config = ConfigDict(extra="forbid")

    design: str
    target_band: str
    exp_id: str
    model_type: str
    repo_sha: str
    healthgate_valid: bool
    unit_dir: str


class DesignScore(BaseModel):
    """One design's StrictScore: the full 0..19 composed result, nothing else.

    ``strict_score`` exists ONLY at full scope; ``file_vector`` carries the 20
    per-FILE entries — the only legal expression of per-band information.
    """

    model_config = ConfigDict(extra="forbid")

    design: str
    strict_score: float
    file_vector: list[float]
    deliverable_dirs: list[str]
    units: list[UnitProvenance]

    @field_validator("file_vector")
    @classmethod
    def _file_vector_is_full_scope(cls, value: list[float]) -> list[float]:
        if len(value) != _FULL_FILE_COUNT:
            raise ValueError(
                f"file_vector must carry exactly {_FULL_FILE_COUNT} per-FILE entries "
                f"(full 0..19 scope by contract §4); got {len(value)}"
            )
        return value


class StrictBestSelection(BaseModel):
    """The emitted Strict Best artifact: all StrictScores plus the selection."""

    model_config = ConfigDict(extra="forbid")

    contract: str
    selection_rule: str
    metric_id: str
    metric_direction: str
    designs: list[DesignScore]
    selected_design: str
    selected_strict_score: float
    selected_deliverable_dirs: list[str]
    generated_utc: str


# ---------------------------------------------------------------------------
# Production boundary resolution
# ---------------------------------------------------------------------------


def _resolve_compose_and_score() -> ComposeAndScore:
    """Bind the sibling lane's shared composer (contract §4) by module path.

    Lazy and importlib-based on purpose: the module belongs to a parallel
    writer lane, so a static import would make THIS module unimportable (and
    unanalyzable) until the sibling lands. A missing module or attribute is a
    named refusal — never a silent fallback to any other scoring path.
    """
    try:
        module = importlib.import_module(_STAGE3_COMMON_MODULE)
    except ModuleNotFoundError as exc:
        raise StrictBestRefusal(
            [
                f"shared composer module {_STAGE3_COMMON_MODULE!r} is not importable "
                f"({exc}). It is owned by the stage3_common writer lane (contract §4); "
                "Strict Best refuses rather than re-inlining score_vector."
            ]
        ) from exc
    fn = getattr(module, "compose_and_score", None)
    if fn is None:
        raise StrictBestRefusal(
            [
                f"{_STAGE3_COMMON_MODULE!r} defines no compose_and_score — the frozen "
                "§4 boundary is absent; refusing rather than substituting a scorer."
            ]
        )
    return cast(ComposeAndScore, fn)


def _unit_stamped_spec(
    stage2_root: Path, design: str, band: str
) -> tuple[StampedMetricSpec | None, list[str]]:
    """One unit's persisted 09a metric stamp, read through the verified loader.

    Step-09a discipline (local-gate ruling, 2026-08-26): this module derives
    NOTHING. Each retrain unit's ``workspace/`` is a normal single-iteration
    chain workspace (contract §2), so its ``HyperparamTuningOutput`` carries
    the tuner's stamped ``metric_spec`` — the ONE stamping authority. The
    read reuses the composed-best lane's manifest-VERIFIED loader (digest
    rules included; ``arm=None`` because units carry no arm concept), and a
    unit whose workspace is missing, unverifiable, multi-iteration, or
    stamp-less is a NAMED refusal — pre-09a-shaped units refuse, never
    default.

    Returns ``(stamped, refusals)`` — exactly one of the two is meaningful,
    mirroring :func:`_verify_unit` so the caller aggregates across all 16.
    """
    label = f"unit {design}_{band}"
    workspace = os.path.join(stage2_root, f"{design}_{band}", WORKSPACE_DIR_NAME)
    if not os.path.isdir(workspace):
        return None, [
            f"{label}: no {WORKSPACE_DIR_NAME}/ chain workspace (contract §2) — the "
            f"unit's stamped metric_spec cannot be sourced; refusing."
        ]
    try:
        completed = [
            loaded
            for iter_index, iter_dir in _iteration_dirs(workspace)
            if (loaded := _load_completed_iteration(iter_index, iter_dir, None)) is not None
        ]
    except Stage3ComposedBestError as exc:
        return None, [f"{label}: workspace verification failed: {exc}"]
    if not completed:
        return None, [f"{label}: no completed iteration in {workspace} — refusing."]
    if len(completed) > 1:
        return None, [
            f"{label}: {len(completed)} completed iterations in {workspace}; a "
            f"contract §2 unit is single-iteration — refusing."
        ]
    output, output_path = completed[0]
    try:
        spec = _stamped_metric_spec(output, output_path)
    except Stage3ComposedBestError as exc:
        return None, [f"{label}: {exc}"]
    return StampedMetricSpec(label=f"{label} run output", spec=spec), []


# ---------------------------------------------------------------------------
# Verification (contract §2/§3) — fail-closed, all refusals collected
# ---------------------------------------------------------------------------


def _verify_unit(
    stage2_root: Path, design: str, band: str
) -> tuple[UnitProvenance | None, list[str]]:
    """Verify ONE retrain unit per the frozen consumption rule.

    Returns ``(provenance, [])`` for a verified unit, else ``(None,
    [named refusal])``. Never raises for a per-unit condition — the caller
    aggregates refusals across all 16 units so one run names every problem.
    Refusal text deliberately never repeats the marker's ``denoising_score``.
    """
    unit_dir = Path(os.path.join(stage2_root, f"{design}_{band}"))
    marker_path = Path(os.path.join(unit_dir, COMPLETE_MARKER_NAME))
    label = f"unit {design}_{band} at {unit_dir}"
    if not marker_path.is_file():
        return None, [
            f"{label}: {COMPLETE_MARKER_NAME} is absent — the unit is NOT DONE "
            "(contract §2: the atomic marker is the only completion signal; partial "
            "unit contents are not evidence, and Strict Best refuses rather than skips)"
        ]
    try:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [
            f"{label}: {COMPLETE_MARKER_NAME} is unreadable or not JSON "
            f"({exc.__class__.__name__}: {exc}) — malformed marker refused"
        ]
    try:
        marker = CompleteMarker.model_validate(raw)
    except ValidationError as exc:
        # loc + msg only: Pydantic's msg never echoes the offending VALUE, so a
        # malformed denoising_score cannot leak a band-scoped scalar into logs.
        details = "; ".join(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        return None, [
            f"{label}: {COMPLETE_MARKER_NAME} fails the frozen marker schema "
            f"(contract §2) — {details}"
        ]
    if marker.design != design or marker.target_band != band:
        return None, [
            f"{label}: marker identity mismatch — marker says design={marker.design!r}, "
            f"target_band={marker.target_band!r}; the directory name says "
            f"design={design!r}, target_band={band!r} (wrong artifact in the unit dir)"
        ]
    if marker.healthgate_valid is not True:
        return None, [
            f"{label}: healthgate_valid is not true — a HealthGate-invalid retrain is "
            "never selectable, however good its numbers look (contract §3 consumption "
            "rule; operator negative control). Its score is deliberately not repeated."
        ]
    deliverables_dir = Path(os.path.join(unit_dir, DELIVERABLES_DIR_NAME))
    if not deliverables_dir.is_dir():
        return None, [
            f"{label}: {DELIVERABLES_DIR_NAME}/ is missing despite {COMPLETE_MARKER_NAME} "
            "(contract §2 layout violation)"
        ]
    provenance = UnitProvenance(
        design=design,
        target_band=band,
        exp_id=marker.exp_id,
        model_type=marker.model_type,
        repo_sha=marker.repo_sha,
        healthgate_valid=True,
        unit_dir=str(unit_dir.resolve()),
    )
    return provenance, []


# ---------------------------------------------------------------------------
# Scoring — ONE composer call per design, full 0..19 scope
# ---------------------------------------------------------------------------


def _pooled_deliverable_dirs(stage2_root: Path, design: str) -> list[str]:
    """The design's 4 band ``deliverables/`` dirs, absolute, in frozen band order."""
    return [
        str(Path(os.path.join(stage2_root, f"{design}_{band}", DELIVERABLES_DIR_NAME)).resolve())
        for band in BAND_VOCABULARY
    ]


def _score_design(
    design: str,
    stage2_root: Path,
    units: list[UnitProvenance],
    compose_and_score: ComposeAndScore,
    *,
    reconciled_spec: MetricSpec,
) -> DesignScore:
    """StrictScore(design): the ONE full-scope composer call for this design.

    This function owns the module's single ``compose_and_score`` call site
    (SRI-11: with one call site, no division and no sum/mean/max/min in this
    module, a per-band-scalar path is inexpressible). ``files`` and
    ``sample_set`` are passed explicitly so the frozen full-scope contract is
    stated at the call, not inherited from a default.
    """
    pooled_dirs = _pooled_deliverable_dirs(stage2_root, design)
    try:
        file_vector, strict_score = compose_and_score(
            pooled_dirs, files=FULL_FILE_SET, sample_set=None, reconciled_spec=reconciled_spec
        )
    except NotScoreableError as refusal:
        raise StrictBestRefusal(
            [
                f"design {design}: the shared composer refused the pooled 0..19 "
                f"deliverable — {refusal}"
            ]
        ) from refusal
    return DesignScore(
        design=design,
        strict_score=float(strict_score),
        file_vector=[float(entry) for entry in file_vector],
        deliverable_dirs=pooled_dirs,
        units=units,
    )


def _strict_score_key(score: DesignScore) -> float:
    return score.strict_score


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def finalize_strict_best(
    workspace_root: Path,
    designs: Sequence[str],
    *,
    compose_and_score_fn: ComposeAndScore | None = None,
    metric: MetricSpec | None = None,
) -> StrictBestSelection:
    """Verify 4x4 Stage-2 units, score each design ONCE, select by MetricOrder.

    Args:
        workspace_root: the campaign's persistent root (contains ``stage2/``).
        designs: exactly the 4 frozen winner design ids, in operator order
            (ties in the selection resolve to the earliest, per
            :meth:`MetricOrder.best`).
        compose_and_score_fn: testing/injection seam for the §4 boundary;
            ``None`` binds the sibling module's production composer.
        metric: testing/injection seam for the metric spec; ``None`` — the
            production path — RECONCILES the 09a ``metric_spec`` stamps
            persisted in the 16 units' chain workspaces through the ONE
            reconciliation authority (Step-09a: this module derives nothing;
            absent or divergent stamps are named fail-closed refusals).
            Direction is interpreted ONLY by :class:`MetricOrder`.

    Returns:
        The full :class:`StrictBestSelection` (not yet written to disk).

    Raises:
        StrictBestRefusal: fail-closed — invalid design list, any unverified
            unit among the 16 (every one named), an unresolvable composer, or
            a composer refusal. No partial selection is ever returned.
    """
    design_list = list(designs)
    if len(design_list) != EXPECTED_DESIGN_COUNT:
        raise StrictBestRefusal(
            [
                f"Strict Best finalizes exactly {EXPECTED_DESIGN_COUNT} frozen winner "
                f"designs (operator-frozen semantics); got {len(design_list)}: "
                f"{design_list!r}. A best-of-N over a partial design set is the "
                "degradation this refusal exists to prevent."
            ]
        )
    if len(set(design_list)) != EXPECTED_DESIGN_COUNT:
        raise StrictBestRefusal([f"design ids must be distinct; got duplicates in {design_list!r}"])
    stage2_root = Path(os.path.join(workspace_root, STAGE2_DIR_NAME))
    if not stage2_root.is_dir():
        raise StrictBestRefusal([f"stage2 root is missing: {stage2_root} (contract §2 layout)"])

    refusals: list[str] = []
    units_by_design: dict[str, list[UnitProvenance]] = {}
    stamped_sources: list[StampedMetricSpec] = []
    for design in design_list:
        verified: list[UnitProvenance] = []
        for band in BAND_VOCABULARY:
            provenance, unit_refusals = _verify_unit(stage2_root, design, band)
            refusals.extend(unit_refusals)
            if provenance is not None:
                verified.append(provenance)
            if metric is None:
                stamped, spec_refusals = _unit_stamped_spec(stage2_root, design, band)
                refusals.extend(spec_refusals)
                if stamped is not None:
                    stamped_sources.append(stamped)
        units_by_design[design] = verified
    if refusals:
        # Fail-closed BEFORE any scoring: no composer call happens for a
        # finalization that cannot be completed (module docstring decision).
        raise StrictBestRefusal(refusals)

    compose_and_score = (
        compose_and_score_fn if compose_and_score_fn is not None else _resolve_compose_and_score()
    )
    if metric is not None:
        declared, order = metric, MetricOrder(metric)
    else:
        # ONE reconciliation authority over the 16 units' 09a stamps, never a
        # hand-rolled equality and never a fresh derivation (local-gate
        # Step-09a ruling, 2026-08-26). Per-unit absence already refused
        # above, so the authority sees a fully-stamped set.
        try:
            reconciled = reconcile_metric_specs(stamped_sources)
        except MetricIdentityConflictError as exc:
            raise StrictBestRefusal([f"unit metric stamps disagree: {exc}"]) from exc
        if reconciled is None:  # defensive: unreachable past the refusal aggregation
            raise StrictBestRefusal(["no Stage-2 unit carries a 09a metric_spec stamp — refusing."])
        declared, order = reconciled, MetricOrder(reconciled)

    design_scores = [
        _score_design(
            design,
            stage2_root,
            units_by_design[design],
            compose_and_score,
            reconciled_spec=declared,
        )
        for design in design_list
    ]
    best = order.best(design_scores, key=_strict_score_key)
    return StrictBestSelection(
        contract=CONTRACT_DOC,
        selection_rule=SELECTION_RULE,
        metric_id=declared.id,
        metric_direction=order.direction,
        designs=design_scores,
        selected_design=best.design,
        selected_strict_score=best.strict_score,
        selected_deliverable_dirs=best.deliverable_dirs,
        generated_utc=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def render_summary(selection: StrictBestSelection) -> list[str]:
    """Human-readable summary lines, derived ONLY from the selection artifact.

    Formatting rule (coordinator hazard flag): a line naming a band token
    carries no numeric value, and score lines carry no band token — per-band
    information is only expressible as the JSON artifact's per-FILE vector.
    """
    lines: list[str] = []
    for score in selection.designs:
        for unit in score.units:
            lines.append(
                f"[strict_best] unit ok: {unit.design}_{unit.target_band} "
                "(COMPLETE, healthgate_valid)"
            )
    for score in selection.designs:
        lines.append(
            f"[strict_best] design {score.design}: strict_score={score.strict_score!r} "
            "over the composed full 0..19 deliverable"
        )
    lines.append(
        f"[strict_best] SELECTED {selection.selected_design} "
        f"strict_score={selection.selected_strict_score!r} "
        f"(metric {selection.metric_id}, direction {selection.metric_direction}, "
        f"rule {selection.selection_rule})"
    )
    return lines


def _write_atomic(path: Path, text: str) -> None:
    """Write-then-rename, mirroring the contract §2 marker discipline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Stage-3 Strict Best finalization: verify the 4x4 Stage-2 retrain units, "
            "score each frozen design ONCE over the composed full 0..19 deliverable, "
            "and select the best StrictScore under MetricOrder. Fail-closed: any "
            "unverified unit refuses the whole finalization (exit 2)."
        )
    )
    parser.add_argument(
        "--workspace_root",
        required=True,
        help="Campaign persistent root containing stage2/ (contract Conventions).",
    )
    parser.add_argument(
        "--designs",
        required=True,
        help=(
            "Comma-separated ids of the 4 frozen winner designs (the design registry "
            "is the campaign plan's), e.g. wavenetA,punetB,gatedfnoC,rnnD."
        ),
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Selection artifact path; default "
            f"{{workspace_root}}/{DEFAULT_SELECTION_RELPATH} (contract §3 namespace)."
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    compose_and_score_fn: ComposeAndScore | None = None,
    metric: MetricSpec | None = None,
) -> int:
    """CLI entry point. Returns 0 on selection, 2 on a named fail-closed refusal."""
    args = build_parser().parse_args(argv)
    workspace_root = Path(args.workspace_root)
    design_list = [item.strip() for item in str(args.designs).split(",") if item.strip()]
    out_path = (
        Path(args.out)
        if args.out
        else Path(os.path.join(workspace_root, DEFAULT_SELECTION_RELPATH))
    )
    try:
        selection = finalize_strict_best(
            workspace_root,
            design_list,
            compose_and_score_fn=compose_and_score_fn,
            metric=metric,
        )
    except StrictBestRefusal as refusal:
        print("[strict_best] REFUSED — no selection emitted (fail-closed):", file=sys.stderr)
        for line in refusal.refusals:
            print(f"[strict_best]   {line}", file=sys.stderr)
        return 2
    _write_atomic(out_path, selection.model_dump_json(indent=2) + "\n")
    for line in render_summary(selection):
        print(line)
    print(f"[strict_best] selection written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
