# Design: V20 PR E — Campaign-scoped control state

- **Status**: **IMPLEMENTED — all ten commits landed and pushed;
  awaiting Draft PR, exact-head CI and operator review.** Branch
  `feature/v20-pr-e-campaign-scoped-control`. See §16 for the
  implementation ledger, the measured evidence and the unresolved
  follow-ups. **CI: PASS** on the exact head `b0f83568`
  (`Lint + Type + Unit Tests`, 9m53s, run 30959782093).
  Draft PR: #169.

  *Design history.* Rev 3's architecture direction was approved
  (operator, second review 2026-08-04) with nine corrections applied;
  the §5 deviations were then signed off individually during
  implementation (D-E-3 with one correction found by the E-C4 audit,
  D-E-7 with the fixed-string addition).
  Rev 3 changed the design in six substantive ways, not just the prose:
  legacy compatibility became a campaign-level adoption mode rather than
  a per-record fallback (BC-2); the override surface narrowed to three
  values (§4.2); the admission sequence became one ordered guard
  (§4.2a); the identifier rule was corrected to *equal to* `.`/`..`
  rather than *contains* (D-E-9); the wave record gained a defined
  canonical/derived contract with `record_id` (D-E-3a); and the
  commit plan grew to eight independently green commits (§8).
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
# v19_queue_runner.sh:334
--advice 'advice/workflow/v18r_${FLAVOR}_explorer.json' \
```

`FLAVOR` is supplied by `launch_chain()`'s fourth parameter (`:270`).
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
prefix is `v18r_` (`:334`) while `advice/workflow/v19_gate0_arch.json`
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

## 3a. Strict-shell failure semantics — read-only audit, `master@59dff189`

Commissioned after the fail-closed hotfix (#168) found that a bare
`VAR="$(cmd)"` under `set -e` terminates the shell *before* any
classification, record or cleanup runs. PR E adds several shell→Python
helper calls on exactly that path, so this is execution semantics the
freeze must own, not tidying.

**No production code was modified by this audit.** Load-bearing cases were
confirmed by controlled failure injection, never by reading alone.

### 3a.1 The measured strict-shell state

```text
v19_queue_runner.sh        errexit ON   nounset ON   pipefail ON
v19_gate0_pair_runner.sh   errexit OFF  nounset ON
```

Both measured by sourcing and inspecting `$-`, not read from `set` lines.
`errexit` reaches the queue runner from `_chain_common.sh:40`, which it
sources at `:61` — it is **not** set in the runner itself, which is why a
reader looking only at the runner would conclude it is absent.

**The Gate runner has no `errexit` at all.** The same construct therefore
behaves differently in the two files, and a pattern proven safe in the Gate
runner proves nothing about the queue runner.

### 3a.2 The finding that scopes everything else

Bash **suspends `errexit` inside a function invoked as a condition**.
Verified by injection:

```text
set -e; f() { false; echo AFTER; }
if f; then ... fi     -> AFTER runs, shell survives
f                     -> shell dies at `false`
```

So the hazard is **not** a property of the construct. It is a property of
the construct's *invocation context*:

```text
inside `if fn`, `fn ||`, `while fn`   -> errexit suspended, failures return
top-level / inside a bare-called fn   -> errexit terminates immediately
```

`launch_chain` and `wait_and_record` are both condition-invoked, so their
internals are suspended. `main` is called bare (`:611`), so **its top level
is the exposed surface** — which is exactly where `campaign_spend` sat, and
exactly where PR E adds its new calls.

### 3a.3 Inventory — 26 occurrences, classified

| class | meaning | count |
|---|---|---|
| **A** | explicitly guarded (`\|\|`, `&&`, condition) | 6 |
| **B** | errexit suspended by condition-invocation | 2 |
| **B** | intentionally fatal, or cannot fail | 7 |
| **B** | Gate runner — no errexit, hazard cannot arise | 9 |
| **C** | strict-shell termination bypasses classification | **0 remaining** |

Load-bearing classifications, with their evidence:

| site | verdict | evidence |
|---|---|---|
| `:344` `SPID="$(screen -ls \| grep …)"` | **B** | `grep` returns 1 on no match and `pipefail` would propagate it — but it is inside `launch_chain`, which every call site invokes as `if launch_chain …`. Suspended. |
| `:380` `WAITED=$(( … ))` | **B** | inside `wait_and_record`, invoked with `\|\|`. Suspended. |
| `:101 :428 :445 :548 :582` `date` | **B, intentionally fatal** | a failing `date` means the host is broken; there is no useful classified refusal, and continuing with a wrong timestamp is worse. Retained deliberately. |
| `:502 TAG="$(band_tag …)"` | **B** | injected with `"not-a-band"` and `""`: returns **rc=0** both times. It cannot terminate the shell. *Separate observation, not strict-shell*: it silently yields `00_00` for malformed input rather than refusing — recorded as **FU-E-10**, outside PR E. |
| `:474` `campaign_spend` | **A** | guarded by #168; the regression test also asserts `errexit` is still on, so the guard cannot become decoration. |
| `_chain_common.sh:228` | **B** | inside `filter_roster`, whose only call site (`:421`) is a `while … done < <(…)` process substitution — a subshell whose failure does not terminate the parent. |

**The only class-C defect ever found on this path was `campaign_spend`, and
it is fixed.** The sweep did not turn up a second one.

### 3a.4 The invocation pattern PR E freezes

Every new shell→Python helper call PR E adds **must** enter an explicit
failure-handling context:

```bash
if OUT="$(helper …)"; then
    :
else
    RC=$?
    log "…"                      # diagnostic, naming the command
    record_queue_stop "<reason>" "$WAVE" "…"   # persisted classification
    exit 1                       # the queue-refusal convention
fi
```

Equivalently `OUT="$(helper)" || RC=$?` followed by an explicit check.

**Forbidden**, because the second line may be unreachable:

```bash
OUT="$(helper)"
RC=$?
```

Each such call site's tests must assert **all** of: the expected reason is
recorded; the expected exit code is used; the diagnostic and stderr are
visible; cleanup ran; `errexit` is still enabled; and the dangerous form
fails a mutation.

### 3a.5 Disposition

* **Nothing is added to PR E's commits from this audit** — there is no
  class-C defect left to fix.
* **No predecessor hotfix is required**; the one that existed became #168.
* **No blanket rewrite.** The class-B intentionally-fatal `date` calls stay
  exactly as they are: wrapping them would convert a broken-host signal
  into a silently-continuing run, which is the opposite of the correction
  #168 made.
* **FU-E-10** — `band_tag` yields `00_00` for malformed input instead of
  refusing. Not strict-shell, not PR E, recorded so it is not lost.

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
├── <campaign_id>_wave_state.jsonl         LEGACY — readable ONLY under adoption (BC-2)
├── <campaign_id>_queue_runner.log         LEGACY — never read, never written
└── STOP                                   LEGACY GLOBAL — observed and recorded, no authority
```

Resolution, in one place. **Exactly three values are overridable, and
the subdirectories are not among them** (operator ruling, 2026-08-04):

```bash
# --- overridable -----------------------------------------------------
WS_ROOT="${WS_ROOT:-…}"                          # campaign COLLECTION root
CAMPAIGN_HOME="${CAMPAIGN_HOME:-$WS_ROOT/$CAMPAIGN_ID}"
QUEUE_STOP_FILE="${QUEUE_STOP_FILE:-$CAMPAIGN_HOME/control/STOP}"   # compat only

# --- derived, NOT independently overridable --------------------------
CAMPAIGN_CONTROL_DIR="$CAMPAIGN_HOME/control"
CAMPAIGN_STAMP="$CAMPAIGN_CONTROL_DIR/campaign.json"
QUEUE_STATE_DIR="$CAMPAIGN_HOME/queue_state"
WAVE_STATE="$QUEUE_STATE_DIR/wave_state.jsonl"
LOGF="$QUEUE_STATE_DIR/queue_runner.log"
PAIR_SUMMARY_DIR="$CAMPAIGN_HOME/pair_summaries"
```

**Why the subdirectory overrides are removed.** An earlier draft made
`CAMPAIGN_CONTROL_DIR`, `QUEUE_STATE_DIR` and `PAIR_SUMMARY_DIR`
independently overridable, on the general principle that machine-specific
paths should be configurable. That principle is right and the application
was wrong: independent overrides let two campaigns be pointed at one
`QUEUE_STATE_DIR`, which **recreates the exact cross-campaign authority
defect this PR exists to remove** — campaign B's runner would then read
completion records written by campaign A. A configuration surface that
can reconstruct the defect is not a configuration surface; it is the
defect with a flag on it. One override (`CAMPAIGN_HOME`) moves the whole
campaign coherently; three overrides let its parts drift apart.

`QUEUE_STOP_FILE` survives as a **compatibility override only**, because
existing operator muscle memory, the docs table at
`docs/running_chain_test.md:141` and `test_c13_stop_semantics.py:161-171`
all pass it explicitly. Only its **default** moves. It is not a
general-purpose relocation knob and the docs must not present it as one.

**The campaign stamp** (`control/campaign.json`) is what makes E3
enforceable given §3.2's finding that nothing writes a STOP file:

```json
{"campaign_id": "v20a", "created_at": "…Z", "ws_root": "…",
 "campaign_home": "…", "runner": "v19_queue_runner.sh", "runner_pid": 12345,
 "legacy_adopted_from": null}
```

#### 4.2a The campaign admission sequence — one ordered guard

An earlier draft required the stamp mismatch to be refused "before any
directory is created", while a different commit created those
directories. **That ordering was impossible**, and the operator's review
caught it. The two guarantees are different and are now stated
separately:

```text
invalid campaign_id      -> refuse before ANY mkdir
foreign/malformed stamp  -> refuse before any new state write, any STOP
                            read, and any chain launch
                            (pre-existing directories are not this run's
                             side effect, so their existence is not a
                             violation)
```

Both are satisfied by giving **one guard the whole sequence**, in this
order:

```text
1. validate campaign_id                     -> refuse: nothing created
2. inspect the existing campaign home       -> read-only
3. validate an existing stamp               -> refuse: nothing written
4. create the directories                   -> first side effect
5. atomically create the stamp if absent    -> first writer wins
```

Step 5 follows an existing precedent exactly:
`write_run_invariants()` (`core/run_invariants.py:190-222`) publishes
with `os.link`, which **fails when the target exists** instead of
overwriting, and `ensure_run_invariants()` falls through to validation on
`FileExistsError`. That is the semantics the stamp needs — first writer
wins, a concurrent loser validates instead of clobbering — and it is
already written, tested and in production. PR E reuses the pattern.

Steps 1-5 are one responsibility with one entry point, which is what
makes the ordering guarantee checkable rather than distributed across
commits. E-C2 owns the whole sequence.

### 4.3 Backward-compatibility rules

**BC-1 — nothing on disk is moved, rewritten or deleted by shipped
code.** Historical layouts (§3.10) stay exactly where they are.

**BC-2 — legacy compatibility is a campaign-level MODE, not a
per-lookup retry.**

An earlier draft specified a per-record fallback: if the new wave state
has no completion record for a run, consult the legacy file, and if that
shows `exit: 0`, skip the launch. **The operator's review rejected this,
correctly.** It is stated as "readable, never authoritative" but it *is*
authority — its worst case is that both states exist, a run is recorded
complete only in the legacy file, and the launch is skipped on the
strength of a file the new campaign was never supposed to obey. That is
the §1 defect in a different costume: cross-*state* authority instead of
cross-*campaign* authority.

The replacement is an **adoption decision made once, at first start,
and recorded**:

```text
FIRST START ONLY
  the campaign's new state does not exist
  AND a legacy state file for the SAME campaign_id exists
    -> the stamp records  legacy_adopted_from = <legacy path>
    -> this campaign may read legacy completion evidence, READ-ONLY

ONCE THE NEW wave_state EXISTS
    -> the legacy file is NEVER consulted again, for any record
```

Three properties follow, and each is a test in §9:

- the decision is **auditable** — it is a field in the stamp, not an
  implicit behaviour of a lookup;
- it is **monotonic** — adoption can only be granted at first start, so
  a legacy file appearing later (restored from a backup, copied by an
  operator) cannot acquire authority over a running campaign;
- it is **scoped** — adoption names one path for one campaign id, so a
  legacy file belonging to a different campaign is never in range.

A campaign that starts fresh after PR E has `legacy_adopted_from: null`
and no legacy read path at all. All writes go to the new location in
every case.

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

- [x] **Approved with one correction — operator ruling, 2026-08-04.** The
  E-C4 audit found that the example record's `{"run": …}` key makes a
  failed chain satisfy `chain_completed`; the field is `run_name`. See
  E-C4's implementation record.

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

#### D-E-3a — Dual-write consistency: one canonical source, one derived view

One record goes to two places, so which one is true has to be stated
before it is written, not discovered after the two disagree.

```text
canonical source :  <campaign_home>/queue_state/wave_state.jsonl   (append-only)
derived view     :  <campaign_home>/pair_summaries/wave_<n>_<band>.json

write order:
  1. append the record to the canonical JSONL, then flush + fsync
  2. only then, atomically write the derived per-wave file
```

**Why this order.** The JSONL is append-only history; the per-wave file
is a single mutable snapshot. Writing the durable, append-only fact
first means a failure between the steps loses the *convenience*, never
the *evidence*.

**If step 2 fails**: the fact is already preserved canonically, the run
**fails explicitly** rather than continuing quietly, and the derived
file is rebuildable from the JSONL. A silently missing summary is the
failure mode the launcher's own comment warns against — an aborted wave
must not be the one case that leaves no summary (`:513-514`).

**If step 1 fails**: nothing is written anywhere and the run fails. The
derived file is never written ahead of its canonical record, so a
per-wave file that exists without a matching JSONL line is a detectable
inconsistency rather than a normal state.

**`record_id` — required, because the two views age differently.** The
JSONL *appends* and the per-wave file *overwrites*. A retried wave under
the same campaign therefore produces two JSONL records and one file, and
without an identifier there is no way to say which record the file
corresponds to. Every wave record carries:

```text
record_id = <campaign_id>:<wave>:<band_tag>:<attempt>
```

`attempt` is the count of existing canonical records already matching
the first three fields, resolved by the writer from the JSONL at write
time — so it is derived from persisted evidence, not from launcher
state that a restart would lose.

The derived file is defined to hold **the latest attempt**, and carries
its own `record_id`, so:

- "which attempt is this file?" is answered by reading the file;
- "how many attempts were there?" is answered by the canonical JSONL;
- a duplicate is identified as *the same `record_id`* — which must never
  occur, and a test asserts a retried wave produces a **different**
  `record_id` rather than a silent second copy of the first.

**Not in scope**: reconciling or rebuilding the derived files for
historical waves. Nothing on disk is rewritten (BC-1), and the rebuild
path is documented rather than implemented — **FU-E-7**.

### D-E-4 — The Gate pair summary is scoped and stamped; the Gate gains no stop channel

- [x] **Approved with all three sub-decisions closed — operator ruling,
      2026-08-04.** Prefixed filenames only, **no** new subdirectory
      (closes OPEN-E-7); **no** new Gate stop channel (OPEN-E-3 becomes a
      follow-up, not PR E); and `GATE_RUN_PREFIX` must pass the **same**
      safe-path-component validator as `campaign_id`. Historical
      `gate0_pair_summary.json` is untouched.

Three parts.

**Do:** `SUMMARY` (`v19_gate0_pair_runner.sh:59`) derives from
`GATE_RUN_PREFIX` like every other name the file builds
(`$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`), and the record's
hardcoded `"gate": "v19_gate0"` (`:290`) becomes the resolved prefix.
This closes the verified overwrite hazard the file documents against
itself at `:379-382`. The runner log (`:63`) gets the same treatment.

**Also do:** validate `GATE_RUN_PREFIX` with the **same** typed
safe-path-component validator as `campaign_id` (D-E-9). It is written
into filenames (`:59`, `:63`) and into the record's `"gate"` field
(`:290`) — the identical hazard for the identical reason. An empty
prefix yields `_pair_summary.json`; a separator, or a segment equal to
`.` or `..`, escapes `GATE_ROOT`. Reusing one validator rather than
writing a second is what keeps the two rules from drifting apart.

This creates a dependency from E-C5 on E-C2's typed identity that E-C5
would not otherwise have. Accepted deliberately: one shared rule beats
two rules that happen to agree today.

**Do not:** add a stop file channel to the Gate runner, and **do not**
give `GATE_ROOT` a `$GATE_RUN_PREFIX` subdirectory. The Gate has no stop
channel today — its only trap is `trap write_summary EXIT` (`:304`) and
its only bound is `WALL_CAP_SECONDS` (`:48`). Adding one is a *stop
semantics change*, out of §20.7's scope; it becomes a follow-up
(**FU-E-8**), not a PR E commit. A prefix subdirectory would strand the
existing Gate evidence under a now-unused layout for no additional
isolation, since prefixed filenames already remove the overwrite
collision.

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

- [x] **Approved with one addition — operator ruling, 2026-08-04**: the
  exclusion must be FIXED-STRING (`grep -vF`). The basename contains a
  `.`, which as a regex would widen the exclusion to processes that are
  not this runner. See E-C6's implementation record.

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

**What is taken.** A narrow typed identifier in `core/`, validated as
exactly two rules:

```text
re.fullmatch(r"[A-Za-z0-9._-]{1,128}", campaign_id)   # from _WRITER_ID_RE
and campaign_id not in {".", ".."}                    # the gap it leaves
```

**The second rule rejects the id *equal to* `.` or `..`. It does not
reject an id that merely *contains* `..`.** An earlier draft was
inconsistent about this and the operator's review corrected it:
`alpha..beta` is a legal directory name, cannot traverse anywhere,
and must be allowed. The only traversal risk is a path *segment* that
is exactly `.` or `..`, and since `/` and `\` are already rejected by
the character class, the id is always exactly one segment — so
comparing the whole string against `{".", ".."}` is complete.

The first rule carries the rest: empty is rejected by `{1,128}`; `/`,
`\`, control characters, NUL and every absolute-path form are rejected
by the character class; over-length is rejected by the bound.

**One rule, stated once, three places.** The validator, its tests
(§9 Layer 1) and BD-5 all say *equal to* `.` or `..`, never *contains*.
A test asserts `alpha..beta` is **accepted**, so the stricter reading
cannot creep back in unnoticed.

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

- [x] All campaign paths resolved in exactly one block, derived from
      `CAMPAIGN_HOME`; **only** `WS_ROOT`, `CAMPAIGN_HOME` and the
      compatibility-only `QUEUE_STOP_FILE` are overridable (§4.2)
      — E-C2
- [x] Setting `QUEUE_STATE_DIR` / `CAMPAIGN_CONTROL_DIR` /
      `PAIR_SUMMARY_DIR` in the environment has **no effect** — proved by
      test, because an override that split them could point two
      campaigns at one state directory — E-C1, re-proved at E-C2
- [x] `QUEUE_STOP_FILE` default is `$CAMPAIGN_HOME/control/STOP`; the
      compatibility override still works — E-C2
- [x] `WAVE_STATE` and `LOGF` under `queue_state/` — E-C2
- [x] Wave summaries written **canonical-first**: append + `fsync` the
      JSONL, then atomically write
      `pair_summaries/wave_<n>_<band>.json`, both carrying the same
      `record_id` (D-E-3a) — E-C4; the fsync-before-replace ordering is
      asserted by a spy, not inferred
- [x] Gate pair summary and runner log derive from `GATE_RUN_PREFIX` —
      E-C5; the `"gate"` field too
- [x] **Evidence**: a test enumerates every authority-bearing path the
      runner resolves and asserts each contains the campaign id; it
      fails if a new path is added without it — E-C2,
      `test_campaign_path_resolution.py::test_every_authority_bearing_path_contains_the_campaign_id`
- [x] **Evidence**: the wave/pair record is produced by the typed
      atomic writer (D-E-3) and parses as JSON in the two-chain,
      three-chain and aborted-launch cases — E-C4

### E2 — Backward compatibility

- [x] Legacy compatibility is a **campaign-level adoption mode** decided
      once at first start and recorded as `legacy_adopted_from` in the
      stamp — **not** a per-record fallback (BC-2) — E-C3,
      `core.campaign_identity.resolve_adoption`, called only on the
      stamp-creating branch
- [x] `chain_completed()` consults the legacy file **only** under
      adoption, read-only, for the recorded path only — E-C3; the
      predicate is shared via `_completed_in`, so it is provably
      identical on both files
- [x] Adoption cannot be granted after first start — E-C3; the
      `existing is not None` branch re-validates but never re-decides
- [x] Legacy `$WS_ROOT/STOP` is observed, logged, recorded, and does
      **not** stop the launch — E-C3, `legacy_global_stop_observed`
- [x] No shipped code path deletes, moves or rewrites any legacy file —
      E-C3, proved by bytes and `st_mtime_ns` over a four-file tree
- [x] V18r layout untouched; `v18r_queue_runner.sh` not modified —
      verified at the final head: it is absent from `git diff --name-only
      origin/master...HEAD` (FU-E-3 keeps its self-exclusion pattern)
- [x] **Evidence**: a test with a legacy tree on disk proves (a) an
      adopted campaign still skips a chain completed in legacy state,
      (b) **a campaign whose new state exists does NOT skip a chain
      recorded complete only in legacy** — the blocker case, (c) the
      legacy global STOP does not block, (d) every legacy file is
      byte-identical and mtime-identical after the run — E-C3, all four
      in `test_campaign_admission.py`; (b) additionally asserts the
      `screen` shim recorded the launch

### E3 — Campaign mismatch protection

- [x] `campaign_id` is validated **before any `mkdir`** — empty, `/`,
      `\`, control characters, over-length, and an id **equal to** `.`
      or `..` are refused; an id merely *containing* `..` is **accepted**
      (D-E-9) — E-C2, and E-C2b for the empty case: the shell uses
      `${CAMPAIGN_ID-v19}` so an explicitly empty id reaches the
      validator, while an unset one still defaults
- [x] The same validator guards `GATE_RUN_PREFIX` (D-E-4) — E-C5,
      `core.campaign_identity.validate_path_component`, reached through
      `scripts/validate_path_component.py`; asserted to be one rule, not
      a second copy
- [x] One guard owns the whole ordered admission sequence — validate id →
      inspect home → validate stamp → create dirs → atomically create
      stamp (§4.2a) — E-C2, `core.campaign_identity.admit_campaign`
- [x] `control/campaign.json` created atomically, first writer wins
      (`os.link` semantics, per `core/run_invariants.py:190-222`) — E-C2
- [x] A stamp naming a different `campaign_id` aborts **before any new
      state write, any STOP read and any chain launch**. Pre-existing
      directories are not this run's side effect and are not a violation
      — E-C2
- [x] The refusal names both ids and the stamp path — E-C2
- [x] **Evidence**: a test that pre-writes a foreign stamp and asserts
      non-zero exit, the diagnostic text, that no chain was launched and
      no state file was written; plus a positive control that
      `alpha..beta` is accepted — E-C2,
      `test_campaign_admission.py::TestAForeignStampRefusesBeforeAnyWrite`
      and `::test_an_id_containing_two_dots_is_accepted`

### E4 — Stop semantics preserved

- [x] `test_c13_stop_semantics.py` passes unchanged except for the two
      path expressions it constructs
- [x] Chain stop: after current iteration, `chain_stopped.json`,
      `respawn: false`, exit 99 — unchanged
- [x] Queue stop: current wave finishes, no further wave, `queue_stopped`
      record, exit 99 — unchanged
- [x] Signalled child (`>= 128`) still ends the loop; ordinary non-zero
      still continues
- [x] **Evidence**: a mutation proof — revert the path change alone and
      show the C13 suite still passes, i.e. the C13 guarantees are
      genuinely independent of where the file lives

### E5 — Recovery validation

- [x] Two synthetic campaigns under one root, launched and stopped
      independently, with `screen` shimmed — no GPU, no API — E-C7
- [x] Campaign A stopped → campaign B launches — E-C7; proved by B
      reaching the shim, not by the absence of a stop record
- [x] Wrong-campaign STOP ignored; correct-campaign STOP honoured
      (exit 99 + `operator_stop_requested`) — E-C7
- [x] Both campaigns' state files coexist and neither is written by the
      other's runner — E-C7, asserted by bytes **and** `st_mtime_ns`
      over each neighbouring tree
- [x] A legacy global STOP present throughout, and never honoured — E-C7;
      it also survives byte- and mtime-identical
- [x] **Evidence**: one test module,
      `test_multi_campaign_isolation.py`, **fully green in the committed
      suite** (11 tests), plus **two separate documented mutation runs**:
      reverting `QUEUE_STOP_FILE`'s default to `$WS_ROOT/STOP` fails 3,
      and reverting `CAMPAIGN_HOME` to `$WS_ROOT` fails 6; both restored
      and re-run green

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
name (`:334`), the `arch`/`loss` role vocabulary, and every pinned
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
- [ ] New policy values enter through documented variables, with the
      override surface **deliberately narrow** — `WS_ROOT`,
      `CAMPAIGN_HOME` and the compatibility-only `QUEUE_STOP_FILE`; the
      subdirectories are derived, because independent overrides could
      reconstruct the cross-campaign defect (§4.2)
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
- [ ] New policy is configurable at the campaign level and its resolved
      value is logged; no override can point two campaigns at one state
      directory
- [ ] TIDMAD behaviour preserved through defaults, not special cases
- [ ] FU-E-1..FU-E-8 filed

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
lands with its own tests. The table is the index; the E-C1..E-C8
subsections below are the implementation contract.

| # | Commit | Content | Checkpoint evidence |
|---|---|---|---|
| **E-C1** `[x]` | Campaign path resolver | The resolution block (§4.2); **no consumer changes** — provably behaviour-neutral | pre-E1 |
| **E-C2** `[x]` + **E-C2b** `[x]` | **Campaign admission and the path move** | The typed identity; the ordered admission sequence (§4.2a); the path-default flip; directory creation; atomic first-writer stamp | E1 + E3 |
| **E-C3** `[x]` | Legacy campaign adoption | `legacy_adopted_from` in the stamp; adoption-gated legacy read; legacy-global-STOP observation | E2 |
| **E-C4** `[x]` | Wave record and pair summaries | Typed atomic Python writer; `chains` array + mirror; canonical/derived dual write with `record_id`; `MAX_CONC` deleted | E1 |
| **E-C5** `[x]` | Gate pair summary scoping | `GATE_RUN_PREFIX` derivation for `SUMMARY`, `RUNNER_LOG`, `"gate"`, plus the shared path-component validator | E1 |
| **E-C6** `[x]` | Process-guard self-exclusion (D-E-7) | `grep -v` derives from `$(basename "${BASH_SOURCE[0]}")` | — |
| **E-C7** `[x]` | Multi-campaign isolation test | `test_multi_campaign_isolation.py` | E5 |
| **E-C8** `[x]` | Doc sync (last, per the operator rule) | Every documented variable and default quoted against merged source | merge blocker |

**Four structural rulings from the second operator review are baked
into this table.**

*E-C0 is gone.* The role-derivation fix landed ahead of PR E as its own
hotfix — `fe51377c`, PR #165 (D-E-6). It is no longer PR E's work. Its
audit and its history stay in §3.7 and D-E-6 because they are the reason
the fail-closed posture exists, but no commit here reimplements it. PR E
inherits it and must not regress it.

*No commit is knowingly red.* **Operator ruling, 2026-08-04.** Every
commit below is independently green, and each one's acceptance criteria
require the suite to pass **at that commit**, not at a later one. Where
a commit changes a path that an existing test pins, that test is
re-pointed in the same commit with its defect class preserved and
restated — never left red for a successor to repair. This is the
standing resolution of OPEN-E-9.

*E-C2 owns the whole admission sequence.* The second operator review
found that an earlier split made the stamp guard's ordering
**impossible**: it required refusing a foreign stamp "before any
directory is created" while a *different* commit created those
directories. §4.2a re-states the two guarantees separately — an invalid
id is refused before any `mkdir`; a foreign or malformed stamp is
refused before any new state write, STOP read or chain launch — and
gives one guard the ordered sequence that satisfies both. That sequence
is one responsibility with one entry point, so it is one commit.

*Legacy adoption is its own commit.* It was previously folded into
E-C2, which the review flagged as overloaded. It is now E-C3: the
adoption decision, its consumption, and the legacy-global-STOP
observation — one coherent "what do we do about the past" unit. E-C2
stays green without it because E-C2 re-points the one test that pins the
legacy filename; E-C3 then adds the adoption tests on top.

*D-E-7 leaves E-C2 entirely.* The process guard's self-exclusion has no
causal dependency on the path move, and E-C2 was carrying too much. It
is now E-C6, a small independent commit (operator ruling, 2026-08-04).
It could equally be a follow-up; it stays in PR E only because it is two
lines and the same campaign-identity defect class.

**A note on E4.** No single commit "does" E4 (stop semantics preserved).
It is a property every commit must not break, and it is discharged by
E-C2's and E-C7's parity evidence plus the E4 mutation proof (§9). It is
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
#### IMPLEMENTATION RECORD — E-C1 `[x]` COMPLETE

**Files changed** (2): `sdsc_submission_scripts/v19_queue_runner.sh`
(+35, the resolver block at `:85-115`); new
`tests/unit/sdsc_submission_scripts/test_campaign_path_resolution.py` (14
tests).

**Call path before/after**: unchanged. No consumer reads a new variable.
`LOGF`, `WAVE_STATE` and `QUEUE_STOP_FILE` keep their original definitions
verbatim, and the five new variables resolve to today's locations.

**Checklist**: all §3 implementation items done; all §4 validation items
done; all §5 acceptance criteria met.

**Tests**: `test_campaign_path_resolution.py` — 14 passed, 0.12 s.
Targeted suite `tests/unit/sdsc_submission_scripts/` — **340 passed,
8.3 s, zero existing test files modified**.

**Static**: pyright 0 errors (unchanged from the pre-commit baseline);
`ruff check` clean; `ruff format --check` clean; `bash -n` clean.

**Mutations**, each restored and re-baselined:

| mutation | result |
|---|---|
| give `QUEUE_STATE_DIR` an independent `${NAME:-…}` override | 1 test fails |
| flip `CAMPAIGN_HOME` to E-C2's target early | 8 tests fail |

The second is the parity proof working in the direction that matters: if
E-C2's move happens by accident inside E-C1, eight assertions say so.

**Deviations from the plan**: none. Scope, non-goals and the "no `mkdir` at
definition scope" constraint were all honoured;
`test_source_safe_entry.py` passes unmodified.

**Process note worth keeping.** The first attempt at this commit bundled
the edit with a shell command that sourced the runner. The repository's
launch guard blocked the *whole* invocation, so the edit never applied —
and the block's output was briefly misread as a partial success. Verified
afterwards by grepping for the new variables, which is why the miss was
caught before any test was written against a file that had not changed.
The verification now lives in a committed test rather than an ad-hoc
source, which is the better outcome anyway.

**New follow-ups**: none.

**Remaining risk**: E-C1 is inert by construction, so its risk is confined
to E-C2 flipping the defaults. The parity tests above are what will make
that flip visible.

**Next authorized checkpoint**: E-C2.

### E-C2 — Campaign admission and the path move

*(Restructured after the second operator review: the stamp guard's
ordering was impossible as previously split, and D-E-7 and legacy
adoption have both left this commit. See §8's structural rulings.)*

#### 1. Goal

Make `CAMPAIGN_HOME` real and bind this run to it through **one ordered
admission sequence**: validate the id, inspect any existing campaign
home, validate any existing stamp, create the directories, atomically
create the stamp if absent.

**This is the commit that closes the §1 defect**, and the sequence is
one commit because its ordering guarantee is only checkable if one guard
owns the whole order. §4.2a states the two guarantees it must satisfy:
an invalid id is refused before **any** `mkdir`; a foreign or malformed
stamp is refused before any new state write, any STOP read and any chain
launch. Splitting those across commits is what made the earlier draft's
ordering unsatisfiable.

#### 2. Scope

**Changes**: `sdsc_submission_scripts/v19_queue_runner.sh` —
`:81`, `:82`, `:104` (defaults flip to §4.2's targets), `:390`
(`mkdir -p "$WS_ROOT"` becomes the campaign directories), one new
admission guard called once from `main()` before the `--only` branch
(`:392`), and the startup log line so the operator can read the resolved
stop path.

**New Python** (D-E-9, placement forced by §3.13): the typed campaign
identity and the stamp model in `core/`, plus the thin CLI entry in
`scripts/` the shell calls. Both inside `pyrightconfig.json`'s
`"include"`.

**Tests updated**: `test_v19_queue_runner.py:294-304`
(`test_completed_only_selection_skips_and_exits_clean`) is re-pointed at
the new state location **in this commit**, so nothing is left red. Its
defect class is unchanged and must be restated in its docstring: *a
targeted run of an already-completed chain must skip it, never relaunch
it and clobber its workspace.* The legacy-filename variant of that
scenario is added in E-C3, where adoption exists.
`test_c13_stop_semantics.py:161-171` passes `QUEUE_STOP_FILE` explicitly
and should keep passing untouched — **verify, do not assume.**

**Non-goals.** No legacy read path of any kind — E-C3. No
legacy-global-STOP observation — E-C3. No D-E-7 process-guard change —
E-C6. No wave-record change — E-C4. No Gate runner — E-C5. The
chain-level STOP (`_chain_common.sh:694-696`) is not touched.

**Must stay unchanged**: stop check points (before each wave `:444`,
after each wave `:535`); `record_queue_stop`'s fields (`:206-211`); exit
code 99 (`:106`, `:447`, `:538`); the trap channel (`:190-196`);
`chain_completed()`'s contract — complete iff a record with `"exit": 0`
exists for that run name (`:213-219`) — which this commit re-points but
does not redefine; the workspace-exists guard (`:255`); `V19_RESUME`
semantics; `role_for_run()` (`:134-170`); the `--only` path; the
source-safe guard; the three existing launch guards' order.

**Dependencies**: E-C1.

#### 3. Implementation plan

*The typed identity (D-E-9)*
- [ ] Add the identity in `core/`: `re.fullmatch(r"[A-Za-z0-9._-]{1,128}")`
      — the `_WRITER_ID_RE` pattern (`observation_store.py:38`) — **plus**
      rejection of an id **equal to** `.` or `..`
- [ ] Do **not** reject an id merely containing `..`: `/` and `\` are
      already excluded by the class, so the id is always one path
      segment and `alpha..beta` cannot traverse. A test asserts it is
      **accepted**
- [ ] Add the `scripts/` CLI entry; model it on `campaign_spend.py`,
      which the launcher already calls at `:236-243`

*The stamp*
- [ ] Model the stamp on `core/run_invariants.py:190-222`
      (`write_run_invariants`): write to a same-directory `mkstemp`, then
      publish with `os.link`, which **fails when the target exists**
      rather than overwriting. That is what makes "first writer wins"
      true under concurrency, and `ensure_run_invariants` (`:303`) is the
      existing example of a loser falling through to validation
- [ ] Fields per §4.2, with `legacy_adopted_from` present and `null` —
      E-C3 populates it, and declaring it here avoids a schema change in
      the next commit

*The sequence, in this order*
- [ ] 1. validate `campaign_id` → refuse with nothing created
- [ ] 2. inspect the existing campaign home → read-only
- [ ] 3. validate an existing stamp → refuse with nothing written
- [ ] 4. create `control/`, `queue_state/`, `pair_summaries/`
- [ ] 5. atomically create the stamp if absent
- [ ] Call the guard from `main()` before the `--only` branch (`:392`);
      confirm by reading `:378-392` that no launch or state write can
      precede it
- [ ] On a step-3 refusal: message naming the stamp path, the stamped id
      and the requested id; non-zero exit; **no wave state written**.
      Recommendation: do **not** append a refusal record to the wave
      state — writing into campaign B's state on a failed launch of
      campaign A is the cross-campaign write this PR forbids. Log to
      stderr

*The path move*
- [ ] Flip the E-C1 defaults from the compatibility values to §4.2's
      targets, in one hunk, and delete the three subdirectory override
      hooks — `control/`, `queue_state/` and `pair_summaries/` are
      derived from `CAMPAIGN_HOME`, never independently set (§4.2)
- [ ] Keep the `mkdir` inside `main()` — `:375-377` states main is the
      only thing that touches the filesystem, and
      `test_source_safe_entry.py` enforces it
- [ ] Confirm `log()` (`:188`) is not called before `queue_state/`
      exists. Inspect every call site reachable before `:390` — the
      argument parser at `:381-388` uses `echo … >&2`, not `log`, but
      verify
- [ ] Add a startup line logging the resolved `CAMPAIGN_HOME`,
      `QUEUE_STOP_FILE` and `WAVE_STATE`, so BD-1's operator-visible
      change is discoverable
- [ ] Inspect what `campaign_spend()` does when the interpreter is
      missing (`:236-243` ends `|| echo "0 0.00"`), then decide the
      admission guard's posture deliberately: a swallowed failure there
      yields a zero spend, but a swallowed failure here would skip the
      guard entirely. **Recommendation: fail closed** — record the
      decision either way

#### 4. Validation plan

**Unit**
- [ ] `QUEUE_STOP_FILE` resolves to `$CAMPAIGN_HOME/control/STOP`
- [ ] `WAVE_STATE` and `LOGF` resolve under `$CAMPAIGN_HOME/queue_state/`
- [ ] `CAMPAIGN_HOME` override moves all four derived paths together
- [ ] Setting `QUEUE_STATE_DIR` in the environment has **no effect** —
      the override was removed deliberately (§4.2)
- [ ] The `QUEUE_STOP_FILE` compatibility override still wins
- [ ] The E1 path-enumeration test: every authority-bearing path
      contains the campaign id
- [ ] Absent stamp → created once, with the resolved id and
      `legacy_adopted_from: null`
- [ ] Matching stamp → accepted, contents not rewritten (compare mtime)
- [ ] Mismatched stamp → non-zero exit, message names both ids

**Integration / pseudo**
- [ ] `test_source_safe_entry.py` still green — sourcing creates no
      directory
- [ ] A `--only` run against a temp root creates the three directories
      and writes its log to the new location
- [ ] A full `--only` run with a foreign stamp: exits non-zero, launches
      nothing (no screen shim invocation), writes no wave state

**Negative / invalid input**
- [ ] D-E-9's refusal set, each its own case: empty; `/`; a path
      containing `/`; an id equal to `.`; an id equal to `..`; an
      absolute path; a backslash; a control character; a 129-character id
- [ ] **Positive control on the same rule**: `alpha..beta` and
      `a.b_c-d` are **accepted**. Without this the validator can silently
      tighten to "contains `..`" and no test would notice
- [ ] Every refusal happens **before** any directory is created —
      asserted by listing the root before and after
- [ ] Malformed, truncated or empty stamp JSON → **STOP**
- [ ] Stamp present but `campaign_id` key absent → **STOP**
- [ ] Stamp whose recorded id fails validation → **STOP**; a stamp
      written before the validator existed must not grandfather in an
      unsafe id
- [ ] Concurrent creation: two writers, one stamp, the loser validates
      instead of overwriting (the `os.link` property)
- [ ] `WS_ROOT` unwritable → reported before any chain launches

**Backward compatibility / default parity**
- [ ] C13 parity: `test_c13_stop_semantics.py` green with **zero
      modifications** — if it needs edits, that is a semantics change
      and must be reported, not absorbed
- [ ] `test_v19_chain_role_resolution.py` green, unmodified
- [ ] The E4 mutation proof: revert only the path defaults and confirm
      every C13 assertion still passes

**Real Gate**
- [ ] None. **No real-training run is authorized by this commit.**

#### 5. Acceptance criteria

- [ ] After a `--only` run against a temp `WS_ROOT` with
      `CAMPAIGN_ID=alpha`, the filesystem contains
      `<tmp>/alpha/control/campaign.json`,
      `<tmp>/alpha/queue_state/queue_runner.log` and
      `<tmp>/alpha/pair_summaries/` — asserted by listing the tree, not
      by echoing a variable
- [ ] `touch <tmp>/STOP` before that run does **not** stop it, and the
      log names the resolved stop path. (The observation *record* is
      E-C3; this commit only proves the legacy path is not consulted.)
- [ ] `touch <tmp>/alpha/control/STOP` **does** stop it, with a
      `queue_stopped` record whose `reason` is `operator_stop_requested`
      and exit code 99
- [ ] `CAMPAIGN_ID=..` exits non-zero and `<tmp>` gains **no** new
      directory — verified by listing `<tmp>` before and after
- [ ] `CAMPAIGN_ID=alpha..beta` is **accepted** and produces
      `<tmp>/alpha..beta/control/`
- [ ] With a stamp naming `beta` under `<tmp>/alpha/control/`, the run
      exits non-zero, the screen shim records zero invocations, and
      `<tmp>/alpha/queue_state/` gains no record from this attempt
- [ ] Removing the admission call makes exactly one test fail (the E3
      reachability mutation proof)
- [ ] `test_c13_stop_semantics.py` diff is empty
- [ ] **The full test suite is green at this commit**
- [ ] Pyright clean over the new `core/` and `scripts/` modules

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Campaign id empty, `/`, `\`, control chars, over-length, or equal to `.` / `..` | **STOP** before any directory is created |
| Campaign id *containing* `..` (e.g. `alpha..beta`) | **ACCEPT** — one path segment, cannot traverse (D-E-9) |
| Campaign-id mismatch against an existing stamp | **STOP** before any state write, STOP read or launch |
| Missing campaign dir | **Created** in step 4; a fresh campaign is the normal case |
| Missing stamp in an existing campaign dir | **Adopt** — write it, proceed. This is every pre-PR-E campaign |
| Unreadable or malformed stamp | **STOP** — cannot prove a match |
| Stamp write loses a race | **Fall through to validation**, per `os.link` semantics; never overwrite |
| Stamp write fails for any other reason | **STOP** — an unstampable campaign cannot be guarded |
| `mkdir` fails (permissions, read-only mount) | **STOP** before any launch, with the path named |
| Legacy `$WS_ROOT/STOP` present | **Not consulted.** Its observation record is E-C3 |
| Legacy wave state present | **Not consulted at all in this commit** — adoption is E-C3 |
| Campaign directory exists from a prior run of the same id | Normal resume; the stamp validates, the workspace-exists guard (`:255`) and `chain_completed()` still decide what relaunches |
| Two campaigns concurrently under one root | Each writes only under its own `CAMPAIGN_HOME`; proven in E-C7 |
| Validator interpreter unavailable | See the implementation step; **recommendation: fail closed**, decision recorded either way |
| Cleanup-script assumptions | None exist (§3.11); nothing to update |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
.venv/bin/python -m pytest tests/unit/core/ -q -k campaign
bash -n sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
git diff --stat -- tests/unit/sdsc_submission_scripts/test_c13_stop_semantics.py
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] C13 diff empty: __
- [ ] observed directory tree after a `--only` run: __
- [ ] `<tmp>` listing before/after the `CAMPAIGN_ID=..` refusal: __
- [ ] `alpha..beta` positive-control result: __
- [ ] admission mutation proof (guard removed → exactly 1 failure): __
- [ ] E4 mutation proof result: __
- [ ] validator-interpreter-unavailable decision recorded: __

#### 8. Commit boundary

- [ ] Independently reviewable: one responsibility — admit this campaign
      and bind it to its state — with one entry point and one stated
      order
- [ ] Independently green: the one test that pinned the old path is
      re-pointed here, not left for a successor
- [ ] No legacy read, no global-STOP record, no D-E-7, no wave-record
      change, no Gate runner, no docs, no unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the observed directory tree,
      both refusal listings, and any deviation from this section

#### IMPLEMENTATION RECORD — E-C2 `[x]` COMPLETE

**Commit**: `<filled at commit>` on
`feature/v20-pr-e-campaign-scoped-control`, on top of E-C1 `ded153d0`.

**Behavior Delta: BD-1, BD-3 (partial), BD-5.** This is the commit that
closes the §1 defect. Every campaign path moved; an invalid campaign id
is now refused; a foreign stamp now stops a run.

**Production files changed**

| File | What |
|---|---|
| `sdsc_submission_scripts/v19_queue_runner.sh` | defaults flipped to §4.2's targets; `QUEUE_STOP_FILE` default moved into `control/`; new `admit_campaign()` helper; admission call + startup path log in `main()` |
| `core/campaign_identity.py` (**new**, 302 lines) | `validate_campaign_id`, `CampaignStamp`, `read_campaign_stamp`, `write_campaign_stamp`, `admit_campaign`, `CAMPAIGN_SUBDIRS` |
| `scripts/campaign_admission.py` (**new**, 71 lines) | the CLI the shell calls; exit 0 admitted / 2 refused, modelled on `campaign_spend.py` |

**Resolved paths, before → after** (`WS_ROOT=<R>`, `CAMPAIGN_ID=v19`):

```text
QUEUE_STOP_FILE  <R>/STOP                      -> <R>/v19/control/STOP
WAVE_STATE       <R>/v19_wave_state.jsonl      -> <R>/v19/queue_state/wave_state.jsonl
LOGF             <R>/v19_queue_runner.log      -> <R>/v19/queue_state/queue_runner.log
CAMPAIGN_STAMP   <R>/v19_campaign.json         -> <R>/v19/control/campaign.json
PAIR_SUMMARY_DIR <R>                           -> <R>/v19/pair_summaries
```

**Observed tree after a real `--only` run** (asserted, not echoed):

```text
<R>/v19/control/campaign.json
<R>/v19/queue_state/queue_runner.log
<R>/v19/queue_state/wave_state.jsonl
<R>/v19/pair_summaries/
```

**Refusal listings.** `CAMPAIGN_ID=..` → rc≠0, `<R>` listing identical
before and after, and no `control/`, `queue_state/` or `pair_summaries/`
appears in `<R>`'s **parent** (the directory a `..` id resolves into).
`CAMPAIGN_ID=alpha..beta` → **accepted**, produced
`<R>/alpha..beta/control/`.

**Tests** — 404 passed in 10.8 s
(`tests/unit/sdsc_submission_scripts/` + `tests/unit/core/test_campaign_identity.py`);
baseline before this commit was 340.

| File | Count | Covers |
|---|---|---|
| `tests/unit/core/test_campaign_identity.py` (**new**) | 32 | D-E-9 refusal set + positive control; both ordering guarantees; stamp read/validate/adopt; first-writer-wins; unwritable root |
| `tests/unit/sdsc_submission_scripts/test_campaign_admission.py` (**new**) | 23 | real-launcher runs: directory creation, stamp contents, startup log, both refusal classes, campaign STOP → exit 99, legacy STOP ignored, reachability + `errexit` |
| `test_campaign_path_resolution.py` (rewritten) | 23 (was 14) | E-C1's parity assertions inverted into E-C2's move; E1 path enumeration; shell↔Python layout parity |

**Static**: pyright **0 errors, 4 warnings** (baseline 0/4 — unchanged;
the two new modules are inside `"include"`). `ruff check` clean.
`ruff format --check` clean. `bash -n` clean.

**Mutation and reachability proofs**

| Mutation | Result |
|---|---|
| Admission call deleted from `main()` | **16 fail** (design predicted "exactly one"; the real figure is reported) |
| Path defaults reverted to pre-E-C2 (7 lines) | **C13: 14/14 still pass** — the E4 proof; 32 of the E-C2 path/admission tests fail |
| `\|\| ADMIT_RC=$?` → bare assignment + `RC=$?` (§3a.4 hazard) | **6 fail** — the 5 refusal cases lose their diagnostic entirely, confirming `errexit` kills the shell before it |
| `value in {".",".."}` → `".." in value` | **2 fail** — both positive controls, in Python and through the shell |

Hygiene: file backups, `__pycache__` cleared, each substitution asserted
`count == 1`, restore verified by `grep -cF`, baseline re-run green after
every restore.

**Decisions recorded**

*Interpreter unavailable → **fail closed*** (the design asked for this to
be decided explicitly). A swallowed failure in `campaign_spend` produced
a zero spend; a swallowed failure here would skip the guard entirely and
launch into a directory whose owner was never proven. There is no safe
default identity.

*Directory creation lives in Python, inside the one guard*, not in the
shell. §2 reads as though the shell's `mkdir` line becomes the campaign
directories, but a shell `mkdir` would necessarily precede the Python
validator and break guarantee 1 — `CAMPAIGN_ID=..` would create state
outside the collection root before anything could refuse it. The whole
ordered sequence is therefore one Python entry point, which is what §4.2a
requires anyway. `mkdir -p "$WS_ROOT"` is **retained**, moved to just
after admission: `WS_ROOT` holds the flat chain workspaces (§4.4) and an
overridden `CAMPAIGN_HOME` would otherwise leave it uncreated.

**Deviations from the frozen plan**

1. **`test_c13_stop_semantics.py` is NOT diff-empty** — 2 lines added,
   pinning `LOGF` beside the `WAVE_STATE` the tests already pinned.
   §4 required this to be reported rather than absorbed, so: it is a
   **test-harness assumption, not a semantics change**. Both tests call
   `record_queue_stop` / `wait_and_record` directly, bypassing `main()`;
   `record_queue_stop` ends in `log()`, and `LOGF`'s directory is now
   created by admission. In production `log()` is unreachable before
   admission — asserted by
   `test_campaign_admission.py::test_no_log_call_precedes_admission`.
   Stop timing, exit code 99, the record's fields and the trap channel
   are untouched, and all 14 C13 assertions pass **unmodified** under
   the E4 mutation.
   *Second-order finding*: `test_the_wall_cap_is_configurable…` runs
   under `set +e`, so its `log()` failure was silent — it passed while
   half-broken. The same one-line pin fixes it.

2. **Two more tests needed re-pointing than §2 named.** §2 named only
   `test_v19_queue_runner.py:294-304`. Also required:
   `TestWaveStateMachine._state_env` (the shared helper — one line, fixes
   6 tests) and `test_v19_campaign_pinning.py::test_queue_state_and_log_carry_the_campaign_id`,
   whose assertion was `"camp1_" in path` (a **prefix**). E-C2 replaces
   the prefix mechanism with a directory, so the assertion now asks for
   the segment `/camp1/`. The concept it guards — a queue-state path two
   campaigns can both resolve to — is unchanged and now stronger.

3. **The admission-removal mutation fails 16 tests, not one.** §5
   predicted "exactly one". Reported as measured; the suite is not
   weakened to match the estimate.

**Defect found in E-C2, corrected in E-C2b** — see the record below. It
was first filed as a follow-up (FU-E-11); the operator's review
(2026-08-04) correctly reclassified it as an **implementation defect
against the identity contract E-C2 had already approved**, not a new
policy question. FU-E-11 is withdrawn.

**Remaining risk — E-C2 and E-C2b are internal checkpoints, not a
releasable state.** A campaign that already has a legacy
`<R>/<id>_wave_state.jsonl` will not see its completion history at these
commits: adoption is E-C3 by design. **Neither commit may be used for a
legacy resume**, no Draft PR may stop at either head, and no unrelated
work may be inserted before E-C3 closes the gap.

**Next authorized checkpoint**: E-C2b, then immediately E-C3 (legacy
campaign adoption).

#### IMPLEMENTATION RECORD — E-C2b `[x]` COMPLETE

*An E-C2 correction, landed as its own commit. `29af020c` is pushed and
is not amended or rewritten.*

**Commit**: `<filled at commit>`.

**The defect.** `CAMPAIGN_ID="${CAMPAIGN_ID:-v19}"` collapses two
different inputs into one. `:-` substitutes the default when the variable
is unset **or empty**, so an explicitly empty id never reached the
validator that D-E-9 requires to refuse it — it silently became `v19`.

The failure mode is the one this PR exists to prevent, arrived at from
the opposite direction: an operator who **clears** `CAMPAIGN_ID`
specifically to avoid reusing an identity is handed exactly the identity
they were avoiding, and then writes into that campaign's control state.

**The fix**, one character:

```bash
CAMPAIGN_ID="${CAMPAIGN_ID-v19}"     # `-`, not `:-`
```

`-` substitutes only when the variable is **unset**, so:

```text
CAMPAIGN_ID unset            -> `v19`, the compatibility default, unchanged
CAMPAIGN_ID explicitly empty -> stays empty -> the typed validator refuses
```

No validator change was needed — `validate_campaign_id("")` already
refuses via the `{1,128}` bound, and `tests/unit/core/test_campaign_identity.py`
already asserted it. The defect was entirely that the shell prevented the
empty string from ever arriving.

**Behavior Delta**: an explicitly empty `CAMPAIGN_ID` now exits 1 instead
of running as `v19`. An unset `CAMPAIGN_ID` is byte-identical to before.
This is BD-5's stated intent, not an extension of it.

**Files changed**: `sdsc_submission_scripts/v19_queue_runner.sh` (the
expansion plus its explanation);
`tests/unit/sdsc_submission_scripts/test_campaign_admission.py` (`_run`
gained `campaign_id=None` to leave the variable genuinely unset — the
distinction cannot be tested without it).

**Tests** — 408 pass (E-C2 baseline 404); 4 new in
`TestAnUnsetIdAndAnEmptyIdAreDifferentInputs`:

| Test | Proves |
|---|---|
| `test_an_unset_id_still_defaults_to_v19` | backward compatibility: `env -u CAMPAIGN_ID` still stamps `v19` |
| `test_an_explicitly_empty_id_is_refused` | non-zero exit with the refusal diagnostic |
| `test_the_empty_id_refusal_touches_nothing` | the whole contract: no directory created, **no STOP consulted**, no state written, no chain launched |
| `test_the_runner_uses_the_unset_only_expansion` | structural, so the one-character difference cannot be re-introduced silently |

**How "no STOP is read" is proven.** Through the exit code, not a
comment. A run that reads a STOP and obeys it exits **99** and leaves a
`queue_stopped` record; a refusal exits **1** and leaves none. The test
arms *both* a legacy `<R>/STOP` and a `<R>/v19/control/STOP`, so if the
empty id resolved to either location the run would stop rather than
refuse — and the assertion is `returncode == 1`.

**Mutation**: restoring `${CAMPAIGN_ID:-v19}` → **3 fail** (both
behavioural cases and the structural guard). The unset-default test stays
green under the mutation, which is correct: it is the compatibility half
of the contract and the mutation does not break it.

**Static**: pyright 0 errors / 4 warnings (unchanged), ruff + format
clean, `bash -n` clean.

**Deviations**: none.

**Next authorized checkpoint**: E-C3, immediately, with no unrelated work
inserted.

---
### E-C3 — Legacy campaign adoption

*(Split out of E-C2 by the second operator review, and redesigned: the
previous per-record fallback was authority in disguise. See BC-2.)*

#### 1. Goal

Let a campaign that was interrupted **before** PR E resume without
relaunching chains it already completed — **without** giving a legacy
file standing authority over a new campaign.

BC-2 states the model: adoption is a **campaign-level mode decided once
at first start and recorded in the stamp**, not a per-lookup retry. The
earlier per-record fallback would have skipped a launch on the strength
of a legacy record whenever the new state happened to lack one, which is
the §1 defect wearing a different hat.

**Why after E-C2.** The decision is a stamp field, and E-C2 owns the
stamp. E-C2 declares `legacy_adopted_from: null`; this commit is the
only thing that ever sets it non-null.

#### 2. Scope

**Changes**: `v19_queue_runner.sh` — `chain_completed()` (`:213-219`)
gains an adoption-gated read; the legacy-global-STOP observation in
`main()`. **Python**: the stamp's `legacy_adopted_from` is populated at
creation time by the admission sequence's step 5.

**New tests**: an adoption class in `test_v19_queue_runner.py` covering
the legacy-filename scenario that E-C2 re-pointed away from the new
location, plus byte-and-mtime identity over a legacy fixture tree.

**Non-goals.** No migration, archiving, deletion or rewriting of any
legacy file. No adoption of another campaign's legacy state. No
adoption decision after first start. No reading of the legacy
`queue_runner.log` — only the wave state is ever adopted. No reading of
the V18r `v18r_queue_state` index (§3.10), which belongs to a runner PR
E does not modify.

**Must stay unchanged**: `chain_completed()`'s predicate — complete iff
a record with `"exit": 0` exists for that run name — which must be
provably identical on both files; the workspace-exists guard (`:255`);
`V19_RESUME` semantics; every stop check point.

**Dependencies**: E-C2.

#### 3. Implementation plan

*The adoption decision — once, at first start*
- [ ] In the admission sequence's step 5 (stamp creation only), set
      `legacy_adopted_from` to the legacy path **iff** the new wave state
      does not exist **and** `$WS_ROOT/${CAMPAIGN_ID}_wave_state.jsonl`
      does exist
- [ ] Never set it when the stamp already exists — adoption is decided
      at first start and is thereafter immutable. This is what makes a
      legacy file restored from a backup mid-campaign harmless
- [ ] Confirm the path recorded interpolates `${CAMPAIGN_ID}`, so
      adoption can never name another campaign's file

*The consumption — gated, read-only*
- [ ] Extend `chain_completed()`: consult the legacy file **only** when
      the stamp records `legacy_adopted_from`, and then only for the
      recorded path
- [ ] Keep the existing `grep … | grep -q` form so the completion
      predicate is provably identical on both files
- [ ] Verify no write path targets a legacy filename: grep for
      `${CAMPAIGN_ID}_wave_state` and confirm every occurrence is a read

*The legacy global STOP (BC-3)*
- [ ] If `$WS_ROOT/STOP` exists, log it with path and mtime and append a
      `legacy_global_stop_observed` record to the **new** wave state,
      matching `record_queue_stop`'s shape (`:206-211`). **Do not remove
      the file, and do not stop**

#### 4. Validation plan

**Unit**
- [ ] First start, new state absent, legacy present → stamp records
      `legacy_adopted_from` and a completed chain is skipped
- [ ] First start, new state absent, **no** legacy → `null`, no legacy
      read attempted
- [ ] **The blocker case**: new state exists *and* legacy exists, run
      completed **only** in legacy → the chain is **launched**, not
      skipped. This is the defect the earlier design would have shipped
- [ ] Adoption is not granted on a later run: stamp already exists,
      legacy file appears afterwards → still `null`, never consulted
- [ ] A legacy file for a **different** campaign id is never in range
- [ ] `legacy_global_stop_observed` is recorded and the run proceeds

**Integration / pseudo**
- [ ] A full `--only` run over a legacy fixture tree exits 0, skips the
      completed chain, and launches nothing

**Negative / invalid input**
- [ ] Adopted legacy file unparseable, truncated or unreadable → **warn
      and continue**, treated as "no completion evidence". Blocking here
      would restore a legacy file's authority over a new campaign
- [ ] Stamp records a `legacy_adopted_from` path that no longer exists →
      **warn and continue**, same reasoning
- [ ] Stamp records a path outside `$WS_ROOT` → **STOP**; adoption names
      one file, and a stamp is not a general file-read capability

**Backward compatibility / default parity**
- [ ] Byte-and-mtime identity over every file in a legacy fixture tree
      before and after a full run — the E2 evidence
- [ ] The legacy global STOP is unchanged and still present afterwards
- [ ] A campaign created fresh after PR E has `legacy_adopted_from: null`
      and never opens a legacy path at all

**Real Gate**
- [ ] None.

#### 5. Acceptance criteria

- [ ] Given `<tmp>/alpha_wave_state.jsonl` with an `"exit": 0` record for
      `alpha_arch_15_19` and **no** `<tmp>/alpha/queue_state/`, a first
      `--only alpha_arch_15_19` run writes a stamp whose
      `legacy_adopted_from` is that path, logs `SKIP … already
      completed`, and the screen shim records zero invocations
- [ ] Given the **same** legacy file but a pre-existing
      `<tmp>/alpha/queue_state/wave_state.jsonl` that lacks the record,
      the chain **is launched** — the shim records one invocation
- [ ] A stamp created without adoption, followed by a legacy file being
      created, followed by another run → the chain is launched; the
      stamp is byte-identical
- [ ] `<tmp>/STOP` present: the run completes and a
      `legacy_global_stop_observed` record naming the legacy path and its
      mtime exists in the **new** wave state
- [ ] Every pre-existing file under `<tmp>` has identical bytes and
      identical `st_mtime_ns` after every run above
- [ ] `grep -n '_wave_state' v19_queue_runner.sh` shows the legacy
      filename only in a read position, inside the adoption branch
- [ ] Full suite green at this commit; pyright clean

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Legacy global STOP present | **Warn + record, continue.** Never honoured, never deleted |
| First start with legacy state present | **Adopt**, record the path in the stamp, read-only |
| New state exists and legacy also exists | **Never consult legacy** — the blocker case |
| Legacy file appears after first start | **Never consulted** — adoption is decided once |
| Adopted legacy file unreadable or malformed | **Warn and continue** — treated as no evidence |
| Adopted path missing at read time | **Warn and continue** |
| Adopted path outside `$WS_ROOT` | **STOP** — a tampered stamp is not a read capability |
| Legacy file of another campaign | Out of range by construction; a test asserts it |
| V18r `v18r_queue_state` index | **Never consulted**; recorded in E-C8's README table so an operator is not surprised |
| Partial migration | Supported by construction — the adoption mode is exactly this case |
| Cleanup-script assumptions | None exist (§3.11); nothing to update |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ tests/unit/core/ -q
grep -n '_wave_state' sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] blocker-case result (legacy-only record → chain LAUNCHED): __
- [ ] byte/mtime identity result over the legacy fixture tree: __
- [ ] `legacy_global_stop_observed` record contents: __

#### 8. Commit boundary

- [ ] Independently reviewable: one coherent unit — what this campaign
      does about the past
- [ ] Independently green at this commit
- [ ] No path changes, no stamp-schema change (E-C2 declared the field),
      no deletion, no archiving, no migration, no docs, no unrelated
      cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the blocker-case result, the
      identity-assertion result, and any deviation from this section

#### IMPLEMENTATION RECORD — E-C3 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of E-C2b `9060b13f`.

**Behavior Delta: BD-2, BD-3 (completes it).** This commit closes the
E-C2 gap: a campaign interrupted before the move can resume again.

**Production files changed**

| File | What |
|---|---|
| `core/campaign_identity.py` | `legacy_wave_state_name`, `resolve_adoption`, `adopted_legacy_state`, `_validate_adoption_source`; `admit_campaign` gains `wave_state` / `legacy_wave_state` and populates `legacy_adopted_from` **only on the stamp-creating branch** |
| `scripts/campaign_admission.py` | the two new arguments; a second output line carrying the adopted path or `-` |
| `sdsc_submission_scripts/v19_queue_runner.sh` | `LEGACY_WAVE_STATE`, `LEGACY_GLOBAL_STOP`, `ADOPTED_LEGACY_STATE`; `chain_completed` split into `_completed_in` + an adoption-gated caller; the BC-3 observation record; the stale header comment naming the pre-move authoritative path |

**The decision, and where it lives.** Adoption is evaluated in exactly
one place — the branch of `admit_campaign` that *creates* the stamp:

```text
the campaign's own wave state does NOT exist yet
AND a legacy wave state for THIS campaign id does
  -> legacy_adopted_from = <that path>
```

The `existing is not None` branch **re-validates** the recorded path but
never re-decides. That single structural fact is what makes adoption
monotonic: a legacy file restored from a backup mid-campaign cannot
acquire authority, because nothing after first start can grant it.

**The predicate is provably identical on both files.** `_completed_in`
holds the original `grep … | grep -q "\"exit\": 0"` and both call sites
use it. Adoption may change *which* file is readable; it cannot change
what "complete" means.

```bash
chain_completed() {
  local RUN="$1"
  _completed_in "$WAVE_STATE" "$RUN" && return 0
  [ -n "$ADOPTED_LEGACY_STATE" ] || return 1
  _completed_in "$ADOPTED_LEGACY_STATE" "$RUN"
}
```

Note what this is **not**: "consult legacy when the new state lacks a
record". That per-record fallback is the rejected design, and the gate is
on the adoption *decision*, not on a missing record.

**Adoption is not a read capability.** `_validate_adoption_source`
re-checks, on every use including a pre-existing stamp, that the
recorded path resolves to exactly `<ws_root>/<campaign_id>_wave_state.jsonl`.
A hand-edited stamp stops the run rather than widening what it may read.
This was not in the frozen plan's implementation steps; §4's
"stamp records a path outside `$WS_ROOT` → STOP" required it, and the
narrow form (exact name, exact directory) is stricter than "inside
`$WS_ROOT`" for the same cost.

**Tests** — 438 pass in 37.2 s (E-C2b baseline 408); 30 new.

| Class | Count | Covers |
|---|---|---|
| `TestAdoptionIsDecidedOnce` | 6 | the conjunction; canonical-state-blocks-adoption; monotonicity with a byte-identical stamp; another campaign out of range |
| `TestAdoptionIsNotAReadCapability` | 8 | four tampered paths refused, a positive control accepted, `None` is a value, reachability through `admit_campaign`, and a vanished-but-legitimate path still reported as adopted |
| `TestLegacyAdoption` (shell) | 10 | the real launcher: pre-move resume, **the blocker case**, monotonicity, foreign campaign, fresh campaign, unusable/deleted adopted files, tampered stamp, and the legacy filename in a read position only |
| `TestTheLegacyGlobalStopIsObservedNotHonoured` | 3 | the record's contents, the file's survival, and no record when absent |
| `TestLegacyBytesAreNeverTouched` | 1 | E2: bytes **and** `st_mtime_ns` over a four-file legacy tree |
| `TestResolveAdoptionDirectly` | 1 | refusal at the decision layer |

**Blocker-case result.** `<R>/v19/queue_state/wave_state.jsonl` exists
without the record, `<R>/v19_wave_state.jsonl` has it with `"exit": 0`:
the stamp records `legacy_adopted_from: null`, the log contains no
`SKIP`, and the `screen` shim records
`-dmS siderius-v19_arch_15_19` — **the chain is launched.**

**Byte/mtime identity result.** A four-file legacy tree
(`v19_wave_state.jsonl`, `v19_queue_runner.log`, `STOP`,
`v19_campaign.json`) is identical in both `read_bytes()` and
`st_mtime_ns` after a full `--only` run that adopts and skips.

**`legacy_global_stop_observed` record**

```json
{"legacy_global_stop_observed": true, "path": "<R>/STOP",
 "mtime": "1754...", "observed_at": "…Z", "runner_pid": 1234,
 "honoured": false, "removed": false}
```

Written to the **new** wave state, so the observation belongs to the
campaign that made it. A failed `stat` yields `"unknown"`, never `0` — a
gap is never a zero.

**Mutation and reachability proofs**

| Mutation | Result |
|---|---|
| `legacy_adopted_from=None` — the decision is computed but never persisted | **6 fail** |
| `chain_completed` restored to the per-record fallback | **2 fail** — the blocker case and monotonicity, exactly the two the rejected design would have broken |
| `QUEUE_STOP_FILE` default back to `$WS_ROOT/STOP` (honouring the legacy STOP) | **3 fail** |
| `adopted_legacy_state(existing)` re-validation removed from `admit_campaign` | **2 fail** — proves the check is on the production path, not in an unused helper |

Hygiene: backups, `__pycache__` cleared, every substitution asserted
`count == 1`, restores verified by `grep -cF`, baseline re-run green.

**Static**: pyright **0 errors, 4 warnings** (unchanged), ruff check +
format clean, `bash -n` clean.
`grep -n '_wave_state' v19_queue_runner.sh` → three hits, two comments
and one definition; **no write position**, asserted by a test.

**Deviations from the frozen plan**

1. **The adoption decision is computed in Python, not in the shell.** §3
   places it "in the admission sequence's step 5", which is Python; the
   shell supplies the two paths and consumes the answer. This keeps the
   filename rule (`{campaign_id}_wave_state.jsonl`) in one place, where
   "another campaign's file" is a comparison rather than a convention.
2. **The helper's output gained a second line** rather than a third
   field, because a path may contain a space and the launcher parses with
   word splitting. "None" is spelled `-`: command substitution strips
   trailing newlines, so an empty line 2 would be indistinguishable from
   a missing one.
3. **`chain_completed` was split into `_completed_in` + a caller.** The
   plan said "keep the existing `grep … | grep -q` form so the predicate
   is provably identical on both files"; extracting it makes that
   *structurally* true rather than a matter of two copies staying in
   sync.
4. **The stale header comment at `:41` was corrected.** It named
   `$WS_ROOT/v19_wave_state.jsonl` as the authoritative status file,
   which E-C2 made false and this commit makes actively misleading. One
   comment, describing exactly what this commit changes.

**Self-corrected during implementation.** A first draft of
`test_a_legacy_file_appearing_later_never_gains_authority` contained
`assert first.returncode != 0 or True` — a vacuously true assertion, the
exact anti-pattern CLAUDE.md records from 2026-08-02. Removed; the first
run's launch outcome is not that test's subject and is now simply not
asserted.

**Remaining risk.** None specific to adoption. The E-C2 gap is closed:
`<R>/<id>_wave_state.jsonl` is read again, under an auditable, recorded,
once-only decision.

**Next authorized checkpoint**: E-C4 (wave record and pair summaries).

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
identity). Independent of E-C3.

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
- [ ] Implement the dual write in D-E-3a's fixed order: **append to the
      canonical `wave_state.jsonl`, flush, `fsync` — then** atomically
      write the derived `$PAIR_SUMMARY_DIR/wave_<n>_<band>.json`. Never
      the reverse: a derived file that exists without its canonical
      record is an inconsistency, and writing it second makes that state
      unreachable
- [ ] If the derived write fails, **fail the run explicitly**. The fact
      is already canonical, so nothing is lost, but a silently missing
      summary is the failure mode `:513-514` exists to prevent
- [ ] Compute `record_id = <campaign_id>:<wave>:<band_tag>:<attempt>`,
      resolving `attempt` from the count of matching canonical records
      already in the JSONL — derived from persisted evidence, so a
      restart cannot lose it
- [ ] Write `record_id` into **both** views, so the derived file states
      which attempt it represents
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
- [ ] `record_id` is present in both views and identical between them
- [ ] **A retried wave produces a different `record_id`** — two
      canonical records, one derived file holding the later attempt.
      Without this the two views diverge silently, which is the whole
      reason `record_id` exists
- [ ] The canonical append happens before the derived write: with the
      derived write forced to fail, the canonical record is still
      present and the run exits non-zero

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
- [ ] After two attempts at one wave, `wave_state.jsonl` holds two
      records with distinct `record_id`s and `pair_summaries/` holds one
      file whose `record_id` equals the later of the two
- [ ] With the derived write forced to fail, the canonical record exists
      and the run exits non-zero — verified by reading the JSONL
- [ ] Full suite green at this commit; **pyright clean over the new
      `core/` and `scripts/` modules — this commit is where pyright is
      most load-bearing**

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Summary file already exists for the same wave | **Overwrite** — the derived view holds the latest attempt, and its `record_id` says which. History lives in the canonical JSONL (D-E-3a) |
| Derived write fails after the canonical append | **STOP** — the run fails explicitly. Evidence is preserved canonically and the file is rebuildable from the JSONL |
| Canonical append fails | **STOP** — nothing is written anywhere; the derived file is never written ahead of its record |
| A derived file with no matching canonical record | Unreachable by construction; if observed, it indicates a manual edit and is a detectable inconsistency, not a normal state |
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

#### IMPLEMENTATION RECORD — E-C4 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of E-C3 `ed61bb50`.

**Behavior Delta: BD-4.**

> ### A DEFECT IN THE FROZEN DESIGN, found by audit before implementing
>
> **D-E-3's own example record makes a failed chain read as complete.**
>
> The proposed array is `{"run": "v20a_arch_15_19", …, "exit": 0}`, and
> `chain_completed` decides completion by grepping the **whole line**:
>
> ```bash
> grep '"run": "<X>"' wave_state.jsonl | grep -q '"exit": 0'
> ```
>
> A wave summary in which one chain succeeded therefore satisfies that
> predicate for **every chain it names**. Measured on the design's own
> example: a wave with `arch exit 0` and `loss exit 137` reports
> `v19_loss_15_19 -> COMPLETED`. On the next resume that chain is
> skipped as finished and its failure disappears from the science. The
> pre-E-C4 record does not collide, because `"arch_run": "…"` has `_`
> before `run`, not `"`.
>
> **Correction taken**: the field inside `chains` is **`run_name`**.
> `chain_completed` is byte-identical, the interpretation of duplicate
> JSONL records is unchanged, and no authority semantics move — this is
> a field-naming fix, which is why it was made rather than escalated.
> Guarded by two regression tests, one on the serialised bytes and one
> end-to-end through the launcher.

**Production files changed**

| File | What |
|---|---|
| `core/wave_records.py` (**new**, 289 lines) | `ChainRecord`, `WaveSummaryRecord`, the mirror rule, `next_attempt`, `build_record_id`, canonical append + fsync, atomic derived write, `CanonicalWriteError` / `DerivedWriteError` |
| `scripts/record_wave_summary.py` (**new**, 138 lines) | the CLI; `--chain RUN:ROLE:PID:EXIT` repeatable; exit codes 0/2/3 |
| `sdsc_submission_scripts/v19_queue_runner.sh` | `record_wave_summary()` rewritten as a guarded writer call; both call sites; `MAX_CONC` deleted; `chains_per_wave` logged |

**The record**

```json
{"wave_summary": 1, "record_id": "v19:1:15_19:1", "campaign_id": "v19",
 "band": "15-19", "band_tag": "15_19",
 "chains": [{"run_name": "v19_arch_15_19", "role": "arch", "pid": "1111", "exit": 0},
            {"run_name": "v19_loss_15_19", "role": "loss", "pid": "2222", "exit": 137}],
 "arch_run": "v19_arch_15_19", "arch_pid": "1111", "arch_exit": 0,
 "loss_run": "v19_loss_15_19", "loss_pid": "2222", "loss_exit": 137,
 "start": "…", "end": "…", "disposition": "failed"}
```

Identical bytes in both destinations. The mirror is emitted **only** for
exactly two chains whose roles are exactly `arch` and `loss`; a one-,
three- or other-role wave gets `chains` and no mirror, never a fabricated
one — an invented `arch_exit` is worse than an absent one, because a
report would show it.

**Retry and duplicate semantics — unchanged, and now expressible.**
`record_id = <campaign_id>:<wave>:<band_tag>:<attempt>`, with `attempt`
counted from the canonical file at write time, so a queue restart cannot
reset it. Two attempts leave two JSONL records with **different**
`record_id`s and one derived file carrying the later one. How duplicate
JSONL records are interpreted did not change: `chain_completed` still
reads per-chain `record_chain` lines, and wave summaries remain
non-participating in that predicate.

**Failure semantics, distinctly**

| Outcome | Exit | Canonical | Shell |
|---|---|---|---|
| both written | 0 | written | logs `summary recorded: <record_id>` |
| schema refusal / canonical write failed | 2 | **nothing written** | `record_queue_stop "wave_summary_write_failed"`, exit 1 |
| derived write failed | 3 | **preserved** | `record_queue_stop "wave_summary_derived_write_failed"`, names the rebuild source, exit 1 |

Collapsing 3 into 2 would report a missing convenience file as missing
evidence and invite a retry that duplicates the canonical record.

**Tests** — 471 pass in 38.3 s (E-C3 baseline 438); 36 net new.

| File | Count | Covers |
|---|---|---|
| `tests/unit/core/test_wave_records.py` (**new**) | 25 | write order observed on disk; derived failure keeps the evidence; distinct error types; no surviving temp file; retry `record_id`s; attempt survives a restart; unparseable lines not counted; the mirror's four negative cases + positive; the `run_name` regression on serialised bytes; **fsync-before-replace ordering**, spied |
| `test_campaign_admission.py::TestTheWaveSummaryWriterFailsExplicitly` (**new**) | 7 | the §3a.4 guarded form end to end: reason persisted, exit code, stderr visible, `errexit` still on, canonical preserved, null role does not destroy the summary |
| `test_v19_queue_runner.py` | 2 rewritten | all operator fields over the new shape; a wave summary never makes a failed chain look complete |
| `test_v19_queue_runner.py` | 1 replaced | `MAX_CONC == 2` → the wave launches exactly the ROSTER chains for its band |
| `test_source_safe_entry.py` | 1 repointed | `${MAX_CONC:-unset}` → `$CAMPAIGN_HOME` |

**Mutation and reachability proofs**

| Mutation | Result |
|---|---|
| derived write moved **before** canonical | **2 fail** |
| `chains` field spelled `run` (D-E-3's own example) | **4 fail**, including the end-to-end "failed chain reads as complete" |
| writer call → bare assignment + `RC=$?` (§3a.4) | **5 fail** — every classification path loses its diagnostic |
| `attempt` pinned to 1 | **2 fail** — retries become indistinguishable |

**Static**: pyright **0 errors, 4 warnings** (unchanged), ruff check +
format clean, `bash -n` clean.

**Test deletions, justified**

- `test_exactly_two_chains_per_wave_max_conc` — asserted a variable that
  gated nothing; deleting `MAX_CONC` changed no behaviour, which is what
  made it decoration. **Replaced**, not dropped: the defect it reached
  for ("a wave must not launch more chains than intended") is now
  asserted against the ROSTER.
- A drafted `TestTheRecordIsValidated` (3 cases) was deleted before
  commit: an empty `chains` list, a non-integer exit, and `-1` compared
  to itself are `Field(min_length=1)`, a declared `int`, and a value
  asserted against itself. Ruff's B017 flagged two of them as blind
  `Exception` assertions, which is the same finding from the other
  direction. The reachable behaviour is asserted end to end instead.

**Deviations from the frozen plan**

1. **`run_name`, not `run`** — the defect above. The only change to a
   frozen artifact's contents, and it changes no semantics.
2. **The role is resolved inside `record_wave_summary`, and a failure
   yields `null`** rather than aborting. The function is called on every
   wave exit path including the aborted-launch one, and the launcher's
   own rule is that an aborted wave must not be the one case that leaves
   no summary. A guess of `arch` is exactly what D-E-6 removed.
3. **`--chain` is a colon-joined string**, `rsplit(":", 3)` — a run name
   may contain no colon but the remaining fields never do, so splitting
   from the right keeps a surprising run name from shifting every field.
4. **Exit code 3 was added** for "canonical written, derived not". §4
   required the two failures to be distinguishable; a distinct code is
   how the shell distinguishes them.
5. **`chains_per_wave` is logged per wave**, at the launch line, rather
   than at the queue-start line where `MAX_CONC` was: the count is a
   property of a wave's `NEEDED` set, and only that site knows it.

**Not done, deliberately**: no launcher concurrency change (FU-E-2 stays
deferred — `WAVES` still pairs two names), no rebuild of historical
derived summaries (FU-E-7), no Gate runner change, no other shell record
converted, no stop or exit-code semantics touched, no E-C3 change.

#### IMPLEMENTATION RECORD — E-C4b `[x]` COMPLETE

*An E-C4 correction, landed as its own commit. `25a95556` is not amended.*

**Commit**: `<filled at commit>`.

**The gap.** E-C4 recorded an unresolvable role as `"role": null` and
emitted no compatibility mirror — correct, but **silent**. A reader
seeing a null role and no mirror cannot tell a wave with unusual roles
*by design* from a ROSTER lookup that *failed*, and those two call for
opposite operator responses: the first is normal, the second means the
ROSTER and the launched set have diverged. The operator's acceptance of
E-C4 stated the gap explicitly ("disposition/reason must record the
resolution failure").

**The fix.** Two additive fields, present **only** when at least one role
is unresolved:

```json
{"role_resolution_failed": true, "unresolved_roles": ["not_in_the_roster"]}
```

**`disposition` is deliberately NOT overloaded.** Its vocabulary
(`complete` / `failed` / `launch_failed`) describes what happened to the
**chains**; a recording gap is not a chain outcome. Overloading it would
also break an operator filtering on `disposition == "complete"`, who
would lose the wave entirely. A test asserts the disposition is unchanged
when the marker fires.

**Behavior Delta**: none for a fully-resolved wave — the record is
byte-identical to E-C4's, because the fields are absent rather than
`false`. A wave with an unresolved role gains two keys.

**Tests** — 474 pass (E-C4 baseline 471); 4 new: the marker fires, a
normal record carries neither key, the disposition is not overloaded, and
the end-to-end launcher path emits both fields.

**Mutation**: dropping the marker → **2 fail**, one at the model and one
through the real launcher.

**Static**: pyright 0 errors / 4 warnings (unchanged), ruff + format
clean.

**Deviations**: none.

**Next authorized checkpoint**: E-C5 (Gate pair summary scoping).

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

**Dependencies**: **E-C2**, for the shared safe-path-component
validator (D-E-4, operator ruling 2026-08-04). This dependency did not
exist in the earlier draft and is accepted deliberately: one shared rule
beats two rules that happen to agree today.

#### 3. Implementation plan

- [ ] Change `SUMMARY` to `$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`
- [ ] Change `RUNNER_LOG` to `$GATE_ROOT/${GATE_RUN_PREFIX}_runner.log`
- [ ] Change the `"gate"` field at `:290` to emit `$GATE_RUN_PREFIX`
- [ ] Confirm `log()` (`:65`) is only called after `GATE_RUN_PREFIX` is
      defined — it is defined at `:56` and `log` at `:65`, but verify no
      earlier caller exists
- [ ] Update `_run_main` (`test_…:188-214`) to read the derived filename
- [ ] Update the pre-written filename in `test_source_safe_entry.py`
- [ ] Validate `GATE_RUN_PREFIX` with **E-C2's validator**, not a
      second copy: reject empty, `.`, `..`, separators and control
      characters, and **accept** an id merely containing `..`, exactly as
      for `campaign_id` (D-E-9). Refuse before `SUMMARY` or `RUNNER_LOG`
      is used
- [ ] Do **not** add a `$GATE_ROOT/$GATE_RUN_PREFIX/` subdirectory —
      closed by operator ruling, prefixed filenames only (D-E-4)
- [ ] Do **not** add a Gate stop channel — closed by the same ruling;
      it becomes FU-E-8

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
- [ ] Empty `GATE_RUN_PREFIX` → **refused**, rather than producing
      `_pair_summary.json`
- [ ] `GATE_RUN_PREFIX` equal to `.` or `..`, containing `/`, `\`, a
      control character, or over-length → **refused**
- [ ] `GATE_RUN_PREFIX` containing `..` (e.g. `c14..b`) → **accepted**,
      the same positive control as for `campaign_id`
- [ ] Every refusal happens before `SUMMARY` or `RUNNER_LOG` is written

**Backward compatibility / default parity**
- [ ] An existing `gate0_pair_summary.json` on disk is **not** read,
      renamed or deleted — it stays as historical evidence, and E-C8's
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
      returns only unrelated matches) — the ruling says none is added
- [ ] `GATE_ROOT` gained no `$GATE_RUN_PREFIX` subdirectory — prefixed
      filenames only
- [ ] An empty `GATE_RUN_PREFIX` is refused and no file named
      `_pair_summary.json` is ever created
- [ ] Full suite green at this commit; pyright count unchanged

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Two Gate runs under one root | Both summaries survive — the defect being fixed |
| Historical `gate0_pair_summary.json` | Left untouched; documented in E-C8 |
| Empty `GATE_RUN_PREFIX` | **STOP** — refused by the shared validator |
| `GATE_RUN_PREFIX` equal to `.` or `..`, or containing a separator or control character | **STOP** — refused |
| `GATE_RUN_PREFIX` merely containing `..` | **ACCEPT** — one path segment, cannot traverse |
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
- [ ] empty-prefix refusal observed: __
- [ ] `c14..b` positive-control result: __

#### 8. Commit boundary

- [ ] Independently reviewable: three literals and two test fixtures
- [ ] Independently green at this commit
- [ ] No stop channel added (FU-E-8); no `GATE_ROOT` restructuring; no
      conversion of the Gate's own printf; no second copy of the
      validator; no docs; no unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, the two-prefix listing, and
      both validator control results

#### IMPLEMENTATION RECORD — E-C5 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of E-C4b `061bccfb`.

**Behavior Delta**: the Gate summary and runner log move from fixed
`gate0_*` names to `${GATE_RUN_PREFIX}_*`; the summary's `"gate"` field
becomes the resolved prefix instead of the literal `"v19_gate0"`; an
unsafe or explicitly empty `GATE_RUN_PREFIX` is refused at startup.

**Production files changed**

| File | What |
|---|---|
| `core/campaign_identity.py` | `validate_path_component(value, kind=)` extracted; `PathComponentError`; `validate_campaign_id` delegates to it and re-raises `CampaignIdError` so E-C2's callers and tests are untouched |
| `scripts/validate_path_component.py` (**new**, 43 lines) | the CLI a shell caller reaches the shared rule through; exit 0 / 2 |
| `sdsc_submission_scripts/v19_gate0_pair_runner.sh` | `SUMMARY`, `RUNNER_LOG`, the `"gate"` field; the startup guard; `${GATE_RUN_PREFIX-v19_c14}` |

**A prefix, not a directory.** `$GATE_ROOT/${GATE_RUN_PREFIX}_pair_summary.json`,
never `$GATE_ROOT/$GATE_RUN_PREFIX/…`. The Gate has no directory model and
this commit does not invent one.

**One rule, not a second copy.** The Gate reaches
`validate_path_component` — the same function `validate_campaign_id` now
delegates to. A shell `case` here would have been a second copy of a
security rule, and a second copy is how two rules drift: one of them
eventually learns about `..` and the other does not. Asserted
structurally.

**Written for THIS shell.** The Gate runner has `set -u` only, **no
`errexit`** (`:42`) — unlike the queue runner, which inherits `-e` from
`_chain_common.sh:40`. A failing command here does not abort, so the
guard checks the status explicitly with `if ! cmd`, which is correct
under either setting. The E-C2 pattern was **not** copied mechanically.

**Guard placement, and why a refusal writes no summary.** The guard runs
before `mkdir -p "$GATE_ROOT"` and before `trap write_summary EXIT`. It
has to: `$SUMMARY`'s own path is built from the value being refused, so
running `write_summary` would write to a path derived from a rejected
prefix. A startup refusal therefore leaves **no artifacts at all**, which
is the accurate representation — nothing ran. The diagnostic names the
variable and the value on stderr, and the exit code is 2.

> ### A second `:-` defect, found by the empty-prefix test
>
> `GATE_RUN_PREFIX="${GATE_RUN_PREFIX:-v19_c14}"` made
> `GATE_RUN_PREFIX= bash …` run silently as `v19_c14` — so the operator's
> refusal set could not include "empty", because an empty value never
> reached the validator. Identical to FU-E-11 in the queue runner, in a
> different file, and found the same way: by testing the case rather than
> reading the line.
>
> Fixed with the same one-character change, `${GATE_RUN_PREFIX-v19_c14}`.
> Unset still defaults to `v19_c14`; explicitly empty now reaches the
> validator and is refused. An operator who **clears** the variable to
> avoid reusing a Gate label would otherwise have been handed that label
> and overwritten its summary.

**Tests** — 494 pass in 54.4 s (E-C4b baseline 474); 20 new, all in
`test_v19_gate0_pair_runner.py`.

| Class | Count | Covers |
|---|---|---|
| `TestGateArtifactsAreScopedByPrefix` | 4 | two prefixes → four separate artifacts; each summary names its own run; a second run does not overwrite the first; a historical `gate0_*` pair is byte- and mtime-identical |
| `TestAnUnsafeGatePrefixIsRefused` | 14 | seven refusals (incl. empty) with zero launches; no artifacts left; the diagnostic; four positive controls incl. the shipped default `v19_c14` and `alpha..beta`; guard reachability above `mkdir`/`trap`; the no-second-copy assertion |
| `TestSourcingTheGateRunnerStillTouchesNothing` | 1 | sourcing with an invalid prefix neither refuses nor creates |
| harness | repointed | `_run_main` takes a prefix and derives the summary path from it, so the test cannot drift from the runner |

**Two-prefix listing observed** under one `GATE_ROOT`:

```text
probe1_pair_summary.json   probe1_runner.log
probe2_pair_summary.json   probe2_runner.log
gate0_pair_summary.json    gate0_runner.log     <- pre-existing, unchanged
```

`probe1`'s summary reports `"gate": "probe1"`, `probe2`'s reports
`"gate": "probe2"`, and the historical pair is identical in bytes and
`st_mtime_ns` after the runs.

**Mutation and reachability proofs**

| Mutation | Result |
|---|---|
| validator call removed from `main()` | **11 fail** |
| `SUMMARY` / `RUNNER_LOG` back to fixed `gate0_*` | **12 fail** |
| `${GATE_RUN_PREFIX:-v19_c14}` restored | **1 fail** — the empty-prefix case, precisely |

**Static**: pyright **0 errors, 4 warnings** (unchanged), ruff check +
format clean, `bash -n` clean on both runners. Full `tests/unit/` run:
2439 passed, 2 skipped.

**Deviations from the frozen plan**

1. **`${GATE_RUN_PREFIX-v19_c14}`** — the second `:-` defect above. §4's
   refusal set names "empty", and without this the case was unreachable.
2. **A startup refusal writes no summary**, rather than a summary
   recording the refusal. §4 asked that the refusal be accurately
   represented; a summary cannot be, because its path derives from the
   rejected value. Stated here so the absence is a decision, not a gap.
3. **The shared rule was extracted rather than imported as
   `validate_campaign_id`.** Calling a function named for campaigns from
   the Gate would have made the Gate a campaign. `validate_campaign_id`
   is now a thin caller-specific face over
   `validate_path_component`, so E-C2's error type and tests are
   unchanged — verified by the campaign suite passing untouched.

**Not done, deliberately**: no Gate stop channel (FU-E-8), no
`GATE_ROOT` restructuring, no conversion of the Gate's `printf` to
E-C4's typed writer, no new Gate schema, no queue-runner change, no
`bg_gpu_sampler.sh` change, no Gate execution parameters touched, no
real Gate run.

**Next authorized checkpoint**: E-C6 (process-guard self-exclusion,
D-E-7).

---

### E-C6 — Process-guard self-exclusion (D-E-7)

*(Split out of E-C2 by the second operator review: it has no causal
dependency on the path move, and E-C2 was carrying too much.)*

#### 1. Goal

`:259`'s live-process guard excludes the runner from its own `ps` scan
by a hardcoded script name:

```bash
if ps -eo args | grep -v grep | grep -v v19_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
```

A renamed or copied runner self-matches — its own argv contains
`$WS_ROOT/$RUN` once it is inside `launch_chain`'s screen command — and
refuses to launch anything. The exclusion must derive from the script's
own basename.

**Why its own commit.** It is the same *class* of defect as the rest of
PR E — the current campaign's name baked into generic logic — but it
shares no cause with the path move, no file region, and no test. Landing
it inside E-C2 made a large commit larger for no reviewability gain. It
could equally be a follow-up; it stays in PR E because it is two lines.

#### 2. Scope

**Changes**: `sdsc_submission_scripts/v19_queue_runner.sh:259` only.
**New test**: a rename case in `test_v19_queue_runner.py`.

**Non-goals.** `v18r_queue_runner.sh:48` carries the identical pattern
and is **not** touched — it is a historical launch surface protected
from change by `test_v19_queue_runner.py:261-269` (FU-E-3).

**Must stay unchanged**: the guard's meaning — a live process already
referencing this run's workspace blocks the launch — and its position
among the three launch guards (`:255`, `:258`, `:259`).

**Dependencies**: none. May land at any point in the sequence, or as a
follow-up, without affecting any other commit.

#### 3. Implementation plan

- [ ] Replace the literal with
      `grep -v "$(basename "${BASH_SOURCE[0]}")"`
- [ ] Confirm `BASH_SOURCE[0]` is the runner and not `_chain_common.sh`
      at that point — `:59` already uses `${BASH_SOURCE[0]}` for `REPO`,
      so the idiom is established in this file, but verify at `:259`
      specifically, inside `launch_chain`
- [ ] Confirm the guard still matches a genuine live process: the
      exclusion must remove only the runner's own argv line

#### 4. Validation plan

**Unit**
- [ ] A copy of the runner under a different filename does not
      self-match, and launches
- [ ] Under the current filename, behaviour is byte-identical

**Integration / pseudo**
- [ ] A `--only` run with a stubbed `ps` that reports a genuine live
      process still refuses, with the existing message

**Negative / invalid input**
- [ ] A `ps` scan returning nothing does not falsely refuse
- [ ] A filename containing regex metacharacters does not break the
      `grep` — **inspect** whether `grep -v` needs `-F` here, then decide

**Backward compatibility / default parity**
- [ ] `v18r_queue_runner.sh` untouched; its own test still green

**Real Gate**
- [ ] None.

#### 5. Acceptance criteria

- [ ] A byte-copy of the runner at `v20_queue_runner.sh` launches
      successfully against a temp root, where the pre-change version
      refuses — observed from the log, not from a variable
- [ ] Under the original filename the log output is identical to the
      pre-change run
- [ ] `grep -n 'v19_queue_runner' v19_queue_runner.sh` shows the literal
      only in comments and `--only` usage strings
- [ ] Full suite green at this commit; pyright count unchanged

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| Runner renamed or copied | **Launches** — the defect being fixed |
| Genuine live process on this workspace | **STOP** — unchanged |
| Filename with regex metacharacters | See the implementation step; decide from observed behaviour |
| `v18r_queue_runner.sh` | Untouched (FU-E-3) |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/sdsc_submission_scripts/ -q
bash -n sdsc_submission_scripts/v19_queue_runner.sh
PATH=~/.cache/pyright-python/nodeenv/bin:$PATH ./.venv/bin/pyright
```

- [ ] test count: __
- [ ] wall time: __
- [ ] pyright errors (baseline → after): __ → __
- [ ] local run: __      - [ ] CI run on pushed head: __
- [ ] renamed-copy launch result: __

#### 8. Commit boundary

- [ ] Independently reviewable: one line and one test
- [ ] Independently green at this commit
- [ ] No path work, no campaign identity, no docs, no v18r change, no
      unrelated cleanup
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the test output, the pyright count, and the renamed-copy result

#### IMPLEMENTATION RECORD — E-C6 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of E-C5 `240d7ac1`.

**Behavior Delta**: a runner running under any filename now excludes its
own process from the live-process scan. Under the shipped filename,
behaviour is unchanged.

**Production diff — two lines**

```diff
+RUNNER_BASENAME="${BASH_SOURCE[0]##*/}"
-  if ps -eo args | grep -v grep | grep -v v19_queue_runner | grep -qF "$WS_ROOT/$RUN"; then
+  if ps -eo args | grep -v grep | grep -vF -- "$RUNNER_BASENAME" | grep -qF -- "$WS_ROOT/$RUN"; then
```

`${BASH_SOURCE[0]##*/}` rather than `$(basename …)`: pure parameter
expansion, so no subshell and no `set -e` surface, and it matches the
form E-C2 already uses for the admission helper's `--runner` argument.

**`-F` is not cosmetic — operator instruction, and it is load-bearing.**
The basename is `v19_queue_runner.sh` and `.` is a regex wildcard, so a
plain `grep -v` would also exclude a process named
`v19_queue_runnerXsh`. That widens the exclusion to processes that are
**not** this runner, which is the direction that silently skips the
guard. Both sides of the pipeline are now fixed-string, and `--` guards
a value that begins with `-`.

**Unchanged**: the guard's meaning (a live process already referencing
this run's workspace blocks the launch), its position among the three
launch guards, the `grep -v grep` stage, and `pipefail`/return-code
behaviour — the guard is inside `launch_chain`, which every call site
invokes as a condition, so `errexit` stays suspended there exactly as
before.

**Tests** — 6 new in `test_v19_queue_runner.py`; full `tests/unit`:
**2445 passed, 2 skipped** in 103 s.

| Test | Proves |
|---|---|
| `test_a_genuine_external_process_still_blocks_the_launch` | the meaning is intact |
| `test_the_runner_does_not_see_itself` | unchanged under the shipped filename |
| `test_a_process_that_is_not_this_runner_is_not_excluded` | the exclusion stays narrow |
| `test_a_renamed_runner_still_excludes_itself` | **the regression**, with an actually-renamed copy |
| `test_the_exclusion_is_fixed_string_not_a_regex` | `v19_queue_runnerXsh` still blocks |
| `test_the_exclusion_derives_from_the_script_name` | structural, no literal anywhere |

Each behavioural case runs the **real `launch_chain`** against a real
background process whose argv contains this run's workspace path, and
reads the guard's own message out of the log — so what is asserted is the
guard's decision, not the shape of a pipeline.

**Mutations**

| Mutation | Result |
|---|---|
| `grep -v v19_queue_runner` restored | **3 fail** |
| `-F` dropped from the self-exclusion | **2 fail** |

**Static**: pyright 0 errors / 4 warnings (unchanged), ruff + format
clean, `bash -n` clean. `git diff --stat` confirms only
`v19_queue_runner.sh` and its test file changed: no `role_for_run`, no
campaign paths, no legacy adoption, no wave writer, no
`v18r_queue_runner.sh`, no Gate runner.

**Two defects found in my own tests, both fixed before commit**

1. **The rename test did not discriminate.** As first written it varied
   the *fixture's* name, not the script's — and passed under the
   hardcoded literal too, which the mutation exposed. It now copies the
   runner and `_chain_common.sh` into a temp tree and runs the copy under
   a different filename, which is the only form that reproduces the
   defect. The mutation went from 2 failures to 3.
2. **The fixture process was invisible to `ps`.** `bash -c "sleep 30 # <marker>"`
   is a lone simple command, so bash **execs** it and replaces its own
   argv — the marker vanished and three "should block" cases silently
   didn't. Fixed with `; true`, verified by injection. Separately, the
   fixture held the captured pipes open after being killed (its orphaned
   `sleep` inherited them), making the class take 120 s; redirecting its
   output brought that to 4.8 s.

**Follow-up filed and immediately closed**

- **FU-E-12** — `v19_gate0_pair_runner.sh:209` carried the identical
  hardcoded self-exclusion (`grep -v gate0_pair_runner`, also without
  `-F`). Filed as a follow-up because E-C6's frozen scope names the queue
  runner only; the operator's review (2026-08-04) declined the deferral —
  the Gate runner is a production surface PR E already touched in E-C5,
  and the fix is the same two lines. **Closed by E-C6b below.**
  `v18r_queue_runner.sh:48` remains FU-E-3: it is a historical launch
  surface protected from change by an existing test.

**Next authorized checkpoint**: E-C6b, then E-C7.

#### IMPLEMENTATION RECORD — E-C6b `[x]` COMPLETE

*Closes FU-E-12. Operator ruling, 2026-08-04: not deferred.*

**Commit**: `<filled at commit>`, on top of E-C6 `6dc1fdb1`.

**Behavior Delta**: a Gate runner running under any filename now excludes
its own process from the live-process scan. Under the shipped filename,
behaviour is unchanged.

**Production diff — two lines**, the E-C6 change transposed:

```diff
+GATE_RUNNER_BASENAME="${BASH_SOURCE[0]##*/}"
-  if ps -eo args | grep -v grep | grep -v gate0_pair_runner | grep -qF "$GATE_ROOT/$RUN"; then
+  if ps -eo args | grep -v grep | grep -vF -- "$GATE_RUNNER_BASENAME" | grep -qF -- "$GATE_ROOT/$RUN"; then
```

**Tests** — 5 new, mirroring E-C6's class against
`launch_gate_chain` and `$GATE_ROOT/$RUN`: the meaning is intact, the
shipped filename is unchanged, an actually-renamed copy excludes itself,
`v19_gate0_pair_runnerXsh` still blocks, and the literal is gone.
`tests/unit/sdsc_submission_scripts/`: **430 passed** in 64 s.

**Mutations**: the literal restored → **3 fail**; `-F` dropped →
**2 fail**. Same discriminating pair as E-C6, including the
actually-renamed-copy case.

**Static**: pyright 0 errors / 4 warnings (unchanged), ruff + format
clean, `bash -n` clean.

**Scope held**: only `v19_gate0_pair_runner.sh` and its test file
changed. No `v18r_queue_runner.sh` (`git diff --stat` empty), no Gate
stop channel, no summary/wall-cap/trap/execution-parameter change, no
queue-runner change.

**Next authorized checkpoint**: E-C7 (multi-campaign isolation test),
**test-only** — any production change required there is a stop-and-report
condition, because it would mean the preceding implementation evidence
was insufficient.

---
### E-C7 — Multi-campaign isolation test

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
- [ ] Do **not** put the negative control in the module as an expected
      failure. The formal suite stays green; an `xfail`-shaped test that
      passes by failing is indistinguishable from a broken test six
      months later. The isolation tests here assert the **correct**
      behaviour only
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
- [ ] The module's own negative cases assert correct refusals (wrong
      campaign's STOP ignored, legacy STOP ignored) — all **passing**
      assertions

**Mutation evidence — a separate documented run, not a suite member**
- [ ] Temporarily restore the old `QUEUE_STOP_FILE` default in the
      source, run this module, observe the isolation test **fail**,
      record the failure output, restore the source, re-run and observe
      green. Per the mutation-proof hygiene rule: clear `.pyc` caches,
      assert the edit hit exactly one site, and re-run the baseline
      afterwards
- [ ] The evidence is attached to the PR; **nothing in the committed
      suite is expected to fail**

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
- [ ] The committed module is **fully green** — no expected failures,
      no `xfail`, no skips
- [ ] The mutation run's recorded failure output is attached to the PR,
      together with the restored-source green re-run
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
- [ ] mutation-run failure output (source temporarily reverted): __
- [ ] restored-source green re-run: __
- [ ] cross-write check result: __

A negative control that was not executed is not a negative control — and
one that lives in the suite as an expected failure is not a control at
all, it is a broken test with an alibi.

#### 8. Commit boundary

- [ ] Independently reviewable: one new test file, zero production lines
- [ ] Independently green at this commit
- [ ] No production change; if one is needed, stop and report
- [ ] Before committing, show `git diff --stat`, the staged file list,
      the module output (fully green), the CI result, and the separate
      mutation-run evidence

#### IMPLEMENTATION RECORD — E-C7 `[x]` COMPLETE

**Commit**: `<filled at commit>`, on top of E-C6b `f3c7cf5b`.

**Behavior Delta: none. Zero production lines.**
`git diff --stat -- sdsc_submission_scripts/ core/ scripts/` is **empty**
— one new file,
`tests/unit/sdsc_submission_scripts/test_multi_campaign_isolation.py`.

That is the checkpoint's acceptance condition and it held: nothing in
E-C2..E-C6b needed correcting to make the isolation observable, so the
preceding implementation evidence was sufficient.

**The fixture** — §9 Layer 2, built once and reused:

```text
<root>/STOP                  legacy global — no authority over anything
<root>/alpha/control/STOP    alpha is stopped
<root>/alpha/{control,queue_state,pair_summaries}/
<root>/beta/{control,queue_state,pair_summaries}/
```

Every test runs the **real launcher** against that tree and then looks at
the filesystem. A PATH `screen` shim records each invocation, so
"nothing launched" *and* "something launched" are both assertions —
`beta` proving it is unaffected by reaching its launch, not merely by
lacking a stop record.

**Tests** — 11, all green in 50.7 s.
`tests/unit/sdsc_submission_scripts/`: **441 passed**.

| Class | Count | Property |
|---|---|---|
| `TestOneCampaignsStopDoesNotStopTheOther` | 3 | **the 08:17 incident**: `alpha` exits 99 with `operator_stop_requested` and launches nothing; `beta` reaches its launch shim; neither honours `$WS_ROOT/STOP`, which survives byte- and mtime-identical |
| `TestNeitherCampaignWritesIntoTheOther` | 4 | each run leaves the neighbour's whole tree byte- and mtime-identical; each stamps only its own home; canonical **and** derived records stay in their own home and never name the other campaign |
| `TestTheCampaignsCannotBeConfusedForEachOther` | 3 | disjoint run names, screen sessions and `EXIT_DIR` markers; `record_id`s prefixed by their own campaign with an empty intersection; pointing `beta` at `alpha`'s home is refused by the stamp with `alpha`'s tree untouched |
| `TestLegacyAdoptionIsPerCampaign` | 1 | `alpha` adopts its pre-PR-E file and skips; `beta` adopts nothing and launches; the legacy file is not written to |

**Negative controls — executed against the implementation, and NOT left
in the suite.** An `xfail`-shaped test that passes by failing is
indistinguishable from a broken test six months later, so the module
asserts correct behaviour only and the controls are run as mutations:

| Mutation | Result |
|---|---|
| `QUEUE_STOP_FILE` default back to `$WS_ROOT/STOP` — the literal 08:17 defect | **3 fail**: `beta` stops on `alpha`'s file; both honour the legacy STOP; the launch sets collide |
| `CAMPAIGN_HOME` back to `$WS_ROOT` — both campaigns share one home | **6 fail**: cross-tree writes, a shared stamp, colliding markers, and legacy adoption leaking across campaigns |

Both restored and the module re-run green, verified by `grep -cF`.

**Static**: pyright 0 errors / 4 warnings (unchanged), ruff + format
clean.

**Deviations**: none. One harness adjustment during writing — `_run`
gained `**env` so the foreign-stamp case could pass `CAMPAIGN_HOME`;
test-side only.

**Next authorized checkpoint**: E-C8 (doc sync, last), then the full
suite and one Draft PR.

---

### E-C8 — Doc sync

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
historical record. **No `WAVE_WALL_SECONDS` change — see below.**

> **SEQUENCED OUT OF PR E — operator ruling, second review.**
> `docs/running_chain_test.md:142` and
> `docs/design/runtime_estimation_and_calibration.md:3841-3842` state
> `WAVE_WALL_SECONDS` defaults to `86400`; the code is `259200`
> (`v19_queue_runner.sh:89`), and `test_v19_campaign_pinning.py:190`
> asserts the cap exceeds 86400 — so the code is right and both docs
> are stale.
>
> **The correct sequencing is a separate docs-only hotfix that fixes
> 86400 → 259200 BEFORE PR E.** PR E's doc sync then simply does not
> touch those lines, because by then they are already correct.
>
> An earlier draft of this commit carried an acceptance criterion that
> `WAVE_WALL_SECONDS` must *still read 86400* after doc sync — i.e. it
> asserted a known-wrong operator-facing default as a passing condition.
> That directly contradicts V20's rule that operator-facing labels must
> reflect actual behaviour, and it has been **removed**. A deferral is
> permission not to fix something in this PR; it is never permission to
> pin the error in place.

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
- [ ] Confirm the predecessor docs hotfix has landed and both files
      already read `259200`. If it has not, **stop and report** rather
      than either fixing it here or documenting around it

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
- [ ] `WAVE_WALL_SECONDS` reads `259200` in both docs, corrected by the
      **predecessor docs hotfix**, and this commit's diff does not touch
      those lines
- [ ] Every checkpoint box in §6 of this document is either `[x]` with
      evidence or `[ ]` with a stated reason

#### 6. Failure and edge cases

| Case | Behaviour |
|---|---|
| A doc statement contradicts the merged code | **STOP** and report — it means an earlier commit deviated from the design |
| `WAVE_WALL_SECONDS` not yet corrected by the predecessor hotfix | **STOP and report.** Do not fix it here, and do not merge a doc sync that leaves a known-wrong default standing |
| Another stale default found in passing | Record it in §14 as a follow-up. Do not fix it here — the same reasoning that deferred OPEN-E-10 |
| An existing doc-sync test covers these files | Must be updated in this commit |
| A V19 protocol document describes the old paths | **Leave** — historical record, explicitly out of scope |

#### 7. Verification commands and evidence

```bash
grep -rn 'WS_ROOT/STOP\|v19_wave_state.jsonl\|gate0_pair_summary' docs/ \
     sdsc_submission_scripts/
grep -rn 'WAVE_WALL_SECONDS' docs/          # must show 259200 (predecessor hotfix)
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
- [ ] predecessor docs hotfix confirmed landed (`259200` in both files): __

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
5. `alpha` carries a legacy wave-state file and `beta` does not, so the
   adoption mode (BC-2) is exercised end to end alongside isolation.

**All five assertions pass in the committed suite.** The mutation
evidence that makes them a regression test rather than a description is
a **separate documented run** (Layer 4), not a suite member: an
expected-failure test is indistinguishable from a broken one after a few
months.

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
- **Mutation proof for E3**: remove the admission-guard call and
  confirm exactly one test fails — proving the guard is reached from the
  production path, not just unit-tested in isolation.
- **Mutation proof for E5 (the isolation control)**: temporarily restore
  the old `QUEUE_STOP_FILE` default **in the source**, run the isolation
  module, observe the failure, record it, restore, re-run green. This is
  the evidence that Layer 2 is a regression test. It is run and
  documented, never committed as an expected failure.
- **Reachability for E1**: add a deliberately unscoped path to the
  resolver in a scratch commit and confirm the enumeration test fails.
- **Hygiene for all of the above**: clear `.pyc` caches, assert each
  mutation hit exactly one site, and re-run the baseline afterwards —
  mutation proofs have lied before via stale bytecode and via a
  git-checkout silently restoring the target.

### Not required, and why

No Gate 1: PR E changes no LLM-facing prompt, schema or decision
surface.

No Gate 2 — **but not for the reason an earlier draft gave.** That draft
said "zero Python production modules are in scope", which is **false**:
PR E adds a typed campaign identity and a stamp model in `core/`, and a
wave-record writer in `scripts/`. The accurate statement is:

> **No existing scientific, GPU or agent Python production module is
> modified.** Two small campaign-control Python modules are added. None
> of the added code runs during training, inference, scoring, admission
> or estimation; none of it is imported by any node, by
> `sandbox_executor`, or by `core/runtime_control/`.

Gate 2 is therefore still N/A, on the ground that **nothing PR E adds
executes inside a scientific phase** — not on the ground that no Python
was added. The distinction matters: the first is checkable by an import
audit, and §7's genericization tests provide exactly that. If review
finds any added module reachable from a scientific phase, PR E stops and
the gate question reopens.

---

## 10. Merge criteria

- [ ] **No cross-campaign authority.** Every authority-bearing path the
      launchers read or write contains the resolved campaign identity,
      proved by the enumeration test, not by inspection.
- [ ] **Stop semantics unchanged.** C13 suite green with only path
      expressions changed; the E4 mutation proof recorded.
- [ ] **Historical evidence preserved.** A byte- and mtime-identity
      assertion over a legacy fixture tree after a full run.
- [ ] **Legacy state never re-acquires authority.** Adoption is a
      campaign-level mode decided once at first start and recorded in the
      stamp (BC-2), proved by the blocker case: new state present, legacy
      present, run completed **only** in legacy → the chain is
      **launched**.
- [ ] **The override surface cannot reconstruct the defect.** Only
      `WS_ROOT`, `CAMPAIGN_HOME` and the compatibility-only
      `QUEUE_STOP_FILE` are settable; no override can point two campaigns
      at one state directory (§4.2).
- [ ] **No manual cleanup before a new launch.** Demonstrated by the
      Layer-2 test starting `beta` with `alpha`'s STOP and the legacy
      global STOP both armed.
- [ ] **The role defect stays fixed.** Landed ahead of PR E
      (`fe51377c`, PR #165 — D-E-6); PR E must not regress it, proved by
      `test_v19_chain_role_resolution.py` green and unmodified.
- [ ] **The campaign id cannot escape the campaign root** (D-E-9),
      proved by refusal tests for an id **equal to** `.` or `..`, and for
      `/`, empty, absolute, control characters and over-length — each
      showing **no directory was created** — plus a **positive control**
      that `alpha..beta` is accepted, so the rule cannot silently tighten.
- [ ] **The same validator guards `GATE_RUN_PREFIX`** (D-E-4), not a
      second copy of the rule.
- [ ] **The two views of a wave record cannot diverge**: canonical JSONL
      written first with `fsync`, derived file second, both carrying the
      same `record_id`, and a retried wave producing a distinct one
      (D-E-3a).
- [ ] **Every commit was independently green**, with no knowingly-red
      intermediate (operator ruling, OPEN-E-9).
- [ ] Genericization section complete; FU-E-1..FU-E-8 filed.
- [ ] Doc sync commit (E-C8) verified by quoting each documented
      variable and default against the merged source.
- [ ] The predecessor docs hotfix has corrected `WAVE_WALL_SECONDS` to
      `259200`, and PR E's doc sync does not touch those lines. **No
      merge criterion asserts a known-wrong default.**
- [ ] The committed suite is **fully green** — every mutation and
      negative-control proof is a separate documented run, never an
      expected failure in the suite.
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
   fully green in the suite, with its mutation evidence recorded as a
   separate documented run.
4. **A record of which historical layouts remain readable** — §3.10
   promoted into `sdsc_submission_scripts/README.md`, naming each
   layout, its producer, and whether it is read, written, or read-only.
5. **The typed campaign identity** (D-E-9) — one validated identifier in
   `core/`, shared with `GATE_RUN_PREFIX` (D-E-4), refusing empty, `/`,
   `\`, control characters, over-length, and an id **equal to** `.` or
   `..` — while **accepting** an id that merely contains `..`.
6. **The typed atomic wave-record writer** (D-E-3, D-E-3a) — Pydantic
   record models plus a `mkstemp`/`fsync`/`os.replace` write in `core/`,
   the `scripts/` CLI the launcher calls, and the canonical-then-derived
   write order with a `record_id` in both views.
6a. **The campaign stamp with `legacy_adopted_from`** — the auditable
   record of whether this campaign may read legacy completion evidence
   at all (BC-2), created with `os.link` first-writer-wins semantics.
7. **The Behavior Delta statements** — §13, carried into the PR
   description.
8. **FU-E-1 … FU-E-8** — filed follow-ups.
8a. **The predecessor docs hotfix** — `WAVE_WALL_SECONDS` 86400 → 259200
   in `docs/running_chain_test.md:142` and
   `docs/design/runtime_estimation_and_calibration.md:3841-3842`, merged
   **before** PR E so PR E's doc sync need not touch it.
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

Completion detection reads the new file. It consults the legacy file
**only** when the campaign's stamp records `legacy_adopted_from` — a
decision made once, at first start, when the new state did not yet exist
and a legacy file for the same campaign id did (BC-2). Once new state
exists, the legacy file is never consulted again for any record.

**This is stricter than the earlier draft**, which fell back per record
whenever the new state lacked one. That would have skipped a launch on
the strength of a legacy record even while new state existed — authority,
not compatibility. A campaign started fresh after PR E has
`legacy_adopted_from: null` and no legacy read path at all.

**No existing file is written to again.** An operator inspecting an old
campaign finds everything where it was.

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
validation anywhere in the launcher. **After**: an id is **refused at
startup, before any directory is created** (D-E-9) if it is

- empty, or longer than 128 characters;
- contains `/`, `\`, a control character, or any other character outside
  `[A-Za-z0-9._-]` — which also excludes every absolute-path form;
- **or is equal to** `.` **or** `..`.

**It is NOT refused for merely containing `..`.** `alpha..beta` is a
legal one-segment directory name, cannot traverse anywhere, and is
accepted. The validator, its tests and this statement say *equal to*,
never *contains* — an earlier draft was inconsistent on exactly this
point.

This is a new refusal path that did not exist before, and it is the one
place PR E can reject a launch that previously proceeded. It is
deliberate: the id becomes a *directory* component for the first time,
and an id of `..` would resolve `$WS_ROOT/../control/STOP` — an escape
from the campaign root. Every id any real campaign has used (`v19`,
`v19r2…`, `v19_c14`, `camp1`) passes unchanged.

The **same** validator guards `GATE_RUN_PREFIX` (D-E-4), so an empty
prefix no longer yields `_pair_summary.json`.

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

### Closed — second operator review, 2026-08-04

**Architecture direction APPROVED.** Nine corrections were required
before implementation; all nine are applied in this revision. The
questions they closed:

| # | Decision |
|---|---|
| **OPEN-E-1** | **Directory model APPROVED.** The prefix-only alternative is off the table; §4.2 is the model, with the override surface narrowed (correction 2) |
| **OPEN-E-2** | **Do NOT move chain workspaces.** They stay flat at `$WS_ROOT/<run_name>` (§4.4) |
| **OPEN-E-3** | **Gate stop channel is NOT in PR E** — follow-up **FU-E-8**. The Gate keeps `trap write_summary EXIT` (`:304`) and `WALL_CAP_SECONDS` (`:48`) as its only bounds |
| **OPEN-E-4** | **V20 advice files are NOT PR E**, but **must be resolved before the V20 launch packet.** PR E leaves `advice/workflow/v18r_${FLAVOR}_explorer.json` (`:334`) exactly as it is; the *role* is already correct after `fe51377c` |
| **OPEN-E-5** | **RESOLVED AND FIXED** in a predecessor hotfix, before PR E. The collision is **real but not the pairing first proposed**: `v20` vs `v20a` does NOT collide — the glob's underscore delimiter separates them, and `v20a` was correctly independent. The defect is the **underscore-prefix** case: `{campaign_id}_*` matched `v20_extra_*`, so `v20` reported 600 tokens where it owned 100. That total feeds `SPENT_TOKENS` and `token_cap_reached`, so one campaign could be stopped by another's spend. **Fix: membership comes from the ROSTER, passed explicitly as repeated `--run-name`** — the same principle as E-C0's `role_for_run`: identity comes from the declared roster, never decoded from a string. Rejected alternatives: forbidding `_` in campaign ids (narrows the validator PR E specifies), parsing `{campaign_id}_{role}_{band}` (re-creates the implicit protocol E-C0 deleted), and any more elaborate glob. |
| **Budget fail-open** | **RESOLVED AND FIXED** in a second predecessor hotfix. `campaign_spend()` ended `2>/dev/null \|\| echo "0 0.00"`, so ANY helper failure became "zero spent" — which does not read as *unknown*, it reads as *budget available*, disarming both caps. Now **fail-closed**: an unreadable answer records `budget_accounting_unavailable` and exits 1, reusing the `pair_infeasible_under_host_quota` convention (a precondition the queue could not satisfy). Deliberately NOT `token_cap_reached` — that would blame the campaign's own spend for an infrastructure failure — and NOT exit 99, which means "stopped on request". **A `set -e` hazard was found while fixing it**: `_chain_common.sh:40` sets `-e` and the runner sources it at `:61`, so a bare `VAR="$(cmd)"` from a failing substitution kills the shell before any check runs; the first draft refused to launch but left no record. Guarded with `\|\| SPEND_RC=$?`, with a regression test that also asserts `set -e` is still active so the guard cannot become decoration. |
| **OPEN-E-6** | **The README campaign-control section IS PR E doc sync.** E-C8 creates it; §12 artifact 4 lives there |
| **OPEN-E-7** | **Prefixed filenames only.** No `$GATE_ROOT/$GATE_RUN_PREFIX/` subdirectory (D-E-4) |
| **OPEN-E-8** | **Validate the campaign id** — D-E-9, enforced in E-C2 before any `mkdir`. Rule corrected: reject *equal to* `.`/`..`, not *contains* (correction 4) |
| **OPEN-E-9** | **No knowingly-red intermediate**, as a standing rule for every commit, not a one-off merge (§8) |
| **OPEN-E-10** | **Separate docs hotfix, sequenced BEFORE PR E**, fixing 86400 → 259200. It is **not** a preserved error, and no PR E criterion asserts the wrong value (correction 8) |

Also closed, and not previously numbered:

- **The wave-record emission mechanism** → a typed atomic Python writer
  (D-E-3), with canonical/derived write order and `record_id`
  (D-E-3a, correction 5).
- **D-E-3's typed writer stays in PR E**, and **Gate summary scoping
  stays in PR E** — the Gate summary is the same campaign-identity
  overwrite defect class, not a separable concern.
- **BC-2's legacy model** → campaign-level adoption, not a per-lookup
  fallback (BLOCKER 1, correction 1).
- **The stamp guard's ordering** → one guard owns the whole admission
  sequence; the two guarantees are stated separately (§4.2a,
  correction 3).
- **D-E-7 leaves E-C2** → its own commit, E-C6 (correction 6).
- **The Gate 2 rationale** → "nothing added executes inside a scientific
  phase", replacing a false "zero Python production modules" claim
  (correction 9).
- **The isolation negative control** → a separate documented mutation
  run; the committed suite stays fully green (correction 9).

### Still open

**OPEN-E-4a — which advice files does the V20 campaign use?**
Closed *for PR E* (above) but **not closed for the launch.** The formal
queue still points at `advice/workflow/v18r_${FLAVOR}_explorer.json`
(`:334`) while `v19_gate0_arch.json` / `v19_gate0_loss.json` exist and
are unused. This is a scientific decision the code cannot answer.
*Resolved by*: the operator naming the V20 advice files **in the V20
launch packet**. Tracked here so it is not lost between PR E and launch.

**OPEN-E-11 — does the derived pair-summary view need a rebuild path?**
D-E-3a defines `pair_summaries/` as a derived view of the canonical
JSONL and states that historical waves are not backfilled (BC-1). If an
operator later wants the derived files for pre-PR-E waves, something has
to rebuild them. *Resolved by*: whether any operator report reads the
per-wave files directly rather than the JSONL. Filed as **FU-E-7**;
raised here because the answer also decides whether FU-E-1's mirror-key
removal is safe.

**OPEN-E-12 — should `$EXIT_DIR` markers move under the campaign home?**
They stay in `/tmp` (§3.4, §4.4) and do not collide, because run names
carry the campaign id. But `/tmp` is shared, survives across campaigns,
and is the one authority-adjacent path the E1 enumeration test cannot
assert campaign identity over. *Resolved by*: whether a stale
`${RUN}.exit` from an aborted identically-named run has ever been
misread. `:263` removes the marker before each launch, so the exposure
is narrow; recorded rather than acted on.

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
                        overwritten once (:379-382). No Python reads campaign
                        state. The role-derivation defect is FIXED and merged
                        ahead of PR E (fe51377c, PR #165).
Scope:                  Campaign path model with a narrow override surface;
                        one ordered campaign-admission guard (typed identity,
                        stamp, directories); campaign-level legacy adoption;
                        typed atomic wave/pair summary writer with a defined
                        canonical/derived contract; Gate summary scoping under
                        the same validator; the process-guard basename fix;
                        a shell isolation test.
Out of scope:           Stop semantics; no-respawn; deleting legacy evidence;
                        workspace relocation; an N-chain scheduler; wave
                        ordering; bands; advice content; any node; any
                        EXISTING core/ module; a Gate stop channel (FU-E-8);
                        the WAVE_WALL_SECONDS doc fix (predecessor hotfix);
                        the campaign_spend prefix-glob (FU-E-9).
Production callers:     sdsc_submission_scripts/v19_queue_runner.sh (queue),
                        v19_gate0_pair_runner.sh (Gate). _chain_common.sh is
                        read but not changed. Two NEW Python modules under
                        core/ and scripts/, called by the launcher exactly as
                        campaign_spend.py (:236-243) already is. No existing
                        Python module is modified.
Persistent schema impact: New control/campaign.json stamp, including
                        legacy_adopted_from. Wave summary record gains
                        `chains`, `campaign_id` and `record_id`, and moves to
                        a typed atomic writer; arch_*/loss_* retained as a
                        labelled mirror (FU-E-1). New derived per-wave files
                        under pair_summaries/, canonical source stays the
                        JSONL. Legacy files read only under adoption, never
                        rewritten.
Backward compatibility: BC-1..BC-5 (§4.3). No file moved, rewritten or deleted.
                        Legacy compatibility is a campaign-level MODE decided
                        once at first start (BC-2), not a per-lookup fallback.
                        One new refusal path: an invalid campaign id (BD-5).
Implementation checkpoints: E1 path model, E2 backward compat, E3 mismatch
                        guard, E4 stop semantics, E5 recovery validation.
                        Commits E-C1..E-C8 (§8), each independently green.
Deterministic tests:    Layer 1 (§9) — eleven named defects, each with the
                        statement of how it fails, plus positive controls on
                        the identifier rule.
Layer-2 evaluation:     Multi-campaign isolation, two synthetic campaigns,
                        five assertions, all PASSING in the committed suite.
Mutation evidence:      Separate documented runs, never suite members: E3
                        guard reachability, E4 stop-semantics independence,
                        E5 isolation control (old QUEUE_STOP_FILE default
                        temporarily restored in source), E1 unscoped-path
                        reachability. Cache-cleared, single-site-asserted,
                        baseline re-run.
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
                        class. An invalid campaign id, a foreign stamp and an
                        unresolvable Gate prefix are startup refusals with
                        named diagnostics, not classified failures.
Attribution:            Not applicable — no OOM, no resource decision.
Genericization impact:  §7 — seven questions answered; closes FU-B-7.
Hardcoding introduced:  None. Two path values, one identifier pattern and one
                        record_id format, all configured policy or derived
                        structure with documented behaviour.
Hardcoding removed:     v19_queue_runner process-guard literal (:259);
                        MAX_CONC=2 (:80, closes FU-B-7); the two-role state
                        schema (:226-229); an unvalidated campaign id and an
                        unvalidated GATE_RUN_PREFIX used as path components;
                        "gate": "v19_gate0" (gate :290);
                        gate0_pair_summary.json (gate :59). The v19_loss_
                        role literal was removed ahead of PR E by #165.
Hardcoding deferred:    FU-E-1 arch/loss mirror keys; FU-E-2 N-chain launcher;
                        FU-E-3 v18r historical surface; FU-E-4 shared
                        identifier extraction from observation_store;
                        FU-E-5 shared atomic-write helper; FU-E-6 pyright
                        coverage and mode; FU-E-7 derived-view rebuild path;
                        FU-E-8 Gate stop channel; FU-E-9 campaign_spend
                        prefix-glob collision.
Artifacts:              §12 — eleven.
Stop conditions:        §11 — seven.
Merge criteria:         §10 — seventeen.
Dependencies:           fe51377c (PR #165) already on master. One predecessor
                        docs hotfix (WAVE_WALL_SECONDS 86400 -> 259200) must
                        merge BEFORE PR E's doc sync.
Operator decisions:     Architecture direction APPROVED, second review
                        2026-08-04, with nine corrections — all applied.
                        APPROVED: D-E-4 (all three Gate sub-decisions),
                        D-E-6 (DONE, merged fe51377c), D-E-9.
                        CLOSED: OPEN-E-1..E-3, E-5..E-10 (§14 table).
                        PENDING: D-E-1, D-E-2, D-E-3, D-E-5, D-E-7, D-E-8.
                        STILL OPEN: OPEN-E-4a (V20 advice files — required
                        before the launch packet, not before PR E),
                        OPEN-E-11 (derived-view rebuild), OPEN-E-12
                        (EXIT_DIR markers).
```

---

## 16. Implementation ledger — final

Written at E-C8, from `git log` and the per-checkpoint records above.
Branch `feature/v20-pr-e-campaign-scoped-control`, cut from the design
freeze `786e0319`.

### 16.1 Commits

| # | SHA | Commit | Behavior Delta |
|---|---|---|---|
| E-C1 | `ded153d0` | Campaign path resolver, deliberately inert | **none** — every path byte-identical |
| E-C2 | `29af020c` | Campaign admission and the path move | **BD-1, BD-3 (partial), BD-5** |
| E-C2b | `9060b13f` | Refuse an explicitly empty campaign id | an empty `CAMPAIGN_ID` exits 1 instead of running as `v19`; unset unchanged |
| E-C3 | `ed61bb50` | Campaign-level legacy adoption | **BD-2, BD-3 (completes it)** |
| E-C4 | `25a95556` | Typed wave record, canonical/derived dual write | **BD-4** |
| E-C4b | `061bccfb` | State an unresolved chain role | none for a fully-resolved wave; two additive keys otherwise |
| E-C5 | `240d7ac1` | Scope the Gate summary and log by run prefix | Gate artifacts prefix-scoped; `"gate"` is the resolved prefix; unsafe/empty prefix refused |
| E-C6 | `6dc1fdb1` | Queue-runner self-exclusion from the script name | **BD-6** |
| E-C6b | `f3c7cf5b` | Gate-runner self-exclusion from the script name | same, for the Gate |
| E-C7 | `01ee1eda` | Multi-campaign isolation test | **none — zero production lines** |
| E-C8 | *this commit* | Doc sync | **none — documentation only** |

**Predecessor hotfixes**, merged to master before this branch and
inherited rather than reimplemented: `fe51377c` (#165, role from the
ROSTER — D-E-6), plus the `WAVE_WALL_SECONDS` docs fix, the
`campaign_spend` membership fix and its fail-closed correction (#168).

### 16.2 Checkpoints

| | Status | Evidence |
|---|---|---|
| **E1** Path model | `[x]` | E-C1 + E-C2; the path-enumeration test asserts every authority-bearing path carries the campaign id |
| **E2** Backward compatibility | `[x]` | E-C3; adoption is a once-only stamp field, and a four-file legacy tree is byte- and mtime-identical after an adopting run |
| **E3** Campaign mismatch protection | `[x]` | E-C2 + E-C2b; one ordered guard, refusals observed on the filesystem |
| **E4** Stop semantics preserved | `[x]` | property, not a commit: all 14 C13 assertions pass under the path-revert mutation |
| **E5** Recovery validation | `[x]` | E-C7; 11 tests, two documented negative-control mutations |

### 16.3 Measured evidence

| Commit | Tests | Static | Mutations |
|---|---|---|---|
| E-C1 | 14 new / 340 targeted, 8.3 s | pyright 0, ruff clean | 2 (1 fail, 8 fail) |
| E-C2 | 404, 10.8 s | pyright 0 | 4 (16, C13 14/14 green, 6, 2) |
| E-C2b | 408 | pyright 0 | 1 (3 fail) |
| E-C3 | 438, 37.2 s | pyright 0 | 4 (6, 2, 3, 2) |
| E-C4 | 471, 38.3 s | pyright 0 | 4 (2, 4, 5, 2) |
| E-C4b | 474 | pyright 0 | 1 (2 fail) |
| E-C5 | 494, 54.4 s | pyright 0 | 3 (11, 12, 1) |
| E-C6 | 2445 full unit, 103 s | pyright 0 | 2 (3, 2) |
| E-C6b | 430 launcher | pyright 0 | 2 (3, 2) |
| E-C7 | 11 module / 441 launcher | pyright 0 | 2 negative controls (3, 6) |
| E-C8 | 498 launcher + doc-sync | pyright 0 | — |

Pyright is **0 errors, 4 warnings** at every commit — identical to the
pre-branch baseline; the two new `core/` modules and three new
`scripts/` entries are all inside `pyrightconfig.json`'s `include`.
`ruff check`, `ruff format --check` and `bash -n` clean throughout.
`"typeCheckingMode"` is `"basic"`, not strict, and this PR does not
change it.

### 16.4 Deviations from the frozen design

| # | Deviation | Why |
|---|---|---|
| 1 | **`chains[].run_name`, not `run`** (E-C4) | D-E-3's own example record made a **failed** chain satisfy `chain_completed`, which greps the whole line. Measured, not theorised. A field-naming fix: no authority semantics move |
| 2 | Directory creation lives in Python, inside the one guard (E-C2) | a shell `mkdir` would necessarily precede the validator and break the "refuse before any `mkdir`" guarantee |
| 3 | `${VAR-default}` for `CAMPAIGN_ID` and `GATE_RUN_PREFIX` (E-C2b, E-C5) | `:-` made an explicitly empty value unreachable by the validator that was required to refuse it |
| 4 | Adoption source re-validated on every use, against the exact filename (E-C3) | §4 required "outside `$WS_ROOT` → STOP"; the exact-name form is stricter for the same cost and also closes a sibling campaign's file |
| 5 | Exit code 3 for "canonical written, derived not" (E-C4) | §4 required the two failures to be distinguishable; this is how the shell distinguishes them |
| 6 | `role_resolution_failed` / `unresolved_roles` rather than overloading `disposition` (E-C4b) | `disposition` describes chain outcomes; a recording gap is not one, and overloading it would drop the wave for anyone filtering on `complete` |
| 7 | `validate_path_component` extracted; `validate_campaign_id` delegates (E-C5) | the Gate must reach one rule, not a second copy — but calling a campaign-named function from the Gate would have made the Gate a campaign |
| 8 | `-F` on the self-exclusion (E-C6, E-C6b) | operator instruction, and load-bearing: the basename contains `.`, so a regex would widen the exclusion to processes that are not the runner |
| 9 | C13 gained a 2-line `LOGF` pin (E-C2) | a test-harness assumption, not a semantics change: production `log()` is unreachable before admission, asserted by a test |
| 10 | Three more tests re-pointed than §2 named (E-C2, E-C5) | a shared `_state_env` helper, a prefix-shaped pinning assertion, and the Gate harness's summary path |

### 16.5 Follow-ups

**Every `FU-E-*` id this document mentions appears below.** A first
version of this table listed only nine of the twelve and the completion
summary reported "seven open", which was wrong twice over: FU-E-5 and
FU-E-6 are open and were missing, and FU-E-9 is closed and was missing.
Corrected here, and the count is now derived from the table rather than
asserted beside it.

**Nine open, two closed, one withdrawn.**

| id | Status |
|---|---|
| FU-E-1 | **open** — remove the `arch`/`loss` compatibility mirror once every report consumer reads `chains[]`. Deliberately not widened into PR E |
| FU-E-2 | **open** — an N-chain *scheduler*; the state schema is already N-chain-capable, the launcher is not |
| FU-E-3 | **open** — `v18r_queue_runner.sh:48` carries the same self-exclusion pattern; historical surface, protected from change by an existing test |
| FU-E-4 | **open** — unify `_WRITER_ID_RE` (`observation_store.py:38`) with `validate_path_component` |
| FU-E-5 | **open** — share one atomic-write helper instead of the local copy; reaching into a PR C module's private method is worse than one copy |
| FU-E-6 | **open** — `pyrightconfig.json` excludes `tests` and runs `basic`, not `strict`. A type-checking policy change is not PR E's causal claim |
| FU-E-7 | **open** — rebuild derived per-wave views for historical waves |
| FU-E-8 | **open** — a Gate stop channel, deliberately not added here |
| FU-E-10 | **open** — `band_tag` yields `00_00` for malformed input instead of refusing |
| FU-E-9 | **closed** — the `campaign_spend` prefix-glob collision, fixed by a predecessor hotfix before this branch; `scripts/campaign_spend.py` now takes explicit `--run-name` values and the glob is gone |
| FU-E-12 | **closed** — the Gate's identical self-exclusion, fixed in E-C6b rather than deferred (operator ruling) |
| FU-E-11 | **withdrawn** — reclassified by operator review as an E-C2 implementation defect, not a follow-up; fixed in E-C2b |

### 16.6 Final Behavior Delta

**BD-1** the queue stop file's default moves into the campaign's
`control/`. **BD-2** a legacy `$WS_ROOT/STOP` no longer blocks a launch;
it is observed and recorded. **BD-3** queue and wave state move to a
campaign directory, with a once-only legacy read-back. **BD-4** the wave
summary gains `chains`, `record_id` and a derived per-wave file;
`MAX_CONC` is gone. **BD-5** an invalid — or explicitly empty — campaign
id is refused before anything is created. **BD-6** the live-process guard
no longer hardcodes the script name, in either runner.

Not changed: stop timing, exit code 99, signal handling, the no-respawn
rule, chain-level `$WORKSPACE/STOP`, `chain_stopped.json`, chain
workspace layout, `EXIT_DIR`, queue scheduling, concurrency, GPU
admission, scientific configuration, and LLM-facing behaviour.

### 16.7 Validation status

- Local, full `tests/unit` at the final head `b0f83568`:
  **7272 passed, 2 skipped, 4 xfailed** in 427 s.
- Exact-head static checks: pyright **0 errors, 4 warnings**;
  `ruff check` clean; `ruff format --check` clean; `bash -n` clean over
  every script in `sdsc_submission_scripts/`.
- **CI: PASS** on `b0f83568` — `Lint + Type + Unit Tests`, 9m53s,
  [run 30959782093](https://github.com/Galileo-Sandbox/SIDERIUS/actions/runs/30959782093).
  Draft PR **#169**, not merged.
- No real-training run, no GPU run, no API key, and no real Gate was
  executed by any commit in this PR.
