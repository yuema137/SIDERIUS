# Candidate-worker tests

These tests exercise candidate execution, validation, and research-loop lifecycle
behavior with synthetic tasks and offline providers. Native CPU validation stays
real; no API keys or GPU runs are needed.

With this checkout's development environment installed, run from the repository
root:

```bash
.venv/bin/python -m pytest tests/unit/tools/candidate_worker/ -q
```

Lifecycle tests keep operation and segment processes separate. Validation starts
in a fresh interpreter so it cannot inherit the parent's autograd state. The
usage test checks both sides of a pause/resume: a validator response in each
segment must appear in the root run's token ledger, alongside the other provider
responses.

A successful run preserves process boundaries, validation results, and accounting.
The original inherited-autograd failure is host-dependent; the usage witness also
checks process IDs and the child environment so CPU-only hosts can detect a
regression. See the [lifecycle testing contract](lifecycle-testing.md) for fixture
ownership, transported evidence, and limitations.
