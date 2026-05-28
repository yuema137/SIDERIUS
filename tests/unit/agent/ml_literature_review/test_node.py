"""
Unit tests for ``nodes/ml_literature_review.py`` — the lit-review node.

Flow-only: the LLMBridge is a fake injected via ``bridge_factory`` and
``paper_resolver_skill.run_skill`` is monkeypatched. No network, no real LLM,
no PDF. Covers Commit 4a of docs/commit_plan_ml_literature_review.md.
"""

from __future__ import annotations

import json

import pytest

import nodes.ml_literature_review as node_mod
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    ConfidenceRubric,
    DynamicSearchConfig,
    LiteratureReviewInput,
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review import MLLiteratureReviewAgent, _sanitize_paper_id

# ---------------------------------------------------------------------------
# Fakes + builders
# ---------------------------------------------------------------------------

_VALID_EXTRACT = {
    "title": "TIDMAD",
    "authors": "A. Author",
    "year": "2024",
    "core_idea": "A denoising benchmark dataset.",
    "architecture_details": "WaveNet: dilated causal convs, full-spectrum.",
    "key_results": "FC-Net 6.43 under frequency-split training.",
    "relevance_to_task": "Only full-spectrum baseline is directly comparable.",
}


class FakeBridge:
    """Records call labels; returns canned responses keyed by label.

    A label's value may be a dict (returned every call) or a list (popped FIFO,
    empty dict once exhausted).
    """

    def __init__(self, *, provider=None, model_id=None, responses=None, **_):
        self.provider = provider
        self.model_id = model_id
        self.calls: list[str] = []
        self.prompts: list[tuple[str, str, str]] = []  # (label, system, user) per call
        self.responses = responses or {}

    def generate(self, system, user, *, label="", components=None):
        self.calls.append(label)
        self.prompts.append((label, system, user))
        r = self.responses.get(label)
        if isinstance(r, list):
            return r.pop(0) if r else {}
        return r if r is not None else {}


class FakeSkill:
    """Stand-in for ``run_skill``; records kwargs, dispatches on ``mode``."""

    def __init__(self, resolve=None, search=None):
        self.calls: list[dict] = []
        self._resolve = resolve
        self._search = search

    def __call__(self, sandbox, **kwargs):
        self.calls.append(kwargs)
        spec = self._resolve if kwargs.get("mode") == "resolve" else self._search
        if callable(spec):
            return spec(kwargs)
        if spec is not None:
            return spec
        return {"status": "error", "data": None, "message": "no canned response"}

    @property
    def resolve_calls(self) -> list[dict]:
        return [c for c in self.calls if c.get("mode") == "resolve"]

    @property
    def search_calls(self) -> list[dict]:
        return [c for c in self.calls if c.get("mode") == "search"]


def _bridge_factory(fake: FakeBridge):
    return lambda **kw: fake


def _interp() -> InterpretationOutput:
    return InterpretationOutput(
        model_types=["punet"],
        model_descriptions={"punet": "Probabilistic U-Net ..."},
        total_experiments=1,
        key_findings=["high-frequency band overfits"],
        bottlenecks=["loss saturates after ~5 epochs"],
        take_home_message="need more temporal depth",
    )


def _input(tmp_path, *, root_papers=None, dynamic=None, run_name="litv1") -> LiteratureReviewInput:
    return LiteratureReviewInput(
        experiment_history=_interp(),
        root_papers=root_papers
        if root_papers is not None
        else [PaperSource(source_type="arxiv", identifier="2406.04378", verbosity=1)],
        dynamic_search=dynamic or DynamicSearchConfig(enabled=False),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name=run_name),
        ),
        run_name=run_name,
        llm_provider="openai",
        llm_model_id="gpt-4o-mini",
    )


def _resolve_ok(full_text="WaveNet uses dilated causal convolutions across the full spectrum."):
    return {
        "status": "ok",
        "data": {
            "source_type": "arxiv",
            "identifier": "2406.04378",
            "s2_metadata": {
                "title": "TIDMAD",
                "year": 2024,
                "abstract": "A dark-matter denoising dataset.",
                "externalIds": {"ArXiv": "2406.04378"},
            },
            "verbosity_achieved": 1,
            "full_text": full_text,
        },
        "message": "PDF resolved via arxiv_fallback",
    }


def _search_ok(kwargs):
    return {
        "status": "ok",
        "data": {
            "query": kwargs.get("query"),
            "results": [
                {
                    "paperId": "p1",
                    "title": "Dilated Conv Denoiser",
                    "year": 2023,
                    "abstract": "A dilated convolution denoiser.",
                    "openAccessPdf": None,
                    "externalIds": {"ArXiv": "2301.00001"},
                }
            ],
            "total": 1,
            "offset": 0,
            "next": None,
        },
        "message": "search returned 1 result(s)",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentCardTrustGuidance:
    """The static AgentCard carries the confidence-rubric legend so the proposer
    can interpret each finding's confidence number (invariant 3)."""

    def test_trust_guidance_carries_rubric_bands(self):
        tg = node_mod._AGENT_CARD.trust_guidance
        assert "0.80" in tg and "0.40" in tg  # band bounds visible to the proposer
        assert "deep-read" in tg  # band criteria carried over

    def test_trust_guidance_within_field_cap(self):
        # AgentCard.trust_guidance max_length is 800; the rendered rubric must fit
        # (construction would otherwise raise at import time).
        assert len(node_mod._AGENT_CARD.trust_guidance) <= 800


class TestFullRun:
    def test_full_run_mocked(self, tmp_path, monkeypatch):
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.search_decision": [
                    {"action": "search", "query": "dilated conv 1d denoising", "reasoning": "gap"},
                    {"action": "done", "reasoning": "enough coverage"},
                ],
                "lit_review.synthesis": {
                    "findings": [
                        {
                            "content": "Dilated causal convs widen receptive field cheaply.",
                            "cite_id": "arxiv:2406.04378",
                            "confidence": 0.8,
                        }
                    ]
                },
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok(), search=_search_ok)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path, dynamic=DynamicSearchConfig(enabled=True, max_rounds=3)))

        assert isinstance(out, LiteratureReviewOutput)
        assert out.agent_card.agent_name == "ml_literature_review"
        # Root paper + one search hit.
        assert len(out.retrieved_papers) == 2
        assert out.search_rounds_used == 1  # one search, then done
        assert len(out.findings) == 1
        assert out.findings[0].kind == "literature"
        assert out.findings[0].source == "ml_literature_review"
        # Root paper got compressed.
        root = next(p for p in out.retrieved_papers if p.paper_id == "arxiv:2406.04378")
        assert root.extract is not None
        assert root.verbosity_achieved == 1


class TestSearchLoopTermination:
    def test_terminates_at_max_rounds(self, tmp_path, monkeypatch):
        # LLM never says done; loop must stop at max_rounds.
        bridge = FakeBridge(
            responses={
                "lit_review.search_decision": {
                    "action": "search",
                    "query": "spectral convolution denoising",
                    "reasoning": "keep going",
                },
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(search=_search_ok)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(
            _input(
                tmp_path,
                root_papers=[],  # isolate the loop
                dynamic=DynamicSearchConfig(enabled=True, max_rounds=3),
            )
        )

        assert out.search_rounds_used == 3
        assert bridge.calls.count("lit_review.search_decision") == 3


class TestRootCache:
    def test_cache_hit_skips_resolver(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        cached = RetrievedPaper(
            paper_id="arxiv:2406.04378",
            source=PaperSource(source_type="arxiv", identifier="2406.04378", verbosity=1),
            s2_metadata={"title": "Cached TIDMAD"},
            extract=PaperExtract(title="Cached TIDMAD"),
            verbosity_achieved=1,
        )
        (cache_dir / f"{_sanitize_paper_id('arxiv:2406.04378')}.json").write_text(
            cached.model_dump_json()
        )

        bridge = FakeBridge(responses={"lit_review.synthesis": {"findings": []}})
        skill = FakeSkill()  # any call would record; assert none happen
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(cache_dir)
        )
        out = agent.run(_input(tmp_path))  # dynamic disabled

        assert skill.resolve_calls == []  # resolver NOT called on cache hit
        assert len(out.retrieved_papers) == 1
        assert out.retrieved_papers[0].extract.title == "Cached TIDMAD"

    def test_cache_miss_calls_resolver_and_writes_cache(self, tmp_path, monkeypatch):
        cache_dir = tmp_path / "cache"
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(cache_dir)
        )
        agent.run(_input(tmp_path))

        assert len(skill.resolve_calls) == 1
        cache_file = cache_dir / f"{_sanitize_paper_id('arxiv:2406.04378')}.json"
        assert cache_file.exists()
        # Cache round-trips and carries the compressed extract.
        rp = RetrievedPaper.model_validate_json(cache_file.read_text())
        assert rp.verbosity_achieved == 1
        assert rp.extract is not None


class TestCompressionFallback:
    def test_malformed_extract_degrades_without_raising(self, tmp_path, monkeypatch):
        bridge = FakeBridge(
            responses={
                # Wrong-typed field → PaperExtract.model_validate raises → caught.
                "lit_review.paper_extract": {"title": ["not", "a", "string"]},
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path))  # dynamic disabled

        root = out.retrieved_papers[0]
        assert root.extract is None
        assert root.verbosity_achieved == 0  # degraded from requested 1


class TestEscalation:
    def test_escalate_deep_reads_a_search_hit(self, tmp_path, monkeypatch):
        # Round 0: search (1 hit at v0). Round 1: escalate that hit → v1 extract.
        bridge = FakeBridge(
            responses={
                "lit_review.search_decision": [
                    {"action": "search", "query": "dilated conv denoising", "reasoning": "gap"},
                    {
                        "action": "escalate",
                        "paper_id": "arxiv:2301.00001",
                        "verbosity": 1,
                        "reasoning": "directly addresses the bottleneck",
                    },
                    {"action": "done", "reasoning": "done"},
                ],
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )

        def _resolve(kw):
            # Escalation resolves the search hit's arxiv id at v1.
            assert kw["identifier"] == "2301.00001"
            return {
                "status": "ok",
                "data": {
                    "s2_metadata": {"title": "Dilated Conv Denoiser", "year": 2023},
                    "verbosity_achieved": 1,
                    "full_text": "dilated causal convolution body text",
                },
                "message": "ok",
            }

        skill = FakeSkill(resolve=_resolve, search=_search_ok)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(
            _input(
                tmp_path,
                root_papers=[],
                dynamic=DynamicSearchConfig(enabled=True, max_rounds=5, escalation_allowed=True),
            )
        )

        assert out.search_rounds_used == 1  # one search; escalations don't consume the round budget
        hit = next(p for p in out.retrieved_papers if p.paper_id == "arxiv:2301.00001")
        assert hit.verbosity_achieved == 1
        assert hit.extract is not None


class TestStorageDump:
    def test_output_written_and_roundtrips(self, tmp_path, monkeypatch):
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        agent.run(_input(tmp_path, run_name="dump_test"))

        out_path = tmp_path / "ml_literature_review_dump_test.json"
        assert out_path.exists()
        reloaded = LiteratureReviewOutput.model_validate_json(out_path.read_text())
        assert reloaded.run_name == "dump_test"
        assert (
            json.loads(out_path.read_text())["agent_card"]["agent_name"] == "ml_literature_review"
        )


class TestSynthesis:
    """Synthesis-call behavior: valid items, empty findings, cite_id soft-drop."""

    def _run(self, tmp_path, monkeypatch, synthesis_response):
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": synthesis_response,
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        return agent.run(_input(tmp_path))  # dynamic disabled → retrieved = [root]

    def test_valid_findings_with_confidence(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "findings": [
                    {
                        "content": "Given high-freq overfitting, dilated convs help. "
                        "(confidence 0.7: single full-spectrum paper)",
                        "cite_id": "arxiv:2406.04378",
                        "confidence": 0.7,
                    }
                ]
            },
        )
        assert len(out.findings) == 1
        item = out.findings[0]
        assert item.confidence == 0.7
        assert item.kind == "literature"
        assert item.source == "ml_literature_review"
        assert item.cite_id == "arxiv:2406.04378"

    def test_no_relevant_papers_yields_empty_findings(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch, {"findings": []})
        assert out.findings == []  # empty is valid output and must not raise

    def test_unmatched_cite_id_is_soft_dropped(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "findings": [
                    {"content": "well cited", "cite_id": "arxiv:2406.04378", "confidence": 0.6},
                    {
                        "content": "hallucinated cite",
                        "cite_id": "arxiv:9999.99999",
                        "confidence": 0.9,
                    },
                ]
            },
        )
        # Only the well-cited item survives; the bad cite_id is dropped, not raised.
        assert len(out.findings) == 1
        assert out.findings[0].cite_id == "arxiv:2406.04378"


class TestAbstractOnlyConfidenceClamp:
    """A finding citing a verbosity-0 (abstract-only) paper is capped at the
    rubric's abstract_only_ceiling; deep-read (v1+) citations are untouched.

    The root paper (arxiv:2406.04378) resolves at v1 (deep-read); the search hit
    (arxiv:2301.00001) stays at v0 (abstract-only). Citing both lets one test
    exercise the clamp branch and the pass-through branch together.
    """

    def _run(self, tmp_path, monkeypatch, findings, *, rubric=None):
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.search_decision": [
                    {"action": "search", "query": "dilated conv 1d denoising", "reasoning": "gap"},
                    {"action": "done", "reasoning": "enough"},
                ],
                "lit_review.synthesis": {"findings": findings},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok(), search=_search_ok)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        inp = _input(tmp_path, dynamic=DynamicSearchConfig(enabled=True, max_rounds=3))
        if rubric is not None:
            inp = inp.model_copy(update={"confidence_rubric": rubric})
        return agent.run(inp)

    def test_v0_over_ceiling_clamped_v1_kept(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            [
                {"content": "deep-read paper", "cite_id": "arxiv:2406.04378", "confidence": 0.85},
                {
                    "content": "abstract-only paper",
                    "cite_id": "arxiv:2301.00001",
                    "confidence": 0.85,
                },
            ],
        )
        by_cite = {f.cite_id: f.confidence for f in out.findings}
        assert by_cite["arxiv:2406.04378"] == 0.85  # v1 deep-read: untouched
        assert by_cite["arxiv:2301.00001"] == 0.79  # v0 abstract-only: clamped to ceiling

    def test_v0_below_ceiling_unchanged(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            [{"content": "modest", "cite_id": "arxiv:2301.00001", "confidence": 0.6}],
        )
        assert out.findings[0].confidence == 0.6  # below ceiling → no clamp

    def test_custom_ceiling_respected(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            [{"content": "abstract-only", "cite_id": "arxiv:2301.00001", "confidence": 0.85}],
            rubric=ConfidenceRubric(abstract_only_ceiling=0.5),
        )
        assert out.findings[0].confidence == 0.5  # node reads the ceiling from the rubric


class TestSearchBridgeRouting:
    def test_search_decision_uses_search_bridge(self, tmp_path, monkeypatch):
        # search_llm_* set -> the search-decision call routes to the search bridge
        # (deepseek), while compression + synthesis stay on the main bridge.
        main = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )
        search = FakeBridge(
            responses={"lit_review.search_decision": {"action": "done", "reasoning": "enough"}}
        )

        def factory(**kw):
            return search if kw.get("provider") == "deepseek" else main

        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=factory, root_cache_dir=str(tmp_path / "cache")
        )
        inp = _input(tmp_path, dynamic=DynamicSearchConfig(enabled=True, max_rounds=2))
        inp = inp.model_copy(
            update={"search_llm_provider": "deepseek", "search_llm_model_id": "deepseek-v4-pro"}
        )
        agent.run(inp)

        # search-decision -> search bridge only; compression + synthesis -> main only
        assert "lit_review.search_decision" in search.calls
        assert "lit_review.search_decision" not in main.calls
        assert "lit_review.paper_extract" in main.calls
        assert "lit_review.synthesis" in main.calls
        assert search.calls.count("lit_review.search_decision") >= 1

    def test_no_override_uses_single_bridge(self, tmp_path, monkeypatch):
        # Without search_llm_*, the same bridge handles all calls (fallback).
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.search_decision": {"action": "done", "reasoning": "x"},
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        agent.run(_input(tmp_path, dynamic=DynamicSearchConfig(enabled=True, max_rounds=2)))
        # all three call labels landed on the one bridge
        assert {
            "lit_review.search_decision",
            "lit_review.paper_extract",
            "lit_review.synthesis",
        } <= set(bridge.calls)


class TestConfidenceRubricWiring:
    def test_custom_rubric_reaches_synthesis_prompt(self, tmp_path, monkeypatch):
        from agent.schemas.literature_review import ConfidenceBand, ConfidenceRubric

        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)

        rubric = ConfidenceRubric(
            bands=[ConfidenceBand(lower=0.9, upper=1.0, criteria="DISTINCTIVE-RUBRIC-MARKER")],
            omit_below=0.9,
        )
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        inp = _input(tmp_path).model_copy(update={"confidence_rubric": rubric})
        agent.run(inp)

        synth_prompts = [s for (lbl, s, u) in bridge.prompts if lbl == "lit_review.synthesis"]
        assert synth_prompts, "synthesis call never happened"
        assert "DISTINCTIVE-RUBRIC-MARKER" in synth_prompts[0]  # custom rubric injected by the node


class TestZeroHitFeedback:
    def test_prior_zero_hit_query_fed_into_next_round(self, tmp_path, monkeypatch):
        # Round 0 search returns 0 hits; round 1's search-decision prompt must
        # carry that query + "0 hits" + the "too specific" annotation (Fix C b).
        bridge = FakeBridge(
            responses={
                "lit_review.search_decision": [
                    {"action": "search", "query": "narrow query alpha", "reasoning": "r"},
                    {"action": "search", "query": "broader beta", "reasoning": "r"},
                    {"action": "done", "reasoning": "done"},
                ],
                "lit_review.synthesis": {"findings": []},
            }
        )

        def _search(kw):
            q = kw.get("query")
            results = (
                []
                if q == "narrow query alpha"
                else [
                    {
                        "paperId": "p1",
                        "title": "T",
                        "year": 2023,
                        "abstract": "a",
                        "openAccessPdf": None,
                        "externalIds": {"ArXiv": "2301.00001"},
                    }
                ]
            )
            return {
                "status": "ok",
                "data": {
                    "query": q,
                    "results": results,
                    "total": len(results),
                    "offset": 0,
                    "next": None,
                },
                "message": "ok",
            }

        skill = FakeSkill(search=_search)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        agent.run(
            _input(
                tmp_path, root_papers=[], dynamic=DynamicSearchConfig(enabled=True, max_rounds=3)
            )
        )

        sd_user_prompts = [
            u for (lbl, s, u) in bridge.prompts if lbl == "lit_review.search_decision"
        ]
        assert len(sd_user_prompts) >= 2
        # Round 0 prompt has no feedback block yet.
        assert "Queries already tried this run" not in sd_user_prompts[0]
        # Round 1 prompt carries round 0's whiffed query + annotation.
        assert "narrow query alpha" in sd_user_prompts[1]
        assert "0 hits" in sd_user_prompts[1]
        assert "too specific" in sd_user_prompts[1]


class TestYearOverride:
    def test_year_overridden_from_s2_metadata(self, tmp_path, monkeypatch):
        # LLM extracts "2023" from degraded PDF; S2 metadata says 2020. The node
        # must overwrite the extract year with the authoritative S2 value.
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT, year="2023"),
                "lit_review.synthesis": {"findings": []},
            }
        )

        def _resolve(kw):
            r = _resolve_ok()
            r["data"]["s2_metadata"]["year"] = 2020
            return r

        skill = FakeSkill(resolve=_resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path))

        root = out.retrieved_papers[0]
        assert root.extract is not None
        assert root.extract.year == "2020"  # S2 year wins over the LLM's "2023"


class TestEscalationCap:
    def test_caps_escalations_per_round(self, tmp_path, monkeypatch):
        # One search returns 3 hits; the LLM requests 3 escalations in that round
        # — only 2 (the cap) execute; the third is logged and dropped.
        bridge = FakeBridge(
            responses={
                "lit_review.search_decision": [
                    {"action": "search", "query": "denoising", "reasoning": "gap"},
                    {
                        "action": "escalate",
                        "paper_id": "arxiv:3001.00001",
                        "verbosity": 1,
                        "reasoning": "a",
                    },
                    {
                        "action": "escalate",
                        "paper_id": "arxiv:3001.00002",
                        "verbosity": 1,
                        "reasoning": "b",
                    },
                    {
                        "action": "escalate",
                        "paper_id": "arxiv:3001.00003",
                        "verbosity": 1,
                        "reasoning": "c",
                    },
                    {"action": "done", "reasoning": "done"},
                ],
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )

        def _search_three(kwargs):
            return {
                "status": "ok",
                "data": {
                    "query": kwargs.get("query"),
                    "results": [
                        {
                            "paperId": f"p{i}",
                            "title": f"Paper {i}",
                            "year": 2023,
                            "abstract": "a",
                            "openAccessPdf": None,
                            "externalIds": {"ArXiv": f"3001.0000{i}"},
                        }
                        for i in (1, 2, 3)
                    ],
                    "total": 3,
                    "offset": 0,
                    "next": None,
                },
                "message": "ok",
            }

        def _resolve(kw):
            return {
                "status": "ok",
                "data": {
                    "s2_metadata": {"title": "x"},
                    "verbosity_achieved": 1,
                    "full_text": "body text",
                },
                "message": "ok",
            }

        skill = FakeSkill(resolve=_resolve, search=_search_three)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(
            _input(
                tmp_path,
                root_papers=[],
                dynamic=DynamicSearchConfig(
                    enabled=True,
                    max_rounds=5,
                    escalation_allowed=True,
                    max_escalations_per_round=2,
                ),
            )
        )

        # Only 2 of the 3 escalations executed → exactly 2 resolve calls.
        assert len(skill.resolve_calls) == 2
        escalated = [p for p in out.retrieved_papers if p.verbosity_achieved == 1]
        assert len(escalated) == 2
        not_escalated = [p for p in out.retrieved_papers if p.verbosity_achieved == 0]
        assert len(not_escalated) == 1  # the third hit stayed metadata-only
        assert out.search_rounds_used == 1  # only the search counts as a round
