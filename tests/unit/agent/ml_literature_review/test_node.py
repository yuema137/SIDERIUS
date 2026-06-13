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
                            "source_ref": "arxiv:2406.04378",
                            "content_paper_id": "arxiv:2406.04378",
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

    def test_escalate_returns_ok_when_verbosity_raised(self, tmp_path, monkeypatch):
        # Fix 3 (Commit 6.5b-2): _escalate now returns a 3-state status.
        # When run_skill resolves with new full_text AND _compress produces
        # an extract, verbosity_achieved is raised → status "ok". The
        # test calls _escalate directly (skipping agent.run()) so it
        # exercises only the per-escalation contract, not the search-loop
        # bookkeeping.
        bridge = FakeBridge(
            responses={"lit_review.paper_extract": dict(_VALID_EXTRACT)},
        )
        skill = FakeSkill(
            resolve=lambda kw: {
                "status": "ok",
                "data": {
                    "s2_metadata": {"title": "T", "year": 2023},
                    "verbosity_achieved": 1,
                    "full_text": "real body text",
                },
                "message": "ok",
            }
        )
        monkeypatch.setattr(node_mod, "run_skill", skill)

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        # Set self.bridge manually since we're not going through run() —
        # it's what _compress (called inside _escalate) reads.
        agent.bridge = bridge

        target = RetrievedPaper(
            paper_id="arxiv:1",
            source=PaperSource(source_type="arxiv", identifier="1"),
            verbosity_achieved=0,
        )

        status = agent._escalate(target, 1)

        assert status == "ok"
        assert target.verbosity_achieved == 1
        assert target.extract is not None

    def test_escalate_returns_noop_on_empty_full_text_and_error_on_failure(
        self, tmp_path, monkeypatch
    ):
        # Fix 3 (Commit 6.5b-2): _escalate's 3-state status covers two
        # degenerate outcomes besides "ok":
        #   (a) "noop"  — the resolve call succeeded but returned no new
        #                 full_text (paper already at requested verbosity,
        #                 or the fetcher dropped the body). verbosity_achieved
        #                 stays at its pre-call value.
        #   (b) "error" — the resolve call failed outright (PDF 404, S2
        #                 down, etc.). target.error is set; the LLM should
        #                 not retry this paper.
        # Both share the budget-charge semantics (Decision 2); the
        # _run_search_loop side of that contract lands as the 6.5b-3 test
        # gate. Here we exercise only _escalate's return + mutation
        # contract.
        bridge = FakeBridge(responses={})  # _compress never gets called
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        agent.bridge = bridge

        # --- Sub-case (a): noop — resolve ok but no full_text ---
        monkeypatch.setattr(
            node_mod,
            "run_skill",
            FakeSkill(
                resolve=lambda kw: {
                    "status": "ok",
                    "data": {
                        "s2_metadata": {"title": "T", "year": 2023},
                        "verbosity_achieved": 1,
                        # full_text deliberately omitted (None / empty)
                    },
                    "message": "ok-no-body",
                }
            ),
        )
        target_noop = RetrievedPaper(
            paper_id="arxiv:noop",
            source=PaperSource(source_type="arxiv", identifier="noop"),
            verbosity_achieved=0,
        )
        assert agent._escalate(target_noop, 1) == "noop"
        assert target_noop.verbosity_achieved == 0  # unchanged
        assert target_noop.extract is None  # _compress never ran

        # --- Sub-case (b): error — resolve failed ---
        monkeypatch.setattr(
            node_mod,
            "run_skill",
            FakeSkill(
                resolve=lambda kw: {
                    "status": "error",
                    "data": None,
                    "message": "HTTP 404 on the PDF URL",
                }
            ),
        )
        target_err = RetrievedPaper(
            paper_id="arxiv:err",
            source=PaperSource(source_type="arxiv", identifier="err"),
            verbosity_achieved=0,
        )
        assert agent._escalate(target_err, 1) == "error"
        assert target_err.error == "HTTP 404 on the PDF URL"
        assert target_err.verbosity_achieved == 0


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
    """Synthesis-call behavior: valid items, empty findings, source_ref soft-drop."""

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
                        "source_ref": "arxiv:2406.04378",
                        "content_paper_id": "arxiv:2406.04378",
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
        assert item.source_ref == "arxiv:2406.04378"

    def test_no_relevant_papers_yields_empty_findings(self, tmp_path, monkeypatch):
        out = self._run(tmp_path, monkeypatch, {"findings": []})
        assert out.findings == []  # empty is valid output and must not raise

    def test_unmatched_cite_id_is_soft_dropped(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            {
                "findings": [
                    {
                        "content": "well cited",
                        "source_ref": "arxiv:2406.04378",
                        "content_paper_id": "arxiv:2406.04378",
                        "confidence": 0.6,
                    },
                    {
                        "content": "hallucinated cite",
                        "source_ref": "arxiv:9999.99999",
                        # content_paper_id matches the (invalid) source_ref so the
                        # test exercises only the source_ref check, not the new
                        # content_paper_id hook (which would also drop it).
                        "content_paper_id": "arxiv:9999.99999",
                        "confidence": 0.9,
                    },
                ]
            },
        )
        # Only the well-cited item survives; the bad source_ref is dropped, not raised.
        assert len(out.findings) == 1
        assert out.findings[0].source_ref == "arxiv:2406.04378"


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
                {
                    "content": "deep-read paper",
                    "source_ref": "arxiv:2406.04378",
                    "content_paper_id": "arxiv:2406.04378",
                    "confidence": 0.85,
                },
                {
                    "content": "abstract-only paper",
                    "source_ref": "arxiv:2301.00001",
                    "content_paper_id": "arxiv:2301.00001",
                    "confidence": 0.85,
                },
            ],
        )
        by_cite = {f.source_ref: f.confidence for f in out.findings}
        assert by_cite["arxiv:2406.04378"] == 0.85  # v1 deep-read: untouched
        assert by_cite["arxiv:2301.00001"] == 0.79  # v0 abstract-only: clamped to ceiling

    def test_v0_below_ceiling_unchanged(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            [
                {
                    "content": "modest",
                    "source_ref": "arxiv:2301.00001",
                    "content_paper_id": "arxiv:2301.00001",
                    "confidence": 0.6,
                }
            ],
        )
        assert out.findings[0].confidence == 0.6  # below ceiling → no clamp

    def test_custom_ceiling_respected(self, tmp_path, monkeypatch):
        out = self._run(
            tmp_path,
            monkeypatch,
            [
                {
                    "content": "abstract-only",
                    "source_ref": "arxiv:2301.00001",
                    "content_paper_id": "arxiv:2301.00001",
                    "confidence": 0.85,
                }
            ],
            rubric=ConfidenceRubric(abstract_only_ceiling=0.5),
        )
        assert out.findings[0].confidence == 0.5  # node reads the ceiling from the rubric


class TestSourceTypeRouting:
    """The node routes all four source types through
    _resolve_root_paper -> cache -> compress identically. arxiv is exercised by
    the full-run / cache tests + the canonical trace; this covers doi / local /
    openreview at the node level: paper_id construction, skill dispatch, v1
    compression, and a filesystem-safe cache round-trip."""

    @pytest.mark.parametrize(
        ("source_type", "identifier"),
        [
            ("doi", "10.1109/TGRS.2020.3036065"),
            ("openreview", "https://openreview.net/forum?id=AbC123"),
            ("local", "reference_data/papers/foo_paper.pdf"),
        ],
    )
    def test_root_paper_routes_caches_and_compresses(
        self, tmp_path, monkeypatch, source_type, identifier
    ):
        paper_id = f"{source_type}:{identifier}"

        def resolve(kw):
            return {
                "status": "ok",
                "data": {
                    "source_type": source_type,
                    "identifier": identifier,
                    # local sources carry no S2 metadata; remote ones do
                    "s2_metadata": (
                        None if source_type == "local" else {"title": "P", "year": 2023}
                    ),
                    "verbosity_achieved": 1,
                    "full_text": "A denoising method described in prose.",
                },
                "message": "resolved",
            }

        skill = FakeSkill(resolve=resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )
        cache_dir = tmp_path / "cache"
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(cache_dir)
        )
        out = agent.run(
            _input(
                tmp_path,
                root_papers=[
                    PaperSource(source_type=source_type, identifier=identifier, verbosity=1)
                ],
            )
        )

        # 1. skill dispatched with the right source_type + identifier
        rc = skill.resolve_calls
        assert rc and rc[0]["source_type"] == source_type
        assert rc[0]["identifier"] == identifier
        # 2. paper_id built as "{source_type}:{identifier}", compressed to v1
        rp = next(p for p in out.retrieved_papers if p.paper_id == paper_id)
        assert rp.verbosity_achieved == 1
        assert rp.extract is not None
        # 3. cache written at the sanitized (filesystem-safe) path + round-trips
        cache_file = cache_dir / f"{_sanitize_paper_id(paper_id)}.json"
        assert cache_file.exists()
        assert RetrievedPaper.model_validate_json(cache_file.read_text()).paper_id == paper_id

    def test_sanitize_paper_id_is_filesystem_safe(self):
        # The cache filename must contain no path-unsafe chars (: / ? =) for any
        # source type; dots and hyphens are preserved.
        assert (
            _sanitize_paper_id("doi:10.1109/TGRS.2020.3036065") == "doi_10.1109_TGRS.2020.3036065"
        )
        assert _sanitize_paper_id("local:reference_data/papers/foo.pdf") == (
            "local_reference_data_papers_foo.pdf"
        )
        orv = _sanitize_paper_id("openreview:https://openreview.net/forum?id=AbC")
        for bad in (":", "/", "?", "="):
            assert bad not in orv
        assert orv.startswith("openreview_https")


class TestHeadingNormalization:
    """`_normalize_finding_content_headings` rewrites known LLM heading slips
    (e.g. DeepSeek's `**Adaption:**` typo) to canonical form, leaving canonical
    headings untouched. The synthesis prompt at findings_verbosity=1 instructs
    the LLM to use canonical headings verbatim; this normalizer is the
    backstop for occasional model variance."""

    def test_adaption_variant_normalized_canonical_unchanged(self):
        from nodes.ml_literature_review import _normalize_finding_content_headings

        variant = (
            "**Implication:** widen receptive field.\n"
            "**Mechanism:** dilated convolutions.\n"
            "**Adaption:** stack three dilated blocks.\n"  # the slip
            "(rationale: on-domain.)"
        )
        normalized = _normalize_finding_content_headings(variant)
        assert "**Adaption:**" not in normalized
        assert "**Adaptation:** stack three dilated blocks." in normalized

        canonical = (
            "**Implication:** widen receptive field.\n"
            "**Mechanism:** dilated convolutions.\n"
            "**Adaptation:** stack three dilated blocks.\n"
            "(rationale: on-domain.)"
        )
        assert _normalize_finding_content_headings(canonical) == canonical


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


# ---------------------------------------------------------------------------
# extraction_method propagation (Commit 2c-b)
# ---------------------------------------------------------------------------


class TestExtractionMethodPropagation:
    """The skill emits ``extraction_method`` on the resolve response; the node
    reads it from ``data`` and stamps it onto ``PaperExtract.extraction_method``
    AFTER LLM validation (the LLM is not allowed to mint or overwrite this
    trust signal). The instruction block injected into the prompt also varies
    with the extraction method so the LLM knows what input quality to expect.
    """

    @pytest.mark.parametrize(
        "method",
        ["arxiv_source", "pdfplumber_llm", "abstract_only"],
    )
    def test_method_from_skill_lands_on_extract(self, tmp_path, monkeypatch, method):
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )

        # abstract_only carries no full_text — synthesize accordingly so the
        # _compress path is still exercised (the node only compresses when
        # full_text is present and verbosity≥1).
        def resolve(_kw):
            return {
                "status": "ok",
                "data": {
                    "source_type": "arxiv",
                    "identifier": "2406.04378",
                    "s2_metadata": {"title": "T", "year": 2024},
                    "verbosity_achieved": 1,
                    "full_text": "Some prose body.",
                    "extraction_method": method,
                },
                "message": f"resolved via {method}",
            }

        skill = FakeSkill(resolve=resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path))
        rp = out.retrieved_papers[0]
        assert rp.extract is not None
        assert rp.extract.extraction_method == method

    def test_missing_method_in_data_defaults_to_pdfplumber_llm(self, tmp_path, monkeypatch):
        # Pre-2c cached entries don't carry ``extraction_method``. The node
        # must default to the conservative Tier-3 label so trust signals stay
        # consistent (better than blindly claiming a higher tier).
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )

        def resolve(_kw):
            # NOTE: no "extraction_method" key in data.
            return {
                "status": "ok",
                "data": {
                    "source_type": "arxiv",
                    "identifier": "2406.04378",
                    "s2_metadata": {"title": "T", "year": 2024},
                    "verbosity_achieved": 1,
                    "full_text": "Body.",
                },
                "message": "legacy resolve response",
            }

        skill = FakeSkill(resolve=resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path))
        rp = out.retrieved_papers[0]
        assert rp.extract is not None
        assert rp.extract.extraction_method == "pdfplumber_llm"

    def test_llm_cannot_override_extraction_method(self, tmp_path, monkeypatch):
        # If the LLM hallucinates a higher tier (e.g. claims "arxiv_source")
        # while the skill actually emitted "pdfplumber_llm", the node's
        # post-validation stamp must win. This is the trust-signal invariant.
        lying_extract = dict(_VALID_EXTRACT)
        lying_extract["extraction_method"] = "arxiv_source"  # LLM lies
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": lying_extract,
                "lit_review.synthesis": {"findings": []},
            }
        )

        def resolve(_kw):
            return {
                "status": "ok",
                "data": {
                    "source_type": "arxiv",
                    "identifier": "2406.04378",
                    "s2_metadata": {"title": "T", "year": 2024},
                    "verbosity_achieved": 1,
                    "full_text": "Body.",
                    "extraction_method": "pdfplumber_llm",
                },
                "message": "tier-3 resolve",
            }

        skill = FakeSkill(resolve=resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        out = agent.run(_input(tmp_path))
        rp = out.retrieved_papers[0]
        assert rp.extract is not None
        assert rp.extract.extraction_method == "pdfplumber_llm"  # skill wins

    @pytest.mark.parametrize(
        ("method", "fingerprint"),
        [
            ("arxiv_source", "clean LaTeX"),
            ("pdfplumber_llm", "pdfplumber"),
            ("abstract_only", "abstract"),
        ],
    )
    def test_prompt_carries_tier_specific_instructions(
        self, tmp_path, monkeypatch, method, fingerprint
    ):
        # The render function selects the instruction block matching the
        # extraction tier. We check that a tier-distinctive phrase reaches
        # the system prompt the bridge sees.
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": []},
            }
        )

        def resolve(_kw):
            return {
                "status": "ok",
                "data": {
                    "source_type": "arxiv",
                    "identifier": "2406.04378",
                    "s2_metadata": {"title": "T", "year": 2024},
                    "verbosity_achieved": 1,
                    "full_text": "Body.",
                    "extraction_method": method,
                },
                "message": "resolved",
            }

        skill = FakeSkill(resolve=resolve)
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        agent.run(_input(tmp_path))
        extract_prompts = [
            (system, user)
            for (label, system, user) in bridge.prompts
            if label == "lit_review.paper_extract"
        ]
        assert extract_prompts, "no paper_extract prompt was issued"
        system, _user = extract_prompts[0]
        assert fingerprint.lower() in system.lower(), (
            f"system prompt for method={method!r} should mention {fingerprint!r}; "
            f"got: {system[:200]}..."
        )


# ---------------------------------------------------------------------------
# Commit 2d — node-side synthesis-prompt assembly.
#
# _paper_for_synthesis builds the per-paper dict the synthesis prompt's
# render function reads. Commit 2d added three fields (key_equations_md,
# pseudocode_md, extraction_method) so the LLM can quote equations directly
# inside ExpertContextItem.content. These tests pin the assembly contract.
# ---------------------------------------------------------------------------


class TestPaperForSynthesis2dFields:
    """``MLLiteratureReviewAgent._paper_for_synthesis`` must surface 2d's
    new fields from the PaperExtract verbatim. The node is the producer of
    the per-paper dict; if it drops the fields here, no downstream renderer
    can recover them."""

    def _agent(self, tmp_path):
        bridge = FakeBridge()
        return MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )

    def _retrieved_with_extract(self, **extract_overrides):
        extract_kwargs = {
            "title": "T",
            "authors": "A",
            "year": "2024",
            "core_idea": "ci",
            "architecture_details": "AD",
            "key_results": "KR",
            "relevance_to_task": "RT",
            "key_equations_md": "",
            "pseudocode_md": "",
            "extraction_method": "abstract_only",
        }
        extract_kwargs.update(extract_overrides)
        return RetrievedPaper(
            paper_id="arxiv:test",
            source=PaperSource(source_type="arxiv", identifier="test", verbosity=1),
            s2_metadata={"title": "T", "year": 2024},
            extract=PaperExtract(**extract_kwargs),
            verbosity_achieved=1,
        )

    def test_tier1_extract_fields_propagate(self, tmp_path):
        rp = self._retrieved_with_extract(
            key_equations_md="$$y = f(x)$$",
            pseudocode_md="```python\nfor i in range(N):\n    ...\n```",
            extraction_method="arxiv_source",
        )
        d = self._agent(tmp_path)._paper_for_synthesis(rp)
        assert d["key_equations_md"] == "$$y = f(x)$$"
        assert d["pseudocode_md"] == "```python\nfor i in range(N):\n    ...\n```"
        assert d["extraction_method"] == "arxiv_source"

    def test_tier2_extract_fields_propagate(self, tmp_path):
        rp = self._retrieved_with_extract(
            key_equations_md="$$y \\approx f(x)$$",
            pseudocode_md="",
            extraction_method="pdfplumber_llm",
        )
        d = self._agent(tmp_path)._paper_for_synthesis(rp)
        assert d["key_equations_md"] == "$$y \\approx f(x)$$"
        assert d["pseudocode_md"] == ""
        assert d["extraction_method"] == "pdfplumber_llm"

    def test_abstract_only_paper_has_empty_quote_fields(self, tmp_path):
        rp = self._retrieved_with_extract(
            key_equations_md="",
            pseudocode_md="",
            extraction_method="abstract_only",
        )
        d = self._agent(tmp_path)._paper_for_synthesis(rp)
        assert d["key_equations_md"] == ""
        assert d["pseudocode_md"] == ""
        assert d["extraction_method"] == "abstract_only"

    def test_no_extract_defaults_to_abstract_only(self, tmp_path):
        # A v=0 retrieval (no extract at all) still produces a usable dict
        # with the safe-default tier — the synthesis prompt will see
        # ``abstract_only`` and skip the equation sub-blocks.
        rp = RetrievedPaper(
            paper_id="arxiv:meta_only",
            source=PaperSource(source_type="arxiv", identifier="meta_only", verbosity=0),
            s2_metadata={"title": "MO", "year": 2020, "abstract": "Just an abstract."},
            extract=None,
            verbosity_achieved=0,
        )
        d = self._agent(tmp_path)._paper_for_synthesis(rp)
        assert d["key_equations_md"] == ""
        assert d["pseudocode_md"] == ""
        assert d["extraction_method"] == "abstract_only"
        # Existing prose-summary fallback path still works.
        assert d["summary"] == "Just an abstract."

    def test_legacy_dict_keys_still_present(self, tmp_path):
        # Backward compat: every consumer that read the old 4 keys must
        # still find them. The new fields are additive.
        rp = self._retrieved_with_extract(extraction_method="arxiv_source")
        d = self._agent(tmp_path)._paper_for_synthesis(rp)
        for key in ("paper_id", "title", "year", "summary"):
            assert key in d, f"legacy key {key!r} missing"


class TestSynthesisPromptReceivesPerPaperEquations:
    """End-to-end: a v=1 retrieved paper with non-empty key_equations_md /
    pseudocode_md must reach the rendered synthesis system+user prompts
    such that the LLM sees the equation verbatim. Mocked bridge — no real
    LLM call."""

    def test_equation_and_pseudocode_reach_synthesis_user_prompt(self, tmp_path, monkeypatch):
        # Stub the resolver to return a Tier-1 paper with equations + pseudocode
        # in its extract; the node compresses it (via the FakeBridge) and then
        # synthesises. We capture the synthesis prompt the bridge sees.
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": {
                    "title": "EquationCarryingPaper",
                    "authors": "A. Auth",
                    "year": "2024",
                    "core_idea": "...",
                    "architecture_details": "...",
                    "key_results": "...",
                    "relevance_to_task": "...",
                    "key_equations_md": "$$\\hat{y} = M(x)$$",
                    "pseudocode_md": "```algorithm\nfor t: y_t = M(x_t)\n```",
                },
                "lit_review.synthesis": {"findings": []},
            }
        )
        # Resolver returns v=1 text + arxiv_source tier so the node compresses
        # via the bridge and the extract's tier is arxiv_source end-to-end.
        skill = FakeSkill(
            resolve=lambda kw: {
                "status": "ok",
                "data": {
                    "source_type": "arxiv",
                    "identifier": "2406.04378",
                    "s2_metadata": {"title": "EquationCarryingPaper", "year": 2024},
                    "verbosity_achieved": 1,
                    "full_text": "fake LaTeX body",
                    "extraction_method": "arxiv_source",
                },
                "message": "ok",
            }
        )
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        agent.run(_input(tmp_path))

        # Find the synthesis user prompt the bridge actually saw.
        synth_user_prompts = [
            user for (label, _sys, user) in bridge.prompts if label == "lit_review.synthesis"
        ]
        assert synth_user_prompts, "synthesis prompt was not issued"
        user = synth_user_prompts[0]

        # The equation reached the synthesis prompt verbatim — including
        # the dollar-sign delimiters so the LLM can copy them into
        # ``**Mechanism:**`` unchanged.
        assert "$$\\hat{y} = M(x)$$" in user
        # Pseudocode block also present.
        assert "```algorithm" in user
        assert "y_t = M(x_t)" in user
        # Per-tier marker tells the LLM to quote verbatim.
        assert "Extraction: arxiv_source (Tier 1" in user

    def test_synthesis_system_prompt_carries_placement_rule(self, tmp_path, monkeypatch):
        # Independent of the per-paper content, the locked placement rule
        # (Mechanism = source-extracted; Adaptation = LLM reasoning, no raw
        # equations) must reach the synthesis system prompt every run.
        bridge = FakeBridge(responses={"lit_review.synthesis": {"findings": []}})
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        agent.run(_input(tmp_path))
        synth_systems = [
            sys_ for (label, sys_, _user) in bridge.prompts if label == "lit_review.synthesis"
        ]
        assert synth_systems
        system = synth_systems[0]
        assert "Placement rule (LOCKED" in system
        assert "Mechanism = source-extracted content ONLY" in system
        assert "Adaptation MUST NOT contain raw equations" in system


# ---------------------------------------------------------------------------
# Post-2c-c.2 cite-id-mismatch fix — Layer 2 (node-side validation).
# The _validate_content_paper_id helper is the structural defence paired with
# the Layer-1 prompt changes: it hard-drops findings whose declared
# content_paper_id (the paper the LLM says it described in Mechanism) does
# not match source_ref (the paper the LLM cited).
# ---------------------------------------------------------------------------


class TestValidateContentPaperIdHelper:
    """Direct unit tests of ``_validate_content_paper_id``. Exercises all four
    branches: match-passes, missing-field-drops, not-in-corpus-drops,
    mismatch-drops. Imports the helper module-level (the function is part of
    the file's documented internal API)."""

    def _helper(self):
        from nodes.ml_literature_review import _validate_content_paper_id

        return _validate_content_paper_id

    def test_match_passes(self):
        helper = self._helper()
        f = {
            "source_ref": "arxiv:2406.04378",
            "content_paper_id": "arxiv:2406.04378",
            "content": "irrelevant for this check",
        }
        result = helper(f, {"arxiv:2406.04378", "arxiv:2301.00001"})
        # Returned dict is the input unchanged (same identity).
        assert result is f

    def test_mismatch_drops(self):
        helper = self._helper()
        f = {
            "source_ref": "arxiv:2510.25800",  # FreLE — what the LLM cited
            "content_paper_id": "arxiv:2501.04967",  # TADA — what it actually described
            "content": "TADA-shaped Mechanism content",
        }
        valid = {"arxiv:2510.25800", "arxiv:2501.04967"}
        # Both ids are in the corpus, but they don't match → drop.
        assert helper(f, valid) is None

    def test_missing_content_paper_id_drops(self):
        # Pre-2d-cite-id-fix mock or partial LLM output: the field is absent.
        # Hook drops with the "missing content_paper_id" warning.
        helper = self._helper()
        f = {"source_ref": "arxiv:1", "content": "x"}  # no content_paper_id key
        assert helper(f, {"arxiv:1"}) is None

    def test_empty_string_content_paper_id_drops(self):
        # Defence in depth: an empty string for content_paper_id is treated
        # the same as missing — drop, don't compare-equal to an empty
        # source_ref (which itself would also be dropped upstream).
        helper = self._helper()
        f = {"source_ref": "arxiv:1", "content_paper_id": "", "content": "x"}
        assert helper(f, {"arxiv:1"}) is None

    def test_content_paper_id_not_in_corpus_drops(self):
        # The LLM emitted a real-looking arxiv id that isn't actually one of
        # the retrieved papers. Hallucination — drop.
        helper = self._helper()
        f = {
            "source_ref": "arxiv:2406.04378",
            "content_paper_id": "arxiv:1234.56789",  # not in valid_ids
            "content": "x",
        }
        assert helper(f, {"arxiv:2406.04378"}) is None


class TestContentPaperIdHookInSynthesize:
    """End-to-end inside ``_synthesize``: the hook drops mismatched findings
    before they reach ``ExpertContextItem``, mirrors the existing source_ref
    soft-drop pattern, and ``content_paper_id`` is consumed (never forwarded
    onto the schema)."""

    def _run_synthesis(self, tmp_path, monkeypatch, findings):
        """Drive a minimal node run with the given mocked synthesis findings."""
        bridge = FakeBridge(
            responses={
                "lit_review.paper_extract": dict(_VALID_EXTRACT),
                "lit_review.synthesis": {"findings": findings},
            }
        )
        skill = FakeSkill(resolve=lambda kw: _resolve_ok())
        monkeypatch.setattr(node_mod, "run_skill", skill)
        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge), root_cache_dir=str(tmp_path / "cache")
        )
        return agent.run(_input(tmp_path))  # dynamic disabled → retrieved = [root]

    def test_mismatch_finding_dropped_end_to_end(self, tmp_path, monkeypatch):
        # Two findings: one consistent, one with content_paper_id != source_ref.
        # Only the consistent one reaches the output.
        out = self._run_synthesis(
            tmp_path,
            monkeypatch,
            [
                {
                    "content": "consistent finding",
                    "source_ref": "arxiv:2406.04378",
                    "content_paper_id": "arxiv:2406.04378",
                    "confidence": 0.7,
                },
                {
                    "content": "cited paper A, described paper B (hallucination)",
                    "source_ref": "arxiv:2406.04378",
                    # The valid_ids set in a single-paper run is just the root
                    # paper, so any non-root id here is also "not in corpus".
                    # We use a different in-corpus id by mocking — but with a
                    # single retrieved paper this isn't possible end-to-end
                    # from a node test. The point of THIS test is that the
                    # hook fires; the not-in-corpus drop reason still soft-
                    # drops the finding correctly.
                    "content_paper_id": "arxiv:2510.25800",  # not retrieved
                    "confidence": 0.8,
                },
            ],
        )
        assert len(out.findings) == 1
        assert out.findings[0].content == "consistent finding"

    def test_missing_content_paper_id_finding_dropped(self, tmp_path, monkeypatch):
        # A finding lacking content_paper_id is soft-dropped (matches what
        # would happen if the LLM produced a pre-2d-style response by mistake).
        out = self._run_synthesis(
            tmp_path,
            monkeypatch,
            [
                {
                    "content": "legacy-format finding without content_paper_id",
                    "source_ref": "arxiv:2406.04378",
                    "confidence": 0.7,
                },
            ],
        )
        assert out.findings == []

    def test_content_paper_id_consumed_not_forwarded(self, tmp_path, monkeypatch):
        # ExpertContextItem schema has six fields; content_paper_id is not
        # one of them. After the hook validates, the field is read from the
        # raw dict and never forwarded — the constructed ExpertContextItem
        # carries source_ref only.
        out = self._run_synthesis(
            tmp_path,
            monkeypatch,
            [
                {
                    "content": "consistent finding",
                    "source_ref": "arxiv:2406.04378",
                    "content_paper_id": "arxiv:2406.04378",
                    "confidence": 0.7,
                },
            ],
        )
        assert len(out.findings) == 1
        item = out.findings[0]
        # ExpertContextItem schema is unchanged — only the documented six
        # fields exist, and content_paper_id is not among them.
        assert not hasattr(item, "content_paper_id")
        assert item.source_ref == "arxiv:2406.04378"

    def test_hook_warning_logged_on_drop(self, tmp_path, monkeypatch, caplog):
        # The hook emits a warning naming both ids so the operator can grep
        # the run log for hallucinated findings.
        import logging

        with caplog.at_level(logging.WARNING, logger="nodes.ml_literature_review"):
            self._run_synthesis(
                tmp_path,
                monkeypatch,
                [
                    {
                        "content": "mismatched",
                        "source_ref": "arxiv:2406.04378",
                        "content_paper_id": "arxiv:2510.25800",  # not retrieved
                        "confidence": 0.5,
                    }
                ],
            )
        # The not-in-corpus drop path fires (the test's single-paper setup
        # can't reach the != source_ref branch end-to-end; that branch is
        # covered by TestValidateContentPaperIdHelper).
        assert any(
            "content_paper_id" in record.message and "arxiv:2510.25800" in record.message
            for record in caplog.records
        )


class TestInitialVerbosity:
    """Pre-flight B regression (commit 6c493ee, 2026-06-11) —
    ``DynamicSearchConfig.initial_verbosity`` is wired through
    ``_run_search_loop`` → ``_do_search`` → ``_retrieved_from_search_result``
    so it lands on ``PaperSource.verbosity`` for every new search hit.
    Before the fix this knob was schema-defined but never read."""

    def test_initial_verbosity_threaded_to_paper_source(self, tmp_path, monkeypatch):
        """initial_verbosity=2 → RetrievedPaper.source.verbosity == 2."""
        bridge = FakeBridge(
            responses={
                # One search round, then done. No escalations.
                "lit_review.search_decision": [
                    {"action": "search", "query": "denoising", "reasoning": "gap"},
                    {"action": "done", "reasoning": "enough"},
                ],
                # Synthesis returns no findings — we only inspect retrieved_papers.
                "lit_review.synthesis": {"findings": []},
            },
        )
        skill = FakeSkill(search=_search_ok)  # no root papers, only search
        monkeypatch.setattr(node_mod, "run_skill", skill)

        inp = LiteratureReviewInput(
            experiment_history=_interp(),
            root_papers=[],
            dynamic_search=DynamicSearchConfig(
                enabled=True,
                max_rounds=1,
                initial_verbosity=2,  # the Pre-flight B knob
                escalation_allowed=False,
                results_per_query=10,
                max_escalations_per_round=0,
            ),
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="iv_test"),
            ),
            run_name="iv_test",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
        )

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        out = agent.run(inp)

        assert len(out.retrieved_papers) == 1
        rp = out.retrieved_papers[0]
        # Operator's REQUESTED verbosity (2) is recorded on source.verbosity.
        # verbosity_achieved stays at 0 because the S2 search itself is
        # metadata-only — escalation (disabled here) is what would actually
        # produce a deep-read. See nodes/ml_literature_review/ml_literature_review.py
        # _do_search docstring for the full semantic.
        assert rp.source.verbosity == 2, (
            f"initial_verbosity=2 should propagate to PaperSource.verbosity; "
            f"got {rp.source.verbosity}"
        )
        assert rp.verbosity_achieved == 0  # search retrieved metadata only

    def test_initial_verbosity_default_zero_preserves_pre_fix_behaviour(
        self, tmp_path, monkeypatch
    ):
        """When initial_verbosity is left at the schema default 0, the
        search hit's source.verbosity must remain 0 — guards against any
        accidental knob-flip from the Pre-flight B fix."""
        bridge = FakeBridge(
            responses={
                "lit_review.search_decision": [
                    {"action": "search", "query": "denoising", "reasoning": "gap"},
                    {"action": "done", "reasoning": "enough"},
                ],
                "lit_review.synthesis": {"findings": []},
            },
        )
        skill = FakeSkill(search=_search_ok)
        monkeypatch.setattr(node_mod, "run_skill", skill)

        inp = LiteratureReviewInput(
            experiment_history=_interp(),
            root_papers=[],
            dynamic_search=DynamicSearchConfig(enabled=True, max_rounds=1),
            # initial_verbosity NOT passed → schema default 0
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="default_iv_test"),
            ),
            run_name="default_iv_test",
            llm_provider="openai",
            llm_model_id="gpt-4o-mini",
        )

        agent = MLLiteratureReviewAgent(
            bridge_factory=_bridge_factory(bridge),
            root_cache_dir=str(tmp_path / "cache"),
        )
        out = agent.run(inp)

        assert len(out.retrieved_papers) == 1
        assert out.retrieved_papers[0].source.verbosity == 0
