# `paper_resolver_skill` agent contract

## Boundary

This skill resolves one known paper or searches Semantic Scholar. It is an
effectful network/filesystem adapter, not a literature-opinion generator. It
accepts `sandbox` for the universal skill interface but does not use it.

## Invocation

```python
run_skill(sandbox, **kwargs) -> dict[str, Any]
```

`mode` is required and must be `resolve` or `search`.

Resolve mode requires `source_type` (`arxiv`, `doi`, `openreview`, or `local`)
and `identifier`; `verbosity` defaults to 1 and must be 0, 1, or 2. Zero is
metadata-only, one retrieves full text when available, and two also retains
the full extracted text. Local identifiers are bounded to the current
checkout.

Search mode requires a non-empty `query`. `limit` defaults to 10 and is capped
to 1–50; `offset` defaults to 0. Optional filters are `year`,
`fields_of_study`, `publication_types`, and `min_citation_count`.

## Output and effects

Normal paths return `{"status": "ok"|"partial"|"error", "data": ..., "message": str}`.
Resolve data reports source/identifier, S2 metadata where applicable,
`verbosity_achieved`, `full_text`, and `extraction_method` (`arxiv_source`,
`pdfplumber_llm`, or `abstract_only`). Search data reports query, mapped
results, total, offset, and next page information. Missing or semantically
invalid values that reach the mode handlers, plus network, PDF, and extraction
failures, become an error or partial envelope. Direct Python callers whose
`verbosity`, `limit`, or `offset` values are not integer-coercible, or whose
cache-key inputs are unhashable, receive an error envelope before any network
request is attempted.

Remote calls may use Semantic Scholar, arXiv, or an open-access PDF URL.
Full-text extraction tries arXiv source first and pdfplumber fallback where
applicable. Local resolution reads an allowed checkout-relative path. A
process-local request cache and throttle are module-level and not thread-safe.
The HTTP wrapper retries 429/5xx up to six times after the first request,
using `Retry-After` when supplied and otherwise capped exponential backoff.
For workers sharing one `S2_API_KEY` across hosts, set both
`S2_SHARED_KEY_WORKERS` and each worker's distinct zero-based
`S2_SHARED_KEY_SLOT`. The wrapper schedules those workers in separate UTC
slots 1.5 seconds apart. All hosts must have synchronized clocks and every
user of that key must be included in the worker count; otherwise 429 retries
remain the fallback, not a global rate guarantee. Invalid or partial slot
configuration returns an error envelope before an HTTP request.

## Callers and evidence

The literature-review node consumes resolve/search context. Offline tests in
`tests/unit/agent/skills/test_paper_resolver_skill.py` and
`test_arxiv_source.py` cover validation, routing, local safety, mocked network,
and extraction fallback. Live retrieval is isolated in
`tests/integration/skills/test_paper_resolver_skill.py`.
