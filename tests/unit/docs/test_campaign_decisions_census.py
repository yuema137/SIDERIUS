"""Executable census over ``docs/campaign/official_campaign_decisions.yaml``.

WHICH DEFECT THIS CATCHES THAT NOTHING ELSE DOES
------------------------------------------------
That file is the FROZEN AUTHORITY a tag-time release-blocker census reads, and
before this module **nothing in the repository parsed it**. Several test modules
mention row ids in their docstrings; none loads the YAML. The census was a human
reading 7,600 lines.

The file has TWO WRITERS on two branches — the release lanes (later on
REMEDIATION) and the campaign-planning lane (later on OPERATOR RULINGS) — and
they diverge bidirectionally. That produces one failure mode no other check in
this repository can see:

    A ROW WHOSE `status` IS STALE ON BOTH BRANCHES AT ONCE.

On 2026-08-27 the four ``F-SCANE-*`` rows read ``PENDING_IMPLEMENTATION`` on
``origin/master`` while their fix WAS ``origin/master``'s own HEAD commit
(``d2c12ebe``, PR #360, which changed 29 files and did not touch this ledger).
The campaign branch read ``PENDING_IMPLEMENTATION`` too. A diff between the two
writers showed nothing, because *two stale copies agree*. Pyright, ruff and
Pydantic see a YAML document they never load; every other test sees Python. The
only thing that could have caught it is an assertion about the CONTENT of the
census, pinned to a set someone has to justify changing — which is this module.

It is not a one-off. Within three merges it happened again: PR #361
(``b012616a``) closed ``F-SCANB-3``, ``F-SCANF-1`` and ``F-SCANF-2`` in code and
left all three reading ``PENDING_IMPLEMENTATION`` here. The pattern is
structural, not careless — the PR that fixes a defect updates code and tests,
and the ledger is written by a separate reconciliation pass, so the window is
open by construction on every single fix. A guard is the only thing that closes
it, because the person best placed to notice is the one who just proved the
code correct and has no reason to open a YAML file.

The consequence runs in both directions and both are release hazards:

* a FALSE OPEN holds a tag for work that already landed;
* a FALSE CLOSED ships a genuine release blocker.

HOW THESE TESTS FAIL WHEN THE BEHAVIOUR BREAKS
----------------------------------------------
* ``test_open_release_blockers_are_exactly_the_declared_set`` — a row moving
  into or out of the open set fails with the two symmetric differences printed
  by id. It is a POSITIVE MEMBERSHIP assertion (``==`` against a named set), not
  ``assert not offenders``: an emptiness assertion passes when the scanner
  silently stops finding anything, which is census blindness shape 2.
* ``test_a_terminal_release_blocker_names_its_evidence`` — flipping a status to
  ``DISCHARGED`` without a SHA, a ruling or a moot reason fails naming the row.
* ``test_fields_carrying_an_open_token_are_classified`` — a NEW field name
  carrying an open-status token fails until it is classified HISTORICAL (what
  the row used to say) or LIVE (a declared open item). Without this the ruled
  historical-field exclusion could silently widen, and the census would change
  meaning with nobody deciding that it should.
* ``test_the_ledger_vocabulary_is_a_subset_of_the_plan`` — the YAML declaring a
  status the plan's §0 does not define fails naming it.
* ``test_every_status_in_use_is_declared`` — a row carrying an undeclared
  status fails naming it. This is the direction a newly INVENTED value takes,
  and the pair is asserted because the two catch opposite drifts.

THE VOCABULARY PAIR, and why it is not ceremony. Measured 2026-08-27: SIX
statuses were carried by rows while declared in neither the plan's §0 nor the
ledger, and ALL FIVE members of this module's then-private terminal set were
undeclared — ``RESOLVED_BY_RULING`` was not even carried by any row. A census
that owns its own closed-side vocabulary cannot be wrong about it, so every
mismatch reads as a ledger bug and the cheapest repair is to edit the census.
The set now has exactly one home (``terminal_statuses`` in the ledger, defined
in plan §0.1) and these two tests make drift a failure rather than a discovery.

Evidence lives in ``~/.siderius_supervisor/AUTHORITY_RECONCILIATION_2026_08_27.md``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER = REPO_ROOT / "docs" / "campaign" / "official_campaign_decisions.yaml"
PLAN = REPO_ROOT / "docs" / "campaign" / "official_campaign_plan.md"

# --------------------------------------------------------------------------
# The ruled closure predicate (operator-ruled, 2026-08-27).
#
# THIS MODULE DECLARES NO STATUS VOCABULARY OF ITS OWN. Until 2026-08-27 the
# terminal set was a frozenset literal here, and NONE of its five members was
# declared in the plan's §0 or in the ledger's `status_vocabulary` —
# `RESOLVED_BY_RULING` was not even carried by a row. A census whose closed-side
# vocabulary is private to the census cannot be wrong about it, which is the
# problem: any mismatch reads as a bug in the ledger, and the cheapest repair is
# to edit this file until it agrees with whatever was written. The terminal set
# is now READ from the ledger's declared `terminal_statuses`, and the two
# vocabulary tests below make guard/authority drift a failure instead of a
# discovery.
# --------------------------------------------------------------------------

#: Scalar values that DECLARE an open item when they appear as a whole field
#: value. Matched on the exact stripped, upper-cased leaf — never as a
#: substring, because every `reconciled` block in the file quotes these words in
#: prose while describing work that is finished.
OPEN_TOKENS = frozenset(
    {
        "OPEN",
        "OPEN_MUST",
        "PENDING",
        "PENDING_AUDIT",
        "PENDING_IMPLEMENTATION",
        "PENDING_LAUNCH_AUDIT",
        "PENDING_OPERATOR_DECISION",
        "PENDING_RELEASE_IMPLEMENTATION",
        "PENDING_RUNTIME_EVIDENCE",
        "NOT_IMPLEMENTED",
        "UNRESOLVED",
        "TODO",
        "BLOCKED",
    }
)

#: HISTORICAL fields: they record what a row USED TO say. Excluded BY NAME,
#: because no scan can tell a superseded value from a live one by shape.
#: `test_fields_carrying_an_open_token_are_classified` is what stops this set
#: from widening by accident.
HISTORICAL_FIELDS = frozenset(
    {
        "superseded_status",
        "reconciled",
        "prior_status",
        "resolution",
        "discharge",
        "historical_state",
        "historical_values",
        "superseded_by",
        "supersedes",
        "historical_event",
        "withdrawn",
        "correction_to_earlier_record",
        "status_correction_2026_08_26",
        "closed_2026_08_27",
        "re_derivation_2026_08_26",
        "alias",
        "historical_aliases",
        "origin",
        "historical_census_result",
        # Added 2026-08-27 by the authority reconciliation, with its reason
        # recorded rather than assumed: `current_state_audited` describes the
        # world AT THE MOMENT THE ROW WAS RAISED. R-OBS-1 carries four
        # NOT_IMPLEMENTED values there while being closed by its own
        # `closed_2026_08_27` evidence block. Left unexcluded it makes R-OBS-1
        # a phantom open blocker against that evidence.
        "current_state_audited",
        # Reconciliation notes written by this lane. Same role as `reconciled`,
        # which the ruled list already excludes; distinct keys only because
        # YAML forbids duplicate keys on rows that already carry one.
        "reconciled_status_2026_08_27",
        "disposition_corrected_2026_08_27",
        "discharge_verified_2026_08_27",
        "master_verification_2026_08_27",
    }
)

#: Fields that DECLARE a live open item. Every one is counted by the predicate.
#: Listed so that a new field name carrying an open token cannot join the
#: census — in either direction — without someone classifying it.
LIVE_OPEN_ITEM_FIELDS = frozenset(
    {
        "api_retry_vs_scientific_attempt",
        "artifact_status",
        "audit_status",
        "disposition",
        "enforcement_status",
        "frozen_value",
        "implementation_status",
        "known_gap",
        "materialization_status",
        "mechanism_status",
        "open_must_false_header_in_shipped_config",
        "operator_confirmation_owed",
        "seed_values_status",
        # NESTED sub-item statuses. The ROW-level `status` is the predicate's
        # subject and is skipped before this scan; a `status` reached inside a
        # sub-mapping (D-TREAT-8's per-hash entries, D-LLM-13's per-provider
        # entry, F-SCAND-2's residual) is a declared open item like any other.
        "status",
        "finding_status",
        "value_status",
        "enabled_state_for_the_formal_campaign",
    }
)

#: Fields whose presence discharges a terminal status: a SHA, a ruling, or a
#: named reason. A terminal status carrying none of these is bookkeeping.
EVIDENCE_FIELDS = frozenset(
    {
        "reconciled",
        "reconciled_status_2026_08_27",
        "discharge",
        "discharge_verified_2026_08_27",
        "closed_2026_08_27",
        "resolution",
        "moot_because",
        "verification",
        "status_correction_2026_08_26",
        "re_derivation_2026_08_26",
    }
)

# --------------------------------------------------------------------------
# The census result, pinned. Changing this set is a DECISION, not a fixup.
# --------------------------------------------------------------------------

#: Every genuinely-open v0.1.0 RELEASE_BLOCKER, with the PR that owns it.
#: Hardcoded, never read back from the ledger — a set derived from the thing
#: under test asserts the file against itself and passes for any content.
#:
#: THE RULE FOR CHANGING THIS SET. Because it is hardcoded, every merge that
#: closes a blocker moves it, and the temptation is to edit it until the suite
#: is green. Removing an id REQUIRES that the row itself already carry a LANDED
#: SHA — a `reconciled` / `discharge` / `closed_*` field or a `ruling_*` naming
#: the commit — verified against merged source, never against a PR being open
#: or a commit message. `test_a_terminal_release_blocker_names_its_evidence`
#: enforces the SHA half independently, so deleting an id here without
#: evidencing the row leaves the suite red anyway. Adding an id is always
#: allowed: a newly-found blocker is a finding, not a regression in this file.
#: EMPTY again as of 2026-08-27, after `b5b063f3` (PR #374) landed the five
#: blinded-review repairs this set named while they were in flight. Those rows
#: carried `landed_sha: null` until a REAL SHA existed; none was invented.
#:
#: This set has now gone empty → non-empty → empty within one day, and both
#: transitions were caught by this test rather than noticed. That churn is the
#: normal state of a pre-tag ledger, not an anomaly.
#:
#: EMPTY is the strongest state this pin can hold AND the most fragile:
#: `observed == expected` is trivially true when BOTH are empty, including when
#: the scan is broken and examines nothing. `test_the_blocker_census_is_not_
#: vacuous` exists for exactly this state — an all-clear is only meaningful if
#: something was inspected.
EXPECTED_OPEN_RELEASE_BLOCKERS: dict[str, str] = {}


@pytest.fixture(scope="module")
def ledger() -> dict[str, Any]:
    return yaml.safe_load(LEDGER.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    decisions = ledger["decisions"]
    assert decisions, "the ledger declares no decisions — the census would be vacuous"
    return decisions


@pytest.fixture(scope="module")
def terminal_statuses(ledger: dict[str, Any]) -> frozenset[str]:
    """The CLOSED side of the predicate, read from the authority, never local."""
    declared = ledger.get("terminal_statuses")
    assert declared, (
        "the ledger declares no `terminal_statuses`. That key IS the closed side "
        "of the census predicate (plan §0.1); without it this guard would have to "
        "reinvent a private vocabulary, which is the defect it exists to prevent."
    )
    return frozenset(declared)


def _plan_declared_statuses() -> set[str]:
    """Every status named in the plan's §0 tables — the semantic authority.

    Parsed from the markdown table's leading ``| `NAME` |`` cell, including the
    ``A`` / ``B`` pair form that §0 uses for ``VERIFIED_DISABLED`` /
    ``VERIFIED_ABSENT``.
    """
    text = PLAN.read_text(encoding="utf-8")
    start = text.index("## 0. Status vocabulary")
    end = text.index("## 1. Campaign naming")
    declared: set[str] = set()
    for match in re.finditer(r"^\|\s*`([^`]+)`(?:\s*/\s*`([^`]+)`)?\s*\|", text[start:end], re.M):
        declared.add(match.group(1))
        if match.group(2):
            declared.add(match.group(2))
    return declared


def _open_items(row: dict[str, Any]) -> list[tuple[str, str]]:
    """Declared open items in a row, ignoring `status` and historical fields."""

    def leaves(value: Any) -> list[str]:
        if isinstance(value, dict):
            return [
                leaf
                for key, sub in value.items()
                if key not in HISTORICAL_FIELDS
                for leaf in leaves(sub)
            ]
        if isinstance(value, list):
            return [leaf for sub in value for leaf in leaves(sub)]
        return [value] if isinstance(value, str) else []

    return [
        (field, leaf)
        for field, value in row.items()
        if field != "status" and field not in HISTORICAL_FIELDS
        for leaf in leaves(value)
        if leaf.strip().upper() in OPEN_TOKENS
    ]


def _is_closed(row: dict[str, Any], terminal: frozenset[str]) -> bool:
    return row.get("status") in terminal and not _open_items(row)


def test_open_release_blockers_are_exactly_the_declared_set(
    rows: list[dict[str, Any]],
    terminal_statuses: frozenset[str],
) -> None:
    """The tag-time census result, pinned to a set someone must justify moving.

    Fails when a row enters the open set (a new blocker, or a discharge
    reverted) and equally when one leaves it (a row marked DISCHARGED without
    this pin being updated). Both directions print the row ids.
    """
    observed = {
        row["decision_id"]
        for row in rows
        if row.get("disposition") == "RELEASE_BLOCKER" and not _is_closed(row, terminal_statuses)
    }
    expected = set(EXPECTED_OPEN_RELEASE_BLOCKERS)

    newly_open = sorted(observed - expected)
    newly_closed = sorted(expected - observed)
    assert observed == expected, (
        "the open v0.1.0 RELEASE_BLOCKER set moved.\n"
        f"  now open, not declared here: {newly_open}\n"
        f"  declared here, no longer open: {newly_closed}\n"
        "Update EXPECTED_OPEN_RELEASE_BLOCKERS with the owning PR and the "
        "landed SHA. Do NOT relax the predicate to make this green."
    )


def test_a_terminal_release_blocker_names_its_evidence(
    rows: list[dict[str, Any]],
    terminal_statuses: frozenset[str],
) -> None:
    """A closed blocker must cite a SHA, a ruling or a named reason.

    This is the bookkeeping-discharge guard. A status flipped to DISCHARGED
    with no evidence field is indistinguishable, to the census, from a real
    discharge — and it is the cheapest possible way to make a release blocker
    disappear.
    """
    unevidenced = sorted(
        row["decision_id"]
        for row in rows
        if row.get("disposition") == "RELEASE_BLOCKER"
        and row.get("status") in terminal_statuses
        and not (EVIDENCE_FIELDS & set(row) or any(k.startswith("ruling_") for k in row))
    )
    assert unevidenced == [], (
        f"closed RELEASE_BLOCKER rows citing no SHA, ruling or reason: {unevidenced}"
    )


def test_fields_carrying_an_open_token_are_classified(
    rows: list[dict[str, Any]],
) -> None:
    """Every field that can declare openness is classified HISTORICAL or LIVE.

    Without this, the ruled historical-field exclusion widens silently: a new
    field name carrying `PENDING_IMPLEMENTATION` either joins the census or is
    ignored by it, and which one happens is decided by a name nobody reviewed.
    """

    def named_leaves(value: Any, field: str) -> list[str]:
        # Descends by the SAME rule `_open_items` uses — historical subtrees are
        # not entered. A scan that classified names the census never reads would
        # demand a verdict on fields whose openness is already excluded.
        if isinstance(value, dict):
            return [
                leaf
                for key, sub in value.items()
                if key not in HISTORICAL_FIELDS
                for leaf in named_leaves(sub, key)
            ]
        if isinstance(value, list):
            return [leaf for sub in value for leaf in named_leaves(sub, field)]
        return [field] if isinstance(value, str) and value.strip().upper() in OPEN_TOKENS else []

    carrying = {
        field
        for row in rows
        for key, value in row.items()
        if key != "status" and key not in HISTORICAL_FIELDS
        for field in named_leaves(value, key)
    }
    known = HISTORICAL_FIELDS | LIVE_OPEN_ITEM_FIELDS
    assert carrying <= known, (
        "field names carrying an open-status token that are classified as "
        f"neither HISTORICAL nor LIVE: {sorted(carrying - known)}. Decide which "
        "one each is and add it to the matching set."
    )
    # Non-vacuity: the scanner must actually be finding something. An empty
    # `carrying` would satisfy the subset assertion above for any file.
    assert carrying & LIVE_OPEN_ITEM_FIELDS, (
        "the scanner found no LIVE open-item field anywhere in the ledger — it "
        "is matching nothing and the census above is vacuous"
    )


def test_the_ledger_vocabulary_is_a_subset_of_the_plan(ledger: dict[str, Any]) -> None:
    """The YAML may not declare a status the plan's §0 does not define.

    §0 is the SEMANTIC authority — it says what each status means, in prose an
    operator reads. The YAML is its machine-readable mirror. This direction
    fails when the mirror grows a member the authority never defined, which is
    how a vocabulary drifts out of the document humans consult and into the one
    only tooling reads.
    """
    declared_in_yaml = set(ledger["status_vocabulary"]) | set(ledger["terminal_statuses"])
    declared_in_plan = _plan_declared_statuses()
    assert declared_in_plan, (
        "parsed no statuses from the plan's §0 — the parser is broken, not the plan"
    )
    undefined = sorted(declared_in_yaml - declared_in_plan)
    assert undefined == [], (
        "statuses declared in official_campaign_decisions.yaml that the plan's "
        f"§0 does not define: {undefined}. Define them in §0 (that is the "
        "semantic authority) rather than deleting them here."
    )


def test_every_status_in_use_is_declared(rows: list[dict[str, Any]]) -> None:
    """No row may carry a status the vocabulary does not declare.

    THIS IS THE DIRECTION A NEWLY INVENTED VALUE TAKES, and it is why the pair
    is asserted rather than just the subset above. Someone writes
    ``status: CLOSED`` on a row; the census reports that row OPEN, because
    `CLOSED` is not terminal; and the natural repair is to add `CLOSED` to
    whatever set the failing test names. Failing HERE points at the ledger and
    the plan instead — which is where a new status has to be defined.

    Measured on 2026-08-27, before the repair: SIX statuses were in use while
    declared in neither the plan's §0 nor the YAML, and all five members of the
    then-private terminal set were among the undeclared.
    """
    ledger = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    declared = set(ledger["status_vocabulary"]) | set(ledger["terminal_statuses"])
    in_use = {row["status"] for row in rows if row.get("status")}
    assert in_use, "no row carries a status — the scan is matching nothing"
    undeclared = sorted(in_use - declared)
    assert undeclared == [], (
        f"statuses carried by rows but declared nowhere: {undeclared}. Declare "
        "each in the plan's §0 and in `status_vocabulary` (and in "
        "`terminal_statuses` if it CLOSES a row) — do not add it to this test."
    )


def test_the_blocker_census_is_not_vacuous(
    rows: list[dict[str, Any]],
    terminal_statuses: frozenset[str],
) -> None:
    """The open-blocker census must be examining rows, not finding none.

    WHY THIS EXISTS, and why it appeared only on 2026-08-27. While the expected
    open set was non-empty, `observed == expected` could not pass on a broken
    scan: a scanner returning nothing failed against a set naming real ids. The
    set is now EMPTY — every release blocker is discharged — and that same
    assertion becomes trivially true whenever `observed` is empty FOR ANY
    REASON, including `_is_closed` wrongly returning True for everything or the
    disposition filter matching nothing after a key rename.

    So the census's INPUT is asserted separately from its OUTPUT: there must be
    RELEASE_BLOCKER rows to examine, and they must genuinely be closed by
    terminal statuses that the ledger declares. An all-clear is only meaningful
    if something was inspected.
    """
    blockers = [row for row in rows if row.get("disposition") == "RELEASE_BLOCKER"]
    assert len(blockers) >= 20, (
        f"only {len(blockers)} RELEASE_BLOCKER rows found. This census has "
        "always ranged over dozens; a collapse means the disposition key was "
        "renamed or the parse is wrong, and an 'all clear' from it is vacuous."
    )
    closed_by = {row["status"] for row in blockers if _is_closed(row, terminal_statuses)}
    assert closed_by <= terminal_statuses, (
        f"rows reported closed on statuses outside the declared terminal set: "
        f"{sorted(closed_by - terminal_statuses)}"
    )
    assert closed_by, "no RELEASE_BLOCKER row is closed — the closure test is inverted"
