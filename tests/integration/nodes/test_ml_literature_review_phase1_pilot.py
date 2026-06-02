"""
§10 Phase-1 pilot — Commit 2c-c.2.

Resolves and compresses the seven §10.2 corpus papers end-to-end with the
real DeepSeek bridge and live arXiv / Semantic Scholar, then renders a
human-review Markdown report via ``render_review_report``. The artifact is
written to ``reference_data/lit_review_pilot_cache/phase1_pilot_report.md``
(gitignored) for operator review against the §10.5 acceptance criteria;
promotion into ``docs/validation_suite_runs.md`` is a manual step after
Checkpoint E sign-off.

Two tests live in this file:

* ``test_cache_layer_round_trip_offline`` — non-``@real_run``; exercises the
  pilot's disk cache (resolve + extract JSON files) with a stubbed resolver
  and a fake bridge. Always runs in CI; no network, no LLM.
* ``test_phase1_pilot_real_run`` — ``@real_run`` + skipped without S2 +
  DeepSeek keys. Hits the live API stack, writes the artifact, and asserts
  the structural floor (every paper resolves, expected tier per paper, key
  equations populated for the six Tier-1 papers). Quality assessment (the
  Checkpoint E sign-off itself) is a human-review step on the artifact.

Run real pilot with:
  uv run pytest -m real_run \
    tests/integration/nodes/test_ml_literature_review_phase1_pilot.py -v -s

Run cache tests only (CI default):
  uv run pytest tests/integration/nodes/test_ml_literature_review_phase1_pilot.py -v

Re-running after a prompt tweak: delete the ``.extract.json`` files in
``reference_data/lit_review_pilot_cache/`` (keeps the expensive arXiv
fetches; only the LLM-compression layer is invalidated).
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.literature_review import (
    render_paper_extract_prompt,
    render_review_report,
)
from agent.schemas.literature_review import (
    LiteratureReviewOutput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
)
from agent.schemas.proposal import AgentCard
from agent.skills.paper_resolver_skill.wrapper import run_skill

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Corpus + provider config (locked — see §10.2 of external_agents_for_proposer.md)
# ---------------------------------------------------------------------------

# Order matches §10.2 #1-#7 exactly so the rendered report's per-paper
# section numbers line up with the spec. ``expected_method`` is the
# acceptance-criteria value; the test fails if a paper drops to a
# different tier (e.g. arxiv source fetch silently 404s).
CORPUS: list[dict[str, str]] = [
    {"arxiv_id": "2312.00752", "expected_method": "arxiv_source", "label": "Mamba"},
    {"arxiv_id": "2211.14730", "expected_method": "arxiv_source", "label": "PatchTST"},
    {"arxiv_id": "2511.20731", "expected_method": "arxiv_source", "label": "GW denoising"},
    {"arxiv_id": "1811.02695", "expected_method": "arxiv_source", "label": "DeepDenoiser"},
    {"arxiv_id": "2501.04967", "expected_method": "arxiv_source", "label": "TADA"},
    {"arxiv_id": "2510.25800", "expected_method": "arxiv_source", "label": "FreLE"},
    {"arxiv_id": "2503.18162", "expected_method": "pdfplumber_llm", "label": "SNRAware"},
]

DEEPSEEK_PROVIDER = "deepseek"
DEEPSEEK_MODEL_ID = "deepseek-v4-pro"

CACHE_DIR = _PROJECT_ROOT / "reference_data" / "lit_review_pilot_cache"
ARTIFACT_PATH = CACHE_DIR / "phase1_pilot_report.md"

_HAS_KEYS = bool(os.getenv("S2_API_KEY")) and bool(os.getenv("DEEPSEEK_API_KEY"))


# ---------------------------------------------------------------------------
# AgentCard for the synthesized Phase-1 LiteratureReviewOutput. Mirrors the
# node's static card so the rendered banner matches a production run.
# ---------------------------------------------------------------------------


def _pilot_agent_card() -> AgentCard:
    return AgentCard(
        agent_name="ml_literature_review",
        role="Surface ML denoising literature relevant to the current iteration.",
        expertise_domain="ML denoising architectures; Semantic Scholar corpus.",
        coverage="ArXiv/S2 results any year; §10 corpus for Phase-1 pilot.",
        limitations=("Phase-1 pilot does not run synthesis; findings list is empty by design."),
        trust_guidance=(
            "Phase-1 pilot artifact for Checkpoint E/F human review — not a production output."
        ),
    )


# ---------------------------------------------------------------------------
# Cache layer — two files per paper:
#   {safe_id}.resolve.json — resolver response (s2_metadata + full_text + tier)
#   {safe_id}.extract.json — validated PaperExtract JSON
# Split so re-running after a prompt tweak only invalidates the extract layer.
# ---------------------------------------------------------------------------


def _safe_id(paper_id: str) -> str:
    """Filesystem-safe stem — mirrors ``nodes/ml_literature_review._sanitize_paper_id``."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def _cache_paths(cache_dir: Path, paper_id: str) -> tuple[Path, Path]:
    stem = _safe_id(paper_id)
    return cache_dir / f"{stem}.resolve.json", cache_dir / f"{stem}.extract.json"


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _resolve_with_cache(
    arxiv_id: str,
    cache_dir: Path,
    resolver=run_skill,
) -> dict[str, Any]:
    """Resolve via ``run_skill`` at verbosity=1, caching the response on disk.

    Returns the ``data`` sub-dict of the resolver envelope (s2_metadata,
    full_text, extraction_method, verbosity_achieved). Raises on a resolver
    error envelope; the test logs the message before re-raising so the
    operator can diagnose without grepping the JSON.
    """
    paper_id = f"arxiv:{arxiv_id}"
    resolve_path, _ = _cache_paths(cache_dir, paper_id)

    cached = _load_json_if_exists(resolve_path)
    if cached is not None:
        return cached

    envelope = resolver(
        None,
        mode="resolve",
        source_type="arxiv",
        identifier=arxiv_id,
        verbosity=1,
    )
    if envelope["status"] != "ok":
        raise RuntimeError(
            f"resolver returned non-ok for {arxiv_id!r}: "
            f"status={envelope['status']!r} message={envelope.get('message')!r}"
        )
    data = envelope["data"]
    _write_json(resolve_path, data)
    return data


def _compress_with_cache(
    paper_id: str,
    full_text: str,
    extraction_method: str,
    bridge: LLMBridge,
    cache_dir: Path,
) -> PaperExtract:
    """Compress full text into a ``PaperExtract`` via the real bridge, caching it.

    Mirrors ``nodes/ml_literature_review._compress``: render the prompt for
    the right extraction tier, generate, validate, then stamp
    ``extraction_method`` post-validation (the LLM is not allowed to mint
    or override the trust signal).
    """
    _, extract_path = _cache_paths(cache_dir, paper_id)
    cached = _load_json_if_exists(extract_path)
    if cached is not None:
        return PaperExtract.model_validate(cached)

    sys_prompt, user_prompt = render_paper_extract_prompt(
        full_text,
        extraction_method=extraction_method,  # type: ignore[arg-type]
    )
    raw = bridge.generate(sys_prompt, user_prompt, label="lit_review_pilot.paper_extract")
    extract = PaperExtract.model_validate(raw)
    extract.extraction_method = extraction_method  # type: ignore[assignment]
    _write_json(extract_path, extract.model_dump())
    return extract


def _build_retrieved_paper(
    arxiv_id: str, data: dict[str, Any], extract: PaperExtract
) -> RetrievedPaper:
    """Wrap resolver data + validated extract into a ``RetrievedPaper``."""
    return RetrievedPaper(
        paper_id=f"arxiv:{arxiv_id}",
        source=PaperSource(source_type="arxiv", identifier=arxiv_id, verbosity=1),
        s2_metadata=data.get("s2_metadata"),
        extract=extract,
        verbosity_achieved=1,
        error=None,
    )


def _run_phase1(
    cache_dir: Path,
    bridge: LLMBridge,
    *,
    resolver=run_skill,
) -> LiteratureReviewOutput:
    """End-to-end Phase-1: resolve + compress all 7 papers; assemble the output.

    No synthesis is run — ``findings=[]`` by design. ``search_rounds_used=0``
    so the rendered report shows the explicit "synthesis was not invoked"
    callout.
    """
    started = _iso_now()
    retrieved: list[RetrievedPaper] = []
    for paper in CORPUS:
        arxiv_id = paper["arxiv_id"]
        data = _resolve_with_cache(arxiv_id, cache_dir, resolver=resolver)
        extract = _compress_with_cache(
            paper_id=f"arxiv:{arxiv_id}",
            full_text=data["full_text"],
            extraction_method=data["extraction_method"],
            bridge=bridge,
            cache_dir=cache_dir,
        )
        retrieved.append(_build_retrieved_paper(arxiv_id, data, extract))
    finished = _iso_now()

    return LiteratureReviewOutput(
        agent_card=_pilot_agent_card(),
        findings=[],
        retrieved_papers=retrieved,
        search_rounds_used=0,
        run_name="phase1_pilot",
        started_at=started,
        finished_at=finished,
    )


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Cache-layer offline test — proves the disk cache works without touching
# either the resolver network path or the bridge LLM path.
# ---------------------------------------------------------------------------


class _FakeBridge:
    """Counts ``generate`` calls and returns a fixed PaperExtract dict.

    Stands in for ``LLMBridge`` in the offline cache test so we can assert
    cache hits don't re-invoke the LLM.
    """

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system: str, user: str, *, label: str = "", **_kw) -> dict[str, Any]:
        self.calls += 1
        return {
            "title": "Cache test paper",
            "authors": "A. Author",
            "year": "2025",
            "core_idea": "Tests cache layer.",
            "architecture_details": "Pure offline.",
            "key_results": "Cache hit count goes up.",
            "relevance_to_task": "Validates the wrapper.",
            "key_equations_md": "$$x = y$$",
            "pseudocode_md": "",
        }


def test_cache_layer_round_trip_offline(tmp_path):
    """First call writes both cache files; second call reads both and skips
    the resolver + the bridge entirely."""

    resolver_call_count = {"n": 0}

    def fake_resolver(_sandbox, **_kw):
        resolver_call_count["n"] += 1
        return {
            "status": "ok",
            "data": {
                "source_type": "arxiv",
                "identifier": "fake.id",
                "s2_metadata": {"title": "Cache test paper", "paperId": "p1"},
                "full_text": "Some cleaned LaTeX/Markdown.",
                "extraction_method": "arxiv_source",
                "verbosity_achieved": 1,
            },
            "message": "fake",
        }

    bridge = _FakeBridge()

    # First call: cold cache → writes both files, exactly one resolver +
    # one bridge invocation.
    data1 = _resolve_with_cache("fake.id", tmp_path, resolver=fake_resolver)
    extract1 = _compress_with_cache(
        paper_id="arxiv:fake.id",
        full_text=data1["full_text"],
        extraction_method="arxiv_source",
        bridge=bridge,  # type: ignore[arg-type]
        cache_dir=tmp_path,
    )
    assert resolver_call_count["n"] == 1
    assert bridge.calls == 1
    resolve_path, extract_path = _cache_paths(tmp_path, "arxiv:fake.id")
    assert resolve_path.exists()
    assert extract_path.exists()
    assert extract1.extraction_method == "arxiv_source"
    assert extract1.title == "Cache test paper"

    # Second call: warm cache → no resolver hit, no bridge hit, same data.
    data2 = _resolve_with_cache("fake.id", tmp_path, resolver=fake_resolver)
    extract2 = _compress_with_cache(
        paper_id="arxiv:fake.id",
        full_text=data2["full_text"],
        extraction_method="arxiv_source",
        bridge=bridge,  # type: ignore[arg-type]
        cache_dir=tmp_path,
    )
    assert resolver_call_count["n"] == 1  # unchanged
    assert bridge.calls == 1  # unchanged
    assert data2 == data1
    assert extract2.model_dump() == extract1.model_dump()

    # Operator workflow: deleting only the extract file re-runs the LLM
    # without re-hitting arXiv. This is the prompt-tweak iteration path.
    extract_path.unlink()
    extract3 = _compress_with_cache(
        paper_id="arxiv:fake.id",
        full_text=data2["full_text"],
        extraction_method="arxiv_source",
        bridge=bridge,  # type: ignore[arg-type]
        cache_dir=tmp_path,
    )
    assert resolver_call_count["n"] == 1  # still no resolver call
    assert bridge.calls == 2  # bridge re-invoked
    assert extract3.title == "Cache test paper"


def test_safe_id_is_filesystem_safe():
    """The cache filename stem mirrors the node's sanitization rules."""
    assert _safe_id("arxiv:2312.00752") == "arxiv_2312.00752"
    assert _safe_id("doi:10.1109/foo/bar") == "doi_10.1109_foo_bar"
    # No path separators or colons leak through.
    for unsafe in (":", "/", "?", " "):
        assert unsafe not in _safe_id(f"prefix:{unsafe}value")


# ---------------------------------------------------------------------------
# Real-run pilot — the actual Phase-1 artifact producer.
# ---------------------------------------------------------------------------


@pytest.mark.real_run
@pytest.mark.skipif(
    not _HAS_KEYS,
    reason="needs S2_API_KEY (resolution) + DEEPSEEK_API_KEY (compression)",
)
def test_phase1_pilot_real_run():
    """Resolve + compress all 7 §10.2 papers and emit the human-review artifact.

    Structural assertions only — the Checkpoint E quality review is a
    separate human step against the rendered Markdown.
    """
    bridge = LLMBridge(provider=DEEPSEEK_PROVIDER, model_id=DEEPSEEK_MODEL_ID)
    output = _run_phase1(CACHE_DIR, bridge)

    # 1. All 7 papers resolved + compressed.
    assert len(output.retrieved_papers) == 7
    for paper, spec in zip(output.retrieved_papers, CORPUS, strict=True):
        assert paper.extract is not None, f"{spec['label']} ({spec['arxiv_id']}): no extract"
        assert paper.verbosity_achieved == 1, (
            f"{spec['label']}: verbosity degraded to {paper.verbosity_achieved}"
        )

    # 2. Extraction method per §10.2: six arxiv_source, one pdfplumber_llm.
    for paper, spec in zip(output.retrieved_papers, CORPUS, strict=True):
        actual = paper.extract.extraction_method  # type: ignore[union-attr]
        assert actual == spec["expected_method"], (
            f"{spec['label']} ({spec['arxiv_id']}): expected "
            f"extraction_method={spec['expected_method']!r}, got {actual!r}"
        )

    # 3. Tier-1 papers must carry non-empty key_equations_md (Tier-2 is
    # best-effort and not held to the same bar — §10.5 acceptance criteria).
    tier1_missing_equations: list[str] = []
    for paper, spec in zip(output.retrieved_papers, CORPUS, strict=True):
        if spec["expected_method"] != "arxiv_source":
            continue
        if not paper.extract.key_equations_md.strip():  # type: ignore[union-attr]
            tier1_missing_equations.append(f"{spec['label']} ({spec['arxiv_id']})")
    assert not tier1_missing_equations, "Tier-1 papers missing key_equations_md: " + ", ".join(
        tier1_missing_equations
    )

    # 4. Render the artifact, write to disk, and pin a few structural
    # invariants on the rendered Markdown.
    report = render_review_report(output)
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(report, encoding="utf-8")

    # Every paper's heading is present.
    for spec in CORPUS:
        assert f"`arxiv:{spec['arxiv_id']}`" in report, (
            f"paper heading for {spec['label']} missing from rendered report"
        )
    # SNRAware gets the Tier-2 trust callout.
    assert "Trust note — Tier 2 source" in report
    # Phase 1: findings section explicitly empty, points at the synthesis-
    # didn't-run callout.
    assert "synthesis was not invoked" in report

    # Operator hand-off log line — printed so a `-s` run surfaces the path.
    print(f"\n=== §10 Phase 1 pilot artifact written to: {ARTIFACT_PATH} ===")
    print(
        "Review against §10.5 acceptance criteria, then promote into "
        "docs/validation_suite_runs.md under a dated section."
    )
