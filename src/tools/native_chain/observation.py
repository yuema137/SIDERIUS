"""Bounded no-follow scientific evidence projection; never controls execution."""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, TypeAdapter

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from core.iteration_manifest import verify_iteration_manifest
from core.native_observation import EvidenceReadBytes, ObservationPolicy, observation_policy
from core.record_role import IterationFormalEvidence, formal_evidence_of
from core.run_invariants import RUN_INVARIANTS_BASENAME, parse_run_invariants
from core.seeding import RunSeed, SeedSource
from tools.native_chain.review import read_bytes
from tools.native_chain.token_identity import parse_token_identity
from tools.workflow_preview.models import PreviewModel

CURRENT_OBSERVATION_POLICY: ObservationPolicy = 3
_POLICY_ADAPTER = TypeAdapter(ObservationPolicy)
#: The run-invariants lock is a small control file read under its own fixed
#: bound, never through the evidence budget.
LOCK_READ_MAX_BYTES = 65536


class NativeChainCheckpointObservation(PreviewModel):
    iteration: int
    native_status: str | None = None
    integrity: Literal["verified", "unverified", "missing", "invalid"]
    manifest_sha256: str | None = None
    output_sha256: str | None = None
    manifest_verified: bool = False
    artifact_verified: bool = False
    model_type: str | None = None
    best_score: float | None = None
    formal_best_score: float | None = None
    formal_evidence: IterationFormalEvidence | None = None


class NativeChainEvidence(PreviewModel):
    availability: Literal["available", "unavailable", "limit_exceeded", "integrity_failure"]
    checkpoints: tuple[NativeChainCheckpointObservation, ...] = ()
    anomalies: tuple[str, ...] = ()
    token_run_id: str | None = None
    token_sidecar_sha256: str | None = None


class ObservationBounds(PreviewModel):
    final_iteration: int = Field(gt=0, le=1000, strict=True)
    input_max_bytes: int = Field(gt=0, le=16777216, strict=True)
    max_observation_bytes: int = Field(gt=0, le=1048576, strict=True)
    max_evidence_read_bytes: EvidenceReadBytes | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class ObservationLimit(ValueError):
    pass


def _require_canonical(path: Path) -> None:
    if path != path.resolve() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("noncanonical evidence path")


class LockedRunSeed(PreviewModel):
    """A chain's run seed read back from its run-invariants lock (issue #983).

    Both fields are absent before iteration 1 locks the seed and for a
    pre-seed workspace; ``run_seed_source`` is the lock's own provenance.
    ``run_seed_anomaly`` replaces both when the lock contradicts the reviewed
    declaration (see :func:`checked_against_declaration`).
    """

    run_seed: RunSeed | None = Field(default=None, exclude_if=lambda value: value is None)
    run_seed_source: SeedSource | None = Field(default=None, exclude_if=lambda value: value is None)
    run_seed_anomaly: Literal["lock_contradicts_declaration"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    def checked_against_declaration(self, declared: int | None) -> "LockedRunSeed":
        """Show the lock's seed only if the reviewed declaration explains it.

        ``declared`` is the declaration's ``run.run_seed``. A declared seed must
        be locked as that value with source ``operator``; a seedless
        declaration's seed must be locked with source ``generated``. Anything
        else (a forged, rewritten or source-less lock) is reported as an
        anomaly instead of a value.
        """
        if self.run_seed is None:
            return self
        expected = "generated" if declared is None else "operator"
        if self.run_seed_source != expected or declared not in (None, self.run_seed):
            return LockedRunSeed(run_seed_anomaly="lock_contradicts_declaration")
        return self


def read_locked_seed(workspace: Path, file_limit: int) -> LockedRunSeed:
    """No-follow, bounded readback of the lock's seed; never controls execution.

    Display only: an absent, aliased, oversized or invalid lock reads as no
    seed (shown as unrecorded) and never makes the operation unreadable. The
    native startup, not this reader, refuses such a lock for continuation.
    """
    path = workspace / RUN_INVARIANTS_BASENAME
    try:
        _require_canonical(path)
        lock = parse_run_invariants(
            read_bytes(path, min(file_limit, LOCK_READ_MAX_BYTES)), str(workspace)
        )
    except (OSError, ValueError):
        return LockedRunSeed()
    return LockedRunSeed(run_seed=lock.run_seed, run_seed_source=lock.run_seed_source)


class _Budget:
    def __init__(self, bounds: ObservationBounds, policy: ObservationPolicy):
        if (policy == 3) != (bounds.max_evidence_read_bytes is not None):
            raise ValueError("evidence-read budget requires observation policy 3")
        read_limit = bounds.max_evidence_read_bytes
        self.remaining: int = bounds.max_observation_bytes if read_limit is None else read_limit
        self.file_limit = bounds.input_max_bytes

    def read(self, path: Path) -> bytes:
        _require_canonical(path)
        limit = min(self.file_limit, self.remaining)
        if limit <= 0:
            raise ObservationLimit()
        try:
            data = read_bytes(path, limit)
        except ValueError as error:
            if str(error) == "input_too_large":
                raise ObservationLimit() from error
            raise
        self.remaining -= len(data)
        return data


def _checkpoint(workspace: Path, index: int, budget: _Budget) -> NativeChainCheckpointObservation:
    manifest_path = workspace / f"iter_{index:03d}" / "manifest.json"
    try:
        raw = budget.read(manifest_path)
    except FileNotFoundError:
        return NativeChainCheckpointObservation(iteration=index, integrity="missing")
    digest = hashlib.sha256(raw).hexdigest()
    output_digest = None
    try:
        manifest = json.loads(raw)
        if not isinstance(manifest, dict):
            raise ValueError("manifest object required")
        status = manifest.get("status")
        if not isinstance(status, str):
            raise ValueError("manifest status required")
        output = None
        payload = None
        if status == "completed":
            output = Path(manifest["output_path"])
            if not output.is_absolute() or not output.is_relative_to(
                workspace / f"iter_{index:03d}"
            ):
                raise ValueError("artifact outside admitted iteration")
            payload = budget.read(output)
            output_digest = hashlib.sha256(payload).hexdigest()
        verdict = verify_iteration_manifest(
            manifest,
            iter_idx=index,
            manifest_path=str(manifest_path),
            output_path=str(output) if output else None,
            output_bytes=payload,
        )
        if verdict.problem:
            raise ValueError("manifest or artifact integrity failed")
        parsed = (
            HyperparamTuningOutput.model_validate_json(payload) if payload is not None else None
        )
        return NativeChainCheckpointObservation(
            iteration=index,
            native_status=status,
            integrity="verified"
            if verdict.manifest_verified and (status != "completed" or verdict.artifact_verified)
            else "unverified",
            manifest_sha256=digest,
            output_sha256=output_digest,
            manifest_verified=verdict.manifest_verified,
            artifact_verified=verdict.artifact_verified,
            model_type=parsed.model_type if parsed else None,
            best_score=parsed.best_denoising_score if parsed else None,
            formal_best_score=parsed.best_formal_denoising_score if parsed else None,
            formal_evidence=formal_evidence_of(parsed) if parsed else None,
        )
    except ObservationLimit:
        raise
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return NativeChainCheckpointObservation(
            iteration=index,
            integrity="invalid",
            manifest_sha256=digest,
            output_sha256=output_digest,
        )


def observe_native_chain(
    workspace: Path,
    run_name: str,
    bounds: ObservationBounds,
    *,
    policy: ObservationPolicy | None = None,
) -> NativeChainEvidence:
    """Bound all discovery, retained bytes and emitted projection; never truncate success."""
    selected_policy = _POLICY_ADAPTER.validate_python(
        observation_policy(bounds.max_evidence_read_bytes) if policy is None else policy
    )
    budget = _Budget(bounds, selected_policy)
    try:
        if workspace != workspace.resolve() or workspace.is_symlink():
            raise ValueError("workspace alias")
        if not workspace.exists():
            return NativeChainEvidence(availability="unavailable")
        controls = {
            ".token_run_id",
            ".chain_halted",
            "chain_stopped.json",
            "run_invariants_lock.json",
            "effective_config.json",
            "health_checks_effective.yaml",
            "memory_trace.jsonl",
            "per_file_best.json",
            "evolution_log.jsonl",
            "plugins",
            "plugin_source_sentinel",
            f"{run_name}_hardware.json",
            "generated_library",
            "STOP",
        }
        if selected_policy >= 2:
            controls.add("token_usage.jsonl")
        indices = set()
        anomalies = []
        with os.scandir(workspace) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 2 * bounds.final_iteration + len(controls):
                    raise ObservationLimit()
                hardware = re.fullmatch(r"iter_(\d+)_hardware.json", entry.name)
                if hardware is not None:
                    index = int(hardware[1])
                    if (
                        not 1 <= index <= bounds.final_iteration
                        or entry.name != f"iter_{index:03d}_hardware.json"
                        or entry.is_symlink()
                    ):
                        anomalies.append("unexpected_hardware_entry")
                    continue
                match = re.fullmatch(r"iter_(\d+)", entry.name)
                if match is None:
                    if entry.name not in controls:
                        anomalies.append("unexpected_entry")
                    continue
                index = int(match[1])
                if (
                    index in indices
                    or entry.name != f"iter_{index:03d}"
                    or not 1 <= index <= bounds.final_iteration
                ):
                    anomalies.append("unexpected_iteration")
                indices.add(index)
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    anomalies.append("invalid_iteration_path")
        if indices and any(
            i not in indices for i in range(1, min(max(indices), bounds.final_iteration) + 1)
        ):
            anomalies.append("iteration_gap")
        rows = tuple(
            _checkpoint(workspace, i, budget) for i in range(1, bounds.final_iteration + 1)
        )
        token = None
        token_digest = None
        try:
            token_path = workspace / ".token_run_id"
            # Sidecar has its own smaller native format bound, never token-row scanning.
            previous = budget.file_limit
            budget.file_limit = min(previous, 256)
            raw = budget.read(token_path)
            token, token_digest = parse_token_identity(raw, run_name)
        except FileNotFoundError:
            pass
        result = NativeChainEvidence(
            availability="available",
            checkpoints=rows,
            anomalies=tuple(anomalies),
            token_run_id=token,
            token_sidecar_sha256=token_digest,
        )
        projection_limit = (
            bounds.max_observation_bytes if selected_policy == 3 else budget.remaining
        )
        if len(result.model_dump_json().encode()) > projection_limit:
            raise ObservationLimit()
        return result
    except ObservationLimit:
        return NativeChainEvidence(availability="limit_exceeded")
    except (OSError, ValueError, RuntimeError):
        return NativeChainEvidence(availability="integrity_failure")
