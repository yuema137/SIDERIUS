# tests/unit/nodes

Node tests protect the one-public-boundary rule, proposal/scoring helpers, and
task-owned scoring routes with synthetic schemas and source inspection.

## Focused route

`.venv/bin/python -m pytest tests/unit/nodes/test_f2_round_boundary_health.py -q`

Owner: `src/nodes/`; no LLM, provider, or training path is opened.
`goldens/` retains score precision inputs and the tuner child map owns its
composed guardrail fixtures; neither is a standalone node entrypoint.
