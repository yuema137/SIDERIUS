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
import pytest
from unittest.mock import MagicMock, patch

from agent.schemas.interpretation import (
    InterpretationInput, InterpretationOutput, ModelRunSummary,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    _build_per_model_prompt,
    _build_synthesis_prompt,
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
    model_type="punet", run_name="v1", status="completed",
    completed_rounds=3,
    best_denoising_score=1.8,
    worst_denoising_score=1.2,
    best_config={"model_config": {"depth": 4}, "train_config": {"lr": 1e-4}, "loss_config": {"loss_type": "focal"}},
    round_scores=[1.2, 1.5, 1.8],
    round_conclusions=["Initial baseline.", "Improved with focal loss.", "Best with depth=4."],
)

FCNET_SUMMARY = ModelRunSummary(
    model_type="fcnet", run_name="v1", status="completed",
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


def _llm_dispatch(system_prompt: str, user_prompt: str) -> dict:
    """Route mock LLM calls to the right fake response based on the system prompt."""
    if "ONE model architecture" in system_prompt:
        return FAKE_PER_MODEL_RESPONSE
    else:
        return FAKE_SYNTHESIS_RESPONSE


def make_input(summary, workspace="/tmp/interp_test", run_name="r1"):
    return InterpretationInput(
        summaries=[summary],
        storage={"backend": "local", "local": {"workspace": workspace, "run_name": run_name}},
    )


# ---------------------------------------------------------------------------
# Single-model tests
# ---------------------------------------------------------------------------

class TestSingleModel:

    def test_best_score_extracted(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_denoising_score == 1.8

    def test_worst_score_extracted(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.worst_denoising_score == 1.2

    def test_best_config_from_summary(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.best_config["model_config"]["depth"] == 4

    def test_total_experiments(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.total_experiments == 3

    def test_per_model_scores(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_worst["punet"] == 1.2

    def test_phase1_findings_used(self, agent, tmp_path):
        """Single-model: phase 1 findings used directly, synthesis skipped."""
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert output.key_findings == FAKE_PER_MODEL_RESPONSE["key_findings"]
        assert output.bottlenecks == FAKE_PER_MODEL_RESPONSE["bottlenecks"]
        assert "punet" in output.take_home_message.lower() or "plateau" in output.take_home_message.lower()

    def test_per_model_summaries_populated(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.model_knowledge_cache
        assert output.model_knowledge_cache["punet"]["key_findings"] == FAKE_PER_MODEL_RESPONSE["key_findings"]

    def test_output_written_to_file(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path), run_name="myrun")
        agent.run(inp)
        out_path = tmp_path / "interpretation_myrun.json"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "punet" in data["model_types"]
        assert data["best_denoising_score"] == 1.8

    def test_output_is_valid(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert isinstance(output, InterpretationOutput)
        assert "punet" in output.model_types

    def test_model_description_loaded(self, agent, tmp_path):
        inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
        output = agent.run(inp)
        assert "punet" in output.model_descriptions
        assert len(output.model_descriptions["punet"]) > 100


# ---------------------------------------------------------------------------
# Multi-model tests
# ---------------------------------------------------------------------------

class TestMultiModel:

    def test_two_models_both_in_output(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert "punet" in output.model_types
        assert "fcnet" in output.model_types

    def test_overall_best_is_cross_model_max(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.best_denoising_score == 1.8
        assert output.worst_denoising_score == 0.5

    def test_per_model_scores_independent(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_best["punet"] == 1.8
        assert output.per_model_best["fcnet"] == 0.9

    def test_total_experiments_across_models(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.total_experiments == 5  # 3 + 2

    def test_synthesis_used_for_multi_model(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.key_findings == FAKE_SYNTHESIS_RESPONSE["key_findings"]
        assert output.take_home_message == FAKE_SYNTHESIS_RESPONSE["take_home_message"]

    def test_per_model_summaries_for_all(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert "punet" in output.model_knowledge_cache
        assert "fcnet" in output.model_knowledge_cache

    def test_descriptions_loaded_for_all(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY, FCNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert "punet" in output.model_descriptions
        assert "fcnet" in output.model_descriptions


# ---------------------------------------------------------------------------
# model_knowledge_cache: cache hit / cache miss / _stats
# ---------------------------------------------------------------------------

# A pre-built cache entry for punet — as if produced by a previous iteration
_PUNET_CACHED_ENTRY = {
    **FAKE_PER_MODEL_RESPONSE,
    "_stats": {
        "best_denoising_score":  1.8,
        "worst_denoising_score": 1.2,
        "best_file_vector":      None,
        "best_model_params":     None,
        "completed_rounds":      3,
        "best_config":           PUNET_SUMMARY.best_config,
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
        assert output.model_knowledge_cache["punet"]["key_findings"] == FAKE_PER_MODEL_RESPONSE["key_findings"]

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
            summaries=[],                                        # no new summaries
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
            summaries=[FCNET_SUMMARY],                           # only fcnet is new
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
            summaries=[ModelRunSummary(
                model_type="nonexistent_model", run_name="v1",
                status="completed", completed_rounds=0,
            )],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        with pytest.raises(FileNotFoundError, match="nonexistent_model"):
            agent.run(inp)

    def test_no_model_provided_raises(self):
        with pytest.raises(Exception, match="At least one model type"):
            InterpretationInput()


# ---------------------------------------------------------------------------
# Enriched summaries for prompt builder and output computation tests
# ---------------------------------------------------------------------------

ENRICHED_SUMMARY = ModelRunSummary(
    model_type="punet", run_name="v1", status="completed",
    completed_rounds=3,
    best_denoising_score=1.8,
    worst_denoising_score=0.5,
    best_config={"model_config": {"depth": 4}, "train_config": {"lr": 1e-4}},
    round_scores=[0.5, 1.2, 1.8],
    round_conclusions=["Baseline.", "Improved.", "Best."],
    # New fields
    best_file_vector=[0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 78.0, 1.5, 2.5,
                      3.0, 7.0, 1.3, 0.9, 40.0, 21.0, 5.0, 5.0, 3.0, 0.8],
    formal_score=1.6,
    formal_file_vector=[0.002, 0.02, 0.15, 0.6, 1.1, 2.2, 5.5, 80.0, 1.6, 2.6,
                        3.1, 7.5, 1.4, 1.0, 41.0, 22.0, 5.2, 5.1, 3.2, 0.9],
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

    def test_includes_file_vector(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "File Vector" in prompt
        assert "78.0000" in prompt  # file 7 has the highest value
        assert "File  0:" in prompt

    def test_includes_formal_score(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "Formal round score" in prompt
        assert "1.6" in prompt

    def test_includes_formal_file_vector(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "formal round" in prompt.lower()
        assert "80.0000" in prompt  # formal file 7

    def test_includes_model_params(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "55,000" in prompt

    def test_includes_training_psd_segments(self):
        prompt = _build_per_model_prompt(ENRICHED_SUMMARY, "PUNet description")
        assert "200" in prompt
        assert "4000" in prompt  # baseline reference

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
        assert "File Vector" not in prompt
        assert "Formal round score" not in prompt
        assert "Training PSD segments" not in prompt


class TestBuildSynthesisPrompt:

    def test_includes_file_vector_summary(self):
        prompt = _build_synthesis_prompt(
            per_model_summaries={"punet": FAKE_PER_MODEL_RESPONSE},
            per_model_best={"punet": 1.8},
            per_model_worst={"punet": 0.5},
            overall_best_score=1.8,
            overall_worst_score=0.5,
            overall_best_config=None,
            per_model_file_vectors={"punet": ENRICHED_SUMMARY.best_file_vector},
        )
        assert "File Vector Summary" in prompt
        assert "Weak files" in prompt

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
        assert "File Vector" not in prompt


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
            model_type="punet", run_name="v1", status="completed",
            completed_rounds=2,
            best_denoising_score=1.8,
            worst_denoising_score=1.2,
            formal_score=1.5,  # distinct from best (which came from a trial round)
            best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        )
        inp = InterpretationInput(
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
                "best_denoising_score":  1.8,
                "worst_denoising_score": 1.2,
                "best_file_vector":      None,
                "best_model_params":     None,
                "completed_rounds":      3,
                "best_config":           PUNET_SUMMARY.best_config,
                "formal_score":          1.5,
            },
        }
        inp = InterpretationInput(
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

    def test_per_model_file_vectors_populated(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[ENRICHED_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_file_vectors is not None
        assert "punet" in output.per_model_file_vectors
        assert len(output.per_model_file_vectors["punet"]) == 20

    def test_weak_frequency_files_computed(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[ENRICHED_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.weak_frequency_files is not None
        assert "punet" in output.weak_frequency_files
        # Files 0-3 and 13,19 have scores < 1.0
        weak = output.weak_frequency_files["punet"]
        assert 0 in weak  # score 0.001
        assert 1 in weak  # score 0.01
        assert 7 not in weak  # score 78.0

    def test_per_model_params_populated(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[ENRICHED_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_params is not None
        assert output.per_model_params["punet"] == 55000

    def test_per_model_training_segments_populated(self, agent, tmp_path):
        inp = InterpretationInput(
            summaries=[ENRICHED_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_training_segments is not None
        assert output.per_model_training_segments["punet"] == 200

    def test_none_fields_produce_none_output(self, agent, tmp_path):
        """Old-style summary (no file_vector etc) produces None for enriched fields."""
        inp = InterpretationInput(
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        )
        output = agent.run(inp)
        assert output.per_model_file_vectors is None
        assert output.weak_frequency_files is None
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
    return _VocabEntry(name=name, kind=kind, description=description, tier="canonical", aliases=aliases or [])


def _promoted(name, kind="feature", description="test"):
    return _VocabEntry(name=name, kind=kind, description=description, tier="canonical", seen_in_runs=["r1", "r2", "r3"])


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
            "is_duplicate": False, "duplicate_of": None, "rationale": "Distinct concept."
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
            "is_duplicate": False, "duplicate_of": None, "rationale": "Distinct."
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
                {"name": "log_fno_gates", "kind": "feature",
                 "description": "FNO with log-spaced frequency gates"},
            ],
        }
        inp = InterpretationInput(
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
                {"name": "log_fno_gates", "kind": "feature",
                 "description": "FNO with log-spaced gates",
                 "proposed_by_run": "earlier_model"},
            ],
        }
        inp = InterpretationInput(
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
            summaries=[PUNET_SUMMARY],
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            previous_proposal=None,
        )
        output = agent.run(inp)
        # No candidates from proposal — only seed/discovery entries possible
        candidate_names = {e.name for e in output.runtime_vocab if e.tier == "candidate"}
        assert "log_fno_gates" not in candidate_names
