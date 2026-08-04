# Design: V20 PR E — Campaign-scoped control state

- **Status**: **DESIGN — awaiting operator review. No implementation is
  authorized.** Per §20.1's per-PR design-doc rule, nothing in this
  document may be built until the operator approves it, and the
  deviations in §5 are approved or rejected individually.
- **Parent plan**: `docs/design/v20_priorities.md` §20.7 (PR scope),
  §9 (P2-1, the confirmed defect), §1.4 (genericization contract),
  §20.11 (review template).
- **Audited against**: `master` @ `4974055c` (2026-08-04), i.e. after
  PR A (#152, `5c18946`), PR B (#153, `4472f15`), PR C1 (#161,
  `781e3e8a`), PR C2 (#164, `40d17f69`) **and the role-resolution
  hotfix (#165, `fe51377c`)**. Every line number below was re-read at
  that commit. `fe51377c` inserted `role_for_run()` at
  `v19_queue_runner.sh:134-170`, shifting every citation past line 132
  by +39 and every citation past the wave loop's launch block by +44;
  the whole document was re-mapped rather than left to drift.
- **Dependencies**: **none.** PR E touches the shell launcher surface,
  the path logic inside it, one small typed Python module the shell
  calls, and the tests and docs that pin those paths. It imports
  nothing from PR A/B/C and is not blocked by PR D.
- **Blast radius**: `sdsc_submission_scripts/` (2 files),
  `tests/unit/sdsc_submission_scripts/` (5 files), `core/` and
  `scripts/` (one new module each — see D-E-3 and D-E-9), `docs/`.
  **No existing Python production module is modified** (§3.8); two are
  added, and both fall inside `pyrightconfig.json`'s `include` by
  deliberate placement (§3.13).

**What this PR is NOT.**

- It is **not** a redesign of stop semantics. C13's two channels (stop
  file + signal), the after-current-iteration timing, the no-respawn
  rule, the `chain_stopped.json` record and exit code 99 are frozen.
- It is **not** a concurrency scheduler. It does not make the queue run
  one, three or five chains. It removes the assumption that the *state
  schema* can only describe two — see D-E-3.
- It is **not** a cleanup or migration tool. No existing file on disk is
  moved, rewritten or deleted by any code this PR ships.
- It is **not** a workspace relocation. Chain workspaces stay at
  `$WS_ROOT/<run_name>` — see D-E-2 and OPEN-E-2.
- It is **not** a HealthGate, admission, estimator or scientific change.

---

## 1. Problem statement

**CONFIRMED DEFECT (parent doc §9.1).** The first launch of
`v19r3_10iter_20260731_1842` stopped immediately with
`QUEUE STOPPED (operator)`. The cause was a queue-level `STOP` file
created at 08:17 when the **previous** contaminated campaign was
stopped, left in the shared `v19/` root.

The stop mechanism worked exactly as designed. C13 read the file and
correctly refused to launch. **The defect is scope**: the file that
recorded one campaign's terminal decision sat at a path that a
*different* campaign also consults, so one campaign's terminal state
held authority over another's launch.

The defect is one line, and it is still on `master`:

```bash
# sdsc_submission_scripts/v19_queue_runner.sh:104
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$WS_ROOT/STOP}"
```

`$WS_ROOT` is the campaign *collection* root (default
`/home/klz/Data/SIDEREIS_DATA/v19`, `:78`). `CAMPAIGN_ID` exists three
lines earlier (`:68`) and is already threaded through the log
(`:81`), the queue state (`:82`), every run name (`:124-131`,
`:450-451`) and the spend query (`:241`). **The stop file is the one
authority-bearing path that was left out of that threading.**

This is the §1.4.2 error in its cleanest form: a *campaign policy
decision* ("this campaign is over") was persisted at a path whose scope
is *the shared filesystem*, and it was then read with an authority it
never earned.

The operator's workaround was manual and destructive-adjacent: the file
was archived by hand into
`v19r2_10iter_20260731_0750_stop_evidence/` and the campaign relaunched.
**A launch must not require an operator to remember which files from a
previous campaign are still armed.**

---

## 2. Objective and non-goals

**Objective.** One campaign's STOP, queue state or pair summary cannot
control another campaign, and no manual root-level cleanup is required
before a new launch.

**In scope — exactly six things.**

1. A path model in which every authority-bearing control path carries
   campaign identity.
2. A **validated typed campaign identity** (D-E-9), because the id
   becomes a directory component for the first time, and a campaign
   stamp plus a launcher guard that refuses a campaign-ID mismatch.
3. Backward compatibility: historical layouts stay readable; legacy
   global state loses authority without being deleted.
4. The remaining campaign-identity defect in the launcher (§3.9). The
   other one (§3.7, the role derivation) was **fixed and merged ahead of
   PR E** — `fe51377c`, PR #165 — per D-E-6.
5. A **typed, atomic Python writer** for the wave/pair summary record
   (D-E-3), replacing an eleven-positional `printf` that cannot express
   a variable-length chain roster.
6. A shell-level multi-campaign isolation test (no GPU, no API).

**Out of scope — restated so it cannot drift.** Stop semantics; the
no-respawn rule; deleting or rewriting legacy STOP evidence; chain
workspace relocation; a general N-chain scheduler; wave ordering; band
definitions; advice content; any change to `run_one_iteration.py`, any
**existing** `core/` module, or any node. The two new Python modules
add code; they modify nothing that exists.

---

## 3. Audit findings that shape the design

Read-only audit at `dd8d66aa`. Every claim below was verified by reading
the file; §3.11 records which of §20.7's claims survived that check.

### 3.1 STOP readers — three, and only two are campaign control

| # | Reader | Path expression | Scope today |
|---|---|---|---|
| 1 | `_chain_common.sh:712-716` `chain_stop_requested()` | `chain_stop_file()` `:694-696` → `${CHAIN_STOP_FILE:-${WORKSPACE}/STOP}` | **per-chain workspace — already isolated** |
| 2 | `v19_queue_runner.sh:198-202` `queue_stop_requested()` | `$QUEUE_STOP_FILE` `:104` → `${QUEUE_STOP_FILE:-$WS_ROOT/STOP}` | **shared root — THE DEFECT** |
| 3 | `scripts/bg_gpu_sampler.sh:96` | `$STOP` `:48` → `$OUTDIR/STOP` | diagnostic tool, own outdir |

Reader 1 is already correct: `${WORKSPACE}` is `$WS_ROOT/<run_name>`
(`v19_queue_runner.sh:248`) and run names carry `CAMPAIGN_ID`
(`:450-451`), so a chain STOP is campaign-scoped *by construction*.
**PR E must not disturb it.**

Reader 3 is a different mechanism that happens to share a filename.
It is not campaign control and PR E does not touch it — but see D-E-8
for the collision it creates today.

Reader 2 is the entire defect.

### 3.2 STOP writers — there are none

Grepping `STOP` across `*.py`, `*.sh`, `*.yaml` at `dd8d66aa` finds
**no production code that creates a stop file.** The stop file is
written by an operator with `touch`, documented at
`docs/running_chain_test.md:111` (chain) and `:131` (queue), and by
tests (`tests/unit/sdsc_submission_scripts/test_c13_stop_semantics.py:32,
84, 162`).

**This is the single most design-shaping finding.** §20.7's checkpoint
E3 says "the launcher rejects mismatched campaign state". There is no
write path to stamp, so *validation cannot happen at write time*. It has
to be:

```text
launcher startup  → resolve campaign root → write/validate a campaign stamp
operator          → touch <campaign root>/control/STOP   (an ordinary file)
runner loop       → read only the resolved campaign path
```

The stamp, not the STOP file, is what carries identity. See §4.2.

### 3.3 Stopped-state writers — two, both already correctly scoped

| Writer | Destination | Scope |
|---|---|---|
| `_chain_common.sh:720-736` `record_chain_stop()` | `${WORKSPACE}/chain_stopped.json` `:722` | per-chain — correct |
| `v19_queue_runner.sh:206-211` `record_queue_stop()` | appends to `$WAVE_STATE` | `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl` `:82` — **already campaign-scoped, by filename prefix** |

So the *stopped-state record* was never the problem. Only the *armed
stop file* was.

### 3.4 Queue state paths — already half-scoped, by prefix not by directory

```bash
# v19_queue_runner.sh
:78  WS_ROOT="${WS_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19}"
:79  EXIT_DIR="${EXIT_DIR:-/tmp}"
:81  LOGF="$WS_ROOT/${CAMPAIGN_ID}_queue_runner.log"
:82  WAVE_STATE="$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl"
:104 QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$WS_ROOT/STOP}"
```

Two of the three carry `CAMPAIGN_ID`. The third does not. The existing
mechanism is **prefix scoping in a flat root**, not directory scoping —
`test_v19_campaign_pinning.py:160-166` asserts exactly that ("queue
state and log carry the campaign id"). §20.7 asks for directory
scoping. That is a change of *mechanism*, not just of the one broken
path — see D-E-1.

Per-chain markers live outside the root entirely:
`$EXIT_DIR/${RUN}.exit` (written `:250`, read `marker_exit()` `:334-337`)
and `$EXIT_DIR/${RUN}.pid` (`:321`, read `chain_pid()` `:329-332`),
`EXIT_DIR` defaulting to `/tmp` (`:79`). Run names carry `CAMPAIGN_ID`,
so these do not collide across campaigns, and `:263` removes a stale
marker before every launch. **No change needed; recorded so the audit is
complete.**

### 3.5 Pair summaries — §20.7's third path does not exist as a directory

§20.7 lists `<root>/<campaign_id>/pair_summaries/`. Nothing in the tree
writes to a directory of that name. What exists is two different things:

1. **Wave summaries**, appended as records into the queue state file —
   `record_wave_summary()` (`v19_queue_runner.sh:226-229`), called at
   `:515` (aborted wave) and `:530` (normal wave). Destination is
   `$WAVE_STATE`, which is already campaign-scoped. These are already
   isolated.
2. **The Gate pair summary**, a fixed single file:

   ```bash
   # v19_gate0_pair_runner.sh
   :44  GATE_ROOT="${GATE_ROOT:-/home/klz/Data/SIDEREIS_DATA/v19/gate0}"
   :56  GATE_RUN_PREFIX="${GATE_RUN_PREFIX:-v19_c14}"
   :57  ARCH_RUN="${GATE_RUN_PREFIX}_arch_15_19"
   :58  LOSS_RUN="${GATE_RUN_PREFIX}_loss_15_19"
   :59  SUMMARY="$GATE_ROOT/gate0_pair_summary.json"
   :63  RUNNER_LOG="$GATE_ROOT/gate0_runner.log"
   ```

   `GATE_RUN_PREFIX` (`:56`, default `v19_c14`) is explicitly
   documented at `:51-55` as the value "the launcher derives EVERY name
   from it, so the summary, the markers and the chain argv cannot
   disagree". **The summary path is the exception: it does not derive
   from it.** Two Gate runs under one `GATE_ROOT` silently overwrite
   each other's summary. The record itself also hardcodes the literal
   `"gate": "v19_gate0"` (`:290`) regardless of the resolved prefix.

   This has already produced one incident: `:379-382` records that on
   2026-07-31 the runner was sourced without the opt-out while diffing
   the argv, nothing launched (the workspace guard refused), "**but the
   pair summary was overwritten**".

So §20.7's `pair_summaries/` maps onto a real, verified defect — just
not the one its name implies. See D-E-4.

### 3.6 `MAX_CONC=2` is a log label, not a concurrency control

§20.7 cites `v19_queue_runner.sh:80` for `MAX_CONC=2`. **CONFIRMED
verbatim at line 80.** But its only other occurrence in the file is:

```bash
# v19_queue_runner.sh:416
log "v19 pairwise queue started: waves=${#WAVES[@]} max_conc=$MAX_CONC resume=${V19_RESUME:-0}"
```

`grep -n MAX_CONC` over the file returns exactly `:80` and `:416`. It
gates nothing. Contrast `v18r_queue_runner.sh`, where `MAX_CONC=4`
(`:20`) is genuinely enforced by a slot check at `:112` and `:114`.

**Deleting or parameterizing `MAX_CONC` in the V19 runner would change
no behaviour at all.** The real "exactly two" assumption is structural
and lives in three places:

| Site | Shape |
|---|---|
| `:450-451` | `ARCH_RUN` / `LOSS_RUN`, two scalars, one wave |
| `:453-458`, `:497-506` | the pair loop over exactly those two names |
| `:226-229` | `record_wave_summary()`, an 11-positional-argument printf (`:226` names the order in a comment) with `arch_run`, `loss_run`, `arch_pid`, `loss_pid`, `arch_exit`, `loss_exit` baked into the JSON at `:227` |

Only the third is a **state schema**, which is what §20.7's
genericization requirement actually constrains. See D-E-3.

`test_v19_queue_runner.py:79-81`
(`test_exactly_two_chains_per_wave_max_conc`) asserts `MAX_CONC == 2`.
Per the CLAUDE.md test rule, that test currently names a defect nothing
else catches only if `MAX_CONC` is load-bearing. It is not. See D-E-3.

### 3.7 `arch`/`loss` — structural, task-flavoured, and one site is broken

The role name reaches production behaviour through the advice file:

```bash
# v19_queue_runner.sh:310
--advice 'advice/workflow/v18r_${FLAVOR}_explorer.json' \
```

`FLAVOR` is supplied by `launch_chain()`'s fourth parameter (`:247`).
**At the time of this audit it was resolved in two different ways, and
they did not agree:**

```bash
# :402 — the --only (targeted, serial) path: read from the ROSTER field
IFS=: read -r RUN SCOPE FILES FLAVOR <<< "$spec"

# the pairwise wave path (pre-fix): re-derived by stripping a LITERAL prefix
FLAVOR="arch"; [ "${RUN#v19_loss_}" != "$RUN" ] && FLAVOR="loss"
```

**That line hardcoded `v19_`.** The ROSTER at `:124-131` builds every
name from `${CAMPAIGN_ID}`, and the wave loop does too (`:450-451`).
So under any `CAMPAIGN_ID` other than `v19`:

```text
CAMPAIGN_ID=v20  →  LOSS_RUN=v20_loss_15_19
                 →  "${RUN#v19_loss_}" == "$RUN"   (no prefix match)
                 →  FLAVOR stays "arch"
                 →  BOTH chains launch with v18r_arch_explorer.json
```

The pair would still *look* correct — two chains, right names, right
bands, right workspaces — while both arms of a paired experiment ran the
same treatment. It was a **live production defect that the V20 launch
would have hit on its first wave**, and it is exactly a campaign-identity
defect. The `--only` path was unaffected because it reads the role from
the ROSTER rather than reconstructing it.

> **FIXED AND MERGED — `fe51377c`, PR #165, 2026-08-04.** Ahead of PR E,
> per D-E-6's recommendation. The fix **deleted the implicit protocol**
> rather than updating the prefix: `role_for_run()`
> (`v19_queue_runner.sh:134-170`) looks the role up in ROSTER field 4
> and **fails closed** — an unknown run or an empty role returns
> non-zero (`:164`, `:169`), and the wave loop records
> `unresolvable_chain_role` and stops rather than defaulting to `arch`
> (`:498-503`). The function's own comment states why `s/v19_/v20_/`
> was rejected: it would defer the same defect to V21 (`:151-153`).
> `--only` is untouched. 13 tests in
> `tests/unit/sdsc_submission_scripts/test_v19_chain_role_resolution.py`,
> mutation-proved against three mutations including the non-fix.
>
> The audit text above is kept because it is the record of what the
> defect was and how it stayed invisible — the reason the fail-closed
> posture exists.

Secondary, and deliberately *not* asserted as a defect: the advice
prefix is `v18r_` (`:310`) while `advice/workflow/v19_gate0_arch.json`
and `v19_gate0_loss.json` exist. Whether the V19 formal campaign
intentionally reused the V18r explorer advice is a scientific decision
this audit cannot read off the code. See OPEN-E-4.

### 3.8 Resume reads no campaign state

`core/resume.py` contains **no** reference to `campaign`, `CAMPAIGN_ID`,
`wave_state`, `chain_stopped` or a queue. Its scope is a single chain
workspace throughout: the public entry point is
`restore_prior_state(workspace: str, …)` (`:1079`). The invariants lock
it validates has no campaign field either — `RunInvariants`
(`core/run_invariants.py:50-130`) pins data scope, health-gate
enablement, config hash and runtime identities, and nothing above the
chain.

A repo-wide grep for Python readers of `wave_state`, `chain_stopped` or
`queue_stopped` across `scripts/`, `core/`, `dashboard/` and `nodes/`
returns **nothing**. The only consumers are the shell runner's own
`chain_completed()` (`v19_queue_runner.sh:215-219`, a `grep` over
`$WAVE_STATE`) and the tests.

**Consequences.** (a) §20.7's validation item "resume reads only
matching campaign state" is satisfied for `core/resume.py` *by absence*
— it never reads campaign state at all, so it cannot read the wrong
campaign's. The campaign-level resume that *does* exist is entirely
shell: `chain_completed()` plus `V19_RESUME=1` plus the workspace-exists
guard at `:255`. That is the surface PR E must cover. (b) Changing the
wave-state record shape breaks no Python consumer — which is what makes
D-E-3 affordable.

### 3.9 Two more campaign-identity leaks in the launcher

```bash
# v19_queue_runner.sh:259 — the live-process guard excludes itself by literal name
if ps -eo args | grep -v grep | grep -v v19_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
```

A renamed or copied runner self-matches (its own argv contains
`$WS_ROOT/$RUN` once it is inside `launch_chain`'s screen command) and
refuses to launch. `v18r_queue_runner.sh:48` has the identical pattern
with its own name. Bounded fix: derive the exclusion from
`$(basename "${BASH_SOURCE[0]}")`.

The screen session name `siderius-$RUN` (`:251`, checked by
`chain_screen_alive()` `:231`) and the `--only` error text carry run
names that already include `CAMPAIGN_ID` — no collision. Recorded for
completeness.

### 3.10 Historical layouts on disk

Three distinct layouts must remain readable. None is produced by code
that PR E may rewrite in place.

| Layout | Producer | Shape |
|---|---|---|
| **V18r** | `v18r_queue_runner.sh:21-22` | `$WS_ROOT/v18r_queue_runner.log`, `$WS_ROOT/v18r_queue_state` (a plain text index, **not** JSONL) |
| **V19 flat-prefix** | `v19_queue_runner.sh:81-82` | `$WS_ROOT/<campaign_id>_queue_runner.log`, `$WS_ROOT/<campaign_id>_wave_state.jsonl` |
| **V19 Gate** | `v19_gate0_pair_runner.sh:59, 64` | `$GATE_ROOT/gate0_pair_summary.json`, `$GATE_ROOT/gate0_runner.log` |

Plus the archived stop evidence directory from the incident
(`v19r2_10iter_20260731_0750_stop_evidence/`), which is operator-created
and referenced only by the parent design doc.

The V18r runner is a historical launch surface that
`test_v19_queue_runner.py:261-269`
(`test_old_h100_profiles_untouched`) explicitly protects from V19
settings leaking into it. **PR E does not modify `v18r_queue_runner.sh`.**

### 3.11 §20.7's claims, checked

| §20.7 claim | Verdict |
|---|---|
| `v19_queue_runner.sh:80` hardcodes `MAX_CONC=2` | **CONFIRMED verbatim.** But it is inert — §3.6 |
| `:412-413` names the pair `arch`/`loss` | **NOT CONFIRMED at those lines.** At the time of audit the assignments were `:411` (`ARCH_RUN`) and `:412` (`LOSS_RUN`), with `:413` blank — off by one. Post-`fe51377c` they are `:450-451`. The naming is real; the citation was not |
| `<root>/<campaign_id>/control/STOP` | **Does not exist.** No path containing `control/` exists anywhere in the tree (grep excluding `runtime_control`, "control flow", "control/treatment") |
| `<root>/<campaign_id>/queue_state/` | **Does not exist as a directory.** Equivalent state exists as `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl` — §3.4 |
| `<root>/<campaign_id>/pair_summaries/` | **Does not exist.** Wave summaries are records inside the queue state; the only file named a pair summary is the Gate's — §3.5 |
| "All STOP readers; all STOP writers" | Readers: three (§3.1). **Writers: zero** (§3.2) — this changes where E3 can be enforced |
| "resume behaviour" | `core/resume.py` reads no campaign state (§3.8); the campaign-level resume is shell-only |
| "cleanup scripts" | **None exist.** No script in `scripts/` deletes or archives campaign control state; the incident archive was done by hand |
| PR E "touches launcher and path logic only" | **PARTLY.** No *existing* Python module is modified (§3.8), but the operator's 2026-08-04 rulings add two small new ones: a typed campaign identity and an atomic wave-summary writer (D-E-3, D-E-9). The launcher calls them, as it already calls `campaign_spend.py` (`:236-243`) and `pair_admission` (`:468`) |

### 3.12 Tests and docs that pin the current paths

Anything PR E changes must land with these, per the node/skill doc-sync
rule.

| File | What it pins |
|---|---|
| `tests/unit/sdsc_submission_scripts/test_c13_stop_semantics.py` | `:84` chain `ws/STOP`; `:99-104` `CHAIN_STOP_FILE` override; `:161-171` queue `QUEUE_STOP_FILE` sees a stop file; `:172-186` queue stop record JSON |
| `tests/unit/sdsc_submission_scripts/test_v19_campaign_pinning.py` | `:147-158` every run name derives from `CAMPAIGN_ID`; `:160-166` queue state + log carry it; `:167-176` two ids give disjoint names; `:192-224` spend is campaign-filtered |
| `tests/unit/sdsc_submission_scripts/test_v19_queue_runner.py` | `:79-81` `MAX_CONC == 2`; `:105, 163, 183, 277, 297` the literal `v19_wave_state.jsonl` filename; `:178-204` the wave-summary field list |
| `tests/unit/sdsc_submission_scripts/test_source_safe_entry.py` | `:60-84` sourcing creates no root and modifies no `gate0_pair_summary.json` / `v19_wave_state.jsonl`; `:88` probes `MAX_CONC` as the queue runner's "definitions are visible" witness |
| `tests/unit/sdsc_submission_scripts/test_v19_gate0_pair_runner.py` | `:214` `gate0_pair_summary.json` |
| `tests/unit/sdsc_submission_scripts/test_v19_chain_role_resolution.py` | the merged `role_for_run()` contract (`fe51377c`) — PR E must not regress it |
| `docs/running_chain_test.md` | `:111` `touch "$WORKSPACE/STOP"`; `:122` `CHAIN_STOP_FILE` table row; `:131` `touch "$WS_ROOT/STOP"`; `:135` `v19_wave_state.jsonl`; `:141` `QUEUE_STOP_FILE` table row |
| `docs/design/runtime_estimation_and_calibration.md` | `:3822-3853` the C13 operator surface narrative; `:3911` the Gate pair summary |
| `sdsc_submission_scripts/v19_queue_runner.sh:36-56` | the file's own header block, which documents `$WS_ROOT/v19_wave_state.jsonl` and "No other hidden state" |

### 3.13 Identifier validation, atomic writes, and pyright coverage

Added 2026-08-04 for the operator's rulings on identifier validation
(OPEN-E-8) and JSON emission. Searched before designing anything, as
instructed.

**Identifier validation — one precedent exists, and it is private.**

```python
# core/runtime_control/observation_store.py:38
_WRITER_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
```

It guards exactly this hazard — an identifier about to become a
**filename component** — in `_writer_path()` (`:188-194`), which raises
rather than joining an unvalidated string into `observations_{id}.jsonl`.
It is module-private and coupled to `ObservationStore`, so it is a
**pattern to follow, not a symbol to import**.

Nothing else in `core/` or `agent/schemas/` validates a run, campaign or
workspace identifier. The only other path-safety validator is
`PaperSource._check_local_path`
(`agent/schemas/literature_review.py:56-68`), which rejects a leading
`/` and any `..` segment for lit-review local paths — the right *checks*,
attached to the wrong *type*.

**The pattern alone is not sufficient**, and this is the load-bearing
detail: `^[A-Za-z0-9._-]{1,128}$` rejects the empty string, `/`, `\`,
control characters and absolute paths, but **it accepts `.` and `..`**,
because both are made only of characters in the class. A campaign id of
`..` would resolve `$WS_ROOT/../control/STOP` — an escape from the
campaign root, which is precisely what the operator's ruling forbids. The
validator PR E adds is therefore *the regex plus an explicit rejection of
`.` and `..`*.

**Atomic writes — two precedents, one stronger.**

| Precedent | Form |
|---|---|
| `core/campaign_artifacts.py:150-156` `write_campaign_manifest()` | `f"{path}.tmp"` → `json.dump` → `os.replace` |
| `core/runtime_control/calibration_registry.py:186-195` `_atomic_write()` | `tempfile.mkstemp(dir=path.parent)` → write → `flush` → `fsync` → `os.replace`, with cleanup on exception |

The registry form is the stronger one: a fixed `.tmp` suffix collides if
two writers race, and no `fsync` means a crash can leave a renamed but
empty file. **PR E follows the registry form.** Neither helper is
currently shared, so PR E's writer implements it locally rather than
reaching into `calibration_registry`'s private method — extracting a
shared helper would touch a PR C module and is deferred (FU-E-5).

**Pyright coverage — a placement constraint, not a preference.**

CI runs `uv run pyright` (`.github/workflows/ci.yml:43-44`) against
`pyrightconfig.json`. Two facts from that file decide where PR E's
Python may live:

- `"include"` lists `nodes`, `agent`, `core`, `execute_tools`,
  `ml_models`, `dashboard`, `env_validation`, `tools`, `scripts`,
  `workflows` — **`sdsc_submission_scripts` is not among them.** A
  Python file placed beside the launcher would be **invisible to the
  blocking type check.**
- `"exclude"` lists `tests` — **test helpers cannot be pyright-checked
  at all** under the current configuration.
- `"typeCheckingMode"` is **`"basic"`**, not `strict`. The instruction
  to "run strict pyright" is honoured as *"run the blocking CI pyright
  with the invocation that reproduces CI"*; the mode is whatever
  `pyrightconfig.json` says, and PR E does not change it.

Consequently PR E's Python goes in `core/` (the typed identity and
record models) and `scripts/` (the CLI the shell calls), both inside
`include`. This is the same split `campaign_spend.py` already uses:
a `scripts/` CLI invoked from the launcher (`:236-243`). The
test-coverage gap is recorded, not claimed away — see §9.

---

## 4. The path model

### 4.1 First: what `<root>` means — resolved

§20.7 writes `<root>/<campaign_id>/control/STOP`. `<root>` is ambiguous
against the current tree, because `WS_ROOT`'s default already ends in a
campaign-shaped segment (`.../SIDEREIS_DATA/v19`, `:78`).

Two readings:

- **(a) `<root>` = `WS_ROOT`.** Control state moves into a new
  `$WS_ROOT/$CAMPAIGN_ID/` subdirectory. Chain workspaces stay flat at
  `$WS_ROOT/<run_name>`.
- **(b) `<root>` = the parent of `WS_ROOT`,** i.e. `WS_ROOT` *is* the
  campaign directory and only `control/` is added under it.

**Reading (a) is correct, and the incident proves it.** The two
campaigns in §9.1 — `v19r2_10iter_20260731_0750` and
`v19r3_10iter_20260731_1842` — shared one `WS_ROOT` of `v19/`. Under
reading (b) they would share `WS_ROOT/control/STOP` and the defect would
survive the fix.

The consequence to state plainly: with the current default, the
resolved control path is
`/home/klz/Data/SIDEREIS_DATA/v19/<campaign_id>/control/STOP` — a
campaign segment under a campaign-*shaped* segment. That is not a bug;
`v19/` is a **campaign collection root** whose name happens to look like
a campaign. PR E relabels it as such in the code comment and the docs,
and does not change its value.

### 4.2 The model

```text
$WS_ROOT/                                 campaign COLLECTION root (unchanged)
├── <campaign_id>/                         campaign home  (NEW)
│   ├── control/
│   │   ├── campaign.json                  identity stamp   (NEW, written at launch)
│   │   └── STOP                           operator-created; read ONLY here
│   ├── queue_state/
│   │   ├── wave_state.jsonl               queue + wave + stop records
│   │   └── queue_runner.log
│   └── pair_summaries/
│       └── wave_<n>_<band>.json           one file per launched wave group
├── <run_name>/                            chain workspace  (UNCHANGED, flat)
│   ├── STOP                               chain stop  (UNCHANGED)
│   └── chain_stopped.json                 (UNCHANGED)
├── <campaign_id>_wave_state.jsonl         LEGACY — read-only, never written again
├── <campaign_id>_queue_runner.log         LEGACY — read-only
└── STOP                                   LEGACY GLOBAL — archived on sight, no authority
```

Resolution, in one place, with every value overridable:

```bash
CAMPAIGN_HOME="${CAMPAIGN_HOME:-$WS_ROOT/$CAMPAIGN_ID}"
CAMPAIGN_CONTROL_DIR="${CAMPAIGN_CONTROL_DIR:-$CAMPAIGN_HOME/control}"
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$CAMPAIGN_CONTROL_DIR/STOP}"
CAMPAIGN_STAMP="$CAMPAIGN_CONTROL_DIR/campaign.json"
QUEUE_STATE_DIR="${QUEUE_STATE_DIR:-$CAMPAIGN_HOME/queue_state}"
WAVE_STATE="$QUEUE_STATE_DIR/wave_state.jsonl"
LOGF="$QUEUE_STATE_DIR/queue_runner.log"
PAIR_SUMMARY_DIR="${PAIR_SUMMARY_DIR:-$CAMPAIGN_HOME/pair_summaries}"
```

`QUEUE_STOP_FILE` keeps its name and its override so existing operator
muscle memory, the docs table at `docs/running_chain_test.md:141`, and
`test_c13_stop_semantics.py:161-171` all keep working. Only its
**default** moves.

**The campaign stamp** (`control/campaign.json`) is what makes E3
enforceable given §3.2's finding that nothing writes a STOP file:

```json
{"campaign_id": "v20a", "created_at": "…Z", "ws_root": "…",
 "campaign_home": "…", "runner": "v19_queue_runner.sh", "runner_pid": 12345}
```

Written once at launcher startup if absent. If present and its
`campaign_id` differs from the resolved `CAMPAIGN_ID`, the launcher
**refuses to start, before any directory is created and before any
chain launches** — the same posture as the existing workspace-exists
guard (`:255`) and screen-alive guard (`:258`).

### 4.3 Backward-compatibility rules

**BC-1 — nothing on disk is moved, rewritten or deleted by shipped
code.** Historical layouts (§3.10) stay exactly where they are.

**BC-2 — legacy state is readable, never authoritative.** The
completion check `chain_completed()` is the one place a legacy file
still has to be *read*, so that a campaign interrupted before PR E can
resume without relaunching completed chains. It reads
`$WAVE_STATE`, and if the new file does not exist, falls back to
`$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl` — **read-only, and only for
the matching campaign id.** All writes go to the new path.

**BC-3 — a legacy global STOP has no authority, and is not deleted.**
At startup, if `$WS_ROOT/STOP` exists, the launcher:
1. logs it explicitly, naming the file and its mtime;
2. records a `legacy_global_stop_observed` line in the new queue state;
3. **continues.**

It does not stop, and it does not remove the file. Silently ignoring it
would destroy the operator's ability to reconstruct the 08:17 incident;
honouring it would reproduce the defect. Logging it is the only option
that does neither. Archiving it stays a manual operator act — see D-E-5.

**BC-4 — the chain stop path is untouched.** `${WORKSPACE}/STOP`,
`CHAIN_STOP_FILE`, `chain_stopped.json`, exit code 99, the traps, the
`>= 128` signalled-child rule: byte-identical.

**BC-5 — a fresh campaign requires no cleanup.** The merge criterion.
Given BC-1 to BC-3, a new `CAMPAIGN_ID` under an existing `WS_ROOT`
starts with an empty `control/` and cannot observe any predecessor's
armed state.

### 4.4 What deliberately does not move

- **Chain workspaces** stay at `$WS_ROOT/<run_name>`. Moving them to
  `$CAMPAIGN_HOME/<run_name>` would break `campaign_spend.py:58`
  (`root.glob(f"{campaign_id}_*/token_usage.jsonl")`), every
  historical path in the reports, and the resume guard at `:255` — for
  no isolation benefit, since run names already carry the campaign id.
  See OPEN-E-2.
- **`EXIT_DIR` markers** stay in `/tmp` (§3.4).
- **`v18r_queue_runner.sh`** is not modified (§3.10).
- **`scripts/bg_gpu_sampler.sh`** is not modified (D-E-8).

---

## 5. Design deviations

Each requires an explicit operator decision. `[x]` = approved,
`[ ]` = pending.

### D-E-1 — Directory scoping replaces prefix scoping, and that is a mechanism change

- [ ] Approved  [ ] Rejected  [ ] Modified

§20.7 asks for `<root>/<campaign_id>/…`. The tree already achieves
partial isolation by a *filename prefix* in a flat root (§3.4), and
`test_v19_campaign_pinning.py:160-166` asserts that mechanism by name.

The minimal fix for §1's defect is one line: give `QUEUE_STOP_FILE` the
same prefix treatment (`$WS_ROOT/${CAMPAIGN_ID}_STOP`). That would close
the incident with a two-character diff.

**Proposal: take the directory model anyway.** Rationale:

1. Prefix scoping has already failed once *by omission* — an author has
   to remember to interpolate `${CAMPAIGN_ID}` into every new path, and
   the one time someone didn't, a campaign was blocked. A directory
   boundary makes the default safe: a path built without thinking lands
   inside the campaign home.
2. §20.7's third path (`pair_summaries/`) has no prefix equivalent
   (§3.5) and needs a directory regardless.
3. The `control/` boundary is what lets E5 be tested cheaply: create two
   campaign homes, arm one, prove the other launches.

**Cost, stated honestly:** it is a bigger diff than the defect requires,
it changes a mechanism two tests assert, and it needs BC-2's legacy
read-back. If the operator prefers the two-character fix, D-E-1 is the
decision point to say so — the rest of this document then reduces to
D-E-6, D-E-4 and the E5 test.

### D-E-2 — `<root>` = `WS_ROOT`; chain workspaces stay flat

- [ ] Approved  [ ] Rejected  [ ] Modified

Per §4.1 and §4.4. The alternative reading of §20.7 would not fix the
incident, because the two campaigns that collided shared one `WS_ROOT`.

### D-E-3 — The wave record becomes chain-list-shaped; `MAX_CONC` is retired as a label

- [ ] Approved  [ ] Rejected  [ ] Modified

§20.7 requires that "a campaign with one chain, or five, or chains named
for something other than architecture and loss, must not require a
schema change". The audit (§3.6) shows the binding constraint is
`record_wave_summary()` (`:226-229`), not `MAX_CONC` (`:80`), which
gates nothing.

**Proposal.**

```json
{"wave_summary": 1, "band": "15-19", "campaign_id": "v20a",
 "chains": [
   {"run": "v20a_arch_15_19", "role": "arch", "pid": "…", "exit": 0},
   {"run": "v20a_loss_15_19", "role": "loss", "pid": "…", "exit": 0}],
 "arch_run": "v20a_arch_15_19", "loss_run": "v20a_loss_15_19",
 "arch_exit": 0, "loss_exit": 0,
 "start": "…", "end": "…", "disposition": "complete"}
```

The `chains` array is the generic shape: N entries, role supplied by the
ROSTER's existing fourth field rather than by position. The six
`arch_*`/`loss_*` keys are **retained and labelled a compatibility
mirror**, emitted only when the wave has exactly two chains with those
roles. Rationale: no Python consumer exists (§3.8), but the operator
reports and `test_v19_queue_runner.py:178-204` read those key names, and
§20.1's minimal-change principle says a schema addition beats a schema
replacement. A follow-up **FU-E-1** removes the mirror once the operator
report tooling is confirmed to read `chains`.

`MAX_CONC` is **deleted**, not parameterized — a variable that gates
nothing but appears in a log line is worse than absent, because it
reads as a control. The log line at `:416` reports
`chains_per_wave=${#NEEDED[@]}`, a measured fact.

Consequently `test_v19_queue_runner.py:79-81` is deleted (it asserts a
value that controls nothing — a decoration test by CLAUDE.md's rule),
and `test_source_safe_entry.py:88`'s `MAX_CONC` probe is repointed at
`CAMPAIGN_HOME`, which is a real definition. **The class of defect
`test_exactly_two_chains_per_wave_max_conc` was reaching for — "a wave
must not launch more chains than intended" — is preserved by a new test
asserting that the wave loop launches exactly the chains the ROSTER
names for that band**, which is the property that was actually true.

*Scope note.* This makes the **state schema** N-chain-capable. It does
**not** make the *launcher* N-chain-capable: `:450-451` still builds two
names and `WAVES` still pairs them. That is deliberate — an N-chain
scheduler is a concurrency change with GPU-admission consequences (the
pair ceiling, PR B), and §20.7 puts it out of scope. Recorded as
**FU-E-2**.

> **EMISSION MECHANISM — RESOLVED by operator ruling, 2026-08-04:
> delegate the JSON writing to Python.**
>
> The eleven-positional `printf` (`:226-229`) is **not** extended. A
> variable-length chain roster is handed to a small Python writer that
> takes typed/structured input and writes the file **atomically**.
>
> This is not a shell rewrite. It moves **one responsibility** that has
> outgrown positional formatting, and it follows a precedent this file
> already set for the same reason: `campaign_spend()` (`:236-243`)
> delegates to `scripts/campaign_spend.py` precisely because a shell
> scan of a nested JSON field silently inflated the number a cost cap
> depended on. A shell `printf` that must now emit a nested array is the
> same hazard one step further along.
>
> Placement is forced by §3.13: the writer goes under `scripts/` (inside
> `pyrightconfig.json`'s `include`), with the record models and the
> atomic-write helper in `core/`. A module beside the launcher in
> `sdsc_submission_scripts/` would be invisible to the blocking type
> check.
>
> Atomicity follows `calibration_registry.py:186-195` — `mkstemp` in the
> target directory, `flush`, `fsync`, `os.replace` — not the weaker
> fixed-`.tmp` form (§3.13).
>
> The record is a Pydantic model, so CLAUDE.md's "never pass raw output
> to execution without validation" applies in the direction that matters
> here: the shell hands the writer structured arguments, and a malformed
> wave record fails at the schema rather than producing unparseable
> JSON on disk.

### D-E-4 — The Gate pair summary is scoped and stamped; the Gate gains no stop channel

- [ ] Approved  [ ] Rejected  [ ] Modified

Two halves.

**Do:** `SUMMARY` (`v19_gate0_pair_runner.sh:59`) derives from
`GATE_RUN_PREFIX` like every other name the file builds
(`$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`), and the record's
hardcoded `"gate": "v19_gate0"` (`:290`) becomes the resolved prefix.
This closes the verified overwrite hazard the file documents against
itself at `:379-382`. The runner log (`:63`) gets the same treatment.

**Do not:** add a stop file channel to the Gate runner. It has none
today — its only trap is `trap write_summary EXIT` (`:304`) and its only
bound is `WALL_CAP_SECONDS` (`:48`). Adding one would be a *stop
semantics change*, explicitly out of scope per §20.7. Flagged as
OPEN-E-3 rather than silently either done or dropped.

### D-E-5 — A legacy global STOP is logged and recorded, never honoured and never deleted

- [ ] Approved  [ ] Rejected  [ ] Modified

Per BC-3. Three candidate behaviours were considered: honour it
(reproduces the defect), delete/archive it automatically (destroys
evidence and violates §20.7's "no destructive cleanup"), or observe and
record it. The third is the only one that satisfies both E2 and the
stop-condition "migration would require deleting existing evidence".

The observation is written into the new queue state as a first-class
record, so "why did this campaign start when a STOP file existed?" has a
persisted answer rather than a log-text one — the same principle
`record_queue_stop()` already applies (`:204-211`).

### D-E-6 — The `v19_loss_` role-derivation defect — **DONE, MERGED `fe51377c`**

- [x] **Approved as a separate hotfix PR landing first** — merged
      2026-08-04, PR #165, merge commit `fe51377c`
- [ ] ~~Approved as part of PR E~~
- [ ] ~~Rejected~~

§3.7 documented a live defect: the wave loop stripped a literal
`v19_loss_` prefix, so under any other `CAMPAIGN_ID` both chains of every
wave launched with the arch advice file. V20 launches with a new campaign
id by definition (parent doc §14, "new ID, run names, workspaces,
report, queue state, cold start"), so **the V20 launch would have hit
this on wave 1.**

The recommendation was to land it as its own one-commit hotfix PR before
PR E, on the standing rule that production hotfixes get their own PR and
that a launch blocker must not wait on D-E-1's mechanism decision. **The
operator took that route, and the shipped fix is stronger than the one
proposed here.**

The proposal was "look the run up in the ROSTER instead of re-deriving
it". The merged fix does that and adds the part this deviation did not
state: it **deletes the implicit name-encodes-role protocol** and
**fails closed**. `role_for_run()` (`:134-170`) returns non-zero on an
unknown run (`:169`) or an empty role (`:164`); the wave loop records
`unresolvable_chain_role` and stops (`:498-503`) rather than defaulting
to `arch`. Defaulting is how the original defect stayed invisible, so
removing the default is the actual repair.

Evidence: 13 tests in
`tests/unit/sdsc_submission_scripts/test_v19_chain_role_resolution.py`,
mutation-proved against three mutations — including `s/v19_/v20_/`,
the non-fix that would have deferred the same defect to V21.

**Consequences for PR E.** The role work is no longer PR E's. PR E
inherits the clean base and must not regress it: the role-resolution
test module joins the parity set in §3.12, and no PR E commit may
reintroduce a name-derived role. `--only` remains the second reader of
ROSTER field 4 (`:402`) and is unchanged.

### D-E-7 — The self-exclusion in the live-process guard derives from the script name

- [ ] Approved  [ ] Rejected  [ ] Modified

`:259`'s `grep -v v19_queue_runner` becomes
`grep -v "$(basename "${BASH_SOURCE[0]}")"`. Small, in-passing, and
directly related: it is the same class of "the current campaign's name
is baked into generic logic" defect as D-E-6. `v18r_queue_runner.sh:48`
carries the identical pattern and is **not** touched (§3.10).

### D-E-8 — The `bg_gpu_sampler.sh` STOP collision is recorded, not fixed

- [ ] Approved  [ ] Rejected  [ ] Modified

`scripts/bg_gpu_sampler.sh` reads `$OUTDIR/STOP` (`:48`, `:96`) — an
unrelated mechanism with an identical filename. Today, a diagnostic
sampler pointed at `$WS_ROOT` would arm the queue's stop file the moment
an operator stopped the sampler. Moving the queue stop to
`control/STOP` removes the collision as a side effect. The sampler is
not modified: it is a diagnostic tool with its own contract, and
renaming its control file would break documented operator usage
(`bg_gpu_sampler.sh:38, 94`) for no remaining benefit.

### D-E-9 — A validated typed campaign identity, because the id becomes a path component

- [x] **Approved — operator ruling, 2026-08-04** (resolves OPEN-E-8)

**The ruling.** `campaign_id` must be rejected if it is empty, contains
`/`, contains `..`, is an absolute path, contains control characters or
any path separator, or is any value that could escape the campaign root.

**What the audit found** (§3.13, searched before designing anything).
One precedent exists — `_WRITER_ID_RE` in
`core/runtime_control/observation_store.py:38`, guarding the identical
hazard for `observations_{id}.jsonl`. It is module-private and coupled
to `ObservationStore`, so PR E **reuses the pattern, not the symbol**.
`PaperSource._check_local_path`
(`agent/schemas/literature_review.py:56-68`) has the right checks
(`/`-prefix, `..` segments) attached to the wrong type.

**What is taken.** A narrow typed identifier in `core/`, validated as:

```text
re.fullmatch(r"[A-Za-z0-9._-]{1,128}", campaign_id)   # from _WRITER_ID_RE
and campaign_id not in {".", ".."}                    # the gap it leaves
```

The second line is not decoration. `^[A-Za-z0-9._-]{1,128}$` **accepts
`..`** — both characters are in the class — so the borrowed pattern
alone would admit `$WS_ROOT/../control/STOP`, an escape from the
campaign root and exactly what the ruling forbids. Every other
prohibited form (empty, `/`, `\`, control characters, absolute paths,
NUL) is already rejected by the character class and the length bound.

**Where it is enforced.** At launcher startup, **before** the resolved
campaign directory is created — i.e. in E-C2, at the first moment the id
becomes a real path component, not in E-C3 with the stamp guard. By then
the directory already exists.

**Why a type and not a shell `case`.** The same validated identity is
needed by three writers (the stamp, the wave record, the pair summary),
and the ruling asks for a typed identifier. One Pydantic model is one
source of truth; three shell globs are three places to forget the `..`
case. The launcher already calls Python for decisions —
`campaign_spend.py` (`:236-243`) and `pair_admission` (`:468`).

**Deferred**: extracting `_WRITER_ID_RE` so `observation_store.py`
consumes the shared identity would touch a PR C module and is outside
PR E's bounded scope — **FU-E-4**.

---

## 6. Checkpoints

Tracker. `[ ]` = not started. No checkpoint may be marked done without
the evidence named in its row.

### E1 — Path model

- [ ] `CAMPAIGN_HOME` / `CAMPAIGN_CONTROL_DIR` / `QUEUE_STATE_DIR` /
      `PAIR_SUMMARY_DIR` resolved in exactly one block, each overridable
- [ ] `QUEUE_STOP_FILE` default is `$CAMPAIGN_CONTROL_DIR/STOP`; the
      `QUEUE_STOP_FILE` env override still works
- [ ] `WAVE_STATE` and `LOGF` under `queue_state/`
- [ ] Wave summaries written to `pair_summaries/wave_<n>_<band>.json`
      **and** appended to the queue state (both, so no existing
      operator query loses its source)
- [ ] Gate pair summary and runner log derive from `GATE_RUN_PREFIX`
- [ ] **Evidence**: a test enumerates every authority-bearing path the
      runner resolves and asserts each contains the campaign id; it
      fails if a new path is added without it
- [ ] **Evidence**: the wave/pair record is produced by the typed
      atomic writer (D-E-3) and parses as JSON in the two-chain,
      three-chain and aborted-launch cases

### E2 — Backward compatibility

- [ ] `chain_completed()` falls back to the legacy flat-prefix wave
      state, read-only, matching campaign id only
- [ ] Legacy `$WS_ROOT/STOP` is observed, logged, recorded, and does
      **not** stop the launch
- [ ] No shipped code path deletes, moves or rewrites any legacy file
- [ ] V18r layout untouched; `v18r_queue_runner.sh` not modified
- [ ] **Evidence**: a test with a legacy tree on disk proves (a) a
      completed chain in the legacy state is still skipped, (b) the
      legacy global STOP does not block, (c) every legacy file is
      byte-identical and mtime-identical after the run

### E3 — Campaign mismatch protection

- [ ] `campaign_id` is validated before it becomes a path component —
      empty, `/`, `\`, `..`, `.`, absolute and control-character forms
      all refused (D-E-9)
- [ ] `control/campaign.json` written at startup when absent
- [ ] A stamp naming a different `campaign_id` aborts **before** any
      directory is created and before any chain launches
- [ ] The refusal names both ids and the stamp path
- [ ] **Evidence**: a test that pre-writes a foreign stamp and asserts
      non-zero exit, the diagnostic text, and that no chain was launched
      and no state file was written

### E4 — Stop semantics preserved

- [ ] `test_c13_stop_semantics.py` passes unchanged except for the two
      path expressions it constructs
- [ ] Chain stop: after current iteration, `chain_stopped.json`,
      `respawn: false`, exit 99 — unchanged
- [ ] Queue stop: current wave finishes, no further wave, `queue_stopped`
      record, exit 99 — unchanged
- [ ] Signalled child (`>= 128`) still ends the loop; ordinary non-zero
      still continues
- [ ] **Evidence**: a mutation proof — revert the path change alone and
      show the C13 suite still passes, i.e. the C13 guarantees are
      genuinely independent of where the file lives

### E5 — Recovery validation

- [ ] Two synthetic campaigns under one root, launched and stopped
      independently, with `launch_chain` stubbed — no GPU, no API
- [ ] Campaign A stopped → campaign B launches
- [ ] Wrong-campaign STOP ignored; correct-campaign STOP honoured
- [ ] Both campaigns' state files coexist and neither is written by the
      other's runner
- [ ] A legacy global STOP present throughout, and never honoured
- [ ] **Evidence**: one test module, `test_multi_campaign_isolation.py`,
      that fails if `QUEUE_STOP_FILE`'s default is reverted to
      `$WS_ROOT/STOP`

---

## 7. Genericization impact and in-passing refactor

Binding per `v20_priorities.md` §1.4. The seven questions of §1.4.5.

**1. Which touched modules are generic infrastructure?**

`sdsc_submission_scripts/_chain_common.sh` — the chain loop, stop
channels and stop record are campaign-, task- and dataset-agnostic
today, and PR E does not change them. The *path-resolution block* PR E
adds to `v19_queue_runner.sh` is generic campaign-control
infrastructure: it knows about a collection root, a campaign identity
and a control directory, and nothing else.

The two new Python modules are generic infrastructure by construction
and by placement. The typed campaign identity (D-E-9) knows only that an
identifier will become a path component; the wave-record writer (D-E-3)
knows only that a wave has N chains with roles. Neither imports a
dataset, a task, a metric or a hardware module, and a test asserts that
(§1.4.6, "generic runtime-control tests do not import TIDMAD-specific
modules"). Both live under `core/` and `scripts/`, which §3.13 shows is
also what puts them inside the blocking type check.

**2. Which are task-, dataset-, metric- or hardware-specific?**

Task/experiment-shaped, and correctly so: the `WAVES` band definitions
(`:115-120`), `file_order_for_scope()` (`:178-186`), the advice file
name (`:310`), the `arch`/`loss` role vocabulary, and every pinned
scientific flag in the launch block (`:270-311`), which
`test_v19_campaign_pinning.py:37-67` deliberately freezes. **PR E moves
none of these.** They describe what this campaign measures; per §1.4.4
they are current-campaign configuration, not framework rules, and they
are already labelled as such by the ROSTER's fourth field and by the
pinning test's docstring.

Hardware-owned: `PAIR_CAP_GIB` (`:110`) and the pair-admission call
(`:468`). Out of scope; owned by PR B.

**3. Does the PR introduce any new hardcoded assumption?**

Target: none. Three values are introduced and all three are configured
policy with an environment override and a documented default:
`CAMPAIGN_HOME`, `CAMPAIGN_CONTROL_DIR`, `QUEUE_STATE_DIR`,
`PAIR_SUMMARY_DIR`. The directory names `control`, `queue_state`,
`pair_summaries` are structural literals inside those defaults — the
same class as `iter_NNN` in the chain layout — and are overridable one
level up.

The `arch`/`loss` mirror keys in D-E-3's record are **explicitly
labelled a compatibility mirror with a removal follow-up (FU-E-1)**,
which is what §1.4.4 requires of a compatibility default: kept, named,
and not presented as a universal rule.

**4. Which existing hardcoded assumption does it remove or move behind
configuration?**

| Removed | Where | Class (§1.4.4) |
|---|---|---|
| `v19_loss_` literal in role derivation | pre-`fe51377c` wave loop | **unacceptable hardcoding** — **already removed** by PR #165, ahead of PR E (D-E-6). The implicit protocol is gone, not the prefix updated |
| `v19_queue_runner` literal in the process guard | `:259` | unacceptable hardcoding — fixed (D-E-7) |
| `MAX_CONC=2` | `:80` | campaign policy that gates nothing — deleted (D-E-3); this closes **FU-B-7**, deferred from PR B |
| `arch`/`loss` as the *only* expressible chain shape in the state schema | `:226-229` | campaign + task shape — role now comes from the ROSTER, count is unbounded (D-E-3) |
| `"gate": "v19_gate0"` literal in the pair summary | gate runner `:290` | campaign identity — derives from `GATE_RUN_PREFIX` (D-E-4) |
| `gate0_pair_summary.json` fixed filename | gate runner `:59` | campaign identity — derives from `GATE_RUN_PREFIX` (D-E-4) |
| `WS_ROOT` implicitly meaning "the campaign" | `:78` | relabelled a **campaign collection root** in code comment and docs; value unchanged |
| An unvalidated `campaign_id` used as a filename component | `:81-82`, `:124-131` | generic infrastructure policy — becomes a validated typed identifier before it becomes a *directory* component (D-E-9) |
| Eleven-positional `printf` as the wave-record encoder | `:226-229` | generic infrastructure policy — a positional shell formatter cannot express a variable-length roster; moved to a typed atomic writer (D-E-3) |

**5. Which assumptions remain, and why are they deferred?**

| Remaining | Why deferred | ID |
|---|---|---|
| `arch_*`/`loss_*` mirror keys in the wave record | operator reports read them; removal needs a reader audit | **FU-E-1** |
| The launcher builds exactly two chain names per wave (`:450-451`) | an N-chain scheduler changes GPU admission (pair ceiling, PR B) — a concurrency change, out of §20.7's scope | **FU-E-2** |
| `WAVES`, bands, `file_order_for_scope()`, advice filenames | current campaign configuration, correctly placed, and frozen by the pinning test | n/a — §1.4.4 "keep; label as an example" |
| `v18r_queue_runner.sh`'s own `MAX_CONC=4` and name literals | a historical launch surface protected from change by `test_v19_queue_runner.py:261-269` | **FU-E-3** |
| `EXIT_DIR` markers in `/tmp` | run names already carry campaign id; no collision demonstrated | n/a |
| `bg_gpu_sampler.sh`'s `STOP` filename | different mechanism, documented operator contract | D-E-8 |
| `_WRITER_ID_RE` stays private to `observation_store.py` instead of consuming the shared identity | extracting it touches a PR C module, outside PR E's bounded scope | **FU-E-4** |
| Atomic write is implemented locally rather than shared with `calibration_registry._atomic_write` | same reason — reaching into a PR C module's private method is worse than one local copy | **FU-E-5** |
| `pyrightconfig.json` excludes `tests` and runs `basic`, not `strict` | a type-checking policy change is not PR E's causal claim | **FU-E-6** |

**6. What compatibility surface preserves existing TIDMAD behaviour?**

BC-1 to BC-5 in §4.3. Concretely: `WS_ROOT`'s value is unchanged; every
run name, band, file order, advice file and pinned scientific flag is
unchanged; `QUEUE_STOP_FILE` and `CHAIN_STOP_FILE` keep their names and
overrides; legacy wave state is still read for completion; and no file
on disk is touched. A V19 campaign interrupted before this PR resumes
without operator intervention.

**7. What tests prove generic infrastructure does not depend on a
specific dataset, task, metric or hardware model?**

- The E5 isolation test uses **two synthetic campaign ids that are not
  `v19` or `v20`** and a stubbed launcher, so it exercises the path
  layer with no dataset, no GPU, no advice file and no band semantics.
- The E1 path-enumeration test asserts campaign identity for *every*
  resolved path under a synthetic id — it fails on a new unscoped path
  regardless of what that path is for.
- A **non-default configuration** test (§1.4.6 requirement) drives the
  runner with `CAMPAIGN_HOME`, `QUEUE_STATE_DIR` and `PAIR_SUMMARY_DIR`
  all pointed outside `WS_ROOT`, proving the defaults are defaults.
- A role test asserts that a ROSTER entry with a role that is neither
  `arch` nor `loss` produces a correct record — the direct proof that
  D-E-3 removed the two-role assumption from the state schema.
  (The launcher-side half of this was already proved by `fe51377c`'s
  `test_v19_chain_role_resolution.py`.)
- The campaign-identity tests use ids that are neither `v19` nor `v20`
  and assert on the *validation rules*, not on any campaign's name.
- A test asserts the two new `core/` and `scripts/` modules import
  nothing task-, dataset- or hardware-specific.

**§1.4.6 shared checklist**

Implementation
- [ ] No new TIDMAD-specific constant enters generic infrastructure
- [ ] No task-specific prompt, metric, file layout, model family or
      hardware ceiling embedded in the generic path layer
- [ ] New policy values enter through documented, overridable variables
- [ ] Task-specific assumptions in touched code move behind the ROSTER
      boundary where bounded (roles), stay put where not (bands)
- [ ] Backward compatibility for the current TIDMAD workflow explicit
      (BC-1..BC-5)

Validation
- [ ] Tests use synthetic campaign ids and stubbed launches
- [ ] At least one test exercises a non-default configuration
- [ ] No test assumes a GPU, a physical device index, or a dataset
- [ ] Band/advice/scientific-flag tests remain in the pinning module
- [ ] No new import of a TIDMAD-specific module anywhere
- [ ] Pyright run with the CI-reproducing invocation on every
      code-bearing commit; its coverage gaps (`tests` excluded,
      `sdsc_submission_scripts` not in `include`) recorded, not
      claimed away
- [ ] Every machine-state-touching test run **both** locally and on CI

Merge criteria
- [ ] Genericization section completed (this section)
- [ ] No unexplained new hardcoded assumption
- [ ] New policy is overridable and its resolved value is logged
- [ ] TIDMAD behaviour preserved through defaults, not special cases
- [ ] FU-E-1..FU-E-6 filed

Decomposition (§1.5)
- [ ] `main()` in `v19_queue_runner.sh` gains no new responsibility —
      path resolution is a definitions-block concern, campaign
      validation is one guard function called once, alongside the
      existing `chain_completed` / `chain_screen_alive` guards
- [ ] Each new shell function has one documented responsibility and
      writes only to paths derived from its own arguments
- [ ] The two new Python units have explicit inputs, a typed result, a
      documented responsibility and bounded side effects — the writer
      does not read outer state, and the identity validator decides
      nothing beyond validity
- [ ] Behavioural parity proven: wave ordering, stop timing, exit codes,
      the `--only` path and the source-safe guard all unchanged
- [ ] A reachability test fails if the runner reads a stop file the
      resolver did not produce
- [ ] No behaviour changed "while refactoring"

---

## 8. Commit plan

Each commit is independently revertible, **independently green**, and
lands with its own tests. The table is the index; the E-C1..E-C7
subsections below are the implementation contract.

| # | Commit | Content | Checkpoint evidence |
|---|---|---|---|
| **E-C1** | Campaign path resolver | The resolution block (§4.2); **no consumer changes** — provably behaviour-neutral | pre-E1 |
| **E-C2** | Queue runner consumes the resolver, **with the legacy read-back** | `QUEUE_STOP_FILE`, `WAVE_STATE`, `LOGF` move; directory creation; id validation; `chain_completed()` fallback; legacy-global-STOP observation; D-E-7 | E1 + E2 |
| **E-C3** | Campaign stamp and mismatch guard | `control/campaign.json`; refusal before any side effect | E3 |
| **E-C4** | Wave record and pair summaries | Typed atomic Python writer; `chains` array + mirror; per-wave files; `MAX_CONC` deleted | E1 |
| **E-C5** | Gate pair summary scoping | `GATE_RUN_PREFIX` derivation for `SUMMARY`, `RUNNER_LOG`, `"gate"` | E1 |
| **E-C6** | Multi-campaign isolation test | `test_multi_campaign_isolation.py` | E5 |
| **E-C7** | Doc sync (last, per the operator rule) | Every documented variable and default quoted against merged source | merge blocker |

**Two structural rulings are baked into this table.**

*E-C0 is gone.* The role-derivation fix landed ahead of PR E as its own
hotfix — `fe51377c`, PR #165 (D-E-6). It is no longer PR E's work. Its
audit and its history stay in §3.7 and D-E-6 because they are the reason
the fail-closed posture exists, but no commit here reimplements it. PR E
inherits it and must not regress it.

*E-C2 and the old E-C4 are one commit.* **Operator ruling, 2026-08-04:
do not knowingly commit a red intermediate.** Moving the wave-state path
and updating its read-back and its legacy test are one behavioural unit
— the read-back is the *reason* the move is safe, and splitting them
separated a change from its justification while leaving
`test_completed_only_selection_skips_and_exits_clean`
(`test_v19_queue_runner.py:294-304`) red across two commits. They now
land together, and E-C2's acceptance criteria require the full suite to
be green **at that commit**, not at a later one. This resolves OPEN-E-9
as option (b). Everything after renumbers down by one.

**A note on E4.** No single commit "does" E4 (stop semantics preserved).
It is a property every commit must not break, and it is discharged by
E-C2's and E-C6's parity evidence plus the E4 mutation proof (§6). It is
listed in each commit's acceptance criteria rather than owning a commit.

### Standing verification rules — every commit

These apply to §7 of every subsection below and are not restated there.

**Pyright is run before every push, with the invocation that reproduces
CI**, not with a bare `pyright`:

```bash
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

CI runs `uv run pyright` (`.github/workflows/ci.yml:43-44`) over
`pyrightconfig.json`. **PR C shipped 44 pyright errors latent behind
2,416 passing tests**, so a green pytest run is not evidence of a green
type check. Three coverage facts from §3.13 decide what this means per
commit:

| Commit content | What pyright covers |
|---|---|
| Shell only (E-C1, E-C2, E-C3, E-C5) | Nothing new. Run it anyway, to prove **no regression** — the errors PR C shipped were in untouched files |
| New Python in `core/` or `scripts/` (E-C2's validator, E-C4's writer) | **Load-bearing.** These paths are inside `"include"` |
| Test helpers (E-C6) | **Not covered** — `pyrightconfig.json` excludes `tests`. Recorded as a limitation, never claimed as checked |

`"typeCheckingMode"` is `"basic"`, not `strict`. PR E does not change it;
"strict pyright" is honoured as "the blocking CI pyright, reproduced
exactly".

**A locally-green suite is not a green CI.** PR C's registry test passed
on this box and failed on a runner. Every PR E test touches machine
state by construction — `$HOME`, `/tmp` (`EXIT_DIR`, `:79`), `screen`,
`ps`, and absolute paths — so each commit records **both**:

- [ ] local run: __
- [ ] CI run on the pushed head: __

A test that was run only locally is reported as *locally green, CI
pending*. It is never reported as passing.

**Not-run rule.** Any command that could not be executed in this
environment is recorded as **not run**, with the reason. It is never
reported as passed.

---
### E-C1 — Campaign path resolver (behaviour-neutral)

#### 1. Goal

Introduce the single resolution block of §4.2 — `CAMPAIGN_HOME`,
`CAMPAIGN_CONTROL_DIR`, `QUEUE_STATE_DIR`, `PAIR_SUMMARY_DIR`,
`CAMPAIGN_STAMP` — **without changing any value any consumer reads.**

**Why its own commit.** The path model is the part most likely to be
revised in review (D-E-1 is still open). Landing the resolver with every
default pinned to today's location makes the *shape* reviewable while
proving, by test, that nothing moved yet. If review rejects the
directory model, this commit reverts alone and E-C2..E-C6 never land.

#### 2. Scope

**Changes**: `sdsc_submission_scripts/v19_queue_runner.sh` — the
definitions block between `:78` and `:110`. New variables only.

**Non-goals.** `QUEUE_STOP_FILE` (`:104`), `WAVE_STATE` (`:82`) and
`LOGF` (`:81`) keep their current definitions in this commit. No
`mkdir`. No consumer reads a new variable yet. No campaign-id
validation — that arrives with the directory in E-C2, where the id
first becomes a path component.

**Must stay unchanged**: `WS_ROOT`'s value (`:78`); `EXIT_DIR` (`:79`);
`role_for_run()` (`:134-170`, merged `fe51377c`); the source-safe guard
(`:558`), which `test_source_safe_entry.py:46-59` asserts creates no
directory when the file is merely sourced — **this commit must not add
a `mkdir` at definition scope, or that test fails.**

**Dependencies**: none. `fe51377c` is already on `master`.

#### 3. Implementation plan

- [ ] Add the five variables in the definitions block, each in the
      `"${NAME:-<default>}"` form so every one is overridable
- [ ] Set each default to **today's** effective location, not the target
      location, so the commit is a no-op:
      `CAMPAIGN_HOME="${CAMPAIGN_HOME:-$WS_ROOT}"` and the rest derived
      from it, reproducing `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl`
      etc. exactly
- [ ] Document in-file which line each default will move to in E-C2, so
      the two commits are readable as a pair
- [ ] Confirm placement is after `CAMPAIGN_ID` (`:68`) and after
      `WS_ROOT` (`:78`) — both are read by the defaults
- [ ] Verify nothing at definition scope touches the filesystem

#### 4. Validation plan

**Unit**
- [ ] Sourcing the runner and echoing each new variable yields exactly
      today's paths
- [ ] Each variable honours its environment override

**Integration / pseudo**
- [ ] `test_source_safe_entry.py` passes unchanged — sourcing still
      creates nothing and modifies nothing
- [ ] `test_v19_chain_role_resolution.py` passes unchanged — the
      inherited hotfix is not disturbed

**Negative / invalid input**
- [ ] None applicable. The commit adds inert definitions; invalid-input
      handling is E-C2's (D-E-9) and E-C3's. Stated rather than left
      blank, so the absence is a decision

**Backward compatibility / default parity**
- [ ] A parity test asserting each resolved path equals its current
      literal form, so E-C2's move is a visible, reviewed diff rather
      than an accident

**Real Gate**
- [ ] None. No GPU, no training, no LLM. **No test in this commit may
      invoke `run_chain.sh` with real training; a proposal to do so
      needs separate operator approval and does not run here.**

#### 5. Acceptance criteria

- [ ] `V19_QUEUE_NO_MAIN=1 source …; echo "$QUEUE_STOP_FILE"` prints
      `$WS_ROOT/STOP` — i.e. **the resolved path is still the old one**
- [ ] The same for `WAVE_STATE` and `LOGF` against their `:81-82` forms
- [ ] `git diff` touches exactly one file and adds only variable
      definitions and comments
- [ ] The full `tests/unit/sdsc_submission_scripts/` suite is green **at
      this commit** with **zero test files modified**
- [ ] Pyright error count is unchanged from the pre-commit baseline

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| A variable already set in the operator's environment | Honoured — that is the point of `:-` |
| Definition-scope filesystem access | Must not exist; caught by `test_source_safe_entry.py` |
| `CAMPAIGN_ID` unset | Falls back to `v19` (`:68`), unchanged |
| `CAMPAIGN_ID` containing a path separator or `..` | **Not yet guarded** — deliberately. The id is not yet a directory component; E-C2 adds the D-E-9 guard in the same commit that makes it one |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
bash -n sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
V19_QUEUE_NO_MAIN=1 bash -c \
  "source sdsc_submission_scripts/v19_queue_runner.sh; \
   for v in CAMPAIGN_HOME CAMPAIGN_CONTROL_DIR QUEUE_STATE_DIR \
            PAIR_SUMMARY_DIR QUEUE_STOP_FILE WAVE_STATE LOGF; \
   do echo \"\$v=\${!v}\"; done"
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] resolved-path dump, before vs after (must be identical): __

#### 8. Commit boundary

- [ ] Independently reviewable: definitions only, provably inert
- [ ] Independently green: full shell suite passes at this commit
- [ ] No consumer change, no `mkdir`, no test modified, no doc change,
      no unrelated cleanup, no future work
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the resolved-path dump, and
      any deviation from this section

---
### E-C2 — The queue runner consumes the resolver, with the legacy read-back

*(Merged from the previously separate E-C2 and E-C4 by operator ruling,
2026-08-04 — OPEN-E-9 resolved as option (b). See §8's structural
rulings for why.)*

#### 1. Goal

Move `QUEUE_STOP_FILE`, `WAVE_STATE` and `LOGF` to the campaign-scoped
defaults, validate the campaign id before it becomes a directory,
create the directories, keep legacy state readable, strip the legacy
global STOP of its authority without deleting it, and fix D-E-7's
process-guard literal.

**This is the commit that closes the §1 defect**, and it is one commit
because the path move and the read-back are one behavioural unit: the
read-back is what makes the move safe. Splitting them would leave
`test_completed_only_selection_skips_and_exits_clean`
(`test_v19_queue_runner.py:294-304`) red in between, and would present a
change to review without its justification.

#### 2. Scope

**Changes**: `sdsc_submission_scripts/v19_queue_runner.sh` —
`:81`, `:82`, `:104` (defaults), `:259` (D-E-7), `:390`
(`mkdir -p "$WS_ROOT"` becomes the three campaign directories),
`chain_completed()` (`:215-219`, legacy fallback), a startup validation
call and a legacy-global-STOP observation in `main()`, and the startup
log line so the operator can read the resolved stop path.

**New Python** (D-E-9, placement forced by §3.13): a typed campaign
identity in `core/`, plus the thin CLI entry in `scripts/` the shell
calls. Both inside `pyrightconfig.json`'s `"include"`.

**Tests updated**: `test_v19_queue_runner.py:294-304` — its fixture
already writes the legacy filename, so it becomes the legacy-fallback
test with its log-path assertion repointed.
`test_c13_stop_semantics.py:161-171` passes `QUEUE_STOP_FILE`
explicitly and should keep passing untouched — **verify, do not assume.**

**Non-goals.** The chain-level STOP (`_chain_common.sh:694-696`) is not
touched. The wave record shape is E-C4. The Gate runner is E-C5. No
migration, archiving, deletion or rewriting of any legacy file. No
support for reading a *different* campaign's legacy state.

**Must stay unchanged**: stop check points (before each wave `:444`,
after each wave `:535`); `record_queue_stop`'s fields (`:206-211`); exit
code 99 (`:106`, `:447`, `:538`); the trap channel (`:190-196`);
`chain_completed()`'s contract — complete iff a record with `"exit": 0`
exists for that run name (`:213-219`); the workspace-exists guard
(`:255`); `V19_RESUME` semantics; `role_for_run()` (`:134-170`); the
`--only` path; the source-safe guard.

**Dependencies**: E-C1.

#### 3. Implementation plan

*Path move*
- [ ] Flip the five E-C1 defaults from the compatibility values to the
      §4.2 target values, in one hunk
- [ ] Replace `mkdir -p "$WS_ROOT"` (`:390`) with creation of
      `$CAMPAIGN_CONTROL_DIR`, `$QUEUE_STATE_DIR`, `$PAIR_SUMMARY_DIR`
      (each `mkdir -p` creates `$CAMPAIGN_HOME` implicitly). Keep it
      inside `main()` — `:375-377` states main is the only thing that
      touches the filesystem, and `test_source_safe_entry.py` enforces it
- [ ] Confirm `log()` (`:188`) is not called before the directory
      exists: it appends to `$LOGF`, now under `queue_state/`. Inspect
      every call site reachable before `:390` — the argument parser at
      `:381-388` uses `echo … >&2`, not `log`, but verify
- [ ] Add a startup line logging the resolved `CAMPAIGN_HOME`,
      `QUEUE_STOP_FILE` and `WAVE_STATE`, so BD-1's operator-visible
      change is discoverable from the log
- [ ] Replace `:259`'s `grep -v v19_queue_runner` with the basename of
      `${BASH_SOURCE[0]}`

*Identity validation (D-E-9)*
- [ ] Add the typed identity in `core/`: the `_WRITER_ID_RE` pattern
      (`observation_store.py:38`) **plus** explicit rejection of `.` and
      `..`, which that pattern accepts (§3.13)
- [ ] Add the `scripts/` CLI entry; model it on `campaign_spend.py`,
      which the launcher already calls at `:236-243`
- [ ] Call it in `main()` **before** the `mkdir` block — the id must be
      refused before it is used to create anything
- [ ] Inspect what `campaign_spend()` does when the interpreter is
      missing (`:236-243` ends `|| echo "0 0.00"`), then decide the
      validator's posture deliberately: a swallowed failure there yields
      a zero spend, but a swallowed failure here would skip the guard.
      **Recommendation: fail closed** — record the decision either way

*Legacy compatibility*
- [ ] Extend `chain_completed()`: if `$WAVE_STATE` does not exist or has
      no matching record, additionally check
      `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl` — **read only**
- [ ] Keep the existing `grep … | grep -q` form so the completion
      predicate is provably identical on both files
- [ ] Confirm the fallback cannot match another campaign: it
      interpolates `${CAMPAIGN_ID}` into the filename, and the record
      match is on the exact run name
- [ ] Add the legacy-global-STOP observation: if `$WS_ROOT/STOP` exists,
      log it with path and mtime and append a
      `legacy_global_stop_observed` record to the **new** wave state,
      matching `record_queue_stop`'s shape (`:206-211`). **Do not remove
      the file, and do not stop**
- [ ] Verify no write path targets a legacy filename: grep for
      `${CAMPAIGN_ID}_wave_state` and confirm every occurrence is a read
- [ ] Re-run the `test_c13_stop_semantics.py` queue class and confirm it
      is genuinely unaffected

#### 4. Validation plan

**Unit**
- [ ] `QUEUE_STOP_FILE` resolves to `$WS_ROOT/$CAMPAIGN_ID/control/STOP`
- [ ] `WAVE_STATE` and `LOGF` resolve under `$CAMPAIGN_HOME/queue_state/`
- [ ] The `QUEUE_STOP_FILE` override still wins over the new default
- [ ] The E1 path-enumeration test: every authority-bearing path
      contains the campaign id
- [ ] D-E-7: a copy of the runner under a different filename does not
      self-match the process guard
- [ ] Legacy state present, new state absent → a completed chain is
      still skipped
- [ ] Legacy and new state both present → the new state is
      authoritative; a chain completed only in legacy is still skipped
- [ ] Legacy state naming a **different** campaign id is not consulted
- [ ] `legacy_global_stop_observed` is recorded and the run proceeds

**Integration / pseudo**
- [ ] `test_source_safe_entry.py` still green — sourcing creates no
      directory
- [ ] A `--only` run against a temp root creates the three directories
      and writes its log to the new location
- [ ] A full `--only` run over a legacy fixture tree exits 0, skips the
      completed chain, and launches nothing

**Negative / invalid input**
- [ ] D-E-9's full refusal set, each its own case: empty; `/`; a path
      containing `/`; `..`; `.`; an absolute path; a backslash; a
      control character; a 129-character id
- [ ] Each refusal happens **before** any directory is created
- [ ] `WS_ROOT` unwritable → reported before any chain launches
- [ ] Legacy file present but unparseable or unreadable → **warn and
      continue**, treated as "no completion evidence". Blocking here
      would restore a legacy file's authority over a new campaign
- [ ] A stop file at the **old** global location does not stop the queue

**Backward compatibility / default parity**
- [ ] C13 parity: `test_c13_stop_semantics.py` green with **zero
      modifications** — if it needs edits, that is a semantics change
      and must be reported, not absorbed
- [ ] `test_v19_chain_role_resolution.py` green, unmodified
- [ ] The E4 mutation proof: revert only the three defaults and confirm
      every C13 assertion still passes
- [ ] Byte-and-mtime identity over every file in a legacy fixture tree
      before and after a full run — the E2 evidence
- [ ] The legacy global STOP is unchanged and still present afterwards

**Real Gate**
- [ ] None. **No real-training run is authorized by this commit.**

#### 5. Acceptance criteria

- [ ] After a `--only` run against a temp `WS_ROOT` with
      `CAMPAIGN_ID=alpha`, the filesystem contains
      `<tmp>/alpha/control/`, `<tmp>/alpha/queue_state/queue_runner.log`
      and `<tmp>/alpha/pair_summaries/` — asserted by listing the tree,
      not by echoing a variable
- [ ] `touch <tmp>/STOP` before that run does **not** stop it; the run
      launches, the log names the resolved stop path, and a
      `legacy_global_stop_observed` record naming the legacy path exists
      in the **new** wave state
- [ ] `touch <tmp>/alpha/control/STOP` **does** stop it, with a
      `queue_stopped` record whose `reason` is `operator_stop_requested`
      and exit code 99
- [ ] `CAMPAIGN_ID=..` exits non-zero and `<tmp>` gains **no** new
      directory — verified by listing `<tmp>` before and after
- [ ] Given `<tmp>/alpha_wave_state.jsonl` with an `"exit": 0` record
      for `alpha_arch_15_19` and no new-location state, `--only
      alpha_arch_15_19` logs `SKIP … already completed` and the screen
      shim records zero invocations
- [ ] Every pre-existing file under `<tmp>` has identical bytes and
      identical `st_mtime_ns` after the run
- [ ] `test_c13_stop_semantics.py` diff is empty
- [ ] A renamed copy of the runner launches (D-E-7)
- [ ] **The full test suite is green at this commit**, not at a later one
- [ ] Pyright is clean over the new `core/` and `scripts/` modules

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Campaign id empty, `/`, `\`, `..`, `.`, absolute, control chars, over-length | **STOP** before any directory is created (D-E-9) |
| Legacy `$WS_ROOT/STOP` present | **Warn + record, continue.** Never honoured, never deleted |
| Legacy wave state present | Read-only fallback, same campaign id only |
| Legacy state unreadable or malformed | **Warn and continue** — treated as no evidence |
| Both legacy and new state present | New state authoritative; legacy consulted only when the new one lacks the record |
| `$CAMPAIGN_HOME` missing | **Created** by `main()`; a fresh campaign is the normal case |
| `mkdir` fails (permissions, read-only mount) | **STOP** before any launch, with the path named |
| Campaign directory exists from a prior run of the same id | Normal resume; not an error. The workspace-exists guard (`:255`) and `chain_completed()` still decide what relaunches |
| Two campaigns running concurrently under one root | Each writes only under its own `CAMPAIGN_HOME`; proven in E-C6 |
| Partial migration (new dirs and legacy files both present) | Supported by construction — that is what the fallback is for |
| Historical V18r layout (`v18r_queue_state`, a plain text index, §3.10) | **Not consulted.** It belongs to a runner PR E does not modify; recorded in E-C7's README table so an operator is not surprised |
| Validator interpreter unavailable | See the implementation step; **recommendation: fail closed**, and the decision is recorded either way |
| Cleanup-script assumptions | None exist (§3.11); nothing to update |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
.venv/bin/python -m pytest tests/unit/core/ -q -k campaign
bash -n sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
git diff --stat -- tests/unit/sdsc_submission_scripts/test_c13_stop_semantics.py
grep -n '_wave_state' sdsc_submission_scripts/v19_queue_runner.sh
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] C13 diff empty: __
- [ ] observed directory tree after a `--only` run: __
- [ ] `<tmp>` listing before/after the `CAMPAIGN_ID=..` refusal: __
- [ ] byte/mtime identity result over the legacy fixture tree: __
- [ ] `legacy_global_stop_observed` record contents: __
- [ ] E4 mutation proof result: __
- [ ] validator-interpreter-unavailable decision recorded: __

#### 8. Commit boundary

- [ ] Independently reviewable: one behavioural unit — the path move and
      the compatibility that makes it safe — plus two named in-passing
      items the design approved (D-E-7, D-E-9)
- [ ] Independently green: no red intermediate, by ruling
- [ ] No stamp, no wave-record change, no Gate runner, no docs, no
      deletion, no archiving, no migration, no unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the observed directory tree,
      the identity-assertion result, and any deviation from this section

---
### E-C3 — Campaign stamp and mismatch guard

#### 1. Goal

Give checkpoint E3 something to enforce. §3.2 found that **nothing in
the repository writes a STOP file**, so a mismatch cannot be caught at
write time. The stamp is the identity artifact; the guard is the
refusal.

**Why after E-C2.** The stamp lives in `control/`, which E-C2 creates,
and it records an id that E-C2's validator has already proven safe. A
stamp written earlier would land in the old flat root and then need
moving — the migration this PR promises not to perform.

#### 2. Scope

**Changes**: `v19_queue_runner.sh` — one new guard function beside the
existing guards, called once from `main()` after directory creation and
**before** the `--only` branch (`:392`) so both paths are covered.
**Reuses**: E-C2's typed campaign identity — the stamp records an
already-validated id and never re-derives its own rules.
**New artifact**: `control/campaign.json` (§4.2 shape).
**New test**: a mismatch class in `test_v19_campaign_pinning.py`
(`TestCampaignIdentity` already owns campaign identity).

**Non-goals.** No stamping of chain workspaces. No stamp validation in
`core/run_invariants.py` — that lock is per-chain and has no campaign
field (§3.8); adding one is a schema change §20.7 does not ask for. No
cross-checking against run names.

**Must stay unchanged**: the order and behaviour of the three existing
launch guards (`:255`, `:258`, `:259`); `filter_roster` validation
(`_chain_common.sh:209-255`), which must still be what rejects an
unknown `--only` name; `role_for_run()`'s fail-closed refusal
(`:498-503`), which is a *different* guard and must not be folded in.

**Dependencies**: E-C2.

#### 3. Implementation plan

- [ ] Write the guard as a function with one responsibility: given
      `$CAMPAIGN_STAMP` and `$CAMPAIGN_ID`, either write the stamp,
      accept it, or refuse — no other side effect
- [ ] Emit and read the stamp through E-C2's Python entry rather than a
      shell `printf`. The stamp is JSON that is later *read back and
      compared*, which is the case that motivated the D-E-3 ruling; a
      `printf` producer with a `grep` consumer is the shape that failed
      in `campaign_spend`
- [ ] Write it atomically, per §3.13's registry form
- [ ] Call it from `main()` after the `mkdir` block and before the
      `--only` branch; confirm by reading `:378-392` that no launch or
      state write can precede it
- [ ] On mismatch: message naming the stamp path, the stamped id and the
      requested id; non-zero exit; **no wave state written**
- [ ] Decide whether the refusal appends a record to the wave state.
      Recommendation: **no** — writing into campaign B's state on a
      failed launch of campaign A is precisely the cross-campaign write
      this PR forbids. Log to stderr instead

#### 4. Validation plan

**Unit**
- [ ] Absent stamp → written once, containing the resolved
      `campaign_id`, `campaign_home` and a UTC `created_at`
- [ ] Matching stamp → accepted, contents not rewritten (compare mtime)
- [ ] Mismatched stamp → non-zero exit, message names both ids

**Integration / pseudo**
- [ ] A full `--only` run with a foreign stamp: exits non-zero, launches
      nothing (no screen shim invocation), writes no wave state

**Negative / invalid input**
- [ ] Malformed or truncated stamp JSON → **STOP**. A stamp that cannot
      be read cannot be shown to match, and proceeding would be the §1
      defect with extra steps
- [ ] Empty stamp file → same
- [ ] Stamp present but `campaign_id` key absent → same
- [ ] Stamp whose recorded id fails D-E-9's validation → **STOP**; a
      stamp written before the validator existed must not grandfather in
      an unsafe id

**Backward compatibility / default parity**
- [ ] A campaign directory created by E-C2 (no stamp yet) is adopted:
      the stamp is written and the run proceeds. An existing campaign
      must not need a manual stamp

**Real Gate**
- [ ] None.

#### 5. Acceptance criteria

- [ ] With `CAMPAIGN_ID=alpha` and a stamp naming `beta` at
      `<tmp>/alpha/control/campaign.json`, the runner exits non-zero,
      stderr names both ids and the stamp path, and
      `<tmp>/alpha/queue_state/` contains **no** `wave_state.jsonl`
      entry from this attempt
- [ ] The screen shim recorded zero invocations
- [ ] Removing the guard call makes exactly one test fail (the E3
      reachability mutation proof)
- [ ] A second run with the matching id succeeds and leaves the stamp
      byte-identical
- [ ] Full suite green at this commit; pyright clean

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Campaign-id mismatch | **STOP** — non-zero, before any launch or state write |
| Missing campaign dir | Created by E-C2; stamp then written. Not an error |
| Missing stamp in an existing campaign dir | **Adopt** — write it, proceed. This is every pre-PR-E campaign |
| Unreadable or malformed stamp | **STOP** — cannot prove a match |
| Stamp records an id that fails validation | **STOP** — no grandfathering |
| Stamp write fails | **STOP** — an unstampable campaign cannot be guarded |
| Concurrent campaigns | Each guards its own stamp; no shared file is read |
| Legacy global STOP | Unrelated to the stamp; handled in E-C2 |
| Cleanup scripts | None exist (§3.11). Nothing to update |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest \
  tests/unit/sdsc_submission_scripts/test_v19_campaign_pinning.py -q
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] mutation proof (guard call removed → exactly 1 failure): __
- [ ] observed stderr on mismatch: __

#### 8. Commit boundary

- [ ] Independently reviewable: one guard, one artifact, one test class
- [ ] Independently green at this commit
- [ ] No path changes, no record-shape changes, no docs, no unrelated
      cleanup, no future work
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the mutation-proof result, and
      any deviation from this section

---
### E-C4 — Wave record and pair summaries

#### 1. Goal

Satisfy §20.7's genericization requirement at the level where it
actually binds: the **state schema**. Today
`record_wave_summary()` (`:226-229`) can only express two chains named
`arch` and `loss`. Move the emission to a typed atomic Python writer,
add the `chains` array, write per-wave summary files under
`pair_summaries/`, and delete `MAX_CONC` (`:80`), which gates nothing
(§3.6).

**Why after E-C3.** It changes a record shape. Doing it before the
compatibility read-back and the stamp existed would put a shape change
and two compatibility mechanisms in flight at once.

#### 2. Scope

**Changes**: `v19_queue_runner.sh` — `record_wave_summary()`
(`:226-229`) becomes a call into the writer; its two call sites (`:515`,
`:530`); the startup log line (`:416`); deletion of `MAX_CONC` (`:80`).
**New Python**: the record models and the atomic write in `core/`, the
CLI in `scripts/` — the split §3.13 forces so the code is inside
pyright's `"include"`.
**Tests updated**: `test_v19_queue_runner.py:79-81` (deleted — see
below), `:178-204` (wave-summary fields), and
`test_source_safe_entry.py:88`, whose `MAX_CONC` probe must be
repointed at a variable that still exists.

**Non-goals.** The launcher still builds exactly two chain names per
wave (`:450-451`). This commit does **not** make the queue run one or
five chains — that is FU-E-2. `WAVES` and the band definitions are
untouched. This is **not** a shell rewrite: one responsibility moves,
and the rest of the file keeps its `printf` records.

**Must stay unchanged**: the disposition vocabulary (`complete`,
`failed`, `launch_failed`); the guarantee that a summary is written on
**every** exit path including the aborted-launch path (`:513-515`),
which `docs/running_chain_test.md:144-146` documents; the queue-state
append order; `record_queue_stop` and `record_chain`, which keep their
`printf` form because they emit flat records.

**Dependencies**: E-C2 (needs `PAIR_SUMMARY_DIR` and the typed
identity), E-C3.

**Test-deletion justification (CLAUDE.md rule).**
`test_exactly_two_chains_per_wave_max_conc` asserts `MAX_CONC == 2`.
`MAX_CONC` is read only by a log line (`:416`), so no defect is caught
by that assertion. The *class* the test was reaching for — "a wave must
not launch more chains than intended" — is preserved by a replacement
asserting that the wave loop launches exactly the ROSTER's chains for
that band. Input classes covered by the original: exactly one (a
constant). Input classes covered by the replacement: the launched set
for each of the four waves. The replacement fails if the wave loop
launches a chain from another band, which the original never could.

#### 3. Implementation plan

- [ ] Read `:226-229` and both call sites in full before editing; the
      printf is positional and the call sites pass eleven arguments
- [ ] Define the record as a Pydantic model in `core/`: `wave_summary`,
      `band`, `campaign_id`, `chains: list[ChainOutcome]`, `start`,
      `end`, `disposition`, plus the compatibility mirror fields
- [ ] Implement the atomic write per §3.13's registry form —
      `tempfile.mkstemp(dir=…)`, write, `flush`, `fsync`, `os.replace`,
      cleanup on exception — rather than the weaker fixed-`.tmp` form
- [ ] Add the `scripts/` CLI taking the chain roster as structured
      arguments; the shell passes run/role/pid/exit per chain
- [ ] Emit the six `arch_*`/`loss_*` keys as a labelled compatibility
      mirror when the wave has exactly two chains with those roles
- [ ] Write the record to `$PAIR_SUMMARY_DIR/wave_<n>_<band>.json`
      **and** append it to the wave state — both, so no existing
      operator query loses its source
- [ ] Reuse `band_tag()` (`:173-175`) for the filename rather than
      embedding `$SCOPE`, which contains a `-`
- [ ] Change `:416` to report the measured chain count instead of
      `MAX_CONC`; delete `:80`
- [ ] Repoint `test_source_safe_entry.py:88`'s probe at `CAMPAIGN_HOME`

#### 4. Validation plan

**Unit**
- [ ] The record contains `chains` with one entry per launched chain,
      each carrying `run`, `role`, `pid`, `exit`
- [ ] The record contains `campaign_id`
- [ ] The compatibility mirror is present for a two-chain arch/loss wave
- [ ] A three-entry synthetic chain list produces a valid record with
      three entries and **no** mirror keys — the direct proof that the
      two-chain assumption left the schema
- [ ] A role that is neither `arch` nor `loss` round-trips
- [ ] The atomic write leaves no `.tmp` residue on success
- [ ] An exception mid-write leaves the previous file intact and no
      partial file behind

**Integration / pseudo**
- [ ] A `--only` run and an aborted-launch path each produce a summary
      file under `pair_summaries/` **and** an appended wave-state record

**Negative / invalid input**
- [ ] A chain with a `missing` marker still records `-1`, as `:517` and
      `:532` do today
- [ ] An empty launched set does not produce a malformed record
- [ ] A malformed chain argument is rejected by the Pydantic model
      **before** anything is written — the schema is the boundary, per
      CLAUDE.md
- [ ] An unwritable `PAIR_SUMMARY_DIR` fails loudly rather than silently
      skipping the summary

**Backward compatibility / default parity**
- [ ] Every record emitted parses with `json.loads` — the check that
      caught the ledger bug motivating `campaign_spend.py`
- [ ] For a standard two-chain wave, all eleven original keys are
      present with the same values as before the change

**Real Gate**
- [ ] None.

#### 5. Acceptance criteria

- [ ] After a simulated wave, `<tmp>/alpha/pair_summaries/` contains
      exactly one file per wave group, each parsing as JSON with a
      `chains` array whose length equals the number of launched chains
- [ ] The same record is present in
      `<tmp>/alpha/queue_state/wave_state.jsonl`
- [ ] `grep -c MAX_CONC v19_queue_runner.sh` returns 0
- [ ] The startup log line reports the measured chain count
- [ ] A synthetic three-chain record parses and carries no mirror keys
- [ ] No `.tmp` or `mkstemp` residue remains in `pair_summaries/`
- [ ] Full suite green at this commit; **pyright clean over the new
      `core/` and `scripts/` modules — this commit is where pyright is
      most load-bearing**

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Summary file already exists for the same wave | **Overwrite** is acceptable within a campaign (a wave is retried under one id); the wave-state append preserves history. Confirm this matches operator expectation in review |
| `PAIR_SUMMARY_DIR` missing | Created by E-C2; if absent, **STOP** rather than lose a summary silently — `:513-514` says an aborted wave must not be the one case with no summary |
| Writer raises | **STOP** and surface it. A silently skipped summary is the failure mode `:513-514` exists to prevent |
| Crash mid-write | Atomic replace means the previous file survives intact; no torn file is ever visible |
| Legacy records with the old shape | Left in place; no reader exists (§3.8), and the mirror keys keep operator queries working |
| Concurrent campaigns | Each writes only under its own `PAIR_SUMMARY_DIR` |
| Interpreter unavailable | **STOP** — same posture as the E-C2 validator, and recorded there |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ tests/unit/core/ -q
grep -c MAX_CONC sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
ruff check . && ruff format --check .
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] emitted record, two-chain case (must parse): __
- [ ] emitted record, three-chain synthetic case: __
- [ ] residue check on `pair_summaries/` after a forced write failure: __

#### 8. Commit boundary

- [ ] Independently reviewable: one record shape, one responsibility
      moved to Python, one deletion, three test updates each with a
      written defect statement
- [ ] Independently green at this commit
- [ ] No launcher concurrency change (FU-E-2 stays deferred), no other
      shell record converted, no docs, no unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, both emitted records, and the
      test-deletion justification

---
### E-C5 — Gate pair summary scoping

#### 1. Goal

`v19_gate0_pair_runner.sh:59` writes a fixed
`$GATE_ROOT/gate0_pair_summary.json` while every other name in the file
derives from `GATE_RUN_PREFIX` (`:56`), which `:51-55` documents as the
value "the launcher derives EVERY name from it, so the summary, the
markers and the chain argv cannot disagree". Two Gate runs under one
`GATE_ROOT` silently overwrite each other — and `:379-382` records that
this has already happened once.

**Why here.** It is the smallest and most isolated change, and it
touches a different file, so putting it after the queue-runner sequence
keeps each review focused on one launcher.

#### 2. Scope

**Changes**: `v19_gate0_pair_runner.sh` — `SUMMARY` (`:59`),
`RUNNER_LOG` (`:63`), and the `"gate"` literal in the summary record
(`:290`).
**Tests updated**: `test_v19_gate0_pair_runner.py:214`, where
`_run_main` reads `gate_root / "gate0_pair_summary.json"`;
`test_source_safe_entry.py:62-71`, which pre-writes
`gate0_pair_summary.json` as one of the files sourcing must not modify.

**Non-goals — D-E-4's second half.** **Do not add a stop channel to the
Gate runner.** It has none today: its only trap is
`trap write_summary EXIT` (`:304`) and its only bound is
`WALL_CAP_SECONDS` (`:48`). Adding one is a stop-semantics change, out
of §20.7's scope, and is OPEN-E-3. Do **not** convert the Gate's
`write_summary` printf to the E-C4 writer either: it emits a flat
record with a fixed two-chain shape that no ruling asked to generalize,
and converting it would widen the PR for no defect.

**Must stay unchanged**: `write_summary`'s idempotence guard
(`:280-281`); the `trap … EXIT` registration (`:304`); the
summary-on-every-exit-path guarantee; the stagger logic; the
source-safe guard (`:385-387`).

**Dependencies**: none on E-C1..E-C4. May be reordered freely.

#### 3. Implementation plan

- [ ] Change `SUMMARY` to `$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`
- [ ] Change `RUNNER_LOG` to `$GATE_ROOT/${GATE_RUN_PREFIX}_runner.log`
- [ ] Change the `"gate"` field at `:290` to emit `$GATE_RUN_PREFIX`
- [ ] Confirm `log()` (`:65`) is only called after `GATE_RUN_PREFIX` is
      defined — it is defined at `:56` and `log` at `:65`, but verify no
      earlier caller exists
- [ ] Update `_run_main` (`test_…:188-214`) to read the derived filename
- [ ] Update the pre-written filename in `test_source_safe_entry.py`
- [ ] **OPEN-E-7 — decide and record**: whether the Gate root should
      also carry the prefix (`$GATE_ROOT/$GATE_RUN_PREFIX/`). §20.7 does
      not ask for it, the two-file rename removes the collision, and a
      directory move would strand the existing Gate evidence. Author's
      recommendation: **no** — files only

#### 4. Validation plan

**Unit**
- [ ] `SUMMARY`, `RUNNER_LOG` and the `"gate"` field all reflect a
      non-default `GATE_RUN_PREFIX`
- [ ] With the default prefix, all three match today's values except the
      filenames, which now carry `v19_c14`

**Integration / pseudo**
- [ ] `_run_main` still produces a parseable summary in every existing
      scenario (both pass; arch fails before stagger; launch error)
- [ ] Two `_run_main` runs with **different** prefixes under one
      `GATE_ROOT` produce two distinct summary files, neither
      overwritten

**Negative / invalid input**
- [ ] Empty `GATE_RUN_PREFIX` → inspect current behaviour first. If it
      produces `_pair_summary.json`, decide whether to refuse. Do not
      assume a guard exists
- [ ] `GATE_RUN_PREFIX` containing `/` or `..` → the same hazard D-E-9
      addresses for `CAMPAIGN_ID`. **Inspect, then decide**: reusing the
      typed identity here is a two-line change, but it makes E-C5 depend
      on E-C2, which it otherwise does not. Record the decision

**Backward compatibility / default parity**
- [ ] An existing `gate0_pair_summary.json` on disk is **not** read,
      renamed or deleted — it stays as historical evidence, and E-C7's
      README table records that the old filename belongs to the
      pre-PR-E Gate

**Real Gate**
- [ ] None. This commit touches the Gate *runner's* bookkeeping, not any
      Gate execution. **No Gate run is authorized by this commit; a real
      Gate 0 execution requires separate operator approval and is not
      part of PR E.**

#### 5. Acceptance criteria

- [ ] With `GATE_RUN_PREFIX=probe1` and `GATE_RUN_PREFIX=probe2` run in
      turn under one `GATE_ROOT`, the directory afterwards contains
      `probe1_pair_summary.json` **and** `probe2_pair_summary.json`,
      both parseable, with `"gate"` fields `probe1` and `probe2`
      respectively
- [ ] A pre-existing `gate0_pair_summary.json` is byte- and
      mtime-identical after both runs
- [ ] `grep -n 'gate0_pair_summary\|v19_gate0' v19_gate0_pair_runner.sh`
      shows the literals only in comments
- [ ] The Gate runner still has no stop-file reader (`grep` for `STOP`
      returns only unrelated matches)
- [ ] Full suite green at this commit; pyright count unchanged

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Two Gate runs under one root | Both summaries survive — the defect being fixed |
| Historical `gate0_pair_summary.json` | Left untouched; documented in E-C7 |
| Empty `GATE_RUN_PREFIX` | See the implementation step; decide from observed behaviour, do not assume |
| `GATE_RUN_PREFIX` containing `/` or `..` | See the negative-input step; decision recorded either way |
| `GATE_ROOT` unwritable | **STOP** — unchanged from today |
| Sourcing the runner | Must still modify nothing; `test_source_safe_entry.py` enforces it, and its fixture filename changes with this commit |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest \
  tests/unit/sdsc_submission_scripts/test_v19_gate0_pair_runner.py \
  tests/unit/sdsc_submission_scripts/test_source_safe_entry.py -q
bash -n sdsc_submission_scripts/v19_gate0_pair_runner.sh
grep -n 'STOP' sdsc_submission_scripts/v19_gate0_pair_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] two-prefix directory listing: __
- [ ] OPEN-E-7 decision recorded: __
- [ ] `GATE_RUN_PREFIX` validation decision recorded: __

#### 8. Commit boundary

- [ ] Independently reviewable: three literals and two test fixtures
- [ ] Independently green at this commit
- [ ] No stop channel added; no `GATE_ROOT` restructuring; no conversion
      of the Gate's own printf; no docs; no unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the two-prefix listing, and
      the recorded decisions

---

### E-C6 — Multi-campaign isolation test

#### 1. Goal

Produce checkpoint E5's evidence and §12's artifact 3: a test that
**observes** two campaigns coexisting, rather than asserting a
configuration value. Its negative control is what turns it from a
description into a regression test.

**Why its own commit.** It is the acceptance evidence for the whole PR
and must be reviewable as a single artifact. It also must be able to
fail: writing it after the code means a green result is meaningful.

#### 2. Scope

**New file**:
`tests/unit/sdsc_submission_scripts/test_multi_campaign_isolation.py`.
**No production change.** If this commit needs a production edit, the
design was wrong and that must be reported, not absorbed.

**Non-goals.** No GPU, no API key, no dataset, no `run_chain.sh`
invocation with real training, no `screen` outside the shim.

**Must stay unchanged**: everything. This commit adds a file.

**Dependencies**: E-C2 through E-C4.

#### 3. Implementation plan

- [ ] Reuse the established harness shapes rather than inventing one:
      `_sourced` (`test_v19_queue_runner.py:36`), `_run` (`:49-61`, runs
      the real script with `WS_ROOT` in a temp dir), and the PATH
      `screen` shim (`test_v19_gate0_pair_runner.py:169-186`), which
      already simulates a chain by writing exit markers
- [ ] Build the §9 fixture tree: a legacy global `STOP`, two campaign
      homes `alpha` and `beta`, `alpha`'s `control/STOP` armed
- [ ] Assert the four properties of §9 Layer 2, each as its own test
- [ ] Add the negative control: force `QUEUE_STOP_FILE` to
      `$WS_ROOT/STOP` and assert the isolation property **fails**. Use
      the environment override rather than editing the script, so the
      control is a runtime condition and not a source mutation
- [ ] Include a byte-and-mtime cross-check: after `beta`'s run, every
      file under `alpha/` is unchanged, and vice versa
- [ ] State each test's defect in its docstring, per the CLAUDE.md rule

#### 4. Validation plan

**Unit**
- [ ] Each of the four §9 assertions passes

**Integration / pseudo**
- [ ] The whole module runs against the **real** runner script via the
      shim — no reimplementation of the wave loop in Python

**Negative / invalid input**
- [ ] The negative control: with the old default restored, the
      "campaign beta launches" assertion fails. **This must be observed,
      not assumed** — run it and record the failure output

**Backward compatibility / default parity**
- [ ] The legacy global STOP is present for every test in the module and
      never honoured; it is byte-identical at the end

**Real Gate**
- [ ] None. **The module must be runnable on a machine with no GPU and
      no API key. If any test cannot satisfy that, it does not belong
      here.**

#### 5. Acceptance criteria

- [ ] With `alpha/control/STOP` armed and `<tmp>/STOP` present, a run
      with `CAMPAIGN_ID=beta` reaches the launch path (shim invoked) and
      a run with `CAMPAIGN_ID=alpha` exits 99 with an
      `operator_stop_requested` record — both observed from the
      filesystem and exit code, not from a variable
- [ ] After both runs, no file under `alpha/` was written by `beta`'s
      run and no file under `beta/` was written by `alpha`'s
- [ ] `<tmp>/STOP` is byte- and mtime-identical at the end
- [ ] The negative control's recorded failure output is attached
- [ ] Total module wall time is bounded and recorded
- [ ] **Run both locally and on CI.** This module touches `/tmp`,
      `screen`, `ps` and absolute paths — the exact profile of the PR C
      test that passed here and failed on a runner

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Legacy global STOP | Present throughout, never honoured — asserted |
| Campaign-id mismatch | Covered by E-C3's tests; this module may add one end-to-end case |
| Invalid campaign id | Covered by E-C2's tests; not repeated here |
| Missing campaign dir | `beta` starts from nothing — the normal fresh-campaign case |
| Historical layout | `alpha` carries a legacy wave-state file so the read-back is exercised end to end |
| Concurrent campaigns | Runs are sequential in-test; the property asserted is *no cross-writes*, which is what concurrency would violate |
| Partial migration | `alpha` has both legacy and new state; `beta` has only new |
| Unreadable state | One test gives `alpha` a truncated legacy file and asserts the run still proceeds |
| Test flakiness from `screen` | Eliminated by the PATH shim; the real `screen` is never invoked |
| Pyright coverage | **None** — `pyrightconfig.json` excludes `tests`. Recorded, not claimed |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest \
  tests/unit/sdsc_submission_scripts/test_multi_campaign_isolation.py -q
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __ *(module itself is not
      covered — `tests` is excluded)*
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] negative-control failure output: __
- [ ] cross-write check result: __

A negative control that was not executed is not a negative control.

#### 8. Commit boundary

- [ ] Independently reviewable: one new test file, zero production lines
- [ ] Independently green at this commit
- [ ] No production change; if one is needed, stop and report
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the module output, the CI result, and the negative-control failure
      output

---

### E-C7 — Doc sync

#### 1. Goal

Discharge the node/skill doc-sync rule: every CLI argument, default and
behaviour explanation the PR changed is corrected in the operator-facing
docs, **as the last step before merge**, so the docs describe the merged
code rather than the intended code.

**Why last.** The rule says so, and for a reason: several OPEN items may
still resolve differently during implementation, and a doc written
earlier would describe a design rather than a result.

#### 2. Scope

**Changes**:

| File | What |
|---|---|
| `docs/running_chain_test.md` | `:131` the queue stop command; `:135` the wave-state filename; `:141` the `QUEUE_STOP_FILE` default row; new rows for `CAMPAIGN_HOME` and the campaign stamp |
| `sdsc_submission_scripts/v19_queue_runner.sh` | the file's own header `:36-56`, which documents `$WS_ROOT/v19_wave_state.jsonl` and asserts "No other hidden state" |
| `sdsc_submission_scripts/README.md` | **a new section** — see the scope note below |
| `docs/design/runtime_estimation_and_calibration.md` | `:3837-3840` the queue stop-channel narrative and `:3852-3853` the wave-state filename; `:3911` the Gate pair summary filename |
| `docs/design/v20_priorities.md` §20.7 | status pointer to this document |
| this document | checkpoint boxes, deviation approvals, OPEN resolutions |

> **Scope note — larger than the design assumed. OPEN-E-6.**
> `sdsc_submission_scripts/README.md` currently documents only
> `run_chain.sh`, `_chain_common.sh`, `run_one_iteration.py`,
> `submit_one_iteration.slurm`, the Tier-3 runner and the auxiliary
> scripts. A grep for `v19`, `v18r`, `queue` and `gate0` matches
> **nothing**: the queue runner, the Gate pair runner,
> `v18r_queue_runner.sh` and `launch_v18_wave1.sh` have never been in
> the folder map. §12's artifact 4 (the record of readable historical
> layouts) therefore means **creating a campaign-control section**, not
> editing one.

**Non-goals.** No restructuring of `running_chain_test.md`. No new
design document. No edits to V19 protocol documents, which are
historical record. **No `WAVE_WALL_SECONDS` correction — see below.**

> **DEFERRED BY OPERATOR RULING, 2026-08-04 — OPEN-E-10 stays open and
> leaves PR E.** `docs/running_chain_test.md:142` and
> `docs/design/runtime_estimation_and_calibration.md:3841-3842` state
> `WAVE_WALL_SECONDS` defaults to `86400`; the code is `259200`
> (`v19_queue_runner.sh:89`), and
> `test_v19_campaign_pinning.py:190` asserts the cap exceeds 86400, so
> the code is right and both docs are stale. It is a **separate docs
> follow-up** and must **not** be folded into PR E, even though this
> commit opens both files. The finding stays recorded in §14; fixing it
> here would mix an unrelated correction into a doc-sync commit whose
> job is to describe *this* PR's merged behaviour.

**Must stay unchanged**: every doc statement about chain-level stop
semantics, which this PR does not alter; every doc statement about
`role_for_run()`, which `fe51377c` already documented.

**Dependencies**: all preceding commits merged.

#### 3. Implementation plan

- [ ] Re-read each target section immediately before editing — never
      edit from memory of this audit
- [ ] For every documented variable and default, quote it against the
      **merged** source and record the line number
- [ ] Add the `CAMPAIGN_HOME` / `CAMPAIGN_CONTROL_DIR` /
      `QUEUE_STATE_DIR` / `PAIR_SUMMARY_DIR` rows to the env table in
      `running_chain_test.md`
- [ ] Document the campaign-id validation rules (D-E-9) in operator
      terms — an operator who picks an id needs to know what is refused
- [ ] Add a "campaign control" section to
      `sdsc_submission_scripts/README.md` covering the three launchers,
      the path model, and the historical-layout table from §3.10
- [ ] Correct the queue-runner header block's "No other hidden state"
      claim to name the stamp
- [ ] Update this document's checkpoint boxes with evidence, not
      assertions
- [ ] **Leave `WAVE_WALL_SECONDS` alone** in both files, per the ruling
      above. If the temptation to fix it in passing arises, that is the
      rule working

#### 4. Validation plan

**Unit**
- [ ] Inspect whether a documentation-sync test already exists for these
      files (`tests/unit/scripts/test_c2_documentation_sync.py` is the
      precedent for this pattern). If one covers the queue runner, it
      must be updated; if none does, do **not** invent one here

**Integration / pseudo**
- [ ] Every command shown in the edited docs is executed once against a
      temp root and produces the documented effect

**Negative / invalid input**
- [ ] Not applicable — no code changes

**Backward compatibility / default parity**
- [ ] Every default quoted in a doc is grepped out of the merged source
      and matched character for character

**Real Gate**
- [ ] None.

#### 5. Acceptance criteria

- [ ] Every default appearing in an edited doc has a recorded
      `file:line` citation from the merged source
- [ ] `touch "$WS_ROOT/STOP"` no longer appears as the queue-stop
      instruction anywhere in `docs/`
- [ ] `grep -rn 'v19_wave_state.jsonl' docs/` returns only historical
      or explicitly-labelled-legacy references
- [ ] `sdsc_submission_scripts/README.md` names all three campaign
      launchers and carries the historical-layout table
- [ ] `WAVE_WALL_SECONDS` still reads `86400` in both docs — the
      deferral is verified, not assumed
- [ ] Every checkpoint box in §6 of this document is either `[x]` with
      evidence or `[ ]` with a stated reason

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| A doc statement contradicts the merged code | **STOP** and report — it means an earlier commit deviated from the design |
| The stale `WAVE_WALL_SECONDS` default | **Leave.** Deferred by ruling to its own change; recorded in §14 |
| Another stale default found in passing | Record it in §14 as a follow-up. Do not fix it here — the same reasoning that deferred OPEN-E-10 |
| An existing doc-sync test covers these files | Must be updated in this commit |
| A V19 protocol document describes the old paths | **Leave** — historical record, explicitly out of scope |

#### 7. Verification commands and evidence

```bash
grep -rn 'WS_ROOT/STOP\|v19_wave_state.jsonl\|gate0_pair_summary' docs/ \
     sdsc_submission_scripts/
grep -rn 'WAVE_WALL_SECONDS' docs/          # must still show 86400
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ \
     tests/unit/scripts/ -q
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
ruff check . && ruff format --check .
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] quoted-default audit table (doc line → source line): __
- [ ] `WAVE_WALL_SECONDS` deferral verified untouched: __

#### 8. Commit boundary

- [ ] Independently reviewable: documentation only
- [ ] No production code; no future work; no in-passing corrections; no
      restructuring beyond the new README section this PR's artifact
      requires
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the quoted-default audit table, and every OPEN item's resolution

---

## 9. Validation

No GPU, no API key, no dataset is required by any layer. That is a
property of the PR, not a compromise: control state is filesystem
logic, and testing it against a real campaign would prove less, slower.

**Two standing rules apply to every layer**, stated once here and once
in §8 rather than repeated per test:

1. **Pyright runs before every push**, with the CI-reproducing
   invocation `PATH=~/.cache/pyright-python/nodeenv/bin:$PATH
   ./.venv/bin/pyright`. PR C shipped 44 pyright errors behind 2,416
   passing tests, so pytest green is not type-check green. §3.13 records
   what the current `pyrightconfig.json` does and does not cover —
   notably that `tests` is excluded, so **no test in any layer below is
   type-checked**, and that is recorded rather than claimed away.
2. **Local green is not CI green.** PR C's registry test passed on this
   box and failed on a runner. Every layer below touches machine state
   — `$HOME`, `/tmp` (`EXIT_DIR`, `:79`), `screen`, `ps`, absolute
   paths — so every layer is run **both** locally and on CI, and a
   local-only result is reported as *locally green, CI pending*.

### Layer 1 — deterministic path and guard unit tests

Bash-driven, in the established `_sourced(...)` style already used by
`test_v19_campaign_pinning.py:85`, `test_v19_queue_runner.py:36` and
`test_c13_stop_semantics.py:152`, so the **real** script is the code
under test.

| Test | Defect it catches, that nothing else does |
|---|---|
| every resolved authority path contains the campaign id | a future path added without campaign scoping — the exact §1 defect class, made structural |
| `QUEUE_STOP_FILE` env override still wins | the fix silently removing the operator's documented escape hatch |
| foreign stamp → non-zero exit, no directory created, no chain launched | a mismatched campaign resuming into another's state |
| absent stamp → written once, with the resolved id | the guard being unreachable because nothing ever stamps |
| legacy global STOP → run proceeds, record written, file untouched | either regression: honouring it (defect returns) or deleting it (evidence destroyed) |
| legacy wave state → completed chain still skipped | a resume relaunching a completed chain and clobbering its workspace |
| a ROSTER role that is neither `arch` nor `loss` | the two-role assumption surviving in the state schema |
| campaign id `..`, `.`, `/`, empty, absolute, control-char, over-length | an id escaping the campaign root once it becomes a directory component (D-E-9). `..` is the one the borrowed regex alone would admit |
| a wave record with three chains parses and carries no mirror keys | the typed writer silently re-imposing the two-chain shape |
| the writer leaves no temp residue, and a crash leaves the previous file intact | a torn or half-written summary, which the fixed-`.tmp` form permits |
| non-default `CAMPAIGN_HOME` / `QUEUE_STATE_DIR` / `PAIR_SUMMARY_DIR` outside `WS_ROOT` | the "configurable" values being decorative (§1.4.6) |

### Layer 2 — multi-campaign isolation (the §20.7 shell-level test)

One module, one fixture tree, `launch_chain` and `screen` stubbed:

```text
tmp/
├── STOP                       legacy global — armed for the whole test
├── alpha/control/STOP         armed
├── alpha/…                    campaign alpha state
└── beta/…                     campaign beta state
```

Assertions:

1. runner with `CAMPAIGN_ID=beta` launches; `alpha`'s STOP is not read;
2. runner with `CAMPAIGN_ID=alpha` records `operator_stop_requested`
   and exits 99;
3. after both, every file under `alpha/` is byte- and mtime-identical
   from `beta`'s run, and vice versa;
4. the legacy `tmp/STOP` blocked neither, and is unchanged;
5. **negative control**: with `QUEUE_STOP_FILE` forced back to
   `$WS_ROOT/STOP`, assertion 1 fails. This is what makes the module
   a regression test rather than a description.

### Layer 3 — bounded real shell queue run

The real `v19_queue_runner.sh`, executed (not sourced), against a temp
`WS_ROOT`, with a `screen` shim and a `launch_chain` that writes exit
markers directly — the pattern
`test_v19_queue_runner.py:294-310` already uses for the completed-`--only`
case. Proves the wave loop, the stop checks, the summary writes and the
guards work together on the new paths, end to end, in seconds.

### Layer 4 — parity and reachability proofs

- **C13 parity**: `test_c13_stop_semantics.py` runs unchanged except for
  the two constructed path expressions. A diff of the file must show
  nothing but those.
- **Mutation proof for E4**: revert only the path default and confirm
  every C13 assertion still passes — proving the stop *semantics* are
  independent of the stop *location*, which is the claim E4 makes.
- **Mutation proof for E3**: remove the stamp-validation call and
  confirm exactly one test fails — proving the guard is reached from the
  production path, not just unit-tested in isolation.
- **Reachability for E1**: add a deliberately unscoped path to the
  resolver in a scratch commit and confirm the enumeration test fails.

### Not required, and why

No Gate 1 (no LLM-facing prompt, schema or decision surface changes).
No Gate 2 (no training, inference, scoring, admission or estimator code
is touched; zero Python production modules are in scope, §3.8). If
review finds any of that untrue, PR E stops and the gate question
reopens.

---

## 10. Merge criteria

- [ ] **No cross-campaign authority.** Every authority-bearing path the
      launchers read or write contains the resolved campaign identity,
      proved by the enumeration test, not by inspection.
- [ ] **Stop semantics unchanged.** C13 suite green with only path
      expressions changed; the E4 mutation proof recorded.
- [ ] **Historical evidence preserved.** A byte- and mtime-identity
      assertion over a legacy fixture tree after a full run.
- [ ] **No manual cleanup before a new launch.** Demonstrated by the
      Layer-2 test starting `beta` with `alpha`'s STOP and the legacy
      global STOP both armed.
- [ ] **The role defect stays fixed.** Landed ahead of PR E
      (`fe51377c`, PR #165 — D-E-6); PR E must not regress it, proved by
      `test_v19_chain_role_resolution.py` green and unmodified.
- [ ] **The campaign id cannot escape the campaign root** (D-E-9),
      proved by refusal tests for `..`, `.`, `/`, empty, absolute,
      control characters and over-length — each showing **no directory
      was created**.
- [ ] **Every commit was independently green**, with no knowingly-red
      intermediate (operator ruling, OPEN-E-9).
- [ ] Genericization section complete; FU-E-1..FU-E-6 filed.
- [ ] Doc sync commit (E-C7) verified by quoting each documented
      variable and default against the merged source.
- [ ] `WAVE_WALL_SECONDS` left untouched in both docs — OPEN-E-10 is
      deferred to its own change, verified rather than assumed.
- [ ] **Pyright clean on the exact head**, run with the CI-reproducing
      invocation, with the before/after error counts recorded per
      commit.
- [ ] CI green on the exact head, including `ruff check` and
      `ruff format --check` — and every machine-state-touching test
      confirmed on CI, not only locally.

---

## 11. Stop conditions

Stop and return to the operator if:

- **Historical layouts cannot be read without ambiguity.** Specifically:
  if a legacy `$WS_ROOT/<id>_wave_state.jsonl` cannot be attributed to a
  campaign id unambiguously — e.g. two campaign ids where one is a
  prefix of the other, so a `glob` matches both. (`campaign_spend.py:58`
  has the same latent exposure with `f"{campaign_id}_*"`; if BC-2's
  read-back inherits it, stop rather than paper over it.)
- **Any authority-bearing path cannot carry campaign identity without
  changing stop semantics.** The chain STOP is the case to watch: if
  scoping it required moving `${WORKSPACE}/STOP`, C13's operator surface
  would change and PR E would be exceeding its scope. (The audit says it
  does not — §3.1 — but a discovery to the contrary is a stop.)
- **Migration would require deleting existing evidence.** If any
  compatibility rule cannot be satisfied without removing or rewriting a
  file, stop. BC-1 is unconditional.
- **The scope grows into concurrency.** If closing E1 turns out to
  require an N-chain scheduler, or to interact with PR B's pair
  admission, stop: that is FU-E-2 and a different PR.
- **`MAX_CONC` turns out to be load-bearing somewhere unread.** The
  audit found two occurrences (§3.6). If a third exists in an
  environment the repo does not contain, deleting it is not safe.
- **The Python surface grows beyond two small modules.** D-E-3 and
  D-E-9 add a typed identity and a wave-record writer. If closing E-C4
  turns out to require converting `record_queue_stop`, `record_chain` or
  the Gate's `write_summary` as well, stop: that is a shell rewrite, and
  the ruling authorized moving **one** responsibility that had outgrown
  positional formatting.
- **A commit cannot be made independently green.** The operator ruled
  that no red intermediate may be knowingly committed. If a split turns
  out to be impossible to land green, stop and re-cut the boundary
  rather than committing red and repairing later.

---

## 12. Expected artifacts

1. **The path model** — §4, implemented as one resolution block in
   `v19_queue_runner.sh`, with every value overridable and its resolved
   value logged at startup.
2. **The campaign stamp and mismatch guard** —
   `control/campaign.json` plus a startup guard that refuses before any
   side effect.
3. **The multi-campaign isolation test** —
   `tests/unit/sdsc_submission_scripts/test_multi_campaign_isolation.py`,
   with the negative control that fails on revert.
4. **A record of which historical layouts remain readable** — §3.10
   promoted into `sdsc_submission_scripts/README.md`, naming each
   layout, its producer, and whether it is read, written, or read-only.
5. **The typed campaign identity** (D-E-9) — one validated identifier in
   `core/`, refusing empty, `/`, `\`, `.`, `..`, absolute, control-char
   and over-length ids, with the `..` case explicitly covered because
   the borrowed `_WRITER_ID_RE` pattern admits it.
6. **The typed atomic wave-record writer** (D-E-3) — Pydantic record
   models plus a `mkstemp`/`fsync`/`os.replace` write in `core/`, and
   the `scripts/` CLI the launcher calls.
7. **The Behavior Delta statements** — §13, carried into the PR
   description.
8. **FU-E-1 … FU-E-6** — filed follow-ups.
9. **Per-commit pyright and CI evidence** — the before/after error
   counts and the local-vs-CI result recorded in each commit's §7 slots,
   so "green" is a number and a runner, not an adjective.

---

## 13. Behavior Delta

Six, stated so review can check each independently.

### BD-1 — The queue stop file's default location moves

**Before**: `$WS_ROOT/STOP`. **After**: `$WS_ROOT/$CAMPAIGN_ID/control/STOP`.

Unchanged: the `QUEUE_STOP_FILE` override, the signal channel, the
check points (before each wave, after each wave), the `queue_stopped`
record, exit code 99, the no-further-wave rule, and the
"stopped-on-request chains produce no restart suggestion" behaviour.

**Operator-visible**: `touch "$WS_ROOT/STOP"` no longer stops a queue.
`docs/running_chain_test.md:131` must change in the same PR, and the
runner logs its resolved stop path at startup so an operator can copy it.

**Migration**: none required. A campaign already running under the old
default keeps reading the old default, because its runner process
already resolved it.

### BD-2 — A legacy global STOP no longer blocks a launch

**Before**: `$WS_ROOT/STOP` from any past campaign blocks every future
launch under that root — the §1 defect. **After**: it is logged,
recorded in the queue state as `legacy_global_stop_observed`, and
ignored. **The file is not deleted.**

**Why this is safe**: a campaign that wants to be stopped now writes to
its own control directory, and the launcher tells the operator exactly
which path that is. **Why it is not silent**: the observation is a
persisted record, not a log line.

### BD-3 — Queue and wave state move to a directory, with a legacy read-back

**Before**: `$WS_ROOT/<id>_wave_state.jsonl`, `<id>_queue_runner.log`.
**After**: `$WS_ROOT/<id>/queue_state/wave_state.jsonl` and
`queue_runner.log`, plus per-wave files under `pair_summaries/`.

Completion detection reads the new file, then falls back to the legacy
file for the **same** campaign id, read-only. **No existing file is
written to again.** An operator inspecting an old campaign finds
everything where it was.

### BD-4 — The wave summary record gains a chain list, moves to a typed writer, and `MAX_CONC` disappears

Additive: a `chains` array and `campaign_id`. The six `arch_*`/`loss_*`
keys remain as a labelled compatibility mirror. No consumer breaks (§3.8
found none in Python; the operator reports read the mirror keys).

**The producer changes.** The eleven-positional `printf` (`:226-229`) is
replaced by a typed Python writer that validates the record and writes
it atomically (`mkstemp`/`fsync`/`os.replace`). Two consequences worth
naming: a malformed wave record now fails at the schema instead of
landing on disk as unparseable JSON, and a crash mid-write can no longer
leave a torn summary. `record_queue_stop` and `record_chain` keep their
`printf` form — they emit flat records, and converting them was not
authorized.

`MAX_CONC` is deleted from `v19_queue_runner.sh`. **This changes no
behaviour** — it was read only by a log line (`:416`) — and the log line
now reports the measured chain count. `v18r_queue_runner.sh`'s
`MAX_CONC=4`, which *is* enforced, is untouched.

### BD-5 — An invalid campaign id is now refused

**Before**: `CAMPAIGN_ID` is interpolated into filenames with no
validation anywhere in the launcher. **After**: an id that is empty, or
contains `/`, `\`, a control character, or is `.`, `..`, an absolute
path, or longer than 128 characters, is **refused at startup, before
any directory is created** (D-E-9).

This is a new refusal path that did not exist before, and it is the one
place PR E can reject a launch that previously proceeded. It is
deliberate: the id becomes a *directory* component for the first time,
and `..` would resolve `$WS_ROOT/../control/STOP` — an escape from the
campaign root. Every id any real campaign has used (`v19`, `v19r2…`,
`v19_c14`, `camp1`) passes unchanged.

### BD-6 — The live-process guard no longer hardcodes the script name

**D-E-7**: the self-exclusion derives from the script's own basename, so
a renamed or copied runner no longer refuses to launch. No effect under
the current name.

**Landed ahead of PR E, recorded here for completeness.** The
role-derivation fix (`fe51377c`, PR #165) changed what a non-`v19` wave
actually runs — the loss arm now gets the loss advice, and an
unresolvable role stops the queue instead of silently defaulting to
`arch`. That behaviour delta belongs to PR #165, not to PR E, and PR E
must not alter it.

**Retry / round / attempt accounting**: unchanged by all six.
**LLM impact**: none. **GPU impact**: none. **Scientific numerics**:
none.

---

## 14. Open questions

Marked OPEN. Each names the evidence that would close it. Resolved items
are kept with their decision, because a resolution is only auditable
next to the question it answered.

### Resolved — operator rulings, 2026-08-04

**RESOLVED-E-8 — `campaign_id` must be validated before it becomes a
path component.** Rejected if empty, containing `/`, containing `..`, an
absolute path, or containing control characters or any path separator —
anything that could escape the campaign root. The audit was run first,
as instructed: the only precedent is `_WRITER_ID_RE`
(`core/runtime_control/observation_store.py:38`), which is
module-private and guards the identical hazard, so PR E **reuses the
pattern and not the symbol**, and adds the `.`/`..` rejection the
pattern alone does not provide (§3.13). Implemented as a narrow typed
identifier — D-E-9, enforced in E-C2 before the directory is created.

**RESOLVED-E-9 — no knowingly-red intermediate.** The old E-C2 and E-C4
are one commit. The wave-state path move and its read-back are one
behavioural unit, and splitting them left
`test_completed_only_selection_skips_and_exits_clean` red across two
commits while separating a change from its justification. Resolved as
option (b). Every commit's acceptance criteria now require the suite to
be green **at that commit**. §8's commit list renumbers accordingly.

**RESOLVED — the wave-record emission mechanism** (raised inside the old
E-C5 implementation plan, not as a numbered OPEN). Do not extend the
eleven-positional `printf`. A variable-length chain roster goes to a
small typed Python writer that writes atomically — following the
precedent this file already set when `campaign_spend()` was delegated
because a shell scan misread a nested JSON field. One responsibility
moves; this is not a shell rewrite. See D-E-3's resolution block.

**Note on numbering.** The ruling that resolved the emission mechanism
was labelled "OPEN-E-5". OPEN-E-5 in this document is a *different*
item — the `campaign_spend.py` prefix-glob question — and it remains
open below.

### Still open

**OPEN-E-1 — Is the directory model worth its diff?**
D-E-1 argues yes; the two-character prefix fix would also close the §1
incident. *Resolved by*: an operator decision on whether campaign
control state is expected to grow (more control files, more summary
kinds, a campaign manifest). If it is not, the prefix fix is the correct
minimal change and this PR shrinks by roughly two thirds.

**OPEN-E-2 — Should chain workspaces move under the campaign home?**
§4.4 says no. *Resolved by*: whether any future campaign is expected to
reuse a run name across campaign ids. If run names remain
campaign-prefixed, the move buys nothing and costs
`campaign_spend.py:58`, every report path, and the resume guard.

**OPEN-E-3 — Should the Gate pair runner gain a stop channel?**
It has none today (§3.5, D-E-4). Adding one is a *stop semantics*
change, out of §20.7's scope, but a 6-hour Gate with no graceful stop is
a real operator gap. *Resolved by*: an operator decision; if yes, it is
its own PR, not PR E.

**OPEN-E-4 — Is `advice/workflow/v18r_${FLAVOR}_explorer.json` (`:310`)
the intended advice for a V20 campaign?**
`v19_gate0_arch.json` / `v19_gate0_loss.json` exist and are not used by
the formal queue. This is a scientific decision the code cannot answer,
and D-E-6's fix makes the *role* correct without touching *which file*.
*Resolved by*: the operator naming the V20 advice files. **Until then,
D-E-6 fixes the role only, and the `v18r_` prefix stays.**

**OPEN-E-5 — Does `campaign_spend.py:58`'s
`glob(f"{campaign_id}_*/token_usage.jsonl")` mis-attribute spend when
one campaign id is a prefix of another** (e.g. `v20` and `v20a`)?
Not exercised by any current pair of ids, and not in PR E's scope, but
it is the same defect class. *Resolved by*: a test with two such ids.
If confirmed, file it separately rather than widening this PR.

The five below were raised by the deeper per-commit audit (§8) and did
not exist in the first draft.

**OPEN-E-6 — Does `sdsc_submission_scripts/README.md` gaining a
campaign-control section count as in-scope doc sync, or as new
documentation work?**
A grep for `v19`, `v18r`, `queue` and `gate0` in that README matches
**nothing**: the folder map covers `run_chain.sh`, `_chain_common.sh`,
`run_one_iteration.py`, `submit_one_iteration.slurm`, the Tier-3 runner
and the auxiliary scripts, and has never listed any campaign launcher.
§12's artifact 4 (a record of which historical layouts remain readable)
has nowhere to live without creating that section. *Resolved by*: an
operator ruling that the section is in scope for E-C7 — the author's
reading, since the doc-sync rule requires creating a minimal doc where
none exists — or a decision to file it separately, in which case
artifact 4 needs a different home.

**OPEN-E-7 — Should the Gate runner's `GATE_ROOT` gain a
`$GATE_RUN_PREFIX` subdirectory, or only prefixed filenames?**
D-E-4 proposes filenames only (`${GATE_RUN_PREFIX}_pair_summary.json`),
which removes the verified overwrite hazard with two literal changes. A
directory would be tidier and would match the queue's new model, but it
strands the existing Gate evidence under a now-unused layout. *Resolved
by*: an operator preference. Author's recommendation: filenames only.

*(OPEN-E-8 and OPEN-E-9 were resolved on 2026-08-04 — see "Resolved"
above.)*

**OPEN-E-10 — the stale `WAVE_WALL_SECONDS` default in the docs.
DEFERRED, still open, and deliberately NOT part of PR E.**
`docs/running_chain_test.md:142` and
`docs/design/runtime_estimation_and_calibration.md:3841-3842` both state
the default is `86400`. The code is `259200`
(`v19_queue_runner.sh:89`), and
`test_v19_campaign_pinning.py:190` asserts the cap exceeds 86400 — so
the code is correct and both docs are stale.

**Operator ruling, 2026-08-04: this is a separate docs follow-up. Do not
fold it into PR E**, even though E-C7 opens both files. The finding is
recorded here so it is not lost, and E-C7 carries an explicit acceptance
criterion that `WAVE_WALL_SECONDS` still reads `86400` after the doc-sync
commit — the deferral is verified rather than assumed. *Closed by*: its
own doc-only change.

---

## 15. §20.11 review template

```
Problem statement:      A previous campaign's queue-level STOP file, left at
                        $WS_ROOT/STOP, blocked a new campaign's launch
                        (parent §9.1). One campaign's terminal state held
                        authority over another's.
Confirmed evidence:     v19_queue_runner.sh:104 (the defect, still on master);
                        :81-82 show CAMPAIGN_ID already threaded through the
                        two neighbouring paths; :80 MAX_CONC=2 is read only
                        by :416; the Gate pair summary at gate runner :59 is
                        not derived from GATE_RUN_PREFIX and has already been
                        overwritten once (:379-382). Zero Python readers of
                        campaign state. The role-derivation defect is FIXED
                        and merged ahead of PR E (fe51377c, PR #165).
Scope:                  Campaign path model; validated typed campaign identity;
                        campaign stamp + mismatch guard; legacy compatibility;
                        typed atomic wave/pair summary writer; Gate summary
                        scoping; one remaining campaign-identity defect
                        (D-E-7); a shell isolation test.
Out of scope:           Stop semantics; no-respawn; deleting legacy evidence;
                        workspace relocation; an N-chain scheduler; wave
                        ordering; bands; advice content; any node; any
                        EXISTING core/ module; the WAVE_WALL_SECONDS doc fix
                        (OPEN-E-10, deferred by ruling).
Production callers:     sdsc_submission_scripts/v19_queue_runner.sh (queue),
                        v19_gate0_pair_runner.sh (Gate). _chain_common.sh is
                        read but not changed. Two NEW Python modules under
                        core/ and scripts/, called by the launcher exactly as
                        campaign_spend.py (:236-243) already is. No existing
                        Python module is modified.
Persistent schema impact: Wave summary record gains `chains` + `campaign_id`
                        and moves to a typed atomic writer; arch_*/loss_*
                        retained as a labelled mirror (FU-E-1). New
                        control/campaign.json stamp. Legacy files read,
                        never rewritten.
Backward compatibility: BC-1..BC-5 (§4.3). No file moved, rewritten or deleted.
                        One new refusal path: an invalid campaign id (BD-5).
Implementation checkpoints: E1 path model, E2 backward compat, E3 mismatch
                        guard, E4 stop semantics, E5 recovery validation.
                        Commits E-C1..E-C7 (§8), each independently green.
Deterministic tests:    Layer 1 (§9) — eleven named defects, each with the
                        statement of how it fails.
Layer-2 evaluation:     Multi-campaign isolation, two synthetic campaigns,
                        with a negative control that fails on revert.
Bounded real validation: Layer 3 — the real runner executed against a temp
                        WS_ROOT with a screen shim. No GPU, no API.
Type checking:          Pyright run per commit with the CI-reproducing
                        invocation; before/after error counts recorded.
                        Coverage gaps recorded, not claimed: pyrightconfig
                        excludes `tests` and does not include
                        sdsc_submission_scripts, which is why the new Python
                        is placed under core/ and scripts/ (§3.13). Mode is
                        "basic"; PR E does not change it (FU-E-6).
CI vs local:            Every layer touches machine state, so every layer is
                        run both locally and on CI. Local-only results are
                        reported as "locally green, CI pending".
Failure classification: Not applicable — PR E introduces no runtime failure
                        class. A campaign-ID mismatch and an invalid campaign
                        id are startup refusals with named diagnostics, not
                        classified failures.
Attribution:            Not applicable — no OOM, no resource decision.
Genericization impact:  §7 — seven questions answered; closes FU-B-7.
Hardcoding introduced:  None. Four new path values and one identifier pattern,
                        all configured policy with environment overrides and
                        documented defaults.
Hardcoding removed:     v19_queue_runner process-guard literal (:259);
                        MAX_CONC=2 (:80, closes FU-B-7); the two-role state
                        schema (:226-229); an unvalidated campaign id used as
                        a path component; "gate": "v19_gate0" (gate :290);
                        gate0_pair_summary.json (gate :59). The v19_loss_
                        role literal was removed ahead of PR E by #165.
Hardcoding deferred:    FU-E-1 arch/loss mirror keys; FU-E-2 N-chain launcher;
                        FU-E-3 v18r historical surface; FU-E-4 shared
                        identifier extraction from observation_store;
                        FU-E-5 shared atomic-write helper; FU-E-6 pyright
                        coverage and mode.
Artifacts:              §12 — nine.
Stop conditions:        §11 — seven.
Merge criteria:         §10 — twelve.
Dependencies:           None. fe51377c (PR #165) is already on master.
Operator decisions:     D-E-1..D-E-5, D-E-7, D-E-8 pending (§5).
                        D-E-6 APPROVED and DONE — merged fe51377c.
                        D-E-9 APPROVED 2026-08-04.
                        Resolved 2026-08-04: E-8 (id validation -> D-E-9,
                        enforced in E-C2), E-9 (no red intermediate -> E-C2
                        and E-C4 merged, list renumbered), and the wave-record
                        emission mechanism (-> typed atomic Python writer).
                        Deferred 2026-08-04: OPEN-E-10 leaves PR E entirely.
                        Still open and gating commits: OPEN-E-1 (the whole
                        path-model mechanism), OPEN-E-2, OPEN-E-3,
                        OPEN-E-4, OPEN-E-5, OPEN-E-6 gates E-C7,
                        OPEN-E-7 gates E-C5.
```
