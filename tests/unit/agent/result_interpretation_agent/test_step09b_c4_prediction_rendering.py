"""Step 09b C4 — the version-aware prediction track record.

Owners here (design §11.4 / §9):

* the renderer's four history shapes, with hand-owned expected strings;
* the invariant C4 exists for — a v2 fraction is NEVER rendered over the
  frozen legacy pool's denominator, and the two populations are never summed;
* `unevaluated` can inflate no N;
* ONE authority: the interpreter's synthesis prompt and the proposer's
  reasoning prompt render through the same function;
* the two framework task-literal residues C4 removed.

The proposer-side cells live beside the rest of that node's prompt contract
in `tests/unit/agent/ml_model_proposal_agent/test_prompt_context_surfacing.py`
(`TestBuildReasoningPromptTrackRecord`).
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent.prompt_templates.interpretation.rendering import (
    _build_synthesis_prompt,
    render_prediction_track_record,
)
from agent.schemas.interpretation import (
    PREDICTION_SEMANTICS_LEGACY_V1,
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

V2 = PREDICTION_SEMANTICS_SIGNSAFE_V2


def _render(**kwargs) -> list[str]:
    base = {
        "legacy_history": None,
        "outcomes_by_semantics": None,
        "legacy_gain": None,
        "gain_by_semantics": None,
        "scientific_accuracy": None,
    }
    return render_prediction_track_record(**{**base, **kwargs})


class TestTheFourHistoryShapes:
    def test_empty_history_renders_nothing(self):
        assert _render() == []
        assert (
            _render(
                legacy_history={"confirmed": 0, "partial": 0, "refuted": 0},
                outcomes_by_semantics={V2: {"confirmed": 0, "partial": 0, "refuted": 0}},
                legacy_gain=0.0,
                gain_by_semantics={V2: 0.0},
                scientific_accuracy=None,
            )
            == []
        )

    def test_v2_only_history(self):
        lines = _render(
            outcomes_by_semantics={V2: {"confirmed": 3, "partial": 1, "refuted": 1}},
            gain_by_semantics={V2: 1.23456},
            scientific_accuracy={"confirmed": 0.6, "partial": 0.2, "refuted": 0.2},
        )
        assert lines == [
            "  Scientific accuracy (metric_order_signsafe_v2, N=5) : "
            "confirmed=60%  partial=20%  refuted=20%",
            "  Cumulative information gain (metric_order_signsafe_v2) : 1.235",
        ]

    def test_legacy_only_history_states_the_pool_and_refuses_percentages(self):
        lines = _render(
            legacy_history={"confirmed": 3, "partial": 0, "refuted": 3},
            legacy_gain=0.42,
        )
        assert lines == [
            "  Earlier predictions (legacy_v1) : 6 outcome(s) recorded under "
            "pre-correction semantics — NOT comparable with the statistics above "
            "and not pooled into them",
            "  Cumulative information gain (legacy_v1) : 0.420",
        ]
        assert not any("confirmed=" in line for line in lines)

    def test_mixed_history_labels_both_and_pools_neither(self):
        lines = _render(
            legacy_history={"confirmed": 0, "partial": 9, "refuted": 0},
            outcomes_by_semantics={V2: {"confirmed": 2, "partial": 0, "refuted": 0}},
            legacy_gain=0.3,
            gain_by_semantics={V2: 0.5},
            scientific_accuracy={"confirmed": 1.0, "partial": 0.0, "refuted": 0.0},
        )
        rendered = "\n".join(lines)
        assert "Scientific accuracy (metric_order_signsafe_v2, N=2)" in rendered
        assert "Earlier predictions (legacy_v1) : 9 outcome(s)" in rendered
        assert "(metric_order_signsafe_v2) : 0.500" in rendered
        assert "(legacy_v1) : 0.300" in rendered
        # The defect this commit removes, and its naive "fix":
        assert "N=9" not in rendered, "v2 fractions over the legacy denominator"
        assert "N=11" not in rendered, "the two populations must never be summed"


class TestTheInvariants:
    def test_an_unevaluated_key_cannot_inflate_either_n(self):
        lines = _render(
            legacy_history={"confirmed": 1, "unevaluated": 40},
            outcomes_by_semantics={V2: {"confirmed": 2, "unevaluated": 50}},
            scientific_accuracy={"confirmed": 1.0, "partial": 0.0, "refuted": 0.0},
        )
        rendered = "\n".join(lines)
        assert "N=2" in rendered
        assert "(legacy_v1) : 1 outcome(s)" in rendered
        for inflated in ("N=52", "N=50", "41 outcome"):
            assert inflated not in rendered

    def test_a_zero_legacy_gain_renders_no_gain_line(self):
        lines = _render(legacy_history={"confirmed": 1}, legacy_gain=0.0)
        assert len(lines) == 1
        assert "Cumulative information gain (legacy_v1)" not in lines[0]

    def test_accuracy_without_a_pool_renders_nothing(self):
        """A fraction with no denominator behind it is not a track record."""
        assert _render(scientific_accuracy={"confirmed": 1.0}) == []

    def test_the_version_ids_come_from_the_schema_authority(self):
        """F-09a-17's single-authority rule extended to the renderer."""
        source = inspect.getsource(render_prediction_track_record)
        tree = ast.parse(source.lstrip())
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        # `clean=False`: the cleaned form is dedented and would no longer
        # equal the raw Constant, silently leaving the docstring in the scan.
        docstring = ast.get_docstring(tree.body[0], clean=False) or ""
        executable = [lit for lit in literals if lit != docstring]
        for spelled in executable:
            assert "metric_order_signsafe" not in spelled
            assert "legacy_v1" not in spelled


class TestOneAuthorityTwoConsumers:
    def test_the_synthesis_prompt_renders_through_the_same_function(self):
        rendered = _build_synthesis_prompt(
            per_model_summaries={"m": {"key_findings": [], "bottlenecks": []}},
            per_model_best={"m": 0.1},
            per_model_worst={"m": 0.2},
            overall_best_score=0.1,
            overall_worst_score=0.2,
            overall_best_config=None,
            vocab_diversity_ratio=0.5,
            cumulative_information_gain=0.3,
            prediction_outcomes_history={"confirmed": 2},
            prediction_outcomes_by_semantics={V2: {"confirmed": 1, "partial": 1, "refuted": 0}},
            cumulative_information_gain_by_semantics={V2: 0.12},
            scientific_accuracy={"confirmed": 0.5, "partial": 0.5, "refuted": 0.0},
        )
        assert "Scientific accuracy (metric_order_signsafe_v2, N=2)" in rendered
        assert "Earlier predictions (legacy_v1) : 2 outcome(s)" in rendered
        # The pre-09b line and its false explanation are gone.
        assert "total boldness × confirmed across all iterations" not in rendered

    def test_the_proposer_calls_the_same_renderer(self):
        """ONE track-record authority, shared by both consumers.

        Scanned over the proposer NODE PACKAGE rather than its main module.
        Step 10 / P3 C3 relocated the legacy interpretation renderer — and with
        it this call — into the node-private `evidence_rendering.py`. The claim
        is unchanged and is about the node: it renders the track record through
        the interpreter's authority instead of computing its own N from the
        frozen legacy pool. Pinning the FILE rather than the node would have
        made a pure relocation look like a regression, which is what it did
        until this guard was re-pointed.
        """
        node = REPO_ROOT / "src/nodes/ml_model_proposal_agent"
        sources = {p.name: p.read_text(encoding="utf-8") for p in node.glob("*.py")}
        assert any("render_prediction_track_record" in src for src in sources.values()), (
            "no module in the proposer node calls the shared track-record "
            f"renderer; scanned {sorted(sources)}"
        )
        # …and no module computes an N of its own from the legacy pool.
        for name, src in sources.items():
            assert "sum(pred_hist.values())" not in src, name


class TestFrameworkTaskLiteralsRemoved:
    HELPERS = REPO_ROOT / "src/nodes/interpretation_helpers.py"

    def test_the_discovery_metric_fallback_is_not_a_task_name(self):
        source = self.HELPERS.read_text()
        assert 'get("metric", "denoising_score")' not in source

    def test_the_timing_advice_names_no_task_hyperparameter(self):
        source = self.HELPERS.read_text()
        assert "segmentation_size" not in source

    @pytest.mark.parametrize("token", ["segmentation_size"])
    def test_the_generated_timing_discovery_is_task_free(self, token):
        from execute_tools.metric_order import MetricOrder
        from nodes.interpretation_helpers import generate_discoveries
        from tests.helpers.metric_fixtures import shipped_spec

        discoveries = generate_discoveries(
            prediction_eval=None,
            model_type="m",
            best_score=None,
            inherited_components=[],
            proposed_vocab_links=[],
            timing={"train_time_s": 2000.0, "inference_time_s": 1000.0},
            overall_best_score=None,
            order=MetricOrder(shipped_spec()),
        )
        assert len(discoveries) == 1, "anti-vacuity: the timing discovery must fire"
        assert token not in discoveries[0].description
        assert "High compute cost" in discoveries[0].description
