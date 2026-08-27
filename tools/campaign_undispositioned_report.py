"""REPORT ONLY — rows a disposition-scoped census structurally cannot see.

NOT A GUARD. This module asserts nothing, is not a test, and is not wired into
CI. Running it prints a report; nothing fails. That is deliberate and dated —
see ENFORCEMENT_IS_OWED below.

THE DEFECT IT MEASURES
----------------------
The tag-time release-blocker census, and the executable guard at
``tests/unit/docs/test_campaign_decisions_census.py``, range over rows where
``disposition == "RELEASE_BLOCKER"``. A row carrying **no disposition field at
all** is not evaluated in either direction: it cannot be reported open and it
cannot be reported closed. It is not in the domain.

This is the shape *"the set a check ranges over was chosen by what was
convenient to enumerate."* It has already bitten once: ``R-OBS-1`` and
``D-BUD-16`` were repaired row-by-row on 2026-08-27 (master's own `reconciled`
prose on ``R-OBS-1`` names the mechanism verbatim — *"a disposition-scoped
census could not see it in EITHER direction"*), and ``D-BUD-17`` was then
missed, because that repair enumerated the rows someone noticed instead of
deriving the set.

So this module derives the domain from what a row IS:

    a row COULD be a blocker if it declares `blocking_v0_1_0: true`,
    or carries `blocked_on:`, or has an F- / R- / Q- prefixed id

...and reports every such row that carries no ``disposition``.

WHY IT DOES NOT ENFORCE
-----------------------
Measured 2026-08-27 against the ledger at that date: the predicate surfaces 23
rows, of which 7 are already CLOSED under the ruled closure predicate (adding a
disposition to those is pure label churn) and 16 are not. Of the 16, the large
majority need a genuine routing decision that belongs to the operator or the
Supervisor — not to whoever is running the census. Enforcing before the tag
would convert a documentation debt into a release blocker.

A disposition-scoped census that silently cannot see these rows is dishonest.
A non-enforcing report that says so, with its enforcement recorded as owed, is
not. That is the trade this file makes explicit rather than leaving implied.

ENFORCEMENT_IS_OWED
-------------------
Recorded 2026-08-27, awaiting Supervisor routing of the open rows. When they
carry dispositions, this predicate should become an assertion in
``tests/unit/docs/test_campaign_decisions_census.py`` and this module should be
deleted rather than left as a report nobody runs. Until then the debt is
visible here instead of invisible in the census's domain.

**Tracked as issue #371** ("census domains chosen by convenience"), which
carries this finding alongside its siblings elsewhere in the repository. The
point #371 preserves, and the reason a row-by-row fix is the wrong repair: the
earlier pass that gave ``R-OBS-1`` and ``D-BUD-16`` dispositions **enumerated
the rows someone noticed rather than deriving the set**, which is why
``D-BUD-17`` was missed — and patching that one row would have looked like a
success while leaving the defect intact.

The same shape landed independently in ``F-N1`` on the same day: a fix whose
docstring claimed "every sibling authority already anchors this way" was false
about three constants, and its repair replaced the prose claim with a census
that AST-DISCOVERS ``LEGACY_DEFAULT_*`` instead of listing it. Two lanes, two
subsystems, one failure mode.

Usage::

    .venv/bin/python tools/campaign_undispositioned_report.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "docs" / "campaign" / "official_campaign_decisions.yaml"


# The closed side of the predicate is READ from the ledger's declared
# `terminal_statuses` (plan §0.1), never restated here. An earlier draft of this
# module carried its own frozenset copy — which was the very defect it was
# written to report, one level down: a second private vocabulary that could
# drift from the authority without anything noticing.
def _terminal_statuses(document: dict[str, Any]) -> frozenset[str]:
    declared = document.get("terminal_statuses")
    if not declared:
        raise SystemExit(
            "the ledger declares no `terminal_statuses`; this report will not "
            "substitute a private copy of the closed-side vocabulary."
        )
    return frozenset(declared)


_COULD_BE_BLOCKER_ID = re.compile(r"^(F|R|Q)-")


def could_be_a_blocker(row: dict[str, Any]) -> list[str]:
    """Why this row is in the derived domain, or an empty list if it is not."""
    reasons: list[str] = []
    if row.get("blocking_v0_1_0") is True:
        reasons.append("blocking_v0_1_0:true")
    if "blocked_on" in row:
        reasons.append("blocked_on:")
    if _COULD_BE_BLOCKER_ID.match(row["decision_id"]):
        reasons.append("F/R/Q- id")
    return reasons


def main() -> int:
    document = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = document["decisions"]
    terminal = _terminal_statuses(document)

    in_domain = [row for row in rows if could_be_a_blocker(row)]
    surfaced = [row for row in in_domain if "disposition" not in row]
    closed = [row for row in surfaced if row.get("status") in terminal]
    still_open = [row for row in surfaced if row.get("status") not in terminal]

    print(f"ledger rows                                  : {len(rows)}")
    print(f"in the derived 'could be a blocker' domain   : {len(in_domain)}")
    print(f"of those, carrying NO disposition            : {len(surfaced)}")
    print(f"  already terminal (label-only churn)        : {len(closed)}")
    print(f"  NOT terminal (invisible to the census)     : {len(still_open)}")
    print()
    for label, group in (("TERMINAL", closed), ("NOT TERMINAL", still_open)):
        print(f"-- {label} --")
        for row in group:
            why = "+".join(could_be_a_blocker(row))
            print(f"   {row['decision_id']:<22} status={row.get('status')!s:<30} [{why}]")
        print()

    # The declared-vocabulary cross-check this module used to REPORT is now
    # ASSERTED, in both directions, by test_campaign_decisions_census.py — see
    # `test_the_ledger_vocabulary_is_a_subset_of_the_plan` and
    # `test_every_status_in_use_is_declared`. It is printed here only as a
    # visible zero: when it stops being zero the tests fail first.
    declared = set(document.get("status_vocabulary") or ()) | set(terminal)
    used: set[str] = {str(s) for row in rows if (s := row.get("status"))}
    undeclared = sorted(used - declared)
    print(f"-- statuses USED but declared nowhere ({len(undeclared)}) --")
    for status in undeclared:
        mark = " (TERMINAL under the ruled predicate)" if status in terminal else ""
        print(f"   {status}{mark}")
    if not undeclared:
        print("   none — asserted by tests/unit/docs/test_campaign_decisions_census.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
