# tests/integration/workflows

Workflow integration contains pseudo campaign chains and small deterministic
positive paths. Real scientific workflows and hardware qualification belong to
external consumers, not to task- or machine-specific branches hidden here.

## Focused route

`.venv/bin/python -m pytest tests/integration/workflows/test_arxiv_p1_generated_library_pseudo.py -q`

The generic two-iteration physical-rejection feedback path has its own compact
offline witness:

```bash
.venv/bin/python -m pytest \
  tests/integration/workflows/test_vram_awareness.py -q
```

Owner: `src/workflows/` and launch adapters. See the
[integration map](../README.md).
