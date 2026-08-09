"""V21 PR F — F1: the frozen methodology, proved before any real number.

Fixture models are tiny and CPU-only; the real populations are F2's
business. Harness measurement functions are driven with model objects
directly (their real signatures), and the AST tests pin that the timed
calls are the REAL production imports — not reimplementations.
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

import pytest
import torch
import torch.nn as nn

from scripts.inspection_cost_study import harness as harness_mod
from scripts.inspection_cost_study.classify import classify_point, summarize_exact
from scripts.inspection_cost_study.harness import (
    _measure_candidate_probe,
    _measure_full_search,
    _measure_training_probe,
    read_measurements,
    run_study,
)
from scripts.inspection_cost_study.manifest import _builtin_grid, _entry, _scaled
from scripts.inspection_cost_study.schemas import (
    Measurement,
    SweepEntry,
    manifest_hash,
)

_STUDY_DIR = Path(__file__).resolve().parents[3] / "scripts" / "inspection_cost_study"


def _fixture_entry(**over) -> SweepEntry:
    base = dict(
        entry_id="T_fixture",
        population="builtin_reference",
        architecture_family="fixture",
        model_identity="wavenet",  # real registry key: keeps production
        # helpers (_build_probe_tensors dtype lookup) on their real path
        exact_config={},
        segmentation_size=64,
        realized_total_parameter_count=100,
        realized_trainable_parameter_count=100,
        loss_type="ce",
    )
    base.update(over)
    return SweepEntry(**base)


class _TinyClassifier(nn.Module):
    def __init__(self, delay_s: float = 0.0):
        super().__init__()
        self.emb = nn.Embedding(256, 4)
        self.out = nn.Conv1d(4, 256, 1)
        self.delay_s = delay_s

    def forward(self, x):
        if self.delay_s:
            time.sleep(self.delay_s)
        return self.out(self.emb(x.long()).transpose(1, 2))


# ---------------------------------------------------------------------------
# Manifest: determinism, labels, timing-blindness
# ---------------------------------------------------------------------------


class TestManifest:
    def test_builtin_grid_is_deterministic_and_pure(self):
        g1, g2 = _builtin_grid(), _builtin_grid()
        assert g1 == g2
        assert len(g1) == 29  # 5 ladder steps x 5 families + 4 fcnet steps

    def test_scaled_is_deterministic(self):
        assert _scaled(32, 0.5) == 16
        assert _scaled(1, 0.125) == 1  # the minimum floor

    def test_entry_records_both_parameter_conventions(self):
        e = _entry("T_wv", "builtin_reference", "wavenet", "wavenet", {})
        assert e.load_error is None
        assert (e.realized_total_parameter_count or 0) > 0
        assert e.realized_trainable_parameter_count is not None
        assert e.population == "builtin_reference"
        assert e.architecture_family == "wavenet"

    def test_invalid_config_is_recorded_not_replaced(self):
        """The timing-blind rule's mechanical half: an out-of-schema config
        stays in the manifest as evidence with the constructor error."""
        e = _entry(
            "T_bad",
            "builtin_reference",
            "punet",
            "punet",
            {"multi": 10**9},
        )
        assert e.load_error is not None
        assert "ValidationError" in e.load_error

    def test_manifest_hash_is_content_stable_and_order_sensitive(self):
        a = _fixture_entry(entry_id="one")
        b = _fixture_entry(entry_id="two")
        assert manifest_hash([a, b]) == manifest_hash([a, b])
        assert manifest_hash([a, b]) != manifest_hash([b, a])


# ---------------------------------------------------------------------------
# Harness semantics — per operation, matching production enforcement
# ---------------------------------------------------------------------------


class TestCandidateProbeSemantics:
    def test_completed_carries_exact_elapsed(self):
        m = _measure_candidate_probe(_fixture_entry(), _TinyClassifier(), 2, 0)
        assert m.execution_outcome == "completed"
        assert m.elapsed_seconds is not None and m.lower_bound_seconds is None

    def test_backstop_is_lower_bound_only_and_labelled_harness(self, monkeypatch):
        monkeypatch.setattr(harness_mod, "_CANDIDATE_BACKSTOP_S", 1.0)
        m = _measure_candidate_probe(_fixture_entry(), _TinyClassifier(delay_s=3.0), 1, 0)
        assert m.execution_outcome == "harness_backstop"
        assert m.lower_bound_seconds == 1.0
        assert m.elapsed_seconds is None  # never written as exact


class TestTrainingProbeNativeSemantics:
    def test_native_180_seam_is_preserved_not_relaxed(self, monkeypatch):
        """THE Revision-3 correction: the training probe runs under
        production's own single_probe_seconds alarm. With that budget
        shrunk to 1 s, a 3 s model must be interrupted AT the native
        bound and recorded native_timeout with lower bound == the native
        budget — not at any 2x relaxation, and never as a backstop."""
        from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets

        monkeypatch.setattr(
            harness_mod,
            "_production_budgets",
            lambda: ProbeBudgets(single_probe_seconds=1.0),
        )
        started = time.monotonic()
        m = _measure_training_probe(_fixture_entry(), _TinyClassifier(delay_s=4.0), 0)
        elapsed = time.monotonic() - started
        assert m.execution_outcome == "native_timeout"
        assert m.native_operation == "training_probe"
        assert m.lower_bound_seconds == 1.0
        assert m.elapsed_seconds is None
        assert elapsed < 3.5, "the native alarm did not preempt — a relaxation snuck in"

    def test_fast_training_probe_completes_exact(self):
        m = _measure_training_probe(_fixture_entry(), _TinyClassifier(), 0)
        assert m.execution_outcome == "completed"
        assert m.elapsed_seconds is not None


class TestFullSearchNativeSemantics:
    def test_native_batch_search_timeout_survives_verbatim(self, monkeypatch):
        """A REAL BatchSearchTimeout (typed record attached) must arrive as
        native_timeout with the record verbatim and its EXACT post-hoc
        elapsed — never collapsed into completed or a harness event."""
        from agent.skills.evaluate_vram_skill.batch_resolver import BatchSearchTimeout
        from agent.skills.evaluate_vram_skill.probe_budgets import ProbeTimeoutRecord

        record = ProbeTimeoutRecord(
            operation="batch_candidate",
            budget_seconds=120.0,
            elapsed_seconds=145.3,
            candidate_batch=64,
            phase="inference_batch_resolution",
            model_identity="fixture",
            disposition="inconclusive",
        )

        def _raise(*a, **kw):
            raise BatchSearchTimeout(record)

        monkeypatch.setattr(harness_mod, "_measure_full_search", harness_mod._measure_full_search)
        import agent.skills.evaluate_vram_skill.batch_resolver as br

        monkeypatch.setattr(br, "resolve_inference_batch", _raise)
        m = _measure_full_search(_fixture_entry(), _TinyClassifier(), 2**30, 0)
        assert m.execution_outcome == "native_timeout"
        assert m.native_operation == "batch_candidate"
        assert m.elapsed_seconds == pytest.approx(145.3)  # EXACT (post-hoc)
        assert m.native_record is not None
        rt = ProbeTimeoutRecord.model_validate(m.native_record)
        assert rt == record  # verbatim round-trip

    def test_completed_search_records_resolved_batch(self):
        m = _measure_full_search(_fixture_entry(), _TinyClassifier(), 2**40, 0)
        assert m.execution_outcome == "completed"
        assert m.resolved_batch == 64  # huge cap -> largest candidate wins
        assert m.elapsed_seconds is not None


# ---------------------------------------------------------------------------
# Wall, persistence, read-back
# ---------------------------------------------------------------------------


class TestWallAndPersistence:
    def _entries(self):
        return [
            _fixture_entry(entry_id="T_a"),
            _fixture_entry(entry_id="T_b"),
        ]

    def test_run_study_end_to_end_and_read_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(harness_mod, "_build", lambda e: _TinyClassifier())
        monkeypatch.setattr(harness_mod, "_candidate_batches", lambda: (2, 1))
        out = tmp_path / "m.jsonl"
        counts = run_study(self._entries(), out, wall_seconds=300.0, repeats=1)
        header, ms, expired = read_measurements(out)
        assert not expired
        assert counts["completed"] == len(ms) == 2 * (2 + 1 + 1)
        assert header.production_budgets["single_probe_seconds"] == 180.0

    def test_wall_expiry_is_marked_and_prior_points_survive(self, tmp_path, monkeypatch):
        monkeypatch.setattr(harness_mod, "_build", lambda e: _TinyClassifier(delay_s=0.3))
        monkeypatch.setattr(harness_mod, "_candidate_batches", lambda: (1,))
        out = tmp_path / "m.jsonl"
        run_study(self._entries(), out, wall_seconds=0.5, repeats=3)
        _header, ms, expired = read_measurements(out)
        assert expired is True
        assert 0 < len(ms) < 2 * 3 * 3  # something measured, not everything

    def test_overwrite_refused(self, tmp_path):
        out = tmp_path / "m.jsonl"
        out.write_text("{}")
        with pytest.raises(FileExistsError):
            run_study(self._entries(), out, wall_seconds=1.0)

    def test_malformed_line_raises_on_read_back(self, tmp_path):
        out = tmp_path / "m.jsonl"
        out.write_text('{"header": {"bogus": 1}}\n')
        with pytest.raises((ValueError, KeyError, TypeError)):
            # pydantic ValidationError subclasses ValueError
            read_measurements(out)


# ---------------------------------------------------------------------------
# Classification — the frozen truth table
# ---------------------------------------------------------------------------


def _m(outcome, *, elapsed=None, bound=None, batch=64, repeat=0):
    return Measurement(
        entry_id="P",
        operation="candidate_probe",
        candidate_batch=batch,
        repeat_index=repeat,
        execution_outcome=outcome,
        elapsed_seconds=elapsed,
        lower_bound_seconds=bound,
    )


class TestClassificationTruthTable:
    def test_all_under_is_clear(self):
        v = classify_point(
            [_m("completed", elapsed=5.0), _m("completed", elapsed=6.0, repeat=1)],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "CLEAR" and v.n_under == 2

    def test_exact_overrun_counts_as_over_with_exact_time(self):
        """The post-hoc nuance: a completed 145 s probe against a 120 s
        budget is over-EXACT, not censored."""
        v = classify_point(
            [_m("completed", elapsed=145.0), _m("completed", elapsed=150.0, repeat=1)],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "WOULD_BE_CENSORED"
        assert v.n_over_exact == 2 and v.n_over_censored == 0

    def test_native_exact_and_censored_both_count_as_over(self):
        v = classify_point(
            [
                _m("native_timeout", elapsed=145.0),
                _m("harness_backstop", bound=240.0, repeat=1),
            ],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "WOULD_BE_CENSORED"
        assert v.n_over_exact == 1 and v.n_over_censored == 1

    def test_straddle_is_indeterminate(self):
        v = classify_point(
            [_m("completed", elapsed=100.0), _m("completed", elapsed=130.0, repeat=1)],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "INDETERMINATE"

    def test_deadline_forces_indeterminate(self):
        v = classify_point(
            [_m("completed", elapsed=5.0), _m("harness_deadline", repeat=1)],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "INDETERMINATE"

    def test_union_of_reruns_moves_only_toward_indeterminate(self):
        first = [_m("completed", elapsed=100.0)]
        rerun = [_m("completed", elapsed=130.0, repeat=1)]
        v1 = classify_point(first, budget_name="single_candidate_seconds", budget_seconds=120.0)
        v_union = classify_point(
            first + rerun, budget_name="single_candidate_seconds", budget_seconds=120.0
        )
        assert v1.verdict == "CLEAR"
        assert v_union.verdict == "INDETERMINATE"  # never a silent flip to censored

    def test_lower_bound_below_budget_cannot_place_the_point(self):
        v = classify_point(
            [_m("harness_backstop", bound=50.0)],
            budget_name="single_candidate_seconds",
            budget_seconds=120.0,
        )
        assert v.verdict == "INDETERMINATE"

    def test_mixed_points_refused(self):
        with pytest.raises(ValueError, match="span"):
            classify_point(
                [_m("completed", elapsed=1.0), _m("completed", elapsed=1.0, batch=32)],
                budget_name="single_candidate_seconds",
                budget_seconds=120.0,
            )


class TestSummaries:
    def test_exact_only_and_counts_visible(self):
        ms = [
            _m("completed", elapsed=10.0),
            _m("completed", elapsed=20.0, repeat=1),
            _m("harness_backstop", bound=240.0, repeat=2),
            _m("native_timeout", elapsed=145.0, repeat=3),
        ]
        s = summarize_exact(ms)
        # censored bound and native-timeout exact are EXCLUDED from the
        # completed-call statistics; both are counted visibly.
        assert s["median_s"] == 15.0 and s["min_s"] == 10.0 and s["max_s"] == 20.0
        assert s["n_completed"] == 2
        assert s["n_native_timeout"] == 1 and s["n_backstop"] == 1

    def test_a_measurement_cannot_claim_both_exact_and_bound(self):
        with pytest.raises(Exception, match="both"):
            _m("native_timeout", elapsed=10.0, bound=180.0)


# ---------------------------------------------------------------------------
# Structural pins: real production imports; report delegates classification
# ---------------------------------------------------------------------------


def _module_ast(name: str) -> ast.Module:
    return ast.parse((_STUDY_DIR / name).read_text())


class TestRealSeams:
    def test_harness_calls_the_real_production_functions(self):
        src = (_STUDY_DIR / "harness.py").read_text()
        for needle in (
            "from agent.skills.evaluate_vram_skill.structural_probe import",
            "from agent.skills.evaluate_vram_skill.batch_resolver import",
            "from agent.skills.evaluate_vram_skill.wrapper import",
            "probe_activation_footprint(",
            "resolve_inference_batch(",
            "_forward_pass_timeout(",
            "_build_probe_tensors(",
        ):
            assert needle in src, f"harness lost its real production seam: {needle}"

    def test_training_probe_uses_the_native_budget_attribute(self):
        """AST: inside _measure_training_probe, _forward_pass_timeout is
        called with budgets.single_probe_seconds — the native attribute —
        not a literal, not a multiple (the no-360-relaxation pin)."""
        tree = _module_ast("harness.py")
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_measure_training_probe"
        )
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_forward_pass_timeout"
        ]
        assert len(calls) == 1
        arg = calls[0].args[0]
        assert isinstance(arg, ast.Attribute) and arg.attr == "single_probe_seconds", (
            "the training probe must run under the NATIVE single_probe_seconds "
            "attribute — any literal or arithmetic here is a relaxation"
        )

    def test_every_backstop_construction_is_bound_only(self):
        """AST over BOTH backstop sites (the direct except and the
        chain-walk branch): a Measurement built with
        execution_outcome="harness_backstop" must set lower_bound_seconds
        and must NOT set elapsed_seconds. M-F1-3 survived round 1 because
        the direct-except site is unreachable by a sleep fixture (torchinfo
        launders the alarm, F-A3) — this pin covers the unreachable site
        structurally."""
        tree = _module_ast("harness.py")
        found = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "Measurement"):
                continue
            kw = {k.arg: k for k in node.keywords}
            outcome = kw.get("execution_outcome")
            if (
                outcome is not None
                and isinstance(outcome.value, ast.Constant)
                and outcome.value.value == "harness_backstop"
            ):
                found += 1
                assert "lower_bound_seconds" in kw, "backstop without a lower bound"
                assert "elapsed_seconds" not in kw, (
                    "a harness_backstop Measurement sets elapsed_seconds — "
                    "a lower bound written as an exact time"
                )
        assert found >= 3  # candidate direct + candidate laundered + search sites

    def test_report_delegates_classification_to_the_single_rule(self):
        src = (_STUDY_DIR / "report.py").read_text()
        assert "classify_point(" in src
        # The report must not inline its own verdict logic: the class
        # literals may only appear as counter INITIALISATION, never in a
        # comparison/assignment decision.
        tree = _module_ast("report.py")
        # Verdict literals may appear ONLY as dict keys (the counter
        # initialiser). Anywhere else — comparisons, IfExp branches,
        # assignments — is classification leaking out of classify.py.
        allowed: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key in node.keys:
                    if isinstance(key, ast.Constant):
                        allowed.add(id(key))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in (
                "CLEAR",
                "WOULD_BE_CENSORED",
                "INDETERMINATE",
            ):
                assert id(node) in allowed, (
                    f"report.py uses verdict literal {node.value!r} outside "
                    "the counter-initialiser dict — classification leaked "
                    "out of classify.py"
                )


class TestPopulationDiscipline:
    def test_report_groups_by_population_and_keeps_family(self, tmp_path, monkeypatch):
        from scripts.inspection_cost_study.report import build_report

        monkeypatch.setattr(harness_mod, "_build", lambda e: _TinyClassifier())
        monkeypatch.setattr(harness_mod, "_candidate_batches", lambda: (1,))
        entries = [
            _fixture_entry(entry_id="T_a", population="v20_generated_realized"),
            _fixture_entry(entry_id="T_b", population="builtin_reference"),
        ]
        out = tmp_path / "m.jsonl"
        run_study(entries, out, wall_seconds=300.0, repeats=1)
        payload = build_report(entries, out)
        keys = set(payload["verdict_counts_per_population_operation"])
        assert any(k.startswith("v20_generated_realized::") for k in keys)
        assert any(k.startswith("builtin_reference::") for k in keys)
        # no pooled key exists
        assert not any(k.startswith("ALL::") or "::pooled" in k for k in keys)
        assert all("architecture_family" in row for row in payload["rows"])
        json.dumps(payload)  # serialisable evidence
