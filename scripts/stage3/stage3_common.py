"""Stage-3 shared compose-and-score module (stage_artifact_contract.md §4).

The ONE wrapper every Stage-3 writer calls (composed_best / strict_best /
the terminal-evaluation writer — contract §4: "All three writers ... call
THIS function; none re-inlines ``score_vector``").

Frozen semantics implemented here, quoted from the contract:

* Wraps the existing ``score_vector`` authority **EXACTLY ONCE** — one call
  over all 20 files with the canonical committed anchor map (global
  ``s_max`` ruler).
* For each file 0-19, exactly ONE deliverable must resolve across
  ``deliverable_dirs`` — a missing index is a ``NotScoreableError``-class
  refusal (never a silent skip); a duplicate index is a refusal naming both
  paths.
* The frozen TIDMAD score formula is byte-untouched; this module composes
  INPUTS, never arithmetic.

**No per-band scalar exists anywhere in this module** (F-SCAND-1: the
slice-mean aggregation is refused; F-SCAND-4 verified the valid
construction). The reuse anchor is ``scripts/score_tidmad_official_banded.py``
(one pooled deliverable set, one ``score_vector`` call, anchor ``s_max``
ruler) — that script's safety is STRUCTURAL: it computes zero band scalars,
so none can be averaged. This module preserves the property structurally:
per-band information is expressible only as per-FILE vector entries, there is
no aggregation of any kind here (a repo test pins the deliberate omission —
SRI-11), and a partial ``files`` range is refused at the boundary so a band
scalar cannot even be requested.

Deliverable resolution and filename semantics both come from the
``DeliverableNaming`` authority (``execute_tools/deliverable_spec.py``) —
``input_identity_of`` is the contract's own inverse parser, so this module
never restates the filename template with a regex of its own.

``score_vector`` receives ABSOLUTE deliverable paths through
``denoised_filename_fn`` with an inert ``data_dir=""`` — the production-
blessed pass-through: ``os.path.join`` discards the base when the right-hand
side is absolute (``nodes/ml_hyperparameter_tune_agent/records.py``
``_build_denoised_filename`` documents exactly this, and production scoring
already calls ``score_vector`` this way at ``core/sandbox_executor.py:2061``).
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence

from execute_tools.build_anchor_map import default_anchor_map_path, load_anchor_map
from execute_tools.data_paths import TIDMAD_DATA_DIR
from execute_tools.dataset_config import NUM_FILES, SEGMENTS_PER_FILE
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import (
    MetricSpec,
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from execute_tools.scoring_utils import score_vector

#: Contract id stamped on every composition refusal this module raises.
COMPOSITION_CONTRACT_ID = "stage3_compose_and_score"

#: The canonical committed anchor map's global ``s_max`` ruler, pinned to the
#: same value ``scripts/score_tidmad_official_banded.py:74`` pins and checks
#: (its ``EXPECTED_S_MAX``). A different value means a swapped or rebuilt
#: anchor artifact, which would silently re-rule every composed score — so it
#: is refused, exactly as the reuse anchor refuses it.
EXPECTED_S_MAX = 295715680.14248306


def _composition_refusal(
    failures: Sequence[ScoreabilityFailure], *, reconciled_spec: MetricSpec
) -> NotScoreableError:
    """A ``NotScoreableError``-class refusal for a malformed pooled deliverable set.

    Contract §4: a missing file is a "``NotScoreableError``-class refusal,
    never a silent skip". The structured result carries the run metric's own
    identity so the refusal is a typed fact, not an incidental exception.

    Step-09a discipline (local-gate ruling, 2026-08-26): the identity is the
    caller's RECONCILED stamped spec, TRANSPORTED here — this module derives
    nothing (the tuner's derivation is the ONE stamping authority; a fresh
    derivation in the script producing the campaign's published numbers is
    the consumer-re-derivation class 09a closed).

    Args:
        failures: at least one named violation. Each names the requirement,
            the input identity where applicable, and the offending path(s).
        reconciled_spec: the caller's reconciled stamped metric spec — the
            identity every refusal envelope carries.

    Returns:
        The constructed exception, for the caller to ``raise``.
    """
    return NotScoreableError(
        NotScoreableResult(
            metric_id=reconciled_spec.id,
            direction=reconciled_spec.direction,
            verdict=ScoreabilityVerdict(
                contract_id=COMPOSITION_CONTRACT_ID,
                failures=tuple(failures),
            ),
        )
    )


def resolve_pooled_deliverables(
    deliverable_dirs: Sequence[str], *, reconciled_spec: MetricSpec
) -> dict[int, str]:
    """Resolve exactly ONE absolute deliverable path per file index 0..19.

    ``reconciled_spec`` is identity TRANSPORT for the refusal envelopes
    (Step-09a: stamped-and-reconciled by the caller, never derived here).

    Scans each directory (entries in sorted order, directories in caller
    order) for files matching the ``DeliverableNaming`` authority's shipped
    template, parsing the input identity back out with the authority's own
    inverse (``input_identity_of``).

    Refusals (all ``NotScoreableError``-class, all collected before raising
    so one refusal names every violation at once):

    * a listed directory does not exist or is not a directory;
    * a deliverable resolves an input identity outside ``0..NUM_FILES-1``
      (a malformed pooled set, refused rather than silently ignored);
    * the same input identity resolves from two entries — the refusal names
      BOTH absolute paths (contract §4), even when the two entries point at
      the same bytes: a pooled set that lists an input twice is malformed;
    * an input identity in ``0..NUM_FILES-1`` resolves from no entry.

    Args:
        deliverable_dirs: pooled directories, each holding ABRA-format
            ``.h5`` deliverables named by the ``DeliverableNaming`` authority.

    Returns:
        ``{input_identity: absolute_path}`` with keys exactly
        ``0..NUM_FILES-1``.

    Raises:
        NotScoreableError: any of the refusals above.
    """
    naming = DeliverableNaming()
    failures: list[ScoreabilityFailure] = []
    resolved: dict[int, str] = {}
    duplicates: dict[int, list[str]] = {}

    for directory in deliverable_dirs:
        if not os.path.isdir(directory):
            failures.append(
                ScoreabilityFailure(
                    requirement="deliverable_dir_exists",
                    detail=f"not a directory: {os.path.abspath(directory)}",
                )
            )
            continue
        for entry in sorted(os.listdir(directory)):
            identity = naming.input_identity_of(entry)
            if identity is None:
                continue  # not a deliverable of the shipped template
            path = os.path.abspath(os.path.join(directory, entry))
            if not 0 <= identity < NUM_FILES:
                failures.append(
                    ScoreabilityFailure(
                        requirement="input_identity_in_range",
                        input_identity=identity,
                        detail=(
                            f"deliverable resolves input identity {identity}, outside "
                            f"0..{NUM_FILES - 1}: {path}"
                        ),
                    )
                )
                continue
            if identity in resolved:
                duplicates.setdefault(identity, [resolved[identity]]).append(path)
            else:
                resolved[identity] = path

    for identity in sorted(duplicates):
        paths = ", ".join(duplicates[identity])
        failures.append(
            ScoreabilityFailure(
                requirement="exactly_one_deliverable_per_input",
                input_identity=identity,
                detail=f"input identity {identity} resolved from more than one entry: {paths}",
            )
        )

    for identity in range(NUM_FILES):
        if identity not in resolved:
            failures.append(
                ScoreabilityFailure(
                    requirement="exactly_one_deliverable_per_input",
                    input_identity=identity,
                    detail=(
                        f"no deliverable for input identity {identity} in any of: "
                        + ", ".join(os.path.abspath(d) for d in deliverable_dirs)
                    ),
                )
            )

    if failures:
        raise _composition_refusal(failures, reconciled_spec=reconciled_spec)
    return resolved


def compose_and_score(
    deliverable_dirs: list[str],
    *,
    files: range = range(20),
    sample_set: None = None,
    reconciled_spec: MetricSpec,
) -> tuple[list[float], float]:
    """Compose a pooled 20-file deliverable set and score it EXACTLY ONCE.

    The frozen §4 interface of ``docs/campaign/stage_artifact_contract.md``.
    The signature is the contract's, byte-for-byte: ``files`` defaults to the
    full ``0..19`` set and any OTHER range is refused (full-scope by
    contract — a partial range is the forbidden per-band construction,
    F-SCAND-1); ``sample_set`` is typed ``None`` because ``None`` — the FULL
    sample set — is the only legal value here, and a non-``None`` value is
    refused at runtime as well.

    Args:
        deliverable_dirs: pooled directories; each holds ABRA-format ``.h5``
            deliverables. Exactly ONE deliverable must resolve per file
            index across all of them (see
            :func:`resolve_pooled_deliverables`).
        files: must be the full ``range(0, NUM_FILES)``. Present because the
            contract froze it; validated so a band slice is inexpressible.
        sample_set: must be ``None`` (the full sample set — every segment of
            every file). Partial scopes are not legal here.
        reconciled_spec: the caller's RECONCILED stamped ``MetricSpec``
            (§4 amendment, local-gate Step-09a ruling 2026-08-26). Identity
            TRANSPORT only — it names the metric in every refusal envelope
            and never alters composition or arithmetic. Callers obtain it by
            reconciling the persisted 09a stamps of the artifacts they pool
            (``reconcile_metric_specs``); this module derives nothing.

    Returns:
        ``(file_vector, scalar)`` — ``score_vector``'s own 2-tuple: the
        length-``NUM_FILES`` per-file vector and the single scalar. Every
        vector entry is a real number; a file whose entry the scorer could
        not compute (all segments NaN-filtered) is REFUSED, not passed
        through as ``None``.

    Raises:
        ValueError: a scope-pin violation — ``files`` is not the full range,
            ``sample_set`` is not ``None``, or ``deliverable_dirs`` is
            empty. These are caller programming errors, refused so the
            forbidden per-band construction cannot be expressed through this
            module.
        NotScoreableError: a malformed pooled deliverable set (missing /
            duplicate / out-of-range input identity, missing directory), a
            swapped anchor artifact (``s_max`` off the pinned ruler), or a
            per-file entry the scorer could not compute.
    """
    if sample_set is not None:
        raise ValueError(
            "compose_and_score scores the FULL sample set only; sample_set must be None "
            "(stage_artifact_contract.md §4: partial scopes are not legal here)."
        )
    if (files.start, files.stop, files.step) != (0, NUM_FILES, 1):
        raise ValueError(
            f"compose_and_score is full-scope by contract: files must be "
            f"range(0, {NUM_FILES}), got {files!r}. A partial range is the forbidden "
            f"per-band construction (F-SCAND-1: no per-band scalar may exist)."
        )
    if not deliverable_dirs:
        raise ValueError("compose_and_score requires at least one deliverable directory.")
    if not isinstance(reconciled_spec, MetricSpec):
        raise ValueError(
            f"compose_and_score requires the reconciled stamped MetricSpec (identity "
            f"transport for refusal envelopes, Step-09a); got "
            f"{type(reconciled_spec).__name__} — pass the reconcile_metric_specs result, "
            f"never a raw dict and never a fresh derivation."
        )

    resolved = resolve_pooled_deliverables(deliverable_dirs, reconciled_spec=reconciled_spec)

    anchor_data = load_anchor_map(default_anchor_map_path())
    s_max = float(anchor_data["s_max"])
    if not math.isclose(s_max, EXPECTED_S_MAX, rel_tol=0.0, abs_tol=1e-6):
        raise _composition_refusal(
            [
                ScoreabilityFailure(
                    requirement="canonical_anchor_ruler",
                    detail=(
                        f"anchor map s_max {s_max} is not the pinned canonical ruler "
                        f"{EXPECTED_S_MAX} (score_tidmad_official_banded.py:74); refusing "
                        f"to score against a swapped or rebuilt anchor artifact."
                    ),
                )
            ],
            reconciled_spec=reconciled_spec,
        )

    # THE one scoring call (contract §4). Full sample set, canonical anchors,
    # global s_max ruler, non-legacy mode — the reuse anchor's exact
    # construction (score_tidmad_official_banded.py:616-637). data_dir is
    # inert: every filename below is absolute, and os.path.join discards the
    # base for an absolute right-hand side (the Bug-A pass-through production
    # scoring already uses — core/sandbox_executor.py:2061).
    full_sample_set = {index: list(range(SEGMENTS_PER_FILE)) for index in files}
    file_vector, scalar = score_vector(
        data_dir="",
        sample_set=full_sample_set,
        anchor_map=anchor_data["anchors"],
        s_max=s_max,
        denoised_filename_fn=lambda file_index: resolved[int(file_index)],
        raw_data_dir=TIDMAD_DATA_DIR,
        legacy_mode=False,
    )

    vector: list[float] = []
    uncomputable: list[int] = []
    for index, value in enumerate(file_vector):
        if value is None:
            uncomputable.append(index)
        else:
            vector.append(float(value))
    if uncomputable:
        raise _composition_refusal(
            [
                ScoreabilityFailure(
                    requirement="per_file_score_computable",
                    input_identity=index,
                    detail=(
                        f"score_vector produced no per-file value for input identity "
                        f"{index} (every segment was NaN-filtered): {resolved[index]}"
                    ),
                )
                for index in uncomputable
            ],
            reconciled_spec=reconciled_spec,
        )
    return vector, scalar
