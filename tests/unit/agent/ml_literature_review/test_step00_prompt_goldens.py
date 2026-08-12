"""Step-00 PB-9 — literature-review prompt goldens (3 families, branch variants).

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§13.1 / §15.1 (roadmap step 01 A-surface; variants per the audited branch
map — NOT a combinatorial matrix).

Variant set: paper_extract — 2 system goldens (default ``pdfplumber_llm``
+ ``arxiv_source``) + 1 user; search_decision — 1 system + 2 user (first
round through the node loop; prior/escalation/coverage blocks via the real
producer); synthesis — 3 system (v1/moderate, v0/moderate, v1/strict) + 1
user (one paper with equations present + pseudocode empty exercises both
the render and the skip branch).

All drives go through the node methods (``_compress`` / ``_run_search_loop``
/ ``_synthesize``) with the boundary recorder — never ``run()`` (which
touches disk caches and network). ``root_cache_dir`` is pinned to tmp_path
defensively; the recorder's raising clients are the network backstop.
"""

from __future__ import annotations

from pathlib import Path

from agent.prompt_templates.literature_review import render_search_decision_prompt
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
    SynthesisConfig,
)
from nodes.ml_literature_review.ml_literature_review import MLLiteratureReviewAgent
from tests.helpers.golden import assert_golden
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge

GOLDENS = Path(__file__).parent / "goldens"

_TASK = "PB-9 fixture task: denoise SQUID magnetometer data."

HIST = InterpretationOutput(
    model_types=["wavenet"],
    model_descriptions={"wavenet": "d"},
    total_experiments=3,
    key_findings=["kf1"],
    bottlenecks=["b1"],
    take_home_message="thm",
)

RP = RetrievedPaper(
    paper_id="arxiv:1609.03499",
    source=PaperSource(source_type="arxiv", identifier="1609.03499"),
    verbosity_achieved=1,
    extract=PaperExtract(
        title="WaveNet",
        year="2016",
        architecture_details="dilated causal conv",
        key_results="SOTA",
        relevance_to_task="rel",
        key_equations_md="EQ",
        pseudocode_md="",
        extraction_method="arxiv_source",
    ),
)


def make_agent(tmp_path) -> MLLiteratureReviewAgent:
    a = MLLiteratureReviewAgent(root_cache_dir=str(tmp_path / "cache"))
    a.bridge = BoundaryRecorderBridge()
    a.search_bridge = a.bridge
    a._task_description = _TASK
    return a


def make_input(**over) -> LiteratureReviewInput:
    base = dict(
        experiment_history=HIST,
        storage={"backend": "local", "local": {"workspace": "/pb9/ws", "run_name": "r1"}},
        run_name="r1",
        llm_provider="openai",
        llm_model_id="m",
        task_description=_TASK,
    )
    return LiteratureReviewInput(**{**base, **over})


class TestPB9PaperExtract:
    def test_arxiv_source_variant(self, tmp_path):
        a = make_agent(tmp_path)
        a._compress("PB-9 frozen fixture paper text.", extraction_method="arxiv_source")
        assert len(a.bridge.captures) == 1
        _, label, system, user = a.bridge.captures[0]
        assert label == "lit_review.paper_extract"
        assert_golden(
            system,
            GOLDENS / "pb9_extract_system_arxiv.txt",
            surface="PB-9 extract system (arxiv_source)",
        )
        assert_golden(user, GOLDENS / "pb9_extract_user.txt", surface="PB-9 extract user")

    def test_pdfplumber_default_variant(self, tmp_path):
        a = make_agent(tmp_path)
        a._compress("PB-9 frozen fixture paper text.", extraction_method="pdfplumber_llm")
        assert_golden(
            a.bridge.captures[0][2],
            GOLDENS / "pb9_extract_system_pdfplumber.txt",
            surface="PB-9 extract system (pdfplumber_llm)",
        )


class TestPB9SearchDecision:
    def test_first_round_through_node_loop(self, tmp_path):
        a = make_agent(tmp_path)
        inp = make_input(
            dynamic_search=DynamicSearchConfig(enabled=True, max_rounds=1, escalation_allowed=False)
        )
        a._run_search_loop(inp, [], {})
        assert len(a.bridge.captures) == 1, "exactly one decision round; no network reached"
        _, label, system, user = a.bridge.captures[0]
        assert label == "lit_review.search_decision"
        assert_golden(
            system, GOLDENS / "pb9_search_system.txt", surface="PB-9 search-decision system"
        )
        assert_golden(
            user,
            GOLDENS / "pb9_search_user_first.txt",
            surface="PB-9 search-decision user (first round)",
        )

    def test_prior_escalation_coverage_blocks(self):
        _system, user = render_search_decision_prompt(
            key_findings=["kf1"],
            bottlenecks=["b1"],
            take_home_message="thm",
            explored_models=["wavenet"],
            papers_seen=[
                {
                    "paper_id": "arxiv:1609.03499",
                    "title": "WaveNet",
                    "year": 2016,
                    "verbosity_achieved": 1,
                    "snippet": "raw audio",
                }
            ],
            escalation_allowed=True,
            prior_search_results=[
                ("dilated conv denoising", 7),
                ("squid magnetometer transformer", 0),
            ],
            prior_escalation_results=[("arxiv:1609.03499", "noop", "tried deep read")],
            dimension_counts={
                "bottleneck": 2,
                "take_home": 0,
                "architectural_gap": 1,
                "adjacent_technique": 0,
            },
            task_description=_TASK,
        )
        assert_golden(
            user,
            GOLDENS / "pb9_search_user_prior.txt",
            surface="PB-9 search-decision user (prior + escalation + coverage)",
        )


class TestPB9Synthesis:
    def test_default_v1_moderate(self, tmp_path):
        a = make_agent(tmp_path)
        a._synthesize(make_input(), [RP])
        assert len(a.bridge.captures) == 1
        _, label, system, user = a.bridge.captures[0]
        assert label == "lit_review.synthesis"
        assert_golden(
            system,
            GOLDENS / "pb9_synthesis_system_v1_moderate.txt",
            surface="PB-9 synthesis system (v1/moderate)",
        )
        assert_golden(user, GOLDENS / "pb9_synthesis_user.txt", surface="PB-9 synthesis user")

    def test_verbosity0_system(self, tmp_path):
        a = make_agent(tmp_path)
        a._synthesize(make_input(findings_verbosity=0), [RP])
        assert_golden(
            a.bridge.captures[0][2],
            GOLDENS / "pb9_synthesis_system_v0_moderate.txt",
            surface="PB-9 synthesis system (v0)",
        )

    def test_strict_tolerance_system(self, tmp_path):
        a = make_agent(tmp_path)
        a._synthesize(
            make_input(synthesis_config=SynthesisConfig(transfer_tolerance="strict")), [RP]
        )
        assert_golden(
            a.bridge.captures[0][2],
            GOLDENS / "pb9_synthesis_system_v1_strict.txt",
            surface="PB-9 synthesis system (strict)",
        )
