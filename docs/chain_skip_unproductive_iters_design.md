# Chain Iteration Budget — Skip Unproductive Iters (Design)

**Status**: design — pending operator review before implementation.
**Branch**: `chore/ruff-pyright-cleanup` (will likely split to a feature branch).
**Author**: Yue Ma + Claude pairing session, 2026-05-25.
**Related**: `sdsc_submission_scripts/_chain_common.sh`,
`sdsc_submission_scripts/run_chain.sh`,
`sdsc_submission_scripts/run_one_iteration.py`,
`scripts/inspect_run_state.py`.

---

## 1. Problem

The user's stated design intent: *"a failed iteration should not consume
the total iteration limit."*

The current implementation does the opposite:

```
_chain_common.sh:run_chain()  →  for ITER in $(seq 1 NUM_ITERATIONS); do ...
```

Every call to `submit_iteration` consumes one slot of `NUM_ITERATIONS`
regardless of whether the iter produced a useful model. Status tracked
via `iter_NNN/manifest.json` (`completed` / `no_records` / `failed`) is
written but **never read** by the loop.

What the codebase **does** implement is a *consecutive-failure halt
brake* (`run_one_iteration.py:_check_consecutive_failure_brake`,
default 3). That is a safety net for `status="failed"` Python crashes
— it is NOT a budget-aware retry.

### Empirical witness (Phase 3b Run III, 2026-05-23)

| iter | arch              | manifest status | outcome                           |
|------|-------------------|-----------------|-----------------------------------|
| 1    | fft_gate_tcn      | `no_records`    | 9× forward-pass probe timeout     |
| 2    | spectral_skip_tcn | `completed`     | trained, scored 5.5625            |

Launched with `--num_iterations 2`. Iter 1 produced nothing useful, iter
2 succeeded once. Chain stopped at 2 because the budget was consumed by
two `submit_iteration` calls, even though only one produced a model.

---

## 2. Goal

Change the iteration loop to be **outcome-aware**: count toward the
budget only iters that produced a `completed` manifest. Iters that
finished as `no_records` or `failed` advance the iter index but do not
consume the success budget. A safety cap (`--max_total_attempts`)
prevents runaway.

### Decisions taken

| decision | value | rationale |
|---|---|---|
| Semantics | **B-strict** — only `completed` consumes a slot | The intent is "produce N useful models". Both `no_records` (clean run, no model) and `failed` (crash) failed to deliver; both should be free retries. |
| Scope | **lilab mode only** | SDSC slurm `afterany` chains pre-submit all N jobs upfront before any iter runs. Dynamic re-queuing requires either a buffer-of-N+k submission strategy or a refactor to dynamic chaining. Out of scope for this commit. |
| Safety cap | `--max_total_attempts` CLI flag, default `NUM_ITERATIONS * 2` | A runaway-bad chain must terminate. `2×` is generous enough to absorb 50% no_records/failed and still hit the success budget; tighter than `+5` for small chains. |
| Pre-existing bug | Fix `compute_next_iter` to return `max(all_iters) + 1` | Currently returns `max(committed) + 1`, which would overwrite an existing `no_records` dir on auto-resume. Not introduced by this change but made much more likely by it; fixed in the same commit. |

---

## 3. Proposed change

### 3a. `_chain_common.sh:run_chain()`

Replace the mechanical for-loop with an outcome-aware while loop:

```bash
run_chain() {
    if [ "$DRY_RUN" -ne 1 ]; then
        mkdir -p "$WORKSPACE"
    fi
    local ITER="${START_ITER:-1}"
    local completed=0
    # Default cap: 2× the requested success budget. Operator may override
    # with --max_total_attempts. Cap is over ITER not over attempt count,
    # so resuming a chain with --start_iter > 1 still works correctly.
    local cap
    if [ -n "${MAX_TOTAL_ATTEMPTS:-}" ]; then
        cap="$MAX_TOTAL_ATTEMPTS"
    else
        cap=$(( NUM_ITERATIONS * 2 ))
    fi

    while [ "$completed" -lt "$NUM_ITERATIONS" ] && [ "$ITER" -le "$cap" ]; do
        build_source_paths "$ITER"
        build_app_args "$ITER"

        echo ""
        echo "############################################################"
        echo "  Iteration $ITER  (completed so far: $completed / $NUM_ITERATIONS; cap: $cap)"
        echo "  Source paths: ${#SOURCE_PATHS[@]} entries"
        local p
        for p in "${SOURCE_PATHS[@]}"; do
            echo "    - $p"
        done
        echo "############################################################"

        # Catch exit 3 (chain-brake halt) without taking down the script.
        local rc=0
        submit_iteration "$ITER" || rc=$?
        if [ "$rc" -eq 3 ]; then
            echo "[CHAIN] consecutive-failure brake fired (exit 3) — stopping."
            break
        elif [ "$rc" -ne 0 ]; then
            echo "[CHAIN] iteration runner exited $rc — aborting chain."
            exit "$rc"
        fi

        # Read manifest status. Missing/unreadable manifest counts as
        # not-completed (chain continues), matching the fail-open policy
        # of _check_consecutive_failure_brake.
        local mfst="${WORKSPACE}/$(printf 'iter_%03d' "$ITER")/manifest.json"
        local status="unknown"
        if [ -f "$mfst" ]; then
            status=$("${PY_CMD[@]}" -c \
                "import json,sys; print(json.load(open(sys.argv[1])).get('status',''))" \
                "$mfst" 2>/dev/null || echo "unknown")
        fi
        case "$status" in
            completed)  ((completed++)) ;;
            no_records) echo "[CHAIN] iter $ITER produced no usable model — does NOT consume success budget" ;;
            failed)     echo "[CHAIN] iter $ITER failed — does NOT consume success budget" ;;
            *)          echo "[CHAIN] iter $ITER produced manifest status=$status — treating as non-success" ;;
        esac
        ((ITER++))
    done

    if [ "$completed" -ge "$NUM_ITERATIONS" ]; then
        echo "[CHAIN] success budget met: $completed completed iters (of $NUM_ITERATIONS requested)."
    else
        echo "[CHAIN] STOPPED at cap $cap with only $completed / $NUM_ITERATIONS completed iters."
    fi
}
```

### 3b. New flag in `parse_chain_args`

```bash
--max_total_attempts) MAX_TOTAL_ATTEMPTS="$2"; shift 2 ;;
```

Default: empty (resolves to `NUM_ITERATIONS * 2` in `run_chain`). Header
print should show the resolved cap, not the raw flag, so operators
always see the effective value.

### 3c. SDSC-mode warning

`run_chain.sh:submit_iteration_sdsc` should detect the new
`--max_total_attempts` flag on SDSC mode and emit a clear notice:

```
NOTE: --max_total_attempts is lilab-only. SDSC mode uses the legacy
"N attempts total" semantics. To get budget-aware behaviour on SDSC,
see docs/chain_skip_unproductive_iters_design.md §6 (deferred).
```

No silent divergence.

### 3d. `scripts/inspect_run_state.py:compute_next_iter`

Current (L425-427):
```python
committed = [r for r in reports if r.status == "COMMITTED"]
if committed:
    return max(r.iter_idx for r in committed) + 1
```

Fix:
```python
# Advance past the highest iter dir on disk, not just the highest
# COMMITTED one — otherwise we would overwrite a PARTIAL/no_records
# iter that lives above the highest committed one. This is the
# correct semantics for both the legacy (mechanical) loop and the
# new outcome-aware loop, since a no_records dir is a real artefact
# the next iter should respect.
return max(r.iter_idx for r in reports) + 1
```

The pre-existing logic was reachable when:

* iter 1 → `completed`
* iter 2 → `no_records` (`status=PARTIAL` in inspector terms)
* chain interrupted before iter 3 launches
* `--auto_resume` queries `--next-iter` → returns 2 → **overwrites iter 2**

Verified by re-reading the inspector at
`scripts/inspect_run_state.py:391-429`. The bug exists today but is
masked by the fact that the mechanical loop typically runs all
iterations in one session, so auto-resume rarely sees this state. The
new while-loop creates many more `no_records` dirs in normal operation,
so the bug becomes hot.

---

## 4. Implementation checklist

* [ ] Commit DOC.1 — Folder clarity (this branch)
    * [ ] Update head comment in `_chain_common.sh` (library role)
    * [ ] Update head comment in `run_chain.sh` (entry-point role)
    * [ ] Add `sdsc_submission_scripts/README.md` (folder map)
* [ ] Commit DOC.2 — This design doc + commit plan (this branch)
* [ ] Commit IMPL.1 — `_chain_common.sh:run_chain()` while-loop refactor
    * [ ] New `MAX_TOTAL_ATTEMPTS` default + parser case
    * [ ] While loop with `completed`/cap accounting
    * [ ] Manifest status read + classification
    * [ ] Exit-code handling (rc=3 chain-brake, rc≠0 abort)
    * [ ] Updated final summary print
    * [ ] Header print shows resolved cap + new semantics
* [ ] Commit IMPL.2 — `compute_next_iter` overwrite fix
    * [ ] One-line change in `scripts/inspect_run_state.py`
    * [ ] Update docstring
* [ ] Commit IMPL.3 — Tests
    * [ ] Existing unit tests in `tests/unit/sdsc_submission_scripts/`
          updated for the new loop shape
    * [ ] New unit test: while loop stops at success budget when all
          iters are `completed`
    * [ ] New unit test: while loop continues past `no_records` without
          consuming budget
    * [ ] New unit test: while loop stops at `--max_total_attempts` cap
    * [ ] New unit test: while loop breaks on rc=3 (chain-brake)
    * [ ] New unit test: `compute_next_iter` returns
          `max(all_iters)+1` when latest iter is `no_records`
* [ ] Commit VAL — Real-LLM chain validation
    * [ ] Launch a 2-success-target chain with a known-flaky LLM prompt
          to force ≥1 `no_records` iter
    * [ ] Verify the chain advances past `no_records` without
          consuming the budget
    * [ ] Verify the success budget terminates the chain (not the cap)

---

## 5. Test plan

### Unit (mock everything, fast)

In `tests/unit/sdsc_submission_scripts/test_run_chain_loop.py` (new
file). Source `_chain_common.sh`, stub `submit_iteration` as a function
that writes a synthetic `manifest.json` with a configurable status,
then assert on:

| scenario                              | assertion                              |
|---------------------------------------|----------------------------------------|
| all iters `completed`, budget=3       | loop runs exactly 3 iters              |
| iter 1 `no_records`, then 3 `completed`, budget=3 | loop runs 4 iters; ends on iter 4 |
| iter 1 `failed`, then 2 `completed`, budget=2     | loop runs 3 iters; ends on iter 3 |
| every iter `no_records`, budget=3, cap=4 | loop runs 4 iters; ends at cap         |
| iter 1 returns rc=3 (chain-brake)     | loop breaks immediately; no iter 2     |
| iter 1 returns rc=1 (unhandled)       | loop exits with rc=1                   |

### Integration (real subprocess, dual-mode)

Existing dual-mode tests in `tests/integration/workflows/` should
already cover the per-iter path. Add one new dual-mode test that drives
a 2-budget chain through pseudo-mode with one iter returning
`no_records` and one returning `completed`, asserting the chain
produces exactly 2 successes regardless of how many iter dirs were
created.

### Real-API smoke

After unit + integration are green, launch a small chain with a known
hard-rejection prompt (e.g. constrain the LLM to propose architectures
with `segmentation_size=200000` so the probe times out) to confirm the
new loop behaves as designed in a live setting.

---

## 6. Out of scope (deferred)

### SDSC parity

SDSC slurm chains pre-submit all N jobs upfront with
`--dependency=afterany:<prev>`. To support outcome-aware budgeting in
SDSC mode, one of:

1. **Buffer-submit**: submit `NUM_ITERATIONS + k` slurm jobs; each
   reads the manifest history at startup and self-aborts with exit 3
   if the success budget has been met. Wastes slurm allocations but
   keeps the submission model simple. Buffer size `k` would need
   tuning per workspace failure profile.
2. **Dynamic chaining**: each slurm job submits its own successor
   conditionally (sbatch from inside a slurm job). Larger refactor
   but cleaner semantics. Requires resolving the cron-style
   dependency that slurm doesn't natively express.

Neither belongs in this commit. The current SDSC behaviour ("N attempts
total") remains correct for SDSC's typical operating point (chains of
15–30 iters where the cost of one `no_records` slot is amortised).

### Manifest-aware retry of the same iter

We do not propose retrying the *same* iter index after a `failed`
manifest — the next iter is the rescue path, with a fresh LLM proposal
and fresh state. Retrying the same arch on `failed` would mostly just
hit the same failure mode again.

---

## 7. Operator-facing changes

* New flag: `--max_total_attempts N` (lilab only; ignored on SDSC).
* `--num_iterations` semantic shift in lilab mode: now reads as "how
  many *successful* iters do I want?", not "how many attempts total."
  Documented in the header banner and the README.
* `iter_NNN/` dir count may exceed `--num_iterations` (will not exceed
  `--max_total_attempts`).
* SDSC mode behaviour is unchanged.

---

## 8. Rollback

The refactor is contained to one function (`_chain_common.sh:run_chain`)
plus one one-line fix in `inspect_run_state.py`. Reverting the
`_chain_common.sh` change restores the legacy mechanical loop. The
`compute_next_iter` fix is independent and should be kept on revert
since it closes a latent bug.
