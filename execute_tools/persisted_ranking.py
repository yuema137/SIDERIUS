"""Ranking a corpus of PERSISTED records by the metric they declare.

Step 10 P2a C3. Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §4.1 (reconciliation before
ordering), §4.2 (the four per-artifact cases), §4.4 (what a persisted record
actually carries).

Why this module exists
----------------------
Three consumers read artifacts whose producing run is long gone — the
dashboard, ``build_diagnostic_summary`` and
``finalize_recovered_diagnostic_round`` — and all three must answer the same
question: *given these record dicts, which order may I rank them in, if any?*
Written once here rather than three times, because three copies of a
fail-closed rule are three chances for one of them to quietly stop failing.

What it is NOT
--------------
It is neither of the two authorities it composes, and it must not grow into
either:

* identity reconciliation ("are these the same metric?") belongs to
  ``evaluation_metric``;
* ordering ("which value is better?") belongs to ``MetricOrder``.

This module only decides WHICH records may participate and hands the reconciled
declaration to ``MetricOrder``. It contains no comparison of its own — no
``>``, no ``max``, no ``reverse=True`` on a score — and adding one here would
be the second ordering authority P2a exists to prevent.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from typing import Any

from execute_tools.evaluation_metric import (
    METRIC_IDENTITY_UNAVAILABLE,
    MetricIdentityConflictError,
    StampedMetricSpec,
    metric_identity_from_record,
    metric_identity_unavailable_notice,
    reconcile_metric_identity,
)
from execute_tools.metric_order import MetricOrder


def partition_by_metric_identity(
    records: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records into ``(rankable, unranked)`` by declared identity.

    §4.2 case B, applied PER RECORD: a record with no declared metric identity
    is excluded INDIVIDUALLY. It stays fully readable — the caller still shows
    its raw values — it simply never receives a rank and is never called best.
    One such record does not poison the compatible records beside it.
    """
    rankable: list[dict[str, Any]] = []
    unranked: list[dict[str, Any]] = []
    for record in records:
        (rankable if metric_identity_from_record(record) is not None else unranked).append(record)
    return rankable, unranked


def corpus_order(records: Sequence[dict[str, Any]]) -> tuple[MetricOrder | None, str | None]:
    """The ONE order a corpus of persisted records may be ranked by.

    Exclude identity-less records with :func:`partition_by_metric_identity`
    BEFORE calling, so that exclusion is a visible act rather than a side
    effect of reconciliation.

    Returns:
        ``(order, None)`` when every record shares one identity (case A);
        ``(None, None)`` when there is nothing rankable (case C);
        ``(None, diagnostic)`` when the corpus mixes two KNOWN, incomparable
        identities (case D) — the ranking refuses and NAMES the conflict
        instead of silently choosing one of them.
    """
    identities = [
        StampedMetricSpec(
            label=f"record {record.get('exp_id')!r}",
            spec=metric_identity_from_record(record),
        )
        for record in records
    ]
    if not identities:
        return None, None
    try:
        reconciled = reconcile_metric_identity(identities)
    except MetricIdentityConflictError as exc:
        return None, (f"{METRIC_IDENTITY_UNAVAILABLE}: incomparable metrics in one ranking — {exc}")
    if reconciled is None:
        return None, None
    return MetricOrder(reconciled), None


def best_by_declared_metric(
    records: Sequence[dict[str, Any]],
    *,
    context: str,
    score_key: str = "denoising_score",
) -> dict[str, Any] | None:
    """The best record on the metric the records themselves declare.

    The diagnostic scripts' entry point. Emits the canonical
    metric-identity-unavailable notice on STDERR (see :func:`_notify`)
    whenever some or all records cannot be ranked, so ``best: null`` is never
    silently indistinguishable from "there were no records".

    Returns:
        The best record, or ``None`` when nothing is rankable. ``None`` here
        means "not ranked", never "ranked and found nothing".
    """
    rankable, unranked = partition_by_metric_identity(records)
    if unranked:
        _notify(
            metric_identity_unavailable_notice(
                f"{len(unranked)} of {len(records)} {context} records",
                detail="excluded from ranking individually",
            )
        )
    order, conflict = corpus_order(rankable)
    if order is None:
        if conflict is not None:
            _notify(f"[metric] {context}: {conflict}")
        elif rankable or unranked:
            _notify(metric_identity_unavailable_notice(f"the {context} best record"))
        return None
    return order.best(rankable, key=lambda record: record[score_key])


def _notify(message: str) -> None:
    """Emit a human-facing diagnostic on STDERR.

    Never stdout: callers of this module include scripts whose stdout is a
    machine-readable artifact — ``finalize_recovered_diagnostic_round`` writes
    a JSON document there, and ``rebuild_per_file_best --print-only`` has a
    byte-exact stdout contract. A diagnostic line on stdout corrupts them.
    The notice is for a human; stdout is for a program.
    """
    print(message, file=sys.stderr)
