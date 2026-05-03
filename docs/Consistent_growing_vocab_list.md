# Cross-Iteration Vocabulary & Findings Persistence

**Branch:** `hotfix/estimator-recalibration-v7`
**Status:** PLANNING — diffs drafted, awaiting review before apply.
**Author:** Yue Ma + Claude (2026-04-30)
**Related:** `docs/phase68_orchestrator_memory_and_resume.md` §3.3, §200, §218, §423

---

## 1. Problem Statement

### 1.1 The "Knowledge Amnesia" gap

The V7 chain runner spawns a fresh Python process per iter (`run_chain.sh` →
`run_one_iteration.py`). `core.resume.restore_prior_state` was designed to
restore the "soul" of prior iters — but it currently restores only:

1. **Plugin classes** — re-registers `MODEL_REGISTRY` entries from prior iters'
   `plugins/iter_NNN/*.py`.
2. **Run-output JSONs** — appends prior iters' `run_output_iter_NNN.json` paths
   to `source_paths`, so the workflow re-loads them as historical
   `ModelRunSummary` objects.

Critically, it does **not** restore:

- `runtime_vocab` (the accumulating list of `VocabEntry` items — features,
  capabilities, discoveries, candidate→canonical promotion state).
- `key_findings` (the chronological list of free-text take-homes that the
  interpretation node produces each iter).

`workflows.model_exploration.run_workflow` then unconditionally resets vocab
to the static seed at the top of every per-iter Python process:

```python
# workflows/model_exploration.py:728
current_runtime_vocab = list(vocab_seed)     # starts with seed, grows with discoveries
```

The "grows with discoveries" comment was true for the legacy in-process runner
(where one Python interpreter ran `max_iterations` of the loop and the local
variable persisted). It is **false** in chain mode (where `max_iterations=1`
and the process exits at iter end).

### 1.2 Empirical confirmation (V7 explore workspace, 2026-04-30)

Snapshot of `<workspace>/iter_NNN/iteration_001/interpretation_iter_NNN.json::runtime_vocab`
across five committed iters on
`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v7_0429/`:

| Source                                    | # Vocab entries | Tier breakdown    | # Discoveries |
|-------------------------------------------|----------------:|-------------------|--------------:|
| `agent/schemas/vocab_seed.json` (static)  |              21 | all canonical     |             0 |
| `iter_001/.../interpretation_iter_001.json` |            21 | all canonical     |             0 |
| `iter_002/.../interpretation_iter_002.json` |            21 | all canonical     |             0 |
| `iter_003/.../interpretation_iter_003.json` |            21 | all canonical     |             0 |
| `iter_005/.../interpretation_iter_005.json` |            21 | all canonical     |             0 |

Five iters, zero growth. Every iter's interp node sees only the static seed.
The `seen_in_runs ≥ 3` candidate→canonical promotion threshold cannot fire —
no candidate ever survives more than one iter.

### 1.3 Why the original assumption broke

`docs/phase68_orchestrator_memory_and_resume.md` §423 stated:

> Promotion is reconstructible from records on any future run.

The chain-first design assumed that *anything worth keeping* would appear in
the on-disk `run_output_*.json` records (model_type, hyperparams, scores).
The interp node would then re-derive vocabulary from those records each time.

That assumption fails for:

- **Untested candidate entries** — features/capabilities the LLM proposed but
  the architecture got rejected by the gate, never reached training, never
  produced a run record.
- **Cross-iter `seen_in_runs` accumulation** — the in-memory `vocab_by_name`
  dict in `build_runtime_vocab` is the only place `seen_in_runs` accrues, and
  it dies with the Python process at iter end.
- **Chronological `key_findings`** — the `key_findings: List[str]` on
  `InterpretationOutput` is overwritten each iter; only the latest iter's
  bullet list is in scope at any time. Chain-iter N's interp node sees only
  iter N-1's findings via `previous_proposal`, and the proposer for iter N
  sees nothing from iters 1..N-2.

**Net effect:** the SIDERIUS chain has the *appearance* of long-term memory
(prior model architectures get re-registered, prior run records flow into the
summaries channel) but the *vocabulary evolution* loop is silently flat.

---

## 2. Solution Overview

Wire two new pieces of state through the chain restore boundary:

```
┌───────────────────┐   reads iter_NNN/iteration_001/interpretation_iter_NNN.json
│ load_latest_      │
│ knowledge()       │   →  RestoredState.runtime_vocab          (latest committed iter)
│  (core/resume.py) │   →  RestoredState.accumulated_key_findings (union, all committed iters)
└───────────────────┘
          │
          ▼  forwarded by run_one_iteration.py as kwargs
┌───────────────────────────────┐
│ run_workflow(                 │
│   restored_runtime_vocab=...  │   →  current_runtime_vocab    (replaces static seed when present)
│   accumulated_key_findings=...│   →  ExpertContextItem        (passed to local_full_context → proposer)
│ )                             │
└───────────────────────────────┘
```

### 2.1 Alignment decisions (locked, 2026-04-30)

| Question                  | Decision                                         | Rationale                                                                                                                              |
|---------------------------|--------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------|
| Branch                    | **(b)** stay on `hotfix/estimator-recalibration-v7` | User: "critical fix for the V7 experiment's validity." Mixed scope is acceptable here.                                                |
| Promotion semantics       | **(b)** tested-only                              | A vocab entry's `seen_in_runs` must only grow when an actual architecture using that vocab completed a run. LLM-mention does not count. |
| `key_findings` relay      | **(a)** accumulate all prior iters               | Proposer needs full historical context to avoid repeating known dead-ends.                                                             |
| Timing                    | **(b)** implement + merge now                    | V7 chains will be killed and relaunched against the patched code; iter_006/iter_005 mid-experiment is acceptable.                       |
| `seen_in_runs` preservation | preserve verbatim during relay                 | `build_runtime_vocab` only appends new run IDs from the current iter via the `proposed_candidates` channel; load path must not mutate. |

### 2.2 Why the four design choices are mutually consistent

- **Tested-only promotion** is enforced *by construction*: `load_latest_knowledge`
  only reads digests under `committed_iters` (manifests with
  `status == "completed"`). The `seen_in_runs` lists in those digests already
  reflect tested architectures — they were appended during the prior iter's
  `result_interpretation_agent.run()` call, which only ran after the tuner
  produced a successful record.
- **`seen_in_runs` preservation verbatim** falls out of the same property:
  the load function copies `seen_in_runs` from disk into the `VocabEntry`
  object, and `build_runtime_vocab` (unchanged) only appends *the current
  iter's run name* via `proposed_candidates`. No double-counting, no
  inflation from LLM-mention.
- **Accumulated `key_findings`** ride a separate channel
  (`ExpertContextItem` → proposer prompt), so they never interact with the
  vocabulary promotion logic.

---

## 3. Detailed Implementation Plan

### 3.1 File-level summary

| File                                              | Change kind | LOC delta (approx) |
|---------------------------------------------------|-------------|--------------------|
| `core/resume.py`                                  | extend      | +90 / -0           |
| `workflows/model_exploration.py`                  | edit        | +35 / -1           |
| `sdsc_submission_scripts/run_one_iteration.py`    | edit        | +3  / -0           |
| `tests/unit/core/test_resume.py`                  | extend      | +60 / -0 (new tests) |
| `docs/phase68_orchestrator_memory_and_resume.md`  | annotate    | +20 / -0 (reversal note) |

### 3.2 `core/resume.py` — DNA extractor

**3.2.1 New import**

```python
from agent.schemas.proposal import VocabEntry
```

**3.2.2 Extend `RestoredState`**

```python
@dataclass
class RestoredState:
    resolved_source_paths: List[str] = field(default_factory=list)
    restored_plugins: List[str]      = field(default_factory=list)
    committed_iters: List[int]       = field(default_factory=list)
    # NEW:
    runtime_vocab: List[VocabEntry]            = field(default_factory=list)
    accumulated_key_findings: List[str]        = field(default_factory=list)
```

**3.2.3 New helpers**

```python
def _interpretation_path(workspace: str, iter_idx: int) -> str:
    """{workspace}/iter_NNN/iteration_001/interpretation_iter_NNN.json"""
    return os.path.join(
        workspace,
        _iter_run_name(iter_idx),
        "iteration_001",
        f"interpretation_{_iter_run_name(iter_idx)}.json",
    )


def load_latest_knowledge(
    workspace: str,
    current_iter: int,
    committed_iters: Sequence[int],
) -> tuple[List[VocabEntry], List[str]]:
    """Read prior iters' interpretation digests; return (runtime_vocab, accumulated_key_findings).

    Behaviour:
      - current_iter <= 1 OR no committed iters       -> ([], [])
      - missing/malformed digest                       -> warn + skip that iter, keep going
      - runtime_vocab: LATEST committed iter wins (already merged with seed via build_runtime_vocab)
      - accumulated_key_findings: union across ALL committed iters, dedup-by-string,
                                  first-occurrence wins, chronological order preserved
      - per-entry validation failure                   -> warn, drop that entry, keep the rest
    """
```

**3.2.4 Wire into `restore_prior_state`**

At the very end of the function, after the for-loop and before `return state`:

```python
state.runtime_vocab, state.accumulated_key_findings = load_latest_knowledge(
    abs_workspace, current_iter, state.committed_iters,
)
if state.runtime_vocab or state.accumulated_key_findings:
    print(
        f"[resume] knowledge carry-over: "
        f"{len(state.runtime_vocab)} vocab entries, "
        f"{len(state.accumulated_key_findings)} accumulated key findings"
    )
return state
```

### 3.3 `workflows/model_exploration.py` — Knowledge Relay

**3.3.1 Import update**

```python
# from agent.schemas.proposal import VocabEntry
from agent.schemas.proposal import ExpertContextItem, VocabEntry
```

**3.3.2 New `run_workflow` kwargs**

```python
# --- Cross-iter knowledge carry-over (forwarded by chain runner) ---
restored_runtime_vocab: list | None = None,
accumulated_key_findings: list[str] | None = None,
```

Both default to `None` so the in-process / first-iter caller path is
unchanged. Chain-mode `run_one_iteration.py` always supplies them.

**3.3.3 Replace static-seed initialization (line 728)**

```python
# OLD
current_runtime_vocab = list(vocab_seed)

# NEW
if restored_runtime_vocab:
    current_runtime_vocab = [
        v if hasattr(v, "name") else VocabEntry.model_validate(v)
        for v in restored_runtime_vocab
    ]
    print(
        f"  Vocab restored from prior chain iters: "
        f"{len(current_runtime_vocab)} entries "
        f"({sum(1 for v in current_runtime_vocab if v.kind == 'discovery')} discoveries)"
    )
else:
    current_runtime_vocab = list(vocab_seed)  # first iter or in-process run
```

**3.3.4 Build `ExpertContextItem` for the proposer**

Just before the `propose_input = local_full_context(...)` call inside the
attempt loop:

```python
expert_context_for_propose: list[ExpertContextItem] = []
if accumulated_key_findings:
    bullet_block = "\n".join(f"- {kf}" for kf in accumulated_key_findings)
    expert_context_for_propose.append(
        ExpertContextItem(
            source="prior_iters",
            kind="findings",
            content=(
                f"Accumulated key findings from "
                f"{len(accumulated_key_findings)} prior iter(s):\n"
                f"{bullet_block}"
            ),
            cite_id="prior_iters_key_findings",
        )
    )
```

Then pass it as `expert_context=expert_context_for_propose` to
`local_full_context`. The protocol already merges `expert_context` with any
legacy `human_advice` it converts.

### 3.4 `sdsc_submission_scripts/run_one_iteration.py` — Wiring

In the `run_workflow(...)` call (line ~652):

```python
# NEW (last two kwargs)
restored_runtime_vocab=state.runtime_vocab,
accumulated_key_findings=state.accumulated_key_findings,
```

### 3.5 `tests/unit/core/test_resume.py` — Coverage

New tests to add:

1. **`test_load_latest_knowledge_iter1_returns_empty`** —
   `current_iter=1` → `([], [])` (no prior iters).
2. **`test_load_latest_knowledge_picks_latest_runtime_vocab`** —
   write 2 mock interp digests under `iter_001/` and `iter_002/`; assert
   returned `runtime_vocab` matches iter_002's entries (latest wins).
3. **`test_load_latest_knowledge_accumulates_findings_chronologically`** —
   iter_001 findings = `["A", "B"]`, iter_002 findings = `["B", "C"]`;
   assert returned list is `["A", "B", "C"]` (first-occurrence wins).
4. **`test_load_latest_knowledge_skips_missing_digest_with_warning`** —
   iter_002 has manifest but no interp digest; assert warn emitted, iter_001's
   vocab still returned.
5. **`test_load_latest_knowledge_skips_malformed_json_with_warning`** —
   iter_002 digest is malformed JSON; assert warn emitted, iter_001's vocab
   still returned.
6. **`test_load_latest_knowledge_drops_malformed_vocab_entries`** —
   iter_001 digest has 2 valid + 1 invalid `runtime_vocab` entry; assert 2
   entries returned, 1 warn emitted.
7. **`test_restore_prior_state_populates_new_fields`** — full-stack: build a
   mock 2-iter workspace, call `restore_prior_state`, assert
   `state.runtime_vocab` and `state.accumulated_key_findings` are populated.
8. **`test_restore_prior_state_iter1_leaves_new_fields_empty`** —
   `current_iter=1` → both new fields are `[]`.
9. **`test_seen_in_runs_preserved_verbatim_across_load`** —
   write iter_001 digest with a vocab entry whose `seen_in_runs == ["iter_001"]`;
   load it; assert returned entry's `seen_in_runs == ["iter_001"]` (no
   mutation, no append, no drop).

### 3.6 Doc reversal note

In `docs/phase68_orchestrator_memory_and_resume.md`, append a
**§3.3.x Vocabulary persistence reversal** subsection that:

- Notes that §200 + §423 ("promotion is reconstructible from records") was
  empirically refuted on 2026-04-30 by the V7 explore-chain data.
- Points at this doc as the patch design.
- Records the new contract: `RestoredState` carries vocab + findings
  alongside source paths.

---

## 4. Back-compat & Failure Modes

| Scenario                                                            | Behaviour                                                                                            |
|---------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| First chain iter (`current_iter == 1`)                              | `load_latest_knowledge` returns `([], [])`; `run_workflow` falls back to static seed.                 |
| Legacy in-process caller (no `state` object)                        | `restored_runtime_vocab=None`, `accumulated_key_findings=None` defaults → static seed, no findings. |
| Prior iter has manifest but no interp digest                        | Warn, skip; loader continues with remaining iters.                                                   |
| Prior iter's digest is malformed JSON                               | Warn, skip; loader continues with remaining iters.                                                   |
| Prior iter's digest has a malformed `runtime_vocab` entry           | Warn, drop that entry; rest of the digest survives.                                                  |
| `committed_iters == []` (every iter was `no_records`)               | Returns `([], [])`; static seed used; this is correct — nothing was ever validated.                  |
| Test runs that don't touch chain resume                             | Untouched — no test currently constructs `RestoredState` with kwargs we removed.                     |

---

## 5. Verification Plan

### 5.1 Unit tests (must pass)
```bash
.venv/bin/python -m pytest tests/unit/core/test_resume.py -v
```
All 9 new tests + existing tests must pass.

### 5.2 Smoke check on live V7 explore workspace (read-only)
```bash
.venv/bin/python -c "
from core.resume import load_latest_knowledge
ws = '/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v7_0429'
vocab, findings = load_latest_knowledge(ws, current_iter=7, committed_iters=[1,2,3,5])
print(f'vocab entries: {len(vocab)}')
print(f'findings:      {len(findings)}')
print(f'discoveries:   {sum(1 for v in vocab if v.kind == \"discovery\")}')
"
```
**Expected (pre-relaunch):** vocab ≥ 21, findings ≥ 1 (cumulative across prior iters).
**Sanity:** since the bug means runtime_vocab on disk is currently just the seed,
this should return 21 entries on the first read. After at least one
patched-code iter runs, the count should grow.

### 5.3 End-to-end: relaunch and observe
1. Kill current V7 chains (`screen -X -S siderius-explore-v7 quit` and exploit).
2. Cleanup any partial in-flight iter dirs as needed (consult inspector).
3. Relaunch both chains against the patched code.
4. After iter_006 (explore) / iter_005 (exploit) commits, inspect:
   `iter_NNN/iteration_001/interpretation_iter_NNN.json::runtime_vocab`.
   **Expected:** entry count > 21, OR at least one entry with
   `seen_in_runs >= 2` (the relayed entry from the prior iter, plus
   the current iter's append via `proposed_candidates`).

### 5.4 Regression sanity
- `tests/integration/workflows/test_vocab_accumulation.py` (in-process
  agent-level test) must still pass — the new code path does not touch
  in-process semantics.
- `tests/integration/nodes/test_*.py` for interpretation + proposal nodes:
  no schema changes, no behavioural change when both new kwargs default
  to `None`.

---

## 6. Commit Strategy

Single commit on `hotfix/estimator-recalibration-v7`:

```
feat(evolution): implement cross-iteration vocabulary and findings persistence

- core/resume.py: load_latest_knowledge() reads iter_NNN's interpretation digests
  and returns (runtime_vocab, accumulated_key_findings). Extends RestoredState
  with two new fields populated at the end of restore_prior_state.
- workflows/model_exploration.py: run_workflow accepts restored_runtime_vocab
  and accumulated_key_findings kwargs. The static seed init is replaced with
  a priority check; accumulated findings are surfaced to the proposer via a
  single ExpertContextItem(source="prior_iters", kind="findings").
- sdsc_submission_scripts/run_one_iteration.py: forwards the new RestoredState
  fields into run_workflow.
- tests/unit/core/test_resume.py: 9 new tests covering load behaviour,
  back-compat, and seen_in_runs preservation.
- docs/phase68_orchestrator_memory_and_resume.md: §3.3.x reversal note.

Empirical motivation: V7 explore-chain iter_001..005 all show 21 vocab
entries (== static seed). Five iterations, zero growth — the chain-first
"promotion is reconstructible from records" assumption empirically failed
for untested candidates and seen_in_runs accumulation. This patch wires
the missing carry-over channel through the resume boundary.
```

---

## 7. Checklist

### Pre-implementation
- [x] Empirical confirmation of the bug on V7 explore workspace (5 iters, 21 entries each).
- [x] Trace of the reset point (`workflows/model_exploration.py:728`).
- [x] Schema verification — `InterpretationOutput.runtime_vocab` and `.key_findings` both present.
- [x] Filename/path convention confirmed: `{workspace}/iter_NNN/iteration_001/interpretation_iter_NNN.json`.
- [x] Alignment with user on the four open questions (branch / promotion / findings / timing).

### Implementation
- [x] `core/resume.py` — add `VocabEntry` import.
- [x] `core/resume.py` — extend `RestoredState` with `runtime_vocab` + `accumulated_key_findings`.
- [x] `core/resume.py` — add `_interpretation_path` helper.
- [x] `core/resume.py` — add `load_latest_knowledge` function.
- [x] `core/resume.py` — call `load_latest_knowledge` at end of `restore_prior_state`.
- [x] `workflows/model_exploration.py` — add `ExpertContextItem` to imports.
- [x] `workflows/model_exploration.py` — add `restored_runtime_vocab` + `accumulated_key_findings` kwargs to `run_workflow`.
- [x] `workflows/model_exploration.py` — replace static-seed init with priority check.
- [x] `workflows/model_exploration.py` — build `ExpertContextItem` and pass via `local_full_context(expert_context=...)`.
- [x] `sdsc_submission_scripts/run_one_iteration.py` — forward both new fields into `run_workflow`.

### Testing
- [x] `tests/unit/core/test_resume.py` — 9 new tests written.
- [x] All `tests/unit/core/test_resume.py` tests pass with `.venv/bin/python -m pytest` (35 passed: 26 pre-existing + 9 new).
- [x] Smoke check (§5.2) on V7 explore workspace: 21 vocab entries (matches static seed pre-patch — expected per §8 risk #4), 23 accumulated key findings.
- [ ] In-process integration test `tests/integration/workflows/test_vocab_accumulation.py` still passes.

### Doc updates
- [ ] `docs/phase68_orchestrator_memory_and_resume.md` — reversal subsection added.
- [ ] This doc (`docs/Consistent_growing_vocab_list.md`) — checkboxes ticked as work progresses.

### Commit + relaunch
- [ ] Single feat commit on `hotfix/estimator-recalibration-v7` with the message in §6.
- [ ] V7 chains killed cleanly (both screens).
- [ ] V7 workspaces inspected with `scripts/inspect_run_state.py --layout chain --next-iter` to confirm next-iter values.
- [ ] V7 chains relaunched against patched code with the same 135-min budget.
- [ ] After first patched iter commits on each chain, verify
      `interpretation_iter_NNN.json::runtime_vocab` shows growth (entry count > 21
      OR at least one entry with `seen_in_runs >= 2`).

---

## 8. Open Risks (post-merge watch list)

1. **Prompt size growth.** `accumulated_key_findings` is unbounded. After 20
   iters with ~5 findings each, the proposer prompt gains ~100 bullets. If
   this becomes a problem, switch to a bounded FIFO (last K iters) or
   summarisation pass — but only after observing real growth, not
   pre-emptively.
2. **Stale relayed candidates.** A candidate the LLM proposed in iter N+1's
   architecture might fail the gate forever; the relay still carries it
   forward. The `seen_in_runs ≥ 3` promotion threshold prevents canonical
   contamination, but the candidate clutter accumulates. Acceptable for now
   — the proposer can see it as "tried, didn't pan out" context. Revisit if
   prompt size becomes an issue.
3. **Schema drift.** If `InterpretationOutput.runtime_vocab` ever changes
   shape, `load_latest_knowledge`'s per-entry `VocabEntry.model_validate`
   will start dropping entries. The warning emit makes this visible but
   silent loss is possible. Mitigation: the existing test suite covers
   schema stability for `VocabEntry`; add a CI check if needed.
4. **First-iter-after-patch regression.** The first iter after this lands
   reads digests written by the *unpatched* code. Those digests contain
   only the static seed. So the first patched iter's vocab still matches
   the seed; growth begins from iter N+2 onward. This is correct — no
   action needed, just an expectation to set.

---

*End of design doc.*
