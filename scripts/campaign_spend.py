#!/usr/bin/env python
"""Sum a campaign's token spend from the per-chain ledgers.

    python scripts/campaign_spend.py --root <WS_ROOT> --campaign-id <ID>
    -> "<total_tokens> <estimated_usd>"

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


def campaign_tokens(root: Path, campaign_id: str) -> int:
    """Total tokens across every chain belonging to this campaign.

    Only workspaces whose name starts with the campaign id are counted,
    so a shared root holding several campaigns cannot cross-contaminate.
    """
    total = 0
    for ledger in sorted(root.glob(f"{campaign_id}_*/token_usage.jsonl")):
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
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--cost-per-mtok", type=float, default=DEFAULT_COST_PER_MTOK_USD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print("0 0.00")
        return 0
    tokens = campaign_tokens(args.root, args.campaign_id)
    cost = estimated_cost_usd(tokens, args.cost_per_mtok)
    if args.json:
        print(
            json.dumps(
                {
                    "campaign_id": args.campaign_id,
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
