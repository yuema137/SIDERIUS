"""The experiment record history: one canonical fact, one derived view.

arXiv-readiness S2 / U5 (#257, #258). Same rule ``core/wave_records.py``
already states for wave summaries — *which copy is true is stated before it
is written, not discovered when the two disagree*:

    canonical : <workspace>/records/<run_name>/records.jsonl   append-only history
    derived   : <workspace>/summary_<run_name>.json            latest-wins projection

Before this module the summary WAS the history: ``LocalRecorder`` read the
whole list, upserted one entry in place and rewrote the file with
``open(path, "w")``. A crash inside that rewrite left a torn file, and
``get_summary`` mapped a torn file to ``[]`` — so the NEXT save rewrote the
run's history as a single record. The tear was the defect; the ``[]`` was
the amplifier.

The projection preserves exactly the two observable properties every
existing reader relies on:

* **latest wins by ``exp_id``** — the upsert contract (a resumed baseline
  replaces its record; a recovered diagnostic round replaces its record;
  ``MongoRecorder`` does the same with ``upsert=True``);
* **first-insertion order** — an updated record keeps the position of its
  first appearance, which is what an in-place ``summary[i] = record``
  produced and what the REC-3 goldens pin.

The log itself is never projected in place: a record that is superseded
stays in the log as evidence, which is the whole point of having one.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Hashable, Iterable
from typing import Any

from core.durable_io import append_line_durably, publish_bytes_write_once

#: Basename of the canonical append-only log, beside the per-record detail
#: files in ``records/<run_name>/``. No experiment id can collide with it:
#: detail files are ``<exp_id>.json``.
RECORD_LOG_BASENAME = "records.jsonl"


class RecordHistoryUnreadable(RuntimeError):
    """Neither the canonical log nor a legacy summary can be read.

    Raised instead of returning ``[]``: an empty history is what a FRESH
    workspace has, and treating an unreadable one the same way is how a
    torn summary used to become the silent loss of every prior record.
    """


def encode_record_line(record: dict[str, Any]) -> str:
    """One record as one JSON line (non-ASCII preserved, no embedded newlines)."""
    return json.dumps(record, ensure_ascii=False)


def read_record_log(path: str) -> list[dict[str, Any]]:
    """Parse every record line of the canonical log, in order.

    A line that is not a JSON object is SKIPPED with a warning on stderr,
    never raised: the only way such a line is produced by this module is a
    crash mid-append (a torn tail), and refusing the whole history over one
    unfinished line would turn a survivable crash into an unusable
    workspace. The skip is announced with the line number so an operator
    can tell a torn tail from external damage.
    """
    with open(path, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    records: list[dict[str, Any]] = []
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            print(
                f"[records] WARN: {path}:{line_no} is not a complete JSON record "
                f"(torn append?) — skipped; every other line is kept.",
                file=sys.stderr,
            )
            continue
        if not isinstance(parsed, dict):
            print(
                f"[records] WARN: {path}:{line_no} is not a JSON object — skipped.",
                file=sys.stderr,
            )
            continue
        records.append(parsed)
    return records


def project_latest_by_exp_id(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest record per ``exp_id``, in first-insertion order.

    A record without an ``exp_id`` keeps its own positional slot rather than
    collapsing with every other id-less record under ``None``.
    """
    projected: dict[Hashable, dict[str, Any]] = {}
    for position, record in enumerate(records):
        key: Hashable = record.get("exp_id")
        if key is None:
            key = ("__positional__", position)
        # Re-assigning an existing key keeps its original position — this is
        # the dict semantics the first-insertion order rests on.
        projected[key] = record
    return list(projected.values())


def append_record(path: str, record: dict[str, Any]) -> None:
    """Append one record line durably (``flush`` + ``fsync``)."""
    append_line_durably(path, encode_record_line(record))


def bootstrap_record_log(path: str, records: Iterable[dict[str, Any]]) -> bool:
    """Create the canonical log from a pre-existing (legacy) history, once.

    Published write-once as a single file so the log can never exist in a
    half-bootstrapped state: a crash leaves either no log (the legacy
    summary is still the source) or the complete one. Returns ``False`` when
    the log already existed — a concurrent bootstrap won, and its content
    is authoritative.
    """
    payload = "".join(encode_record_line(record) + "\n" for record in records).encode("utf-8")
    try:
        publish_bytes_write_once(path, payload)
    except FileExistsError:
        return False
    return True


def record_log_path(record_dir: str) -> str:
    """The canonical log inside a run's ``records/<run_name>/`` directory."""
    return os.path.join(record_dir, RECORD_LOG_BASENAME)
