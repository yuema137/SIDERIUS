"""Narrow manifest and completeness helpers for resumable comparison campaigns."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ValidationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    missing_inference_outputs: list[str] = field(default_factory=list)


@dataclass
class Phase1ReuseDecision:
    """Explicit outcome of the same-campaign Phase 1 reuse policy."""

    action: Literal["train", "reuse", "regenerate_inference"]
    validation: ValidationReport | None = None


def validate_experiment_completeness(
    record: dict[str, Any], *, configured_gate_ids: list[str]
) -> list[str]:
    errors: list[str] = []
    if record.get("denoising_score") is None and not record.get("invalid_score_reason"):
        errors.append("missing scalar score and invalid_score_reason")
    if record.get("file_vector") is None and not record.get("file_vector_absence_reason"):
        errors.append("missing file_vector and file_vector_absence_reason")
    results = record.get("health_gate_results") or []
    by_name = {item.get("gate_name"): item for item in results}
    missing = [gate_id for gate_id in configured_gate_ids if gate_id not in by_name]
    if missing:
        errors.append(f"missing HealthGate results: {missing}")
    # Imported here, and read at CALL time, so a bound task is honoured and
    # nothing freezes a topology at import. Local import mirrors the
    # existing convention in `validate_phase1_baseline` below.
    from execute_tools.dataset_config import resolve_dataset_profile

    declared_health_peek = resolve_dataset_profile().health_peek_files
    for gate_id, result in by_name.items():
        status = result.get("execution_status")
        if status not in {"passed", "failed", "not_run", "error"}:
            errors.append(f"gate {gate_id}: invalid execution_status={status!r}")
        if result.get("resolved_action") != "continue":
            errors.append(f"gate {gate_id}: observe action is not continue")
        if status in {"passed", "failed"} and not result.get("metrics"):
            errors.append(f"gate {gate_id}: executed gate has no metrics")
        requested = (result.get("aggregation") or {}).get("files_requested") or []
        # The per-file completeness check applies to gates that peeked the
        # task's DECLARED health-peek set — the same declaration the
        # blocking checks resolve, rather than a second hardcoded copy of
        # TIDMAD's triplet.
        #
        # The comparison stays an EXACT ORDERED LIST equality, unchanged.
        # `requested` is copied verbatim from `peek_file_indices` by
        # health_checks/evaluation.py:202, and today a reordered list such
        # as [10, 3, 17] takes the else-branch and is silently NOT
        # enforced. Comparing as a set, or sorting either side, would
        # newly ENFORCE those records — a POLICY change disguised as an
        # authority change. Any improvement here is Step-08 work.
        if requested == declared_health_peek:
            per_file = (result.get("metrics") or {}).get("per_file") or {}
            absent = [str(index) for index in requested if str(index) not in per_file]
            if absent:
                errors.append(f"gate {gate_id}: missing per-file entries {absent}")
    if not record.get("checkpoint_path"):
        errors.append("missing checkpoint_path")
    if not record.get("params"):
        errors.append("missing validated config params")
    return errors


def validate_phase1_baseline(
    record: dict[str, Any],
    *,
    campaign_name: str,
    model_type: str,
    expected_params: dict[str, Any],
    expected_training_files: list[str],
    configured_gate_ids: list[str],
    expected_output_paths: list[str],
    expected_resolved_data_scope: list[int] | None = None,
) -> ValidationReport:
    errors = validate_experiment_completeness(record, configured_gate_ids=configured_gate_ids)
    if record.get("campaign_run_name") != campaign_name:
        errors.append("campaign_run_name mismatch")
    # DS6d — functional campaign identity: reuse never crosses a DataScope
    # boundary. A record without a stamp predates the feature and was
    # necessarily produced under the full scope. None skips the check
    # (legacy callers).
    if expected_resolved_data_scope is not None:
        from execute_tools.dataset_config import TIDMAD

        record_scope = record.get("resolved_data_scope")
        effective_scope = (
            list(range(TIDMAD.num_files)) if record_scope is None else sorted(record_scope)
        )
        if effective_scope != sorted(expected_resolved_data_scope):
            errors.append("data_scope mismatch")
    if record.get("model_type") != model_type:
        errors.append("model_type mismatch")
    actual_params = record.get("params") or {}
    for key in ("model_config", "train_config", "loss_config"):
        if actual_params.get(key) != expected_params.get(key):
            errors.append(f"effective {key} mismatch")
    if record.get("training_files") != expected_training_files:
        errors.append("ordered training-file inventory mismatch")
    if record.get("status") not in {"success", "failed_mode_collapse"}:
        errors.append("training did not complete successfully")
    checkpoint = record.get("checkpoint_path")
    if not checkpoint or not os.path.isfile(checkpoint):
        errors.append("checkpoint missing")
    elif record.get("checkpoint_sha256") != sha256_file(checkpoint):
        errors.append("checkpoint hash mismatch")
    missing_outputs = [path for path in expected_output_paths if not os.path.isfile(path)]
    return ValidationReport(
        valid=not errors,
        errors=errors,
        missing_inference_outputs=missing_outputs,
    )


def decide_phase1_reuse(
    record: dict[str, Any] | None,
    *,
    campaign_name: str,
    model_type: str,
    expected_params: dict[str, Any],
    expected_training_files: list[str],
    configured_gate_ids: list[str],
    expected_output_paths: list[str],
    expected_resolved_data_scope: list[int] | None = None,
) -> Phase1ReuseDecision:
    """Choose training, reuse, or inference regeneration without side effects."""
    if record is None:
        return Phase1ReuseDecision(action="train")
    report = validate_phase1_baseline(
        record,
        campaign_name=campaign_name,
        model_type=model_type,
        expected_params=expected_params,
        expected_training_files=expected_training_files,
        configured_gate_ids=configured_gate_ids,
        expected_output_paths=expected_output_paths,
        expected_resolved_data_scope=expected_resolved_data_scope,
    )
    if not report.valid:
        return Phase1ReuseDecision(action="train", validation=report)
    if report.missing_inference_outputs:
        return Phase1ReuseDecision(action="regenerate_inference", validation=report)
    return Phase1ReuseDecision(action="reuse", validation=report)


def write_campaign_manifest(path: str, payload: dict[str, Any]) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
    return path
