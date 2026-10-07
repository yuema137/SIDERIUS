"""
Tests for nodes/result_interpretation_agent.py

LLM calls are mocked — these tests validate:
  - Deterministic pre-computation (best/worst scores from ModelRunSummary)
  - LLM response merged correctly into InterpretationOutput
  - Output validated against schema
  - Output file written to correct path
  - Multiple model summaries handled correctly
  - Single-model mode skips synthesis
  - Multi-model mode uses synthesis LLM call
  - Unknown model type raises FileNotFoundError
"""

import json
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest

from agent.prompt_templates.interpretation.rendering import (
    _build_per_model_prompt,
    _build_synthesis_prompt,
)
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    ModelRunSummary,
)
from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.dataset_config import bind_dataset_profile
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.formal_evidence import disabled_formal_evidence
from tests.helpers.metric_fixtures import shipped_spec
from tests.helpers.two_family_profile import make_two_family_profile

_SCORE_TABLE_PROFILE = make_two_family_profile(num_files=20)


@pytest.fixture(autouse=True)
def _bind_interpretation_profile():
    """Run profile-sensitive interpreter code under an explicit test topology."""
    with bind_dataset_profile(_SCORE_TABLE_PROFILE):
        yield


def _make_score_table(fv):
    """Build a fixture ScoreComparisonTable from a length-20 list of
    per-file model scores. Reference columns are constant placeholders —
    tests only exercise the model column (and derived columns)."""
    with bind_dataset_profile(_SCORE_TABLE_PROFILE):
        return _make_score_table_bound(fv)


def _make_score_table_bound(fv):
    rows = [
        PerFileRow(
            file_index=i,
            raw_baseline=0.1,
            ground_truth=100.0,
            model=v,
            gain_vs_raw=(v - 0.1) if v is not None else None,
            headroom_vs_gt=(100.0 - v) if v is not None else None,
        )
        for i, v in enumerate(fv)
    ]
    present = [v for v in fv if v is not None]
    model_scalar = (sum(present) / len(present)) if present else 0.0
    return ScoreComparisonTable(
        rows=rows,
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.1,
            ground_truth_scalar=100.0,
            model_scalar=model_scalar,
            percent_of_ceiling_log=model_scalar / 100.0,
            num_sampled_files=len(present) or 1,
        ),
        s_max_global=1.0,
        reference_source="test_fixture",
        rendered_markdown="| file | raw | gt | model |\n(test fixture)",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Phase 1 response (per-model summarization)
FAKE_PER_MODEL_RESPONSE = {
    "key_findings": [
        "focal loss with gamma=2 consistently outperforms ce by ~0.05",
        "increasing depth beyond 3 yields diminishing returns",
    ],
    "bottlenecks": [
        "architecture capacity ceiling at depth=3 — score plateaued across 8 experiments",
    ],
    "best_config_analysis": "Depth 4 with focal loss gamma=2 yielded the best result.",
    "score_trend": "Scores improved initially but plateaued after depth=3.",
}

# Phase 2 response (cross-model synthesis)
FAKE_SYNTHESIS_RESPONSE = {
    "key_findings": [
        "punet outperforms fcnet by 0.9 points at best",
        "both models plateau at similar training budgets",
    ],
    "bottlenecks": [
        "all current architectures hit a capacity ceiling",
    ],
    "take_home_message": "The current architecture has saturated; a fundamentally different design is needed.",
}

PUNET_SUMMARY = ModelRunSummary(
    model_type="punet",
    run_name="v1",
    status="completed",
    completed_rounds=3,
    best_denoising_score=1.8,
    worst_denoising_score=1.2,
    best_config={
        "model_config": {"depth": 4},
        "train_config": {"lr": 1e-4},
        "loss_config": {"loss_type": "focal"},
    },
    round_scores=[1.2, 1.5, 1.8],
    round_conclusions=["Initial baseline.", "Improved with focal loss.", "Best with depth=4."],
)

FCNET_SUMMARY = ModelRunSummary(
    model_type="fcnet",
    run_name="v1",
    status="completed",
    completed_rounds=2,
    best_denoising_score=0.9,
    worst_denoising_score=0.5,
    best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
    round_scores=[0.5, 0.9],
    round_conclusions=["Poor start.", "Moderate improvement."],
)


@pytest.fixture
def agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        yield a


def _llm_dispatch(system_prompt: str, user_prompt: str, **kwargs) -> dict:
    """Route mock LLM calls to the right fake response based on the system prompt.

    Accepts ``**kwargs`` so newer ``label=`` / ``components=`` kwargs from
    the bridge call sites (Commit 3 of the token-usage refactor) don't
    raise ``TypeError`` against this stub.
    """
    if "ONE model architecture" in system_prompt:
        return FAKE_PER_MODEL_RESPONSE
    else:
        return FAKE_SYNTHESIS_RESPONSE


def make_input(summary, workspace="/tmp/interp_test", run_name="r1"):
    return InterpretationInput(
        summaries=[summary],
        # Step 09a C2 — a score-bearing interpretation REQUIRES the run's
        # bound MetricSpec; ordering direction is never assumed. The shipped
        # TIDMAD spec is `higher`, so every assertion below is unchanged.
        metric_spec=shipped_spec(),
        storage={"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# Shared runs — one agent.run() per contract, not one per field
# ---------------------------------------------------------------------------
#
# 21 tests used to run the SAME agent.run() with the SAME input and assert
# one field each. That granularity was illusory: they passed and failed
# together, because a break anywhere in the reduction broke all of them.
#
# Grouped by SEMANTICS, deliberately not as one model_dump() snapshot: a
# snapshot makes a failure unreadable and churns whenever an unrelated
# field is added. Each group below names one public contract, so a failure
# message points at one behaviour.
#
# Tests whose field comes from an INDEPENDENT path or risk are NOT here --
# cache dispatch, persistence, the Phase-1-vs-synthesis decision, the
# legacy-summary branch, vocab carry-forward and chain accounting all keep
# their own runs.


def _run_once(workspace, summaries):
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        return a.run(
            InterpretationInput(
                summaries=summaries,
                # Step 09a C2 — see make_input above.
                metric_spec=shipped_spec(),
                storage={
                    "backend": "local",
                    "local": {"workspace": str(workspace), "run_name": "r1"},
                },
            )
        )


@pytest.fixture(scope="module")
def single_model_output(tmp_path_factory):
    return _run_once(tmp_path_factory.mktemp("single"), [PUNET_SUMMARY])


@pytest.fixture(scope="module")
def multi_model_output(tmp_path_factory):
    """FCNET first, deliberately.

    With the higher-scoring PUNET first, replacing the global-max
    reduction with "take the first model" produced an identical result
    and no test failed. Ordering the weaker summary first makes that
    mutation detectable. The pre-consolidation tests used the same
    ordering and had the same blind spot.
    """
    return _run_once(tmp_path_factory.mktemp("multi"), [FCNET_SUMMARY, PUNET_SUMMARY])


class TestSingleModelContract:
    """One completed summary -> a schema-valid digest whose aggregates are
    computed from that summary and whose knowledge artifacts are
    populated for the model."""

    def test_score_aggregation(self, single_model_output):
        """Broken max/min reduction, broken per-model keying, a dropped
        round-count sum, or a dropped echo of the winning config each
        fail a different line here."""
        out = single_model_output
        assert out.best_denoising_score == 1.8
        assert out.worst_denoising_score == 1.2
        assert out.per_model_best["punet"] == 1.8
        assert out.per_model_worst["punet"] == 1.2
        assert out.total_experiments == 3
        assert out.best_config["model_config"]["depth"] == 4

    def test_knowledge_artifacts(self, single_model_output):
        """Schema drift, a broken model-description registry lookup, and
        a Phase-1 result not stored under the model key are three
        different failures."""
        out = single_model_output
        assert isinstance(out, InterpretationOutput)
        assert "punet" in out.model_types
        assert len(out.model_descriptions["punet"]) > 100
        assert (
            out.model_knowledge_cache["punet"]["key_findings"]
            == FAKE_PER_MODEL_RESPONSE["key_findings"]
        )


class TestMultiModelContract:
    """Two summaries -> aggregates are cross-model reductions while
    per-model artifacts stay independent and complete."""

    def test_cross_model_aggregation(self, multi_model_output):
        """A reduction that takes the first model instead of the global
        extreme fails the overall assertions; one that collapses the
        per-model maps fails the per-model ones."""
        out = multi_model_output
        assert out.best_denoising_score == 1.8
        assert out.worst_denoising_score == 0.5
        assert out.per_model_best["punet"] == 1.8
        assert out.per_model_best["fcnet"] == 0.9
        assert out.total_experiments == 5

    def test_every_model_reaches_every_map(self, multi_model_output):
        """A loop that stops after the first model fails here, and the
        assertion names which map lost it."""
        out = multi_model_output
        for model in ("punet", "fcnet"):
            assert model in out.model_types
            assert model in out.model_knowledge_cache
            assert model in out.model_descriptions


# ---------------------------------------------------------------------------
# Single-model tests
# ---------------------------------------------------------------------------


class TestSingleModel:
    def test_phase1_findings_used(self, agent, tmp_path):
        """Single-model: phase 1 findings used directly, synthesis skipped."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.key_findings == FAKE_PER_MODEL_RESPONSE["key_findings"]
        assert output.bottlenecks == FAKE_PER_MODEL_RESPONSE["bottlenecks"]
        assert (
            "punet" in output.take_home_message.lower()
            or "plateau" in output.take_home_message.lower()
        )

    def test_output_written_to_file(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path), run_name="myrun")
        agent.run(inp)
        out_path = tmp_path / "interpretation_myrun.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "punet" in data["model_types"]
        assert data["best_denoising_score"] == 1.8


# ---------------------------------------------------------------------------
# Multi-model tests
# ---------------------------------------------------------------------------


class TestMultiModel:
    def test_synthesis_used_for_multi_model(self, agent, tmp_path):
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.key_findings == FAKE_SYNTHESIS_RESPONSE["key_findings"]
        assert output.take_home_message == FAKE_SYNTHESIS_RESPONSE["take_home_message"]


# ---------------------------------------------------------------------------
# model_knowledge_cache: cache hit / cache miss / _stats
# ---------------------------------------------------------------------------

# A pre-built cache entry for punet — as if produced by a previous iteration
_PUNET_CACHED_ENTRY = {
    **FAKE_PER_MODEL_RESPONSE,
    "_stats": {
        "best_denoising_score": 1.8,
        "worst_denoising_score": 1.2,
        "best_file_vector": None,
        "best_model_params": None,
        "completed_rounds": 3,
        "best_config": PUNET_SUMMARY.best_config,
    },
}


class TestModelKnowledgeCache:
    def test_cache_miss_calls_llm_and_populates_cache(self, agent, tmp_path):
        """New model (not in cache) → Phase 1 LLM called, cache entry built."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        call_count_before = agent.bridge.generate.call_count
        output = agent.run(inp)
        # Phase 1 LLM was called (cache miss)
        assert agent.bridge.generate.call_count > call_count_before
        assert "punet" in output.model_knowledge_cache
        assert (
            output.model_knowledge_cache["punet"]["key_findings"]
            == FAKE_PER_MODEL_RESPONSE["key_findings"]
        )

    def test_cache_miss_stores_stats(self, agent, tmp_path):
        """Cache entry built from cache miss includes _stats from ModelRunSummary."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        stats = output.model_knowledge_cache["punet"]["_stats"]
        assert stats["best_denoising_score"] == 1.8
        assert stats["worst_denoising_score"] == 1.2
        assert stats["completed_rounds"] == 3

    def test_cache_hit_skips_llm_call(self, agent, tmp_path):
        """Model already in cache → Phase 1 LLM not called, cached entry reused."""
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[],  # no new summaries
            model_knowledge_cache={"punet": _PUNET_CACHED_ENTRY},
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        call_count_before = agent.bridge.generate.call_count
        output = agent.run(inp)
        # No Phase 1 LLM call (single-model path also skips Phase 2 synthesis)
        assert agent.bridge.generate.call_count == call_count_before
        # Cached entry content passed through unchanged
        assert output.model_knowledge_cache["punet"] == _PUNET_CACHED_ENTRY

    def test_cache_hit_scores_from_stats(self, agent, tmp_path):
        """Scores for cached model are reconstructed from cache _stats, not raw summary."""
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[],
            model_knowledge_cache={"punet": _PUNET_CACHED_ENTRY},
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_worst["punet"] == 1.2
        assert output.total_experiments == 3

    def test_mixed_one_cached_one_new_llm_called_once(self, agent, tmp_path):
        """punet cached, fcnet new → exactly one Phase 1 LLM call (for fcnet only)."""
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[FCNET_SUMMARY],  # only fcnet is new
            model_knowledge_cache={"punet": _PUNET_CACHED_ENTRY},
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        call_count_before = agent.bridge.generate.call_count
        output = agent.run(inp)
        calls_made = agent.bridge.generate.call_count - call_count_before
        # 1 Phase 1 call (fcnet) + 1 Phase 2 synthesis call = 2 total
        assert calls_made == 2
        assert "punet" in output.model_knowledge_cache
        assert "fcnet" in output.model_knowledge_cache
        # punet scores from cache, fcnet scores from new summary
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_best["fcnet"] == 0.9


# ---------------------------------------------------------------------------
# model_types only (no summaries)
# ---------------------------------------------------------------------------


class TestModelTypesOnly:
    def test_descriptions_only_no_summaries(self, agent, tmp_path):
        inp = InterpretationInput(
            model_types=["punet"],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert "punet" in output.model_types
        assert "punet" in output.model_descriptions
        assert output.total_experiments == 0
        assert output.best_denoising_score is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_unknown_model_type_raises(self, tmp_path):
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[
                ModelRunSummary(
                    model_type="nonexistent_model",
                    run_name="v1",
                    status="completed",
                    completed_rounds=0,
                )
            ],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        with patch("nodes.result_interpretation_agent.LLMBridge"):
            agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            with pytest.raises(FileNotFoundError, match="nonexistent_model"):
                agent.run(inp)

    def test_no_model_provided_raises(self):
        with pytest.raises(Exception, match="At least one model type"):
            InterpretationInput()


# ---------------------------------------------------------------------------
# Enriched summaries for prompt builder and output computation tests
# ---------------------------------------------------------------------------

_ENRICHED_BEST_FV = [
    0.001,
    0.01,
    0.1,
    0.5,
    1.0,
    2.0,
    5.0,
    78.0,
    1.5,
    2.5,
    3.0,
    7.0,
    1.3,
    0.9,
    40.0,
    21.0,
    5.0,
    5.0,
    3.0,
    0.8,
]
_ENRICHED_FORMAL_FV = [
    0.002,
    0.02,
    0.15,
    0.6,
    1.1,
    2.2,
    5.5,
    80.0,
    1.6,
    2.6,
    3.1,
    7.5,
    1.4,
    1.0,
    41.0,
    22.0,
    5.2,
    5.1,
    3.2,
    0.9,
]

with bind_dataset_profile(_SCORE_TABLE_PROFILE):
    ENRICHED_SUMMARY = ModelRunSummary(
        model_type="punet",
        run_name="v1",
        status="completed",
        completed_rounds=3,
        best_denoising_score=1.8,
        worst_denoising_score=0.5,
        best_config={"model_config": {"depth": 4}, "train_config": {"lr": 1e-4}},
        round_scores=[0.5, 1.2, 1.8],
        round_conclusions=["Baseline.", "Improved.", "Best."],
        # Per-file performance — raw primitive retained per §7.2 scope note.
        best_file_vector=_ENRICHED_BEST_FV,
        formal_score=1.6,
        formal_file_vector=_ENRICHED_FORMAL_FV,
        # Per-file performance — enriched (Phase 4) — what downstream agents read.
        best_score_table=_make_score_table(_ENRICHED_BEST_FV),
        formal_score_table=_make_score_table(_ENRICHED_FORMAL_FV),
        best_model_params=55000,
        training_psd_segments=200,
        eval_psd_segments=200,
        trial_portion=0.05,
        round_trial_portions=[0.05, 0.05, 0.1],
        round_model_params=[55000, 55000, 55000],
    )


# ---------------------------------------------------------------------------
# Prompt builder tests
# ---------------------------------------------------------------------------


class TestBuildPerModelPrompt:
    def test_includes_best_score_table_rendered_markdown(self):
        # Phase 5 A: per-model prompt drops the 20-line per-file listing and
        # renders the full ScoreComparisonTable markdown instead. The fixture's
        # rendered_markdown carries the sentinel "(test fixture)" line.
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "Per-file performance (best experiment)" in prompt
        assert "(test fixture)" in prompt

    def test_includes_formal_score(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "Formal round score" in prompt
        assert "1.6" in prompt

    def test_includes_formal_score_table(self):
        # Formal round's rendered markdown lands under its own section header.
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "Per-file performance (formal round" in prompt

    def test_includes_model_params(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "55,000" in prompt

    def test_includes_training_psd_segments(self):
        """The VOLUME renders; the baseline-comparison FACT does not.

        Step 09b C2 (DW-8): "(baseline typically uses 4000)" was TIDMAD
        science riding in a framework user-prompt line. The schema-derived
        label and the run's actual segment count stay here; the baseline
        reference now lives in the task's `evidence_reading` block, where the
        C2 census owns the positive half (it must appear in the ASSEMBLED
        TIDMAD system prompt).
        """
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "Training PSD segments: 200" in prompt
        assert "4000" not in prompt

    def test_includes_trial_portion(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "0.05" in prompt

    def test_includes_round_trial_portions_in_trajectory(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "portion=0.05" in prompt
        assert "portion=0.1" in prompt  # round 3 increased portion

    def test_includes_round_model_params_in_trajectory(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "params=55,000" in prompt

    def test_skips_none_fields(self):
        """When new fields are None (old data), prompt still works."""
        prompt = _build_per_model_prompt(PUNET_SUMMARY, "PUNet description")
        assert "Per-file performance" not in prompt
        assert "Formal round score" not in prompt
        assert "Training PSD segments" not in prompt


class TestBuildSynthesisPrompt:
    def test_includes_score_table(self):
        # 2-zh: synthesis prompt renders the full ScoreComparisonTable
        # markdown. The pre-V9 threshold-based "Weak Frequency Files
        # (attention cue)" block has been deleted — opportunity ranking is
        # now read directly from the table's Impact_Score column (rendered
        # as a secondary block by build_score_table).
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_score_tables={"punet": ENRICHED_SUMMARY.best_score_table},
        )
        assert "Per-file performance (best experiment)" in prompt
        assert "(test fixture)" in prompt
        assert "Weak Frequency" not in prompt

    def test_synthesis_prompt_renders_weight_and_impact_columns(self):
        # P1-Impact: the impact-aware ScoreComparisonTable's pre-rendered
        # markdown must drop into the synthesis prompt verbatim — the LLM
        # must see the new Weight % and Impact columns plus the secondary
        # block. We construct a real impact-aware table via build_score_table
        # so the rendered_markdown is the production output, not a fixture
        # placeholder.
        import math

        from execute_tools.scoring_helpers import (
            _LOG_BASE,
            _LOG_OFFSET,
            build_score_table,
        )
        from nodes.scoring_reference import ReferenceScores

        n_segments = 200
        gt_linear_sum = [20.0] * 20  # gt mean = 0.10 per file
        raw_linear_sum = [2.0] * 20
        ref = ReferenceScores(
            raw_per_file_log=[math.log(s / n_segments, _LOG_BASE) for s in raw_linear_sum],
            gt_per_file_log=[math.log(s / n_segments, _LOG_BASE) for s in gt_linear_sum],
            raw_per_file_linear_sum=raw_linear_sum,
            raw_per_file_n_segments=[n_segments] * 20,
            gt_per_file_linear_sum=gt_linear_sum,
            gt_per_file_n_segments=[n_segments] * 20,
            raw_scalar_full=math.log(0.01, _LOG_BASE),
            gt_scalar_full=math.log(0.10, _LOG_BASE),
            s_max=1.0,
        )
        # Heterogeneous fv → impacts span a range so the secondary block is
        # meaningfully sorted.
        fv_linear = [0.005 * (i + 1) for i in range(20)]
        fv_log = [math.log(v + _LOG_OFFSET, _LOG_BASE) for v in fv_linear]
        impact_table = build_score_table(
            fv_log,
            model_scalar=fv_log[0],
            reference=ref,
            model_fv_linear=fv_linear,
        )
        assert impact_table is not None
        assert any(r.linear_weight is not None for r in impact_table.rows), (
            "fixture must carry linear_weight on sampled rows"
        )

        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_score_tables={"punet": impact_table},
        )
        assert "Weight %" in prompt
        assert "Impact" in prompt
        assert "Sampled files re-ranked by Impact_Score" in prompt

    def test_includes_params(self):
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_params={"punet": 55000},
        )
        assert "55,000" in prompt

    def test_includes_training_segments(self):
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_training_segments={"punet": 200},
        )
        assert "200" in prompt

    def test_works_without_new_fields(self):
        """When new fields are None, synthesis prompt still works."""
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
        )
        assert "punet" in prompt
        assert "Per-file performance" not in prompt


# ---------------------------------------------------------------------------
# Bug 3 fix: formal_score in _stats and synthesis prompt
# ---------------------------------------------------------------------------


class TestFormalScore:
    """
    Verify that formal_score is:
    1. Stored in _stats when a new cache entry is built.
    2. Reconstructed into per_model_formal from the cache for cached models.
    3. Rendered in the synthesis prompt only when it differs from best_score.
    """

    def test_formal_score_stored_in_stats_on_cache_miss(self, agent, tmp_path):
        """Cache miss: _stats must include formal_score from ModelRunSummary."""
        summary = ModelRunSummary(
            model_type="punet",
            run_name="v1",
            status="completed",
            completed_rounds=2,
            best_denoising_score=1.8,
            worst_denoising_score=1.2,
            formal_score=1.5,  # distinct from best (which came from a trial round)
            best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        )
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[summary],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        stats = output.model_knowledge_cache["punet"]["_stats"]
        assert "formal_score" in stats
        assert stats["formal_score"] == 1.5

    def test_formal_score_none_stored_when_absent(self, agent, tmp_path):
        """When summary has no formal_score, _stats["formal_score"] is None."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        stats = output.model_knowledge_cache["punet"]["_stats"]
        assert "formal_score" in stats
        assert stats["formal_score"] is None

    def test_formal_score_rendered_in_synthesis_when_different(self):
        """Synthesis prompt shows 'Formal score' line when it differs from best."""
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_formal={"punet": 1.5},  # differs from best 1.8
        )
        assert "Formal score" in prompt
        assert "1.5" in prompt
        assert "trial" in prompt  # warning about trial round inflation

    def test_formal_score_not_rendered_when_equal_to_best(self):
        """No 'Formal score' line when formal == best (no inflation to warn about)."""
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_formal={"punet": 1.8},  # same as best — no warning needed
        )
        assert "Formal score" not in prompt

    def test_formal_score_reconstructed_from_cache(self, agent, tmp_path):
        """
        Cached model with formal_score in _stats → synthesis prompt shows it.
        This is the core scenario: second iteration, model already cached.
        """
        cached_entry = {
            **FAKE_PER_MODEL_RESPONSE,
            "_stats": {
                "best_denoising_score": 1.8,
                "worst_denoising_score": 1.2,
                "best_file_vector": None,
                "best_model_params": None,
                "completed_rounds": 3,
                "best_config": PUNET_SUMMARY.best_config,
                "formal_score": 1.5,
            },
        }
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[FCNET_SUMMARY],  # new model this iteration
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            model_knowledge_cache={"punet": cached_entry},
        )
        output = agent.run(inp)
        # punet was cached — its formal_score must appear in the synthesis prompt.
        # Verify indirectly: the output was produced without error and punet is in the cache.
        assert "punet" in output.model_knowledge_cache
        assert output.model_knowledge_cache["punet"]["_stats"]["formal_score"] == 1.5


# ---------------------------------------------------------------------------
# Output computation tests
# ---------------------------------------------------------------------------


class TestOutputEnrichedFields:
    def test_enriched_fields_are_projected_without_loss(self, agent, tmp_path):
        """Three projections of one enriched summary, one run.

        A dropped/flattened score table fails the isinstance or the row
        count; params or segments not forwarded each fail their own
        equality. The None branch below is a DIFFERENT input and keeps
        its own run.
        """
        inp = make_input(ENRICHED_SUMMARY, workspace=str(tmp_path))
        out = agent.run(inp)
        table = out.per_model_score_tables["punet"]
        assert isinstance(table, ScoreComparisonTable)
        assert len(table.rows) == 20
        assert out.per_model_params["punet"] == 55000
        assert out.per_model_training_segments["punet"] == 200

    def test_none_fields_produce_none_output(self, agent, tmp_path):
        """Old-style summary (no score_table etc) produces None for enriched fields."""
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_score_tables is None
        assert output.per_model_params is None
        assert output.per_model_training_segments is None


# ---------------------------------------------------------------------------
# Expert advice prompt injection tests
# ---------------------------------------------------------------------------


class TestExpertAdviceInPrompts:
    """Verify expert_advice appears in prompt text when provided."""

    def test_per_model_prompt_includes_expert_advice_string(self):
        prompt = _build_per_model_prompt(
            summary=PUNET_SUMMARY,
            description="PUNet description",
            expert_advice_str="Focus on low-frequency performance",
        )
        assert "Expert Guidance" in prompt
        assert "Focus on low-frequency performance" in prompt

    def test_per_model_prompt_excludes_expert_when_empty(self):
        prompt = _build_per_model_prompt(
            summary=PUNET_SUMMARY,
            description="PUNet description",
            expert_advice_str="",
        )
        assert "Expert Guidance" not in prompt

    def test_synthesis_prompt_includes_expert_advice_string(self):
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            expert_advice_str="Compare all models on same data volume",
        )
        assert "Expert Guidance" in prompt
        assert "Compare all models on same data volume" in prompt

    def test_synthesis_prompt_excludes_expert_when_empty(self):
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            expert_advice_str="",
        )
        assert "Expert Guidance" not in prompt

    def test_expert_advice_before_human_advice_in_per_model(self):
        """Expert advice section appears before human advice in prompt text."""
        prompt = _build_per_model_prompt(
            summary=PUNET_SUMMARY,
            description="PUNet description",
            expert_advice_str="Expert says focus here",
            human_advice="Human says focus there",
        )
        expert_pos = prompt.index("Expert Guidance")
        human_pos = prompt.index("Human Guidance")
        assert expert_pos < human_pos

    def test_expert_advice_before_human_advice_in_synthesis(self):
        """Expert advice section appears before human advice in synthesis prompt."""
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            expert_advice_str="Expert says focus here",
            human_advice="Human says focus there",
        )
        expert_pos = prompt.index("Expert Guidance")
        human_pos = prompt.index("Human Guidance")
        assert expert_pos < human_pos


# ---------------------------------------------------------------------------
# Semantic dedup (C.6)
# ---------------------------------------------------------------------------

from agent.schemas.proposal import VocabEntry as _VocabEntry


def _canon(name, kind="feature", description="test", aliases=None):
    return _VocabEntry(
        name=name, kind=kind, description=description, tier="canonical", aliases=aliases or []
    )


def _promoted(name, kind="feature", description="test"):
    return _VocabEntry(
        name=name,
        kind=kind,
        description=description,
        tier="canonical",
        seen_in_runs=["r1", "r2", "r3"],
    )


class TestDedupPromoted:
    def test_no_promotions_skips_llm(self, agent):
        """Empty promoted_names → bridge.generate not called, vocab unchanged."""
        vocab = [_canon("dilated_causal_conv")]
        call_count_before = agent.bridge.generate.call_count
        updated_vocab, changes = agent._dedup_promoted([], vocab)
        assert agent.bridge.generate.call_count == call_count_before
        assert changes == []
        assert len(updated_vocab) == 1

    def test_no_existing_canonicals_of_same_kind_skips_llm(self, agent):
        """Promoted entry is the only canonical of its kind → skip LLM call."""
        promoted = _promoted("log_fno", kind="feature")
        call_count_before = agent.bridge.generate.call_count
        updated_vocab, changes = agent._dedup_promoted(["log_fno"], [promoted])
        assert agent.bridge.generate.call_count == call_count_before
        assert changes == []
        assert any(e.name == "log_fno" for e in updated_vocab)

    def test_genuine_new_entry_stays_canonical(self, agent):
        """LLM says not a duplicate → promoted entry stays in vocab."""
        agent.bridge.generate.side_effect = None
        agent.bridge.generate.return_value = {
            "is_duplicate": False,
            "duplicate_of": None,
            "rationale": "Distinct concept.",
        }
        vocab = [_canon("dilated_causal_conv"), _promoted("log_fno")]
        updated_vocab, changes = agent._dedup_promoted(["log_fno"], vocab)
        assert any(e.name == "log_fno" for e in updated_vocab)
        assert changes == []

    def test_duplicate_removed_and_aliased(self, agent):
        """LLM says duplicate → promoted entry removed, name added to existing aliases."""
        agent.bridge.generate.side_effect = None
        agent.bridge.generate.return_value = {
            "is_duplicate": True,
            "duplicate_of": "dilated_causal_conv",
            "rationale": "Same mechanism, different name.",
        }
        vocab = [_canon("dilated_causal_conv"), _promoted("dilated_conv_alt")]
        updated_vocab, changes = agent._dedup_promoted(["dilated_conv_alt"], vocab)
        names = {e.name for e in updated_vocab}
        assert "dilated_conv_alt" not in names
        canon = next(e for e in updated_vocab if e.name == "dilated_causal_conv")
        assert "dilated_conv_alt" in canon.aliases
        assert len(changes) == 1
        assert "dilated_conv_alt" in changes[0]

    def test_invalid_duplicate_of_name_treated_as_genuine(self, agent):
        """LLM returns nonexistent duplicate_of → no merge, entry stays canonical."""
        agent.bridge.generate.side_effect = None
        agent.bridge.generate.return_value = {
            "is_duplicate": True,
            "duplicate_of": "nonexistent_entry",
            "rationale": "Seems similar.",
        }
        vocab = [_canon("dilated_causal_conv"), _promoted("log_fno")]
        updated_vocab, changes = agent._dedup_promoted(["log_fno"], vocab)
        assert any(e.name == "log_fno" for e in updated_vocab)
        assert changes == []

    def test_only_same_kind_used_for_comparison(self, agent):
        """Capabilities are not compared against features and vice versa."""
        agent.bridge.generate.side_effect = None
        agent.bridge.generate.return_value = {
            "is_duplicate": False,
            "duplicate_of": None,
            "rationale": "Distinct.",
        }
        # promoted is a capability; existing canonical is a feature — different kind
        existing_feature = _canon("dilated_causal_conv", kind="feature")
        promoted_cap = _promoted("freq_selectivity", kind="capability")
        # Add one existing canonical of the same kind so LLM IS called
        existing_cap = _canon("receptive_field", kind="capability")
        vocab = [existing_feature, existing_cap, promoted_cap]
        agent._dedup_promoted(["freq_selectivity"], vocab)
        # LLM was called once (existing_cap is same kind)
        call_args = agent.bridge.generate.call_args[0]
        assert "dilated_causal_conv" not in call_args[1]  # feature not in prompt


# ---------------------------------------------------------------------------
# Bug 1 fix: proposed_by_run injection (result_interpretation_agent.run)
# ---------------------------------------------------------------------------


class TestProposedByRunInjection:
    """
    Verify that the interpretation agent injects proposed_by_run from
    previous_proposal.model_name before calling build_runtime_vocab.

    The LLM never produces proposed_by_run itself; without the injection
    seen_in_runs stays empty forever and promote_candidates can never fire.
    """

    def test_proposed_by_run_injected_from_model_name(self, agent, tmp_path):
        """
        Candidates in previous_proposal.proposed_vocab_candidates with no
        proposed_by_run key should get proposed_by_run = model_name injected,
        so seen_in_runs is populated on the resulting VocabEntry.
        """
        previous_proposal = {
            "model_name": "attn_wavenet",
            "proposed_vocab_candidates": [
                {
                    "name": "log_fno_gates",
                    "kind": "feature",
                    "description": "FNO with log-spaced frequency gates",
                },
            ],
        }
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            previous_proposal=previous_proposal,
        )
        output = agent.run(inp)

        entry = next((e for e in output.runtime_vocab if e.name == "log_fno_gates"), None)
        assert entry is not None, "Candidate should appear in runtime_vocab"
        assert "attn_wavenet" in entry.seen_in_runs, (
            "proposed_by_run should have been injected from model_name — "
            "seen_in_runs must contain the proposing model name"
        )

    def test_existing_proposed_by_run_not_overwritten(self, agent, tmp_path):
        """
        If a candidate already carries proposed_by_run (e.g. set by an earlier
        test or future pipeline stage), the agent must not overwrite it.
        """
        previous_proposal = {
            "model_name": "attn_wavenet",
            "proposed_vocab_candidates": [
                {
                    "name": "log_fno_gates",
                    "kind": "feature",
                    "description": "FNO with log-spaced gates",
                    "proposed_by_run": "earlier_model",
                },
            ],
        }
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            previous_proposal=previous_proposal,
        )
        output = agent.run(inp)

        entry = next((e for e in output.runtime_vocab if e.name == "log_fno_gates"), None)
        assert entry is not None
        assert "earlier_model" in entry.seen_in_runs
        assert "attn_wavenet" not in entry.seen_in_runs

    def test_no_previous_proposal_no_crash(self, agent, tmp_path):
        """previous_proposal=None (first iteration) must not crash or produce candidates."""
        inp = InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            previous_proposal=None,
        )
        output = agent.run(inp)
        # No candidates from proposal — only seed/discovery entries possible
        candidate_names = {e.name for e in output.runtime_vocab if e.tier == "candidate"}
        assert "log_fno_gates" not in candidate_names


# ---------------------------------------------------------------------------
# V8 hardening Domain 2b — Degraded interpreter path
# ---------------------------------------------------------------------------


class TestDegradedInterpreterPath:
    """When bridge.generate() raises past the 3-retry envelope, the agent
    must still emit a digest with is_degraded=True so the chain's
    load_latest_knowledge() does not skip the iter and regress the vocab.
    """

    INCOMING_VOCAB: ClassVar[list[dict[str, Any]]] = [
        {
            "name": "dilated_causal_conv",
            "kind": "feature",
            "description": "1-D dilated causal convolution.",
            "tier": "canonical",
            "seen_in_runs": ["seed"],
        },
        {
            "name": "receptive_field",
            "kind": "capability",
            "description": "Effective temporal context window.",
            "tier": "canonical",
            "seen_in_runs": ["seed"],
        },
    ]

    def _make_input(self, tmp_path, run_name="degraded_r1"):
        return InterpretationInput(
            # Step 09a C2 — score-bearing input: the run's bound MetricSpec
            # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
            metric_spec=shipped_spec(),
            summaries=[PUNET_SUMMARY],
            storage={
                "backend": "local",
                "local": {"workspace": str(tmp_path), "run_name": run_name},
            },
            runtime_vocab=self.INCOMING_VOCAB,
            cumulative_information_gain=2.5,
            prediction_outcomes_history={"confirmed": 3, "partial": 1, "refuted": 2},
            # Step 09a C4 — the VERSIONED pools travel the degraded path too.
            prediction_outcomes_by_semantics={
                "metric_order_signsafe_v2": {"confirmed": 1, "partial": 0, "refuted": 1}
            },
            cumulative_information_gain_by_semantics={"metric_order_signsafe_v2": 0.75},
            vocab_link_confirmations={"dilated_causal_conv:receptive_field": ["run_a", "run_b"]},
        )

    def _make_failing_agent(self):
        """Build an agent whose bridge.generate always raises — simulates a
        persistent LLM failure after the Bridge's internal 3-retry envelope."""
        with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
            MockBridge.return_value.generate.side_effect = RuntimeError(
                "LLM unreachable after 3 retries"
            )
            a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            a.bridge = MockBridge.return_value
            return a

    def test_degraded_digest_shape(self, tmp_path):
        """The digest is returned, flagged, empty of invented content and
        labelled -- one failing run, one contract.

        An escaping exception fails the run itself; an unset flag fails
        is_degraded; hallucinated findings synthesised by the fallback
        fail the empty-list assertions; a silently degraded digest fails
        the marker. Carry-forward, persistence and the healthy control
        stay separate below -- they are the parts most likely to break
        WHILE this shape still holds.
        """
        agent = self._make_failing_agent()
        out = agent.run(self._make_input(tmp_path))
        assert isinstance(out, InterpretationOutput)
        assert out.is_degraded is True
        assert out.key_findings == []
        assert out.bottlenecks == []
        assert "DEGRADED" in out.take_home_message

    def test_runtime_vocab_carried_forward_unchanged(self, tmp_path):
        """Degraded output must preserve the incoming runtime_vocab verbatim
        (no growth, no shrinkage) so the next iter's load_latest_knowledge()
        still sees a complete vocab."""
        agent = self._make_failing_agent()
        inp = self._make_input(tmp_path)
        output = agent.run(inp)
        out_names = sorted(e.name for e in output.runtime_vocab)
        in_names = sorted(e["name"] for e in self.INCOMING_VOCAB)
        assert out_names == in_names

    def test_digest_persisted_to_disk(self, tmp_path):
        """The whole point of the fallback is that the digest file exists —
        without it, load_latest_knowledge() skips the iter."""
        agent = self._make_failing_agent()
        inp = self._make_input(tmp_path, run_name="degraded_persist")
        agent.run(inp)
        out_path = tmp_path / "interpretation_degraded_persist.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert data["is_degraded"] is True
        assert {v["name"] for v in data["runtime_vocab"]} == {
            "dilated_causal_conv",
            "receptive_field",
        }

    def test_carry_forward_metrics_preserved(self, tmp_path):
        """Cumulative metrics must pass through unchanged so chain accounting
        does not silently zero out on a degraded iter.

        Step 09a C4 EXTENDS this to the versioned pools. The per-field rule
        never re-bases anything — the structure itself is versioned — so the
        degraded path copies every pool and sum forward untouched. If it
        rewrote or merged them here, a single LLM failure would corrupt the
        prediction record of every iteration before it.
        """
        agent = self._make_failing_agent()
        inp = self._make_input(tmp_path)
        output = agent.run(inp)
        # legacy pool and scalar: unchanged, exactly as before Step 09a
        assert output.cumulative_information_gain == 2.5
        assert output.prediction_outcomes_history == {"confirmed": 3, "partial": 1, "refuted": 2}
        # versioned pools: carried, not merged into the legacy ones
        assert output.prediction_outcomes_by_semantics == {
            "metric_order_signsafe_v2": {"confirmed": 1, "partial": 0, "refuted": 1}
        }
        assert output.cumulative_information_gain_by_semantics == {"metric_order_signsafe_v2": 0.75}
        # and the provenance still states BOTH pool sizes
        assert output.prediction_pool_sizes == {
            "legacy_v1": 6,
            "metric_order_signsafe_v2": 2,
        }
        assert output.vocab_link_confirmations == {
            "dilated_causal_conv:receptive_field": ["run_a", "run_b"]
        }

    def test_healthy_path_default_is_not_degraded(self, agent, tmp_path):
        """Sanity: when the LLM works, is_degraded must default to False."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.is_degraded is False


# ---------------------------------------------------------------------------
# V20 PR D (D-C5) — the scientific aggregate excludes non-authoritative formal
# ---------------------------------------------------------------------------


class TestScientificAggregationReachesTheRealOutput:
    """Reachability, not a unit test of the boundary.

    `execute_tools.scientific_aggregation` is proven separately. What is
    proven HERE is that the interpretation agent actually calls it on the
    production path, that a non-authoritative formal score really is kept
    out of the aggregate the synthesis prompt sees, and that the exclusion
    provenance reaches the output where a report can render it without a
    model's cooperation.
    """

    @staticmethod
    def _verdict(mode, authority, validity) -> dict:
        from core.scientific_authority import ScientificAuthority

        return ScientificAuthority.from_context(
            healthgate_mode=mode,
            declared_result_authority=authority,
            formal_validity=validity,
        ).model_dump()

    def _summary(self, model_type, formal, verdict):
        return ModelRunSummary(
            model_type=model_type,
            run_name="v1",
            status="completed",
            completed_rounds=1,
            best_denoising_score=formal,
            worst_denoising_score=formal,
            formal_score=formal,
            scientific_authority=verdict,
            formal_evidence=disabled_formal_evidence(model_type, formal),
            round_scores=[formal],
            round_conclusions=["c"],
        )

    def test_the_summary_carries_the_formal_records_verdict(self):
        """The PRODUCER half: `tuning_output_to_model_run_summary` must
        attach the verdict of the SAME formal record `formal_score` came
        from, or the consumer has nothing to partition on — and the score
        and its authority could describe different experiments."""
        import inspect

        from nodes.result_interpretation_agent import tuning_output_to_model_run_summary

        src = inspect.getsource(tuning_output_to_model_run_summary)
        assert "formal_rec.scientific_authority" in src, (
            "the summary does not carry the formal record's verdict, so the "
            "aggregation boundary has nothing to partition on"
        )

    def test_the_agent_partitions_before_any_llm_call(self, tmp_path):
        """§4.7: the filtering is deterministic. A model must not be the
        thing that decides — or remembers to mention — the exclusion.

        Step 09a C1b UPGRADE: this was a source-text pin on ``run()``
        (``"partition_for_aggregation(inp.summaries)" in getsource``), which
        the node-local extraction necessarily breaks — the call now lives in
        ``ordering.precompute_evidence``. A source pin would have forced the
        call to stay inline to keep a test green, which is backwards.

        The REACHABILITY form is stronger anyway: it records the real call
        ORDER through the production path. Both events are observed, and the
        partition must be observed FIRST. Stub the authority on the module
        that CALLS it (``ordering``), never on its defining module.
        """
        # `importlib.import_module` on the full dotted path is the repo's
        # convention for reaching a node's private module (the tuner's
        # conftest does the same): the package `__init__` rebinds
        # `sys.modules["nodes.result_interpretation_agent"]` to the MAIN
        # module, so `from nodes.result_interpretation_agent import ordering`
        # would look for an attribute that does not exist there.
        import importlib

        _ordering = importlib.import_module("nodes.result_interpretation_agent.ordering")

        events: list[str] = []
        real_partition = _ordering.partition_for_aggregation

        def _recording_partition(summaries, **kwargs):
            events.append("partition")
            return real_partition(summaries, **kwargs)

        def _recording_generate(system_prompt, user_prompt, **kwargs):
            events.append(f"llm:{kwargs.get('label')}")
            return _llm_dispatch(system_prompt, user_prompt, **kwargs)

        summaries = [
            self._summary("punet", 1.0, self._verdict("blocking", "scientific", "valid")),
            self._summary("fcnet", 99.0, self._verdict("blocking", "diagnostic", "valid")),
        ]
        with (
            patch.object(_ordering, "partition_for_aggregation", _recording_partition),
            patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge,
        ):
            MockBridge.return_value.generate.side_effect = _recording_generate
            agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            agent.bridge = MockBridge.return_value
            agent.run(
                InterpretationInput(
                    # Step 09a C2 — score-bearing input: the run's bound MetricSpec
                    # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
                    metric_spec=shipped_spec(),
                    summaries=summaries,
                    storage={
                        "backend": "local",
                        "local": {"workspace": str(tmp_path), "run_name": "r1"},
                    },
                )
            )

        assert "partition" in events, (
            "the production path never reached partition_for_aggregation — the "
            "aggregation authority is not actually wired into run()"
        )
        assert any(e.startswith("llm:") for e in events), (
            "no LLM call was observed, so 'before any LLM call' is vacuous here"
        )
        assert events.index("partition") < next(
            i for i, e in enumerate(events) if e.startswith("llm:")
        ), f"the partition must precede every LLM call; observed order: {events}"

    def test_a_non_authoritative_formal_score_is_kept_out_of_the_aggregate(self, tmp_path):
        """The behaviour, end to end through the real agent."""
        summaries = [
            self._summary("punet", 1.0, self._verdict("blocking", "scientific", "valid")),
            self._summary("fcnet", 99.0, self._verdict("blocking", "diagnostic", "valid")),
        ]
        out = _run_once(tmp_path, summaries)

        scope = out.scientific_aggregation
        assert scope is not None
        assert scope["included"] == ["punet"]
        assert scope["excluded_count"] == 1
        assert scope["exclusion_reason_counts"] == {"declared_diagnostic": 1}

    def test_the_exclusion_provenance_survives_to_the_output(self, tmp_path):
        """A report renders this; it must not depend on the LLM."""
        out = _run_once(
            tmp_path,
            [self._summary("fcnet", 99.0, self._verdict("blocking", "diagnostic", "valid"))],
        )
        scope = out.scientific_aggregation
        assert scope["all_excluded"] is True
        assert scope["included"] == []

    def test_an_excluded_formal_score_never_reaches_the_synthesis_prompt(self, tmp_path):
        """MUTATION TARGET: the agent stops filtering `per_model_formal`.

        This is the property D-C5 exists for, and it is only observable at
        the PROMPT — the aggregate is a local. An earlier version of this
        class missed it: the fixture set `best_denoising_score` equal to
        `formal_score`, and the renderer only emits a "Formal score" line
        when the two DIFFER, so removing the filter changed nothing
        visible and the mutation survived. The scores here are deliberately
        unequal so the line renders.

        The diagnostic model scores 99.0 against the authoritative 1.0, so
        an unfiltered aggregate would hand the model a non-authoritative
        result as the best formal evidence in the campaign.
        """
        captured: list[str] = []

        def _capture(system_prompt: str, user_prompt: str, **kwargs):
            captured.append(user_prompt)
            return _llm_dispatch(system_prompt, user_prompt, **kwargs)

        good = self._summary("punet", 1.0, self._verdict("blocking", "scientific", "valid"))
        good.best_denoising_score = 0.5  # differs from formal_score -> line renders
        diag = self._summary("fcnet", 99.0, self._verdict("blocking", "diagnostic", "valid"))
        diag.best_denoising_score = 50.0  # differs from formal_score -> line would render

        with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
            MockBridge.return_value.generate.side_effect = _capture
            agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
            agent.bridge = MockBridge.return_value
            agent.run(
                InterpretationInput(
                    # Step 09a C2 — score-bearing input: the run's bound MetricSpec
                    # is REQUIRED (shipped TIDMAD spec is `higher`, assertions unchanged).
                    metric_spec=shipped_spec(),
                    summaries=[good, diag],
                    storage={
                        "backend": "local",
                        "local": {"workspace": str(tmp_path), "run_name": "r1"},
                    },
                )
            )

        synthesis = "\n".join(captured)
        assert "Formal score: 1.0" in synthesis, (
            "the authoritative formal score should still reach the aggregate"
        )
        assert "Formal score: 99.0" not in synthesis, (
            "a non-authoritative formal score reached the synthesis prompt — it "
            "can now inform a scientific claim, which is what D-C5 prevents"
        )
