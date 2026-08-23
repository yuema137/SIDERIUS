"""The scope artifact + digest ABI — ONE identity authority (PR-12bc B4).

Step 12 / PR-12bc, Phase B. The chain every scope crosses the process
boundary through, and the ONE place its identity is computed::

    task scope object
      -> TaskScopeCapability.serialize_scope   (the TASK owns canonicality)
      -> canonical bytes
      -> sha256                                 = scope_digest
      -> ATOMIC write to a run-scoped artifact
      -> argv carries only  <path>  and  <digest>
      -> child: read -> RECOMPUTE the digest -> refuse on mismatch
                        -> only then deserialize

Three properties this module exists to guarantee, each of which the obvious
implementation gets wrong:

**The digest is recomputed, never re-read.** A child that trusted a digest
stored *inside* the artifact would be asking the artifact to vouch for itself.
The expected digest arrives out of band, on argv, from the parent.

**Verification happens BEFORE deserialization.** Handing tampered bytes to a
task's parser and hoping it refuses is not a check — the parser's job is to
build a scope, not to authenticate one. `read_scope_artifact` returns the
payload only after the bytes match, so a caller physically cannot deserialize
first.

**The write is ATOMIC** (tmp + `os.replace`), per the frozen §5.5 ruling and
D-BC-7. This is deliberately unlike the nearest sibling precedent
(`--sample_set_json`, a bare non-atomic `json.dump`): that file's BYTES are a
contract, but nothing reads it concurrently with its writer. A scope artifact
is parent-produced and child-read with identity carried separately, so a torn
read must be impossible rather than merely unlikely. The difference is
recorded rather than silently inherited.

**What this module does NOT do.** It never parses, inspects, canonicalizes or
validates the payload. The payload is the TASK's vocabulary (parent §3 scope
opacity); the framework handles bytes and a hash. A framework site that looked
inside would be the exact defect Q-12-4 removed one layer down.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile

from pydantic import BaseModel, ConfigDict, Field

#: Filename stem for the training-leg artifact, completed as
#: ``<stem>_{exp_id}.json`` under the run's ``dirs["configs"]`` — the existing
#: parent->child artifact convention (``core/sandbox_executor.py:1549``).
TRAINING_SCOPE_STEM = "task_scope"

#: The evaluation leg. A separate artifact rather than two payloads in one
#: file: the two legs are transported by separate flags and either may be
#: absent, and a combined file would make "eval scope absent" and "eval scope
#: empty" the same on-disk state.
EVAL_SCOPE_STEM = "task_eval_scope"


class ScopeArtifactError(RuntimeError):
    """A scope artifact could not be produced or trusted.

    One type for the whole chain, because every member of it has the same
    consequence — the attempt does not run. The MESSAGE distinguishes them,
    and always names the path.
    """


def scope_digest(payload: str) -> str:
    """The scope identity: sha256 over the payload's UTF-8 bytes.

    The ONE digest authority. A second one is not a duplicate implementation
    of a hash, it is a second answer to "which scope did this child execute?".
    """
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scope_artifact_path(configs_dir: str, stem: str, exp_id: str) -> str:
    """``<configs_dir>/<stem>_<exp_id>.json``, absolute.

    Keyed by ``exp_id`` like every sibling artifact, which is also what keeps
    two concurrent attempts from colliding: they have different ids, so they
    have different files.
    """
    return os.path.abspath(os.path.join(configs_dir, f"{stem}_{exp_id}.json"))


def write_scope_artifact(path: str, payload: str) -> str:
    """Write ``payload`` ATOMICALLY and return its digest.

    tmp + ``os.replace`` in the SAME directory, so the rename is atomic on
    POSIX. A reader therefore sees either the previous file or the complete
    new one — never a prefix. The temporary file is removed on any failure,
    so a crashed write leaves no debris to be mistaken for an artifact.

    Args:
        path: Destination, from :func:`scope_artifact_path`.
        payload: The bytes the TASK produced. Written verbatim — the
            framework does not re-canonicalize what it cannot read.

    Returns:
        The digest the child will be asked to reproduce.

    Raises:
        ScopeArtifactError: The destination directory is unusable. Raised at
            the PARENT, before any subprocess is launched.
    """
    directory = os.path.dirname(path)
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        raise ScopeArtifactError(
            f"cannot create the scope artifact directory {directory!r} ({exc}). "
            f"Refused at the parent, before any subprocess was launched."
        ) from exc

    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_path, path)
    except OSError as exc:
        # Failing to remove the temp file must not mask the write failure
        # that is actually being reported.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise ScopeArtifactError(
            f"cannot write the scope artifact {path!r} ({exc}). Refused at the "
            f"parent, before any subprocess was launched."
        ) from exc
    return scope_digest(payload)


def read_scope_artifact(path: str, expected_digest: str) -> str:
    """Read and VERIFY, returning the payload only when the bytes match.

    The verification gate. There is deliberately no "read without checking"
    entry point on this module: a caller cannot deserialize first, because it
    cannot obtain the payload first.

    Args:
        path: The artifact the parent named on argv.
        expected_digest: The digest the parent named on argv — out of band,
            never read from inside the artifact.

    Returns:
        The verified payload, ready for the task's ``deserialize_scope``.

    Raises:
        ScopeArtifactError: Missing, unreadable, or digest mismatch. The
            mismatch message names BOTH digests, so an operator can tell a
            tampered artifact from a stale one at a glance.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = handle.read()
    except FileNotFoundError as exc:
        raise ScopeArtifactError(
            f"the scope artifact named on argv does not exist: {path!r}. The "
            f"parent said it wrote one, so this fails closed rather than "
            f"building a scope of its own."
        ) from exc
    except OSError as exc:
        raise ScopeArtifactError(f"the scope artifact {path!r} is unreadable ({exc}).") from exc

    found = scope_digest(payload)
    if found != expected_digest:
        raise ScopeArtifactError(
            f"scope artifact {path!r} does not match the digest the parent "
            f"transported: expected {expected_digest}, found {found}. The "
            f"bytes changed between the parent writing them and this child "
            f"reading them — refusing BEFORE deserialization, because a "
            f"parser's job is to build a scope, not to authenticate one."
        )
    return payload


class ScopeEvidence(BaseModel):
    """WHICH scope a child executed — the attempt-scope identity stamp.

    Additive evidence, not a persisted-global-schema change (§D.2). The
    composition fingerprint is the task's STATIC identity; a scope varies per
    attempt, so without this a Gate or an adversarial test can only INFER
    which scope ran. Carrying the ref and the digest lets it cite one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    leg: str = Field(min_length=1, description="Which leg — the artifact stem.")
    ref: str = Field(min_length=1, description="Absolute path the child was given.")
    digest: str = Field(
        min_length=64, max_length=64, description="sha256 of the transported payload."
    )
