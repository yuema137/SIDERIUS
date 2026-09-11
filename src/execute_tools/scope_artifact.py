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


def load_transported_scope(ref: str | None, digest: str | None, *, leg: str) -> object | None:
    """The child half of the scope transport: verify, THEN deserialize.

    Step 12 / PR-12bc B6; RELOCATED here by PR-12d seam C (B6). It lived in
    ``train_engine_sandbox`` while the training child was the only one that
    received a scope. Now that the inference child receives one too, a copy
    there would be the duplicated child-side verification §E.2 forbids — so
    the reader moves beside the writer, and both children import the SAME
    function. The order it enforces is unchanged.

    The same two-case rule every other transported flag follows — SUPPLIED but broken fails closed naming the path; ABSENT leaves
    regime-A to the run itself.

    Order is load-bearing, and is why this is ONE function rather than two
    steps at the call site: the bytes are checked against the digest the PARENT
    transported before the task's parser is ever handed them. A parser's job is
    to build a scope, not to authenticate one.

    Args:
        ref: ``--task_scope_ref`` / ``--task_eval_scope_ref``.
        digest: its out-of-band sha256.
        leg: which leg, for diagnostics only.

    Returns:
        The task's own scope object, or ``None`` when the flag was absent.

    Raises:
        ValueError: The pair is half-supplied.
        ScopeArtifactError: The artifact is missing, unreadable or tampered.
    """
    if ref is None and digest is None:
        return None
    if ref is None or digest is None:
        raise ValueError(
            f"the {leg} scope transport is half-supplied (ref={ref!r}, digest "
            f"{'present' if digest else 'absent'}). A path without its digest "
            f"could not be verified and a digest without a path names nothing — "
            f"refusing rather than proceeding on whichever half arrived."
        )
    from execute_tools.task_data_path import (
        resolve_bound_task_data_path,
        resolve_task_scope_capability,
    )

    # Verify FIRST, then narrow through the ONE resolver. `deserialize_scope`
    # is not on the frozen four-method protocol and must not be: the capability
    # is an optional sibling, so a binding that declares none must produce a
    # named refusal here rather than an AttributeError deep in the engine.
    payload = read_scope_artifact(ref, digest)
    capability = resolve_task_scope_capability(resolve_bound_task_data_path())
    return capability.deserialize_scope(payload)


def task_scope_argv(configs_dir: str, exp_id: str, task_scopes: object) -> list[str]:
    """The composed run's SCOPE transport — empty unless scopes were acquired.

    Step 12 / PR-12bc B6; RELOCATED here by PR-12d seam C. It lived in
    ``core/sandbox_executor.py`` — the launch consumer — while it had one call
    site. With a second child receiving a scope it grew a sibling
    (:func:`validation_rows_argv`), and the launch consumer's own file budget
    named the remedy: *"extract the responsibility into a sibling module
    instead of growing the launch consumer"* (R-11-11). The scope ABI is that
    sibling: this function WRITES the artifacts this module defines and puts
    their paths on argv, so it belongs beside them.

    Follows ``_task_data_path_argv``'s shape exactly: a
    small pure emitter, splatted at the call site, that yields NOTHING when the
    run is un-composed. An un-composed command line is therefore byte-identical
    (R-11-1 / R-11-13), which the B0 fixture pins independently.

    The scope payload itself never rides argv (parent §5.5, frozen): the task's
    canonical bytes are written to a run-scoped ATOMIC artifact and argv carries
    only a path and a digest, so a large or variable-length scope has no
    ``ARG_MAX`` exposure.

    The bytes come from the TASK (``serialize_scope``); this function neither
    inspects nor canonicalizes them.
    """
    from execute_tools.task_data_path import (
        active_task_data_path,
        resolve_task_scope_capability,
    )

    training = getattr(task_scopes, "training", None)
    if training is None:
        return []
    bound = active_task_data_path()
    if bound is None:
        raise ValueError(
            "task scopes were acquired but no task data path is bound, so the "
            "bytes cannot be produced by the implementation that built them."
        )

    # Narrowed through the ONE resolver rather than accessed off `TaskDataPath`:
    # the frozen four-method protocol does NOT declare `serialize_scope`, and it
    # must not — the capability is an optional SIBLING. Reaching for the method
    # directly is what a static checker rejects, and it is right to: the binding
    # here could be an implementation that declares no capability at all, and
    # the resolver is what turns that into a named refusal.
    capability = resolve_task_scope_capability(bound)

    fragment: list[str] = []
    for stem, scope, flag in (
        (TRAINING_SCOPE_STEM, training, "--task_scope"),
        (EVAL_SCOPE_STEM, getattr(task_scopes, "evaluation", None), "--task_eval_scope"),
    ):
        if scope is None:
            continue
        path = scope_artifact_path(configs_dir, stem, exp_id)
        digest = write_scope_artifact(path, capability.serialize_scope(scope))
        fragment.extend([f"{flag}_ref", path, f"{flag}_digest", digest])
    return fragment


def validation_rows_argv(
    task_scopes: object, data_dir: str, *, regime_a_eval_declared: bool
) -> list[str]:
    """The EXPLICIT eval leg's declared row count — emitted ONLY on that leg.

    Step 12 / PR-12d, seam C (B9). ``run_experiment_streaming`` REFUSES an
    explicit ``task_eval_scope`` that arrives without
    ``validation_requested_rows``, and nothing in production emitted one: the
    only two callers that ever supplied it are the in-process D14 Gate
    harnesses, which built their own row lists and therefore knew the number.
    A composed contrast run had no such caller, so its training child refused
    before the first epoch.

    **Leg-gated by F-Q4-2 (v0.1.0).** The training child has TWO validation
    declaration legs and ONE authority per leg, refused crosswise (D14-2 C5b,
    ``train_engine_sandbox.run_experiment_streaming``): under regime-A
    (``--eval_sample_set_json``) the child's own preflight is the ONLY
    declaration authority; only the explicit leg — a transported eval scope
    WITHOUT a regime-A eval SampleSet — consumes this flag. The first cut of
    this emitter gated on scope PRESENCE alone (``task_scopes.evaluation is
    not None``), which is true on EVERY composed run because every shipped
    implementation declares ``build_eval_scope`` — but a composed run whose
    task declares physical geometry (composed TIDMAD) still supplies the
    legacy eval SampleSet too (PR-12bc D-BC-13), so both authorities arrived
    and 5/5 composed training attempts exited on the crosswise refusal before
    epoch 0, zero records. PR-12bc's own audit froze the rule this function
    now implements: under D-BC-13 the composed path is on the regime-A
    declaration leg and ``validation_requested_rows`` must stay ``None`` —
    "threading it would have TRIPPED the first refusal."

    ``regime_a_eval_declared`` is therefore REQUIRED, no default: whether the
    regime-A eval declaration is on this child's argv is the same dichotomy
    the child itself dispatches on (``eval_sample_set is not None``), and the
    caller must answer it from the argv actually being built — never from a
    re-derivation that can drift from the emission site.

    The task-built evaluation scope itself still crosses on the regime-A leg
    (:func:`task_scope_argv` — scope IDENTITY, consumed by the child's R3
    pass); what stays home there is the DECLARATION, whose authority the
    preflight already owns. The two explicit-leg flags — the eval-scope
    ref/digest pair and this count — must never be able to outrun each other:
    this function mirrors :func:`task_scope_argv`'s training-scope early
    return, so the count is emitted only when the eval-scope artifact it
    declares is transported too. A count without a scope would dangle
    silently (the engine arms R3 on ``task_eval_scope``, not on the count);
    a scope without a count on the explicit leg is refused by the engine.

    **Why the count is produced HERE and not by the child.** The child's
    ``TrainingHistory`` asserts ``requested == materialized``, and the
    materialized value comes from the validation pass itself. A declaration
    the child derived would compare the pass to itself and pass for any
    number — CLAUDE.md's "never assert a value read back from the thing under
    test". The declaration has to come from the other side of the boundary,
    which is what makes the check able to catch a scope that crossed
    corrupted or a pass that silently truncated.

    **Why no new capability method.** The count is obtained through
    ``validation_dataset`` — one of the FOUR FROZEN ``TaskDataPath`` methods —
    and ``len()`` on the torch ``Dataset`` the ``DataLoader`` already requires
    to be ``Sized``. Reuse before invention (§D.C): nothing is added to
    ``TaskScopeCapability``, whose four methods 12bc froze.

    **What this costs, corrected at F-12d-35.** This docstring used to claim
    materialization "is lazy for every shipped implementation, so this reads a
    row count, not the data". That is FALSE for TIDMAD, whose
    ``validation_dataset`` builds a ``TIDMADEpochDataset`` over the real
    ``.h5`` files and FAILS CLOSED when materialized != requested. So for any
    run that acquired an evaluation scope, the PARENT touches the dataset
    while building argv, and a missing or short dataset is refused here rather
    than inside the child.

    That is the intended trade — the count must come from the other side of
    the boundary or it proves nothing — but it is a real I/O cost and a real
    failure site, and it went unnoticed until CI (which has no TIDMAD data)
    failed on a test that passed on every developer machine. The F-Q4-2 leg
    gate also returns BEFORE this materialization, so the regime-A leg no
    longer pays parent-side eval I/O for a count the child would have refused.

    Returns ``[]`` when the run is un-composed, acquired no evaluation scope,
    or is on the regime-A declaration leg — so a legacy argv is byte-identical
    and a composed regime-A argv carries exactly ONE validation declaration
    authority.
    """
    from execute_tools.task_data_path import (
        EvalMaterializationParams,
        active_task_data_path,
    )

    evaluation = getattr(task_scopes, "evaluation", None)
    if evaluation is None:
        return []
    # PAIRING (F-Q4-2): mirror `task_scope_argv`'s training-scope early return.
    # Without a training scope that emitter transports NO artifacts — including
    # the eval-scope ref this count declares — and a declaration must never
    # outrun the scope it declares.
    if getattr(task_scopes, "training", None) is None:
        return []
    # LEG (F-Q4-2): under regime-A the child's preflight is the ONLY
    # declaration authority (D14-2 C5b; PR-12bc D-BC-13). The task-built
    # evaluation scope was still acquired and still crosses as scope identity;
    # it is deliberately NOT consumed for validation rows here.
    if regime_a_eval_declared:
        return []
    bound = active_task_data_path()
    if bound is None:
        raise ValueError(
            "an evaluation scope was acquired but no task data path is bound, "
            "so its row count cannot be declared by the implementation that "
            "built it."
        )
    dataset = bound.validation_dataset(evaluation, EvalMaterializationParams(data_dir=data_dir))
    return ["--validation_requested_rows", str(len(dataset))]  # type: ignore[arg-type]
