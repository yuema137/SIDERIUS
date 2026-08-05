"""REQUEST_PROBE resolution lifecycle (C9b).

The C8 closure audit found that `REQUEST_PROBE` was a decision the system
could REACH but never RESOLVE: no production caller ran a bounded probe,
so a formal decision either proceeded on prior-tier evidence or waited
for evidence that would never arrive. This module is the missing edge:

```text
REQUEST_PROBE
  -> invoke the bounded probe EXACTLY ONCE
  -> persist the observation(s)
  -> rebuild the estimate from the measurement
  -> re-run the policy
  -> ALLOW / REJECT / ABORT
```

Operator-approved rules (2026-07-30), each enforced here and tested:

* no continuation into execution before the probe resolves;
* no authoritative static fallback — if the probe cannot produce
  evidence, the answer is ABORT, never "proceed on the prior";
* a second REQUEST_PROBE after a completed probe is an INVARIANT
  FAILURE, not a retry: it becomes ABORT (this is what makes an
  unresolved probe loop structurally impossible);
* probe infrastructure failure (load failure, executor construction,
  registry write, telemetry gap that prevents classification) -> ABORT;
* measured candidate failure (OOM, wall-cap) -> REJECT.

Everything heavy is INJECTED: the probe runner, the registry writer and
the clock. Unit tests drive the whole lifecycle with fakes; the
production wiring supplies the real bounded probe (`run_bounded_probe`
with `production_probe_executors`) and the real registry.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecision,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.estimate_types import RuntimeEstimate
from core.runtime_control.probe import ProbeResult, extrapolate_probe


#: Raised by an injected runner when the probe could not be ATTEMPTED —
#: as opposed to a probe that ran and measured a failure. The distinction
#: is the whole point: the first is our infrastructure, the second is the
#: candidate.
class ProbeInfrastructureError(RuntimeError):
    """The evidence channel failed; no statement about the candidate."""


class ProbeRequest(BaseModel):
    """What the lifecycle needs to run and price one bounded probe."""

    model_config = ConfigDict(frozen=True)

    model_identity: str
    train_steps: int = Field(ge=0)
    inference_batches: int = Field(ge=0)
    workload: dict[str, Any] = Field(default_factory=dict)
    model_family: str = "unknown"


class ProbeResolution(BaseModel):
    """The outcome of resolving one REQUEST_PROBE."""

    model_config = ConfigDict(frozen=True)

    decision: RuntimeDecision
    probe_ran: bool
    probe_status: str | None = None
    observation_ids: tuple[str, ...] = ()
    estimate: RuntimeEstimate | None = None


class ProbeResolver:
    """Resolves REQUEST_PROBE decisions for ONE candidate attempt.

    Stateful by design: it remembers whether the probe has already run for
    this attempt, which is what turns a would-be loop into an explicit
    invariant failure. One resolver per candidate attempt.
    """

    def __init__(
        self,
        *,
        policy: RuntimeDecisionPolicy,
        run_probe: Callable[[ProbeRequest], ProbeResult],
        persist: Callable[[ProbeResult, ProbeRequest], tuple[str, ...]] | None = None,
        producer_identity: str = "runtime_probe_lifecycle@1.0.0",
    ) -> None:
        self._policy = policy
        self._run_probe = run_probe
        self._persist = persist
        self._producer_identity = producer_identity
        self._probe_completed = False

    @property
    def probe_completed(self) -> bool:
        return self._probe_completed

    def resolve(
        self,
        request: ProbeRequest,
        *,
        budget: RuntimeBudget,
        mode: RuntimeMode,
    ) -> ProbeResolution:
        """Run the probe once and re-decide from its measurement."""
        if self._probe_completed:
            # A second REQUEST_PROBE after a completed probe means the
            # re-decision did not consume the measurement. Retrying would
            # spin forever, so this is an invariant failure, not a retry.
            return self._abort(
                "REQUEST_PROBE issued again after a probe already completed for this "
                "candidate — the re-decision did not consume the measured evidence "
                "(invariant failure, not a retry)"
            )

        try:
            result = self._run_probe(request)
        except ProbeInfrastructureError as exc:
            return self._abort(f"probe could not be attempted: {exc}")
        except Exception as exc:  # unexpected: still an evidence-channel failure
            return self._abort(f"probe raised an unexpected error: {exc!r}")
        finally:
            # Marked even on failure: one attempt gets one probe. A failed
            # probe is answered by ABORT/REJECT, never by probing again.
            self._probe_completed = True

        # The probe budget for this attempt is now SPENT, and every
        # re-decision below must be told so.
        #
        # Why this matters (Gate 2 attempt 1, 2026-08-05): the re-decision
        # used to run with the ORIGINAL mode, in which `probe_available` was
        # still True. Two of the policy's three `REQUEST_PROBE` producers are
        # gated on exactly that flag:
        #
        #   decision_policy.py:346  contended measurement + probe_available
        #   decision_policy.py:347  prior-tier evidence  + probe_available
        #
        # so a freshly measured probe that was ITSELF classified contended
        # re-entered producer 346 and asked for another probe — which the
        # invariant below then reported as "the measured evidence was not
        # consumed". The evidence HAD been consumed; the policy was simply
        # never told the budget was gone, and the diagnosis blamed the wrong
        # component.
        #
        # With the budget marked spent, both producers take their EXISTING
        # `else ADVISORY` branch, and the third producer (line 309) cannot
        # fire because it requires `evidence_channel == "probe_absent"` while
        # the re-decision passes "ok". A `REQUEST_PROBE` after a completed
        # probe therefore becomes structurally impossible rather than
        # reachable-and-misreported.
        #
        # The invariant check is deliberately KEPT below. It is now
        # unreachable by construction, which is what an invariant should be:
        # if a future producer stops honouring `probe_available`, it still
        # fails closed rather than looping.
        spent = mode.model_copy(update={"probe_available": False})

        if result.status in ("oom", "wall_cap"):
            # MEASURED candidate failure — the strongest candidate-local
            # evidence there is.
            measured_failure = "oom" if result.status == "oom" else "wall_cap"
            # A failed probe is never extrapolated: `extrapolate_probe`
            # refuses a non-ok result by contract, and projecting a rate
            # measured up to the moment of failure would be inventing a
            # completion that did not happen. The measured FAILURE is the
            # evidence; the policy blocks on it directly.
            decision = self._policy.decide(
                _unpriced_probe_estimate(result),
                budget,
                # Behaviourally identical here — `measured_failure`
                # short-circuits to REJECT/ABORT before any producer reads
                # `probe_available` — but the budget IS spent, and one mode
                # object that tells the truth beats two that differ.
                spent,
                measured_failure=measured_failure,  # type: ignore[arg-type]
            )
            return ProbeResolution(decision=decision, probe_ran=True, probe_status=result.status)

        if result.status != "ok":
            # load_failure and anything else: the candidate never ran, so
            # this is our channel, not the model.
            return self._abort(
                f"probe did not produce evidence (status={result.status}): {result.error}",
                probe_ran=True,
                probe_status=result.status,
            )

        estimate = extrapolate_probe(
            result,
            train_steps=request.train_steps,
            inference_batches=request.inference_batches,
            producer_identity=self._producer_identity,
        )

        observation_ids: tuple[str, ...] = ()
        if self._persist is not None:
            try:
                observation_ids = tuple(self._persist(result, request))
            except Exception as exc:
                # The measurement exists but the evidence channel cannot
                # keep it. Deciding from unrecorded evidence would leave a
                # formal decision unauditable.
                return self._abort(
                    f"probe measured successfully but the observation could not be "
                    f"persisted: {exc!r}",
                    probe_ran=True,
                    probe_status=result.status,
                )

        decision = self._policy.decide(estimate, budget, spent, evidence_channel="ok")
        if decision.kind == "REQUEST_PROBE":
            return self._abort(
                "policy still requests a probe after a completed, persisted probe — "
                "the measured evidence was not consumed (invariant failure)",
                probe_ran=True,
                probe_status=result.status,
            )
        return ProbeResolution(
            decision=decision,
            probe_ran=True,
            probe_status=result.status,
            observation_ids=observation_ids,
            estimate=estimate,
        )

    def _abort(
        self, reason: str, *, probe_ran: bool = False, probe_status: str | None = None
    ) -> ProbeResolution:
        return ProbeResolution(
            decision=RuntimeDecision(
                kind="ABORT",
                reasons=(reason,),
                evidence_provenance="unknown",
                evidence_rank=-1,
            ),
            probe_ran=probe_ran,
            probe_status=probe_status,
        )


def _unpriced_probe_estimate(result: ProbeResult) -> RuntimeEstimate:
    """Measured-failure evidence with no usable rate (e.g. OOM before the
    first timed step). Carries the measured peak VRAM when there is one —
    the measurement that DOES exist — and nothing invented."""
    from core.runtime_control.estimate_types import make_estimate

    return make_estimate(
        provenance="bounded_live_probe",
        confidence="low",
        peak_vram_gb=result.peak_vram_gb,
        concurrency_identity=result.concurrency_identity,
        warnings=(f"probe ended with status={result.status}: {result.error}",),
    )
