"""An unfinished VRAM inspection must never become a verdict about the model.

The V19 campaign `v19r2_10iter_20260731_0750` was stopped and invalidated
on 2026-07-31 for exactly this. One 60-second alarm wrapped the ENTIRE
inference-batch search, which internally probes seven candidate batches
`(64, 32, 16, 8, 4, 2, 1)` with a full `torchinfo` trace each, on CPU.
For a 24-block WaveNet at T=16000 the cumulative cost exceeds 60 s by
construction. The timeout then surfaced as a hard `Resource check error`
whose text blamed a loop "inside `nn.Module.forward`", the agent
concluded that large models are unsafe, and both chains downsized until
they were proposing models at 2-3 % of their VRAM budget.

The same configuration failed and later passed depending on CPU load,
which is what proves it was never capacity evidence.

Two invariants are asserted throughout:

* a budget names the ONE operation it bounds;
* not finishing is not a verdict — only a MEASURED OOM or a MEASURED peak
  above the cap may reject a candidate or ask an agent to shrink it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.skills.evaluate_vram_skill.probe_budgets import (
    InconclusivePreflight,
    ProbeBudgets,
    ProbeTimeoutRecord,
    may_recommend_downsizing,
    timeout_disposition,
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _record(**over) -> ProbeTimeoutRecord:
    base = dict(
        operation="batch_search",
        budget_seconds=600.0,
        elapsed_seconds=601.0,
        model_identity="wavenet_full_spectrum_baseline_v1",
    )
    base.update(over)
    return ProbeTimeoutRecord(**base)


class TestBudgetsAreSeparate:
    """Seven sequential checks must not share one forward's budget."""

    def test_each_operation_has_its_own_budget(self):
        b = ProbeBudgets()
        assert b.for_operation("batch_candidate") != b.for_operation("batch_search")
        assert b.for_operation("batch_search") > b.for_operation("batch_candidate"), (
            "a whole search must be allowed more time than one candidate, or the "
            "search is bounded as though it were a single forward"
        )

    def test_the_search_budget_covers_a_full_candidate_sweep(self):
        """7 candidates at the per-candidate budget must fit the search budget.

        This is the arithmetic the old design got wrong: 7 x (up to 60 s)
        against a single shared 60 s.
        """
        b = ProbeBudgets()
        candidates = 7
        assert b.batch_search_seconds >= candidates * 60.0

    def test_the_old_single_shared_budget_is_no_longer_used(self):
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/wrapper.py").read_text()
        block = source[source.index("resolve_inference_batch(") :]
        assert "_FORWARD_PASS_TIMEOUT_S" not in block.split(")")[0]

    @pytest.mark.parametrize(
        "operation",
        ["model_inspection", "batch_candidate", "batch_search", "training_probe"],
    )
    def test_every_operation_resolves_to_a_positive_budget(self, operation):
        assert ProbeBudgets().for_operation(operation) > 0


class TestTimeoutIsInconclusive:
    @pytest.mark.parametrize("operation", ["model_inspection", "batch_candidate", "batch_search"])
    def test_a_timeout_of_any_operation_is_inconclusive(self, operation):
        assert timeout_disposition(operation) == "inconclusive"
        assert _record(operation=operation).disposition == "inconclusive"

    def test_an_inconclusive_result_is_not_capacity_evidence(self):
        assert _record().is_capacity_evidence is False

    def test_an_inconclusive_result_may_not_recommend_downsizing(self):
        assert may_recommend_downsizing("inconclusive") is False

    def test_only_a_measured_capacity_failure_may_recommend_downsizing(self):
        assert may_recommend_downsizing("measured_capacity_failure") is True
        for other in ("completed", "inconclusive", "infrastructure_failure"):
            assert may_recommend_downsizing(other) is False

    def test_a_candidate_timeout_records_which_candidate(self):
        r = _record(operation="batch_candidate", candidate_batch=64, budget_seconds=120.0)
        assert r.candidate_batch == 64
        assert "candidate batch 64" in r.agent_facing_summary()

    def test_a_search_timeout_records_the_search_elapsed_separately(self):
        r = _record(elapsed_seconds=601.0, search_elapsed_seconds=601.0)
        assert r.search_elapsed_seconds == 601.0

    def test_the_record_carries_the_full_diagnostic_set(self):
        r = _record(
            operation="batch_candidate",
            candidate_batch=32,
            phase="inference_batch_resolution",
            realized_parameter_count=2_924_160,
            device="cpu",
        )
        for field in (
            "operation",
            "budget_seconds",
            "elapsed_seconds",
            "candidate_batch",
            "phase",
            "model_identity",
            "realized_parameter_count",
            "device",
            "provenance",
            "disposition",
        ):
            assert getattr(r, field) is not None


class TestAgentFacingText:
    """The old message sent agents chasing their own model."""

    def test_it_never_blames_a_loop_in_the_candidate(self):
        text = _record().agent_facing_summary()
        assert "nn.Module.forward" not in text
        assert "for`/`while" not in text

    def test_it_states_the_result_is_inconclusive(self):
        text = _record().agent_facing_summary().lower()
        assert "inconclusive" in text

    def test_it_explicitly_forbids_downsizing(self):
        text = _record().agent_facing_summary().lower()
        assert "not a reason to reduce" in text
        assert "too large" in text  # as a negation

    def test_the_live_timeout_handler_uses_the_same_language(self):
        """Checks the RAISED string, not the surrounding comments — the
        comment there deliberately quotes the old wording to explain why
        it was removed."""
        source = (REPO_ROOT / "agent/skills/evaluate_vram_skill/wrapper.py").read_text()
        handler = source[source.index("def _handler") : source.index("old_handler =")]
        raised = handler[handler.index("ForwardPassTimeoutError(") :]
        message = raised[: raised.index("\n        )")]
        assert "INCONCLUSIVE" in message
        assert "nn.Module.forward" not in message
        assert "not a reason to reduce" in message


class TestPromptSafety:
    """An inconclusive attempt must not become a silent size ceiling."""

    def test_the_prompt_explains_inconclusive_records(self):
        source = (REPO_ROOT / "agent/prompts.py").read_text()
        assert "inconclusive_preflight" in source
        assert "{inconclusive_note}" in source

    def test_the_note_forbids_capacity_reduction(self):
        source = (REPO_ROOT / "agent/prompts.py").read_text()
        block = source[source.index("inconclusive_note = (") :][:1400]
        assert "Do NOT reduce model capacity" in block
        assert "NOT a measurement of your model" in block

    def test_inconclusive_does_not_trigger_the_oom_warning(self):
        """The OOM warning keys off `skipped_oom_risk`, which demands a
        smaller config. An inconclusive attempt must never reach it."""
        source = (REPO_ROOT / "agent/prompts.py").read_text()
        oom = source[source.index("oom_records = [") :][:400]
        assert 'status") == "skipped_oom_risk"' in oom
        assert "inconclusive" not in oom


class TestFailureClassification:
    def test_inconclusive_is_distinct_from_a_model_error(self):
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "tuner_mod",
            REPO_ROOT / "nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["tuner_mod"] = mod
        spec.loader.exec_module(mod)

        classify = mod._classify_attempt_failure
        assert (
            classify(InconclusivePreflight("x"), "vram_structural_probe")
            == "inconclusive_preflight"
        )
        # the same stage with a genuine model error keeps its own name
        assert classify(RuntimeError("boom"), "vram_structural_probe") == "model_forward_error"

    def test_the_exception_carries_its_record(self):
        exc = InconclusivePreflight("did not finish", record={"operation": "batch_search"})
        assert exc.record["operation"] == "batch_search"


class TestMeasuredResultsStillReject:
    """The repair must not disarm the real gate."""

    def test_a_measured_capacity_failure_is_capacity_evidence(self):
        assert _record(disposition="measured_capacity_failure").is_capacity_evidence is True

    def test_infrastructure_failure_is_neither_capacity_nor_downsizing(self):
        r = _record(disposition="infrastructure_failure")
        assert r.is_capacity_evidence is False
        assert may_recommend_downsizing(r.disposition) is False

    def test_dispositions_are_mutually_exclusive(self):
        with pytest.raises(ValidationError):
            _record(disposition="not_a_disposition")


class TestFormalAdviceLimits:
    ADVICE = (
        REPO_ROOT / "advice/workflow/v18r_arch_explorer.json",
        REPO_ROOT / "advice/workflow/v18r_loss_explorer.json",
    )

    @pytest.mark.parametrize("path", ADVICE, ids=lambda p: p.name)
    def test_no_stale_16_gb_language(self, path):
        assert "16 GB" not in path.read_text()

    @pytest.mark.parametrize("path", ADVICE, ids=lambda p: p.name)
    def test_states_the_12_gib_hard_cap(self, path):
        body = path.read_text()
        assert "12 GiB" in body
        assert re.search(r"12 GiB (per-chain )?(HARD CAP|hard cap)", body)

    @pytest.mark.parametrize("path", ADVICE, ids=lambda p: p.name)
    def test_keeps_the_fcnet_reference_with_the_measured_peak(self, path):
        body = path.read_text()
        assert "323" in body
        assert "6.04 GiB" in body

    @pytest.mark.parametrize("path", ADVICE, ids=lambda p: p.name)
    def test_encourages_the_10m_to_100m_range_without_mandating_300m(self, path):
        body = path.read_text()
        assert "10M-100M" in body
        assert "must be 323M" not in body
        assert "minimum parameter count" not in body

    @pytest.mark.parametrize("path", ADVICE, ids=lambda p: p.name)
    def test_the_advice_is_still_valid_json_with_the_expected_sections(self, path):
        d = json.loads(path.read_text())
        assert set(d) == {"mindset", "propose", "implement", "tune", "validate"}
        assert all(isinstance(v, list) and v for v in d.values())
