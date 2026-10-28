"""Console launches under the shared host reservation ledger (B3-4c, backend).

The console loads the operator's ledger selection once and every submission goes
through ``CandidateConsole.submit``, which applies it by kind.
"""

import json
from uuid import uuid4

import pytest

from core.runtime_control.pair_admission import ResolvedGpuCeiling
from core.runtime_control.scheduling import GpuHardwareClass, GpuSlot, HostBudget
from tests.unit.tools.candidate_worker.conftest import prepared as worker_prepared
from tools.candidate_console.models import ConsoleHostLedger, RunResourcesSelection
from tools.candidate_console.service import CandidateConsole, with_run_resources
from tools.candidate_operations import (
    CandidateLoopResumeOperation,
    CandidateLoopResumeRequest,
    CandidateOperation,
    PrepareOperation,
)
from tools.candidate_operations.models import OperationResources

SERVICE = "tools.candidate_console.service."
__all__ = ["worker_prepared"]


def _budget() -> HostBudget:
    return HostBudget(
        gpus=(
            GpuSlot(
                uuid="GPU-aaaa",
                hardware_class=GpuHardwareClass(
                    device_name="NVIDIA H100",
                    total_memory_bytes=80 * 1024**3,
                    compute_capability=(9, 0),
                ),
                ceiling=ResolvedGpuCeiling(
                    operator_ceiling_gib=4.0,
                    operator_source="caller",
                    host_quota_gib=None,
                    measured_capacity_gib=80.0,
                ),
            ),
        ),
        host_memory_gib=64.0,
        cpu_slots=16,
        max_concurrent_units=4,
        source="file",
    )


@pytest.fixture
def ledgered(console_config, tmp_path):
    root = tmp_path / "host-ledger"
    root.mkdir(mode=0o700)
    budget = tmp_path / "host-budget.json"
    budget.write_text(_budget().model_dump_json(exclude={"source"}))
    return console_config.model_copy(
        update={"host_ledger": ConsoleHostLedger(ledger_root=str(root), budget_file=str(budget))}
    )


def test_the_ledger_selection_reaches_exactly_the_kinds_it_governs(ledgered, monkeypatch):
    """Candidate runs and loop resumes reserve; preparations and native chains never do.

    A console that dropped ``host`` would launch GUI runs unbudgeted beside
    ledger-placed CLI runs (oversubscription); one that passed it for a
    preparation would refuse it ``resources_required``.
    """
    console = CandidateConsole(ledgered)
    assert console.host is not None and console.host.budget.digest == _budget().digest
    seen = {}

    def submit(store, submission, *, launch_environment, expected_reusable_inputs=None, host):
        seen[submission.kind] = host
        return None

    monkeypatch.setattr(SERVICE + "submit_operation", submit)
    candidate = CandidateOperation.model_construct(kind="candidate", request_id=uuid4())
    resume = CandidateLoopResumeOperation(
        request_id=uuid4(),
        request=CandidateLoopResumeRequest(
            predecessor_operation_id=uuid4(), expected_receipt_digest="a" * 64
        ),
    )
    prepare = PrepareOperation.model_construct(kind="prepare", request_id=uuid4())
    chain = PrepareOperation.model_construct(kind="native_chain", request_id=uuid4())
    for submission in (candidate, resume, prepare, chain):
        console.submit(submission, launch_environment={})
    assert seen == {
        "candidate": console.host,
        "candidate_loop_resume": console.host,
        "prepare": None,
        "native_chain": None,
    }


def test_an_unusable_ledger_stops_the_console_instead_of_launching_unbudgeted(ledgered, tmp_path):
    """A typo in the budget file must not silently turn every launch serial."""
    broken = tmp_path / "broken-budget.json"
    broken.write_text(json.dumps({"gpus": []}))
    config = ledgered.model_copy(
        update={"host_ledger": ledgered.host_ledger.model_copy(update={"budget_file": str(broken)})}
    )
    with pytest.raises(ValueError, match="configured host ledger is unusable"):
        CandidateConsole(config)


def test_a_serial_launch_keeps_its_operation_bytes_and_resources_attach_after_review(
    worker_prepared,
):
    """Without operator inputs the reviewed operation is submitted byte for byte;
    with them, the reservation and parallel opt-in reach the operation the ledger reads."""
    from tests.helpers.candidate_fanout import fanout_request
    from tools.candidate_worker.parallel_models import CapabilityResources, ParallelDispatch

    operation = CandidateOperation(request_id=uuid4(), request=fanout_request(worker_prepared))
    serial = with_run_resources(operation, RunResourcesSelection())
    assert serial.model_dump_json() == operation.model_dump_json()
    resources = OperationResources(
        gpu_count=0, host_memory_gib=2.0, cpu_slots=1, time_budgeted=False
    )
    parallel = ParallelDispatch(
        capabilities={
            "implementation": CapabilityResources(gpu=False, host_memory_gib=1.0, cpu_slots=1)
        }
    )
    launched = with_run_resources(
        operation, RunResourcesSelection(resources=resources, parallel=parallel)
    )
    assert launched.resources == resources
    assert launched.request.parallel == parallel
    assert launched.request_id == operation.request_id
