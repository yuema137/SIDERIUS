"""Campaign identity: the validated id, the stamp, and the admission sequence.

V20 PR E, D-E-9 and §4.2a.

A campaign's control state lives at ``<ws_root>/<campaign_id>/``, which
makes ``campaign_id`` a **path component**. Two things follow, and this
module owns both.

**It must be validated before it is one.** The precedent is
``_WRITER_ID_RE`` (``core/runtime_control/observation_store.py:38``),
which guards the identical hazard for ``observations_{id}.jsonl``. It is
module-private and coupled to ``ObservationStore``, so the pattern is
reused here rather than the symbol (FU-E-4 tracks unifying them).

The rule is two lines, and the second one is narrow on purpose:

    re.fullmatch(r"[A-Za-z0-9._-]{1,128}", campaign_id)
    and campaign_id not in {".", ".."}

The second rejects an id **equal to** ``.`` or ``..``. It does **not**
reject an id that merely *contains* ``..``: ``/`` and ``\\`` are already
excluded by the character class, so the id is always exactly one path
segment, and ``alpha..beta`` is an ordinary directory name that cannot
traverse anywhere. A test asserts it is accepted, so the stricter reading
cannot creep back in unnoticed.

**The campaign must be bound to its state.** Directory scoping stops one
campaign from *reading* another's records, but nothing stops an operator
from pointing campaign ``beta`` at the directory campaign ``alpha``
already owns. The stamp is what makes that detectable: the first run
writes its identity into ``control/campaign.json``, and every later run
must match it or refuse.

The whole admission sequence is one function because its **order** is the
guarantee, and an order split across call sites is not checkable:

    1. validate campaign_id                  -> refuse: nothing created
    2. inspect the existing campaign home    -> read-only
    3. validate an existing stamp            -> refuse: nothing written
    4. create the directories                -> first side effect
    5. atomically create the stamp if absent -> first writer wins

Step 5 follows ``core/run_invariants.py:190-222`` exactly — publish with
``os.link``, which FAILS when the target exists instead of overwriting it.
That is what makes "first writer wins" true under concurrency, and it
gives a losing racer a ``FileExistsError`` to fall through to validation
on, rather than a silently clobbered stamp.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, field_validator

#: The subdirectories every campaign home owns. The launcher resolves the
#: same three names at definition scope (it needs ``LOGF`` before it may
#: call Python), so a cross-language parity test pins the two lists
#: together — that duplication is deliberate and guarded, not accidental.
CAMPAIGN_SUBDIRS: tuple[str, ...] = ("control", "queue_state", "pair_summaries")

#: Identity stamp, inside ``control/``.
STAMP_FILENAME = "campaign.json"

#: From ``_WRITER_ID_RE``. Rejects empty (the ``{1,128}`` bound), every
#: path separator, control characters, NUL and every absolute-path form
#: (the character class), and over-length ids (the bound).
_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

#: The only two whole-string values that can traverse. Checked by
#: equality, never by substring — see the module docstring.
_TRAVERSING_IDS = frozenset({".", ".."})


class CampaignAdmissionError(Exception):
    """A campaign may not be admitted. Refusal, never a warning."""


class CampaignIdError(CampaignAdmissionError):
    """The campaign id is not safe to use as a path component."""


class CampaignStampError(CampaignAdmissionError):
    """An existing stamp is missing, unreadable, malformed, or names a
    different campaign."""


def validate_campaign_id(value: str) -> str:
    """The campaign id, or refuse.

    Args:
        value: the requested campaign id.

    Returns:
        The same id, once proven safe as a single path component.

    Raises:
        CampaignIdError: the id is empty, over-length, contains a path
            separator or control character, or is exactly ``.`` or ``..``.
    """
    if not isinstance(value, str):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise CampaignIdError(f"campaign id must be a string, got {type(value).__name__}")
    if value in _TRAVERSING_IDS:
        raise CampaignIdError(
            f"campaign id {value!r} is a path-traversal segment; it would "
            f"resolve the campaign home outside its collection root"
        )
    if not _CAMPAIGN_ID_RE.match(value):
        raise CampaignIdError(
            f"campaign id {value!r} is not a safe path component: it must "
            f"be 1-128 characters from [A-Za-z0-9._-]. The id becomes a "
            f"directory name, so separators, control characters and empty "
            f"values are refused."
        )
    return value


class CampaignStamp(BaseModel):
    """The identity a campaign home is bound to.

    Written once, by the first runner to admit this campaign, and read by
    every later one. ``campaign_id`` is re-validated on load so that a
    stamp written before this validator existed cannot grandfather an
    unsafe id back in.
    """

    campaign_id: str
    created_at: str
    ws_root: str
    campaign_home: str
    runner: str
    runner_pid: int
    #: Set by E-C3 when this campaign adopts a pre-PR-E state file.
    #: Declared here so adoption does not need a schema change.
    legacy_adopted_from: str | None = None

    @field_validator("campaign_id")
    @classmethod
    def _id_is_a_safe_path_component(cls, value: str) -> str:
        return validate_campaign_id(value)


@dataclass(frozen=True)
class CampaignAdmission:
    """What admission decided, for the caller to log."""

    campaign_id: str
    campaign_home: str
    stamp_path: str
    stamp: CampaignStamp
    outcome: Literal["created", "validated"]


def campaign_subdir_paths(campaign_home: str) -> tuple[str, ...]:
    """The three directories a campaign home owns, in declaration order."""
    return tuple(os.path.join(campaign_home, name) for name in CAMPAIGN_SUBDIRS)


def stamp_path_for(campaign_home: str) -> str:
    """Where the identity stamp lives for this campaign home."""
    return os.path.join(campaign_home, CAMPAIGN_SUBDIRS[0], STAMP_FILENAME)


def read_campaign_stamp(path: str) -> CampaignStamp | None:
    """The stamp at ``path``, or ``None`` when there is none.

    Absent is a value — a campaign that has never been stamped is the
    normal first-start case, and every pre-PR-E campaign. Present but
    unreadable is an error: a stamp that cannot be parsed cannot prove a
    match, and proceeding would launch into a home whose owner is unknown.

    Raises:
        CampaignStampError: the file exists but is unreadable, is not
            JSON, is not an object, or does not satisfy the schema
            (including a recorded id that fails validation).
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except OSError as exc:
        raise CampaignStampError(
            f"campaign stamp {path!r} exists but cannot be read: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise CampaignStampError(
            f"campaign stamp {path!r} is not valid JSON ({exc}). Refusing to "
            f"guess which campaign owns this directory."
        ) from exc
    if not isinstance(payload, dict):
        raise CampaignStampError(
            f"campaign stamp {path!r} is a {type(payload).__name__}, not an object"
        )
    try:
        return CampaignStamp.model_validate(payload)
    except Exception as exc:
        raise CampaignStampError(
            f"campaign stamp {path!r} does not describe a usable campaign identity ({exc})"
        ) from exc


def write_campaign_stamp(stamp: CampaignStamp, path: str) -> None:
    """Publish the stamp atomically. First writer wins.

    Mirrors ``write_run_invariants`` (``core/run_invariants.py:190-222``):
    write to a same-directory temp file, then publish with ``os.link``,
    which fails when the target exists rather than overwriting it.

    Raises:
        FileExistsError: a stamp is already published — the caller lost a
            race and must validate against the winner instead.
    """
    directory = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(stamp.model_dump(), handle, indent=2)
            handle.write("\n")
        os.link(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)


def admit_campaign(
    *,
    campaign_id: str,
    ws_root: str,
    campaign_home: str,
    runner: str,
    runner_pid: int,
) -> CampaignAdmission:
    """Admit this campaign to this home, in the one order that is safe.

    See the module docstring for the sequence and why it is one function.
    Both ordering guarantees hold here and are testable at one entry
    point: an invalid id is refused before **any** ``mkdir``, and a
    foreign or malformed stamp is refused before **any** write.

    Args:
        campaign_id: the requested identity; becomes a directory name.
        ws_root: the campaign collection root, recorded for provenance.
        campaign_home: the resolved home. Normally
            ``<ws_root>/<campaign_id>``; an operator override moves the
            whole campaign coherently.
        runner: the launcher's filename, recorded for provenance.
        runner_pid: the launcher's pid, recorded for provenance.

    Returns:
        What was decided, including whether this call created the stamp.

    Raises:
        CampaignIdError: step 1 — nothing was created.
        CampaignStampError: step 3 — nothing was written.
        OSError: a directory or the stamp could not be created. An
            unstampable campaign cannot be guarded, so this is fatal
            rather than a downgrade to "unbound".
    """
    # 1. Validate. Before this line nothing has touched the filesystem,
    #    which is the whole point of doing it first: `..` must never
    #    reach a `mkdir`.
    validated = validate_campaign_id(campaign_id)

    # 2-3. Inspect, read-only, and refuse a foreign owner before any write.
    stamp_path = stamp_path_for(campaign_home)
    existing = read_campaign_stamp(stamp_path)
    if existing is not None and existing.campaign_id != validated:
        raise CampaignStampError(
            f"campaign home {campaign_home!r} is stamped as "
            f"{existing.campaign_id!r} but this run requested "
            f"{validated!r} (stamp: {stamp_path}). Refusing: one campaign's "
            f"control state may not be written or read by another. Use a "
            f"different CAMPAIGN_HOME, or the id this home already owns."
        )

    # 4. First side effect.
    for directory in campaign_subdir_paths(campaign_home):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            raise OSError(f"cannot create campaign directory {directory!r}: {exc}") from exc

    if existing is not None:
        return CampaignAdmission(
            campaign_id=validated,
            campaign_home=campaign_home,
            stamp_path=stamp_path,
            stamp=existing,
            outcome="validated",
        )

    # 5. Publish, first writer wins.
    stamp = CampaignStamp(
        campaign_id=validated,
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ws_root=ws_root,
        campaign_home=campaign_home,
        runner=runner,
        runner_pid=runner_pid,
    )
    try:
        write_campaign_stamp(stamp, stamp_path)
    except FileExistsError:
        # A concurrent runner won. Validate against the winner rather than
        # overwrite it — the loser has no more right to the home than the
        # winner, and one of the two identities has to be authoritative.
        winner = read_campaign_stamp(stamp_path)
        if winner is None:
            raise CampaignStampError(
                f"campaign stamp {stamp_path!r} vanished between a losing write and its validation"
            ) from None
        if winner.campaign_id != validated:
            raise CampaignStampError(
                f"campaign home {campaign_home!r} was stamped concurrently as "
                f"{winner.campaign_id!r} while this run requested {validated!r}"
            ) from None
        return CampaignAdmission(
            campaign_id=validated,
            campaign_home=campaign_home,
            stamp_path=stamp_path,
            stamp=winner,
            outcome="validated",
        )
    return CampaignAdmission(
        campaign_id=validated,
        campaign_home=campaign_home,
        stamp_path=stamp_path,
        stamp=stamp,
        outcome="created",
    )
