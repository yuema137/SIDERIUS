"""
Tier-1 real-API integration test for the ml_literature_review node (Commit 4b).

End-to-end with a real ``LLMBridge`` (DeepSeek — the shipped default, see
docs/dynamic_search_pilot.md) + live Semantic Scholar / arxiv: one root paper
(TIDMAD), a 2-round dynamic search loop, and synthesis into
``LiteratureReviewOutput``. The experiment-history seed is hand-built here
(self-contained) — Checkpoint C separately exercises the loop on a richer seed.
Runs with the shipped config defaults (``findings_verbosity=1``,
``synthesis_config.transfer_tolerance="moderate"``).

Opt-in: ``@real_run`` + skipped unless BOTH ``S2_API_KEY`` and
``DEEPSEEK_API_KEY`` are present.

Run with:
  uv run pytest -m real_run tests/integration/nodes/test_ml_literature_review.py -v -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import (
    DynamicSearchConfig,
    LiteratureReviewInput,
    PaperSource,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_literature_review import MLLiteratureReviewAgent

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

TIDMAD_ARXIV = "2406.04378"
_HAS_KEYS = bool(os.getenv("S2_API_KEY")) and bool(os.getenv("DEEPSEEK_API_KEY"))


def _interp_seed() -> InterpretationOutput:
    """Representative experiment state for a full-spectrum denoising run."""
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


@pytest.mark.real_run
@pytest.mark.skipif(
    not _HAS_KEYS,
    reason="needs S2_API_KEY (resolution/search) + DEEPSEEK_API_KEY (compression/synthesis)",
)
def test_node_real_run(tmp_path):
    inp = LiteratureReviewInput(
        experiment_history=_interp_seed(),
        root_papers=[PaperSource(source_type="arxiv", identifier=TIDMAD_ARXIV, verbosity=1)],
        dynamic_search=DynamicSearchConfig(enabled=True, max_rounds=2),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="tier1"),
        ),
        run_name="tier1",
        llm_provider="deepseek",
        llm_model_id="deepseek-v4-pro",
    )

    agent = MLLiteratureReviewAgent(root_cache_dir=str(tmp_path / "cache"))
    out = agent.run(inp)

    # --- Structural assertions ---
    assert out.agent_card.agent_name == "ml_literature_review"
    assert out.retrieved_papers, "expected at least the root paper"
    # Every cited paper_id must exist in the retrieved set (source_ref soft-drop).
    retrieved_ids = {rp.paper_id for rp in out.retrieved_papers}
    assert out.findings, "expected at least one ExpertContextItem in findings"
    for item in out.findings:
        assert item.source_ref in retrieved_ids, f"finding cites unknown paper {item.source_ref!r}"
        assert item.confidence is None or 0.0 <= item.confidence <= 1.0

    # Root paper resolved + compressed.
    root = next(p for p in out.retrieved_papers if p.paper_id == f"arxiv:{TIDMAD_ARXIV}")
    assert root.extract is not None, "TIDMAD root should have a compressed extract"
    assert root.extract.architecture_details, "architecture_details should be populated"

    # Storage dump landed.
    assert (tmp_path / "ml_literature_review_tier1.json").exists()

    # Printed for human Checkpoint-style inspection (frequency-split qualifier, etc.).
    print("\n=== LiteratureReviewOutput (tier1) ===")
    print(json.dumps(out.model_dump(), indent=2))
