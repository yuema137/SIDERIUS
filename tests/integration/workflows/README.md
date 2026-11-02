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

It checks that the next proposal receives the recorded memory estimate in GiB,
the rejection details, and the hardware context. See the
[VRAM feedback fixture contract](vram-feedback-fixture-contract.md).

Owner: `src/workflows/` and launch adapters. See the
[integration map](../README.md).

To check vocabulary growth and promotion across iterations with supplied results:

```bash
.venv/bin/python -m pytest tests/integration/workflows/test_vocab_accumulation.py -q
```

The tests supply observed prediction references and explicitly bind a dataset
profile where prompt rendering needs it. See the
[vocabulary fixture contract](vocabulary-fixture-contract.md).

The tuner scope tests use symbolic rows so planning can count training samples
without loading data or running a model:

```bash
.venv/bin/python -m pytest tests/integration/workflows/test_data_scope_tuner_pseudo.py -q
```

See the [symbolic fixture contract](../../fixtures/tuner-composed-task-contract.md)
for sampling rules and the boundaries that prevent execution.
