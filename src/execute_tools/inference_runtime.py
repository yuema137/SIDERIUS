"""Runtime evidence for task-generic streaming inference.

Observe existing production work, including loader wait and writer consumption.
Never run a second inference pass or change batch ordering to obtain timing.
"""

from __future__ import annotations

import time

import torch

from core.runtime_control.session import RuntimeVerificationSession
from core.runtime_control.workload import ResolvedPhaseWorkload


class InferenceRuntimeEvidence:
    """Own the inference component's workload, verification and actual duration."""

    def __init__(
        self,
        session: RuntimeVerificationSession,
        *,
        samples: int,
        device: torch.device,
        started: float,
    ) -> None:
        self.session = session
        self.device = device
        self.started = started
        self.setup_seconds = time.perf_counter() - started
        self.finished_verification = False
        session.record_phase_workload(
            "inference",
            ResolvedPhaseWorkload(
                phase="inference",
                unit="inference_sample",
                unit_count=samples,
                detail={"derivation": "complete materialized evaluation scope"},
            ),
        )
        self.verifier = session.start_phase_verification("inference", unit="inference_sample")

    def start_batch(self) -> float:
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        return time.perf_counter()

    def finish_batch(self, started: float, samples: int) -> None:
        if self.finished_verification:
            return
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        elapsed_ms = max((time.perf_counter() - started) * 1000, 1e-6)
        self.verifier.feed(elapsed_ms / samples, elapsed_ms=elapsed_ms)
        if self.verifier.is_terminal:
            self._complete_verification()

    def _complete_verification(self) -> None:
        if self.finished_verification:
            return
        self.session.complete_phase_verification(
            "inference",
            self.verifier,
            source="real_inference_verification",
            extra_predicted_seconds=self.setup_seconds,
            extra_detail={
                "setup_seconds": self.setup_seconds,
                "batch_timing_includes": [
                    "loader",
                    "forward",
                    "cpu_transfer",
                    "writer_consumption",
                ],
                "unpredicted_work": "writer final flush after prediction stream exhaustion",
            },
        )
        self.finished_verification = True

    def finish(self) -> None:
        """Called only after successful, complete deliverable consumption."""
        self._complete_verification()
        self.session.record_phase_actual("inference", time.perf_counter() - self.started)
        from core.runtime_control.realized_memory import read_process_peak_mib

        allocated, reserved, device_index = read_process_peak_mib()
        self.session.record_phase_peak_memory(
            "inference",
            allocator_peak_mib=allocated,
            reserved_peak_mib=reserved,
            completeness="complete"
            if allocated is not None or reserved is not None
            else "unavailable",
            device_index=device_index,
        )
        self.session.finalize("inference_complete")
