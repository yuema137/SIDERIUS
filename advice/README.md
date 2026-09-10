# `advice/` — caller-owned human advice

Only this README is tracked here. There are no shipped `single_agent/`,
`workflow/` or `gate/` directories or advice JSON artifacts. Keep active advice
in the task/experiment repository or an explicit workspace selected by its
caller. Historical documents may cite retired advice paths; those citations
do not make the files available or select them for a new run.

## Chain entry and format

Pass an explicit JSON path with `--human_advice_file` or `--advice` to the
chain/iteration entrypoint. `--advice` takes precedence when both are supplied.
The source authority is
[`run_one_iteration.py::load_advice_artifact`](../sdsc_submission_scripts/run_one_iteration.py),
with `render_advice_value` shared by validation and argument normalization.
The five agent keys target interpretation, proposal, implementation, validation
and tuning; `mindset` supplies the proposer's preamble.

```json
{
  "propose": "Explain which existing evidence supports the proposed change.",
  "tune": ["Use the declared task objective.", "Record what each attempt tested."],
  "_meta": "An illustrative format, not a scientific treatment or Gate preset."
}
```

Sparse advice is valid: omitted keys mean no advice for those agents. Present
keys must carry readable text. The loader reads, hashes and parses the same
bytes; a supplied digest must match the observed digest.

## The key set is closed

`sdsc_submission_scripts/run_one_iteration.py::load_advice_artifact` refuses
an advice artifact that could not inject anything (F-SCHED-5). The recognised
top-level keys are exactly:

```
interpret · propose · implement · validate · tune · mindset
```

Each takes a string, or a list of lines that is joined with newlines. The
loader REFUSES, naming what was wrong:

| artifact | verdict |
|---|---|
| `{"propse": "..."}` | refused — unrecognised key (a probable misspelling) |
| `{"propose": ""}` | refused — present but injects nothing |
| `{"propose": []}` | refused — empty after the line-join |
| `{"propose": ["", ""]}` | refused — joins to `"\n"`, which is truthy but unreadable |
| `{"propose": {"a": 1}}` | refused — advice must be text |
| `{}` | refused — no recognised key at all |
| `{"propose": "..."}` | **accepted** — sparse advice is legal |

To carry a note the agents must never read, prefix its key with `_`, which
declares it deliberately inert. For example, `_meta` may record why an
artifact exists. This is an explicit opt-out; an unrecognised key *without*
it is treated as the typo it almost always is.

**Why this is a refusal and not a warning.** The artifact's sha256 is pinned
into the run-invariants lock as the run's treatment identity, distributed to
every band and certified by each. A misspelled or empty artifact still hashes,
still certifies, and still gets recorded — producing a run whose provenance
says advice artifact X was used while every agent received nothing derived
from it. Certification answers *which bytes*; it cannot answer whether those
bytes reached a prompt.


## Other callers and historical Gate advice

Standalone node inputs follow their own [node contracts](../docs/agent-reference/README.md#nodes).
The external TIDMAD baseline tool now lives at
`siderius-exp/tasks/tidmad/tools/run_comparison.py`; its separate advice reader
requires a `tune` key. It is not the chain loader described here. See the
[external-consumer map](../docs/repository-map.md#external-consumer-and-evidence)
for the inspected repository and revision.

Historical Gate advice is validation evidence, not a new scientific default.
Its model/VRAM constraints belong to the specific approved Gate contract and
[Gate standard](../docs/gates/gate_testing_standard.md), not to this format
README. No new run or advice artifact is selected by this document.
