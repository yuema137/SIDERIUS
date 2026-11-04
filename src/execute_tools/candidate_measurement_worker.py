"""Isolated measurement worker entry: ``python -m execute_tools.candidate_measurement_worker``.

Loads the candidate's serialized checkpoint and runs the declared builtin
measurements (#1296). It is the only process that executes candidate model
code for measurement; it writes typed ``MeasurementResult`` JSON and nothing else.
"""

from __future__ import annotations

import json
import sys

from execute_tools.candidate_measurement import MeasurementWorkerRequest, measure_components


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: candidate_measurement_worker <request.json>", file=sys.stderr)
        return 2
    with open(args[0], encoding="utf-8") as handle:
        worker = MeasurementWorkerRequest.model_validate(json.load(handle))
    results = measure_components(worker.components, worker.request)
    with open(worker.output_path, "w", encoding="utf-8") as handle:
        json.dump([r.model_dump(mode="json") for r in results], handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
