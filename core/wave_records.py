"""The wave summary: one canonical fact, one derived view.

V20 PR E, D-E-3 and D-E-3a.

The wave record used to be an eleven-positional shell ``printf`` that
could express exactly two chains named ``arch`` and ``loss``. §20.7 asks
that a campaign with one chain, or five, or chains named for something
else, not require a schema change — and a positional formatter cannot
emit a variable-length array. It moves here, for the same reason
``campaign_spend`` moved: a shell scan of nested JSON silently inflated
the number a cost cap depended on, and a shell ``printf`` emitting a
nested array is that hazard one step further along.

**Which copy is true is stated before it is written, not discovered when
the two disagree.**

    canonical : <home>/queue_state/wave_state.jsonl   append-only history
    derived   : <home>/pair_summaries/wave_<n>_<tag>.json   mutable snapshot

    1. append to the canonical JSONL, flush, fsync
    2. only then, atomically replace the derived file

A failure between the steps loses the *convenience*, never the
*evidence*, and a derived file that exists without a canonical line is
therefore a detectable inconsistency rather than a normal state. The two
failures are reported distinctly (`CanonicalWriteError` vs
`DerivedWriteError`) because "the summary is missing" and "the evidence
is missing" call for different operator responses.

**``record_id`` exists because the two views age differently.** The JSONL
appends and the per-wave file overwrites, so a retried wave leaves two
records and one file. Every record carries

    <campaign_id>:<wave>:<band_tag>:<attempt>

with ``attempt`` resolved by counting the canonical records that already
match the first three fields — derived from persisted evidence, not from
launcher state a restart would lose. "Which attempt is this file?" is
answered by reading the file; "how many were there?" by the JSONL.

**A note on the field name inside ``chains``.** It is ``run_name``, not
``run``, and that is load-bearing rather than stylistic. The launcher
decides completion with

    grep '"run": "<X>"' wave_state.jsonl | grep -q '"exit": 0'

over the whole line. A ``chains`` array spelled ``{"run": …, "exit": 0}``
would let a wave summary in which one chain succeeded satisfy that
predicate for *every* chain it names — so a chain that exited 137 would
be skipped as complete on the next resume. Measured, not theorised, and
guarded by a regression test.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

from pydantic import BaseModel, Field

#: The two roles the compatibility mirror can describe. A wave with any
#: other shape gets `chains` and no mirror — never a fabricated one.
MIRROR_ROLES = ("arch", "loss")

#: `marker_exit` yields this when a chain left no exit marker. Preserved
#: from the pre-PR-E record rather than changed to `null`, because the
#: operator reports already read it.
NO_MARKER_EXIT = -1


class WaveRecordError(Exception):
    """The wave summary could not be recorded."""


class CanonicalWriteError(WaveRecordError):
    """The append-only evidence could not be written. Nothing was
    recorded anywhere."""


class DerivedWriteError(WaveRecordError):
    """The canonical record IS written; the derived view is not.

    A distinct type because the operator response differs: the evidence
    survives and the per-wave file is rebuildable from the JSONL.
    """


class ChainRecord(BaseModel):
    """One chain's outcome within a wave."""

    run_name: str
    #: From the ROSTER's fourth field. ``None`` when it could not be
    #: resolved — a gap, never a guess, and never a default of ``arch``.
    role: str | None = None
    pid: str = "unknown"
    #: ``-1`` means the chain left no exit marker.
    exit: int


class WaveSummaryRecord(BaseModel):
    """A wave's outcome, in the generic N-chain shape.

    The ``arch_*``/``loss_*`` keys are a **compatibility mirror**, not
    part of the model: they are emitted by :meth:`to_record` only when
    the wave has exactly two chains with exactly those roles. FU-E-1
    removes them once the operator report tooling reads ``chains``.
    """

    record_id: str
    campaign_id: str
    #: The wave number. Keeps the pre-PR-E key name (`wave_summary`) on
    #: serialisation, so existing readers are unaffected.
    wave: int
    band: str
    band_tag: str
    chains: list[ChainRecord] = Field(min_length=1)
    start: str
    end: str
    disposition: str

    def mirror(self) -> dict[str, Any]:
        """The legacy two-role keys, or nothing.

        Emitted only for exactly two chains whose roles are exactly
        ``arch`` and ``loss``. A three-chain wave, a single-chain wave or
        an unresolved role gets no mirror rather than a fabricated one —
        an invented ``arch_exit`` is worse than an absent one, because a
        report would show it.
        """
        if len(self.chains) != 2:
            return {}
        by_role = {c.role: c for c in self.chains if c.role is not None}
        if set(by_role) != set(MIRROR_ROLES):
            return {}
        out: dict[str, Any] = {}
        for role in MIRROR_ROLES:
            chain = by_role[role]
            out[f"{role}_run"] = chain.run_name
            out[f"{role}_pid"] = chain.pid
            out[f"{role}_exit"] = chain.exit
        return out

    def unresolved_roles(self) -> list[str]:
        """The chains whose role the ROSTER could not supply."""
        return [c.run_name for c in self.chains if c.role is None]

    def to_record(self) -> dict[str, Any]:
        """The JSON object written to both destinations."""
        record: dict[str, Any] = {
            "wave_summary": self.wave,
            "record_id": self.record_id,
            "campaign_id": self.campaign_id,
            "band": self.band,
            "band_tag": self.band_tag,
            "chains": [c.model_dump() for c in self.chains],
        }
        record.update(self.mirror())
        # An unresolved role is stated, not merely left null (E-C4b). A
        # reader seeing `"role": null` and no mirror cannot tell whether
        # the wave had unusual roles by design or whether the ROSTER
        # lookup failed — and those call for opposite operator responses.
        # `disposition` is deliberately NOT overloaded to carry this: its
        # vocabulary (complete / failed / launch_failed) describes what
        # happened to the CHAINS, and a recording gap is not a chain
        # outcome. Absent when every role resolved, so a normal record is
        # byte-identical to before.
        unresolved = self.unresolved_roles()
        if unresolved:
            record["unresolved_roles"] = unresolved
            record["role_resolution_failed"] = True
        record.update({"start": self.start, "end": self.end, "disposition": self.disposition})
        return record


def derived_filename(wave: int, band_tag: str) -> str:
    """The per-wave view's filename."""
    return f"wave_{wave}_{band_tag}.json"


def next_attempt(canonical_path: str, *, campaign_id: str, wave: int, band_tag: str) -> int:
    """How many times this wave has been recorded, plus one.

    Counted from the canonical file rather than tracked by the launcher,
    so a queue restart cannot reset it. Unparseable lines are skipped:
    the JSONL holds several record types and may hold pre-PR-E lines, and
    a line that cannot be read is not evidence of an attempt.

    Returns:
        1 for a wave that has never been recorded.
    """
    if not os.path.exists(canonical_path):
        return 1
    seen = 0
    with open(canonical_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if (
                record.get("campaign_id") == campaign_id
                and record.get("wave_summary") == wave
                and record.get("band_tag") == band_tag
            ):
                seen += 1
    return seen + 1


def build_record_id(*, campaign_id: str, wave: int, band_tag: str, attempt: int) -> str:
    return f"{campaign_id}:{wave}:{band_tag}:{attempt}"


def _append_canonical(path: str, record: dict[str, Any]) -> None:
    """Append one line and make it durable before anything else runs.

    ``fsync`` is the point: the derived write must not be able to land
    before the evidence it describes.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise CanonicalWriteError(f"could not append the wave record to {path!r}: {exc}") from exc


def _write_derived(path: str, record: dict[str, Any]) -> None:
    """Replace the per-wave view atomically.

    ``mkstemp`` in the target directory, ``flush``, ``fsync``,
    ``os.replace`` — following ``calibration_registry.py:186-195``. A
    reader therefore sees the old file or the new one, never a torn one,
    and no temp file survives either outcome.
    """
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    except OSError as exc:
        raise DerivedWriteError(
            f"the canonical record is written; the derived summary "
            f"{path!r} could not be started: {exc}"
        ) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        raise DerivedWriteError(
            f"the canonical record is written; the derived summary "
            f"{path!r} could not be published: {exc}"
        ) from exc
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def write_wave_summary(
    *,
    canonical_path: str,
    derived_dir: str,
    campaign_id: str,
    wave: int,
    band: str,
    band_tag: str,
    chains: list[ChainRecord],
    start: str,
    end: str,
    disposition: str,
) -> WaveSummaryRecord:
    """Record one wave, canonical first.

    Raises:
        CanonicalWriteError: nothing was written anywhere.
        DerivedWriteError: the evidence IS recorded; the view is not.
    """
    attempt = next_attempt(canonical_path, campaign_id=campaign_id, wave=wave, band_tag=band_tag)
    record = WaveSummaryRecord(
        record_id=build_record_id(
            campaign_id=campaign_id, wave=wave, band_tag=band_tag, attempt=attempt
        ),
        campaign_id=campaign_id,
        wave=wave,
        band=band,
        band_tag=band_tag,
        chains=chains,
        start=start,
        end=end,
        disposition=disposition,
    )
    payload = record.to_record()
    _append_canonical(canonical_path, payload)
    _write_derived(os.path.join(derived_dir, derived_filename(wave, band_tag)), payload)
    return record
