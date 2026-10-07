# Persistence and records

**Audience**: anyone reading a run directory, or wondering whether the
numbers in it can be trusted after a crash, a rerun, or a resume.
**Answers**: which copy of the history is true, what is append-only versus
derived, and what the integrity machinery refuses.

The directory layout itself is in
[workspaces and resume](../guides/workspaces-and-resume.md) — this page is
about the *rules* the files obey. Implementer depth:
[persistence and resume mechanism](../agent-reference/mechanisms/persistence-and-resume.md).

---

## One canonical fact, one derived view

The experiment record history follows a single rule, stated before anything
is written (`core/record_log.py`):

```
canonical : {tuner_workspace}/records/<run_name>/records.jsonl   append-only history
derived   : {tuner_workspace}/summary_<run_name>.json            latest-wins projection
```

Every saved experiment record is **appended** to the canonical JSONL log
(flush + fsync), and the summary every reader consumes — the dashboard
included — is a *projection* of that log: the latest record per `exp_id`, in
first-insertion order, regenerated and published atomically on every save. A
superseded record **stays in the log as evidence**; the projection is never
applied to the log itself.

Why it is built this way: before this rule the summary *was* the history —
rewritten wholesale on every save. A crash mid-rewrite left a torn file, a
torn file read as an empty list, and the next save silently rewrote the
run's entire history as a single record. Now:

- each record's **detail file** (`records/<run_name>/<exp_id>.json`) is
  published by atomic replace;
- the **append** is durable before the view is touched;
- the **summary** is rebuilt from the log and replaced atomically — a view
  that is torn, missing, or stale is repaired in place on the next read;
- an **unreadable** history raises `RecordHistoryUnreadable` instead of
  returning `[]`, because "empty" is what a *fresh* workspace looks like and
  an unreadable one must never be mistaken for it;
- a workspace written before the log existed is bootstrapped from its legacy
  summary once, write-once, so no old history is lost.

A torn *tail line* in the log (a crash mid-append) is skipped with a stderr
warning naming the line — one unfinished line never costs the rest of the
history.

## Iteration manifests are write-once

`iter_NNN/manifest.json` is the chain's committed handoff between iterations
and the anchor of replay integrity (`core/iteration_manifest.py`). Each
manifest carries two digests: `run_output_sha256` (the artifact it names)
and `manifest_sha256` (a self-digest over every other field, computed over
canonical bytes so formatting cannot move it).

The rules, frozen by operator ruling #258:

- **Normal manifests are write-once.** Publishing into an occupied slot is
  `ManifestAlreadyPublishedError`, and the gate fires at *launch* time —
  before an hours-long rerun, not after it.
- **A same-iteration replacement is an explicit operation with recorded
  provenance**: `--replace_iteration_manifest --replacement_reason '<why>'`.
  The previous manifest is set aside (never deleted) as
  `manifest.replaced.<utc-stamp>.json`, and the new one records the reason,
  the timestamps, and the previous digests under `manifest_replacement`.
- **An ordinary rerun never silently regenerates integrity hashes.**

Verification has **one definition**: `verify_iteration_manifest` is the
predicate `core/resume.py`, `execute_tools/per_file_best.py` and
`scripts/launch/inspect_run_state.py` all call. A tampered field, a removed
artifact hash on a completed iteration, or an artifact that no longer hashes
to its manifest each produce a named problem; a genuinely pre-digest legacy
manifest is admitted *visibly unverified* — "unverified" is a state, never
an error. Stated plainly: a hand rewrite that recomputes every digest is
indistinguishable from a legitimate publish — there is no secret; the
control is the write-once publish plus the replacement provenance, which a
rewrite through the sanctioned producer cannot skip.

## The invariants lock pins comparability

`{workspace}/run_invariants_lock.json` pins, per workspace: the resolved
data scope, health-gate enablement, and the sha256 of the effective health
configuration — because **aggregate scores are only comparable within one
scope and one health configuration**. Any resume, seed or reuse with one of
these different fails at startup, naming the mismatch. Provenance-class
fields (resolved memory ceilings, the generated-library root) are *recorded
and never compared*, so the same science resumed on a differently-calibrated
host stays legal.

## Records are logs, never channels

Every node writes its output record to
`{workspace}/{node}_{run_name}.json` — for humans and recovery. Nodes never
read each other's files; data flows between nodes through typed protocol
functions in memory. Reading a peer's record file by convention would create
an edge invisible to the protocol system, which is why it is a defect and
not a shortcut.

## What this machinery refuses, on purpose

| you did | it says |
|---|---|
| rerun a completed iteration without the replacement flag | `…/manifest.json already exists — iteration manifests are write-once (#258)…` |
| pass the replacement flag with nothing to replace | `--replace_iteration_manifest was given but … does not exist — there is nothing to replace` |
| edit a published manifest | `iter NNN manifest changed after publication …` from every verifier |
| resume under a different scope / health config | startup failure naming the mismatched invariant |
| point it at a corrupt legacy summary with no log | `RecordHistoryUnreadable` — restore it; an unreadable history is not an empty one |

Each row is the guard working. None of them is something to relax.

## Where to go next

- [Workspaces and resume](../guides/workspaces-and-resume.md) — the layout and the two-verb model
- [Persistence and resume mechanism](../agent-reference/mechanisms/persistence-and-resume.md) — carried state, digests, source map
- [Operating a run](../guides/operating-a-run.md)
