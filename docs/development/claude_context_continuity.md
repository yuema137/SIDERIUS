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
matchers.

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
