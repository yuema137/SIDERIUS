"""Advice artifact identity, consumability and explicit launcher selection.

Only explicit loading reads files. Importing this owner has no launch effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path


class AdviceArtifactError(ValueError):
    """A run's advice artifact is unreadable, unparseable, not the one the
    launcher certified, or unable to inject anything.

    Fail-CLOSED, on the ``RequiredProfileBindingError`` precedent: the advice
    artifact is the Gold campaign's INDEPENDENT VARIABLE, so "the file moved
    or changed since the launcher hashed it" must stop the launch rather than
    quietly run a different treatment under the same arm label.

    F-SCHED-5 extends that from IDENTITY to CONSUMABILITY. Certifying WHICH
    bytes were read says nothing about whether those bytes reach a prompt,
    and the binding mechanism is what hides the difference: a misspelled key
    parses, hashes, is distributed to all four bands, is certified by each
    against the parent-pinned digest and is pinned into the run-invariants
    lock as ``_CANONICAL``, while injecting NOTHING. The result is a run
    whose provenance records that advice artifact X was used and whose
    agents received nothing derived from X. ``gold_arm_args`` refuses to
    launch the formal path WITHOUT an advice file, which is the proof that
    the treatment is required; an artifact that cannot inject is therefore
    refused here, by name, rather than satisfying that requirement in form
    only.
    """


#: Top-level keys ``normalize_args`` explodes onto ``args.human_advice_*``.
#: The union of both schemas the loader tolerates during transition:
#: 4-key (propose, implement, tune, mindset) and 5-key (interpret, propose,
#: implement, validate, tune). Any other key reaches NO consumer.
ADVICE_PER_AGENT_KEYS = (
    "interpret",
    "analysis",
    "propose",
    "implement",
    "validate",
    "tune",
)
ADVICE_RECOGNISED_KEYS = (*ADVICE_PER_AGENT_KEYS, "mindset")

#: The ONE way to say "this key is deliberately not advice". A leading
#: underscore marks an inert annotation block. It is spelled as an explicit
#: opt-out precisely so
#: that an unrecognised key WITHOUT it can be treated as the typo it almost
#: always is, instead of being dropped in silence.
ADVICE_INERT_KEY_PREFIX = "_"


def render_advice_value(value: object) -> str | None:
    """Render one advice value the way the agents receive it, or ``None``.

    The ONE rendering authority, called by ``load_advice_artifact`` to decide
    whether a key carries content and by ``normalize_args`` to produce the
    content itself. Split authorities are how a loader comes to accept an
    artifact the consumer then drops: the emptiness test must be the exact
    expression whose result is injected, not a second opinion about it.

    Args:
        value: A parsed JSON value from the advice mapping.

    Returns:
        The rendered text, or ``None`` when the value carries nothing an
        agent could read. A list is joined with newlines (the file format's
        line-list form); every other value is returned unchanged when truthy.
    """
    if isinstance(value, list):
        value = "\n".join(item for item in value if isinstance(item, str))
    return value or None  # type: ignore[return-value]


def _validate_advice_consumability(content: dict, *, resolved: str, observed: str) -> None:
    """Refuse an advice artifact that cannot inject what it declares.

    Three refusals, one property: every declaration in the file reaches a
    consumer, and at least one does.

    1. An unrecognised top-level key that is not ``_``-prefixed. This is the
       misspelling: ``implemnt`` parses as valid JSON and is read by nothing.
    2. A recognised key whose value is not a string or list of strings. The
       list case additionally protects ``normalize_args``, which joins
       unguarded and would raise a bare ``TypeError`` naming no file.
    3. A recognised key present but rendering nothing an agent can read —
       empty, or whitespace only. ``["", ""]`` joins to ``"\\n"``, which is
       TRUTHY, so the consumer's ``or None`` would inject a bare newline;
       emptiness is therefore judged on the STRIPPED rendered text.
    4. No recognised key at all — the vacuous-treatment case.

    Args:
        content: The parsed advice mapping.
        resolved: Absolute path, for the message.
        observed: The artifact's observed digest, for the message — the
            operator needs to know WHICH bytes were refused.

    Raises:
        AdviceArtifactError: naming every offending key and what was wrong
            with it, so one launch surfaces every defect rather than one
            per relaunch.
    """
    where = f"advice artifact at {resolved} (sha256={observed})"

    unrecognised = sorted(
        key
        for key in content
        if key not in ADVICE_RECOGNISED_KEYS and not key.startswith(ADVICE_INERT_KEY_PREFIX)
    )
    if unrecognised:
        raise AdviceArtifactError(
            f"{where} declares top-level keys no agent reads: "
            f"{', '.join(repr(k) for k in unrecognised)}. A key outside "
            f"{ADVICE_RECOGNISED_KEYS} injects nothing, so one transposed letter "
            f"records this artifact as the run's treatment while the agents receive "
            f"nothing derived from it. Correct the spelling, or prefix the key with "
            f"{ADVICE_INERT_KEY_PREFIX!r} to declare it deliberately inert."
        )

    ill_typed: list[str] = []
    empty: list[str] = []
    for key in ADVICE_RECOGNISED_KEYS:
        if key not in content:
            continue
        value = content[key]
        if not isinstance(value, str) and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            ill_typed.append(key)
        else:
            # Emptiness is judged on the RENDERED text, after the same join
            # the consumer applies — `["", ""]` renders to "\n", which is
            # TRUTHY, so the consumer's own `or None` would inject a bare
            # newline and call it advice. `render_advice_value` is left
            # mirroring the consumer exactly; the whitespace test lives here,
            # in the validator, which asks the different question of whether
            # an agent could read anything.
            rendered = render_advice_value(value)
            if rendered is None or not str(rendered).strip():
                empty.append(key)

    if ill_typed:
        raise AdviceArtifactError(
            f"{where} declares {', '.join(repr(k) for k in ill_typed)} with a value "
            f"that is neither a string nor a list of strings. Advice is text an "
            f"agent reads; anything else either reaches a prompt as a repr or "
            f"crashes the line-list join with a bare TypeError naming no file."
        )
    if empty:
        raise AdviceArtifactError(
            f"{where} declares {', '.join(repr(k) for k in empty)} with empty "
            f"content. An empty declaration is dropped by the consumer, so the "
            f"key is present in the artifact and absent from every prompt. Give "
            f"it content or remove the key."
        )

    if not any(key in content for key in ADVICE_RECOGNISED_KEYS):
        raise AdviceArtifactError(
            f"{where} carries no recognised advice key, so it would bind a real "
            f"sha256 into the run-invariants lock and inject NOTHING into any "
            f"round — provenance recording that this artifact was used by a run "
            f"that received nothing derived from it. "
            f"Recognised keys: {', '.join(ADVICE_RECOGNISED_KEYS)}."
        )


@dataclass(frozen=True)
class AdviceArtifact:
    """The advice artifact this process actually read.

    Attributes:
        path: The resolved ABSOLUTE path the bytes came from.
        sha256: The OBSERVED sha256 of those exact bytes. This — never a
            declared value — is what reaches the workspace lock.
        content: The parsed advice mapping, from the SAME bytes.
    """

    path: str
    sha256: str
    content: dict


def load_advice_artifact(path: str, *, declared_sha256: str | None = None) -> AdviceArtifact:
    """Read, certify and parse the advice artifact from ONE read of the file.

    TOCTOU-safe by construction, the ``_load_bound_overlay`` precedent
    (``core/runtime_control/watchdog_profile.py``): the file is read exactly
    once with ``Path.read_bytes``, the sha256 is computed over that bytes
    object, and ``json.loads`` parses the SAME object — never a re-open, so
    no window exists in which a swapped file is hashed as one content and
    parsed as another.

    ``declared_sha256`` is the campaign launcher's OBSERVATION, forwarded on
    argv as a cross-process integrity check. It is CERTIFIED against the
    digest computed here and then discarded: the returned ``sha256`` is
    always this process's own observation. That asymmetry is the point —
    stamping the declared value would make the lock an ECHO, which is
    behaviourally invisible right up until the day the two differ, and that
    is exactly the day the record has to be true.

    Args:
        path: The advice artifact path, absolute or relative to this
            process's working directory.
        declared_sha256: The digest the launcher observed, or ``None`` when
            nothing was declared (a hand-run chain).

    Returns:
        The artifact, carrying the resolved path, the observed digest and
        the parsed content.

    Certification is about WHICH bytes; it is not about whether those bytes
    can do anything. ``_validate_advice_consumability`` closes that gap
    (F-SCHED-5) before the artifact is returned, so an artifact that would
    inject nothing never reaches the digest's distribution at all.

    Raises:
        AdviceArtifactError: the file is missing or unreadable, its bytes do
            not parse as a JSON object, its digest is not
            ``declared_sha256``, or its content cannot inject (an
            unrecognised key, an ill-typed value, an empty declaration, or
            no recognised key at all).
    """
    resolved = os.path.abspath(path)
    try:
        data = Path(resolved).read_bytes()
    except FileNotFoundError:
        raise AdviceArtifactError(
            f"advice artifact not found: {resolved}. A declared advice file is "
            f"the run's treatment — a missing one refuses the launch rather "
            f"than running an untreated arm under a treated label."
        ) from None
    except OSError as exc:
        raise AdviceArtifactError(f"advice artifact at {resolved} is unreadable: {exc}") from exc
    observed = hashlib.sha256(data).hexdigest()
    if declared_sha256 is not None and declared_sha256 != observed:
        raise AdviceArtifactError(
            f"advice artifact identity cannot be certified: the file at "
            f"{resolved} hashes to sha256={observed}, but this launch declares "
            f"sha256={declared_sha256}. The bytes are not the ones the "
            f"launcher recorded — refuse, never consume them. Every band of a "
            f"campaign must read one artifact; an edit between two band "
            f"launches is exactly what this comparison exists to catch."
        )
    try:
        content = json.loads(data)
    except json.JSONDecodeError as exc:
        raise AdviceArtifactError(
            f"advice artifact at {resolved} (sha256={observed}) is not valid JSON: {exc}"
        ) from exc
    if not isinstance(content, dict):
        raise AdviceArtifactError(
            f"advice artifact at {resolved} (sha256={observed}) must be a JSON "
            f"object of advice keys; got {type(content).__name__}."
        )
    _validate_advice_consumability(content, resolved=resolved, observed=observed)
    return AdviceArtifact(path=resolved, sha256=observed, content=content)


def resolve_advice_artifact(args: argparse.Namespace) -> AdviceArtifact | None:
    """The ONE authority for "which advice artifact does this launch read".

    Idempotent and cached on ``args``: ``normalize_args`` resolves it to get
    the advice CONTENT, and ``resolve_launch_identity`` resolves it to get
    the lock IDENTITY. Both must see the same bytes, so exactly one read
    happens per process and both callers go through here — a second reader
    with its own ``open()`` is how the content and the pinned identity would
    come to describe different files.

    Returns:
        The artifact, or ``None`` when this launch declares no advice.
    """
    cached = getattr(args, "advice_artifact", None)
    if cached is not None:
        return cached
    # --advice (4-key) takes precedence over --human_advice_file (5-key).
    path = args.advice or args.human_advice_file
    if not path:
        return None
    artifact = load_advice_artifact(path, declared_sha256=args.advice_sha256)
    args.advice_artifact = artifact
    return artifact
