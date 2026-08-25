# Claude Code context continuity

How a long implementation session survives compaction, and what you have
to do to keep that true.

The implementation lives in `tools/claude_hooks/` and is tested by
`tests/unit/tools/claude_hooks/` in normal CI. Only the *registration*
is per-machine, because it points at your own checkout.

---

## The one principle

> **Continuity is intra-PR. Repository design documents are inter-PR
> memory.**

A Claude implementation context belongs to exactly one pull request.
Inside that PR the context may compact and resume as often as it needs
to. The *next* PR starts from a fresh handoff — it never inherits the
previous PR's unfinished notes. What the previous PR did is read from
merged repository and design state.

```text
new PR authorized
  -> fresh Implementation Working Rules contract
  -> fresh handoff initialised from the canonical template
  -> implementation
  -> zero or more compact/resume cycles   (SAME PR)
  -> READY FOR OPERATOR REVIEW
  -> CONTEXT STATE: CLOSED / AWAITING OPERATOR ACTION
  -> operator merge
  -> post-merge design/status synchronization
  -> NEXT PR starts a NEW context
```

---

## What you get, precisely

- The semantic handoff is refreshed at normal implementation milestones —
  **by the agent, as part of its work.** No hook writes it.
- A **manual** `/compact` refuses to run over a stale handoff, naming
  every failing condition.
- An **automatic** compaction never deadlocks. If the handoff is stale it
  writes a mechanical rescue snapshot and lets compaction proceed.
- **Resume** points the session at the PR that is actually active, read
  from the handoff at run time.
- The resumed agent is told to audit repository truth before editing.
- **Stop** refuses to end the turn while the handoff records work that is
  active, incomplete and not waiting on you.

### What you do NOT get

**There is no "compacts at 95% context" trigger, and this system does not
build one.** Claude Code 2.1.228 exposes `PreToolUse`, `PostToolUse`,
`UserPromptSubmit`, `Notification`, `Stop`, `SubagentStop`, `PreCompact`,
`PostCompact`, `SessionStart` and `SessionEnd` — and no context-percentage
event of any kind. Anything claiming otherwise would be polling a number
the hook surface does not provide.

Keeping the handoff current is therefore the agent's continuous job. The
automatic-compaction fail-safe is a **last resort**, not the normal
synchronization mechanism.

---

## Installation (per machine, ~1 minute)

`.claude/settings.local.json` is gitignored and yours alone. Register the
tracked scripts in it:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "matcher": "manual",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/tools/claude_hooks/precompact_memory_guard.py --mode manual",
            "timeout": 60
          }
        ]
      },
      {
        "matcher": "auto",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/tools/claude_hooks/precompact_memory_guard.py --mode auto",
            "timeout": 60
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/tools/claude_hooks/inject_session_memory.py",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

Repeat the `SessionStart` block for the `resume`, `compact` and `clear`
matchers, and register the Stop guard alongside them:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/tools/claude_hooks/stop_continuation_guard.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

`--mode` duplicates what the matcher already routes. That is deliberate:
it keeps the scripts runnable — and testable — without Claude Code, and
it means a future change to the payload cannot silently flip the strict
path into the fail-safe one.

### Verify the installation

```bash
./.venv/bin/python tools/claude_hooks/precompact_memory_guard.py --check
```

Exit 0 with "complete and current" means the guard can see your handoff
and your repository. Exit 2 prints every condition that is failing.

---

## Starting a new PR

Do **not** edit the previous PR's handoff.

```bash
./.venv/bin/python tools/claude_hooks/init_pr_handoff.py \
    --project "Widget refactor (PR 42)" \
    --design  docs/design/development/widget_refactor.md
```

It refuses to overwrite a handoff whose context is still `ACTIVE` — close
that PR first (set `CONTEXT STATE: CLOSED / AWAITING OPERATOR ACTION`),
then re-run with `--force`.

Only the PR identity is filled in. The objective, checkpoints and next
actions are yours to write: inheriting someone else's is the failure this
command exists to prevent.

---

## Keeping the handoff current

Refresh `before_end_memory.md`:

- after every semantic milestone (typically: every semantic commit);
- whenever the active checkpoint materially changes;
- after any material audit finding, deviation or unexpected failure;
- before a manual compact, a long test run, a Gate, or a branch change.

**Aim for no more than one semantic milestone stale.**

The three freshness fields are mechanical — read them from the repository
rather than remembering them:

```bash
./.venv/bin/python -c "
from tools.claude_hooks import context_state as cs
r = cs.repo_root()
print('HEAD       ', cs.head_sha(r))
print('fingerprint', cs.working_tree_fingerprint(r))"
```

### Why freshness is state-derived

Correctness never depends on anything having observed a `git commit`. It
is a comparison between the repository as it is now and what the handoff
recorded:

```text
current HEAD                  vs  handoff HEAD
current working-tree digest   vs  handoff fingerprint
current branch                vs  handoff IMPLEMENTATION BRANCH
```

That last one is the lifecycle guard: a handoff naming a different branch
is the previous PR's context still sitting in the active slot.

Two properties of the fingerprint are worth knowing:

- **A clean tree always produces the same digest**, at every commit. It is
  the hash of three empty parts. HEAD comparison is what distinguishes one
  clean checkout from another — the fingerprint only describes
  *uncommitted* work.
- **Edits under `tools/claude_hooks/` DO change it**, because that is
  ordinary tracked source. Only `before_end_memory.md` and `.claude/` are
  excluded, and only so the system cannot invalidate its own bookkeeping.

---

## The Stop guard: not stopping at an ordinary milestone

The failure it removes, observed repeatedly through Step 03: an ACTIVE
PR, an incomplete checkpoint, explicit next actions, nothing outstanding
from the operator — and the turn ends anyway with *"Next: Checkpoint
C…"*, so the operator has to type **continue**. Autonomous execution
that pauses at every milestone is not autonomous execution.

The guard reads recorded state and nothing else:

```text
CONTEXT STATE: ACTIVE
+ this checkout is on the handoff's IMPLEMENTATION BRANCH
+ '## Exact Next Actions' lists something
+ 'Operator input required' is not yes
    -> BLOCK, quoting those next actions verbatim

anything else                                   -> ALLOW
```

It never authors semantics. The blocking message is one fixed sentence
plus the agent's own recorded next actions; deciding what to do next is
still the agent's job, from the handoff and the design document.

### Handing control back

Three ways, all of them recorded state rather than prose:

| Situation | What to write |
|---|---|
| PR reached its stop condition | `CONTEXT STATE: CLOSED / AWAITING OPERATOR ACTION` |
| Genuine mid-PR operator decision | `Operator input required: yes` |
| Nothing left to do | `## Exact Next Actions` → `NONE` |

`Operator input required` is the only one that releases control without
closing the context. Set it *before* asking the question, and back to
`no` once the answer lands — a stale `yes` silently disables the guard.

### Why it cannot deadlock

Three independent backstops, in order of who owns them:

1. **Allow is the fail-safe direction.** Missing, malformed, truncated,
   uninterpretable or another PR's handoff — every one of them allows
   the stop. The guard blocks only on a state it fully understood.
2. **A block requires progress.** Each block records the HEAD and
   working-tree fingerprint it happened at, in
   `.claude/continuity/last_stop_block.json` (gitignored). An identical
   state next time means the previous continuation changed nothing, and
   the stop is allowed. A continuation that does no work can therefore
   never loop.
3. **Claude Code's own cap.** Consecutive Stop blocks are capped at 8
   (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`), independently of anything here.

Claude Code's guidance is to return success whenever `stop_hook_active`
is true, which would limit the guard to one block per session. Backstop
2 is strictly stronger — it permits further blocks only after real
repository change — so the guard uses that instead, with the built-in
cap underneath it.

---

## When automatic compaction happens over a stale handoff

You get `.claude/context_rescue/latest_auto_compact.md` (gitignored), and
the next session opens in **AUTO-COMPACT RECOVERY MODE**.

The snapshot contains only what a shell process can know for certain:
schema version, timestamp, session id, transcript path, branch, HEAD,
fingerprint, `git status`, changed files, `diff --stat`, recent commits,
the handoff's own recorded HEAD/fingerprint/PR identity copied verbatim
and labelled unverified, and the list of freshness failures.

**It contains no summary, no diagnosis and no next steps** — a script
cannot author semantic memory, and text that looks like memory but was
generated mechanically is the exact failure the whole system exists to
prevent.

Recovery mode ends by itself. Precedence is state-derived: once the
handoff validates clean again, the incident the snapshot describes has
been repaired and resume returns to normal. A leftover rescue file can
never pin future sessions in emergency mode.

---

## Troubleshooting

**"canonical template missing"** — the guard resolves its template from
`tools/claude_hooks/templates/`. If this fires, your checkout is
incomplete; it is not something to work around by putting a template
under `.claude/`.

**"this handoff belongs to a different PR"** — you are on a new branch
with the old PR's handoff still active. Close that context and run
`init_pr_handoff.py`.

**"field X is declared 2 times"** — a field is read from its FIRST
occurrence, so a second copy makes later corrections silently ineffective.
Delete the duplicate.

**A full-suite run reddens `test_preflight_all_invariants`** — that guard
requires production untouched at launch and does not allowlist
uncommitted `tools/`. Commit your checkpoint, then run the full suite.
Do not widen the allowlist.

**The guard blocks and you disagree** — read the conditions. If the
handoff genuinely is current and the guard is wrong, that is a bug in
`tools/claude_hooks/`; fix it there with a test, never by loosening the
freshness fields to values you have not verified.

---

## Known limitation: a PARALLEL session is blocked by the implementation session's handoff

**Observed 2026-08-23, Step 12 (recorded, NOT fixed — see the ruling at the
end of this section).** A planning / design / audit session running in a
SEPARATE worktree, alongside a live implementation session, is blocked at
every turn-end and handed **the implementation session's** next actions.

### What happens

```text
/home/<user>/SIDERIUS                  main checkout — implementation session,
                                       CONTEXT STATE: ACTIVE, next actions listed
/home/<user>/siderius-<topic>-planning separate worktree — planning session,
                                       different branch, its own unrelated work
```

The planning session finishes its work and tries to end the turn. The guard
blocks it and quotes the implementation session's checklist.

### Why — and note the branch check is not the bug

The guard's branch condition is real, but `stop_continuation_guard.main()`
does:

```python
root = repo_root()          # resolves to CLAUDE_PROJECT_DIR — the MAIN checkout, always
decision, ... = evaluate(root)
```

so `branch_name(root)`, `head_sha(root)` and the handoff all come from
whatever occupies the **main checkout**, regardless of which worktree the
session is actually working in. From the guard's viewpoint the repository has
exactly one current checkout, and that checkout is ACTIVE with next actions
pending. A session in another worktree is invisible to it.

### What is actually blocked

**Only the stop.** No tool call is prevented: edits, commits and subagents in
the parallel session all execute normally. The cost is extra turns, not lost
or corrupted work.

### What a blocked session MUST NOT do

1. **Do not execute the quoted next actions.** They belong to another
   session, in another worktree, which very likely has uncommitted changes
   there. The message is imperative ("Continue with the recorded next
   actions") and looks authoritative — that is exactly the trap.
2. **Do not write `before_end_memory.md`** to take the guard's escape clause.
   That file is the *implementation* session's crash-recovery handoff;
   marking it `Operator input required: yes` corrupts the state of a session
   that is running normally.

Instead: verify from git which session owns which worktree and branch, say so
plainly, deliver the parallel session's own work, and let the operator decide.

**The real risk is a FRESH session, not an informed one.** A session without
this history reads a confident, specific checklist and may simply do it — in
the wrong worktree, or on top of another session's uncommitted work.

### Operator ruling, 2026-08-23: RECORD, DO NOT FIX

> The main implementation must not be put at risk to remove an annoyance.

The guard is **left exactly as it is**. This section is the mitigation. The
cheapest workaround while a parallel session is running is to close it rather
than let it end its turn.

**If it is ever fixed, it needs evidence first, not a patch.** Two candidate
designs were considered and **neither is validated**:

* resolve the root from the *calling* worktree (`git rev-parse
  --show-toplevel`) instead of `repo_root()` — depends on the Stop event
  carrying a `cwd`, or on the harness launching the hook inside the session's
  worktree. **Neither is confirmed**; every hook in this repository reads only
  `session_id` and `source`, so there is no local precedent.
* record in the handoff the `session_id` that authored it and allow the stop
  when the event's `session_id` differs — needs no worktree topology at all,
  but must not lose protection when a session resumes under a new id (fall
  back to the branch check for that case).

**Dump one real Stop event and read its fields before choosing.** Any change
here lands with a test, on a checkout that is not hosting a live
implementation session.
