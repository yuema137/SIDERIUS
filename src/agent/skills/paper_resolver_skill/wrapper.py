# agent/skills/paper_resolver_skill/wrapper.py
"""
Paper-resolver skill — single skill with two modes ('resolve', 'search').

Modes share all post-processing (per-paper field mapping, openAccessPdf
extraction, PDF download/text extraction, auth/rate-limit plumbing). Only
the URL and the envelope shape differ — resolve hits ``/paper/{id}`` and
returns a single paper object; search hits ``/paper/search`` and returns an
envelope ``{"total","offset","next","data":[...]}`` whose ``data`` items
are a strict subset of the resolve-mode paper shape (verified against
api.semanticscholar.org's OpenAPI spec, May 2026).

Universal exit contract: every code path returns

    {"status": "ok" | "partial" | "error", "data": <payload>, "message": <str>}

Never raises. ``partial`` covers e.g. S2 metadata fetched but the PDF
download failed — the caller still gets useful information.

Direct callers whose scalar inputs cannot be coerced for cache identity, or
whose cache-key values are unhashable, receive the same error envelope before
any network request is attempted.

Cache (module-level ``_S2_CACHE``) is **per-process, per-run, not
thread-safe**. Keyed by the full request shape so repeated calls within
one lit-review run skip the network. Cleared by re-import only.
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any
from urllib.parse import quote

import requests

from agent.skills.paper_resolver_skill.arxiv_source import parse_arxiv_source
from core.layout import checkout_root

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
S2_DEFAULT_FIELDS = "title,authors,year,abstract,openAccessPdf,externalIds"
S2_DEFAULT_TIMEOUT_S = 30
S2_SEARCH_LIMIT_CAP = 50

# Rate-limit controls for the Semantic Scholar API (1 req/s ceiling).
S2_MIN_REQUEST_INTERVAL_S = 1.1  # slight margin over 1.0s for clock skew
S2_MAX_RETRIES = 6  # retry attempts beyond the first
S2_RETRY_BACKOFF_BASE_S = 1.0  # exp-backoff base when no Retry-After header
S2_SHARED_SLOT_INTERVAL_S = 1.5  # 1 RPS key limit plus clock/scheduling margin

# Repo root, resolved relative to this file. ``local`` source paths are
# resolved against this; absolute paths and ``..`` segments are rejected
# both here (defence-in-depth) and at the ``PaperSource`` schema layer.
_PROJECT_ROOT = checkout_root()

# Per-process cache. Key shape:
#   resolve: ("resolve", source_type, identifier, verbosity)
#   search : ("search", query, limit, offset, frozenset(filters.items()))
# Value: the full envelope dict that will be returned.
_S2_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}

# time.monotonic() of the last S2 request *sent*. Drives _throttle_s2's
# pacing. Module-level, per-process, not thread-safe — same contract as
# _S2_CACHE above.
_LAST_S2_REQUEST_TS: float = 0.0


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _s2_headers() -> dict[str, str]:
    """Return request headers, including the S2 API key when set."""
    headers = {"User-Agent": "siderius-paper-resolver/1.0"}
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _throttle_s2() -> None:
    """Block until >= S2_MIN_REQUEST_INTERVAL_S has elapsed since the last S2
    request, then record this request's send time.

    Proactive pacing keeps the request rate under Semantic Scholar's 1 req/s
    ceiling. Only the *remaining* fraction of the interval is slept, so a
    caller that already spent time between calls (e.g. an LLM decision step in
    the dynamic-search loop) waits zero. Module-level and **not thread-safe**
    — same contract as ``_S2_CACHE``.
    """
    global _LAST_S2_REQUEST_TS
    elapsed = time.monotonic() - _LAST_S2_REQUEST_TS
    wait = S2_MIN_REQUEST_INTERVAL_S - elapsed
    if wait > 0:
        time.sleep(wait)
    shared_slot = _shared_key_slot()
    if shared_slot is not None:
        workers, slot = shared_slot
        wait = _shared_slot_wait_seconds(time.time(), workers=workers, slot=slot)
        if wait > 0:
            time.sleep(wait)
    _LAST_S2_REQUEST_TS = time.monotonic()


def _shared_key_slot() -> tuple[int, int] | None:
    """Read the optional common-key schedule shared by independent workers."""

    raw_workers = os.environ.get("S2_SHARED_KEY_WORKERS")
    raw_slot = os.environ.get("S2_SHARED_KEY_SLOT")
    if raw_workers is None and raw_slot is None:
        return None
    try:
        workers = int(raw_workers) if raw_workers is not None else 0
        slot = int(raw_slot) if raw_slot is not None else -1
    except ValueError as exc:
        raise ValueError("S2 shared-key workers and slot must be integers") from exc
    if workers < 2 or not 0 <= slot < workers:
        raise ValueError("S2 shared-key slot must be in [0, workers); workers must be >= 2")
    return workers, slot


def _shared_slot_wait_seconds(now: float, *, workers: int, slot: int) -> float:
    """Place one worker's requests in its own recurring UTC time slot."""

    cycle = workers * S2_SHARED_SLOT_INTERVAL_S
    phase = slot * S2_SHARED_SLOT_INTERVAL_S
    return (phase - now) % cycle


def _retry_after_seconds(resp: requests.Response) -> float | None:
    """Parse a ``Retry-After`` header expressed in integer seconds.

    Returns ``None`` when the header is absent or not a plain number; the
    HTTP-date form is not honoured (S2 sends the seconds form).
    """
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _s2_get(
    url: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: int = S2_DEFAULT_TIMEOUT_S,
) -> tuple[dict[str, Any] | None, str | None]:
    """GET a Semantic Scholar endpoint. Returns (json, error_message).

    Paces sends to <= 1/s via ``_throttle_s2`` and retries up to
    ``S2_MAX_RETRIES`` times on a 429 or 5xx, honouring ``Retry-After`` when
    present and falling back to exponential backoff otherwise. A raised
    ``requests`` exception is **not** retried — it surfaces immediately. On
    any terminal failure returns ``(None, str)``; callers map that onto the
    universal envelope.
    """
    last_err: str | None = None
    for attempt in range(S2_MAX_RETRIES + 1):
        try:
            _throttle_s2()
        except ValueError as exc:
            return None, f"S2 rate-limit configuration error: {exc}"
        try:
            resp = requests.get(
                url,
                params=params,
                headers=_s2_headers(),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return None, f"S2 request failed: {exc}"

        if resp.status_code == 200:
            try:
                return resp.json(), None
            except ValueError as exc:
                return None, f"S2 response was not JSON: {exc}"

        # Retryable: 429 (rate limited) or any 5xx (transient server error).
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            last_err = f"S2 returned HTTP {resp.status_code}: {resp.text[:200]}"
            if attempt < S2_MAX_RETRIES:
                retry_after = _retry_after_seconds(resp)
                backoff = (
                    retry_after
                    if retry_after is not None
                    else min(60.0, S2_RETRY_BACKOFF_BASE_S * (2**attempt))
                )
                time.sleep(backoff)
                continue
            return None, last_err

        # Non-retryable HTTP error (e.g. 404 not found).
        return None, f"S2 returned HTTP {resp.status_code}: {resp.text[:200]}"

    return None, last_err or "S2 request failed after retries"


# ---------------------------------------------------------------------------
# Shared per-paper mapping
# ---------------------------------------------------------------------------


def _paper_object_to_dict(obj: dict[str, Any]) -> dict[str, Any]:
    """Map an S2 paper object (from either /paper/{id} or /paper/search's
    ``data`` items) to the dict shape consumed by ``RetrievedPaper.s2_metadata``.

    The two endpoints' per-paper shapes overlap on every field we care about
    (verified against the S2 OpenAPI spec). This helper is the only place
    that knows the field projection — both modes call it.
    """
    return {
        "paperId": obj.get("paperId"),
        "title": obj.get("title"),
        "authors": obj.get("authors") or [],
        "year": obj.get("year"),
        "abstract": obj.get("abstract"),
        "openAccessPdf": obj.get("openAccessPdf"),
        "externalIds": obj.get("externalIds") or {},
    }


# ---------------------------------------------------------------------------
# PDF + local file handling
# ---------------------------------------------------------------------------


def _download_pdf(url: str, timeout: int = S2_DEFAULT_TIMEOUT_S) -> tuple[bytes | None, str | None]:
    """Stream a PDF to memory. Returns (bytes, error_message)."""
    try:
        resp = requests.get(url, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        return None, f"PDF download failed: {exc}"
    if resp.status_code != 200:
        return None, f"PDF download HTTP {resp.status_code}"
    try:
        return resp.content, None
    except requests.RequestException as exc:
        return None, f"PDF stream read failed: {exc}"


# ---------------------------------------------------------------------------
# Tier-1 arXiv source extraction
# ---------------------------------------------------------------------------

ARXIV_SRC_BASE_URL = "https://arxiv.org/src/"
ARXIV_TIER1_USER_AGENT = "siderius-lit-review/1.0 (mailto:y5ma@ucsd.edu)"


def _try_arxiv_tier1(arxiv_id: str, timeout: int = 60) -> str | None:
    """Try Tier-1 arXiv source extraction.

    Fetches ``arxiv.org/src/{arxiv_id}`` and parses the ``.tar.gz`` via
    ``arxiv_source.parse_arxiv_source``. Returns cleaned Markdown on success,
    ``None`` on any failure — PDF-only submission (content-type pdf), network
    error, HTTP non-200, corrupt tarball, LaTeX parse error, or empty body.
    Caller falls through to the next tier (Tier-3 pdfplumber on the PDF).
    """
    try:
        resp = requests.get(
            ARXIV_SRC_BASE_URL + arxiv_id,
            headers={"User-Agent": ARXIV_TIER1_USER_AGENT},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        logger.debug("Tier-1 arXiv-source network error for %s: %s", arxiv_id, exc)
        return None
    if resp.status_code != 200:
        logger.debug("Tier-1 arXiv-source HTTP %d for %s", resp.status_code, arxiv_id)
        return None
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype:
        # PDF-only submission (e.g. SNRAware) — cleanly cascade to Tier-3.
        logger.debug("Tier-1 arXiv-source: PDF-only submission for %s", arxiv_id)
        return None
    try:
        return parse_arxiv_source(resp.content)
    except Exception as exc:
        logger.debug("Tier-1 arXiv-source unexpected exception for %s: %s", arxiv_id, exc)
        return None


def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str | None, str | None]:
    """Extract text from PDF bytes via pdfplumber. Returns (text, error_message).

    pdfplumber is imported lazily so the rest of the skill stays usable
    (e.g. in unit tests that mock this function) even when pdfplumber is
    not yet installed in the active environment.
    """
    try:
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError as exc:
        return None, f"pdfplumber not installed: {exc}"
    try:
        import io

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        text = "\n\n".join(pages)
    except Exception as exc:
        # pdfplumber wraps a wide variety of low-level errors (pdfminer,
        # zlib, MemoryError on huge pages, ...). Returning a flat envelope
        # is the explicit contract — re-raising would break it.
        return None, f"PDF text extraction failed: {exc}"
    if not text.strip():
        # Image-only / scanned PDFs yield no extractable text. Treat empty
        # extraction as a failure so callers fall back to verbosity_achieved=0
        # instead of silently "succeeding" with an empty string.
        logger.warning("PDF extraction produced no text (likely an image-only/scanned PDF)")
        return None, "PDF extraction produced no text (likely image-only/scanned PDF)"
    return text, None


def _read_local_paper(identifier: str) -> tuple[str | None, str | None]:
    """Read a repo-relative local file. Returns (text, error_message).

    Defence-in-depth: rejects absolute paths and ``..`` segments even
    though ``PaperSource`` validates these at construction.
    """
    if identifier.startswith("/"):
        return None, f"local identifier must be repo-relative, got absolute: {identifier!r}"
    if ".." in identifier.split("/"):
        return None, f"local identifier may not contain '..': {identifier!r}"
    if _PROJECT_ROOT is None:
        return None, "local papers require the SIDERIUS source checkout"
    path = (_PROJECT_ROOT / identifier).resolve()
    try:
        path.relative_to(_PROJECT_ROOT)
    except ValueError:
        return None, f"local identifier escapes project root: {identifier!r}"
    if not path.exists():
        return None, f"local file not found: {identifier!r}"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            pdf_bytes = path.read_bytes()
        except OSError as exc:
            return None, f"failed to read local PDF: {exc}"
        return _extract_pdf_text(pdf_bytes)
    if suffix in {".txt", ".md"}:
        try:
            return path.read_text(encoding="utf-8", errors="replace"), None
        except OSError as exc:
            return None, f"failed to read local text: {exc}"
    return None, f"unsupported local file suffix: {suffix!r}"


# ---------------------------------------------------------------------------
# Resolve-mode
# ---------------------------------------------------------------------------


def _s2_lookup_id(source_type: str, identifier: str) -> str:
    """Build the percent-encoded path component for ``GET /paper/{id_form}``.

    The id is percent-encoded with ``:`` and ``/`` kept literal, so special
    characters — notably the ``?`` in OpenReview forum URLs — stay inside the
    path segment instead of being parsed as a query string by ``requests``.
    Without this, ``URL:https://openreview.net/forum?id=X`` is truncated at
    ``?`` before it reaches S2. arXiv / DOI ids contain no such characters, so
    their on-the-wire form is unchanged.
    """
    if source_type == "arxiv":
        raw = f"ARXIV:{identifier}"
    elif source_type == "doi":
        raw = f"DOI:{identifier}"
    elif source_type == "openreview":
        # S2 accepts URL: for arbitrary URLs; OpenReview links resolve this way.
        raw = f"URL:{identifier}"
    else:
        raise ValueError(f"_s2_lookup_id called with unsupported source_type: {source_type!r}")
    return quote(raw, safe=":/")


def _arxiv_fallback_url(external_ids: dict[str, Any]) -> str | None:
    """Build https://arxiv.org/pdf/{arxiv_id}.pdf when externalIds has ArXiv."""
    arxiv_id = external_ids.get("ArXiv") if external_ids else None
    if not arxiv_id:
        return None
    return f"https://arxiv.org/pdf/{arxiv_id}.pdf"


def _resolve_remote(source_type: str, identifier: str, verbosity: int) -> dict[str, Any]:
    """Resolve a remote-source paper (arxiv / doi / openreview)."""
    lookup_id = _s2_lookup_id(source_type, identifier)
    url = f"{S2_BASE_URL}/paper/{lookup_id}"
    s2_json, err = _s2_get(url, params={"fields": S2_DEFAULT_FIELDS})
    if s2_json is None:
        return {
            "status": "error",
            "data": {
                "source_type": source_type,
                "identifier": identifier,
                "s2_metadata": None,
                "verbosity_achieved": 0,
                "full_text": None,
                "extraction_method": "abstract_only",
            },
            "message": err or "S2 lookup returned no data",
        }

    metadata = _paper_object_to_dict(s2_json)
    payload: dict[str, Any] = {
        "source_type": source_type,
        "identifier": identifier,
        "s2_metadata": metadata,
        "verbosity_achieved": 0,
        "full_text": None,
        "extraction_method": "abstract_only",
    }

    # verbosity 0 → metadata only, done.
    if verbosity == 0:
        return {"status": "ok", "data": payload, "message": "metadata only"}

    # Tier 1 — arXiv source (.tex via arxiv.org/src). Only for arxiv source
    # type; for DOI / OpenReview we don't have an arxiv id to query.
    if source_type == "arxiv":
        tier1_text = _try_arxiv_tier1(identifier)
        if tier1_text:
            payload["full_text"] = tier1_text
            payload["verbosity_achieved"] = 2 if verbosity == 2 else 1
            payload["extraction_method"] = "arxiv_source"
            return {
                "status": "ok",
                "data": payload,
                "message": "extracted via arXiv source (Tier 1)",
            }
        # Tier 1 failed (PDF-only / network / parse) → fall through to Tier 2.

    # Tier 2 — openAccessPdf / arxiv-fallback PDF + pdfplumber. (A GPU-based
    # PDF→Markdown tier was considered for this slot — see §5a of
    # docs/external_agents_for_proposer.md — and dropped before 2c-c.)
    pdf_url = None
    if metadata.get("openAccessPdf"):
        oap = metadata["openAccessPdf"]
        pdf_url = oap.get("url") if isinstance(oap, dict) else None
    pdf_path_taken = "openAccessPdf" if pdf_url else None
    if not pdf_url:
        pdf_url = _arxiv_fallback_url(metadata.get("externalIds") or {})
        if pdf_url:
            pdf_path_taken = "arxiv_fallback"

    if not pdf_url:
        return {
            "status": "partial",
            "data": payload,
            "message": "no PDF URL available (neither openAccessPdf nor ArXiv fallback)",
        }

    pdf_bytes, pdf_err = _download_pdf(pdf_url)
    if pdf_bytes is None:
        return {
            "status": "partial",
            "data": payload,
            "message": f"PDF fetch failed via {pdf_path_taken}: {pdf_err}",
        }
    text, text_err = _extract_pdf_text(pdf_bytes)
    if text is None:
        return {
            "status": "partial",
            "data": payload,
            "message": f"PDF text extraction failed via {pdf_path_taken}: {text_err}",
        }
    payload["full_text"] = text
    payload["verbosity_achieved"] = 2 if verbosity == 2 else 1
    payload["extraction_method"] = "pdfplumber_llm"
    return {
        "status": "ok",
        "data": payload,
        "message": f"PDF resolved via {pdf_path_taken}",
    }


def _run_resolve_mode(source_type: str, identifier: str, verbosity: int) -> dict[str, Any]:
    """Top-level resolve-mode dispatch."""
    if source_type == "local":
        text, err = _read_local_paper(identifier)
        if text is None:
            return {
                "status": "error",
                "data": {
                    "source_type": "local",
                    "identifier": identifier,
                    "s2_metadata": None,
                    "verbosity_achieved": 0,
                    "full_text": None,
                    "extraction_method": "abstract_only",
                },
                "message": err or "local file read failed",
            }
        return {
            "status": "ok",
            "data": {
                "source_type": "local",
                "identifier": identifier,
                "s2_metadata": None,
                "verbosity_achieved": 2 if verbosity == 2 else 1,
                "full_text": text,
                # Local files are pre-extracted text — Tier-3-equivalent trust.
                "extraction_method": "pdfplumber_llm",
            },
            "message": "local file read",
        }
    if source_type in {"arxiv", "doi", "openreview"}:
        return _resolve_remote(source_type, identifier, verbosity)
    return {
        "status": "error",
        "data": None,
        "message": f"unsupported source_type: {source_type!r}",
    }


# ---------------------------------------------------------------------------
# Search-mode
# ---------------------------------------------------------------------------


def _run_search_mode(
    query: str,
    limit: int,
    offset: int,
    filters: dict[str, Any],
) -> dict[str, Any]:
    """Run an S2 keyword search and return mapped paper objects.

    Note: search-mode never fetches PDFs per result — that would be a
    fan-out cost trap. Callers escalate per-paper via a follow-up
    resolve-mode call.
    """
    capped_limit = min(max(1, limit), S2_SEARCH_LIMIT_CAP)
    params: dict[str, Any] = {
        "query": query,
        "limit": capped_limit,
        "offset": max(0, offset),
        "fields": S2_DEFAULT_FIELDS,
    }
    for key in ("year", "fields_of_study", "publication_types", "min_citation_count"):
        val = filters.get(key)
        if val is None:
            continue
        # S2 query-param names are camelCase variants of the skill's
        # snake_case params. Translate here so the skill surface stays
        # Pythonic.
        s2_key = {
            "year": "year",
            "fields_of_study": "fieldsOfStudy",
            "publication_types": "publicationTypes",
            "min_citation_count": "minCitationCount",
        }[key]
        params[s2_key] = val

    url = f"{S2_BASE_URL}/paper/search"
    s2_json, err = _s2_get(url, params=params)
    if s2_json is None:
        return {
            "status": "error",
            "data": {"query": query, "results": [], "total": 0, "offset": offset, "next": None},
            "message": err or "S2 search returned no data",
        }
    items = s2_json.get("data") or []
    mapped = [_paper_object_to_dict(item) for item in items]
    return {
        "status": "ok",
        "data": {
            "query": query,
            "results": mapped,
            "total": s2_json.get("total", len(mapped)),
            "offset": s2_json.get("offset", offset),
            "next": s2_json.get("next"),
        },
        "message": f"search returned {len(mapped)} result(s)",
    }


# ---------------------------------------------------------------------------
# Universal entry point
# ---------------------------------------------------------------------------


def _make_cache_key(kwargs: dict[str, Any]) -> tuple[Any, ...]:
    """Build the cache key for this call's request shape."""
    mode = kwargs.get("mode")
    if mode == "resolve":
        return (
            "resolve",
            kwargs.get("source_type"),
            kwargs.get("identifier"),
            int(kwargs.get("verbosity", 1)),
        )
    if mode == "search":
        filter_items = tuple(
            sorted(
                (k, kwargs.get(k))
                for k in ("year", "fields_of_study", "publication_types", "min_citation_count")
                if kwargs.get(k) is not None
            )
        )
        return (
            "search",
            kwargs.get("query"),
            int(kwargs.get("limit", 10)),
            int(kwargs.get("offset", 0)),
            filter_items,
        )
    return ("invalid_mode", mode)


def run_skill(sandbox: Any, **kwargs: Any) -> dict[str, Any]:
    """Universal entry point.

    ``sandbox`` is accepted and ignored (consistent with the universal
    skill convention — see Q3 of docs/commit_plan_ml_literature_review.md).
    All real arguments arrive via ``**kwargs``; their schema is documented
    in ``skill_config.json``.

    Never raises. Every exit returns the universal envelope shape.
    """
    del sandbox  # intentionally unused

    mode = kwargs.get("mode")
    if mode not in {"resolve", "search"}:
        return {
            "status": "error",
            "data": None,
            "message": f"mode must be 'resolve' or 'search', got {mode!r}",
        }

    try:
        cache_key = _make_cache_key(kwargs)
        cached = _S2_CACHE.get(cache_key)
    except (TypeError, ValueError) as exc:
        return {
            "status": "error",
            "data": None,
            "message": (
                "invalid paper resolver input: verbosity, limit, and offset "
                f"must be integer-coercible and cache-key inputs hashable ({exc})"
            ),
        }
    if cached is not None:
        return cached

    if mode == "resolve":
        source_type = kwargs.get("source_type")
        identifier = kwargs.get("identifier")
        verbosity = int(kwargs.get("verbosity", 1))
        if not source_type or not identifier:
            return {
                "status": "error",
                "data": None,
                "message": "resolve-mode requires 'source_type' and 'identifier'",
            }
        if verbosity not in {0, 1, 2}:
            return {
                "status": "error",
                "data": None,
                "message": f"verbosity must be 0, 1, or 2, got {verbosity!r}",
            }
        result = _run_resolve_mode(source_type, identifier, verbosity)
    else:  # mode == "search"
        query = kwargs.get("query")
        if not query:
            return {
                "status": "error",
                "data": None,
                "message": "search-mode requires non-empty 'query'",
            }
        limit = int(kwargs.get("limit", 10))
        offset = int(kwargs.get("offset", 0))
        filters = {
            "year": kwargs.get("year"),
            "fields_of_study": kwargs.get("fields_of_study"),
            "publication_types": kwargs.get("publication_types"),
            "min_citation_count": kwargs.get("min_citation_count"),
        }
        result = _run_search_mode(query, limit, offset, filters)

    _S2_CACHE[cache_key] = result
    return result
