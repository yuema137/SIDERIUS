"""V19 PR 1 (P1-C5) — per-file best table (design doc §3.7).

The table is BOOKKEEPING, not decision state. Nothing in V19 consumes
it. Its purpose is analytical: given a chain workspace with committed
per-iteration artifacts, produce a canonical, deterministic per-file
summary of the best HealthGate-valid and best raw scores achieved.

One single computation — :func:`build_table` — is shared by both the
incremental writer (called from ``run_one_iteration.py`` after each
completed manifest commit) and the standalone
``scripts/rebuild_per_file_best.py`` CLI, so their outputs cannot
drift. See design doc §3.7 (contract) and §3.7.3 (file plan).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.resume import (
    CandidateHealthValidity,
    CommitTimeClassification,
    ReplayIntegrityError,
    classify_committed_record,
)
from execute_tools.evaluation_metric import TIDMAD_METRIC_ID


def _iter_run_name(iter_idx: int) -> str:
    """Chain-mode ``run_name`` convention — mirrored from
    ``core.resume`` (same one-liner; kept local so this module's only
    ``core.resume`` coupling is the single public boundary
    ``classify_committed_record``)."""
    return f"iter_{iter_idx:03d}"


def _sha256_stream(path: str) -> str:
    """Stream a file's SHA-256 hex digest.

    Same integrity check as :func:`core.resume._sha256_file`; kept
    local for the same coupling reason.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Constants (canonical serialization + metric provenance)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1"
TABLE_BASENAME = "per_file_best.json"
LOG_BASE = 5.27  # TIDMAD `denoising_score` — persisted in the header

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
        recorded_sha = manifest.get("run_output_sha256")
        artifact_verified = False
        if recorded_sha:
            actual = _sha256_stream(output_path)
            if actual != recorded_sha:
                raise ReplayIntegrityError(
                    f"[per_file_best] REPLAY-INTEGRITY: iter "
                    f"{iter_idx:03d} committed artifact changed: "
                    f"{output_path} expected sha256 {recorded_sha[:16]}… "
                    f"but found {actual[:16]}…. Restore the original "
                    f"artifact or regenerate a consistent manifest, then "
                    f"rebuild the per-file best table."
                )
            artifact_verified = True
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

    # (file_index, phase, validity) -> best row candidate, tracked in
    # linear space so tie-breaks compare on the same units as the
    # persisted vector.
    candidates: dict[tuple[int, str, str], _RowCandidate] = {}
    skipped_nonpositive = 0

    for src in sources:
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
                    )

    files_covered = sorted({key[0] for key in candidates})
    rows = [candidates[k].as_row() for k in sorted(candidates)]
    return {
        "schema_version": SCHEMA_VERSION,
        # Step 06 C5 — the identity is DECLARED once, in the metric module; this
        # artifact was its precedent and now imports it (emitted value unchanged).
        "metric_id": TIDMAD_METRIC_ID,
        "score_transform": "log",
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


def _consider(
    candidates: dict[tuple[int, str, str], _RowCandidate],
    key: tuple[int, str, str],
    new: _RowCandidate,
) -> None:
    """A3 tie rule: max linear score; ties → earliest iteration →
    persisted round rule → lex smallest ``exp_id``. Applied once per row
    key so incremental and rebuild resolve ties identically."""
    current = candidates.get(key)
    if current is None or _row_beats(new, current):
        candidates[key] = new


def _row_beats(new: _RowCandidate, current: _RowCandidate) -> bool:
    if new.best_linear != current.best_linear:
        return new.best_linear > current.best_linear
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
