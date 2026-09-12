# tests/integration

Cross-boundary integration coverage is grouped by API, protocol, node, runner,
scoring, skill, and workflow seams; inspect markers before opting into effects.

## Child routes

- [dashboard](dashboard/README.md) — FastAPI TestClient API checks.
- [execute_tools](execute_tools/README.md), [nodes](nodes/README.md), and
  [protocols](protocols/README.md) — typed cross-boundary seams.
- [prompt_templates](prompt_templates/README.md), [runner](runner/README.md),
  and [scoring](scoring/README.md) — rendering, launch bookkeeping, and
  historical scoring compatibility.
- [skills](skills/README.md) and [workflows](workflows/README.md) — effectful
  or pseudo campaign paths; inspect their markers before running.
- `agent/` and `health_checks/` contain only `__init__.py` placeholders today;
  they have no standalone integration implementation.

Dashboard `test_api.py` uses FastAPI TestClient with synthetic local JSON and
does not need a server. Other dual-mode families default to recording doubles;
real provider or training paths require `--real-llm`/`--real-training` (the
deprecated `--real-api-call` enables both). Collection alone is not a live-run
claim. See the [tests map](../README.md).
