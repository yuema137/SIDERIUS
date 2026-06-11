#!/usr/bin/env python
"""
§10 Phase-2 diagnostic — dynamic search DISABLED.

Re-runs the §10 Phase-2 FULL pipeline on the same 7-paper §10.2 corpus,
same _interp_seed bottlenecks, same `findings_verbosity=1`, same
`synthesis.transfer_tolerance="moderate"`, same DeepSeek bridge — but with
`dynamic_search.enabled=False`. Goal: isolate whether TADA / FreLE / etc.
fail to appear in the §10 FULL synthesis findings because

  (a) dynamic-search context noise pushes them out of the LLM's window, OR
  (b) synthesis stochasticity alone drops them across re-rolls.

If this diagnostic produces ≥ the same set of TADA/FreLE-style root-paper
citations the most recent §10 FULL run did, (a) is exonerated and (b) is
the cause. If it produces strictly MORE such citations, dynamic-search
noise is (at least partly) the cause.

Inputs:
  * S2_API_KEY (used by the root-paper resolver IFF a cache miss happens;
    with Phase-1 cache populated, S2 is touched 0 times).
  * DEEPSEEK_API_KEY (used by the synthesis LLM).
  * reference_data/lit_review_pilot_cache/ populated with Phase-1 extracts
    (run test_ml_literature_review_phase1_pilot.py first if missing).

Output artifact:
  reference_data/lit_review_pilot_cache/phase2_diagnostic_no_search_report.md

Cost: synthesis-only on cached extracts. Realistic budget: $0.30-$1.50,
2-5 minute wall time on deepseek-v4-pro. No dynamic-search calls means
no per-round search-decision LLM cost.

Run with:
  .venv/bin/python scripts/phase2_diagnostic_no_dynamic_search.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

# Make the project root importable as if we were under pytest.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

from agent.llm_bridge import LLMBridge  # noqa: E402
from agent.schemas.literature_review import (  # noqa: E402
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperSource,
    SynthesisConfig,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig  # noqa: E402
from nodes.ml_literature_review import MLLiteratureReviewAgent  # noqa: E402

# Reuse the locked §10.2 corpus + helpers from the Phase-2 pilot.
from tests.integration.nodes.test_ml_literature_review_phase2_pilot import (  # noqa: E402
    CACHE_DIR,
    CORPUS,
    DEEPSEEK_MODEL_ID,
    DEEPSEEK_PROVIDER,
    _interp_seed,
    _load_corpus_or_skip,
    _render_phase2_artifact,
)

ARTIFACT_PATH = CACHE_DIR / "phase2_diagnostic_no_search_report.md"


def _diagnostic_input(workspace: Path) -> LiteratureReviewInput:
    """Build a ``LiteratureReviewInput`` matching the FULL run EXCEPT
    ``dynamic_search.enabled=False`` (max_rounds left at 3 for symmetry; it is
    not consulted when disabled). All other parameters identical so the
    only causal difference between this diagnostic and the latest FULL
    artifact is dynamic search.
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
            enabled=False,  # the diagnostic variable
            max_rounds=3,
        ),
        synthesis_config=SynthesisConfig(transfer_tolerance="moderate"),
        findings_verbosity=1,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=str(workspace), run_name="phase2_diagnostic_no_search"
            ),
        ),
        run_name="phase2_diagnostic_no_search",
        llm_provider=DEEPSEEK_PROVIDER,
        llm_model_id=DEEPSEEK_MODEL_ID,
    )


def main() -> int:
    if not os.getenv("S2_API_KEY"):
        print("ERROR: S2_API_KEY not set — needed if any cache miss occurs.")
        return 2
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("ERROR: DEEPSEEK_API_KEY not set — needed for synthesis.")
        return 2

    # Phase-1 cache must be populated. Otherwise this turns into a live
    # S2 + extraction run, which is not what the diagnostic budgets for.
    _load_corpus_or_skip(CACHE_DIR)

    with tempfile.TemporaryDirectory(prefix="phase2_diag_") as tmp:
        workspace = Path(tmp)
        inp = _diagnostic_input(workspace)
        agent = MLLiteratureReviewAgent(root_cache_dir=str(CACHE_DIR))
        agent.bridge = LLMBridge(provider=DEEPSEEK_PROVIDER, model_id=DEEPSEEK_MODEL_ID)

        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        print(f"\n=== §10 Phase-2 diagnostic (no-dynamic-search) START {started_at} ===")
        output = agent.run(inp)
        finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        print(f"=== §10 Phase-2 diagnostic END   {finished_at} ===")

        findings = output.findings
        retrieved = output.retrieved_papers

    # Per-root-paper finding counts — the diagnostic signal.
    root_arxiv_ids = {p["arxiv_id"] for p in CORPUS}
    per_root_finding_count: dict[str, int] = {a: 0 for a in root_arxiv_ids}
    for item in findings:
        # source_ref is "{source_type}:{identifier}" — strip the prefix.
        ref = item.source_ref.split(":", 1)[-1] if ":" in item.source_ref else item.source_ref
        if ref in per_root_finding_count:
            per_root_finding_count[ref] += 1

    cited_roots = sum(1 for c in per_root_finding_count.values() if c > 0)
    print("\n=== Per-root-paper finding count ===")
    for paper in CORPUS:
        aid = paper["arxiv_id"]
        title = paper.get("short_title", paper.get("title", aid))
        print(f"  {aid:<14} ({title:<24}) — findings: {per_root_finding_count[aid]}")
    print(f"\nRoot papers with ≥1 finding: {cited_roots} of {len(CORPUS)}  (§10.5 floor: ≥2 of 7)")
    print(f"Total findings: {len(findings)}")

    # Render the same artifact the FULL test renders, but write to the
    # diagnostic path so we don't clobber the §10 FULL artifact.
    artifact = _render_phase2_artifact(findings, retrieved, inp)
    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(artifact, encoding="utf-8")
    print(f"\n=== Diagnostic artifact written to: {ARTIFACT_PATH} ===")
    print(
        "Compare against the latest §10 FULL artifact at "
        f"{CACHE_DIR / 'phase2_full_report.md'}\n"
        "to determine whether dynamic-search noise or synthesis "
        "stochasticity is responsible for missing root-paper citations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
