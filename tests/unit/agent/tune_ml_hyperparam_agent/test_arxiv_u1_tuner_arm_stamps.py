"""arXiv U1 (#254) — the tuner stamps the arm label and never reads it.

What only these tests catch:

* ``TestEmitRecordSeam`` — the ONE validate-and-persist seam writes the arm
  key ONLY when the run is labelled. Fails when an unlabelled run starts
  writing ``experiment_arm: null`` (every legacy summary artifact changes)
  or when a labelled run stops stamping (its own records are refused at the
  next resume under the three-case rule).
* ``TestEveryEmissionSitePassesTheLabel`` — the ``candidate_id`` precedent:
  a record-construction site that reaches ``_emit_record`` without the
  label emits an unstamped record inside a labelled run. The census reads
  the whole node, so a site cannot hide by moving files.
* ``TestTheTunerNeverInterpretsTheIdentity`` — ruling R2, executable: the
  three pass-through names never appear inside a test expression anywhere
  in the node. A branch keyed on the arm label is the defect.
* ``TestReachabilityThroughTheRealRun`` — the bounded pseudo iteration
  drives the REAL ``run()``: a labelled input reaches every record, the
  output and the per-model lock; an unlabelled one leaves the summary
  entries and the lock without the key. A stamp that exists only in a
  helper nobody calls is what this fails on.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration
from tests.helpers.tuner_source import tuner_node_tree

# importlib because the package __init__ re-exports the main module's names
# and shadows the submodule name (the same quirk the Step-00 helper notes).
_records = importlib.import_module("nodes.ml_hyperparameter_tune_agent.records")

_PREFLIGHT_FIXTURE = Path(__file__).parent / "fixtures" / "step00_preflight_results.json"
IDENTITY_NAMES = ("experiment_arm", "lit_review_enabled", "lit_review_config_sha256")


class _Sandbox:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_record(self, record: dict) -> None:
        self.saved.append(dict(record))


def _record() -> dict:
    return {
        "exp_id": "m_r_001",
        "status": "skipped_oom_risk",
        "model_type": "m",
        "timestamp": "2026-08-24 00:00:00",
        "file_index": 6,
        "params": {},
    }


class TestEmitRecordSeam:
    def test_unlabelled_emits_no_key(self):
        sandbox = _Sandbox()
        _records._emit_record(sandbox, _record(), candidate_id=None)
        assert "experiment_arm" not in sandbox.saved[0]

    def test_labelled_stamps_the_label(self):
        sandbox = _Sandbox()
        _records._emit_record(
            sandbox, _record(), candidate_id=None, experiment_arm="with-prior-art"
        )
        assert sandbox.saved[0]["experiment_arm"] == "with-prior-art"


def _calls_named(tree: ast.Module, target: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name == target:
            out.append(node)
    return out


def _emit_calls(tree: ast.Module) -> list[ast.Call]:
    return _calls_named(tree, "_emit_record")


class TestEveryEmissionSitePassesTheLabel:
    """DECLARED DELTA (landed-source integration, 84d74280): the structural
    budget on ``run_inference_scoring_health`` forced the S1 identity kwargs
    into ONE extracted owner, ``execution._emit_attempt_record``. A compliant
    emission site is now EITHER a direct ``_emit_record`` call passing
    ``experiment_arm=`` explicitly OR a call to the helper (compliant by
    construction — its own two inner ``_emit_record`` calls are direct sites
    this census still checks). HOW THIS FAILS WHEN THE BEHAVIOUR BREAKS:
    drop ``experiment_arm=`` from either helper branch and the per-call check
    goes RED on that inner line; bypass the helper with a bare
    ``_emit_record(sandbox, rec, candidate_id=...)`` anywhere and the same
    check names the new line; delete emission sites and the floor fires."""

    def test_every_emit_record_call_passes_experiment_arm(self):
        tree = tuner_node_tree()
        direct = _emit_calls(tree)
        helper_sites = _calls_named(tree, "_emit_attempt_record")
        # Pre-extraction the node had >= 10 direct sites; six execution.py
        # sites collapsed into the helper (two inner direct calls + six
        # helper call sites = the same emission surface, counted both ways).
        assert len(direct) + len(helper_sites) >= 12, "the node lost emission sites"
        assert len(helper_sites) >= 6, (
            "execution.py's attempt emissions must route through "
            "_emit_attempt_record — a direct call there re-inlines the "
            "identity threading the budget extraction removed"
        )
        missing = [c.lineno for c in direct if "experiment_arm" not in {k.arg for k in c.keywords}]
        assert not missing, f"_emit_record calls without experiment_arm= at lines {missing}"

    def test_the_two_forwarding_helpers_are_handed_the_label(self):
        """`_handle_admission_refusal` / `_handle_in_subprocess_rejection`
        emit on the caller's behalf; a caller that drops the label there
        produces an unstamped admission/rejection record."""
        tree = tuner_node_tree()
        forwarded = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None)
            in {"_handle_admission_refusal", "_handle_in_subprocess_rejection"}
        ]
        assert len(forwarded) >= 3
        missing = [
            c.lineno for c in forwarded if "experiment_arm" not in {k.arg for k in c.keywords}
        ]
        assert not missing, f"helper calls without experiment_arm= at lines {missing}"


def _is_presence_check(node: ast.AST) -> bool:
    """``x is None`` / ``x is not None`` — the omission idiom, not a reading
    of the label's VALUE."""
    return (
        isinstance(node, ast.Compare)
        and all(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops)
        and all(isinstance(c, ast.Constant) and c.value is None for c in node.comparators)
    )


def _mentions_identity(node: ast.AST) -> bool:
    """Does this TEST expression read one of the identity names?

    A call's arguments are transport (``helper(experiment_arm=...)``), so
    only the callee is inspected; a bare presence check is the omission
    idiom. Everything else — equality, membership, truthiness, a method on
    the label — is an interpretation and is reported.
    """
    if isinstance(node, ast.Call):
        return _mentions_identity(node.func)
    if _is_presence_check(node):
        return False
    if isinstance(node, ast.Attribute) and node.attr in IDENTITY_NAMES:
        return True
    if isinstance(node, ast.Name) and node.id in IDENTITY_NAMES:
        return True
    return any(_mentions_identity(child) for child in ast.iter_child_nodes(node))


class TestTheTunerNeverInterpretsTheIdentity:
    def test_no_test_expression_in_the_node_reads_the_identity(self):
        tree = tuner_node_tree()
        offenders: list[str] = []
        for node in ast.walk(tree):
            tests: list[ast.AST] = []
            if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
                tests.append(node.test)
            elif isinstance(node, (ast.Compare, ast.BoolOp)):
                tests.append(node)
            elif isinstance(node, ast.Match):
                tests.append(node.subject)
            for t in tests:
                if _mentions_identity(t):
                    offenders.append(f"line {node.lineno}: {ast.dump(t)[:80]}")
        assert not offenders, "the tuner keyed behaviour on a pass-through identity:\n" + "\n".join(
            offenders
        )


class TestReachabilityThroughTheRealRun:
    @pytest.fixture(scope="class")
    def runs(self, tmp_path_factory):
        from _pytest.monkeypatch import MonkeyPatch

        preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
        out = {}
        for label in ("with-prior-art", None):
            mp = MonkeyPatch()
            tmp = tmp_path_factory.mktemp("u1_arm")
            try:
                output, _bridge, _sandbox, workspace = run_bounded_pseudo_iteration(
                    tmp,
                    mp,
                    preflight_results=list(preflight),
                    input_overrides={"experiment_arm": label} if label else None,
                )
            finally:
                mp.undo()
            out[label] = (output, Path(workspace))
        return out

    def test_a_labelled_run_stamps_every_record_the_output_and_its_lock(self, runs):
        output, workspace = runs["with-prior-art"]
        assert output.all_records, "the bounded run produced no records"
        assert all(r.experiment_arm == "with-prior-art" for r in output.all_records)
        assert output.experiment_arm == "with-prior-art"
        summary = json.loads((workspace / "summary_step00_pseudo.json").read_text())
        assert summary and all(e["experiment_arm"] == "with-prior-art" for e in summary)
        lock = json.loads((workspace / "run_invariants_lock.json").read_text())
        assert lock["experiment_arm"] == "with-prior-art"

    def test_an_unlabelled_run_writes_no_key_anywhere_on_disk(self, runs):
        output, workspace = runs[None]
        assert output.experiment_arm is None
        summary = json.loads((workspace / "summary_step00_pseudo.json").read_text())
        assert summary and all("experiment_arm" not in e for e in summary)
        lock = json.loads((workspace / "run_invariants_lock.json").read_text())
        for name in IDENTITY_NAMES:
            assert name not in lock, name


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
