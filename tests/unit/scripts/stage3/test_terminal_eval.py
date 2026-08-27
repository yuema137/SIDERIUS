"""Witnesses for the Stage-3 terminal 100% re-evaluation writer.

Stage artifact contract (PR #329) §3 terminal_eval + §4 shared wrapper.
Every test names the defect only it can catch and how it fails when the
behaviour breaks. The shared ``compose_and_score`` (writer-owned in a
parallel PR, ``scripts/stage3/stage3_common.py``) is STUBBED with the
contract §4 frozen signature — these are unit tests; no scoring runs.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import scripts.stage3.stage3_terminal_eval as te
from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.evaluation_metric import derive_tidmad_metric_spec
from scripts.stage3.stage3_terminal_eval import (
    ARTIFACT_NAMESPACE_KEY,
    CENSUS_ALLOWED_PRODUCTION_REFERENCES,
    SEARCH_SIDE_CONSUMERS,
    TERMINAL_NAMESPACE_MARKER,
    TERMINAL_NAMESPACE_SEGMENTS,
    ChampionIdentity,
    InvalidChampionError,
    ReadClosureViolationError,
    SearchSideConsumer,
    TerminalChampion,
    TerminalEvalError,
    TerminalNamespaceViolationError,
    TerminalOutputLayout,
    VacuousReadClosureError,
    assert_terminal_read_closure,
    audit_terminal_read_closure,
    census_terminal_namespace_references,
    run_terminal_eval,
    terminal_namespace,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

#: Contract §3 consumer enumeration — hardcoded here (never read back from
#: the module under test) so the pin below fails on ANY enumeration edit.
_EXPECTED_CONSUMER_ENUMERATION = {
    "stage1_band_chain_workspaces": (
        "*_band0-3",
        "*_band4-9",
        "*_band10-14",
        "*_band15-19",
    ),
    "stage2_retrain_units": ("stage2/*",),
    "stage3_composed_best_pool": ("stage3/composed_best",),
    "stage3_strict_best_pool": ("stage3/strict_best",),
}

_BAND_LABELS = ("0-3", "4-9", "10-14", "15-19")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _valid_record(exp_id: str = "exp_champ", score: float = 6.1) -> dict[str, Any]:
    """A record the REAL eligibility authority classifies VALID.

    ``health_gate_enabled=False`` is the authority's own DS5 declared
    disabled-mode waiver — the hermetic VALID path that does not depend on
    the shipped gate roster.
    """
    return {
        "status": "success",
        "denoising_score": score,
        "health_gate_enabled": False,
        "exp_id": exp_id,
    }


def _identity() -> ChampionIdentity:
    return ChampionIdentity(
        exp_id="exp_champ", model_type="wavenet", iteration=3, experiment_arm="goldA"
    )


def _make_campaign_workspace(tmp_path: Path) -> Path:
    """A workspace where EVERY contract-enumerated consumer resolves >=1 root."""
    ws = tmp_path / "ws"
    for arm_band in ("goldA_band0-3", "goldB_band15-19"):
        (ws / arm_band / "iter_001").mkdir(parents=True)
        (ws / arm_band / "iter_001" / "record.json").write_text('{"status": "success"}')
    (ws / "stage2" / "wavenetA_0-3" / "deliverables").mkdir(parents=True)
    (ws / "stage2" / "wavenetA_0-3" / "workspace").mkdir(parents=True)
    (ws / "stage3" / "composed_best").mkdir(parents=True)
    (ws / "stage3" / "strict_best").mkdir(parents=True)
    return ws


def _make_deliverables(root: Path, count: int = 20) -> Path:
    deliv = root / "goldA_band0-3" / "iter_001" / "deliv"
    deliv.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (deliv / f"denoised_file{index:04d}.h5").write_bytes(b"h5-payload-%d" % index)
    return deliv


def _make_anchor(tmp_path: Path) -> Path:
    anchor = tmp_path / "segment_anchors.json"
    anchor.write_text(json.dumps({"s_max": 1.0, "anchors": {}}))
    return anchor


class _ComposeStub:
    """Contract §4 FROZEN-signature stub for the shared wrapper."""

    def __init__(self, vector: list[float] | None = None, scalar: float = 6.234) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        #: The reconciled spec each call TRANSPORTED (§4 amendment) — recorded
        #: separately because it is required identity transport, not a
        #: scope override.
        self.specs: list[Any] = []
        self.vector = vector if vector is not None else [round(0.1 * i, 3) for i in range(20)]
        self.scalar = scalar

    def __call__(
        self,
        deliverable_dirs: list[str],
        *,
        files: range = range(20),
        sample_set: None = None,
        reconciled_spec: Any = None,
    ) -> tuple[list[float], float]:
        kwargs: dict[str, Any] = {}
        if files != range(20):
            kwargs["files"] = files
        if sample_set is not None:
            kwargs["sample_set"] = sample_set
        self.specs.append(reconciled_spec)
        self.calls.append((deliverable_dirs, kwargs))
        return list(self.vector), self.scalar


#: The champion's stamped 09a spec (tests play the STAMPING side; production
#: champions carry the winner's reconciled persisted stamp).
CHAMPION_SPEC = derive_tidmad_metric_spec(resolve_dataset_profile())


def _champion(
    deliv: Path,
    records: list[dict[str, Any]] | None = None,
    provenance_workspace: Path | None = None,
) -> TerminalChampion:
    return TerminalChampion(
        identity=_identity(),
        deliverable_dirs=[str(deliv)],
        provenance_records=[_valid_record()] if records is None else records,
        metric_spec=CHAMPION_SPEC,
        # The band workspace the deliverables came from — the run whose pinned
        # effective HealthGate config governs the provenance records (F-4).
        provenance_workspace=(
            deliv.parents[1] if provenance_workspace is None else provenance_workspace
        ),
    )


def _walk_paths(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def _band_scalar_fields(payload: Any, path: str = "$") -> list[str]:
    """Independent (test-side) detector of band-level scalar fields, so the
    artifact assertion does not certify the production guard with itself."""
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if isinstance(key, str) and (key in _BAND_LABELS or "band" in key.lower()):
                if isinstance(value, int | float) and not isinstance(value, bool):
                    found.append(child)
                elif isinstance(value, list | tuple) and any(
                    isinstance(item, int | float) and not isinstance(item, bool) for item in value
                ):
                    found.append(child)
            found.extend(_band_scalar_fields(value, child))
    elif isinstance(payload, list | tuple):
        for index, item in enumerate(payload):
            found.extend(_band_scalar_fields(item, f"{path}[{index}]"))
    return found


# ---------------------------------------------------------------------------
# Happy path: terminal namespace only, full scope, faithful provenance
# ---------------------------------------------------------------------------


def test_happy_path_writes_only_terminal_namespace_full_scope(tmp_path: Path) -> None:
    """Defect: terminal eval writing outside its namespace, narrowing scope,
    or scoring more than once. Fails when: any file outside terminal_eval/
    changes, the wrapper is called with files/sample_set overrides or
    called twice, or the artifacts land off the contract layout."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    anchor = _make_anchor(tmp_path)
    stub = _ComposeStub()
    before = _walk_paths(ws)

    result = run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=stub,
        anchor_map_path=anchor,
        repo_sha="testsha123",
    )

    ns = terminal_namespace(ws)
    # Exactly one full-scope call, deliverable dirs positional, no overrides.
    assert stub.calls == [([str(deliv)], {})]
    # Contract layout, pinned.
    assert result.champion_input_path == ns / "input" / "champion.json"
    assert result.score_path == ns / "results" / "terminal_score.json"
    assert result.provenance_path == ns / "results" / "terminal_provenance.json"
    for path in (result.champion_input_path, result.score_path, result.provenance_path):
        assert path.is_file()
    # NO writes anywhere else: everything outside the namespace is unchanged.
    after_outside = {p for p in _walk_paths(ws) if not (ws / p).resolve().is_relative_to(ns)}
    assert after_outside == before
    # Score artifact: full-scope declaration + the wrapper's own 2-tuple.
    score = json.loads(result.score_path.read_text())
    assert score["scope"] == "100%"
    assert score["denoising_score"] == 6.234
    assert score["file_vector"] == [round(0.1 * i, 3) for i in range(20)]
    assert score[ARTIFACT_NAMESPACE_KEY] == TERMINAL_NAMESPACE_MARKER
    assert score["champion"]["exp_id"] == "exp_champ"


def test_provenance_records_hashes_anchor_sha_and_scope(tmp_path: Path) -> None:
    """Defect: terminal provenance not identifying WHAT was measured — wrong
    deliverable hashes, wrong anchor sha, or a missing 100% scope
    declaration. Fails when: any recorded hash differs from an
    independently computed sha256, or the anchor/scope/repo_sha fields
    drift."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    anchor = _make_anchor(tmp_path)

    result = run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=_ComposeStub(),
        anchor_map_path=anchor,
        repo_sha="testsha123",
    )

    prov = json.loads(result.provenance_path.read_text())
    assert prov["scope"] == "100%"
    assert prov["repo_sha"] == "testsha123"
    assert prov["anchor_map"]["sha256"] == hashlib.sha256(anchor.read_bytes()).hexdigest()
    hashes = prov["deliverable_hashes"][str(deliv)]
    assert len(hashes) == 20
    for index in range(20):
        expected = hashlib.sha256(b"h5-payload-%d" % index).hexdigest()
        assert hashes[f"denoised_file{index:04d}.h5"] == expected
    assert prov["champion"] == {
        "exp_id": "exp_champ",
        "model_type": "wavenet",
        "iteration": 3,
        "experiment_arm": "goldA",
    }


def test_partial_file_vector_refused(tmp_path: Path) -> None:
    """Defect: a partial-scope wrapper result silently persisted under the
    '100%' scope declaration. Fails when: a 19-entry vector is accepted."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    stub = _ComposeStub(vector=[0.1] * 19)
    with pytest.raises(TerminalEvalError, match="full-scope"):
        run_terminal_eval(
            _champion(deliv),
            ws,
            compose_and_score_fn=stub,
            anchor_map_path=_make_anchor(tmp_path),
            repo_sha="x",
        )
    assert not terminal_namespace(ws).exists()


# ---------------------------------------------------------------------------
# W1 — invalid champion refused by name, BEFORE compute and BEFORE write
# ---------------------------------------------------------------------------


def test_invalid_champion_refused_by_name_before_any_effect(tmp_path: Path) -> None:
    """The operator's negative control. Defect: a champion without
    HealthGate-valid provenance terminal-evaluated as a success. Fails
    when: a failed-status record slips through, the wrapper is invoked, or
    anything is written before the refusal."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    stub = _ComposeStub()
    bad = _valid_record() | {"status": "failed"}
    with pytest.raises(InvalidChampionError) as excinfo:
        run_terminal_eval(
            _champion(deliv, records=[bad]),
            ws,
            compose_and_score_fn=stub,
            anchor_map_path=_make_anchor(tmp_path),
            repo_sha="x",
        )
    # Refused BY NAME: the champion is identified in the refusal.
    assert "exp_champ" in str(excinfo.value)
    assert stub.calls == []
    assert not terminal_namespace(ws).exists()


def test_a_champion_failing_its_RUNS_OWN_blocking_gate_is_refused(tmp_path: Path) -> None:
    """F-4 — the gate set comes from the champion's OWN pinned config.

    The record below carries every gate the REPO-CURRENT shipped roster asks
    for, all passing, PLUS the run's own declared blocking gate, failed. Asked
    against the repo-current roster — which is what the zero-argument
    ``is_valid_candidate(record)`` default resolves, collapsing UNKNOWN to the
    empty set on the way — it is VALID and the champion is terminal-evaluated
    as a success. Asked against the roster its own workspace PINNED, it is
    INVALID.

    Fails as: no refusal at all, i.e. a champion measured on a run whose own
    blocking gate said no. That boolean is the same one Stage-2 records as
    ``healthgate_valid`` and Strict Best's negative control trusts.
    """
    from execute_tools.health_checks.candidate_eligibility import (
        pinned_workspace_gate_ids,
        required_blocking_gate_ids,
    )
    from tests.helpers.health_task_config import write_pinned_effective_config

    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    band_ws = deliv.parents[1]

    write_pinned_effective_config(band_ws, ["witness_run_declared_blocking"])
    run_declared = pinned_workspace_gate_ids(band_ws) or frozenset()
    repo_current = required_blocking_gate_ids()
    # Vacuity guards: both rosters non-empty and DISJOINT, or a champion
    # satisfying one would satisfy the other and this proves nothing.
    assert run_declared, "the run's pinned roster is empty — the witness is vacuous"
    assert repo_current, "shipped blocking-gate roster unexpectedly empty"
    assert not (run_declared & repo_current), "the two rosters must not overlap"

    def _gate(name: str, passed: bool) -> dict[str, Any]:
        return {"gate_name": name, "execution_status": "passed", "check_passed": passed}

    record = {
        "status": "success",
        "denoising_score": 9.99,
        "exp_id": "exp_champ",
        "health_gate_results": [
            *(_gate(gate_id, True) for gate_id in sorted(repo_current)),
            *(_gate(gate_id, False) for gate_id in sorted(run_declared)),
        ],
    }

    stub = _ComposeStub()
    with pytest.raises(InvalidChampionError, match="exp_champ"):
        run_terminal_eval(
            _champion(deliv, records=[record]),
            ws,
            compose_and_score_fn=stub,
            anchor_map_path=_make_anchor(tmp_path),
            repo_sha="x",
        )
    assert stub.calls == [], "an invalid champion must never reach the composer"
    assert not terminal_namespace(ws).exists()


def test_a_champion_passing_its_RUNS_OWN_blocking_gate_is_measured(tmp_path: Path) -> None:
    """The same wiring from the other side, so the refusal above is not
    merely "everything is refused now".

    This record carries ONLY the run's own declared gate, passing, and NONE of
    the repo-current ones. Under the repo-current roster it is UNKNOWN and
    would be refused; under its own run's roster it is VALID and measured.
    """
    from tests.helpers.health_task_config import write_pinned_effective_config

    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    write_pinned_effective_config(deliv.parents[1], ["witness_run_declared_blocking"])

    record = {
        "status": "success",
        "denoising_score": 6.1,
        "exp_id": "exp_champ",
        "health_gate_results": [
            {
                "gate_name": "witness_run_declared_blocking",
                "execution_status": "passed",
                "check_passed": True,
            }
        ],
    }

    stub = _ComposeStub()
    result = run_terminal_eval(
        _champion(deliv, records=[record]),
        ws,
        compose_and_score_fn=stub,
        anchor_map_path=_make_anchor(tmp_path),
        repo_sha="x",
    )
    assert len(stub.calls) == 1
    assert len(result.file_vector) == 20


def test_numerically_excellent_champion_without_gate_evidence_refused(tmp_path: Path) -> None:
    """The exact hazard the semantics freeze names: numerically excellent
    but not HealthGate-valid. A success record with a huge score and NO
    gate results is UNKNOWN to the ONE eligibility authority — refused,
    never measured. Fails when: the eligibility wiring is bypassed or
    replaced by a score/status check.

    Under F-4 it is also the UNKNOWN-policy case: this workspace pinned no
    effective config, so the run's roster cannot be established, and an
    unestablished roster is a refusal rather than a pass."""
    from execute_tools.health_checks.candidate_eligibility import required_blocking_gate_ids

    # Precondition (keeps this witness non-vacuous): the shipped config
    # declares at least one blocking gate, so gate-less records are UNKNOWN.
    assert required_blocking_gate_ids(), "shipped blocking-gate roster unexpectedly empty"

    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    stub = _ComposeStub()
    excellent_invalid = {"status": "success", "denoising_score": 9.99, "exp_id": "exp_champ"}
    with pytest.raises(InvalidChampionError, match="exp_champ"):
        run_terminal_eval(
            _champion(deliv, records=[excellent_invalid]),
            ws,
            compose_and_score_fn=stub,
            anchor_map_path=_make_anchor(tmp_path),
            repo_sha="x",
        )
    assert stub.calls == []
    assert not terminal_namespace(ws).exists()


def test_champion_with_no_provenance_records_refused(tmp_path: Path) -> None:
    """Defect: absence of provenance treated as absence of a problem. Fails
    when: an empty provenance list reaches scoring."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    with pytest.raises(InvalidChampionError, match="NO provenance"):
        run_terminal_eval(
            _champion(deliv, records=[]),
            ws,
            compose_and_score_fn=_ComposeStub(),
            anchor_map_path=_make_anchor(tmp_path),
            repo_sha="x",
        )


# ---------------------------------------------------------------------------
# W2 — out-of-namespace output refused at construction
# ---------------------------------------------------------------------------


def test_output_path_outside_namespace_refused_at_construction(tmp_path: Path) -> None:
    """Defect: terminal outputs relocated into search-readable space. Fails
    when: a layout whose results_dir is outside stage3/terminal_eval/ can
    be constructed at all (the refusal must precede every side effect)."""
    ws = _make_campaign_workspace(tmp_path)
    outside = tmp_path / "elsewhere"
    with pytest.raises(TerminalNamespaceViolationError, match="outside the terminal namespace"):
        TerminalOutputLayout(workspace_root=ws, results_dir=outside)
    assert not outside.exists()
    assert not terminal_namespace(ws).exists()


def test_traversal_escape_refused_at_construction(tmp_path: Path) -> None:
    """Defect: a '..' traversal smuggling terminal output into a sibling
    search namespace. Fails when: the resolved path is not what is
    checked."""
    ws = _make_campaign_workspace(tmp_path)
    sneaky = terminal_namespace(ws) / ".." / "composed_best"
    with pytest.raises(TerminalNamespaceViolationError):
        TerminalOutputLayout(workspace_root=ws, input_dir=sneaky)


def test_write_helper_defends_namespace_even_with_valid_layout(tmp_path: Path) -> None:
    """Defect: a direct write-path bypass of the layout check. Fails when:
    _write_terminal_json accepts a path outside the namespace."""
    ws = _make_campaign_workspace(tmp_path)
    layout = TerminalOutputLayout(workspace_root=ws)
    target = ws / "stage3" / "composed_best" / "leak.json"
    with pytest.raises(TerminalNamespaceViolationError):
        te._write_terminal_json(layout, target, {"k": "v"})
    assert not target.exists()


# ---------------------------------------------------------------------------
# W3 — the mutation-capable read-closure guard (contract §3 isolation)
# ---------------------------------------------------------------------------


def test_read_closure_green_and_nonvacuous_on_clean_workspace(tmp_path: Path) -> None:
    """SRI-9 positive control. Defect: a guard that passes because it
    scanned nothing. Fails when: any contract-enumerated consumer resolves
    zero roots in a fully populated campaign workspace, when nothing was
    scanned, or when a clean workspace reports violations."""
    ws = _make_campaign_workspace(tmp_path)
    report = assert_terminal_read_closure(ws)
    # Every one of the four contract consumers resolved at least one root.
    assert set(report.roots_by_consumer) == set(_EXPECTED_CONSUMER_ENUMERATION)
    for name, roots in report.roots_by_consumer.items():
        assert roots, f"consumer {name} resolved no input root — guard would be vacuous"
    assert len(report.roots_by_consumer["stage1_band_chain_workspaces"]) == 2
    assert report.entries_scanned > 0
    assert report.violations == ()


def test_read_closure_red_on_planted_terminal_artifact(tmp_path: Path) -> None:
    """THE plant — the guard's own negative control. A REAL terminal
    artifact (produced by the production writer, so it carries the real
    self-declaration) is copied into a search-consumable root; the guard
    must turn RED. Fails when: a terminal artifact can sit inside a
    Stage-2 deliverables dir without the guard naming it."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    result = run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=_ComposeStub(),
        anchor_map_path=_make_anchor(tmp_path),
        repo_sha="x",
    )
    plant = ws / "stage2" / "wavenetA_0-3" / "deliverables" / "innocent_looking.json"
    shutil.copy(result.provenance_path, plant)

    with pytest.raises(ReadClosureViolationError, match="terminal_artifact_inside"):
        assert_terminal_read_closure(ws)
    report = audit_terminal_read_closure(ws)
    planted = [
        v for v in report.violations if v.kind == "terminal_artifact_inside_search_consumable_root"
    ]
    assert [v.path for v in planted] == [plant]
    assert planted[0].consumer == "stage2_retrain_units"

    # Control of the control: remove the plant and the SAME guard is green
    # again, so the RED verdict came from the plant and nothing else.
    plant.unlink()
    assert audit_terminal_read_closure(ws).violations == ()


def test_read_closure_red_on_symlink_resolving_into_namespace(tmp_path: Path) -> None:
    """Defect: a symlink inside a search root laundering terminal content
    (realpath escape). Fails when: resolution-based containment is not
    checked for consumable entries."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    result = run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=_ComposeStub(),
        anchor_map_path=_make_anchor(tmp_path),
        repo_sha="x",
    )
    link = ws / "goldA_band0-3" / "iter_001" / "leak.json"
    link.symlink_to(result.score_path)

    report = audit_terminal_read_closure(ws)
    kinds = {(v.kind, v.path) for v in report.violations}
    assert ("consumable_path_resolves_into_terminal_namespace", link) in kinds


def test_read_closure_red_when_terminal_root_enters_an_enumeration(tmp_path: Path) -> None:
    """The second required mutation: ADDING the terminal root to a
    consumer's enumeration must turn the guard RED — in both directions
    (a consumer root inside terminal_eval/, and a root that CONTAINS it).
    Fails when: the disjointness check misses either containment
    direction."""
    ws = _make_campaign_workspace(tmp_path)
    terminal_namespace(ws).mkdir(parents=True)

    rogue_inside = SearchSideConsumer(
        name="rogue_terminal_reader",
        input_root_globs=("stage3/terminal_eval",),
        contract_clause="test mutation: enumeration gained the terminal root",
    )
    report = audit_terminal_read_closure(ws, consumers=(*SEARCH_SIDE_CONSUMERS, rogue_inside))
    assert any(
        v.kind == "enumerated_root_overlaps_terminal_namespace"
        and v.consumer == "rogue_terminal_reader"
        for v in report.violations
    )
    with pytest.raises(ReadClosureViolationError):
        assert_terminal_read_closure(ws, consumers=(*SEARCH_SIDE_CONSUMERS, rogue_inside))

    rogue_parent = SearchSideConsumer(
        name="rogue_parent_reader",
        input_root_globs=("stage3",),
        contract_clause="test mutation: enumeration gained a PARENT of the terminal root",
    )
    report = audit_terminal_read_closure(ws, consumers=(rogue_parent,))
    assert any(
        v.kind == "enumerated_root_overlaps_terminal_namespace"
        and v.consumer == "rogue_parent_reader"
        for v in report.violations
    )


def test_read_closure_refuses_vacuity(tmp_path: Path) -> None:
    """SRI-9. Defect: an isolation 'proof' over nothing. Fails when: an
    empty consumer enumeration, or a workspace where no root resolves,
    yields a green verdict instead of a named refusal."""
    ws = _make_campaign_workspace(tmp_path)
    with pytest.raises(VacuousReadClosureError, match="EMPTY"):
        audit_terminal_read_closure(ws, consumers=())
    empty_ws = tmp_path / "empty_ws"
    empty_ws.mkdir()
    with pytest.raises(VacuousReadClosureError, match="scanned nothing"):
        assert_terminal_read_closure(empty_ws)


# ---------------------------------------------------------------------------
# SRI-11 — pins: the enumeration, the namespace, the single owner
# ---------------------------------------------------------------------------


def test_search_side_enumeration_pinned_to_contract() -> None:
    """SRI-11 pin, half 1. Defect: someone adds a consumer of the terminal
    artifacts to the search side (or moves the namespace) by editing the
    executable enumeration without a contract change. Fails when: the
    enumeration, the namespace segments, the marker, the scope
    declaration, or the census allowlist differ from the contract values
    hardcoded here."""
    actual = {c.name: c.input_root_globs for c in SEARCH_SIDE_CONSUMERS}
    assert actual == _EXPECTED_CONSUMER_ENUMERATION
    assert TERMINAL_NAMESPACE_SEGMENTS == ("stage3", "terminal_eval")
    assert TERMINAL_NAMESPACE_MARKER == "stage3/terminal_eval"
    assert te.TERMINAL_SCOPE_DECLARATION == "100%"
    assert te.TERMINAL_FILE_COUNT == 20
    assert CENSUS_ALLOWED_PRODUCTION_REFERENCES == frozenset(
        {"scripts/stage3/stage3_terminal_eval.py"}
    )


def test_census_no_production_reference_outside_owner() -> None:
    """SRI-11 pin, half 2. Defect: production code outside the terminal
    writer referencing the reserved namespace name (the contract reserves
    the directory name; a new consumer is a contract change first). Fails
    when: any tracked production .py outside the allowlist mentions
    terminal_eval — including a future stage3_common/composed_best/
    strict_best reaching for it."""
    offenders = census_terminal_namespace_references(REPO_ROOT)
    assert offenders == ()
    # Allowlist rot control: the single allowed owner exists and really does
    # reference the reserved name (else the allowlist is masking nothing).
    owner = REPO_ROOT / "scripts" / "stage3" / "stage3_terminal_eval.py"
    assert owner.is_file()
    assert "terminal_eval" in owner.read_text(encoding="utf-8")


def test_census_is_mutation_capable_and_nonvacuous(tmp_path: Path) -> None:
    """Census negative + positive controls (census-blindness hygiene).
    Defect: a census green for the wrong reason. Fails when: a planted
    reference in the scanned file set is not reported, a clean file is
    reported, or an empty file set passes instead of refusing."""
    offender = tmp_path / "rogue_consumer.py"
    offender.write_text('ROOT = "stage3/terminal_eval"\n')
    clean = tmp_path / "clean_module.py"
    clean.write_text("VALUE = 1\n")

    reported = census_terminal_namespace_references(tmp_path, file_set=[offender, clean])
    assert reported == ("rogue_consumer.py",)
    with pytest.raises(VacuousReadClosureError, match="EMPTY"):
        census_terminal_namespace_references(tmp_path, file_set=[])


# ---------------------------------------------------------------------------
# Band-scalar addendum (campaign-lane hazard flag, 2026-08-26)
# ---------------------------------------------------------------------------


def test_terminal_artifacts_contain_no_band_level_scalar_field(tmp_path: Path) -> None:
    """Defect: a per-band scalar leaking into the terminal artifact set —
    the terminal score exists only at full 0..19 scope, and per-band
    information may appear only as per-FILE vector entries. Checked with a
    TEST-SIDE detector (never the production guard judging itself). Fails
    when: any emitted artifact carries a band-shaped key with a numeric
    (or numeric-sequence) value."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    result = run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=_ComposeStub(),
        anchor_map_path=_make_anchor(tmp_path),
        repo_sha="x",
    )
    for path in (result.champion_input_path, result.score_path, result.provenance_path):
        payload = json.loads(path.read_text())
        assert _band_scalar_fields(payload) == [], f"band-level scalar in {path.name}"


def test_band_scalar_emission_refused_at_write(tmp_path: Path) -> None:
    """Defect: the writer emitting a band-level scalar field. Fails when: a
    band-labelled or band-named key with a numeric value (or a numeric
    sequence — a per-band vector is aggregation too) reaches disk, or when
    legitimate band tokens in string VALUES / hash-keyed filenames are
    refused (false positive breaking real provenance)."""
    ws = _make_campaign_workspace(tmp_path)
    layout = TerminalOutputLayout(workspace_root=ws)
    target = layout.namespace / "results" / "probe.json"

    for bad in (
        {"per_band_scores": {"0-3": 1.2}},
        {"0-3": 6.1},
        {"band_means": [1.0, 2.0, 3.0, 4.0]},
    ):
        with pytest.raises(te.BandScalarEmissionError):
            te._write_terminal_json(layout, target, bad)
        assert not target.exists()

    # Band tokens in VALUES and in hash-map KEYS with string values are
    # provenance, not scalars — they must pass.
    benign = {
        "deliverable_dirs": ["/ws/goldA_band0-3/iter_001/deliv"],
        "deliverable_hashes": {"abra_denoised_wavenet_goldA_band0-3_file0000.h5": "deadbeef"},
    }
    te._write_terminal_json(layout, target, benign)
    assert json.loads(target.read_text()) == benign


def test_band_guard_reached_on_every_production_write(tmp_path: Path, monkeypatch: Any) -> None:
    """Reachability evidence. Defect: an artifact write path that bypasses
    the band-scalar guard (the guard exists but production never calls
    it). Fails when: fewer than the three terminal artifacts pass through
    _refuse_band_scalars during a production run."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    seen: list[str] = []
    original = te._refuse_band_scalars

    def spy(payload: Any, *, artifact: str, key_path: str = "$") -> None:
        if key_path == "$":
            seen.append(artifact)
        original(payload, artifact=artifact, key_path=key_path)

    monkeypatch.setattr(te, "_refuse_band_scalars", spy)
    run_terminal_eval(
        _champion(deliv),
        ws,
        compose_and_score_fn=_ComposeStub(),
        anchor_map_path=_make_anchor(tmp_path),
        repo_sha="x",
    )
    assert sorted(seen) == [
        "champion.json",
        "terminal_provenance.json",
        "terminal_score.json",
    ]


# ---------------------------------------------------------------------------
# The shared-wrapper seam (contract §4) and the CLI's refusal honesty
# ---------------------------------------------------------------------------


def test_compose_and_score_resolved_from_agreed_module(monkeypatch: Any) -> None:
    """Defect: the terminal writer importing the shared wrapper from the
    wrong seam (the cross-writer agreement is scripts/stage3/
    stage3_common.py), or degrading its absence into something other than
    a named refusal. Fails when: resolution ignores the agreed module
    name, or a missing module / missing attribute is not refused by
    name."""
    fake = types.ModuleType("scripts.stage3.stage3_common")

    def fake_compose(
        deliverable_dirs: list[str],
        *,
        files: range = range(20),
        sample_set: None = None,
    ) -> tuple[list[float], float]:
        return [0.0] * 20, 0.0

    fake.compose_and_score = fake_compose  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.stage3.stage3_common", fake)
    assert te._resolve_compose_and_score() is fake_compose

    bare = types.ModuleType("scripts.stage3.stage3_common")
    monkeypatch.setitem(sys.modules, "scripts.stage3.stage3_common", bare)
    with pytest.raises(te.ComposeAndScoreUnavailableError, match="compose_and_score"):
        te._resolve_compose_and_score()

    def boom(name: str) -> Any:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(te, "importlib", types.SimpleNamespace(import_module=boom))
    with pytest.raises(te.ComposeAndScoreUnavailableError, match="stage3_common"):
        te._resolve_compose_and_score()


def test_cli_refusal_exits_nonzero_naming_reason(tmp_path: Path, capsys: Any) -> None:
    """Defect: the CLI swallowing a refusal into exit 0, making an invalid
    champion look operationally like a successful terminal measurement.
    Fails when: an invalid champion yields exit 0 or an unnamed error."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    champion = _champion(deliv, records=[_valid_record() | {"status": "failed"}])
    champion_json = tmp_path / "champion.json"
    champion_json.write_text(champion.model_dump_json())

    rc = te.main(["--champion_json", str(champion_json), "--workspace_root", str(ws)])
    captured = capsys.readouterr()
    assert rc == 2
    assert "REFUSED" in captured.err
    assert "exp_champ" in captured.err
    assert not terminal_namespace(ws).exists()


def test_cli_happy_path_reports_full_scope(tmp_path: Path, capsys: Any, monkeypatch: Any) -> None:
    """Defect: the CLI wiring dropping the terminal semantics (wrong module
    seam, or reporting something other than the full-scope scalar). Fails
    when: exit != 0, or the report omits the 100% scope."""
    ws = _make_campaign_workspace(tmp_path)
    deliv = _make_deliverables(ws)
    fake = types.ModuleType("scripts.stage3.stage3_common")
    fake.compose_and_score = _ComposeStub()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "scripts.stage3.stage3_common", fake)
    champion_json = tmp_path / "champion.json"
    champion_json.write_text(_champion(deliv).model_dump_json())

    rc = te.main(["--champion_json", str(champion_json), "--workspace_root", str(ws)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "scope 100%" in captured.out
    assert "6.234" in captured.out
    assert (terminal_namespace(ws) / "results" / "terminal_score.json").is_file()
