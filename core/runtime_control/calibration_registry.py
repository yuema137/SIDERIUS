"""Calibration registry storage engine (C5).

Layout (operator-approved; default root ``~/.siderius/runtime_calibration``,
``SIDERIUS_CALIBRATION_DIR`` honored as ``$SIDERIUS_CALIBRATION_DIR/
runtime_calibration`` so the new registry coexists with the legacy
k-table files in the same override directory):

```text
runtime_calibration/
    registry.json               # compact RegistryManifest (index)
    registry.lock               # advisory flock for index writes
    hardware_profiles/<64hex>.json
    environment_profiles/<64hex>.json
    observations/<64hex>.json   # one immutable file per observation
    summaries/<name>.json       # derived caches (rebuildable)
    installation_id             # stable local UUID (never hostname)
```

Concurrency strategy (C5 implementation record):

* every record file is written via tmp-file + atomic ``os.replace`` and
  NAMED BY ITS CONTENT HASH — concurrent writers of the same content
  are idempotent; different contents never collide; a partially written
  tmp file is never discoverable (readers only follow the index or
  hash-named files);
* the index (``registry.json``) is small and rewritten atomically under
  an advisory ``fcntl.flock`` on ``registry.lock`` (read-modify-write
  race window closed by the lock, not by the rename alone);
* the index only commits IDs whose record file already exists on disk —
  a crash between record write and index write leaves an orphan record
  that ``rebuild_index`` re-adopts (never a dangling index entry);
* ``rebuild_index`` re-derives the manifest from the record files,
  verifying each file's content hash against its filename (corruption
  and tamper detection: mismatches are excluded and reported).

Cross-machine authority rule (§3.3): ``as_estimate`` forces evidence
from a DIFFERENT execution environment to ``historical_observation_prior``
provenance (tier 1 — never blocking alone), regardless of how it was
measured there. Local validated evidence keeps its measured provenance.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from core.runtime_control.estimate_types import RuntimeEstimate, make_estimate
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    CalibrationSummary,
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
    LegacySourceReference,
    RegistryManifest,
)

LEGACY_ADAPTER_VERSION = "1.0.0"


def default_registry_root() -> Path:
    override = os.environ.get("SIDERIUS_CALIBRATION_DIR")
    base = Path(override) if override else Path.home() / ".siderius"
    return base / "runtime_calibration"


def _digest_of(full_id: str) -> str:
    scheme, _, digest = full_id.partition(":")
    if scheme != "sha256" or len(digest) != 64:
        raise ValueError(f"not a full sha256 content id: {full_id!r}")
    return digest


class CalibrationRegistry:
    """Typed, atomic, concurrency-safe registry over the approved layout."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_registry_root()
        self._obs_dir = self.root / "observations"
        self._hw_dir = self.root / "hardware_profiles"
        self._env_dir = self.root / "environment_profiles"
        self._summary_dir = self.root / "summaries"
        for d in (self._obs_dir, self._hw_dir, self._env_dir, self._summary_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "registry.json"
        self._lock_path = self.root / "registry.lock"

    # ── installation identity ──────────────────────────────────────────
    def installation_id(self) -> str:
        """Stable local UUID (generated once; never hostname-derived)."""
        path = self.root / "installation_id"
        if path.exists():
            return path.read_text().strip()
        new_id = str(uuid.uuid4())
        self._atomic_write(path, new_id)
        return new_id

    # ── low-level atomic IO ────────────────────────────────────────────
    def _atomic_write(self, path: Path, text: str) -> None:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def _write_record(self, directory: Path, full_id: str, payload: dict) -> Path:
        path = directory / f"{_digest_of(full_id)}.json"
        if path.exists():  # content-addressed → identical content, dedup
            return path
        self._atomic_write(path, json.dumps(payload, sort_keys=True, indent=1))
        return path

    def _locked_index_update(self, mutate) -> RegistryManifest:
        with open(self._lock_path, "a+") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            try:
                manifest = self.load_manifest()
                changed = mutate(manifest)
                if changed:
                    manifest.generation += 1
                    self._atomic_write(self._index_path, manifest.model_dump_json(indent=1))
                return manifest
            finally:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)

    # ── manifest ───────────────────────────────────────────────────────
    def load_manifest(self) -> RegistryManifest:
        if not self._index_path.exists():
            return RegistryManifest()
        try:
            return RegistryManifest.model_validate_json(self._index_path.read_text())
        except Exception as exc:
            raise ValueError(
                f"registry index corrupt at {self._index_path}: {exc}. "
                "Run rebuild_index() to reconstruct it from the records."
            ) from exc

    # ── writers ────────────────────────────────────────────────────────
    def put_hardware_profile(self, profile: HardwareCompatibilityProfile) -> str:
        pid = profile.profile_id
        self._write_record(self._hw_dir, pid, profile.model_dump(mode="json"))

        def _mutate(m: RegistryManifest) -> bool:
            if pid in m.hardware_profile_ids:
                return False
            m.hardware_profile_ids.append(pid)
            m.hardware_profile_ids.sort()
            return True

        self._locked_index_update(_mutate)
        return pid

    def put_environment_profile(self, profile: ExecutionEnvironmentProfile) -> str:
        pid = profile.profile_id
        self._write_record(self._env_dir, pid, profile.model_dump(mode="json"))

        def _mutate(m: RegistryManifest) -> bool:
            if pid in m.environment_profile_ids:
                return False
            m.environment_profile_ids.append(pid)
            m.environment_profile_ids.sort()
            return True

        self._locked_index_update(_mutate)
        return pid

    def record_observation(self, obs: CalibrationObservation) -> str:
        """Write the immutable record first, then commit its ID to the
        index under the lock — a crash in between leaves an orphan
        record (re-adopted by rebuild), never a dangling index entry."""
        oid = obs.observation_id
        self._write_record(self._obs_dir, oid, obs.model_dump(mode="json"))

        def _mutate(m: RegistryManifest) -> bool:
            if oid in m.observation_ids:
                return False  # dedup: truly identical canonical record
            m.observation_ids.append(oid)
            m.observation_ids.sort()
            return True

        self._locked_index_update(_mutate)
        return oid

    def reference_legacy_source(self, ref: LegacySourceReference) -> None:
        def _mutate(m: RegistryManifest) -> bool:
            if any(
                r.file_sha256 == ref.file_sha256 and r.adapter_version == ref.adapter_version
                for r in m.legacy_sources
            ):
                return False
            m.legacy_sources.append(ref)
            return True

        self._locked_index_update(_mutate)

    # ── readers ────────────────────────────────────────────────────────
    def load_observation(self, full_id: str) -> CalibrationObservation:
        path = self._obs_dir / f"{_digest_of(full_id)}.json"
        obs = CalibrationObservation.model_validate_json(path.read_text())
        if obs.observation_id != full_id:
            raise ValueError(
                f"content-hash mismatch for {path.name}: stored content hashes "
                f"to {obs.observation_id} (corruption or tampering)"
            )
        return obs

    def iter_observations(self) -> Iterator[CalibrationObservation]:
        for oid in self.load_manifest().observation_ids:
            yield self.load_observation(oid)

    # ── reconstruction + verification ──────────────────────────────────
    def rebuild_index(self) -> tuple[RegistryManifest, list[str]]:
        """Reconstruct the manifest from the record files. Files whose
        content hash does not match their filename are EXCLUDED and
        reported (corruption detection). Existing legacy references and
        the generation counter are preserved (generation +1)."""
        rejected: list[str] = []

        def _collect(directory: Path, validate) -> list[str]:
            ids: list[str] = []
            for path in sorted(directory.glob("*.json")):
                try:
                    full_id = validate(path)
                    if _digest_of(full_id) != path.stem:
                        raise ValueError("content-hash/filename mismatch")
                    ids.append(full_id)
                except Exception as exc:
                    rejected.append(f"{path.name}: {exc}")
            return ids

        obs_ids = _collect(
            self._obs_dir,
            lambda p: CalibrationObservation.model_validate_json(p.read_text()).observation_id,
        )
        hw_ids = _collect(
            self._hw_dir,
            lambda p: HardwareCompatibilityProfile.model_validate_json(p.read_text()).profile_id,
        )
        env_ids = _collect(
            self._env_dir,
            lambda p: ExecutionEnvironmentProfile.model_validate_json(p.read_text()).profile_id,
        )

        def _mutate(m: RegistryManifest) -> bool:
            m.observation_ids = sorted(obs_ids)
            m.hardware_profile_ids = sorted(hw_ids)
            m.environment_profile_ids = sorted(env_ids)
            return True

        manifest = self._locked_index_update(_mutate)
        return manifest, rejected

    # ── derived applicability (rebuildable cache) ──────────────────────
    def derive_summary(self, *, operation: str | None = None) -> CalibrationSummary:
        manifest = self.load_manifest()
        selected = [
            o for o in self.iter_observations() if operation is None or o.operation == operation
        ]

        def _rng(key: str) -> tuple[int, int] | None:
            vals = [
                int(o.workload[key])
                for o in selected
                if isinstance(o.workload.get(key), (int, float))
            ]
            return (min(vals), max(vals)) if vals else None

        params = [
            int(o.realized_model["parameter_count"])
            for o in selected
            if isinstance(o.realized_model.get("parameter_count"), (int, float))
        ]
        return CalibrationSummary(
            derived_from_generation=manifest.generation,
            source_observation_ids=tuple(o.observation_id for o in selected),
            operation=operation,  # type: ignore[arg-type]
            parameter_count_range=(min(params), max(params)) if params else None,
            batch_size_range=_rng("batch_size"),
            segment_length_range=_rng("segment_length"),
            sample_count=len(selected),
            concurrency_identities=tuple(sorted({o.concurrency_identity for o in selected})),
            hardware_compatibility_ids=tuple(
                sorted({o.hardware_compatibility_id for o in selected})
            ),
            execution_environment_ids=tuple(sorted({o.execution_environment_id for o in selected})),
            newest_timestamp=max((o.timestamp_metadata or "" for o in selected), default=None)
            or None,
        )

    def save_summary_cache(self, name: str, summary: CalibrationSummary) -> Path:
        path = self._summary_dir / f"{name}.json"
        self._atomic_write(path, summary.model_dump_json(indent=1))
        return path

    def load_summary_cache(self, name: str) -> tuple[CalibrationSummary, bool]:
        """Returns ``(summary, stale)`` — stale when the registry
        generation moved or any source observation left the index."""
        path = self._summary_dir / f"{name}.json"
        summary = CalibrationSummary.model_validate_json(path.read_text())
        manifest = self.load_manifest()
        stale = summary.derived_from_generation != manifest.generation or not set(
            summary.source_observation_ids
        ).issubset(manifest.observation_ids)
        return summary, stale

    # ── cross-machine authority rule (§3.3) ────────────────────────────
    def as_estimate(
        self, obs: CalibrationObservation, *, current_environment_id: str
    ) -> RuntimeEstimate:
        """Wrap an observation as decision evidence. Evidence collected in
        a DIFFERENT execution environment is demoted to
        ``historical_observation_prior`` (tier 1 — never blocking alone),
        even under an identical hardware compatibility profile."""
        local = obs.execution_environment_id == current_environment_id
        seconds = obs.measured_value_ms / 1000.0
        if local and obs.validation_status == "validated":
            return make_estimate(
                provenance=obs.provenance,
                confidence="medium",
                expected_seconds=seconds,
                training_seconds=seconds if obs.operation == "training" else None,
                inference_seconds=seconds if obs.operation == "inference" else None,
                setup_seconds=seconds if obs.operation == "setup" else None,
                concurrency_identity=obs.concurrency_identity,
            )
        warnings = []
        if not local:
            warnings.append(
                "cross-machine observation (different execution environment): "
                "historical prior only — requires local live validation for "
                "blocking authority (§3.3)"
            )
        if obs.validation_status != "validated":
            warnings.append(f"validation_status={obs.validation_status}")
        return make_estimate(
            provenance="historical_observation_prior",
            confidence="low",
            expected_seconds=seconds,
            training_seconds=seconds if obs.operation == "training" else None,
            inference_seconds=seconds if obs.operation == "inference" else None,
            setup_seconds=seconds if obs.operation == "setup" else None,
            concurrency_identity=obs.concurrency_identity,
            warnings=tuple(warnings),
        )


# ── read-only legacy adapter (§5) ───────────────────────────────────────────


def adapt_legacy_k_table(path: Path) -> tuple[LegacySourceReference, list[dict[str, Any]]]:
    """Load the legacy per-GPU k-table READ-ONLY: returns the content-hash
    reference + the raw history entries stamped for legacy-prior use.
    Never writes; callers convert entries via
    ``estimate_types.from_legacy_calibration_entry`` (always
    ``legacy_calibration_prior`` provenance — never measurement-backed)."""
    import hashlib

    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    entries = [e for e in data.get("history", []) if e.get("actual_ms_per_step")]
    slug = path.stem.replace("time_calibration_", "")
    ref = LegacySourceReference(
        gpu_slug=slug,
        file_sha256=hashlib.sha256(raw).hexdigest(),
        adapter_version=LEGACY_ADAPTER_VERSION,
        entry_count=len(entries),
    )
    return ref, entries
