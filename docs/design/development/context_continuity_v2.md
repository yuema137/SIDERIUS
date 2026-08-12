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
- [ ] **C1** tracked shared foundation + canonical template.
- [ ] **C2** strict MANUAL PreCompact path.
- [ ] **C3** fail-safe AUTO PreCompact + mechanical rescue snapshot.
- [ ] **C4** dynamic SessionStart / resume injection.
- [ ] **C5** PR-scoped lifecycle (init / continuation / closeout).
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
