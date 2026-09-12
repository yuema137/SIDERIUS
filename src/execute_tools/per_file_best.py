"""V19 PR 1 (P1-C5) — per-file best table (design doc §3.7).

The table is BOOKKEEPING, not decision state. Nothing in V19 consumes
it. Its purpose is analytical: given a chain workspace with committed
per-iteration artifacts, produce a canonical, deterministic per-file
summary of the best HealthGate-valid and best raw scores achieved.

One single computation — :func:`build_table` — is shared by both the
incremental writer (called from ``run_one_iteration.py`` after each
completed manifest commit) and the standalone
``scripts/runtime/rebuild_per_file_best.py`` CLI, so their outputs cannot
drift. See design doc §3.7 (contract) and §3.7.3 (file plan).
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.iteration_manifest import verify_iteration_manifest
from core.resume import (
    CandidateHealthValidity,
    CommitTimeClassification,
    ReplayIntegrityError,
    classify_committed_record,
)
from execute_tools.evaluation_metric import (
    MetricIdentityKey,
    StampedMetricSpec,
    metric_identity_from_record,
    metric_identity_unavailable_notice,
    reconcile_metric_identity,
)
from execute_tools.metric_order import MetricOrder


def _iter_run_name(iter_idx: int) -> str:
    """Chain-mode ``run_name`` convention — mirrored from
    ``core.resume`` (same one-liner; kept local so this module's only
    ``core.resume`` coupling is the single public boundary
    ``classify_committed_record``)."""
    return f"iter_{iter_idx:03d}"


# ---------------------------------------------------------------------------
# Constants (canonical serialization + metric provenance)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1"
TABLE_BASENAME = "per_file_best.json"
# The base of the ONE transform this module applies: `_log` derives every
# row's `best_log_score` from its `best_linear`, unconditionally, for every
# workspace. `LOG_BASE` and the `score_transform` header field therefore
# document THIS MODULE'S derived row column — they are not, and must not be
# read as, the run metric's declared transform. The run's metric is reported
# by the `metric_id` header field, which is RESOLVED (see `_table_identity`).
# The value originates in TIDMAD's `denoising_score`; that a generic row
# column is still transformed by it is the named capability gap recorded in
# `_row_beats`, not a claim about the run.
LOG_BASE = 5.27
SCORE_TRANSFORM = "log"

# Per A2 (design §3.7 rev 3): one stable gate_summary schema for both
# raw and valid rows.
_VALIDITY_LABELS = {
    CandidateHealthValidity.VALID: "valid",
    CandidateHealthValidity.INVALID: "invalid",
    CandidateHealthValidity.UNKNOWN: "unknown",
}

# ---------------------------------------------------------------------------
# Types (data classes are pure structural; not persisted directly)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SourceIter:
    """One committed iteration worth of table-relevant data."""

    iter_idx: int
    manifest: dict
    parsed: HyperparamTuningOutput
    output_path: str
    artifact_verified: bool  # False when the manifest carried no hash
    formal_eval_portion: float | None  # from run_config; null for legacy
    formal_strategy: str | None  # from run_config; null for legacy


# ---------------------------------------------------------------------------
# Public API — one shared computation
# ---------------------------------------------------------------------------


def build_table(workspace: str) -> dict[str, Any]:
    """Return the canonical per-file best table dict for ``workspace``.

    Walks ``{workspace}/iter_NNN/manifest.json`` in ascending order,
    accepts only manifests with ``status == "completed"`` (A6), verifies
    ``run_output_sha256`` when present (§3.6 rules — legacy no-hash
    manifests are ADMITTED but flagged in ``unverified_sources``; a hash
    mismatch on a hash-carrying manifest raises
    :class:`ReplayIntegrityError` — same fail-closed behavior as
    incumbent reconstruction), then selects per-file bests per §3.7 A3.

    Args:
        workspace: chain workspace root (absolute path preferred).

    Returns:
        A dict conforming to the §3.7 A8 canonical header + row schema.
        Empty ``rows`` when no committed iterations exist.

        Header ``metric_id`` is the metric the committed artifacts DECLARE
        (:func:`_table_identity`), or ``null`` when none of them declares one.
        Header ``score_transform``/``log_base`` describe :func:`_log`, the
        transform applied to every row's ``best_log_score``; they document
        this module's derived column and are constant across tasks.

        The table is written for every run, including a task with no per-file
        deliverable — such a run simply has no rows. Emptiness is not
        task-shaped: a TIDMAD run whose scores are all non-positive, or one
        whose first iteration produced no successful record, is equally
        row-less, so suppressing the artifact on emptiness would change TIDMAD
        behaviour while still not detecting "this task has no per-file
        concept". The header states what is known and the empty ``rows`` and
        ``files_covered`` state what is not.

    Raises:
        ReplayIntegrityError: a committed manifest's
            ``run_output_sha256`` no longer matches the on-disk bytes.
    """
    abs_workspace = os.path.abspath(workspace)
    sources = list(_iter_committed_sources(abs_workspace))
    return _assemble(sources)


def write_table(workspace: str) -> Path:
    """Materialize the table atomically under ``{workspace}/per_file_best.json``.

    Same computation as :func:`build_table`; adds:
      * canonical serialization (sorted keys, fixed separators, LF, UTF-8);
      * atomic temp-file + ``os.replace`` — a partially written table is
        never observable, and a failure preserves any previous version;
      * strict byte-equality guarantee against a rebuild-CLI invocation
        over the same inputs.

    Returns:
        The path the table was written to.

    Raises:
        ReplayIntegrityError: (from ``build_table``) on hash mismatch.
        OSError: on filesystem errors during write.
    """
    table = build_table(workspace)
    path = Path(os.path.abspath(workspace)) / TABLE_BASENAME
    payload = _canonical_json(table)
    _atomic_write_bytes(path, payload)
    return path


def canonical_bytes(table: dict[str, Any]) -> bytes:
    """Return the canonical JSON bytes for ``table``.

    Exposed so rebuild-vs-incremental byte-equality tests can compare
    without touching disk. Byte identity relies on canonical
    serialization (sorted keys, fixed separators, LF, UTF-8) and on the
    table itself excluding any non-committed-derived fields (design A7,
    A8).
    """
    return _canonical_json(table)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _iter_committed_sources(workspace: str) -> Iterable[_SourceIter]:
    """Yield one :class:`_SourceIter` per accepted committed iteration.

    Failure policy mirrors the incumbent walker's rules:
      * missing ``iter_NNN/`` → walk terminates (no gap-fill).
      * manifest with ``status != "completed"`` → SKIPPED (A6); walk
        continues (matches ``no_records`` handling in resume).
      * manifest without ``output_path`` or ``run_output`` file
        unreachable → SKIPPED with no exception (best-effort table).
      * ``run_output_sha256`` present and mismatched → raises
        :class:`ReplayIntegrityError` (fail-closed, same as resume).
    """
    if not os.path.isdir(workspace):
        return
    iter_idx = 1
    while True:
        run_name = _iter_run_name(iter_idx)
        iter_dir = os.path.join(workspace, run_name)
        manifest_path = os.path.join(iter_dir, "manifest.json")
        if not os.path.isfile(manifest_path):
            return
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            iter_idx += 1
            continue
        if manifest.get("status") != "completed":
            iter_idx += 1
            continue
        output_path = manifest.get("output_path")
        if not output_path or not os.path.isfile(output_path):
            iter_idx += 1
            continue
        # S2 / U5 — the SAME predicate resume applies (manifest self-digest,
        # hash removal, artifact bytes), from the one shared authority.
        verdict = verify_iteration_manifest(
            manifest, iter_idx=iter_idx, manifest_path=manifest_path, output_path=output_path
        )
        if verdict.problem is not None:
            raise ReplayIntegrityError(
                f"[per_file_best] REPLAY-INTEGRITY: {verdict.problem}. Restore the "
                f"original artifact, or replace the iteration explicitly "
                f"(run_one_iteration.py --replace_iteration_manifest "
                f"--replacement_reason '<why>'), then rebuild the per-file best table."
            )
        artifact_verified = verdict.artifact_verified
        try:
            with open(output_path, encoding="utf-8") as f:
                parsed = HyperparamTuningOutput.model_validate_json(f.read())
        except Exception:
            iter_idx += 1
            continue
        formal_eval_portion, formal_strategy = _read_formal_provenance(
            iter_dir, run_name, parsed.model_type
        )
        yield _SourceIter(
            iter_idx=iter_idx,
            manifest=manifest,
            parsed=parsed,
            output_path=output_path,
            artifact_verified=artifact_verified,
            formal_eval_portion=formal_eval_portion,
            formal_strategy=formal_strategy,
        )
        iter_idx += 1


def _read_formal_provenance(
    iter_dir: str, run_name: str, model_name: str
) -> tuple[float | None, str | None]:
    """Load committed formal-eval provenance from ``run_config_iter_NNN.json``.

    Layout: ``{iter_dir}/iteration_{iter_idx:03d}/{model_name}/run_config_{run_name}.json``.
    Missing file or missing keys → ``(None, None)`` per A4 rule (never
    inferred from current defaults or repo configuration).
    """
    # iter_dir already encodes ``iter_NNN``; the tuner writes its
    # ``run_config`` inside its own sub-workspace.
    iter_num = int(run_name.split("_")[-1])
    config_path = os.path.join(
        iter_dir,
        f"iteration_{iter_num:03d}",
        model_name,
        f"run_config_{run_name}.json",
    )
    if not os.path.isfile(config_path):
        return None, None
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None
    portion = cfg.get("formal_eval_portion")
    strategy = cfg.get("formal_strategy")
    return (
        (float(portion) if isinstance(portion, (int, float)) else None),
        (str(strategy) if isinstance(strategy, str) else None),
    )


def _record_dict(record: Any) -> dict[str, Any]:
    """Local copy of core.resume's helper (dataset-agnostic; trivial)."""
    if isinstance(record, dict):
        return record
    if hasattr(record, "model_dump"):
        return record.model_dump(mode="json")
    return {}


def _assemble(sources: list[_SourceIter]) -> dict[str, Any]:
    """Build the canonical table dict from parsed sources."""
    iterations_included = sorted(s.iter_idx for s in sources)
    unverified = sum(1 for s in sources if not s.artifact_verified)

    # Step 10 P2a C2 — one reconciled identity for the whole table, built from
    # what the artifacts DECLARE (§4.4). A set of iterations spanning two
    # metric bindings refuses here rather than ranking per-file rows across
    # incomparable metrics. The SAME resolution names the metric in the header
    # and orders the rows, so the artifact cannot report one and rank by the
    # other.
    table_identity = _table_identity(sources)
    row_order = MetricOrder(table_identity) if table_identity is not None else None

    # (file_index, phase, validity) -> best row candidate, tracked in
    # linear space so tie-breaks compare on the same units as the
    # persisted vector.
    candidates: dict[tuple[int, str, str], _RowCandidate] = {}
    skipped_nonpositive = 0

    # Q-10-2: nothing declares which way is better, so no row can be called
    # "best". The header is still emitted — the table stays inspectable and
    # its provenance readable — but it carries no rows and says why.
    scanned_sources = sources if row_order is not None else []
    if row_order is None and sources:
        # STDERR, not stdout. `scripts/runtime/rebuild_per_file_best.py --print-only`
        # writes this table's canonical JSON to stdout and its contract is
        # byte-exact (`test_cli_print_only_writes_canonical_json_to_stdout`
        # compares stdout to `canonical_bytes` directly), so a diagnostic line
        # on stdout would corrupt a machine-readable artifact. The notice is
        # for a human; the table is for a program.
        print(
            metric_identity_unavailable_notice(
                "the per-file best table",
                detail=(
                    f"{len(sources)} committed iteration(s) declare no metric identity; "
                    "no row is selected"
                ),
            ),
            file=sys.stderr,
        )

    for src in scanned_sources:
        # `scanned_sources` is EMPTY whenever `row_order` is None, so the body
        # below is unreachable without an order. Stated for the type checker,
        # which cannot see that coupling across the assignment above.
        assert row_order is not None
        # A single validity classification per record — used for BOTH
        # the ``valid`` row eligibility and the raw row's gate_summary.
        for rec in src.parsed.all_records:
            data = _record_dict(rec)
            if data.get("status") != "success":
                continue
            file_vector = data.get("file_vector")
            if not isinstance(file_vector, list):
                continue
            phase = "trial" if data.get("is_trial") else "formal"
            cls = classify_committed_record(
                rec,
                src.parsed,
                src.output_path,
                os.path.dirname(os.path.dirname(src.output_path)) or ".",
            )
            gate_summary = _gate_summary(data, cls)
            eval_strategy, eval_portion = _sampling_provenance(data, phase, src)

            for file_index, linear in enumerate(file_vector):
                if not isinstance(linear, (int, float)):
                    continue
                if not math.isfinite(linear) or linear <= 0.0:
                    if isinstance(linear, (int, float)):
                        skipped_nonpositive += 1
                    continue
                # Every finite-positive score contributes to the RAW pool.
                _consider(
                    candidates,
                    (file_index, phase, "raw"),
                    _RowCandidate(
                        file_index=file_index,
                        phase=phase,
                        validity_row="raw",
                        best_linear=float(linear),
                        iter_idx=src.iter_idx,
                        round_index=cls.round_index,
                        round_provenance=cls.round_provenance,
                        exp_id=str(data.get("exp_id") or ""),
                        model_type=str(data.get("model_type") or src.parsed.model_type),
                        model_params=data.get("model_params"),
                        eval_strategy=eval_strategy,
                        eval_portion=eval_portion,
                        gate_summary=gate_summary,
                        timestamp=str(data.get("timestamp") or ""),
                    ),
                    order=row_order,
                )
                # VALID rows only get commit-time VALID records.
                if cls.validity is CandidateHealthValidity.VALID:
                    _consider(
                        candidates,
                        (file_index, phase, "valid"),
                        _RowCandidate(
                            file_index=file_index,
                            phase=phase,
                            validity_row="valid",
                            best_linear=float(linear),
                            iter_idx=src.iter_idx,
                            round_index=cls.round_index,
                            round_provenance=cls.round_provenance,
                            exp_id=str(data.get("exp_id") or ""),
                            model_type=str(data.get("model_type") or src.parsed.model_type),
                            model_params=data.get("model_params"),
                            eval_strategy=eval_strategy,
                            eval_portion=eval_portion,
                            gate_summary=gate_summary,
                            timestamp=str(data.get("timestamp") or ""),
                        ),
                        order=row_order,
                    )

    files_covered = sorted({key[0] for key in candidates})
    rows = [candidates[k].as_row() for k in sorted(candidates)]
    return {
        "schema_version": SCHEMA_VERSION,
        # The metric THIS RUN was scored under, RESOLVED from what the committed
        # artifacts declare (`_table_identity`) — never a literal, never a
        # default. `null` means the workspace declared no identity, which is
        # also why it has no rows. Until this was resolved the field emitted
        # `TIDMAD_METRIC_ID` unconditionally, so every composed non-TIDMAD run
        # stamped TIDMAD's identity onto its own table.
        "metric_id": table_identity.id if table_identity is not None else None,
        # These two describe `_log`, the transform this module applies to every
        # row's `best_log_score` — see the `LOG_BASE` declaration. They are a
        # property of the derived row column, NOT of the run's metric, and are
        # therefore constant across tasks.
        "score_transform": SCORE_TRANSFORM,
        "log_base": LOG_BASE,
        "iterations_included": iterations_included,
        "files_covered": files_covered,
        "skipped_nonpositive_count": skipped_nonpositive,
        "unverified_sources": unverified,
        "validity_semantics": (
            "record-level commit-time HealthGate validity (NOT per-file "
            "gate verdicts); raw rows are gate-agnostic finite-positive "
            "bests; valid rows require CandidateHealthValidity.VALID under "
            "the iteration's commit-time policy"
        ),
        "rows": rows,
    }


def _sampling_provenance(
    record: dict[str, Any],
    phase: str,
    src: _SourceIter,
) -> tuple[str | None, float | None]:
    """Return ``(eval_strategy, eval_portion)`` for a row's source record.

    Trial rows source from the record (both keys always written when
    ``is_trial``). Formal rows source from committed
    ``run_config_iter_NNN.json`` per A4 — legacy sources correctly
    resolve to ``(None, None)``.
    """
    if phase == "trial":
        strategy = record.get("eval_strategy")
        portion = record.get("eval_portion")
        return (
            (str(strategy) if isinstance(strategy, str) else None),
            (float(portion) if isinstance(portion, (int, float)) else None),
        )
    return src.formal_strategy, src.formal_eval_portion


def _gate_summary(
    record: dict[str, Any],
    cls: CommitTimeClassification,
) -> dict[str, Any]:
    """A2 stable gate_summary — same shape on raw and valid rows.

    ``blocking_failed_gate_ids`` and ``waiver_ids`` are always lists
    (possibly empty), never null — canonical stability for byte-equality.
    """
    blocking_failed: list[str] = []
    waiver_ids: list[str] = []
    if record.get("health_gate_enabled") is False:
        waiver_ids.append("health_gate_enabled=false")
    for raw in record.get("health_gate_results") or []:
        item = raw if isinstance(raw, dict) else _record_dict(raw)
        if item.get("would_invalidate_under_production_policy") is True:
            gate_id = item.get("gate_name")
            if isinstance(gate_id, str):
                blocking_failed.append(gate_id)
    return {
        "candidate_validity": _VALIDITY_LABELS[cls.validity],
        "validity_basis": cls.validity_basis,
        "blocking_failed_gate_ids": sorted(set(blocking_failed)),
        "waiver_ids": sorted(set(waiver_ids)),
    }


@dataclass
class _RowCandidate:
    """One row's mutable candidate during selection; frozen once picked."""

    file_index: int
    phase: str
    validity_row: str
    best_linear: float
    iter_idx: int
    round_index: int | None
    round_provenance: str
    exp_id: str
    model_type: str
    model_params: int | None
    eval_strategy: str | None
    eval_portion: float | None
    gate_summary: dict[str, Any]
    timestamp: str

    def as_row(self) -> dict[str, Any]:
        return {
            "file_index": self.file_index,
            "phase": self.phase,
            "validity": self.validity_row,
            "best_log_score": _log(self.best_linear),
            "best_linear": self.best_linear,
            "iteration": self.iter_idx,
            "round_index": self.round_index,
            "round_provenance": self.round_provenance,
            "exp_id": self.exp_id,
            "model_type": self.model_type,
            "model_params": self.model_params,
            "eval_strategy": self.eval_strategy,
            "eval_portion": self.eval_portion,
            "gate_summary": self.gate_summary,
            "timestamp": self.timestamp,
        }


def _table_identity(sources: list[_SourceIter]) -> MetricIdentityKey | None:
    """The ONE metric identity this table describes, or ``None``.

    This is the table's single metric authority. Its result feeds BOTH the
    ``metric_id`` header field and the :class:`MetricOrder` every row is
    selected by, so the artifact cannot name one metric while ranking under
    another — which is exactly what it used to do: the header emitted
    ``TIDMAD_METRIC_ID`` as a literal while this function resolved the real
    identity from the artifacts and threw it away. A composed
    California-housing run (metric ``mae``, direction ``lower``) wrote
    ``metric_id: "tidmad_denoising_score"`` for that reason.

    The identity granularity is ``(id, direction)`` and deliberately no more.
    The pool below is HETEROGENEOUS — iteration outputs contribute whole
    ``MetricSpec`` objects, scored records contribute ``MetricIdentityKey``
    pairs — and ``reconcile_metric_specs`` compares whole declarations, so a
    spec and a key for the SAME metric would never compare equal. Identity is
    the only granularity that spans this pool, which is why the table can
    report a resolved ``metric_id`` and cannot report a resolved transform
    without opening a second reconciliation over a different pool. It does not
    need one: ``score_transform``/``log_base`` describe ``_log``, this
    module's own row column, not the run's metric.

    Step 10 P2a C2. Both declared sources §4.4 names for this module are
    offered to the SHARED reconciliation authority — each iteration's stamped
    ``MetricSpec`` and each scored record's persisted ``metric_result`` — so a
    workspace whose iterations span two metric bindings refuses here rather
    than silently ranking per-file rows across incomparable metrics.

    Returns ``None`` when NOTHING declares an identity (a pre-Step-06
    workspace). The table then reports no rows rather than ranking them on an
    assumed direction, and its ``metric_id`` is ``null`` — a named absence.
    Emitting a metric name there would be a fabrication, not a default: the
    workspace has said nothing about which metric it was scored under.

    **It deliberately does NOT derive a spec in that case.** An earlier draft
    fell back to ``derive_tidmad_metric_spec``, reasoning that this module
    already emitted ``metric_id: TIDMAD_METRIC_ID`` in its own header. That was
    wrong twice over: P2a's frozen contract is that it derives metric identity
    NOWHERE, and Step 09a's executable census pins the exact set of production
    modules allowed to derive the TIDMAD metric — the fallback made this a
    fifth, and CI caught it. Emitting a metric's NAME is not the same as being
    entitled to invent its direction. The header literal that motivated that
    draft is now itself gone; the premise it argued from no longer exists.

    Raises:
        MetricIdentityConflictError: sources declare different metrics.
    """
    stamped: list[StampedMetricSpec] = [
        StampedMetricSpec(label=f"iteration {src.iter_idx}", spec=src.parsed.metric_spec)
        for src in sources
        if getattr(src.parsed, "metric_spec", None) is not None
    ]
    stamped += [
        StampedMetricSpec(
            label=f"iteration {src.iter_idx} record {data.get('exp_id')!r}",
            spec=identity,
        )
        for src in sources
        for data in (_record_dict(rec) for rec in src.parsed.all_records)
        if (identity := metric_identity_from_record(data)) is not None
    ]
    return reconcile_metric_identity(stamped)


def _consider(
    candidates: dict[tuple[int, str, str], _RowCandidate],
    key: tuple[int, str, str],
    new: _RowCandidate,
    *,
    order: MetricOrder,
) -> None:
    """A3 tie rule: BEST linear score; ties → earliest iteration →
    persisted round rule → lex smallest ``exp_id``. Applied once per row
    key so incremental and rebuild resolve ties identically."""
    current = candidates.get(key)
    if current is None or _row_beats(new, current, order=order):
        candidates[key] = new


def _row_beats(new: _RowCandidate, current: _RowCandidate, *, order: MetricOrder) -> bool:
    """Whether ``new`` displaces ``current`` for one row key.

    Step 10 P2a C2 / design §4.3. Only the SCORE comparison consults
    ``order``; every tie rule below it is direction-INDEPENDENT and is
    unchanged.

    Why comparing ``best_linear`` is legitimate (§4.3, a TIDMAD fact — NOT a
    generic framework contract): ``best_linear`` holds the persisted
    ``file_vector`` values themselves, and the log form emitted as
    ``best_log_score`` is a DERIVED display computed by :func:`_log`. Since
    ``LOG_BASE`` is 5.27 > 1, ``log_5.27`` is strictly increasing, so ranking
    in linear space and ranking in log space agree for every positive value —
    and the loader already discards non-positive entries. A future metric
    whose per-sample values need a NON-monotone display transform would break
    that equivalence; that is a named future capability requirement of the
    metric interface, deliberately not faked here as a generic guard.
    """
    if new.best_linear != current.best_linear:
        return order.is_better(new.best_linear, current.best_linear)
    if new.iter_idx != current.iter_idx:
        return new.iter_idx < current.iter_idx
    # Persisted round wins over legacy-unknown at the same iteration.
    new_persisted = new.round_provenance == "persisted"
    cur_persisted = current.round_provenance == "persisted"
    if new_persisted != cur_persisted:
        return new_persisted
    if (
        new.round_index is not None
        and current.round_index is not None
        and new.round_index != current.round_index
    ):
        return new.round_index < current.round_index
    return new.exp_id < current.exp_id


def _log(linear: float) -> float:
    """Convert linear file-vector value to canonical log score."""
    return math.log(linear) / math.log(LOG_BASE)


# ---------------------------------------------------------------------------
# Canonical serialization + atomic write
# ---------------------------------------------------------------------------


def _canonical_json(table: dict[str, Any]) -> bytes:
    """Sorted keys, fixed separators, LF-terminated UTF-8."""
    text = json.dumps(table, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Temp-file + ``os.replace`` — a partially written table is never
    observable, and a failed write preserves the previous version."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "wb") as f:
        f.write(payload)
    os.replace(tmp, path)
