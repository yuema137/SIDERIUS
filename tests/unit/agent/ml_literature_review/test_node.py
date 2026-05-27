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
        self.responses = responses or {}

    def generate(self, system, user, *, label="", components=None):
        self.calls.append(label)
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
