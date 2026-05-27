"""
Real-API integration tests for ``paper_resolver_skill`` (Commit 2).

These validate the four root-paper source types end-to-end against the live
Semantic Scholar API + real ``pdfplumber`` — the unit suite only covers mocked
HTTP/PDF. They are **opt-in**: the arxiv/doi/openreview tests are marked
``@real_run`` and skip without an S2 API key; the local ``.txt`` test is offline
(no network/key) and always runs.

Run the network ones with:
  uv run pytest -m real_run tests/integration/skills/test_paper_resolver_skill.py -v -s

Source-type coverage (see docs/paper_resolver_pilot.md):
  arxiv      — TIDMAD primary paper, exercises the arxiv-fallback PDF path.
  doi        — same paper via its DataCite DOI; cross-checks ArXiv id.
  openreview — S2 does not currently index OpenReview forum URLs (no fallback
               yet); xfail until coverage lands. See external_agents §9.
  local      — real file read of a committed reference_data fixture (offline).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv

from agent.skills.paper_resolver_skill.wrapper import run_skill

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

TIDMAD_ARXIV = "2406.04378"
TIDMAD_DOI = "10.48550/arXiv.2406.04378"
# ICLR 2024 (TimeMixer). Kept as a real fixture so the xfail flips to xpass
# automatically if S2 ever indexes OpenReview forum URLs.
OPENREVIEW_URL = "https://openreview.net/forum?id=7oLshfEIC2"


@pytest.mark.real_run
def test_resolve_arxiv_real():
    out = run_skill(
        None, mode="resolve", source_type="arxiv",
        identifier=TIDMAD_ARXIV, verbosity=1,
    )
    assert out["status"] == "ok", out["message"]
    md = out["data"]["s2_metadata"]
    assert md is not None
    assert "TIDMAD" in (md["title"] or "")
    assert out["data"]["full_text"]  # non-empty real extraction
    assert out["data"]["verbosity_achieved"] == 1


@pytest.mark.real_run
def test_resolve_doi_real():
    out = run_skill(
        None, mode="resolve", source_type="doi",
        identifier=TIDMAD_DOI, verbosity=0,
    )
    assert out["status"] == "ok", out["message"]
    md = out["data"]["s2_metadata"]
    assert md is not None
    assert "TIDMAD" in (md["title"] or "")
    # DOI resolves to the same paper as the arxiv path.
    assert md["externalIds"].get("ArXiv") == TIDMAD_ARXIV


@pytest.mark.real_run
@pytest.mark.xfail(
    reason=(
        "S2 coverage of OpenReview forum URLs is inconsistent — the TimeMixer "
        "URL is not indexed, and there is no OpenReview-API fallback yet "
        "(see docs/external_agents_for_proposer.md §9). The URL-encoding bug "
        "that truncated '?id=' is fixed, so a correctly-formed URL now reaches "
        "S2; this xfail tracks coverage, not encoding."
    ),
    strict=False,
)
def test_resolve_openreview_real():
    out = run_skill(
        None, mode="resolve", source_type="openreview",
        identifier=OPENREVIEW_URL, verbosity=0,
    )
    assert out["status"] == "ok", out["message"]
    assert out["data"]["s2_metadata"] is not None


def test_resolve_local_txt_offline():
    # Offline: real file read of a committed fixture; no network/key needed,
    # so this is intentionally NOT marked real_run.
    out = run_skill(
        None, mode="resolve", source_type="local",
        identifier="reference_data/tidmad_signal_frequencies.txt", verbosity=1,
    )
    assert out["status"] == "ok", out["message"]
    assert out["data"]["s2_metadata"] is None
    assert out["data"]["full_text"]  # non-empty real read
    assert out["data"]["verbosity_achieved"] == 1
