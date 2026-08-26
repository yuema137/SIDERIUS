"""Restore / process-provenance harness — Step 12 / PR-12e, workstream C.

**What this exists to answer.** `G-12e` is a 2x1 track rather than 1x1 for one
reason: the graduation claim includes *"iteration 2 ran in a genuinely FRESH
process and consumed iteration 1's committed state"*. The frozen restore
contract (design §K) states the standard the evidence must meet::

    the evidence records process provenance -- PIDs or equivalent process
    boundaries -- proving the second iteration is not a continuation of the
    first's interpreter. The CLI's iteration counter is not evidence.

Nothing in the repository met that standard before this module.
``scripts/step12_pr12a_gate2_evaluate.py::check_a1`` infers the restart
*circumstantially* ("iteration 2 produced its own per-model lock, therefore a
second process ran"), and no persisted artifact carries the producing process's
identity -- so a single long-lived interpreter that wrote both iterations is
indistinguishable from a real restart. On the unit side,
``tests/unit/workflows/test_step10_p56_c4_resume_equality.py`` makes **two
in-process ``run_workflow`` calls** while its docstring claims a defect class
that "appears only across a process boundary". Both are honest about what they
do; neither is a process-boundary witness.

**The discriminator.** :attr:`ProcessIdentity.interpreter_nonce` is generated
once per *interpreter* and stashed in ``sys.modules`` under a fixed key, so:

* a fresh ``python`` process gets a fresh nonce (fresh ``sys.modules``);
* re-importing this module -- under any name, in any package -- returns the
  SAME nonce, so an in-process "restart" cannot manufacture a fresh one;
* a ``fork``ed child inherits ``sys.modules`` and therefore the nonce, and is
  correctly reported as a continuation of its parent's interpreter, which it
  is -- it carries the parent's entire in-memory state.

That last property is why the nonce is decisive over the ``(boot_id, pid,
start_ticks)`` triple rather than merely additional to it: a fork has a
different pid and a different start time while being exactly the continuation
§K forbids.

**Scope, stated honestly.** This module is evidence *machinery*. It proves
nothing about a real chain on its own. What it makes possible is that
`G-12e`'s evidence set can answer the §K questions from artifacts instead of
from a CLI flag. The final restore property is `G-12e`'s and `G-12e` has not
run.

Public API (workstream B consumes this read-only; see design §G.3):

* :class:`ProcessIdentity`, :func:`same_interpreter`, :func:`assert_fresh_process`
* :func:`record_iteration_process`, :func:`read_process_ledger`, :func:`provenance_path`
* :class:`RestoreEvidence`, :func:`read_restore_evidence`
* :class:`CheckResult`, :class:`RestoreVerdict`, :func:`evaluate_restore_contract`
* :func:`main` -- ``python -m tests.helpers.step12_pr12e_restore_harness``
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import sys
import types
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Production imports are DEFERRED into the reader functions below, not taken at
# module scope. The recorder half of this module runs inside a real Gate
# iteration's own interpreter (see `step12_pr12e_gate_iteration.py`), and an
# evidence recorder must not import a slice of production before the workload
# does — that is a side effect the evidence would then be describing.
# `core.resume` and `core.run_invariants` are needed only when READING a
# finished workspace, which happens in a separate, ordinary process.

__all__ = [
    "PACKAGE_ROOT_ENV",
    "PROVENANCE_BASENAME",
    "CheckOutcome",
    "CheckResult",
    "IterationEvidence",
    "ProcessIdentity",
    "ProcessLedgerEntry",
    "RestoreEvidence",
    "RestoreEvidenceError",
    "RestoreVerdict",
    "assert_fresh_process",
    "evaluate_restore_contract",
    "external_package_manifest",
    "external_package_root",
    "main",
    "provenance_path",
    "read_process_ledger",
    "read_restore_evidence",
    "record_iteration_process",
    "same_interpreter",
]


class RestoreEvidenceError(RuntimeError):
    """The restore evidence contradicts §K, or cannot be read at all."""


# ---------------------------------------------------------------------------
# Where the out-of-tree package is — supplied, never guessed
# ---------------------------------------------------------------------------

#: Environment variable naming workstream A's package root.
#:
#: The package lives OUTSIDE the repository by construction (design §G.2), so
#: nothing in the checkout may name its location: a hardcoded absolute path
#: would be the CLAUDE.md portability defect, and a "conventional" sibling
#: directory would be the same defect wearing a relative path. The operator
#: points at it; absent, callers skip and SAY they skipped.
#:
#: **The spelling is workstream B's** (``test_step12_pr12e_census.py``), which
#: owns the identifier-extraction helper under the §G.3 partition. Two names
#: for one concept would be worse than a duplicated function: an operator who
#: set only one would watch half the Gate's evidence skip silently.
#:
#: INTEGRATION ACTION: at the ⛔I checkpoint this reader and B's
#: ``package_root_from_env`` collapse onto ONE authority — B's, promoted out of
#: the guardrail test module so a helper does not import a test.
PACKAGE_ROOT_ENV = "SIDERIUS_12E_PACKAGE_ROOT"


def external_package_root() -> pathlib.Path | None:
    """The configured package root, or ``None`` when unconfigured/absent."""
    raw = os.environ.get(PACKAGE_ROOT_ENV, "").strip()
    if not raw:
        return None
    root = pathlib.Path(raw).expanduser()
    return root if root.is_dir() else None


def external_package_manifest() -> pathlib.Path | None:
    """The configured package's composition manifest, or ``None``.

    The frozen §D.2 package contract names ``composition.yaml`` as THE operator
    entrypoint, so there is deliberately no second environment variable to
    override it — one knob, and it is the one B already reads. Returns ``None``
    rather than a non-existent path, so a caller cannot report "composition
    failed" for a file that was never there.
    """
    root = external_package_root()
    if root is None:
        return None
    candidate = root / "composition.yaml"
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------------
# Interpreter identity
# ---------------------------------------------------------------------------

#: ``sys.modules`` key holding this interpreter's nonce.
#:
#: A module-level ``uuid4()`` would be per-IMPORT, not per-interpreter: import
#: this file twice under two names (a package rename, a `runpy` execution, a
#: plugin loader's `spec_from_file_location`) and the same process would hand
#: out two nonces -- which is precisely the in-process shortcut §K exists to
#: catch, reporting itself as fresh. ``sys.modules`` is process-global, is not
#: shared with a spawned child, and IS inherited by a fork, so it gives the
#: three answers the contract needs.
_NONCE_MODULE_KEY = "_siderius_step12_pr12e_interpreter_nonce"


def interpreter_nonce() -> str:
    """This interpreter's nonce; stable for the life of the process."""
    holder = sys.modules.get(_NONCE_MODULE_KEY)
    if holder is None:
        holder = types.ModuleType(_NONCE_MODULE_KEY)
        holder.__dict__["value"] = uuid.uuid4().hex
        sys.modules[_NONCE_MODULE_KEY] = holder
    return str(holder.__dict__["value"])


def _boot_id() -> str | None:
    """The kernel's boot identity, so a pid from a previous boot is not
    mistaken for this one's. ``None`` off Linux -- an absence, not a value."""
    try:
        return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _start_ticks(pid: int) -> int | None:
    """Field 22 of ``/proc/<pid>/stat`` -- the process's start time in clock
    ticks since boot. With ``boot_id`` and ``pid`` it identifies a process
    even across pid reuse. ``None`` off Linux."""
    try:
        raw = pathlib.Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        # `comm` is parenthesised and may itself contain spaces and
        # parentheses, so the fields are counted from the LAST ')'.
        tail = raw[raw.rindex(")") + 1 :].split()
        return int(tail[19])
    except (ValueError, IndexError):
        return None


class ProcessIdentity(BaseModel):
    """WHICH interpreter produced a piece of evidence.

    Every field is observed by the process describing itself.
    :meth:`current` takes no arguments on purpose: provenance a caller can
    supply is provenance a caller can forge, and the whole point is that the
    recorded identity belongs to the process that did the work. This copies
    ``core/runtime_control/session.py``'s ``owning_process_pid=os.getpid()``
    discipline, which is guarded the same way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pid: int
    boot_id: str | None = None
    start_ticks: int | None = None
    interpreter_nonce: str = Field(min_length=1)
    executable: str = ""
    hostname: str = ""
    recorded_at: str = ""

    @classmethod
    def current(cls) -> ProcessIdentity:
        """This interpreter, right now. No parameters -- see the class doc."""
        pid = os.getpid()
        return cls(
            pid=pid,
            boot_id=_boot_id(),
            start_ticks=_start_ticks(pid),
            interpreter_nonce=interpreter_nonce(),
            executable=sys.executable,
            hostname=socket.gethostname(),
            recorded_at=datetime.now(UTC).isoformat(),
        )


def same_interpreter(a: ProcessIdentity, b: ProcessIdentity) -> bool:
    """Whether ``a`` and ``b`` describe ONE interpreter's execution.

    Two independent criteria, either of which is decisive:

    1. **Equal nonces.** The nonce lives in ``sys.modules``, so equality means
       one process wrote both -- including the ``fork`` case, where the pid and
       the start time differ while the child carries the parent's entire heap.
       A forked "iteration 2" is a continuation, not a restart, and §K's
       requirement is about the interpreter, not about the pid.
    2. **Equal ``(boot_id, pid, start_ticks)``.** Kept because it holds even if
       the nonce were somehow re-seeded, and because it is the reading an
       operator can reproduce from ``/proc`` by hand.

    Neither criterion alone is sufficient, so both are checked.
    """
    if a.interpreter_nonce == b.interpreter_nonce:
        return True
    return (
        a.boot_id is not None
        and a.boot_id == b.boot_id
        and a.pid == b.pid
        and a.start_ticks is not None
        and a.start_ticks == b.start_ticks
    )


def assert_fresh_process(previous: ProcessIdentity, current: ProcessIdentity) -> None:
    """Raise unless ``current`` is a genuinely different interpreter.

    Raises:
        RestoreEvidenceError: the two identities describe one interpreter. The
            message names WHICH criterion matched, because "same nonce" (an
            in-process or forked continuation) and "same pid+start" call for
            different operator actions.
    """
    if not same_interpreter(previous, current):
        return
    # Ordered most-specific first. "Same boot, same pid, same start tick" is a
    # stronger statement than "same nonce" and names a different operator
    # action (you evaluated one process twice, vs. your launch never forked a
    # new interpreter), so it must not be shadowed by the broader branch.
    if (
        previous.boot_id is not None
        and previous.boot_id == current.boot_id
        and previous.pid == current.pid
        and previous.start_ticks is not None
        and previous.start_ticks == current.start_ticks
    ):
        reason = (
            f"both entries are boot {previous.boot_id!r} pid {previous.pid} "
            f"started at tick {previous.start_ticks} -- literally the same process."
        )
    else:
        reason = (
            f"both entries carry interpreter nonce {previous.interpreter_nonce!r}. "
            "One interpreter wrote both -- an in-process continuation, a module "
            "re-import, or a fork. A fork is still a continuation: it inherits "
            "the parent's memory, which is exactly the state a restore must "
            "have re-read from disk."
        )
    raise RestoreEvidenceError(
        "restore provenance does not show a fresh process: " + reason + " "
        "The CLI's iteration counter is not evidence (design §K)."
    )


# ---------------------------------------------------------------------------
# The provenance ledger
# ---------------------------------------------------------------------------

#: Append-only, one JSON object per line, in the run's workspace.
#:
#: Append-only is load-bearing: a second entry written by the SAME interpreter
#: does not overwrite the first, it sits beside it carrying the same nonce, and
#: the freshness check fails on the pair. A last-writer-wins file would have
#: erased the evidence of the shortcut.
PROVENANCE_BASENAME = "step12_pr12e_process_provenance.jsonl"


class ProcessLedgerEntry(BaseModel):
    """One process's claim to have executed one iteration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iteration: int = Field(ge=1)
    role: str = Field(min_length=1)
    identity: ProcessIdentity


def provenance_path(workspace: str | os.PathLike[str]) -> str:
    """Where the ledger lives for ``workspace``."""
    return os.path.join(str(workspace), PROVENANCE_BASENAME)


def record_iteration_process(
    workspace: str | os.PathLike[str], iteration: int, *, role: str = "iteration"
) -> ProcessLedgerEntry:
    """Append THIS interpreter's identity as the executor of ``iteration``.

    Called from inside the process that is about to run the iteration (see
    ``tests/helpers/step12_pr12e_gate_iteration.py``), before the work starts,
    so a crashed iteration still leaves its provenance behind.

    There is deliberately no ``identity=`` parameter: the recorder observes,
    it does not accept.
    """
    entry = ProcessLedgerEntry(
        iteration=int(iteration), role=role, identity=ProcessIdentity.current()
    )
    target = provenance_path(workspace)
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
    return entry


def read_process_ledger(workspace: str | os.PathLike[str]) -> tuple[ProcessLedgerEntry, ...]:
    """Every recorded entry, in write order. Empty when nothing recorded.

    Raises:
        RestoreEvidenceError: a line is present but unreadable. A corrupt
            ledger is a failure of the evidence set, never an empty one --
            silently dropping it would turn "the recorder never ran" and "the
            recorder wrote garbage" into the same, passable, answer.
    """
    target = provenance_path(workspace)
    if not os.path.isfile(target):
        return ()
    entries: list[ProcessLedgerEntry] = []
    for number, line in enumerate(
        pathlib.Path(target).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            entries.append(ProcessLedgerEntry.model_validate_json(line))
        except Exception as exc:
            raise RestoreEvidenceError(
                f"{target}:{number} is not a readable provenance entry ({exc})."
            ) from exc
    return tuple(entries)


# ---------------------------------------------------------------------------
# Evidence read from a real workspace
# ---------------------------------------------------------------------------


class IterationEvidence(BaseModel):
    """What one iteration left behind, as read -- never as inferred."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    iteration: int
    manifest_path: str
    manifest_present: bool
    status: str | None = None
    output_path: str | None = None
    output_present: bool = False
    #: The invariant stamps the committed ``HyperparamTuningOutput`` carries.
    output_stamps: dict[str, Any] = Field(default_factory=dict)
    #: Raw committed-output text, kept so an identifier search reads what was
    #: actually written rather than a re-serialization of it.
    output_text: str | None = None


class RestoreEvidence(BaseModel):
    """Everything §K needs, read from one workspace. No judgements here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace: str
    lock_present: bool
    lock: dict[str, Any] | None = None
    locked_fingerprint: str | None = None
    iterations: tuple[IterationEvidence, ...] = ()
    process_ledger: tuple[ProcessLedgerEntry, ...] = ()
    chain_run_id: str | None = None


_STAMP_KEYS = (
    "task_composition_fingerprint",
    "health_config_sha256",
    "resolved_data_scope",
    "health_gate_enabled",
)


def _iteration_dir_name(iteration: int) -> str:
    """The chain runner's directory convention, from its single authority.

    ``core.resume._iter_run_name`` centralises ``iter_{n:03d}`` precisely so
    that resume cannot drift from the writer. Re-spelling the format here would
    make this reader a second authority, and the day the writer changed the
    reader would silently find nothing and report an empty workspace.
    """
    from core.resume import _iter_run_name

    return _iter_run_name(iteration)


def _read_iteration(workspace: str, iteration: int) -> IterationEvidence:
    manifest_path = os.path.join(workspace, _iteration_dir_name(iteration), "manifest.json")
    if not os.path.isfile(manifest_path):
        return IterationEvidence(
            iteration=iteration, manifest_path=manifest_path, manifest_present=False
        )
    try:
        manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreEvidenceError(f"{manifest_path} is unreadable ({exc}).") from exc
    output_path = manifest.get("output_path")
    text: str | None = None
    stamps: dict[str, Any] = {}
    present = bool(output_path) and os.path.isfile(str(output_path))
    if present:
        text = pathlib.Path(str(output_path)).read_text(encoding="utf-8")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RestoreEvidenceError(f"{output_path} is not valid JSON ({exc}).") from exc
        if isinstance(parsed, dict):
            stamps = {key: parsed.get(key) for key in _STAMP_KEYS if key in parsed}
    return IterationEvidence(
        iteration=iteration,
        manifest_path=manifest_path,
        manifest_present=True,
        status=manifest.get("status"),
        output_path=str(output_path) if output_path else None,
        output_present=present,
        output_stamps=stamps,
        output_text=text,
    )


def read_restore_evidence(
    workspace: str | os.PathLike[str], *, iterations: Sequence[int] = (1, 2)
) -> RestoreEvidence:
    """Read one workspace's restore evidence. Pure: nothing is mutated.

    The lock is loaded through production's own ``load_run_invariants``, so a
    corrupt lock is refused by the authority that owns the format rather than
    re-parsed here into a second opinion.
    """
    from core.run_invariants import RUN_INVARIANTS_BASENAME, RunInvariants, load_run_invariants

    root = str(workspace)
    lock: RunInvariants | None = load_run_invariants(root)
    sidecar = os.path.join(root, ".token_run_id")
    chain_run_id = (
        pathlib.Path(sidecar).read_text(encoding="utf-8").strip()
        if os.path.isfile(sidecar)
        else None
    )
    return RestoreEvidence(
        workspace=root,
        lock_present=os.path.isfile(os.path.join(root, RUN_INVARIANTS_BASENAME)),
        lock=None if lock is None else lock.model_dump(mode="json"),
        locked_fingerprint=None if lock is None else lock.task_composition_fingerprint,
        iterations=tuple(_read_iteration(root, index) for index in iterations),
        process_ledger=read_process_ledger(root),
        chain_run_id=chain_run_id,
    )


# ---------------------------------------------------------------------------
# The §K verdict
# ---------------------------------------------------------------------------


class CheckOutcome(StrEnum):
    """``UNPROVEN`` is not a soft pass.

    A check whose evidence was never collected is reported as UNPROVEN and,
    when the check is required, the verdict is NOT PASS. The alternative --
    treating absent evidence as agreement -- is exactly the reasoning
    ``validate_stamped_invariants`` refuses for an unstamped record.
    """

    PASS = "pass"
    FAIL = "fail"
    UNPROVEN = "unproven"


class CheckResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    outcome: CheckOutcome
    detail: str
    required: bool = True


class RestoreVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    checks: tuple[CheckResult, ...]
    observed_but_not_gating: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Every REQUIRED check passed. UNPROVEN never counts as passed."""
        return all(
            check.outcome is CheckOutcome.PASS for check in self.checks if check.required
        ) and any(check.required for check in self.checks)

    def named(self, name: str) -> CheckResult:
        """One check by name, so a caller states which it means."""
        for check in self.checks:
            if check.name == name:
                return check
        raise KeyError(f"no check named {name!r}; have {[c.name for c in self.checks]}")


def _check_committed_state(evidence: RestoreEvidence, first: int) -> CheckResult:
    from core.run_invariants import RUN_INVARIANTS_BASENAME

    name = "K1_committed_restorable_state"
    problems: list[str] = []
    if not evidence.lock_present:
        problems.append(f"no {RUN_INVARIANTS_BASENAME} in the workspace")
    elif evidence.locked_fingerprint is None:
        problems.append(
            "the lock carries no task_composition_fingerprint, so the run was "
            "not composed and no package identity was pinned"
        )
    iteration = next((i for i in evidence.iterations if i.iteration == first), None)
    if iteration is None or not iteration.manifest_present:
        problems.append(f"iteration {first} wrote no manifest.json")
    elif iteration.status != "completed":
        problems.append(
            f"iteration {first} manifest status is {iteration.status!r}, not "
            "'completed' -- it committed no records for a later iteration to consume"
        )
    elif not iteration.output_present:
        problems.append(
            f"iteration {first} manifest names output_path {iteration.output_path!r}, "
            "which is not on disk"
        )
    if problems:
        return CheckResult(name=name, outcome=CheckOutcome.FAIL, detail="; ".join(problems))
    return CheckResult(
        name=name,
        outcome=CheckOutcome.PASS,
        detail=(
            f"lock pins {str(evidence.locked_fingerprint)[:12]}…; iteration {first} "
            "committed a manifest and its run_output"
        ),
    )


def _check_fresh_process(evidence: RestoreEvidence, wanted: Sequence[int]) -> CheckResult:
    name = "K2_fresh_process_provenance"
    by_iteration: dict[int, list[ProcessLedgerEntry]] = {}
    for entry in evidence.process_ledger:
        if entry.role == "iteration":
            by_iteration.setdefault(entry.iteration, []).append(entry)
    missing = [index for index in wanted if index not in by_iteration]
    if missing:
        # FAIL, not UNPROVEN: §K makes this evidence REQUIRED, and a Gate that
        # passed without it would be back to inferring the restart from the
        # iteration counter.
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=(
                f"no provenance recorded for iteration(s) {missing} in "
                f"{provenance_path(evidence.workspace)}. Launch each iteration "
                "through tests/helpers/step12_pr12e_gate_iteration.py so the "
                "executing interpreter records itself."
            ),
        )
    ordered = [(index, by_iteration[index][0].identity) for index in wanted]
    for (left_index, left), (right_index, right) in pairwise(ordered):
        try:
            assert_fresh_process(left, right)
        except RestoreEvidenceError as exc:
            return CheckResult(
                name=name,
                outcome=CheckOutcome.FAIL,
                detail=f"iterations {left_index} and {right_index}: {exc}",
            )
    pids = ", ".join(f"iter {index}=pid {identity.pid}" for index, identity in ordered)
    return CheckResult(
        name=name,
        outcome=CheckOutcome.PASS,
        detail=f"distinct interpreters recorded themselves: {pids}",
    )


def _check_identity_across_boundary(evidence: RestoreEvidence) -> CheckResult:
    name = "K3_identity_same_value_across_boundary"
    locked = evidence.locked_fingerprint
    if locked is None:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail="the lock pins no composition fingerprint, so nothing crossed to compare",
        )
    stamped = [
        iteration
        for iteration in evidence.iterations
        if iteration.output_stamps.get("task_composition_fingerprint") is not None
    ]
    if not stamped:
        # The anti-vacuity branch, copied from `check_a3` in the 12a evaluator:
        # a comparison over zero artifacts is not agreement.
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=(
                "no committed run_output carries a task_composition_fingerprint. "
                "A check that compares nothing cannot pass."
            ),
        )
    drifted = [
        f"iteration {iteration.iteration} stamped "
        f"{str(iteration.output_stamps['task_composition_fingerprint'])[:12]}…"
        for iteration in stamped
        if iteration.output_stamps["task_composition_fingerprint"] != locked
    ]
    if drifted:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=f"lock pins {locked[:12]}… but {'; '.join(drifted)}",
        )
    return CheckResult(
        name=name,
        outcome=CheckOutcome.PASS,
        detail=(f"{len(stamped)} committed artifact(s) carry the locked identity {locked[:12]}…"),
    )


def _check_package_named(
    evidence: RestoreEvidence, identifiers: Iterable[str] | None, first: int
) -> CheckResult:
    name = "K3b_declared_package_named_in_committed_state"
    if identifiers is None:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.UNPROVEN,
            detail=(
                "no package identifiers supplied. Pass the set produced by "
                "workstream B's identifier-extraction helper (design §G.3) to "
                "evaluate this check."
            ),
            required=False,
        )
    wanted = sorted({value for value in identifiers if value})
    if not wanted:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail="an EMPTY identifier set was supplied; it would match any run",
            required=False,
        )
    iteration = next((i for i in evidence.iterations if i.iteration == first), None)
    text = iteration.output_text if iteration is not None else None
    if not text:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=f"iteration {first} committed no run_output text to search",
            required=False,
        )
    found = [value for value in wanted if value in text]
    if not found:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=(
                f"iteration {first}'s committed run_output names none of {wanted} — "
                "the restored state does not belong to the declared package"
            ),
            required=False,
        )
    return CheckResult(
        name=name,
        outcome=CheckOutcome.PASS,
        detail=f"iteration {first}'s committed run_output names {found}",
        required=False,
    )


def _check_child_argv_identity(child_argv: Sequence[Sequence[str]] | None) -> CheckResult:
    name = "K4_transported_identity_is_one_value"
    if child_argv is None:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.UNPROVEN,
            detail=(
                "no child argv captured. That the transported identity is the "
                "REGISTRATION capture rather than a fresh read of the plugin file "
                "(F-12bc-7) is proved deterministically by "
                "tests/unit/workflows/test_step12_pr12e_c4_registration_identity.py; "
                "this check reports only what a real run's argv showed."
            ),
            required=False,
        )
    from execute_tools.task_data_path import TASK_DATA_PATH_IDENTITY_FLAG

    seen: set[str] = set()
    for argv in child_argv:
        parts = [str(part) for part in argv]
        if TASK_DATA_PATH_IDENTITY_FLAG not in parts:
            continue
        index = parts.index(TASK_DATA_PATH_IDENTITY_FLAG)
        if index + 1 < len(parts):
            seen.add(parts[index + 1])
    if not seen:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=(
                f"none of the {len(list(child_argv))} captured child argvs carried "
                f"{TASK_DATA_PATH_IDENTITY_FLAG}; the run transported no identity"
            ),
            required=False,
        )
    if len(seen) > 1:
        return CheckResult(
            name=name,
            outcome=CheckOutcome.FAIL,
            detail=f"children were spawned with DIFFERENT transported identities: {sorted(seen)}",
            required=False,
        )
    return CheckResult(
        name=name,
        outcome=CheckOutcome.PASS,
        detail=f"every identity-carrying child argv transported {sorted(seen)[0]}",
        required=False,
    )


def evaluate_restore_contract(
    evidence: RestoreEvidence,
    *,
    iterations: Sequence[int] = (1, 2),
    expected_fingerprint: str | None = None,
    package_identifiers: Iterable[str] | None = None,
    child_argv: Sequence[Sequence[str]] | None = None,
) -> RestoreVerdict:
    """Evaluate design §K over one workspace's evidence.

    Args:
        evidence: from :func:`read_restore_evidence`.
        iterations: the chain's iteration indices, in order.
        expected_fingerprint: the composition fingerprint the Gate DECLARED
            before launching. Supplied separately -- and never read back from
            the run -- for the same reason ``step12_pr12a_gate2_evaluate.py``
            hardcodes ``EXPECTED_FINGERPRINT``: a value the run produced cannot
            certify the run.
        package_identifiers: workstream B's extracted identifiers (§G.3). C
            consumes this read-only and implements no copy of it.
        child_argv: captured child command lines, if the Gate collected them.

    Returns:
        A :class:`RestoreVerdict`. ``UNPROVEN`` checks are non-required and are
        reported, never silently upgraded.
    """
    ordered = list(iterations)
    if not ordered:
        raise ValueError("iterations must name at least one iteration")
    first = ordered[0]
    checks = [
        _check_committed_state(evidence, first),
        _check_fresh_process(evidence, ordered),
        _check_identity_across_boundary(evidence),
        _check_package_named(evidence, package_identifiers, first),
        _check_child_argv_identity(child_argv),
    ]
    if expected_fingerprint is not None:
        matches = evidence.locked_fingerprint == expected_fingerprint
        checks.append(
            CheckResult(
                name="K1b_lock_pins_the_declared_composition",
                outcome=CheckOutcome.PASS if matches else CheckOutcome.FAIL,
                detail=(
                    f"declared {expected_fingerprint[:12]}…; lock pins "
                    f"{str(evidence.locked_fingerprint)[:12]}…"
                ),
            )
        )
    observed = {
        "chain_run_id": evidence.chain_run_id,
        "per_iteration": {
            iteration.iteration: {
                "status": iteration.status,
                "output_path": iteration.output_path,
            }
            for iteration in evidence.iterations
        },
        "NOTE": (
            "recorded, NOT gating: model quality, score magnitude, convergence, "
            "HealthGate PASS and LLM response quality are not §K criteria"
        ),
    }
    return RestoreVerdict(checks=tuple(checks), observed_but_not_gating=observed)


# ---------------------------------------------------------------------------
# Operator entry point
# ---------------------------------------------------------------------------


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    """Evaluate a workspace and write the evidence packet.

    Exit codes mirror ``scripts/step12_pr12a_gate2_evaluate.py``: ``0`` PASS,
    ``1`` FAIL, ``2`` the workspace is not there.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate PR-12e's restore / process-provenance contract (design §K)."
    )
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--out", default=None, help="directory receiving the JSON packet")
    parser.add_argument("--iterations", default="1,2", help="comma-separated iteration indices")
    parser.add_argument("--expected-fingerprint", default=None)
    parser.add_argument(
        "--package-identifiers",
        default=None,
        help="comma-separated identifiers from workstream B's extraction helper",
    )
    args = parser.parse_args(argv)

    if not os.path.isdir(args.workspace):
        print(f"[step12-pr12e] workspace not found: {args.workspace}", file=sys.stderr)
        return 2

    indices = [int(part) for part in (_split_csv(args.iterations) or [])]
    evidence = read_restore_evidence(args.workspace, iterations=indices)
    verdict = evaluate_restore_contract(
        evidence,
        iterations=indices,
        expected_fingerprint=args.expected_fingerprint,
        package_identifiers=_split_csv(args.package_identifiers),
    )
    payload = {
        "gate": "G-12e restore / process provenance (design §K)",
        "workspace": os.path.abspath(args.workspace),
        "declared_fingerprint": args.expected_fingerprint,
        "checks": [check.model_dump(mode="json") for check in verdict.checks],
        "observed_but_NOT_gating": verdict.observed_but_not_gating,
        "verdict": "PASS" if verdict.passed else "FAIL",
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        target = os.path.join(args.out, "step12_pr12e_restore_result.json")
        pathlib.Path(target).write_text(text + "\n", encoding="utf-8")
        print(f"[step12-pr12e] wrote {target}")
    print(text)
    return 0 if verdict.passed else 1


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
