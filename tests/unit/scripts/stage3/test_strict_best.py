"""Stage-3 Strict Best finalization witnesses (contract PR #329, operator lane D).

Every test drives the REAL production entry points (``finalize_strict_best``
or ``main``) with only the frozen §4 composer boundary stubbed (SRI-2: prove
consumption at the runtime consumer, never a re-implementation), on synthetic
Stage-2 trees under ``tmp_path``. The witnesses, each with its failure mode:

* missing-COMPLETE refusal — a marker-less unit (even with partial content
  present) refuses the WHOLE finalization by name, with zero composer calls;
* healthgate_invalid refusal — the operator negative control: a numerically
  excellent invalid unit is never selectable, its score never echoed;
* one-composed-call-per-design — exactly one full-scope pooled call per
  design, in frozen band order;
* direction-aware selection — including a lower-is-better MetricOrder case;
* SRI-11 pin — an AST census over the production module that goes RED if a
  per-band-mean path (second composer call site, division, sum/mean family,
  local max/min/sorted, or a direction-literal comparison) is added;
* no-band-scalar outputs (coordinator hazard flag, 2026-08-26) — the
  provenance JSON and stdout carry no band-level scalar field.

The sibling module ``scripts/stage3/stage3_common.py`` is owned by a parallel
writer lane and may not exist on this branch; the stubs here honor the frozen
signature, and one test proves the production importlib binding resolves that
exact module path.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import types
from pathlib import Path

import pytest

from core.iteration_manifest import publish_iteration_manifest, sha256_file
from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.evaluation_metric import (
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
    derive_tidmad_metric_spec,
)
from execute_tools.metric_order import MetricOrder
from scripts.stage3 import stage3_strict_best as strict_best
from scripts.stage3.stage3_strict_best import (
    StrictBestRefusal,
    StrictBestSelection,
    finalize_strict_best,
    main,
)

# Contract vocabulary, restated as LITERALS on purpose: expectations here must
# not be derived from the module under test (a drifted production constant has
# to turn a test red, not re-shape the fixtures silently).
BANDS = ("0-3", "4-9", "10-14", "15-19")
DESIGNS = ("wavenetA", "punetB", "gatedfnoC", "rnnD")

#: Fixture sentinels: unit dir exists but carries no COMPLETE.json (a partial),
#: or the unit dir does not exist at all.
SKIP_MARKER = object()
ABSENT_UNIT = object()

_FLOAT_RE = re.compile(r"-?\d+\.\d+")


def _marker_payload(design: str, band: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "design": design,
        "target_band": band,
        "exp_id": f"exp_{design}_{band}",
        "model_type": "wavenet",
        "repo_sha": "a" * 40,
        "denoising_score": -3.25,
        "healthgate_valid": True,
        # Q-S3-2 ruling A: the TARGET band's file count (band "a-b" == b-a+1).
        "deliverable_count": len(strict_best.band_file_indices(band)),
        "completed_utc": "2026-08-26T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _build_tree(
    workspace_root: Path, overrides: dict[tuple[str, str], object] | None = None
) -> Path:
    """Build a synthetic 4x4 Stage-2 tree per contract §2 under tmp_path.

    ``overrides[(design, band)]`` may be ``SKIP_MARKER`` (partial unit, no
    marker), ``ABSENT_UNIT`` (no dir), a raw ``str`` (written verbatim as the
    marker file), or a ``dict`` of payload overrides.
    """
    overrides = overrides or {}
    for design in DESIGNS:
        for band in BANDS:
            spec = overrides.get((design, band), {})
            if spec is ABSENT_UNIT:
                continue
            unit_dir = workspace_root / "stage2" / f"{design}_{band}"
            (unit_dir / "deliverables").mkdir(parents=True)
            if spec is SKIP_MARKER:
                # Partial content WITHOUT the atomic marker: must count as
                # "not done", never as evidence.
                (unit_dir / "deliverables" / "partial_file0000.h5").write_bytes(b"partial")
                continue
            if isinstance(spec, str):
                (unit_dir / "COMPLETE.json").write_text(spec, encoding="utf-8")
                continue
            assert isinstance(spec, dict)
            payload = _marker_payload(design, band)
            payload.update(spec)
            (unit_dir / "COMPLETE.json").write_text(json.dumps(payload), encoding="utf-8")
    return workspace_root


class ComposerSpy:
    """Frozen §4 boundary stub: records every call, returns per-design scores.

    Declares ``files`` and ``sample_set`` WITHOUT defaults so the test fails
    if production ever stops passing the full scope explicitly.
    """

    def __init__(
        self, scores_by_design: dict[str, float], *, raises: Exception | None = None
    ) -> None:
        self.scores_by_design = scores_by_design
        self.raises = raises
        self.calls: list[tuple[list[str], range, None, object]] = []

    def __call__(
        self,
        deliverable_dirs: list[str],
        *,
        files: range,
        sample_set: None,
        reconciled_spec: object,
    ) -> tuple[list[float], float]:
        self.calls.append((list(deliverable_dirs), files, sample_set, reconciled_spec))
        if self.raises is not None:
            raise self.raises
        designs = {Path(entry).parent.name.rsplit("_", 1)[0] for entry in deliverable_dirs}
        assert len(designs) == 1, f"pooled dirs must belong to ONE design, got {designs}"
        scalar = self.scores_by_design[designs.pop()]
        return ([scalar] * 20, scalar)


def _expected_pooled_dirs(workspace_root: Path, design: str) -> list[str]:
    return [
        str((workspace_root / "stage2" / f"{design}_{band}" / "deliverables").resolve())
        for band in BANDS
    ]


def _uniform_scores() -> dict[str, float]:
    return {"wavenetA": -2.0, "punetB": 1.5, "gatedfnoC": 3.0, "rnnD": 2.5}


def _seam_spec(direction: str = "higher"):
    """A full MetricSpec for the injection seam (tests play the stamping side).

    ``model_copy`` keeps the production shape while overriding the identity —
    the seam narrowed to ``MetricSpec`` after the gate ruling (an identity
    key cannot cross the §4 composer boundary).
    """
    base = derive_tidmad_metric_spec(resolve_dataset_profile())
    return base.model_copy(update={"id": "strict_best_test_metric", "direction": direction})


def _write_unit_workspaces(
    root: Path, stamp: dict[str, object] | None = None, *, omit_spec_for: str | None = None
) -> None:
    """Give every 4x4 unit the contract-§2 chain workspace with a 09a stamp.

    The production metric path (``metric=None``) RECONCILES the stamped
    ``metric_spec`` from each unit's ``workspace/`` run output, read through
    the manifest-VERIFIED loader — so the fixture publishes a REAL manifest
    (self-digested, output-digested), never a hand-rolled one.
    """
    payload = (
        stamp
        if stamp is not None
        else derive_tidmad_metric_spec(resolve_dataset_profile()).model_dump()
    )
    for design in DESIGNS:
        for band in BANDS:
            iter_dir = root / "stage2" / f"{design}_{band}" / "workspace" / "iter_001"
            sub = iter_dir / "iteration_001" / "wavenet"
            sub.mkdir(parents=True, exist_ok=True)
            output_path = sub / "run_output_iter_001.json"
            output_doc: dict[str, object] = {
                "run_name": "iter_001",
                "metric_spec": payload,
                "all_records": [],
            }
            if omit_spec_for == f"{design}_{band}":
                # The pre-09a output shape (gate-ruling regression fixture).
                del output_doc["metric_spec"]
            output_path.write_text(json.dumps(output_doc), encoding="utf-8")
            publish_iteration_manifest(
                str(iter_dir),
                {
                    "status": "completed",
                    "iteration_dir": str(iter_dir),
                    "output_path": str(output_path),
                    "model_name": "wavenet",
                    "run_output_sha256": sha256_file(str(output_path)),
                },
            )


# ---------------------------------------------------------------------------
# Frozen-constant pins
# ---------------------------------------------------------------------------


def test_frozen_vocabulary_pins() -> None:
    """Contract Conventions + operator semantics, pinned as hardcoded literals.

    Fails when: the band vocabulary (values OR order — order fixes the pooled
    dir sequence), the 4-design rule, or the full 0..19 scope constant drifts.
    """
    assert strict_best.BAND_VOCABULARY == ("0-3", "4-9", "10-14", "15-19")
    assert strict_best.EXPECTED_DESIGN_COUNT == 4
    assert strict_best.FULL_FILE_SET == range(20)
    assert strict_best.COMPLETE_MARKER_NAME == "COMPLETE.json"
    assert strict_best.DELIVERABLES_DIR_NAME == "deliverables"


# ---------------------------------------------------------------------------
# Witness: missing-COMPLETE refusal (fail-closed, all refusals named)
# ---------------------------------------------------------------------------


def test_missing_complete_marker_is_named_refusal_and_no_scoring(tmp_path: Path) -> None:
    """A unit without its atomic marker refuses the WHOLE finalization by name.

    Two units are broken at once — a partial dir without COMPLETE.json and a
    fully absent unit — and BOTH must be named in one refusal (the operator
    sees the complete list, not one problem per rerun), with zero composer
    calls and no partial selection.

    Fails when: a marker-less unit is skipped instead of refused, partial
    content is accepted as completion, refusals are reported one-at-a-time,
    or scoring proceeds on an incomplete design set.
    """
    root = _build_tree(
        tmp_path / "campaign",
        {("punetB", "4-9"): SKIP_MARKER, ("rnnD", "15-19"): ABSENT_UNIT},
    )
    _write_unit_workspaces(root)
    spy = ComposerSpy(_uniform_scores())
    with pytest.raises(StrictBestRefusal) as excinfo:
        finalize_strict_best(root, DESIGNS, compose_and_score_fn=spy)
    refusal = excinfo.value
    assert len(refusal.refusals) == 2
    text = str(refusal)
    assert "punetB_4-9" in text
    assert "rnnD_15-19" in text
    assert "COMPLETE.json" in text
    assert spy.calls == []


# ---------------------------------------------------------------------------
# Witness: healthgate_invalid refusal — the operator negative control
# ---------------------------------------------------------------------------


def test_healthgate_invalid_unit_never_selectable_negative_control(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A numerically excellent HealthGate-invalid unit must NOT be selectable.

    The invalid unit carries denoising_score=999.25 — the best number anywhere
    in the tree. The finalization must refuse (exit 2), name the unit and the
    healthgate condition, write NO selection artifact, make NO composer call,
    and never echo the excellent score into any output (band-scoped scalar,
    coordinator hazard flag).

    Fails when: validity stops gating selection, an invalid unit's score can
    reach or influence a selection, a selection file appears despite the
    refusal, or the refusal leaks the unit's score.
    """
    root = _build_tree(
        tmp_path / "campaign",
        {("gatedfnoC", "10-14"): {"healthgate_valid": False, "denoising_score": 999.25}},
    )
    _write_unit_workspaces(root)
    spy = ComposerSpy(_uniform_scores())
    rc = main(
        ["--workspace_root", str(root), "--designs", ",".join(DESIGNS)],
        compose_and_score_fn=spy,
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "gatedfnoC_10-14" in captured.err
    assert "healthgate_valid" in captured.err
    assert "999.25" not in captured.out + captured.err
    assert spy.calls == []
    assert not (root / "stage3").exists()


# ---------------------------------------------------------------------------
# Witness: malformed markers refuse (fail-closed marker validation routing)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "expected_fragment"),
    [
        pytest.param({"healthgate_valid": "true"}, "frozen marker schema", id="string-bool"),
        pytest.param("{not valid json", "not JSON", id="corrupt-json"),
        pytest.param({"design": "someoneelse"}, "identity mismatch", id="identity-mismatch"),
        pytest.param(
            {"deliverable_count": 20},
            "frozen marker schema",
            id="q-s3-2-wrong-band-count",
        ),
    ],
)
def test_malformed_marker_is_named_refusal(
    tmp_path: Path, override: object, expected_fragment: str
) -> None:
    """A malformed COMPLETE.json becomes a NAMED unit refusal, never a pass.

    The string-bool case is the strictness pin: ``"healthgate_valid": "true"``
    must refuse — relaxing StrictBool to lax bool would silently coerce the
    one gate field Stage-3 consumes, and this test goes red exactly then. The
    others pin the refusal ROUTING (corrupt file, wrong artifact in the dir)
    rather than an unhandled traceback.

    Fails when: marker validation is relaxed or a malformed marker crashes
    instead of refusing with the unit named; or scoring proceeds regardless.
    """
    root = _build_tree(tmp_path / "campaign", {("wavenetA", "0-3"): override})
    spy = ComposerSpy(_uniform_scores())
    with pytest.raises(StrictBestRefusal) as excinfo:
        finalize_strict_best(root, DESIGNS, compose_and_score_fn=spy)
    text = str(excinfo.value)
    assert "wavenetA_0-3" in text
    assert expected_fragment in text
    assert spy.calls == []


@pytest.mark.parametrize(
    "designs",
    [
        pytest.param(DESIGNS[:3], id="three-designs"),
        pytest.param((*DESIGNS, "extraE"), id="five-designs"),
        pytest.param(("wavenetA", "wavenetA", "gatedfnoC", "rnnD"), id="duplicate"),
    ],
)
def test_design_set_must_be_exactly_four_distinct(tmp_path: Path, designs: tuple[str, ...]) -> None:
    """The frozen 4-design semantics is enforced before anything runs.

    Fails when: a partial or duplicated design list is accepted — the
    "best of 3" degradation the fail-closed rule exists to prevent.
    """
    root = _build_tree(tmp_path / "campaign")
    spy = ComposerSpy(_uniform_scores())
    with pytest.raises(StrictBestRefusal):
        finalize_strict_best(root, designs, compose_and_score_fn=spy)
    assert spy.calls == []


# ---------------------------------------------------------------------------
# Witness: one composed full-scope call per design
# ---------------------------------------------------------------------------


def test_one_composed_score_call_per_design_full_scope(tmp_path: Path) -> None:
    """Each design gets EXACTLY ONE composer call: 4 pooled band dirs, 0..19.

    Fails when: scoring becomes per-band (16 calls), the pooled dir order
    leaves the frozen band order, the full scope stops being passed
    explicitly (the spy declares no defaults), sample_set gains a value, or
    a design is scored twice/never.
    """
    root = _build_tree(tmp_path / "campaign")
    spy = ComposerSpy(_uniform_scores())
    selection = finalize_strict_best(
        root,
        DESIGNS,
        compose_and_score_fn=spy,
        metric=_seam_spec(),
    )
    assert isinstance(selection, StrictBestSelection)
    assert len(spy.calls) == 4
    for design, (dirs, files, sample_set, _spec) in zip(DESIGNS, spy.calls, strict=True):
        assert dirs == _expected_pooled_dirs(root, design)
        assert files == range(20)
        assert sample_set is None


def test_composer_refusal_is_named_and_fail_closed(tmp_path: Path) -> None:
    """A NotScoreableError from the composer surfaces as a refusal naming the design.

    Fails when: the composer's refusal is swallowed, loses the design name,
    or escapes as a raw traceback instead of the named fail-closed channel.
    """
    root = _build_tree(tmp_path / "campaign")
    refusal_exc = NotScoreableError(
        NotScoreableResult(
            metric_id="tidmad_denoising_score",
            direction="higher",
            verdict=ScoreabilityVerdict(
                contract_id="stage3_compose_pooling",
                failures=(
                    ScoreabilityFailure(
                        requirement="exactly_one_deliverable_per_file",
                        input_identity=7,
                        detail="file 0007 unresolved across pooled dirs",
                    ),
                ),
            ),
        )
    )
    spy = ComposerSpy(_uniform_scores(), raises=refusal_exc)
    with pytest.raises(StrictBestRefusal) as excinfo:
        finalize_strict_best(
            root,
            DESIGNS,
            compose_and_score_fn=spy,
            metric=_seam_spec(),
        )
    text = str(excinfo.value)
    assert "wavenetA" in text
    assert "file 0007 unresolved across pooled dirs" in text


# ---------------------------------------------------------------------------
# Witness: direction-aware selection (never assumed higher-is-better)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "expected_design"),
    [
        pytest.param("higher", "gatedfnoC", id="higher-is-better"),
        pytest.param("lower", "wavenetA", id="lower-is-better"),
    ],
)
def test_selection_follows_metric_order_direction(
    tmp_path: Path, direction: str, expected_design: str
) -> None:
    """Selection is MetricOrder's, from the declaration — both directions.

    Scores are fixed so argmax and argmin land on DIFFERENT designs; a
    hardcoded max() (or any local direction literal) passes one case and
    goes red on the other.

    Fails when: the direction stops being read from the declaration, or the
    selected score/dirs are mis-plumbed from a different design.
    """
    root = _build_tree(tmp_path / "campaign")
    scores = _uniform_scores()
    spy = ComposerSpy(scores)
    selection = finalize_strict_best(
        root,
        DESIGNS,
        compose_and_score_fn=spy,
        metric=_seam_spec(direction),
    )
    assert selection.selected_design == expected_design
    assert selection.selected_strict_score == scores[expected_design]
    assert selection.selected_deliverable_dirs == _expected_pooled_dirs(root, expected_design)
    assert selection.metric_id == "strict_best_test_metric"
    assert selection.metric_direction == direction


def test_gate_ruling_unit_without_spec_stamp_is_a_named_refusal(tmp_path: Path) -> None:
    """Step-09a gate-ruling negative (2026-08-26): a stamp-less unit refuses.

    The production metric path reconciles the 09a stamps persisted in the 16
    unit workspaces; a unit whose run output carries NO ``metric_spec`` is a
    pre-09a shape and must join the ONE aggregated fail-closed refusal —
    zero composer calls, no selection. Fails when: the sourcing regains a
    fallback derivation (selection would succeed) or the absence is
    silently excluded instead of refused."""
    root = _build_tree(tmp_path / "campaign")
    _write_unit_workspaces(root, omit_spec_for="punetB_4-9")
    spy = ComposerSpy(_uniform_scores())
    with pytest.raises(StrictBestRefusal) as excinfo:
        finalize_strict_best(root, DESIGNS, compose_and_score_fn=spy)
    text = str(excinfo.value)
    assert "punetB_4-9" in text
    assert "no metric_spec stamp" in text
    assert spy.calls == []


def test_production_metric_authority_selects(tmp_path: Path) -> None:
    """Without injection, selection follows the ONE production metric authority.

    The expected winner is computed here THROUGH the authority chain
    (``derive_tidmad_metric_spec(resolve_dataset_profile())`` + MetricOrder) —
    no direction literal appears in this test.

    Fails when: production stops consulting the derivation authority (e.g. a
    reintroduced hardcoded max/min), or the stamped metric identity diverges
    from the spec that ordered the selection.
    """
    root = _build_tree(tmp_path / "campaign")
    _write_unit_workspaces(root)
    scores = _uniform_scores()
    spy = ComposerSpy(scores)
    out_path = tmp_path / "out" / "selection.json"
    rc = main(
        [
            "--workspace_root",
            str(root),
            "--designs",
            ",".join(DESIGNS),
            "--out",
            str(out_path),
        ],
        compose_and_score_fn=spy,
    )
    assert rc == 0
    spec = derive_tidmad_metric_spec(resolve_dataset_profile())
    expected_design, _ = MetricOrder(spec).best(list(scores.items()), key=lambda kv: kv[1])
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["selected_design"] == expected_design
    assert data["metric_id"] == spec.id
    assert data["metric_direction"] == spec.direction


# ---------------------------------------------------------------------------
# Witness: SRI-11 — a per-band-mean path is inexpressible in the module
# ---------------------------------------------------------------------------


def _is_path_join_operand(node: ast.expr) -> bool:
    """A ``/`` right operand that can only be a pathlib join, never a divisor.

    Allowed: an f-string, a str constant, or an ALL-CAPS frozen-constant Name
    (the module's layout constants). A chained join ``a / b / c`` always has
    one of these as each right operand. A mean's divisor — a numeric
    constant, ``len(...)``, or a lowercase name — is none of these.
    """
    if isinstance(node, ast.JoinedStr):
        return True
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]*", node.id):
        return True
    return False


def test_sri11_per_band_mean_is_inexpressible() -> None:
    """SRI-11 pin: adding a per-band-mean path turns this census RED.

    Over the production module's AST: exactly ONE ``compose_and_score`` call
    site; no sum/mean/average/median family (called OR referenced); no local
    ``max``/``min``/``sorted`` calls (ordering belongs to MetricOrder); no
    ``statistics``/``numpy`` import; no ``/`` whose right operand could be a
    divisor (only pathlib joins onto strings/frozen constants are allowed) and
    no ``//``; no arithmetic with a NUMERIC constant operand (``/ 4``,
    ``* 0.25``, ``+ 1`` are all refused); no arithmetic AugAssign (accumulator
    loops); and no comparison against a ``"higher"``/``"lower"`` literal
    (direction is interpreted ONLY by MetricOrder). Every idiomatic way to
    average four band scalars needs at least one of these constructs — and the
    runtime witnesses close the rest: one-call-per-design catches per-band
    composer calls, and the no-band-scalar witness catches emitting a band
    scalar however computed.

    Fails when: any construct above appears in
    ``scripts/stage3/stage3_strict_best.py``.
    """
    source = Path(strict_best.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    compose_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "compose_and_score")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "compose_and_score")
        )
    ]
    assert len(compose_calls) == 1, (
        f"SRI-11: expected exactly ONE compose_and_score call site, found {len(compose_calls)}"
    )

    banned_refs = {"mean", "fmean", "nanmean", "average", "median"}
    banned_calls = {"sum", "max", "min", "sorted"}

    def _is_numeric_constant(node: ast.expr) -> bool:
        return (
            isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in banned_refs, f"SRI-11: banned reference {node.id!r}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in banned_refs, f"SRI-11: banned reference .{node.attr}"
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            assert name not in banned_calls, (
                f"SRI-11: banned call {name!r} — ordering/aggregation must not be local"
            )
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.FloorDiv):
                raise AssertionError("SRI-11: floor division found")
            if isinstance(node.op, ast.Div):
                assert _is_path_join_operand(node.right), (
                    f"SRI-11: '/' with a non-path right operand at line {node.lineno} — "
                    "only pathlib joins are allowed, a divisor is not"
                )
            if isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
                assert not (_is_numeric_constant(node.left) or _is_numeric_constant(node.right)), (
                    f"SRI-11: arithmetic with a numeric constant at line {node.lineno} — "
                    "no local score arithmetic is allowed"
                )
        if isinstance(node, ast.AugAssign):
            assert not isinstance(
                node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
            ), f"SRI-11: arithmetic AugAssign (accumulator) at line {node.lineno}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in {"statistics", "numpy"}, (
                    f"SRI-11: banned import {alias.name!r}"
                )
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] not in {"statistics", "numpy"}, (
                f"SRI-11: banned import-from {node.module!r}"
            )
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for operand in operands:
                assert not (
                    isinstance(operand, ast.Constant) and operand.value in {"higher", "lower"}
                ), "SRI-11: direction literal compared locally — MetricOrder is the only reader"


# ---------------------------------------------------------------------------
# Witness: no band-level scalar in outputs (coordinator hazard flag)
# ---------------------------------------------------------------------------


def test_outputs_carry_no_band_level_scalar(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Provenance JSON and stdout carry NO band-scoped scalar, ever.

    A StrictScore exists only at full 0..19 scope; per-band information is
    expressed only as per-FILE vector entries. Concretely: every numeric leaf
    in the emitted JSON lives under {strict_score, selected_strict_score,
    file_vector}; any JSON node carrying band identity (a ``target_band`` key
    or a band-vocabulary key/value) has ZERO numeric leaves beneath it; the
    marker's ``denoising_score`` never appears as a KEY or standalone token
    (the metric id ``tidmad_denoising_score`` legitimately CONTAINS the
    substring, so the checks are key-exact / word-bounded); and no stdout
    line pairs a band token with a float.

    Fails when: a per-unit or per-band numeric field (e.g. an echoed
    ``denoising_score``, a ``band_scores`` map, a "just for logging" band
    scalar) is added to the artifact or the summary lines.
    """
    root = _build_tree(tmp_path / "campaign")
    _write_unit_workspaces(root)
    spy = ComposerSpy(_uniform_scores())
    rc = main(
        ["--workspace_root", str(root), "--designs", ",".join(DESIGNS)],
        compose_and_score_fn=spy,
    )
    captured = capsys.readouterr()
    assert rc == 0
    out_path = root / "stage3" / "strict_best" / "strict_best_selection.json"
    raw_text = out_path.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    allowed_numeric_keys = {"strict_score", "selected_strict_score", "file_vector"}

    def numeric_entries(node: object, key: str) -> list[tuple[str, object]]:
        if isinstance(node, bool):
            return []
        if isinstance(node, (int, float)):
            return [(key, node)]
        if isinstance(node, dict):
            return [
                entry
                for child_key, child in node.items()
                for entry in numeric_entries(child, child_key)
            ]
        if isinstance(node, list):
            return [entry for child in node for entry in numeric_entries(child, key)]
        return []

    offending = [
        entry for entry in numeric_entries(data, "<root>") if entry[0] not in allowed_numeric_keys
    ]
    assert offending == [], f"band/unit-level numeric fields in provenance: {offending}"

    def band_subtrees(node: object) -> list[dict[str, object]]:
        found: list[dict[str, object]] = []
        if isinstance(node, dict):
            band_identity = (
                "target_band" in node
                or any(key in BANDS for key in node)
                or any(isinstance(value, str) and value in BANDS for value in node.values())
            )
            if band_identity:
                found.append(node)
            for value in node.values():
                found.extend(band_subtrees(value))
        elif isinstance(node, list):
            for value in node:
                found.extend(band_subtrees(value))
        return found

    subtrees = band_subtrees(data)
    assert subtrees, "fixture defect: no band-identity node found in provenance"
    for subtree in subtrees:
        assert numeric_entries(subtree, "<band-subtree>") == [], (
            f"numeric leaf under a band-scoped node: {subtree}"
        )

    def all_keys(node: object) -> set[str]:
        keys: set[str] = set()
        if isinstance(node, dict):
            for child_key, child in node.items():
                keys.add(child_key)
                keys.update(all_keys(child))
        elif isinstance(node, list):
            for child in node:
                keys.update(all_keys(child))
        return keys

    assert "denoising_score" not in all_keys(data)
    assert re.search(r'"denoising_score"\s*:', raw_text) is None
    standalone_marker_field = re.compile(r"(?<![A-Za-z0-9_])denoising_score(?![A-Za-z0-9_])")
    assert standalone_marker_field.search(captured.out + captured.err) is None
    for line in captured.out.splitlines():
        has_band_token = any(band in line for band in BANDS)
        assert not (has_band_token and _FLOAT_RE.search(line)), (
            f"stdout line pairs a band token with a scalar: {line!r}"
        )


# ---------------------------------------------------------------------------
# Witness: production boundary binds the sibling module by its contract path
# ---------------------------------------------------------------------------


def test_production_boundary_resolves_writer_c_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no injection, the composer resolves from scripts.stage3.stage3_common.

    A stub module is installed under the exact contract path; production must
    bind and call ITS compose_and_score (4 calls, one per design).

    Fails when: the importlib binding drifts from the agreed module path or
    attribute name, or a fallback scorer is substituted.
    """
    root = _build_tree(tmp_path / "campaign")
    _write_unit_workspaces(root)
    spy = ComposerSpy(_uniform_scores())
    stub = types.ModuleType("scripts.stage3.stage3_common")
    stub.compose_and_score = spy  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.stage3.stage3_common", stub)
    selection = finalize_strict_best(root, DESIGNS)
    assert isinstance(selection, StrictBestSelection)
    assert len(spy.calls) == 4
