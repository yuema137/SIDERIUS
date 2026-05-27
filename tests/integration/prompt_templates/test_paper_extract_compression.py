"""
Real-API integration test for the paper-compression prompt (Commit 3).

End-to-end: resolve the TIDMAD paper's full text via ``paper_resolver_skill``
(live Semantic Scholar + arxiv PDF), render the compression prompt, call the
real ``LLMBridge``, and validate the result into ``PaperExtract``. This is the
Behavioral Checkpoint B driver — it prints the extract so a human can judge
compression quality.

Opt-in: marked ``@real_run`` and skipped unless BOTH ``S2_API_KEY`` (PDF
resolution) and ``OPENAI_API_KEY`` (compression) are present.

Run with:
  uv run pytest -m real_run tests/integration/prompt_templates/test_paper_extract_compression.py -v -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge
from agent.prompt_templates.literature_review import render_paper_extract_prompt
from agent.schemas.literature_review import PaperExtract
from agent.skills.paper_resolver_skill.wrapper import run_skill

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

TIDMAD_ARXIV = "2406.04378"

_HAS_KEYS = bool(os.getenv("S2_API_KEY")) and bool(os.getenv("OPENAI_API_KEY"))


@pytest.mark.real_run
@pytest.mark.skipif(
    not _HAS_KEYS,
    reason="needs S2_API_KEY (PDF resolution) + OPENAI_API_KEY (compression)",
)
def test_compress_tidmad_real():
    # 1. Resolve the TIDMAD full text (live S2 + arxiv PDF fallback, F1).
    resolved = run_skill(
        None,
        mode="resolve",
        source_type="arxiv",
        identifier=TIDMAD_ARXIV,
        verbosity=2,
    )
    assert resolved["status"] == "ok", resolved["message"]
    full_text = resolved["data"]["full_text"]
    assert full_text, "expected non-empty extracted text"

    # 2. Compress via the real LLM.
    bridge = LLMBridge(provider="openai", model_id="gpt-4o-mini")
    system, user = render_paper_extract_prompt(full_text)
    raw = bridge.generate(system, user, label="lit_review.paper_extract")

    # 3. generate() returns a parsed dict — validate it into PaperExtract.
    extract = PaperExtract.model_validate(raw)

    # Sanity only; the human judges compression quality at Checkpoint B.
    assert extract.title, "title should be populated"
    assert extract.architecture_details, "architecture_details should be populated"

    # Printed so the run output is the Checkpoint B artifact source.
    print("\n=== PaperExtract (TIDMAD) ===")
    print(json.dumps(extract.model_dump(), indent=2))
