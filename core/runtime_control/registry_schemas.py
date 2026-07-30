"""Versioned typed schemas for the calibration registry (C5).

Operator-approved design (runtime_estimation_and_calibration.md §10 +
the C5 approval with hardware-identity amendment):

* content-addressed identities persist the FULL digest
  (``sha256:<64 hex>``); 12-char prefixes are display-only;
* TWO separate hardware concepts: the *hardware compatibility profile*
  (technical comparability — never hostname) and the *execution
  environment profile* (where an observation was actually collected —
  stable installation UUID, never hostname). Identical compatibility
  profiles admit cross-machine observations as HISTORICAL PRIORS ONLY;
  formal-blocking authority requires local live validation (C7 policy);
* observations are immutable records; training and inference stay
  distinct records; the legacy hard-coded inference batch fallback can
  never masquerade as a measured observation (schema-enforced:
  ``measured_value_ms`` must be a real measurement and the producer
  identity is required);
* timestamps are METADATA — excluded from the content hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.estimate_types import ConcurrencyIdentity
from core.runtime_control.identity import _canonicalize
from core.runtime_control.records import PredictionSource

REGISTRY_SCHEMA_VERSION = "1.0.0"

ObservationOperation = Literal["setup", "training", "inference", "io"]
#: D4 lifecycle (operator, 2026-07-30): "unvalidated" IS the candidate
#: stage; promotions to provisional/validated are DERIVED records
#: (CalibrationPromotion) — observations are never mutated in place.
ValidationStatus = Literal["validated", "provisional", "unvalidated", "rejected"]


def content_id(payload: dict[str, Any]) -> str:
    """Authoritative content address: ``sha256:<64 lowercase hex>`` over
    the canonical JSON payload (sorted keys, UTF-8; sets rejected)."""
    canonical = _canonicalize(payload)
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def display_id(full_id: str) -> str:
    """Human-readable alias: scheme + first 12 hex chars + ellipsis."""
    scheme, _, digest = full_id.partition(":")
    return f"{scheme}:{digest[:12]}…"


class HardwareCompatibilityProfile(BaseModel):
    """Technical-comparability identity (§3.1 of the C5 approval).

    NO hostname, NO machine-instance identity — two machines with the
    same accelerator + stack share this profile, which admits their
    observations as historical priors for each other (never more)."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    accelerator_vendor: str
    accelerator_model: str
    gpu_count: int = Field(ge=1)
    vram_gb: float = Field(gt=0.0)
    compute_capability: str | None = None
    driver_version: str | None = None
    cuda_version: str | None = None
    torch_version: str | None = None
    dtypes: tuple[str, ...] = ()
    mig_or_virtualization_mode: str | None = None
    kernel_backend_identity: str | None = None

    @property
    def profile_id(self) -> str:
        return content_id(self.model_dump(mode="json"))


class ExecutionEnvironmentProfile(BaseModel):
    """Where an observation was actually collected (§3.2).

    ``installation_id`` is a locally generated stable UUID (never a
    hostname). Observations from a DIFFERENT execution environment —
    even with an identical compatibility profile — enter as historical
    priors only (§3.3 cross-machine authority rule)."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    hardware_compatibility_id: str
    installation_id: str
    gpu_power_limit_w: float | None = None
    clock_policy: str | None = None
    accelerator_topology: str | None = None
    cpu_model: str | None = None
    cpu_count: int | None = None
    ram_gb: float | None = None
    storage_class: str | None = None
    container_context: str | None = None
    concurrency_regime: ConcurrencyIdentity | None = None

    @property
    def profile_id(self) -> str:
        return content_id(self.model_dump(mode="json"))


class CalibrationObservation(BaseModel):
    """One immutable validated-or-pending calibration observation.

    The content hash covers every semantically meaningful field;
    ``timestamp_metadata`` is EXCLUDED (metadata, not measured content).
    ``validation_status`` IS included: a later validation change is a
    NEW record superseding the old identity, never an in-place edit."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    operation: ObservationOperation
    measurement_unit: str
    measured_value_ms: float = Field(gt=0.0)
    workload: dict[str, Any] = Field(default_factory=dict)
    realized_model: dict[str, Any] = Field(
        default_factory=dict,
        description="Realized (recomputed) model properties (§16.7) — "
        "never LLM-authored estimates.",
    )
    model_family: str = Field(
        default="unknown",
        min_length=1,
        description="D5: explicit family from implementation metadata or "
        "deterministic structural features ONLY — never the nearest known "
        "family. 'unknown' is a first-class value; unknown-family "
        "candidates never inherit known-family calibration authority "
        "(bucket separation).",
    )
    hardware_compatibility_id: str
    execution_environment_id: str
    concurrency_identity: ConcurrencyIdentity
    contention_telemetry: dict[str, Any] = Field(default_factory=dict)
    software_stack: dict[str, Any] = Field(default_factory=dict)
    producer_identity: str = Field(
        min_length=1,
        description="Identity of the measuring producer (probe/verifier "
        "component identity) — REQUIRED: an observation without a real "
        "producer is not a measurement.",
    )
    provenance: PredictionSource
    uncertainty_inputs: dict[str, Any] = Field(default_factory=dict)
    source_run: dict[str, Any] = Field(default_factory=dict)
    validation_status: ValidationStatus = Field(
        default="unvalidated",
        description="Producer-declared status ONLY. C7/D4: calibration "
        "authority is read from the bucket's CalibrationPromotion record "
        "(observations are immutable, so this field can never be raised "
        "in place) — never trust it as authority.",
    )
    timestamp_metadata: str | None = Field(
        default=None, description="Excluded from the content hash."
    )

    @model_validator(mode="after")
    def _measured_provenance_only(self) -> CalibrationObservation:
        from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES

        if self.provenance not in MEASUREMENT_BACKED_SOURCES:
            raise ValueError(
                f"a CalibrationObservation records a MEASUREMENT; provenance "
                f"{self.provenance!r} is a prior — priors (incl. the legacy "
                "inference-batch fallback) can never be stored as measured "
                "observations"
            )
        return self

    def hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("timestamp_metadata", None)
        return payload

    @property
    def observation_id(self) -> str:
        return content_id(self.hash_payload())


class LegacySourceReference(BaseModel):
    """Read-only reference to a legacy k-table artifact (§5): identified
    by content hash, never modified, adapted evidence stamped legacy."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    kind: Literal["legacy_k_table"] = "legacy_k_table"
    gpu_slug: str
    file_sha256: str
    adapter_version: str
    entry_count: int = Field(ge=0)


class CalibrationSummary(BaseModel):
    """DERIVED applicability view (§4 of the C5 approval) — a rebuildable
    cache, never the source of truth. Records its exact sources and the
    registry generation it was derived from; staleness is detected by
    comparing both against the live manifest."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    derived_from_generation: int
    source_observation_ids: tuple[str, ...]
    operation: ObservationOperation | None = None
    parameter_count_range: tuple[int, int] | None = None
    batch_size_range: tuple[int, int] | None = None
    segment_length_range: tuple[int, int] | None = None
    sample_count: int = Field(ge=0)
    concurrency_identities: tuple[ConcurrencyIdentity, ...] = ()
    hardware_compatibility_ids: tuple[str, ...] = ()
    execution_environment_ids: tuple[str, ...] = ()
    newest_timestamp: str | None = None


class CalibrationPromotion(BaseModel):
    """D4 deterministic promotion record — a DERIVED, immutable record
    naming its source observations; the authoritative status source for
    a bucket. Never mutates observations."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = REGISTRY_SCHEMA_VERSION
    bucket_key: str
    level: Literal["provisional", "validated"]
    source_observation_ids: tuple[str, ...] = Field(min_length=2)
    consistency_ratio: float = Field(gt=0.0)
    n_observations: int = Field(ge=2)
    rate_median_ms: float = Field(gt=0.0)
    rate_min_ms: float = Field(gt=0.0)
    rate_max_ms: float = Field(gt=0.0)
    policy_identity: str
    derived_from_generation: int = Field(ge=0)
    validation_route: Literal["consistency", "verification_agreement"]
    timestamp_metadata: str | None = Field(default=None)

    def hash_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("timestamp_metadata", None)
        return payload

    @property
    def promotion_id(self) -> str:
        return content_id(self.hash_payload())


class RegistryManifest(BaseModel):
    """Compact index + schema entry point (registry.json). Rebuildable
    from the record files; ``generation`` increments on every committed
    index write (stale-cache detection anchor)."""

    schema_version: str = REGISTRY_SCHEMA_VERSION
    generation: int = Field(default=0, ge=0)
    observation_ids: list[str] = Field(default_factory=list)
    hardware_profile_ids: list[str] = Field(default_factory=list)
    environment_profile_ids: list[str] = Field(default_factory=list)
    legacy_sources: list[LegacySourceReference] = Field(default_factory=list)
    promotion_ids: list[str] = Field(default_factory=list)
