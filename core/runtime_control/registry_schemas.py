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
from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import PredictionSource

#: Bumped to 2.0.0 by V20 PR C1 / C-C2b. The version is INSIDE every
#: record's content hash (``hash_payload`` dumps the whole model), so a
#: bump is indistinguishable from corruption to a loader reading the old
#: tree -- which is exactly why operator decision O-1 gives each major
#: version its own tree rather than migrating in place. See
#: ``calibration_registry.default_registry_root``.
REGISTRY_SCHEMA_VERSION = "2.0.0"

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


# ── V20 PR C1 / C-C2: the v2 identity model ─────────────────────────────────
#
# The v1 bucket key (`calibration_policy.bucket_components`) put identity,
# applicability and policy into one seven-part string. Three consequences,
# each measured on the live registry during the PR C audit:
#
#   * a matching bucket READ as applicability, when it is only a candidate
#     set that still has to be checked;
#   * `task` and `data_shape_class` were absent entirely, while the registry
#     lives at one per-user root -- so two different tasks with the same
#     family, hardware and stack shared a bucket;
#   * the device INSTANCE was absent: `hardware_compatibility_id` describes a
#     model of GPU, not the card. A 5090 measurement could speak for another
#     5090, and (with a matching profile) for an H100-class entry.
#
# So identity is separated from applicability and from policy:
#
#   MeasurementIdentity    WHO this measurement is about.  Exact match.
#   ApplicabilityEnvelope  WHO ELSE it may speak for.      Bounded ranges.
#   CalibrationPolicy      WHEN it becomes trustworthy.    Configured.
#
# This module owns the first. The envelope and the policy live in
# `calibration_policy.py` beside the rules that read them.

#: What a measurement measures. A first-class identity dimension, so a
#: promoted millisecond can never answer a memory query -- the failure the
#: PR C audit found when the ladder assumed the calibration registry could
#: supply PR B's `requirement_mib`. It cannot: it stores `measured_value_ms`.
#:
#: Deliberately NOT declared: `gpu_allocated` and `gpu_reserved`. Allocated
#: has exactly one production call site and is an in-process allocator view;
#: reserved has no producer anywhere. Declaring a kind nothing emits is how
#: `IsolatedProbeResult.cuda_peak_allocated_gb` came to exist as a field that
#: reads like a measurement and is never written.
MeasurementKind = Literal[
    "duration",
    "gpu_requirement",
    "host_memory",
]

#: Family value meaning "we could not classify this". First-class -- never
#: the nearest known family -- and never authoritative (frozen invariant,
#: PR C design §8.A).
UNKNOWN_MODEL_FAMILY = "unknown"


class MeasurementIdentity(BaseModel):
    """Exact-match identity of a measurement: WHO it is about.

    Every field here is compared for equality. Nothing in this model is a
    range, a threshold or a tolerance -- those are the envelope's and the
    policy's job. If two measurements differ in any field below, they are
    about different things and may not substitute for one another.

    `extra="forbid"` because a silently-absorbed field would be an identity
    dimension nobody compares.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    measurement_kind: MeasurementKind
    #: Which task this measurement was taken for. Absent from v1 entirely,
    #: which is only safe if one account runs one task.
    task_identity: str = Field(min_length=1)
    #: The data-shape class the measurement was taken under. Not the dataset
    #: path: a shape class is what makes two datasets interchangeable for
    #: resource purposes.
    data_shape_class: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    #: Full candidate configuration, content-hashed. `model_family` alone
    #: cannot separate two candidates of the same family with materially
    #: different configs.
    candidate_config_hash: str = Field(min_length=1)
    #: The framework's five-phase vocabulary, not the registry's legacy
    #: four-value `ObservationOperation`. Nothing loses meaning: `io` is
    #: declared there and produced nowhere, while `scoring` and
    #: `orchestration` are real phases v1 could not express.
    phase: RuntimePhase
    #: The device INSTANCE, not its model. `hardware_compatibility_id`
    #: describes a class of card; two 5090s in one host are not the same
    #: device, and a measurement from one is not authoritative for the other.
    hardware_uuid: str = Field(min_length=1)
    #: `stack_identity(...)` digest of the software stack.
    runtime_stack_identity: str = Field(min_length=1)

    @property
    def family_is_known(self) -> bool:
        """False when the family could not be classified.

        Callers must not treat an unknown-family measurement as
        authoritative (frozen invariant §8.A). Exposed as a property rather
        than enforced by a validator because the RECORD is legitimate --
        it is evidence, and quarantining it is O-2's job; what is forbidden
        is granting it authority.
        """
        return self.model_family != UNKNOWN_MODEL_FAMILY

    def components(self) -> tuple[str, ...]:
        """Ordered identity components, stack LAST.

        Mirrors `bucket_components`' convention so drift analysis can group
        by `components()[:-1]` -- same everything, different stack.
        """
        return (
            self.measurement_kind,
            self.task_identity,
            self.data_shape_class,
            self.model_family,
            self.candidate_config_hash,
            self.phase,
            self.hardware_uuid,
            self.runtime_stack_identity,
        )

    @property
    def identity_key(self) -> str:
        return "|".join(self.components())
