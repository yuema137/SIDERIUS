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
    promotions/<64hex>.json     # C7 derived D4 promotion records
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

from core.runtime_control.calibration_read import (
    NO_CANDIDATE,
    CandidateRequest,
    evaluate_candidate_authority,
)
from core.runtime_control.estimate_types import RuntimeEstimate, make_estimate
from core.runtime_control.registry_schemas import (
    REGISTRY_SCHEMA_VERSION,
    CalibrationObservation,
    CalibrationPromotion,
    CalibrationSummary,
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
    LegacySourceReference,
    QuarantineRecord,
    RegistryManifest,
)

LEGACY_ADAPTER_VERSION = "1.0.0"


def schema_major(schema_version: str) -> int:
    """Major component of a registry schema version."""
    try:
        return int(schema_version.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"not a registry schema version: {schema_version!r}") from exc


def registry_dirname(schema_version: str = REGISTRY_SCHEMA_VERSION) -> str:
    """Directory name for a schema version.

    v1 keeps the historical name so the existing tree is found exactly where
    it has always been; v2 and later get a suffixed sibling.
    """
    major = schema_major(schema_version)
    return "runtime_calibration" if major <= 1 else f"runtime_calibration_v{major}"


def default_registry_root(schema_version: str = REGISTRY_SCHEMA_VERSION) -> Path:
    """Root for the CURRENT schema version.

    V20 PR C1 / C-C2b, operator decision O-1: a new schema version gets a
    NEW TREE. The old one is left in place, byte for byte, and is never
    re-hashed.

    That is not a stylistic choice. `CalibrationObservation.hash_payload()`
    dumps the whole model, and `schema_version` is inside it, so adding any
    field -- even an optional one defaulting to None -- changes every
    existing record's content id. `load_observation` then raises
    "content-hash mismatch ... (corruption or tampering)", and
    `rebuild_index` silently drops every record into its rejected list and
    commits an empty manifest. Verified empirically against a live record
    during the PR C audit: one added optional field moved
    sha256:09e767d8... to sha256:6cff7c0d....

    Migrating in place would therefore mean either rewriting 20 records
    whose ids other artifacts may cite, or teaching the loader to accept a
    hash it cannot verify. A sibling tree costs a directory.
    """
    override = os.environ.get("SIDERIUS_CALIBRATION_DIR")
    base = Path(override) if override else Path.home() / ".siderius"
    return base / registry_dirname(schema_version)


def legacy_registry_root() -> Path:
    """The v1 tree, for READ-ONLY inspection.

    Nothing in the v2 write path may target this. It exists so an operator
    tool can report what the old tree holds without the v2 loader trying to
    verify hashes computed under a different schema.
    """
    return default_registry_root("1.0.0")


def _digest_of(full_id: str) -> str:
    scheme, _, digest = full_id.partition(":")
    if scheme != "sha256" or len(digest) != 64:
        raise ValueError(f"not a full sha256 content id: {full_id!r}")
    return digest


def _measured_dimensions(observations: list[Any]) -> tuple[str, ...]:
    """Numeric workload keys present across a bucket's own observations.

    Derived from the evidence rather than declared, because producers spell
    the workload differently and a hardcoded list silently excludes whichever
    one it does not name.
    """
    keys: set[str] = set()
    for obs in observations:
        keys.update(k for k, v in (obs.workload or {}).items() if isinstance(v, (int, float)))
    return tuple(sorted(keys))


class CalibrationRegistry:
    """Typed, atomic, concurrency-safe registry over the approved layout."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_registry_root()
        self._obs_dir = self.root / "observations"
        self._hw_dir = self.root / "hardware_profiles"
        self._env_dir = self.root / "environment_profiles"
        self._summary_dir = self.root / "summaries"
        self._promo_dir = self.root / "promotions"
        #: O-2. Physically separate from `observations/` so a quarantined
        #: record cannot be picked up by a directory walk that means to read
        #: usable evidence.
        self._quarantine_dir = self.root / "quarantine"
        for d in (
            self._obs_dir,
            self._hw_dir,
            self._env_dir,
            self._summary_dir,
            self._promo_dir,
            self._quarantine_dir,
        ):
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
            manifest = RegistryManifest.model_validate_json(self._index_path.read_text())
        except Exception as exc:
            raise ValueError(
                f"registry index corrupt at {self._index_path}: {exc}. "
                "Run rebuild_index() to reconstruct it from the records."
            ) from exc
        self._refuse_foreign_schema(manifest)
        return manifest

    def _refuse_foreign_schema(self, manifest: RegistryManifest) -> None:
        """Fail closed when this tree was written under another major schema.

        O-1 gives each major version its own tree, but a tree is just a path
        -- an operator pointing `SIDERIUS_CALIBRATION_DIR` at the old one, or
        a stale override in a launcher, would otherwise have v2 code append
        v2 records beside v1 records in a directory whose manifest claims v1.

        The failure that would follow is silent: `rebuild_index` verifies
        every file's content hash and *excludes* the ones that do not match,
        committing a manifest that omits them. Half the evidence would
        disappear with no error. Refusing here turns that into a message
        naming both versions and both paths.
        """
        found = schema_major(manifest.schema_version)
        expected = schema_major(REGISTRY_SCHEMA_VERSION)
        if found != expected:
            raise ValueError(
                f"registry at {self.root} was written under schema major {found} "
                f"(version {manifest.schema_version!r}), but this build writes "
                f"major {expected} (version {REGISTRY_SCHEMA_VERSION!r}). "
                "Each major version has its own tree (operator decision O-1); "
                f"the current one is {default_registry_root()}. The older tree is "
                "read-only evidence and must not be written to or re-hashed."
            )

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

    def record_promotion(self, promotion: CalibrationPromotion) -> str:
        """Persist a DERIVED D4 promotion record (C7). Same atomicity
        contract as observations; the sources it names are verified to be
        indexed first — a promotion can never cite evidence the registry
        does not hold. Observations are NEVER mutated: the promotion is
        the authoritative status for its bucket."""
        manifest = self.load_manifest()
        missing = [
            oid for oid in promotion.source_observation_ids if oid not in manifest.observation_ids
        ]
        if missing:
            raise ValueError(f"promotion cites observations absent from the index: {missing}")
        pid = promotion.promotion_id
        self._write_record(self._promo_dir, pid, promotion.model_dump(mode="json"))

        def _mutate(m: RegistryManifest) -> bool:
            if pid in m.promotion_ids:
                return False
            m.promotion_ids.append(pid)
            m.promotion_ids.sort()
            return True

        self._locked_index_update(_mutate)
        return pid

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
    def quarantine_observation(
        self,
        payload: dict,
        *,
        reason: str,
        missing_identity_fields: tuple[str, ...] = (),
        timestamp_metadata: str | None = None,
    ) -> str:
        """Record a measurement that cannot be trusted with an identity.

        O-2. The record is written and indexed, so an operator can count and
        inspect it, but its id goes to `quarantined_ids` -- never
        `observation_ids`. Every reader that walks observations walks that
        list, so this record is structurally unable to reach a bucket, a
        promotion, an applicability verdict or any authority.

        Returns the quarantine id.
        """
        record = QuarantineRecord(
            observation_payload=payload,
            reason=reason,
            missing_identity_fields=missing_identity_fields,
            timestamp_metadata=timestamp_metadata,
        )
        qid = record.quarantine_id
        self._write_record(self._quarantine_dir, qid, record.model_dump(mode="json"))

        def _mutate(m: RegistryManifest) -> bool:
            if qid in m.quarantined_ids:
                return False
            m.quarantined_ids.append(qid)
            m.quarantined_ids.sort()
            return True

        self._locked_index_update(_mutate)
        return qid

    def load_quarantined(self, full_id: str) -> QuarantineRecord:
        path = self._quarantine_dir / f"{_digest_of(full_id)}.json"
        record = QuarantineRecord.model_validate_json(path.read_text())
        if record.quarantine_id != full_id:
            raise ValueError(
                f"content-hash mismatch for {path.name}: stored content hashes "
                f"to {record.quarantine_id} (corruption or tampering)"
            )
        return record

    def iter_quarantined(self) -> Iterator[QuarantineRecord]:
        """Audit surface. Deliberately a DIFFERENT method from
        `iter_observations`: a caller that wants usable evidence must not
        receive these by default, and a caller that wants to audit what was
        lost has to say so."""
        for qid in self.load_manifest().quarantined_ids:
            yield self.load_quarantined(qid)

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

    def load_promotion(self, full_id: str) -> CalibrationPromotion:
        path = self._promo_dir / f"{_digest_of(full_id)}.json"
        promo = CalibrationPromotion.model_validate_json(path.read_text())
        if promo.promotion_id != full_id:
            raise ValueError(
                f"content-hash mismatch for {path.name}: stored content hashes "
                f"to {promo.promotion_id} (corruption or tampering)"
            )
        return promo

    def iter_promotions(self) -> Iterator[CalibrationPromotion]:
        for pid in self.load_manifest().promotion_ids:
            yield self.load_promotion(pid)

    def bucket_status(self, bucket_key: str) -> tuple[str, CalibrationPromotion | None]:
        """Authoritative D4 status for a bucket: the promotion derived
        from the MOST evidence wins ties by (n_observations, route,
        generation) — deterministic, and never stronger than the
        evidence that produced it. No promotion ⇒ ``"unvalidated"``
        (candidate-only)."""
        promos = [p for p in self.iter_promotions() if p.bucket_key == bucket_key]
        if not promos:
            return "unvalidated", None
        best = max(
            promos,
            key=lambda p: (
                p.level == "validated",
                p.n_observations,
                p.derived_from_generation,
                p.promotion_id,
            ),
        )
        return best.level, best

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
        promo_ids = _collect(
            self._promo_dir,
            lambda p: CalibrationPromotion.model_validate_json(p.read_text()).promotion_id,
        )
        # A promotion whose sources did not survive rebuild would cite
        # evidence the registry no longer holds — dropped and reported.
        kept_promotions: list[str] = []
        for pid in promo_ids:
            promo = CalibrationPromotion.model_validate_json(
                (self._promo_dir / f"{_digest_of(pid)}.json").read_text()
            )
            orphaned = [s for s in promo.source_observation_ids if s not in obs_ids]
            if orphaned:
                rejected.append(
                    f"{_digest_of(pid)}.json: promotion cites missing observations {orphaned}"
                )
            else:
                kept_promotions.append(pid)

        def _mutate(m: RegistryManifest) -> bool:
            m.observation_ids = sorted(obs_ids)
            m.hardware_profile_ids = sorted(hw_ids)
            m.environment_profile_ids = sorted(env_ids)
            m.promotion_ids = sorted(kept_promotions)
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
        self,
        obs: CalibrationObservation,
        *,
        current_environment_id: str,
        validation_level: str | None = None,
        request: CandidateRequest | None = None,
    ) -> RuntimeEstimate:
        """Wrap an observation as decision evidence. Evidence collected in
        a DIFFERENT execution environment is demoted to
        ``historical_observation_prior`` (tier 1 — never blocking alone),
        even under an identical hardware compatibility profile.

        C7: authority comes from the bucket's PROMOTION record, not from
        the (immutable, always-``unvalidated``) observation — observations
        are never mutated, so promotion is the only status source.
        ``validation_level`` overrides the lookup for callers that already
        resolved it; only ``"validated"`` keeps measured provenance
        (``"provisional"`` is explicitly not calibration-authoritative).

        C-C5a: a validated local bucket is NECESSARY but NOT SUFFICIENT.
        ``request`` names the concrete candidate this estimate is for, and
        measured authority additionally requires an exact identity match and
        applicability to that candidate. Omitting ``request`` fails closed --
        this method must not be able to hand back blocking authority that
        nobody checked, on the assumption a caller will remember to check it
        separately."""
        from core.runtime_control.calibration_policy import ApplicabilityEnvelope, bucket_key

        level = validation_level
        key = bucket_key(obs)
        if level is None:
            level, _ = self.bucket_status(key)
        local = obs.execution_environment_id == current_environment_id
        seconds = obs.measured_value_ms / 1000.0

        authority = NO_CANDIDATE
        if local and level == "validated":
            # The envelope describes what this bucket actually observed, so
            # it is derived from the bucket's own records -- never from the
            # single observation being wrapped, which is a point rather than
            # a range.
            siblings = [o for o in self.iter_observations() if bucket_key(o) == key]
            authority = evaluate_candidate_authority(
                obs,
                request,
                # Dimensions come from what the bucket ACTUALLY recorded, not
                # from a fixed list. Two producers spell the workload
                # differently -- C-C3c derived records carry `seg_size`
                # (`DERIVED_WORKLOAD_DIMENSIONS`), probe records carry
                # `segment_length` -- so any hardcoded vocabulary silently
                # finds no range for one of them, fails closed on it, and
                # never matches. Fail-closed is correct; never matching is
                # indistinguishable from an empty registry.
                envelope=ApplicabilityEnvelope.from_observations(
                    siblings, dimensions=_measured_dimensions(siblings)
                )
                if siblings
                else None,
            )
            if authority.granted:
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
        if local and level == "validated" and not authority.granted:
            warnings.append(
                "validated bucket is not applicable to this candidate: "
                + "; ".join(authority.reasons)
            )
        if not local:
            warnings.append(
                "cross-machine observation (different execution environment): "
                "historical prior only — requires local live validation for "
                "blocking authority (§3.3)"
            )
        if level != "validated":
            warnings.append(
                f"bucket validation level={level!r} (D4: only 'validated' is "
                "calibration-authoritative)"
            )
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
