"""Adversarial fixture library for the Stage-3 Gold-campaign contract.

**What this module is.** The INDEPENDENT validator's side of the Stage-3
work. It fabricates contract-conformant Stage-1 / Stage-2 / Stage-3 trees
under a caller-supplied temporary ``workspace_root``, together with the
parameterized CORRUPTIONS the witness tests need, plus the two census
scanners and the two monkeypatch helpers those witnesses run against a
writer's real module.

**Built from the contract alone.** The only specification consulted is
``docs/campaign/stage_artifact_contract.md`` (Lane F, FROZEN). No Stage-3
writer branch and no writer worktree was read while building this, because
a harness that mirrors the implementation it validates cannot catch a
defect the two share.

**Where it is NOT independent — deliberately.** Every fact the contract
delegates to a landed production authority is resolved by CALLING that
authority, never by restating it:

===================================  ====================================
fact                                 authority
===================================  ====================================
deliverable filenames                ``DeliverableNaming`` (``name`` /
                                     ``any_glob`` / ``input_identity_of``)
which gates a valid candidate needs  ``required_blocking_gate_ids``
whether a record is a valid          ``is_valid_candidate``
candidate
gate-result record shape             ``PersistedHealthGateResult``
record / tuner-output shape          ``ExperimentRecord`` /
                                     ``HyperparamTuningOutput``
iteration manifest + self-digest     ``publish_iteration_manifest``
effective Health config + its sha    ``materialize_effective_config``
run-invariants lock                  ``RunInvariants``
metric identity and direction        ``TIDMAD_METRIC_ID`` /
                                     ``MetricIdentityKey`` / ``MetricOrder``
===================================  ====================================

A fixture that hand-rolls ``abra_validation_denoised_{...}.h5`` would pass
against a writer that hand-rolls the same template and fail against one
that correctly asks the authority; that is the exact inversion this table
exists to prevent.

**Known fixture limitations, stated rather than hidden.**

* Deliverables are placeholder bytes carrying the HDF5 magic signature.
  They satisfy "the file exists, is named correctly and sniffs as HDF5";
  they are NOT readable by ``h5py``. Every witness here stubs the scoring
  authority, so no witness opens one. A phase-2 witness that needs a real
  scorer must build real HDF5 instead — see ``DELIVERABLE_PAYLOAD_NOTE``.
* Scores planted here are arbitrary ordering material. They are not
  physically meaningful and must never be quoted as evidence about a model.

**Hard constraint honoured by every artifact this module writes**: no
per-band SCALAR is ever produced. Band names appear in PATHS and as STRING
labels (``target_band: "4-9"``); no artifact maps a band identifier to a
number. ``COMPLETE.json``'s ``denoising_score`` is a UNIT-level scalar,
which contract §2 declares explicitly.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Iterable, Iterator, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from core.iteration_manifest import publish_iteration_manifest
from core.run_invariants import RunInvariants
from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import (
    TIDMAD_METRIC_ID,
    MetricIdentityKey,
    derive_tidmad_metric_spec,
)
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
    required_blocking_gate_ids,
)
from execute_tools.health_checks.config import materialize_effective_config
from execute_tools.health_checks.schemas import PersistedHealthGateResult
from execute_tools.metric_order import MetricOrder
from scripts.stage3.stage3_terminal_eval import (
    ARTIFACT_NAMESPACE_KEY,
    TERMINAL_NAMESPACE_MARKER,
)

#: The repository this harness validates, derived from THIS file's location.
#: ``tests/unit/scripts/stage3/<this file>`` -> four parents to the root.
#: Never an absolute literal: a hardcoded path silently reads a different
#: clone and a green run then says nothing about the code under test.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]

DELIVERABLE_PAYLOAD_NOTE: Final[str] = (
    "placeholder deliverable: correct name, HDF5 magic signature, no readable "
    "HDF5 content. Witnesses stub the scoring authority and never open it."
)

# HDF5 signature, so a magic-byte sniff succeeds while an h5py open honestly
# fails rather than silently reading zeros.
_HDF5_MAGIC: Final[bytes] = b"\x89HDF\r\n\x1a\n"

# --------------------------------------------------------------------------
# Band vocabulary — contract "Conventions" line, cross-checked against
# scripts/score_tidmad_official_banded.py:77 (``BANDS = [(0,4),(4,10),
# (10,15),(15,20)]``, from TIDMAD train.py ``ifile_checkpoint``). The labels
# are INCLUSIVE on both ends; the production tuples are half-open. That
# mismatch is precisely the off-by-one W1a/W1b exist to catch, so it is
# written out here once and never recomputed.
# --------------------------------------------------------------------------

NUM_FILES: Final[int] = 20

BAND_LABELS: Final[tuple[str, str, str, str]] = ("0-3", "4-9", "10-14", "15-19")

BAND_FILES: Final[Mapping[str, tuple[int, ...]]] = {
    "0-3": (0, 1, 2, 3),
    "4-9": (4, 5, 6, 7, 8, 9),
    "10-14": (10, 11, 12, 13, 14),
    "15-19": (15, 16, 17, 18, 19),
}

#: The metric identity a TIDMAD campaign record carries. Direction is read
#: from here by every consumer; nothing in this module assumes "higher".
TIDMAD_METRIC_IDENTITY: Final[MetricIdentityKey] = MetricIdentityKey(
    id=TIDMAD_METRIC_ID, direction="higher"
)


def band_of_file(file_index: int) -> str:
    """The band label owning ``file_index``.

    Raises:
        ValueError: for an index outside 0..19.
    """
    for label, files in BAND_FILES.items():
        if file_index in files:
            return label
    raise ValueError(f"file_index {file_index} is outside the band map {BAND_LABELS}")


# --------------------------------------------------------------------------
# Corruption vocabularies
# --------------------------------------------------------------------------


class Stage1Corruption(StrEnum):
    """Which adversarial defect a Stage-1 layout is built to carry."""

    NONE = "none"
    #: W1a — the 4-9 winner's deliverable set is short exactly one file at
    #: the band's UPPER boundary (file 0009 absent).
    MISSING_BAND_UPPER_BOUNDARY = "missing_band_upper_boundary"
    #: W1b — file 0004 is resolvable from BOTH the 0-3 pool and the 4-9
    #: pool, as an off-by-one band map on the LOWER boundary would produce.
    DUPLICATE_BAND_LOWER_BOUNDARY = "duplicate_band_lower_boundary"


class Stage2Corruption(StrEnum):
    """Which adversarial defect a Stage-2 tree is built to carry."""

    NONE = "none"
    #: W2a — one design quad has 3 completed units and 1 stale partial:
    #: deliverables/ populated, COMPLETE.json absent.
    STALE_PARTIAL_UNIT = "stale_partial_unit"
    #: W2b — one unit's COMPLETE.json carries ``healthgate_valid: false``.
    HEALTHGATE_INVALID_UNIT = "healthgate_invalid_unit"


class FinalizerOutcome(StrEnum):
    """What ``strict_best`` must do with a given Stage-2 tree.

    **Q-S3-1, ruled A by the supervisor (2026-08-26).** ``strict_best`` is a
    FINALIZER and it FAILS CLOSED: an incomplete or HealthGate-invalid unit
    does not get filtered out so the run can continue on what remains — it
    refuses the whole finalization, naming every failing unit, calls the
    scoring wrapper ZERO times, writes no selection artifact, and exits
    nonzero.

    The "absence == unit not done, partial dirs are ignored" reading in
    contract §2/§3 governs the Stage-2 POLLER only. The distinction matters
    because the two readings are indistinguishable on a HEALTHY tree and
    differ completely on a degraded one — which is the only tree that
    matters.
    """

    #: Every unit is complete and HealthGate-valid: finalization proceeds.
    PROCEED = "proceed"
    #: At least one unit fails: one aggregated refusal, nothing scored.
    REFUSE = "refuse"


#: Process exit code a refusing finalizer is expected to return. Not a
#: contract value — the implementers' convention, supplied by the manager
#: with the Q-S3-1 ruling. Named here so a phase-2 witness asserting it
#: cites one place rather than a bare literal.
EXPECTED_REFUSAL_EXIT_CODE: Final[int] = 2


#: The band whose boundaries both Stage-1 corruptions attack. 4-9 is chosen
#: because it has BOTH neighbours, so an upper-boundary omission and a
#: lower-boundary duplicate are expressible on the same band.
CORRUPTION_BAND: Final[str] = "4-9"

#: The exact file identities the two Stage-1 corruptions act on. Hardcoded,
#: never derived from ``BAND_FILES``: a witness whose expectation is
#: recomputed from the same map the fixture used cannot see that map being
#: wrong.
MISSING_FILE_IDENTITY: Final[int] = 9
DUPLICATED_FILE_IDENTITY: Final[int] = 4


# --------------------------------------------------------------------------
# Planted-fact carriers
# --------------------------------------------------------------------------


class DecoyReason(StrEnum):
    """Why a planted record must NOT be selected as a band winner.

    Each value names one clause of the contract §1 winner table, so a
    phase-2 failure reports which rule the writer dropped.
    """

    TRIAL_ROUND = "trial_round"
    HEALTHGATE_INVALID = "healthgate_invalid"
    STATUS_NOT_SUCCESS = "status_not_success"
    WORSE_SCORE_LATER_ITERATION = "worse_score_later_iteration"


class PlantedDecoy(BaseModel):
    """A record deliberately planted to be rejected, and the rule it tests."""

    model_config = ConfigDict(frozen=True)

    band: str
    exp_id: str
    iteration: int
    denoising_score: float | None
    reason: DecoyReason


class PlantedWinner(BaseModel):
    """The band winner this fixture PLANTED, as a hardcoded expectation.

    Nothing about this is read back from the code under test: the builder
    decides the winner, and the witness asserts the writer found this one.
    """

    model_config = ConfigDict(frozen=True)

    band: str
    arm: str
    run_name: str
    model_type: str
    exp_id: str
    iteration: int
    denoising_score: float
    #: The tuner sandbox ``base_dir`` holding this winner's deliverables.
    #: Contract §1 says "the iteration's tuner sandbox data dir (base_dir)";
    #: ``base_dir`` is the operative half — see ``CONTRACT_NOTES``.
    deliverable_dir: Path
    #: Identities actually written, AFTER any corruption.
    deliverable_files: tuple[int, ...]
    #: The band's full file set — what a conformant winner must provide.
    expected_files: tuple[int, ...]


class Stage1Layout(BaseModel):
    """A fabricated Stage-1 arm: four band chain workspaces and their winners."""

    model_config = ConfigDict(frozen=True)

    workspace_root: Path
    arm: str
    corruption: Stage1Corruption
    band_workspace: dict[str, Path]
    winners: dict[str, PlantedWinner]
    decoys: tuple[PlantedDecoy, ...]
    metric_identity: MetricIdentityKey

    #: Absolute dirs a conformant ``composed_best`` pool would be built
    #: from — the four winners' ``deliverable_dir`` values, band order.
    def pooled_deliverable_dirs(self) -> list[str]:
        """The four winners' deliverable dirs, in band order, as strings."""
        return [str(self.winners[label].deliverable_dir) for label in BAND_LABELS]


class PlantedUnit(BaseModel):
    """One Stage-2 retrain unit as planted, with its completion state."""

    model_config = ConfigDict(frozen=True)

    design: str
    target_band: str
    unit_id: str
    unit_dir: Path
    deliverable_dir: Path
    exp_id: str
    model_type: str
    denoising_score: float
    healthgate_valid: bool
    #: ``None`` when COMPLETE.json was deliberately not written (W2a).
    complete_json: Path | None


class Stage2Tree(BaseModel):
    """A fabricated Stage-2 tree: 16 units under ``{root}/stage2``."""

    model_config = ConfigDict(frozen=True)

    workspace_root: Path
    stage2_root: Path
    corruption: Stage2Corruption
    units: tuple[PlantedUnit, ...]
    #: Hardcoded expectation: unit ids that make the finalizer FAIL CLOSED,
    #: mapped to why. Every one of these must be NAMED in the single
    #: aggregated refusal — not silently dropped from the pool (Q-S3-1 = A).
    failing_units: dict[str, str]
    #: Hardcoded expectation: what ``strict_best`` must do with this tree.
    expected_outcome: FinalizerOutcome

    def unit(self, unit_id: str) -> PlantedUnit:
        """The planted unit with this id."""
        for planted in self.units:
            if planted.unit_id == unit_id:
                return planted
        raise KeyError(f"no planted unit {unit_id!r}; have {[u.unit_id for u in self.units]}")


class Stage3Namespaces(BaseModel):
    """The three Stage-3 consumption namespaces, contract §3."""

    model_config = ConfigDict(frozen=True)

    stage3_root: Path
    composed_best: Path
    strict_best: Path
    terminal_eval: Path
    terminal_eval_input: Path
    terminal_eval_results: Path


# --------------------------------------------------------------------------
# Low-level writers
# --------------------------------------------------------------------------


def write_placeholder_deliverable(path: Path, *, note: str = DELIVERABLE_PAYLOAD_NOTE) -> Path:
    """Write one placeholder deliverable and return its path.

    HDF5 magic signature followed by an ASCII note, so anything that sniffs
    the magic accepts it and anything that opens it fails loudly instead of
    reading plausible zeros.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_HDF5_MAGIC + note.encode("ascii"))
    return path


def deliverable_name(
    naming: DeliverableNaming,
    *,
    model_type: str,
    run_name: str,
    exp_id: str,
    file_index: int,
) -> str:
    """Render one deliverable filename THROUGH the production authority.

    A thin pass-through kept as a named function so the harness has exactly
    one place where a deliverable name is produced. Restating the template
    here would make every witness green against a writer that restates it
    the same wrong way.
    """
    return naming.name(
        model_type=model_type, run_name=run_name, exp_id=exp_id, input_identity=file_index
    )


def build_gate_results(*, all_passed: bool) -> list[dict[str, Any]]:
    """Persisted blocking-gate results for a record, from the live roster.

    The gate ids come from ``required_blocking_gate_ids()`` — the SAME
    authority ``is_valid_candidate`` consults — so a change to the shipped
    roster moves the fixture with it instead of silently making the
    "valid" record invalid.

    Args:
        all_passed: True builds a record that genuinely passes eligibility;
            False fails exactly ONE blocking gate on its check verdict,
            which is the narrowest way to be invalid rather than unknown.
    """
    gate_ids = sorted(required_blocking_gate_ids())
    if not gate_ids:
        raise RuntimeError(
            "the shipped HealthGate config declares no blocking gates, so a fixture "
            "cannot build a record that genuinely exercises eligibility. This is an "
            "environment/config problem, not a test expectation to relax."
        )
    results: list[dict[str, Any]] = []
    for index, gate_id in enumerate(gate_ids):
        passed = all_passed or index != 0
        results.append(
            PersistedHealthGateResult(
                gate_name=gate_id,
                execution_status="passed" if passed else "failed",
                check_passed=passed,
                would_invalidate_under_production_policy=not passed,
                resolved_action="continue" if passed else "invalidate_round",
                gate_role="blocking",
                failure_reason=None if passed else "planted adversarial failure",
            ).model_dump(mode="json")
        )
    return results


def build_experiment_record(
    *,
    exp_id: str,
    model_type: str,
    denoising_score: float | None,
    timestamp: str,
    status: str = "success",
    is_trial: bool = False,
    healthgate_valid: bool = True,
    file_index: int = 6,
) -> dict[str, Any]:
    """One persisted ExperimentRecord, as production writes it: a DICT.

    Two properties are load-bearing and neither survives a
    ``model_dump()`` round trip:

    * a FORMAL record carries **no** ``is_trial`` key at all
      (``records.py:1436`` sets it only when the round was a trial), which
      is the contract §1 formal test;
    * a formal record likewise carries no ``trial_portion`` key (#316 B2).

    The dict is validated against ``ExperimentRecord`` before being
    returned — so it is provably record-SHAPED — but the dict, not the
    model, is what callers persist.
    """
    record: dict[str, Any] = {
        "record_type": "experiment",
        "exp_id": exp_id,
        "status": status,
        "model_type": model_type,
        "timestamp": timestamp,
        "file_index": file_index,
        "params": {"note": "adversarial fixture; not a physically meaningful configuration"},
        "denoising_score": denoising_score,
        "health_gate_enabled": True,
        "health_gate_results": build_gate_results(all_passed=healthgate_valid),
    }
    if denoising_score is not None and status == "success":
        record["metric_result"] = {
            "metric_id": TIDMAD_METRIC_IDENTITY.id,
            "direction": TIDMAD_METRIC_IDENTITY.direction,
            "scalar": denoising_score,
            "per_sample": None,
            "references_used": [],
        }
    if is_trial:
        # Trial-only keys, both of them, exactly as the contract's §1 note
        # describes the persisted shape.
        record["is_trial"] = True
        record["trial_portion"] = 0.1

    # Shape proof, not a round trip: validation must accept it, and the
    # dict returned is the one validated.
    ExperimentRecord.model_validate(record)

    expected_valid = healthgate_valid and status == "success" and denoising_score is not None
    actual_valid = is_valid_candidate(record)
    if actual_valid is not expected_valid:
        raise RuntimeError(
            f"fixture record {exp_id!r} was built to be "
            f"{'valid' if expected_valid else 'invalid'} under is_valid_candidate but the "
            f"authority returned {actual_valid}. The fixture, not the authority, is wrong."
        )
    return record


def _tuner_output_payload(
    *,
    run_name: str,
    model_type: str,
    records: Sequence[Mapping[str, Any]],
    best_score: float | None,
    resolved_scope: Sequence[int],
    health_config_sha256: str,
    experiment_arm: str,
) -> dict[str, Any]:
    """A ``run_output_{run_name}.json`` payload, built the way production does.

    Production writes this file as ``HyperparamTuningOutput.model_dump()``
    (``records.py:1048``). That round trip MATERIALIZES ``is_trial: false``
    on formal records, because the field is declared with a default. This
    function reproduces production faithfully — including that effect —
    which is why the same records are ALSO persisted, key-absent, in
    ``summary_{run_name}.json``. See ``CONTRACT_NOTES['formal_identity']``.
    """
    output = HyperparamTuningOutput(
        run_name=run_name,
        model_type=model_type,
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-08-26T00:00:00Z",
        finished_at="2026-08-26T01:00:00Z",
        all_records=list(records),  # type: ignore[arg-type]
        best_denoising_score=best_score,
        resolved_data_scope=list(resolved_scope),
        health_gate_enabled=True,
        health_config_sha256=health_config_sha256,
        experiment_arm=experiment_arm,
        metric_spec=derive_tidmad_metric_spec(resolve_dataset_profile()).model_dump(mode="json"),
    )
    return output.model_dump(mode="json")


# --------------------------------------------------------------------------
# Stage 1
# --------------------------------------------------------------------------


def build_stage1_layout(
    workspace_root: Path,
    *,
    arm: str = "gold_a",
    corruption: Stage1Corruption = Stage1Corruption.NONE,
    naming: DeliverableNaming | None = None,
) -> Stage1Layout:
    """Fabricate one contract-conformant Stage-1 arm, optionally corrupted.

    Per band ``{workspace_root}/{arm}_band{BAND}/`` gets a run-invariants
    lock, a materialized effective Health config, and three ``iter_NNN/``
    directories, each holding a published ``manifest.json`` plus a tuner
    sub-workspace with ``run_output_{run_name}.json`` and
    ``summary_{run_name}.json``.

    Records per iteration are planted so that a reader which drops ANY
    clause of the contract §1 winner table selects the wrong record:

    * iter_001 — a valid FORMAL record (the eventual winner's predecessor,
      strictly worse);
    * iter_002 — the PLANTED WINNER (valid, formal, best score) beside a
      TRIAL record with a BETTER score and a HealthGate-INVALID formal
      record with a BETTER score;
    * iter_003 — a valid FORMAL record with a WORSE score, so "take the
      last iteration" is wrong, and a ``status="error_training"`` record.

    Deliverables are written ONLY for the planted winner, and only for its
    own band's files, matching contract §3's "files outside the winner's
    source band are never read from it".

    Args:
        workspace_root: an existing, writable temporary directory.
        arm: the campaign arm label (opaque; stamped as ``experiment_arm``).
        corruption: which adversarial defect to plant.
        naming: deliverable naming authority; the shipped TIDMAD default
            when omitted.

    Returns:
        The planted facts, as hardcoded expectations for the witnesses.
    """
    naming = naming or DeliverableNaming()
    workspace_root = Path(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    band_workspace: dict[str, Path] = {}
    winners: dict[str, PlantedWinner] = {}
    decoys: list[PlantedDecoy] = []

    for band_position, band in enumerate(BAND_LABELS):
        files = BAND_FILES[band]
        workspace = workspace_root / f"{arm}_band{band}"
        workspace.mkdir(parents=True, exist_ok=True)
        band_workspace[band] = workspace

        # The effective Health config and its sha come from the production
        # materializer. `files=` is the DS8 twin rule: under a partial
        # scope the monitored-file list must lie inside the scope.
        _effective_path, health_sha = materialize_effective_config(
            None, list(files), str(workspace), resolved_scope=list(files)
        )

        lock = RunInvariants(
            resolved_data_scope=list(files),
            health_gate_enabled=True,
            health_config_sha256=health_sha,
            experiment_arm=arm,
        )
        (workspace / "run_invariants_lock.json").write_text(
            json.dumps(lock.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

        run_name = f"{arm}_band{band}"
        model_type = ("wavenet", "punet", "wavenet", "punet")[band_position]

        # Scores are hand-picked so the planted winner is the best VALID
        # FORMAL record while two better-scoring records are ineligible.
        winner_score = -2.30 - 0.01 * band_position
        earlier_score = winner_score - 0.40
        later_score = winner_score - 0.15
        trial_score = winner_score + 0.50
        invalid_score = winner_score + 0.30

        winner_exp_id = f"exp_{band_position:02d}02"
        winner_iteration = 2

        per_iteration: dict[int, list[dict[str, Any]]] = {
            1: [
                build_experiment_record(
                    exp_id=f"exp_{band_position:02d}01",
                    model_type=model_type,
                    denoising_score=earlier_score,
                    timestamp="2026-08-26T00:10:00Z",
                )
            ],
            2: [
                build_experiment_record(
                    exp_id=f"exp_{band_position:02d}02t",
                    model_type=model_type,
                    denoising_score=trial_score,
                    timestamp="2026-08-26T00:20:00Z",
                    is_trial=True,
                ),
                build_experiment_record(
                    exp_id=f"exp_{band_position:02d}02x",
                    model_type=model_type,
                    denoising_score=invalid_score,
                    timestamp="2026-08-26T00:25:00Z",
                    healthgate_valid=False,
                ),
                build_experiment_record(
                    exp_id=winner_exp_id,
                    model_type=model_type,
                    denoising_score=winner_score,
                    timestamp="2026-08-26T00:30:00Z",
                ),
            ],
            3: [
                build_experiment_record(
                    exp_id=f"exp_{band_position:02d}03",
                    model_type=model_type,
                    denoising_score=later_score,
                    timestamp="2026-08-26T00:40:00Z",
                ),
                build_experiment_record(
                    exp_id=f"exp_{band_position:02d}03e",
                    model_type=model_type,
                    denoising_score=None,
                    timestamp="2026-08-26T00:45:00Z",
                    status="error_training",
                ),
            ],
        }

        decoys.extend(
            [
                PlantedDecoy(
                    band=band,
                    exp_id=f"exp_{band_position:02d}02t",
                    iteration=2,
                    denoising_score=trial_score,
                    reason=DecoyReason.TRIAL_ROUND,
                ),
                PlantedDecoy(
                    band=band,
                    exp_id=f"exp_{band_position:02d}02x",
                    iteration=2,
                    denoising_score=invalid_score,
                    reason=DecoyReason.HEALTHGATE_INVALID,
                ),
                PlantedDecoy(
                    band=band,
                    exp_id=f"exp_{band_position:02d}03",
                    iteration=3,
                    denoising_score=later_score,
                    reason=DecoyReason.WORSE_SCORE_LATER_ITERATION,
                ),
                PlantedDecoy(
                    band=band,
                    exp_id=f"exp_{band_position:02d}03e",
                    iteration=3,
                    denoising_score=None,
                    reason=DecoyReason.STATUS_NOT_SUCCESS,
                ),
            ]
        )

        winner_dir: Path | None = None
        for iteration, records in sorted(per_iteration.items()):
            iter_dir = workspace / f"iter_{iteration:03d}"
            sandbox_base = iter_dir / model_type
            (sandbox_base / "configs" / run_name).mkdir(parents=True, exist_ok=True)

            scored = [
                r["denoising_score"] for r in records if isinstance(r["denoising_score"], float)
            ]
            best = max(scored) if scored else None

            output_path = sandbox_base / f"run_output_{run_name}.json"
            output_path.write_text(
                json.dumps(
                    _tuner_output_payload(
                        run_name=run_name,
                        model_type=model_type,
                        records=records,
                        best_score=best,
                        resolved_scope=files,
                        health_config_sha256=health_sha,
                        experiment_arm=arm,
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )
            # The dict-shaped mirror: this is the persisted form in which a
            # FORMAL record genuinely has NO `is_trial` key.
            (sandbox_base / f"summary_{run_name}.json").write_text(
                json.dumps(list(records), indent=2), encoding="utf-8"
            )

            if iteration == winner_iteration:
                winner_dir = sandbox_base
                written = _write_winner_deliverables(
                    sandbox_base,
                    naming=naming,
                    model_type=model_type,
                    run_name=run_name,
                    exp_id=winner_exp_id,
                    band=band,
                    corruption=corruption,
                )
            manifest = {
                "status": "completed",
                "iteration_dir": str(iter_dir),
                "output_path": str(output_path),
                "model_name": model_type,
                "best_score": best,
                "completed_rounds": len(records),
                "resolved_data_scope": list(files),
                "health_gate_enabled": True,
                "health_config_sha256": health_sha,
                "experiment_arm": arm,
                "run_output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
            }
            publish_iteration_manifest(str(iter_dir), manifest)

        assert winner_dir is not None  # every band plants iteration 2
        winners[band] = PlantedWinner(
            band=band,
            arm=arm,
            run_name=run_name,
            model_type=model_type,
            exp_id=winner_exp_id,
            iteration=winner_iteration,
            denoising_score=winner_score,
            deliverable_dir=winner_dir,
            deliverable_files=written,
            expected_files=files,
        )

    if corruption is Stage1Corruption.DUPLICATE_BAND_LOWER_BOUNDARY:
        _plant_lower_boundary_duplicate(winners, naming=naming)

    layout = Stage1Layout(
        workspace_root=workspace_root,
        arm=arm,
        corruption=corruption,
        band_workspace=band_workspace,
        winners=winners,
        decoys=tuple(decoys),
        metric_identity=TIDMAD_METRIC_IDENTITY,
    )
    _assert_planted_winners_are_orderable(layout)
    return layout


def _write_winner_deliverables(
    sandbox_base: Path,
    *,
    naming: DeliverableNaming,
    model_type: str,
    run_name: str,
    exp_id: str,
    band: str,
    corruption: Stage1Corruption,
) -> tuple[int, ...]:
    """Write the winner's band deliverables, honouring the W1a corruption."""
    written: list[int] = []
    for file_index in BAND_FILES[band]:
        if (
            corruption is Stage1Corruption.MISSING_BAND_UPPER_BOUNDARY
            and band == CORRUPTION_BAND
            and file_index == MISSING_FILE_IDENTITY
        ):
            continue
        write_placeholder_deliverable(
            sandbox_base
            / deliverable_name(
                naming,
                model_type=model_type,
                run_name=run_name,
                exp_id=exp_id,
                file_index=file_index,
            )
        )
        written.append(file_index)
    return tuple(written)


def _plant_lower_boundary_duplicate(
    winners: Mapping[str, PlantedWinner], *, naming: DeliverableNaming
) -> None:
    """Make file 0004 resolvable from the 0-3 pool as well as the 4-9 pool.

    This is what an off-by-one band map on the LOWER boundary produces: the
    0-3 chain, told its band is ``range(0, 5)``, also emits file 4. Both
    copies are legitimately named through the authority, each under its own
    run/exp identity, so nothing but a per-identity uniqueness check across
    the pooled dirs can see it.
    """
    lower = winners["0-3"]
    write_placeholder_deliverable(
        lower.deliverable_dir
        / deliverable_name(
            naming,
            model_type=lower.model_type,
            run_name=lower.run_name,
            exp_id=lower.exp_id,
            file_index=DUPLICATED_FILE_IDENTITY,
        )
    )


def _assert_planted_winners_are_orderable(layout: Stage1Layout) -> None:
    """Fixture self-check: the planted winner really is the best eligible one.

    Uses ``MetricOrder`` — the ONE direction authority — over the records
    the fixture just wrote, to confirm the hand-picked winner is not merely
    asserted but genuinely optimal among eligible records. This guards the
    FIXTURE; the witnesses still assert the hardcoded ``exp_id``.
    """
    order = MetricOrder(layout.metric_identity)
    for band, winner in layout.winners.items():
        eligible: list[tuple[str, float]] = []
        for record in iter_persisted_records(layout.band_workspace[band]):
            if record.get("status") != "success":
                continue
            if record.get("is_trial"):
                continue
            score = record.get("denoising_score")
            if not isinstance(score, float) or not math.isfinite(score):
                continue
            if not is_valid_candidate(record):
                continue
            eligible.append((str(record["exp_id"]), score))
        if not eligible:
            raise RuntimeError(f"band {band}: fixture planted no eligible formal record")
        best_exp_id, _best_score = order.best(eligible, key=lambda item: item[1])
        if best_exp_id != winner.exp_id:
            raise RuntimeError(
                f"band {band}: fixture planted {winner.exp_id!r} as the winner but the "
                f"best eligible record is {best_exp_id!r}. The fixture's scores are wrong."
            )


def iter_persisted_records(band_workspace: Path) -> Iterator[dict[str, Any]]:
    """Every persisted record dict under one band chain workspace.

    Reads the ``summary_{run_name}.json`` mirrors, which preserve the
    key-ABSENCE shape of a formal record. Provided so a witness can inspect
    what was planted without re-implementing a writer's discovery walk.
    """
    for summary in sorted(band_workspace.glob("iter_*/**/summary_*.json")):
        payload = json.loads(summary.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    yield entry


# --------------------------------------------------------------------------
# Stage 2
# --------------------------------------------------------------------------

#: Four frozen-design identifiers x four target bands = the 16 units of
#: contract §2. The names are campaign-opaque; only the ``{design}_{band}``
#: directory shape is contractual.
STAGE2_DESIGNS: Final[tuple[str, str, str, str]] = (
    "wavenetA",
    "wavenetB",
    "punetA",
    "punetB",
)

#: Which unit each Stage-2 corruption acts on. Hardcoded so a witness's
#: expectation never comes from the same expression the fixture used.
STALE_PARTIAL_UNIT_ID: Final[str] = "wavenetB_10-14"
HEALTHGATE_INVALID_UNIT_ID: Final[str] = "punetA_4-9"


def build_stage2_tree(
    workspace_root: Path,
    *,
    corruption: Stage2Corruption = Stage2Corruption.NONE,
    naming: DeliverableNaming | None = None,
) -> Stage2Tree:
    """Fabricate the 16-unit Stage-2 tree of contract §2, optionally corrupted.

    Each unit gets ``workspace/iter_001/``, a ``deliverables/`` dir holding
    all 20 named files, and a ``COMPLETE.json`` written LAST via an atomic
    rename — so a reader that polls mid-write sees either no marker or a
    complete one, never a truncated one.

    Args:
        workspace_root: an existing, writable temporary directory.
        corruption: which adversarial defect to plant.
        naming: deliverable naming authority; shipped default when omitted.
    """
    naming = naming or DeliverableNaming()
    workspace_root = Path(workspace_root)
    stage2_root = workspace_root / "stage2"
    stage2_root.mkdir(parents=True, exist_ok=True)

    units: list[PlantedUnit] = []
    failing_units: dict[str, str] = {}

    for design_position, design in enumerate(STAGE2_DESIGNS):
        for band_position, band in enumerate(BAND_LABELS):
            unit_id = f"{design}_{band}"
            unit_dir = stage2_root / unit_id
            iter_dir = unit_dir / "workspace" / "iter_001"
            iter_dir.mkdir(parents=True, exist_ok=True)
            deliverables = unit_dir / "deliverables"
            deliverables.mkdir(parents=True, exist_ok=True)

            model_type = "wavenet" if design.startswith("wavenet") else "punet"
            exp_id = f"s2_{design_position}{band_position}"
            run_name = f"stage2_{unit_id}"

            # §4 amendment (local-gate Step-09a ruling, 2026-08-26): the
            # strict_best production path RECONCILES the 09a metric_spec
            # stamps persisted in each unit's chain workspace, read through
            # the manifest-VERIFIED loader — so the fixture publishes a REAL
            # self-digested manifest over a stamped run output.
            unit_sub = iter_dir / "iteration_001" / model_type
            unit_sub.mkdir(parents=True, exist_ok=True)
            unit_output = unit_sub / f"run_output_{run_name}.json"
            unit_output.write_text(
                json.dumps(
                    {
                        "run_name": run_name,
                        "metric_spec": derive_tidmad_metric_spec(
                            resolve_dataset_profile()
                        ).model_dump(mode="json"),
                        "all_records": [],
                    }
                ),
                encoding="utf-8",
            )
            publish_iteration_manifest(
                str(iter_dir),
                {
                    "status": "completed",
                    "iteration_dir": str(iter_dir),
                    "output_path": str(unit_output),
                    "model_name": model_type,
                    "run_output_sha256": hashlib.sha256(unit_output.read_bytes()).hexdigest(),
                },
            )
            # Q-S3-2 ruling A (supervisor, 2026-08-26): a unit's deliverables/
            # holds its TARGET-BAND files ONLY. A band-scoped Stage-2 run
            # produces exactly its scope's files (DS8's enforced behaviour), so
            # a design's four units PARTITION 0..19 and whole-dir pooling
            # composes with zero duplicates. The pre-ruling literal-20 shape
            # could never compose — four dirs x 20 files resolved every index
            # four times and refused on a perfectly healthy tree.
            for file_index in BAND_FILES[band]:
                write_placeholder_deliverable(
                    deliverables
                    / deliverable_name(
                        naming,
                        model_type=model_type,
                        run_name=run_name,
                        exp_id=exp_id,
                        file_index=file_index,
                    )
                )

            healthgate_valid = not (
                corruption is Stage2Corruption.HEALTHGATE_INVALID_UNIT
                and unit_id == HEALTHGATE_INVALID_UNIT_ID
            )
            write_marker = not (
                corruption is Stage2Corruption.STALE_PARTIAL_UNIT
                and unit_id == STALE_PARTIAL_UNIT_ID
            )
            # A unit-level scalar, contract §2. NOT a per-band scalar: the
            # score belongs to the UNIT, and `target_band` beside it is a
            # string label.
            score = -2.50 + 0.01 * (design_position * len(BAND_LABELS) + band_position)

            marker_path: Path | None = None
            if write_marker:
                marker_path = _write_complete_marker(
                    unit_dir,
                    design=design,
                    target_band=band,
                    exp_id=exp_id,
                    model_type=model_type,
                    denoising_score=score,
                    healthgate_valid=healthgate_valid,
                )
            else:
                failing_units[unit_id] = (
                    "no COMPLETE.json: absence == unit not done (contract §2). A "
                    "populated deliverables/ dir is NOT completion evidence, and under "
                    "Q-S3-1 = A the finalizer must REFUSE naming this unit rather than "
                    "quietly finalize on the remaining three"
                )
            if not healthgate_valid:
                failing_units[unit_id] = (
                    "COMPLETE.json carries healthgate_valid: false. Under Q-S3-1 = A "
                    "the finalizer must REFUSE naming this unit, never exclude it and "
                    "continue"
                )

            units.append(
                PlantedUnit(
                    design=design,
                    target_band=band,
                    unit_id=unit_id,
                    unit_dir=unit_dir,
                    deliverable_dir=deliverables,
                    exp_id=exp_id,
                    model_type=model_type,
                    denoising_score=score,
                    healthgate_valid=healthgate_valid,
                    complete_json=marker_path,
                )
            )

    return Stage2Tree(
        workspace_root=workspace_root,
        stage2_root=stage2_root,
        corruption=corruption,
        units=tuple(units),
        failing_units=failing_units,
        expected_outcome=(
            FinalizerOutcome.PROCEED if not failing_units else FinalizerOutcome.REFUSE
        ),
    )


def _write_complete_marker(
    unit_dir: Path,
    *,
    design: str,
    target_band: str,
    exp_id: str,
    model_type: str,
    denoising_score: float,
    healthgate_valid: bool,
) -> Path:
    """Write ``COMPLETE.json`` LAST, via an atomic same-directory rename.

    ``deliverable_count`` is the TARGET BAND's file count (Q-S3-2 ruling A,
    2026-08-26), not the literal 20 the pre-ruling contract froze. It is
    taken from this module's own band map — which is pinned against the
    contract vocabulary by its own test — so a fixture drift shows up as a
    band-map failure rather than as a mystery marker refusal.
    """
    payload = {
        "design": design,
        "target_band": target_band,
        "exp_id": exp_id,
        "model_type": model_type,
        "repo_sha": "0" * 40,
        "denoising_score": denoising_score,
        "healthgate_valid": healthgate_valid,
        "deliverable_count": len(BAND_FILES[target_band]),
        "completed_utc": "2026-08-26T02:00:00Z",
    }
    final = unit_dir / "COMPLETE.json"
    staging = unit_dir / ".COMPLETE.json.partial"
    staging.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(staging, final)
    return final


def build_stage3_namespaces(workspace_root: Path) -> Stage3Namespaces:
    """Create the three contract §3 namespaces under ``{root}/stage3``."""
    stage3 = Path(workspace_root) / "stage3"
    composed_best = stage3 / "composed_best"
    strict_best = stage3 / "strict_best"
    terminal_eval = stage3 / "terminal_eval"
    terminal_input = terminal_eval / "input"
    terminal_results = terminal_eval / "results"
    for directory in (composed_best, strict_best, terminal_input, terminal_results):
        directory.mkdir(parents=True, exist_ok=True)
    return Stage3Namespaces(
        stage3_root=stage3,
        composed_best=composed_best,
        strict_best=strict_best,
        terminal_eval=terminal_eval,
        terminal_eval_input=terminal_input,
        terminal_eval_results=terminal_results,
    )


# --------------------------------------------------------------------------
# W4 — the score_vector call counter
# --------------------------------------------------------------------------


class ScoreVectorCallCounter:
    """A counting stand-in for the scoring authority.

    Returns a plausible ``(file_vector, scalar)`` 2-tuple and records every
    call, so a witness can assert BOTH that scoring happened exactly once
    and what that one call covered.
    """

    def __init__(self, *, file_count: int = NUM_FILES, scalar: float = -2.4242) -> None:
        self.calls: list[dict[str, Any]] = []
        self._file_count = file_count
        self._scalar = scalar

    @property
    def call_count(self) -> int:
        """How many times the scoring authority was invoked."""
        return len(self.calls)

    def __call__(self, *args: Any, **kwargs: Any) -> tuple[list[float | None], float]:
        self.calls.append({"args": args, "kwargs": kwargs})
        return ([-2.0 - 0.01 * i for i in range(self._file_count)], self._scalar)


def install_counting_score_vector(
    monkeypatch: Any, target: str, *, scalar: float = -2.4242
) -> ScoreVectorCallCounter:
    """Replace the scoring authority at ``target`` with a counting stub.

    Args:
        monkeypatch: pytest's ``monkeypatch`` fixture.
        target: the dotted IMPORT SITE to patch, e.g.
            ``"scripts.stage3.compose_and_score.score_vector"``. It must be
            the name as the wrapper's module resolves it, not the name in
            ``execute_tools.scoring_utils`` — a module that did
            ``from ... import score_vector`` holds its own binding.
        scalar: the aggregate the stub returns.

    Returns:
        The counter, whose ``call_count`` is the witness's assertion target.

    Raises:
        AttributeError: when ``target`` does not exist. This is deliberate
            and is half the value of the witness: patching a name nothing
            binds would leave the real authority in place and the counter
            at zero, so a broken witness would report "not called" — which
            reads exactly like a passing "never called twice" test.
    """
    counter = ScoreVectorCallCounter(scalar=scalar)
    monkeypatch.setattr(target, counter, raising=True)
    return counter


# --------------------------------------------------------------------------
# W3 — terminal_eval read-closure plant machinery + census
# --------------------------------------------------------------------------

#: The reserved namespace contract §3 forbids any search / selection /
#: tuning / scoring-for-selection path from reading.
TERMINAL_EVAL_TOKEN: Final[str] = "terminal_eval"


class TerminalEvalPlant(StrEnum):
    """Shapes an adversarial ``terminal_eval`` read can take in source.

    Each shape defeats a different naive guard, which is why the plant
    machinery is parameterized rather than emitting one canonical form.
    """

    #: ``os.path.join(root, "stage3", "terminal_eval")`` — defeats a guard
    #: grepping for the literal ``"stage3/terminal_eval"``.
    JOINED_SEGMENTS = "joined_segments"
    #: ``f"{root}/stage3/terminal_eval/input"`` — defeats an AST guard that
    #: only inspects plain string constants and skips f-strings.
    FSTRING_PATH = "fstring_path"
    #: ``glob.glob(...)`` over the namespace — a READ that opens no file
    #: itself, so a guard watching ``open``/``h5py.File`` misses it.
    GLOB_SCAN = "glob_scan"
    #: ``"terminal" + "_eval"`` — a computed name. Included because the
    #: census is DOCUMENTED not to catch it; see ``CENSUS_BLIND_SPOTS``.
    COMPUTED_NAME = "computed_name"


_PLANT_BODIES: Final[Mapping[TerminalEvalPlant, str]] = {
    TerminalEvalPlant.JOINED_SEGMENTS: (
        "\n\n"
        "def _planted_terminal_eval_read(workspace_root):\n"
        '    """PLANTED BY THE ADVERSARIAL HARNESS — not production code."""\n'
        "    import os\n"
        '    return os.path.join(workspace_root, "stage3", "terminal_eval", "input")\n'
    ),
    TerminalEvalPlant.FSTRING_PATH: (
        "\n\n"
        "def _planted_terminal_eval_read(workspace_root):\n"
        '    """PLANTED BY THE ADVERSARIAL HARNESS — not production code."""\n'
        '    return f"{workspace_root}/stage3/terminal_eval/input"\n'
    ),
    TerminalEvalPlant.GLOB_SCAN: (
        "\n\n"
        "def _planted_terminal_eval_read(workspace_root):\n"
        '    """PLANTED BY THE ADVERSARIAL HARNESS — not production code."""\n'
        "    import glob\n"
        "    import os\n"
        "    return glob.glob(\n"
        '        os.path.join(workspace_root, "stage3", "terminal_eval", "**", "*.h5"),\n'
        "        recursive=True,\n"
        "    )\n"
    ),
    TerminalEvalPlant.COMPUTED_NAME: (
        "\n\n"
        "def _planted_terminal_eval_read(workspace_root):\n"
        '    """PLANTED BY THE ADVERSARIAL HARNESS — not production code."""\n'
        "    import os\n"
        '    reserved = "terminal" + "_eval"\n'
        '    return os.path.join(workspace_root, "stage3", reserved)\n'
    ),
}

#: What the census provably cannot see, stated so nobody mistakes a green
#: run for a proof of the isolation rule.
CENSUS_BLIND_SPOTS: Final[tuple[str, ...]] = (
    "a namespace name assembled at runtime from fragments "
    '(TerminalEvalPlant.COMPUTED_NAME: "terminal" + "_eval")',
    "a namespace name arriving from configuration, argv or an environment "
    "variable rather than appearing in source",
    "a read performed by a subprocess whose argv is built elsewhere",
)


class TerminalEvalFinding(BaseModel):
    """One executable source reference to the reserved namespace."""

    model_config = ConfigDict(frozen=True)

    path: Path
    lineno: int
    #: What syntactic construct carried the reference.
    kind: str
    snippet: str


class PlantedTree(BaseModel):
    """A tmp copy of production sources, with one planted read inside it."""

    model_config = ConfigDict(frozen=True)

    tree_root: Path
    planted_file: Path
    plant: TerminalEvalPlant
    #: Path of the ORIGINAL production module the copy was taken from,
    #: recorded so a phase-2 report can name the site that was probed.
    source_module: Path


def copy_production_tree(
    modules: Iterable[Path], dest_root: Path, *, repo_root: Path = REPO_ROOT
) -> Path:
    """Copy production modules into ``dest_root``, preserving repo-relative paths.

    Real production files are NEVER modified: the plant machinery only ever
    edits the copies this function makes.

    Raises:
        ValueError: if a module lies outside ``repo_root`` — a plant that
            reaches outside the checkout would be editing another clone.
    """
    dest_root = Path(dest_root)
    for module in modules:
        module = Path(module).resolve()
        try:
            relative = module.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(
                f"{module} is not inside the repository root {repo_root}; the plant "
                f"machinery refuses to copy from another checkout."
            ) from exc
        destination = dest_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(module, destination)
    return dest_root


def plant_terminal_eval_read(
    source_module: Path,
    dest_root: Path,
    *,
    plant: TerminalEvalPlant = TerminalEvalPlant.JOINED_SEGMENTS,
    repo_root: Path = REPO_ROOT,
) -> PlantedTree:
    """Copy ``source_module`` into ``dest_root`` and inject a terminal_eval read.

    The reusable half of witness W3. Phase 2 chooses WHICH production
    search / selection consumer to probe — deliberately one the implementer
    did NOT use as their own negative control, so the guard is shown to
    cover a site its author did not have in mind.

    Args:
        source_module: an existing production ``.py`` inside ``repo_root``.
        dest_root: a temporary directory the mutated tree is built under.
        plant: which adversarial shape to inject.
        repo_root: the checkout the module must belong to.

    Returns:
        The mutated tree, for ``scan_for_terminal_eval_reads`` to scan.
    """
    source_module = Path(source_module).resolve()
    if source_module.suffix != ".py" or not source_module.is_file():
        raise ValueError(f"{source_module} is not an existing Python module")
    copy_production_tree([source_module], dest_root, repo_root=repo_root)
    planted = Path(dest_root) / source_module.relative_to(repo_root)
    with planted.open("a", encoding="utf-8") as handle:
        handle.write(_PLANT_BODIES[plant])
    return PlantedTree(
        tree_root=Path(dest_root),
        planted_file=planted,
        plant=plant,
        source_module=source_module,
    )


def scan_for_terminal_eval_reads(
    tree_root: Path, *, token: str = TERMINAL_EVAL_TOKEN
) -> tuple[TerminalEvalFinding, ...]:
    """Every EXECUTABLE source reference to the reserved namespace in a tree.

    Comments and docstrings are deliberately NOT findings: the contract
    itself names the directory, and a guard that flags
    ``# never read terminal_eval`` would make documenting the rule
    impossible. What IS a finding is the token appearing in a value the
    program computes — a string constant, an f-string fragment, or an
    identifier.

    Files that do not parse are reported as a ``syntax_error`` finding
    rather than skipped: a consumer this scanner cannot read is unproven,
    never clean.

    See ``CENSUS_BLIND_SPOTS`` for what it provably cannot see.
    """
    findings: list[TerminalEvalFinding] = []
    for path in sorted(Path(tree_root).rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if token not in source:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            findings.append(
                TerminalEvalFinding(
                    path=path,
                    lineno=exc.lineno or 0,
                    kind="syntax_error",
                    snippet=f"file could not be parsed: {exc.msg}",
                )
            )
            continue
        docstrings = _docstring_nodes(tree)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if token in node.value and node not in docstrings:
                    findings.append(_finding(path, node, "string_constant", lines, node.value))
            elif isinstance(node, ast.Name) and token in node.id:
                findings.append(_finding(path, node, "identifier", lines, node.id))
            elif isinstance(node, ast.Attribute) and token in node.attr:
                findings.append(_finding(path, node, "attribute", lines, node.attr))
    return tuple(findings)


def _docstring_nodes(tree: ast.AST) -> set[ast.Constant]:
    """The Constant nodes that occupy a docstring position."""
    found: set[ast.Constant] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(first.value)
    return found


def _finding(
    path: Path, node: ast.AST, kind: str, lines: Sequence[str], detail: str
) -> TerminalEvalFinding:
    lineno = getattr(node, "lineno", 0) or 0
    snippet = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else detail
    return TerminalEvalFinding(path=path, lineno=lineno, kind=kind, snippet=snippet)


# --------------------------------------------------------------------------
# W3, artifact half — terminal-eval ARTIFACT plants
#
# The source census above answers "does any consumer's CODE name the
# reserved namespace?". It cannot answer "did a terminal artifact reach a
# search-side consumer's INPUT tree?", which is the other half of the
# isolation rule and the half a real leak takes. A production guard for it
# has three possible detection bases, and they do not cover the same cases:
#
#   path resolution   — the artifact's real path lands inside terminal_eval/
#                       (survives a symlink; survives a stripped marker)
#   content marker    — the artifact self-declares its namespace in an
#                       envelope key (survives a copy; NOT a strip)
#   enumeration       — the consumer's input roots are a closed list that
#                       structurally cannot contain the namespace
#
# The plants below are built to separate those three, so a phase-2 result
# says WHICH basis a guard actually has rather than only whether it fired.
# --------------------------------------------------------------------------

#: Envelope key/value by which a terminal artifact self-declares its
#: namespace. PHASE 2: imported from the production module that emits them
#: (``ARTIFACT_NAMESPACE_KEY`` / ``TERMINAL_NAMESPACE_MARKER``), never
#: restated — a plant built from a restated constant would sail past the
#: real guard while the harness reported it caught.
TERMINAL_ARTIFACT_MARKER_KEY: Final[str] = ARTIFACT_NAMESPACE_KEY
TERMINAL_ARTIFACT_MARKER_VALUE: Final[str] = TERMINAL_NAMESPACE_MARKER


class ArtifactPlant(StrEnum):
    """How a terminal artifact can reach a search-side consumer's input tree."""

    #: A straight copy into the consumer tree, envelope marker intact. The
    #: easiest case: BOTH a content-marker guard and an enumeration guard
    #: should catch it; a path-resolution guard alone will not.
    COPY_MARKER_INTACT = "copy_marker_intact"
    #: A SYMLINK inside the consumer tree pointing into terminal_eval/, with
    #: the marker stripped from the target. Only PATH RESOLUTION catches
    #: this — the link's own name is innocent and there is no marker left.
    SYMLINK_MARKER_STRIPPED = "symlink_marker_stripped"
    #: A marker-stripped COPY that lives OUTSIDE the namespace. Nothing
    #: about the file or its path betrays its origin, so no content or
    #: path guard can see it. Detectable ONLY by enumeration — the
    #: consumer's input roots being a closed list. Reported, never failed.
    COPY_OUTSIDE_MARKER_STRIPPED = "copy_outside_marker_stripped"


class PlantedArtifact(BaseModel):
    """One planted terminal artifact, with what a correct guard should see.

    ``expected_detectable`` plus ``detection_basis`` are the harness's
    HARDCODED expectations. A phase-2 witness asserts the guard fires for
    the detectable plants and REPORTS — rather than fails — the residual,
    because that residual is enumeration-based by design and is a property
    of the architecture, not a defect in the guard.
    """

    model_config = ConfigDict(frozen=True)

    plant: ArtifactPlant
    #: Where the artifact appears from the consumer's point of view.
    planted_path: Path
    #: What ``planted_path`` resolves to after following links.
    resolved_path: Path
    marker_present: bool
    resolves_into_terminal_namespace: bool
    expected_detectable: bool
    detection_basis: str


def resolves_into(path: Path, namespace_root: Path) -> bool:
    """Whether ``path``'s REAL location is inside ``namespace_root``.

    The reference for the symlink-resolution violation kind: both sides are
    fully resolved before comparison, so a link whose own path sits in an
    innocent tree is still recognised by where it actually points. A guard
    that compares unresolved strings answers False here and lets the leak
    through.
    """
    try:
        real = path.resolve()
        root = namespace_root.resolve()
    except OSError:
        return False
    return real == root or root in real.parents


def write_terminal_artifact(
    path: Path,
    *,
    marker_key: str = TERMINAL_ARTIFACT_MARKER_KEY,
    marker_value: str = TERMINAL_ARTIFACT_MARKER_VALUE,
    with_marker: bool = True,
    payload: Mapping[str, Any] | None = None,
) -> Path:
    """Write one terminal-evaluation artifact envelope.

    Args:
        path: destination ``.json`` envelope.
        marker_key: envelope key by which the artifact declares its namespace.
        marker_value: the declared namespace.
        with_marker: False writes an otherwise identical envelope with the
            declaration STRIPPED — the adversarial case.
        payload: extra envelope content; a harmless default when omitted.
    """
    envelope: dict[str, Any] = dict(
        payload
        or {
            "artifact_kind": "terminal_evaluation_input",
            "created_utc": "2026-08-26T03:00:00Z",
        }
    )
    if with_marker:
        envelope[marker_key] = marker_value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
    return path


def plant_terminal_artifact(
    *,
    terminal_eval_root: Path,
    consumer_root: Path,
    plant: ArtifactPlant,
    marker_key: str = TERMINAL_ARTIFACT_MARKER_KEY,
    marker_value: str = TERMINAL_ARTIFACT_MARKER_VALUE,
    artifact_name: str = "terminal_probe.json",
) -> PlantedArtifact:
    """Plant one terminal artifact against a search-side consumer's input tree.

    Args:
        terminal_eval_root: ``{workspace_root}/stage3/terminal_eval``.
        consumer_root: the input tree of the consumer being probed — e.g. a
            ``{arm}_band{BAND}`` chain workspace for the
            ``stage1_band_chain_workspaces`` consumer, or the
            ``composed_best`` pool dir.
        plant: which of the three shapes to build.
        marker_key: the envelope key the implementer's guard reads.
        marker_value: the declared namespace value.
        artifact_name: basename of the planted artifact.

    Returns:
        The plant, carrying the harness's hardcoded detectability expectation.

    Raises:
        OSError: if a symlink cannot be created on this filesystem. That is
            reported rather than worked around: a platform where the
            symlink plant cannot be built is a platform where the
            symlink-resolution guard is UNPROVEN, not proven.
    """
    terminal_eval_root = Path(terminal_eval_root)
    consumer_root = Path(consumer_root)
    consumer_root.mkdir(parents=True, exist_ok=True)

    if plant is ArtifactPlant.COPY_MARKER_INTACT:
        planted = write_terminal_artifact(
            consumer_root / artifact_name,
            marker_key=marker_key,
            marker_value=marker_value,
            with_marker=True,
        )
        return PlantedArtifact(
            plant=plant,
            planted_path=planted,
            resolved_path=planted.resolve(),
            marker_present=True,
            resolves_into_terminal_namespace=resolves_into(planted, terminal_eval_root),
            expected_detectable=True,
            detection_basis=(
                "content marker: the envelope still declares its namespace, so a "
                "marker-reading guard catches it even though the path is innocent"
            ),
        )

    if plant is ArtifactPlant.SYMLINK_MARKER_STRIPPED:
        target = write_terminal_artifact(
            terminal_eval_root / "results" / artifact_name,
            marker_key=marker_key,
            marker_value=marker_value,
            with_marker=False,
        )
        link = consumer_root / artifact_name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)
        return PlantedArtifact(
            plant=plant,
            planted_path=link,
            resolved_path=link.resolve(),
            marker_present=False,
            resolves_into_terminal_namespace=resolves_into(link, terminal_eval_root),
            expected_detectable=True,
            detection_basis=(
                "path resolution ONLY: the marker is gone and the link's own path is "
                "innocent, so a guard that does not resolve links cannot see it"
            ),
        )

    # COPY_OUTSIDE_MARKER_STRIPPED — the enumeration residual.
    planted = write_terminal_artifact(
        consumer_root / artifact_name,
        marker_key=marker_key,
        marker_value=marker_value,
        with_marker=False,
    )
    return PlantedArtifact(
        plant=plant,
        planted_path=planted,
        resolved_path=planted.resolve(),
        marker_present=False,
        resolves_into_terminal_namespace=False,
        expected_detectable=False,
        detection_basis=(
            "neither: no marker, and the real path never enters the namespace. Only "
            "enumeration — the consumer's input roots being a closed, declared list — "
            "keeps this out, which is exactly what contract §3's isolation rule (b) "
            "claims. REPORT this residual; it is not a guard defect."
        ),
    )


# --------------------------------------------------------------------------
# W5 — the no-band-scalar census
# --------------------------------------------------------------------------

#: A key that IDENTIFIES a band on its own. The anchors matter: a unit id
#: such as ``wavenetA_0-3`` carries a band token but is identified by its
#: DESIGN too, and its score is a UNIT-level scalar that contract §2
#: declares legal. Flagging it would be the census's most likely false
#: positive, so the pattern refuses any leading qualifier.
_BAND_KEY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^(?:per[_-]?band|bands?)$"),
    re.compile(r"^(?:band[_-]?)?(\d{1,2})(?:-|_|to)(\d{1,2})$"),
    re.compile(r"^band[_-]?(\d{1,2})$"),
)

#: Substrings that make a key score-BEARING. Deliberately narrow: a count
#: or a duration under a band key is provenance, not a per-band scalar.
_SCORE_KEY_MARKERS: Final[tuple[str, ...]] = ("score", "scalar", "file_vector", "denoising")


class BandScalarFinding(BaseModel):
    """One per-band scalar found in an output artifact."""

    model_config = ConfigDict(frozen=True)

    path: Path
    #: Dotted JSON path to the offending key, e.g. ``summary.per_band.4-9``.
    location: str
    kind: str
    detail: str


def is_band_shaped_key(key: str) -> bool:
    """Whether ``key`` identifies a band ON ITS OWN.

    ``"4-9"``, ``"band_4-9"``, ``"band4to9"``, ``"band_2"``, ``"per_band"``
    and ``"bands"`` are band-shaped. ``"wavenetA_0-3"``, ``"target_band"``
    and ``"source_band"`` are NOT: the first is identified by its design as
    well, and the last two are LABEL keys whose values are strings.
    """
    normalized = key.strip().lower()
    return any(pattern.match(normalized) for pattern in _BAND_KEY_PATTERNS)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _score_bearing_keys(value: Mapping[str, Any]) -> list[str]:
    return [
        key
        for key in value
        if any(marker in str(key).lower() for marker in _SCORE_KEY_MARKERS)
        and _has_numeric_leaf(value[key])
    ]


def _has_numeric_leaf(value: Any) -> bool:
    if _is_number(value):
        return True
    if isinstance(value, list):
        return any(_has_numeric_leaf(item) for item in value)
    if isinstance(value, dict):
        return any(_has_numeric_leaf(item) for item in value.values())
    return False


def scan_payload_for_band_scalars(
    payload: Any, *, path: Path, location: str = "$"
) -> list[BandScalarFinding]:
    """Findings for one already-parsed JSON/YAML document.

    RED when a band-shaped key maps to:

    * a number — ``{"4-9": -2.41}``;
    * a score-bearing object — ``{"band_4-9": {"denoising_score": -2.41}}``;
    * a sequence of numbers — ``{"per_band": [-2.4, -2.5, -2.6, -2.7]}``.

    LEGAL, and specifically not flagged:

    * a band LABEL as a string value — ``{"source_band": "4-9"}``;
    * a band roster — ``{"bands": ["0-3", "4-9", "10-14", "15-19"]}``;
    * a band-keyed manifest of non-numeric provenance —
      ``{"per_band": {"4-9": {"winner_exp_id": "exp_0102"}}}``;
    * the frozen whole-run artifacts — ``denoising_score`` and the 20-entry
      ``file_vector`` are not keyed by a band.
    """
    findings: list[BandScalarFinding] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{location}.{key}"
            if is_band_shaped_key(str(key)):
                findings.extend(_band_key_findings(path, child, str(key), value))
            findings.extend(scan_payload_for_band_scalars(value, path=path, location=child))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            findings.extend(
                scan_payload_for_band_scalars(item, path=path, location=f"{location}[{index}]")
            )
    return findings


def _band_key_findings(path: Path, location: str, key: str, value: Any) -> list[BandScalarFinding]:
    if _is_number(value):
        return [
            BandScalarFinding(
                path=path,
                location=location,
                kind="band_keyed_number",
                detail=f"band-shaped key {key!r} maps directly to the number {value!r}",
            )
        ]
    if isinstance(value, list) and value and all(_is_number(item) for item in value):
        return [
            BandScalarFinding(
                path=path,
                location=location,
                kind="band_keyed_number_sequence",
                detail=f"band-shaped key {key!r} maps to a sequence of {len(value)} numbers",
            )
        ]
    if isinstance(value, dict):
        bearing = _score_bearing_keys(value)
        if bearing:
            return [
                BandScalarFinding(
                    path=path,
                    location=location,
                    kind="band_keyed_score_object",
                    detail=(
                        f"band-shaped key {key!r} maps to an object carrying "
                        f"score-bearing key(s) {bearing}"
                    ),
                )
            ]
    return []


def scan_tree_for_band_scalars(
    tree_root: Path, *, suffixes: Sequence[str] = (".json", ".yaml", ".yml")
) -> tuple[BandScalarFinding, ...]:
    """Scan an output tree for per-band scalars.

    Structured documents (JSON/YAML) are parsed and analysed by KEY and by
    VALUE TYPE, which is what makes a band LABEL legal while a band-keyed
    NUMBER is not. An unparseable document is reported as a finding rather
    than skipped, for the same reason the terminal_eval census reports a
    syntax error: unreadable is unproven, not clean.

    Text formats outside ``suffixes`` are NOT scanned. A prose report can
    legitimately print a per-band table for humans, and this census makes
    no claim about such files — see the module docstring's limitations.
    """
    findings: list[BandScalarFinding] = []
    for path in sorted(Path(tree_root).rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            payload = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            findings.append(
                BandScalarFinding(
                    path=path,
                    location="$",
                    kind="unparseable",
                    detail=f"document could not be parsed, so it is unproven: {exc}",
                )
            )
            continue
        findings.extend(scan_payload_for_band_scalars(payload, path=path))
    return tuple(findings)


# --------------------------------------------------------------------------
# Contract observations this harness had to resolve to build anything
# --------------------------------------------------------------------------

#: Points where the FROZEN contract text is ambiguous or where a literal
#: reading of it disagrees with landed production. Recorded here rather
#: than silently resolved, so phase 2 can raise each with Lane F.
CONTRACT_NOTES: Final[Mapping[str, str]] = {
    "formal_identity": (
        "§1 makes 'absence of the is_trial key' the FORMAL test. That holds for the "
        "dict-shaped records production writes (records.py:1436 sets the key only for "
        "trials), but run_output_{run_name}.json is written as "
        "HyperparamTuningOutput.model_dump() (records.py:1048), and that round trip "
        "MATERIALIZES is_trial: false on every formal record. A consumer implementing "
        "the rule literally as `'is_trial' not in record` therefore classifies every "
        "formal record in run_output_*.json as non-formal and selects nothing. The "
        "tuner's own authority uses `not r.get('is_trial', False)` (policy.py:650). "
        "This fixture persists BOTH shapes so either reading is exercised. "
        "STATUS: CLOSED as Q-S3-3 — the landed §1 row now reads 'is_trial absent or "
        "False' and composed_best._formal_role implements it, refusing loudly only on "
        "a non-bool is_trial or a non-None trial_portion. The fixture keeps both "
        "shapes so the regression cannot return unnoticed."
    ),
    "records_file_name": (
        "§1 shows '<node output records>  # {node}_{run_name}.json per the storage "
        "contract', but the tuner's persisted artifact is run_output_{run_name}.json "
        "inside a per-model sub-workspace (records.py:1033; inspect_run_state.py:167), "
        "with summary_{run_name}.json beside it. The contract does not name the file a "
        "Stage-3 winner-selection consumer must open, nor the key holding the records "
        "(HyperparamTuningOutput.all_records)."
    ),
    "deliverable_dir": (
        "§1 says deliverables are 'written into the iteration's tuner sandbox data dir "
        "(base_dir)'. Those are two different directories in production: "
        "sandbox.dirs['data'] is the READ-ONLY raw data root, while deliverables are "
        "written to os.path.join(self.base_dir, denoised_filename_fn(i)) "
        "(sandbox_executor.py:2061). The parenthetical is the operative half; the "
        "phrase 'data dir' can send a consumer to the wrong directory."
    ),
    "refusal_class": (
        "§4 requires a 'NotScoreableError-class refusal'. Production's "
        "NotScoreableError takes a NotScoreableResult, which requires a metric_id and "
        "a verdict naming at least one failure — i.e. the refusal must be built with a "
        "metric identity even though compose_and_score composes INPUTS and does not "
        "know a metric. Phase 2 must decide whether the writers' refusal type is the "
        "production class, a subclass, or a sibling."
    ),
    "strict_best_needs_staging": (
        "A tension between §2, §3 and §4 that only appears when they are read "
        "together. §2 gives EVERY Stage-2 unit all 20 deliverables; §3 says "
        "strict_best 'reads Stage-2 deliverables/ dirs'; §4 refuses when more than one "
        "deliverable resolves for a file across the pooled dirs. Passing four unit "
        "deliverables/ dirs straight to compose_and_score therefore resolves FOUR "
        "candidates for every file and refuses — always, on a perfectly healthy tree. "
        "The only conformant construction is to STAGE a pooled dir holding each "
        "selected unit's target-band slice only, which is exactly what the §4 anchor "
        "(score_tidmad_official_banded.py) does. composed_best does NOT need this: a "
        "Stage-1 band chain ran under a band DataScope, so its winner dir already "
        "holds that band's files and nothing else. §3's wording invites the wrong "
        "reading for strict_best and should say 'stages a pooled dir from'. "
        "STATUS: CLOSED as Q-S3-2 ruling A (supervisor, 2026-08-26), and resolved the "
        "OTHER way than this note proposed — rather than staging a slice, a unit's "
        "deliverables/ now carries its TARGET-BAND files ONLY, so a design's four "
        "units partition 0..19 and whole-dir pooling composes with zero duplicates. "
        "COMPLETE.json's deliverable_count became the band's count, enforced by a "
        "CompleteMarker validator. This fixture builds to the ruling."
    ),
    "resolution_mechanism": (
        "§4's frozen signature takes only deliverable_dirs — no record identities — so "
        "the ONLY way to answer 'exactly one deliverable per file across dirs' is to "
        "parse the input identity out of the filename, i.e. "
        "DeliverableNaming.input_identity_of. The contract does not say so explicitly."
    ),
    "strict_best_fail_closed": (
        "§3 states 'strict_best reads Stage-2 deliverables/ dirs, only from units "
        "whose COMPLETE.json exists and has healthgate_valid: true', which reads as a "
        "FILTER. Q-S3-1 was ruled A by the supervisor (2026-08-26): that filter "
        "reading governs the Stage-2 POLLER only, while strict_best is a FINALIZER "
        "that FAILS CLOSED — one aggregated refusal naming every failing unit, zero "
        "compose_and_score calls, no selection artifact, nonzero exit. This harness "
        "encodes the RULING, not the §3 sentence, because the two are "
        "indistinguishable on a healthy tree and opposite on a degraded one. The "
        "STATUS: CLOSED and VERIFIED against the landed contract on the integration "
        "head — §3 now carries the fail-closed sentence explicitly, and "
        "finalize_strict_best verifies all 16 units and raises BEFORE binding the "
        "composer, so the zero-composer-call property is structural rather than "
        "incidental."
    ),
    "terminal_artifact_marker": (
        "§3's isolation rule is argued STRUCTURALLY (disjoint input roots + a reserved "
        "name), so the contract declares no artifact-level marker at all. The "
        "terminal-eval implementer's guard nevertheless has a content-marker "
        "violation kind — an envelope key by which a terminal artifact self-declares "
        "its namespace. That key is not contract material, so this harness "
        "parameterizes it (TERMINAL_ARTIFACT_MARKER_KEY) and phase 2 supplies the "
        "real one. If a marker becomes load-bearing for isolation, it belongs in §3."
    ),
    "band_label_inclusivity": (
        "The band labels 0-3 / 4-9 / 10-14 / 15-19 are INCLUSIVE on both ends, while "
        "the production band tuples are half-open ((0,4),(4,10),(10,15),(15,20) — "
        "score_tidmad_official_banded.py:77). W1a and W1b exist because that is a "
        "standing off-by-one invitation."
    ),
}
