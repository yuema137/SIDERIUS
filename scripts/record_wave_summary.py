#!/usr/bin/env python
"""Record one wave summary: canonical JSONL first, then the derived view.

    python scripts/record_wave_summary.py \
        --canonical <wave_state.jsonl> --derived-dir <pair_summaries/> \
        --campaign-id <id> --wave <n> --band <15-19> --band-tag <15_19> \
        --start <ts> --end <ts> --disposition <complete|failed|launch_failed> \
        --chain '<run_name>:<role>:<pid>:<exit>' [--chain ...]
    -> "<record_id> <derived path>"

Replaces an eleven-positional shell `printf` that could describe exactly
two chains called `arch` and `loss`. See `core.wave_records` for the
canonical/derived contract and for why the field inside `chains` is
`run_name` rather than `run`.

Exit codes are deliberately distinct, because the operator response
differs:

    0  recorded in both places
    2  refused or the canonical write failed — NOTHING was written
    3  the canonical record IS written; the derived view is not

Collapsing 3 into 2 would report a missing convenience file as missing
evidence, and would invite a retry that duplicates the canonical record.

An empty role is passed as an empty field (`run:...:pid:exit`) and
becomes `null`. The launcher does that rather than guessing `arch` when
the ROSTER cannot resolve a role — a gap is never a guess — and a record
with a null role simply gets no compatibility mirror.
"""

from __future__ import annotations

import argparse
import sys

from core.wave_records import (
    CanonicalWriteError,
    ChainRecord,
    DerivedWriteError,
    derived_filename,
    write_wave_summary,
)


class ChainSpecError(ValueError):
    """A `--chain` argument does not describe one chain."""


def parse_chain(spec: str) -> ChainRecord:
    """`run_name:role:pid:exit` -> a validated record.

    Split from the right on exactly three colons, because a run name may
    contain none but the remaining fields never do — and `rsplit` keeps a
    surprising run name from silently shifting every other field.

    Raises:
        ChainSpecError: the wrong number of fields, an empty run name, or
            a non-integer exit code.
    """
    parts = spec.rsplit(":", 3)
    if len(parts) != 4:
        raise ChainSpecError(f"chain spec {spec!r} must be '<run_name>:<role>:<pid>:<exit>'")
    run_name, role, pid, exit_code = parts
    if not run_name:
        raise ChainSpecError(f"chain spec {spec!r} has an empty run name")
    try:
        parsed_exit = int(exit_code)
    except ValueError as exc:
        raise ChainSpecError(
            f"chain spec {spec!r} has a non-integer exit code {exit_code!r}"
        ) from exc
    return ChainRecord(
        run_name=run_name,
        role=role or None,
        pid=pid or "unknown",
        exit=parsed_exit,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", required=True, help="the append-only wave state")
    parser.add_argument("--derived-dir", required=True, help="pair_summaries/")
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--wave", required=True, type=int)
    parser.add_argument("--band", required=True, help="e.g. 15-19")
    parser.add_argument("--band-tag", required=True, help="e.g. 15_19")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--disposition", required=True)
    parser.add_argument(
        "--chain",
        action="append",
        default=[],
        dest="chains",
        metavar="RUN:ROLE:PID:EXIT",
        help="one per chain in the wave; repeatable, order preserved",
    )
    args = parser.parse_args(argv)

    try:
        chains = [parse_chain(spec) for spec in args.chains]
        if not chains:
            raise ChainSpecError("a wave summary needs at least one --chain")
    except (ChainSpecError, ValueError) as exc:
        print(f"record_wave_summary: {exc}", file=sys.stderr)
        return 2

    try:
        record = write_wave_summary(
            canonical_path=args.canonical,
            derived_dir=args.derived_dir,
            campaign_id=args.campaign_id,
            wave=args.wave,
            band=args.band,
            band_tag=args.band_tag,
            chains=chains,
            start=args.start,
            end=args.end,
            disposition=args.disposition,
        )
    except CanonicalWriteError as exc:
        print(f"record_wave_summary: {exc}", file=sys.stderr)
        return 2
    except DerivedWriteError as exc:
        print(f"record_wave_summary: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # schema violation: nothing was written
        print(f"record_wave_summary: invalid wave record ({exc})", file=sys.stderr)
        return 2

    print(f"{record.record_id} {derived_filename(args.wave, args.band_tag)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
