# tests/unit/workflows

Workflow tests pin task configuration, lifecycle wiring, provenance, cache,
and launch/registration contracts. Synthetic fixtures expose stale or dropped
cross-layer fields without running a campaign.

## Focused route

`.venv/bin/python -m pytest tests/unit/workflows/test_arxiv_255_impl_content_fingerprint.py -q`

Owner: `src/workflows/`; focused routes are deterministic and side-effect free.
The nested `goldens/` files preserve pre-refactor launch defaults for parity
assertions; they are historical fixtures, not current workflow configuration.
