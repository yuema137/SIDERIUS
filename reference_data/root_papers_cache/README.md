# `reference_data/root_papers_cache/`

Persistent on-disk cache for the `ml_literature_review` node's root-paper
extracts.

## What lives here

One JSON file per resolved root paper, named after the paper's sanitized
identifier. Each file is a serialized `RetrievedPaper`
(`agent/schemas/literature_review.py`) — the audit-trail unit the node
emits whenever it resolves a paper at verbosity ≥ 0.

**Filename convention**: `{sanitized_paper_id}.json` where
`sanitized_paper_id` is `_sanitize_paper_id(paper_id)` (see
`nodes/ml_literature_review/ml_literature_review.py:95-101`). The
sanitizer replaces every character outside `[A-Za-z0-9._-]` with `_` so
the filesystem can safely hold `:` / `/` from raw paper IDs.

**Examples**:

| Raw `paper_id` | Cache filename |
|---|---|
| `arxiv:2406.04378` | `arxiv_2406.04378.json` |
| `doi:10.1103/PhysRevD.XX` | `doi_10.1103_PhysRevD.XX.json` |
| `local:reference_data/papers/foo.pdf` | `local_reference_data_papers_foo.pdf.json` |

## Cache behaviour

The node reads this directory in `_resolve_root_paper`
(`nodes/ml_literature_review/ml_literature_review.py:315-342`):

1. Compute the cache path from `paper_id`.
2. If the file exists → load + validate as `RetrievedPaper` → return.
3. On cache miss → call `paper_resolver_skill` → compress (if
   verbosity ≥ 1) → write the result back under the same cache path.

The cache key is the `paper_id`, NOT the requested verbosity. A cached
paper at verbosity=0 will be returned for any subsequent v=0/1/2
request — the node trusts the cached `verbosity_achieved`. **To force
a re-fetch + re-compression, delete the cache file manually**:

```bash
rm reference_data/root_papers_cache/arxiv_2406.04378.json
```

The next run will repopulate the entry from S2 + the configured
extraction tier. There is **no automatic cache invalidation** — prompt
revisions, schema changes, etc. require manual cleanup.

## What's tracked in git

- This **README only**.
- The cache files themselves (`*.json`) are gitignored — production
  runs populate them on first invocation; subsequent runs hit the
  cache. Committing them would bloat the repo with content that
  ultimately depends on the upstream LLM's compression output.
  (Risk 5 resolution, P-design 2026-06-09; revisit if reproducibility
  issues from S2 variability become a problem.)

## Bit-for-bit reproducibility (optional)

Operators wanting reproducible cache contents (e.g. for the §10 FULL
validation suite) can copy the Phase-1 pilot cache files from the
sibling `reference_data/lit_review_pilot_cache/` directory:

```bash
cp reference_data/lit_review_pilot_cache/arxiv_*.json \
   reference_data/root_papers_cache/
```

`lit_review_pilot_cache/` is also gitignored but populated by the
`tests/integration/nodes/test_ml_literature_review_phase1_pilot.py`
flow. It's the canonical source of cached §10-corpus extracts.

## Default contract with the lit-review node

The node's `DEFAULT_ROOT_CACHE_DIR` constant
(`nodes/ml_literature_review/ml_literature_review.py:62`) points here
by default. `MLLiteratureReviewAgent.__init__(root_cache_dir=...)`
accepts an override (tests pass a `tmp_path`); production wiring uses
the default.

## Related

- `nodes/ml_literature_review/ml_literature_review.py` — the consumer.
- `agent/schemas/literature_review.py` — `RetrievedPaper` schema.
- `docs/commit_plan_ml_literature_review.md` — Commit 6 design (Risk 5).
- `docs/external_agents_for_proposer.md` §4 — verbosity tiers + cache rule.
