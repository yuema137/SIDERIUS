#!/usr/bin/env python
"""V20 campaign orchestrator — two slots, refilled the moment one frees.

Process management only. The queue POLICY lives in
`core.campaign.slot_scheduler` and is unit-tested there without a clock,
a subprocess or a GPU; this module must never re-decide what launches
next. The scientific policy lives in `launch_v20_campaign.sh` and is not
duplicated here either — this passes only the job-specific band, chain
type, run name and workspace.

**This is not V19's scheduler.** V19 advanced by waves, starting a band
only after both chains of the previous one finished. V20 keeps one global
FIFO capped at two active chains, so chains from adjacent bands overlap.

**`max_active` bounds CHAINS, not GPU training phases.** Two chains may be
alive while only one holds the card: since M5 a valid measurement that
finds insufficient headroom refuses the phase, and that refusal is
correct. Never widen concurrency, and never weaken admission, to force
two candidates onto the GPU together.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

SIDERIUS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIDERIUS_ROOT))

from core.campaign.slot_scheduler import CampaignJob, SlotScheduler, v20_campaign_jobs  # noqa: E402

LAUNCHER = SIDERIUS_ROOT / "sdsc_submission_scripts" / "launch_v20_campaign.sh"

#: How long after `screen -dmS` returns a chain is still treated as
#: `running` even with no visible session. Covers the gap between the
#: launch call returning and screen registering the session; without it a
#: healthy chain reads as a crash on the very first poll.
LAUNCH_GRACE_SECONDS = 20.0


class ChainProcess:
    """One launched chain, and the only authority on whether it is done."""

    def __init__(self, job: CampaignJob, *, ws_root: Path, iterations: int):
        self.job = job
        self.workspace = ws_root / job.run_name
        self.logfile = ws_root / f"{job.run_name}.log"
        self.session = f"siderius-{job.run_name}"
        self.marker = ws_root / "queue_state" / "exit" / f"{job.run_name}.exit"
        self.iterations = iterations
        self.started_at: float | None = None

    def command(self) -> list[str]:
        return [
            "bash",
            str(LAUNCHER),
            "--workspace",
            str(self.workspace),
            "--run_name",
            self.job.run_name,
            "--num_iterations",
            str(self.iterations),
            "--data_scope",
            self.job.band,
            "--chain_type",
            self.job.chain_type,
        ]

    def session_alive(self) -> bool:
        out = subprocess.run(["screen", "-ls"], capture_output=True, text=True, check=False).stdout
        return f".{self.session}\t" in out or f".{self.session} " in out

    def classify(self) -> str:
        """`running` | `completed` | `unexpected_process_exit`.

        A slot is freed by a TERMINAL STATE, never by silence — but
        **failure is terminal too**. Three cases, and the third is the one
        that matters:

        * marker + live session -> `running`. The marker may be stale from
          an earlier campaign; the live session is authoritative.
        * marker + dead session -> `completed`. The chain recorded its own
          exit. `EXIT=0` or not, it finished on its own terms.
        * no marker + dead session -> `unexpected_process_exit`. A Python
          crash, an OOM kill, a screen that died before the wrapper could
          record anything. This is NOT a success and must never be
          reported as one — but it IS terminal. Refusing to release the
          slot would strand it: one crash would leave the campaign running
          at half concurrency, and two would deadlock all eight chains
          with nothing active.

        A freshly launched chain is `running` during `LAUNCH_GRACE_SECONDS`
        so that the gap between `screen -dmS` returning and the session
        appearing is not misread as a crash.
        """
        if self.session_alive():
            return "running"
        if self.started_at is not None and (time.time() - self.started_at) < LAUNCH_GRACE_SECONDS:
            return "running"
        return "completed" if self.marker.exists() else "unexpected_process_exit"

    def is_terminal(self) -> bool:
        return self.classify() != "running"

    def exit_note(self) -> str:
        try:
            return self.marker.read_text().strip()
        except OSError:
            return "no marker"

    def already_complete(self) -> bool:
        return self.marker.exists() and "EXIT=0" in self.exit_note()

    def record_unexpected_exit(self) -> None:
        """Persist scheduler-level evidence for a chain that vanished.

        Deliberately a SCHEDULER artifact, not a scientific one. It never
        claims a round, a score or a verdict — fabricating a scientific
        record for a process that died would put a result into the
        campaign that no measurement produced.

        `scientific_status: not_established` is the whole point: something
        ran, we do not know what it concluded, and nothing downstream may
        treat that as evidence.
        """
        import json

        self.marker.parent.mkdir(parents=True, exist_ok=True)
        (self.marker.parent / f"{self.job.run_name}.unexpected_exit.json").write_text(
            json.dumps(
                {
                    "run_name": self.job.run_name,
                    "band": self.job.band,
                    "chain_type": self.job.chain_type,
                    "scheduler_status": "unexpected_process_exit",
                    "scientific_status": "not_established",
                    "detail": (
                        "the chain's session is gone and no terminal marker was "
                        "written; the process did not record its own exit"
                    ),
                    "workspace": str(self.workspace),
                    "logfile": str(self.logfile),
                    "retried": False,
                    "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                },
                indent=2,
            )
            + "\n"
        )

    def launch(self) -> None:
        self.workspace.parent.mkdir(parents=True, exist_ok=True)
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.unlink(missing_ok=True)
        inner = (
            f"cd {shlex.quote(str(SIDERIUS_ROOT))}; "
            + " ".join(shlex.quote(c) for c in self.command())
            + " --foreground; "
            + f"printf 'EXIT=%s\\n' \"$?\" > {shlex.quote(str(self.marker))}"
        )
        subprocess.run(["screen", "-dmS", self.session, "bash", "-lc", inner], check=True)
        self.started_at = time.time()


def build_processes(jobs, ws_root: Path, iterations: int) -> dict[str, ChainProcess]:
    return {j.run_name: ChainProcess(j, ws_root=ws_root, iterations=iterations) for j in jobs}


def print_plan(jobs, ws_root: Path, iterations: int, max_active: int) -> None:
    print("#" * 60)
    print(f"  V20 CAMPAIGN QUEUE — slot-driven, max {max_active} concurrent chains")
    print(f"  ws_root : {ws_root}")
    print(f"  iters   : {iterations} per chain")
    print("#" * 60)
    for i, j in enumerate(jobs, 1):
        slot = "INITIAL ACTIVE" if i <= max_active else "pending"
        print(f"  {i}. {j.run_name:<18} band={j.band:<6} type={j.chain_type:<5} {slot}")
    print()
    print("  Any ONE chain reaching a terminal state frees exactly one slot,")
    print("  filled immediately from the FIFO. Adjacent bands MAY overlap —")
    print("  there is no band barrier. 'max 2' bounds CHAINS, not GPU phases:")
    print("  M5 admission decides when each chain may take the card.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="print the queue, no side effects")
    mode.add_argument("--dry-run", action="store_true", help="print the exact launch commands")
    mode.add_argument("--execute", action="store_true", help="START THE REAL CAMPAIGN")
    ap.add_argument("--ws_root", default="/home/klz/Data/SIDEREIS_DATA/v20")
    ap.add_argument("--num_iterations", type=int, default=10)
    ap.add_argument("--max_active", type=int, default=2)
    ap.add_argument("--poll_seconds", type=float, default=30.0)
    ap.add_argument("--campaign_id", default="v20")
    args = ap.parse_args()

    jobs = v20_campaign_jobs(args.campaign_id)
    ws_root = Path(args.ws_root)
    procs = build_processes(jobs, ws_root, args.num_iterations)

    print_plan(jobs, ws_root, args.num_iterations, args.max_active)

    if args.plan or not (args.dry_run or args.execute):
        print("\n  (--plan prints only; --dry-run shows commands; --execute starts it)")
        return 0

    if args.dry_run:
        print("\n--- exact launch commands ---")
        for j in jobs:
            print("  " + " ".join(shlex.quote(c) for c in procs[j.run_name].command()))
        return 0

    scheduler = SlotScheduler(jobs, max_active=args.max_active)
    stop_file = ws_root / "STOP"
    log_path = ws_root / "queue_state" / "v20_queue_runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
        print(line, flush=True)
        with log_path.open("a") as fh:
            fh.write(line + "\n")

    log(f"V20 CAMPAIGN START — {args.campaign_id}, {len(jobs)} chains, max {args.max_active}")
    while not scheduler.done:
        if stop_file.exists():
            log(f"STOP observed at {stop_file} — launching nothing further")
            break
        for job in scheduler.claim_slots():
            proc = procs[job.run_name]
            if proc.already_complete():
                log(f"SKIP {job.run_name} — already complete (resume)")
                scheduler.release(job.run_name)
                continue
            proc.launch()
            log(f"LAUNCHED {job.run_name} band={job.band} type={job.chain_type} log={proc.logfile}")
        if scheduler.done:
            break
        time.sleep(args.poll_seconds)
        for run_name in list(scheduler.running):
            proc = procs[run_name]
            state = proc.classify()
            if state == "running":
                continue
            if state == "unexpected_process_exit":
                # Failure is terminal. Record scheduler-level evidence,
                # release the slot, keep going — and do NOT relaunch: a
                # silent retry would re-enter whatever killed it and would
                # also double-count the chain's scientific history. The
                # workspace is preserved for a deliberate operator resume.
                proc.record_unexpected_exit()
                log(
                    f"UNEXPECTED EXIT {run_name} — no terminal marker and no live "
                    f"session. scheduler_status=unexpected_process_exit "
                    f"scientific_status=not_established. Slot released, NOT retried; "
                    f"workspace preserved at {proc.workspace}"
                )
            else:
                log(f"TERMINAL {run_name} ({proc.exit_note()}) — slot released")
            scheduler.release(run_name)
    log(f"queue finished — launched {len(scheduler.launch_order)} chain(s)")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
