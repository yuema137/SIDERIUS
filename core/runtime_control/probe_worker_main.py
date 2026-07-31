"""Probe worker entry point — runs one bounded probe and reports (C12 fix).

Executed as ``python -m core.runtime_control.probe_worker_main <spec>``
in its OWN process group. The parent
(`probe_subprocess.run_worker`) owns the hard deadline and will
SIGTERM/SIGKILL this group; that is the only reliable way to bound an
operation blocked inside a CUDA call.

This process:

* announces its phase to a progress file, so a timeout can name what was
  running rather than guessing;
* runs the SAME `run_bounded_probe` production uses — the subprocess
  boundary adds a hard bound, it does not fork the measurement logic;
* writes a typed result atomically and exits.

It never writes into a run workspace or V19 state: the parent validates
the typed result and decides what to persist.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: probe_worker_main <spec.json>", file=sys.stderr)
        return 2

    from core.runtime_control.probe_subprocess import (
        ProbeWorkerResult,
        ProbeWorkerSpec,
        dump_result,
        worker_result_paths,
    )

    spec = ProbeWorkerSpec.model_validate_json(Path(args[0]).read_text(encoding="utf-8"))
    paths = worker_result_paths(spec.result_path)

    from core.runtime_control.probe_subprocess import write_progress

    write_progress(paths["progress"], "setup")
    try:
        from core.runtime_control.calibration_policy import sample_contention_window
        from core.runtime_control.probe import ProbeCaps, run_bounded_probe
        from core.runtime_control.probe_production import production_probe_executors

        executors = production_probe_executors(
            model_type=spec.model_type,
            model_config=spec.model_config_payload,
            train_config=spec.train_config,
            loss_config=spec.loss_config,
            data_dir=spec.data_dir,
            device=spec.device,
        )

        def _window(**kwargs):
            write_progress(paths["progress"], "setup")
            return sample_contention_window(**kwargs)

        # Phase announcements bracket the real work so a stall is
        # attributable. run_bounded_probe owns the between-operation caps;
        # the parent owns the hard one.
        write_progress(paths["progress"], "training")
        result = run_bounded_probe(
            model_identity=spec.model_type,
            executors=executors,
            caps=ProbeCaps(**spec.caps) if spec.caps else ProbeCaps(),
            device_vram_gb=spec.device_vram_gb,
            contention_window=_window,
        )
        write_progress(paths["progress"], "complete")
        dump_result(
            ProbeWorkerResult(
                status=result.status,
                phase="complete",
                model_identity=result.model_identity,
                realized=result.realized.model_dump(mode="json") if result.realized else None,
                setup_seconds=result.setup_seconds,
                train_ms_per_step=result.train_ms_per_step,
                train_ms_spread=result.train_ms_spread,
                inference_ms_per_batch=result.inference_ms_per_batch,
                inference_ms_spread=result.inference_ms_spread,
                peak_vram_gb=result.peak_vram_gb,
                concurrency_identity=result.concurrency_identity,
                contention_telemetry=result.contention_telemetry,
                error=result.error,
            ),
            paths["result"],
        )
        return 0
    except Exception as exc:  # the worker still reports, then exits
        from core.runtime_control.probe import is_out_of_memory

        dump_result(
            ProbeWorkerResult(
                status="oom" if is_out_of_memory(exc) else "load_failure",
                phase="setup",
                model_identity=spec.model_type,
                error=f"{type(exc).__name__}: {exc}",
            ),
            paths["result"],
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
