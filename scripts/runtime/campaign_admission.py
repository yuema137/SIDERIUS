#!/usr/bin/env python
"""Admit a campaign to its home directory, or refuse.

    python scripts/runtime/campaign_admission.py --campaign-id <id> \
        --ws-root <path> --campaign-home <path> \
        --runner <filename> --runner-pid <pid> \
        [--wave-state <path> --legacy-wave-state <path>]
    -> line 1: "<created|validated> <stamp path>"
       line 2: the adopted legacy state path, or "-"

Two lines rather than three fields, because a path may contain a space
and the launcher parses this with shell word splitting. Line 2 is always
present — an empty line would be indistinguishable from a missing one
after command substitution strips trailing newlines, so "none" is spelled
`-`.

The launcher calls this once, from ``main()``, before it may launch
anything or write any state. It owns the whole ordered sequence described
in ``core.campaign_identity`` — validate, inspect, validate the stamp,
create the directories, publish the stamp — because the **order** is the
guarantee and an order split across a shell script and a helper is not
checkable.

Exit codes follow ``campaign_spend.py``, the launcher's other Python
decision helper:

    0  admitted; the outcome and stamp path are on stdout
    2  refused; the reason is on stderr and NOTHING was launched

A refusal is deliberately not written into the campaign's wave state.
Appending a record about campaign A's failed launch into campaign B's
state file is precisely the cross-campaign write this PR exists to
remove, and the state directory may not even exist yet when the refusal
happens. The reason goes to stderr, which the launcher surfaces.
"""

from __future__ import annotations

import argparse
import sys

from core.campaign_identity import CampaignAdmissionError, admit_campaign


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--ws-root", required=True, help="campaign collection root")
    parser.add_argument(
        "--campaign-home",
        required=True,
        help="resolved campaign home; the launcher owns the default",
    )
    parser.add_argument("--runner", required=True, help="launcher filename, for provenance")
    parser.add_argument("--runner-pid", required=True, type=int)
    parser.add_argument(
        "--wave-state",
        default=None,
        help="this campaign's own state file; with --legacy-wave-state, enables the BC-2 adoption decision",
    )
    parser.add_argument(
        "--legacy-wave-state",
        default=None,
        help="the pre-PR-E state file for this campaign id",
    )
    args = parser.parse_args(argv)

    try:
        admission = admit_campaign(
            campaign_id=args.campaign_id,
            ws_root=args.ws_root,
            campaign_home=args.campaign_home,
            runner=args.runner,
            runner_pid=args.runner_pid,
            wave_state=args.wave_state,
            legacy_wave_state=args.legacy_wave_state,
        )
    except CampaignAdmissionError as exc:
        print(f"campaign_admission: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # An unstampable campaign cannot be guarded. Refusing is the only
        # option that does not launch work into an unbound directory.
        print(f"campaign_admission: {exc}", file=sys.stderr)
        return 2

    print(f"{admission.outcome} {admission.stamp_path}")
    print(admission.stamp.legacy_adopted_from or "-")
    return 0


if __name__ == "__main__":
    sys.exit(main())
