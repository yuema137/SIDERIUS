# tests/unit/guardrails

Guardrail tests statically reject hardcoded device/model routing, stale
authority, path, and contract patterns. They catch repository-level defects
that ordinary behavior tests cannot see.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/guardrails/test_c12p_b11_segmentation_default_census.py -q`

Owner: production-source scans under `src/` and configuration contracts; tests
are deterministic and side-effect free.
