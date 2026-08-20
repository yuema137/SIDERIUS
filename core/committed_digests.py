"""The ONE read / parse / soft-fail authority for committed interpretation digests.

Step 09.5a finding A-2: four functions in :mod:`core.resume` —
``load_latest_knowledge``, ``load_latest_knowledge_cache``,
``load_latest_fingerprint_history`` and ``load_latest_prediction_memory`` —
implemented the *same* contract four times. All four were called consecutively
from ``restore_prior_state`` with identical arguments, so for N committed
iterations the same digest file was opened and ``json.load``-ed **4N times**,
and the soft-fail policy lived in four places that could drift independently.

WHAT THIS MODULE OWNS, AND WHAT IT DOES NOT
--------------------------------------------
It owns exactly one question: **"is this committed digest present and
parseable, and if so what is in it?"** One open, one parse, one classification,
one :class:`DigestRead` per committed iteration per restoration pass.

It does **not** own what any particular carried value means. The four
projections are genuinely different and stay that way — two of them raise on a
malformed value, one warns and drops the offending entry, one ignores a
non-dict; three are latest-wins and one accumulates a union. Flattening those
into a single "generic loader" would be a semantic regression, not a
simplification.

    one open + one parse + one readability verdict   (here)
        ->
    many projections, each with its own validator, merge rule and
    failure policy                                    (core.resume)

DIAGNOSTICS ARE DELIBERATELY STILL PER-PROJECTION
--------------------------------------------------
A corrupt digest still produces one warning per carried value, with the same
message text as before, because this is a behaviour-preserving refactor and
those messages tell an operator *which* carry-over was affected. The message is
built here so the four wordings cannot drift apart, but it is emitted by the
projection, at the same stack depth as before.

    duplicate diagnostic emission  !=  duplicate state-loading authority
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

#: Why a digest could not be used. ``ok`` carries a payload; the other two carry
#: a ``detail`` describing the failure.
DigestStatus = Literal["ok", "missing", "unreadable"]


@dataclass(frozen=True)
class DigestRead:
    """One committed iteration's digest, read and classified exactly once."""

    #: 1-based chain-wide iteration index.
    iter_idx: int
    #: Absolute path the reader resolved. Kept so a projection can reproduce the
    #: historical warning text verbatim without recomputing the path.
    path: str
    #: Whether the file was present and parseable.
    status: DigestStatus
    #: The parsed digest, or ``None`` when ``status != "ok"``.
    payload: dict[str, Any] | None = None
    #: The ``OSError`` / ``JSONDecodeError`` text, or ``None``.
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def digest_unusable_message(read: DigestRead, carry_over: str) -> str:
    """The historical per-projection warning text for an unusable digest.

    ``carry_over`` is the projection's own label — ``"knowledge"``,
    ``"fingerprint-history"``, ``"prediction-memory"``,
    ``"knowledge-cache"`` — and it is the ONLY thing that varied between the
    four original messages. Building the sentence here means the four wordings
    cannot drift apart; passing the label means they stay distinguishable.
    """
    if read.status == "missing":
        return (
            f"[resume] iter {read.iter_idx:03d}: interpretation digest not "
            f"found at {read.path}. Skipping for {carry_over} carry-over."
        )
    return (
        f"[resume] iter {read.iter_idx:03d}: cannot read interpretation "
        f"digest {read.path}: {read.detail}. Skipping for {carry_over} carry-over."
    )


def interpretation_digest_path(workspace: str, iter_idx: int) -> str:
    """Path convention for the chain-mode interpretation digest.

    Mirrors ``workflows.model_exploration.run_workflow``: the interp agent's
    storage is rooted at ``{iter_dir}/`` with run_name ``iter_NNN``, and
    ``ResultInterpretationAgent.run`` writes ``interpretation_{run_name}.json``
    under that workspace, resolving to::

        {workspace}/iter_NNN/iteration_NNN/interpretation_iter_NNN.json

    Both NNN segments carry the same chain-wide iter index because in chain mode
    each subprocess sets ``run_name = f"iter_{start_iteration:03d}"`` AND the
    workflow's loop variable is also ``start_iteration``.
    """
    run_name = f"iter_{iter_idx:03d}"
    return os.path.join(
        workspace,
        run_name,
        f"iteration_{iter_idx:03d}",
        f"interpretation_{run_name}.json",
    )


def read_committed_digests(
    workspace: str,
    current_iter: int,
    committed_iters: Sequence[int],
) -> list[DigestRead]:
    """Read every committed iteration's digest ONCE, in ascending order.

    Args:
        workspace: chain workspace root (absolute path preferred).
        current_iter: the iter the runner is about to launch. ``<= 1``
            short-circuits to ``[]`` — there is nothing committed to carry.
        committed_iters: ascending iter indices known to be committed.

    Returns:
        One :class:`DigestRead` per entry of ``committed_iters``, in the same
        order. Entries that were missing or unparseable are **present** with a
        non-``ok`` status rather than dropped, so a projection can still emit
        its own diagnostic for them — which is what preserves the historical
        warning multiplicity without a second read.

    This function emits no warning of its own. Whether an unusable digest is
    worth telling the operator about is a projection's decision, not the
    reader's.
    """
    if current_iter <= 1 or not committed_iters:
        return []

    reads: list[DigestRead] = []
    for iter_idx in committed_iters:
        path = interpretation_digest_path(workspace, iter_idx)
        if not os.path.isfile(path):
            reads.append(DigestRead(iter_idx=iter_idx, path=path, status="missing"))
            continue
        try:
            with open(path) as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            reads.append(
                DigestRead(iter_idx=iter_idx, path=path, status="unreadable", detail=str(e))
            )
            continue
        reads.append(DigestRead(iter_idx=iter_idx, path=path, status="ok", payload=payload))
    return reads
