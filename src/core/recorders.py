"""Experiment recorders — the run's record-persistence strategies.

Extracted VERBATIM from ``core/sandbox_executor.py`` at the arXiv-readiness
integration head: the S2 durability rework (append-only canonical log +
derived summary view, #257) grew the launch consumer past its frozen Step-11
file budget (R-11-11: "extract the responsibility into a sibling module
instead of growing the launch consumer"), and record PERSISTENCE is exactly
such a responsibility — it shares no state with subprocess launching beyond
the sandbox constructing one recorder. ``core.sandbox_executor`` re-exports
all three names, so every existing import path keeps working.
"""

import json
import os
from typing import Any, cast

from core.durable_io import publish_json_atomically
from core.record_log import (
    RecordHistoryUnreadable,
    append_record,
    bootstrap_record_log,
    project_latest_by_exp_id,
    read_record_log,
    record_log_path,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none


def _ensure_dir(path: str) -> None:
    """Create directory if it does not exist. Raises RuntimeError with a clear message on failure.

    Replicated VERBATIM from ``core.sandbox_executor._ensure_dir`` (the
    extraction's one shared utility; importing it back from the launch
    consumer would invert the dependency the extraction exists to cut).
    """
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError as e:
        raise RuntimeError(
            f"[Sandbox] Permission denied: cannot create directory '{path}'. "
            "Check that you have write access to the workspace."
        ) from e
    except OSError as e:
        raise RuntimeError(
            f"[Sandbox] Failed to create directory '{path}': {e}. "
            "Check that the path is valid and the filesystem is accessible."
        ) from e
    if not os.access(path, os.W_OK):
        raise RuntimeError(
            f"[Sandbox] Directory '{path}' exists but is not writable. "
            "Check filesystem permissions."
        )


class BaseRecorder:
    """Base class for experiment recording."""

    def save_record(self, record: dict[str, Any]):
        raise NotImplementedError

    def get_summary(self) -> list:
        raise NotImplementedError


class LocalRecorder(BaseRecorder):
    """File-based recording for persistent agent memory.

    S2 / U5 (#257, #258): the canonical history is the append-only
    ``records/<run_name>/records.jsonl``; ``summary_<run_name>.json`` is a
    DERIVED view — the latest-wins-by-``exp_id``, first-insertion-ordered
    projection of that log — regenerated and published atomically on every
    save. See ``core/record_log.py`` for the rule and why it exists.

    Order inside ``save_record`` is load-bearing:

        1. detail file  ``records/<run_name>/<exp_id>.json``   (atomic replace)
        2. canonical    append + flush + fsync
        3. derived      summary projection, atomic replace

    so a crash between any two steps leaves every previously written record
    readable and the view rebuildable. ``get_summary`` reads the CANONICAL
    log (never the view), and a view that disagrees with the log — torn,
    missing, or stale from a crash between steps 2 and 3 — is repaired in
    place. A workspace written before the log existed is bootstrapped from
    its summary on the first save, so no legacy history is lost.
    """

    def __init__(self, record_dir: str, summary_file: str, run_name: str):
        self.summary_file = summary_file
        self.record_dir = os.path.join(record_dir, run_name)
        _ensure_dir(self.record_dir)
        self.record_log = record_log_path(self.record_dir)

    def save_record(self, record: dict[str, Any]):
        exp_id = record["exp_id"]

        # Coerce float('-inf') no-signal sentinels to JSON null so the on-disk
        # record stays browser-safe (RFC-8259 doesn't allow Infinity / -Infinity).
        #
        # The cast discharges what the coercion's runtime contract guarantees
        # but its unannotated signature cannot say: a dict INPUT yields a dict
        # of the same shape (the helper recurses structure-preservingly and
        # only rewrites non-finite floats to None). pyright otherwise infers
        # the full recursive union and refuses `append_record(dict[str, Any])`
        # — found by CI's pyright, the one check this host cannot run.
        safe_record = cast("dict[str, Any]", coerce_nonfinite_to_none(record))

        # every detail json should stay in the run_name folder
        detail_path = os.path.join(self.record_dir, f"{exp_id}.json")
        publish_json_atomically(detail_path, safe_record, indent=4, ensure_ascii=False)

        history = self._canonical_history(bootstrap=True)
        append_record(self.record_log, safe_record)
        history.append(safe_record)
        self._publish_summary(project_latest_by_exp_id(history))

    def get_summary(self) -> list:
        projection = project_latest_by_exp_id(self._canonical_history(bootstrap=False))
        if os.path.exists(self.record_log) and not self._summary_matches(projection):
            # The view is torn, missing or stale; the log is the truth.
            self._publish_summary(projection)
        return projection

    # -- internals -----------------------------------------------------------

    def _canonical_history(self, *, bootstrap: bool) -> list[dict[str, Any]]:
        """The full record history, from the log or (legacy) the summary.

        ``bootstrap=True`` creates the log from a legacy summary so the
        following append lands on a complete history; ``False`` never
        writes. Raises :class:`RecordHistoryUnreadable` only when there is no
        log AND the summary exists but cannot be read — a fresh workspace
        (neither file) is ``[]``.
        """
        if os.path.exists(self.record_log):
            return read_record_log(self.record_log)
        legacy = self._read_legacy_summary()
        if legacy is None:
            return []
        if bootstrap:
            bootstrap_record_log(self.record_log, legacy)
            return read_record_log(self.record_log)
        return legacy

    def _read_legacy_summary(self) -> list[dict[str, Any]] | None:
        if not os.path.exists(self.summary_file):
            return None
        try:
            with open(self.summary_file, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecordHistoryUnreadable(
                f"[records] the summary {self.summary_file!r} cannot be read ({exc}) and "
                f"no canonical record log exists at {self.record_log!r}. Refusing to "
                f"treat an unreadable history as empty — restore the summary from a "
                f"backup or the per-record detail files before continuing."
            ) from exc
        if not isinstance(data, list):
            raise RecordHistoryUnreadable(
                f"[records] the summary {self.summary_file!r} is not a JSON list and no "
                f"canonical record log exists at {self.record_log!r}."
            )
        return data

    def _summary_matches(self, projection: list[dict[str, Any]]) -> bool:
        try:
            with open(self.summary_file, encoding="utf-8") as f:
                return json.load(f) == projection
        except (OSError, json.JSONDecodeError):
            return False

    def _publish_summary(self, projection: list[dict[str, Any]]) -> None:
        # Same ``json.dump(..., indent=4, ensure_ascii=False)`` bytes the
        # pre-S2 recorder wrote — every reader of the view is unchanged.
        publish_json_atomically(self.summary_file, projection, indent=4, ensure_ascii=False)


class MongoRecorder(BaseRecorder):
    """MongoDB-based recording for robust development.

    Parity note (S2 / U5): ``update_one(..., upsert=True)`` is the same
    latest-wins-by-``exp_id`` contract ``LocalRecorder`` projects from its
    canonical log; Mongo keeps no append-only history of superseded
    versions. Unchanged by U5.
    """

    def __init__(self, uri: str, db_name: str):
        from pymongo import MongoClient  # type: ignore[reportMissingImports]

        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.collection = self.db["experiments"]

    def save_record(self, record: dict[str, Any]):
        self.collection.update_one({"exp_id": record["exp_id"]}, {"$set": record}, upsert=True)

    def get_summary(self) -> list:
        # For MongoDB, we return more fields to support Agent reasoning
        cursor = self.collection.find({}, {"_id": 0})
        return list(cursor)
