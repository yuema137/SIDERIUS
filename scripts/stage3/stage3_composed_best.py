"""Stage-3 writer: Composed Best (stage_artifact_contract.md §1, §3, §4).

Pools the four Stage-1 band winners' SOURCE-BAND deliverables and emits ONE
authoritative Composed Best Golden score plus a provenance JSON, under
``{workspace_root}/stage3/composed_best/``.

Winner identification implements the contract's §1 table literally, through
the cited authorities and nothing else:

* completed scoring — ``record["status"] == "success"``;
* FORMAL round — ABSENCE of the ``is_trial`` key (the ``BestTracks``
  authority, ``nodes/ml_hyperparameter_tune_agent/policy.py``: "Formal
  records have no ``is_trial`` key"; the top-level ``trial_portion`` key is
  likewise trial-only, #316 B2). A record carrying ``is_trial`` with any
  value other than ``True``, or carrying ``trial_portion`` without
  ``is_trial``, is a shape production never writes — REFUSED loudly, never
  silently included or excluded;
* HealthGate-valid — ``is_valid_candidate`` (the ONE eligibility authority,
  ``execute_tools/health_checks/candidate_eligibility.py``), resolved
  against the workspace's own pinned ``health_checks_effective.yaml``
  through ``resolve_scientific_gate_ids`` — the resolver's documented
  resume-time pattern, so this consumer cannot disagree with in-run
  selection. A ``None`` resolution (roles unknown) is a refusal, never a
  fallback to the repo-current default;
* direction — ``MetricOrder`` over the run outputs' stamped
  ``metric_spec`` identity. Never assumed higher-is-better; a missing or
  divergent stamp is a refusal.

Deliverable filenames resolve EXCLUSIVELY through the ``DeliverableNaming``
authority for (``model_type``, ``run_name``, ``exp_id``, file index) in the
winning iteration's sandbox base dir (the directory holding the tuner's
``run_output_*.json`` — ``TidmadSandbox.base_dir``, where production writes
deliverables: ``core/sandbox_executor.py:1151`` + ``records.py``'s Bug-A
absolute-path contract).

No per-band scalar exists anywhere in this writer's outputs, logs, or
provenance (F-SCAND-1). Winner provenance entries carry IDENTITY ONLY —
never the winning record's own band-scoped ``denoising_score``, because a
band-scoped aggregate is exactly the scalar this stage must not put next to
three others. Per-band information appears only as per-FILE vector entries.

Reads are strictly read-only against Stage-1 workspaces: the pooled input is
a symlink farm inside the stage3 namespace pointing at the winners' files.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.iteration_manifest import sha256_file, verify_iteration_manifest
from core.run_invariants import load_run_invariants
from execute_tools.build_anchor_map import default_anchor_map_path, load_anchor_map
from execute_tools.dataset_config import NUM_FILES
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import (
    MetricDirection,
    MetricIdentityConflictError,
    MetricSpec,
    StampedMetricSpec,
    metric_spec_from_declaration,
    reconcile_metric_specs,
)
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
    resolve_scientific_gate_ids,
)
from execute_tools.metric_order import MetricOrder
from scripts.stage3.stage3_common import compose_and_score

#: The frozen band vocabulary (stage_artifact_contract.md conventions; the
#: DS8 band grammar "a-b" is INCLUSIVE). Cross-checked at startup to
#: partition the full file set exactly.
BAND_LABELS: tuple[str, ...] = ("0-3", "4-9", "10-14", "15-19")

CONTRACT_DOC = "docs/campaign/stage_artifact_contract.md"
PROVENANCE_KIND = "stage3_composed_best_provenance"
EFFECTIVE_HEALTH_CONFIG = "health_checks_effective.yaml"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Stage3ComposedBestError(RuntimeError):
    """A named Composed Best refusal — the writer stops, nothing is emitted."""


class MetricIdentity(BaseModel):
    """The persisted comparison identity (``metric_id`` + ``direction``).

    ``direction`` is typed by the metric module's own ONE-declaration
    vocabulary (``MetricDirection``), so an output stamped with an unknown
    direction fails validation here rather than reaching ``MetricOrder``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    direction: MetricDirection


class DeliverableProvenance(BaseModel):
    """One pooled deliverable: identity, source path, digest, pooled link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_index: int
    source_path: str
    sha256: str
    pooled_link: str


class BandWinnerProvenance(BaseModel):
    """One band winner's IDENTITY (contract §1) — no score fields.

    Deliberately scalar-free: the winner's own ``denoising_score`` is a
    band-scoped aggregate and never appears in Stage-3 outputs (F-SCAND-1;
    identity fields are sufficient to locate the record).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    band: str
    workspace: str
    iteration: str
    exp_id: str
    model_type: str
    run_name: str
    experiment_arm: str
    deliverables: list[DeliverableProvenance]


class ComposedBestProvenance(BaseModel):
    """The emitted provenance document — the ONE authoritative artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(default=PROVENANCE_KIND)
    contract: str = Field(default=CONTRACT_DOC)
    arm: str
    metric: MetricIdentity
    winners: list[BandWinnerProvenance]
    anchor_map_path: str
    anchor_map_sha256: str
    s_max: float
    file_vector: list[float]
    denoising_score: float
    computed_at_utc: str
    repo_sha: str | None


class _BandWinner(BaseModel):
    """Internal selection result for one band (identity + resolved paths)."""

    model_config = ConfigDict(frozen=True)

    band: str
    workspace: str
    iteration: str
    exp_id: str
    model_type: str
    run_name: str
    experiment_arm: str
    metric: MetricSpec  # the workspace's RECONCILED 09a stamp (full spec)
    deliverable_paths: dict[int, str]


def band_file_indices(label: str) -> list[int]:
    """Parse an inclusive DS8 band label ``"a-b"`` into ``[a..b]``."""
    start_text, _, end_text = label.partition("-")
    start, end = int(start_text), int(end_text)
    if end < start:
        raise Stage3ComposedBestError(f"malformed band label {label!r}")
    return list(range(start, end + 1))


def assert_band_partition(labels: tuple[str, ...], num_files: int) -> None:
    """Refuse unless the band vocabulary partitions ``0..num_files-1`` exactly."""
    covered: list[int] = []
    for label in labels:
        covered.extend(band_file_indices(label))
    if sorted(covered) != list(range(num_files)) or len(covered) != num_files:
        raise Stage3ComposedBestError(
            f"band vocabulary {labels} does not partition 0..{num_files - 1}: {sorted(covered)}"
        )


def _iteration_dirs(workspace: str) -> list[tuple[int, str]]:
    """``(index, path)`` for every ``iter_NNN`` dir, ascending.

    Matches exactly ``iter_`` + three digits, mirroring the chain runner's
    own resume scan (``run_one_iteration.py``), so artefacts like
    ``iter_001.bak`` are never swept in.
    """
    results: list[tuple[int, str]] = []
    for name in sorted(os.listdir(workspace)):
        if len(name) == 8 and name.startswith("iter_") and name[5:].isdigit():
            results.append((int(name[5:]), os.path.join(workspace, name)))
    results.sort()
    return results


def _resolve_output_path(manifest: dict[str, Any], iter_dir: str) -> str:
    """The run-output artifact path, rebased if the workspace moved.

    The manifest records absolute paths from launch time; a relocated
    workspace root invalidates them. Rebasing is safe because the manifest's
    ``run_output_sha256`` is verified against the resolved artifact —
    content addressing, not path trust.
    """
    output_path = manifest.get("output_path")
    if not isinstance(output_path, str) or not output_path:
        raise Stage3ComposedBestError(
            f"completed manifest in {iter_dir} carries no output_path — refusing."
        )
    if os.path.isfile(output_path):
        return output_path
    recorded_iter_dir = manifest.get("iteration_dir")
    if isinstance(recorded_iter_dir, str) and recorded_iter_dir:
        tail = os.path.relpath(output_path, recorded_iter_dir)
        if not tail.startswith(".."):
            rebased = os.path.join(iter_dir, tail)
            if os.path.isfile(rebased):
                return rebased
    raise Stage3ComposedBestError(
        f"run output named by {iter_dir} manifest does not exist: {output_path}"
    )


def _load_completed_iteration(
    iter_index: int, iter_dir: str, arm: str | None
) -> tuple[dict[str, Any], str] | None:
    """Load and VERIFY one iteration's tuner output; ``None`` if not completed.

    Strict campaign mode: the manifest self-digest AND the run-output digest
    must both verify (``verify_iteration_manifest`` rules 1-3). A legacy
    digest-less manifest is refused — the golden score does not build on
    unverifiable provenance.

    ``arm=None`` skips the arm cross-check (Stage-2 retrain-unit workspaces
    carry no arm concept — strict_best's spec sourcing reads them through
    this same verified loader).
    """
    manifest_file = os.path.join(iter_dir, "manifest.json")
    if not os.path.isfile(manifest_file):
        return None
    with open(manifest_file, encoding="utf-8") as handle:
        manifest = json.load(handle)
    status = manifest.get("status")
    if status in ("failed", "no_records"):
        # A failed/record-less iteration has no consumable output; a success
        # record cannot hide in one (its score would have made it completed).
        return None
    if status != "completed":
        raise Stage3ComposedBestError(
            f"unknown manifest status {status!r} in {manifest_file} — refusing."
        )
    output_path = _resolve_output_path(manifest, iter_dir)
    verdict = verify_iteration_manifest(
        manifest, iter_idx=iter_index, manifest_path=manifest_file, output_path=output_path
    )
    if verdict.problem is not None:
        raise Stage3ComposedBestError(verdict.problem)
    if not (verdict.manifest_verified and verdict.artifact_verified):
        raise Stage3ComposedBestError(
            f"iteration manifest {manifest_file} carries no verifiable digests "
            f"(legacy pre-#258 shape) — the composed golden score refuses "
            f"unverifiable provenance."
        )
    with open(output_path, encoding="utf-8") as handle:
        output = json.load(handle)
    if not isinstance(output, dict):
        raise Stage3ComposedBestError(f"run output at {output_path} is not a JSON object.")
    if arm is not None:
        _check_arm_stamp(manifest.get("experiment_arm"), f"manifest {manifest_file}", arm)
    return output, output_path


def _check_arm_stamp(stamp: Any, source: str, arm: str) -> None:
    """Cross-check an OPTIONAL arm stamp against the launch arm.

    Absent stamps are tolerated (the manifest omission rule writes the key
    only when it departs from the legacy default); a PRESENT stamp must
    match exactly.
    """
    if stamp is not None and stamp != arm:
        raise Stage3ComposedBestError(
            f"experiment_arm mismatch: {source} carries {stamp!r}, expected {arm!r}."
        )


def _formal_role(record: dict[str, Any], where: str) -> bool:
    """True iff the record is FORMAL — ``is_trial`` absent or ``False``.

    Q-S3-3 (2026-08-26): the contract's "absence of the ``is_trial`` key"
    describes the BUILDER's in-memory dicts (``policy.py``: the key is set
    only when ``trial_config.is_trial``), but the records Stage-3 READS are
    the persisted ``run_output_*.json`` ``all_records`` — and
    ``HyperparamTuningOutput.all_records: list[ExperimentRecord]``
    re-validates every dict into the model, so ``model_dump()``
    (``records.py:1048``) MATERIALIZES the defaults ``is_trial: False`` and
    ``trial_portion: None`` onto every persisted FORMAL record. The
    BestTracks authority's own test is falsy-tolerant
    (``not r.get("is_trial", False)`` — ``policy.py:650``); this predicate
    matches it. The literal absence test (and its loud refusal of
    ``is_trial: False``) would have refused EVERY real formal record.

    ``is_trial: True`` == trial (excluded, normal). A NON-BOOL ``is_trial``,
    or a NON-None ``trial_portion`` (a trial-only value, #316 B2) on a
    record whose ``is_trial`` is not ``True``, is a shape production never
    writes — refused loudly rather than silently classified either way,
    because a silent choice could silently move the winner.
    """
    role = record.get("is_trial")
    if role is True:
        return False
    if role is not None and role is not False:
        raise Stage3ComposedBestError(
            f"record {where} carries is_trial={role!r} — a non-bool role is a "
            f"shape production never writes; refusing an anomalous role shape."
        )
    if record.get("trial_portion") is not None:
        raise Stage3ComposedBestError(
            f"record {where} is formal-shaped (is_trial={role!r}) but carries "
            f"trial_portion={record['trial_portion']!r} — a trial-only value "
            f"(#316 B2); refusing."
        )
    return True


def _stamped_metric_spec(output: dict[str, Any], output_path: str) -> MetricSpec:
    """The run output's stamped ``MetricSpec`` (09a stamp); absence refuses.

    Step-09a discipline: this VALIDATES a transported stamp — it derives
    nothing, and a pre-09a output (no stamp, or a stamp that is not a full
    ``MetricSpec``) is a NAMED refusal, never a default.
    """
    raw = output.get("metric_spec")
    if not isinstance(raw, dict):
        raise Stage3ComposedBestError(
            f"run output {output_path} carries no metric_spec stamp — a pre-09a "
            f"output refuses; direction is never assumed (contract §1)."
        )
    try:
        # The ONE sanctioned rebind for a persisted spec mapping — a bare
        # MetricSpec.model_validate cannot re-instantiate the ABSTRACT
        # scoreability field from its own dump (its docstring's verified
        # 3-error refusal).
        return metric_spec_from_declaration(raw)
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        raise Stage3ComposedBestError(
            f"run output {output_path} carries a malformed metric_spec stamp "
            f"(not a full MetricSpec): {exc}"
        ) from exc


class _Candidate(BaseModel):
    """One eligible formal record with the context needed to resolve deliverables."""

    model_config = ConfigDict(frozen=True)

    score: float
    exp_id: str
    model_type: str
    run_name: str
    iteration: str
    base_dir: str


def _eligible_candidates(
    output: dict[str, Any],
    output_path: str,
    iteration_name: str,
    required_gate_ids: frozenset[str],
    arm: str,
) -> list[_Candidate]:
    """§1-eligible records of one iteration output, in record order."""
    run_name = output.get("run_name")
    if not isinstance(run_name, str) or not run_name:
        raise Stage3ComposedBestError(f"run output {output_path} carries no run_name.")
    _check_arm_stamp(output.get("experiment_arm"), f"run output {output_path}", arm)
    candidates: list[_Candidate] = []
    records = output.get("all_records")
    if not isinstance(records, list):
        raise Stage3ComposedBestError(f"run output {output_path} all_records is not a list.")
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise Stage3ComposedBestError(
                f"run output {output_path} all_records[{position}] is not an object."
            )
        where = f"{output_path} all_records[{position}]"
        if record.get("status") != "success":
            continue
        if not _formal_role(record, where):
            continue
        if not is_valid_candidate(record, required_gate_ids=required_gate_ids):
            continue
        exp_id = record.get("exp_id")
        model_type = record.get("model_type")
        score = record.get("denoising_score")
        if not isinstance(exp_id, str) or not isinstance(model_type, str):
            raise Stage3ComposedBestError(f"eligible record {where} lacks exp_id/model_type.")
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise Stage3ComposedBestError(f"eligible record {where} lacks a numeric score.")
        candidates.append(
            _Candidate(
                score=float(score),
                exp_id=exp_id,
                model_type=model_type,
                run_name=run_name,
                iteration=iteration_name,
                base_dir=os.path.dirname(output_path),
            )
        )
    return candidates


def select_band_winner(workspace_root: str, arm: str, band: str) -> _BandWinner:
    """The band's cumulative best HealthGate-valid FORMAL winner (contract §1)."""
    indices = band_file_indices(band)
    workspace = os.path.join(workspace_root, f"{arm}_band{band}")
    if not os.path.isdir(workspace):
        raise Stage3ComposedBestError(f"band workspace does not exist: {workspace}")

    lock = load_run_invariants(workspace)
    if lock is None:
        raise Stage3ComposedBestError(f"no run_invariants_lock.json in {workspace} — refusing.")
    if lock.experiment_arm != arm:
        raise Stage3ComposedBestError(
            f"lock experiment_arm {lock.experiment_arm!r} in {workspace} does not match "
            f"the launch arm {arm!r}."
        )
    if sorted(lock.resolved_data_scope) != indices:
        raise Stage3ComposedBestError(
            f"lock resolved_data_scope {sorted(lock.resolved_data_scope)} in {workspace} "
            f"is not the band's file set {indices} — this is not the band's workspace."
        )

    effective_config = os.path.join(workspace, EFFECTIVE_HEALTH_CONFIG)
    if not os.path.isfile(effective_config):
        raise Stage3ComposedBestError(
            f"missing pinned effective HealthGate config: {effective_config}"
        )
    required_gate_ids = resolve_scientific_gate_ids(effective_config)
    if required_gate_ids is None:
        raise Stage3ComposedBestError(
            f"scientific gate roles cannot be established from {effective_config} — "
            f"eligibility is UNKNOWN, refusing (never a fallback to the repo default)."
        )

    candidates: list[_Candidate] = []
    stamped_specs: list[StampedMetricSpec] = []
    for iter_index, iter_dir in _iteration_dirs(workspace):
        loaded = _load_completed_iteration(iter_index, iter_dir, arm)
        if loaded is None:
            continue
        output, output_path = loaded
        stamped_specs.append(
            StampedMetricSpec(
                label=f"run output {output_path}",
                spec=_stamped_metric_spec(output, output_path),
            )
        )
        candidates.extend(
            _eligible_candidates(
                output, output_path, os.path.basename(iter_dir), required_gate_ids, arm
            )
        )

    if not stamped_specs:
        raise Stage3ComposedBestError(f"no completed iterations in {workspace}.")
    # ONE reconciliation authority, never a hand-rolled equality (local-gate
    # Step-09a ruling, 2026-08-26): whole specs are compared, and any
    # disagreement across this workspace's iterations fails closed.
    try:
        metric = reconcile_metric_specs(stamped_specs)
    except MetricIdentityConflictError as exc:
        raise Stage3ComposedBestError(
            f"metric identity diverges across iterations in {workspace}: {exc}"
        ) from exc
    if metric is None:  # unreachable: _stamped_metric_spec refuses absent stamps
        raise Stage3ComposedBestError(
            f"no iteration in {workspace} carries a metric_spec stamp — refusing."
        )
    if not candidates:
        raise Stage3ComposedBestError(
            f"no HealthGate-valid formal winner in {workspace} (contract §1 conditions)."
        )

    order = MetricOrder(metric)
    winner = order.best(candidates, key=lambda candidate: candidate.score)

    naming = DeliverableNaming()
    deliverable_paths: dict[int, str] = {}
    for index in indices:
        name = naming.name(
            model_type=winner.model_type,
            run_name=winner.run_name,
            exp_id=winner.exp_id,
            input_identity=index,
        )
        path = os.path.join(winner.base_dir, name)
        if not os.path.isfile(path):
            raise Stage3ComposedBestError(
                f"winner deliverable missing for file {index}: {path} — the Stage-1 "
                f"retention clause requires formal-round deliverables to be kept "
                f"(contract §1); refusing."
            )
        deliverable_paths[index] = path

    return _BandWinner(
        band=band,
        workspace=workspace,
        iteration=winner.iteration,
        exp_id=winner.exp_id,
        model_type=winner.model_type,
        run_name=winner.run_name,
        experiment_arm=arm,
        metric=metric,
        deliverable_paths=deliverable_paths,
    )


def materialize_pooled_input(out_root: str, winners: list[_BandWinner]) -> str:
    """Build the pooled 20-link input dir inside the stage3 namespace.

    Symlinks only — Stage-1 workspaces are never written to. Built fresh in
    a temp dir and swapped in; a pre-existing pooled dir is verified to be
    all-symlink before removal (this writer never deletes real data).
    """
    pooled = os.path.join(out_root, "pooled_input")
    tmp = f"{pooled}.tmp-{os.getpid()}"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    for winner in winners:
        for _, source in sorted(winner.deliverable_paths.items()):
            link = os.path.join(tmp, os.path.basename(source))
            if os.path.lexists(link):
                raise Stage3ComposedBestError(
                    f"pooled link name collision: {os.path.basename(source)} "
                    f"(bands {', '.join(w.band for w in winners)})"
                )
            os.symlink(source, link)
    if os.path.isdir(pooled):
        for entry in os.listdir(pooled):
            if not os.path.islink(os.path.join(pooled, entry)):
                raise Stage3ComposedBestError(
                    f"refusing to replace {pooled}: {entry} is not a symlink."
                )
        shutil.rmtree(pooled)
    os.rename(tmp, pooled)
    return pooled


def _repo_sha() -> str | None:
    """Best-effort git HEAD of the repo this writer ran from."""
    try:
        result = subprocess.run(
            ["git", "-C", _REPO_ROOT, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def build_provenance(
    arm: str,
    winners: list[_BandWinner],
    pooled: str,
    file_vector: list[float],
    scalar: float,
) -> ComposedBestProvenance:
    """Assemble the provenance document (identity-only winners, one scalar)."""
    anchor_path = default_anchor_map_path()
    winner_blocks: list[BandWinnerProvenance] = []
    for winner in winners:
        deliverables = [
            DeliverableProvenance(
                file_index=index,
                source_path=source,
                sha256=sha256_file(source),
                pooled_link=os.path.join(pooled, os.path.basename(source)),
            )
            for index, source in sorted(winner.deliverable_paths.items())
        ]
        winner_blocks.append(
            BandWinnerProvenance(
                band=winner.band,
                workspace=winner.workspace,
                iteration=winner.iteration,
                exp_id=winner.exp_id,
                model_type=winner.model_type,
                run_name=winner.run_name,
                experiment_arm=winner.experiment_arm,
                deliverables=deliverables,
            )
        )
    return ComposedBestProvenance(
        arm=arm,
        metric=MetricIdentity(id=winners[0].metric.id, direction=winners[0].metric.direction),
        winners=winner_blocks,
        anchor_map_path=anchor_path,
        anchor_map_sha256=sha256_file(anchor_path),
        s_max=float(load_anchor_map(anchor_path)["s_max"]),
        file_vector=file_vector,
        denoising_score=scalar,
        computed_at_utc=datetime.now(UTC).isoformat(),
        repo_sha=_repo_sha(),
    )


def _write_provenance(out_root: str, provenance: ComposedBestProvenance) -> str:
    """Atomically write the provenance JSON (same-dir temp + replace)."""
    path = os.path.join(out_root, "composed_best_provenance.json")
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(provenance.model_dump(mode="json"), handle, indent=2, allow_nan=False)
        handle.write("\n")
    os.replace(tmp, path)
    return path


def run(workspace_root: str, arm: str) -> str:
    """Select, pool, score once, emit provenance. Returns the provenance path."""
    assert_band_partition(BAND_LABELS, NUM_FILES)

    winners = [select_band_winner(workspace_root, arm, band) for band in BAND_LABELS]
    # Cross-band agreement through the ONE reconciliation authority, never a
    # hand-rolled equality (local-gate Step-09a ruling, 2026-08-26).
    try:
        reconciled = reconcile_metric_specs(
            [
                StampedMetricSpec(label=f"band {winner.band} winner", spec=winner.metric)
                for winner in winners
            ]
        )
    except MetricIdentityConflictError as exc:
        raise Stage3ComposedBestError(f"metric identity diverges across bands: {exc}") from exc
    if reconciled is None:  # unreachable: every winner carries a validated stamp
        raise Stage3ComposedBestError("no band winner carries a metric_spec stamp — refusing.")
    for winner in winners:
        print(
            f"[stage3.composed_best] band {winner.band} winner: {winner.iteration} "
            f"exp_id={winner.exp_id} model_type={winner.model_type} "
            f"run_name={winner.run_name}"
        )

    out_root = os.path.join(workspace_root, "stage3", "composed_best", arm)
    os.makedirs(out_root, exist_ok=True)
    pooled = materialize_pooled_input(out_root, winners)

    file_vector, scalar = compose_and_score([pooled], reconciled_spec=reconciled)

    provenance = build_provenance(arm, winners, pooled, file_vector, scalar)
    path = _write_provenance(out_root, provenance)

    print(f"[stage3.composed_best] Composed Best Golden score (denoising_score): {scalar}")
    for index, value in enumerate(file_vector):
        print(f"[stage3.composed_best]   file {index:04d}: {value}")
    print(f"[stage3.composed_best] provenance: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description=(
            "Stage-3 Composed Best: pool the four Stage-1 band winners' source-band "
            "deliverables and score the composed 20-file set exactly once "
            "(stage_artifact_contract.md §1/§3/§4)."
        )
    )
    parser.add_argument(
        "--workspace_root",
        required=True,
        help="The campaign's persistent workspace root (contract conventions).",
    )
    parser.add_argument(
        "--arm",
        required=True,
        help="The campaign arm label (opaque; must match each workspace's lock).",
    )
    args = parser.parse_args(argv)
    try:
        run(args.workspace_root, args.arm)
    except Stage3ComposedBestError as error:
        print(f"[stage3.composed_best] REFUSED: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
