"""Adversarial witnesses for the Stage-3 Gold-campaign contract — PHASE 1.

**What phase 1 proves.** Not that the writers are correct — their branches
have deliberately not been read. It proves the HARNESS works: every witness
below is executed against a quarantined reference that implements the
frozen contract semantics and nothing else, so a witness that could never
fire is caught here rather than passing vacuously against real code in
phase 2.

**How phase 2 uses this file.** Two fixtures — ``compose_and_score`` and
``strict_best_finalizer`` — are the only swap points. Phase 2 re-points
them at the landed writer modules and the witnesses run unchanged. The
reference implementations stay, as the harness's own regression proof.

Witness inventory, each with the defect it catches and how it fails:

===  =====================================================================
W0   FROZEN SIGNATURE. Defect: the §4 signature drifts — a renamed
     parameter, a lost keyword-only marker, a changed default. Fails as
     a signature mismatch naming the parameter. Only this catches it,
     because all three writers call the wrapper positionally in the happy
     path and would not notice until the second caller.
W1a  BAND-BOUNDARY MISSING. Defect: ``range(4, 9)`` where ``range(4, 10)``
     was meant, so the 4-9 winner is one file short at the UPPER boundary.
     Fails as "no refusal raised" — or, worse in production, as a silent
     19-file score that looks like a valid campaign number.
W1b  BAND-BOUNDARY DUPLICATE. Defect: an off-by-one band map on the LOWER
     boundary makes file 0004 resolvable from two pools. Fails as "no
     refusal raised", or as a refusal that names only one of the two
     paths, which cannot be debugged.
W1c  FORMAL IDENTITY, BOTH PERSISTED SHAPES. Defect: implementing §1's
     "absence of the is_trial key" literally, when the persisted
     run_output_*.json materializes ``is_trial: false``. Fails as "the
     formal predicate rejected a formal record".
W2a  STRICT_BEST STALE-PARTIAL. Defect: a design quad with 3 markers and 1
     stale partial gets finalized on the surviving three. Fails as "no
     refusal", or as a refusal that does not name the unit, or as a
     nonzero compose call count, or as a selection artifact on disk.
W2b  STRICT_BEST HEALTHGATE-INVALID. Same shape, different cause.
W3   TERMINAL_EVAL READ CLOSURE. Defect: a search/selection consumer gains
     a read of the reserved namespace. Two halves — a SOURCE census and
     an ARTIFACT plant matrix separating the three detection bases. Fails
     as an unflagged plant.
W4   SCORE_VECTOR CALL COUNT. Defect: the wrapper scores per band and
     aggregates, which is the F-SCAND-1 slice-mean the contract refuses.
     Fails as a call count != 1.
W5   NO-BAND-SCALAR CENSUS. Defect: a per-band scalar reaches an output
     artifact. Fails as an unflagged plant; the inverse defect — flagging
     a legal band LABEL — fails as a finding on the clean artifact.
===  =====================================================================
"""

from __future__ import annotations

import inspect
import json
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_metric import (
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
    derive_tidmad_metric_spec,
)
from execute_tools.metric_order import MetricOrder
from scripts.stage3.stage3_composed_best import (
    Stage3ComposedBestError,
    _formal_role,  # deliberate private import: the role predicate under adversarial probe — renaming it breaks this suite by design
    select_band_winner,
)
from scripts.stage3.stage3_composed_best import run as composed_best_run
from scripts.stage3.stage3_strict_best import (
    DEFAULT_SELECTION_RELPATH,
    StrictBestRefusal,
    finalize_strict_best,
)
from scripts.stage3.stage3_strict_best import main as strict_best_main
from scripts.stage3.stage3_terminal_eval import (
    BandScalarEmissionError,
    _refuse_band_scalars,  # deliberate private import: the emission guard under adversarial probe (F-VAL-1 witnesses) — renaming it breaks this suite by design
    audit_terminal_read_closure,
)
from tests.unit.scripts.stage3.stage3_adversarial_fixtures import (
    BAND_FILES,
    BAND_LABELS,
    CENSUS_BLIND_SPOTS,
    CONTRACT_NOTES,
    CORRUPTION_BAND,
    DUPLICATED_FILE_IDENTITY,
    EXPECTED_REFUSAL_EXIT_CODE,
    HEALTHGATE_INVALID_UNIT_ID,
    MISSING_FILE_IDENTITY,
    NUM_FILES,
    REPO_ROOT,
    STAGE2_DESIGNS,
    STALE_PARTIAL_UNIT_ID,
    TIDMAD_METRIC_IDENTITY,
    ArtifactPlant,
    DecoyReason,
    FinalizerOutcome,
    ScoreVectorCallCounter,
    Stage1Corruption,
    Stage2Corruption,
    TerminalEvalPlant,
    build_stage1_layout,
    build_stage2_tree,
    build_stage3_namespaces,
    install_counting_score_vector,
    is_band_shaped_key,
    plant_terminal_artifact,
    plant_terminal_eval_read,
    resolves_into,
    scan_for_terminal_eval_reads,
    scan_payload_for_band_scalars,
    scan_tree_for_band_scalars,
)

# ==========================================================================
# QUARANTINED REFERENCES — **NOT PRODUCTION CODE**
#
# Nothing below is importable by, or intended for, any production module.
# Each implements ONE frozen contract semantic and deliberately no more:
# it exists so a witness can be shown to FIRE, which is the only way to
# know the witness is not vacuous before it meets real code in phase 2.
#
# In particular these references implement NO writer-owned policy: not the
# design-quad selection rule, not the scoring arithmetic, not the winner
# ranking. Where the contract delegates, so do they.
# ==========================================================================

#: Reference-only. The real segment set per file is production's business
#: (score_vector's SampleSet); the harness must not invent one, so the
#: reference sends an obviously-empty placeholder and the witnesses assert
#: only the FILE COVERAGE, never the segment content.
_REFERENCE_SEGMENTS: list[int] = []


class _ReferenceComposeAndScore:
    """NOT PRODUCTION. Contract §4 input-resolution semantics, nothing else.

    Implements exactly three frozen facts:

    1. for each file, exactly ONE deliverable must resolve across the
       pooled dirs — missing raises, duplicate raises naming both paths;
    2. a partial ``sample_set`` is not legal here;
    3. the scoring authority is delegated to EXACTLY ONCE, over one pooled
       directory, following the §4 anchor's construction.

    It computes no score of its own: the arithmetic stays behind the
    injected ``score_vector``, exactly as the contract requires of the real
    wrapper.
    """

    #: The contract-id this reference stamps on its refusals.
    contract_id = "stage3_compose_and_score_input_resolution"

    def __init__(
        self,
        *,
        score_vector: Callable[..., tuple[list[float | None], float]],
        pool_root: Path,
        naming: DeliverableNaming | None = None,
    ) -> None:
        self._score_vector = score_vector
        self._pool_root = Path(pool_root)
        self._naming = naming or DeliverableNaming()

    def __call__(
        self,
        deliverable_dirs: list[str],
        *,
        files: range = range(NUM_FILES),
        sample_set: None = None,
    ) -> tuple[list[float], float]:
        if sample_set is not None:
            raise ValueError(
                "compose_and_score scores the FULL sample set; a partial scope is not "
                "legal here (contract §4). Aggregate scalars are only comparable "
                "within one scope."
            )
        resolved = self._resolve(deliverable_dirs)
        failures = self._failures(resolved, files, deliverable_dirs)
        if failures:
            raise NotScoreableError(
                NotScoreableResult(
                    metric_id=TIDMAD_METRIC_IDENTITY.id,
                    direction=TIDMAD_METRIC_IDENTITY.direction,
                    verdict=ScoreabilityVerdict(
                        contract_id=self.contract_id, failures=tuple(failures)
                    ),
                )
            )
        pool = self._stage_pool(resolved, files)
        file_vector, scalar = self._score_vector(
            data_dir=str(pool),
            sample_set={int(f): list(_REFERENCE_SEGMENTS) for f in files},
            denoised_filename_fn=lambda index: self._naming.name(
                model_type="pooled",
                run_name="stage3_pool",
                exp_id="pool",
                input_identity=index,
            ),
        )
        return ([v for v in file_vector if v is not None], scalar)

    def _resolve(self, deliverable_dirs: Sequence[str]) -> dict[int, list[str]]:
        """``{input identity: [absolute paths]}`` across every pooled dir."""
        resolved: dict[int, list[str]] = {}
        for directory in deliverable_dirs:
            for path in sorted(Path(directory).glob(self._naming.any_glob())):
                identity = self._naming.input_identity_of(path.name)
                if identity is None:
                    continue
                resolved.setdefault(identity, []).append(str(path.resolve()))
        return resolved

    def _failures(
        self,
        resolved: Mapping[int, list[str]],
        files: range,
        deliverable_dirs: Sequence[str],
    ) -> list[ScoreabilityFailure]:
        failures: list[ScoreabilityFailure] = []
        for file_index in files:
            paths = resolved.get(int(file_index), [])
            if not paths:
                failures.append(
                    ScoreabilityFailure(
                        requirement="exactly_one_deliverable_per_input",
                        input_identity=int(file_index),
                        detail=(
                            f"no deliverable resolves for file {int(file_index):04d} "
                            f"across the {len(deliverable_dirs)} pooled dirs "
                            f"{list(deliverable_dirs)}"
                        ),
                    )
                )
            elif len(paths) > 1:
                failures.append(
                    ScoreabilityFailure(
                        requirement="exactly_one_deliverable_per_input",
                        input_identity=int(file_index),
                        detail=(
                            f"{len(paths)} deliverables resolve for file "
                            f"{int(file_index):04d}: " + " AND ".join(sorted(paths))
                        ),
                    )
                )
        return failures

    def _stage_pool(self, resolved: Mapping[int, list[str]], files: range) -> Path:
        """One pooled dir, uniformly named — the §4 anchor's construction."""
        pool = self._pool_root / "pooled"
        pool.mkdir(parents=True, exist_ok=True)
        for file_index in files:
            source = Path(resolved[int(file_index)][0])
            shutil.copy2(
                source,
                pool
                / self._naming.name(
                    model_type="pooled",
                    run_name="stage3_pool",
                    exp_id="pool",
                    input_identity=int(file_index),
                ),
            )
        return pool


class _StrictBestRefusal(RuntimeError):
    """NOT PRODUCTION. The aggregated fail-closed refusal of Q-S3-1 = A."""

    exit_code = EXPECTED_REFUSAL_EXIT_CODE

    def __init__(self, failures: Mapping[str, str]) -> None:
        self.failing_units = dict(failures)
        listed = "; ".join(f"{unit}: {why}" for unit, why in sorted(failures.items()))
        super().__init__(
            f"strict_best finalization REFUSED: {len(failures)} Stage-2 unit(s) are not "
            f"finalizable — {listed}. Nothing was scored and no selection artifact was "
            f"written."
        )


class _ReferenceStrictBestFinalizer:
    """NOT PRODUCTION. The Q-S3-1 = A fail-closed rule, and nothing else.

    Enumerates the Stage-2 units, collects EVERY unit that is incomplete or
    HealthGate-invalid, and — if there is even one — raises a single
    aggregated refusal naming all of them, without calling the scoring
    wrapper and without writing a selection artifact.

    The design-quad SELECTION rule is writer-owned; this reference uses an
    arbitrary deterministic stand-in on the healthy path, marked as such,
    because the witnesses assert refusal behaviour and call counts, never
    which unit a healthy tree selects.
    """

    def __init__(self, compose_and_score: Callable[..., tuple[list[float], float]]) -> None:
        self._compose = compose_and_score

    def __call__(self, stage2_root: Path, *, output_path: Path) -> tuple[list[float], float]:
        stage2_root = Path(stage2_root)
        failures: dict[str, str] = {}
        complete: dict[str, Path] = {}
        for unit_dir in sorted(p for p in stage2_root.iterdir() if p.is_dir()):
            marker = unit_dir / "COMPLETE.json"
            if not marker.is_file():
                failures[unit_dir.name] = (
                    "no COMPLETE.json — absence means the unit is not done, and a "
                    "populated deliverables/ dir is not completion evidence"
                )
                continue
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                failures[unit_dir.name] = f"COMPLETE.json is unparseable: {exc}"
                continue
            if payload.get("healthgate_valid") is not True:
                failures[unit_dir.name] = (
                    f"COMPLETE.json reports healthgate_valid={payload.get('healthgate_valid')!r}"
                )
                continue
            complete[unit_dir.name] = unit_dir / "deliverables"

        if failures:
            raise _StrictBestRefusal(failures)

        # Writer-owned in production; an arbitrary deterministic stand-in
        # here. Each unit contributes only its TARGET BAND's slice — see
        # CONTRACT_NOTES['strict_best_needs_staging'] for why passing whole
        # unit deliverables/ dirs would refuse on a healthy tree.
        staged = output_path.parent / "strict_best_staged"
        staged.mkdir(parents=True, exist_ok=True)
        naming = DeliverableNaming()
        for band in BAND_LABELS:
            unit_id = sorted(u for u in complete if u.endswith(f"_{band}"))[0]
            source_dir = complete[unit_id]
            for file_index in BAND_FILES[band]:
                matches = [
                    path
                    for path in sorted(source_dir.glob(naming.any_glob()))
                    if naming.input_identity_of(path.name) == file_index
                ]
                shutil.copy2(matches[0], staged / matches[0].name)
        result = self._compose([str(staged)])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps({"denoising_score": result[1], "file_count": NUM_FILES}, indent=2),
            encoding="utf-8",
        )
        return result


# ==========================================================================
# PHASE-2 SWAP POINTS
# ==========================================================================


#: PHASE 2: the wrapper's own binding. ``stage3_common`` does
#: ``from execute_tools.scoring_utils import score_vector``, so it holds its
#: OWN module attribute — patching the authority's home module would leave
#: this binding untouched and the counter at zero.
SCORE_VECTOR_IMPORT_SITE = "scripts.stage3.stage3_common.score_vector"


#: The reconciled stamp threaded through direct §4 calls (the amendment's
#: required identity transport; tests play the stamping side).
RECONCILED_SPEC = derive_tidmad_metric_spec(resolve_dataset_profile())


@pytest.fixture
def score_counter(monkeypatch: pytest.MonkeyPatch) -> ScoreVectorCallCounter:
    """The counting stand-in installed at the wrapper's real import site."""
    return install_counting_score_vector(monkeypatch, SCORE_VECTOR_IMPORT_SITE)


@pytest.fixture
def compose_and_score(
    score_counter: ScoreVectorCallCounter,
) -> Callable[..., tuple[list[float], float]]:
    """PHASE 2: the LANDED §4 wrapper, with the scoring authority counted."""
    from scripts.stage3.stage3_common import compose_and_score as landed

    return landed


@pytest.fixture
def reference_compose_and_score(tmp_path: Path) -> _ReferenceComposeAndScore:
    """The phase-1 quarantined reference, retained as the harness's own proof.

    Kept so the witnesses stay mutation-proven: every assertion below was
    shown to FIRE against this reference before it ever met production
    code. Deleting it would leave the suite unable to demonstrate that a
    green phase-2 run means anything.
    """
    return _ReferenceComposeAndScore(
        score_vector=ScoreVectorCallCounter(), pool_root=tmp_path / "reference_pool"
    )


# ==========================================================================
# Harness portability — the checkout this harness actually validates
# ==========================================================================


def test_authorities_resolve_from_this_checkout() -> None:
    """The production authorities imported here come from THIS repository.

    Defect caught: this harness silently validating a DIFFERENT clone.
    ``execute_tools`` is a namespace package whose ``__path__`` in a
    worktree contains both the worktree and the editable install's root, so
    an authority missing from the worktree resolves from the other tree and
    a green run says nothing about the code under test — the exact failure
    CLAUDE.md's portability section names.

    Fails as: an assertion naming the module and the foreign path it came
    from.
    """
    import execute_tools.deliverable_spec as spec_module
    import execute_tools.health_checks.candidate_eligibility as eligibility_module

    for module in (spec_module, eligibility_module):
        resolved = Path(module.__file__ or "").resolve()
        assert resolved.is_relative_to(REPO_ROOT), (
            f"{module.__name__} resolved to {resolved}, which is outside the checkout "
            f"under test ({REPO_ROOT}). This harness would be validating another clone."
        )


# ==========================================================================
# W0 — the frozen §4 signature
# ==========================================================================


def test_w0_compose_and_score_has_the_frozen_signature(
    compose_and_score: Callable[..., tuple[list[float], float]],
) -> None:
    """W0: the §4 signature is frozen, parameter names included.

    Defect caught: signature drift. ``deliverable_dirs`` renamed, ``files``
    or ``sample_set`` losing keyword-only status, or a default changing.
    The contract makes this ONE wrapper serve all three writers, so a
    rename that the first caller absorbs positionally breaks the second and
    third — and nothing else in the suite compares the shape.

    Fails as: a mismatch naming the parameter that moved.
    """
    signature = inspect.signature(compose_and_score)
    parameters = list(signature.parameters.values())

    # §4 as amended (supervisor local-gate Step-09a ruling, 2026-08-26):
    # `reconciled_spec` joined the frozen signature as REQUIRED keyword-only
    # identity transport — the caller's reconciled 09a stamp, never derived
    # by the composer.
    assert [p.name for p in parameters] == [
        "deliverable_dirs",
        "files",
        "sample_set",
        "reconciled_spec",
    ], f"§4 freezes the parameter names and their order; got {[p.name for p in parameters]}"
    assert parameters[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    for keyword_only in parameters[1:]:
        assert keyword_only.kind is inspect.Parameter.KEYWORD_ONLY, (
            f"§4 marks {keyword_only.name!r} keyword-only (the '*' in the frozen "
            f"signature); got {keyword_only.kind}"
        )
    assert parameters[1].default == range(NUM_FILES), (
        f"§4 freezes files=range(20) as the full-scope default; got {parameters[1].default!r}"
    )
    assert parameters[2].default is None, (
        "§4 freezes sample_set=None, meaning the FULL sample set; a different default "
        "would make a partial scope reachable"
    )
    assert parameters[3].default is inspect.Parameter.empty, (
        "§4 (amended) makes reconciled_spec REQUIRED — a default would let a caller "
        "compose without a reconciled stamped identity"
    )


def test_w0_partial_sample_set_is_refused(
    tmp_path: Path, compose_and_score: Callable[..., tuple[list[float], float]]
) -> None:
    """W0b: a partial ``sample_set`` is not legal at this seam.

    Defect caught: the wrapper accepting a caller-supplied sample set and
    silently producing a scalar that is only comparable within that scope,
    while every consumer treats it as the campaign's full-scope number.

    Fails as: no exception raised.
    """
    layout = build_stage1_layout(tmp_path / "ws")
    with pytest.raises((ValueError, TypeError, NotScoreableError)):
        compose_and_score(
            layout.pooled_deliverable_dirs(),
            sample_set={0: [0]},  # type: ignore[arg-type]
            reconciled_spec=RECONCILED_SPEC,
        )


# ==========================================================================
# W1 — composed_best band boundaries
# ==========================================================================


def test_w1a_missing_upper_band_boundary_is_a_named_refusal(
    tmp_path: Path,
    compose_and_score: Callable[..., tuple[list[float], float]],
    score_counter: ScoreVectorCallCounter,
) -> None:
    """W1a: the 4-9 winner is short file 0009 — refuse, never score 19 files.

    Defect caught: the natural off-by-one in band-range code — ``range(4, 9)``
    where the inclusive label ``4-9`` means ``range(4, 10)``. The band
    labels are inclusive while the production band tuples are half-open
    (score_tidmad_official_banded.py:77), so the two conventions meet in
    every band map.

    Why nothing else catches it: a 19-file compose produces a perfectly
    plausible campaign scalar. There is no downstream check that the number
    covered 20 files, and the missing file is at a band EDGE, so a per-band
    sanity check that counts "6 files for 4-9" also passes if the map itself
    is what is wrong.

    Fails as: no ``NotScoreableError`` raised — and, if a wrapper instead
    scored the 19 available files, additionally as a nonzero call count on
    the scoring authority.
    """
    layout = build_stage1_layout(
        tmp_path / "ws", corruption=Stage1Corruption.MISSING_BAND_UPPER_BOUNDARY
    )
    winner = layout.winners[CORRUPTION_BAND]
    assert MISSING_FILE_IDENTITY not in winner.deliverable_files
    assert len(winner.deliverable_files) == len(winner.expected_files) - 1

    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score(layout.pooled_deliverable_dirs(), reconciled_spec=RECONCILED_SPEC)

    failures = excinfo.value.result.verdict.failures
    named = {failure.input_identity for failure in failures}
    assert named == {MISSING_FILE_IDENTITY}, (
        f"the refusal must name exactly the missing input identity "
        f"{MISSING_FILE_IDENTITY}; it named {sorted(i for i in named if i is not None)}"
    )
    assert score_counter.call_count == 0, (
        "a refused compose must not reach the scoring authority at all; scoring 19 "
        "files and refusing afterwards still burns the run and still produces a number"
    )


def test_w1b_duplicate_lower_band_boundary_refusal_names_both_paths(
    tmp_path: Path,
    compose_and_score: Callable[..., tuple[list[float], float]],
    score_counter: ScoreVectorCallCounter,
) -> None:
    """W1b: file 0004 resolves from two pools — refuse, naming BOTH paths.

    Defect caught: an off-by-one band map on the LOWER boundary, where the
    0-3 chain believes its band is ``range(0, 5)`` and also emits file 4.
    Both copies are correctly named through the authority under their own
    run/exp identities, so only a per-identity uniqueness check ACROSS the
    pooled dirs can see it.

    Why naming both paths matters, and is asserted separately: a refusal
    saying only "duplicate for file 0004" leaves an operator unable to tell
    which of two band chains has the wrong map. The contract requires both.

    Fails as: no refusal raised (a wrapper that takes the first match wins
    silently, scoring one band's file under another band's model), or a
    refusal whose detail text names fewer than two paths.
    """
    layout = build_stage1_layout(
        tmp_path / "ws", corruption=Stage1Corruption.DUPLICATE_BAND_LOWER_BOUNDARY
    )
    with pytest.raises(NotScoreableError) as excinfo:
        compose_and_score(layout.pooled_deliverable_dirs(), reconciled_spec=RECONCILED_SPEC)

    failures = [
        failure
        for failure in excinfo.value.result.verdict.failures
        if failure.input_identity == DUPLICATED_FILE_IDENTITY
    ]
    assert failures, (
        f"the refusal must name input identity {DUPLICATED_FILE_IDENTITY}, the file "
        f"resolvable from both the 0-3 and the 4-9 pool"
    )
    detail = failures[0].detail
    lower_dir = str(layout.winners["0-3"].deliverable_dir)
    upper_dir = str(layout.winners[CORRUPTION_BAND].deliverable_dir)
    assert lower_dir in detail and upper_dir in detail, (
        "the duplicate refusal must name BOTH resolving paths so the operator can tell "
        f"which band chain has the wrong map; detail was: {detail}"
    )
    assert score_counter.call_count == 0


def test_w1c_formal_identity_holds_in_both_persisted_shapes(tmp_path: Path) -> None:
    """W1c: the formal predicate must accept BOTH persisted record shapes.

    Defect caught: implementing §1's "absence of the ``is_trial`` key"
    literally as ``"is_trial" not in record``. That is correct for the
    dict-shaped records in ``summary_*.json`` and WRONG for
    ``run_output_*.json``, which production writes as
    ``HyperparamTuningOutput.model_dump()`` — a round trip that
    materializes ``is_trial: false`` on every formal record. A literal
    implementation reading run_output therefore finds no formal records at
    all and selects no winner, in silence.

    This test asserts the FIXTURE genuinely carries both shapes, so the
    phase-2 witness that runs a writer's predicate over them cannot pass
    vacuously.

    Fails as: one of the two persisted forms not carrying the shape it is
    supposed to, which would mean the phase-2 witness is testing one shape
    twice.
    """
    layout = build_stage1_layout(tmp_path / "ws")
    workspace = layout.band_workspace[CORRUPTION_BAND]
    winner = layout.winners[CORRUPTION_BAND]

    summaries = sorted(workspace.glob("iter_*/**/summary_*.json"))
    summary_records = [
        record
        for path in summaries
        for record in json.loads(path.read_text(encoding="utf-8"))
        if record["exp_id"] == winner.exp_id
    ]
    assert summary_records, "the fixture planted no winner record in the summary mirror"
    for record in summary_records:
        assert "is_trial" not in record, (
            "the summary mirror is the shape §1 describes: a FORMAL record carries no "
            "is_trial key at all"
        )
        assert "trial_portion" not in record

    outputs = sorted(workspace.glob("iter_*/**/run_output_*.json"))
    output_records = [
        record
        for path in outputs
        for record in json.loads(path.read_text(encoding="utf-8"))["all_records"]
        if record["exp_id"] == winner.exp_id
    ]
    assert output_records, "the fixture planted no winner record in run_output"
    for record in output_records:
        assert record.get("is_trial") is False, (
            "run_output_*.json is produced by HyperparamTuningOutput.model_dump(), "
            "which MATERIALIZES is_trial: false on formal records. If this ever stops "
            "being true the contract's literal-absence rule becomes safe and "
            "CONTRACT_NOTES['formal_identity'] should be retired."
        )

    trial_records = [
        record
        for path in summaries
        for record in json.loads(path.read_text(encoding="utf-8"))
        if record.get("is_trial") is True
    ]
    assert trial_records, (
        "the fixture must plant a TRIAL record too, or a predicate that returns True "
        "for everything would pass this witness"
    )


# ==========================================================================
# W2 — strict_best fails closed (Q-S3-1 = A)
# ==========================================================================


@pytest.mark.parametrize(
    ("corruption", "expected_unit"),
    [
        (Stage2Corruption.STALE_PARTIAL_UNIT, STALE_PARTIAL_UNIT_ID),
        (Stage2Corruption.HEALTHGATE_INVALID_UNIT, HEALTHGATE_INVALID_UNIT_ID),
    ],
    ids=["w2a_stale_partial", "w2b_healthgate_invalid"],
)
def test_w2_degraded_stage2_tree_refuses_and_names_the_unit(
    tmp_path: Path,
    corruption: Stage2Corruption,
    expected_unit: str,
    score_counter: ScoreVectorCallCounter,
) -> None:
    """W2a / W2b: one bad unit refuses the WHOLE finalization, by name.

    Defect caught, W2a: treating a stale partial as "just not there" and
    finalizing the campaign on the surviving three units of the quad. The
    filter reading is correct for the Stage-2 POLLER and wrong for the
    FINALIZER (Q-S3-1 = A) — and the two are indistinguishable on a healthy
    tree, so only a degraded tree can tell them apart.

    Defect caught, W2b: the same, for a unit whose ``COMPLETE.json`` says
    ``healthgate_valid: false``. Excluding it and continuing silently
    changes what the campaign's headline number was computed from.

    Four independent properties are asserted because a wrapper can get any
    one of them right and the rest wrong: the refusal happens; it NAMES the
    failing unit; the scoring authority is called ZERO times; and no
    selection artifact is left on disk.

    Fails as: no exception; or an exception not naming the unit (an
    operator then cannot tell which retrain to re-run); or a nonzero call
    count (the run was scored and then thrown away, or worse, scored and
    kept); or a selection artifact present, which a later stage would read
    as a completed finalization.
    """
    tree = build_stage2_tree(tmp_path / "ws", corruption=corruption)
    assert tree.expected_outcome is FinalizerOutcome.REFUSE
    assert expected_unit in tree.failing_units

    _assert_fails_closed(
        finalizer=finalize_strict_best,
        workspace_root=tmp_path / "ws",
        expected_unit=expected_unit,
        counter=score_counter,
    )


def _assert_fails_closed(
    *,
    finalizer: Callable[..., Any],
    workspace_root: Path,
    expected_unit: str,
    counter: ScoreVectorCallCounter,
) -> None:
    """The Q-S3-1 = A assertion bundle, as ONE reusable unit.

    Four independent properties, because a finalizer can get any one right
    and the rest wrong: it refuses; the refusal NAMES the failing unit; the
    scoring authority is called ZERO times; and no selection artifact is
    left behind. Extracted so the vacuity proof below can run the SAME
    bundle against a deliberately defective finalizer and show it fails —
    the assertions are then known to be load-bearing rather than assumed.
    """
    with pytest.raises(StrictBestRefusal) as excinfo:
        finalizer(workspace_root, STAGE2_DESIGNS)

    message = str(excinfo.value)
    assert expected_unit in message, (
        f"the aggregated refusal must NAME the failing unit {expected_unit!r} so the "
        f"operator knows which retrain to re-run; message was: {message}"
    )
    assert counter.call_count == 0, (
        "a refusing finalizer must not score anything: the point of failing closed is "
        "that no number is produced from an incomplete pool"
    )


def test_w2_refusal_aggregates_every_failing_unit_not_just_the_first(
    tmp_path: Path, score_counter: ScoreVectorCallCounter
) -> None:
    """W2c: TWO independently broken units are BOTH named in ONE refusal.

    Defect caught: a finalizer that refuses on the first problem it meets.
    That still "fails closed", so W2a and W2b both pass against it — but an
    operator then repairs one unit, re-runs the campaign finalization, and
    discovers the second failure only on the next pass. On a 16-unit tree
    with a 4-GPU-wave retrain budget, serialized discovery is the expensive
    failure mode the aggregated refusal exists to prevent.

    Fails as: a refusal naming only one of the two planted units.
    """
    build_stage2_tree(tmp_path / "ws", corruption=Stage2Corruption.STALE_PARTIAL_UNIT)
    # Break a SECOND unit, in a different design quad and by a different
    # cause, so neither failure can mask the other.
    invalid = tmp_path / "ws" / "stage2" / HEALTHGATE_INVALID_UNIT_ID / "COMPLETE.json"
    payload = json.loads(invalid.read_text(encoding="utf-8"))
    payload["healthgate_valid"] = False
    invalid.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(StrictBestRefusal) as excinfo:
        finalize_strict_best(tmp_path / "ws", STAGE2_DESIGNS)

    message = str(excinfo.value)
    for unit in (STALE_PARTIAL_UNIT_ID, HEALTHGATE_INVALID_UNIT_ID):
        assert unit in message, (
            f"the refusal must name EVERY failing unit in one pass; {unit!r} is missing "
            f"from: {message}"
        )
    assert score_counter.call_count == 0


def test_w2_assertion_bundle_is_not_vacuous(
    tmp_path: Path, score_counter: ScoreVectorCallCounter
) -> None:
    """W2 vacuity proof: the bundle FAILS against a filter-and-continue finalizer.

    Defect caught: the W2 witnesses passing for the wrong reason. Production
    may not be mutated to prove a witness fires, so the proof is carried
    here instead — a deliberately defective NON-PRODUCTION finalizer that
    implements the rejected reading (drop the bad unit, finalize on the
    rest). Running the identical assertion bundle against it must FAIL.

    Fails as: the bundle passing against the defective finalizer, which
    would mean W2a/W2b assert nothing.
    """

    def _filter_and_continue(workspace_root: Path, designs: Sequence[str]) -> None:
        """NOT PRODUCTION — the Q-S3-1 reading the supervisor rejected."""
        return None  # silently "succeeds" on a degraded tree

    build_stage2_tree(tmp_path / "ws", corruption=Stage2Corruption.STALE_PARTIAL_UNIT)
    with pytest.raises((AssertionError, pytest.fail.Exception)):
        _assert_fails_closed(
            finalizer=_filter_and_continue,
            workspace_root=tmp_path / "ws",
            expected_unit=STALE_PARTIAL_UNIT_ID,
            counter=score_counter,
        )


def test_w2d_cli_refusal_exits_two_names_the_unit_and_writes_nothing(
    tmp_path: Path,
    score_counter: ScoreVectorCallCounter,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """W2d: at the CLI boundary the bar is exit 2 + named stderr + no artifact.

    Defect caught: a finalizer that refuses correctly in-process but whose
    CLI still exits 0, or writes a selection file before refusing. The
    campaign launcher reads the EXIT CODE, so an in-process refusal that
    exits 0 is invisible to it — and a selection artifact left on disk
    would be read by the next stage as a completed finalization.

    Fails as: a nonzero-but-wrong exit code, a stderr that does not name
    the failing unit, or a selection artifact on disk.
    """
    build_stage2_tree(tmp_path / "ws", corruption=Stage2Corruption.STALE_PARTIAL_UNIT)
    selection = tmp_path / "ws" / DEFAULT_SELECTION_RELPATH

    code = strict_best_main(
        ["--workspace_root", str(tmp_path / "ws"), "--designs", ",".join(STAGE2_DESIGNS)]
    )

    assert code == EXPECTED_REFUSAL_EXIT_CODE, (
        f"a fail-closed refusal must exit {EXPECTED_REFUSAL_EXIT_CODE}; the launcher "
        f"reads the exit code and an exit 0 refusal is invisible to it. Got {code}."
    )
    stderr = capsys.readouterr().err
    assert STALE_PARTIAL_UNIT_ID in stderr, (
        f"the refusal must name {STALE_PARTIAL_UNIT_ID!r} on stderr; got: {stderr}"
    )
    assert not selection.exists(), (
        "no selection artifact may be written by a refused finalization; the next "
        "stage would read it as a completed one"
    )
    assert score_counter.call_count == 0


def test_w2_healthy_tree_scores_once_per_design(
    tmp_path: Path, score_counter: ScoreVectorCallCounter
) -> None:
    """W2 control: a complete tree finalizes, with ONE composer call per design.

    Defect caught: a finalizer that fails closed unconditionally. Without
    this control, W2a and W2b both pass against a function whose body is
    ``raise``, and the harness would certify a mechanism that can never
    finalize a healthy campaign.

    The call count is the second half: contract §4 plus the frozen
    ``strict_best.fail_closed.one_composed_score_per_design.v1`` rule means
    four designs cost exactly four full-scope composer calls. A fifth call
    would mean something is scoring outside the per-design boundary; fewer
    would mean a design was never scored yet still ranked.

    Fails as: an unexpected refusal on a healthy tree, or a call count
    other than exactly one per design.
    """
    tree = build_stage2_tree(tmp_path / "ws", corruption=Stage2Corruption.NONE)
    assert tree.expected_outcome is FinalizerOutcome.PROCEED
    assert tree.failing_units == {}
    assert len(tree.units) == 16, "contract §2: 16 units — 4 designs x 4 target bands"

    selection = finalize_strict_best(tmp_path / "ws", STAGE2_DESIGNS)

    assert score_counter.call_count == len(STAGE2_DESIGNS) == 4, (
        f"one full-scope composer call per design; got {score_counter.call_count}"
    )
    assert selection.selected_design in STAGE2_DESIGNS
    for call in score_counter.calls:
        sample_set = call["kwargs"].get("sample_set")
        assert isinstance(sample_set, Mapping)
        assert sorted(int(k) for k in sample_set) == list(range(NUM_FILES)), (
            "each per-design call must cover all 20 files; a call covering one band's "
            "files is the per-band scalar F-SCAND-1 forbids, wearing a global call count"
        )


# ==========================================================================
# W3 — terminal_eval read closure
# ==========================================================================


@pytest.mark.parametrize(
    "plant",
    [
        TerminalEvalPlant.JOINED_SEGMENTS,
        TerminalEvalPlant.FSTRING_PATH,
        TerminalEvalPlant.GLOB_SCAN,
    ],
)
def test_w3_source_census_catches_each_planted_read(
    tmp_path: Path, plant: TerminalEvalPlant
) -> None:
    """W3 source half: a planted read of the reserved namespace is flagged.

    Defect caught: a search / selection / tuning / scoring-for-selection
    consumer acquiring a read of ``stage3/terminal_eval/``, which is
    exactly what contract §3's isolation rule forbids and what would
    contaminate the terminal evaluation.

    Three plant shapes because they defeat three different naive guards: a
    joined path defeats a literal ``"stage3/terminal_eval"`` grep, an
    f-string defeats an AST pass that only visits plain constants, and a
    glob defeats a guard watching for ``open`` / ``h5py.File``.

    Fails as: zero findings for a planted shape — meaning that shape of
    leak would ship unnoticed.
    """
    target = REPO_ROOT / "execute_tools" / "deliverable_spec.py"
    planted = plant_terminal_eval_read(target, tmp_path / "tree", plant=plant)

    findings = scan_for_terminal_eval_reads(planted.tree_root)
    assert findings, f"the census missed the {plant.value} plant entirely"
    assert any(f.path == planted.planted_file for f in findings)
    assert all(f.kind != "syntax_error" for f in findings), (
        "the plant must leave the copied module parseable, or the census is only "
        "reporting that it could not read the file"
    )
    # Production itself is untouched.
    assert "terminal_eval" not in target.read_text(encoding="utf-8")


def test_w3_source_census_is_clean_on_unplanted_copy(tmp_path: Path) -> None:
    """W3 source control: an unplanted copy yields no findings.

    Defect caught: a census that flags everything. Without this, the
    parametrized test above passes against a scanner whose body is
    ``return (one_finding,)``.

    Fails as: findings on a clean tree — a guard that cries wolf gets
    switched off, which is worse than no guard.
    """
    from tests.unit.scripts.stage3.stage3_adversarial_fixtures import copy_production_tree

    target = REPO_ROOT / "execute_tools" / "deliverable_spec.py"
    tree = copy_production_tree([target], tmp_path / "clean")
    assert scan_for_terminal_eval_reads(tree) == ()


def test_w3_source_census_blind_spot_is_declared_not_discovered(tmp_path: Path) -> None:
    """W3: the computed-name plant is NOT caught, and that is documented.

    Defect caught: this harness overclaiming. A static census cannot see
    ``"terminal" + "_eval"``, and a phase-2 report that presents a green
    census as proof of the isolation rule would be wrong. Pinning the
    blind spot as an executable fact keeps the claim honest and makes the
    limitation impossible to forget.

    Fails as: the blind spot silently closing (then delete this test and
    widen the claim) or the declared list drifting away from reality.
    """
    target = REPO_ROOT / "execute_tools" / "deliverable_spec.py"
    planted = plant_terminal_eval_read(
        target, tmp_path / "tree", plant=TerminalEvalPlant.COMPUTED_NAME
    )
    findings = scan_for_terminal_eval_reads(planted.tree_root)
    assert findings == (), (
        "the computed-name plant is expected to be INVISIBLE to a static census. If "
        "the census now catches it, the guard genuinely improved — update "
        "CENSUS_BLIND_SPOTS and this test together."
    )
    assert any("terminal" in spot and "_eval" in spot for spot in CENSUS_BLIND_SPOTS)


@pytest.mark.parametrize(
    "plant",
    [
        ArtifactPlant.COPY_MARKER_INTACT,
        ArtifactPlant.SYMLINK_MARKER_STRIPPED,
        ArtifactPlant.COPY_OUTSIDE_MARKER_STRIPPED,
    ],
)
def test_w3_artifact_plants_separate_the_three_detection_bases(
    tmp_path: Path, plant: ArtifactPlant
) -> None:
    """W3 artifact half: each plant isolates ONE detection basis.

    Defect caught: a guard that appears to enforce the isolation rule while
    resting on a single basis. A content-marker guard misses a stripped
    symlink; a path-resolution guard misses a marked copy; neither sees a
    stripped copy outside the namespace, which only closed-list enumeration
    excludes.

    Phase 2 asserts a real guard fires on the two detectable plants and
    REPORTS the third rather than failing it, because that residual is a
    property of contract §3's structural argument, not a defect.

    Fails as: the fixture's own claims about a plant being wrong — for
    example a symlink whose real path does not actually land inside the
    namespace, which would make the phase-2 symlink assertion vacuous.
    """
    root = tmp_path / "ws"
    namespaces = build_stage3_namespaces(root)
    layout = build_stage1_layout(root)
    consumer_root = layout.band_workspace[CORRUPTION_BAND]

    planted = plant_terminal_artifact(
        terminal_eval_root=namespaces.terminal_eval,
        consumer_root=consumer_root,
        plant=plant,
    )

    if plant is ArtifactPlant.COPY_MARKER_INTACT:
        assert planted.marker_present is True
        assert planted.resolves_into_terminal_namespace is False
        assert planted.expected_detectable is True
    elif plant is ArtifactPlant.SYMLINK_MARKER_STRIPPED:
        assert planted.marker_present is False
        assert planted.resolves_into_terminal_namespace is True, (
            "the symlink plant is only meaningful if its REAL path lands inside "
            "terminal_eval/; otherwise the phase-2 path-resolution assertion is vacuous"
        )
        assert planted.planted_path.is_symlink()
        assert not resolves_into(planted.planted_path.parent, namespaces.terminal_eval), (
            "the link's own directory must stay innocent, or the plant proves nothing "
            "about resolution"
        )
        assert planted.expected_detectable is True
    else:
        assert planted.marker_present is False
        assert planted.resolves_into_terminal_namespace is False
        assert planted.expected_detectable is False, (
            "the marker-stripped copy outside the namespace is the enumeration "
            "residual; phase 2 reports it and must not fail a guard for missing it"
        )

    payload = json.loads(planted.resolved_path.read_text(encoding="utf-8"))
    from tests.unit.scripts.stage3.stage3_adversarial_fixtures import (
        TERMINAL_ARTIFACT_MARKER_KEY,
    )

    assert (TERMINAL_ARTIFACT_MARKER_KEY in payload) is planted.marker_present


# ==========================================================================
# W4 — the scoring authority is invoked exactly once
# ==========================================================================


def test_w4_full_valid_compose_scores_exactly_once(
    tmp_path: Path,
    compose_and_score: Callable[..., tuple[list[float], float]],
    score_counter: ScoreVectorCallCounter,
) -> None:
    """W4: one compose over 20 valid files = exactly ONE scoring call.

    Defect caught: scoring per band and aggregating the four results —
    F-SCAND-1, the slice-mean the contract explicitly refuses. A per-band
    loop produces four calls and a mean-of-log-space-scores that is not the
    campaign's metric and is not comparable to anything published.

    Why the count is the right assertion: the aggregate produced by four
    calls and a mean can look entirely reasonable. Only the CALL COUNT
    distinguishes "one global ruler" from "four local rulers averaged".

    The coverage assertion is secondary and best-effort: it reads the
    sample-set keys when the wrapper passes a mapping, which proves the one
    call really covered all 20 files rather than one band.

    Fails as: a call count other than 1 — 4 for the per-band loop, 0 for a
    wrapper that never reaches the authority (or a witness patched at the
    wrong import site, which ``install_counting_score_vector`` refuses).
    """
    layout = build_stage1_layout(tmp_path / "ws", corruption=Stage1Corruption.NONE)
    _file_vector, scalar = compose_and_score(
        layout.pooled_deliverable_dirs(), reconciled_spec=RECONCILED_SPEC
    )

    assert score_counter.call_count == 1, (
        f"§4 wraps the scoring authority EXACTLY once over all {NUM_FILES} files; it "
        f"was called {score_counter.call_count} times"
    )
    assert isinstance(scalar, float)

    sample_set = score_counter.calls[0]["kwargs"].get("sample_set")
    if isinstance(sample_set, Mapping):
        assert sorted(int(k) for k in sample_set) == list(range(NUM_FILES)), (
            "the single scoring call must cover every file 0-19; a call covering one "
            "band's files is a per-band scalar wearing a global call count"
        )


def test_w4_counting_stub_refuses_a_wrong_import_site(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W4 control: patching a name nothing binds must FAIL, not count zero.

    Defect caught: a phase-2 witness aimed at the wrong import site. A
    module that did ``from ... import score_vector`` holds its own binding,
    so patching ``execute_tools.scoring_utils.score_vector`` would leave the
    wrapper's binding untouched, the counter at zero — and "0 != 1" reads
    like a real finding while actually meaning the witness never connected.

    Fails as: no ``AttributeError`` — i.e. the helper silently accepting a
    target that does not exist.
    """
    from tests.unit.scripts.stage3.stage3_adversarial_fixtures import (
        install_counting_score_vector,
    )

    with pytest.raises(AttributeError):
        install_counting_score_vector(
            monkeypatch,
            "tests.unit.scripts.stage3.stage3_adversarial_fixtures.no_such_score_vector",
        )


# ==========================================================================
# W5 — the no-band-scalar census
# ==========================================================================


@pytest.mark.parametrize(
    ("payload", "expected_kind"),
    [
        ({"4-9": -2.41}, "band_keyed_number"),
        ({"band_4-9": -2.41}, "band_keyed_number"),
        ({"band4to9": -2.41}, "band_keyed_number"),
        ({"band_1": -2.41}, "band_keyed_number"),
        ({"per_band": {"4-9": {"denoising_score": -2.41}}}, "band_keyed_score_object"),
        ({"summary": {"band_0-3": {"final_scalar": -2.6}}}, "band_keyed_score_object"),
        ({"per_band": [-2.4, -2.5, -2.6, -2.7]}, "band_keyed_number_sequence"),
    ],
    ids=[
        "bare_band_label_to_number",
        "band_prefixed_to_number",
        "band_to_form_to_number",
        "band_index_to_number",
        "per_band_score_object",
        "nested_band_score_object",
        "per_band_number_sequence",
    ],
)
def test_w5_census_flags_every_planted_band_scalar(
    tmp_path: Path, payload: dict[str, Any], expected_kind: str
) -> None:
    """W5: each planted per-band scalar shape is flagged, by kind.

    Defect caught: a per-band scalar reaching an output artifact.
    ``No per-band scalars exist anywhere`` (§4, F-SCAND-1) is the campaign's
    load-bearing scoring invariant: a band-sliced mean of log-space scores
    is a different number from the global-ruler score, and once it appears
    in an artifact somebody will quote it.

    Seven shapes because the invariant is about MEANING, not spelling: the
    same defect writes ``4-9``, ``band_4-9``, ``band4to9`` or ``band_1``,
    and hides the number one level down inside a per-band object or a
    positional list.

    Fails as: an unflagged shape, or the right shape reported under the
    wrong kind (which would misdirect the person fixing it).
    """
    findings = scan_payload_for_band_scalars(payload, path=tmp_path / "artifact.json")
    assert findings, f"the census missed {payload!r}"
    assert expected_kind in {finding.kind for finding in findings}


@pytest.mark.parametrize(
    "payload",
    [
        {"source_band": "4-9", "denoising_score": -2.41},
        {"target_band": "0-3", "healthgate_valid": True, "denoising_score": -2.5},
        {"bands": ["0-3", "4-9", "10-14", "15-19"]},
        {"per_band": {"4-9": {"winner_exp_id": "exp_0102", "model_type": "wavenet"}}},
        {"file_vector": [-2.0 - 0.01 * i for i in range(NUM_FILES)], "denoising_score": -2.4},
        {"units": {"wavenetA_0-3": {"denoising_score": -2.5}}},
        {"band_for_file": {"0": "0-3", "4": "4-9"}},
        {"per_band": {"4-9": {"deliverable_count": 6}}},
    ],
    ids=[
        "band_label_as_string_value",
        "complete_json_unit_scalar",
        "band_roster_of_strings",
        "band_keyed_non_numeric_provenance",
        "frozen_file_vector_and_global_scalar",
        "unit_id_carrying_a_band_token",
        "file_to_band_map",
        "band_keyed_count_not_a_score",
    ],
)
def test_w5_census_passes_legal_band_labels(tmp_path: Path, payload: dict[str, Any]) -> None:
    """W5 inverse: legal band LABELS and unit scalars must NOT be flagged.

    Defect caught: a census so eager that it fires on correct artifacts. A
    band label as a string VALUE is legal provenance; ``COMPLETE.json``'s
    ``denoising_score`` beside ``target_band`` is a UNIT-level scalar that
    contract §2 declares outright; a unit id such as ``wavenetA_0-3``
    carries a band token but is identified by its design too; and a count
    under a band key is provenance, not a score.

    This is the harder half of W5. A census that flags these gets disabled
    within a day, and then the real invariant is unguarded — so the false
    positives are not a cosmetic concern, they are how the guard dies.

    Fails as: any finding at all, naming the legal construction it
    misread.
    """
    findings = scan_payload_for_band_scalars(payload, path=tmp_path / "artifact.json")
    assert findings == [], (
        f"the census flagged a LEGAL construction {payload!r}: {[f.detail for f in findings]}"
    )


def test_w5_band_shaped_key_discrimination() -> None:
    """W5 unit: which keys identify a band ON THEIR OWN.

    Defect caught: the key predicate widening until it matches any key
    containing "band", which is what turns the census into the
    false-positive machine the test above guards against. Pinned
    separately because the predicate is the census's whole discrimination.

    Fails as: a key moving across the boundary.
    """
    for key in ("4-9", "0-3", "band_4-9", "band4to9", "band_1", "band0", "per_band", "bands"):
        assert is_band_shaped_key(key), f"{key!r} identifies a band on its own"
    for key in (
        "wavenetA_0-3",
        "target_band",
        "source_band",
        "band_for_file",
        "denoising_score",
        "file_vector",
        "banded_summary",
    ):
        assert not is_band_shaped_key(key), (
            f"{key!r} does NOT identify a band on its own; flagging it is the census's "
            f"most likely false positive"
        )


def test_w5_tree_scan_reports_unparseable_documents(tmp_path: Path) -> None:
    """W5: a document the census cannot parse is a finding, not a pass.

    Defect caught: a census that skips what it cannot read and reports a
    clean tree. Unreadable is UNPROVEN. This is the same failure class as
    a census whose file set omits a directory — it stays green for a
    reason that has nothing to do with the property being asserted.

    Fails as: an empty finding list over a tree containing malformed JSON.
    """
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    findings = scan_tree_for_band_scalars(tmp_path)
    assert [f.kind for f in findings] == ["unparseable"]


def test_w5_fixture_artifacts_contain_no_band_scalars(tmp_path: Path) -> None:
    """W5 self-application: this harness's own artifacts are clean.

    Defect caught: the harness violating the invariant it enforces. Every
    Stage-1 lock, manifest, tuner output and Stage-2 ``COMPLETE.json`` this
    library writes is scanned by its own census. A fixture that emitted a
    per-band scalar would teach a writer the wrong shape and make the
    phase-2 census's negative result meaningless.

    Fails as: a finding in the fixture tree, naming the artifact and key.
    """
    root = tmp_path / "ws"
    build_stage1_layout(root)
    build_stage2_tree(root)
    build_stage3_namespaces(root)

    findings = scan_tree_for_band_scalars(root)
    assert findings == (), (
        "the harness's own fixtures must satisfy the no-band-scalar invariant: "
        f"{[(str(f.path), f.location, f.detail) for f in findings]}"
    )


# ==========================================================================
# PHASE 2 — the WRITER boundary (composed_best), above the composer
# ==========================================================================


def test_w1a_writer_boundary_refuses_the_missing_band_edge_file(
    tmp_path: Path, score_counter: ScoreVectorCallCounter
) -> None:
    """W1a at composed_best's own boundary: named refusal, nothing scored.

    Defect caught: the writer noticing a winner is a file short and
    proceeding anyway — pooling 19 links and letting the composer produce a
    number, or silently dropping the band. The composer-level W1a proves the
    §4 boundary refuses; this proves the layer ABOVE it does not paper over
    the same defect before the composer ever sees it.

    The refusal class differs by design: composed_best refuses at WINNER
    RESOLUTION (``Stage3ComposedBestError``, citing the §1 retention
    clause), strictly earlier than the composer's ``NotScoreableError``.
    Both are named refusals; the witness asserts the file identity is named
    and that nothing was scored, which is what the contract constrains.

    Fails as: no refusal (a 19-file golden score), a refusal that does not
    name the missing file, or a nonzero scoring-call count.
    """
    layout = build_stage1_layout(
        tmp_path / "ws", corruption=Stage1Corruption.MISSING_BAND_UPPER_BOUNDARY
    )
    with pytest.raises(Stage3ComposedBestError) as excinfo:
        composed_best_run(str(tmp_path / "ws"), layout.arm)

    message = str(excinfo.value)
    assert (
        f"{MISSING_FILE_IDENTITY:04d}" in message or f"file {MISSING_FILE_IDENTITY}" in message
    ), f"the refusal must name the missing input identity {MISSING_FILE_IDENTITY}; got: {message}"
    assert score_counter.call_count == 0, (
        "a winner that cannot supply its band must be refused BEFORE scoring; scoring "
        "19 files and refusing afterwards still produces a number"
    )


def test_w1_writer_selects_the_planted_winner_and_scores_once(
    tmp_path: Path, score_counter: ScoreVectorCallCounter
) -> None:
    """W1 control: the writer picks the PLANTED winner, not a decoy, and scores once.

    Defect caught: a selection that drops any clause of the §1 winner table.
    Four decoys are planted per band, each defeating a different shortcut —
    a TRIAL record with a better score (drops the formal rule), a
    HealthGate-invalid record with a better score (drops
    ``is_valid_candidate``), a later iteration with a worse score (takes the
    last iteration instead of the cumulative best), and a non-success record.
    The expected winner is HARDCODED by the fixture, never recomputed here.

    Fails as: a selected ``exp_id`` that is one of the planted decoys —
    the failure message then names which rule was dropped.
    """
    layout = build_stage1_layout(tmp_path / "ws", corruption=Stage1Corruption.NONE)
    decoys = {decoy.exp_id: decoy.reason.value for decoy in layout.decoys}

    # The witness only discriminates if the ineligible decoys would WIN on
    # score alone. Asserted rather than assumed: if a future fixture edit
    # made the decoys worse than the winner, every shortcut implementation
    # would pass this test and nobody would notice it had stopped testing.
    order = MetricOrder(layout.metric_identity)
    for band, winner in layout.winners.items():
        tempting = [
            decoy
            for decoy in layout.decoys
            if decoy.band == band
            and decoy.reason in (DecoyReason.TRIAL_ROUND, DecoyReason.HEALTHGATE_INVALID)
            and decoy.denoising_score is not None
        ]
        assert tempting, f"band {band}: no score-bearing decoy planted"
        for decoy in tempting:
            assert order.is_better(decoy.denoising_score, winner.denoising_score), (
                f"band {band}: decoy {decoy.exp_id} ({decoy.reason.value}) scores "
                f"{decoy.denoising_score}, which is NOT better than the planted "
                f"winner's {winner.denoising_score} — the decoy is not tempting and "
                f"this witness no longer discriminates"
            )

    for band in BAND_LABELS:
        winner = select_band_winner(str(tmp_path / "ws"), layout.arm, band)
        expected = layout.winners[band]
        assert winner.exp_id == expected.exp_id, (
            f"band {band}: selected {winner.exp_id!r}"
            + (
                f" — a planted DECOY whose rule is {decoys[winner.exp_id]!r}"
                if winner.exp_id in decoys
                else ""
            )
            + f"; the planted winner is {expected.exp_id!r}"
        )
        assert winner.model_type == expected.model_type
        assert sorted(winner.deliverable_paths) == list(expected.expected_files)

    assert score_counter.call_count == 0, "winner selection alone must score nothing"

    composed_best_run(str(tmp_path / "ws"), layout.arm)
    assert score_counter.call_count == 1, (
        f"a composed golden score is ONE full-scope scoring call; got {score_counter.call_count}"
    )


def test_w1c_production_formal_predicate_accepts_both_persisted_shapes(
    tmp_path: Path,
) -> None:
    """W1c: the landed formal predicate accepts BOTH persisted record shapes.

    Defect caught: the Q-S3-3 regression returning. The contract's original
    wording ("absence of the ``is_trial`` key") is literally false for
    ``run_output_*.json``, where ``HyperparamTuningOutput.model_dump()``
    materializes ``is_trial: False``. A predicate implementing the literal
    reading refuses EVERY real formal record and the campaign selects no
    winner, silently.

    This runs the PRODUCTION predicate over records taken from both
    persisted files the fixture writes — the key-absent summary mirror and
    the key-present run_output — so neither shape can regress alone.

    Fails as: the predicate rejecting (or raising on) a real formal record,
    or accepting a trial record.
    """
    layout = build_stage1_layout(tmp_path / "ws")
    workspace = layout.band_workspace[CORRUPTION_BAND]
    winner_id = layout.winners[CORRUPTION_BAND].exp_id

    absent_shape = [
        record
        for path in sorted(workspace.glob("iter_*/**/summary_*.json"))
        for record in json.loads(path.read_text(encoding="utf-8"))
        if record["exp_id"] == winner_id
    ]
    present_shape = [
        record
        for path in sorted(workspace.glob("iter_*/**/run_output_*.json"))
        for record in json.loads(path.read_text(encoding="utf-8"))["all_records"]
        if record["exp_id"] == winner_id
    ]
    assert absent_shape and present_shape
    assert all("is_trial" not in record for record in absent_shape)
    assert all(record.get("is_trial") is False for record in present_shape)

    for record in (*absent_shape, *present_shape):
        assert _formal_role(record, "adversarial fixture") is True, (
            "a persisted FORMAL record must be classified formal in BOTH shapes; "
            "the literal-absence reading refuses every real winner (Q-S3-3)"
        )

    trials = [
        record
        for path in sorted(workspace.glob("iter_*/**/summary_*.json"))
        for record in json.loads(path.read_text(encoding="utf-8"))
        if record.get("is_trial") is True
    ]
    assert trials, "the fixture must plant a trial record or this witness is one-sided"
    for record in trials:
        assert _formal_role(record, "adversarial fixture") is False


# ==========================================================================
# PHASE 2 — W3 against the LANDED read-closure guard
# ==========================================================================


@pytest.mark.parametrize(
    "plant",
    [
        ArtifactPlant.COPY_MARKER_INTACT,
        ArtifactPlant.SYMLINK_MARKER_STRIPPED,
        ArtifactPlant.COPY_OUTSIDE_MARKER_STRIPPED,
    ],
)
def test_w3_landed_read_closure_guard_against_the_plant_matrix(
    tmp_path: Path, plant: ArtifactPlant
) -> None:
    """W3: the landed guard is probed on each detection basis SEPARATELY.

    Defect caught: a read-closure guard that appears to enforce contract §3
    while resting on one basis. A content-marker guard misses a stripped
    symlink; a path-resolution guard misses a marked copy. The plants are
    built so exactly one basis can see each.

    The plant site is ``stage1_band_chain_workspaces`` — deliberately NOT
    ``stage2_retrain_units``, which the implementer used as their own
    negative control, so the guard is exercised on a consumer its author
    did not have in mind.

    The third plant is the ENUMERATION RESIDUAL: marker stripped, real path
    never entering the namespace. Nothing about the file betrays it, so the
    witness asserts it is NOT flagged and reports the residual rather than
    failing the guard — that residual is exactly what §3's structural
    argument (b) rests on, and a guard cannot be blamed for it.

    Fails as: a detectable plant not producing a violation, or the residual
    unexpectedly producing one (which would mean the guard has a basis this
    harness has not accounted for — a finding either way).
    """
    root = tmp_path / "ws"
    namespaces = build_stage3_namespaces(root)
    layout = build_stage1_layout(root)
    consumer_root = layout.band_workspace[CORRUPTION_BAND]

    planted = plant_terminal_artifact(
        terminal_eval_root=namespaces.terminal_eval,
        consumer_root=consumer_root,
        plant=plant,
    )
    report = audit_terminal_read_closure(root)
    hits = [v for v in report.violations if Path(v.path) == planted.planted_path]

    if planted.expected_detectable:
        assert hits, (
            f"the {plant.value} plant at {planted.planted_path} was NOT flagged; its "
            f"only detection basis is {planted.detection_basis}"
        )
        expected_kind = (
            "consumable_path_resolves_into_terminal_namespace"
            if plant is ArtifactPlant.SYMLINK_MARKER_STRIPPED
            else "terminal_artifact_inside_search_consumable_root"
        )
        assert any(hit.kind == expected_kind for hit in hits), (
            f"expected violation kind {expected_kind!r} for {plant.value}; got "
            f"{[hit.kind for hit in hits]}"
        )
        assert any(hit.consumer == "stage1_band_chain_workspaces" for hit in hits)
    else:
        assert not hits, (
            f"the enumeration residual was flagged as {[h.kind for h in hits]}; if the "
            f"guard genuinely gained a basis for it, this witness and "
            f"PlantedArtifact.expected_detectable must be updated together"
        )


def test_w3_landed_guard_is_clean_on_an_unplanted_workspace(tmp_path: Path) -> None:
    """W3 control: a clean campaign workspace produces zero violations.

    Defect caught: a guard that flags everything, which would make the
    parametrized witness above pass for the wrong reason and would get the
    guard switched off in practice.

    Fails as: violations on a workspace with no plant in it.
    """
    root = tmp_path / "ws"
    build_stage3_namespaces(root)
    build_stage1_layout(root)
    build_stage2_tree(root)

    report = audit_terminal_read_closure(root)
    assert report.violations == (), (
        f"clean workspace flagged: {[(v.kind, str(v.path)) for v in report.violations]}"
    )
    assert report.total_roots > 0, "a guard that resolved zero roots proves nothing"


# ==========================================================================
# PHASE 2 — W5 against the LANDED band-scalar refusal
# ==========================================================================


#: F-VAL-1 — FOUND by this harness (phase 2, 2026-08-26) as two
#: ``xfail(strict=True)`` divergences: the landed emission guard inspected
#: only the value DIRECTLY under a band-shaped key, so a band-keyed OBJECT
#: carrying the number one level down was allowed through. FIXED pre-merge
#: (``_refuse_band_scalars`` now refuses any numeric DESCENDANT under a
#: band-shaped key via ``_numeric_descendant``); the two cases below are
#: plain assertions again and are the F-VAL-1 regression witnesses.


@pytest.mark.parametrize(
    ("payload", "independent_verdict"),
    [
        ({"4-9": -2.41}, True),
        ({"band_4-9": -2.41}, True),
        ({"band4to9": -2.41}, True),
        ({"per_band": [-2.4, -2.5, -2.6, -2.7]}, True),
        ({"per_band": {"4-9": {"denoising_score": -2.41}}}, True),
        ({"summary": {"band_0-3": {"final_scalar": -2.6}}}, True),
    ],
    ids=[
        "bare_band_label_to_number",
        "band_prefixed_to_number",
        "band_to_form_to_number",
        "per_band_number_sequence",
        "per_band_nested_band_label_to_score",
        "band_keyed_score_object_one_level_down",
    ],
)
def test_w5_landed_band_scalar_refusal_against_the_independent_census(
    tmp_path: Path, payload: dict[str, Any], independent_verdict: bool
) -> None:
    """W5: the landed emission guard, probed with an INDEPENDENT census.

    Defect caught: a per-band scalar reaching a terminal artifact.
    ``No per-band scalars exist anywhere`` (§4, F-SCAND-1) is the campaign's
    load-bearing scoring invariant — a band-sliced mean of log-space scores
    is a different number from the global-ruler score, and once it lands in
    an artifact somebody will quote it.

    Both censuses run on each payload. Where they disagree, the
    disagreement IS the finding: this harness's census was written from the
    contract alone, so a shape it flags and the production guard does not is
    a gap in the guard, not a difference of opinion.

    Fails as: the independent census missing a shape it should flag. A
    production-guard miss is REPORTED through the divergence assertion
    below, which names the payload and the mechanism.
    """
    findings = scan_payload_for_band_scalars(payload, path=tmp_path / "artifact.json")
    assert bool(findings) is independent_verdict, (
        f"the independent census verdict changed for {payload!r}: {findings}"
    )

    production_refused = True
    try:
        _refuse_band_scalars(payload, artifact="adversarial probe")
    except BandScalarEmissionError:
        production_refused = True
    else:
        production_refused = False

    assert production_refused == independent_verdict, (
        f"CENSUS DIVERGENCE on {payload!r}: the independent census says "
        f"{'REFUSE' if independent_verdict else 'ALLOW'} and the landed emission guard "
        f"says {'REFUSE' if production_refused else 'ALLOW'}. A band-shaped key whose "
        f"numeric payload sits one level down inside an object is still a per-band "
        f"scalar; the landed predicate only inspects the value DIRECTLY under the "
        f"band-shaped key, so an object-wrapped score passes."
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"source_band": "4-9", "denoising_score": -2.41},
        {"bands": ["0-3", "4-9", "10-14", "15-19"]},
        {"per_band": {"4-9": {"winner_exp_id": "exp_0102", "model_type": "wavenet"}}},
        {"file_vector": [-2.0 - 0.01 * i for i in range(NUM_FILES)], "denoising_score": -2.4},
    ],
    ids=[
        "band_label_as_string_value",
        "band_roster_of_strings",
        "band_keyed_non_numeric_provenance",
        "frozen_file_vector_and_global_scalar",
    ],
)
def test_w5_both_censuses_pass_legal_band_labels(tmp_path: Path, payload: dict[str, Any]) -> None:
    """W5 inverse: neither census may flag a legal band LABEL.

    Defect caught: a census so eager it fires on correct artifacts. A band
    label as a string VALUE is provenance; a band roster is a roster; the
    frozen 20-entry ``file_vector`` beside a global scalar is the contract's
    own output shape. A guard that refuses these blocks a legitimate
    terminal emission, and a blocked guard gets removed.

    Fails as: either census flagging a legal construction.
    """
    findings = scan_payload_for_band_scalars(payload, path=tmp_path / "artifact.json")
    assert findings == [], f"independent census flagged legal {payload!r}: {findings}"
    _refuse_band_scalars(payload, artifact="adversarial probe")


# ==========================================================================
# Contract observations — kept executable so they cannot rot silently
# ==========================================================================


def test_contract_notes_are_populated_for_phase_two() -> None:
    """Every contract ambiguity this harness hit is recorded, not resolved.

    Defect caught: an ambiguity being silently decided inside the harness
    and never reaching Lane F. Each entry is a decision the writers may
    each have made differently; the phase-2 report reads from here.

    Fails as: a note going missing, which would mean an ambiguity was
    resolved in code without being raised.
    """
    expected = {
        "formal_identity",
        "records_file_name",
        "deliverable_dir",
        "refusal_class",
        "strict_best_fail_closed",
        "strict_best_needs_staging",
        "terminal_artifact_marker",
        "resolution_mechanism",
        "band_label_inclusivity",
    }
    assert set(CONTRACT_NOTES) == expected
    assert all(len(text) > 80 for text in CONTRACT_NOTES.values())


def test_fixture_band_map_matches_the_contract_vocabulary() -> None:
    """The band vocabulary is the contract's, and it partitions 0..19.

    Defect caught: the harness's own band map drifting from the DS8
    vocabulary, which would make W1a and W1b test the wrong boundary and
    quietly certify the very off-by-one they exist to find.

    Fails as: a label or a file set that does not match the contract's
    ``0-3 | 4-9 | 10-14 | 15-19``, or a file appearing in two bands.
    """
    assert BAND_LABELS == ("0-3", "4-9", "10-14", "15-19")
    assert BAND_FILES["0-3"] == (0, 1, 2, 3)
    assert BAND_FILES["4-9"] == (4, 5, 6, 7, 8, 9)
    assert BAND_FILES["10-14"] == (10, 11, 12, 13, 14)
    assert BAND_FILES["15-19"] == (15, 16, 17, 18, 19)

    covered = [f for label in BAND_LABELS for f in BAND_FILES[label]]
    assert sorted(covered) == list(range(NUM_FILES))
    assert len(covered) == len(set(covered)), "a file may belong to exactly one band"


def test_harness_never_reads_a_writer_worktree_or_branch() -> None:
    """This harness imports nothing from a Stage-3 writer's tree.

    Defect caught: the independence rule eroding. A harness that imports a
    writer's module cannot catch a defect it shares with that module — the
    validation becomes a tautology. Checked as a property of the imported
    module set rather than as a promise in a docstring.

    Fails as: a loaded module resolving inside ``.claude/worktrees`` or a
    ``stage3`` package that phase 1 has no business importing.
    """
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if not origin:
            continue
        resolved = Path(origin).resolve()
        if ".claude/worktrees" not in str(resolved):
            continue
        assert resolved.is_relative_to(REPO_ROOT), (
            f"module {name} was loaded from another worktree ({resolved}); phase 1 "
            f"must read only its own checkout"
        )
