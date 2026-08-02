"""Why a GPU phase ran out of memory (V20 PR B, B-C3a).

Generic runtime infrastructure. It returns a typed outcome and an
authority flag; it never prescribes a parameter change. What the
authority *means* to a scientist is the task layer's business, and
putting that sentence here is how a signal about one task ends up in a
framework.

**Why a counterfactual and not a threshold.** V19 told an agent to
shrink a candidate that was never too large, because a CUDA OOM raised
while a neighbouring chain held the card was read as a statement about
the candidate. The obvious fix — "if the other side held more than X,
call it contention" — replaces one unjustified constant with another.
The question is answerable instead:

    would this allocation have fitted had the other occupancy not been
    there?

That needs the size that was actually attempted, so a framework-specific
adapter supplies ``attempted_allocation_mib`` and this module consumes
it. Without it the answer is ``unknown``, which is the point: a wrong
``unknown`` costs one piece of feedback, while a wrong candidate verdict
tells the agent to shrink something that was the right size.

**Why unattributed memory is an interval, not a rounding error.** The
driver reports how much of the device is in use; the per-process query
reports who is using it. The two do not have to agree, and the
difference — ``unattributed_mib`` — belongs to nobody in particular:
driver context, a graphics client, or a process the query could not
attribute. Charging it to the candidate silently manufactures the V19
verdict; crediting it to the peers silently manufactures the opposite.
So it is carried as a band, and the candidate may only be blamed when
the allocation fails even under the reading most favourable to it —
that every unattributed byte belonged to somebody else.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.runtime_control.gpu_observer import GpuEvidenceBundle

#: Frozen vocabulary. Exactly one member carries downsizing authority.
FailureAttribution = Literal[
    "candidate_gpu_capacity",
    "gpu_contention",
    "host_memory_pressure",
    "external_termination",
    "unknown",
]

#: The single member that may tell a caller the candidate was too large.
_MAY_RECOMMEND_REDUCTION: frozenset[str] = frozenset({"candidate_gpu_capacity"})

#: How many steady sampling intervals may separate the last valid sample
#: from the child's end before that sample stops describing the failure.
#: Derived from the run's own observation policy, never from a wall-clock
#: constant — if no policy was recorded, freshness is unestablished and
#: the verdict is ``unknown``.
_FRESHNESS_INTERVALS = 3

_TRIED_TO_ALLOCATE = re.compile(
    r"Tried to allocate\s+([0-9]+(?:\.[0-9]+)?)\s*(KiB|MiB|GiB|TiB)", re.IGNORECASE
)
_UNIT_TO_MIB = {"kib": 1 / 1024, "mib": 1.0, "gib": 1024.0, "tib": 1024.0 * 1024.0}

_CUDA_OOM_MARKERS = ("cuda out of memory", "outofmemoryerror", "cuda error: out of memory")


class AttributionResult(BaseModel):
    """A verdict, its authority, and everything it was derived from."""

    model_config = ConfigDict(frozen=True)

    attribution: FailureAttribution
    #: True only for ``candidate_gpu_capacity``. Enforced by a validator
    #: rather than left to the caller, so a new outcome cannot quietly
    #: acquire the right to tell an agent to shrink a candidate.
    may_recommend_resource_reduction: bool
    #: Why this verdict and not another, in one sentence.
    reason: str
    #: Every figure the decision used, so it is auditable rather than
    #: asserted. Absent keys mean the quantity was unavailable.
    #:
    #: ``frozen=True`` protects the verdict fields; it does not deep-
    #: freeze this dict. Treat it as a record to read, not a surface to
    #: mutate.
    evidence: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, _ctx: Any) -> None:
        expected = self.attribution in _MAY_RECOMMEND_REDUCTION
        if self.may_recommend_resource_reduction != expected:
            raise ValueError(
                f"{self.attribution!r} may_recommend_resource_reduction must be "
                f"{expected}. Only {sorted(_MAY_RECOMMEND_REDUCTION)} may tell a "
                "caller the candidate was too large."
            )


def may_recommend_resource_reduction(attribution: str) -> bool:
    """Authority for an outcome, for callers holding only the string.

    An unrecognised string is denied authority rather than raising: the
    safe direction for a caller that has read a legacy record.
    """
    return attribution in _MAY_RECOMMEND_REDUCTION


def extract_attempted_allocation_mib(text: str | None) -> float | None:
    """Best-effort ``Tried to allocate N GiB`` out of a failure message.

    Framework-specific by nature, and deliberately confined here: the
    attribution function itself parses nothing, so a change in one
    framework's wording cannot reach the decision logic.

    Returns ``None`` when the size is not stated — which the caller must
    treat as unknown, never as zero. Byte-valued and thousands-separated
    forms are not supported and also yield ``None``.
    """
    if not text:
        return None
    match = _TRIED_TO_ALLOCATE.search(text)
    if match is None:
        return None
    try:
        value = float(match.group(1))
    except ValueError:  # pragma: no cover - guarded by the pattern
        return None
    return value * _UNIT_TO_MIB[match.group(2).lower()]


def looks_like_cuda_oom(text: str | None) -> bool:
    """Whether the message credibly reports a device-side OOM.

    Host ``MemoryError`` and a bare non-zero exit are deliberately not
    matched: neither says anything about the device.

    Substring matching, so a sentence that *mentions* a device OOM
    without reporting one would match. Callers pass captured child
    stderr, where that does not arise; it is not a general-purpose
    classifier.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _CUDA_OOM_MARKERS)


def _unknown(reason: str, evidence: dict[str, Any] | None = None) -> AttributionResult:
    return AttributionResult(
        attribution="unknown",
        may_recommend_resource_reduction=False,
        reason=reason,
        evidence=evidence or {},
    )


def _normalize_bundle(bundle: Any) -> tuple[GpuEvidenceBundle | None, str | None]:
    """Coerce the caller's evidence into the typed model, or explain why not.

    A record-shaped ``dict`` is re-validated rather than read with
    ``getattr``: ``coverage_is_thin`` is a computed property and is
    absent from ``model_dump()``, so attribute access against a raw dict
    would silently refuse every bundle and look like healthy caution.
    Re-validating recomputes it. It also makes a field rename fail
    loudly instead of widening a bound.
    """
    if bundle is None:
        return None, "no GPU evidence bundle was captured"
    if isinstance(bundle, GpuEvidenceBundle):
        return bundle, None
    if isinstance(bundle, Mapping):
        try:
            return GpuEvidenceBundle.model_validate(dict(bundle)), None
        except ValidationError as exc:
            return None, f"the evidence bundle did not validate ({exc.error_count()} error(s))"
    return None, f"the evidence bundle is a {type(bundle).__name__}, not GpuEvidenceBundle"


def _bundle_diagnostics(bundle: GpuEvidenceBundle) -> dict[str, Any]:
    """Telemetry-health figures, recorded whatever the verdict.

    A refusal that records nothing cannot be distinguished later from a
    refusal that was wrong, so the health of the evidence travels with
    every outcome — not only the ones that reached the arithmetic.
    """
    return {
        "valid_sample_count": bundle.valid_sample_count,
        "failed_sample_count": bundle.failed_sample_count,
        "child_runtime_ms": bundle.child_runtime_ms,
        "last_valid_offset_ms": bundle.last_valid_offset_ms,
        "observer_error": bundle.observer_error,
        "observer_join_timed_out": bundle.observer_join_timed_out,
        "coverage_is_thin": bundle.coverage_is_thin,
    }


def _gate_evidence_quality(bundle: GpuEvidenceBundle) -> str | None:
    """The reason a GPU verdict is not permitted, or ``None`` if it is.

    Every condition is required. ``coverage_is_thin`` is mandatory but
    not sufficient on its own: a bundle can be thick and still describe
    the wrong device, rest on telemetry that raised, or end long before
    the failure did.
    """
    if bundle.observer_error is not None:
        return f"the observer itself failed ({bundle.observer_error})"
    if bundle.observer_join_timed_out:
        return "the observer did not stop within its join timeout, so its samples are unbounded"
    if bundle.coverage_is_thin:
        return "sampling coverage is too thin to support a verdict"

    baseline = bundle.baseline_before_spawn
    peak = bundle.observed_peak
    last = bundle.last_while_alive
    if baseline is None:
        return "no pre-spawn baseline was captured"
    if peak is None:
        return "no observed peak was captured"
    if last is None:
        return "no sample was taken while the child was alive"

    for label, snap in (("baseline", baseline), ("peak", peak), ("last", last)):
        if not snap.telemetry_available:
            return f"telemetry was unavailable for the {label} snapshot"

    uuids = {snap.device.uuid for snap in (baseline, peak, last)}
    if bundle.device is not None:
        uuids.add(bundle.device.uuid)
    if len(uuids) != 1:
        return f"snapshots describe different devices ({sorted(uuids)})"

    if bundle.sampling_policy is None:
        return "no observation policy was recorded, so sample freshness cannot be established"
    if bundle.child_runtime_ms is None or bundle.last_valid_offset_ms is None:
        return (
            "the child runtime or the last-sample offset was not recorded, so sample "
            "freshness cannot be established"
        )
    freshness_ms = _FRESHNESS_INTERVALS * bundle.sampling_policy.steady_interval_ms
    staleness_ms = bundle.child_runtime_ms - bundle.last_valid_offset_ms
    if staleness_ms > freshness_ms:
        return (
            f"the last valid sample is {staleness_ms:.0f} ms before the child ended, "
            f"beyond the {freshness_ms:.0f} ms freshness bound"
        )
    return None


def attribute_gpu_failure(
    *,
    bundle: Any,
    attempted_allocation_mib: float | None,
    failure_text: str | None = None,
) -> AttributionResult:
    """Classify a device-memory failure by counterfactual.

    Args:
        bundle: the B-C2b evidence bundle for the failed phase, either a
            ``GpuEvidenceBundle`` or a mapping that validates as one.
        attempted_allocation_mib: the size the framework tried to
            allocate. ``None`` yields ``unknown`` — this is the
            quantity the counterfactual turns on.
        failure_text: the child's message, used only to confirm the
            failure really was a device OOM.

    The decision is an interval, because unattributed device memory has
    no owner::

        current_free                 = total - used
        free_without_known_other     = current_free + other
        free_without_all_possible_other
                                     = free_without_known_other + unattributed

        attempted <= current_free                  -> unknown
        .. <= free_without_known_other             -> gpu_contention
        .. <= free_without_all_possible_other      -> unknown
        attempted >  free_without_all_possible_other
                                                   -> candidate_gpu_capacity

    Only the last case blames the candidate, and it holds even under the
    reading most favourable to it: that every unattributed byte belonged
    to somebody else.
    """
    if not looks_like_cuda_oom(failure_text):
        return _unknown(
            "the failure does not carry credible CUDA out-of-memory evidence",
            {"failure_text_present": failure_text is not None},
        )

    typed, problem = _normalize_bundle(bundle)
    if typed is None:
        return _unknown(problem or "the evidence bundle is unusable")

    diagnostics = _bundle_diagnostics(typed)
    blocked = _gate_evidence_quality(typed)
    if blocked is not None:
        return _unknown(blocked, diagnostics)

    if attempted_allocation_mib is None:
        return _unknown(
            "the attempted allocation size is unknown, so the counterfactual cannot be evaluated",
            diagnostics,
        )

    last = typed.last_while_alive
    if last is None:  # pragma: no cover - the gate above established this
        return _unknown("no sample was taken while the child was alive", diagnostics)
    total = last.device_total_mib
    used = last.device_used_mib
    other = last.other_mib
    if total is None or used is None or other is None:
        return _unknown("the final snapshot is missing device or occupancy figures", diagnostics)
    if used > total:
        return _unknown(
            f"the device reports {used} MiB used of {total} MiB total, which cannot "
            "be true; the telemetry is inconsistent",
            diagnostics | {"device_total_mib": total, "device_used_mib": used},
        )

    unattributed = last.unattributed_mib
    current_free = total - used
    free_without_known_other = current_free + other

    peak = typed.observed_peak
    evidence = diagnostics | {
        "attempted_allocation_mib": attempted_allocation_mib,
        "device_total_mib": total,
        "device_used_mib": used,
        "other_mib": other,
        "unattributed_mib": unattributed,
        "accounting_skew_mib": last.accounting_skew_mib,
        "current_free_mib": current_free,
        "free_without_known_other_mib": free_without_known_other,
        "own_tree_mib": last.own_tree_mib,
        "observed_peak_mib": peak.own_tree_mib if peak is not None else None,
        "device_uuid": last.device.uuid,
        "freshness_bound_ms": (
            _FRESHNESS_INTERVALS * typed.sampling_policy.steady_interval_ms
            if typed.sampling_policy is not None
            else None
        ),
    }

    if attempted_allocation_mib <= current_free:
        return _unknown(
            "the allocation should have fitted in the free memory observed, so "
            "the cause is unobserved — allocator fragmentation, sampling skew, "
            "or something else. Guessing here is how a candidate gets blamed "
            "for someone else's problem",
            evidence,
        )

    if attempted_allocation_mib <= free_without_known_other:
        return AttributionResult(
            attribution="gpu_contention",
            may_recommend_resource_reduction=False,
            reason=(
                f"{attempted_allocation_mib:.0f} MiB did not fit in {current_free} MiB "
                f"free, but would have fitted in {free_without_known_other} MiB had the "
                f"other {other} MiB not been held. The candidate was not too large."
            ),
            evidence=evidence,
        )

    if unattributed is None:
        return _unknown(
            "the device reports no unattributed-memory figure, so the reading most "
            "favourable to the candidate cannot be evaluated, and blaming it would "
            "rest on an assumption rather than a measurement",
            evidence,
        )

    free_without_all_possible_other = free_without_known_other + unattributed
    evidence = evidence | {"free_without_all_possible_other_mib": free_without_all_possible_other}

    if attempted_allocation_mib <= free_without_all_possible_other:
        return _unknown(
            f"{attempted_allocation_mib:.0f} MiB did not fit in the "
            f"{free_without_known_other} MiB attributable to others, but would have "
            f"fitted in {free_without_all_possible_other} MiB if the {unattributed} MiB "
            "the driver could not attribute belonged to somebody else. Who owns that "
            "memory decides the verdict, and it is not known",
            evidence,
        )

    return AttributionResult(
        attribution="candidate_gpu_capacity",
        may_recommend_resource_reduction=True,
        reason=(
            f"{attempted_allocation_mib:.0f} MiB did not fit even under the reading "
            f"most favourable to the candidate, in which all {other} MiB attributed "
            f"elsewhere and all {unattributed} MiB the driver could not attribute "
            f"belonged to somebody else ({free_without_all_possible_other} MiB). "
            "Removing the other occupancy would not have saved it."
        ),
        evidence=evidence,
    )


def attribute_process_termination(
    *,
    returncode: int | None,
    host_memory_evidence: bool = False,
    external_signal_evidence: bool = False,
    failure_text: str | None = None,
) -> AttributionResult:
    """Classify a kill, which a signal number alone cannot do.

    ``returncode == -9`` is compatible with a kernel OOM kill, an
    external quota watchdog, an operator, and other terminations. It is
    recorded as evidence but is never a discriminator: this function
    branches only on the two corroboration flags. The existing
    ``oom_host_ram`` status is likewise *evidence*, not a verdict to
    inherit, because it may itself have been derived from ``-9``.
    """
    evidence = {
        "returncode": returncode,
        "host_memory_evidence": host_memory_evidence,
        "external_signal_evidence": external_signal_evidence,
        "failure_text_present": failure_text is not None,
    }
    if host_memory_evidence and not external_signal_evidence:
        return AttributionResult(
            attribution="host_memory_pressure",
            may_recommend_resource_reduction=False,
            reason="host memory exhaustion is corroborated by RSS/cgroup evidence",
            evidence=evidence,
        )
    if external_signal_evidence and not host_memory_evidence:
        return AttributionResult(
            attribution="external_termination",
            may_recommend_resource_reduction=False,
            reason="the process was terminated by a watchdog, quota or operator",
            evidence=evidence,
        )
    if host_memory_evidence and external_signal_evidence:
        return _unknown(
            "host-pressure and external-termination evidence disagree; a kill "
            "explained two ways is not explained",
            evidence,
        )
    return _unknown(
        "a signal alone does not identify a cause — a kernel OOM kill, a quota "
        "watchdog and an operator stop are indistinguishable by return code",
        evidence,
    )
