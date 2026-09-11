"""Iteration manifest integrity — ONE authority for digest, publish, replace, verify.

arXiv-readiness S2 / U5 (#257, #258). ``iter_NNN/manifest.json`` is the
chain's committed handoff between iterations and the anchor of replay
integrity: it names the ``run_output`` it describes and, since V19 PR 1,
carries that artifact's SHA-256. Before this module three things were
undetectable:

* an edit to a manifest FIELD (the artifact hash stayed consistent);
* REMOVAL of ``run_output_sha256`` — the verifiers read a hash-less
  manifest as a pre-V19 legacy one and admitted it "visibly unverified";
* a plain rerun of the same iteration, which rewrote the manifest with
  ``open(path, "w")`` and silently regenerated the hash.

Operator ruling #258 freezes the answer: normal iteration manifests are
WRITE-ONCE; a same-iteration replacement is allowed only through an
EXPLICIT operation that records provenance; an ordinary rerun must never
silently regenerate integrity hashes. Concretely:

* ``manifest_sha256`` — a self-digest over the canonical bytes of every
  other field. A manifest that carries it but lacks ``run_output_sha256``
  for a completed iteration is a TAMPER, not a legacy downgrade. A manifest
  with NEITHER digest is a pre-S2 legacy manifest and stays visibly
  unverified, exactly as before.
* :func:`publish_iteration_manifest` publishes with ``os.link`` (same
  mechanism as ``core/run_invariants.py``): a second publish for the same
  iteration is :class:`ManifestAlreadyPublishedError`, by name.
* :class:`ManifestReplacementRequest` is the explicit operation. The
  previous manifest is set aside (never deleted) as
  ``manifest.replaced.<utc-stamp>.json`` and the new manifest records
  ``replaced_at``, ``replacement_reason``, ``previous_manifest_sha256`` and
  ``previous_run_output_sha256`` under ``manifest_replacement``.
* :func:`verify_iteration_manifest` is the verification predicate
  ``core/resume.py``, ``execute_tools/per_file_best.py`` and
  ``scripts/launch/inspect_run_state.py`` all call, so "trustworthy" has one
  definition and one message shape.

What content hashing cannot do, stated plainly: a hand rewrite that
recomputes EVERY digest is indistinguishable from a legitimate publish —
there is no secret. The control against that is the write-once publish plus
the replacement provenance, both of which a rewrite through the sanctioned
producer cannot skip.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.durable_io import publish_bytes_write_once

MANIFEST_BASENAME = "manifest.json"
MANIFEST_DIGEST_KEY = "manifest_sha256"
RUN_OUTPUT_DIGEST_KEY = "run_output_sha256"
MANIFEST_REPLACEMENT_KEY = "manifest_replacement"
#: A set-aside previous manifest: ``manifest.replaced.<utc-stamp>.json``.
REPLACED_MANIFEST_PREFIX = "manifest.replaced."


class ManifestAlreadyPublishedError(RuntimeError):
    """A manifest already exists for this iteration and no replacement was
    requested. The existing manifest is untouched."""


class ManifestReplacementError(ValueError):
    """The replacement request is malformed, or there is nothing to replace."""


class ManifestReplacementRequest(BaseModel):
    """The explicit, provenance-bearing same-iteration replacement (#258)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str
    requested_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @field_validator("reason")
    @classmethod
    def _reason_is_an_explanation(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "a manifest replacement needs a non-empty replacement_reason — the reason "
                "is recorded in the new manifest's provenance"
            )
        return stripped


@dataclass(frozen=True)
class ManifestVerdict:
    """Result of :func:`verify_iteration_manifest`.

    ``problem`` is ``None`` for a trustworthy manifest; otherwise a sentence
    (already naming the iteration and the offending path) that the caller
    raises or reports under its own prefix. The two ``*_verified`` flags
    are ``False`` for a legacy manifest that carries no digest to verify —
    "unverified" is a visible state, never an error.
    """

    manifest_verified: bool
    artifact_verified: bool
    problem: str | None
    expected_artifact_sha256: str | None = None
    actual_artifact_sha256: str | None = None


def manifest_path(iter_dir: str) -> str:
    return os.path.join(iter_dir, MANIFEST_BASENAME)


def sha256_file(path: str) -> str:
    """Stream a file's SHA-256 hex digest (same check as ``core.resume``)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_canonical_bytes(manifest: Mapping[str, Any]) -> bytes:
    """Sorted keys, compact separators, UTF-8 — every field but the digest.

    Computed over the parsed VALUES, not the on-disk formatting, so the
    digest is independent of indentation and of the order in which a
    producer happened to insert keys, and stable across a JSON round trip.
    """
    body = {k: v for k, v in manifest.items() if k != MANIFEST_DIGEST_KEY}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def manifest_self_digest(manifest: Mapping[str, Any]) -> str:
    return hashlib.sha256(manifest_canonical_bytes(manifest)).hexdigest()


def classify_manifest_slot(iter_dir: str, replacement: ManifestReplacementRequest | None) -> None:
    """Launch-time gate for the iteration's manifest slot.

    Raises:
        ManifestAlreadyPublishedError: a manifest exists and no replacement
            was requested — the iteration must not even start, so an
            hours-long rerun cannot end in a refused publish.
        ManifestReplacementError: a replacement was requested but there is
            nothing to replace.
    """
    path = manifest_path(iter_dir)
    exists = os.path.exists(path)
    if replacement is None and exists:
        raise ManifestAlreadyPublishedError(
            f"{path} already exists — iteration manifests are write-once (#258). To rerun "
            f"this iteration deliberately, pass --replace_iteration_manifest together with "
            f"--replacement_reason '<why>'; the previous manifest is kept as "
            f"{REPLACED_MANIFEST_PREFIX}<stamp>.json and its digests are recorded in the "
            f"new manifest's provenance."
        )
    if replacement is not None and not exists:
        raise ManifestReplacementError(
            f"--replace_iteration_manifest was given but {path} does not exist — there is "
            f"nothing to replace; launch without the flag."
        )


def _set_aside_previous_manifest(
    path: str, replacement: ManifestReplacementRequest
) -> dict[str, Any]:
    """Rename the previous manifest away and return the provenance block."""
    previous_sha: str | None = None
    previous_run_output_sha: str | None = None
    previous_status: str | None = None
    aside_name: str | None = None
    if os.path.exists(path):
        with open(path, "rb") as handle:
            raw = handle.read()
        previous_sha = hashlib.sha256(raw).hexdigest()
        try:
            previous = json.loads(raw)
        except json.JSONDecodeError:
            previous = None
        if isinstance(previous, dict):
            previous_run_output_sha = previous.get(RUN_OUTPUT_DIGEST_KEY)
            previous_status = previous.get("status")
        directory = os.path.dirname(path)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        aside_name = f"{REPLACED_MANIFEST_PREFIX}{stamp}.json"
        serial = 0
        while os.path.exists(os.path.join(directory, aside_name)):
            serial += 1
            aside_name = f"{REPLACED_MANIFEST_PREFIX}{stamp}.{serial}.json"
        os.rename(path, os.path.join(directory, aside_name))
    return {
        "replaced_at": datetime.now(UTC).isoformat(),
        "replacement_reason": replacement.reason,
        "requested_at": replacement.requested_at,
        "previous_manifest_sha256": previous_sha,
        "previous_run_output_sha256": previous_run_output_sha,
        "previous_manifest_status": previous_status,
        "previous_manifest_path": aside_name,
    }


def publish_iteration_manifest(
    iter_dir: str,
    manifest: dict[str, Any],
    *,
    replacement: ManifestReplacementRequest | None = None,
) -> str:
    """Stamp ``manifest_sha256`` and publish ``iter_dir/manifest.json`` write-once.

    ``manifest`` is mutated in place (the digest and, when replacing, the
    provenance block are added) so the dict the producer returns to its
    caller IS the published content. A caller-supplied ``manifest_sha256``
    is discarded, never trusted.

    Returns:
        The published path.

    Raises:
        ManifestAlreadyPublishedError: the slot is taken and no replacement
            was requested. Nothing on disk changes.
        OSError: the payload could not be made durable.
    """
    path = manifest_path(iter_dir)
    if replacement is not None:
        manifest[MANIFEST_REPLACEMENT_KEY] = _set_aside_previous_manifest(path, replacement)
    manifest.pop(MANIFEST_DIGEST_KEY, None)
    manifest[MANIFEST_DIGEST_KEY] = manifest_self_digest(manifest)
    payload = json.dumps(manifest, indent=2).encode("utf-8")
    try:
        publish_bytes_write_once(path, payload)
    except FileExistsError:
        raise ManifestAlreadyPublishedError(
            f"{path} already exists — iteration manifests are write-once (#258); a "
            f"same-iteration replacement must be requested explicitly with "
            f"--replace_iteration_manifest --replacement_reason '<why>'. The existing "
            f"manifest was NOT modified."
        ) from None
    return path


def verify_iteration_manifest(
    manifest: Mapping[str, Any],
    *,
    iter_idx: int,
    manifest_path: str,
    output_path: str | None,
) -> ManifestVerdict:
    """The replay-integrity predicate, shared by every verifier.

    Rules, in order:

    1. ``manifest_sha256`` present and mismatched → problem (a field edit,
       a hash-only edit, or a consistent artifact+hash rewrite that left
       the self-digest stale).
    2. For a ``completed`` manifest: ``manifest_sha256`` present but
       ``run_output_sha256`` absent → problem (hash removal is a tamper).
       Neither digest → legacy, admitted visibly unverified, no problem.
    3. ``run_output_sha256`` present → the artifact at ``output_path`` must
       hash to it; mismatch → problem, match → ``artifact_verified``.

    ``output_path`` is only consulted under rule 3; pass ``None`` for a
    manifest that names no artifact.
    """
    label = f"iter {iter_idx:03d}"
    recorded_digest = manifest.get(MANIFEST_DIGEST_KEY)
    manifest_verified = False
    if recorded_digest is not None:
        actual_digest = manifest_self_digest(manifest)
        if actual_digest != recorded_digest:
            return ManifestVerdict(
                manifest_verified=False,
                artifact_verified=False,
                problem=(
                    f"{label} manifest changed after publication: {manifest_path} "
                    f"expected manifest_sha256 {str(recorded_digest)[:16]}… but found "
                    f"{actual_digest[:16]}…"
                ),
            )
        manifest_verified = True

    if manifest.get("status") != "completed":
        return ManifestVerdict(manifest_verified, False, None)

    recorded_sha = manifest.get(RUN_OUTPUT_DIGEST_KEY)
    if not recorded_sha:
        if manifest_verified:
            return ManifestVerdict(
                manifest_verified=True,
                artifact_verified=False,
                problem=(
                    f"{label} manifest carries {MANIFEST_DIGEST_KEY} but no "
                    f"{RUN_OUTPUT_DIGEST_KEY} for a completed iteration: {manifest_path} — "
                    f"the artifact hash was removed after publication (or the artifact was "
                    f"missing when the manifest was published); this is not a legacy "
                    f"manifest and the committed history is not trustworthy"
                ),
            )
        return ManifestVerdict(False, False, None)

    if output_path is None or not os.path.isfile(output_path):
        return ManifestVerdict(
            manifest_verified=manifest_verified,
            artifact_verified=False,
            problem=(
                f"{label} manifest records {RUN_OUTPUT_DIGEST_KEY} but its output_path "
                f"{output_path} does not exist"
            ),
            expected_artifact_sha256=str(recorded_sha),
        )
    actual_sha = sha256_file(output_path)
    if actual_sha != recorded_sha:
        return ManifestVerdict(
            manifest_verified=manifest_verified,
            artifact_verified=False,
            problem=(
                f"{label} committed artifact changed: {output_path} expected sha256 "
                f"{str(recorded_sha)[:16]}… but found {actual_sha[:16]}…"
            ),
            expected_artifact_sha256=str(recorded_sha),
            actual_artifact_sha256=actual_sha,
        )
    return ManifestVerdict(
        manifest_verified=manifest_verified,
        artifact_verified=True,
        problem=None,
        expected_artifact_sha256=str(recorded_sha),
        actual_artifact_sha256=actual_sha,
    )
