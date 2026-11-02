# tests/unit/tools

Tool tests protect contributor-gate wording, Markdown link resolution, token
baseline reporting, and documentation census rules. They inspect local files;
no CI service is contacted.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/tools/test_contributor_gate_makefile.py -q`

Owner: `src/tools/` and repository documentation contracts.

## Candidate worker receipt causality

The [causality tests](candidate_worker/test_parallel_causality.py) check that a
parallel step cannot start before its inputs or route decision are ready. The
default lane runs 24 real dispatcher traces representing all 23 observed
failure/drain classes listed in the coverage contract, plus four forged-trace regressions:

```bash
.venv/bin/python -m pytest tests/unit/tools/candidate_worker/test_parallel_causality.py -q
```

For the expanded 288-trace timing and capacity matrix, opt in explicitly:

```bash
SIDERIUS_FULL_PARALLEL_CAUSALITY=1 .venv/bin/python -m pytest tests/unit/tools/candidate_worker/test_parallel_causality.py -q
```

Expect 28 tests by default or 292 with the opt-in. Both routes use offline native
fixtures; neither calls providers or launches GPU training. Supply `--basetemp`
on your configured scratch volume when needed. The full matrix takes several
minutes and is excluded from the default CI lane. The
[coverage contract](candidate_worker/parallel-causality-testing.md) explains the
23 failure/drain classes, their representatives, and the skipped-route mutation
witness.
