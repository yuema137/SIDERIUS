"""
§10 Phase-2 pilot — Commit 2d.

Drives the lit-review node's synthesis step on the seven §10.2 corpus papers
with the real DeepSeek bridge and the 2c/2d prompt chain, then renders the
resulting findings as a human-review Markdown artifact for **Checkpoint G**
sign-off. Resolve + compress are loaded from the Phase-1 pilot cache (the
expensive paths shipped in 2c-c.2); only synthesis is re-run — uncached, by
design, so a prompt-tweak iteration always produces a fresh artifact.

Two tests live in this file:

* ``test_phase2_cache_loader_offline`` — non-``@real_run``; exercises the
  cache-loading helper with canned JSON. Verifies a ``RetrievedPaper`` can be
  reconstructed from the two-file Phase-1 cache without a live API call.
  Always runs in CI.

* ``test_phase2_pilot_real_run`` — ``@real_run`` + skipped without S2 +
  DeepSeek keys AND without the Phase-1 cache populated. Runs the real
  synthesis call against the live DeepSeek bridge, validates the structural
  floor for Checkpoint G (≥2 findings — see floor comment in the test for
  why this seed binds at 2; three-part content; per-tier equation/flag
  placement; no raw LaTeX in Adaptation), and writes the rendered artifact
  to ``reference_data/lit_review_pilot_cache/phase2_pilot_report.md`` for
  operator review.

Run real pilot with:
  uv run pytest -m real_run \\
    tests/integration/nodes/test_ml_literature_review_phase2_pilot.py -v -s

Run cache tests only (CI default):
  uv run pytest \\
    tests/integration/nodes/test_ml_literature_review_phase2_pilot.py -v

If the Phase-1 cache is missing (fresh checkout), populate it first by
running ``tests/integration/nodes/test_ml_literature_review_phase1_pilot.py``
with ``@real_run``. The Phase-2 pilot then reuses those cached extracts —
re-running Phase 2 after a synthesis-prompt tweak costs one synthesis call,
not 7 extractions + 1 synthesis.

Checkpoint G validation summary (operator artifact review):
  - Tier-1 (#1-#6) findings: Mechanism contains LaTeX content in any
    standard delimiter form (``$$...$$``, ``$...$``, ``\\(...\\)``,
    ``\\[...\\]``) when the cited paper has non-empty ``key_equations_md``
    — the LLM actually quoted the equation rather than dropping it. The
    placement rule cares WHERE the equation appears (Mechanism), not which
    delimiter the LLM chose.
  - Tier-2 (#7 SNRAware) findings: Mechanism carries a paraphrase / flag
    word (``approximate`` / ``paraphrased`` / ``reconstructed`` / ``degraded
    PDF``) instead of presenting the equation as ground truth.
  - All findings: Adaptation contains NO LaTeX delimiters (any form) —
    enforces the locked Mechanism-vs-Adaptation placement rule from 2d.

Note: the test asserts the **structural floor** only. The substantive
Checkpoint G review (correctness vs source, implementability bar,
measurable improvement vs pre-2d) is the human-review step on the
rendered artifact.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperExtract,
    PaperSource,
    RetrievedPaper,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review import MLLiteratureReviewAgent

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Corpus + provider config — mirror the Phase-1 pilot exactly (§10.2)
# ---------------------------------------------------------------------------

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
ARTIFACT_PATH = CACHE_DIR / "phase2_pilot_report.md"

_HAS_KEYS = bool(os.getenv("S2_API_KEY")) and bool(os.getenv("DEEPSEEK_API_KEY"))

# Tier-2 paraphrase / flag words the synthesis prompt instructs the LLM to use
# when quoting from a `pdfplumber_llm` paper. Any one of these in the
# Mechanism section satisfies the Tier-2 paraphrase check.
_TIER2_FLAG_WORDS = ("approximate", "paraphrased", "reconstructed", "degraded")

# Match any standard LaTeX delimiter form: ``$$...$$`` (display), ``$...$``
# (inline), ``\(...\)`` (inline), ``\[...\]`` (display). Used to assert
# Mechanism contains an equation for Tier-1 citations, and that Adaptation
# contains NO raw LaTeX for ANY citation. Earlier revisions of this pilot
# used a ``$$``-only regex, which falsely flagged DeepSeek output that
# preserved the equation's content but transliterated ``$$`` → ``\(...\)``
# (see commit message of the LaTeX-regex-loosen fix). The placement rule
# is about WHERE the equation appears (Mechanism vs Adaptation), not which
# delimiter form the LLM chose to wrap it in.
_LATEX_DELIMITER_RE = re.compile(
    r"""
    \$\$        # display-math: $$ ... $$
    | \$        # inline-math:  $ ... $
    | \\\(      # inline-math:  \( ... \)
    | \\\[      # display-math: \[ ... \]
    """,
    re.VERBOSE,
)


# ---------------------------------------------------------------------------
# Cache loader — reads the two-file Phase-1 cache, rebuilds RetrievedPaper.
# Mirrors Phase-1's `_cache_paths` naming convention exactly.
# ---------------------------------------------------------------------------


def _safe_id(paper_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id)


def _cache_paths(cache_dir: Path, paper_id: str) -> tuple[Path, Path]:
    stem = _safe_id(paper_id)
    return cache_dir / f"{stem}.resolve.json", cache_dir / f"{stem}.extract.json"


def _load_retrieved_from_cache(arxiv_id: str, cache_dir: Path) -> RetrievedPaper:
    """Reconstruct a single ``RetrievedPaper`` from the Phase-1 cache.

    Raises ``FileNotFoundError`` when either cache file is missing — the
    caller (the corpus loader below) catches this and turns it into a
    pytest.skip with a clear pointer at the Phase-1 pilot.
    """
    paper_id = f"arxiv:{arxiv_id}"
    resolve_path, extract_path = _cache_paths(cache_dir, paper_id)
    if not resolve_path.exists() or not extract_path.exists():
        raise FileNotFoundError(
            f"Phase-1 cache missing for {paper_id!r}: "
            f"{resolve_path.name} or {extract_path.name} not found in "
            f"{cache_dir}. Run the Phase-1 pilot first."
        )
    resolve_data = json.loads(resolve_path.read_text(encoding="utf-8"))
    extract_data = json.loads(extract_path.read_text(encoding="utf-8"))
    return RetrievedPaper(
        paper_id=paper_id,
        source=PaperSource(source_type="arxiv", identifier=arxiv_id, verbosity=1),
        s2_metadata=resolve_data.get("s2_metadata"),
        extract=PaperExtract.model_validate(extract_data),
        verbosity_achieved=1,
        error=None,
    )


def _load_corpus_or_skip(cache_dir: Path) -> list[RetrievedPaper]:
    """Load all 7 corpus papers from the Phase-1 cache, or pytest.skip.

    A single missing paper skips the whole test — partial coverage is not
    a useful Checkpoint G artifact.
    """
    retrieved: list[RetrievedPaper] = []
    for paper in CORPUS:
        try:
            retrieved.append(_load_retrieved_from_cache(paper["arxiv_id"], cache_dir))
        except FileNotFoundError as exc:
            pytest.skip(
                f"Phase-2 pilot requires the Phase-1 cache: {exc}. "
                f"Run `pytest -m real_run "
                f"tests/integration/nodes/test_ml_literature_review_phase1_pilot.py` "
                f"first."
            )
    return retrieved


# ---------------------------------------------------------------------------
# Interpretation seed — representative experiment state the synthesis prompt
# grounds findings against. Mirrors the existing Tier-1 integration test in
# ``test_ml_literature_review.py`` so the artifact is comparable.
# ---------------------------------------------------------------------------


def _interp_seed() -> InterpretationOutput:
    return InterpretationOutput(
        model_types=["wavenet", "punet"],
        model_descriptions={
            "wavenet": "Dilated causal convolution autoregressive denoiser (full-spectrum).",
            "punet": "UNet recast as 256-class per-timestep segmentation.",
        },
        total_experiments=6,
        key_findings=[
            "WaveNet seed scores ~5.6 full-spectrum; an added gating mechanism "
            "destabilised training (best ~ -1.5).",
            "Reconstruction error concentrates in the high-frequency band.",
        ],
        bottlenecks=[
            "Training instability when a new inductive bias conflicts with the "
            "dilated causal convolution backbone.",
            "Model under-converges at low data volume — strong data sensitivity.",
        ],
        take_home_message=(
            "Need a stable way to widen receptive field / spectral coverage "
            "without breaking WaveNet's causal structure."
        ),
    )


def _phase2_input(tmp_path: Path, retrieved: list[RetrievedPaper]) -> LiteratureReviewInput:
    """Build a ``LiteratureReviewInput`` carrying the synthesis-relevant
    fields. ``root_papers`` is the cited list, dynamic search is OFF (we are
    synthesising over a fixed locked corpus, not searching)."""
    return LiteratureReviewInput(
        experiment_history=_interp_seed(),
        root_papers=[
            PaperSource(
                source_type="arxiv",
                identifier=paper["arxiv_id"],
                verbosity=1,
            )
            for paper in CORPUS
        ],
        dynamic_search=DynamicSearchConfig(enabled=False),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="phase2_pilot"),
        ),
        run_name="phase2_pilot",
        llm_provider=DEEPSEEK_PROVIDER,
        llm_model_id=DEEPSEEK_MODEL_ID,
    )


# ---------------------------------------------------------------------------
# Finding parsing — split the content string on the three canonical headings.
# The synthesis prompt mandates the order, and ``_normalize_finding_content_
# headings`` in the node rewrites known variants to the canonical form, so
# this parser is robust against the spellings the LLM actually emits.
# ---------------------------------------------------------------------------


def _extract_sections(content: str) -> dict[str, str]:
    """Return a mapping {"implication": str, "mechanism": str, "adaptation": str}.

    Each value is the text between the corresponding bold heading and the
    next one (or the closing ``(rationale: ...)``). Missing sections map to
    the empty string — the caller asserts presence separately.
    """
    out = {"implication": "", "mechanism": "", "adaptation": ""}
    # Anchors include the closing rationale to bound the Adaptation section.
    pattern = re.compile(
        r"\*\*Implication:\*\*(?P<implication>.*?)"
        r"\*\*Mechanism:\*\*(?P<mechanism>.*?)"
        r"\*\*Adaptation:\*\*(?P<adaptation>.*?)"
        r"(?:\(rationale:|$)",
        re.DOTALL,
    )
    m = pattern.search(content)
    if not m:
        return out
    out["implication"] = m.group("implication").strip()
    out["mechanism"] = m.group("mechanism").strip()
    out["adaptation"] = m.group("adaptation").strip()
    return out


# ---------------------------------------------------------------------------
# Artifact renderer — a small focused Markdown report for Checkpoint G.
# Not using `render_review_report` because the audience here is the
# Checkpoint G reviewer, who wants finding-by-finding inspection alongside
# the cited paper's source equations for verbatim/paraphrase comparison.
# ---------------------------------------------------------------------------


def _render_phase2_artifact(
    findings: list,  # list[ExpertContextItem]
    retrieved: list[RetrievedPaper],
    inp: LiteratureReviewInput,
) -> str:
    """Render the per-finding Markdown with source-equation cross-reference.

    For each finding, shows:
      - Citation header + cited paper's tier
      - Source ``key_equations_md`` from the cited paper (ground truth)
      - The finding's three sections side-by-side with the source equation
      - Per-section Checkpoint-G annotation (Mechanism has equation?
        Adaptation has no LaTeX?)
    """
    by_paper_id = {rp.paper_id: rp for rp in retrieved}
    hist = inp.experiment_history
    lines: list[str] = [
        "# §10 Phase-2 Pilot — Checkpoint G Artifact",
        "",
        f"**Generated:** `{datetime.now(UTC).isoformat(timespec='seconds')}`",
        f"**Synthesis LLM:** `{DEEPSEEK_PROVIDER}` / `{DEEPSEEK_MODEL_ID}`",
        f"**Corpus:** §10.2 ({len(CORPUS)} papers locked)",
        f"**Findings emitted:** {len(findings)}",
        "",
        "## Synthesis input (grounding state)",
        "",
        "**Bottlenecks:**",
        *[f"- {b}" for b in hist.bottlenecks],
        "",
        "**Key findings:**",
        *[f"- {kf}" for kf in hist.key_findings],
        "",
        f"**Take-home message:** {hist.take_home_message}",
        "",
        "---",
        "",
        "## Findings (synthesis output)",
        "",
    ]
    for i, item in enumerate(findings, start=1):
        rp = by_paper_id.get(item.source_ref)
        method = rp.extract.extraction_method if rp and rp.extract else "unknown"
        source_eq = (rp.extract.key_equations_md if rp and rp.extract else "").strip()
        sections = _extract_sections(item.content)
        mechanism_has_eq = bool(_LATEX_DELIMITER_RE.search(sections["mechanism"]))
        adaptation_has_eq = bool(_LATEX_DELIMITER_RE.search(sections["adaptation"]))

        lines += [
            f"### Finding {i} — `{item.source_ref}` (Tier: `{method}`)",
            "",
            f"**Confidence:** `{item.confidence}`",
            "",
            "**Source `key_equations_md` (ground truth for comparison):**",
            "",
        ]
        if source_eq:
            lines += ["```", source_eq, "```"]
        else:
            lines.append("*(none — paper has no extracted equations)*")
        lines += [
            "",
            "**Finding content (verbatim):**",
            "",
            "```markdown",
            item.content,
            "```",
            "",
            "**Checkpoint G placement checks:**",
            f"- Mechanism contains LaTeX (`$$`): **{mechanism_has_eq}**",
            f"- Adaptation contains LaTeX (`$$`): **{adaptation_has_eq}** "
            "(must be False — locked rule)",
            "",
            "---",
            "",
        ]
    lines += [
        "## How to review",
        "",
        "Verify each finding against the **§10.5 Phase-2 acceptance criteria** "
        "and the **Checkpoint G sub-criteria** (see "
        "`docs/commit_plan_ml_literature_review.md` §523). Promote the run "
        "into a dated section of `docs/validation_suite_runs.md` once sign-off "
        "is complete.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_phase2_cache_loader_offline(tmp_path):
    """Round-trip a canned resolve+extract JSON pair through the loader.

    Verifies the loader builds a valid ``RetrievedPaper`` without going
    near the live API stack. Catches regressions in the two-file cache
    schema before they break the real_run path.
    """
    # Write a minimal pair of cache files for one fake paper.
    arxiv_id = "0000.00001"
    paper_id = f"arxiv:{arxiv_id}"
    resolve_path, extract_path = _cache_paths(tmp_path, paper_id)
    resolve_path.write_text(
        json.dumps(
            {
                "source_type": "arxiv",
                "identifier": arxiv_id,
                "s2_metadata": {"title": "Fake", "year": 2024, "paperId": "x"},
                "full_text": "body",
                "extraction_method": "arxiv_source",
                "verbosity_achieved": 1,
            }
        ),
        encoding="utf-8",
    )
    extract_path.write_text(
        json.dumps(
            {
                "title": "Fake",
                "authors": "A",
                "year": "2024",
                "core_idea": "c",
                "architecture_details": "ad",
                "key_results": "kr",
                "relevance_to_task": "rt",
                "key_equations_md": "$$y = f(x)$$",
                "pseudocode_md": "",
                "extraction_method": "arxiv_source",
            }
        ),
        encoding="utf-8",
    )

    rp = _load_retrieved_from_cache(arxiv_id, tmp_path)
    assert rp.paper_id == paper_id
    assert rp.extract is not None
    assert rp.extract.extraction_method == "arxiv_source"
    assert rp.extract.key_equations_md == "$$y = f(x)$$"
    assert rp.verbosity_achieved == 1


def test_phase2_cache_loader_missing_files_raises(tmp_path):
    """Missing cache files surface a clear error pointing at the Phase-1
    pilot (the corpus loader turns this into a pytest.skip)."""
    with pytest.raises(FileNotFoundError, match="Phase-1 cache missing"):
        _load_retrieved_from_cache("9999.99999", tmp_path)


@pytest.mark.real_run
@pytest.mark.skipif(
    not _HAS_KEYS,
    reason="needs S2_API_KEY (Phase-1 cache provenance) + DEEPSEEK_API_KEY (synthesis)",
)
def test_phase2_pilot_real_run(tmp_path):
    """Run the 2d-updated synthesis on the locked §10 corpus and emit the
    Checkpoint G artifact.

    Structural assertions only — see this file's docstring for the operator-
    review sub-criteria.
    """
    retrieved = _load_corpus_or_skip(CACHE_DIR)
    inp = _phase2_input(tmp_path, retrieved)

    # The agent's _synthesize() is the production code path. We instantiate
    # the agent, manually wire its bridge (bypassing the lazy bridge_factory
    # call inside .run() — we don't want to re-resolve or re-compress), then
    # call the private method directly. Mirrors what production does after
    # resolve + dynamic-search loop.
    agent = MLLiteratureReviewAgent(root_cache_dir=str(tmp_path / "cache"))
    agent.bridge = LLMBridge(provider=DEEPSEEK_PROVIDER, model_id=DEEPSEEK_MODEL_ID)
    findings = agent._synthesize(inp, retrieved)

    # ----- Render the artifact FIRST, before any structural assertion. -----
    # The DeepSeek call is the expensive part of this test. Whether or not the
    # structural floor passes, the operator wants the rendered artifact on
    # disk for Checkpoint G review — a failed assertion in the middle of the
    # checks would otherwise lose the run's output entirely.
    artifact = _render_phase2_artifact(findings, retrieved, inp)
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(artifact, encoding="utf-8")
    # Print the hand-off line up-front too so it's visible even when a later
    # assertion fails.
    print(f"\n=== §10 Phase-2 pilot artifact written to: {ARTIFACT_PATH} ===")
    print(
        "Review against Checkpoint G sub-criteria (§523 of "
        "commit_plan_ml_literature_review.md), then promote into a dated "
        "section of docs/validation_suite_runs.md after sign-off."
    )

    # ----- Structural floor checks (post-artifact-write). -----
    # 1. >=2 findings — see the floor comment below.
    #
    # >=2 is the correct floor for this seed — the synthesis prompt grounds
    # each finding in a bottleneck, and this pilot seed has only 2 bottlenecks
    # + dynamic_search.enabled=False (root papers only). In production with a
    # richer interpretation seed and dynamic search enabled, finding count
    # will be higher. See nodes/ml_literature_review.md §"Parameter Reference"
    # for the full set of finding-count levers (bottlenecks count, omit_below,
    # transfer_tolerance, dynamic_search.enabled, etc.). The §10.5 spec's >=4
    # remains the bar for FULL §10 suite runs — this Phase-2 pilot is a
    # narrower spot-check that validates the 2d synthesis-prompt update,
    # not the full §10 acceptance criteria.
    assert len(findings) >= 2, (
        f"expected >=2 findings, got {len(findings)}. "
        f"Either the synthesis prompt regressed or DeepSeek omitted too many. "
        f"Artifact for review: {ARTIFACT_PATH}"
    )

    # 2. Every finding parses into three labeled sections.
    by_paper_id = {rp.paper_id: rp for rp in retrieved}
    for i, item in enumerate(findings, start=1):
        sections = _extract_sections(item.content)
        for name in ("implication", "mechanism", "adaptation"):
            assert sections[name], (
                f"finding #{i} ({item.source_ref!r}) missing **{name.title()}:** "
                f"section. Content: {item.content!r}"
            )

    # 3. Locked placement rule: Adaptation MUST NOT contain raw LaTeX ($$
    # blocks). Applies to ALL findings regardless of tier.
    adaptation_violations: list[str] = []
    for i, item in enumerate(findings, start=1):
        sections = _extract_sections(item.content)
        if _LATEX_DELIMITER_RE.search(sections["adaptation"]):
            adaptation_violations.append(f"finding #{i} ({item.source_ref})")
    assert not adaptation_violations, (
        "Adaptation contains raw LaTeX ($$ blocks) — violates 2d placement "
        f"rule. Offenders: {adaptation_violations}. "
        f"Artifact for review: {ARTIFACT_PATH}"
    )

    # 4. Tier-1 verbatim check: for findings citing a Tier-1 paper whose
    # source key_equations_md is non-empty, Mechanism should contain a LaTeX
    # block (the LLM actually quoted the equation rather than dropping it).
    tier1_missing_eq: list[str] = []
    tier2_missing_flag: list[str] = []
    for i, item in enumerate(findings, start=1):
        rp = by_paper_id.get(item.source_ref)
        if rp is None or rp.extract is None:
            continue
        method = rp.extract.extraction_method
        sections = _extract_sections(item.content)
        if method == "arxiv_source" and rp.extract.key_equations_md.strip():
            if not _LATEX_DELIMITER_RE.search(sections["mechanism"]):
                tier1_missing_eq.append(f"finding #{i} ({item.source_ref})")
        elif method == "pdfplumber_llm":
            mech_lower = sections["mechanism"].lower()
            if not any(flag in mech_lower for flag in _TIER2_FLAG_WORDS):
                tier2_missing_flag.append(f"finding #{i} ({item.source_ref})")

    assert not tier1_missing_eq, (
        "Tier-1 citations missing a LaTeX equation in Mechanism (placement "
        f"rule violated): {tier1_missing_eq}. Source extracts had non-empty "
        f"key_equations_md but the LLM omitted them. "
        f"Artifact for review: {ARTIFACT_PATH}"
    )
    # Tier-2 flag is a soft-strict check: only fails if a Tier-2 paper was
    # cited at all. If the LLM omitted SNRAware entirely, that's a valid
    # synthesis decision per the omission rule.
    assert not tier2_missing_flag, (
        "Tier-2 citations missing a paraphrase / flag word "
        f"(approximate / paraphrased / reconstructed / degraded): "
        f"{tier2_missing_flag}. Synthesis prompt's per-tier instruction "
        f"may have regressed. "
        f"Artifact for review: {ARTIFACT_PATH}"
    )
