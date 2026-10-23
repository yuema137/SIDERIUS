"""Legacy chain inspection projection; defaults and display remain unchanged."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.iteration_manifest import verify_iteration_manifest
from core.record_role import RecordRoleError, formal_evidence_of

_CHAIN_ITER_RE = re.compile(r"^iter_(\d+)$")


@dataclass
class IterationReport:
    """Per-iteration findings for the summary table.

    Same shape for both layouts so :func:`render_table` is layout-agnostic.
    ``model_subdir`` and ``run_output_path`` are only populated by the
    legacy run-layout walk; chain-layout reports leave them ``None``.

    ``best_score`` is the tuner's MIXED best — ``top_record`` over all
    records, trial and formal — and is rendered under a column that says so.
    ``formal_best_score`` is the authoritative one (F-SCANB-3): it is
    ``None`` for an iteration that ran only trial rounds, which is exactly
    the state the single mixed column used to conceal. Defaulted, so the
    dozen non-COMMITTED constructions below are unchanged.
    """

    iter_idx: int
    iter_dir: Path
    model_subdir: Path | None
    run_output_path: Path | None
    status: str
    model_type: str | None
    best_score: float | None
    detail: str
    formal_best_score: float | None = None


def _formal_evidence_detail(parsed: HyperparamTuningOutput) -> str:
    """The formal-evidence fragment of a report's ``detail`` (F-SCANB-3).

    Degrades rather than raises. The role authority refuses an anomalous
    ``is_trial`` / ``trial_portion`` shape because a silent choice could
    select the wrong record. This inspector owns chain bookkeeping, so it
    reports the anomaly in the row instead of turning reporting into an
    uncaught crash.
    """
    try:
        evidence = formal_evidence_of(parsed)
    except RecordRoleError as exc:
        return f"formal_success=? anomalous_role_shape ({exc})"
    return f"formal_success={evidence.formal_success_count}/{evidence.record_count}"


def _validate_run_output(
    path: Path,
) -> tuple[HyperparamTuningOutput | None, str]:
    """Try to load + validate ``run_output_*.json``. Returns (parsed, err)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"read error: {e}"
    try:
        return HyperparamTuningOutput.model_validate_json(text), ""
    except ValidationError as e:
        return None, f"validation: {e.error_count()} error(s)"
    except json.JSONDecodeError as e:
        return None, f"malformed JSON: {e.msg}"


def inspect_chain_iteration(iter_dir: Path) -> IterationReport:
    """Classify a single ``iter_NNN/`` dir under the chain layout.

    Mirrors the predicate in ``core.resume._read_manifest`` +
    ``_validate_run_output`` so the inspector's "COMMITTED" matches what
    ``restore_prior_state`` will accept.
    """
    m = _CHAIN_ITER_RE.match(iter_dir.name)
    if m is None:
        raise ValueError(
            f"inspect_chain_iteration: {iter_dir.name!r} does not match {_CHAIN_ITER_RE.pattern!r}"
        )
    iter_idx = int(m.group(1))
    manifest_path = iter_dir / "manifest.json"

    if not manifest_path.is_file():
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="MISSING",
            model_type=None,
            best_score=None,
            detail="no manifest.json (iter never committed)",
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=None,
            best_score=None,
            detail=f"manifest malformed JSON: {e.msg}",
        )
    except OSError as e:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=None,
            best_score=None,
            detail=f"manifest read error: {e}",
        )

    status = manifest.get("status")
    model_name = manifest.get("model_name")
    if status != "completed":
        # S2 / U5 — a non-completed manifest names no artifact, but its own
        # self-digest is still verified, exactly as resume does before it
        # skips a no_records iter.
        verdict = verify_iteration_manifest(
            manifest, iter_idx=iter_idx, manifest_path=str(manifest_path), output_path=None
        )
        if verdict.problem is not None:
            return IterationReport(
                iter_idx,
                iter_dir,
                None,
                None,
                status="TAMPERED",
                model_type=model_name,
                best_score=None,
                detail=f"REPLAY-INTEGRITY: {verdict.problem}",
            )
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="PARTIAL",
            model_type=model_name,
            best_score=None,
            detail=f"manifest status={status!r}, expected 'completed'",
        )

    output_path_str = manifest.get("output_path")
    if not output_path_str:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            None,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail="manifest has no output_path field",
        )
    output_path = Path(output_path_str)
    if not output_path.is_file():
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail=f"manifest output_path does not exist: {output_path}",
        )

    # S2 / U5 — replay integrity BEFORE the artifact is trusted, from the
    # one predicate resume and per_file_best share. A manifest that resume
    # would stop the chain on is never called COMMITTED here.
    verdict = verify_iteration_manifest(
        manifest,
        iter_idx=iter_idx,
        manifest_path=str(manifest_path),
        output_path=str(output_path),
    )
    if verdict.problem is not None:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="TAMPERED",
            model_type=model_name,
            best_score=None,
            detail=f"REPLAY-INTEGRITY: {verdict.problem}",
        )

    parsed, err = _validate_run_output(output_path)
    if parsed is None:
        return IterationReport(
            iter_idx,
            iter_dir,
            None,
            output_path,
            status="CORRUPT",
            model_type=model_name,
            best_score=None,
            detail=f"run_output {err}",
        )

    return IterationReport(
        iter_idx,
        iter_dir,
        None,
        output_path,
        status="COMMITTED",
        model_type=parsed.model_type,
        best_score=parsed.best_denoising_score,
        detail=(
            f"status={parsed.status} rounds={parsed.completed_rounds} "
            f"{_formal_evidence_detail(parsed)}"
        ),
        formal_best_score=parsed.best_formal_denoising_score,
    )
