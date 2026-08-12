"""Shared state for the PR-scoped Claude Code continuity hooks.

Context compaction is lossy in a way that matters for long autonomous
sessions: what survives is whatever the summariser judged salient, which
is not the same as the frozen policy, the audit findings that cost hours
to establish, or the exact working-tree state. This module is the single
tracked foundation under a three-part arrangement:

    main agent   writes the SEMANTIC handoff during normal work
    PreCompact   manual -> refuses to compact while that handoff is stale
                 auto   -> never blocks; writes mechanical rescue evidence
    SessionStart re-injects the ACTIVE PR's context and demands a re-audit

**The hooks never invent semantics.** They own exactly one region of the
handoff — the mechanically generated repository state — and validate the
rest. A hook that wrote its own summary would be the same failure as
trusting the compact summary: plausible text nobody verified.

The lifecycle principle this module enforces:

    CONTINUITY IS INTRA-PR.
    REPOSITORY DESIGN DOCUMENTS ARE INTER-PR MEMORY.

One implementation context belongs to exactly one PR. Compaction and
resume may happen many times inside that PR; the *next* PR starts from a
freshly initialised handoff rather than inheriting unfinished scratch
state. That is why the handoff carries PR identity and a context state,
and why a CLOSED context is never resumed as if it were active.

Design constraints that are not incidental:

- **Deterministic.** The fingerprint must be identical across repeated
  runs on an unchanged tree, or the guard blocks forever.
- **Bounded.** SessionStart stdout becomes the model's context, so output
  is capped and never includes full diffs, logs or file contents.
- **No secrets.** Environment values are never emitted.
- **Atomic.** Files are replaced via temp file + rename, so an
  interrupted hook cannot truncate the operator's handoff.
- **Standard library only.** These run before the project is importable.
- **Self-contained.** Everything the tracked hooks need — including the
  canonical template — resolves relative to this file, never through the
  gitignored ``.claude/`` directory.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Region markers. The hooks may rewrite ONLY the generated block.
FIRST_PRINCIPLES_BEGIN = "<!-- FIRST_PRINCIPLES_BEGIN -->"
FIRST_PRINCIPLES_END = "<!-- FIRST_PRINCIPLES_END -->"
SEMANTIC_BEGIN = "<!-- SEMANTIC_HANDOFF_BEGIN -->"
SEMANTIC_END = "<!-- SEMANTIC_HANDOFF_END -->"
GENERATED_BEGIN = "<!-- GENERATED_STATE_BEGIN -->"
GENERATED_END = "<!-- GENERATED_STATE_END -->"

MEMORY_BASENAME = "before_end_memory.md"

#: The canonical template lives BESIDE this module, not under the
#: gitignored ``.claude/``. Tracking the guard while leaving its template
#: ignored would ship a guard that blocks compaction on every fresh
#: checkout, because it treats an unreadable template as a hard failure.
TEMPLATE_DIRNAME = "templates"
TEMPLATE_BASENAME = "before_end_memory.template.md"

#: Emergency auto-compact evidence. Local runtime state, never tracked.
RESCUE_RELDIR = ".claude/context_rescue"
RESCUE_BASENAME = "latest_auto_compact.md"

#: Headings the semantic handoff must contain. Absence means the operator
#: (or the agent) has not actually written a handoff, only a stub.
REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Current Objective",
    "## Frozen Policy and Non-Negotiable Decisions",
    "## Completed Checkpoints",
    "## Current Checkpoint",
    "## Current Implementation State",
    "## Decisions Made and Why",
    "## Audits Performed and Evidence Found",
    "## Problems Encountered",
    "## Deviations from the Design",
    "## Validation Already Completed",
    "## Known Limitations and Deferred Follow-ups",
    "## Genuine Open Policy Questions",
    "## Exact Next Actions",
    "## Stop Conditions",
    "## Design-Document Synchronization",
)

# Machine-checkable freshness fields, ``Key: value`` on their own line.
FIELD_HEAD = "Handoff updated for HEAD"
FIELD_FINGERPRINT = "Handoff working-tree fingerprint"
FIELD_DESIGN_SYNCED = "Design document synchronized"
FIELD_DESIGN_REF = "Design sync reference"
FIELD_SAFE = "Safe to compact"

# PR-identity fields. These are what make a handoff belong to ONE PR, and
# what stop a finished PR's context from being resumed as the next one's.
FIELD_PROJECT = "PROJECT / PR"
FIELD_PRIMARY_DESIGN = "PRIMARY DESIGN DOC"
FIELD_CONTEXT_STATE = "CONTEXT STATE"
# Recorded when known, but never required: a handoff must stay cheap to
# refresh, so only the fields that carry correctness are mandatory.
FIELD_BINDING_DOCS = "RELATED / BINDING DOCS"
FIELD_BASE = "IMPLEMENTATION BASE"
FIELD_BRANCH = "IMPLEMENTATION BRANCH"

REQUIRED_FIELDS: tuple[str, ...] = (
    FIELD_HEAD,
    FIELD_FINGERPRINT,
    FIELD_DESIGN_SYNCED,
    FIELD_DESIGN_REF,
    FIELD_SAFE,
    FIELD_PROJECT,
    FIELD_PRIMARY_DESIGN,
    FIELD_CONTEXT_STATE,
)

STATE_ACTIVE = "ACTIVE"
STATE_CLOSED = "CLOSED"

#: Values that mean "not actually filled in". Checked case-insensitively
#: against required field values only — prose elsewhere may legitimately
#: discuss a TODO.
PLACEHOLDERS: tuple[str, ...] = ("todo", "tbd", "unknown", "fill this in", "n/a", "xxx", "")

#: Untracked files larger than this contribute path+size rather than
#: content, so a stray large artifact cannot make the hooks slow or
#: memory-hungry. Deterministic either way.
MAX_HASHED_BYTES = 2 * 1024 * 1024

#: Hard cap on injected context, so SessionStart cannot flood the window.
MAX_INJECTED_CHARS = 24_000


class ContinuityError(RuntimeError):
    """A problem with the handoff or the repository it describes."""


# --------------------------------------------------------------------------
# Repository truth
# --------------------------------------------------------------------------


def repo_root() -> Path:
    """The repository root, from the environment rather than the cwd.

    ``${CLAUDE_PROJECT_DIR}`` is preferred because a hook's working
    directory is not guaranteed to be the project; ``git rev-parse`` is
    the fallback. Never trust the ambient cwd.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        candidate = Path(env).resolve()
        if (candidate / ".git").exists():
            return candidate
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip()).resolve()
    except (OSError, subprocess.SubprocessError):
        pass
    raise ContinuityError("cannot determine the repository root")


def _git(root: Path, *args: str, timeout: int = 30) -> str:
    """Run git with a fixed argv — never a shell string, so nothing from
    a hook's input can be interpreted as a command."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContinuityError(f"git {' '.join(args)} failed: {exc}") from exc
    return out.stdout


def head_sha(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def branch_name(root: Path) -> str:
    return _git(root, "branch", "--show-current").strip() or "(detached)"


def _is_self_referential(rel: str) -> bool:
    """Paths the continuity system itself owns.

    **Load-bearing, not tidiness.** The handoff records the fingerprint of
    the tree; if the handoff counted toward that fingerprint, writing it
    would immediately invalidate it and the guard could never be
    satisfied. Agent runtime state under ``.claude/`` — including the
    emergency rescue snapshots this system writes — is excluded for the
    same reason.

    What is deliberately NOT excluded: the tracked implementation under
    ``tools/claude_hooks/``. That is ordinary source. Hiding it would let
    the continuity mechanism change its own behaviour without ever
    invalidating a handoff, which is exactly the blindness this system
    exists to remove.

    In this repository ``.claude/`` is gitignored and the handoff is in
    ``.git/info/exclude``, so neither would be listed anyway — but the
    exclusion must live in the algorithm, because a checkout without
    those rules would otherwise deadlock.
    """
    normalised = rel.replace("\\", "/")
    return normalised == MEMORY_BASENAME or normalised.startswith(".claude/")


def working_tree_fingerprint(root: Path) -> str:
    """A deterministic digest of everything not yet committed.

    **Algorithm**, fixed and documented because the guard compares against
    a value the agent recorded earlier:

    1. ``git diff`` — tracked, unstaged.
    2. ``git diff --cached`` — staged.
    3. every untracked, non-ignored path from
       ``git ls-files --others --exclude-standard``, sorted bytewise; each
       contributes ``path\\0<sha256 of contents>`` when at or below
       :data:`MAX_HASHED_BYTES`, otherwise ``path\\0size:<n>``.

    The three parts are joined with a domain separator and hashed once.
    Ignored paths never contribute, so data directories and generated
    artifacts cannot perturb it, and :func:`_is_self_referential` paths
    are skipped so the continuity system cannot invalidate its own record.

    A clean tree yields the digest of three empty parts — a stable,
    well-defined value rather than a special case. It is therefore the
    SAME digest at every commit: HEAD comparison, not the fingerprint, is
    what distinguishes one clean checkout from another.
    """
    unstaged = _git(root, "diff")
    staged = _git(root, "diff", "--cached")

    untracked_lines: list[str] = []
    listing = _git(root, "ls-files", "--others", "--exclude-standard")
    for rel in sorted(line for line in listing.splitlines() if line.strip()):
        if _is_self_referential(rel):
            continue
        path = root / rel
        try:
            if not path.is_file() or path.is_symlink():
                continue
            size = path.stat().st_size
            if size > MAX_HASHED_BYTES:
                untracked_lines.append(f"{rel}\0size:{size}")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            untracked_lines.append(f"{rel}\0{digest}")
        except OSError:
            # Unreadable or vanished between listing and stat. Record the
            # fact deterministically rather than crashing the hook.
            untracked_lines.append(f"{rel}\0unreadable")

    payload = (
        b"unstaged\x00"
        + unstaged.encode("utf-8", "replace")
        + b"\x00staged\x00"
        + staged.encode("utf-8", "replace")
        + b"\x00untracked\x00"
        + "\n".join(untracked_lines).encode("utf-8", "replace")
    )
    return hashlib.sha256(payload).hexdigest()


# --------------------------------------------------------------------------
# Handoff parsing
# --------------------------------------------------------------------------


def _section(text: str, begin: str, end: str) -> str:
    """The content strictly between two markers."""
    try:
        start = text.index(begin) + len(begin)
        stop = text.index(end)
    except ValueError as exc:
        raise ContinuityError(f"missing marker {begin} / {end}") from exc
    if stop < start:
        raise ContinuityError(f"markers out of order: {begin} appears after {end}")
    return text[start:stop]


def first_principles(text: str) -> str:
    return _section(text, FIRST_PRINCIPLES_BEGIN, FIRST_PRINCIPLES_END)


def semantic_handoff(text: str) -> str:
    return _section(text, SEMANTIC_BEGIN, SEMANTIC_END)


def _normalise(block: str) -> str:
    """Whitespace-insensitive comparison, so reformatting the fixed block
    is tolerated while a semantic edit is not."""
    return "\n".join(line.rstrip() for line in block.strip().splitlines() if line.strip())


def template_path() -> Path:
    """The canonical template, resolved from THIS module's location.

    Never a ``.claude/`` path: the template is part of the tracked logic's
    contract, and a fresh checkout must receive both together.
    """
    return Path(__file__).resolve().parent / TEMPLATE_DIRNAME / TEMPLATE_BASENAME


def first_principles_match_template(text: str) -> tuple[bool, str]:
    """Compare the fixed block against the canonical template.

    Deliberately not a hardcoded hash: a hash gives no diagnostic and has
    to be regenerated whenever the wording is legitimately improved. The
    template is the source of truth, and this reports WHAT diverged.
    """
    path = template_path()
    if not path.is_file():
        return False, f"canonical template missing at {path}"
    try:
        template_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"cannot read the canonical template: {exc}"
    try:
        expected = _normalise(first_principles(template_text))
    except ContinuityError as exc:
        return False, f"the template itself is malformed: {exc}"
    actual = _normalise(first_principles(text))
    if actual == expected:
        return True, ""
    exp_lines, act_lines = expected.splitlines(), actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines, strict=False), start=1):
        if e != a:
            return False, f"first-principles line {i} diverges from the template: {a!r} != {e!r}"
    return False, (
        f"first-principles block length differs from the template "
        f"({len(act_lines)} vs {len(exp_lines)} lines)"
    )


_FIELD_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _field_re(key: str) -> re.Pattern[str]:
    pattern = _FIELD_RE_CACHE.get(key)
    if pattern is None:
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", re.MULTILINE)
        _FIELD_RE_CACHE[key] = pattern
    return pattern


def read_field(text: str, key: str) -> str | None:
    """Value of a ``Key: value`` line, searched only in the semantic block.

    Anchored per line so prose mentioning the key elsewhere cannot satisfy
    the guard.
    """
    match = _field_re(key).search(text)
    return match.group(1) if match else None


def count_field(text: str, key: str) -> int:
    """How many times a field is declared.

    :func:`read_field` returns the FIRST match, so a duplicated key takes
    its first value silently. That is how a stale value survives an edit
    that "fixed" the second copy — worth naming rather than tolerating.
    """
    return len(_field_re(key).findall(text))


def section_body(handoff: str, heading: str) -> str:
    """The text under a ``## Heading``, up to the next heading of any level.

    Used to inject the few sections a resumed session actually needs
    (checkpoint, next actions, stop conditions) instead of the whole
    file. Returns an empty string when the heading is absent — the caller
    decides whether that is worth reporting.
    """
    marker = f"\n{heading}\n"
    padded = "\n" + handoff
    index = padded.find(marker)
    if index == -1:
        return ""
    rest = padded[index + len(marker) :]
    lines: list[str] = []
    for line in rest.splitlines():
        if line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def is_placeholder(value: str | None) -> bool:
    return value is None or value.strip().lower().strip("`<>*") in PLACEHOLDERS


def context_state(text: str) -> str | None:
    """``ACTIVE`` / ``CLOSED``, or None when unreadable.

    Tolerant of an operator suffix — ``CLOSED / AWAITING OPERATOR ACTION``
    is the documented closeout wording and must classify as CLOSED.
    """
    raw = read_field(text, FIELD_CONTEXT_STATE)
    if raw is None:
        return None
    head = raw.strip().strip("`*").split("/")[0].strip().upper()
    if head.startswith(STATE_ACTIVE):
        return STATE_ACTIVE
    if head.startswith(STATE_CLOSED):
        return STATE_CLOSED
    return None


@dataclass(frozen=True)
class PRIdentity:
    """Which PR a handoff belongs to. The unit of continuity."""

    project: str | None
    primary_design: str | None
    binding_docs: str | None
    base: str | None
    branch: str | None
    state: str | None

    @property
    def is_active(self) -> bool:
        return self.state == STATE_ACTIVE

    @property
    def is_closed(self) -> bool:
        return self.state == STATE_CLOSED


def read_pr_identity(handoff: str) -> PRIdentity:
    def _get(key: str) -> str | None:
        value = read_field(handoff, key)
        return None if is_placeholder(value) else value

    return PRIdentity(
        project=_get(FIELD_PROJECT),
        primary_design=_get(FIELD_PRIMARY_DESIGN),
        binding_docs=_get(FIELD_BINDING_DOCS),
        base=_get(FIELD_BASE),
        branch=_get(FIELD_BRANCH),
        state=context_state(handoff),
    )


# --------------------------------------------------------------------------
# Generated region
# --------------------------------------------------------------------------


def render_generated_state(root: Path, *, session_id: str = "", trigger: str = "") -> str:
    """The mechanically generated block. Bounded and deterministic.

    Timestamp and session id are the only non-deterministic parts, and
    they are excluded from every freshness comparison.
    """
    sha = head_sha(root)
    fingerprint = working_tree_fingerprint(root)
    status_lines = [line for line in _git(root, "status", "--short").splitlines() if line.strip()]
    diff_check = _git(root, "diff", "--check").strip()

    lines: list[str] = [
        "",
        "## Generated Repository State",
        "",
        "> Written by `tools/claude_hooks/precompact_memory_guard.py`. Do not",
        "> hand-edit: it is regenerated on every compaction attempt.",
        "",
        "```text",
        f"generated_at_utc     {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"session_id           {session_id or '(not supplied)'}",
        f"compact_trigger      {trigger or '(not supplied)'}",
        f"repository_root      {root}",
        f"branch               {branch_name(root)}",
        f"head_sha             {sha}",
        f"working_fingerprint  {fingerprint}",
        f"changed_file_count   {len(status_lines)}",
        f"diff_check           {'clean' if not diff_check else 'WHITESPACE ISSUES'}",
        "```",
        "",
        "### git status --short",
        "",
        "```text",
    ]
    lines += status_lines[:40] or ["(clean)"]
    if len(status_lines) > 40:
        lines.append(f"... and {len(status_lines) - 40} more")
    lines += ["```", "", "### diff --stat (unstaged / staged)", "", "```text"]

    unstaged_stat = [ln for ln in _git(root, "diff", "--stat").splitlines() if ln.strip()]
    staged_stat = [ln for ln in _git(root, "diff", "--cached", "--stat").splitlines() if ln.strip()]
    lines.append("unstaged:")
    lines += [f"  {ln}" for ln in unstaged_stat[-12:]] or ["  (none)"]
    lines.append("staged:")
    lines += [f"  {ln}" for ln in staged_stat[-12:]] or ["  (none)"]
    lines += ["```", "", "### recent commits", "", "```text"]
    lines += [
        ln for ln in _git(root, "log", "--oneline", "--decorate", "-15").splitlines() if ln.strip()
    ]
    lines += ["```", ""]
    return "\n".join(lines)


def replace_generated_state(text: str, generated: str) -> str:
    """Swap ONLY the generated region, leaving every other byte untouched."""
    try:
        start = text.index(GENERATED_BEGIN) + len(GENERATED_BEGIN)
        stop = text.index(GENERATED_END)
    except ValueError as exc:
        raise ContinuityError("missing GENERATED_STATE markers") from exc
    if stop < start:
        raise ContinuityError("GENERATED_STATE markers are out of order")
    return text[:start] + "\n" + generated.strip("\n") + "\n" + text[stop:]


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def atomic_write(path: Path, content: str) -> None:
    """Replace via temp file + rename, so an interrupted hook cannot
    truncate a handoff that took real work to write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".memtmp_", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def memory_path(root: Path) -> Path:
    return root / MEMORY_BASENAME


def rescue_path(root: Path) -> Path:
    """Where automatic compaction leaves mechanical recovery evidence."""
    return root / RESCUE_RELDIR / RESCUE_BASENAME


def load_memory(root: Path) -> str:
    path = memory_path(root)
    if not path.is_file():
        raise ContinuityError(
            f"{MEMORY_BASENAME} does not exist. Copy {template_path()} to "
            f"{MEMORY_BASENAME} and complete the semantic handoff for the "
            f"CURRENT PR."
        )
    if path.is_symlink():
        raise ContinuityError(f"{MEMORY_BASENAME} is a symlink; refusing to follow it")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContinuityError(f"cannot read {MEMORY_BASENAME}: {exc}") from exc


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate(root: Path, text: str) -> list[str]:
    """Every reason the handoff is not fit to survive compaction.

    Returns ALL failures rather than the first, so one retry can fix
    everything — a guard that reports one problem at a time turns into an
    infinite block-fix-block loop.

    This function decides nothing about blocking. It reports state; the
    manual path blocks on it and the automatic path records it in the
    rescue snapshot and compacts anyway.
    """
    problems: list[str] = []

    for begin, end, label in (
        (FIRST_PRINCIPLES_BEGIN, FIRST_PRINCIPLES_END, "first-principles"),
        (SEMANTIC_BEGIN, SEMANTIC_END, "semantic-handoff"),
        (GENERATED_BEGIN, GENERATED_END, "generated-state"),
    ):
        if begin not in text or end not in text:
            problems.append(f"missing {label} markers ({begin} / {end})")
    if problems:
        return problems  # nothing else can be checked reliably

    ok, detail = first_principles_match_template(text)
    if not ok:
        problems.append(
            f"the fixed first-principles block was modified — {detail}. "
            f"Restore it from {template_path()}."
        )

    handoff = semantic_handoff(text)
    missing = [h for h in REQUIRED_HEADINGS if h not in handoff]
    if missing:
        problems.append(f"semantic handoff is missing required headings: {', '.join(missing)}")

    for key in REQUIRED_FIELDS:
        value = read_field(handoff, key)
        if value is None:
            problems.append(f"missing required field '{key}:' in the semantic handoff")
        elif is_placeholder(value):
            problems.append(f"field '{key}' is an unresolved placeholder ({value!r})")
        elif count_field(handoff, key) > 1:
            problems.append(
                f"field '{key}' is declared {count_field(handoff, key)} times; only the "
                f"first is read, so a later correction would be silently ignored"
            )

    state = context_state(handoff)
    if state is None and read_field(handoff, FIELD_CONTEXT_STATE) is not None:
        problems.append(
            f"'{FIELD_CONTEXT_STATE}' is not recognisable as {STATE_ACTIVE} or {STATE_CLOSED}"
        )

    actual_head = head_sha(root)
    recorded_head = (read_field(handoff, FIELD_HEAD) or "").strip().strip("`")
    if recorded_head and not is_placeholder(recorded_head) and recorded_head != actual_head:
        problems.append(
            f"'{FIELD_HEAD}' is {recorded_head[:12]}… but HEAD is {actual_head[:12]}… — "
            f"the handoff describes a different commit"
        )

    actual_fp = working_tree_fingerprint(root)
    recorded_fp = (read_field(handoff, FIELD_FINGERPRINT) or "").strip().strip("`")
    if recorded_fp and not is_placeholder(recorded_fp) and recorded_fp != actual_fp:
        problems.append(
            f"'{FIELD_FINGERPRINT}' is {recorded_fp[:12]}… but the tree is "
            f"{actual_fp[:12]}… — uncommitted work changed since the handoff was written"
        )

    design = read_field(handoff, FIELD_PRIMARY_DESIGN)
    if design and not is_placeholder(design):
        # The design doc is the semantic authority. A handoff naming one
        # that does not exist points the resumed session at nothing.
        candidate = design.split()[0].strip("`,;")
        if candidate.endswith(".md") and not (root / candidate).is_file():
            problems.append(
                f"'{FIELD_PRIMARY_DESIGN}' names {candidate!r}, which does not exist in the "
                f"repository — the resumed session would have no semantic authority to read"
            )

    synced = (read_field(handoff, FIELD_DESIGN_SYNCED) or "").strip().lower()
    if synced not in {"yes", "true"}:
        problems.append(
            f"'{FIELD_DESIGN_SYNCED}' is {synced!r}. Update the PRIMARY DESIGN DOC and its "
            f"implementation ledger, then set it to 'yes'."
        )

    safe = (read_field(handoff, FIELD_SAFE) or "").strip().lower()
    if safe not in {"yes", "true"}:
        problems.append(
            f"'{FIELD_SAFE}' is {safe!r}. Set it to 'yes' only once the handoff above is "
            f"complete and accurate."
        )

    return problems
