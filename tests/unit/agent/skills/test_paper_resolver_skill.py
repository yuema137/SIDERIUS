"""
Unit tests for ``agent/skills/paper_resolver_skill/wrapper.py``.

All network and PDF-extraction calls are mocked. No live S2, no real
``pdfplumber``. The live pilot is captured separately in
``docs/paper_resolver_pilot.md`` (see Commit 2 of
docs/commit_plan_ml_literature_review.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent.skills.paper_resolver_skill import wrapper

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_skill_state(monkeypatch):
    """Reset per-process skill state before each test.

    Clears the S2 cache, resets the throttle clock, and neutralises
    ``time.sleep`` so pacing/backoff never slows the suite. Tests that assert
    on pacing patch ``time.sleep`` themselves inside the test body.
    """
    wrapper._S2_CACHE.clear()
    wrapper._LAST_S2_REQUEST_TS = 0.0
    monkeypatch.setattr(wrapper.time, "sleep", lambda *_a, **_k: None)
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


# ---------------------------------------------------------------------------
# Resolve / arxiv — happy paths
# ---------------------------------------------------------------------------


class TestResolveArxiv:
    @patch.object(wrapper, "_extract_pdf_text", return_value=("EXTRACTED BODY", None))
    @patch.object(wrapper.requests, "get")
    def test_arxiv_openaccess_pdf_path(self, mock_get, mock_extract):
        # First call: S2 metadata (has openAccessPdf).
        # Second call: PDF download.
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="2406.04378", verbosity=1,
        )
        assert out["status"] == "ok"
        assert "openAccessPdf" in out["message"]
        assert out["data"]["full_text"] == "EXTRACTED BODY"
        assert out["data"]["verbosity_achieved"] == 1
        # Confirm we hit the openAccessPdf URL, not the arxiv fallback.
        pdf_url = mock_get.call_args_list[1].args[0]
        assert pdf_url == "https://example.org/paper.pdf"

    @patch.object(wrapper, "_extract_pdf_text", return_value=("FALLBACK BODY", None))
    @patch.object(wrapper.requests, "get")
    def test_arxiv_fallback_when_no_oap(self, mock_get, mock_extract):
        mock_get.side_effect = [
            _ok_response(_paper_without_oap_with_arxiv()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="2101.00001", verbosity=1,
        )
        assert out["status"] == "ok"
        assert "arxiv_fallback" in out["message"]
        pdf_url = mock_get.call_args_list[1].args[0]
        assert pdf_url == "https://arxiv.org/pdf/2101.00001.pdf"
        assert out["data"]["full_text"] == "FALLBACK BODY"

    @patch.object(wrapper.requests, "get")
    def test_arxiv_no_pdf_available(self, mock_get):
        # S2 returns metadata but no openAccessPdf and no ArXiv external id.
        mock_get.return_value = _ok_response(_paper_metadata_only())
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="some-id", verbosity=1,
        )
        assert out["status"] == "partial"
        assert out["data"]["verbosity_achieved"] == 0
        assert out["data"]["s2_metadata"] is not None
        assert out["data"]["full_text"] is None
        # Exactly one HTTP call — only the metadata lookup happened.
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_verbosity_0_skips_pdf(self, mock_get):
        mock_get.return_value = _ok_response(_paper_with_oap())
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="2406.04378", verbosity=0,
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
            None, mode="resolve", source_type="doi",
            identifier="10.9999/zz", verbosity=0,
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
            None, mode="resolve", source_type="openreview",
            identifier="https://openreview.net/forum?id=abc",
            verbosity=2,
        )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] == "OR BODY"
        assert out["data"]["verbosity_achieved"] == 2
        called_url = mock_get.call_args_list[0].args[0]
        assert "URL:" in called_url


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
            None, mode="resolve", source_type="local",
            identifier="notes/paper.md", verbosity=1,
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
                None, mode="resolve", source_type="local",
                identifier="papers/foo.pdf", verbosity=2,
            )
        assert out["status"] == "ok"
        assert out["data"]["full_text"] == "PDF BODY"
        mock_extract.assert_called_once()

    def test_local_absolute_path_rejected(self):
        out = wrapper.run_skill(
            None, mode="resolve", source_type="local",
            identifier="/etc/passwd", verbosity=0,
        )
        assert out["status"] == "error"
        assert "absolute" in out["message"]

    def test_local_parent_traversal_rejected(self):
        out = wrapper.run_skill(
            None, mode="resolve", source_type="local",
            identifier="papers/../../../etc/passwd", verbosity=0,
        )
        assert out["status"] == "error"
        assert ".." in out["message"]

    def test_local_unsupported_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(wrapper, "_PROJECT_ROOT", tmp_path)
        (tmp_path / "weird.docx").write_text("nope")
        out = wrapper.run_skill(
            None, mode="resolve", source_type="local",
            identifier="weird.docx", verbosity=1,
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
            None, mode="search",
            query="squid denoising", limit=10, verbosity=0,
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
        mock_get.return_value = _ok_response(
            {"total": 0, "offset": 0, "next": None, "data": []}
        )
        out = wrapper.run_skill(
            None, mode="search", query="zzz no matches", limit=5,
        )
        assert out["status"] == "ok"
        assert out["data"]["results"] == []
        assert out["data"]["total"] == 0

    @patch.object(wrapper.requests, "get")
    def test_search_filter_passthrough(self, mock_get):
        mock_get.return_value = _ok_response(
            {"total": 0, "offset": 0, "data": []}
        )
        wrapper.run_skill(
            None, mode="search",
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
        mock_get.return_value = _ok_response(
            {"total": 0, "offset": 0, "data": []}
        )
        wrapper.run_skill(
            None, mode="search", query="x", limit=10_000,
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
            None, mode="resolve", source_type="doi",
            identifier="10.9999/zz", verbosity=0,
        )
        out2 = wrapper.run_skill(
            None, mode="resolve", source_type="doi",
            identifier="10.9999/zz", verbosity=0,
        )
        assert out1 == out2
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_search_cache_hit_skips_network(self, mock_get):
        mock_get.return_value = _ok_response(
            {"total": 0, "offset": 0, "data": []}
        )
        wrapper.run_skill(None, mode="search", query="x", limit=3)
        wrapper.run_skill(None, mode="search", query="x", limit=3)
        assert mock_get.call_count == 1

    @patch.object(wrapper.requests, "get")
    def test_s2_network_error_returns_envelope(self, mock_get):
        mock_get.side_effect = requests.ConnectionError("boom")
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="2406.04378", verbosity=1,
        )
        assert out["status"] == "error"
        assert "S2 request failed" in out["message"]

    @patch.object(wrapper.requests, "get")
    def test_s2_non_retryable_http_error_returns_envelope(self, mock_get):
        # 404 is terminal — no retry, immediate error envelope, single call.
        mock_get.return_value = _http_status_response(404, "not found")
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="x", verbosity=0,
        )
        assert out["status"] == "error"
        assert "HTTP 404" in out["message"]
        assert mock_get.call_count == 1

    @patch.object(wrapper, "_extract_pdf_text", return_value=(None, "pdfplumber blew up"))
    @patch.object(wrapper.requests, "get")
    def test_pdf_extraction_failure_returns_partial(self, mock_get, mock_extract):
        mock_get.side_effect = [
            _ok_response(_paper_with_oap()),
            _ok_response({"_": "_"}),
        ]
        out = wrapper.run_skill(
            None, mode="resolve", source_type="arxiv",
            identifier="2406.04378", verbosity=1,
        )
        assert out["status"] == "partial"
        assert "extraction failed" in out["message"]
        assert out["data"]["s2_metadata"] is not None
        assert out["data"]["full_text"] is None


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


# ---------------------------------------------------------------------------
# Rate limiting (1 req/s throttle + 429/5xx retry)
# ---------------------------------------------------------------------------


class TestRateLimiting:
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
            None, mode="resolve", source_type="doi",
            identifier="10.9999/zz", verbosity=0,
        )
        assert out["status"] == "ok"
        assert mock_get.call_count == 2

    @patch.object(wrapper.requests, "get")
    def test_429_exhausts_retries_then_errors(self, mock_get):
        mock_get.return_value = _http_status_response(429, "rate limited")
        out = wrapper.run_skill(
            None, mode="resolve", source_type="doi",
            identifier="10.9999/zz", verbosity=0,
        )
        assert out["status"] == "error"
        assert "HTTP 429" in out["message"]
        assert mock_get.call_count == wrapper.S2_MAX_RETRIES + 1

    @patch.object(wrapper.requests, "get")
    def test_retry_after_header_is_honoured(self, mock_get):
        resp_429 = _http_status_response(429, "slow down")
        resp_429.headers = {"Retry-After": "2"}
        mock_get.side_effect = [resp_429, _ok_response(_paper_metadata_only())]
        with patch.object(wrapper.time, "sleep") as mock_sleep:
            out = wrapper.run_skill(
                None, mode="resolve", source_type="doi",
                identifier="10.9999/zz", verbosity=0,
            )
        assert out["status"] == "ok"
        # Backoff used the Retry-After value (2s), not the exp-backoff default.
        assert any(
            call.args and call.args[0] == 2.0
            for call in mock_sleep.call_args_list
        )


# ---------------------------------------------------------------------------
# URL encoding — openreview '?id=' must reach S2, not be stripped as a query
# ---------------------------------------------------------------------------


class TestUrlEncoding:
    def test_openreview_query_string_is_encoded(self):
        lookup = wrapper._s2_lookup_id(
            "openreview", "https://openreview.net/forum?id=ABC123"
        )
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
