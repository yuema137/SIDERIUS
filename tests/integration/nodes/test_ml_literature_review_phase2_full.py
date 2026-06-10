"""
§10 Phase-2 FULL run — Commit P phase exit / pre-Commit-6 gate.

Drives the lit-review node's FULL synthesis pipeline on the seven §10.2
corpus papers with the real DeepSeek bridge, dynamic search ENABLED (3
rounds, results_per_query default), ``transfer_tolerance="moderate"``,
and ``findings_verbosity=1`` — matching the FULL §10.4 procedure
verbatim. Promotes the artifact for §10.5 acceptance review (≥2 of 7
papers produce ≥1 finding — collapse-detection floor; primary quality
gate is the per-finding structural assertions below, see §10.5.a in
docs/external_agents_for_proposer.md).

Difference vs the Phase-2 pilot (``test_ml_literature_review_phase2_pilot.py``):

* Pilot calls ``agent._synthesize(inp, retrieved)`` directly with cached
  ``retrieved`` (no resolve, no dynamic search). FULL calls
  ``agent.run(inp)`` so the dynamic-search loop actually fires.
* Pilot disables dynamic search (root papers only, 2 bottlenecks);
  FULL enables it (``max_rounds=3``) and uses the same 2-bottleneck
  seed but expects dynamic search to discover additional relevant
  papers and contribute findings.
* Pilot floor is ``len(findings) >= 2`` (relaxed for the narrow
  synthesis-prompt spot-check). FULL floor is ``≥2 of 7 ROOT papers
  produce at least one finding`` — the §10.5 spec bar, set to the
  stable-attractor count for the current 2-bottleneck seed (see
  §10.5.a). The primary quality gate is the per-finding structural
  assertions later in this file.

Cost: Phase-1 root-paper extracts are reused from
``reference_data/lit_review_pilot_cache/`` (same path the pilot writes
to), so root-paper resolve + compression are FREE (cache hits). Dynamic
search + synthesis ARE charged. Realistic budget: $1-6 per run, 5-15
minute wall time on deepseek-v4-pro.

Single test in this file:

* ``test_phase2_full_real_run`` — ``@real_run`` + skipped without S2 +
  DeepSeek keys AND without the Phase-1 cache populated. Runs the real
  FULL pipeline and validates the §10.5 floor.

Run with:
  uv run pytest -m real_run \\
    tests/integration/nodes/test_ml_literature_review_phase2_full.py -v -s

If the Phase-1 cache is missing, populate first by running
``test_ml_literature_review_phase1_pilot.py`` with ``@real_run``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.schemas.literature_review import (
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperSource,
    SynthesisConfig,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review import MLLiteratureReviewAgent

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

# Reuse the locked §10.2 corpus + provider config from the Phase-2 pilot.
# Imported by reference rather than copied so a corpus update in the pilot
# automatically propagates here.
from tests.integration.nodes.test_ml_literature_review_phase2_pilot import (  # noqa: E402
    _LATEX_DELIMITER_RE,  # broad LaTeX-delimiter regex (Tier-1 verbatim-quote check)
    _TIER2_FLAG_WORDS,  # Tier-2 paraphrase flag tokens
    CACHE_DIR,
    CORPUS,
    DEEPSEEK_MODEL_ID,
    DEEPSEEK_PROVIDER,
    _contains_equation_latex,  # equation-vs-shape discriminator for Adaptation rule
    _extract_sections,  # parser for 3-part finding content
    _interp_seed,
    _load_corpus_or_skip,
    _render_phase2_artifact,
)

ARTIFACT_PATH = CACHE_DIR / "phase2_full_report.md"

_HAS_KEYS = bool(os.getenv("S2_API_KEY")) and bool(os.getenv("DEEPSEEK_API_KEY"))


# ---------------------------------------------------------------------------
# §10 FULL input builder — mirrors the §10.4 spec
# ---------------------------------------------------------------------------


def _phase2_full_input(tmp_path: Path) -> LiteratureReviewInput:
    """Build a ``LiteratureReviewInput`` for the §10 FULL run.

    Differs from the pilot's ``_phase2_input`` only in:
    * ``dynamic_search.enabled=True`` with ``max_rounds=3``
    * ``synthesis.transfer_tolerance="moderate"`` explicitly
    * ``findings_verbosity=1`` explicitly
    """
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
        dynamic_search=DynamicSearchConfig(
            enabled=True,
            max_rounds=3,
        ),
        synthesis=SynthesisConfig(transfer_tolerance="moderate"),
        findings_verbosity=1,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="phase2_full"),
        ),
        run_name="phase2_full",
        llm_provider=DEEPSEEK_PROVIDER,
        llm_model_id=DEEPSEEK_MODEL_ID,
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.real_run
@pytest.mark.skipif(
    not _HAS_KEYS,
    reason="needs S2_API_KEY (root-paper resolve + dynamic search) + DEEPSEEK_API_KEY (synthesis + search decisions)",
)
def test_phase2_full_real_run(tmp_path):
    """Run the FULL §10 Phase-2 pipeline and emit the acceptance artifact.

    Validates the §10.5 collapse-detection floor:
        ≥2 of the 7 ROOT papers produce at least one finding.

    The 2-of-7 floor is the stable-attractor count for the current
    2-bottleneck seed (Mamba + FreLE map 1:1 to the bottlenecks), NOT
    the typical run-to-run yield. See §10.5.a in
    docs/external_agents_for_proposer.md for the calibration principle.
    The primary quality gate is the per-finding structural assertions
    earlier in this function — the count floor only guards against
    catastrophic synthesis collapse.
    """
    # Verify the Phase-1 cache is populated before launch — otherwise root
    # papers get re-resolved from S2 and the run becomes much more expensive
    # than budgeted. The cache loader does this check and skips with a clear
    # error pointing at the Phase-1 pilot.
    _load_corpus_or_skip(CACHE_DIR)

    # Reuse Phase-1's cache for root-paper resolution. The agent reads
    # the {safe_id}.resolve.json / {safe_id}.extract.json files at this path
    # before falling back to a live S2 + extraction.
    inp = _phase2_full_input(tmp_path)
    agent = MLLiteratureReviewAgent(root_cache_dir=str(CACHE_DIR))
    agent.bridge = LLMBridge(provider=DEEPSEEK_PROVIDER, model_id=DEEPSEEK_MODEL_ID)

    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"\n=== §10 FULL run START {started_at} ===")
    output = agent.run(inp)
    finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    print(f"=== §10 FULL run END   {finished_at} ===")

    findings = output.findings
    retrieved = output.retrieved_papers

    # ----- Render the artifact FIRST, before any structural assertion. -----
    # Same rationale as the pilot: DeepSeek + dynamic-search calls are the
    # expensive part. Whether or not the floor passes, the operator wants
    # the artifact on disk for §10.5 review.
    artifact = _render_phase2_artifact(findings, retrieved, inp)
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(artifact, encoding="utf-8")
    print(f"\n=== §10 Phase-2 FULL artifact written to: {ARTIFACT_PATH} ===")
    print(
        "Review against §10.5 acceptance criteria in "
        "docs/external_agents_for_proposer.md, then promote into a dated "
        "section of docs/validation_suite_runs.md after sign-off."
    )
    print(f"Findings emitted: {len(findings)}")
    print(f"Retrieved papers: {len(retrieved)} (root + dynamic-search)")
    print(f"Search rounds used: {output.search_rounds_used}/3")

    # ----- §10.5 Phase-2 equation-aware sub-checks (Checkpoint G structural) -----
    # Ported from test_ml_literature_review_phase2_pilot.py. These are the
    # locked Mechanism-vs-Adaptation placement rule + Tier-1 verbatim-quote
    # + Tier-2 paraphrase-flag checks. A §10 FULL regression on any of
    # these is a Checkpoint G regression and must fail the suite
    # automatically — not just surface in the artifact's textual placement
    # check (which is what allowed the 2026-06-09 first FULL run's Finding-3
    # placement violation to escape pytest verification).
    by_paper_id = {rp.paper_id: rp for rp in retrieved}

    # (a) Every finding parses into three labeled sections (Implication /
    # Mechanism / Adaptation). If findings is empty this loop is vacuous —
    # the floor check below handles the catastrophic empty-findings case.
    for i, item in enumerate(findings, start=1):
        sections = _extract_sections(item.content)
        for name in ("implication", "mechanism", "adaptation"):
            assert sections[name], (
                f"finding #{i} ({item.source_ref!r}) missing **{name.title()}:** "
                f"section. Artifact: {ARTIFACT_PATH}"
            )

    # (b) Locked placement rule: Adaptation MUST NOT contain a re-quoted
    # equation. Applies to ALL findings regardless of tier. Pure shape
    # annotations like \([B,256,T]\) and single-variable references like
    # $T$ are allowed — only equation-like content (has '=' or a LaTeX
    # operator macro) is a violation. See _contains_equation_latex.
    adaptation_violations: list[str] = []
    for i, item in enumerate(findings, start=1):
        sections = _extract_sections(item.content)
        if _contains_equation_latex(sections["adaptation"]):
            adaptation_violations.append(f"finding #{i} ({item.source_ref})")
    assert not adaptation_violations, (
        "Adaptation contains a re-quoted equation — Commit 2d locked "
        "Mechanism-vs-Adaptation placement rule violated. Equation-like "
        "content (has '=' or a LaTeX operator macro) must stay in "
        "Mechanism, not Adaptation. Shape annotations like \\([B,T]\\) "
        f"are allowed. Offenders: {adaptation_violations}. "
        f"Artifact: {ARTIFACT_PATH}"
    )

    # (c) Tier-1 verbatim check + Tier-2 paraphrase-flag check.
    tier1_missing_eq: list[str] = []
    tier2_missing_flag: list[str] = []
    for i, item in enumerate(findings, start=1):
        rp = by_paper_id.get(item.source_ref)
        if rp is None or rp.extract is None:
            # Dynamic-search papers without a stored extract — skip the
            # per-tier source-fidelity checks (no ground truth to compare to).
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
        "Tier-1 citations missing a LaTeX equation in Mechanism — "
        "Checkpoint G verbatim-quote regression. Source extracts had "
        f"non-empty key_equations_md but the LLM omitted them: "
        f"{tier1_missing_eq}. Artifact: {ARTIFACT_PATH}"
    )
    assert not tier2_missing_flag, (
        "Tier-2 citations missing a paraphrase / flag word "
        "(approximate / paraphrased / reconstructed / degraded): "
        f"{tier2_missing_flag}. Synthesis prompt's per-tier instruction "
        f"may have regressed. Artifact: {ARTIFACT_PATH}"
    )

    # ----- §10.5 collapse-detection floor (Phase 2): ≥2 of 7 root papers ----
    # The floor is the stable-attractor count for the current 2-bottleneck
    # seed, not the typical yield (which is stochastic in the 2-3 range).
    # Per-finding structural quality is gated by the assertions above; this
    # backstop only fires on catastrophic synthesis collapse. See §10.5.a in
    # docs/external_agents_for_proposer.md.
    root_paper_ids = {f"arxiv:{p['arxiv_id']}" for p in CORPUS}
    cited_root_ids = {item.source_ref for item in findings if item.source_ref in root_paper_ids}
    assert len(cited_root_ids) >= 2, (
        f"§10.5 collapse-detection floor failed: only {len(cited_root_ids)} "
        f"of 7 root papers produced findings; need >=2 (stable-attractor "
        f"count for the current 2-bottleneck seed, not typical yield — "
        f"see §10.5.a in docs/external_agents_for_proposer.md). "
        f"Cited root papers: {sorted(cited_root_ids)}. "
        f"Total findings: {len(findings)}. "
        f"Search rounds used: {output.search_rounds_used}. "
        f"Artifact for review: {ARTIFACT_PATH}"
    )
