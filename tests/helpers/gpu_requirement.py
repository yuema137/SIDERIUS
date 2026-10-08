"""Explicit ended-worker ownership for synthetic admission witnesses."""

from core.runtime_control.gpu_requirement_evidence import GpuRequirementOwnership, ProcessEvidence


def ended_worker_ownership(device_uuid: str, *, pid: int = 4242) -> GpuRequirementOwnership:
    return GpuRequirementOwnership(
        domain="new_worker_process_tree",
        device_uuid=device_uuid,
        process=ProcessEvidence(worker_pid=pid, worker_pgid=pid, exit_code=0),
        owned_pids=(pid,),
    )
