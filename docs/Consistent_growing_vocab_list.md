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

## 9. Post-PR-#66 Audit (2026-05-02)

PR #66 (`dce064a`, merged 2026-05-03) shipped the long-term memory
infrastructure described in §2–§3 plus the V8 cognitive-alignment work and
the V9 formal-strategy refactor. This section records what actually landed
in master and which of the previously-identified gaps remain open.

### 9.1 What landed (verified against master)

`RestoredState` lives at `core/resume.py:65` with seven fields:

| Field | Purpose | Cap |
|---|---|---|
| `resolved_source_paths` | source-data paths for `run_workflow(source_paths=...)` | none |
| `restored_plugins` | plugin classes re-registered into the four registry surfaces | none |
| `committed_iters` | 1-based iter indices successfully restored | none |
| `runtime_vocab` | latest committed iter's `InterpretationOutput.runtime_vocab` (overwrite, not merge) | none |
| `accumulated_key_findings` | chronological union (dedup, first-occurrence) of every committed iter's `key_findings` | **none** |
| `accumulated_physical_rejections` | chronological VRAM-gate rejections | `_MAX_ACCUMULATED_REJECTIONS = 10` |
| `accumulated_gate_exhaustions` | chronological gate-abort summaries | `_MAX_ACCUMULATED_GATE_EXHAUSTIONS = 10` |

The four "memory" channels (`runtime_vocab`, `accumulated_key_findings`,
`accumulated_physical_rejections`, `accumulated_gate_exhaustions`) are
forwarded into `run_workflow` as kwargs at `workflows/model_exploration.py`
lines 608–615 and consumed at:

- **vocab restore**: lines 791–800 — chain-restored runtime_vocab takes
  priority over the static seed; first-iter falls back to seed.
- **key findings render**: ~line 968 — full list rendered into one
  `ExpertContextItem` block for the proposer prompt.
- **physical rejections seed**: prior block — fed into proposer's
  `previous_failures`.
- **gate exhaustions pre-seed**: lines 819–827 — synthetic
  `HyperparamTuningOutput` wrappers pushed into the
  `recent_tune_outputs` deque (maxlen=3) so the proposer's
  `[RECENT GATE EXHAUSTIONS]` block reflects chain history.

Adaptive runner parity: commit `ea4fc21` ("fix(chain): adaptive runner
threads 5 chain-resume kwargs to run_workflow") closes the previously-noted
adaptive/one-iter drift. Both runners now forward identically.

### 9.2 Gaps from the prior audit — current status

The previous audit identified eight gaps (G1–G8). Re-checked against
master (`dce064a`):

| Gap | Field | Severity | Status post-PR-#66 |
|---|---|---|---|
| G1 | `previous_proposal_data` → `proposed_vocab_candidates` / `proposed_vocab_links` | High | **OPEN** |
| G2 | `cumulative_information_gain` | Med | **OPEN** |
| G3 | `vocab_link_confirmations` | Med | **OPEN** |
| G4 | `accumulated_key_findings` cap | Med | **OPEN** |
| G5 | `model_knowledge_cache` | Low (perf) | **OPEN** |
| G6 | `best_score_overall` (status-only) | None | n/a |
| G7 | `iteration_results` (covered by G1-rejections channel) | None | covered |
| G8 | `recent_tune_outputs` deque | None | covered (pre-seed at 819–827) |

PR #66 did not introduce any of the closures the previous audit suggested
for G1–G5. The infrastructure (`RestoredState` + forwarding) is in place,
but the additional fields were never added to it.

### 9.3 G1 — high-severity detail (proposed_vocab_candidates lost)

Confirmed at code level:

- `workflows/model_exploration.py:784`
  ```python
  previous_proposal_data: dict | None = None  # serialized ProposalOutput from iter N-1
  ```
  Initialised to `None` on every chain subprocess entry. No restore from
  disk.
- `workflows/model_exploration.py:1217`
  ```python
  previous_proposal_data = proposal.model_dump()
  ```
  Updates the local only — value is lost when `run_workflow` returns.
- Forwarded into the protocol at line 871
  (`previous_proposal=previous_proposal_data`) and consumed in the interp
  agent at:
  - `nodes/result_interpretation_agent.py:835` (`if inp.previous_proposal:`
    — falsifiable-prediction adjudication block).
  - `nodes/result_interpretation_agent.py:897`
    (`raw_candidates = inp.previous_proposal.get("proposed_vocab_candidates", [])`).
  - `nodes/result_interpretation_agent.py:935–945`
    (`proposed_vocab_links` → `update_vocab_link_confirmations`).

**Consequence in chain mode**: in iter N+1 the interp agent sees
`previous_proposal=None`, so:
- the proposer's iter-N candidates get **zero** `seen_in_runs` increments
  via the candidate channel (line 897 short-circuits);
- the proposer's iter-N vocab links never enter
  `vocab_link_confirmations` (line 935 short-circuits);
- the falsifiable-prediction adjudication (line 835) silently degrades.

The `seen_in_runs ≥ 3` promotion threshold therefore never fires from
chain signal. In a 30-iter chain, candidates are promoted to canonical
**only** when independently re-proposed and surviving the
`new_discoveries` channel — a different, weaker graduation mechanism.

This is the system's primary mechanism for graduating speculative
vocabulary into canonical vocabulary, and it is currently broken in
chain mode.

### 9.4 G2 / G3 — chain-boundary reset of derived interp state

`InterpretationOutput` persists `cumulative_information_gain` (line 1022)
and `vocab_link_confirmations` (line 1026) into the iter digest, but the
chain runner's `restore_prior_state` does not lift either field back into
the next iter's `InterpretationInput`. Each chain subprocess therefore
starts with the schema default for both:

- `cumulative_information_gain` resets to `0.0` (or whatever the input
  default is) → bold-prediction trajectory across the chain is lost.
- `vocab_link_confirmations` resets to `{}` → cross-iter feature↔capability
  link confirmations cannot reach the `≥3 runs → promote to
  VocabEntry.related_to` rule.

Both are derived state that already lives in the digest; closing the gap
is a `RestoredState` extension + a `load_latest_*` helper, not a new
storage surface.

### 9.5 G4 / G5 — bookkeeping items

- **G4**: `accumulated_key_findings` is unbounded. The §8 watch-list
  flagged this as a prompt-size concern; it is not yet a cap. With ~5
  findings/iter, a 30-iter chain produces ~150 bullets in a single
  `ExpertContextItem` block. **The full retention-policy design lives
  in §14** (two-bucket "focus without amnesia" model). The naïve
  trailing-slice mitigation originally noted here was the bridge
  proposal in §9.6.3 — see §14.1 for why it is now superseded.
- **G5**: `model_knowledge_cache: dict = {}` at
  `workflows/model_exploration.py:803` resets every subprocess. The
  Phase-1 LLM call re-runs for repeated models in a chain. Pure perf cost,
  no correctness impact.

### 9.6 Recommended next steps (no code touched yet)

In severity order:

1. **G1 (high)** — see **§10 Evolution Loop Closure** for the full
   approved plan. Summary: extend `RestoredState` with
   `previous_proposal_data: dict | None`, add a `_proposal_path()` helper
   + `load_latest_proposal()` reader, thread a new `restored_previous_
   proposal` kwarg through `run_workflow`, and forward it from
   `run_one_iteration.py`.
2. **G2 + G3 (med, paired)** — add `cumulative_information_gain: float`
   and `vocab_link_confirmations: dict[str, list[str]]` to `RestoredState`
   from the latest committed iter's interp digest. Forward both into the
   `InterpretationInput` constructor in the workflow.
3. **G4 (med)** — **superseded by §14**. The original proposal here
   was a single `_MAX_ACCUMULATED_KEY_FINDINGS` constant + trailing-slice
   trim (mirroring lines 458–464 for rejections/gate-exhaustions). On
   review, that policy is wrong for findings: rejections/gate-exhaustions
   genuinely *do* go stale ("older rejections become stale once the
   architecture/budget combo evolves"), but findings include long-term
   architectural milestones that should survive even when newer findings
   exist. §14 specifies a two-bucket retention policy (recency window +
   milestone reservoir) and a Pydantic `FindingsRetentionPolicy` config
   to make the trade-off explicit and tunable.
4. **G5 (low)** — defer. Persisting `model_knowledge_cache` requires a
   schema for the cache contents; not worth it until measured Phase-1
   re-call cost is meaningful.

Each closure is independent and can ship as its own commit. None require
schema changes to existing JSON on disk — they only add new readers
against fields already persisted.

### 9.7 What this audit did NOT verify yet

- **End-to-end empirical run.** No live V8 chain has been inspected to
  confirm the symptoms predicted above (specifically: a candidate with
  three independent proposals in chain mode that fails to reach canonical
  in the iter-N+3 digest). Recommended as a follow-up smoke once a long
  V8 chain is available.
- **`run_one_iteration.py` forwarding completeness** — verified.
  `sdsc_submission_scripts/run_one_iteration.py:722-726` forwards all
  four memory channels (`runtime_vocab`, `accumulated_key_findings`,
  `accumulated_physical_rejections`, `accumulated_gate_exhaustions`) into
  `run_workflow`. The other three `RestoredState` fields are structural
  (`resolved_source_paths` line 654, `restored_plugins` + `committed_iters`
  lines 647-653 for reporting). No drift between writer and forwarder.

---

## 10. Evolution Loop Closure — G1 Bridge (Candidate Channel)

§1–§8 specified Phase 1 (vocab + key-findings carry-over) and PR #66
shipped it. §9 audited the merge and found the candidate-graduation
edge still severed at the chain-subprocess boundary. This section is
**Phase 2**: the design closure for that edge. It mirrors the §1–§7
template (problem → impact → architecture → verification → commit
plan → checklist → risks).

### 10.1 Why the Candidate Channel is Dark

In chain mode, each iter is a fresh Python subprocess via
`sdsc_submission_scripts/run_one_iteration.py`, and `run_workflow` is
called with `max_iterations=1`. The in-process loop body runs once.
`workflows/model_exploration.py:784` initialises:

```python
previous_proposal_data: dict | None = None
```

Line 1217 updates this local at end-of-iter:

```python
previous_proposal_data = proposal.model_dump()
```

But the process exits as soon as `run_workflow` returns. The next chain
iter is a different OS process; its line-784 init is `None` again. The
proposal file persists on disk at
`{workspace}/iter_NNN/iteration_001/attempt_MMM_<model_name>/proposal_iter_NNN.json`
(verified against live V8 iter 007 — present and well-formed), but
**no reader lifts it back into the next iter's
`InterpretationInput.previous_proposal`**.

In-process multi-iter (`max_iterations > 1`, single Python) is
unaffected: the local update at line 1217 is read by the next loop
turn at line 871. The mechanism only breaks at the subprocess boundary
— exactly where production V8 chains run.

### 10.2 Impact — Three Broken Promotion Paths

Three distinct features in `nodes/result_interpretation_agent.py` all
gate on `if inp.previous_proposal:`. All three short-circuit in chain
mode:

(a) **`seen_in_runs ≥ 3` candidate promotion** — line 897:
```python
if inp.previous_proposal:
    raw_candidates = inp.previous_proposal.get("proposed_vocab_candidates", [])
```
Short-circuits → `raw_candidates = []` → `build_runtime_vocab` does not
increment `seen_in_runs` from the proposer-relay channel.

(b) **Vocab-link confirmation** — lines 935–945:
```python
inp.previous_proposal.get("proposed_vocab_links", [])
if inp.previous_proposal else []
```
Short-circuits → no feature↔capability pairs reach
`update_vocab_link_confirmations` → the
`≥ 3 runs → VocabEntry.related_to` rule never fires from chain signal.

(c) **Falsifiable-prediction adjudication** — lines 835–839:
```python
if inp.previous_proposal:
    prev_prediction = inp.previous_proposal.get("falsifiable_prediction")
    prev_model_type = inp.previous_proposal.get("model_name", "unknown")
    prev_inherited = inp.previous_proposal.get("inherited_components", [])
```
Short-circuits → the LLM cannot score iter N-1's bold prediction
against iter N's measurements; the `Predicted vs. Observed`
reconciliation block degrades silently to "no prior prediction."

The `new_discoveries` channel (interp-emitted, not proposer-relayed)
still fires, so canonical vocab can still grow. But the
candidate-graduation pipeline — the system's *designed* graduation
mechanism — is fully dark in production chains.

### 10.3 Bridge Architecture

Mirror the existing `runtime_vocab` carry-over pattern. No new storage
surface; data already lives on disk.

#### 10.3.1 Schema extension

`core/resume.py`, add an 8th field to `RestoredState`:

```python
previous_proposal_data: dict | None = None
```

Docstring covers (i) latest-wins semantics (one iter's snapshot, not a
merged history), (ii) the three downstream consumers (a/b/c above),
(iii) why the asymmetry with `runtime_vocab` is correct — the interp
digest carries cumulative `seen_in_runs`; the proposal channel only
contributes the iter-N delta.

#### 10.3.2 Loader logic (glob-based)

`core/resume.py`, two new helpers:

```python
def _proposal_path(workspace: str, iter_idx: int) -> str | None:
    """Resolve the proposal JSON path for a committed iter.

    Layout: {workspace}/iter_NNN/iteration_001/attempt_MMM_<model_name>/
            proposal_iter_NNN.json

    The implementor produces one final attempt dir per iter; if multiple
    attempts exist (validation retries), the highest MMM prefix wins.
    Returns None when no attempt dir is present (no_records iter).
    """
```

```python
def load_latest_proposal(
    workspace: str, committed_iters: List[int]
) -> dict | None:
    """Walk committed_iters in reverse; return the first parseable
    proposal dict.

    Latest-wins, mirrors load_latest_knowledge's runtime_vocab semantics.
    Malformed JSON: warn + continue to the next-older iter (do not halt).
    Missing path / no_records iter: skip silently.
    """
```

Wire both into `restore_prior_state` next to the existing
`load_latest_knowledge` call; populate `state.previous_proposal_data`.

#### 10.3.3 Workflow plumbing

`workflows/model_exploration.py`:

- Add new kwarg next to the existing 4 memory kwargs at lines 608–615:
  ```python
  restored_previous_proposal: dict | None = None,
  ```
- Replace line 784 init from `None` to `restored_previous_proposal`.
- Leave line 1217 untouched — the in-process update remains correct;
  chain mode now gets a non-`None` seed instead of `None`.

#### 10.3.4 Chain runner forwarding

`sdsc_submission_scripts/run_one_iteration.py`, one kwarg added to the
`run_workflow` call (currently lines 722–726):

```python
restored_previous_proposal=state.previous_proposal_data,
```

### 10.4 Verification Contract

#### 10.4.1 Unit test (`tests/unit/core/test_resume.py`, extend)

Four cases against a synthetic workspace fixture:

1. Three committed iters, each with a parseable proposal JSON.
   `load_latest_proposal` → iter-3's proposal dict.
2. Iter-2 proposal malformed JSON → warning, fall back to iter-1's
   proposal.
3. Iter-3 has both `attempt_001_foo` and `attempt_002_bar` directories
   → loader picks `attempt_002_bar` (highest MMM wins).
4. No committed iters → `state.previous_proposal_data is None`.

#### 10.4.2 Integration test — `foo` graduation across chain

A 3-iter chain where the proposer (mocked or real) emits a candidate
`foo` (kind=`feature` or `capability_candidate`) in iters 1, 2, 3.
Assertions on the interp digest at each iter:

- after iter 1: `foo.seen_in_runs == ['iter_001']`, `kind == 'candidate'`.
- after iter 2: `foo.seen_in_runs == ['iter_001', 'iter_002']`,
  `kind == 'candidate'`.
- after iter 3: `len(foo.seen_in_runs) == 3`, **promoted from
  `candidate` to canonical kind**, and `foo` no longer appears in
  `proposed_vocab_candidates`.

This is the contract that proves the bridge restored the graduation
mechanism end-to-end.

#### 10.4.3 Regression guard

In-process multi-iter (`max_iterations=3`, single Python) must continue
to promote correctly. The fix is purely additive on the
no-prior-state path; this regression test guards against an accidental
override of line 1217's local update.

### 10.5 Commit Strategy (mirrors §6)

| # | Scope | Tests run before commit |
|---|---|---|
| 1 | `core/resume.py` — schema field + 2 loader helpers + `restore_prior_state` wiring | unit (resume) |
| 2 | `workflows/model_exploration.py` — kwarg accepted + line-784 init replacement | unit (workflow signature) |
| 3 | `sdsc_submission_scripts/run_one_iteration.py` — forwarding line | unit (chain runner signature) |
| 4 | Integration test — `foo` graduation in 3-iter chain (Tier 3) + regression guard | full Tier 3 |
| 5 | Doc closeout — flip §10.6 checkboxes + mark §9.6 G1 closed | n/a |

### 10.6 Checklist

- [x] §10.3.1 schema field added to `RestoredState` with docstring — `e1ca13d` (Commit 1.1)
- [x] §10.3.2 `_proposal_path` + `load_latest_proposal` helpers shipped — `e1ca13d` (Commit 1.1)
- [x] `restore_prior_state` wires the loader + populates field — `e1ca13d` (Commit 1.1)
- [ ] §10.3.3 `run_workflow` accepts and consumes the new kwarg — pending Commit 1.2
- [ ] §10.3.4 `run_one_iteration.py` forwards the new kwarg — pending Commit 1.3
- [x] §10.4.1 unit tests (4 cases) pass — `e1ca13d` shipped 9 (Commit 1.1; 4 mandated + 5 edge cases)
- [ ] §10.4.2 integration test (`foo` graduation) passes — pending Commit 1.4
- [ ] §10.4.3 regression: in-process multi-iter promotion still works — pending Commit 1.4
- [ ] §9.6 G1 bullet marked closed once §10 lands — pending Commit 1.5

### 10.7 Risks (post-merge watch list)

1. **Asymmetric semantics with `runtime_vocab`.** `previous_proposal_data`
   is a single iter's snapshot (latest-wins); `runtime_vocab` is
   conceptually a merged history. This matches today's in-process
   semantics — the interp digest carries cumulative `seen_in_runs`, the
   proposal channel only contributes the iter-N delta. Acceptable, but
   the asymmetry must be explicit in the schema docstring (§10.3.1).
2. **Stale proposal on iter restart.** If a chain iter crashes *after*
   writing the proposal JSON but *before* the digest is committed, the
   next chain run could in principle load a stale proposal. Mitigation
   by construction: `load_latest_proposal` walks `committed_iters` only,
   so it skips iters whose manifest is missing or non-`completed`. The
   crash-mid-iter case is therefore safe.
3. **Glob convention drift.** If the implementor's
   `attempt_NNN_<model>` naming convention changes, the loader silently
   returns `None` and the candidate channel goes dark again without a
   loud failure. Mitigation: §10.4.1 case 3 exercises the glob; a CI
   grep on the writer-side convention would harden it further.
4. **Necessary but not sufficient.** Promotion still requires the
   proposer LLM to *re-mention* the same candidate name across ≥ 3
   iters. The relay only re-opens the channel; if the LLM proposes
   `foo` once and never again, `seen_in_runs` stops at 1. This is
   correct system behaviour, not a bug — but it must be set as
   expectation when interpreting the `foo` integration-test result.

---

## 11. Monotonicity Audit — `runtime_vocab` Restore Path

**Concern raised**: `runtime_vocab` is the system's long-term intellectual
property — a record of every speculative term, every confirmed link,
every promoted capability across the chain. If iter N's digest is empty
or corrupted, does iter N+1's reload "wipe out" the accumulated lineage
from iters 1..N-1?

**Direct answer**: the policy is more accurately **"latest non-empty
parseable digest wins"**, not pure "latest wins". That distinction
provides genuine protection against several failure modes — but the
reload is still **overwrite-based, not merge-based**, so it provides
*soft* monotonicity, not *hard* monotonicity. Three real data-loss
vectors remain in master today.

### 11.1 What IS protected (today)

The reader at `core/resume.py:271-312` walks `committed_iters` in
ascending order. For each iter:

| Failure on iter N | Code path | Outcome |
|---|---|---|
| Digest file missing | line 273 → `continue` | Iter N-1's `runtime_vocab` survives. Safe. |
| Digest JSON malformed / unreadable | line 283 → `continue` | Iter N-1's `runtime_vocab` survives. Safe. |
| Digest parseable but `runtime_vocab` is `[]` (empty list, key absent, or null) | `raw_vocab = []` → validated stays `[]` → **line 309 guard `if validated:` does NOT fire** | Iter N-1's `runtime_vocab` survives. **Empty-snapshot protection.** Safe. |
| Iter N non-`completed` (interp crashed mid-write) | manifest filter in `_read_manifest` excludes from `committed_iters` | Iter never enters the loader. Safe. |

The line-309 guard is the explicit defence the original author put in
to prevent an empty digest from wiping the lineage:

```python
if validated:
    runtime_vocab = validated  # overwrite: only LAST iter's wins
```

That guard is the difference between pure "latest wins" (would wipe on
empty) and "latest non-empty wins" (preserves prior).

### 11.2 What is NOT protected — three residual loss vectors

These are honest gaps. Each is a data-loss path that exists in master
today and would not be caught by the existing protections.

**Loss vector 1 — Per-entry validation drops** (line 300-308).
If iter N's digest contains `[A_valid, B_schema_malformed]`, the
per-entry validate loop drops B with a `UserWarning` and produces
`validated = [A]`. The line-309 guard fires (validated is truthy). Iter
N's effective restored vocab is `[A]`. Iter N+1 receives `[A]` as
`incoming_vocab` for `build_runtime_vocab` (workflow line 802 →
helper line 367), and **B is permanently gone from the lineage** — no
future iter has a structural path to recover it.

**Loss vector 2 — LLM regression on a non-empty digest.**
If the interp pipeline writes iter N's digest with, say, 18 entries
where iter N-1 had 25 (all parseable), the loader has no way to detect
the shrink. `validated` has 18 valid entries → guard fires → 7 entries
lost from the lineage forever. Realistic causes: context-window
truncation in the LLM call that builds the digest, prompt changes
biasing the LLM to emit a smaller list, schema regressions. There is
no min-size or no-shrink check.

**Loss vector 3 — Same-name overwrite inside `build_runtime_vocab`**
(`nodes/interpretation_helpers.py:374-375`):

```python
for discovery in new_discoveries:
    vocab_by_name[discovery.name] = discovery
```

A `new_discovery` whose `name` matches an existing entry **overwrites
wholesale**. If the prior entry had
`seen_in_runs=['iter_001','iter_002']` and the LLM-emitted discovery
has `seen_in_runs=[]`, the overwrite shrinks the run history. The
promotion threshold is monotonic in `seen_in_runs` length, so this
can effectively unwind a candidate's progress toward graduation.

### 11.3 Soft vs. hard monotonicity — the structural truth

The system depends on a **trust contract with the writer**.
`build_runtime_vocab` (interpretation_helpers.py:345-401) is designed
to be additive: it starts with `incoming_vocab` as the base and only
adds. As long as the writer behaves and the digest survives JSON
validation, each iter's digest IS the full cumulative lineage, and
"latest non-empty wins" is equivalent to "cumulative state wins".

But the **reader is overwrite-based**, not merge-based. Once a name
disappears from a single committed iter's digest — for any of the
three reasons above — it is gone for every subsequent iter. There is
no second source of truth.

This is **soft monotonic**: the happy path grows monotonically; an
unhappy iter can permanently shrink the lineage.

### 11.4 Hardening Tiers (decision matrix)

If hard monotonicity is the goal — i.e. the lineage is treated as
durable IP that can never shrink — three layered options exist:

| Tier | Change | Loc | What it buys |
|---|---|---|---|
| **A. Cheap floor** | Loader emits a loud `RuntimeWarning` (or hard fail, configurable) when `len(validated) < len(prior_iter_validated)`. Still overwrites. | ~10 LOC | Visibility on loss vectors 1 + 2. Operator gets a signal but no structural fix. |
| **B. Additive merge** *(recommended)* | Loader takes a **union across all parseable iter digests**. Latest-wins for `kind` / promotion fields on duplicate name; `seen_in_runs` is set-union. | ~30 LOC + 4-case unit test | True hard monotonicity for the read path. Backward-compatible (every existing digest already contains the full cumulative state). Trade-off: a once-promoted entry that the LLM intended to demote can no longer be removed via a single iter — must be done explicitly. Acceptable. |
| **C. Append-only ledger** | New `vocab_ledger.jsonl` at workspace root: every term-creation, every promotion, every link-confirmation appends a row. Reader replays the ledger to reconstruct vocab; iter digests become *projections*, not source-of-truth. | ~80 LOC + schema + migration | Bulletproof provenance. Aligns with the "negative memory counts: success and failure are both wealth" framing — failures can be ledger-recorded too. Over-engineered until measured loss; recommend deferring until tier B is in production and observed. |

**Recommendation**: ship **Tier B** as a sibling closure to §10 (G1).
It is the smallest change that converts soft monotonicity to hard
monotonicity. Tier A is a half-measure that still trusts the writer;
Tier C buys provenance richness we don't yet need.

### 11.5 Tier-B Bridge Plan (if approved)

Single change in `core/resume.py:load_latest_knowledge`:

Replace the per-iter overwrite block (lines 296–310) with an additive
merge:

```python
# Additive merge: union across all parseable iter digests.
# Latest-wins on duplicate `name` for kind/related_to/sources;
# seen_in_runs is set-union (preserves run lineage even if a later
# iter's digest accidentally drops it).
raw_vocab = data.get("runtime_vocab") or []
for entry in raw_vocab:
    try:
        new_entry = VocabEntry.model_validate(entry)
    except Exception as e:
        warnings.warn(
            f"[resume] iter {iter_idx:03d}: dropped malformed "
            f"runtime_vocab entry {entry!r}: {e}",
            UserWarning, stacklevel=2,
        )
        continue
    name = new_entry.name
    if name in vocab_by_name:
        prior = vocab_by_name[name]
        merged_runs = list(dict.fromkeys(
            prior.seen_in_runs + new_entry.seen_in_runs
        ))
        # latest fields win, but seen_in_runs is union
        vocab_by_name[name] = new_entry.model_copy(
            update={"seen_in_runs": merged_runs}
        )
    else:
        vocab_by_name[name] = new_entry
```

Where `vocab_by_name: Dict[str, VocabEntry] = {}` is initialised once
before the iter loop. Final return becomes
`list(vocab_by_name.values()), findings`.

**Verification contract**:

1. Unit — synthetic 3-iter workspace where iter-2's digest is missing
   entry `B` that iter-1 had. Assert merged result contains both
   `A`, `B` (from iter-1), and any iter-2-only / iter-3-only entries.
2. Unit — `seen_in_runs` set-union: iter-1 has `foo` with
   `seen_in_runs=['iter_001']`, iter-2 has `foo` with
   `seen_in_runs=['iter_002']`. Assert merged `foo.seen_in_runs ==
   ['iter_001', 'iter_002']` (order preserved, no dupes).
3. Unit — empty iter-2 digest does not erase iter-1 entries (regression
   guard for the existing line-309 protection — Tier B preserves it
   structurally).
4. Integration — replay a real V8 workspace (e.g.
   `exploration_explore_novel_v8_0430` iters 1–7) under both old and
   new readers. Assert new reader's vocab is a *superset* of old
   reader's (proves no regression on real data).

**Forward-compat with §10 (G1)**: independent. §10 fixes the candidate
*intake* channel (proposer → interp); §11 Tier B fixes the vocab
*restore* channel (disk → next iter). Either can ship first; both
together close the long-term-memory hole completely.

### 11.6 Open questions for the operator

Two design calls before tier B is implemented — flagged here so they
are not silently decided in the code:

1. **Kind conflicts.** If iter-2 has `foo` as `kind='candidate'` and
   iter-3 has `foo` as `kind='capability'` (promoted), the proposed
   merge takes iter-3's kind (latest-wins on non-`seen_in_runs`
   fields). This matches today's intent (promotion is monotonic
   forward). But what if a *demotion* is ever needed? Today: not
   supported. Tier B preserves that. Confirm acceptable.
2. **Cross-iter `related_to` accumulation.** Should `related_to` also
   be set-union (like `seen_in_runs`), or latest-wins? The
   `update_vocab_link_confirmations` writer is itself additive on
   `related_to`, so latest-wins is functionally equivalent in normal
   operation. Recommend latest-wins for simplicity; revisit if a real
   loss is observed.

---

## 12. Vocab Ancestry Observability

**Concern raised**: long-term memory must not just exist "under the hood"
— in iter N we need to *see* exactly which terms were inherited from
iters 1..N-1, when each term was first mentioned, and what was newly
introduced. The audit trail must answer questions like *"a term
proposed in iter 5 — was it first mentioned in iter 2?"* by reading
`workflow_log` or `evolution_log.jsonl`, without parsing every digest
by hand.

**Direct answer**: the *data* required for ancestry already exists in
master (`VocabEntry.seen_in_runs` is a per-term run-list — the first
entry IS the first-seen iter). The *presentation* does not. Today's
logs surface only **counts**, not **names** or **lineage**. Closing
this is an instrumentation extension to existing writers, not a new
storage surface.

### 12.1 What observability exists today (audit)

Three writers contribute to vocab observability:

| Surface | What it records | Path |
|---|---|---|
| `evolution_log.jsonl` (chain root, append-only) | one row per iter: `{timestamp, iteration, evolution_stats: {vocab_total, vocab_canonical, vocab_candidate, promoted_this_iter, is_degraded}, best_score_so_far, take_home_message}` | written by `_append_evolution_log` at `nodes/result_interpretation_agent.py:1045, 1114` |
| `interpretation_iter_NNN.json` (per-iter digest) | full `runtime_vocab: List[VocabEntry]` with per-entry `seen_in_runs: List[str]` | written by `ResultInterpretationAgent.run` storage |
| `workflow_log` / stdout | one-line print on candidate addition/promotion at `nodes/result_interpretation_agent.py:910-915` | console only — not persisted as structured data |

What this gives you today, in iter N's row of `evolution_log.jsonl`:
- vocab **counts** (total / canonical / candidate / promoted-this-iter)
- a free-text `take_home_message` from the LLM
- the best score so far

What you cannot answer from the log alone:
1. *Which* terms are in this iter's vocab.
2. *When* a given term first appeared in the chain.
3. *Which* terms were introduced in this iter vs. inherited from earlier.
4. *What* the LLM is actually building on across iters (the iter→iter
   continuity story).

To answer any of (1)–(4) today, an operator must open every
`interpretation_iter_NNN.json` digest and diff `runtime_vocab` lists
by hand.

### 12.2 The data you need is already there

Every `VocabEntry` carries:
- `name: str` — the canonical identifier.
- `kind: str` — `'canonical'` / `'candidate'` / promoted variants.
- `seen_in_runs: List[str]` — chronological list of run identifiers in
  which the term has been proposed or discovered. **The first element
  is the first-seen iter; the last element is the most recent
  appearance; the length is the promotion-threshold counter.**

`build_runtime_vocab` (`nodes/interpretation_helpers.py:380-399`)
appends to `seen_in_runs` whenever a candidate re-appears, dedup'd —
so the list IS the ancestry record per term. We just don't surface it
in any aggregate view.

This means the instrumentation plan does not require any new schema
on `VocabEntry`, no new write site, no new persistence surface. It is
a pure read-and-format pass over the existing `runtime_vocab` and the
prior iter's restored vocab.

### 12.3 Instrumentation Plan — three layers

Three layers, increasing in operator-friendliness:

#### 12.3.1 Layer 1 — enrich `evolution_log.jsonl` rows (machine-readable)

Extend the `evolution_stats` block at
`nodes/result_interpretation_agent.py:_compute_evolution_stats` (line
500) with three new keys per iter:

```json
{
  "vocab_inherited": [
    {"name": "low_band_calibration", "kind": "canonical",
     "first_seen": "iter_001", "seen_in_n_runs": 5},
    {"name": "spectral_envelope_match", "kind": "candidate",
     "first_seen": "iter_002", "seen_in_n_runs": 2}
  ],
  "vocab_introduced_this_iter": [
    {"name": "phase_locked_residual", "kind": "candidate",
     "source": "proposer_candidate"}
  ],
  "vocab_promoted_this_iter": [
    {"name": "harmonic_leakage", "from_kind": "candidate",
     "to_kind": "canonical", "seen_in_runs":
     ["iter_002","iter_004","iter_005"]}
  ]
}
```

**Computation** (no new I/O, all in-memory in the interp agent):
- `inherited` = entries in `runtime_vocab` whose `seen_in_runs[0] !=
  current_run_name`. The `first_seen` value is `seen_in_runs[0]`;
  `seen_in_n_runs` is `len(seen_in_runs)`.
- `introduced_this_iter` = entries whose `seen_in_runs[0] ==
  current_run_name`. `source` = `"interp_new_discovery"` if the entry
  came from `new_discoveries`, else `"proposer_candidate"`.
- `promoted_this_iter` = the existing `promoted_names` list (already
  computed at line 992) annotated with from/to kind and the run list.

**Cost**: ~25 LOC inside `_compute_evolution_stats`, no new helpers,
no new schema surfaces.

#### 12.3.2 Layer 2 — `vocab_ancestry.md` (human-readable, regenerated each iter)

A markdown snapshot written at `{workspace}/vocab_ancestry.md` after
each iter's interp digest. Overwrites prior iter's file. Three
sections:

```markdown
# Vocab Ancestry — chain at iter 005 (2026-05-02T14:30Z)

## Canonical (23)
| name | first seen | last seen | runs | promoted at |
|---|---|---|---|---|
| low_band_calibration | iter_001 | iter_005 | 5 | iter_003 |
| harmonic_leakage     | iter_002 | iter_005 | 3 | iter_005 |
| ...                  | ...      | ...      | ..| ...     |

## Candidate watch list (4)
| name | first seen | seen in | runs to promotion |
|---|---|---|---|
| spectral_envelope_match | iter_002 | iter_002,iter_004 | 1 more |
| ...                     | ...      | ...                | ...    |

## New this iter (2)
| name | kind | source |
|---|---|---|
| phase_locked_residual | candidate | proposer_candidate |
| transient_burst_gate  | candidate | interp_new_discovery |
```

This is the at-a-glance view you would open mid-chain to see
"is the vocab evolving reasonably?".

**Cost**: ~40 LOC for the renderer + one call site at end-of-interp.

#### 12.3.3 Layer 3 — workflow_log per-iter summary (stdout, persisted via tee)

One structured block printed at the end of each iter's interp run, so
the live `tail -f workflow_log.txt` operator sees inheritance without
opening any file:

```
[iter 005 | vocab inheritance]
  Inherited: 23 entries (22 canonical, 1 candidate)
    Oldest still active: low_band_calibration (iter_001, 5 runs)
    Most recent inheritance: harmonic_leakage (iter_004, 2 runs)
  Introduced this iter: 2 candidates
    phase_locked_residual (proposer_candidate)
    transient_burst_gate  (interp_new_discovery)
  Promoted this iter: 1
    harmonic_leakage: candidate -> canonical (seen in iter_002, iter_004, iter_005)
```

The format is operator-readable, deterministic, and parseable — the
strings can be regex-grepped from `workflow_log.txt` for offline
analysis.

**Cost**: ~15 LOC, single helper called from the interp agent's
existing iter-completion print block.

### 12.4 Verification Contract

#### 12.4.1 Unit (synthetic, deterministic)

Three-iter synthetic chain:
- iter 1 introduces `A`, `B`, `C`.
- iter 2 inherits `A`, `B`, `C`; introduces `D`; re-mentions `A`.
- iter 3 inherits all four; promotes `A` (3rd run); introduces `E`.

Assertions on iter 3's `evolution_log.jsonl` row:
1. `vocab_inherited` contains 4 entries: `A`, `B`, `C`, `D` with
   `first_seen` of `iter_001`, `iter_001`, `iter_001`, `iter_002`.
2. `A.seen_in_n_runs == 3`.
3. `vocab_introduced_this_iter == [{name: "E", ...}]`.
4. `vocab_promoted_this_iter == [{name: "A", from: "candidate", to:
   "canonical", seen_in_runs: ["iter_001","iter_002","iter_003"]}]`.

#### 12.4.2 Integration (real V8 workspace replay)

Replay an existing V8 workspace (e.g.
`exploration_explore_novel_v8_0430` iters 1–7) under the
instrumented interp agent. Assert:
- iter-7's `evolution_log` row's `vocab_inherited` matches the union
  of iters 1–6's persisted vocab minus same-name overwrites.
- `vocab_ancestry.md` renders without crash on a real digest set.
- The workflow_log summary block appears once per iter, with
  consistent counts vs. the JSON row.

#### 12.4.3 Operator smoke

After §12 lands, on a 3-iter chain run, the operator should be able to
answer all four questions from §12.1 using *only* `evolution_log.jsonl`
+ `vocab_ancestry.md` — no per-iter digest opens. This is the human-
in-the-loop acceptance test.

### 12.5 Commit Strategy

| # | Scope | Tests run |
|---|---|---|
| 1 | Layer 1 — `_compute_evolution_stats` enrichment + schema bump on `evolution_stats` field docstring | unit (synthetic 3-iter) |
| 2 | Layer 2 — `vocab_ancestry.md` renderer + write call at end of interp run | unit (renderer fixture) |
| 3 | Layer 3 — workflow_log summary block | smoke (capture stdout, regex-grep) |
| 4 | Integration — real V8 replay test | full Tier 3 |
| 5 | Doc closeout — flip §12 checklist | n/a |

### 12.6 Coordination with §10 + §11

§12 is the **observability layer**; §10 and §11 are the **correctness
layers**. They are independent in code but coupled in operational
value:

- **Without §10 (G1 fix)**: `vocab_introduced_this_iter` of source
  `proposer_candidate` will appear empty across chain iters because
  the proposer's candidates never reach the interp agent. §12 would
  faithfully report the dark channel — accurate, but the dashboard
  would be a "this is broken" indicator. So §12 acquires its full
  signal value only after §10 lands.
- **Without §11 Tier B (hard monotonicity)**: an iter where the LLM
  regresses the digest will silently shrink `vocab_inherited` in the
  next row. §12 would expose the shrink (loud signal that ancestry
  is being lost), which is itself useful — but the underlying loss
  remains.
- **With all three**: §10 re-opens the candidate intake; §11 Tier B
  guarantees the lineage cannot shrink; §12 makes the lineage
  visible and queryable. Together they convert long-term memory
  from "implicit and fragile" to "explicit and durable".

**Recommended ordering**: §10 → §11 Tier B → §12. §12 alone is
observability theatre on a broken pipe; §10+§11 alone are silent
correctness. Ship in order.

### 12.7 Checklist

- [ ] §12.3.1 Layer 1 — `evolution_stats` enriched with three new keys
- [ ] `_compute_evolution_stats` signature accepts prior-iter context
- [ ] §12.3.2 Layer 2 — `vocab_ancestry.md` renderer + write call
- [ ] §12.3.3 Layer 3 — workflow_log summary block
- [ ] §12.4.1 unit (synthetic 3-iter) passes
- [ ] §12.4.2 integration (V8 replay) passes
- [ ] §12.4.3 operator smoke — four questions answerable from logs

### 12.8 Risks (post-merge watch)

1. **Log size growth.** `vocab_inherited` is a per-iter snapshot of all
   inherited entries; in a 30-iter chain with 100 vocab entries, each
   row carries ~100 inherited records. Per-row size ~10 KB → 300 KB
   total log. Acceptable. If it bites in longer chains, switch
   `vocab_inherited` to a delta (entries new since last iter only) and
   leave the full list in `vocab_ancestry.md`.
2. **`first_seen` is a derived field.** It's `seen_in_runs[0]`. If
   §11 Tier B's set-union ever reorders `seen_in_runs` (e.g. sorted
   not chronological), `first_seen` becomes meaningless. Guard:
   §11 Tier B's docstring must specify "chronological order
   preserved, no sort". The unit test at §11.4 case 2 already
   asserts order preservation.
3. **`vocab_ancestry.md` overwrite vs. append.** Overwriting each iter
   loses prior snapshots — but `evolution_log.jsonl` is the durable
   append-only record. The MD file is a *latest-snapshot
   convenience*, not a replacement for the log. Documented in §12.3.2.
4. **Cosmetic divergence between Layer 1 and Layer 3.** If the JSON
   row and the workflow_log summary disagree on counts, the operator
   has no way to tell which is right. Mitigation: both call the same
   `_compute_evolution_stats` payload — Layer 3 is a renderer of
   Layer 1's data, never an independent computation.

---

## 13. Vocab Growth Rate Estimate (20-iter chain)

**Purpose**: pre-§10 baseline for *what to expect* from a 20-iter
chain so that an operator inspecting `evolution_log.jsonl` mid-run
can tell "growth is reasonable" from "growth is broken". This is
not a target, it is a sanity band.

**Confidence**: low-to-medium. The candidate-count-per-iter is
empirically anchored; everything downstream involves LLM-mood
variance the design doc cannot pin down without longer chains.
Treat all cumulative numbers in this section as ±50 %.

### 13.1 Empirical Anchor (real V8 data)

Sampled iters 1, 3, 5, 7 of
`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v8_0430`
(2026-04-30 → 2026-05-01):

| iter | candidates | links | candidate names |
|---|---|---|---|
| 1 | 2 | 6 | `cropped_skip_alignment`, `full_scale_positional_injection` |
| 3 | 3 | 6 | `same_padding_temporal_conv`, `bounded_spectral_fusion`, `score_calibration` |
| 5 | 3 | 6 | `same_padding_temporal_conv`, `bounded_spectral_fusion`, `cross_band_calibration` |
| 7 | 3 | 6 | `band_calibration_head`, `bounded_spectral_gate`, `broadband_calibration` |

Two stable signals:
1. **Per-iter candidate count is tight: 2–3.** The proposer's natural
   output rate under the current prompt budget. No iter sampled has
   exceeded 3 candidates.
2. **Theme recurrence is real.** Iter-3 and iter-5 share two
   candidate names verbatim (`same_padding_temporal_conv`,
   `bounded_spectral_fusion`). Iter-7 shifts naming
   (`bounded_spectral_gate`) but the underlying physics motif
   ("bounded spectral / band-calibration") recurs across iters 3, 5,
   7. This is exactly the signal `seen_in_runs ≥ 3` is designed to
   graduate.

Seed size: 21 entries (`agent/schemas/vocab_seed.json`).

### 13.2 Today (master, chain mode, G1 dark)

**Empirically observed: zero growth.** Every row of the live V8
`evolution_log.jsonl` shows `vocab_total: 21, vocab_canonical: 21,
vocab_candidate: 0` — across all 7+ committed iters of the explore
chain. The G1 short-circuit (§10.1) means the proposer's 2–3
candidates per iter never enter `runtime_vocab`, and the
`new_discoveries` channel has not fired in the inspected iters
either.

**Confidence**: high. Backed by direct log inspection.

So if you start a 20-iter chain on master today, the expected vocab
trajectory is the flat line `vocab_total = 21` for every iter.

### 13.3 Post-§10 Estimate (G1 closed)

Order-of-magnitude bands for a 20-iter chain after §10 lands:

| Quantity | Per-iter (steady state) | Cumulative after 20 iters |
|---|---|---|
| Candidates proposed (with dupes) | 2–3 | 40–60 |
| **Unique** candidate names (post-dedup) | ~1–2 net new | **20–35** |
| Candidates crossing `seen_in_runs ≥ 3` (promoted) | 0–1 | **5–15** |
| `new_discoveries` from interp (unique) | 0–2 | **5–25** |
| **`vocab_total`** | +1 to +3 net per iter | **~45–75** (21 seed + ~25–55 acquired) |
| **`vocab_canonical`** | rises slowly | **~30–50** (21 seed + 10–30 promoted) |
| **`vocab_candidate`** (active watch list) | drifts up | **~10–25** |

### 13.4 Variance Drivers (in rough order of impact)

1. **Theme persistence.** If the LLM keeps returning to the same
   physics motifs across iters, promotions accelerate. The iter-3 ↔
   iter-5 overlap suggests recurrence is real but not dominant;
   rough estimate ~30–50 % candidate-name recurrence after dedup.
2. **Run-name reuse.** `seen_in_runs` is keyed on the proposer's
   `proposed_by_run` field, which today is the `model_type`. If two
   iters propose architectures with similar `model_type` names,
   increments are artificially fast (and possibly inflated). Worth
   confirming convention before treating promotion counts as
   physics signal.
3. **`new_discoveries` channel mood.** Pure LLM-emitted via the
   interp agent. The PR #66 prompt rewrite (Phase-8 cognitive
   alignment) was meant to bias toward discovery emission; live V8
   has not shown any yet. Could be 0/iter or 2/iter — no live
   anchor. This is the highest-variance row.
4. **Prompt pressure.** As `accumulated_key_findings` grows
   (uncapped today — §9.5 G4), the proposer LLM may emit
   fewer / shorter candidates in late iters to fit context, and
   "Attention Decay" against a 100-bullet block degrades the
   relevance of any single finding. Would suppress late-chain
   growth. Mitigated by **§14's two-bucket retention policy**.
5. **Chain length crossing the threshold.** Promotion needs ≥ 3
   appearances. Even with steady recurrence, the *first* promotion
   cannot fire before iter 3, and a candidate first proposed at
   iter 18 cannot reach 3 runs in a 20-iter chain. So the back end
   of the chain produces zero promotions for late-introduced
   candidates.

### 13.5 Per-Iter Operational Sanity Bands

What an operator should expect to see in `evolution_log.jsonl` at
specific milestones (post-§10 + §12):

| At iter | Expected `vocab_total` | Expected `promoted_this_iter` (cumulative) |
|---|---|---|
| 1 | 22–24 | 0 |
| 5 | 26–32 | 0–2 |
| 10 | 33–45 | 2–8 |
| 15 | 40–60 | 4–12 |
| 20 | 45–75 | 5–15 |

**Red flags** (suggest a regression worth investigating):
- `vocab_total` flat across 3 consecutive iters → either G1 still
  open in some path, or LLM has stopped proposing novel candidates.
- `vocab_total` shrinks across an iter → §11 loss vector (likely
  vector 1 or 2). With Tier B in place this should be impossible.
- `promoted_this_iter == 0` cumulatively past iter 10 → recurrence
  rate is below estimate, or `proposed_by_run` keying is breaking
  dedup. Worth sampling several `seen_in_runs` lists by hand.

### 13.6 Confidence Ratings

| Number | Confidence | Why |
|---|---|---|
| Seed = 21 | high | measured (`vocab_seed.json`) |
| 2–3 candidates / iter | high | 4 measured iters all in band |
| 30–50 % theme recurrence | medium-low | 1 sampled overlap pair |
| Total `vocab_total` ~45–75 after 20 iters | low | depends compoundly on recurrence + new_discoveries + prompt-pressure decay |
| Promoted ~5–15 after 20 iters | low | depends on recurrence rate AND chain length AND keying convention |
| `new_discoveries` 5–25 after 20 iters | very low | no live anchor — channel hasn't fired in the inspected workspace |

### 13.7 Calibration Plan

This section is meant to be *updated*, not preserved. After the
first real chain run with §10 + §12 in place:

1. Re-sample candidate counts per iter from `evolution_log.jsonl`
   (now structured per §12.3.1).
2. Re-derive theme-recurrence rate from `seen_in_runs` distributions
   in iter-N's `vocab_inherited` block.
3. Compare measured `vocab_total` trajectory vs. §13.5's bands;
   tighten the bands if measurement is consistently in one half of
   the range.
4. Update §13.6 confidence ratings based on what was actually
   variable vs. predictable.

Goal: by the third real 20-iter chain post-§10, this section should
read with **medium-high confidence** rather than the current
**low**.

---

## 14. G4 — Key-Findings Retention Policy (Focus Without Amnesia)

§9.5 raised G4 (`accumulated_key_findings` is unbounded). §9.6.3
proposed a single `_MAX_ACCUMULATED_KEY_FINDINGS` constant plus a
trailing-slice trim mirroring the rejections / gate-exhaustions
caps. On a second pass, that simple cap is the wrong shape for
findings — it would cause exactly the failure the operator named
("blind truncation" → loss of long-term milestones). This section
supersedes §9.6.3 and specifies a two-bucket retention model with
a Pydantic `FindingsRetentionPolicy` config so the trade-off
between **focus** (bounded prompt size, attention preserved per
bullet) and **continuity** (long-term milestones never silently
evicted) is explicit, parameterised, and unit-testable.

### 14.1 Why a Naïve Cap Fails

The §9.6.3 proposal was: keep only the last K iters' findings,
drop the rest. Its rationale was symmetry with the trailing-slice
already in place for `accumulated_physical_rejections` and
`accumulated_gate_exhaustions` at `core/resume.py:455-464`. That
symmetry breaks down once you look at the *kind* of information
each channel carries:

| Channel | Staleness | What older entries tell the proposer |
|---|---|---|
| `accumulated_physical_rejections` | high — older rejections describe budgets/architectures the chain has already moved past | "this combo OOM'd back when we tried it" — useful only while the relevant arch is still on the table |
| `accumulated_gate_exhaustions` | high — same reason | "this iter aborted on the same warmup wall" — actionable only against the current generation |
| `accumulated_key_findings` | **mixed** — some bullets are perishable iter-N observations; others are durable architectural milestones ("`bounded_spectral_fusion` consistently beats baseline by ≥1 nat", "input-padding asymmetry capped iter-3 across all four arches") | mixture: the durable ones are exactly the kind of long-term IP §10 is also trying to protect |

A trailing-slice over a mixed-staleness channel evicts the
durable items along with the perishable ones — that is "blind
truncation" by definition. Three concrete failure modes:

1. **Anchor erosion** — the iter-1 baseline finding (often the
   single most-cited observation in the entire chain) gets
   evicted at iter K+1 even though every subsequent iter has
   compared itself against it implicitly.
2. **Promotion-event loss** — a finding describing the moment a
   candidate vocab term graduated to canonical (e.g. "iter 4:
   `bounded_spectral_fusion` confirmed across all 3 architectures
   that proposed it") is exactly the kind of structural milestone
   the §10 vocab channel is trying to make load-bearing. Naïve
   FIFO drops it once the chain moves past iter K + 4.
3. **Attention decay without focus** — even if the cap is set
   high (e.g. K=20, ~100 bullets), the proposer LLM has to read
   100 bullets per iter. Attention decay against a flat list of
   100 bullets is a measured behaviour, and it is independent of
   whether the bullets are "kept": a 100-bullet prompt with all
   recent findings is no better than a 100-bullet prompt with all
   ancient findings — both bury the relevant signal.

The right answer is not "keep more" or "keep fewer" — it is
**curate**.

### 14.2 The Two-Bucket Retention Model

The retention policy partitions findings into two buckets and
gives each a separate budget:

```
                                    max_total = recent_budget + milestone_budget
                                                       (e.g. 60     = 30        + 30)

      iter 1 ─── iter K-W-1 │ iter K-W ─── iter K (current) ──→
      ┌─────────────────────┤├──────────────────────────────┐
      │  Bucket B           ││  Bucket A (recency window)   │
      │  Milestone reservoir││  ALL findings kept,          │
      │  Top-M by importance││  no scoring, no eviction     │
      │  score (older iters)││  (last W iters)              │
      └─────────────────────┘└──────────────────────────────┘
```

- **Bucket A — recency window**: every finding from the last `W`
  iters is kept verbatim, regardless of importance score.
  Guarantees no recent-information loss; the proposer always sees
  the most up-to-date reflection state.
- **Bucket B — milestone reservoir**: from older iters, keep the
  top `M = max_total − len(A)` findings ranked by an importance
  score (§14.3). Guarantees long-term milestones survive even
  when many iters have elapsed.

When `len(A)` exceeds `max_total` (i.e. the recency window alone
saturates the budget), bucket A is itself trimmed by recency
(newest iter wins) and bucket B is empty for that frame. This is
the only situation in which a "drop" can happen to the recent
window, and it is bounded by `max_total` — predictable.

The merged output is sorted **chronologically** before being
flattened into the proposer prompt, so the LLM still reads
findings in temporal order (preserves narrative coherence; "iter
3 noted X, iter 7 then refined to Y" reads naturally).

### 14.3 Importance-Scoring Heuristic (No Schema Migration)

Bucket B's ranking is the load-bearing part of the policy. Three
signals are available *without* changing the
`InterpretationOutput.key_findings: List[str]` schema:

1. **Position-within-iter rank.** The interp-agent prompt at
   `nodes/result_interpretation_agent.py:107` already instructs
   the LLM to emit findings *ranked by importance, evidence-based,
   reference actual values*. So index 0 within an iter's
   `key_findings` list is, by contract, more important than
   index 1, etc. Score: `rank_decay ** position` where
   `rank_decay ∈ [0,1]`, default 0.7. Position-0 score = 1.0;
   position-2 score = 0.49.

2. **Cross-iter recurrence.** Findings whose text contains the
   same key noun phrase across multiple iters are stable
   consensus, not iter-N noise. Approximated by case-folded
   substring overlap on the noun-phrase prefix (first 8 tokens),
   not full-text equality (LLMs paraphrase). Score boost:
   `recurrence_weight × log(1 + n_iters_seen)`, default
   `recurrence_weight = 0.5`. A finding seen in 3 iters gets
   `0.5 × log(4) ≈ 0.69` added.

3. **Vocab-mention boost.** Findings whose text mentions a
   canonical or candidate vocab name are structurally coupled to
   the long-term IP §10/§11 are protecting. Resolved against the
   current `runtime_vocab` (already in scope at
   `load_latest_knowledge`'s caller). Score boost:
   `vocab_mention_weight × min(n_mentions, 3)`, default
   `vocab_mention_weight = 0.3`. A finding citing two vocab terms
   gets `0.3 × 2 = 0.6` added.

Final importance score for a finding at iter `i`, position `p`:

```
score(finding) = (rank_decay ** p)                              # base
               + recurrence_weight * log(1 + n_iters_seen)      # consensus signal
               + vocab_mention_weight * min(vocab_mentions, 3)  # structural signal
```

The numerical constants are config (§14.4), not magic numbers.
Default values give: a position-0 finding mentioning two vocab
terms and seen in 3 iters scores `1.0 + 0.69 + 0.6 = 2.29`,
versus a position-3, no-vocab, no-recurrence finding scoring
`0.7³ ≈ 0.34` — a ~6.7× separation, plenty of dynamic range for
top-M selection.

**Why heuristic and not LLM-scored.** A separate LLM pass to
re-rank findings would (a) add a deterministic-budget cost per
chain iter and (b) introduce a second source of LLM
non-determinism into a path that today is deterministic. The
heuristic is good enough for budgeting (we don't need the *true*
top-M, we need a *reasonable* top-M — the proposer LLM does the
real synthesis on the surviving set). If §14.5 Phase 2 is later
adopted, the LLM emits importance directly via schema, and the
heuristic becomes the fallback.

### 14.4 Schema Spec — `FindingsRetentionPolicy` (Pydantic)

New module-level constant block in `core/resume.py`, replacing
the §9.6.3 `_MAX_ACCUMULATED_KEY_FINDINGS` plan:

```python
# core/resume.py — alongside _MAX_ACCUMULATED_REJECTIONS

class FindingsRetentionPolicy(BaseModel):
    """Two-bucket retention policy for accumulated_key_findings.

    Partitions findings across chain iters into a recency window
    (always kept) and a milestone reservoir (top-M by importance
    score). See docs/Consistent_growing_vocab_list.md §14.

    Validated at construction — total budget must cover at least
    the recency window's expected size, otherwise the recency
    bucket would saturate and the milestone bucket would always
    be empty (silently degrading to a recency-only policy, which
    is the failure mode §14.1 calls out).
    """
    max_total: int = Field(
        60, ge=10, le=500,
        description="Hard ceiling on bullets surfaced to the proposer.",
    )
    recent_window_iters: int = Field(
        5, ge=1, le=50,
        description="Iters whose findings are always kept verbatim.",
    )
    rank_decay: float = Field(
        0.7, ge=0.1, le=1.0,
        description="Geometric decay applied to within-iter rank "
                    "(0.7 ≈ position 3 worth half of position 0).",
    )
    enable_recurrence_boost: bool = True
    recurrence_weight: float = Field(0.5, ge=0.0, le=2.0)
    enable_vocab_mention_boost: bool = True
    vocab_mention_weight: float = Field(0.3, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def _budget_covers_recency(self) -> "FindingsRetentionPolicy":
        # Assume ~5 findings/iter (Phase-2 prompt instructs ranked
        # bullets — empirically 4-7 in current V8 chains). If the
        # total budget can't cover even the recency window, the
        # milestone bucket is permanently empty and the policy
        # collapses to plain trailing-slice — the §14.1 failure.
        expected_recency_size = self.recent_window_iters * 5
        if self.max_total < expected_recency_size:
            warnings.warn(
                f"FindingsRetentionPolicy: max_total={self.max_total} "
                f"< expected recency size={expected_recency_size} "
                f"(recent_window_iters * 5). Milestone bucket will "
                f"likely be empty; consider raising max_total or "
                f"reducing recent_window_iters.",
                stacklevel=2,
            )
        return self


# Module-level default (overridable at run_workflow call site if
# we later expose a CLI flag; for now, defaults serve every
# current chain).
_DEFAULT_FINDINGS_RETENTION = FindingsRetentionPolicy()
```

Why Pydantic and not a plain dict / namedtuple: per CLAUDE.md
"Never pass raw config without Pydantic validation", and the
budget-coverage validator is exactly the kind of cross-field
constraint that catches operator misconfiguration at construction
time rather than at the K=12-iter mark when bucket B silently
empties out.

### 14.5 Loader Algorithm — `load_latest_knowledge` Extension

Today, `core/resume.py` accumulates findings as a flat
`List[str]` with chronological dedup-by-string. The retention
policy needs per-finding metadata — at minimum `(iter_origin,
position_within_iter)` — so the internal collection switches to
`List[tuple[int, int, str]]` (iter, position, text) for the
duration of `load_latest_knowledge`, then flattens to
`List[str]` on return.

Pseudocode (replaces the loop body around `core/resume.py:291-294`):

```python
# 1. Collect with metadata, preserving iter + position
collected: list[tuple[int, int, str]] = []
seen_text: set[str] = set()
for iter_idx in committed_iters:
    digest = _read_interpretation_digest(workspace, iter_idx)
    if not digest:
        continue
    for pos, kf in enumerate(digest.get("key_findings") or []):
        if isinstance(kf, str) and kf and kf not in seen_text:
            collected.append((iter_idx, pos, kf))
            seen_text.add(kf)

# 2. Apply two-bucket retention
retained = _apply_findings_retention(
    collected,
    current_iter=current_iter,
    runtime_vocab=runtime_vocab,    # already loaded earlier in this fn
    policy=_DEFAULT_FINDINGS_RETENTION,
)

# 3. Flatten to List[str], chronological order preserved
return [text for (_, _, text) in retained]
```

The `_apply_findings_retention` helper:

```python
def _apply_findings_retention(
    items: list[tuple[int, int, str]],
    *,
    current_iter: int,
    runtime_vocab: list[VocabEntry],
    policy: FindingsRetentionPolicy,
) -> list[tuple[int, int, str]]:
    """Apply two-bucket retention. Returns chronologically ordered."""
    if len(items) <= policy.max_total:
        return items  # under budget; no eviction

    recency_floor = current_iter - policy.recent_window_iters
    bucket_a = [t for t in items if t[0] > recency_floor]
    bucket_b = [t for t in items if t[0] <= recency_floor]

    if len(bucket_a) >= policy.max_total:
        # Recency window already saturates — keep newest, drop B
        bucket_a.sort(key=lambda t: (t[0], t[1]), reverse=True)
        retained = bucket_a[:policy.max_total]
    else:
        milestone_budget = policy.max_total - len(bucket_a)
        vocab_names = {v.name.lower() for v in runtime_vocab}
        recurrence_counts = _count_recurrence_prefixes(items)
        bucket_b.sort(
            key=lambda t: _importance_score(
                t, policy, vocab_names, recurrence_counts,
            ),
            reverse=True,
        )
        retained = bucket_a + bucket_b[:milestone_budget]

    # Sort chronologically for the proposer narrative
    retained.sort(key=lambda t: (t[0], t[1]))
    return retained
```

Both `_count_recurrence_prefixes` and `_importance_score` are
pure functions — straightforward to unit-test (§14.7).

### 14.6 Surface in Proposer Prompt (Transparency)

Today's `ExpertContextItem` block at
`workflows/model_exploration.py:957-983` is opaque — the LLM has
no way to know whether it's seeing all history or a curated
subset. With retention active, the header should disclose what
was filtered, so a proposer LLM that needs more context can
caveat its proposal accordingly.

Patch to the existing block:

```python
# workflows/model_exploration.py — replaces lines 958-979 content block
if accumulated_key_findings:
    n_total = retention_stats["n_total"]    # NEW: returned by loader
    n_kept  = retention_stats["n_kept"]
    n_recent = retention_stats["n_recent"]
    n_milestones = retention_stats["n_milestones"]
    bullet_block = "\n".join(f"- {kf}" for kf in accumulated_key_findings)
    header = (
        f"Accumulated key findings from {len(committed_iters)} prior iter(s).\n"
        f"Showing {n_kept} of {n_total} total ({n_recent} from the last "
        f"{policy.recent_window_iters} iters + {n_milestones} milestones "
        f"from earlier iters by importance score). Older non-milestone "
        f"findings have been retained in their iter's interpretation "
        f"digest on disk but suppressed from this prompt to preserve "
        f"focus.\n"
    )
    expert_context_for_propose.append(
        ExpertContextItem(
            source="prior_iters",
            kind="findings",
            content=header + bullet_block,
            cite_id="prior_iters_key_findings",
        )
    )
```

Two design notes on the header:

- **"Retained on disk"** — the original findings remain in each
  iter's `interpretation_iter_NNN.json` digest; the policy only
  filters what's surfaced to the proposer. No data is destroyed.
  The §11 monotonicity guarantee on `runtime_vocab` is unaffected
  (vocab and findings are independent channels).
- **"Preserve focus"** — explicit acknowledgement of the attention-
  decay trade-off so the LLM understands why filtering happened.

The retention stats are also logged at restore time:

```
[resume] knowledge carry-over: 21 vocab entries, 47 → 32 key findings
         (retention: 15 recent, 17 milestones, 15 suppressed).
```

### 14.7 Verification Contract

#### 14.7.1 Unit (synthetic, deterministic) — `tests/unit/core/test_resume.py`

```
test_retention_under_budget_no_eviction
test_retention_recency_only_when_recent_saturates
test_retention_two_bucket_split_at_W_boundary
test_retention_milestone_ordering_by_score
test_retention_chronological_output_order
test_recurrence_boost_promotes_repeated_finding
test_vocab_mention_boost_promotes_vocab_finding
test_position_rank_decay_orders_within_iter
test_retention_policy_validator_warns_on_undersized_budget
test_retention_policy_invalid_field_ranges_rejected
```

Each test constructs a synthetic `List[tuple[int, int, str]]`
and asserts the post-retention list matches the expected slice.
No filesystem, no real workspace — pure function tests.

#### 14.7.2 Integration (real V8 workspace replay)

Extend `tests/unit/core/test_resume.py` (still synthetic, but
end-to-end through `load_latest_knowledge`):

```
test_load_latest_knowledge_applies_retention_when_over_budget
test_load_latest_knowledge_returns_stats_dict
test_load_latest_knowledge_disabled_retention_keeps_all
```

Then a smoke test on the live V8 explore workspace
(`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v8_0430`):
read-only call into `load_latest_knowledge` with the production
default policy, assert returned bullet count is bounded by
`max_total`, eyeball the content for milestone preservation.

#### 14.7.3 Regression guard

Existing PR #66 tests
(`test_load_latest_knowledge_unions_findings`,
`test_load_latest_knowledge_dedup_first_wins`) must continue to
pass — the policy is a pure trim on the existing union, so
under-budget chains see no behavioural change.

### 14.8 Commit Strategy (mirrors §10.5 / §11.5)

Five commits, each independently testable:

1. **Schema** — add `FindingsRetentionPolicy` Pydantic model +
   `_DEFAULT_FINDINGS_RETENTION` constant + module imports
   (`warnings`, `model_validator`, `Field`). No call-site change
   yet.
2. **Helpers** — add `_count_recurrence_prefixes`,
   `_importance_score`, `_apply_findings_retention` as pure
   functions, plus their unit tests (§14.7.1).
3. **Loader wiring** — modify `load_latest_knowledge` to collect
   `(iter, position, text)` tuples and call
   `_apply_findings_retention` before flattening. Update return
   signature to include the retention stats dict (or extend
   `RestoredState` with a `findings_retention_stats` field —
   §14.10 open question).
4. **Workflow surface** — patch the `ExpertContextItem` builder
   in `workflows/model_exploration.py` to include the disclosure
   header and retention stats.
5. **Doc closeout** — flip §14.9 checkboxes; add a one-line note
   to §13.4 #4 confirming the prompt-pressure mitigation has
   landed.

### 14.9 Checklist

#### Pre-implementation
- [x] Audit confirms G4 is open in master (`accumulated_key_findings` uncapped).
- [x] §9.6.3 supersession written into doc with forward-pointers.
- [x] Two-bucket model rationale documented in §14.1 / §14.2.
- [x] Importance heuristic grounded in actual Phase-2 prompt contract
      (`nodes/result_interpretation_agent.py:107` ranks by importance).

#### Implementation
- [ ] `core/resume.py` — add `FindingsRetentionPolicy` Pydantic class.
- [ ] `core/resume.py` — add `_count_recurrence_prefixes` helper.
- [ ] `core/resume.py` — add `_importance_score` helper.
- [ ] `core/resume.py` — add `_apply_findings_retention` helper.
- [ ] `core/resume.py` — extend `load_latest_knowledge` to apply policy.
- [ ] `core/resume.py` — extend return signature with retention stats.
- [ ] `workflows/model_exploration.py` — surface stats in `ExpertContextItem` header.

#### Testing
- [ ] Unit tests (§14.7.1) — 10 synthetic tests, all pass.
- [ ] Integration test (§14.7.2) — replay over V8 workspace, bounded output.
- [ ] Regression guard — existing PR #66 tests still pass.

#### Doc updates
- [ ] §14.9 checkboxes flipped.
- [ ] §13.4 #4 updated with mitigation-landed note.

### 14.10 Coordination with §10 / §11 Tier-B / §12

| Section | Concern | Interaction with §14 |
|---|---|---|
| §10 | G1 — proposed_vocab_candidates lost | Independent. Vocab and findings are separate channels. §14 does not affect candidate graduation; §10 does not affect findings retention. |
| §11 Tier-B | Vocab additive merge across iters | Adjacent. §11 protects vocab from overwrite; §14 protects findings from blind truncation. Different schemas, same operator-stated intent ("long-term IP must survive"). |
| §12 | Vocab ancestry observability | Aligned. §12's Layer-3 workflow_log block can be extended to include findings-retention stats (`n_kept / n_total / n_milestones`) so operators see retention behaviour live. Doc-only coordination — no code dependency. |

Recommended landing order (revised from §12.6's
§10 → §11 Tier-B → §12):

```
§10 (G1 candidate channel) → §11 Tier-B (vocab monotonicity) →
§14 (findings retention) → §12 (observability across all three)
```

Rationale: §14 should land before §12 so §12.3.3's workflow_log
block can include retention stats from day one; otherwise §12
would need a follow-up patch the moment §14 ships.

### 14.11 Open Questions for the Operator

1. **Default `max_total`.** §14.4 picks 60. With 5 findings/iter
   and a 5-iter recency window, that gives 25-30 milestone slots,
   allowing roughly 5-6 truly distinct architectural milestones
   per recurrence-class. Is 60 the right ceiling for production
   chains? (Could be 40 for tighter focus, 100 for richer
   history. Defaults can be revisited after first 20-iter chain
   with §14 active.)

2. **Default `recent_window_iters`.** §14.4 picks 5. The proposer
   prompt today reads chronologically; with W=5, a 20-iter chain
   has the LLM reading findings from iters 16-20 verbatim plus
   30-ish milestones from iters 1-15. Is W=5 the right inflection,
   or should it be higher (W=8 → all findings from the last 8
   iters survive)?

3. **Schema migration to `KeyFinding`.** Phase 2 (deferred) would
   promote `key_findings: List[str]` → `List[KeyFinding]` with
   explicit `(text, importance_rank, related_vocab, iter_origin,
   kind)` metadata. The LLM emits importance directly. This
   removes the heuristic in §14.3 entirely. Worth scheduling for
   a later PR, or out of scope?

4. **Generic policy for other channels.** The two-bucket model
   is *not specific to findings* — it would apply equally to any
   accumulating channel where some entries are durable and some
   are perishable. Today only `accumulated_key_findings` has the
   mixed-staleness profile; rejections and gate-exhaustions are
   uniformly perishable (§14.1 table) and the existing trailing-
   slice is correct for them. **No generalisation needed today**,
   but the `FindingsRetentionPolicy` class name signals scope; if
   a future channel has the same shape, its policy should sit
   alongside, not subsume.

5. **Stats surface.** §14.5/§14.6 plumb retention stats both into
   the `[resume]` log line and into the `ExpertContextItem`
   header. Should the stats also be added to `evolution_log.jsonl`
   (per §12.3.1) for offline analysis? Lightweight to do, but a
   §12 dependency.

### 14.12 Risks (post-merge watch)

1. **Recurrence-prefix false positives.** The recurrence boost
   matches on case-folded first-8-token prefix, not full text.
   Two structurally unrelated findings that happen to share an
   opening clause ("The model's denoising score …") could be
   over-weighted as recurrent. Mitigation: log the recurrence
   counts in the `[resume]` line so operators can spot anomalies.
   Real fix: token-bag Jaccard similarity above a threshold
   (deferred — heuristic is fine until measured wrong).

2. **Vocab-mention boost is one-shot.** A finding that mentions a
   vocab term once gets the same +0.3 as one that mentions it
   three times *unless* the term appears literally three times in
   the text. In practice the LLM paraphrases, so the cap at 3 is
   defensive. Could degrade silently if the LLM moves to a more
   reference-heavy style. Watch via the importance-score
   distribution in unit fixture replays.

3. **Bucket A saturation in long chains.** If the operator sets
   `recent_window_iters` too high relative to `max_total` (e.g.
   W=12 with 5 findings/iter = 60 expected, equal to default
   `max_total=60`), the milestone bucket goes permanently empty
   and the policy collapses to a recency window. The
   `model_validator` warns at construction (§14.4), but a runtime
   warning when bucket B is consistently empty across iters would
   help operators tune. Cheap to add — defer to first
   misconfiguration report.

4. **Disclosure header confusion.** The header tells the LLM "X
   of Y findings shown". A proposer LLM might mis-interpret this
   as a sign that older context is unreliable, and lean too
   heavily on recent findings. If observed, soften the wording
   from "suppressed" to "summarised" and add a note that all
   suppressed findings remain on disk (which is true).

5. **Interaction with §11 Tier-B vocab-mention boost.** Once §11
   Tier-B is in place, `runtime_vocab` is monotonically growing,
   so the set of vocab names available to the boost is also
   monotonically growing. A finding that mentioned no vocab when
   it was written may, several iters later, mention a *now*-known
   vocab term and have its score elevated. This is *correct*
   behaviour (the finding's structural relevance has grown), but
   it does mean the importance score for any finding is a
   function of the *current* iter's vocab snapshot, not the
   iter-of-emission's snapshot. Document in code comment; not a
   bug.

### 14.13 Phased Rollout — MVP vs. v2 (sprint scope decision)

§14.1–§14.12 describe the **complete** two-bucket retention policy
with importance scoring. Following operator review of §15, the
implementation plan ships only the **MVP slice** this sprint. The
complete spec remains as the v2 target, gated on observed need.

**Phase 3 MVP (this sprint, §15.5)**:

- Plain recency window: drop findings from iters older than
  `current_iter − W` (default `W = 5`).
- Existing first-occurrence dedup-by-string preserved bit-for-bit.
- No Pydantic policy class, no importance scoring, no two-bucket
  reservoir, no helper functions for recurrence/vocab-mention.
- Implementation surface: ~15 LOC in `load_latest_knowledge`, one
  module constant, one stats dict for the proposer header.

**v2 (deferred — gated on observed Milestone Erosion)**:

- Promote MVP recency window into bucket A; add bucket B
  milestone reservoir per §14.2.
- Add `FindingsRetentionPolicy` Pydantic schema per §14.4.
- Implement `_count_recurrence_prefixes`, `_importance_score`,
  `_apply_findings_retention` per §14.5.
- Surface bucket-split stats in proposer header per §14.6.

**v2 trigger — "Milestone Erosion"**: a finding describing an
architectural milestone (promotion event, dead-architecture class,
falsifiable-prediction confirmation) noted in iter K is
*rediscovered* by the proposer in iter K+W+δ because it was
evicted by the recency window. Detectable via:

1. **Manual**: operator reads `take_home_message` at iter K+W+δ
   and recognises a re-statement of an earlier known finding.
2. **Semi-automatic**: a finding's text shares high token overlap
   (Jaccard ≥ 0.6) with a finding from > W iters ago that was
   not surfaced in the current proposer prompt.

If milestone erosion is observed in the first 20-iter chain after
Phase 3 MVP lands, raise it as a follow-up issue and implement
the v2 spec above. Until then, the simpler MVP is the production
code.

**Why MVP first**: the 0.7 / 0.5 / 0.3 weights in §14.3 are not
calibrated against real V8 data. Shipping them as the initial cut
risks tuning on a single-chain anecdote. The MVP is structurally
simple, behaviourally correct (no information loss for recent
iters), and produces the very signal — Milestone Erosion frequency
— that would calibrate v2's weights when needed. Avoiding
premature optimisation per CLAUDE.md "Slow is Smooth, Smooth is
Fast".

---

## 15. Consolidated Implementation Plan (Phased, Linear)

§10, §11, §12, and §14 each ship their own commit strategy. In
practice, three of the four bridges touch the same two files
(`core/resume.py`, `workflows/model_exploration.py`) and they have
hard ordering dependencies. This section is the authoritative,
linear path from green-light to merge. The per-section plans
(§10.5, §11.5, §12.5, §14.8) remain valid as **rationale**.
**When this section and a per-section plan diverge, this section
wins.**

### 15.0 Reading guide

- **Phases run strictly in order**. Phase 2 depends on Phase 1
  having loaded vocab in the first place; Phase 3 depends on
  Phase 2 (§14.3's vocab-mention boost reads `runtime_vocab` —
  §11 Tier-B guarantees that read is monotonically complete);
  Phase 4 reports on artefacts produced by Phases 1–3.
- **Within a phase, commits run in numeric order**. Each commit
  is independently testable; the verification contract MUST pass
  before the next commit lands.
- **Test isolation**: each commit names *only* the test files that
  gate it. Per `feedback_run_relevant_tests_only.md`, the full
  suite is *not* required between commits. A single full-suite
  pass at the end of each phase gates the next phase.
- **Python interpreter**: every command below uses
  `.venv/bin/python` (project convention; system `python3` is 3.8
  and will fail).
- **Branch policy**: per `feedback_worktrees.md`, work directly
  on the active feature branch. No worktree isolation.

### 15.1 Pre-flight (one-time, no commit)

- [ ] Working tree clean from the chosen base branch (`git status --short` empty)
- [ ] V8 replay workspace available: `ls /home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v8_0430/iter_*/iteration_*/interpretation_iter_*.json | head` returns non-empty
- [ ] Specs §10 / §11.5 / §12.3 / §14 / §15.2 (gate cadence) read end-to-end (this section is execution, not design)
- [ ] Full test suite green at HEAD: `.venv/bin/python -m pytest tests/unit -x` passes
- [x] ~~Preflight Gate 1 green~~ — **SKIPPED** per operator decision 2026-05-02 (see preflight observations below)
- [ ] **Preflight Gate 2** at base-branch HEAD (§15.2.2) — calibration anchor; lilab 5090 required. Deferred; harness command pending.
- [ ] Preflight gate results recorded somewhere durable (issue, runbook, or `docs/v9_launch_certification_log.md`) so phase-boundary gate runs have a reference point

**Preflight observations (2026-05-02 — recorded for the audit trail)**

While inspecting V8 chain workspaces ahead of preflight, the
following baseline state was discovered. Both items are upstream of
§15 and do **not** count as §15 commits.

1. **V8 chains crashed mid-iter_002 with the same Pydantic
   `ValidationError`**: `ExpertContextItem.kind` Literal did not include
   `'findings'`, but `workflows/model_exploration.py:940` was
   constructing items with that exact kind to forward
   `accumulated_key_findings`. Both V8 explore and exploit chains
   (launched 2026-04-30 16:26-16:27) died at the same code path on
   their second iter. No live processes remain; the chains are
   permanently halted in a known-broken state.
2. **Fix already landed**: commit `cedca57` —
   `fix(schema): widen ExpertContextItem.kind Literal to accept
   'findings'` — is on the active branch and was verified by running
   `tests/unit/agent/ml_model_proposal_agent/test_phase_b_schemas.py
   -k ExpertContextItem` (5/5 tests green). Schema now accepts the
   six kinds: `empirical | theoretical | literature | human |
   narrative | findings`. This unblocks the chain-mode finding
   carry-over forever — independent of §15 — and also unblocks Phase
   3 Commit 3.2 (which adds a disclosure header to the same
   `findings`-kind item).
3. **Gate 1 skipped**: operator decision (2026-05-02) — running Gate
   1 against the just-fixed code base produces a baseline that is no
   longer the same broken baseline that V8 ran on. Since Phase 1 +
   Phase 2 are the actual amnesia fixes the launch was waiting for,
   the cleaner anchor is the post-Phase-2 gate run. Gate 1 will fire
   at end of Phase 1 (commit 1.5) and end of Phase 2 (commit 2.3) per
   the §15.2.1 cadence — the latter is the load-bearing
   vocab-monotonicity acceptance test.
4. **Gate 2 deferred**: no packaged entrypoint today (per §15.2.2);
   harness gap to be resolved before commit 1.5.

---

### 15.2 Certification Gate Cadence (Cross-Phase)

**Source**: `docs/aggregated_score_table_awareness.md` §12.5 V9 Launch
Certification Gates. Two gates cover orthogonal failure modes; one
of them is a load-bearing test of exactly what §15 is shipping:

- **Gate 1 — Pseudo-Cognitive Probe**
  (`tests/integration/workflows/test_cognitive_alignment_smoke.py`):
  3 pseudo-mode iters with real OpenAI calls at synthesis +
  proposer. Six property-based metrics. **Metric 6 directly tests
  vocab monotonicity** (`runtime_vocab` must grow OR refine across
  3 iters; removed entries are a hard fail) — i.e. the §11 Tier-B
  contract is a Gate-1 acceptance criterion. Cost: ~5 min, OpenAI
  tokens only, no GPU.
- **Gate 2 — Lightweight End-to-End Stress Test**: 3 iters of real
  training + scoring (5090, `trial_portion=0.02`). Three metrics
  on unit consistency, subset-scope footnote, logging completeness.
  Cost: ~5 min, lilab 5090 only (SDSC Expanse not equivalent).

#### 15.2.1 Why phase-boundary cadence (not per-commit, not end-only)

Per-commit cadence (18 × ~10 min ≈ 3 hours) is mostly redundant —
most §15 commits are mechanical (add field, accept kwarg, forward
kwarg) with no observable surface either gate measures.
End-of-plan-only cadence is too sparse: a regression introduced in
Phase 1 surfaces only after Phase 4 lands, forcing a 4-phase
bisect.

Phase-boundary cadence + a calibration baseline at preflight =
**5 checkpoints, 9 gate runs total, ~45 min of gate budget across
the entire 18-commit plan**. Each checkpoint is anchored to a
moment where observable behaviour materially changes.

| Checkpoint | Why this point matters | Gate(s) |
|---|---|---|
| **Preflight** (master HEAD, pre-Phase-1) | Calibration anchor — establishes the green baseline against which all subsequent gate runs are compared. If gates aren't green at preflight, the work is on a broken base, not on us. Decision: fix base or proceed knowingly with a yellow baseline. | Gate 1 + Gate 2 |
| **End of Phase 1** (post-1.5) | Phase 1 plumbs a new memory channel through 3 files. Any data-flow regression (Gate 2) or echo-chamber regression from the freshly-restored candidate context (Gate 1 metric 4) lands here. | Gate 1 + Gate 2 |
| **End of Phase 2** (post-2.3) | Phase 2 changes only vocab-merge semantics in `core/resume.py`. Gate 1 metric 6 (vocab evolution + no-removal) is the direct contract. Gate 2 is unaffected (Tier-B doesn't touch the training/scoring/logging path). | Gate 1 only |
| **End of Phase 3** (post-3.3) | Phase 3 modifies the proposer prompt content (retention header) AND the loader return signature (3-tuple). Cognitive contract (Gate 1 metrics 1, 4) tests prompt change; data-flow contract (Gate 2) tests plumbing change. | Gate 1 + Gate 2 |
| **End of Phase 4** (post-4.5) | Final certification. Gate 1 confirms cognitive contract intact under all 4 phases combined. Gate 2 confirms commit 4.3's `workflow_log` stdout block didn't break captured-stdout assertions or `agent_data_stream.jsonl` completeness. | Gate 1 + Gate 2 |

Gate-run total: **Gate 1 = 5 runs, Gate 2 = 4 runs**.

#### 15.2.2 Gate run procedure (at each checkpoint)

```bash
# Gate 1 — cognitive probe (~5 min, real OpenAI gpt-4o-mini)
.venv/bin/python -m pytest tests/integration/workflows/test_cognitive_alignment_smoke.py \
    --real-api-call -xvs

# Gate 2 — data-flow stress (~5 min, lilab 5090 only)
# Run via the V9 launch harness in §12.5 of aggregated_score_table_awareness.md.
# After completion, inspect:
.venv/bin/python -c "
import json, pathlib
ws = pathlib.Path('<gate2_workspace>/logs/agent_data_stream.jsonl')
for line in ws.read_text().splitlines():
    row = json.loads(line)
    print(row.get('iter'), row.get('per_file_table'))
" | head -20
```

If a packaged Gate 2 entrypoint does not yet exist as a single
script, the harness is the 3-iter formal config documented in
`aggregated_score_table_awareness.md` §12.5 — copy that
configuration, run it, then verify the three metrics by hand.

#### 15.2.3 Triage table — which §15 commit a gate failure points to

| Gate | Metric that failed | Likely root cause within §15 | Action |
|---|---|---|---|
| Gate 1 | #6 vocab evolution / removal | Phase-2 merge regression OR Phase-1 candidate intake silently failing | Bisect on `core/resume.py`; check `seen_in_runs` lineage in fixture output |
| Gate 1 | #4 echo-chamber (Jaccard ≥ 0.7) | Phase-1 leaked stale `previous_proposal_data` across iters, OR Phase-3 retention header degenerates LLM into canned diagnoses | Inspect captured `take_home_message` triples for textual overlap; check retention header wording at workflows/model_exploration.py |
| Gate 1 | #1 dynamic lever / #3 saturation | Phase-3 retention may have suppressed a recency finding the LLM was relying on | Check `findings_retention_stats.suppressed`; if recent finding got demoted to bucket B, reconsider `recent_window_iters` |
| Gate 1 | #2 permanent-irrelevance / #5 columns | Cognitive prompt regression — likely *not* introduced by §15 (no prompt rewrite in scope). | Escalate to prompt-layer owner; if pre-existing, document and gate-defer |
| Gate 2 | #1 unit consistency | Phase-3 loader signature change broke a downstream consumer, OR Phase-4 stdout block introduced a write-path bug | Trace `_compute_evolution_stats` call sites and §14.5 retention-stats wiring |
| Gate 2 | #2 / #3 logging completeness | Phase-4 commit 4.1 (evolution_log) or 4.3 (workflow_log) — silent drop or double-log | Diff `evolution_log.jsonl` row count vs iter count; check `workflow_log.txt` contains the §12.3.3 block once per iter |

A gate failure **stops** the next phase. Fix or revert before
proceeding; do not stack a second phase's changes on top of a red
gate.

#### 15.2.4 Recording gate results in the commit log

The doc-closeout commit at the end of each phase (1.5, 2.3, 3.3,
4.5) carries the gate-run results in its commit message body, so
the audit trail survives in `git log` without a separate ledger.
Format:

```
Phase N closeout — flip §1X.Y checkboxes; mark §9.2 row CLOSED.

Gate 1: pass (15 vocab entries → 18; monotonic; Jaccard 0.41).
Gate 2: pass (1 file sampled at trial_portion=0.02; log-space consistent).
        [or "skipped (Phase 2 — no data-flow surface)"]
```

Commit-time gate verification is now an explicit checklist item in
each phase's doc-closeout commit (commits 1.5, 2.3, 3.3, 4.5) —
see updated checklists in §15.3 / §15.4 / §15.5 / §15.6 below.

---

### 15.3 Phase 1 — G1 Bridge: Candidate Channel Restoration

**Goal**: cross-iter `proposed_vocab_candidates` survives the chain
subprocess boundary, unblocking `seen_in_runs ≥ 3` promotion.
**Source spec**: §10.

#### Commit 1.1 — `core/resume.py`: proposal loader

**Note**: extend `RestoredState` with `previous_proposal_data: dict | None`; add `_proposal_path` glob helper and `load_latest_proposal` reader; wire into `restore_prior_state`.

**Status**: ✅ CLOSED — landed in `e1ca13d` on `fix/cognitive-alignment-v9` (2026-05-02).

Checklist:
- [x] `RestoredState.previous_proposal_data: dict | None = None` field added with docstring (§10.3.1) — `core/resume.py:135`
- [x] `_proposal_path(workspace, iter_idx) -> str | None` walks `iter_NNN/iteration_*/attempt_*_<model>/proposal_iter_NNN.json` — `core/resume.py:337`; uses `sorted(...)[-1]` so highest `MMM` prefix wins (validation-retry case)
- [x] `load_latest_proposal(workspace, committed_iters) -> dict | None` returns latest non-empty parseable; soft-fail (warn + skip) on missing/malformed (§10.3.2) — `core/resume.py:380`
- [x] `restore_prior_state` calls loader and populates the field — `core/resume.py:614`; emits a one-line `[resume] proposal carry-over: latest proposal restored (N proposed_vocab_candidates)` log when populated
- [x] Unit tests added: **9 total** (over-delivered vs. the spec'd 4 — kept the 4 mandated cases and added 5 path-helper / restore-integration cases for edge coverage):
  - `TestLoadLatestProposal::test_load_latest_proposal_no_committed_iters_returns_none` ✅
  - `TestLoadLatestProposal::test_load_latest_proposal_latest_committed_wins` ✅
  - `TestLoadLatestProposal::test_load_latest_proposal_malformed_warns_and_skips` ✅
  - `TestLoadLatestProposal::test_load_latest_proposal_glob_walks_attempt_dirs` ✅
  - `TestLoadLatestProposal::test_proposal_path_returns_none_when_no_attempt_dir` ✅
  - `TestLoadLatestProposal::test_proposal_path_returns_none_when_iteration_dir_missing` ✅
  - `TestRestorePriorStateProposalCarryOver::test_iter1_leaves_proposal_field_none` ✅
  - `TestRestorePriorStateProposalCarryOver::test_populates_previous_proposal_data_from_latest_iter` ✅
  - `TestRestorePriorStateProposalCarryOver::test_proposal_field_none_when_no_proposal_files_exist` ✅

Verification (2026-05-02):
```
$ .venv/bin/python -m pytest tests/unit/core/test_resume.py \
    -k "proposal or LatestKnowledge or NegativeFeedback or CleanThreeIter or TrivialPaths"
# 34 passed, 18 deselected — 9 new proposal tests + 25 regression-scope tests, all green

$ grep -n 'previous_proposal_data\|load_latest_proposal\|_proposal_path' core/resume.py
# 10 matches: field decl (135) + docstring (111) + helper (337) + loader (380, 391, 419)
#            + restore_prior_state call + log (614, 617, 619)
```

#### Commit 1.2 — `workflows/model_exploration.py`: kwarg + init replacement

**Note**: accept `restored_previous_proposal: dict | None` kwarg in `run_workflow`; replace the line-784 unconditional `previous_proposal_data: dict | None = None` reset with a priority check.

Checklist:
- [ ] `run_workflow` signature gains `restored_previous_proposal: dict | None = None`
- [ ] Line-784 init replaced with `previous_proposal_data: dict | None = restored_previous_proposal`
- [ ] In-process multi-iter path (no kwarg) preserves bit-for-bit behaviour (the local update at line 1217 still fires)
- [ ] Docstring on the new kwarg points to §10.3.3

Verification:
```
.venv/bin/python -m pytest tests/integration/workflows/test_vocab_accumulation.py -xvs
# regression: in-process multi-iter promotion still works
grep -n 'previous_proposal_data: dict | None = None' workflows/model_exploration.py
# expected: 0 matches (the unconditional reset is gone)
```

#### Commit 1.3 — `sdsc_submission_scripts/run_one_iteration.py`: forwarding

**Note**: forward `state.previous_proposal_data` into the `run_workflow` call alongside the existing 4 memory channels.

Checklist:
- [ ] One new line at the `run_workflow(...)` call site (lines 722–726): `restored_previous_proposal=state.previous_proposal_data`
- [ ] No other change in this file

Verification:
```
grep -n 'restored_previous_proposal' sdsc_submission_scripts/run_one_iteration.py
# expected: exactly 1 match in the run_workflow(...) call
.venv/bin/python -c "from sdsc_submission_scripts.run_one_iteration import _resolve_chain_state; print('OK')"
# expected: prints OK (import smoke)
```

#### Commit 1.4 — Integration test: `foo` graduation in 3-iter chain

**Note**: new dual-mode test simulates 3 chain iters proposing the same candidate `foo`; asserts iter-3 final digest contains `foo` with `kind == 'capability'` (promotion fired).

Checklist:
- [ ] New file `tests/integration/workflows/test_chain_candidate_graduation.py`
- [ ] `@pytest.mark.dual_mode`, pseudo by default, real-mode opt-in via `--real-api-call`
- [ ] Asserts `seen_in_runs` for `foo` has 3 distinct iter-tagged entries by end-of-iter-3
- [ ] Regression case: in-process `max_iterations=3` produces the same outcome (proves Phase-1 is path-symmetric)

Verification:
```
.venv/bin/python -m pytest tests/integration/workflows/test_chain_candidate_graduation.py -xvs
# expected: both pseudo paths pass (chain mode + in-process mode)
```

#### Commit 1.5 — Doc closeout + Phase-1 gate verification

**Note**: flip §10.6 checkboxes; mark §9.2 G1 row CLOSED; run §15.2 gates; record results in commit message.

Checklist:
- [ ] §10.6 all `[ ]` → `[x]`
- [ ] §9.2 G1 row: `OPEN` → `CLOSED (Phase 1, commits 1.1–1.4, <date>)`
- [ ] One-line "Phase 1 closed YYYY-MM-DD on branch `<name>`" appended to §10
- [ ] **Gate 1 green at this commit's HEAD** (§15.2.2 procedure)
- [ ] **Gate 2 green at this commit's HEAD** (§15.2.2 procedure)
- [ ] Gate results recorded in commit message body per §15.2.4 format

Verification: doc-only code change, but the two gate runs are the load-bearing verification for the phase boundary. Failures triaged via §15.2.3.

---

### 15.4 Phase 2 — Hard Monotonicity: Vocab Tier-B Additive Merge

**Goal**: `runtime_vocab` is monotonically growing across chain
iters; an LLM regression on a single iter's digest cannot shrink
the cumulative vocab. **Source spec**: §11.5.

#### Commit 2.1 — `core/resume.py`: additive merge

**Note**: replace the per-iter overwrite block at `core/resume.py:296–310` with the §11.5 merge — union across all parseable iter digests; latest-wins on `kind`/`related_to`/`sources` for duplicate name; `seen_in_runs` is set-union (chronological, no sort).

Checklist:
- [ ] `vocab_by_name: Dict[str, VocabEntry] = {}` initialised before the iter loop
- [ ] Per-iter loop applies §11.5 merge logic verbatim (model_validate per entry, set-union via `dict.fromkeys` to preserve order)
- [ ] Final return: `list(vocab_by_name.values()), findings`
- [ ] Per-entry validation failure → warn + drop (preserved)
- [ ] Empty iter digest is a no-op (preserved — line-309 protection still in force structurally)
- [ ] `seen_in_runs` order chronological, no sort (required by §12.3.1's `first_seen` derivation)

Verification:
```
.venv/bin/python -m pytest tests/unit/core/test_resume.py -k "monotonic or additive_merge" -xvs
# expected: 4 new tests pass (test_merge_union_across_iters, test_merge_set_union_seen_in_runs_chronological, test_merge_empty_iter_no_erase, test_merge_malformed_entry_drops_only_that_entry)
```

#### Commit 2.2 — Integration replay: V8 superset proof

**Note**: read-only test replays a real V8 workspace under both old reader (pre-Tier-B) and new reader; asserts new ⊇ old (no regression on real data).

Checklist:
- [ ] New test in `tests/unit/core/test_resume.py::test_v8_replay_new_reader_is_superset`
- [ ] Read-only against `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v8_0430`
- [ ] `pytest.skip()` when workspace not present (CI safety)
- [ ] Asserts: every entry in old-reader output is present in new-reader output with identical `kind`; new-reader output may contain additional entries

Verification:
```
.venv/bin/python -m pytest tests/unit/core/test_resume.py::test_v8_replay_new_reader_is_superset -xvs
# expected: passes locally (workspace present); skipped in CI
```

#### Commit 2.3 — Doc closeout

**Note**: mark §11.5 IMPLEMENTED; resolve §11.6 open questions.

Checklist:
- [ ] §11.5 plan annotated as IMPLEMENTED (commit 2.1 hash)
- [ ] §9.2 monotonicity row marked CLOSED via Tier-B
- [ ] §11.6 Q1 (kind conflict on demotion): confirmed `latest-wins` acceptable; no demotion path exists today
- [ ] §11.6 Q2 (`related_to` semantics): confirmed `latest-wins` acceptable; set-union deferred until measured loss
- [ ] **Gate 1 green at this commit's HEAD** (§15.2.2 procedure) — Phase 2 is *the* Gate-1-metric-6 change; this is the load-bearing verification for the phase
- [ ] Gate 2 skipped (Phase 2 has no data-flow surface — record "skipped" in commit message per §15.2.4)
- [ ] Gate results recorded in commit message body per §15.2.4 format

Verification: doc-only code change; the Gate-1 run is the load-bearing verification for the phase boundary.

---

### 15.5 Phase 3 — G4 Retention MVP: Recency Window Only

**Goal**: bound `accumulated_key_findings` to findings from the last
`W` iters; preserve existing first-occurrence dedup; surface stats
in proposer header. **Source spec**: §14 — but **only the MVP slice
per §14.13**. The full importance-scored two-bucket design
(§14.1–§14.12) is deferred to v2; trigger condition is observed
Milestone Erosion in the first 20-iter chain.

**Sprint scope decision (operator review)**: shipping the MVP first
because (a) the §14.3 weights (0.7 / 0.5 / 0.3) are uncalibrated
against real V8 data, and (b) §14.13 makes v2 contingent on a real
signal rather than an upfront guess. This collapses the original 5
commits down to 3.

#### Commit 3.1 — `core/resume.py`: recency cap + stats

**Note**: add module constant `_RECENT_ITERS_FOR_FINDINGS = 5`; in `load_latest_knowledge`, skip iters older than `current_iter − W`; return retention stats dict alongside findings.

Checklist:
- [ ] `_RECENT_ITERS_FOR_FINDINGS = 5` module constant with comment pointing to §14.13
- [ ] `load_latest_knowledge` skips iters with `iter_idx < current_iter − _RECENT_ITERS_FOR_FINDINGS` (oldest dropped first; existing first-occurrence dedup unchanged)
- [ ] Return signature extended: `(runtime_vocab, accumulated_key_findings, retention_stats)`
- [ ] `retention_stats: dict` carries `{n_total_seen, n_kept, n_dropped, recent_iters_window}`
- [ ] `RestoredState` gains `findings_retention_stats: dict = field(default_factory=dict)`
- [ ] All call-sites in `restore_prior_state` updated to unpack the 3-tuple
- [ ] `[resume]` log line shows `47 → 25 key findings (window: last 5 iters)`

Verification:
```
.venv/bin/python -m pytest tests/unit/core/test_resume.py -k "recency" -xvs
# expected: 3 new tests (test_recency_cap_drops_old_iters, test_recency_cap_returns_stats_dict, test_recency_cap_preserves_first_occurrence_dedup)
```

#### Commit 3.2 — `workflows/model_exploration.py`: header surface

**Note**: `ExpertContextItem.content` for `kind="findings"` gains a disclosure header citing the recency window.

Checklist:
- [ ] `run_workflow` accepts `findings_retention_stats: dict | None = None` kwarg
- [ ] Header includes `Showing N findings from last W iters (M total seen, S older iters suppressed)` — exact wording flexible, the three counts must be present
- [ ] Header notes "older findings retained on disk in their iter's interpretation digest" so the LLM understands suppression isn't deletion
- [ ] Stats threaded from `state.findings_retention_stats` through `run_one_iteration.py:722–726` block (one new line)
- [ ] `accumulated_key_findings is None` → no `ExpertContextItem` emitted (regression guard preserved)

Verification:
```
.venv/bin/python -m pytest tests/integration/workflows/test_vocab_accumulation.py -xvs
# regression: existing accumulation flow still passes
grep -n 'last.*iters\|window' workflows/model_exploration.py
# expected: header literal present (≥ 1 match)
grep -n 'findings_retention_stats' sdsc_submission_scripts/run_one_iteration.py
# expected: 1 new match in the run_workflow(...) call
```

#### Commit 3.3 — Doc closeout + Phase-3 gate verification

Checklist:
- [ ] §14.13 marked IMPLEMENTED (MVP slice; v2 deferred)
- [ ] §14.9 left untouched (full v2 checklist; not relevant to MVP commits)
- [ ] §9.6.3 marked `SUPERSEDED — MVP IMPLEMENTED via §14.13`
- [ ] §13.4 #4 (prompt pressure): `mitigated by recency window, in production; v2 deferred per §14.13`
- [ ] §9.5 G4 forward-pointer kept; row in §9.2 marked `CLOSED-MVP (Phase 3 v1; v2 follow-up gated on Milestone Erosion)`
- [ ] **Gate 1 green at this commit's HEAD** (§15.2.2) — confirms recency-window header didn't degenerate cognitive contract
- [ ] **Gate 2 green at this commit's HEAD** (§15.2.2) — confirms 3-tuple loader signature change didn't break data-flow logging
- [ ] Gate results recorded in commit message body per §15.2.4 format

Verification: doc-only code change; the two gate runs are the load-bearing verification for the phase boundary.

**Deferred (do NOT implement this sprint)**: §14.4 `FindingsRetentionPolicy` Pydantic, §14.5 helpers (`_count_recurrence_prefixes`, `_importance_score`, `_apply_findings_retention`), §14.6 bucket-split header. These constitute the v2 work-set; revisit only if Milestone Erosion (§14.13) is observed.

---

### 15.6 Phase 4 — Observability: Three-Layer Instrumentation

**Goal**: vocab ancestry visible from logs alone — operator can
answer §12.1's four questions without parsing per-iter digests.
**Source spec**: §12.

#### Commit 4.1 — Layer 1: enrich `evolution_log.jsonl`

**Note**: extend `_compute_evolution_stats` in `nodes/result_interpretation_agent.py` with three new keys: `vocab_inherited` (full snapshot per row), `vocab_introduced_this_iter` (delta vs. prior row), `findings_retention_stats` (from §14).

Checklist:
- [ ] `_compute_evolution_stats` accepts `prior_iter_stats: dict | None`
- [ ] Output gains 3 new keys per §12.3.1: `vocab_inherited`, `vocab_introduced_this_iter`, `findings_retention_stats`
- [ ] `findings_retention_stats` plumbed in from `restore_prior_state` via interp input
- [ ] Existing keys (`vocab_total`, `vocab_canonical`, `vocab_candidate`, `promoted_this_iter`, `is_degraded`) preserved bit-for-bit for back-compat

Verification:
```
.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent/ -k "evolution_stats" -xvs
# expected: 3 new tests (test_evolution_stats_synthetic_3iter_delta, test_evolution_stats_no_prior_baseline, test_evolution_stats_retention_plumbed)
```

#### Commit 4.2 — Layer 2: `vocab_ancestry.md` renderer (**OPTIONAL — sprint deferral**)

**Sprint-scope decision (operator review of §15)**: Layer 2 is the
human-readable view of the same data already carried by Layer 1
(`evolution_log.jsonl::vocab_inherited` snapshot per row) and Layer 3
(`workflow_log.txt` per-iter summary block). For this sprint, Layers
1 + 3 are expected to provide sufficient signal for an operator to
answer §12.1's four questions. Commit 4.2 is implemented only if,
**after Phase 4's other commits land**, an operator explicitly finds
the JSONL + stdout combination insufficient — i.e. they cannot
answer §12.1 without opening per-iter digests. Until then, this
commit is skipped.

If skipped: §15.6 Commit 4.4 and §15.7 final smoke must source all
their assertions from Layer 1 + Layer 3 only (already true after
this sprint's edits). §12.3.2 / §12.7 design content remains
unchanged as the future v2 spec.

**Note (when implemented)**: new function in `nodes/interpretation_helpers.py` that renders a markdown summary of canonical / candidate / new-this-iter vocab; called at end of interp run; written to `{workspace}/iter_NNN/iteration_001/vocab_ancestry.md`.

Checklist (only if Layer 2 is implemented):
- [ ] `render_vocab_ancestry(runtime_vocab: list[VocabEntry], current_iter: int) -> str`
- [ ] Three sections per §12.3.2: `## Canonical (N)`, `## Candidate watch list (M)`, `## New this iter (K)`
- [ ] Each entry shows `seen_in_runs[0]` as `first_seen` and full `seen_in_runs` lineage
- [ ] Write call wired into the interp agent's terminal write phase
- [ ] Overwrite each iter (NOT append; `evolution_log.jsonl` is the durable record per §12.8 risk 3)

Verification (only if Layer 2 is implemented):
```
.venv/bin/python -m pytest tests/unit/agent/interpretation_helpers/ -k "ancestry" -xvs
# expected: 2 new tests (test_render_vocab_ancestry_three_sections, test_render_vocab_ancestry_first_seen_is_run_idx_zero)
```

#### Commit 4.3 — Layer 3: workflow_log per-iter summary block

**Note**: stdout block at end of each iter showing inherited / new / promoted counts and retention stats. Persisted via existing tee to `workflow_log.txt`.

Checklist:
- [ ] Block emitted at end of `run_workflow` iter loop (single print, ~6 lines)
- [ ] Counts identical to Layer-1 row (single source: same `_compute_evolution_stats` call output dict)
- [ ] Retention stats line included: `findings: K total → N kept (M recent + P milestones, S suppressed)`
- [ ] Format matches §12.3.3 mock

Verification:
```
.venv/bin/python -m pytest tests/integration/workflows/test_v8_certification_smoke.py -k "workflow_log_summary" -xvs
# expected: regex-grep on captured stdout finds the summary block
```

#### Commit 4.4 — Integration: full-stack memory completeness

**Note**: end-to-end test exercising Phase 1 + 2 + 3 + 4 against a fixture 3-iter workspace. Asserts: candidate graduates (Phase 1), vocab is monotonic (Phase 2), findings are bounded (Phase 3), all four §12.1 questions answerable from logs alone (Phase 4).

Checklist:
- [ ] New file `tests/integration/workflows/test_chain_memory_completeness.py`
- [ ] `@pytest.mark.dual_mode`; pseudo by default
- [ ] 4 assertions, one per phase, each with operator-readable failure message
- [ ] Phase-4 assertion reads only `evolution_log.jsonl` (Layer 1) + captured `workflow_log.txt` stdout summary block (Layer 3) — **no dependency on Layer 2 `vocab_ancestry.md`** so the test passes whether Commit 4.2 is implemented or skipped (per its OPTIONAL marker above)
- [ ] No per-iter digest opens (§12.1 acceptance: Layer 1 + 3 alone must answer the four questions)

Verification:
```
.venv/bin/python -m pytest tests/integration/workflows/test_chain_memory_completeness.py -xvs
# expected: all 4 phase assertions pass
```

#### Commit 4.5 — Doc closeout + Phase-4 gate verification (final)

Checklist:
- [ ] §12.7 all `[ ]` → `[x]`
- [ ] §15.8 sequence summary updated with actual commit hashes + dates
- [ ] §9.2 G4 row marked CLOSED via Phase-3
- [ ] Top-level doc header notes "All four phases (G1, Tier-B, G4, observability) IMPLEMENTED as of <date>"
- [ ] **Gate 1 green at this commit's HEAD** (§15.2.2) — final cognitive-contract certification across all 4 phases
- [ ] **Gate 2 green at this commit's HEAD** (§15.2.2) — confirms commit 4.3's stdout block didn't break captured-stdout assertions or `agent_data_stream.jsonl` completeness
- [ ] Gate results recorded in commit message body per §15.2.4 format
- [ ] §15.7 Cross-Phase Final Smoke executed manually on a real V8-style chain — all 6 boxes ticked

Verification: doc-only code change. This commit closes the §15 plan; downstream of it, the §15.7 manual smoke is the operator's acceptance gate before declaring the work done.

---

### 15.7 Cross-Phase Final Smoke (manual, post-merge)

After all 4 phases land, execute one real V8-style chain (3 iters,
real LLM, GPU) and confirm:

- [ ] iter_001 `evolution_log` row has `vocab_introduced_this_iter` non-empty (Phase-1 unblock proof)
- [ ] iter_002 row's `vocab_inherited` includes everything from iter_001 (Phase-2 monotonicity proof)
- [ ] iter_003 row's `findings_retention_stats.suppressed` is non-zero IF total findings > 60 (Phase-3 retention active)
- [ ] iter_003 row's `vocab_inherited` is a strict superset of iter_002's (Phase-2 monotonicity end-to-end)
- [ ] At least one entry in iter_003's `evolution_log.jsonl::vocab_inherited` snapshot has `seen_in_runs` length ≥ 3 (Phase-1 graduation observable from Layer 1 alone)
- [ ] Operator can answer §12.1's four questions reading **only** `evolution_log.jsonl` (Layer 1) + the per-iter summary blocks captured in `workflow_log.txt` (Layer 3) — Layer 2 `vocab_ancestry.md` is **not required** for acceptance per §15.6 Commit 4.2 OPTIONAL deferral. If the operator finds Layer 1 + 3 insufficient, that observation is the trigger to revisit Commit 4.2 as a follow-up.

If any check fails: do not announce Phase 4 closure. Open a
follow-up issue and treat the failing channel as a regression
against the closed phase.

### 15.8 Sequence Summary Table

| # | Phase | File(s) touched | Test gate | Commit hash | Date |
|---|---|---|---|---|---|
| 1.1 | G1 | `core/resume.py` | unit (proposal) | `e1ca13d` | 2026-05-02 |
| 1.2 | G1 | `workflows/model_exploration.py` | accumulation regression |  |  |
| 1.3 | G1 | `sdsc_submission_scripts/run_one_iteration.py` | import smoke |  |  |
| 1.4 | G1 | `tests/integration/workflows/test_chain_candidate_graduation.py` | dual-mode pseudo |  |  |
| 1.5 | G1 | doc | **Gate 1 + Gate 2** (§15.2) |  |  |
| 2.1 | Tier-B | `core/resume.py` | 4 monotonicity unit |  |  |
| 2.2 | Tier-B | `tests/unit/core/test_resume.py` | V8 superset replay |  |  |
| 2.3 | Tier-B | doc | **Gate 1** (§15.2; Gate 2 skipped) |  |  |
| 3.1 | G4 (MVP) | `core/resume.py` | 3 recency unit |  |  |
| 3.2 | G4 (MVP) | `workflows/model_exploration.py` + `sdsc_submission_scripts/run_one_iteration.py` | accumulation regression |  |  |
| 3.3 | G4 (MVP) | doc | **Gate 1 + Gate 2** (§15.2) |  |  |
| 4.1 | Obs | `nodes/result_interpretation_agent.py` | 3 stats unit |  |  |
| 4.2 ⚠ OPTIONAL | Obs | `nodes/interpretation_helpers.py` | 2 renderer unit |  |  |
| 4.3 | Obs | `workflows/model_exploration.py` | smoke regex |  |  |
| 4.4 | Obs | `tests/integration/workflows/test_chain_memory_completeness.py` | 4 phase assertions (Layer 1 + 3 only) |  |  |
| 4.5 | Obs | doc | **Gate 1 + Gate 2** (§15.2) + §15.7 manual smoke |  |  |

**Total**: 16 commits effective for this sprint (5 + 3 + 3 + 4 core), with 1 optional commit (4.2) gated on operator review of Layer 1 + 3 sufficiency per §15.6.
**Phase 3 v2 deferred**: full importance-scored two-bucket retention per §14.1–§14.12 is contingent on observed Milestone Erosion (§14.13); not in this sprint's commit count.
**Hashes + dates**: filled in as each commit lands.
**Phase boundary gate**: §15.1 pre-flight → §15.7 final smoke must pass before tagging the phase closed. §15.2 certification gates fire at preflight + each phase boundary (commits 1.5 / 2.3 / 3.3 / 4.5).

---

*End of design doc.*
