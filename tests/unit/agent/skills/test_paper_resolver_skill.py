"""
Unit tests for ``agent/skills/paper_resolver_skill/wrapper.py``.

All network and PDF-extraction calls are mocked. No live S2, no real
``pdfplumber``. The live pilot is captured separately in
``docs/paper_resolver_pilot.md`` (see Commit 2 of
docs/commit_plan_ml_literature_review.md).
"""

from __future__ import annotations

import os
import subprocess
import sys
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.skills.paper_resolver_skill import wrapper

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_skill_state(tmp_path):
    """Reset per-process skill state before each test.

    Clears the S2 cache, resets the throttle clock, and neutralises
    ``time.sleep`` so pacing/backoff never slows the suite. Tests that assert
    on pacing patch ``time.sleep`` themselves inside the test body.
    """
    wrapper._S2_CACHE.clear()
    wrapper._LAST_S2_REQUEST_TS = 0.0
    # Restore dotenv's direct environment writes as well as test overrides.
    # The autouse scope encloses each test's monkeypatch fixture teardown.
    environment = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("S2_", "PYTHON_DOTENV_", "RESOLVER_TEST_"))
    }
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(wrapper, "_PROJECT_ROOT", tmp_path),
        patch.object(wrapper.time, "sleep", lambda *_a, **_k: None),
        patch("dotenv.main.find_dotenv", side_effect=AssertionError("implicit dotenv lookup")),
    ):
        yield
    wrapper._S2_CACHE.clear()


def _ok_response(payload: dict) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = ""
    resp.content = b"PDFDATA"
    return resp


def _http_status_response(code: int, body: str = "boom") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = code
    resp.text = body
    resp.content = b""
    resp.headers = {}
    resp.json.side_effect = ValueError("no body")
    return resp


def _paper_with_oap() -> dict:
    return {
        "paperId": "abc123",
        "title": "Towards Robust Denoising",
        "authors": [{"authorId": "1", "name": "A. Smith"}],
        "year": 2023,
        "abstract": "Abstract text.",
        "openAccessPdf": {"url": "https://example.org/paper.pdf"},
        "externalIds": {"ArXiv": "2406.04378", "DOI": "10.1234/abc"},
    }


def _paper_without_oap_with_arxiv() -> dict:
    return {
        "paperId": "abc456",
        "title": "Closed Access Paper",
        "authors": [],
        "year": 2021,
        "abstract": None,
        "openAccessPdf": None,
        "externalIds": {"ArXiv": "2101.00001"},
    }


def _paper_metadata_only() -> dict:
    return {
        "paperId": "abc789",
        "title": "Metadata Only",
        "authors": [],
        "year": 2020,
        "abstract": None,
        "openAccessPdf": None,
        "externalIds": {"DOI": "10.9999/zz"},
    }


# ---------------------------------------------------------------------------
# Mode dispatch + validation
# ---------------------------------------------------------------------------


class TestModeDispatch:
    def test_missing_mode(self):
        out = wrapper.run_skill(None)
        assert out["status"] == "error"
        assert "mode" in out["message"]

    def test_invalid_mode(self):
        out = wrapper.run_skill(None, mode="explore")
        assert out["status"] == "error"
        assert "mode" in out["message"]

    def test_resolve_missing_identifier(self):
        out = wrapper.run_skill(None, mode="resolve", source_type="arxiv")
        assert out["status"] == "error"

    def test_resolve_bad_verbosity(self):
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv", identifier="x", verbosity=7
        )
        assert out["status"] == "error"
        assert "verbosity" in out["message"]

    def test_search_missing_query(self):
        out = wrapper.run_skill(None, mode="search")
        assert out["status"] == "error"
        assert "query" in out["message"]

    @pytest.mark.parametrize(
        ("mode", "kwargs", "message_part"),
        [
            (
                "resolve",
                {"source_type": "arxiv", "identifier": "x", "verbosity": "nope"},
                "verbosity",
            ),
            ("search", {"query": "x", "limit": "nope"}, "limit"),
            ("search", {"query": "x", "offset": "nope"}, "offset"),
        ],
    )
    @patch.object(wrapper.requests, "get")
    def test_malformed_direct_scalars_return_error_without_network(
        self, mock_get, mode, kwargs, message_part
    ):
        out = wrapper.run_skill(None, mode=mode, **kwargs)
        assert out["status"] == "error"
        assert out["data"] is None
        assert message_part in out["message"]
        mock_get.assert_not_called()

    @patch.object(wrapper.requests, "get")
    def test_unhashable_cache_input_returns_error_without_network(self, mock_get):
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier=[],
            verbosity=0,
        )
        assert out["status"] == "error"
        assert out["data"] is None
        assert "invalid" in out["message"]
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Resolve / arxiv — happy paths
# ---------------------------------------------------------------------------


class TestResolveArxiv:
    # NOTE: every test in this class short-circuits Tier-1 (`_try_arxiv_tier1`)
    # to None so the legacy openAccessPdf / arxiv-fallback path stays the
    # subject under test. Tier-1 (arxiv source tarball) cascade behavior has
    # its own class below (TestArxivTier1Cascade).

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper, "_extract_pdf_text", return_value=("EXTRACTED BODY", None))
    @patch.object(wrapper.requests, "get")
    def test_arxiv_openaccess_pdf_path(self, mock_get, mock_extract, mock_tier1):
        # First call: S2 metadata (has openAccessPdf).
        # Second call: PDF download.
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=1,
        )
        assert out["status"] == "ok"
        assert "openAccessPdf" in out["message"]
        assert out["data"]["full_text"] == "EXTRACTED BODY"
        assert out["data"]["verbosity_achieved"] == 1
        assert out["data"]["extraction_method"] == "pdfplumber_llm"
        # Confirm we hit the openAccessPdf URL, not the arxiv fallback.
        pdf_url = mock_get.call_args_list[1].args[0]
        assert pdf_url == "https://example.org/paper.pdf"

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper, "_extract_pdf_text", return_value=("FALLBACK BODY", None))
    @patch.object(wrapper.requests, "get")
    def test_arxiv_fallback_when_no_oap(self, mock_get, mock_extract, mock_tier1):
        mock_get.side_effect = [
            _ok_response(_paper_without_oap_with_arxiv()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2101.00001",
            verbosity=1,
        )
        assert out["status"] == "ok"
        assert "arxiv_fallback" in out["message"]
        pdf_url = mock_get.call_args_list[1].args[0]
        assert pdf_url == "https://arxiv.org/pdf/2101.00001.pdf"
        assert out["data"]["full_text"] == "FALLBACK BODY"
        assert out["data"]["extraction_method"] == "pdfplumber_llm"

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper.requests, "get")
    def test_arxiv_no_pdf_available(self, mock_get, mock_tier1):
        # S2 returns metadata but no openAccessPdf and no ArXiv external id.
        mock_get.return_value = _ok_response(_paper_metadata_only())
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="some-id",
            verbosity=1,
        )
        assert out["status"] == "partial"
        assert out["data"]["verbosity_achieved"] == 0
        assert out["data"]["s2_metadata"] is not None
        assert out["data"]["full_text"] is None
        assert out["data"]["extraction_method"] == "abstract_only"
        # Exactly one HTTP call — only the metadata lookup happened.
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_verbosity_0_skips_pdf(self, mock_get):
        mock_get.return_value = _ok_response(_paper_with_oap())
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=0,
        )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] is None
        # Only the metadata call — no PDF download attempted.
        assert mock_get.call_count == 1


# ---------------------------------------------------------------------------
# Resolve / doi + openreview
# ---------------------------------------------------------------------------


class TestResolveOtherSchemes:
    @patch.object(wrapper.requests, "get")
    def test_doi_metadata_only(self, mock_get):
        mock_get.return_value = _ok_response(_paper_metadata_only())
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="doi",
            identifier="10.9999/zz",
            verbosity=0,
        )
        assert out["status"] == "ok"
        assert out["data"]["s2_metadata"]["externalIds"]["DOI"] == "10.9999/zz"
        called_url = mock_get.call_args.args[0]
        assert "DOI:10.9999/zz" in called_url

    @patch.object(wrapper, "_extract_pdf_text", return_value=("OR BODY", None))
    @patch.object(wrapper.requests, "get")
    def test_openreview_full_text(self, mock_get, mock_extract):
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="openreview",
            identifier="https://openreview.net/forum?id=abc",
            verbosity=2,
        )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] == "OR BODY"
        assert out["data"]["verbosity_achieved"] == 2
        called_url = mock_get.call_args_list[0].args[0]
        assert "URL:" in called_url


# ---------------------------------------------------------------------------
# Tier-1 (arXiv source) cascade
# ---------------------------------------------------------------------------


class TestArxivTier1Cascade:
    """Two-tier extraction cascade — Commit 2c-b.

    The wrapper attempts Tier 1 (arxiv.org/src tarball → cleaned Markdown)
    before falling through to Tier 2 (openAccessPdf / arxiv fallback PDF +
    pdfplumber). An earlier design slotted a GPU-based marker-pdf converter
    between the two; it was cancelled before 2c-c — see §5a of
    ``docs/external_agents_for_proposer.md``.

    These tests pin the cascade behavior at the wrapper level; the parser
    itself is covered by ``test_arxiv_source.py``.
    """

    @patch.object(wrapper, "_try_arxiv_tier1", return_value="# Tier-1 Markdown\n\nBody.")
    @patch.object(wrapper.requests, "get")
    def test_tier1_success_short_circuits_pdf(self, mock_get, mock_tier1):
        # S2 metadata returns openAccessPdf, but Tier-1 succeeds first → we
        # never download the PDF, and extraction_method is "arxiv_source".
        mock_get.return_value = _ok_response(_paper_with_oap())
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=1,
        )
        assert out["status"] == "ok"
        assert "Tier 1" in out["message"]
        assert out["data"]["full_text"].startswith("# Tier-1 Markdown")
        assert out["data"]["verbosity_achieved"] == 1
        assert out["data"]["extraction_method"] == "arxiv_source"
        # S2 metadata only — no PDF download.
        assert mock_get.call_count == 1
        mock_tier1.assert_called_once_with("2406.04378")

    @patch.object(wrapper, "_extract_pdf_text", return_value=("PDF BODY", None))
    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper.requests, "get")
    def test_tier1_none_falls_through_to_tier3(self, mock_get, mock_tier1, mock_extract):
        # Tier 1 cleanly returns None → Tier 3 (pdfplumber on openAccessPdf)
        # runs, extraction_method ends up "pdfplumber_llm".
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=1,
        )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] == "PDF BODY"
        assert out["data"]["extraction_method"] == "pdfplumber_llm"
        mock_tier1.assert_called_once()

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper.requests, "get")
    def test_tier1_not_attempted_for_doi(self, mock_get, mock_tier1):
        # DOI source type has no arxiv id → Tier-1 must NOT be invoked.
        mock_get.return_value = _ok_response(_paper_metadata_only())
        wrapper.run_skill(
            None,
            mode="resolve",
            source_type="doi",
            identifier="10.9999/zz",
            verbosity=1,
        )
        mock_tier1.assert_not_called()

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper.requests, "get")
    def test_tier1_not_attempted_for_openreview(self, mock_get, mock_tier1):
        mock_get.return_value = _ok_response(_paper_metadata_only())
        wrapper.run_skill(
            None,
            mode="resolve",
            source_type="openreview",
            identifier="https://openreview.net/forum?id=abc",
            verbosity=1,
        )
        mock_tier1.assert_not_called()

    @patch.object(wrapper, "_try_arxiv_tier1", return_value="# T1")
    @patch.object(wrapper.requests, "get")
    def test_tier1_skipped_for_verbosity_0(self, mock_get, mock_tier1):
        # verbosity=0 → metadata-only; Tier-1 must NOT be triggered.
        mock_get.return_value = _ok_response(_paper_with_oap())
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=0,
        )
        assert out["data"]["full_text"] is None
        assert out["data"]["extraction_method"] == "abstract_only"
        mock_tier1.assert_not_called()


# ---------------------------------------------------------------------------
# _try_arxiv_tier1 — direct unit coverage
# ---------------------------------------------------------------------------


class TestTryArxivTier1Direct:
    """Direct coverage of ``_try_arxiv_tier1`` failure / success branches."""

    @patch.object(wrapper, "parse_arxiv_source", return_value="# Parsed")
    @patch.object(wrapper.requests, "get")
    def test_success_returns_parser_output(self, mock_get, mock_parse):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/x-eprint-tar"}
        resp.content = b"FAKE TARBALL"
        mock_get.return_value = resp
        out = wrapper._try_arxiv_tier1("2406.04378")
        assert out == "# Parsed"
        called_url = mock_get.call_args.args[0]
        assert called_url == "https://arxiv.org/src/2406.04378"
        mock_parse.assert_called_once_with(b"FAKE TARBALL")

    @patch.object(wrapper.requests, "get")
    def test_pdf_only_returns_none(self, mock_get):
        # Content-Type pdf → arXiv only stored a PDF; skip cleanly.
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/pdf"}
        resp.content = b"%PDF-..."
        mock_get.return_value = resp
        assert wrapper._try_arxiv_tier1("1234.56789") is None

    @patch.object(wrapper.requests, "get")
    def test_non_200_returns_none(self, mock_get):
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 404
        resp.headers = {}
        resp.content = b""
        mock_get.return_value = resp
        assert wrapper._try_arxiv_tier1("nope") is None

    @patch.object(wrapper.requests, "get", side_effect=requests.ConnectionError("boom"))
    def test_network_error_returns_none(self, mock_get):
        assert wrapper._try_arxiv_tier1("2406.04378") is None

    @patch.object(wrapper, "parse_arxiv_source", side_effect=RuntimeError("parser blew up"))
    @patch.object(wrapper.requests, "get")
    def test_parser_exception_returns_none(self, mock_get, mock_parse):
        # Defensive: any unhandled parser exception cleanly cascades.
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/x-eprint-tar"}
        resp.content = b"FAKE TARBALL"
        mock_get.return_value = resp
        assert wrapper._try_arxiv_tier1("2406.04378") is None


# ---------------------------------------------------------------------------
# Resolve / local
# ---------------------------------------------------------------------------


class TestResolveLocal:
    def test_local_md_direct_read(self, tmp_path, monkeypatch):
        # Anchor _PROJECT_ROOT at tmp_path so any repo-relative path
        # resolves there.
        monkeypatch.setattr(wrapper, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "notes").mkdir()
        (tmp_path / "notes" / "paper.md").write_text("# Local paper\nbody.")
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="local",
            identifier="notes/paper.md",
            verbosity=1,
        )
        assert out["status"] == "ok"
        assert "Local paper" in out["data"]["full_text"]
        assert out["data"]["s2_metadata"] is None

    def test_local_pdf_uses_pdfplumber_mock(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wrapper, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "papers").mkdir()
        (tmp_path / "papers" / "foo.pdf").write_bytes(b"%PDF-FAKE")
        with patch.object(
            wrapper, "_extract_pdf_text", return_value=("PDF BODY", None)
        ) as mock_extract:
            out = wrapper.run_skill(
                None,
                mode="resolve",
                source_type="local",
                identifier="papers/foo.pdf",
                verbosity=2,
            )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] == "PDF BODY"
        mock_extract.assert_called_once()

    def test_local_absolute_path_rejected(self):
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="local",
            identifier="/etc/passwd",
            verbosity=0,
        )
        assert out["status"] == "error"
        assert "absolute" in out["message"]

    def test_local_parent_traversal_rejected(self):
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="local",
            identifier="papers/../../../etc/passwd",
            verbosity=0,
        )
        assert out["status"] == "error"
        assert ".." in out["message"]

    def test_local_unsupported_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wrapper, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "weird.docx").write_text("nope")
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="local",
            identifier="weird.docx",
            verbosity=1,
        )
        assert out["status"] == "error"
        assert ".docx" in out["message"]


# ---------------------------------------------------------------------------
# Search-mode
# ---------------------------------------------------------------------------


class TestSearchMode:
    @patch.object(wrapper.requests, "get")
    def test_search_happy_path(self, mock_get):
        mock_get.return_value = _ok_response(
            {
                "total": 3,
                "offset": 0,
                "next": 3,
                "data": [
                    _paper_with_oap(),
                    _paper_without_oap_with_arxiv(),
                    _paper_metadata_only(),
                ],
            }
        )
        out = wrapper.run_skill(
            None,
            mode="search",
            query="squid denoising",
            limit=10,
            verbosity=0,
        )
        assert out["status"] == "ok"
        assert out["data"]["total"] == 3
        assert len(out["data"]["results"]) == 3
        assert out["data"]["results"][0]["title"] == "Towards Robust Denoising"
        # search must hit /paper/search, not /paper/{id}
        called_url = mock_get.call_args.args[0]
        assert called_url.endswith("/paper/search")

    @patch.object(wrapper.requests, "get")
    def test_search_empty_result(self, mock_get):
        mock_get.return_value = _ok_response({"total": 0, "offset": 0, "next": None, "data": []})
        out = wrapper.run_skill(
            None,
            mode="search",
            query="zzz no matches",
            limit=5,
        )
        assert out["status"] == "ok"
        assert out["data"]["results"] == []
        assert out["data"]["total"] == 0

    @patch.object(wrapper.requests, "get")
    def test_search_filter_passthrough(self, mock_get):
        mock_get.return_value = _ok_response({"total": 0, "offset": 0, "data": []})
        wrapper.run_skill(
            None,
            mode="search",
            query="denoising",
            year="2023",
            min_citation_count=10,
            fields_of_study="Computer Science",
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["year"] == "2023"
        assert params["minCitationCount"] == 10
        assert params["fieldsOfStudy"] == "Computer Science"

    @patch.object(wrapper.requests, "get")
    def test_search_limit_cap(self, mock_get):
        mock_get.return_value = _ok_response({"total": 0, "offset": 0, "data": []})
        wrapper.run_skill(
            None,
            mode="search",
            query="x",
            limit=10_000,
        )
        params = mock_get.call_args.kwargs["params"]
        assert params["limit"] == wrapper.S2_SEARCH_LIMIT_CAP


# ---------------------------------------------------------------------------
# Cache + error envelopes
# ---------------------------------------------------------------------------


class TestCachingAndErrors:
    @patch.object(wrapper.requests, "get")
    def test_resolve_cache_hit_skips_network(self, mock_get):
        mock_get.return_value = _ok_response(_paper_metadata_only())
        # Two identical calls — only the first should hit the network.
        out1 = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="doi",
            identifier="10.9999/zz",
            verbosity=0,
        )
        out2 = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="doi",
            identifier="10.9999/zz",
            verbosity=0,
        )
        assert out1 == out2
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_search_cache_hit_skips_network(self, mock_get):
        mock_get.return_value = _ok_response({"total": 0, "offset": 0, "data": []})
        wrapper.run_skill(None, mode="search", query="x", limit=3)
        wrapper.run_skill(None, mode="search", query="x", limit=3)
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_s2_network_error_returns_envelope(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=1,
        )
        assert out["status"] == "error"
        assert "S2 request failed" in out["message"]

    @patch.object(wrapper.requests, "get")
    def test_s2_non_retryable_http_error_returns_envelope(self, mock_get):
        # 404 is terminal — no retry, immediate error envelope, single call.
        mock_get.return_value = _http_status_response(404, "not found")
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="x",
            verbosity=0,
        )
        assert out["status"] == "error"
        assert "HTTP 404" in out["message"]
        assert mock_get.call_count == 1

    @patch.object(wrapper, "_try_arxiv_tier1", return_value=None)
    @patch.object(wrapper, "_extract_pdf_text", return_value=(None, "pdfplumber blew up"))
    @patch.object(wrapper.requests, "get")
    def test_pdf_extraction_failure_returns_partial(self, mock_get, mock_extract, mock_tier1):
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="arxiv",
            identifier="2406.04378",
            verbosity=1,
        )
        assert out["status"] == "partial"
        assert "extraction failed" in out["message"]
        assert out["data"]["s2_metadata"] is not None
        assert out["data"]["full_text"] is None
        # Tier-3 was attempted (pdfplumber) and failed → tier stays declared,
        # downstream LLM will read the abstract-only ceiling from the metadata.
        assert out["data"]["extraction_method"] == "abstract_only"


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_no_api_key_means_no_header(self, monkeypatch):
        monkeypatch.delenv("S2_API_KEY", raising=False)
        headers = wrapper._s2_headers()
        assert "x-api-key" not in headers

    def test_api_key_added_when_set(self, monkeypatch):
        monkeypatch.setenv("S2_API_KEY", "secret123")
        headers = wrapper._s2_headers()
        assert headers["x-api-key"] == "secret123"


class TestStandaloneCredentials:
    @pytest.mark.parametrize("mode", ["resolve", "search"])
    def test_public_request_loads_checkout_key_without_bridge(self, tmp_path, monkeypatch, mode):
        (tmp_path / ".env").write_text(
            "RESOLVER_TEST_BASE=file-value\nS2_API_KEY=${RESOLVER_TEST_BASE}\n"
            "S2_SHARED_KEY_WORKERS=2\nS2_SHARED_KEY_SLOT=0\n"
            "RESOLVER_TEST_EXTRA=loaded\n"
        )
        monkeypatch.setenv("RESOLVER_TEST_BASE", "environment-value")
        monkeypatch.setenv("S2_SHARED_KEY_SLOT", "1")
        other = tmp_path / "unrelated"
        other.mkdir()
        (other / ".env").write_text("S2_API_KEY=wrong-directory\n")
        monkeypatch.chdir(other)
        payload = _paper_metadata_only()
        response = payload if mode == "resolve" else {"data": [payload], "total": 1}

        def check_pacing():
            # The FIRST request must already see the file's shared-key policy.
            assert wrapper._shared_key_slot() == (2, 1)

        with (
            patch.object(wrapper, "_throttle_s2", side_effect=check_pacing) as pacing,
            patch.object(wrapper.requests, "get", return_value=_ok_response(response)) as get,
        ):
            out = wrapper.run_skill(
                None,
                mode=mode,
                source_type="doi",
                identifier="10.1234/demo",
                query="demo",
                verbosity=0,
            )
        assert out["status"] == "ok"
        pacing.assert_called_once()
        get.assert_called_once()
        assert get.call_args.kwargs["headers"]["x-api-key"] == "environment-value"
        assert os.environ["RESOLVER_TEST_EXTRA"] == "loaded"
        assert os.environ["RESOLVER_TEST_BASE"] == "environment-value"

    @pytest.mark.parametrize("key", ["exported-key", ""])
    def test_explicit_environment_key_bypasses_dotenv(self, tmp_path, monkeypatch, key):
        (tmp_path / ".env").write_text("S2_API_KEY=file-key\nRESOLVER_TEST_EXTRA=loaded\n")
        monkeypatch.setenv("S2_API_KEY", key)
        with (
            patch.object(wrapper, "load_dotenv", wraps=wrapper.load_dotenv) as load,
            patch.object(wrapper.requests, "get", return_value=_ok_response({"data": []})) as get,
        ):
            out = wrapper.run_skill(None, mode="search", query="demo")
        assert out["status"] == "ok"
        load.assert_not_called()
        headers = get.call_args.kwargs["headers"]
        assert headers == {
            "User-Agent": "siderius-paper-resolver/1.0",
            **({"x-api-key": "exported-key"} if key else {}),
        }
        assert "RESOLVER_TEST_EXTRA" not in os.environ

    @pytest.mark.parametrize("case", ["missing-file", "missing-key", "disabled", "installed"])
    def test_no_eligible_checkout_key_preserves_anonymous_request(
        self, tmp_path, monkeypatch, case
    ):
        other = tmp_path / "unrelated"
        other.mkdir()
        (other / ".env").write_text("S2_API_KEY=wrong-directory\n")
        monkeypatch.chdir(other)
        if case == "missing-key":
            (tmp_path / ".env").write_text("RESOLVER_TEST_EXTRA=loaded\n")
        elif case in {"disabled", "installed"}:
            (tmp_path / ".env").write_text("S2_API_KEY=file-key\n")
        if case == "disabled":
            monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "true")
        if case == "installed":
            monkeypatch.setattr(wrapper, "_PROJECT_ROOT", None)
        with patch.object(wrapper.requests, "get", return_value=_ok_response({"data": []})) as get:
            out = wrapper.run_skill(None, mode="search", query="demo")
        assert out["status"] == "ok"
        assert "x-api-key" not in get.call_args.kwargs["headers"]
        assert "S2_API_KEY" not in os.environ

    @pytest.mark.parametrize("failure", ["unreadable", "encoding"])
    def test_broken_dotenv_refuses_http_without_exposing_contents(self, tmp_path, failure, caplog):
        path = tmp_path / ".env"
        path.write_bytes(b"S2_API_KEY=synthetic-sensitive-marker\xff")
        # Permission bits cannot simulate EACCES reliably when CI runs as root.
        real_open = open

        def open_file(file, *args, **kwargs):
            if file == path and failure == "unreadable":
                raise PermissionError("synthetic-sensitive-marker")
            return real_open(file, *args, **kwargs)

        with (
            patch("builtins.open", side_effect=open_file),
            patch.object(wrapper.requests, "get") as get,
        ):
            out = wrapper.run_skill(None, mode="search", query="demo")
        assert out["status"] == "error"
        assert "S2 configuration error: could not read checkout .env" in out["message"]
        assert "synthetic-sensitive-marker" not in str(out) + caplog.text
        get.assert_not_called()

    def test_local_invalid_and_cached_calls_do_not_initialize_credentials(self, tmp_path):
        (tmp_path / "paper.md").write_text("Local paper")
        with patch.object(wrapper, "load_dotenv", side_effect=AssertionError("unexpected loading")):
            assert wrapper.run_skill(None, mode="search", query="")["status"] == "error"
            local = wrapper.run_skill(
                None, mode="resolve", source_type="local", identifier="paper.md"
            )
            assert local["status"] == "ok"
        with patch.object(wrapper.requests, "get", return_value=_ok_response({"data": []})):
            assert wrapper.run_skill(None, mode="search", query="cached")["status"] == "ok"
        with (
            patch.object(wrapper, "load_dotenv", side_effect=AssertionError("unexpected loading")),
            patch.object(wrapper.requests, "get", side_effect=AssertionError("unexpected HTTP")),
        ):
            assert wrapper.run_skill(None, mode="search", query="cached")["status"] == "ok"

    def test_fresh_interpreter_needs_no_bridge_or_llm_credentials(self, tmp_path):
        (tmp_path / ".env").write_text("S2_API_KEY=cold-process-key\n")
        script = dedent("""
            import os
            import sys
            from pathlib import Path
            from unittest.mock import Mock, patch
            from agent.skills.paper_resolver_skill import wrapper

            assert 'agent.llm_bridge' not in sys.modules
            assert 'S2_API_KEY' not in os.environ
            wrapper._PROJECT_ROOT = Path(sys.argv[1])
            response = Mock(status_code=200)
            response.json.return_value = {'data': []}
            with patch('dotenv.main.find_dotenv', side_effect=AssertionError('implicit lookup')), \
                 patch('socket.socket.connect', side_effect=AssertionError('live network')), \
                 patch.object(wrapper.requests, 'get', return_value=response) as get:
                out = wrapper.run_skill(None, mode='search', query='demo')
            assert out['status'] == 'ok'
            assert get.call_args.kwargs['headers']['x-api-key'] == 'cold-process-key'
            assert 'agent.llm_bridge' not in sys.modules
            print('standalone request verified')
        """)
        result = subprocess.run(
            [sys.executable, "-I", "-c", script, str(tmp_path)],
            cwd=tmp_path,
            env={},
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "standalone request verified"


# ---------------------------------------------------------------------------
# Rate limiting (1 req/s throttle + 429/5xx retry)
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_four_shared_key_slots_are_spaced_across_hosts(self, monkeypatch):
        monkeypatch.setenv("S2_SHARED_KEY_WORKERS", "4")
        scheduled = []
        for slot in range(4):
            monkeypatch.setenv("S2_SHARED_KEY_SLOT", str(slot))
            assert wrapper._shared_key_slot() == (4, slot)
            scheduled.append(100.0 + wrapper._shared_slot_wait_seconds(100.0, workers=4, slot=slot))
        assert sorted(scheduled) == [100.5, 102.0, 103.5, 105.0]

    def test_shared_key_slot_config_must_be_complete(self, monkeypatch):
        monkeypatch.setenv("S2_SHARED_KEY_WORKERS", "4")
        monkeypatch.delenv("S2_SHARED_KEY_SLOT", raising=False)
        with patch.object(wrapper.requests, "get") as mock_get:
            data, error = wrapper._s2_get("https://example.invalid")
        assert data is None
        assert "rate-limit configuration error" in error
        mock_get.assert_not_called()

    def test_shared_slot_paces_one_worker_without_cross_host_lock(self, monkeypatch):
        monkeypatch.setenv("S2_SHARED_KEY_WORKERS", "4")
        monkeypatch.setenv("S2_SHARED_KEY_SLOT", "3")
        wrapper._LAST_S2_REQUEST_TS = 0.0
        with (
            patch.object(wrapper.time, "time", return_value=100.0),
            patch.object(wrapper.time, "sleep") as mock_sleep,
        ):
            wrapper._throttle_s2()
        mock_sleep.assert_called_once_with(0.5)

    def test_throttle_sleeps_when_called_too_soon(self):
        # A prior request "just happened" → throttle must sleep the remainder.
        wrapper._LAST_S2_REQUEST_TS = wrapper.time.monotonic()
        with patch.object(wrapper.time, "sleep") as mock_sleep:
            wrapper._throttle_s2()
        assert mock_sleep.called
        (slept,) = mock_sleep.call_args.args
        assert 0 < slept <= wrapper.S2_MIN_REQUEST_INTERVAL_S

    def test_throttle_no_sleep_when_enough_time_elapsed(self):
        # Last request was long ago → no wait needed.
        wrapper._LAST_S2_REQUEST_TS = wrapper.time.monotonic() - 100.0
        with patch.object(wrapper.time, "sleep") as mock_sleep:
            wrapper._throttle_s2()
        mock_sleep.assert_not_called()

    @patch.object(wrapper.requests, "get")
    def test_429_then_success_is_retried(self, mock_get):
        mock_get.side_effect = [
            _http_status_response(429, "slow down"),
            _ok_response(_paper_metadata_only()),
        ]
        out = wrapper.run_skill(
            None,
            mode="resolve",
            source_type="doi",
            identifier="10.9999/zz",
            verbosity=0,
        )
        assert out["status"] == "ok"
        assert mock_get.call_count == 2

    @patch.object(wrapper.requests, "get")
    def test_429_exhausts_retries_then_errors(self, mock_get):
        mock_get.return_value = _http_status_response(429, "rate limited")
        with (
            patch.object(wrapper, "_throttle_s2"),
            patch.object(wrapper.time, "sleep") as mock_sleep,
        ):
            out = wrapper.run_skill(
                None,
                mode="resolve",
                source_type="doi",
                identifier="10.9999/zz",
                verbosity=0,
            )
        assert out["status"] == "error"
        assert "HTTP 429" in out["message"]
        assert mock_get.call_count == wrapper.S2_MAX_RETRIES + 1
        assert [call.args[0] for call in mock_sleep.call_args_list] == [
            1.0,
            2.0,
            4.0,
            8.0,
            16.0,
            32.0,
        ]

    @patch.object(wrapper.requests, "get")
    def test_retry_after_header_is_honoured(self, mock_get):
        resp_429 = _http_status_response(429, "slow down")
        resp_429.headers = {"Retry-After": "2"}
        mock_get.side_effect = [resp_429, _ok_response(_paper_metadata_only())]
        with patch.object(wrapper.time, "sleep") as mock_sleep:
            out = wrapper.run_skill(
                None,
                mode="resolve",
                source_type="doi",
                identifier="10.9999/zz",
                verbosity=0,
            )
        assert out["status"] == "ok"
        # Backoff used the Retry-After value (2s), not the exp-backoff default.
        assert any(call.args and call.args[0] == 2.0 for call in mock_sleep.call_args_list)

    @pytest.mark.parametrize("header", ["-1", "nan", "infinity", "not-a-delay"])
    def test_invalid_retry_after_uses_exponential_delay(self, header):
        response = _http_status_response(429, "slow down")
        response.headers = {"Retry-After": header}
        assert wrapper._retry_after_seconds(response) is None


# ---------------------------------------------------------------------------
# URL encoding — openreview '?id=' must reach S2, not be stripped as a query
# ---------------------------------------------------------------------------


class TestUrlEncoding:
    def test_openreview_query_string_is_encoded(self):
        lookup = wrapper._s2_lookup_id("openreview", "https://openreview.net/forum?id=ABC123")
        assert "?" not in lookup  # the '?' must be percent-encoded
        assert "%3Fid%3DABC123" in lookup  # the query survives, encoded
        assert lookup.startswith("URL:https://openreview.net/forum")

    def test_arxiv_and_doi_ids_unchanged_on_the_wire(self):
        # arXiv/DOI ids have no '?'; encoding must leave them byte-identical.
        assert wrapper._s2_lookup_id("arxiv", "2406.04378") == "ARXIV:2406.04378"
        assert (
            wrapper._s2_lookup_id("doi", "10.48550/arXiv.2406.04378")
            == "DOI:10.48550/arXiv.2406.04378"
        )


# ---------------------------------------------------------------------------
# Empty PDF extraction is a failure, not a silent success
# ---------------------------------------------------------------------------


class TestEmptyExtraction:
    def test_empty_pdf_text_treated_as_failure(self):
        import pdfplumber

        page = MagicMock()
        page.extract_text.return_value = ""  # image-only page → no text
        fake_pdf = MagicMock()
        fake_pdf.pages = [page]
        fake_pdf.__enter__.return_value = fake_pdf
        fake_pdf.__exit__.return_value = False
        with patch.object(pdfplumber, "open", return_value=fake_pdf):
            text, err = wrapper._extract_pdf_text(b"%PDF-fake")
        assert text is None
        assert "no text" in err
