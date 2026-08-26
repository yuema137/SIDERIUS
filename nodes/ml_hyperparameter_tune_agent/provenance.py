"""Tracks what planning RESOLVED, so downstream narrative can stop guessing.

Private to the tuner node. Planning authors a plan, then overrules parts of it
through a sequence of resolution steps; this module watches that sequence and
produces the typed :class:`~agent.schemas.execution_provenance.ExecutionProvenance`
the reflector is told to trust over the planner's prose.

Why a TRACKER and not six hand-written recorders
------------------------------------------------

The obvious implementation records a provenance entry at each known override
site. It is also the implementation that goes silently blind: add a seventh
resolution step and nothing reports it, because the recorders enumerate the
steps they know about. That is the census-blindness shape this repository has
been bitten by repeatedly — a guard that stays green because its *field set*
was fixed at authoring time.

So the tracker snapshots the plan and DIFFS it. Attribution is best-effort (a
step names itself when it is wrapped); *detection* is structural. The closing
:meth:`ResolutionTracker.finish` sweep compares against the final plan and
reports anything that moved without a registered step claiming it as
``unattributed``. A new override step therefore shows up as a real
disagreement with a vague authority — never as agreement.
"""

from __future__ import annotations

from typing import Any

from agent.schemas.execution_provenance import ExecutionProvenance, ResolutionEvent


def _flatten(value: Any, prefix: str = "") -> dict[str, str]:
    """Render a plan dump as dotted path -> text.

    Values become text here, once, because the consumers are a prompt and a
    report. Containers other than ``dict`` are rendered whole: a list of layer
    widths is one comparable fact, and splitting it into indexed paths would
    turn a single architecture change into a dozen unreadable events.
    """
    flat: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flat.update(_flatten(item, path))
    else:
        flat[prefix] = repr(value)
    return flat


#: Rendered stand-in for "this key was not in the dump at all".
ABSENT = "<absent>"

#: Executed values that carry no narrative content when the planner never
#: authored the key. See :func:`_is_default_materialization`.
_EMPTY_EXECUTED = frozenset({"None", "False"})

#: Plan paths that MIRROR a value authored elsewhere on the plan, and are
#: therefore never an independent overrule.
#:
#: ``model_cfg["model_type"]`` is the only one today. The planner authors its
#: architecture choice in the top-level ``plan.model_type``; the nested copy is
#: filled in from the RESOLVED model so the trainer receives a consistent
#: config. Diffing the mirror reported ``model_cfg.model_type: None ->
#: 'pe_wavenet_delta'`` on an ordinary legacy run where nothing was overruled
#: at all — a non-event, on essentially every run, in a block whose entire
#: value is that its presence means something.
#:
#: The real model channel is not dropped: it is compared once, at
#: ``plan.model_type``, by the caller's ``extra``.
_MIRROR_PATHS = frozenset({"model_cfg.model_type"})


def _is_default_materialization(authored: str, executed: str) -> bool:
    """True for a difference that is representation, not an overrule.

    Plan sub-configs are raw ``dict``s, so an authored ``loss_cfg`` holds only
    the keys the planner actually wrote, while a resolution step that replaces
    it wholesale substitutes a full ``model_dump()`` carrying every schema
    default. The two sides are then asymmetric for reasons that have nothing to
    do with what executed: DAVIS's declared objective produced four events of
    the form ``alpha: <absent> -> None`` around the two that mattered.

    That dilution is a real cost. The reflector is being told which values to
    trust, and burying ``loss_type`` and ``epochs`` among six lines of default
    materialization weakens exactly the signal this block exists to carry.

    So a key the planner never authored, resolving to a falsy default, is
    dropped. A key the planner never authored resolving to a REAL value is
    KEPT — ``loss_name: <absent> -> 'davis_exact_l1'`` is the single most
    useful line in the block, and suppressing every new key would delete it.

    **The limit, stated plainly**: a claim in free prose about a field the plan
    never declared structurally cannot be detected here. Nothing in the plan
    contradicts it. The reflector still receives the resolved values through
    its comparison context, so this narrows a signal rather than removing one.
    """
    return authored == ABSENT and executed in _EMPTY_EXECUTED


class ResolutionTracker:
    """Watches one attempt's plan across its resolution steps.

    Usage mirrors the order planning already runs in::

        tracker = ResolutionTracker(plan)
        plan = _apply_plan_overrides(...)
        tracker.record(plan, "operator_plan_overrides")
        ...
        provenance = tracker.finish(plan)

    ``record`` is safe to call when a step did nothing — a step that changed
    no field contributes no events.
    """

    def __init__(self, authored_plan: Any) -> None:
        #: The plan AS AUTHORED. Every comparison is against this, not against
        #: the previous step, so a field overruled twice reports the authored
        #: value the prose actually describes — not an intermediate value that
        #: no one ever saw and no narrative ever claimed.
        self._authored = _flatten(authored_plan.model_dump())
        #: field_path -> authority, first claimant wins. First rather than last
        #: because the first step to move a field away from the authored value
        #: is the one that made the prose wrong.
        self._claims: dict[str, str] = {}

    def record(self, plan: Any, authority: str) -> None:
        """Attribute to ``authority`` every field it moved away from authored."""
        current = _flatten(plan.model_dump())
        for path, value in current.items():
            if path in _MIRROR_PATHS:
                continue
            authored = self._authored.get(path, ABSENT)
            if _is_default_materialization(authored, value):
                # Same rule as `finish`. Claiming a path that will never be
                # emitted is harmless today but leaves the two halves of this
                # class disagreeing about what counts as an overrule.
                continue
            if authored != value and path not in self._claims:
                self._claims[path] = authority

    def finish(
        self,
        plan: Any,
        *,
        extra: tuple[tuple[str, str, str, str], ...] = (),
    ) -> ExecutionProvenance:
        """Close the tracker against the FINAL plan and emit the provenance.

        The sweep is the completeness guarantee: any field still differing from
        the authored plan that no registered step claimed is reported as
        ``unattributed`` rather than dropped.

        ``extra`` carries disagreements that do not live on the plan object —
        each a ``(field_path, proposed, executed, authority)`` tuple. The forced
        model type is one: it is applied to a COPY of ``model_cfg`` after
        planning has finished mutating the plan, so no plan diff can see it.
        """
        final = _flatten(plan.model_dump())
        events: list[ResolutionEvent] = []
        for path in sorted(set(self._authored) | set(final)):
            authored = self._authored.get(path, ABSENT)
            executed = final.get(path, ABSENT)
            if path in _MIRROR_PATHS:
                continue
            if authored == executed or _is_default_materialization(authored, executed):
                continue
            events.append(
                ResolutionEvent(
                    field_path=path,
                    proposed=authored,
                    executed=executed,
                    authority=self._claims.get(path, "unattributed"),
                )
            )
        for path, proposed, executed, authority in extra:
            if proposed == executed:
                continue
            events.append(
                ResolutionEvent(
                    field_path=path,
                    proposed=proposed,
                    executed=executed,
                    authority=authority,
                )
            )
        return ExecutionProvenance(events=tuple(events))

    def finish_with_model(self, plan: Any, *, executed_model_type: Any) -> ExecutionProvenance:
        """:meth:`finish` plus the model channel, which no plan diff can see.

        The resolved model type is written onto a COPY of ``model_cfg`` after
        the plan stops changing, so it travels as an ``extra``. It is compared
        against ``plan.model_type`` — the architecture the PLANNER authored —
        and never against ``model_cfg["model_type"]``, a mirror filled in from
        the resolved value (see :data:`_MIRROR_PATHS`).
        """
        return self.finish(
            plan,
            extra=(
                (
                    "model_type",
                    repr(plan.model_type),
                    repr(executed_model_type),
                    "forced_model_type",
                ),
            ),
        )
