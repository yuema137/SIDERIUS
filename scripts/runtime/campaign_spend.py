#!/usr/bin/env python
"""Sum a campaign's token spend from the per-chain ledgers.

    python scripts/runtime/campaign_spend.py --root <WS_ROOT> \
        --run-name <exact> [--run-name <exact> ...]
    -> "<total_tokens> <estimated_usd>"

MEMBERSHIP IS EXPLICIT, NEVER INFERRED. The caller passes the exact run
names the campaign owns — the launcher takes them from its ROSTER, which
is the declared source of truth for what a campaign contains.

This replaced a `{campaign_id}_*` glob that decided membership from a name
prefix. The glob was wrong in a way that reached budget authority: a
campaign id which is another's prefix-plus-underscore absorbs it, so
`v20` counted every ledger under `v20_extra_*` as its own. Measured on a
synthetic root: `v20` reported 600 tokens where it owned 100. That total
feeds `SPENT_TOKENS` in the queue runner, which stops the campaign with
`token_cap_reached` — so one campaign could be halted by another's spend.

(`v20` versus `v20a` does NOT collide: the glob's underscore delimiter
separates them, and `v20a` was correctly independent. The defect is
specifically the underscore-prefix case, and the distinction is recorded
because the first hypothesis was the other one.)

`--campaign-id` is retained for provenance in the `--json` output. **It
selects nothing.**

Read from the ledgers rather than from a running total the queue keeps,
so a queue restart cannot lose spend that already happened.

Parsing this with shell text tools is a trap worth naming: a record is

    {"tokens": {"prompt": 3892, "completion": 585, "total": 4477},
     "chars":  {"system": 7888, "user": 9777, "total": 17665}}

so a naive scan for `"total"` picks up the CHARACTER count as well and
silently inflates the number the campaign's cost cap depends on. The
tokens object is addressed explicitly here.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

#: Conservative blended $/1M tokens, used because the ledger records
#: usage but not billed cost. Documented so the reported figure is
#: auditable rather than mysterious.
DEFAULT_COST_PER_MTOK_USD = 3.00


def record_tokens(record: dict) -> int:
    """Tokens for one ledger record; 0 when the record cannot say.

    Accepts both the nested `{"prompt","completion","total"}` shape and a
    bare integer, because an older ledger used the latter.
    """
    tokens = record.get("tokens")
    if isinstance(tokens, int):
        return max(0, tokens)
    if isinstance(tokens, dict):
        total = tokens.get("total")
        if isinstance(total, int):
            return max(0, total)
        parts = [tokens.get("prompt"), tokens.get("completion")]
        return sum(p for p in parts if isinstance(p, int) and p > 0)
    return 0


class RunNameError(ValueError):
    """A run name cannot address exactly one workspace under the root.

    An exception rather than a skipped entry: a spend total assembled from
    an unusable membership list would under-report, and under-reporting is
    the direction that lets a campaign overrun its cap.
    """


def validate_run_names(names: Sequence[str]) -> tuple[str, ...]:
    """The exact workspaces to read, or refuse.

    Each name must address exactly one directory directly under the root.
    Rejected: empty, `.`, `..`, anything containing a path separator, and
    duplicates. Duplicates are refused rather than de-duplicated because a
    caller repeating a name is a caller whose membership list is wrong,
    and silently charging it once hides that.
    """
    if not names:
        raise RunNameError(
            "at least one --run-name is required; campaign membership is "
            "explicit and is never inferred from the campaign id"
        )
    seen: list[str] = []
    for name in names:
        if not name or name in {".", ".."}:
            raise RunNameError(f"invalid run name {name!r}")
        if "/" in name or "\\" in name or "\x00" in name:
            raise RunNameError(
                f"run name {name!r} contains a path separator; it must name "
                "one workspace directly under the root"
            )
        if name in seen:
            raise RunNameError(f"duplicate run name {name!r} would be counted twice")
        seen.append(name)
    return tuple(seen)


def roster_tokens(root: Path, run_names: Sequence[str]) -> int:
    """Total tokens across exactly the named chain workspaces.

    Membership is the caller's explicit list. A named workspace with no
    ledger contributes 0 — the pre-existing treatment of a chain that has
    not written usage yet, and unchanged here.
    """
    total = 0
    for name in validate_run_names(run_names):
        ledger = root / name / "token_usage.jsonl"
        if not ledger.is_file():
            continue
        for line in ledger.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                total += record_tokens(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn final line is a gap, not a reason to fail
    return total


def estimated_cost_usd(tokens: int, per_mtok: float = DEFAULT_COST_PER_MTOK_USD) -> float:
    return tokens / 1_000_000 * per_mtok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--run-name",
        action="append",
        default=[],
        dest="run_names",
        metavar="EXACT_RUN_NAME",
        help=(
            "a workspace this campaign owns; repeatable. Membership is "
            "explicit — it is never inferred from --campaign-id."
        ),
    )
    parser.add_argument(
        "--campaign-id",
        default=None,
        help="provenance only, recorded in --json output; selects nothing",
    )
    parser.add_argument("--cost-per-mtok", type=float, default=DEFAULT_COST_PER_MTOK_USD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # An unusable membership list is refused, not treated as zero spend.
    # Zero would read as "nothing spent" and silently disarm the cap.
    try:
        run_names = validate_run_names(args.run_names)
    except RunNameError as exc:
        print(f"campaign_spend: {exc}", file=sys.stderr)
        return 2

    if not args.root.is_dir():
        print("0 0.00")
        return 0
    tokens = roster_tokens(args.root, run_names)
    cost = estimated_cost_usd(tokens, args.cost_per_mtok)
    if args.json:
        print(
            json.dumps(
                {
                    "campaign_id": args.campaign_id,
                    "run_names": list(run_names),
                    "total_tokens": tokens,
                    "estimated_cost_usd": round(cost, 2),
                    "cost_per_mtok_usd": args.cost_per_mtok,
                    "cost_is_estimated": True,
                },
                indent=1,
            )
        )
    else:
        print(f"{tokens} {cost:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
