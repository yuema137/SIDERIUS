"""Run-scoped visibility for task data-path registrations (PR-12bc C1).

Step 12 / PR-12bc, Phase C. **Its own module, deliberately** (§J): the overlay
is a bounded lifecycle mechanism, not a growth of the composer and not a
service locator.

The problem, from the parent's §8. `_REGISTRY` grows monotonically for the life
of the interpreter and has no removal path, so a registration made for one run
outlives it. The frozen two-phase contract is::

    WITHIN an active run   same identity + same content  -> idempotent
                           same id + DIFFERENT content   -> refuse (named)
                           a different roster mid-run    -> refuse (named)
    AFTER the run unwinds  the next run may register a DIFFERENT roster —
                           no permanent poisoning

C1.1 implemented the first two rows in the registry itself. This module
implements the *unwind*: registrations made inside a scope are retired when it
closes, so the next run starts from the roster it inherited rather than from
whatever the previous one left behind.

**Whose guarantee this is (D-BC-3, ratified with rewording).** The overlay owns
run-scoped lifecycle semantics *wherever multiple run scopes share an
interpreter*. Current production obtains equivalent post-run isolation
STRUCTURALLY — one `run_one_iteration.py` process per iteration, so the
interpreter dies and takes the registry with it. It is neither "what production
does today" nor "test-only": it is the same guarantee, whose owner differs by
execution model.

**Concurrent in-process runs are OUT OF SCOPE and fail closed.** Two scopes
open at once would interleave shared registry state, and the honest answer is
to refuse rather than to invent a semantics nobody designed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from execute_tools import task_data_path as _tdp


class RegistrationScopeError(RuntimeError):
    """A registration scope was used in a way its semantics do not define.

    Today that means exactly one thing: a second scope opened while one is
    already active. Concurrent in-process runs are out of scope, so this is a
    refusal rather than a nested-scope semantics.
    """


#: The ids visible when the ACTIVE scope opened. ``None`` means no scope is
#: open, which is the ordinary production state today.
_SCOPE_BASELINE: ContextVar[frozenset[str] | None] = ContextVar(
    "siderius_task_registration_scope", default=None
)


def active_registration_scope() -> frozenset[str] | None:
    """The active scope's inherited roster, or ``None`` when none is open."""
    return _SCOPE_BASELINE.get()


def retire_registrations(keep: frozenset[str]) -> list[str]:
    """Remove every registration whose id is not in ``keep``. Returns them.

    The ONE mutation path out of the registry, and it is deliberately not a
    public ``unregister(id)``: retiring is a LIFECYCLE operation over a known
    baseline, not an ad-hoc removal a caller can aim at whatever it likes.
    Both maps are cleared in lockstep, so
    :func:`~execute_tools.task_data_path.registry_invariant_holds` stays true.
    """
    retired = sorted(set(_tdp._REGISTRY) - keep)
    for impl_id in retired:
        _tdp._REGISTRY.pop(impl_id, None)
        _tdp._CONTENT.pop(impl_id, None)
    return retired


@contextmanager
def run_registration_scope() -> Iterator[frozenset[str]]:
    """Registrations made inside become invisible when the block exits.

    Mirrors the ContextVar binding discipline the composition edge already
    uses: the scope is entered, the run does its work, and on unwind — INCLUDING
    on an exception — the roster returns to what it inherited.

    Yields:
        The inherited roster, so a caller can see what it started from.

    Raises:
        RegistrationScopeError: a scope is already open. Concurrent in-process
            runs would interleave shared registry state; refusing is the
            honest answer, not a nested-scope semantics.
    """
    if _SCOPE_BASELINE.get() is not None:
        raise RegistrationScopeError(
            "a task-registration scope is already open in this context. "
            "Concurrent in-process runs are out of scope: two runs sharing one "
            "registry would interleave each other's roster, so this refuses "
            "rather than inventing a semantics for it."
        )
    baseline = frozenset(_tdp._REGISTRY)
    token = _SCOPE_BASELINE.set(baseline)
    try:
        yield baseline
    finally:
        _SCOPE_BASELINE.reset(token)
        retire_registrations(baseline)


@contextmanager
def registration_rollback() -> Iterator[None]:
    """Undo any registration made inside, if the block RAISES.

    F-12bc-2. The composition loader rolls back ``sys.modules`` when a plugin
    raises but leaves the registry dirty, so a module that registered a data
    path and then failed leaves its id permanently taken by an implementation
    whose module never finished running. The health loader already does this
    for its own registries (`_plugin_binding.py`); this is the same idiom, one
    family over.

    Deliberately narrower than :func:`run_registration_scope`: it retires ONLY
    on failure. A plugin that loads successfully has registered something the
    run is meant to keep.
    """
    before = frozenset(_tdp._REGISTRY)
    try:
        yield
    except BaseException:
        retire_registrations(before)
        raise
