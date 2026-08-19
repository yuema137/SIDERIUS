# execute_tools/health_checks/_view_provider.py
"""The minimal Health view-provider protocol (Step 08b, C3).

A **view** is whatever a check needs to look at. Until now every check
opened the deliverable itself, which is why the six shipped checks all know
TIDMAD's file layout. A task that stores its outputs differently cannot
reuse them — not because the science differs, but because the READING does.

08b separates the two. A task binds a PROVIDER that knows how to read its
outputs, and a check consumes an opaque payload without knowing where it
came from.

**Two phases, ordered by I/O** (§3.3). This split is the whole design:

```text
PHASE 1 — METADATA ONLY, NO ARTIFACT I/O
    provider_id   : str              stable identity, config-referenced
    capabilities  : frozenset[str]   opaque keys, never interpreted
  (advertised at registration; binding resolution matches against these)

PHASE 2 — MATERIALIZATION, I/O PERMITTED
    materialize(capability_key, ctx, config) -> HealthView
  invoked by the RUNNER, and ONLY after applicability returned applicable
```

If a provider had to open an artifact to say what it offers, 08a's
pre-I/O applicability invariant would be dead: deciding whether a check
applies would already have cost the read the decision exists to avoid.

**Opaque by construction.** The engine never inspects
:attr:`HealthView.payload`, never enumerates capability keys, and never
branches on one. 08b owns the transport; the framework-standard payload
contracts (`categorical_predictions`, `continuous_samples`) are 08c's, and
a plugin-local key like ``vendor.whatever`` is as legitimate as a standard
one — which is what makes an out-of-tree task's own view a first-class
citizen rather than a special case.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.health_checks.schemas import HealthCheckContext


class HealthView(BaseModel):
    """One materialized view, handed to exactly one check.

    A thin envelope, deliberately: it carries enough for a check to know
    what it received and who produced it, and nothing that would let the
    framework start interpreting scientific content it does not own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    capability_key: str = Field(
        description="The capability this view satisfies. Opaque — never parsed.",
    )
    provider_id: str = Field(
        description="Which provider produced it, so a wrong payload is traceable.",
    )
    payload: Any = Field(
        description=(
            "The view's content, in whatever shape the provider and the "
            "consuming check agree on. The engine NEVER inspects this."
        ),
    )


@runtime_checkable
class HealthViewProvider(Protocol):
    """What a task's plugin registers so its checks have something to read.

    Deliberately three members. A provider that needed more would be
    acquiring framework responsibilities, and the point of the seam is that
    a task can supply one without SIDERIUS knowing anything about it.
    """

    provider_id: ClassVar[str]
    """Stable identity the task health config references."""

    capabilities: ClassVar[frozenset[str]]
    """Capability keys this provider can materialize.

    An ADVERTISEMENT, and therefore a claim: failing to honour it is a
    runtime error at materialize time, not a startup error. Startup can only
    check that the claim was made."""

    def materialize(
        self,
        capability_key: str,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthView:
        """Produce the view. I/O is permitted here and ONLY here.

        Called by the runner after applicability returned applicable, so a
        check that does not apply to this task costs no read.

        Args:
            capability_key: which advertised capability to materialize.
            ctx: the round's health-check context.
            config: provider-owned config from the task health config,
                passed through untouched.
        """
        ...


class HealthViewMaterializationError(RuntimeError):
    """A bound provider failed to produce a view it advertised.

    Distinct from a check raising, so the runner's guard can say WHICH
    component failed — but it produces the same ``CheckVerdict.ERROR``,
    because from the gate's point of view a check that could not be given
    its inputs and a check that could not compute are the same thing: a
    question that should have been answered and was not.

    Never ``INAPPLICABLE``. Inapplicability is decided before any of this
    runs, from declarations alone.
    """
