"""Isolated measurement worker entry: ``python -m execute_tools.candidate_measurement_worker``.

Loads the candidate's serialized checkpoint and runs the declared builtin
measurements (#1296). It is the only process that executes candidate model
code for measurement; it writes typed ``MeasurementResult`` JSON and nothing else.
"""

from __future__ import annotations

import json
import os
import sys

from execute_tools.candidate_measurement import (
    MeasurementWorkerRequest,
    measure_components,
    worker_log_path,
)


def redirect_output_to_log(log_path: str) -> None:
    """Replace the parent's stdout/stderr pipes with a log file before candidate code runs.

    The parent captures both pipes in memory; once fds 1 and 2 point at the log,
    candidate code holds no pipe end and cannot flood the parent's memory.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: candidate_measurement_worker <request.json>", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        worker = MeasurementWorkerRequest.model_validate(json.load(handle))
    redirect_output_to_log(worker_log_path(worker.output_path))
    results = measure_components(worker.components, worker.request)
    with open(worker.output_path, "w", encoding="utf-8") as handle:
        json.dump([r.model_dump(mode="json") for r in results], handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
