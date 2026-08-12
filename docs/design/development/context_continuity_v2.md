# Context Continuity v2 — PR-scoped compact / resume infrastructure

## Status

**IN IMPLEMENTATION.** Operator-authorized 2026-08-12 as a standalone
maintenance PR. This document is the **PRIMARY DESIGN DOC** — the
semantic implementation authority for this PR and its live ledger.

This is **NOT** a Generic Framework roadmap step. It changes no
scientific, model, dataset, scorer, tuner, prompt, schema or runtime
behavior.

| Item | Value |
|---|---|
| Implementation base | `aec6db05756ae325a6204f34b58c037e564666c6` (post-PR-01a master) |
| Branch | `feat/context-continuity-v2` |
| Predecessor | PR #199 MERGED as `39f89f52` (verified: `fe4ec2e5` and `d84f6711` are ancestors of master) |
| PR 01b | UNBLOCKED / NOT STARTED — **not touched by this PR** |
| Normal stop | READY FOR OPERATOR REVIEW — **do not merge** |

### The central lifecycle principle (FROZEN)

> **CONTINUITY IS INTRA-PR.
> REPOSITORY DESIGN DOCUMENTS ARE INTER-PR MEMORY.**

One Claude implementation context belongs to exactly one PR. Compaction
and resume may happen many times inside that PR. The *next* PR starts
with a fresh Implementation Working Rules contract and a freshly
initialized handoff — it never inherits the previous PR's unfinished
scratch state. Previous-PR history lives in its design ledger, git
history, the PR record and the parent status document.

---

## 1. CURRENT-STATE AUDIT (source-grounded, 2026-08-12)

Performed on the checkout at `aec6db05` against Claude Code
**2.1.228** (`/home/yuema137/.local/share/claude/versions/2.1.228`,
ELF binary, not stripped). Every claim below was re-verified in source
or in the installed binary; the earlier rescue report was **not**
treated as authority.

### 1.1 Hook registration and matchers (audit item 1)

`.claude/settings.local.json` (gitignored) registers exactly two hook
families — there is no third, and no context-threshold hook of any
kind:

```text
PreCompact   matcher "manual" -> ${CLAUDE_PROJECT_DIR}/.venv/bin/python
                                 ${CLAUDE_PROJECT_DIR}/.claude/hooks/precompact_memory_guard.py
             matcher "auto"   -> (identical command)
SessionStart matcher "compact" | "resume" | "startup" | "clear"
                              -> ${CLAUDE_PROJECT_DIR}/.venv/bin/python
                                 ${CLAUDE_PROJECT_DIR}/.claude/hooks/inject_session_memory.py
```

Both PreCompact matchers invoke the **same command with no argument**,
so the two registrations are behaviourally identical today: the mode
distinction exists in the registration but is discarded before the
script can act on it.

### 1.2 Actual hook payloads (audit items 2, 4, 5, 12)

Extracted from the installed binary rather than from documentation or
memory.

Base fields, built by the shared constructor for every hook event:

```text
session_id, transcript_path, cwd, prompt_id, permission_mode,
agent_id, agent_type, effort
```

**PreCompact** adds:

```text
hook_event_name: "PreCompact"
trigger:          "manual" | "auto"
custom_instructions: <string>
```

and dispatches with `matchQuery: e.trigger` — i.e. **the matcher
matches on `trigger`**, and the same value is also present in the JSON
payload.

**SessionStart** adds:

```text
hook_event_name: "SessionStart"
source: "startup" | "resume" | "clear" | "compact"
agent_type, model, session_title
```

and dispatches with `matchQuery: e` where `e` is the source — so the
matcher matches on `source`, and `source` is likewise in the payload.

**Consequence (decisive for §13 of the authorization):** manual vs auto
is available *twice over* — via the registration matcher and via the
`trigger` field. No fragile inference is needed. Same for SessionStart
via `source`.

**Available hook events** (all present in 2.1.228): `PreToolUse`,
`PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`,
`SubagentStop`, `PreCompact`, `PostCompact`, `SessionStart`,
`SessionEnd`, plus others. **There is no context-percentage event of
any kind** — confirmed by enumeration, and consistent with the existing
guard's own docstring ("there is no hook that fires at '10%
remaining'"). The v2 design does not build one.

`PostToolUse` exists and fires after tool calls, so a *reminder* is
mechanically possible — see §6.3 for why it is used only as a clock,
never as a commit detector.

### 1.3 FINDING — the subagent guard is dead code (audit item 2)

```text
Previous assumption:
  precompact_memory_guard.py correctly skips subagent compactions by
  reading `is_subagent` / `isSubagent` / `subagent` from the payload
  (`precompact_memory_guard.py:74-76`).

Audit evidence:
  the PreCompact hook input schema contains no such field. The base
  field builder emits `agent_id` and `agent_type`, and the binary
  documents agent_type as "Present when the hook fires from within a
  subagent (alongside agent_id)". The strings `is_subagent` /
  `isSubagent` occur in the binary only as telemetry
  (`is_subagent: Boolean(U.agentId)`) and as a `cc_is_subagent=true`
  request header — never as hook input.

Corrected understanding:
  the three key lookups never match, so the early return never fires.
  A subagent compaction today runs the FULL guard against the main
  session's handoff.

Implementation consequence:
  the tracked guard detects a subagent by the presence of `agent_id`
  (falling back to `agent_type`), preserving the intended semantics
  with the field that actually exists.

Validation consequence:
  a test must assert the skip fires for a payload carrying `agent_id`
  and does NOT fire for a main-thread payload. The old test suite
  could not have caught this: it asserted the skip using the
  non-existent field name, so it tested its own fiction.
```

This has been latent since the hooks were written. It is not urgent —
the failure mode is a subagent compaction being blocked by the main
session's stale handoff, which is annoying rather than dangerous — but
it is exactly the class of defect this PR exists to remove.

### 1.4 Exit-code / stdout / stderr semantics (audit item 3)

- `precompact_memory_guard.py` returns **0** to allow, **2** to block;
  diagnostics go to **stderr**. The binary carries the matching
  operator-visible strings ("compaction blocked by PreCompact hook",
  `compaction-blocked-by-hook`), confirming exit 2 genuinely blocks.
- `inject_session_memory.py` always returns **0**; its **stdout** is
  injected into the model's context (the docstring's claim is
  consistent with the SessionStart dispatch path). Output is capped at
  `MAX_INJECTED_CHARS = 24_000`.
- Both scripts tolerate an absent/malformed payload by degrading to an
  empty dict rather than crashing — preserved in v2.

### 1.5 Fingerprint algorithm and self-reference (audit items 6, 7)

`_session_memory.working_tree_fingerprint()` hashes, in fixed order:
`git diff` (unstaged) + `git diff --cached` (staged) + every untracked
non-ignored path from `git ls-files --others --exclude-standard`,
sorted bytewise, each contributing `path\0<sha256>` at or below
`MAX_HASHED_BYTES` (2 MiB) and `path\0size:<n>` above it. Unreadable
paths contribute `path\0unreadable`. The three parts are joined with
domain separators and hashed once. A clean tree yields a stable digest
of three empty parts.

`_is_self_referential()` excludes exactly two things: the memory file
basename, and anything under `.claude/`. The docstring is explicit that
this is **load-bearing, not tidiness** — if the memory file counted
toward the fingerprint it records, writing the handoff would instantly
invalidate the handoff and the guard could never be satisfied.

**v2 keeps this contract unchanged in substance.** `.claude/` stays
excluded (it is gitignored anyway, so it never appears in the untracked
listing — the exclusion exists so a checkout *without* those ignore
rules cannot deadlock). Tracked `tools/claude_hooks/**` is **NOT**
excluded: it is ordinary tracked source, and hiding it would defeat the
mechanism (§10 of the authorization).

### 1.6 Required headings and fields (audit item 8)

The guard requires 15 headings (`## Current Objective`, `## Frozen
Policy and Non-Negotiable Decisions`, `## Completed Checkpoints`,
`## Current Checkpoint`, `## Current Implementation State`,
`## Decisions Made and Why`, `## Audits Performed and Evidence Found`,
`## Problems Encountered`, `## Deviations from the Design`,
`## Validation Already Completed`, `## Known Limitations and Deferred
Follow-ups`, `## Genuine Open Policy Questions`, `## Exact Next
Actions`, `## Stop Conditions`, `## Design-Document Synchronization`)
and 5 `Key: value` fields (`Handoff updated for HEAD`, `Handoff
working-tree fingerprint`, `Design document synchronized`, `Design sync
reference`, `Safe to compact`), with a placeholder blacklist
(`todo`/`tbd`/`unknown`/`fill this in`/`n/a`/`xxx`/empty).

**Gap for v2:** none of these encode **PR identity** or **context
state**. Nothing in the current contract can express "this handoff
belongs to PR X" or "this context is CLOSED", which is precisely the
failure mode the lifecycle principle forbids. v2 adds those fields.

`read_field()` is anchored per line and searches the semantic block
only — but it returns the **first** match, so a duplicated key silently
takes its first value. v2 keeps the anchoring and adds a duplicate-key
check.

### 1.7 Template-path coupling (audit item 9) — the fresh-checkout defect

`TEMPLATE_RELPATH = ".claude/memory/before_end_memory.template.md"`,
consumed by `first_principles_match_template()`, which returns
`(False, "canonical template missing at ...")` when absent — and the
guard turns that into a **BLOCK**.

```text
Previous assumption:
  the template is runtime state and may stay under gitignored .claude/.

Audit evidence:
  the guard validates the handoff's first-principles block against the
  template and BLOCKS when it cannot be read. `.gitignore:38` is a bare
  `.claude/`, so a fresh checkout receives neither the template nor the
  hooks.

Corrected understanding:
  the template is part of the tracked logic's CONTRACT, not runtime
  state. Tracking the guard while leaving the template ignored ships a
  guard that blocks compaction for every teammate on first use.

Implementation consequence:
  the canonical template moves to tools/claude_hooks/templates/ and is
  resolved relative to the tracked module's own location, never via a
  `.claude/` path.

Validation consequence:
  test Q constructs a temp checkout containing the tracked files and NO
  `.claude/` directory and proves the guard still functions.
```

### 1.8 V21 hardcoding (audit item 10)

`inject_session_memory.py:52-59`, inside the module-level `RECOVERY`
constant, hardcodes the recovery ladder as:

```text
a. docs/design/v21_priorities.md — the V21 ledger …
b. docs/design/v21_priorities/README.md — the folder index …
c. that PR's own design document under docs/design/v21_priorities/
   (currently pr_c_generated_model_production_compat.md) …
```

Every resumed session is therefore pointed at a V21 PR that is not the
active work — as observed live at this session's own startup. None of
these literals may survive in the tracked implementation (test R).

### 1.9 Behavior when memory is missing or stale (audit item 11)

- **Missing** — the guard BLOCKS (`load_memory` raises → exit 2); the
  injector prints a "no carried-over state, audit the repository"
  notice and exits 0. The injector's degradation is correct and is
  preserved; the guard's block is correct for *manual* and is the
  deadlock this PR removes for *auto*.
- **Stale** — `validate()` returns **all** failing conditions (not the
  first, deliberately, so one retry can fix everything). The guard
  blocks on any. The injector prepends a WARNING block listing them and
  still injects.
- **Malformed markers** — the guard blocks with a "malformed and cannot
  be refreshed" diagnostic.
- The guard **rewrites the generated region first**, then compares — so
  the freshness comparison always reports on the tree as it is at
  compact time. Semantic content is byte-preserved. v2 keeps this.

### 1.10 Repo-root discovery and fresh-checkout behavior (audit items 13, 14, 15)

`repo_root()` prefers `${CLAUDE_PROJECT_DIR}` (validated by the presence
of `.git`) and falls back to `git rev-parse --show-toplevel`, never the
ambient cwd — portable, and compliant with the repository's
"never hardcode an absolute repository path" rule. Preserved verbatim.

Hook scripts **can** safely create local files: `atomic_write()` already
does `mkdir(parents=True)` + temp-file + `os.replace`, and the guard
already writes the memory file during a compaction attempt. Creating
`.claude/context_rescue/` is therefore not a new capability, only a new
call site.

Fresh checkout today: gets **neither** hooks nor template (both under
gitignored `.claude/`), so there is nothing to break — and nothing to
inherit. After v2, a fresh checkout gets the implementation, the
template and the tests, and needs only local registration.

### 1.11 Gates created by tracking

`pyrightconfig.json` `include` lists `tools` (mode `basic`); `tests` is
excluded. CI runs `ruff check .`, `ruff format --check .`, `pyright`,
and `pytest tests/unit/ -m "not real_run" -q`. Ruff lint selects
`E,W,F,I,B,UP,SIM,RUF` at line-length 100. Local pyright is
**unavailable** (Node v10.19.0); remote CI is authoritative.

`scripts/pr3_l2_calibration/preflight.py` allowlists only
`scripts/pr3_l2_calibration/`, `tests/`, `docs/`, `reports/` and
`*.md`. Uncommitted `tools/claude_hooks/*.py` therefore turns
`test_preflight_all_invariants` RED in a full-suite run. **Expected
behavior — the allowlist is not widened and the preflight is not
weakened.** Commit the semantic checkpoint before the full suite.

`tools/` and `tests/unit/tools/` are pre-existing tracked conventions
(`tools/build_token_baseline_report.py`,
`tests/unit/tools/test_token_baseline_report.py` + `__init__.py`), so
no new source-layout convention is introduced and `.gitignore` is not
touched.

---

## 2. Context authority model (FROZEN)

```text
1. repository / git / process truth
2. PRIMARY DESIGN DOC          (this file, for this PR)
3. parent / higher binding design docs
4. before_end_memory.md
5. emergency mechanical auto-compact snapshot
6. conversational memory
```

A lower source may never override a higher one. Roles:

| Artefact | Role |
|---|---|
| PRIMARY DESIGN DOC | semantic implementation authority for THIS PR |
| parent / binding docs | architecture + cross-PR status authority |
| `before_end_memory.md` | concise compact/resume continuation handoff |
| emergency snapshot | mechanically derived last-resort evidence only |

Memory is **not** a history archive.

---

## 3. Target architecture

```text
TRACKED (tools/claude_hooks/)
  context_state.py       repo truth, fingerprint, handoff parse/validate,
                         template lookup, snapshot paths  [shared]
  precompact_memory_guard.py   manual: strict | auto: fail-safe
  inject_session_memory.py     dynamic SessionStart injection
  templates/before_end_memory.template.md   canonical, PR-scoped

TRACKED (tests/unit/tools/claude_hooks/)   normal CI, no Claude Code needed

LOCAL / IGNORED
  .claude/settings.local.json   registration -> invokes the tracked scripts
  .claude/context_rescue/       emergency snapshots
  before_end_memory.md          active handoff (existing ownership)
```

Mode resolution, in order: explicit `--mode {manual,auto}` (so the code
is testable without Claude Code) → payload `trigger` → **default
`manual`**, because the strict path is the safe default when the mode
is unknown.

---

## 4. Implementation phases

- [x] **C0** kickoff: precondition verified, branch cut, this document,
      fresh PR handoff initialized.
- [x] **C1** tracked shared foundation + canonical template.
- [x] **C2** strict MANUAL PreCompact path.
- [x] **C3** fail-safe AUTO PreCompact + mechanical rescue snapshot.
- [x] **C4** dynamic SessionStart / resume injection.
- [x] **C5** PR-scoped lifecycle (init / continuation / closeout).
- [ ] **C6** local registration migration + developer documentation.
- [ ] **C7** adversarial validation, dry-run dossier, closeout.

Each phase records: Goal, Scope, Implementation, Validation,
Acceptance, Failure cases, Evidence, Commit boundary.

### C0 — kickoff / audit / PR context

**Goal.** Establish a verified base, a fresh PR context, and the §1
audit before any implementation.

**Scope.** This document + `before_end_memory.md` re-initialization.
NON-goals: any `tools/` code, any hook change, any registration change.

**Implementation.**
- [x] Precondition verified mechanically (PR #199 MERGED as `39f89f52`;
      `fe4ec2e5`/`d84f6711` ancestors of master; parent status marks
      01a MERGED and 01b UNBLOCKED/NOT STARTED; tree clean).
- [x] Branch `feat/context-continuity-v2` cut from `aec6db05`.
- [x] §1 current-state audit written from source + installed binary.
- [x] Two findings recorded (§1.3 dead subagent guard, §1.7 template
      fresh-checkout defect).
- [ ] `before_end_memory.md` re-initialized for THIS PR.

**Acceptance.** The active handoff names this PR and this design doc;
no PR-01a content remains active; the guard passes on the C0 head.

**Commit boundary.** Docs + runtime handoff only. Zero code.

**Evidence.** `46ae5904`. Guard PASS at that head with the new handoff;
clean tree.

### C1 — tracked shared foundation + canonical template

**Goal.** One tracked module both hook entry points will consume, plus
the canonical template beside it, with the fingerprint contract
preserved bit-for-bit so migration cannot invalidate a live handoff.

**Scope.** `tools/claude_hooks/context_state.py`,
`tools/claude_hooks/templates/before_end_memory.template.md`,
`tests/unit/tools/claude_hooks/` (+ `__init__.py`, `conftest.py`).
NON-goals: no hook entry point yet, no registration change, no deletion
of the ignored implementation.

**Implementation.**
- [x] `context_state.py` — repository truth (`repo_root`, `head_sha`,
      `branch_name`), the fingerprint, handoff section/field parsing,
      template lookup, generated-region rendering/replacement, atomic
      write, rescue path, and `validate()`.
- [x] The fingerprint algorithm is ported **unchanged in behaviour** —
      required, because the live handoff records a value computed by the
      legacy code and migration must not invalidate it. Proven by the
      clean-tree constant `bd3e625c…` matching across both.
- [x] `template_path()` resolves from `Path(__file__).parent/templates/`
      — the §1.7 fix.
- [x] Canonical template assembled programmatically: the
      first-principles block is copied **byte-identically** from the
      legacy template (verified `True` in the assembly script) so the
      live handoff validates against BOTH implementations throughout
      migration; the legacy template's trailing V20 campaign history
      (lines 312-454) is dropped as initiative-specific prose.
- [x] New required fields — `PROJECT / PR`, `PRIMARY DESIGN DOC`,
      `CONTEXT STATE` — plus `PRIdentity` / `context_state()` parsing,
      tolerant of the documented `CLOSED / AWAITING OPERATOR ACTION`
      closeout wording.
- [x] Two validator additions beyond the legacy behaviour: a
      **duplicate-field** check (see the finding below) and a
      **design-doc existence** check (a handoff naming a missing design
      file points the resumed session at nothing).

**Validation.** `pytest tests/unit/tools/claude_hooks/ -q` →
**23 passed, 0.45 s**. `ruff check` + `ruff format --check` clean on
both new directories. Cross-check: the tracked `validate()` and the
legacy guard agree on the live handoff.

**FINDING — the duplicate-field hazard is real, and the template had it.**

```text
Previous assumption:
  restating PRIMARY DESIGN DOC under `## Design-Document
  Synchronization` is harmless redundancy.

Audit / implementation evidence:
  `read_field()` returns the FIRST regex match. The new duplicate check
  fired on the very first run of the fixture built FROM the shipped
  template — the template declared the field twice (lines 257 and 322),
  and so did the live handoff.

Corrected understanding:
  a duplicated field is a silent-staleness generator: an agent editing
  the later copy sees its correction ignored forever.

Implementation consequence:
  the field is declared ONCE, under `## PR Identity`; both the template
  and the live handoff now say so explicitly at the old site.

Validation consequence:
  `test_duplicate_field_is_reported_not_silently_first_wins` pins it,
  and building the fixture from the shipped template is what made the
  defect visible rather than hypothetical.
```

**FINDING — a fixture ordering bug that made staleness tests vacuous.**

```text
Previous assumption:
  the handoff factory could apply caller overrides while filling the
  template, then pin HEAD/fingerprint afterwards.

Audit / implementation evidence:
  `test_stale_head_is_named` passed a stale HEAD and the validator did
  not complain — because the post-fill freshness pin overwrote the
  override. The test asserted on a handoff that was actually CURRENT.

Corrected understanding:
  overrides must be applied LAST, after the freshness pin.

Implementation consequence:
  the factory reorders: create design doc -> commit -> fill -> pin
  HEAD/fingerprint -> apply overrides -> write.

Validation consequence:
  without this, every staleness test in the file would have passed for
  the wrong reason. It surfaced only because the duplicate-field check
  changed which problem the validator reported first.
```

**Failure/edge cases exercised.** `git init -b` requires git >= 2.28 and
the local git is 2.25.1 — classified as a FIXTURE/environment defect,
not an implementation defect, and fixed by not pinning the default
branch name (it is not load-bearing for any test here). Recorded because
CI's git version is not guaranteed to match a developer's.

**Deferred (recorded, not silently dropped).** The first-principles
block does not yet carry an explicit PR-scoped clause. Adding one
requires editing the template and the live handoff in the same commit,
and while the LEGACY guard is still registered it would also have to be
mirrored into the legacy template. It therefore lands with the
registration switch in C6, where only the tracked implementation is
authoritative. The PR-scoped contract is already encoded in the
template's semantic skeleton (`## PR Identity`, `CONTEXT STATE`, and the
"belongs to exactly ONE pull request" preamble).

**Commit boundary.** Tracked foundation + template + tests. No hook
entry point, no registration change; the ignored implementation remains
the live one.

**Evidence.** `900e6242`. 23 passed, 0.45 s; ruff + format clean.

### C2 — strict MANUAL PreCompact path

**Goal.** A tracked guard entry point whose manual path is a faithful
migration of the legacy strict behaviour, with the mode resolved
explicitly and the §1.3 subagent defect fixed.

**Scope.** `tools/claude_hooks/precompact_memory_guard.py`,
`tests/unit/tools/claude_hooks/test_precompact_guard.py`. NON-goals: the
auto fail-safe branch (C3), any registration change.

**Implementation.**
- [x] `main(argv, *, stdin)` — injectable argv and stdin, so every test
      runs in-process without Claude Code.
- [x] Mode resolution `--mode` → payload `trigger` → **`manual`**.
      Defaulting to the strict path means an upstream field rename
      degrades to "too strict", never to "silently never checks".
- [x] `is_subagent()` reads `agent_id` / `agent_type` — the §1.3 fix.
- [x] `sys.path` is anchored to the repository root
      (`parents[2]`) so the module has ONE identity whether executed as
      a script (as registered) or imported by tests.
- [x] The missing-handoff diagnostic now names the canonical template
      path, so an agent that has never seen this system knows how to
      create one.
- [x] Auto shares the strict path in this commit, documented in the
      module docstring rather than implied.

**Validation.** `pytest tests/unit/tools/claude_hooks/ -q` →
**42 passed, 1.12 s** (23 from C1 + 19 here). ruff + format clean.
Matrix coverage: **A** (manual+current → allow, no rescue file),
**B** (stale HEAD → block, names the commit), **C** (stale fingerprint →
block, names the tree), **D** (design not synchronized → block), plus
missing-handoff, all-failures-at-once, mode resolution, subagent skip,
payload robustness, generated-region refresh, and a subprocess test
proving the file works when invoked exactly as the hook registers it.

**Reachability note.** `test_the_legacy_field_name_does_not_grant_a_skip`
asserts `is_subagent({"is_subagent": True})` is **False**. That is the
inverse of the legacy test, and it is the pin that would have caught the
original defect: the old suite asserted the skip using the same invented
field the production code read, so both agreed with each other and
neither agreed with Claude Code.

**Failure/edge cases exercised.** Malformed JSON payload, empty payload,
and a cwd outside any repository — none may crash and none may block
unrelated work.

**Commit boundary.** Tracked guard + its tests. Behaviour still
identical to the legacy guard; registration unchanged.

**Evidence.** `c5fe657c`. 42 passed, 1.12 s; ruff + format clean.

### C3 — fail-safe AUTO PreCompact + mechanical rescue snapshot

**Goal.** Automatic compaction must never deadlock on a stale handoff,
and what it leaves behind must be evidence rather than invented memory.

**Scope.** `tools/claude_hooks/rescue_snapshot.py`, the auto branches in
the guard, `tests/unit/tools/claude_hooks/test_auto_failsafe.py`.
NON-goals: any change to the manual path; SessionStart (C4).

**Implementation.**
- [x] `rescue_snapshot.render()/write()` — schema
      `siderius.context_rescue/1`, written to
      `.claude/context_rescue/latest_auto_compact.md`.
- [x] Three auto branches in the guard, covering every way the handoff
      can fail to be current: unreadable, malformed, and stale.
- [x] `_fail_safe()` returns ALLOW even when the snapshot write itself
      fails, reporting the failure on stderr. Trading one deadlock for
      another because a file could not be written would defeat the whole
      path.
- [x] The snapshot records the handoff's OWN recorded HEAD/fingerprint
      and PR identity verbatim, explicitly labelled unverified, so a
      resumed session can see what the stale handoff claimed without
      being told to believe it.

**Snapshot schema (mechanical facts only).** `schema`,
`generated_at_utc`, `trigger`, `session_id`, `transcript_path`,
`repository_root`, `branch`, `head_sha`, `working_fingerprint`,
`changed_file_count`; the handoff's verbatim `PROJECT / PR`,
`PRIMARY DESIGN DOC`, `BINDING DOCS`; the handoff's recorded HEAD and
fingerprint; the list of freshness failures; `git status --short`,
changed files vs HEAD, `diff --stat`, recent commits; and the fixed
recovery instruction. **No summary, no diagnosis, no next steps.**

**Validation.** **55 passed, 1.76 s**; ruff + format clean. Matrix
coverage: **E** (auto+current → allow, NO snapshot — a snapshot on a
healthy handoff would train the reader to ignore rescue files),
**F** (auto+stale → allow, snapshot carries real HEAD, fingerprint,
uncommitted filenames, session id, transcript path and the handoff's own
stale value), **G** (hygiene: no fabricated narrative sections, states
plainly that it is not memory, declares a schema version). Plus:
missing handoff, malformed handoff, snapshot-write failure, the
self-reference proof that writing a snapshot cannot invalidate the
handoff, and a divergence pin that manual still BLOCKS on the identical
state.

**Failure/edge cases exercised.** Handoff absent; handoff malformed;
`rescue_snapshot.write` raising `OSError`.

**Commit boundary.** Auto path + snapshot module + tests. Manual path
untouched; registration unchanged.

**Evidence.** `355aded5`. 55 passed, 1.76 s; ruff + format clean.

### C4 — dynamic SessionStart / resume injection

**Goal.** Resume the PR that is actually active, read from the handoff
at run time, with zero project literals in the hook.

**Scope.** `tools/claude_hooks/inject_session_memory.py`,
`context_state.section_body()`,
`tests/unit/tools/claude_hooks/test_session_start_injection.py`.

**Implementation.**
- [x] Three deterministic output shapes: **normal**, **recovery**,
      **cold**.
- [x] The `source` field (`startup`/`resume`/`clear`/`compact`) is read
      from the payload and reported. The audited implementation drained
      stdin and discarded it, so it could not tell a fresh startup from
      a post-compact resume.
- [x] Injected content: live repo state, the PR identity block, the
      validation verdict, and only three sections — `## Current
      Checkpoint`, `## Exact Next Actions`, `## Stop Conditions`. The
      rest of the handoff stays one `Read` away; the previous
      implementation dumped up to 24 000 characters of it into the
      window it was trying to protect.
- [x] CLOSED contexts get an explicit notice that the PR is history and
      that a new PR needs a fresh contract + a handoff initialised from
      the tracked template.
- [x] Cold start names the template and says "do not infer an active
      task from this message" — it must not invent work.

**PRECEDENCE RULE (frozen).** Recovery mode is entered when
`validate() != []` **AND** a rescue snapshot exists. It is therefore
**state-derived, not timestamp-derived**: once the handoff validates
clean, the incident the snapshot describes has been repaired and normal
mode is correct. A leftover rescue file can never pin future sessions in
emergency mode. Comparing file mtimes was rejected — it would make
resume behaviour depend on filesystem accidents rather than on
repository truth.

**Validation.** **90 passed, 2.66 s**; ruff + format clean. Matrix
coverage: **H** (dynamic identity + the three action sections),
**I** (stale + snapshot → banner naming the snapshot path),
**J** (clean handoff outranks an existing snapshot — the precedence
pin), **K** (missing and malformed handoff → generic guidance, no
crash, no historical fallback), **L** (repeated resumes report the same
PR and design), **M** (CLOSED → "new PR needs fresh kickoff", and ACTIVE
gets no such notice), **N** (the template names no specific PR),
**R** (six historical literals asserted absent from injected output AND
from every `.py`/`.md` file under `tools/claude_hooks/`).

**Commit boundary.** SessionStart + its helper + tests. Registration
still points at the legacy hooks.

**Evidence.** `fa943bcd`. 90 passed, 2.66 s; ruff + format clean.

### C5 — PR-scoped lifecycle support

**Goal.** Make "a new PR does not inherit the previous PR's context" a
mechanical fact rather than a discipline, without building a PR-management
system.

**Scope.** `context_state.initialize_handoff()`, the branch-mismatch check
in `validate()`, `tools/claude_hooks/init_pr_handoff.py`,
`tests/unit/tools/claude_hooks/test_pr_lifecycle.py`.

**Implementation.**
- [x] `initialize_handoff()` renders the canonical template with ONLY the
      PR identity filled in. Objective, checkpoints and next actions stay
      at their placeholders on purpose — pre-filling them would be the
      tooling fabricating semantic content, and inheriting them is the
      exact failure being prevented.
- [x] **Branch-mismatch check** — `validate()` reports when
      `IMPLEMENTATION BRANCH` names a branch other than the checkout's.
      This is the one carry-over failure nothing else could see: HEAD and
      fingerprint can both be perfectly current while the handoff
      describes a different PR entirely. Detached HEAD is exempt (normal
      during bisect/review, not evidence of carry-over).
- [x] `init_pr_handoff.py` — refuses to clobber an ACTIVE handoff, tells a
      CLOSED one that `--force` is appropriate, and refuses a
      `--design` path that does not exist (a handoff pointing at a
      non-existent authority is worse than none).
- [x] A CLOSED context still VALIDATES. The operator may need to compact
      while waiting for a merge; blocking then would be the same deadlock
      in a different costume.

**Validation.** **103 passed, 3.18 s**; ruff + format clean. Matrix **N**
(a second PR's handoff carries no trace of the first — name, design path,
branch or base), plus the branch-mismatch pin, the detached-HEAD
exemption, the four `init_pr_handoff` refusal/defaulting behaviours, and
CLOSED-context terminality.

**FINDING — the new check exposed a dishonest fixture.**

```text
Previous assumption:
  the shared handoff fixture was a faithful stand-in for a real handoff.

Audit / implementation evidence:
  adding the branch check turned 11 previously-green tests red at once.
  The fixture filled IMPLEMENTATION BRANCH with the generic "filled-in"
  placeholder while the fixture repo was on a real branch — so every
  fixture handoff was, by its own declaration, describing a different
  PR.

Corrected understanding:
  a handoff belongs to the branch it was written on; a fixture that does
  not record that is not modelling a handoff.

Implementation consequence:
  none in production — the check is correct and unchanged. The fixture
  now pins the branch to the checkout's.

Validation consequence:
  the 11 failures were the new check working on its first run, not a
  regression. Recorded because "many tests went red" is exactly the
  moment a weaker response would have been to relax the check.
```

**Failure/edge cases exercised.** Detached HEAD; CLOSED context;
non-existent design path; clobber refusal against both ACTIVE and CLOSED
handoffs. One test defect found and fixed (a test that did not create
`DESIGN.md` before invoking the init command — the command was right to
refuse).

**Commit boundary.** Lifecycle helpers + the branch check + tests.
Registration still legacy.
