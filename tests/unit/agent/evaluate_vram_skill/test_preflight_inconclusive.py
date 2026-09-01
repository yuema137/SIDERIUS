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
    def test_a_timeout_of_any_operation_is_inconclusive(self):
        """`timeout_disposition` ignores its argument by design -- the rule
        is "a step that did not finish measured nothing", whichever step it
        was. Iterated in one body rather than parametrized, because three
        operations through an argument-ignoring function are one case, not
        three."""
        for operation in ("model_inspection", "batch_candidate", "batch_search"):
            assert timeout_disposition(operation) == "inconclusive"

    @pytest.mark.parametrize(
        ("disposition", "is_evidence", "may_downsize"),
        [
            ("measured_capacity_failure", True, True),
            ("completed", False, False),
            ("inconclusive", False, False),
            ("infrastructure_failure", False, False),
        ],
    )
    def test_the_disposition_decides_evidence_and_authority(
        self, disposition, is_evidence, may_downsize
    ):
        """The whole table, both axes, in one place.

        Five tests used to assert single cells of it -- inconclusive is not
        evidence, inconclusive may not downsize, only measured may downsize,
        measured is evidence, infrastructure is neither. Stated as a table,
        a mutation that widens either predicate fails on the row it wrongly
        admits instead of on whichever cell happened to be covered.
        """
        assert _record(disposition=disposition).is_capacity_evidence is is_evidence
        assert may_recommend_downsizing(disposition) is may_downsize

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

    def test_the_timeout_record_names_the_operation_that_expired(self, monkeypatch):
        """Training and inference timeouts must not both claim inspection."""
        from agent.skills.evaluate_vram_skill import wrapper

        error = wrapper.ForwardPassTimeoutError(
            "timed out",
            operation="inference_probe",
        )
        monkeypatch.setattr(
            wrapper, "_build_model", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
        )

        result = wrapper.run_skill(
            None,
            model_type="synthetic_model",
            model_config={},
            train_config={},
            loss_config={},
        )

        assert result["timeout_record"]["operation"] == "inference_probe"


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


# `TestMeasuredResultsStillReject` lived here with three cases. The first two
# -- measured-is-evidence, infrastructure-is-neither -- are rows of
# `test_the_disposition_decides_evidence_and_authority` above, which asserts
# the same two predicates across all four dispositions.
#
# The third asserted that `disposition="not_a_disposition"` raises
# ValidationError. That is a `Literal` refusing an unknown string, which
# Pydantic enforces by declaration; per CLAUDE.md's test-justification rule
# it is not something pytest should re-check.
