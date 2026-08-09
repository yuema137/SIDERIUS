"""V21 PR D1 — the ScientificAuthority verdict matrix, frozen before transport.

PR D is a **transport** PR: it makes a launcher's declared posture reach
`ScientificAuthority.from_context`. It changes no semantics. This module
exists so that claim is *measured* rather than asserted.

**Why this is pinned BEFORE the transport work.** B1 established the
lesson concretely: a parity claim written *after* a change cannot
distinguish "unchanged" from "changed, and the expectations were written
to match the new behaviour". Pinning first inverts that — D2 must keep
every row below green without editing one of them.

**Every expected value here is hand-derived from the documented rule and
written as a literal.** None was produced by calling the module and
copying its output; doing so would make the whole table circular and it
would pass for any implementation. The rule, from
`core/scientific_authority.py:130-141` and `:64-70`:

```text
blockers, collected as a set:
    legacy_authority_unknown   healthgate_mode is None OR
                               declared_result_authority is None
    declared_diagnostic        declared_result_authority == "diagnostic"
    non_blocking_mode          healthgate_mode == "observe_only"
    gate_invalidated           formal_validity == "invalid"
    formal_validity_unknown    formal_validity == "unknown"   (elif)

reported in _BLOCKER_PRECEDENCE order:
    legacy_authority_unknown, declared_diagnostic, non_blocking_mode,
    gate_invalidated, formal_validity_unknown

authoritative  = not blockers
primary_basis  = blockers[0] if blockers else "blocking_scientific_formal_valid"
```

Note `gate_invalidated` / `formal_validity_unknown` are mutually exclusive
(`elif`), which is why no row below carries both.

Design doc: ``docs/design/v21_priorities/pr_d_scientific_authority_reachable.md``
§0.A and Commit D1.
"""

from __future__ import annotations

import pytest

from core.scientific_authority import ScientificAuthority

_LEGACY = "legacy_authority_unknown"
_DIAG = "declared_diagnostic"
_NONBLOCK = "non_blocking_mode"
_INVALID = "gate_invalidated"
_UNKNOWN_V = "formal_validity_unknown"
_OK = "blocking_scientific_formal_valid"

#: The complete 3x3x3 matrix. Each row is
#: ``(healthgate_mode, declared_result_authority, formal_validity,
#:    blocking_reasons_in_order, authoritative, primary_basis)``.
#: Hand-derived from the rule quoted in the module docstring.
MATRIX: list[tuple[str | None, str | None, str, list[str], bool, str]] = [
    # ---- healthgate_mode = None: legacy always fires (either-axis rule) ----
    (None, None, "valid", [_LEGACY], False, _LEGACY),
    (None, None, "invalid", [_LEGACY, _INVALID], False, _LEGACY),
    (None, None, "unknown", [_LEGACY, _UNKNOWN_V], False, _LEGACY),
    (None, "scientific", "valid", [_LEGACY], False, _LEGACY),
    (None, "scientific", "invalid", [_LEGACY, _INVALID], False, _LEGACY),
    (None, "scientific", "unknown", [_LEGACY, _UNKNOWN_V], False, _LEGACY),
    (None, "diagnostic", "valid", [_LEGACY, _DIAG], False, _LEGACY),
    (None, "diagnostic", "invalid", [_LEGACY, _DIAG, _INVALID], False, _LEGACY),
    (None, "diagnostic", "unknown", [_LEGACY, _DIAG, _UNKNOWN_V], False, _LEGACY),
    # ---- healthgate_mode = blocking ----
    ("blocking", None, "valid", [_LEGACY], False, _LEGACY),
    ("blocking", None, "invalid", [_LEGACY, _INVALID], False, _LEGACY),
    ("blocking", None, "unknown", [_LEGACY, _UNKNOWN_V], False, _LEGACY),
    # THE ONLY AUTHORITATIVE ROW IN THE ENTIRE MATRIX
    ("blocking", "scientific", "valid", [], True, _OK),
    ("blocking", "scientific", "invalid", [_INVALID], False, _INVALID),
    ("blocking", "scientific", "unknown", [_UNKNOWN_V], False, _UNKNOWN_V),
    ("blocking", "diagnostic", "valid", [_DIAG], False, _DIAG),
    ("blocking", "diagnostic", "invalid", [_DIAG, _INVALID], False, _DIAG),
    ("blocking", "diagnostic", "unknown", [_DIAG, _UNKNOWN_V], False, _DIAG),
    # ---- healthgate_mode = observe_only ----
    ("observe_only", None, "valid", [_LEGACY, _NONBLOCK], False, _LEGACY),
    ("observe_only", None, "invalid", [_LEGACY, _NONBLOCK, _INVALID], False, _LEGACY),
    ("observe_only", None, "unknown", [_LEGACY, _NONBLOCK, _UNKNOWN_V], False, _LEGACY),
    ("observe_only", "scientific", "valid", [_NONBLOCK], False, _NONBLOCK),
    ("observe_only", "scientific", "invalid", [_NONBLOCK, _INVALID], False, _NONBLOCK),
    ("observe_only", "scientific", "unknown", [_NONBLOCK, _UNKNOWN_V], False, _NONBLOCK),
    ("observe_only", "diagnostic", "valid", [_DIAG, _NONBLOCK], False, _DIAG),
    ("observe_only", "diagnostic", "invalid", [_DIAG, _NONBLOCK, _INVALID], False, _DIAG),
    ("observe_only", "diagnostic", "unknown", [_DIAG, _NONBLOCK, _UNKNOWN_V], False, _DIAG),
]

#: Exactly the keys a persisted verdict exposes. Pinned so a NEW
#: downstream-visible field cannot appear unnoticed: a reader of an
#: existing record would silently start seeing a fact no row here
#: constrains.
EXPECTED_KEYS = {
    "healthgate_mode",
    "declared_result_authority",
    "formal_validity",
    "blocking_reasons",
    "authoritative",
    "primary_basis",
    "enters_incumbent_selection",
    "enters_scientific_aggregation",
}


def test_the_matrix_covers_the_whole_input_space():
    """27 rows, no duplicates — a missing row is an unpinned semantic."""
    assert len(MATRIX) == 27
    assert len({(m, a, v) for m, a, v, *_ in MATRIX}) == 27


@pytest.mark.parametrize(
    ("mode", "authority", "validity", "blockers", "authoritative", "basis"),
    MATRIX,
    ids=[f"{m}|{a}|{v}" for m, a, v, *_ in MATRIX],
)
def test_row(mode, authority, validity, blockers, authoritative, basis):
    """The complete downstream-visible verdict for one input triple.

    Asserts the whole `model_dump()`, not a selected field: the persisted
    record carries all of it, and `resolve_record_authority` re-derives
    and compares **every key present** on a stored verdict
    (`core/scientific_authority.py:320-325`), so any field drifting would
    change how historical records are judged.
    """
    dumped = ScientificAuthority.from_context(
        healthgate_mode=mode,
        declared_result_authority=authority,
        formal_validity=validity,
    ).model_dump()

    assert set(dumped) == EXPECTED_KEYS, (
        "the verdict's downstream-visible field set changed; every row in "
        "this matrix constrains only the fields it knows about, so a new "
        "field must be added here deliberately"
    )
    assert dumped == {
        "healthgate_mode": mode,
        "declared_result_authority": authority,
        "formal_validity": validity,
        "blocking_reasons": blockers,
        "authoritative": authoritative,
        "primary_basis": basis,
        # Two separate computed fields today. Pinned per row rather than
        # asserted to "track authoritative", so a future divergence shows
        # up as a failing row instead of a silently-passing tautology.
        "enters_incumbent_selection": authoritative,
        "enters_scientific_aggregation": authoritative,
    }


def test_exactly_one_combination_is_authoritative():
    """The scarcity is the point.

    If a transport change ever made a second combination authoritative,
    the campaign's notion of "may inform science" would have widened
    without anyone deciding to widen it.
    """
    authoritative = [(m, a, v) for m, a, v, _b, auth, _p in MATRIX if auth]
    assert authoritative == [("blocking", "scientific", "valid")]


def test_blocking_reasons_are_ordered_not_merely_present():
    """Order is semantic: an operator reads the first reason.

    `primary_basis` is literally `blocking_reasons[0]`, so a set-like
    comparison would let precedence drift while every row still "passed".
    """
    precedence = [_LEGACY, _DIAG, _NONBLOCK, _INVALID, _UNKNOWN_V]
    for mode, authority, validity, blockers, _auth, basis in MATRIX:
        assert blockers == sorted(blockers, key=precedence.index), (
            f"{mode}|{authority}|{validity}: expectation itself is mis-ordered"
        )
        if blockers:
            assert basis == blockers[0]

    # The densest row: three blockers whose relative order is fixed.
    dense = ScientificAuthority.from_context(
        healthgate_mode="observe_only",
        declared_result_authority="diagnostic",
        formal_validity="invalid",
    )
    assert dense.blocking_reasons == [_DIAG, _NONBLOCK, _INVALID]


def test_an_undeclared_axis_alone_blocks_regardless_of_the_other():
    """The either-axis rule, stated as its own property.

    This is the invariant PR D's transport must not weaken, and the reason
    a one-axis default cannot manufacture authority (design §0.E). It is
    asserted separately from the matrix because D2's undeclared-path tests
    depend on exactly this, and a reader should not have to infer it from
    27 rows.
    """
    for mode, authority in (("blocking", None), (None, "scientific")):
        verdict = ScientificAuthority.from_context(
            healthgate_mode=mode,
            declared_result_authority=authority,
            formal_validity="valid",
        )
        assert verdict.authoritative is False
        assert verdict.primary_basis == _LEGACY


def test_a_caller_cannot_supply_a_conclusion():
    """Conclusions are derived, never accepted.

    `extra="forbid"` (`core/scientific_authority.py:86`) means a caller
    that tries to assert `authoritative=True` is refused rather than
    silently ignored — the difference between a wrong verdict and a wrong
    mental model that survives review.
    """
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        ScientificAuthority(
            healthgate_mode="blocking",
            declared_result_authority="scientific",
            formal_validity="invalid",
            authoritative=True,
        )
