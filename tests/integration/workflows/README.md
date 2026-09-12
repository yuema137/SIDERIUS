# tests/integration/workflows

Workflow integration contains pseudo campaign chains and a small deterministic
positive path. Dual-mode modules default to recording doubles; real LLM or
training routes require `--real-llm`/`--real-training` (deprecated
`--real-api-call` enables both).

## Focused route

`.venv/bin/python -m pytest tests/integration/workflows/test_arxiv_p1_generated_library_pseudo.py -q`

Owner: `src/workflows/` and launch adapters. Inspect module markers before
running; see the [integration map](../README.md).
