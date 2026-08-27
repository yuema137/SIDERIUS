"""Stage-3 terminal 100% champion re-evaluation (stage artifact contract, PR #329 §3).

Semantics (operator-frozen): after search freezes and the champion is
selected, ONE terminal full-scope (100% eval scope) measurement is taken.
Selection happens FIRST; the terminal number NEVER feeds back into search.

Everything this module writes lives under the contract's terminal
namespace, ``{workspace_root}/stage3/terminal_eval/`` — the ISOLATION
namespace. The contract's frozen isolation rule (§3): nothing under that
directory is ever read by any search, selection, tuning, or
scoring-for-selection code path. This module is the namespace's ONE
producer, and it enforces its side of the rule structurally:

- every output path is validated against the terminal namespace **at
  construction** (:class:`TerminalOutputLayout`); an outside path is a
  named :class:`TerminalNamespaceViolationError` before any side effect;
- a champion without HealthGate-valid provenance is refused by name
  (:class:`InvalidChampionError`) through the ONE eligibility authority,
  ``classify_under_pinned_policy`` (``execute_tools/health_checks/
  candidate_eligibility.py``), against the gate set the champion's OWN
  workspace pinned — a numerically excellent invalid champion must NOT be
  terminal-evaluated as a success, and neither must an UNKNOWN one;
- the read-closure guard (:func:`audit_terminal_read_closure` /
  :func:`assert_terminal_read_closure`) enumerates the input roots of
  every search-side consumer per the contract's enumerated-roots clause
  and proves the terminal namespace is in none of them — including
  detecting a terminal artifact *planted* inside a search-consumable
  root (every artifact emitted here self-declares its namespace, so a
  copied plant is recognizable);
- no band-level scalar is ever emitted (campaign-lane hazard flag,
  2026-08-26): the terminal score exists only at full 0..19 scope, and
  per-band information may appear only as per-FILE vector entries. The
  write path refuses band-shaped scalar fields
  (:class:`BandScalarEmissionError`).

Scoring goes through the shared ``compose_and_score`` wrapper (contract
§4, frozen signature) owned by ``scripts/stage3/stage3_common.py``. That
module lands in a parallel writer's PR, so it is resolved dynamically at
call time; :class:`ComposeAndScoreFn` pins the frozen signature at this
seam. This module never re-inlines ``score_vector``.

Contract change control: the search-side consumer enumeration
(:data:`SEARCH_SIDE_CONSUMERS`) and the namespace segments
(:data:`TERMINAL_NAMESPACE_SEGMENTS`) are executable images of the
contract's frozen clauses. Any edit here is a CONTRACT change and must be
made in ``docs/campaign/stage_artifact_contract.md`` first; the pinned
tests in ``tests/unit/scripts/stage3/test_terminal_eval.py`` fail loudly
otherwise.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from execute_tools.build_anchor_map import default_anchor_map_path
from execute_tools.evaluation_metric import MetricSpec, MetricSpecField
from execute_tools.health_checks.candidate_eligibility import (
    CandidateHealthValidity,
    classify_under_pinned_policy,
    pinned_workspace_gate_ids,
)

# ---------------------------------------------------------------------------
# Frozen contract constants
# ---------------------------------------------------------------------------

#: Contract §3: the terminal namespace, relative to ``{workspace_root}``.
TERMINAL_NAMESPACE_SEGMENTS: tuple[str, str] = ("stage3", "terminal_eval")

#: The self-declaration every terminal artifact carries. The read-closure
#: guard recognizes a planted terminal artifact by THIS declaration, not by
#: filename convention.
ARTIFACT_NAMESPACE_KEY = "artifact_namespace"
TERMINAL_NAMESPACE_MARKER = "/".join(TERMINAL_NAMESPACE_SEGMENTS)

#: The frozen scope declaration stamped on every terminal artifact: the
#: terminal measurement is full-scope by contract (§4: ``files=range(20)``,
#: ``sample_set=None`` — the FULL sample set).
TERMINAL_SCOPE_DECLARATION = "100%"
TERMINAL_FILE_COUNT = 20

#: Contract header: the DS8 band vocabulary. Used ONLY by guards (the
#: Stage-1 root globs and the band-scalar emission refusal) — never as an
#: artifact field.
BAND_LABELS: tuple[str, str, str, str] = ("0-3", "4-9", "10-14", "15-19")


# ---------------------------------------------------------------------------
# Named refusals
# ---------------------------------------------------------------------------


class TerminalEvalError(Exception):
    """Base class for every named refusal of the terminal evaluation writer."""


class InvalidChampionError(TerminalEvalError):
    """Champion without HealthGate-valid provenance — refused by name.

    Raised BEFORE any scoring and BEFORE any artifact write: an invalid
    champion must not be terminal-evaluated as a success (the operator's
    negative control), however excellent its number.
    """


class TerminalNamespaceViolationError(TerminalEvalError):
    """An output path outside the terminal namespace — refused at construction."""


class ReadClosureViolationError(TerminalEvalError):
    """The terminal namespace is reachable from a search-side input root."""


class VacuousReadClosureError(TerminalEvalError):
    """The read-closure guard had nothing to prove (SRI-9: a guard that
    scans an empty enumeration or resolves zero roots is vacuously green
    and must refuse instead)."""


class BandScalarEmissionError(TerminalEvalError):
    """A band-level scalar field was about to be emitted into a terminal
    artifact (campaign-lane hazard flag, 2026-08-26: per-band information
    is expressed only as per-FILE vector entries)."""


class ComposeAndScoreUnavailableError(TerminalEvalError):
    """The shared compose-and-score module (contract §4) cannot be imported."""


# ---------------------------------------------------------------------------
# The shared compose-and-score seam (contract §4 — frozen signature)
# ---------------------------------------------------------------------------

#: The module that owns the ONE compose-and-score wrapper. It lands in a
#: parallel writer's PR, so it is resolved dynamically (a static import
#: would also fail pyright's ``reportMissingImports`` until it lands).
COMPOSE_AND_SCORE_MODULE = "scripts.stage3.stage3_common"
COMPOSE_AND_SCORE_ATTR = "compose_and_score"


class ComposeAndScoreFn(Protocol):
    """Contract §4 FROZEN signature of the shared compose-and-score wrapper."""

    def __call__(
        self,
        deliverable_dirs: list[str],
        *,
        files: range = ...,
        sample_set: None = ...,
        reconciled_spec: MetricSpec,
    ) -> tuple[list[float], float]: ...


def _resolve_compose_and_score() -> ComposeAndScoreFn:
    """Resolve the shared wrapper from :data:`COMPOSE_AND_SCORE_MODULE`.

    Raises:
        ComposeAndScoreUnavailableError: when the module has not landed in
            this checkout yet, or does not export the frozen attribute.
    """
    try:
        module = importlib.import_module(COMPOSE_AND_SCORE_MODULE)
    except ModuleNotFoundError as exc:
        raise ComposeAndScoreUnavailableError(
            f"shared compose-and-score module {COMPOSE_AND_SCORE_MODULE!r} is not "
            "importable in this checkout (contract §4; it lands in the parallel "
            "stage3_common writer's PR)."
        ) from exc
    fn = getattr(module, COMPOSE_AND_SCORE_ATTR, None)
    if fn is None:
        raise ComposeAndScoreUnavailableError(
            f"{COMPOSE_AND_SCORE_MODULE!r} does not export {COMPOSE_AND_SCORE_ATTR!r} "
            "(contract §4 frozen interface)."
        )
    return cast(ComposeAndScoreFn, fn)


# ---------------------------------------------------------------------------
# Champion input (contract §1 identity fields; §4 deliverable source)
# ---------------------------------------------------------------------------


class ChampionIdentity(BaseModel):
    """Contract §1 winner identity: ``exp_id``, ``model_type``, ``iteration``
    (dir), ``experiment_arm`` (lock + manifest)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exp_id: str = Field(min_length=1)
    model_type: str = Field(min_length=1)
    iteration: int = Field(ge=1)
    experiment_arm: str = Field(min_length=1)


class TerminalChampion(BaseModel):
    """The selected champion handed to terminal evaluation.

    ``deliverable_dirs`` is the pooled deliverable source in the shape the
    shared ``compose_and_score`` wrapper takes (contract §4). Per-file
    resolution (exactly one deliverable per file 0-19, refusals for
    missing/duplicates) is THAT wrapper's authority — never re-implemented
    here.

    ``provenance_records`` are the persisted ``ExperimentRecord`` dicts
    backing the champion (one per contributing winner/unit). Eligibility is
    decided by the ONE authority in
    ``execute_tools/health_checks/candidate_eligibility.py``; an empty list is
    "without HealthGate-valid provenance" and is refused by name.
    """

    model_config = ConfigDict(extra="forbid")

    identity: ChampionIdentity
    deliverable_dirs: list[str] = Field(min_length=1)
    provenance_records: list[dict[str, Any]] = Field(default_factory=list)
    #: The run workspace whose PINNED ``health_checks_effective.yaml`` governs
    #: every record in ``provenance_records`` (F-4). Required, and required
    #: rather than defaulted because the value it would default to — the
    #: repo-current shipped config — is a DIFFERENT run's policy, and judging
    #: a record against a roster its run never declared is the defect this
    #: field exists to make unstatable. Whoever assembles the champion knows
    #: which workspace produced its provenance; this module must not guess.
    #: A champion pooling records from runs with DIFFERENT Health declarations
    #: is not expressible here and must not be assembled.
    provenance_workspace: Path
    #: The champion's RECONCILED 09a metric stamp (local-gate Step-09a
    #: ruling, 2026-08-26): stamped by whoever assembles the champion from
    #: the winner's persisted outputs, TRANSPORTED here, and never derived
    #: by this module. Required — a spec-less champion is a pre-09a shape
    #: and refuses at validation. ``MetricSpecField`` is the round-trip-safe
    #: annotation (the ONE sanctioned rebind for persisted spec mappings).
    metric_spec: MetricSpecField


def require_healthgate_valid(champion: TerminalChampion) -> None:
    """Refuse a champion without HealthGate-valid provenance, by name.

    Every provenance record must classify VALID under the ONE eligibility
    authority (called exactly as the contract writes it — never
    re-implemented from gate fields). UNKNOWN is not valid: a record whose
    gates are absent or not established is a refusal, not a pass.

    **F-4 — the gate set comes from the champion's OWN pinned effective
    config**, resolved by ``pinned_workspace_gate_ids`` exactly as
    ``stage3_composed_best.select_band_winner`` resolves a band's. The
    zero-argument default this used to take reads the REPO-CURRENT shipped
    config, which belongs to no particular run, and collapses UNKNOWN to the
    empty set — so a champion whose run-declared blocking gate FAILED could
    be terminal-evaluated as a success. A workspace that pinned no roster is
    UNKNOWN and refuses here, which is the same answer the docstring above
    already promised.

    Raises:
        InvalidChampionError: naming the champion and the failing record.
    """
    identity = champion.identity
    if not champion.provenance_records:
        raise InvalidChampionError(
            f"champion {identity.exp_id!r} (model_type={identity.model_type!r}, "
            f"iteration={identity.iteration}, arm={identity.experiment_arm!r}) has NO "
            "provenance records: without HealthGate-valid provenance it must not be "
            "terminal-evaluated."
        )
    required_gate_ids = pinned_workspace_gate_ids(champion.provenance_workspace)
    for index, record in enumerate(champion.provenance_records):
        validity = classify_under_pinned_policy(record, required_gate_ids)
        if validity is not CandidateHealthValidity.VALID:
            record_exp_id = record.get("exp_id", "<missing exp_id>")
            raise InvalidChampionError(
                f"champion {identity.exp_id!r} (model_type={identity.model_type!r}, "
                f"iteration={identity.iteration}, arm={identity.experiment_arm!r}) is NOT "
                f"HealthGate-valid: provenance record {index} (exp_id={record_exp_id!r}) "
                f"classified {validity.value!r} against the gate set pinned by "
                f"{str(champion.provenance_workspace)!r} — a numerically excellent "
                "invalid champion must not be terminal-evaluated as a success, and an "
                "UNKNOWN one is a refusal rather than a pass."
            )


# ---------------------------------------------------------------------------
# Terminal namespace + output layout (refusal at construction)
# ---------------------------------------------------------------------------


def terminal_namespace(workspace_root: Path) -> Path:
    """The contract §3 terminal namespace for ``workspace_root``, resolved."""
    root = Path(workspace_root).resolve()
    return root.joinpath(*TERMINAL_NAMESPACE_SEGMENTS)


class TerminalOutputLayout(BaseModel):
    """Where terminal artifacts go — validated against the namespace at
    construction, BEFORE any filesystem side effect.

    An ``input_dir`` / ``results_dir`` that resolves outside
    ``{workspace_root}/stage3/terminal_eval/`` raises
    :class:`TerminalNamespaceViolationError` from the constructor itself
    (the model validator), so a mis-relocated layout can never be built,
    let alone written to.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_root: Path
    input_dir: Path | None = None
    results_dir: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def _refuse_paths_outside_terminal_namespace(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_root = data.get("workspace_root")
        if raw_root is None:
            return data  # let Pydantic report the missing required field
        namespace = terminal_namespace(Path(raw_root))
        resolved_data = dict(data)
        for field_name, default_leaf in (("input_dir", "input"), ("results_dir", "results")):
            raw = data.get(field_name)
            candidate = Path(os.path.join(namespace, default_leaf)) if raw is None else Path(raw)
            # `resolve()` collapses `..` traversal and follows existing
            # symlinks, so an escape cannot hide behind either.
            candidate = (
                candidate if candidate.is_absolute() else Path(os.path.join(namespace, candidate))
            )
            resolved_path = candidate.resolve()
            if not resolved_path.is_relative_to(namespace):
                raise TerminalNamespaceViolationError(
                    f"{field_name}={str(candidate)!r} resolves to {str(resolved_path)!r}, "
                    f"outside the terminal namespace {str(namespace)!r} "
                    "(contract §3 isolation rule): refused at construction."
                )
            resolved_data[field_name] = resolved_path
        return resolved_data

    @property
    def namespace(self) -> Path:
        return terminal_namespace(self.workspace_root)

    @property
    def champion_input_path(self) -> Path:
        assert self.input_dir is not None  # populated by the validator
        return Path(os.path.join(self.input_dir, "champion.json"))

    @property
    def score_path(self) -> Path:
        assert self.results_dir is not None  # populated by the validator
        return Path(os.path.join(self.results_dir, "terminal_score.json"))

    @property
    def provenance_path(self) -> Path:
        assert self.results_dir is not None  # populated by the validator
        return Path(os.path.join(self.results_dir, "terminal_provenance.json"))


# ---------------------------------------------------------------------------
# Band-scalar emission refusal (campaign-lane hazard flag, 2026-08-26)
# ---------------------------------------------------------------------------


def _is_band_shaped_key(key: str) -> bool:
    return key in BAND_LABELS or "band" in key.lower()


def _numeric_descendant(value: Any, path: str = "") -> str | None:
    """Relative path of the first numeric (non-bool) reachable in ``value``.

    ``""`` means the value ITSELF is numeric. ``None`` means the whole
    subtree holds no numeric at any depth.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return path
    if isinstance(value, dict):
        for key, item in value.items():
            found = _numeric_descendant(item, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            found = _numeric_descendant(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _refuse_band_scalars(payload: Any, *, artifact: str, key_path: str = "$") -> None:
    """Refuse any band-level scalar field in a terminal artifact payload.

    A band-shaped KEY (one of the four band labels, or any key containing
    ``band``) whose subtree holds a numeric value at ANY depth is a
    band-level aggregation and is refused — a directly numeric value, a
    sequence containing numerics, or a nested object carrying the number a
    level down (F-VAL-1, adversarial-validator finding 2026-08-26: the
    original guard tested only the DIRECT value, so
    ``{"band_0-3": {"final_scalar": ...}}`` escaped — the exact F-SCAND-1
    smuggling shape). Band tokens inside string VALUES (e.g. a source
    deliverable path ``.../goldA_band0-3/...``) are provenance, not
    scalars, and pass.

    Raises:
        BandScalarEmissionError: naming the artifact, the band-shaped key,
            and where in its subtree the numeric lives.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{key_path}.{key}"
            if isinstance(key, str) and _is_band_shaped_key(key):
                found = _numeric_descendant(value)
                if found is not None:
                    where = child_path if found == "" else f"{child_path}{found}"
                    raise BandScalarEmissionError(
                        f"terminal artifact {artifact!r} would emit a band-level scalar "
                        f"field at {where!r} (under band-shaped key {child_path!r}): the "
                        "terminal score exists only at full 0..19 scope; per-band "
                        "information is expressed only as per-FILE vector entries."
                    )
            _refuse_band_scalars(value, artifact=artifact, key_path=child_path)
    elif isinstance(payload, list | tuple):
        for index, item in enumerate(payload):
            _refuse_band_scalars(item, artifact=artifact, key_path=f"{key_path}[{index}]")


# ---------------------------------------------------------------------------
# Artifact writing (namespace-checked, band-scalar-checked, atomic)
# ---------------------------------------------------------------------------


def _terminal_envelope(kind: str) -> dict[str, Any]:
    return {
        ARTIFACT_NAMESPACE_KEY: TERMINAL_NAMESPACE_MARKER,
        "artifact_kind": kind,
        "scope": TERMINAL_SCOPE_DECLARATION,
        "generated_utc": datetime.now(UTC).isoformat(),
    }


def _write_terminal_json(layout: TerminalOutputLayout, path: Path, payload: dict[str, Any]) -> None:
    """Write one terminal artifact: namespace defense-in-depth + band-scalar
    refusal + atomic replace."""
    resolved = path.resolve()
    if not resolved.is_relative_to(layout.namespace):
        raise TerminalNamespaceViolationError(
            f"refusing to write {str(path)!r}: outside the terminal namespace "
            f"{str(layout.namespace)!r} (contract §3 isolation rule)."
        )
    _refuse_band_scalars(payload, artifact=path.name)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp = resolved.with_name(resolved.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, resolved)


# ---------------------------------------------------------------------------
# Provenance inputs
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_deliverables(deliverable_dirs: Sequence[str]) -> dict[str, dict[str, str]]:
    """sha256 of every ``.h5`` deliverable offered in each source dir.

    This records exactly what was OFFERED to the shared wrapper; per-file
    resolution semantics stay inside ``compose_and_score`` (contract §4).
    """
    hashes: dict[str, dict[str, str]] = {}
    for dir_str in deliverable_dirs:
        directory = Path(dir_str)
        if not directory.is_dir():
            raise TerminalEvalError(
                f"champion deliverable dir does not exist or is not a directory: {dir_str!r}"
            )
        hashes[dir_str] = {
            entry.name: _sha256_file(entry) for entry in sorted(directory.glob("*.h5"))
        }
    return hashes


def _resolve_repo_sha(repo_root: Path) -> str | None:
    """Best-effort ``git rev-parse HEAD`` for provenance; ``None`` when
    unavailable (recorded explicitly as null, never guessed)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


_REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# The terminal evaluation itself
# ---------------------------------------------------------------------------


class TerminalEvalResult(BaseModel):
    """What one terminal measurement produced, and where it was persisted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ChampionIdentity
    file_vector: list[float]
    denoising_score: float
    champion_input_path: Path
    score_path: Path
    provenance_path: Path


def run_terminal_eval(
    champion: TerminalChampion,
    workspace_root: Path,
    *,
    compose_and_score_fn: ComposeAndScoreFn | None = None,
    anchor_map_path: Path | None = None,
    repo_sha: str | None = None,
    layout: TerminalOutputLayout | None = None,
) -> TerminalEvalResult:
    """Take the ONE terminal full-scope measurement of the selected champion.

    Order is load-bearing:

    1. the output layout is constructed (an out-of-namespace path refuses
       HERE, before any side effect);
    2. the champion's HealthGate validity is established through the ONE
       authority (an invalid champion refuses BEFORE any scoring and
       BEFORE any write);
    3. provenance inputs (deliverable hashes, anchor sha) are captured;
    4. the shared ``compose_and_score`` wrapper is called EXACTLY ONCE with
       its frozen full-scope defaults (contract §4);
    5. the artifact set is written under the terminal namespace ONLY.

    Args:
        champion: the selected champion (identity + deliverable source +
            HealthGate provenance records).
        workspace_root: the campaign's persistent root (contract header).
        compose_and_score_fn: test seam; ``None`` resolves the shared
            wrapper from :data:`COMPOSE_AND_SCORE_MODULE`.
        anchor_map_path: test seam; ``None`` uses the committed canonical
            anchor map (``reference_data/segment_anchors.json``).
        repo_sha: test seam; ``None`` resolves ``git rev-parse HEAD``
            best-effort (recorded as null when unresolvable).
        layout: test seam; ``None`` builds the contract-default layout.

    Returns:
        The measurement and its persisted artifact paths.

    Raises:
        InvalidChampionError: champion without HealthGate-valid provenance.
        TerminalNamespaceViolationError: an output path outside the
            terminal namespace.
        TerminalEvalError: missing deliverable dir / anchor map, or a
            wrapper result that is not the full 20-entry file vector.
    """
    if layout is None:
        layout = TerminalOutputLayout(workspace_root=workspace_root)

    # Refusal BEFORE any compute and BEFORE any write: selection happened
    # first, and an invalid champion is never terminal-evaluated.
    require_healthgate_valid(champion)

    fn = compose_and_score_fn if compose_and_score_fn is not None else _resolve_compose_and_score()

    anchor = (
        Path(anchor_map_path) if anchor_map_path is not None else Path(default_anchor_map_path())
    )
    if not anchor.is_file():
        raise TerminalEvalError(f"canonical anchor map not found: {str(anchor)!r}")
    anchor_sha = _sha256_file(anchor)

    deliverable_hashes = _hash_deliverables(champion.deliverable_dirs)

    # Contract §4: the frozen defaults ARE the full scope — this caller
    # never narrows `files` and never passes a partial `sample_set`. The
    # champion's reconciled 09a stamp is identity transport for the
    # composer's refusal envelopes (§4 amendment, 2026-08-26).
    file_vector, scalar = fn(list(champion.deliverable_dirs), reconciled_spec=champion.metric_spec)
    file_vector = [float(value) for value in file_vector]
    if len(file_vector) != TERMINAL_FILE_COUNT:
        raise TerminalEvalError(
            f"compose_and_score returned {len(file_vector)} file-vector entries; the "
            f"terminal measurement is full-scope by contract ({TERMINAL_FILE_COUNT} files)."
        )
    scalar = float(scalar)

    resolved_repo_sha = repo_sha if repo_sha is not None else _resolve_repo_sha(_REPO_ROOT)
    identity_payload = champion.identity.model_dump()

    champion_payload = {
        **_terminal_envelope("terminal_input_champion"),
        "champion": identity_payload,
        "deliverable_dirs": list(champion.deliverable_dirs),
        "provenance": {
            "record_count": len(champion.provenance_records),
            "record_exp_ids": [record.get("exp_id") for record in champion.provenance_records],
            "healthgate_valid": True,
            "eligibility_authority": (
                "execute_tools.health_checks.candidate_eligibility.classify_under_pinned_policy"
            ),
            # WHICH policy that authority was asked about — the champion's own
            # pinned effective config, not the repo-current shipped one.
            "eligibility_policy_workspace": str(champion.provenance_workspace),
        },
    }
    score_payload = {
        **_terminal_envelope("terminal_score"),
        "champion": identity_payload,
        "metric_id": champion.metric_spec.id,
        "metric_direction": champion.metric_spec.direction,
        "file_vector": file_vector,
        "denoising_score": scalar,
    }
    provenance_payload = {
        **_terminal_envelope("terminal_provenance"),
        "champion": identity_payload,
        "deliverable_hashes": deliverable_hashes,
        "anchor_map": {"path": str(anchor), "sha256": anchor_sha},
        "repo_sha": resolved_repo_sha,
    }

    _write_terminal_json(layout, layout.champion_input_path, champion_payload)
    _write_terminal_json(layout, layout.score_path, score_payload)
    _write_terminal_json(layout, layout.provenance_path, provenance_payload)

    return TerminalEvalResult(
        identity=champion.identity,
        file_vector=file_vector,
        denoising_score=scalar,
        champion_input_path=layout.champion_input_path,
        score_path=layout.score_path,
        provenance_path=layout.provenance_path,
    )


# ---------------------------------------------------------------------------
# Read-closure guard (contract §3 isolation rule, executable image)
# ---------------------------------------------------------------------------


class SearchSideConsumer(BaseModel):
    """One search-side consumer and its contract-enumerated input roots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    input_root_globs: tuple[str, ...]
    contract_clause: str


#: The contract's enumerated-roots clause as data. §3 isolation rule (a):
#: "no Stage-1/2 workspace and no Stage-3 writer A/B takes a path under
#: terminal_eval/ as input (their input roots are enumerated above and are
#: disjoint from it)". Editing this tuple is a CONTRACT change (see module
#: docstring); the pin test hardcodes it.
SEARCH_SIDE_CONSUMERS: tuple[SearchSideConsumer, ...] = (
    SearchSideConsumer(
        name="stage1_band_chain_workspaces",
        input_root_globs=tuple(f"*_band{band}" for band in BAND_LABELS),
        contract_clause=(
            "§1 — {arm}_band{BAND} chain workspaces: the search chain's own input "
            "root, and the input roots composed_best pools winners from"
        ),
    ),
    SearchSideConsumer(
        name="stage2_retrain_units",
        input_root_globs=("stage2/*",),
        contract_clause=(
            "§2 — stage2/{design}_{target_band} retrain units: each unit's own chain "
            "workspace plus the deliverables/ dirs strict_best reads"
        ),
    ),
    SearchSideConsumer(
        name="stage3_composed_best_pool",
        input_root_globs=("stage3/composed_best",),
        contract_clause="§3 — writer pool consumed by champion selection",
    ),
    SearchSideConsumer(
        name="stage3_strict_best_pool",
        input_root_globs=("stage3/strict_best",),
        contract_clause="§3 — writer pool consumed by champion selection",
    ),
)

#: Size cap for plant-detection JSON parsing (terminal artifacts are small;
#: anything larger is not one of ours and the realpath check still applies).
_PLANT_SCAN_MAX_BYTES = 4 * 1024 * 1024


class ReadClosureViolation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    consumer: str
    root: Path
    path: Path
    detail: str


class ReadClosureReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    terminal_root: Path
    roots_by_consumer: dict[str, tuple[Path, ...]]
    entries_scanned: int
    violations: tuple[ReadClosureViolation, ...]

    @property
    def total_roots(self) -> int:
        return sum(len(roots) for roots in self.roots_by_consumer.values())


def _declares_terminal_namespace(path: Path) -> bool:
    """Whether a file self-declares as a terminal artifact (the emitted
    envelope's ``artifact_namespace`` marker)."""
    if path.suffix != ".json":
        return False
    try:
        if path.stat().st_size > _PLANT_SCAN_MAX_BYTES:
            return False
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get(ARTIFACT_NAMESPACE_KEY) == (
        TERMINAL_NAMESPACE_MARKER
    )


def audit_terminal_read_closure(
    workspace_root: Path,
    *,
    consumers: Sequence[SearchSideConsumer] = SEARCH_SIDE_CONSUMERS,
) -> ReadClosureReport:
    """Prove (or disprove) the contract §3 isolation rule over a workspace.

    Enumerates the input roots of every search-side consumer and checks:

    1. no enumerated root overlaps the terminal namespace (in either
       direction — a consumer root inside ``terminal_eval/``, or a root
       that CONTAINS it, both violate);
    2. no path reachable under an enumerated root resolves (symlinks
       followed) into the terminal namespace;
    3. no file under an enumerated root self-declares as a terminal
       artifact (a copied plant carries the emitted envelope's namespace
       marker even though its realpath does not escape).

    Raises:
        VacuousReadClosureError: when ``consumers`` is empty — an empty
            enumeration proves nothing (SRI-9).
    """
    if not consumers:
        raise VacuousReadClosureError(
            "search-side consumer enumeration is EMPTY: the read-closure guard has "
            "nothing to prove and must refuse rather than pass vacuously (SRI-9)."
        )
    root = Path(workspace_root).resolve()
    ns = terminal_namespace(root)
    roots_by_consumer: dict[str, tuple[Path, ...]] = {}
    violations: list[ReadClosureViolation] = []
    entries_scanned = 0

    for consumer in consumers:
        resolved_roots: list[Path] = []
        for pattern in consumer.input_root_globs:
            for candidate in sorted(root.glob(pattern)):
                if not candidate.is_dir():
                    continue
                resolved_roots.append(candidate)
                candidate_r = candidate.resolve()
                if candidate_r.is_relative_to(ns) or ns.is_relative_to(candidate_r):
                    violations.append(
                        ReadClosureViolation(
                            kind="enumerated_root_overlaps_terminal_namespace",
                            consumer=consumer.name,
                            root=candidate,
                            path=candidate_r,
                            detail=(
                                f"consumer input root {str(candidate)!r} overlaps the "
                                f"terminal namespace {str(ns)!r}"
                            ),
                        )
                    )
                    continue
                for dirpath, dirnames, filenames in os.walk(candidate, followlinks=False):
                    base = Path(dirpath)
                    for name in (*dirnames, *filenames):
                        entry = Path(os.path.join(base, name))
                        entries_scanned += 1
                        try:
                            entry_real = entry.resolve()
                        except OSError:
                            continue
                        if entry_real.is_relative_to(ns):
                            violations.append(
                                ReadClosureViolation(
                                    kind="consumable_path_resolves_into_terminal_namespace",
                                    consumer=consumer.name,
                                    root=candidate,
                                    path=entry,
                                    detail=(
                                        f"{str(entry)!r} resolves to {str(entry_real)!r} "
                                        "inside the terminal namespace"
                                    ),
                                )
                            )
                        elif entry.is_file() and _declares_terminal_namespace(entry):
                            violations.append(
                                ReadClosureViolation(
                                    kind="terminal_artifact_inside_search_consumable_root",
                                    consumer=consumer.name,
                                    root=candidate,
                                    path=entry,
                                    detail=(
                                        f"{str(entry)!r} self-declares "
                                        f"{ARTIFACT_NAMESPACE_KEY}="
                                        f"{TERMINAL_NAMESPACE_MARKER!r}: a terminal "
                                        "artifact is planted in a search-consumable root"
                                    ),
                                )
                            )
        roots_by_consumer[consumer.name] = tuple(resolved_roots)

    return ReadClosureReport(
        terminal_root=ns,
        roots_by_consumer=roots_by_consumer,
        entries_scanned=entries_scanned,
        violations=tuple(violations),
    )


def assert_terminal_read_closure(
    workspace_root: Path,
    *,
    consumers: Sequence[SearchSideConsumer] = SEARCH_SIDE_CONSUMERS,
) -> ReadClosureReport:
    """The strict form: refuse on any violation, and refuse vacuity.

    Raises:
        VacuousReadClosureError: empty enumeration, or an enumeration that
            resolved ZERO roots in this workspace (a guard that scanned
            nothing proved nothing — SRI-9).
        ReadClosureViolationError: any violation, each named.
    """
    report = audit_terminal_read_closure(workspace_root, consumers=consumers)
    if report.total_roots == 0:
        raise VacuousReadClosureError(
            f"no search-side input root resolved under {str(workspace_root)!r}: the "
            "read-closure guard scanned nothing and refuses to pass vacuously (SRI-9)."
        )
    if report.violations:
        rendered = "; ".join(
            f"[{violation.kind}] {violation.detail}" for violation in report.violations
        )
        raise ReadClosureViolationError(
            f"terminal namespace isolation violated (contract §3): {rendered}"
        )
    return report


# ---------------------------------------------------------------------------
# SRI-11 census: the reserved namespace name has ONE production owner
# ---------------------------------------------------------------------------

#: Production files allowed to reference the reserved namespace name.
#: Contract §3 rule (b): the directory name is reserved — any future
#: consumer must change the contract first, then this allowlist (and the
#: pin test) loudly.
CENSUS_ALLOWED_PRODUCTION_REFERENCES: frozenset[str] = frozenset(
    {"scripts/stage3/stage3_terminal_eval.py"}
)

#: The reserved name, spelled once.
TERMINAL_NAMESPACE_TOKEN = TERMINAL_NAMESPACE_SEGMENTS[1]


def _tracked_production_python_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z", "--", "*.py"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise TerminalEvalError(
            "census requires a git checkout (git ls-files failed); pass an explicit "
            "file_set instead."
        )
    files = [
        Path(os.path.join(repo_root, rel))
        for raw in result.stdout.split(b"\0")
        if (rel := raw.decode("utf-8")) and not rel.startswith("tests/")
    ]
    return files


def census_terminal_namespace_references(
    repo_root: Path,
    *,
    file_set: Iterable[Path] | None = None,
) -> tuple[str, ...]:
    """Every production ``.py`` file referencing the reserved namespace name
    outside the allowed owner set.

    ``file_set=None`` enumerates ALL tracked production ``.py`` files
    (``git ls-files``, ``tests/`` excluded) — the census never silently
    narrows its file set. An empty enumeration refuses (SRI-9).

    Returns:
        Repo-relative offender paths, sorted.
    """
    files = list(file_set) if file_set is not None else _tracked_production_python_files(repo_root)
    if not files:
        raise VacuousReadClosureError(
            "census file set is EMPTY: an empty census proves nothing (SRI-9)."
        )
    offenders: list[str] = []
    for path in files:
        rel = os.path.relpath(path, repo_root)
        if rel in CENSUS_ALLOWED_PRODUCTION_REFERENCES:
            continue
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if TERMINAL_NAMESPACE_TOKEN in text:
            offenders.append(rel)
    return tuple(sorted(offenders))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Terminal evaluation entrypoint.

    A refusal (invalid champion, namespace violation, missing inputs) exits
    non-zero with the named reason on stderr — it must never look like a
    successful terminal measurement.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument(
        "--champion_json",
        required=True,
        type=Path,
        help="Path to a JSON file with the TerminalChampion shape "
        "(identity + deliverable_dirs + provenance_records).",
    )
    parser.add_argument(
        "--workspace_root",
        required=True,
        type=Path,
        help="The campaign's persistent workspace root (contract header).",
    )
    args = parser.parse_args(argv)

    try:
        champion = TerminalChampion.model_validate_json(
            args.champion_json.read_text(encoding="utf-8")
        )
        result = run_terminal_eval(champion, args.workspace_root)
    except (TerminalEvalError, OSError, ValidationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        f"terminal denoising_score={result.denoising_score} "
        f"(scope {TERMINAL_SCOPE_DECLARATION}, {len(result.file_vector)} files)"
    )
    print(f"score:      {result.score_path}")
    print(f"provenance: {result.provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
